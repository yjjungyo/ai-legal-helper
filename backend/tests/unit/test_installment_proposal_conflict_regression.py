# -*- coding: utf-8 -*-
"""분할 반환 제안과 즉시 반환 곤란 진술의 상충 오탐 및 그래프 표시 회귀 테스트.

기존 사실의 부정절을 실제 지급 부정으로 오인하지 않고 제안 화행과 능력 진술을 구분한다.
PostgreSQL/Neo4j에 과거 CONTRADICTS 관계가 남아 있어도 사용자 화면에 출력하지 않는다.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_legal_helper.api.routes import graph as graph_route
from ai_legal_helper.case_intelligence.conflict_detector import (
    build_structured_slots,
    evaluate_claim_against_fact,
    reconcile_case_conflicts,
)
from ai_legal_helper.case_intelligence.fact_semantics import (
    extract_semantic_proposition,
    check_proposition_comparability,
)
from ai_legal_helper.rag.graph_rag import (
    validate_graph_paths,
    filter_verified_graph_contradictions,
)
from ai_legal_helper.database.models import (
    Base, User, Case, EvidenceDocument, EvidenceClaim, EvidenceLink,
    Fact, FactAdjudication,
)

FACT_TEXT = "박정훈은 보증금을 일시에 전액 반환하지 않고 분할 반환하는 방안을 제안하였다."
CLAIM_TEXT = "박정훈은 보증금 3억 원을 즉시 반환하기 어렵다는 취지로 말했다."


@pytest.fixture
def db():
    """외부 PostgreSQL/Neo4j와 분리된 인메모리 SQLite 세션을 준비한다."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def seed_conflict(db, fact_statement=FACT_TEXT, claim_statement=CLAIM_TEXT,
                  link_type="CONTRADICTS", fact_status="DISPUTED"):
    """UI에서 보이는 과거 상충 관계를 실제 ORM 엔티티로 재현한다."""
    user = User(id="u-proposal", email="proposal@example.com", password_hash="hash")
    case = Case(id="case-proposal", user_id=user.id, title="분할 반환 상충 오탐")
    doc1 = EvidenceDocument(
        id="doc-proposal", case_id=case.id, original_filename="분할반환_제안_문자.txt",
        safe_storage_key="test1", media_type="text/plain", size_bytes=100,
        sha256="hash1", status="APPROVED",
    )
    doc2 = EvidenceDocument(
        id="doc-difficulty", case_id=case.id, original_filename="반환곤란_통화요지.txt",
        safe_storage_key="test2", media_type="text/plain", size_bytes=100,
        sha256="hash2", status="APPROVED",
    )
    fact = Fact(
        id="fact-proposal", case_id=case.id, statement=fact_statement,
        fact_type="ACTION", source_type="DOCUMENT_SUPPORTED",
        source_ref=doc1.id, verification_status=fact_status,
    )
    claim = EvidenceClaim(
        id="claim-difficulty", case_id=case.id, evidence_id=doc2.id,
        statement=claim_statement, claim_type="ACTION",
        assertion_status="CONTRADICTION_CANDIDATE",
        review_status="APPROVED", confidence=0.95,
    )
    link = EvidenceLink(
        id="link-proposal", evidence_id=doc2.id, claim_id=claim.id,
        target_type="FACT", target_id=fact.id, link_type=link_type,
    )
    db.add_all([user, case, doc1, doc2, fact, claim, link])
    db.commit()
    return case, fact, claim, link


def test_installment_proposal_and_difficulty_are_not_contradictory():
    """상충 #6 실제 문장: 분할 반환 제안은 일시 반환 곤란 진술과 양립한다."""
    proposal = extract_semantic_proposition(FACT_TEXT)
    difficulty = extract_semantic_proposition(CLAIM_TEXT)
    assert proposal.speech_act == "PROPOSAL"
    assert difficulty.speech_act != "PROPOSAL"
    comp = check_proposition_comparability(proposal, difficulty)
    assert comp.is_comparable is False
    assert comp.status == "DIFFERENT_CONTEXT"
    assert comp.reason_code == "PAYMENT_PROPOSAL_VS_CAPACITY_STATEMENT"

    for claim_text, fact_text in ((CLAIM_TEXT, FACT_TEXT), (FACT_TEXT, CLAIM_TEXT)):
        slots = build_structured_slots(claim_text, claim_type="ACTION")
        fact = Fact(id="fact-test", statement=fact_text, fact_type="ACTION")
        decision = evaluate_claim_against_fact(
            claim_slots=slots, fact=fact, enable_llm_verification=False,
        )
        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "PAYMENT_PROPOSAL_VS_CAPACITY_STATEMENT"


def test_real_amount_contradiction_is_still_detected():
    """동일 계약의 보증금 액수가 실질적으로 다르면 기존 상충 탐지를 유지한다."""
    slots = build_structured_slots("보증금은 2억 원이다.", claim_type="AMOUNT")
    fact = Fact(id="real-conflict", statement="보증금은 3억 원이다.", fact_type="AMOUNT")
    decision = evaluate_claim_against_fact(
        claim_slots=slots, fact=fact, enable_llm_verification=False,
    )
    assert decision.status == "CONTRADICTION"


