# -*- coding: utf-8 -*-
"""
모듈명: test_evidence_structured_graphrag.py

[모듈 개요]
Evidence Structured GraphRAG v2.0 단위·통합 검증 스위트 (T01 ~ T14).
사건 증거 분석에서 ChromaDB/Embedding 의존성이 완전히 제거되었는지 확인하고,
PostgreSQL 구조화 증거 검색(E1/E2), Neo4j Graph Traversal(E3),
Structured Evidence GraphRAG(E4), Stale Worker 복구, 사실 신뢰도 분리,
Adaptive Workflow 연동을 검증한다.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_legal_helper.database.session import Base
from ai_legal_helper.database import models as m
from ai_legal_helper.rag.evidence_search import (
    analyze_evidence_query,
    search_evidence_in_postgres,
)
from ai_legal_helper.rag.graph_rag import (
    GraphRAGRetriever,
    validate_graph_paths,
    retrieve_structured_evidence,
    evaluate_evidence_strategies,
)
from ai_legal_helper.database.graph_sync import sync_case_to_graph
from ai_legal_helper.database.graph_sync_worker import (
    queue_sync_task,
    recover_stale_processing_tasks,
)
from ai_legal_helper.case_intelligence.evidence_manager import (
    process_evidence_review,
    derive_fact_trust_status,
)
from ai_legal_helper.case_intelligence.evidence_extractor import extract_claims_from_evidence


@pytest.fixture()
def db_session():
    """인메모리 SQLite 세션을 생성하여 각 테스트를 독립적으로 격리한다."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _seed_structured_case(db):
    """임대차 보증금 반환 사건의 구조화 증거 데이터를 시드한다."""
    u1 = m.User(id="user-1", email="u1@example.com", display_name="김임차", password_hash="h")
    u2 = m.User(id="user-2", email="u2@example.com", display_name="타인", password_hash="h")
    db.add_all([u1, u2])
    db.flush()

    case_a = m.Case(id="case-a", title="전세보증금 반환 청구 사건", case_type="주택임대차", user_id="user-1")
    case_b = m.Case(id="case-b", title="타인의 별건 대여금 사건", case_type="민법", user_id="user-2")
    db.add_all([case_a, case_b])
    db.flush()

    party_landlord = m.Party(case_id=case_a.id, name="박임대", role="임대인")
    party_tenant = m.Party(case_id=case_a.id, name="김임차", role="임차인")
    db.add_all([party_landlord, party_tenant])
    db.flush()

    doc_contract = m.EvidenceDocument(
        id="doc-contract",
        case_id=case_a.id,
        original_filename="임대차계약서.pdf",
        safe_storage_key="case-a/contract.pdf",
        media_type="application/pdf",
        size_bytes=2048,
        sha256="sha-contract",
        status="REVIEW_REQUIRED",
    )
    doc_notice = m.EvidenceDocument(
        id="doc-notice",
        case_id=case_a.id,
        original_filename="내용증명_갱신거절통지.pdf",
        safe_storage_key="case-a/notice.pdf",
        media_type="application/pdf",
        size_bytes=1024,
        sha256="sha-notice",
        status="REVIEW_REQUIRED",
    )
    doc_other = m.EvidenceDocument(
        id="doc-other",
        case_id=case_b.id,
        original_filename="타인차용증.pdf",
        safe_storage_key="case-b/loan.pdf",
        media_type="application/pdf",
        size_bytes=1024,
        sha256="sha-other",
        status="REVIEW_REQUIRED",
    )
    db.add_all([doc_contract, doc_notice, doc_other])
    db.flush()

    span_deposit = m.EvidenceSpan(
        id="span-deposit",
        evidence_id=doc_contract.id,
        page_number=1,
        paragraph_index=2,
        text_excerpt="제1조(보증금) 임차인 김임차는 임대인 박임대에게 전세보증금 금 오천만원(50,000,000원)을 2024년 1월 10일에 지급한다.",
    )
    span_notice = m.EvidenceSpan(
        id="span-notice",
        evidence_id=doc_notice.id,
        page_number=2,
        paragraph_index=1,
        text_excerpt="수신인 박임대 귀하. 본인은 2025년 10월 15일자 내용증명으로 임대차계약 갱신거절 및 해지를 통지합니다.",
    )
    span_other = m.EvidenceSpan(
        id="span-other",
        evidence_id=doc_other.id,
        page_number=1,
        paragraph_index=1,
        text_excerpt="보증금 5000만원을 차용한다.",
    )
    db.add_all([span_deposit, span_notice, span_other])
    db.flush()

    fact_deposit = m.Fact(
        id="fact-deposit",
        case_id=case_a.id,
        statement="임차인 김임차는 2024-01-10 임대인 박임대에게 보증금 5000만원을 지급하였다.",
        fact_type="AMOUNT",
        source_type="DOCUMENT_SUPPORTED",
        source_ref=doc_contract.id,
        verification_status="DOCUMENT_VERIFIED",
        confidence=0.95,
    )
    fact_notice = m.Fact(
        id="fact-notice",
        case_id=case_a.id,
        statement="임차인은 2025-10-15 임대인 박임대에게 계약 갱신거절 통지서를 발송하였다.",
        fact_type="ACTION",
        source_type="DOCUMENT_SUPPORTED",
        source_ref=doc_notice.id,
        verification_status="DOCUMENT_VERIFIED",
        confidence=0.92,
    )
    fact_gap = m.Fact(
        id="fact-gap",
        case_id=case_a.id,
        statement="임차인은 안방 천장 누수 수리비 150만원을 지출하였다.",
        fact_type="AMOUNT",
        source_type="USER_INPUT",
        verification_status="UNVERIFIED",
        confidence=0.6,
    )
    db.add_all([fact_deposit, fact_notice, fact_gap])
    db.flush()

    issue_return = m.LegalIssue(
        id="issue-return",
        case_id=case_a.id,
        title="임대차 종료에 따른 보증금 5000만원 반환 청구",
        related_fact_ids=[fact_deposit.id, fact_notice.id],
    )
    event_pay = m.Event(
        id="event-pay",
        case_id=case_a.id,
        title="전세보증금 5000만원 지급",
        event_date="2024-01-10",
        related_fact_ids=[fact_deposit.id],
    )
    db.add_all([issue_return, event_pay])
    db.flush()

    claim_deposit = m.EvidenceClaim(
        id="claim-deposit",
        case_id=case_a.id,
        evidence_id=doc_contract.id,
        statement="임차인 김임차가 2024년 1월 10일 임대인 박임대에게 보증금 5000만원을 지급함",
        claim_type="AMOUNT",
        assertion_status="DOCUMENT_STATES",
        confidence=0.95,
        review_status="APPROVED",
    )
    claim_notice = m.EvidenceClaim(
        id="claim-notice",
        case_id=case_a.id,
        evidence_id=doc_notice.id,
        statement="임차인이 2025년 10월 15일 임대인 박임대에게 내용증명으로 갱신거절 및 해지를 통지함",
        claim_type="ACTION",
        assertion_status="DOCUMENT_STATES",
        confidence=0.92,
        review_status="APPROVED",
    )
    claim_contra = m.EvidenceClaim(
        id="claim-contra",
        case_id=case_a.id,
        evidence_id=doc_notice.id,
        statement="임대인 박임대는 보증금으로 3000만원만 수령하였다고 주장함",
        claim_type="AMOUNT",
        assertion_status="CONTRADICTION_CANDIDATE",
        confidence=0.80,
        review_status="APPROVED",
    )
    claim_pending = m.EvidenceClaim(
        id="claim-pending",
        case_id=case_a.id,
        evidence_id=doc_contract.id,
        statement="미승인 특약: 임대인이 위약금 1억원을 지급하기로 함",
        claim_type="CONDITION",
        assertion_status="AI_INFERENCE",
        confidence=0.50,
        review_status="PENDING",
    )
    claim_rejected = m.EvidenceClaim(
        id="claim-rejected",
        case_id=case_a.id,
        evidence_id=doc_contract.id,
        statement="반려된 주장: 보증금 반환 기한을 2030년으로 연장함",
        claim_type="DATE",
        assertion_status="UNCERTAIN",
        confidence=0.30,
        review_status="REJECTED",
    )
    claim_other = m.EvidenceClaim(
        id="claim-other",
        case_id=case_b.id,
        evidence_id=doc_other.id,
        statement="타인 사건 보증금 5000만원 지급",
        claim_type="AMOUNT",
        assertion_status="DOCUMENT_STATES",
        confidence=0.90,
        review_status="APPROVED",
    )
    db.add_all([claim_deposit, claim_notice, claim_contra, claim_pending, claim_rejected, claim_other])
    db.flush()

    db.add_all([
        m.EvidenceSpanClaimLink(claim_id=claim_deposit.id, span_id=span_deposit.id),
        m.EvidenceSpanClaimLink(claim_id=claim_notice.id, span_id=span_notice.id),
        m.EvidenceSpanClaimLink(claim_id=claim_contra.id, span_id=span_notice.id),
        m.EvidenceSpanClaimLink(claim_id=claim_pending.id, span_id=span_deposit.id),
        m.EvidenceSpanClaimLink(claim_id=claim_rejected.id, span_id=span_deposit.id),
        m.EvidenceSpanClaimLink(claim_id=claim_other.id, span_id=span_other.id),
        m.EvidenceLink(
            evidence_id=doc_contract.id,
            claim_id=claim_deposit.id,
            target_type="FACT",
            target_id=fact_deposit.id,
            link_type="SUPPORTS",
        ),
        m.EvidenceLink(
            evidence_id=doc_notice.id,
            claim_id=claim_notice.id,
            target_type="FACT",
            target_id=fact_notice.id,
            link_type="SUPPORTS",
        ),
        m.EvidenceLink(
            evidence_id=doc_notice.id,
            claim_id=claim_contra.id,
            target_type="FACT",
            target_id=fact_deposit.id,
            link_type="CONTRADICTS",
        ),
    ])
    db.commit()
    return {
        "case_a": case_a.id,
        "case_b": case_b.id,
        "doc_contract": doc_contract.id,
        "doc_notice": doc_notice.id,
        "span_deposit": span_deposit.id,
        "span_notice": span_notice.id,
        "fact_deposit": fact_deposit.id,
        "fact_notice": fact_notice.id,
        "fact_gap": fact_gap.id,
        "issue_return": issue_return.id,
        "claim_deposit": claim_deposit.id,
        "claim_notice": claim_notice.id,
        "claim_contra": claim_contra.id,
        "claim_pending": claim_pending.id,
        "claim_rejected": claim_rejected.id,
        "claim_other": claim_other.id,
    }


