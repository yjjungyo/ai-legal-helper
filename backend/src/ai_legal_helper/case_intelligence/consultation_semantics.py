"""Legal consultation intents and event assertions, interpreted semantically.

These functions intentionally distinguish a user's statement from verified
case evidence. Model disagreement/failure is UNKNOWN, never a repayment fact.
"""
from __future__ import annotations

from ai_legal_helper.case_intelligence import semantic_judgment


def _consultation_intent(question: str) -> str:
    return semantic_judgment.classify_statement(
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
    """Distinguish a document review from a new transaction assertion.

    A narrowly recognized, explicit UI action (request to inspect registered
    materials) is safe without legal/factual inference. It never confirms
    that any payment or termination occurred.
    """
    q = (question or "").strip()
    if (any(term in q for term in ("등록된", "제출된", "계약서와", "증거자료", "이체 자료"))
            and any(term in q for term in ("분석", "검토", "정리", "확인해", "대조"))):
        return True
    return _consultation_intent(q) == "EVIDENCE_REVIEW"


def termination_statement_status(statement: str) -> str:
    """ACTUAL_TERMINATION, CONDITIONAL_OR_PLANNED, OTHER or UNKNOWN."""
    stmt = (statement or "").strip()
    if not stmt:
        return "OTHER"

    # [Fast-Path] 종료/해지/퇴거 관련 핵심 키워드가 전혀 없으면 LLM 분류 스킵 (성능 최적화)
    _TERMINATION_KEYWORDS = ("종료", "해지", "퇴거", "만료", "인도완료", "명도", "해제", "이사", "비웠", "방을 뺐")
    if not any(k in stmt for k in _TERMINATION_KEYWORDS):
        return "OTHER"

    result = semantic_judgment.classify_statement(
        statement,
        task="CONTRACT_TERMINATION_OCCURRENCE",
        labels=("CONDITIONAL_OR_PLANNED", "ACTUAL_TERMINATION", "OTHER"),
        context=(
            "CONDITIONAL_OR_PLANNED: 계약 조항, 의무, 가정, 예정 또는 종료 여부 미확인. "
            "ACTUAL_TERMINATION: 특정 계약 종료 사실이 실제 발생했음을 진술함. "
            "단순 만기일 기재, 통지 발송, 도달 여부 미확인 및 예상은 해당하지 않음. "
            "OTHER: 종료와 무관. 사건 주체·계약·시점이 모호하면 UNKNOWN."
        ),
    )
    return result.label


def is_conditional_contract_statement(statement: str) -> bool:
    """Anything not positively interpreted as actual is conditional for safety."""
    return termination_statement_status(statement) != "ACTUAL_TERMINATION"
