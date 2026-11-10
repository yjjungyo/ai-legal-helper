# -*- coding: utf-8 -*-
"""증거 문서 연쇄 삭제 및 정합성 보존 단위 테스트 모듈.

[역할]
증거 문서(EvidenceDocument) 삭제 시 연관된 Fact, Claim, Span, Link, Adjudication,
Event, Party, LegalIssue 및 Neo4j Knowledge Graph가 단일 트랜잭션에서
정합성 있게 연쇄 삭제(Cascade Deletion)되는지 검증한다.

[주요 테스트 시나리오]
1. 단독 지지 Fact 삭제: 삭제 대상 증거만 지지하던 사실은 영구 삭제된다.
2. 다중 지지 Fact 보존: 다른 승인 증거도 지지하던 사실은 보존되고 source_ref만 갱신된다.
3. 종속 하위 엔티티 연쇄 삭제: EvidenceSpan, EvidenceClaim, EvidenceLink, FactAdjudication 정리.
4. 외래 참조 정리: LegalIssue, Event, Party의 related_fact_ids에서 삭제된 Fact ID가 제거된다.
5. Neo4j Graph 동기화: safe_sync_case가 즉시 동기 호출되어 그래프가 일치된다.
"""

from unittest.mock import MagicMock, patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_legal_helper.database.models import (
    Base,
    Case,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceSpan,
    EvidenceSpanClaimLink,
    EvidenceLink,
    Fact,
    Event,
    LegalIssue,
    Party,
    FactAdjudication,
    EvidenceGap,
    EvidenceAssessment,
)
from ai_legal_helper.case_intelligence.evidence_manager import (
    delete_evidence_document_and_cascade,
    cleanup_orphaned_evidence_artifacts,
)