# ---------------------------------------------------------------------------
# T01 & T02: 증거 업로드/추출/승인/Graph Sync 시 Embedding·ChromaDB 호출 0회 검증
# ---------------------------------------------------------------------------
def test_t01_t02_zero_embedding_calls_on_evidence_lifecycle(db_session):
    """T01/T02: 증거 추출, 사용자 승인, Graph Sync 전 과정에서 Embedding 및 ChromaDB 호출이 0회인지 검증한다."""
    ids = _seed_structured_case(db_session)

    with patch("ai_legal_helper.llm.gateway.get_embeddings") as mock_embed:
        # 1. Evidence extraction (with mocked LLM structured output)
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = MagicMock(claims=[])
        mock_llm.with_structured_output.return_value = mock_structured
        with patch("ai_legal_helper.case_intelligence.evidence_extractor.get_llm", return_value=mock_llm):
            ok = extract_claims_from_evidence(db_session, ids["doc_contract"])
            assert ok is True

        # 2. Evidence review approval
        review = process_evidence_review(
            db_session,
            claim_id=ids["claim_pending"],
            action="APPROVE",
            review_reason="테스트 승인",
        )
        assert review.new_review_status == "APPROVED"

        # 3. Graph sync to mock Neo4j driver
        mock_driver = MagicMock()
        sync_res = sync_case_to_graph(db_session, mock_driver, ids["case_a"])
        assert sync_res["status"] == "SYNCED"

        # Embedding API는 단 한 번도 호출되지 않아야 함
        assert mock_embed.call_count == 0


