# -*- coding: utf-8 -*-
"""
Evidence Reliability & Fact Adjudication Engine v1.0 단위 테스트 스위트
(backend/tests/unit/test_evidence_adjudication.py)

[테스트 대상 및 범위]
- R01 ~ R07: CASE-01 ~ CASE-07 핵심 판정 정합성
- R08 ~ R14: 7대 증거 신뢰성 차원 평가 (EvidenceAssessment)
- R15 ~ R19: 증거 공백 탐지 및 보완 추천 생성 (EvidenceGap)
- R20 ~ R24: 사실 확정 5대 상태 판정 (FactAdjudication)
- R25 ~ R28: 리뷰 생명주기(APPROVE/EDIT/REJECT) 및 DB 영구 저장 정합성
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_legal_helper.database.session import Base
from ai_legal_helper.database.models import (
    User,
    Case,
    Fact,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceLink,
    EvidenceAssessment,
    FactAdjudication,
    EvidenceGap,
    FactComparisonAudit,
)
from ai_legal_helper.case_intelligence.fact_semantics import (
    extract_semantic_proposition,
    check_proposition_comparability,
)
from ai_legal_helper.case_intelligence.evidence_reliability import (
    evaluate_evidence_reliability,
    EvidenceAssessmentResult,
)
from ai_legal_helper.case_intelligence.evidence_gap import (
    detect_evidence_gap,
    EvidenceGapItem,
)
from ai_legal_helper.case_intelligence.fact_adjudicator import (
    adjudicate_fact,
    FactAdjudicationResult,
)
from ai_legal_helper.case_intelligence.evidence_manager import (
    process_evidence_review,
)


def _create_in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


# ==============================================================================
# 1. CASE-01 ~ CASE-07 핵심 판정 검증 (R01 ~ R07)
# ==============================================================================

class TestCase01To07Scenarios:
    """CASE-01부터 CASE-07까지 지시서 필수 시나리오 검증."""

    def test_r01_case01_tenant_identity_vs_insurance_unconfirmed(self):
        """[R01/CASE-01] 임차인 신원 확인 사실과 보증보험 미확인 메모는 상충이 아니며,
        계약서로 입증된 임차인 신원은 EVIDENCE_SUPPORTED 상태를 유지해야 함."""
        claim_stmt = "전세보증금 반환보증보험 가입 여부는 확인되지 않았다."
        fact_stmt = "임차인은 이수현이다."

        prop_claim = extract_semantic_proposition(claim_stmt)
        prop_fact = extract_semantic_proposition(fact_stmt)

        comp = check_proposition_comparability(prop_claim, prop_fact)
        assert not comp.is_comparable
        assert comp.status == "DIFFERENT_CONTEXT"

        gap = detect_evidence_gap(prop_claim)
        assert gap is not None
        assert gap.gap_type == "HUG_INSURANCE_CONFIRMATION_GAP"

        adj = adjudicate_fact(prop_claim)
        assert adj.adjudication_status == "EVIDENCE_INCOMPLETE"
        assert adj.primary_relation == "EVIDENCE_GAP"

    def test_r02_case02_different_encumbrance_creditor_instances(self):
        """[R02/CASE-02] 서로 다른 가압류 채권자(동진은행 72M vs HUG 120M)는 별개 인스턴스이므로 상충 아님."""
        stmt_a = "동진은행 가압류 청구금액은 72,000,000원이다."
        stmt_b = "주택도시보증공사 가압류 청구금액은 120,000,000원이다."

        prop_a = extract_semantic_proposition(stmt_a)
        prop_b = extract_semantic_proposition(stmt_b)

        comp = check_proposition_comparability(prop_a, prop_b)
        assert not comp.is_comparable
        assert comp.status == "DIFFERENT_CONTEXT"
        assert comp.reason_code in ("DIFFERENT_OBJECT_QUALIFIER", "DIFFERENT_EVENT_INSTANCE")

    def test_r03_case03_down_payment_vs_total_deposit_sum(self):
        """[R03/CASE-03] 계약금(3천만 원)과 보증금 합계(3억 원)는 COMPONENT_OF / SUM_OF 양립 관계."""
        claim_stmt = "계약금은 30,000,000원이다."
        fact_stmt = "보증금 합계는 300,000,000원이다."

        prop_c = extract_semantic_proposition(claim_stmt)
        prop_f = extract_semantic_proposition(fact_stmt)

        comp = check_proposition_comparability(prop_c, prop_f)
        assert not comp.is_comparable
        assert comp.status == "CONSISTENT"
        assert comp.reason_code == "COMPONENT_OF_SUM"

        adj = adjudicate_fact(prop_c, candidate_facts=[Fact(statement=fact_stmt)])
        assert adj.primary_relation == "PART_OF"
        assert adj.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")

    def test_r04_case04_proposal_vs_rejection_speech_acts(self):
        """[R04/CASE-04] 임대인의 분할반환 제안과 임차인의 거절은 RESPONDS_TO 관계로서 양립 가능함."""
        stmt_proposal = "임대인은 보증금 분할 반환 방안을 제안하였다."
        stmt_rejection = "임차인은 분할 반환 방안에 동의하지 않고 거절하였다."

        prop_prop = extract_semantic_proposition(stmt_proposal)
        prop_rej = extract_semantic_proposition(stmt_rejection)

        assert prop_prop.speech_act == "PROPOSAL"
        assert prop_rej.speech_act == "REJECTION"

        comp = check_proposition_comparability(prop_prop, prop_rej)
        assert not comp.is_comparable
        assert comp.status == "CONSISTENT"
        assert comp.reason_code == "PROPOSAL_VS_REJECTION"

        adj = adjudicate_fact(prop_rej, candidate_facts=[Fact(statement=stmt_proposal)])
        assert adj.primary_relation == "RESPONDS_TO"

    def test_r05_case05_registry_unsubmitted_vs_occupancy_fact(self):
        """[R05/CASE-05] 등기부 미제출은 증거 공백일 뿐, 입주 사실을 부정하거나 모순되지 않음."""
        claim_stmt = "부동산 등기사항전부증명서는 제출되지 않았다."
        fact_stmt = "임차인은 2022년 3월 1일에 목적물에 입주하였다."

        prop_c = extract_semantic_proposition(claim_stmt)
        prop_f = extract_semantic_proposition(fact_stmt)

        comp = check_proposition_comparability(prop_c, prop_f)
        assert not comp.is_comparable
        assert comp.status == "DIFFERENT_CONTEXT"

        gap = detect_evidence_gap(prop_c)
        assert gap is not None
        assert gap.gap_type == "REGISTRY_CONFIRMATION_GAP"

    def test_r06_case06_loan_guarantee_memory_vs_insurance_unconfirmed(self):
        """[R06/CASE-06] 전세대출 보증 기억 진술과 반환보증 가입 미확인은 상충이 아님."""
        claim_stmt = "임차인은 전세대출 보증에 가입했던 것으로 기억한다."
        fact_stmt = "전세보증금 반환보증보험 가입 여부는 확인되지 않았다."

        prop_c = extract_semantic_proposition(claim_stmt)
        prop_f = extract_semantic_proposition(fact_stmt)

        comp = check_proposition_comparability(prop_c, prop_f)
        assert not comp.is_comparable
        assert comp.status == "DIFFERENT_CONTEXT"

    def test_r07_case07_different_date_messages_are_distinct_events(self):
        """[R07/CASE-07] 날짜가 다른 복수의 문자메시지는 반복 발생 가능한 별개 의사표시 사건."""
        msg1 = "임차인은 2026년 9월 1일에 문자를 보냈다."
        msg2 = "임차인은 2026년 9월 15일에 문자를 보냈다."

        prop1 = extract_semantic_proposition(msg1)
        prop2 = extract_semantic_proposition(msg2)

        comp = check_proposition_comparability(prop1, prop2)
        assert not comp.is_comparable
        assert comp.status == "DIFFERENT_CONTEXT"

    def test_r07_notice_date_vs_scheduled_target_date(self):
        """[R07-B] 의사표시 통지 일자와 퇴거 예정일은 서로 다른 시점 차원이므로 상충이 아님."""
        stmt1 = "이수현은 2026년 4월 1일 임대인에게 2026년 9월 30일 퇴거 의사를 문자로 알렸다."
        stmt2 = "퇴거 예정일은 2026년 9월 30일이다."

        prop1 = extract_semantic_proposition(stmt1)
        prop2 = extract_semantic_proposition(stmt2)

        comp = check_proposition_comparability(prop1, prop2)
        assert not comp.is_comparable
        assert comp.status == "CONSISTENT"
        assert comp.reason_code == "NOTICE_DATE_VS_TARGET_DATE"

        adj = adjudicate_fact(prop2, candidate_facts=[prop1])
        assert adj.adjudication_status != "GENUINELY_DISPUTED"
        assert adj.primary_relation == "SUPPORTS"


# ==============================================================================
# 2. 7대 증거 신뢰성 차원 평가 검증 (R08 ~ R14)
# ==============================================================================

class TestEvidenceReliabilityAssessment:
    """7대 신뢰성 차원(진정성, 직접성, 관련성, 완전성, 시점, 보강, 출처) 평가 검증."""

    def test_r08_bilateral_contract_conclusive_dispositive(self):
        """[R08] 양 당사자 서명 임대차계약서는 BILATERAL_SIGNED, DIRECT_DISPOSITIVE 로 평가됨."""
        prop = extract_semantic_proposition("보증금은 300,000,000원이다.")
        res = evaluate_evidence_reliability("주택임대차계약서.pdf", prop)

        assert res.source_authenticity == "BILATERAL_SIGNED"
        assert res.directness == "DIRECT_DISPOSITIVE"
        assert res.assessment_status == "CONCLUSIVE"
        assert res.reliability_score >= 0.85
        assert "약정 보증금 및 차임" in res.proof_scope["proven_propositions"]

    def test_r09_official_public_registry(self):
        """[R09] 등기사항전부증명서는 OFFICIAL_PUBLIC, DIRECT_DISPOSITIVE 로 평가됨."""
        prop = extract_semantic_proposition("동진은행 근저당권 채권최고액은 1억 원이다.")
        res = evaluate_evidence_reliability("등기사항전부증명서.pdf", prop)

        assert res.source_authenticity == "OFFICIAL_PUBLIC"
        assert res.directness == "DIRECT_DISPOSITIVE"
        assert res.assessment_status == "CONCLUSIVE"

    def test_r10_informal_communication_direct_reported(self):
        """[R10] 카카오톡/문자메시지는 의사표시 전달 사실에 대해 DIRECT_REPORTED 로 평가됨."""
        prop = extract_semantic_proposition("임차인은 2026년 9월 1일에 계약해지 통지를 보냈다.")
        res = evaluate_evidence_reliability("문자메시지_캡처.png", prop)

        assert res.source_authenticity == "INFORMAL_COMMUNICATION"
        assert res.directness == "DIRECT_REPORTED"
        assert res.assessment_status == "RELIABLE"

    def test_r11_hearsay_reported_speech_unsupported(self):
        """[R11] 전언 또는 전문 진술('들었다', '주장한다')은 HEARSAY_UNSUPPORTED 로 평가됨."""
        prop = extract_semantic_proposition("임대인이 다음 세입자 들어오면 준다고 말했다고 진술하였다.")
        res = evaluate_evidence_reliability("상담메모.txt", prop)

        assert res.directness == "HEARSAY_UNSUPPORTED"
        assert res.assessment_status in ("PROVISIONAL", "DEFICIENT")

    def test_r12_corroboration_multi_evidence(self):
        """[R12] 복수 증거에서 동일 사실이 확인되면 FULLY_CORROBORATED 로 평가됨."""
        prop = extract_semantic_proposition("보증금은 300,000,000원이다.")
        other_props = [
            extract_semantic_proposition("보증금은 300,000,000원이다."),
            extract_semantic_proposition("전세보증금 반환 요청 금액은 300,000,000원이다."),
        ]
        res = evaluate_evidence_reliability("임대차계약서.pdf", prop, other_evidence_propositions=other_props)

        assert res.corroboration == "FULLY_CORROBORATED"

    def test_r13_corroboration_direct_contradiction(self):
        """[R13] 신뢰성 높은 다른 증거와 수치 대립 시 DIRECTLY_CONTRADICTED 로 평가됨."""
        prop = extract_semantic_proposition("보증금은 250,000,000원이다.")
        other_props = [extract_semantic_proposition("보증금은 300,000,000원이다.")]
        res = evaluate_evidence_reliability("영수증_메모.txt", prop, other_evidence_propositions=other_props)

        assert res.corroboration == "DIRECTLY_CONTRADICTED"

    def test_r14_proof_scope_limits(self):
        """[R14] 임대차계약서의 입증 한계에 '실제 인도 여부'와 '보증보험 가입 여부'가 명시되어야 함."""
        prop = extract_semantic_proposition("임대차기간은 2022.03.01부터 2024.02.28까지이다.")
        res = evaluate_evidence_reliability("주택임대차계약서.pdf", prop)

        assert "실제 인도/입주 여부" in res.proof_scope["unproven_propositions"]
        assert "보증보험 가입 여부" in res.proof_scope["unproven_propositions"]


# ==============================================================================
# 3. 증거 공백 탐지 및 보완 추천 (R15 ~ R19)
# ==============================================================================

class TestEvidenceGapDetection:
    """증거 공백 탐지 및 추천 서류 매핑 검증."""

    def test_r15_hug_insurance_gap(self):
        """[R15] 보증보험 미확인 시 HUG_INSURANCE_CONFIRMATION_GAP 및 HUG 보증증권 추천."""
        prop = extract_semantic_proposition("전세보증금 반환보증보험 가입 여부는 확인되지 않았다.")
        gap = detect_evidence_gap(prop)

        assert gap is not None
        assert gap.gap_type == "HUG_INSURANCE_CONFIRMATION_GAP"
        assert "HUG 전세보증금 반환보증 증권" in gap.recommended_document_types
        assert gap.priority == "HIGH"

    def test_r16_registry_gap(self):
        """[R16] 등기부 미제출 시 REGISTRY_CONFIRMATION_GAP 및 등기사항전부증명서 추천."""
        prop = extract_semantic_proposition("등기사항전부증명서 원본은 제출되지 않았다.")
        gap = detect_evidence_gap(prop)

        assert gap is not None
        assert gap.gap_type == "REGISTRY_CONFIRMATION_GAP"
        assert any("등기사항전부증명서" in d for d in gap.recommended_document_types)

    def test_r17_notice_delivery_gap(self):
        """[R17] 통지 발송 후 도달 미확인 시 NOTICE_DELIVERY_GAP 및 배달증명서 추천."""
        prop = extract_semantic_proposition("계약해지 통지서를 발송한 날은 2026년 9월 1일이다.")
        prop.event_subtype = "NOTICE_SENT"
        gap = detect_evidence_gap(prop)

        assert gap is not None
        assert gap.gap_type == "NOTICE_DELIVERY_GAP"
        assert any("배달증명" in d for d in gap.recommended_document_types)

    def test_r18_residence_confirmation_gap(self):
        """[R18] 전입신고/대항력 미확인 시 RESIDENCE_CONFIRMATION_GAP 추천."""
        prop = extract_semantic_proposition("전입신고 여부 및 확정일자 부여 사실은 미확인이다.")
        gap = detect_evidence_gap(prop)

        assert gap is not None
        assert gap.gap_type == "RESIDENCE_CONFIRMATION_GAP"

    def test_r19_affirmative_proven_fact_has_no_gap(self):
        """[R19] 직접 처분문서로 입증된 확정 사실은 증거 공백(None)으로 탐지되지 않아야 함."""
        prop = extract_semantic_proposition("보증금은 300,000,000원이다.")
        gap = detect_evidence_gap(prop)
        assert gap is None


# ==============================================================================
# 4. 사실 확정 5대 상태 판정 (R20 ~ R24)
# ==============================================================================

class TestFactAdjudicationStates:
    """FactAdjudication 5대 상태 판정 검증."""

    def test_r20_evidence_supported_status(self):
        """[R20] 처분문서가 뒷받침하는 사실은 EVIDENCE_SUPPORTED 상태."""
        prop = extract_semantic_proposition("임대인은 박정훈이다.")
        assess = evaluate_evidence_reliability("임대차계약서.pdf", prop)
        adj = adjudicate_fact(prop, assessment=assess)

        assert adj.adjudication_status == "EVIDENCE_SUPPORTED"
        assert adj.primary_relation == "SUPPORTS"

    def test_r21_corroborated_status(self):
        """[R21] 복수 증거에 의해 뒷받침되는 사실은 CORROBORATED 상태."""
        prop = extract_semantic_proposition("보증금은 300,000,000원이다.")
        other_props = [extract_semantic_proposition("보증금은 300,000,000원이다.")]
        assess = evaluate_evidence_reliability("계약서.pdf", prop, other_evidence_propositions=other_props)
        assess.corroboration = "FULLY_CORROBORATED"
        adj = adjudicate_fact(prop, assessment=assess)

        assert adj.adjudication_status == "CORROBORATED"

    def test_r22_party_alleged_status(self):
        """[R22] 일방 통지서나 비공식 진술만 있는 사실은 PARTY_ALLEGED 상태."""
        prop = extract_semantic_proposition("구두로 보증금 5천만원 감액에 합의했다고 주장한다.")
        assess = evaluate_evidence_reliability("일방메모.txt", prop)
        adj = adjudicate_fact(prop, assessment=assess)

        assert adj.adjudication_status == "PARTY_ALLEGED"

    def test_r23_evidence_incomplete_status(self):
        """[R23] 인식 미확인(NOT_VERIFIED) 진술은 EVIDENCE_INCOMPLETE 상태."""
        prop = extract_semantic_proposition("보증보험 가입 여부는 확인되지 않았다.")
        adj = adjudicate_fact(prop)

        assert adj.adjudication_status == "EVIDENCE_INCOMPLETE"
        assert adj.primary_relation == "EVIDENCE_GAP"

    def test_r24_genuinely_disputed_status(self):
        """[R24] 동일 계약의 보증금에 대해 직접적인 수치 불일치는 GENUINELY_DISPUTED 상태."""
        prop = extract_semantic_proposition("보증금은 250,000,000원이다.")
        existing_facts = [Fact(id="f1", statement="보증금은 300,000,000원이다.", source_ref="doc-1")]
        adj = adjudicate_fact(prop, candidate_facts=existing_facts)

        assert adj.adjudication_status == "GENUINELY_DISPUTED"
        assert adj.primary_relation == "CONTRADICTS"
        assert "doc-1" in adj.contradicting_evidence_ids


# ==============================================================================
# 5. 리뷰 생명주기 및 DB 영구 저장 정합성 (R25 ~ R28)
# ==============================================================================

class TestReviewLifecycleIntegration:
    """리뷰 액션(APPROVE/EDIT/REJECT) 시 DB 테이블 연계 및 정합성 검증."""

    def test_r25_approve_generates_assessment_adjudication_and_gap(self):
        """[R25] APPROVE 시 EvidenceAssessment, FactAdjudication, EvidenceGap, FactComparisonAudit가 정상 저장됨."""
        db = _create_in_memory_db()
        user = User(id="u-1", email="test@example.com", password_hash="pw")
        case = Case(id="c-1", user_id="u-1", title="임대차 보증금 반환 청구")
        doc = EvidenceDocument(
            id="doc-1",
            case_id="c-1",
            original_filename="주택임대차계약서.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            sha256="hash1",
            safe_storage_key="doc1.pdf",
            status="EXTRACTED",
        )
        claim1 = EvidenceClaim(
            id="cl-1",
            case_id="c-1",
            evidence_id="doc-1",
            statement="보증금은 300,000,000원이다.",
            claim_type="AMOUNT",
            review_status="PENDING",
        )
        claim2 = EvidenceClaim(
            id="cl-2",
            case_id="c-1",
            evidence_id="doc-1",
            statement="전세보증금 반환보증보험 가입 여부는 확인되지 않았다.",
            claim_type="CONDITION",
            review_status="PENDING",
        )
        db.add_all([user, case, doc, claim1, claim2])
        db.commit()

        # 1. claim1 승인
        process_evidence_review(db, claim_id="cl-1", action="APPROVE")

        # EvidenceAssessment 확인
        assess1 = db.query(EvidenceAssessment).filter_by(claim_id="cl-1").first()
        assert assess1 is not None
        assert assess1.source_authenticity == "BILATERAL_SIGNED"
        assert assess1.assessment_status == "CONCLUSIVE"

        # FactAdjudication 확인
        adj1 = db.query(FactAdjudication).filter_by(claim_id="cl-1").first()
        assert adj1 is not None
        assert adj1.adjudication_status == "EVIDENCE_SUPPORTED"

        # 2. claim2 승인 (미확인 정보)
        process_evidence_review(db, claim_id="cl-2", action="APPROVE")

        adj2 = db.query(FactAdjudication).filter_by(claim_id="cl-2").first()
        assert adj2 is not None
        assert adj2.adjudication_status == "EVIDENCE_INCOMPLETE"
        assert adj2.primary_relation == "EVIDENCE_GAP"

        # EvidenceGap 확인
        gap2 = db.query(EvidenceGap).filter_by(claim_id="cl-2").first()
        assert gap2 is not None
        assert gap2.gap_type == "HUG_INSURANCE_CONFIRMATION_GAP"
        assert "HUG 전세보증금 반환보증 증권" in gap2.recommended_document_types

        # FactComparisonAudit 확인
        audits = db.query(FactComparisonAudit).filter_by(claim_id="cl-2").all()
        assert len(audits) >= 1
        assert not audits[0].is_comparable

    def test_r26_edit_action_re_adjudicates_and_updates_audit(self):
        """[R26] EDIT 액션 시 기존 평가 및 심리 결과가 갱신되고 새로운 문장 기준으로 재평가됨."""
        db = _create_in_memory_db()
        user = User(id="u-1", email="test@example.com", password_hash="pw")
        case = Case(id="c-1", user_id="u-1", title="임대차 보증금 반환 청구")
        doc = EvidenceDocument(
            id="doc-1",
            case_id="c-1",
            original_filename="계약서.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            sha256="hash1",
            safe_storage_key="test_storage.pdf",
            status="EXTRACTED",
        )
        claim = EvidenceClaim(
            id="cl-1",
            case_id="c-1",
            evidence_id="doc-1",
            statement="보증금은 2억이다.",
            claim_type="AMOUNT",
            review_status="PENDING",
        )
        db.add_all([user, case, doc, claim])
        db.commit()

        # 수정 승인: 2억 -> 3억원
        process_evidence_review(
            db,
            claim_id="cl-1",
            action="EDIT",
            new_statement="보증금은 300,000,000원이다.",
        )

        claim_updated = db.query(EvidenceClaim).filter_by(id="cl-1").first()
        assert claim_updated.review_status == "EDITED"
        assert claim_updated.statement == "보증금은 300,000,000원이다."

        fact = db.query(Fact).filter_by(case_id="c-1").first()
        assert fact is not None
        assert fact.statement == "보증금은 300,000,000원이다."

        adj = db.query(FactAdjudication).filter_by(claim_id="cl-1").first()
        assert adj is not None
        assert adj.adjudication_status == "EVIDENCE_SUPPORTED"

    def test_r27_reject_cleans_up_adjudication_and_assessment(self):
        """[R27] REJECT 시 관련된 EvidenceAssessment 및 FactAdjudication이 깨끗하게 정리됨."""
        db = _create_in_memory_db()
        user = User(id="u-1", email="test@example.com", password_hash="pw")
        case = Case(id="c-1", user_id="u-1", title="임대차 사건")
        doc = EvidenceDocument(
            id="doc-1",
            case_id="c-1",
            original_filename="계약서.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            sha256="hash1",
            safe_storage_key="test_storage.pdf",
            status="EXTRACTED",
        )
        claim = EvidenceClaim(
            id="cl-1",
            case_id="c-1",
            evidence_id="doc-1",
            statement="보증금은 300,000,000원이다.",
            claim_type="AMOUNT",
            review_status="PENDING",
        )
        db.add_all([user, case, doc, claim])
        db.commit()

        process_evidence_review(db, claim_id="cl-1", action="APPROVE")
        assert db.query(FactAdjudication).filter_by(claim_id="cl-1").count() == 1

        # 반려(REJECT) 수행
        process_evidence_review(db, claim_id="cl-1", action="REJECT")
        assert db.query(FactAdjudication).filter_by(claim_id="cl-1").count() == 0
        assert db.query(EvidenceAssessment).filter_by(claim_id="cl-1").count() == 0

    def test_r28_dispositive_contract_resists_wrongful_dispute(self):
        """[R28] 처분문서로 확정된 사실은 무관한 정보 부족(미확인 메모) 승인 시에도 DISPUTED로 오염되지 않음."""
        db = _create_in_memory_db()
        user = User(id="u-1", email="test@example.com", password_hash="pw")
        case = Case(id="c-1", user_id="u-1", title="임대차 사건")
        doc = EvidenceDocument(
            id="doc-1",
            case_id="c-1",
            original_filename="계약서.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            sha256="hash1",
            safe_storage_key="test_storage.pdf",
            status="EXTRACTED",
        )
        claim_contract = EvidenceClaim(
            id="cl-tenant",
            case_id="c-1",
            evidence_id="doc-1",
            statement="임차인은 이수현이다.",
            claim_type="PARTY",
            review_status="PENDING",
        )
        claim_memo = EvidenceClaim(
            id="cl-hug",
            case_id="c-1",
            evidence_id="doc-1",
            statement="전세보증금 반환보증보험 가입 여부는 확인되지 않았다.",
            claim_type="CONDITION",
            review_status="PENDING",
        )
        db.add_all([user, case, doc, claim_contract, claim_memo])
        db.commit()

        # 1. 계약서 임차인 신원 승인
        process_evidence_review(db, claim_id="cl-tenant", action="APPROVE")
        fact_tenant = db.query(Fact).filter(Fact.statement.contains("이수현")).first()
        assert fact_tenant is not None
        assert fact_tenant.verification_status != "DISPUTED"

        # 2. 보증보험 미확인 메모 승인
        process_evidence_review(db, claim_id="cl-hug", action="APPROVE")
        db.refresh(fact_tenant)

        # 계약서로 확정된 임차인 신원은 DISPUTED가 되지 않고 정상 상태를 확고히 유지해야 함
        assert fact_tenant.verification_status != "DISPUTED"
        assert fact_tenant.verification_status in ("DOCUMENT_VERIFIED", "VERIFIED")
