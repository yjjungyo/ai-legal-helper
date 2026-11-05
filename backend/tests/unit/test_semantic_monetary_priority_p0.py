"""Regression counterexamples for amount roles, Korean KRW, priority, and speech-act links."""
from unittest.mock import patch

import pytest

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing, FactItemBrief
from ai_legal_helper.case_intelligence.conflict_detector import (
    _are_amount_roles_compatible,
    build_structured_slots,
    evaluate_claim_against_fact,
)
from ai_legal_helper.case_intelligence.fact_semantics import (
    ComparabilityResult, SemanticProposition, check_proposition_comparability,
)
from ai_legal_helper.case_intelligence.semantic_judgment import SemanticDecision
from ai_legal_helper.case_intelligence.settlement_calculator import (
    evaluate_attachment_ranking,
    extract_amounts_from_text,
    extract_case_prior_verified_repayments,
)
from ai_legal_helper.database.models import Fact


@pytest.mark.parametrize("left,right,equal", [
    ("GENERAL_AMOUNT", "GENERAL_AMOUNT", False),
    ("GENERAL_AMOUNT", "GENERAL_AMOUNT", True),
    ("GENERAL_AMOUNT", "PRINCIPAL_DEPOSIT", False),
    ("PRINCIPAL_DEPOSIT", "GENERAL_AMOUNT", True),
])
def test_unattributed_amounts_are_not_same_semantic_role(left, right, equal):
    assert not _are_amount_roles_compatible(left, right, equal)


def test_unknown_amount_roles_cannot_produce_false_contradiction_or_support():
    with patch(
        "ai_legal_helper.case_intelligence.semantic_judgment.classify_statement",
        return_value=SemanticDecision("UNKNOWN", "", status="UNCONFIRMED"),
    ), patch(
        "ai_legal_helper.case_intelligence.conflict_detector.compare_fact_identity",
        return_value=ComparabilityResult(
            is_comparable=True, status="COMPARABLE", reason_code="TEST_SAME_CONTEXT",
            explanation="Force stage-2 amount comparison to exercise unknown-role guard",
        ),
    ), patch(
        "ai_legal_helper.case_intelligence.conflict_detector._find_shared_concepts",
        return_value={"금액"},
    ):
        candidate = build_structured_slots("영수증에는 비용 20만 원이 기재되었다.", claim_type="AMOUNT")
        fact = Fact(
            id="f1", statement="계약서에는 비용 3억 원이 기재되었다.",
            fact_type="AMOUNT", verification_status="DOCUMENT_VERIFIED",
        )
        decision = evaluate_claim_against_fact(
            candidate, fact, enable_llm_verification=False,
        )
    assert decision.status == "INSUFFICIENT_INFORMATION"
    assert decision.reason_code == "AMOUNT_ROLE_UNCONFIRMED"


@pytest.mark.parametrize("statement,expected", [
    ("보증금 삼억 원", {300_000_000}),
    ("금 삼억 원정", {300_000_000}),
    ("3억 2천 5백만원", {325_000_000}),
    ("삼억오천만원", {350_000_000}),
    ("2026.09.10 5천만 원", {50_000_000}),
    ("2024년 5월 2일 보증금 삼억 원", {300_000_000}),
    ("3억 2천만원", {320_000_000}),
    ("보증금 3억 원 중 5천만 원을 반환받았습니다.", {300_000_000, 50_000_000}),
])
def test_compound_and_korean_written_money(statement, expected):
    assert extract_amounts_from_text(statement) == expected


def test_multiple_amount_quote_can_resolve_actual_refund_without_min_max():
    statement = "보증금 3억 원 중 5천만 원을 반환받았습니다."
    briefing = CaseEvidenceBriefing(
        case_id="refund", title="실제 증빙으로 확인된 일부 반환",
        facts=[
            FactItemBrief(
                fact_id="f-refund", statement=statement,
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="은행거래원본.pdf",
            ),
        ],
    )

    def review(stmt, *, task, **kwargs):
        assert stmt == statement
        if task == "ACTUAL_DEPOSIT_REFUND_TRANSACTION":
            return SemanticDecision("ACTUAL_REPAYMENT", statement)
        if task == "SELECT_ACTUAL_REPAYMENT_AMOUNT":
            return SemanticDecision("ACTUAL_REPAYMENT", "5천만 원을 반환받았습니다")
        return SemanticDecision("UNKNOWN", "", status="UNCONFIRMED")

    with patch(
        "ai_legal_helper.case_intelligence.semantic_judgment.classify_statement",
        side_effect=review,
    ):
        total, provenance = extract_case_prior_verified_repayments(briefing)
    assert total == 50_000_000
    assert any("은행거래원본.pdf" in x for x in provenance)