@pytest.fixture
def in_memory_db():
    """테스트용 인메모리 SQLite DB 세션을 생성한다."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_delete_evidence_document_cascades_exclusive_facts(in_memory_db):
    """단독 지지 사실은 증거 삭제 시 함께 삭제되고 다중 지지 사실은 보존된다."""
    db = in_memory_db
    case_id = "test-case-001"
    ev1_id = "ev-doc-001"
    ev2_id = "ev-doc-002"

    # 1. 테스트 데이터 셋업
    case = Case(id=case_id, title="보증금 반환 사건")
    db.add(case)

    doc1 = EvidenceDocument(
        id=ev1_id,
        case_id=case_id,
        original_filename="E01_계약서.txt",
        safe_storage_key="e01.txt",
        media_type="text/plain",
        size_bytes=100,
        sha256="hash1",
        status="APPROVED",
    )
    doc2 = EvidenceDocument(
        id=ev2_id,
        case_id=case_id,
        original_filename="E02_이체내역.txt",
        safe_storage_key="e02.txt",
        media_type="text/plain",
        size_bytes=200,
        sha256="hash2",
        status="APPROVED",
    )
    db.add_all([doc1, doc2])

    # doc1 전용 Span 및 Claim
    span1 = EvidenceSpan(id="span-1", evidence_id=ev1_id, text_excerpt="보증금 3억 계약")
    claim1 = EvidenceClaim(id="claim-1", case_id=case_id, evidence_id=ev1_id, statement="보증금 3억 계약 체결", review_status="APPROVED")
    
    # doc2 전용 Span 및 Claim
    span2 = EvidenceSpan(id="span-2", evidence_id=ev2_id, text_excerpt="3억 송금 완료")
    claim2 = EvidenceClaim(id="claim-2", case_id=case_id, evidence_id=ev2_id, statement="3억 송금 완료", review_status="APPROVED")
    
    db.add_all([span1, claim1, span2, claim2])

    # Fact A: doc1 단독 지지 사실
    fact_a = Fact(id="fact-a", case_id=case_id, statement="보증금 3억 계약 체결", source_ref=ev1_id, source_type="DOCUMENT_SUPPORTED")
    # Fact B: doc1과 doc2가 함께 지지하는 사실 (동일 statement)
    fact_b = Fact(id="fact-b", case_id=case_id, statement="3억 송금 완료", source_ref=ev1_id, source_type="DOCUMENT_SUPPORTED")
    db.add_all([fact_a, fact_b])

    # EvidenceLink 생성
    link_a = EvidenceLink(evidence_id=ev1_id, claim_id="claim-1", target_type="FACT", target_id="fact-a", link_type="SUPPORTS")
    link_b1 = EvidenceLink(evidence_id=ev1_id, claim_id="claim-1", target_type="FACT", target_id="fact-b", link_type="SUPPORTS")
    link_b2 = EvidenceLink(evidence_id=ev2_id, claim_id="claim-2", target_type="FACT", target_id="fact-b", link_type="SUPPORTS")
    db.add_all([link_a, link_b1, link_b2])

    # Event, LegalIssue, Party 연결
    party = Party(id="party-1", case_id=case_id, name="임차인", related_fact_ids=["fact-a", "fact-b"], related_claim_ids=["claim-1"])
    event = Event(id="event-1", case_id=case_id, title="계약 체결", related_fact_ids=["fact-a"], source_type="EVIDENCE_DERIVED")
    issue = LegalIssue(id="issue-1", case_id=case_id, title="보증금 회수", related_fact_ids=["fact-a", "fact-b"])
    db.add_all([party, event, issue])

    # FactAdjudication
    adj_a = FactAdjudication(fact_id="fact-a", claim_id="claim-1", case_id=case_id, supporting_evidence_ids=[ev1_id], adjudication_status="EVIDENCE_SUPPORTED")
    adj_b = FactAdjudication(fact_id="fact-b", claim_id="claim-2", case_id=case_id, supporting_evidence_ids=[ev1_id, ev2_id], adjudication_status="CORROBORATED")
    db.add_all([adj_a, adj_b])

    db.commit()

    # 2. doc1 삭제 실행 (Mocking safe_sync_case & os.remove)
    with patch("ai_legal_helper.database.graph_sync.safe_sync_case") as mock_graph_sync, \
         patch("os.path.exists", return_value=False), \
         patch("ai_legal_helper.case_intelligence.evidence_manager.synchronize_case_entities"):
        result = delete_evidence_document_and_cascade(db, case_id=case_id, evidence_id=ev1_id, sync_graph_immediately=True)
        db.commit()

    # 3. 검증
    # doc1 삭제 확인
    assert db.query(EvidenceDocument).filter_by(id=ev1_id).first() is None
    # doc2는 안전하게 보존
    assert db.query(EvidenceDocument).filter_by(id=ev2_id).first() is not None

    # doc1에 속한 span1, claim1 삭제 확인
    assert db.query(EvidenceSpan).filter_by(id="span-1").first() is None
    assert db.query(EvidenceClaim).filter_by(id="claim-1").first() is None
    # doc2에 속한 span2, claim2는 보존 확인
    assert db.query(EvidenceSpan).filter_by(id="span-2").first() is not None
    assert db.query(EvidenceClaim).filter_by(id="claim-2").first() is not None

    # 단독 지지 Fact A는 삭제되어야 함
    assert db.query(Fact).filter_by(id="fact-a").first() is None
    # 다중 지지 Fact B는 보존되어야 하고, source_ref는 ev2_id로 갱신되어야 함
    fact_b_db = db.query(Fact).filter_by(id="fact-b").first()
    assert fact_b_db is not None
    assert fact_b_db.source_ref == ev2_id

    # 외래 참조 정리 확인
    party_db = db.query(Party).filter_by(id="party-1").first()
    assert "fact-a" not in party_db.related_fact_ids
    assert "fact-b" in party_db.related_fact_ids
    assert "claim-1" not in party_db.related_claim_ids

    issue_db = db.query(LegalIssue).filter_by(id="issue-1").first()
    assert "fact-a" not in issue_db.related_fact_ids
    assert "fact-b" in issue_db.related_fact_ids

    # FactAdjudication B의 supporting_evidence_ids에서 ev1_id가 제거되어 ev2_id만 남아야 함
    adj_b_db = db.query(FactAdjudication).filter_by(fact_id="fact-b").first()
    assert adj_b_db is not None
    assert ev1_id not in adj_b_db.supporting_evidence_ids
    assert ev2_id in adj_b_db.supporting_evidence_ids

    # Neo4j 동기화 호출 확인
    mock_graph_sync.assert_called_once_with(case_id)
    assert result["status"] == "SUCCESS"
    assert result["deleted_facts_count"] >= 1


def test_cleanup_orphaned_evidence_artifacts(in_memory_db):
    """증거 문서가 삭제되어 남아있던 고아 Span과 Claim이 일괄 청소된다."""
    db = in_memory_db
    case_id = "test-case-orphan"

    case = Case(id=case_id, title="고아 테스트 사건")
    db.add(case)

    # 존재하지 않는 non-existent-doc-id를 가진 고아 span & claim
    orphan_span = EvidenceSpan(id="orphan-span-1", evidence_id="non-existent-doc", text_excerpt="고아 텍스트")
    orphan_claim = EvidenceClaim(id="orphan-claim-1", case_id=case_id, evidence_id="non-existent-doc", statement="고아 주장")
    orphan_link = EvidenceLink(id="orphan-link-1", evidence_id="non-existent-doc", target_type="FACT", target_id="some-fact", link_type="SUPPORTS")
    db.add_all([orphan_span, orphan_claim, orphan_link])
    db.commit()

    with patch("ai_legal_helper.database.graph_sync.safe_sync_case"):
        stats = cleanup_orphaned_evidence_artifacts(db, case_id=case_id, sync_graph=False)
        db.commit()

    assert stats["orphaned_spans"] == 1
    assert stats["orphaned_claims"] == 1
    assert stats["orphaned_links"] == 1

    assert db.query(EvidenceSpan).filter_by(id="orphan-span-1").first() is None
    assert db.query(EvidenceClaim).filter_by(id="orphan-claim-1").first() is None
    assert db.query(EvidenceLink).filter_by(id="orphan-link-1").first() is None
