# -*- coding: utf-8 -*-
"""
모듈명: test_graph_rag.py

[모듈 개요]
P2.4 Evidence GraphRAG 통합 테스트. 실제 PostgreSQL 테스트 DB 와 실제 Neo4j 를 사용한다.

[검증 항목]
1. PostgreSQL → Neo4j 동기화 및 멱등성(2회 동기화 시 동일 결과)
2. Traversal 경로에 evidence_id / span_id / claim_id 가 포함되는지(추적성)
3. 미승인(PENDING) Claim 이 근거로 반환되지 않는지
4. case_id 격리(다른 사건 데이터 비노출)
5. 반려 후 재동기화 시 stale 관계 제거
6. 코드 레벨 검증(validate_graph_paths)이 동기화 지연된 무효 근거를 탐지하는지
7. 증거 공백 / 상충 탐지
8. Graph API 엔드포인트 및 404
9. Neo4j 비활성 시 Fallback

[주의사항]
- Neo4j 에 연결할 수 없으면 Neo4j 의존 테스트는 skip 된다(Fallback 테스트는 항상 실행).
- Neo4j Community 는 단일 DB 이므로 고유 UUID case_id 로 격리하고 종료 시 서브그래프를 삭제한다.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_legal_helper.database.session import Base, get_db
from ai_legal_helper.database import models as m
from ai_legal_helper.database import graph_sync
from ai_legal_helper.database.neo4j import Neo4jConnectionManager, get_neo4j_driver
from ai_legal_helper.rag.graph_rag import GraphRAGRetriever, validate_graph_paths, extract_keywords
from ai_legal_helper.api.main import app

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://ai_user:ai_password@127.0.0.1:5432/ai_legal_helper_test",
)
engine = create_engine(TEST_DB_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def driver():
    d = get_neo4j_driver()
    if d is None:
        pytest.skip("Neo4j 를 사용할 수 없어 그래프 통합 테스트를 건너뜀")
    return d


@pytest.fixture(scope="module")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_db] = _override_get_db
    graph_sync.session_factory = TestingSessionLocal
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
    graph_sync.session_factory = None


def _seed_case(db, title: str):
    """주택임대차 보증금 반환 사건 시드 데이터를 생성한다.

    구조:
      Fact(보증금 지급) ← Claim(APPROVED) ← Span   [근거 있음]
      Fact(수리 요청)                              [증거 공백]
      LegalIssue(보증금 반환) ← RELATED_TO ← Fact(보증금 지급)
      Claim(PENDING, '보증금 미반환')               [근거로 쓰면 안 됨]
      Event 2개 (날짜순)
    """
    user = db.query(m.User).filter_by(id='test-user-id').first()
    if not user:
        user = m.User(id='test-user-id', email='test@example.com', display_name='Test User', password_hash='fakehash')
        db.add(user); db.commit()
    case = m.Case(title=title, case_type="주택임대차", user_id="test-user-id")
    db.add(case); db.flush()
    f1 = m.Fact(case_id=case.id, statement="임차인은 임대인에게 보증금 5000만원을 지급하였다",
                fact_type="금액", source_type="DOCUMENT_SUPPORTED")
    f2 = m.Fact(case_id=case.id, statement="임차인은 누수 수리를 요청하였다", fact_type="행위")
    db.add_all([f1, f2]); db.flush()
    issue = m.LegalIssue(case_id=case.id, title="보증금 반환 청구", related_fact_ids=[f1.id])
    e1 = m.Event(case_id=case.id, title="임대차 계약 체결", event_date="2024-01-10", related_fact_ids=[f1.id])
    e2 = m.Event(case_id=case.id, title="계약 만료", event_date="2026-01-09")
    doc = m.EvidenceDocument(case_id=case.id, original_filename="계약서.txt", safe_storage_key="k",
                             media_type="text/plain", size_bytes=10, sha256="x", status="REVIEW_REQUIRED")
    db.add_all([issue, e1, e2, doc]); db.flush()
    span = m.EvidenceSpan(evidence_id=doc.id, text_excerpt="보증금 금 오천만원을 지급한다", page_number=1)
    c_ok = m.EvidenceClaim(case_id=case.id, evidence_id=doc.id, statement="보증금 5000만원 지급",
                           review_status="APPROVED")
    c_pending = m.EvidenceClaim(case_id=case.id, evidence_id=doc.id, statement="임대인이 보증금을 미반환",
                                review_status="PENDING")
    db.add_all([span, c_ok, c_pending]); db.flush()
    db.add(m.EvidenceSpanClaimLink(claim_id=c_ok.id, span_id=span.id))
    db.add(m.EvidenceLink(evidence_id=doc.id, claim_id=c_ok.id, target_type="FACT",
                          target_id=f1.id, link_type="SUPPORTS"))
    db.commit()
    return {"case": case.id, "f1": f1.id, "f2": f2.id, "issue": issue.id, "doc": doc.id,
            "span": span.id, "c_ok": c_ok.id, "c_pending": c_pending.id}


@pytest.fixture(scope="module")
def seeded(db, driver):
    a = _seed_case(db, "GraphRAG 테스트 사건 A")
    b = _seed_case(db, "GraphRAG 테스트 사건 B")
    yield a, b
    for ids in (a, b):
        graph_sync.delete_case_graph(driver, ids["case"])
        db.query(m.Case).filter(m.Case.id == ids["case"]).delete()
    db.commit()


def _count(driver, case_id):
    with driver.session() as s:
        n = s.run("MATCH (n {case_id:$c}) RETURN count(n) AS c", c=case_id).single()["c"]
        r = s.run("MATCH (a {case_id:$c})-[r]->(b {case_id:$c}) RETURN count(r) AS c", c=case_id).single()["c"]
    return n, r


# ---------------------------------------------------------------- 단위 수준
def test_extract_keywords_strips_josa_and_stopwords():
    kws = extract_keywords("임대인이 보증금을 돌려주지 않는 경우 어떻게 해야 하나요?")
    assert "보증금" in kws and "임대인" in kws
    assert "경우" not in kws and "어떻게" not in kws


# ---------------------------------------------------------------- 동기화
def test_sync_is_idempotent(db, driver, seeded):
    a, _ = seeded
    r1 = graph_sync.sync_case_to_graph(db, driver, a["case"])
    c1 = _count(driver, a["case"])
    r2 = graph_sync.sync_case_to_graph(db, driver, a["case"])
    c2 = _count(driver, a["case"])
    assert r1["status"] == r2["status"] == "SYNCED"
    assert c1 == c2
    # Case + 2 Fact + 1 Issue + 2 Event + 1 Doc + 1 Span + 2 Claim = 10
    assert c1[0] == 10


def test_traversal_traceable_and_excludes_pending(db, driver, seeded):
    a, _ = seeded
    graph_sync.sync_case_to_graph(db, driver, a["case"])
    paths = GraphRAGRetriever(driver).search_traversal(a["case"], query="보증금 반환")
    assert paths, "보증금 관련 경로가 반환되어야 함"
    for p in paths:
        assert p["evidence_id"] == a["doc"]
        assert p["claim_id"] == a["c_ok"]
        assert p["span_id"] == a["span"]
        assert p["claim_id"] != a["c_pending"]
    # 쟁점 경유 경로(Fact→LegalIssue)도 존재해야 함
    assert any(p["target_type"] == "LegalIssue" and p["via_fact_id"] == a["f1"] for p in paths)


def test_case_isolation(db, driver, seeded):
    a, b = seeded
    graph_sync.sync_case_to_graph(db, driver, a["case"])
    graph_sync.sync_case_to_graph(db, driver, b["case"])
    r = GraphRAGRetriever(driver)
    ids_b = {p["claim_id"] for p in r.search_traversal(b["case"], query="보증금")}
    assert a["c_ok"] not in ids_b
    nodes_b = {n["id"] for n in r.get_case_graph(b["case"])["nodes"]}
    assert not (nodes_b & set(a.values()))


def test_gaps_and_contradictions(db, driver, seeded):
    a, _ = seeded
    graph_sync.sync_case_to_graph(db, driver, a["case"])
    r = GraphRAGRetriever(driver)
    gap_ids = {g["node_id"] for g in r.find_evidence_gaps(a["case"])}
    assert a["f2"] in gap_ids          # 근거 없는 사실
    assert a["f1"] not in gap_ids      # 승인 근거 있는 사실
    assert a["issue"] not in gap_ids   # 근거 있는 사실을 경유하는 쟁점

    # 반박 증거 추가 → 상충 탐지
    c_contra = m.EvidenceClaim(case_id=a["case"], evidence_id=a["doc"],
                               statement="보증금은 3000만원이었다", review_status="APPROVED")
    db.add(c_contra); db.flush()
    db.add(m.EvidenceLink(evidence_id=a["doc"], claim_id=c_contra.id, target_type="FACT",
                          target_id=a["f1"], link_type="CONTRADICTS"))
    db.commit()
    graph_sync.sync_case_to_graph(db, driver, a["case"])
    contra = r.find_contradictions(a["case"])
    assert any(c["target_id"] == a["f1"] and a["c_ok"] in c["supporting_claim_ids"] for c in contra)


def test_validation_detects_stale_graph_then_resync_removes(db, driver, seeded):
    _, b = seeded
    graph_sync.sync_case_to_graph(db, driver, b["case"])
    r = GraphRAGRetriever(driver)
    paths = r.search_traversal(b["case"], query="보증금")
    assert paths and validate_graph_paths(db, b["case"], paths)["invalid"] == []

    # PostgreSQL 에서만 반려 (그래프는 아직 동기화 전 = stale)
    claim = db.get(m.EvidenceClaim, b["c_ok"])
    claim.review_status = "REJECTED"
    db.commit()
    checked = validate_graph_paths(db, b["case"], paths)
    assert checked["valid"] == []
    assert any(any(x.startswith("CLAIM_NOT_APPROVED") for x in i["reasons"]) for i in checked["invalid"])

    # 재동기화 후에는 그래프에서도 근거 관계가 사라져야 함
    graph_sync.sync_case_to_graph(db, driver, b["case"])
    assert r.search_traversal(b["case"], query="보증금") == []


# ---------------------------------------------------------------- API
def test_graph_api(client, driver, seeded):
    a, _ = seeded
    assert client.get("/api/v1/graph/health").json()["available"] is True
    res = client.post(f"/api/v1/cases/{a['case']}/graph/sync")
    assert res.status_code == 200 and res.json()["status"] == "SYNCED"

    g = client.get(f"/api/v1/cases/{a['case']}/graph").json()
    assert g["available"] and any(n["type"] == "EvidenceClaim" for n in g["nodes"])
    # 기본 조회에서는 미승인 Claim 제외
    assert a["c_pending"] not in {n["id"] for n in g["nodes"]}
    g2 = client.get(f"/api/v1/cases/{a['case']}/graph?include_pending=true").json()
    assert a["c_pending"] in {n["id"] for n in g2["nodes"]}

    s = client.get(f"/api/v1/cases/{a['case']}/graph/search",
                   params={"q": "보증금", "strategy": "hybrid"}).json()
    assert s["available"] and s["traversal_paths"] and s["invalid"] == []

    an = client.get(f"/api/v1/cases/{a['case']}/graph/analysis").json()
    assert any(g["node_id"] == a["f2"] for g in an["evidence_gaps"])

    assert client.get(f"/api/v1/cases/{uuid.uuid4()}/graph").status_code == 404


# ---------------------------------------------------------------- Fallback
def test_fallback_when_neo4j_disabled(monkeypatch):
    """NEO4J_ENABLED=false 또는 장애 시 None 을 반환하고 검색기는 빈 결과를 낸다."""
    monkeypatch.setenv("NEO4J_ENABLED", "false")
    assert Neo4jConnectionManager().get_driver() is None
    r = GraphRAGRetriever(None)
    res = r.search_hybrid("any", "보증금")
    assert res["available"] is False and res["traversal_paths"] == []


def test_fallback_wrong_password(monkeypatch):
    """잘못된 인증정보에도 예외를 던지지 않고 None 을 반환한다."""
    monkeypatch.setenv("NEO4J_PASSWORD", "definitely-wrong-password")
    assert Neo4jConnectionManager().get_driver() is None


def test_api_fallback_returns_unavailable(client, db, monkeypatch):
    import ai_legal_helper.api.routes.graph as graph_routes
    monkeypatch.setattr(graph_routes, "get_neo4j_driver", lambda: None)
    case = m.Case(title="fallback", user_id="test-user-id")
    db.add(case); db.commit()
    try:
        g = client.get(f"/api/v1/cases/{case.id}/graph").json()
        assert g["available"] is False and g["nodes"] == []
        assert client.post(f"/api/v1/cases/{case.id}/graph/sync").status_code == 503
        # 기존 사건 조회는 그래프 장애와 무관하게 정상 동작
        assert client.get(f"/api/v1/cases/{case.id}").status_code == 200
    finally:
        db.query(m.Case).filter(m.Case.id == case.id).delete(); db.commit()

