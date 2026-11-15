# -*- coding: utf-8 -*-
"""검증기 판례 검색 요청 누락 보완 단위 테스트 모듈.

[역할]
검증 LLM이 missing_issues나 missing_legal_issues에 '판례 근거 부재' 또는 '성질상 불가분채무/분할채무 직접 법리 부재'를
명시했음에도 불구하고, legal_search_requests를 빈 배열로 반환하거나 STATUTE 단독으로 요청하는 누락을
_supplement_precedent_search_requests가 안전하고 결정론적으로 보완하는지 검증한다.
"""
import pytest
from ai_legal_helper.agents.verification import VerificationOutput, _supplement_precedent_search_requests


def test_supplement_precedent_search_requests_when_missing_issues_has_precedent_gap():
    """missing_issues에 판례 부재가 명시되고 legal_search_requests가 비어 있을 때 PRECEDENT 검색 요청을 보완한다."""
    res = VerificationOutput(
        status="REVISE",
        reason_code="ANSWER_REVISION_REQUIRED",
        missing_issues=[
            "상속인들이 임차인에 대하여 보증금 반환채무 전액에 대해 연대·공동으로 책임지는지, 아니면 각 상속분에 따른 분할채무인지에 관한 직접 법리 또는 판례 근거가 현재 출처 목록에 없다."
        ],
        missing_legal_issues=[],
        legal_search_requests=[],
        claims=[],
    )
    question = (
        "장남은 소송 핑계로 지급을 거부하고, 차남은 자기 법정지분(1/3)인 8,333만 원만 주겠다고 합니다. "
        "계약만료일에 이사를 가야 하는데 어떻게 법적 조치를 취해야 하나요?"
    )

    _supplement_precedent_search_requests(res, question=question)

    assert len(res.legal_search_requests) == 1
    req = res.legal_search_requests[0]
    assert req["source_type"] == "PRECEDENT"
    assert req["question_part"] == question
    assert "상속인" in req["precedent_query"] or "보증금" in req["precedent_query"]
    assert res.reason_code == "LEGAL_SOURCE_INSUFFICIENT"
    assert res.recommended_action == "REQUEST_STATUTE_SEARCH_APPROVAL"


def test_supplement_precedent_search_requests_expands_statute_to_both():
    """기존 STATUTE 요청 쟁점에 판례/불가분/분할채무 등 법리 키워드가 포함된 경우 BOTH로 확장하고 precedent_query를 추가한다."""
    res = VerificationOutput(
        status="INSUFFICIENT",
        reason_code="LEGAL_SOURCE_MISSING",
        missing_issues=[],
        missing_legal_issues=["공동상속인 보증금 반환채무"],
        legal_search_requests=[
            {
                "law_name": "민법",
                "issue": "임대인 사망 후 승계된 보증금 반환채무가 공동상속인에게 분할귀속되는지, 연대 또는 불가분채무로 전액 청구 가능한지 판단",
                "question_part": "보증금 반환 채무는 지분대로 나눠서 청구해야 하나요, 아니면 누구에게나 전액 청구할 수 있나요?",
                "articles": ["제1005조"],
                "source_type": "STATUTE",
            }
        ],
        claims=[],
    )
    question = "보증금 반환 채무는 지분대로 나눠서 청구해야 하나요, 아니면 누구에게나 전액 청구할 수 있나요?"

    _supplement_precedent_search_requests(res, question=question)

    assert len(res.legal_search_requests) == 1
    req = res.legal_search_requests[0]
    assert req["source_type"] == "BOTH"
    assert req.get("precedent_query")
    assert "보증금" in req["precedent_query"] or "임대인" in req["precedent_query"]


def test_supplement_precedent_search_requests_no_op_on_pass():
    """검증 판정이 PASS인 경우 검색 요청을 임의로 추가하지 않는다."""
    res = VerificationOutput(
        status="PASS",
        reason_code="NONE",
        missing_issues=["참고 확인사항: 관할 법원 확인"],
        missing_legal_issues=[],
        legal_search_requests=[],
        claims=[],
    )

    _supplement_precedent_search_requests(res, question="테스트 질문")

    assert len(res.legal_search_requests) == 0
    assert res.status == "PASS"
    assert res.reason_code == "NONE"
