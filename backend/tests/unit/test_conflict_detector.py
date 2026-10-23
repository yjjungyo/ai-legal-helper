# -*- coding: utf-8 -*-
"""
모듈명: test_conflict_detector.py

[모듈 개요]
다중 증거 문서 환경의 3단계 증거 상충 탐지 엔진(conflict_detector.py) 및
관련 추출·리뷰·복구·API 중복 제거 로직을 검증하는 단위 테스트 모듈이다.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_legal_helper.case_intelligence.conflict_detector import (
    build_structured_slots,
    evaluate_claim_against_fact,
    evaluate_claim_conflicts,
    extract_normalized_amounts,
    extract_normalized_dates,
    parse_korean_number_phrase,
    reconcile_case_conflicts,
)
from ai_legal_helper.case_intelligence.evidence_extractor import detect_conflicting_fact
from ai_legal_helper.case_intelligence.evidence_manager import process_evidence_review
from ai_legal_helper.api.routes.evidence import get_evidence_conflicts
from ai_legal_helper.database.models import (
    Base,
    Case,
    EvidenceClaim,
    EvidenceDocument,
    EvidenceLink,
    Fact,
    User,
)


def _create_in_memory_db():
    """격리된 인메모리 SQLite 세션을 생성한다."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionTesting()


def test_korean_numeral_place_value_parser():
    """한국어 기수법 자릿수 연산 파서가 다양한 금액 표현을 동일한 원(KRW) 정수로 정규화하는지 검증한다."""
    assert parse_korean_number_phrase("3억") == 300_000_000
    assert parse_korean_number_phrase("삼억") == 300_000_000
    assert parse_korean_number_phrase("300,000,000") == 300_000_000
    assert parse_korean_number_phrase("1억 5,000만") == 150_000_000
    assert parse_korean_number_phrase("일억오천만") == 150_000_000
    assert parse_korean_number_phrase("2천 5백만") == 25_000_000
    assert parse_korean_number_phrase("오백만") == 5_000_000

    assert extract_normalized_amounts("보증금은 금 300,000,000원정으로 한다.") == [300_000_000]
    assert extract_normalized_amounts("전세보증금 3억 원의 반환을 요청하였다.") == [300_000_000]
    assert extract_normalized_amounts("차임은 월 150만 원이다.") == [1_500_000]


def test_date_normalization():
    """다양한 한국어·점·하이픈 날짜 표기가 ISO YYYY-MM-DD로 정규화되는지 검증한다."""
    assert extract_normalized_dates("2026년 9월 30일에 맞춰 반환 요청") == ["2026-09-30"]
    assert extract_normalized_dates("계약기간은 2022. 3. 5.부터 2024-03-04까지이다.") == [
        "2022-03-05",
        "2024-03-04",
    ]


def test_stage1_document_local_metadata_not_conflicting():
    """서로 다른 증거 문서의 고유 제목(DOC_INFO / DOCUMENT_LOCAL)은 상충 비교 대상에서 제외(DIFFERENT_CONTEXT)되어야 한다."""
    fact_contract_title = Fact(
        id="fact-title-1",
        case_id="case-1",
        statement="문서의 제목은 '주택임대차계약서'이다.",
        fact_type="DOC_INFO",
        source_type="EVIDENCE_DERIVED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_slots = build_structured_slots(
        statement="문서의 제목은 '퇴거 및 보증금 반환 요청 문자'이다.",
        claim_type="DOC_INFO",
        evidence_id="doc-2",
        document_name="E05_퇴거_및_보증금_반환_요청_문자.txt",
    )
    decision = evaluate_claim_against_fact(claim_slots, fact_contract_title, fact_doc_name="E01_주택임대차계약서.txt")
    assert decision.status == "DIFFERENT_CONTEXT"
    assert decision.reason_code == "DOCUMENT_LOCAL_METADATA"
    assert detect_conflicting_fact(claim_slots.statement, [fact_contract_title], claim_type="DOC_INFO") is None


