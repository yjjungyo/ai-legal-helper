# -*- coding: utf-8 -*-
"""
모듈명: test_conflict_detector.py

[모듈 개요]
Evidence Conflict Detection Engine v1.1의 3단계 상충 탐지 엔진(conflict_detector.py),
구조화 슬롯 영속화, Claim 승인/수정/반려 생명주기 정합성(evidence_manager.py),
API 중복 제거 및 소유권 검증(evidence.py), Verifier 게이팅 연계(legal_workflow.py),
그리고 복구 함수(reconcile_case_conflicts)의 멱등성·dry_run·안전장치를 검증하는
단위 및 통합 시나리오 테스트 모듈이다 (T01 ~ T16 및 엣지케이스 포괄).
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_legal_helper.case_intelligence.conflict_detector import (
     analyze_polarity_and_predicate,
    build_structured_slots,
    evaluate_claim_against_fact,
    evaluate_claim_conflicts,
    extract_amount_roles,
    extract_dates_with_validation,
    extract_normalized_amounts,
    extract_normalized_dates,
    parse_korean_number_phrase,
    reconcile_case_conflicts,
)
from ai_legal_helper.case_intelligence.evidence_extractor import detect_conflicting_fact
from ai_legal_helper.case_intelligence.evidence_manager import process_evidence_review
from ai_legal_helper.api.routes.evidence import (
    ReviewRequest,
    get_evidence_conflicts,
    review_evidence_claim,
)
from ai_legal_helper.database.models import (
    Base,
    Case,
    Event,
    EvidenceClaim,
    EvidenceDocument,
    EvidenceLink,
    EvidenceSpan,
    EvidenceSpanClaimLink,
    Fact,
    LegalIssue,
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


def test_t01_different_document_titles_are_different_context():
    """[T01] 서로 다른 증거 문서의 고유 제목(DOC_INFO / DOCUMENT_LOCAL)은 DIFFERENT_CONTEXT로 판정되어야 한다."""
    fact_contract_title = Fact(
        id="fact-title-1",
        case_id="case-1",
        statement="문서의 제목은 '주택임대차계약서'이다.",
        fact_type="DOC_INFO",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_slots = build_structured_slots(
        statement="문서의 제목은 '퇴거 요청 문자'이다.",
        claim_type="DOC_INFO",
        evidence_id="doc-2",
        document_name="E05_퇴거_요청_문자.txt",
    )
    decision = evaluate_claim_against_fact(claim_slots, fact_contract_title, fact_doc_name="E01_주택임대차계약서.txt")
    assert decision.status == "DIFFERENT_CONTEXT"
    assert decision.reason_code == "DOCUMENT_LOCAL_METADATA"
    assert detect_conflicting_fact(claim_slots.statement, [fact_contract_title], claim_type="DOC_INFO") is None


def test_t02_same_amount_different_notation_is_consistent():
    """[T02] 같은 금액의 다른 표기('보증금은 300,000,000원이다' vs '전세보증금은 3억 원이다')는 CONSISTENT로 판정되어야 한다."""
    fact_amount = Fact(
        id="fact-amt-1",
        case_id="case-1",
        statement="보증금은 300,000,000원이다.",
        fact_type="AMOUNT",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_slots = build_structured_slots(
        statement="전세보증금은 3억 원이다.",
        claim_type="AMOUNT",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(claim_slots, fact_amount)
    assert decision.status == "CONSISTENT"
    assert decision.reason_code == "NORMALIZED_AMOUNT_MATCH"


def test_t03_principal_deposit_vs_partial_returned_amount_not_contradiction():
    """[T03] 약정 금액('보증금은 3억 원이다')과 일부 반환 금액('임대인은 2억 원을 반환하였다')은 의미 역할이 다르므로 CONTRADICTION이 금지된다."""
    fact_deposit = Fact(
        id="fact-dep-1",
        case_id="case-1",
        statement="보증금은 3억 원이다.",
        fact_type="AMOUNT",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_returned = build_structured_slots(
        statement="임대인은 2억 원을 반환하였다.",
        claim_type="ACTION",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(claim_returned, fact_deposit, enable_llm_verification=False)
    assert decision.status != "CONTRADICTION"
    assert decision.status in ("DIFFERENT_CONTEXT", "POTENTIAL_CONFLICT")
    assert decision.reason_code == "DIFFERENT_AMOUNT_ATTRIBUTE"


def test_t04_contract_deposit_mismatch_is_contradiction():
    """[T04] 동일 계약 보증금에 대한 금액 불일치('계약서상 보증금은 3억 원이다' vs '계약서상 보증금은 2억 원이다')는 CONTRADICTION이어야 한다."""
    fact_deposit = Fact(
        id="fact-dep-1",
        case_id="case-1",
        statement="계약서상 보증금은 3억 원이다.",
        fact_type="AMOUNT",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_mismatch = build_structured_slots(
        statement="계약서상 보증금은 2억 원이다.",
        claim_type="AMOUNT",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(claim_mismatch, fact_deposit, enable_llm_verification=False)
    assert decision.status == "CONTRADICTION"
    assert decision.reason_code == "MUTUALLY_EXCLUSIVE_AMOUNT"


def test_t05_composite_date_and_amount_with_conflicting_date_not_consistent():
    """[T05] 금액(3억 원)이 같더라도 동일 행위의 날짜가 다르면('2026-09-30 보증금 3억 원 반환 요청' vs '2026-10-15 보증금 3억 원 반환 요청') CONSISTENT가 금지된다."""
    fact_req = Fact(
        id="fact-req-1",
        case_id="case-1",
        statement="2026-09-30 보증금 3억 원 반환 요청",
        fact_type="ACTION",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_req = build_structured_slots(
        statement="2026-10-15 보증금 3억 원 반환 요청",
        claim_type="ACTION",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(claim_req, fact_req, enable_llm_verification=False)
    assert decision.status != "CONSISTENT"
    assert decision.status in ("CONTRADICTION", "POTENTIAL_CONFLICT")
    assert decision.reason_code == "SAME_AMOUNT_BUT_DATE_DISCREPANCY"


def test_t06_direct_negation_is_contradiction():
    """[T06] 동일 행위에 대한 직접 긍정 vs 직접 부정('보증금을 반환하였다' vs '보증금을 반환하지 않았다')은 CONTRADICTION이어야 한다."""
    fact_returned = Fact(
        id="fact-act-1",
        case_id="case-1",
        statement="보증금을 반환하였다.",
        fact_type="ACTION",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_not_returned = build_structured_slots(
        statement="보증금을 반환하지 않았다.",
        claim_type="ACTION",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(claim_not_returned, fact_returned, enable_llm_verification=False)
    assert decision.status == "CONTRADICTION"
    assert decision.reason_code == "OPPOSITE_POLARITY_ON_SAME_SUBJECT"


def test_t07_double_negation_and_reported_speech_false_positive_prevention():
    """[T07] 이중 부정('보증금 반환을 거절하지 않았다' vs '보증금을 반환하지 않았다') 및 간접화법 부정은 단순 극성 반전 오탐을 일으키지 않아야 한다."""
    pol_double, _, _ = analyze_polarity_and_predicate("보증금 반환을 거절하지 않았다.")
    assert pol_double == "DOUBLE_NEGATIVE"

    pol_reported, _, _ = analyze_polarity_and_predicate("임대인은 보증금을 반환할 수 없다고 통보하였다.")
    assert pol_reported == "REPORTED_NEGATIVE"

    fact_not_returned = Fact(
        id="fact-neg-1",
        case_id="case-1",
        statement="보증금을 반환하지 않았다.",
        fact_type="ACTION",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_double_neg = build_structured_slots(
        statement="보증금 반환을 거절하지 않았다.",
        claim_type="ACTION",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(claim_double_neg, fact_not_returned, enable_llm_verification=False)
    assert decision.status != "CONTRADICTION"
    assert decision.status in ("POTENTIAL_CONFLICT", "DIFFERENT_CONTEXT")


def test_t08_t09_t10_claim_review_lifecycle_and_fact_cleanup():
    """[T08, T09, T10] Claim 승인 -> 수정(EDIT) -> 다중 지지 일부 반려(REJECT) -> 단독 지지 반려(REJECT) 시 데이터 정합성을 검증한다."""
    db = _create_in_memory_db()
    user = User(id="u-1", email="lifecycle@example.com", password_hash="pw")
    case = Case(id="c-life", user_id="u-1", title="생명주기 정합성 사건")
    doc1 = EvidenceDocument(
        id="doc-1",
        case_id="c-life",
        original_filename="계약서.txt",
        media_type="text/plain",
        size_bytes=100,
        sha256="h1",
        safe_storage_key="d1.txt",
        status="REVIEW_REQUIRED",
    )
    doc2 = EvidenceDocument(
        id="doc-2",
        case_id="c-life",
        original_filename="확인서.txt",
        media_type="text/plain",
        size_bytes=100,
        sha256="h2",
        safe_storage_key="d2.txt",
        status="REVIEW_REQUIRED",
    )
    claim_a = EvidenceClaim(
        id="claim-a",
        case_id="c-life",
        evidence_id="doc-1",
        statement="2024년 3월 5일 보증금은 3억 원이다.",
        claim_type="AMOUNT",
        assertion_status="DOCUMENT_STATES",
        review_status="PENDING",
        confidence=0.95,
    )
    claim_b = EvidenceClaim(
        id="claim-b",
        case_id="c-life",
        evidence_id="doc-2",
        statement="2024년 3월 5일 보증금은 3억 원으로 정한다.",
        claim_type="AMOUNT",
        assertion_status="DOCUMENT_STATES",
        review_status="PENDING",
        confidence=0.92,
    )
    db.add_all([user, case, doc1, doc2, claim_a, claim_b])
    db.commit()

    # 1. Claim A 승인 -> Fact F1 생성 및 타임라인 Event 생성 확인
    process_evidence_review(
        db,
        claim_id="claim-a",
        action="APPROVE",
        expected_case_id="c-life",
        expected_evidence_id="doc-1",
    )
    facts_after_approve = db.query(Fact).filter_by(case_id="c-life").all()
    assert len(facts_after_approve) == 1
    f1_id = facts_after_approve[0].id
    assert facts_after_approve[0].occurred_at == "2024-03-05"

    # LegalIssue가 F1을 참조하도록 설정
    issue = LegalIssue(
        id="iss-1",
        case_id="c-life",
        title="보증금 반환 쟁점",
        related_fact_ids=[f1_id],
    )
    db.add(issue)
    db.commit()

    # [T08] Claim A 수정(EDIT) -> 단독 지지하던 기존 Fact F1은 삭제되고 새 Fact F2가 생성되어야 함
    process_evidence_review(
        db,
        claim_id="claim-a",
        action="EDIT",
        new_statement="2024년 3월 5일 보증금은 3억 5천만 원이다.",
        expected_case_id="c-life",
        expected_evidence_id="doc-1",
    )
    facts_after_edit = db.query(Fact).filter_by(case_id="c-life").all()
    assert len(facts_after_edit) == 1
    f2 = facts_after_edit[0]
    assert f2.id != f1_id
    assert f2.statement == "2024년 3월 5일 보증금은 3억 5천만 원이다."
    db.refresh(issue)
    assert f1_id not in (issue.related_fact_ids or [])

    # [T09] Claim B를 동일 진술로 수정 승인하여 F2를 Claim A와 Claim B가 공동 지지하게 만든 뒤 Claim A 반려
    process_evidence_review(
        db,
        claim_id="claim-b",
        action="EDIT",
        new_statement="2024년 3월 5일 보증금은 3억 5천만 원이다.",
        expected_case_id="c-life",
        expected_evidence_id="doc-2",
    )
    sup_links = db.query(EvidenceLink).filter_by(target_id=f2.id, link_type="SUPPORTS").all()
    assert len(sup_links) == 2

    # Claim A 반려 -> Claim B가 여전히 F2를 지지하므로 F2는 유지되고 Claim A의 링크만 제거되어야 함
    process_evidence_review(
        db,
        claim_id="claim-a",
        action="REJECT",
        review_reason="중복 기재 반려",
        expected_case_id="c-life",
        expected_evidence_id="doc-1",
    )
    facts_after_partial_reject = db.query(Fact).filter_by(case_id="c-life").all()
    assert len(facts_after_partial_reject) == 1
    assert facts_after_partial_reject[0].id == f2.id
    assert db.query(EvidenceLink).filter_by(claim_id="claim-a").count() == 0
    assert db.query(EvidenceLink).filter_by(claim_id="claim-b", target_id=f2.id, link_type="SUPPORTS").count() == 1

    # [T10] 이제 단독 지지가 된 Claim B를 반려 -> Fact F2 및 관련 링크, 타임라인 Event가 모두 정리되어야 함
    process_evidence_review(
        db,
        claim_id="claim-b",
        action="REJECT",
        review_reason="오추출 반려",
        expected_case_id="c-life",
        expected_evidence_id="doc-2",
    )
    assert db.query(Fact).filter_by(case_id="c-life").count() == 0
    assert db.query(EvidenceLink).filter_by(claim_id="claim-b").count() == 0
    assert db.query(Event).filter_by(case_id="c-life").count() == 0
    db.close()


def test_t11_t12_t14_deduplication_neo4j_fallback_and_reconcile_idempotency(monkeypatch):
    """[T11, T12, T14] 상충 중복 제거, Neo4j 비활성 시 PostgreSQL Fallback, 복구 함수 안전장치·dry_run·멱등성을 검증한다."""
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
    span2 = EvidenceSpan(
        id="sp-2",
        evidence_id="doc-2",
        page_number=2,
        paragraph_index=0,
        text_excerpt="보증금은 2억 원이다.",
    )
    fact1 = Fact(
        id="f-1",
        case_id="c-1",
        statement="보증금은 300,000,000원이다.",
        fact_type="AMOUNT",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DISPUTED",
    )
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
    true_claim = EvidenceClaim(
        id="cl-true",
        case_id="c-1",
        evidence_id="doc-2",
        statement="보증금은 2억 원이다.",
        claim_type="AMOUNT",
        assertion_status="CONTRADICTION_CANDIDATE",
        review_status="APPROVED",
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
    span_link = EvidenceSpanClaimLink(claim_id="cl-true", span_id="sp-2")
    db.add_all([user, case, doc1, doc2, span2, fact1, false_claim, false_link, true_claim, true_link, span_link])
    db.commit()

    # [T12] Neo4j가 비활성(get_neo4j_driver -> None)이어도 PostgreSQL 기반으로 상충 조회가 정상 동작해야 함
    monkeypatch.setattr("ai_legal_helper.database.neo4j.get_neo4j_driver", lambda: None)
    api_res = get_evidence_conflicts(case=case, db=db)

    # [T11] EvidenceLink와 EvidenceClaim(CONTRADICTION_CANDIDATE)에 모두 존재하더라도 API 결과는 중복 없이 1건이어야 함
    assert len(api_res["conflicts"]) == 1
    assert api_res["contradiction_count"] == 1
    assert api_res["conflicts"][0]["claim_id"] == "cl-true"
    assert api_res["conflicts"][0]["page_number"] == 2
    assert api_res["conflicts"][0]["paragraph_index"] == 0

    # [T14-1] case_id=None 이면서 allow_all_cases=False 호출 시 안전장치(ValueError) 동작 확인
    with pytest.raises(ValueError):
        reconcile_case_conflicts(db, case_id=None, allow_all_cases=False, sync_neo4j=False)

    # [T14-2] dry_run=True 실행 시 변경 내역(changes)은 산출되나 DB에는 반영되지 않아야 함
    dry_res = reconcile_case_conflicts(db, case_id="c-1", dry_run=True, sync_neo4j=False)
    assert dry_res["dry_run"] is True
    assert dry_res["converted_supports_links"] == 1
    assert len(dry_res["changes"]) > 0
    db.refresh(false_link)
    assert false_link.link_type == "CONTRADICTS"  # dry_run이므로 롤백 유지

    # [T14-3] 실제 복구 1회차 실행 후 2회차 실행 시 추가 변경이 0건(멱등성)이어야 함
    rec1 = reconcile_case_conflicts(db, case_id="c-1", dry_run=False, sync_neo4j=False)
    assert rec1["converted_supports_links"] == 1
    assert rec1["reset_claims"] == 1

    rec2 = reconcile_case_conflicts(db, case_id="c-1", dry_run=False, sync_neo4j=False)
    assert rec2["removed_false_contradict_links"] == 0
    assert rec2["converted_supports_links"] == 0
    assert rec2["reset_claims"] == 0
    assert rec2["restored_disputed_facts"] == 0
    db.close()


def test_t13_stage3_llm_failure_fallback_never_forces_contradiction(monkeypatch):
    """[T13] Stage 3 LLM 검증 중 예외/타임아웃 발생 시 POTENTIAL_CONFLICT로 안전하게 폴백하며 강제 CONTRADICTION을 금지한다."""
    monkeypatch.setattr(
        "ai_legal_helper.case_intelligence.conflict_detector.get_llm",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Simulated LLM timeout")),
    )
    fact = Fact(
        id="f-ambig",
        case_id="case-1",
        statement="임차인은 주택 인도 의무를 이행하기로 약정하였다.",
        fact_type="CONDITION",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_slots = build_structured_slots(
        statement="임차인은 보증금 수령과 동시에 주택 인도 의무를 이행하기로 하였다.",
        claim_type="CONDITION",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(
        claim_slots=claim_slots,
        fact=fact,
        enable_llm_verification=True,
    )
    assert decision.status == "POTENTIAL_CONFLICT"
    assert decision.status != "CONTRADICTION"
    assert decision.reason_code == "LLM_VERIFICATION_UNAVAILABLE"


def test_t15_ownership_validation_blocks_cross_case_or_cross_document_claim():
    """[T15] 다른 사건 또는 다른 증거 문서의 claim_id로 리뷰를 요청하면 거부(ValueError / HTTP 400)되어야 한다."""
    db = _create_in_memory_db()
    user = User(id="u-1", email="owner@example.com", password_hash="pw")
    case1 = Case(id="case-1", user_id="u-1", title="사건 1")
    case2 = Case(id="case-2", user_id="u-1", title="사건 2")
    doc1 = EvidenceDocument(
        id="doc-1",
        case_id="case-1",
        original_filename="문서1.txt",
        media_type="text/plain",
        size_bytes=50,
        sha256="h1",
        safe_storage_key="d1.txt",
        status="REVIEW_REQUIRED",
    )
    doc2 = EvidenceDocument(
        id="doc-2",
        case_id="case-2",
        original_filename="문서2.txt",
        media_type="text/plain",
        size_bytes=50,
        sha256="h2",
        safe_storage_key="d2.txt",
        status="REVIEW_REQUIRED",
    )
    claim_in_case2 = EvidenceClaim(
        id="claim-case2",
        case_id="case-2",
        evidence_id="doc-2",
        statement="보증금은 1억 원이다.",
        claim_type="AMOUNT",
        review_status="PENDING",
    )
    db.add_all([user, case1, case2, doc1, doc2, claim_in_case2])
    db.commit()

    # 1) 서비스 계층(process_evidence_review)에서 expected_case_id 불일치 시 ValueError 발생
    with pytest.raises(ValueError):
        process_evidence_review(
            db,
            claim_id="claim-case2",
            action="APPROVE",
            expected_case_id="case-1",
            expected_evidence_id="doc-1",
        )

    # 2) 라우터 계층(review_evidence_claim)에서 다른 사건/문서의 claim_id 호출 시 HTTPException(400) 발생
    with pytest.raises(HTTPException) as exc_info:
        review_evidence_claim(
            evidence_id="doc-1",
            claim_id="claim-case2",
            req=ReviewRequest(action="APPROVE"),
            request=None,
            background_tasks=None,
            current_user=user,
            case=case1,
            db=db,
        )
    assert exc_info.value.status_code in (400, 403, 404)
    db.close()


def test_t16_invalid_calendar_date_rejected():
    """[T16] 달력상 존재하지 않는 비정상 날짜('2026년 2월 31일 지급')는 유효 날짜로 정규화되지 않고 INSUFFICIENT_INFORMATION을 반환해야 한다."""
    valid_dates, invalid_dates, date_roles = extract_dates_with_validation("2026년 2월 31일 지급")
    assert valid_dates == []
    assert len(invalid_dates) == 1
    assert "31" in invalid_dates[0]
    assert extract_normalized_dates("2026년 2월 31일 지급") == []

    fact_date = Fact(
        id="fact-date-1",
        case_id="case-1",
        statement="보증금 지급일은 2026년 2월 28일이다.",
        fact_type="DATE",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    claim_invalid_date = build_structured_slots(
        statement="보증금 지급일은 2026년 2월 31일이다.",
        claim_type="DATE",
        evidence_id="doc-2",
    )
    decision = evaluate_claim_against_fact(claim_invalid_date, fact_date, enable_llm_verification=False)
    assert decision.status == "INSUFFICIENT_INFORMATION"
    assert decision.reason_code == "INVALID_CALENDAR_DATE"


def test_edge_cases_multi_amount_and_temporal_context():
    """[8.2 엣지케이스] 한 문장 내 다중 금액(계약금/중도금/잔금), 빈 문자열 Claim, 시점 변경(최초 계약 vs 갱신 계약)을 검증한다."""
    # 1) 한 문장 내 다중 금액 역할 분리
    multi_stmt = "보증금 3억 원 중 계약금 3천만 원은 계약 시 지급하고 잔금 2억 7천만 원은 2024년 5월 1일에 지급한다."
    amounts, roles = extract_amount_roles(multi_stmt)
    assert 300_000_000 in amounts
    assert roles.get("PRINCIPAL_DEPOSIT") == [300_000_000]
    assert roles.get("DOWN_PAYMENT") == [30_000_000]
    assert roles.get("INTERIM_OR_BALANCE") == [270_000_000]

    fact_deposit = Fact(
        id="f-dep",
        case_id="case-1",
        statement="임대차 보증금은 300,000,000원이다.",
        fact_type="AMOUNT",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    multi_slots = build_structured_slots(statement=multi_stmt, claim_type="AMOUNT", evidence_id="doc-2")
    dec_multi = evaluate_claim_against_fact(multi_slots, fact_deposit, enable_llm_verification=False)
    assert dec_multi.status == "CONSISTENT"

    # 2) 최초 계약 보증금 vs 갱신 계약 증액 보증금 -> CONTRADICTION이 아닌 POTENTIAL_CONFLICT 또는 DIFFERENT_CONTEXT
    fact_initial = Fact(
        id="f-init",
        case_id="case-1",
        statement="최초 계약 당시 보증금은 3억 원이다.",
        fact_type="AMOUNT",
        source_type="DOCUMENT_SUPPORTED",
        source_ref="doc-1",
        verification_status="DOCUMENT_VERIFIED",
    )
    renewal_slots = build_structured_slots(
        statement="갱신 계약에서 증액된 변경 보증금은 3억 5천만 원이다.",
        claim_type="AMOUNT",
        evidence_id="doc-2",
    )
    dec_renewal = evaluate_claim_against_fact(renewal_slots, fact_initial, enable_llm_verification=False)
    assert dec_renewal.status != "CONTRADICTION"
    assert dec_renewal.status in ("DIFFERENT_CONTEXT", "POTENTIAL_CONFLICT")

    # 3) 빈 문자열 Claim -> INSUFFICIENT_INFORMATION
    empty_slots = build_structured_slots(statement="   ", claim_type="GENERAL", evidence_id="doc-2")
    dec_empty = evaluate_claim_against_fact(empty_slots, fact_deposit, enable_llm_verification=False)
    assert dec_empty.status == "INSUFFICIENT_INFORMATION"


def test_p1_03_verifier_evidence_conflict_gating_integration(monkeypatch):
    """[P1-03 & 8.3] 핵심 Fact 상충 시 Verifier가 단정적 답변을 REVISE(EVIDENCE_CONFLICT)로 차단하고 조건부 답변은 CAUTIONARY로 분류하는지 검증한다."""
    from ai_legal_helper.workflows.legal_workflow import verification_condition, verification_node

    monkeypatch.setattr(
        "ai_legal_helper.agents.verification.run_verification",
        lambda q, draft, sources, ctx="": {
            "status": "PASS",
            "reason_code": "NONE",
            "warnings": [],
            "claims": [],
            "citation_audit": {"verified_sources": sources},
        },
    )

    contradiction_item = {
        "target_type": "Fact",
        "target_id": "f-deposit",
        "target_content": "계약서상 전세보증금은 3억 원이다.",
        "contradicting_statement": "영수증상 전세보증금은 2억 원이다.",
    }

    # 1) 상충을 언급하지 않고 단정적으로 결론 내린 초안 -> REVISE + EVIDENCE_CONFLICT -> 재검토 한도 초과 시 insufficient(WITHHELD)
    state_definitive = {
        "question": "전세보증금 반환 청구 금액은 얼마인가요?",
        "draft_answer": "임대인은 전세보증금 3억 원 전액을 즉시 반환해야 합니다.",
        "retrieved_sources": [],
        "case_context": "",
        "revision_count": 1,
        "hilt_executed": False,
        "graph_evidence": {
            "available": False,
            "valid_paths": [],
            "structured_matches": [],
            "evidence_gaps": [],
            "contradictions": [contradiction_item],
        },
    }
    ver_out_1 = verification_node(state_definitive)
    res_1 = ver_out_1["verification_result"]
    assert res_1["status"] == "REVISE"
    assert res_1["reason_code"] == "EVIDENCE_CONFLICT"
    assert res_1["conflict_acknowledged"] is False
    state_definitive["verification_result"] = res_1
    assert verification_condition(state_definitive) == "insufficient"

    # 2) 상충 사실을 명시하고 조건부로 답변한 초안 -> finalize(CAUTIONARY)로 라우팅
    state_cautionary = {
        **state_definitive,
        "draft_answer": "제출된 계약서(3억 원)와 영수증(2억 원) 간에 전세보증금 액수의 상충이 존재하므로 실제 이체 내역 확인이 필요하며, 확인된 금액에 따라 반환 범위가 달라집니다.",
        "revision_count": 0,
    }
    ver_out_2 = verification_node(state_cautionary)
    res_2 = ver_out_2["verification_result"]
    assert res_2["status"] == "REVISE"
    assert res_2["reason_code"] == "EVIDENCE_CONFLICT"
    assert res_2["conflict_acknowledged"] is True
    state_cautionary["verification_result"] = res_2
    assert verification_condition(state_cautionary) == "finalize"
