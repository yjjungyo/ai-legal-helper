# -*- coding: utf-8 -*-
"""
모듈명: test_conversation_context.py

[모듈 개요]
Phase 1: Context-Aware Multi-turn Conversation 파이프라인의 핵심 기능인
ConversationContext 구축, 다중 턴 메시지 정규화, 사건 및 사용자별 보안 격리,
그리고 LangGraph MessagesState의 정규성(HumanMessage/AIMessage)을 검증하는 단위 테스트 모듈이다.

[테스트 항목]
1. `test_conversation_turn_and_context_models`: 모델 생성 및 턴 직렬화 검증
2. `test_to_chat_history_messages_normalization`: 더미 메시지 없이 깨끗한 Human/AI 메시지 변환 검증
3. `test_withheld_answer_handling`: 이전 답변이 WITHHELD(판단 유보)일 때 안전 태깅 검증
4. `test_format_context_for_prompt`: 프롬프트용 마크다운 요약 포맷팅 검증
5. `test_load_conversation_context_from_db`: DB 레코드로부터 턴 복원 및 다음 turn_index 계산 검증
6. `test_security_isolation_case_mismatch`: 다른 사건의 대화 세션 접근 시 PermissionError 차단 검증
7. `test_security_isolation_user_mismatch`: 다른 사용자의 대화 세션 접근 시 PermissionError 차단 검증
8. `test_langgraph_nodes_messages_normalization`: 워크플로우 노드들의 AIMessage 정규 출력 검증
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage, AIMessage

from ai_legal_helper.workflows.conversation_context import (
    ConversationTurn,
    ConversationContext,
    build_conversation_summary,
    load_conversation_context,
)
from ai_legal_helper.database.models import ConsultationRecord
from ai_legal_helper.workflows.legal_workflow import (
    routing_exit_node,
    insufficient_node,
    finalize_node,
)


def test_conversation_turn_and_context_models():
    """ConversationTurn 및 ConversationContext 모델 생성과 필드 유효성을 검증한다."""
    turn1 = ConversationTurn(
        turn_index=1,
        request_id="req-101",
        question="전세보증금을 반환받지 못했습니다.",
        answer="임차권등기명령 및 내용증명 발송을 우선 권고합니다.",
        answer_status="DELIVERED",
        verification_status="PASS",
        cited_sources=[{"source_id": "law_docs_civil_101", "file": "민법.pdf", "article": "제623조"}],
        created_at="2026-10-22T10:00:00",
    )
    assert turn1.turn_index == 1
    assert turn1.answer_status == "DELIVERED"
    assert len(turn1.cited_sources) == 1

    ctx = ConversationContext(
        conversation_id="conv-001",
        case_id="case-001",
        current_question="이제 뭘 해야 하죠?",
        turn_index=2,
        previous_turns=[turn1],
        last_answer=turn1.answer,
        last_answer_status="DELIVERED",
    )
    assert ctx.turn_index == 2
    assert ctx.last_answer == turn1.answer


def test_to_chat_history_messages_normalization():
    """과거 대화 턴들이 LangChain 표준 HumanMessage, AIMessage 쌍으로 정상 변환되는지 검증한다."""
    t1 = ConversationTurn(
        turn_index=1,
        request_id="req-1",
        question="보증금 1억 돌려받을 수 있나요?",
        answer="네, 계약 종료 후 명도와 동시에 반환 청구가 가능합니다.",
        answer_status="DELIVERED",
    )
    t2 = ConversationTurn(
        turn_index=2,
        request_id="req-2",
        question="확정일자는 있습니다.",
        answer="우선변제권 요건을 갖추셨으므로 대항력을 유지할 수 있습니다.",
        answer_status="DELIVERED",
    )
    ctx = ConversationContext(
        conversation_id="conv-123",
        current_question="그럼 임차권등기명령은 언제 신청하나요?",
        previous_turns=[t1, t2],
    )

    messages = ctx.to_chat_history_messages(max_turns=5)
    assert len(messages) == 4
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "보증금 1억 돌려받을 수 있나요?"
    assert isinstance(messages[1], AIMessage)
    assert messages[1].content == "네, 계약 종료 후 명도와 동시에 반환 청구가 가능합니다."
    assert isinstance(messages[2], HumanMessage)
    assert messages[2].content == "확정일자는 있습니다."
    assert isinstance(messages[3], AIMessage)

    # 더미 메시지("dummy", "system" 등)가 전혀 없음을 확인
    for m in messages:
        assert m.content != "dummy"


def test_withheld_answer_handling():
    """과거 답변이 WITHHELD(판단 유보)였던 경우, 안전 경고 안내문이 포함되어 복원되는지 검증한다."""
    t1 = ConversationTurn(
        turn_index=1,
        request_id="req-withheld",
        question="등기부상 선순위 저당권이 있는데 보증금 전액을 받을 수 있나요?",
        answer="경매 배당 순위 및 감정평가액 자료가 부족하여 확정적인 회수 가능 여부 판단을 유보합니다.",
        answer_status="WITHHELD",
        verification_status="INSUFFICIENT",
    )
    ctx = ConversationContext(
        conversation_id="conv-999",
        current_question="그럼 어떤 서류를 준비해야 하나요?",
        previous_turns=[t1],
    )

    messages = ctx.to_chat_history_messages(max_turns=2)
    assert len(messages) == 2
    ai_msg = messages[1]
    assert isinstance(ai_msg, AIMessage)
    assert "[참고: 이전 상담에서 법률 근거 부족으로 판단이 유보된 답변입니다]" in ai_msg.content


def test_format_context_for_prompt():
    """프롬프트 삽입용 마크다운 포맷팅과 글자 수 제한이 정상 동작하는지 검증한다."""
    t1 = ConversationTurn(
        turn_index=1,
        request_id="req-p1",
        question="임대차 계약 해지 통보는 어떻게 하나요?",
        answer="내용증명 우편 또는 도달 확인이 가능한 문자메시지로 계약 만료 2개월 전까지 통보해야 합니다.",
        answer_status="DELIVERED",
    )
    ctx = ConversationContext(
        conversation_id="conv-prompt",
        current_question="그럼 내용증명 양식은요?",
        previous_turns=[t1],
        conversation_summary="- 턴 1: 계약 해지 통보 절차 안내",
    )

    formatted = ctx.format_context_for_prompt(max_turns=3, max_chars_per_turn=200)
    assert "[이전 상담 대화 이력" in formatted
    assert "■ 이전 상담 핵심 요약:" in formatted
    assert "의뢰인: 임대차 계약 해지 통보는 어떻게 하나요?" in formatted
    assert "법률 도우미:" in formatted


def test_load_conversation_context_from_db():
    """DB 레코드로부터 완료된 상담 턴들을 시간순 복원하고 next turn_index를 계산하는지 검증한다."""
    mock_db = MagicMock()

    # 과거 2건의 완료된 레코드 모의
    rec1 = ConsultationRecord(
        id="c-1",
        case_id="case-100",
        user_id="user-1",
        request_id="req-1",
        conversation_id="conv-multi",
        turn_index=1,
        question="첫 번째 질문입니다.",
        answer="첫 번째 답변입니다.",
        status="SUCCESS",
        answer_status="DELIVERED",
        created_at=datetime(2026, 10, 22, 10, 0, 0),
        sources=[{"source_id": "src-1", "file": "계약서.pdf"}],
    )
    rec2 = ConsultationRecord(
        id="c-2",
        case_id="case-100",
        user_id="user-1",
        request_id="req-2",
        conversation_id="conv-multi",
        turn_index=2,
        question="두 번째 질문입니다.",
        answer="두 번째 답변입니다.",
        status="SUCCESS",
        answer_status="CAUTIONARY",
        created_at=datetime(2026, 10, 22, 10, 5, 0),
        sources=[],
    )

    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [rec1, rec2]

    ctx = load_conversation_context(
        db=mock_db,
        conversation_id="conv-multi",
        current_question="세 번째 질문입니다.",
        case_id="case-100",
        user_id="user-1",
        auth_bypass=False,
    )

    assert ctx.conversation_id == "conv-multi"
    assert ctx.turn_index == 3  # 다음 질문 턴은 3
    assert len(ctx.previous_turns) == 2
    assert ctx.previous_turns[0].question == "첫 번째 질문입니다."
    assert ctx.previous_turns[1].answer_status == "CAUTIONARY"
    assert ctx.last_answer == "두 번째 답변입니다."
    assert len(ctx.previously_cited_sources) == 1


def test_security_isolation_case_mismatch():
    """다른 사건(case_id)에 속한 대화 세션에 접근 시 PermissionError가 발생하는지 검증한다."""
    mock_db = MagicMock()
    rec = ConsultationRecord(
        id="c-1",
        case_id="case-ORIGINAL",
        user_id="user-1",
        request_id="req-1",
        conversation_id="conv-case-leak",
        turn_index=1,
        question="비밀 질문",
        answer="비밀 답변",
        status="SUCCESS",
    )
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [rec]

    # case-ATTACKER로 대화에 접근 시도
    with pytest.raises(PermissionError) as exc_info:
        load_conversation_context(
            db=mock_db,
            conversation_id="conv-case-leak",
            current_question="불법 열람 시도",
            case_id="case-ATTACKER",
            user_id="user-1",
            auth_bypass=False,
        )
    assert "다른 사건" in str(exc_info.value)


def test_security_isolation_user_mismatch():
    """다른 사용자(user_id)의 대화 세션에 접근 시 PermissionError가 발생하는지 검증한다."""
    mock_db = MagicMock()
    rec = ConsultationRecord(
        id="c-1",
        case_id="case-1",
        user_id="user-VICTIM",
        request_id="req-1",
        conversation_id="conv-user-leak",
        turn_index=1,
        question="비밀 질문",
        answer="비밀 답변",
        status="SUCCESS",
    )
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [rec]

    # user-ATTACKER로 대화에 접근 시도
    with pytest.raises(PermissionError) as exc_info:
        load_conversation_context(
            db=mock_db,
            conversation_id="conv-user-leak",
            current_question="불법 열람 시도",
            case_id="case-1",
            user_id="user-ATTACKER",
            auth_bypass=False,
        )
    assert "권한이 없습니다" in str(exc_info.value)


def test_langgraph_nodes_messages_normalization():
    """routing_exit_node, insufficient_node, finalize_node의 messages 출력이 AIMessage 객체인지 검증한다."""
    # 1. routing_exit_node
    r_state = {
        "question": "???",
        "router_status": "NEEDS_CLARIFICATION",
        "router_reason": "정보 부족",
        "warnings": [],
    }
    r_out = routing_exit_node(r_state)
    assert "messages" in r_out
    assert len(r_out["messages"]) == 1
    assert isinstance(r_out["messages"][0], AIMessage)
    assert r_out["messages"][0].content != "dummy"

    # 2. insufficient_node
    i_state = {
        "draft_answer": "초안",
        "verification_result": {"status": "INSUFFICIENT", "reason_code": "LEGAL_SOURCE_MISSING"},
        "warnings": [],
    }
    i_out = insufficient_node(i_state)
    assert "messages" in i_out
    assert len(i_out["messages"]) == 1
    assert isinstance(i_out["messages"][0], AIMessage)
    assert i_out["messages"][0].content != "dummy"

    # 3. finalize_node
    f_state = {
        "draft_answer": "검증 완료된 최종 답변입니다.",
        "retrieved_sources": [],
        "case_context": "",
        "verification_result": {"status": "PASS"},
        "warnings": [],
    }
    f_out = finalize_node(f_state)
    assert "messages" in f_out
    assert len(f_out["messages"]) == 1
    assert isinstance(f_out["messages"][0], AIMessage)
    assert f_out["messages"][0].content == "검증 완료된 최종 답변입니다."