@pytest.mark.parametrize("neo4j_available", [True, False])
def test_stale_link_does_not_appear_in_graph_ui(db, monkeypatch, neo4j_available):
    """Neo4j 연결 유무와 관계없이 과거 잘못된 링크는 화면상 상충에서 제외한다."""
    case, fact, claim, _ = seed_conflict(db)

    class FakeGraph:
        def __init__(self, driver):
            self.driver = driver

        def get_case_graph(self, case_id, include_pending=False):
            return {
                "case_id": case_id,
                "nodes": [],
                "edges": [
                    {"source": claim.id, "target": fact.id, "type": "CONTRADICTS"},
                    {"source": claim.id, "target": fact.id, "type": "SUPPORTS"},
                ],
            }

        def find_evidence_gaps(self, case_id):
            return []

        def _find_pg_gaps_and_contradictions(self, db, case_id):
            return [], [{"target_id": fact.id, "contradicting_id": claim.id}]

    monkeypatch.setattr(graph_route, "get_neo4j_driver",
                        (lambda: object()) if neo4j_available else (lambda: None))
    monkeypatch.setattr(graph_route, "GraphRAGRetriever", FakeGraph)
    # 원본 상충 조회 API의 Neo4j 보강 호출은 테스트에서 비활성화한다.
    monkeypatch.setattr("ai_legal_helper.database.neo4j.get_neo4j_driver", lambda: None)

    analysis = graph_route.analyze_graph(case=case, db=db)
    assert analysis["contradictions"] == []
    if neo4j_available:
        graph = graph_route.get_graph(include_pending=False, case=case, db=db)
        assert not any(e["type"] == "CONTRADICTS" for e in graph["edges"])
        assert any(e["type"] == "SUPPORTS" for e in graph["edges"])


def test_reconciliation_restores_false_dispute_and_adjudication(db):
    """상충 링크 복구 시 Fact와 FactAdjudication의 분쟁 상태를 함께 되돌린다."""
    case, fact, claim, link = seed_conflict(db)
    adjudication = FactAdjudication(
        case_id=case.id, fact_id=fact.id, claim_id=claim.id,
        adjudication_status="GENUINELY_DISPUTED", primary_relation="CONTRADICTS",
        adjudication_basis="이전 버전 오판정", contradicting_evidence_ids=[claim.evidence_id],
    )
    db.add(adjudication)
    db.commit()

    dry_run = reconcile_case_conflicts(
        db, case_id=case.id, dry_run=True, sync_neo4j=False,
    )
    assert dry_run["removed_false_contradict_links"] == 1
    assert db.query(EvidenceLink).filter_by(id=link.id).first() is not None

    applied = reconcile_case_conflicts(
        db, case_id=case.id, dry_run=False, sync_neo4j=False,
    )
    assert applied["removed_false_contradict_links"] == 1
    db.expire_all()
    assert db.query(EvidenceLink).filter_by(id=link.id).first() is None
    assert db.get(Fact, fact.id).verification_status != "DISPUTED"
    assert db.get(FactAdjudication, adjudication.id).adjudication_status != "GENUINELY_DISPUTED"

    again = reconcile_case_conflicts(
        db, case_id=case.id, dry_run=False, sync_neo4j=False,
    )
    assert again["removed_false_contradict_links"] == 0


@pytest.mark.parametrize("original_link_type", ["POTENTIAL_CONFLICT", "CONTRADICTION"])
def test_reconciliation_keeps_canonical_contradicts_link_type(db, original_link_type):
    """신규·레거시 관계는 실제 상충 판정 시 모두 CONTRADICTS로 정규화한다."""
    case, fact, claim, link = seed_conflict(
        db, fact_statement="보증금은 3억 원이다.",
        claim_statement="보증금은 2억 원이다.",
        link_type=original_link_type,
    )
    reconcile_case_conflicts(db, case_id=case.id, dry_run=False, sync_neo4j=False)
    db.expire_all()
    assert db.get(EvidenceLink, link.id).link_type == "CONTRADICTS"


def test_genuine_conflict_remains_visible_after_graph_validation(db, monkeypatch):
    """원천 금액 불일치처럼 실제 모순인 관계는 그래프 필터가 숨기지 않는다."""
    case, fact, claim, _ = seed_conflict(
        db, fact_statement="보증금은 3억 원이다.",
        claim_statement="보증금은 2억 원이다.",
    )
    monkeypatch.setattr("ai_legal_helper.database.neo4j.get_neo4j_driver", lambda: None)
    confirmed = graph_route._validated_graph_contradictions(case=case, db=db)
    assert len(confirmed) == 1
    assert confirmed[0]["target_id"] == fact.id
    assert confirmed[0]["contradicting_id"] == claim.id


@pytest.mark.parametrize("really_conflicts", [False, True])
def test_graph_rag_consultation_excludes_false_contradiction(db, really_conflicts):
    """UI 외 상담 GraphRAG 컨텍스트도 현재 증거로 재검증된 CONTRADICTS만 전달한다."""
    if really_conflicts:
        case, fact, claim, _ = seed_conflict(
            db, fact_statement="보증금은 3억 원이다.",
            claim_statement="보증금은 2억 원이다.",
        )
    else:
        case, fact, claim, _ = seed_conflict(db)

    raw = [{
        "target_type": "Fact",
        "target_id": fact.id,
        "target_content": fact.statement,
        "contradicting_id": claim.id,
        "contradicting_statement": claim.statement,
    }]
    filtered = filter_verified_graph_contradictions(db, case.id, raw)
    assert len(filtered) == (1 if really_conflicts else 0)

    graph_path = {
        "target_type": "Fact",
        "target_id": fact.id,
        "relation": "CONTRADICTS",
        "claim_id": claim.id,
        "evidence_id": claim.evidence_id,
    }
    checked = validate_graph_paths(db, case.id, [graph_path])
    if really_conflicts:
        assert len(checked["valid"]) == 1
        assert checked["invalid"] == []
    else:
        assert checked["valid"] == []
        assert "UNVERIFIED_CONTRADICTION" in checked["invalid"][0]["reasons"]