def test_ambiguous_refund_quote_without_source_grounded_amount_is_not_guessed():
    statement = "보증금 3억 원 중 5천만 원을 반환받았습니다."
    briefing = CaseEvidenceBriefing(
        case_id="ambiguous", title="반환 대상 미확인",
        facts=[FactItemBrief(
            fact_id="f", statement=statement,
            adjudication_status="EVIDENCE_SUPPORTED",
        )],
    )
    with patch(
        "ai_legal_helper.case_intelligence.semantic_judgment.classify_statement",
        side_effect=lambda stmt, *, task, **kwargs: (
            SemanticDecision("ACTUAL_REPAYMENT", statement)
            if task == "ACTUAL_DEPOSIT_REFUND_TRANSACTION"
            else SemanticDecision("UNKNOWN", "", status="UNCONFIRMED")
        ),
    ):
        total, _ = extract_case_prior_verified_repayments(briefing)
    assert total == 0  # Unknown amount must be annotated as unconfirmed, never inferred.


def _priority_briefing(fixed_date: str) -> CaseEvidenceBriefing:
    facts = [
        FactItemBrief(
            fact_id="occupancy",
            statement="임차인은 2024년 5월 1일 주택을 인도받고 주민등록 전입신고를 마쳤다.",
            adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01",
        ),
        FactItemBrief(
            fact_id="fixed",
            statement=f"임차인은 {fixed_date} 확정일자를 받았다.",
            adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E01",
        ),
        FactItemBrief(
            fact_id="attachment",
            statement="2024년 5월 2일 은행의 가압류 등기가 경료되었다.",
            adjudication_status="EVIDENCE_SUPPORTED", evidence_label="E09",
        ),
    ]
    return CaseEvidenceBriefing(
        case_id="tie", title="대항력 익일 발생과 권리등기",
        facts=facts, source_registry={
            "E01": {"document_name": "임대차계약서_및_초본.pdf"},
            "E09": {"document_name": "등기사항전부증명서.pdf"},
        },
    )


def test_priority_arises_before_registered_right_on_same_calendar_day():
    ranking = evaluate_attachment_ranking(_priority_briefing("2024년 5월 1일"))
    assert ranking["tenant_opposing_date"] == "2024.05.01"
    assert ranking["tenant_opposing_effective_date"] == "2024.05.02"
    assert ranking["tenant_priority_date"] == "2024.05.02"
    assert ranking["priority_status"] == "TENANT_SENIOR"


def test_fixed_date_on_same_day_as_attachment_stays_uncertain():
    ranking = evaluate_attachment_ranking(_priority_briefing("2024년 5월 2일"))
    assert ranking["tenant_opposing_effective_date"] == "2024.05.02"
    assert ranking["tenant_priority_date"] == "2024.05.02"
    assert ranking["priority_status"] == "UNCERTAIN"


def test_proposal_and_rejection_not_a_supporting_evidence_relation():
    left = SemanticProposition(
        statement="임대인이 분할반환 제안", speech_act="PROPOSAL",
        event_type="PAYMENT",
    )
    right = SemanticProposition(
        statement="임차인이 그 제안을 거절", speech_act="REJECTION",
        event_type="PAYMENT",
    )
    comparison = check_proposition_comparability(left, right)
    assert comparison.is_comparable is False
    assert comparison.status == "DIFFERENT_CONTEXT"
    assert comparison.reason_code == "PROPOSAL_VS_REJECTION"



def test_one_batch_model_call_for_three_amounts_and_two_dates():
    statement = (
        "2024년 5월 1일 계약 시 원금 3억 원, "
        "2024년 5월 2일 계약금 3천만 원과 잔금 2억 7천만 원을 기록했다."
    )
    calls = []

    def reviewed_batch(text, *, spans, labels_by_kind):
        calls.append((text, spans))
        assert sum(x["kind"] == "AMOUNT" for x in spans) == 3
        assert sum(x["kind"] == "DATE" for x in spans) == 2
        result = {}
        for item in spans:
            token = text[item["start"]:item["end"]]
            if item["kind"] == "DATE":
                result[item["id"]] = "CONTRACT_DATE"
            elif "3천만" in token:
                result[item["id"]] = "DOWN_PAYMENT"
            elif "2억 7천만" in token:
                result[item["id"]] = "INTERIM_OR_BALANCE"
            else:
                result[item["id"]] = "PRINCIPAL_DEPOSIT"
        return result

    with patch(
        "ai_legal_helper.case_intelligence.semantic_judgment.classify_numeric_spans",
        side_effect=reviewed_batch,
    ):
        slots = build_structured_slots(statement, claim_type="AMOUNT_AND_DATE")

    assert len(calls) == 1
    assert slots.amount_roles["PRINCIPAL_DEPOSIT"] == [300_000_000]
    assert slots.amount_roles["DOWN_PAYMENT"] == [30_000_000]
    assert slots.amount_roles["INTERIM_OR_BALANCE"] == [270_000_000]
    assert len(slots.date_roles["CONTRACT_DATE"]) == 2