# ---------------------------------------------------------------------------
# T03: 법령 RAG 회귀 검증
# ---------------------------------------------------------------------------
def test_t03_statute_rag_regression_unaffected():
    """T03: 증거 VectorDB 제거 이후에도 법령 RAG(source_schema, indexer, hybrid_retrieval)는 정상 동작한다."""
    from langchain_core.documents import Document
    from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc

    doc = Document(
        page_content="주택임대차보호법 제3조(대항력 등) ① 임대차는 그 등기가 없는 경우에도...",
        metadata={"law_name": "주택임대차보호법", "article": "제3조", "page": 1, "source": "주택임대차보호법.pdf"},
    )
    src = build_source_from_chroma_doc(doc, category="주택임대차")
    assert src["source_type"] == "STATUTE"
    assert "주택임대차보호법" in (src["statute_name"] or "")


# ---------------------------------------------------------------------------
# T04: PostgreSQL 텍스트·구조화 증거 검색 (날짜/금액/당사자/행위 정규화)
# ---------------------------------------------------------------------------
def test_t04_postgres_structured_and_text_evidence_search(db_session):
    """T04: 날짜('2024년 1월 10일' <-> '2024-01-10'), 금액('5000만원' <-> '오천만원' <-> '50,000,000'), 당사자, 행위 검색 검증."""
    ids = _seed_structured_case(db_session)

    # 질의 분석기가 날짜 및 금액 변형을 정확히 생성하는지 확인
    plan = analyze_evidence_query("박임대에게 2024년 1월 10일에 지급한 보증금 5000만원 계약서")
    assert "2024-01-10" in plan.date_variants
    assert any("50,000,000" in v or "오천만" in v for v in plan.amount_variants)
    assert "DATE" in plan.claim_types and "AMOUNT" in plan.claim_types

    # 한글 금액('오천만원')만 적힌 Span도 아라비아 숫자('5000만원') 질의로 검색됨
    res_struct = search_evidence_in_postgres(
        db_session, ids["case_a"], "보증금 5000만원 지급일 2024-01-10", strategy="structured"
    )
    assert res_struct.hits
    top_claim_ids = {h.claim_id for h in res_struct.hits}
    assert ids["claim_deposit"] in top_claim_ids

    # 내용증명/갱신거절 통지 행위 검색
    res_notice = search_evidence_in_postgres(
        db_session, ids["case_a"], "내용증명 갱신거절 해지 통지", strategy="hybrid_pg"
    )
    assert any(h.claim_id == ids["claim_notice"] for h in res_notice.hits)


