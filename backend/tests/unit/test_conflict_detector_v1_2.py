"""
[모듈 설명]
Evidence Conflict Detection Engine v1.2 단위 및 시나리오 회귀 테스트 슈트.
Fact Semantic & Temporal Reasoning 고도화에 따른 시나리오(S01~S16) 및
정량적 오탐 개선 지표(v1.1 대비 정밀도, 재현율, 오탐률)를 철저히 검증한다.

- 작성일: 2026-10-24
- 설계 기준: Evidence Conflict Detection Engine v1.2 지시서
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_legal_helper.database.models import (
    Base,
    User,
    Case,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceLink,
    EvidenceSpan,
    EvidenceSpanClaimLink,
    Fact,
)
from ai_legal_helper.case_intelligence.conflict_detector import (
    build_structured_slots,
    evaluate_claim_against_fact,
    reconcile_case_conflicts,
)
from ai_legal_helper.case_intelligence.fact_semantics import (
    extract_semantic_fact,
    compare_fact_identity,
    evaluate_temporal_relation,
)
from ai_legal_helper.api.routes.evidence import get_evidence_conflicts


def _create_test_db():
    """인메모리 SQLite 격리 테스트 세션을 생성한다."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return session_factory()


class TestConflictDetectorV12Scenarios:
    """Evidence Conflict Detection Engine v1.2 핵심 시나리오(S01~S16) 검증 테스트."""

    def test_s01_down_payment_vs_balance_payment_due_date(self):
        """[S01] 계약금 지급기일과 잔금 지급기일은 별개 거래 단계이므로 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "잔금 지급기일은 2022년 3월 1일이다."
        fact_stmt = "계약금 지급기일은 2022년 2월 20일이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "DIFFERENT_PAYMENT_COMPONENT"

        # 파이프라인 통합 평가 확인
        c_slots = build_structured_slots(statement=claim_stmt, claim_type="DATE")
        fact = Fact(id="f-s01", statement=fact_stmt, fact_type="DATE", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "DIFFERENT_PAYMENT_COMPONENT"

    def test_s02_same_payment_component_conflicting_due_dates(self):
        """[S02] 동일한 계약금 지급기일에 대해 서로 다른 날짜 진술은 POTENTIAL_CONFLICT 판정."""
        claim_stmt = "계약금 지급기일은 2022년 2월 25일이다."
        fact_stmt = "계약금 지급기일은 2022년 2월 20일이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        # 동일 대상·동일 거래단계이므로 비교 관문 통과(COMPARABLE)
        assert res.is_comparable
        assert res.status == "COMPARABLE"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="DATE")
        fact = Fact(id="f-s02", statement=fact_stmt, fact_type="DATE", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "POTENTIAL_CONFLICT"
        assert decision.reason_code == "SAME_EVENT_DATE_DISCREPANCY"

    def test_s03_due_date_vs_actual_performance_same_date(self):
        """[S03] 약정 잔금일과 실제 잔금 지급일이 동일한 경우 양립 가능(CONSISTENT, TEMPORALLY_COMPATIBLE) 판정."""
        claim_stmt = "잔금 270,000,000원은 2022년 3월 1일에 실제로 지급되었다."
        fact_stmt = "잔금 지급기일은 2022년 3월 1일이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "CONSISTENT"
        assert res.reason_code == "TEMPORALLY_COMPATIBLE"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="DATE")
        fact = Fact(id="f-s03", statement=fact_stmt, fact_type="DATE", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "CONSISTENT"
        assert decision.reason_code == "TEMPORALLY_COMPATIBLE"

    def test_s04_initial_registration_event_vs_maintained_status(self):
        """[S04] 최초 전입신고일(행위)과 특정 기준일 전입 유지 상태(상태)는 EVENT_VS_STATE로 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "2026.10.15 기준 전입 유지 여부는 임차인 진술상 유지 중이다."
        fact_stmt = "전입신고일은 2022.03.02이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "EVENT_VS_STATE"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="CONDITION")
        fact = Fact(id="f-s04", statement=fact_stmt, fact_type="DATE", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "EVENT_VS_STATE"

    def test_s05_lease_start_date_vs_renewal_maintained_status(self):
        """[S05] 임대차 개시일과 갱신 이후 점유 유지 상태는 상충 경고 없이 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "2026.10.15 기준 임차인은 목적물에 거주 중이다."
        fact_stmt = "임대차 개시일은 2022.03.01이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"

    def test_s06_principal_deposit_vs_down_payment_amount(self):
        """[S06] 보증금 원금(3억 원)과 계약금(3천만 원)은 서로 다른 지급 항목이므로 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "계약금은 30,000,000원이다."
        fact_stmt = "보증금은 300,000,000원이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "DIFFERENT_PAYMENT_COMPONENT"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="AMOUNT")
        fact = Fact(id="f-s06", statement=fact_stmt, fact_type="AMOUNT", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "DIFFERENT_PAYMENT_COMPONENT"

    def test_s07_principal_deposit_vs_balance_payment_amount(self):
        """[S07] 보증금 원금(3억 원)과 잔금(2억 7천만 원)은 서로 다른 지급 항목이므로 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "잔금은 270,000,000원이다."
        fact_stmt = "보증금은 300,000,000원이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "DIFFERENT_PAYMENT_COMPONENT"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="AMOUNT")
        fact = Fact(id="f-s07", statement=fact_stmt, fact_type="AMOUNT", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "DIFFERENT_PAYMENT_COMPONENT"

    def test_s08_performance_vs_non_performance_at_same_point(self):
        """[S08] 동일 시점 동일 의무에 대한 이행과 미이행의 정면 대립은 CONTRADICTION 판정."""
        claim_stmt = "임대인은 2024년 2월 28일에 보증금을 반환하지 않았다."
        fact_stmt = "임대인은 2024년 2월 28일에 보증금을 전액 반환하였다."

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="CONDITION")
        fact = Fact(id="f-s08", statement=fact_stmt, fact_type="CONDITION", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "CONTRADICTION"
        assert decision.reason_code in ("OPPOSITE_POLARITY_ON_SAME_SUBJECT", "DIRECT_POLARITY_CONFLICT")

    def test_s09_contract_signing_vs_registry_receipt(self):
        """[S09] 계약 체결일과 등기 접수일은 서로 다른 사건 유형이므로 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "등기 접수일은 2022년 3월 5일이다."
        fact_stmt = "계약 체결일은 2022년 2월 5일이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "DIFFERENT_EVENT_TYPE"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="DATE")
        fact = Fact(id="f-s09", statement=fact_stmt, fact_type="DATE", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "DIFFERENT_EVENT_TYPE"

    def test_s10_labor_hire_vs_resignation_dates(self):
        """[S10] 근로계약상 입사일과 퇴사일은 서로 다른 고용 단계이므로 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "근로자의 퇴사일은 2023년 12월 31일이다."
        fact_stmt = "근로자의 입사일은 2020년 1월 1일이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "DIFFERENT_EMPLOYMENT_STAGE"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="DATE")
        fact = Fact(id="f-s10", statement=fact_stmt, fact_type="DATE", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "DIFFERENT_EMPLOYMENT_STAGE"

    def test_s11_loan_origination_vs_partial_repayment(self):
        """[S11] 대여금 발생일과 일부 변제일은 서로 다른 거래 단계이므로 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "차용인은 2022년 5월 10일에 원금 일부변제를 하였다."
        fact_stmt = "대여일은 2021년 5월 10일이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "DIFFERENT_TRANSACTION_STAGE"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="DATE")
        fact = Fact(id="f-s11", statement=fact_stmt, fact_type="DATE", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "DIFFERENT_TRANSACTION_STAGE"

    def test_s12_notice_sent_vs_notice_reached_dates(self):
        """[S12] 해지 통고서 발송일과 수령(도달)일은 구별되는 절차 단계이므로 DIFFERENT_CONTEXT 판정."""
        claim_stmt = "계약해지 통지서가 도달한 날은 2026년 9월 3일이다."
        fact_stmt = "계약해지 통지서를 발송한 날은 2026년 9월 1일이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "DIFFERENT_COMMUNICATION_STAGE"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="DATE")
        fact = Fact(id="f-s12", statement=fact_stmt, fact_type="DATE", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "DIFFERENT_COMMUNICATION_STAGE"

    def test_s13_epistemic_unconfirmed_status_vs_affirmative_fact(self):
        """[S13] 인식 불확실성('가입 여부는 확인되지 않았다')은 긍정 사실과 모순되지 않음 (DIFFERENT_CONTEXT)."""
        claim_stmt = "전세보증금 반환보증보험 가입 여부는 확인되지 않았다."
        fact_stmt = "임차인은 전세보증금 반환보증보험에 가입하였다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert not res.is_comparable
        assert res.status == "DIFFERENT_CONTEXT"
        assert res.reason_code == "EPISTEMIC_STATUS_NOT_CONTRADICTION"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="CONDITION")
        fact = Fact(id="f-s13", statement=fact_stmt, fact_type="CONDITION", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "DIFFERENT_CONTEXT"
        assert decision.reason_code == "EPISTEMIC_STATUS_NOT_CONTRADICTION"

    def test_s14_conflicting_deposit_amounts_is_contradiction(self):
        """[S14] 동일 계약의 보증금 총액에 대한 서로 다른 금액 진술은 직접적 CONTRADICTION 판정."""
        claim_stmt = "보증금은 250,000,000원이다."
        fact_stmt = "보증금은 300,000,000원이다."

        c_sem = extract_semantic_fact(claim_stmt)
        f_sem = extract_semantic_fact(fact_stmt)
        res = compare_fact_identity(c_sem, f_sem)

        assert res.is_comparable
        assert res.status == "COMPARABLE"

        c_slots = build_structured_slots(statement=claim_stmt, claim_type="AMOUNT")
        fact = Fact(id="f-s14", statement=fact_stmt, fact_type="AMOUNT", verification_status="DOCUMENT_VERIFIED")
        decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

        assert decision.status == "CONTRADICTION"
        assert decision.reason_code in ("MUTUALLY_EXCLUSIVE_AMOUNT", "NORMALIZED_AMOUNT_CONFLICT")

    def test_s15_reconciliation_cleans_up_false_conflict_links(self):
        """[S15] reconcile_case_conflicts 실행 시 오탐된 링크들이 정확히 정리되고 멱등성이 보장됨."""
        db = _create_test_db()
        user = User(id="u-s15", email="s15@example.com", password_hash="hash")
        case = Case(id="c-s15", user_id="u-s15", title="오탐 정리 테스트")
        doc1 = EvidenceDocument(
            id="doc-s15-1",
            case_id="c-s15",
            original_filename="계약서.txt",
            media_type="text/plain",
            size_bytes=100,
            sha256="h1",
            safe_storage_key="k1",
            status="APPROVED",
        )
        doc2 = EvidenceDocument(
            id="doc-s15-2",
            case_id="c-s15",
            original_filename="문자.txt",
            media_type="text/plain",
            size_bytes=100,
            sha256="h2",
            safe_storage_key="k2",
            status="APPROVED",
        )
        fact_down_payment = Fact(
            id="f-down",
            case_id="c-s15",
            statement="계약금 지급기일은 2022년 2월 20일이다.",
            fact_type="DATE",
            source_ref="doc-s15-1",
            verification_status="DISPUTED",
        )
        claim_balance = EvidenceClaim(
            id="cl-balance",
            case_id="c-s15",
            evidence_id="doc-s15-2",
            statement="잔금 지급기일은 2022년 3월 1일이다.",
            claim_type="DATE",
            assertion_status="CONTRADICTION_CANDIDATE",
            review_status="APPROVED",
            confidence=0.9,
        )
        # 과거 v1.1에서 잘못 생성된 CONTRADICTS 링크
        false_link = EvidenceLink(
            id="lnk-false-s15",
            evidence_id="doc-s15-2",
            claim_id="cl-balance",
            target_type="FACT",
            target_id="f-down",
            link_type="CONTRADICTS",
        )
        db.add_all([user, case, doc1, doc2, fact_down_payment, claim_balance, false_link])
        db.commit()

        # dry_run 확인: 실제 변경 없이 삭제 계획 산출 확인
        dry_res = reconcile_case_conflicts(db, case_id="c-s15", dry_run=True, sync_neo4j=False)
        assert dry_res["removed_false_contradict_links"] == 1
        assert len(dry_res["changes"]) >= 1

        # 실제 1회차 복구 수행
        rec1 = reconcile_case_conflicts(db, case_id="c-s15", dry_run=False, sync_neo4j=False)
        assert rec1["removed_false_contradict_links"] == 1
        assert rec1["reset_claims"] == 1

        # 2회차 실행 시 변경 0건 (멱등성 보장)
        rec2 = reconcile_case_conflicts(db, case_id="c-s15", dry_run=False, sync_neo4j=False)
        assert rec2["removed_false_contradict_links"] == 0
        assert rec2["converted_supports_links"] == 0
        assert rec2["reset_claims"] == 0
        db.close()

    def test_s16_neo4j_fallback_to_postgresql_api(self, monkeypatch):
        """[S16] Neo4j 드라이버 연결 실패 시에도 PostgreSQL 기반 get_evidence_conflicts가 정상 서빙됨."""
        monkeypatch.setattr("ai_legal_helper.database.neo4j.get_neo4j_driver", lambda: None)
        db = _create_test_db()
        user = User(id="u-s16", email="s16@example.com", password_hash="hash")
        case = Case(id="c-s16", user_id="u-s16", title="Neo4j 폴백 테스트")
        doc = EvidenceDocument(
            id="doc-s16",
            case_id="c-s16",
            original_filename="증거.txt",
            media_type="text/plain",
            size_bytes=100,
            sha256="h1",
            safe_storage_key="k1",
            status="APPROVED",
        )
        fact = Fact(
            id="f-s16",
            case_id="c-s16",
            statement="보증금은 300,000,000원이다.",
            fact_type="AMOUNT",
            source_ref="doc-s16",
            verification_status="DISPUTED",
        )
        claim = EvidenceClaim(
            id="cl-s16",
            case_id="c-s16",
            evidence_id="doc-s16",
            statement="보증금은 200,000,000원이다.",
            claim_type="AMOUNT",
            assertion_status="CONTRADICTION_CANDIDATE",
            review_status="APPROVED",
            confidence=0.9,
        )
        link = EvidenceLink(
            id="lnk-s16",
            evidence_id="doc-s16",
            claim_id="cl-s16",
            target_type="FACT",
            target_id="f-s16",
            link_type="CONTRADICTS",
        )
        db.add_all([user, case, doc, fact, claim, link])
        db.commit()

        api_res = get_evidence_conflicts(case=case, db=db)
        assert len(api_res["conflicts"]) == 1
        assert api_res["contradiction_count"] == 1
        assert api_res["conflicts"][0]["claim_id"] == "cl-s16"
        db.close()


class TestQuantitativeEvaluationV11VsV12:
    """v1.1 대비 v1.2 상충 엔진 정량적 지표(정밀도, 재현율, 오탐률) 비교 평가."""

    def test_quantitative_accuracy_metrics(self):
        """
        벤치마크 20개 명제 쌍에 대해 정량적 성능 지표를 산출하고
        v1.2의 오탐률(FPR) 0%, 정밀도(Precision) 100%, 재현율(Recall) 100%를 입증한다.
        """
        # 검증용 테스트 데이터셋: (Claim, Fact, Type, GroundTruth: CONTRADICT/POTENTIAL/NOT_CONFLICT)
        benchmark_dataset = [
            # 1. 계약금 vs 잔금 (지급 단계 차이: 비상충)
            ("잔금 지급기일은 2022년 3월 1일이다.", "계약금 지급기일은 2022년 2월 20일이다.", "DATE", "NOT_CONFLICT"),
            # 2. 계약금 기일 상충 (동일 단계 날짜 불일치: 모순/주의)
            ("계약금 지급기일은 2022년 2월 25일이다.", "계약금 지급기일은 2022년 2월 20일이다.", "DATE", "CONFLICT"),
            # 3. 약정일 vs 실제지급일 (동일 일자 정상 이행: 비상충/호환)
            ("잔금은 2022년 3월 1일에 실제로 지급되었다.", "잔금 지급기일은 2022년 3월 1일이다.", "DATE", "NOT_CONFLICT"),
            # 4. 전입신고일(행위) vs 전입유지(상태) (시간/범주 차이: 비상충)
            ("2026.10.15 기준 전입 유지 여부는 임차인 진술상 유지 중이다.", "전입신고일은 2022.03.02이다.", "CONDITION", "NOT_CONFLICT"),
            # 5. 임대차 개시일 vs 거주 유지 상태 (비상충)
            ("2026.10.15 기준 임차인은 목적물에 거주 중이다.", "임대차 개시일은 2022.03.01이다.", "CONDITION", "NOT_CONFLICT"),
            # 6. 보증금 총액 vs 계약금 (금액 단계 차이: 비상충)
            ("계약금은 30,000,000원이다.", "보증금은 300,000,000원이다.", "AMOUNT", "NOT_CONFLICT"),
            # 7. 보증금 총액 vs 잔금 (금액 단계 차이: 비상충)
            ("잔금은 270,000,000원이다.", "보증금은 300,000,000원이다.", "AMOUNT", "NOT_CONFLICT"),
            # 8. 보증금 반환 이행 vs 불이행 (진짜 모순: 상충)
            ("임대인은 2024년 2월 28일에 보증금을 반환하지 않았다.", "임대인은 2024년 2월 28일에 보증금을 전액 반환하였다.", "CONDITION", "CONFLICT"),
            # 9. 계약 체결일 vs 등기 접수일 (사건 유형 차이: 비상충)
            ("등기 접수일은 2022년 3월 5일이다.", "계약 체결일은 2022년 2월 5일이다.", "DATE", "NOT_CONFLICT"),
            # 10. 근로계약 입사일 vs 퇴사일 (고용 단계 차이: 비상충)
            ("근로자의 퇴사일은 2023년 12월 31일이다.", "근로자의 입사일은 2020년 1월 1일이다.", "DATE", "NOT_CONFLICT"),
            # 11. 대여 발생일 vs 일부 변제일 (채무 단계 차이: 비상충)
            ("차용인은 2022년 5월 10일에 원금 일부변제를 하였다.", "대여일은 2021년 5월 10일이다.", "DATE", "NOT_CONFLICT"),
            # 12. 통지 발송일 vs 도달일 (통지 단계 차이: 비상충)
            ("계약해지 통지서가 도달한 날은 2026년 9월 3일이다.", "계약해지 통지서를 발송한 날은 2026년 9월 1일이다.", "DATE", "NOT_CONFLICT"),
            # 13. 미확인 상태 vs 긍정 사실 (인식 불확실성: 비상충)
            ("전세보증금 반환보증보험 가입 여부는 확인되지 않았다.", "임차인은 전세보증금 반환보증보험에 가입하였다.", "CONDITION", "NOT_CONFLICT"),
            # 14. 보증금 총액 직접 불일치 (진짜 모순: 상충)
            ("보증금은 250,000,000원이다.", "보증금은 300,000,000원이다.", "AMOUNT", "CONFLICT"),
            # 15. 보증금 원금과 반환 요청 금액 동일 (일치/호환: 비상충)
            ("전세보증금 반환 요청 금액은 3억 원이다.", "보증금은 300,000,000원이다.", "AMOUNT", "NOT_CONFLICT"),
            # 16. 서로 다른 문서 고유 메타데이터 (비상충)
            ("문서의 제목은 '퇴거 및 보증금 반환 요청 문자'이다.", "문서의 제목은 '주택임대차계약서'이다.", "METADATA", "NOT_CONFLICT"),
            # 17. 은행 가압류 vs HUG 가압류 (채권자 객체 분리: 비상충)
            ("동진은행 가압류 청구금액은 50,000,000원이다.", "HUG 가압류 청구금액은 70,000,000원이다.", "AMOUNT", "NOT_CONFLICT"),
            # 18. 반복적 문자 발송 내역 (시점 다름: 비상충)
            ("임차인은 2026년 9월 1일에 문자를 보냈다.", "임차인은 2026년 9월 15일에 문자를 보냈다.", "DATE", "NOT_CONFLICT"),
            # 19. 잔금 지급기일 정면 대립 (상충)
            ("잔금 지급기일은 2022년 3월 10일이다.", "잔금 지급기일은 2022년 3월 1일이다.", "DATE", "CONFLICT"),
            # 20. 월 차임 금액 직접 불일치 (상충)
            ("월 차임은 1,000,000원이다.", "월 차임은 500,000원이다.", "AMOUNT", "CONFLICT"),
        ]

        tp, fp, tn, fn = 0, 0, 0, 0

        for claim_stmt, fact_stmt, claim_type, ground_truth in benchmark_dataset:
            c_slots = build_structured_slots(statement=claim_stmt, claim_type=claim_type)
            fact = Fact(id="f-eval", statement=fact_stmt, fact_type=claim_type, verification_status="DOCUMENT_VERIFIED")
            decision = evaluate_claim_against_fact(claim_slots=c_slots, fact=fact)

            pred_is_conflict = decision.status in ("CONTRADICTION", "POTENTIAL_CONFLICT")

            if ground_truth == "CONFLICT":
                if pred_is_conflict:
                    tp += 1
                else:
                    fn += 1
            else:  # NOT_CONFLICT
                if pred_is_conflict:
                    fp += 1
                else:
                    tn += 1

        total = len(benchmark_dataset)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

        # 목표 기준 달성 검증
        assert total == 20
        assert fp == 0, f"False positives detected: {fp} cases"
        assert fn == 0, f"False negatives detected: {fn} cases"
        assert precision == 1.0
        assert recall == 1.0
        assert fpr == 0.0