def test_stage1_date_vs_amount_dimension_isolation():
    """날짜만 포함된 진술과 금액만 포함된 진술은 공통 키워드를 공유하더라도 교차 비교되지 않아야 한다."""
    fact_amount = Fact(
        id="fact-amt-1",
        case_id="case-1",
        statement="보증금은 300,000,000원이다.",
        fact_type="AMOUNT",
        source_type="EVIDENCE_DERIVED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_slots = build_structured_slots(
        statement="보증금 반환 요청일로 특정된 날짜는 2026년 9월 30일이다.",
        claim_type="DATE",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(claim_slots, fact_amount)
    assert decision.status == "DIFFERENT_CONTEXT"
    assert decision.reason_code == "INCOMPATIBLE_VALUE_DIMENSION"


def test_stage2_same_amount_different_format_is_consistent():
    """한글 단위 금액과 아라비아 숫자 금액이 정규화 후 일치하면 CONSISTENT로 판정되어야 한다."""
    fact_amount = Fact(
        id="fact-amt-1",
        case_id="case-1",
        statement="보증금은 300,000,000원이다.",
        fact_type="AMOUNT",
        source_type="EVIDENCE_DERIVED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    # 1) 순수 금액 진술 비교 (합성명사 '전세보증금' vs '보증금')
    claim_slots_1 = build_structured_slots(
        statement="전세보증금 반환 요청 금액은 3억 원이다.",
        claim_type="AMOUNT",
        evidence_id="doc-2",
    )
    decision_1 = evaluate_claim_against_fact(claim_slots_1, fact_amount)
    assert decision_1.status == "CONSISTENT"
    assert decision_1.reason_code == "NORMALIZED_AMOUNT_MATCH"

    # 2) 날짜 + 금액 복합 진술과 순수 금액 진술 비교
    claim_slots_2 = build_structured_slots(
        statement="이수현은 2026년 9월 30일에 맞춰 전세보증금 3억 원의 반환을 요청하였다.",
        claim_type="ACTION",
        evidence_id="doc-2",
    )
    decision_2 = evaluate_claim_against_fact(claim_slots_2, fact_amount)
    assert decision_2.status == "CONSISTENT"
    assert decision_2.reason_code == "NORMALIZED_AMOUNT_MATCH"


def test_stage2_true_contradiction_on_mutually_exclusive_amount_and_polarity():
    """동일 대상에 대해 정규화 금액이 실제로 다르거나 긍정/부정 극성이 정반대이면 CONTRADICTION으로 탐지되어야 한다."""
    fact_amount = Fact(
        id="fact-amt-1",
        case_id="case-1",
        statement="보증금은 300,000,000원이다.",
        fact_type="AMOUNT",
        source_type="EVIDENCE_DERIVED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    diff_amount_slots = build_structured_slots(
        statement="전세보증금은 2억 원이다.",
        claim_type="AMOUNT",
        evidence_id="doc-2",
    )
    decision_amt = evaluate_claim_against_fact(diff_amount_slots, fact_amount)
    assert decision_amt.status == "CONTRADICTION"
    assert decision_amt.reason_code == "MUTUALLY_EXCLUSIVE_AMOUNT"

    fact_action = Fact(
        id="fact-act-1",
        case_id="case-1",
        statement="임대인은 임차인에게 보증금을 전액 반환하였다.",
        fact_type="ACTION",
        source_type="EVIDENCE_DERIVED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    neg_action_slots = build_structured_slots(
        statement="임대인은 임차인에게 보증금을 반환하지 않았다.",
        claim_type="ACTION",
        evidence_id="doc-2",
    )
    decision_pol = evaluate_claim_against_fact(neg_action_slots, fact_action)
    assert decision_pol.status == "CONTRADICTION"
    assert decision_pol.reason_code == "OPPOSITE_POLARITY_ON_SAME_SUBJECT"


def test_reconcile_and_deduplicate_conflicts_in_db():
    """오탐 상충 데이터의 자동 복구(reconcile_case_conflicts)와 API 중복 제거를 검증한다."""
    db = _create_in_memory_db()
    user = User(id="u-1", email="test@example.com", password_hash="pw")
    case = Case(id="c-1", user_id="u-1", title="임대차 보증금 반환 사건")
    doc1 = EvidenceDocument(
        id="doc-1",
        case_id="c-1",
        original_filename="계약서.txt",
        media_type="text/plain",
        size_bytes=100,
        sha256="hash1",
        safe_storage_key="doc1.txt",
        status="EXTRACTED",
    )
    doc2 = EvidenceDocument(
        id="doc-2",
        case_id="c-1",
        original_filename="반환요청문자.txt",
        media_type="text/plain",
        size_bytes=100,
        sha256="hash2",
        safe_storage_key="doc2.txt",
        status="EXTRACTED",
    )
    fact1 = Fact(
        id="f-1",
        case_id="c-1",
        statement="보증금은 300,000,000원이다.",
        fact_type="AMOUNT",
        source_type="EVIDENCE_DERIVED",
        source_ref="doc-1",
        verification_status="DISPUTED",
    )
    # 오탐으로 CONTRADICTION_CANDIDATE 및 CONTRADICTS 링크가 걸린 Claim
    false_claim = EvidenceClaim(
        id="cl-false",
        case_id="c-1",
        evidence_id="doc-2",
        statement="전세보증금 반환 요청 금액은 3억 원이다.",
        claim_type="AMOUNT",
        assertion_status="CONTRADICTION_CANDIDATE",
        review_status="APPROVED",
        confidence=0.95,
    )
    false_link = EvidenceLink(
        id="lnk-false",
        evidence_id="doc-2",
        claim_id="cl-false",
        target_type="FACT",
        target_id="f-1",
        link_type="CONTRADICTS",
    )
    # 실제 상충하는 Claim (동일 보증금 항목이 2억 원으로 기재)
    true_claim = EvidenceClaim(
        id="cl-true",
        case_id="c-1",
        evidence_id="doc-2",
        statement="보증금은 2억 원이다.",
        claim_type="AMOUNT",
        assertion_status="CONTRADICTION_CANDIDATE",
        review_status="PENDING",
        confidence=0.9,
    )
    true_link = EvidenceLink(
        id="lnk-true",
        evidence_id="doc-2",
        claim_id="cl-true",
        target_type="FACT",
        target_id="f-1",
        link_type="CONTRADICTS",
    )
    db.add_all([user, case, doc1, doc2, fact1, false_claim, false_link, true_claim, true_link])
    db.commit()

    # 1) API 조회 시 오탐(cl-false)은 필터링되고, 진성 상충(cl-true)은 LINK와 CLAIM에서 중복 없이 1건만 반환되어야 함
    api_before = get_evidence_conflicts(case=case, db=db)
    assert len(api_before["conflicts"]) == 1
    assert api_before["conflicts"][0]["claim_id"] == "cl-true"
    assert api_before["conflicts"][0]["reason_code"] == "MUTUALLY_EXCLUSIVE_AMOUNT"

    # 2) DB 복구(reconcile_case_conflicts) 실행 시 오탐 링크는 SUPPORTS로 전환되고 cl-false 상태가 정상화되어야 함
    rec = reconcile_case_conflicts(db, case_id="c-1", sync_neo4j=False)
    assert rec["converted_supports_links"] == 1
    assert rec["reset_claims"] == 1

    db.refresh(false_claim)
    db.refresh(false_link)
    assert false_claim.assertion_status == "DOCUMENT_STATES"
    assert false_link.link_type == "SUPPORTS"

    # 3) 진성 상충 Claim을 사용자가 REJECT하면 CONTRADICTS 링크가 제거되어 상충 목록이 0건이 되어야 함
    process_evidence_review(db, "cl-true", action="REJECT", review_reason="오추출")
    api_after = get_evidence_conflicts(case=case, db=db)
    assert len(api_after["conflicts"]) == 0
    db.close()