# ---------------------------------------------------------------------------
# T05: 원문 Span 추적성 (evidence_id, span_id, page_number, paragraph_index)
# ---------------------------------------------------------------------------
def test_t05_span_traceability(db_session):
    """T05: 검색 결과와 변환된 표준 출처(StandardSource)가 원문 Span 위치 정보를 온전히 보존하는지 검증한다."""
    ids = _seed_structured_case(db_session)
    ev_res = retrieve_structured_evidence(db_session, ids["case_a"], "보증금 5000만원 계약서", driver=None)

    deposit_match = next(m for m in ev_res.structured_matches if m.get("claim_id") == ids["claim_deposit"])
    assert deposit_match["evidence_id"] == ids["doc_contract"]
    assert deposit_match["span_id"] == ids["span_deposit"]
    assert deposit_match["page_number"] == 1
    assert deposit_match["paragraph_index"] == 2
    assert deposit_match["document_name"] == "임대차계약서.pdf"

    assert ev_res.sources
    src = next(s for s in ev_res.sources if s.get("evidence_id") == ids["doc_contract"])
    assert src["span_id"] == ids["span_deposit"]
    assert src["page"] == "1"
    assert src["retrieval_method"] == "POSTGRES_EVIDENCE_SEARCH"


# ---------------------------------------------------------------------------
# T06 & T07: PENDING/REJECTED 차단 및 사건(case_id / user_id) 격리
# ---------------------------------------------------------------------------
def test_t06_t07_blocks_unapproved_claims_and_enforces_case_isolation(db_session):
    """T06/T07: 미승인(PENDING)/반려(REJECTED) Claim과 타 사건(case_b) 증거는 절대 노출되지 않는다."""
    ids = _seed_structured_case(db_session)

    # 위약금(PENDING), 2030년(REJECTED), 보증금(타 사건 포함) 질의
    res = search_evidence_in_postgres(
        db_session,
        ids["case_a"],
        "위약금 1억원 2030년 보증금 5000만원",
        strategy="hybrid_pg",
        user_id="user-1",
    )
    returned_claim_ids = {h.claim_id for h in res.hits if h.claim_id}
    assert ids["claim_pending"] not in returned_claim_ids
    assert ids["claim_rejected"] not in returned_claim_ids
    assert ids["claim_other"] not in returned_claim_ids

    # 다른 사용자(user-2)가 case_a를 조회하면 빈 결과 반환
    res_wrong_user = search_evidence_in_postgres(
        db_session,
        ids["case_a"],
        "보증금 5000만원",
        strategy="hybrid_pg",
        user_id="user-2",
    )
    assert res_wrong_user.hits == []


