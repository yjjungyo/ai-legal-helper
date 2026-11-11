# -*- coding: utf-8 -*-
"""
테스트 모듈: test_conversation_context_diet.py

[테스트 목적]
1. 연속 상담(Multi-turn) 대화 맥락 복원 시, 이전 턴의 수천 자에 달하는 AI 답변 전문을
   무차별 주입하지 않고 규칙 기반(0.001초, LLM 0회)으로 핵심 결론(150~250자)만 정제 추출하는지 검증한다.
2. `extract_answer_conclusion` 함수가 표준 4단계 의견서에서 `[1. 핵심 결론]` 섹션을 정확히 발췌하는지 검증한다.
3. `to_chat_history_messages`가 `AIMessage`를 생성할 때 장문 전문 대신 핵심 결론 요약문만 담는지 검증한다.
4. `format_context_for_prompt`가 컴팩트한 요약 맥락만 제공하여 토큰 낭비와 과거 답변 환각 전파를 차단하는지 검증한다.
"""
from typing import List
import pytest
from langchain_core.messages import HumanMessage, AIMessage

from ai_legal_helper.workflows.conversation_context import (
    ConversationTurn,
    ConversationContext,
    extract_answer_conclusion,
    build_conversation_summary,
)


def test_extract_answer_conclusion_structured_opinion():
    """표준 4단계 의견서에서 [1. 핵심 결론] 섹션만 정확히 250자 이내로 발췌하는지 테스트."""
    long_answer = """[1. 핵심 결론]
- 의뢰인의 임대차계약은 2024년 8월 묵시적 갱신 후 해지 통보에 따라 적법하게 종료되었습니다.
- 임차권등기명령을 마친 후 주택을 인도하고 전세보증금 반환청구소송을 제기할 수 있습니다.
- 지연손해금은 소장 송달 다음날부터 연 12%의 법정이율이 적용됩니다.

[2. 지금 해야 할 일]
1. 관할 법원에 임차권등기명령을 신청하세요.
2. 등기 완료 전까지는 절대 이사를 가거나 주민등록을 빼지 마세요.
3. 집주인에게 해지통보 도달 증빙 및 내용증명을 발송하세요.

[3. 쟁점별 상세 법률 분석]
주택임대차보호법 제3조, 제3조의2, 제6조, 제6조의2 및 대법원 판례에 따르면...
(이하 수천 글자의 상세 법조문 및 판례 분석 전문)
"""
    conclusion = extract_answer_conclusion(long_answer, max_chars=250)

    # 1. 핵심 결론 문장들이 포함되어 있는가
    assert "묵시적 갱신" in conclusion
    assert "임차권등기명령" in conclusion
    assert "지연손해금" in conclusion

    # 2. 2단계나 3단계의 장문 설명은 제외되었는가
    assert "[2. 지금 해야 할 일]" not in conclusion
    assert "[3. 쟁점별 상세 법률 분석]" not in conclusion
    assert "수천 글자" not in conclusion

    # 3. 길이가 엄격하게 250자 이내로 제어되는가
    assert len(conclusion) <= 260


def test_extract_answer_conclusion_plain_text():
    """태그가 없는 일반 평문 답변에서도 첫 문단 위주로 안전하게 발췌하는지 테스트."""
    plain_answer = """안녕하세요! 질문하신 보증금 반환 절차에 대해 핵심을 안내해 드립니다.
계약 종료 후 보증금을 돌려받지 못하셨다면 내용증명 발송과 임차권등기명령 신청을 최우선으로 진행하세요.

추가적인 법률 검토가 필요하시면 언제든 질문해주세요."""

    conclusion = extract_answer_conclusion(plain_answer, max_chars=150)
    assert "핵심을 안내해 드립니다" in conclusion
    assert len(conclusion) <= 160


def test_to_chat_history_messages_compresses_aimessage():
    """to_chat_history_messages 호출 시 장문 답변 전문 대신 핵심 결론 요약문만 담기는지 테스트."""
    dummy_long_answer = "[1. 핵심 결론]\n- 계약 종료 확인 및 보증금 반환 청구 가능.\n\n" + ("상세 내용..." * 500)

    turns = [
        ConversationTurn(
            turn_index=1,
            request_id="req-001",
            question="보증금 언제 돌려받을 수 있나요?",
            answer=dummy_long_answer,
            answer_status="DELIVERED",
        ),
        ConversationTurn(
            turn_index=2,
            request_id="req-002",
            question="지연이자는 어떻게 계산하나요?",
            answer=dummy_long_answer,
            answer_status="CAUTIONARY",
        ),
    ]

    ctx = ConversationContext(
        conversation_id="conv-123",
        case_id="case-456",
        current_question="소송 비용은 얼마인가요?",
        previous_turns=turns,
    )

    messages = ctx.to_chat_history_messages(max_turns=2)

    # 2턴이므로 HumanMessage 2개 + AIMessage 2개 = 총 4개
    assert len(messages) == 4

    ai_msg_1 = messages[1]
    ai_msg_2 = messages[3]

    assert isinstance(ai_msg_1, AIMessage)
    assert isinstance(ai_msg_2, AIMessage)

    # 장문 전문 5000자가 아니라 300자 이내로 압축되었는가
    assert len(ai_msg_1.content) < 300
    assert len(ai_msg_2.content) < 300
    assert "[핵심 결론]:" in ai_msg_1.content
    assert "[핵심 결론(주의 요망)]:" in ai_msg_2.content
    assert "상세 내용...상세 내용..." not in ai_msg_1.content


def test_format_context_for_prompt_compactness():
    """format_context_for_prompt 출력 결과가 컴팩트한 요약 맥락만 제공하는지 테스트."""
    dummy_long_answer = "[1. 핵심 결론]\n- 묵시적 갱신 후 해지 통보 효력 3개월 발생.\n\n" + ("장문 분석..." * 300)

    turns = [
        ConversationTurn(
            turn_index=1,
            request_id="req-001",
            question="계약 해지 통보는 언제 효력이 생기나요?",
            answer=dummy_long_answer,
            answer_status="DELIVERED",
        )
    ]

    ctx = ConversationContext(
        conversation_id="conv-123",
        case_id="case-456",
        current_question="이후 퇴거는 언제 하나요?",
        previous_turns=turns,
    )

    formatted = ctx.format_context_for_prompt(max_turns=1, max_chars_per_turn=250)

    assert "해지 통보 효력 3개월 발생" in formatted
    assert "장문 분석...장문 분석..." not in formatted
    assert len(formatted) < 500
