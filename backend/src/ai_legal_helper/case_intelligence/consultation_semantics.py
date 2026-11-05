"""Legal consultation intents and event assertions, interpreted semantically.

These functions intentionally distinguish a user's statement from verified
case evidence. Model disagreement/failure is UNKNOWN, never a repayment fact.
"""
from __future__ import annotations

from ai_legal_helper.case_intelligence.semantic_judgment import classify_statement


def _consultation_intent(question: str) -> str:
    return classify_statement(
        question,
        task="CONSULTATION_INTENT_AND_REPAYMENT_ASSERTION",
        labels=("REPAYMENT_ASSERTED", "EVIDENCE_REVIEW", "OTHER"),
        context=(
            "REPAYMENT_ASSERTED: 사용자가 실제로 보증금/채무의 일부 또는 전액을 "
            "돌려받았다고 현재 사건의 발생 사실로 진술함(증명되었다는 뜻은 아님). "
            "EVIDENCE_REVIEW: 새 반환 사실 진술 없이 기등록 자료나 문서의 분석을 요청함. "
            "OTHER: 그 외 질의. 반환 제안, 계획, 질문, 예상, 상대방 주장, 부정 표현은 "
            "REPAYMENT_ASSERTED가 아님."
        ),
    ).label


def has_repayment_assertion(question: str) -> bool:
    """True only when the current user explicitly asserts actual receipt.

    Never infer confirmed payment from a query keyword or rewritten question.
    """
    return _consultation_intent(question) == "REPAYMENT_ASSERTED"


def is_evidence_review_request(question: str) -> bool:
    """Distinguish a document review from a new transaction assertion."""
    return _consultation_intent(question) == "EVIDENCE_REVIEW"


def is_conditional_contract_statement(statement: str) -> bool:
    """Does the text merely state duties, conditions, prospects or plans?

    No rule may assert that an actual termination happened based on wording.
    An UNKNOWN result is treated as conditional by high-stakes verifiers.
    """
    result = classify_statement(
        statement,
        task="CONTRACT_TERMINATION_OCCURRENCE",
        labels=("CONDITIONAL_OR_PLANNED", "ACTUAL_TERMINATION", "OTHER"),
        context=(
            "CONDITIONAL_OR_PLANNED: 계약 조항, 의무, 가정, 예정 또는 종료 여부 미확인. "
            "ACTUAL_TERMINATION: 실제 특정 계약 종료 행위/효과가 발생했다는 "
            "진술임. 단순 만기일 기재나 예상은 해당하지 않음. "
            "OTHER: 계약 종료와 무관. 근거가 모호하면 UNKNOWN."
        ),
    )
    return result.label in ("CONDITIONAL_OR_PLANNED", "UNKNOWN")
