# -*- coding: utf-8 -*-
"""상담 사례의 다섯 발언 쌍 오탐 및 진짜 상충 회귀 테스트.

문자에 공통으로 '보증금 반환'이 등장하더라도 화행(문의/제안/거절/계획)이
다르면 사실의 논리적 충돌이 아니다. 순서를 뒤집어도 결과는 같아야 한다.
"""
import pytest
from ai_legal_helper.case_intelligence.semantic_judgment import SemanticDecision
from ai_legal_helper.case_intelligence.conflict_detector import _LLMConflictVerificationSchema

from ai_legal_helper.case_intelligence.fact_semantics import (
    extract_semantic_proposition, compare_fact_identity, extract_semantic_fact,
)
from ai_legal_helper.case_intelligence.conflict_detector import (
    build_structured_slots, evaluate_claim_against_fact,
)
from ai_legal_helper.database.models import Fact


ASK = "이수현은 2026년 9월 30일 보증금 반환 일정이 가능한지 문의하였다."
NEW_TENANT = "박정훈은 보증금 반환 확답 대신 새 세입자 구하는 절차를 먼저 진행하겠다는 입장을 밝혔다."
PROPOSE = "박정훈은 보증금을 일시에 전액 반환하지 않고 분할 반환하는 방안을 제안하였다."
REJECT = "이수현은 분할 반환에 동의할 수 없다고 밝혔다."
ALTERNATIVE = "박정훈은 보증금 반환을 위한 다른 방법을 찾겠다는 입장을 밝혔다."

# These examples previously depended on hardcoded wording regex. The test now
# injects the semantic model's exact ground-truth outputs, keeping all original
# scenario expectations without requiring a live model/network on CI.
@pytest.fixture(autouse=True)
def stub_reviewed_semantics(monkeypatch):
    speech_acts = {
        ASK: "QUESTION",
        NEW_TENANT: "PLAN",
        PROPOSE: "PROPOSAL",
        REJECT: "REJECTION",
        ALTERNATIVE: "PLAN",
    }
    def fake_classifier(statement, *, task, **kwargs):
        if task == "SPEECH_ACT_AND_EXECUTION_STATUS":
            if statement in speech_acts:
                return SemanticDecision(speech_acts[statement], statement)
            return SemanticDecision("STATEMENT", statement)
        if task == "MONEY_AMOUNT_SEMANTIC_ROLE":
            if statement in (
                "보증금은 2억 원이다.", "보증금은 3억 원이다.",
            ):
                return SemanticDecision("PRINCIPAL_DEPOSIT", statement)
        return SemanticDecision("UNKNOWN", "", status="UNCONFIRMED")

    def fake_conflict_review(claim_slots, fact_slots):
        pair = {claim_slots.statement, fact_slots.statement}
        actual = {
            "보증금은 2억 원이다.", "보증금은 3억 원이다.",
        }
        opposite = {
            "임대인은 2024년 2월 28일에 보증금을 반환하지 않았다.",
            "임대인은 2024년 2월 28일에 보증금을 전액 반환하였다.",
        }
        if pair in (actual, opposite):
            return _LLMConflictVerificationSchema(
                status="CONTRADICTION",
                reason_code="MUTUALLY_EXCLUSIVE_AMOUNT" if pair == actual
                else "DIRECT_POLARITY_CONFLICT",
                explanation="동일 사건·금액 또는 동일 시점의 지급/미지급이 양립 불가",
                confidence=0.99,
            )
        return None

    monkeypatch.setattr(
        "ai_legal_helper.case_intelligence.semantic_judgment.classify_statement",
        fake_classifier,
    )
    monkeypatch.setattr(
        "ai_legal_helper.case_intelligence.conflict_detector._verify_pair_with_llm",
        fake_conflict_review,
    )


FALSE_CONTRADICTIONS = [
    (ASK, PROPOSE),
    (NEW_TENANT, PROPOSE),
    (ASK, REJECT),
    (NEW_TENANT, REJECT),
    (PROPOSE, ALTERNATIVE),
]


@pytest.mark.parametrize("left,right", FALSE_CONTRADICTIONS)
def test_five_reported_false_contradictions_in_both_directions(left, right):
    for fact_text, claim_text in ((left, right), (right, left)):
        slots = build_structured_slots(statement=claim_text, claim_type="ACTION")
        fact = Fact(id="fact-dialogue", statement=fact_text, fact_type="ACTION")
        decision = evaluate_claim_against_fact(
            claim_slots=slots, fact=fact, enable_llm_verification=False,
        )
        assert decision.status == "DIFFERENT_CONTEXT", (
            fact_text, claim_text, decision.status, decision.reason_code, decision.explanation
        )
        assert decision.reason_code == "DISTINCT_SPEECH_ACTS"


def test_speech_act_is_not_lost_through_legacy_semantic_fact_path():
    expectations = [
        (ASK, "QUESTION"),
        (PROPOSE, "PROPOSAL"),
        (REJECT, "REJECTION"),
        (NEW_TENANT, "PLAN"),
        (ALTERNATIVE, "PLAN"),
    ]
    for statement, expected in expectations:
        direct = extract_semantic_proposition(statement)
        legacy_path = extract_semantic_fact(statement).to_proposition()
        # to_proposition() 자체는 레거시용, 비교 API는 화행 보강을 수행한다.
        assert direct.speech_act == expected
        assert isinstance(legacy_path.speech_act, str)

    decision = compare_fact_identity(
        extract_semantic_fact(PROPOSE), extract_semantic_fact(REJECT),
    )
    assert decision.status == "CONSISTENT"
    assert decision.reason_code == "PROPOSAL_VS_REJECTION"


@pytest.mark.parametrize("claim,fact", [
    ("보증금은 2억 원이다.", "보증금은 3억 원이다."),
    ("임대인은 2024년 2월 28일에 보증금을 반환하지 않았다.",
     "임대인은 2024년 2월 28일에 보증금을 전액 반환하였다."),
])
def test_actual_amount_and_payment_contradictions_remain(claim, fact):
    decision = evaluate_claim_against_fact(
        build_structured_slots(claim, claim_type="AMOUNT"),
        Fact(id="real", statement=fact, fact_type="AMOUNT"),
        enable_llm_verification=True,
    )
    assert decision.status == "CONTRADICTION", (decision.status, decision.reason_code)


def test_installment_offer_and_inability_report_keeps_previous_regression():
    other = "박정훈은 보증금 3억 원을 즉시 반환하기 어렵다는 취지로 말했다."
    decision = evaluate_claim_against_fact(
        build_structured_slots(other, claim_type="ACTION"),
        Fact(id="compat", statement=PROPOSE, fact_type="ACTION"),
        enable_llm_verification=False,
    )
    assert decision.status == "DIFFERENT_CONTEXT"
    assert decision.reason_code == "PAYMENT_PROPOSAL_VS_CAPACITY_STATEMENT"