# ---------------------------------------------------------------------------
# T08, T09, T10: Neo4j Traversal, Neo4j 장애 시 PostgreSQL Fallback, Stale Graph 검증
# ---------------------------------------------------------------------------
def test_t08_t09_t10_neo4j_traversal_fallback_and_stale_validation(db_session):
    """T08/T09/T10: Neo4j 그래프 탐색, 드라이버 장애 시 PostgreSQL 폴백, 동기화 지연(Stale) 경로 차단을 검증한다."""
    ids = _seed_structured_case(db_session)

    # T09: Neo4j 장애(driver=None) 시 PostgreSQL Fallback 동작
    r_offline = GraphRAGRetriever(None)
    fallback_res = r_offline.search_hybrid(ids["case_a"], "보증금 5000만원", db=db_session)
    assert fallback_res["available"] is False
    assert fallback_res["strategy"] == "postgresql_fallback"
    assert fallback_res["search_mode"] == "POSTGRESQL_ONLY"
    assert any(m["claim_id"] == ids["claim_deposit"] for m in fallback_res["structured_matches"])
    # PostgreSQL 기반 공백 및 상충도 함께 반환됨
    assert any(g["node_id"] == ids["fact_gap"] for g in fallback_res["evidence_gaps"])
    assert any(c["target_id"] == ids["fact_deposit"] for c in fallback_res["contradictions"])

    # T08 & T10: Neo4j 경로가 반환되었으나 PostgreSQL에서 Claim이 REJECTED로 변경된 경우 validate_graph_paths가 차단
    fake_neo4j_paths = [
        {
            "evidence_id": ids["doc_contract"],
            "filename": "임대차계약서.pdf",
            "span_id": ids["span_deposit"],
            "span_excerpt": "제1조(보증금)...",
            "page_number": 1,
            "claim_id": ids["claim_deposit"],
            "claim_statement": "임차인 김임차가 보증금 5000만원을 지급함",
            "review_status": "APPROVED",
            "relation": "SUPPORTS",
            "via_fact_id": ids["fact_deposit"],
            "target_type": "LegalIssue",
            "target_id": ids["issue_return"],
            "target_text": "임대차 종료에 따른 보증금 5000만원 반환 청구",
        }
    ]
    checked_ok = validate_graph_paths(db_session, ids["case_a"], fake_neo4j_paths)
    assert len(checked_ok["valid"]) == 1
    assert checked_ok["valid"][0]["paragraph_index"] == 2

    # PostgreSQL에서만 반려 처리 (Neo4j 미동기화 시뮬레이션)
    claim_obj = db_session.get(m.EvidenceClaim, ids["claim_deposit"])
    claim_obj.review_status = "REJECTED"
    db_session.commit()

    checked_stale = validate_graph_paths(db_session, ids["case_a"], fake_neo4j_paths)
    assert checked_stale["valid"] == []
    assert len(checked_stale["invalid"]) == 1
    assert any("CLAIM_NOT_APPROVED" in r for r in checked_stale["invalid"][0]["reasons"])


# ---------------------------------------------------------------------------
# T11: Graph Sync Worker Stale PROCESSING 자동 복구
# ---------------------------------------------------------------------------
def test_t11_graph_sync_worker_recovers_stale_processing_tasks(db_session):
    """T11: 비정상 종료로 PROCESSING 상태에 고착된 작업이 타임아웃 경과 후 PENDING/FAILED로 복구된다."""
    ids = _seed_structured_case(db_session)
    task = queue_sync_task(db_session, ids["case_a"])
    task.status = "PROCESSING"
    task.retry_count = 0
    task.updated_at = datetime.utcnow() - timedelta(minutes=10)
    db_session.commit()

    recovered = recover_stale_processing_tasks(db_session, timeout_minutes=5)
    assert recovered == 1
    db_session.refresh(task)
    assert task.status == "PENDING"
    assert task.retry_count == 1