def test_batch_rejects_quote_grounded_in_wrong_identical_amount_occurrence():
    from ai_legal_helper.case_intelligence.semantic_judgment import classify_numeric_spans

    sentence = "원금 5천만 원, 반환액 5천만 원"
    token = "5천만 원"
    first = sentence.index(token)
    second = sentence.rindex(token)
    invocations = []

    def one_response(prompt):
        invocations.append(prompt)
        return {
            "items": [
                # Wrong: this is the SECOND occurrence, not the first.
                {"id": "a0", "role": "PRINCIPAL_DEPOSIT",
                 "evidence_quote": "반환액 5천만 원"},
                {"id": "a1", "role": "RETURNED_AMOUNT",
                 "evidence_quote": "반환액 5천만 원"},
            ]
        }

    decisions = classify_numeric_spans(
        sentence,
        spans=[
            {"id": "a0", "kind": "AMOUNT", "start": first, "end": first + len(token)},
            {"id": "a1", "kind": "AMOUNT", "start": second, "end": second + len(token)},
        ],
        labels_by_kind={"AMOUNT": ("PRINCIPAL_DEPOSIT", "RETURNED_AMOUNT")},
        invoke_fn=one_response,
    )
    assert len(invocations) == 1
    assert "a0" not in decisions
    assert decisions["a1"] == "RETURNED_AMOUNT"



def test_reconcile_removes_legacy_false_support_but_keeps_claim_own_provenance():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from ai_legal_helper.database.models import (
        Base, User, Case, EvidenceClaim, EvidenceDocument, EvidenceLink, Fact,
    )
    from ai_legal_helper.case_intelligence.conflict_detector import (
        reconcile_case_conflicts,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        db.add_all([
            User(id="repair-user", email="repair@test.invalid", password_hash="test"),
            Case(id="repair-case", user_id="repair-user", title="오류 관계 복구"),
            EvidenceDocument(
                id="doc-proposal", case_id="repair-case", original_filename="임대인제안.txt",
                media_type="text/plain", size_bytes=50, sha256="h-proposal",
                safe_storage_key="p.txt", status="APPROVED",
            ),
            EvidenceDocument(
                id="doc-refusal", case_id="repair-case", original_filename="임차인거절.txt",
                media_type="text/plain", size_bytes=50, sha256="h-refusal",
                safe_storage_key="r.txt", status="APPROVED",
            ),
        ])
        db.flush()
        db.add_all([
            Fact(
                id="fact-proposal", case_id="repair-case",
                statement="임대인은 분할 상환을 제안하였다.",
                fact_type="ACTION", source_ref="doc-proposal",
                verification_status="DOCUMENT_VERIFIED",
            ),
            Fact(
                id="fact-refusal", case_id="repair-case",
                statement="임차인은 분할 상환을 거절하였다.",
                fact_type="ACTION", source_ref="doc-refusal",
                verification_status="DOCUMENT_VERIFIED",
            ),
            EvidenceClaim(
                id="claim-refusal", case_id="repair-case",
                evidence_id="doc-refusal",
                statement="임차인은 분할 상환을 거절하였다.",
                claim_type="ACTION", assertion_status="DOCUMENT_STATES",
                review_status="APPROVED", confidence=0.9,
            ),
        ])
        db.flush()
        db.add_all([
            EvidenceLink(
                id="false-cross-support", evidence_id="doc-refusal",
                claim_id="claim-refusal", target_type="FACT",
                target_id="fact-proposal", link_type="SUPPORTS",
            ),
            EvidenceLink(
                id="own-provenance", evidence_id="doc-refusal",
                claim_id="claim-refusal", target_type="FACT",
                target_id="fact-refusal", link_type="SUPPORTS",
            ),
        ])
        db.commit()

        def speech_act(stmt, *, task, **kwargs):
            if task == "SPEECH_ACT_AND_EXECUTION_STATUS":
                return SemanticDecision(
                    "REJECTION" if "거절" in stmt else "PROPOSAL", stmt,
                )
            return SemanticDecision("UNKNOWN", "", status="UNCONFIRMED")

        with patch(
            "ai_legal_helper.case_intelligence.semantic_judgment.classify_statement",
            side_effect=speech_act,
        ):
            dry = reconcile_case_conflicts(
                db, case_id="repair-case", dry_run=True, sync_neo4j=False,
            )
            assert dry["removed_false_support_links"] == 1
            assert db.query(EvidenceLink).filter_by(id="false-cross-support").count() == 1

            live = reconcile_case_conflicts(
                db, case_id="repair-case", dry_run=False, sync_neo4j=False,
            )
            assert live["removed_false_support_links"] == 1

        assert db.query(EvidenceLink).filter_by(id="false-cross-support").count() == 0
        assert db.query(EvidenceLink).filter_by(id="own-provenance").count() == 1
    finally:
        db.close()
        engine.dispose()