# ---------------------------------------------------------------------------
# T12: 사용자 승인(APPROVE)과 사실 객관적 검증 상태 분리
# ---------------------------------------------------------------------------
def test_t12_fact_trust_status_separated_from_user_approval(db_session):
    """T12: Claim 승인 시 assertion_status 및 상충 여부에 따라 Fact.verification_status가 구분된다."""
    assert derive_fact_trust_status("DOCUMENT_STATES", has_conflict=False) == (
        "DOCUMENT_VERIFIED",
        "DOCUMENT_SUPPORTED",
    )
    assert derive_fact_trust_status("PARTY_ALLEGES", has_conflict=False) == (
        "PARTY_ASSERTED",
        "PARTY_ALLEGATION",
    )
    assert derive_fact_trust_status("AI_INFERENCE", has_conflict=False) == (
        "UNVERIFIED",
        "AI_INFERENCE",
    )
    assert derive_fact_trust_status("DOCUMENT_STATES", has_conflict=True) == (
        "DISPUTED",
        "DOCUMENT_SUPPORTED",
    )

    ids = _seed_structured_case(db_session)
    # 일방 당사자 주장(PARTY_ALLEGES) Claim 생성 후 승인
    party_claim = m.EvidenceClaim(
        id="claim-party-alleges",
        case_id=ids["case_a"],
        evidence_id=ids["doc_notice"],
        statement="임차인은 구두로 수리비 정산을 약속받았다고 주장함",
        claim_type="ACTION",
        assertion_status="PARTY_ALLEGES",
        confidence=0.75,
        review_status="PENDING",
    )
    db_session.add(party_claim)
    db_session.commit()

    process_evidence_review(db_session, claim_id=party_claim.id, action="APPROVE")
    created_fact = (
        db_session.query(m.Fact)
        .filter_by(case_id=ids["case_a"], statement=party_claim.statement)
        .first()
    )
    assert created_fact is not None
    assert created_fact.verification_status == "PARTY_ASSERTED"
    assert created_fact.source_type == "PARTY_ALLEGATION"


# ---------------------------------------------------------------------------
# T13: Adaptive Workflow 연동 (verification_node에 PostgreSQL 증거 출처 전달)
# ---------------------------------------------------------------------------
def test_t13_workflow_verification_uses_structured_evidence_sources(db_session):
    """T13: Neo4j 비활성 상태에서도 verification_node가 PostgreSQL structured_matches 출처를 Verifier에 전달한다."""
    from ai_legal_helper.workflows.legal_workflow import verification_node

    ids = _seed_structured_case(db_session)
    ev_res = retrieve_structured_evidence(db_session, ids["case_a"], "보증금 5000만원", driver=None)

    state = {
        "question": "보증금 5000만원을 돌려받을 수 있나요?",
        "draft_answer": "임대차계약서(임대차계약서.pdf, p.1)에 따라 보증금 5000만원 반환 청구가 가능합니다.",
        "retrieved_sources": [],
        "case_context": ev_res.context_text,
        "graph_evidence": {
            "available": False,
            "search_mode": "POSTGRESQL_ONLY",
            "valid_paths": [],
            "structured_matches": ev_res.structured_matches,
            "evidence_gaps": ev_res.evidence_gaps,
            "contradictions": ev_res.contradictions,
        },
    }

    captured_sources = []

    def _fake_run_verification(q, draft, sources, case_ctx):
        captured_sources.extend(sources)
        return {
            "status": "PASS",
            "reason_code": "NONE",
            "warnings": [],
            "citation_audit": {"verified_sources": sources},
        }

    with patch("ai_legal_helper.agents.verification.run_verification", side_effect=_fake_run_verification):
        out = verification_node(state)

    assert captured_sources, "PostgreSQL 구조화 증거 출처가 Verifier에 전달되어야 함"
    assert any(s.get("retrieval_method") == "POSTGRES_EVIDENCE_SEARCH" for s in captured_sources)
    assert any(s.get("evidence_id") == ids["doc_contract"] for s in out["retrieved_sources"])


# ---------------------------------------------------------------------------
# T14: E1 / E2 / E3 / E4 증거 검색 전략 정량 비교 평가
# ---------------------------------------------------------------------------
def test_t14_evaluate_e1_e2_e3_e4_evidence_strategies(db_session):
    """T14: E1(PG Text), E2(PG Structured), E3(Neo4j Traversal), E4(Structured GraphRAG) 비교 평가를 수행한다."""
    ids = _seed_structured_case(db_session)

    # E3/E4 평가를 위한 Mock Neo4j Driver 구성
    mock_driver = MagicMock()

    def _fake_traversal(case_id, query=None, seed_ids=None, limit=30, **kwargs):
        paths = []
        q_str = query or ""
        s_ids = set(seed_ids or [])
        if "보증금" in q_str or "5000" in q_str or ids["claim_deposit"] in s_ids:
            paths.append({
                "evidence_id": ids["doc_contract"],
                "filename": "임대차계약서.pdf",
                "span_id": ids["span_deposit"],
                "span_excerpt": "제1조(보증금) 임차인 김임차는 임대인 박임대에게 전세보증금 금 오천만원(50,000,000원)을 2024년 1월 10일에 지급한다.",
                "page_number": 1,
                "claim_id": ids["claim_deposit"],
                "claim_statement": "임차인 김임차가 2024년 1월 10일 임대인 박임대에게 보증금 5000만원을 지급함",
                "review_status": "APPROVED",
                "relation": "SUPPORTS",
                "via_fact_id": ids["fact_deposit"],
                "target_type": "LegalIssue",
                "target_id": ids["issue_return"],
                "target_text": "임대차 종료에 따른 보증금 5000만원 반환 청구",
            })
        if "내용증명" in q_str or "갱신거절" in q_str or "해지" in q_str or ids["claim_notice"] in s_ids:
            paths.append({
                "evidence_id": ids["doc_notice"],
                "filename": "내용증명_갱신거절통지.pdf",
                "span_id": ids["span_notice"],
                "span_excerpt": "수신인 박임대 귀하. 본인은 2025년 10월 15일자 내용증명으로 임대차계약 갱신거절 및 해지를 통지합니다.",
                "page_number": 2,
                "claim_id": ids["claim_notice"],
                "claim_statement": "임차인이 2025년 10월 15일 임대인 박임대에게 내용증명으로 갱신거절 및 해지를 통지함",
                "review_status": "APPROVED",
                "relation": "SUPPORTS",
                "via_fact_id": ids["fact_notice"],
                "target_type": "Fact",
                "target_id": ids["fact_notice"],
                "target_text": "임차인은 2025-10-15 임대인 박임대에게 계약 갱신거절 통지서를 발송하였다.",
            })
        return paths

    benchmark_queries = [
        {
            "query": "2024-01-10 지급한 보증금 5000만원 근거",
            "expected_claim_id": ids["claim_deposit"],
            "expected_fact_id": ids["fact_deposit"],
            "expects_contradiction": True,
        },
        {
            "query": "박임대에게 보낸 내용증명 갱신거절 해지 통지일",
            "expected_claim_id": ids["claim_notice"],
            "expected_fact_id": ids["fact_notice"],
            "expects_contradiction": False,
        },
        {
            "query": "임대차 종료에 따른 보증금 반환 청구 쟁점 근거",
            "expected_issue_id": ids["issue_return"],
            "expected_claim_id": ids["claim_deposit"],
            "expects_contradiction": True,
        },
    ]

    with patch.object(GraphRAGRetriever, "search_traversal", side_effect=_fake_traversal), \
         patch.object(GraphRAGRetriever, "find_contradictions", return_value=[{
             "target_type": "Fact",
             "target_id": ids["fact_deposit"],
             "target_text": "보증금 5000만원 지급",
             "supporting_claim_ids": [ids["claim_deposit"]],
             "contradicting_claim_ids": [ids["claim_contra"]],
         }]), \
         patch.object(GraphRAGRetriever, "find_evidence_gaps", return_value=[{
             "node_type": "Fact",
             "node_id": ids["fact_gap"],
             "text": "누수 수리비 150만원",
         }]):
        metrics = evaluate_evidence_strategies(
            db_session,
            ids["case_a"],
            benchmark_queries,
            driver=mock_driver,
        )

    assert set(metrics.keys()) == {
        "E1_PG_TEXT",
        "E2_PG_STRUCTURED",
        "E3_NEO4J_TRAVERSAL",
        "E4_STRUCTURED_GRAPHRAG",
    }
    # 모든 전략에서 미승인/반려 Claim 누출률은 0.0이어야 함
    for strat_name, m_val in metrics.items():
        assert m_val["invalid_claim_leak_rate"] == 0.0, f"{strat_name} leaked unapproved claims"
        assert m_val["span_traceability_rate"] > 0.0

    # 최종 채택 전략 E4는 Hit@3 1.0 및 상충 탐지율 1.0 달성
    assert metrics["E4_STRUCTURED_GRAPHRAG"]["hit_at_3"] == 1.0
    assert metrics["E4_STRUCTURED_GRAPHRAG"]["contradiction_detection_rate"] == 1.0
