# -*- coding: utf-8 -*-
"""적응형 법률 워크플로우 단위 테스트 모듈.

[역할]
Phase 2에서 구현된 Context-Aware Adaptive Legal Workflow의 노드 및 조건부 분기를 검증한다.

[주요 기능]
1. `test_intent_condition_branching`: 7개 의도별 올바른 LangGraph 전이 노드 분기 검증
2. `test_general_conversation_node`: 일상적 인사/감사 시 Specialist/RAG 생략 및 DELIVERED 종결 검증
3. `test_followup_action_node`: 후속 조치 질의 시 직전 출처 재사용 및 맞춤형 가이드 초안 생성 검증
4. `test_intent_analysis_node`: 상태(LegalState)로부터 의도 및 문맥 복원 질의 도출 검증
5. `test_adaptive_graph_execution_general_conversation`: LangGraph 레벨에서 일반 대화 경로가 즉시 종결되는지 검증

[주요 의존성]
ai_legal_helper.workflows.legal_workflow, ai_legal_helper.agents.intent_analyzer, ai_legal_helper.workflows.conversation_context
"""

import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import HumanMessage

from ai_legal_helper.workflows.legal_workflow import (
    intent_analysis_node,
    intent_condition,
    general_conversation_node,
    followup_action_node,
    build_legal_graph,
)
from ai_legal_helper.agents.intent_analyzer import ConsultationIntent, IntentDecision
from ai_legal_helper.workflows.conversation_context import (
    ConversationTurn,
    ConversationContext,
)


def test_intent_condition_branching():
    """ConsultationIntent에 따른 LangGraph 조건부 간선 분기 결과를 검증한다."""
    # 1. 일상 대화
    state_general = {"intent": ConsultationIntent.GENERAL_CONVERSATION.value}
    assert intent_condition(state_general) == "general_conversation"

    # 2. 추가 정보 필요 (불명확한 단문)
    state_clarify = {"intent": ConsultationIntent.NEEDS_CLARIFICATION.value}
    assert intent_condition(state_clarify) == "routing_exit"

    # 3. 후속 행동 조치 요령
    state_action = {"intent": ConsultationIntent.FOLLOWUP_ACTION.value}
    assert intent_condition(state_action) == "followup_action"

    # 4. 신규 심층 법률 분석 -> 정규 route 분기
    state_new = {"intent": ConsultationIntent.NEW_LEGAL_ANALYSIS.value}
    assert intent_condition(state_new) == "route"

    # 5. 후속 세부 질의 -> 정규 route 분기
    state_followup_q = {"intent": ConsultationIntent.FOLLOWUP_QUESTION.value}
    assert intent_condition(state_followup_q) == "route"

    # 6. 사실관계 정정 -> 정규 route 분기
    state_fact = {"intent": ConsultationIntent.FACT_CLARIFICATION.value}
    assert intent_condition(state_fact) == "route"


def test_general_conversation_node():
    """일상적 인사 및 감사 표현에 대해 무거운 에이전트 없이 친절하고 정중한 안내를 즉시 반환하는지 검증한다."""
    # 감사 표현
    state_thanks = {"question": "도움 주셔서 대단히 감사합니다!"}
    res_thanks = general_conversation_node(state_thanks)
    assert res_thanks["final_disposition"] == "DELIVERED"
    assert res_thanks["verification_status"] == "PASS"
    assert "도움이 되어 기쁩니다" in res_thanks["final_answer"]
    assert res_thanks["categories"] == []
    assert res_thanks["retrieved_sources"] == []
    assert len(res_thanks["messages"]) == 1

    # 인사 표현
    state_hello = {"question": "안녕하세요 변호사님"}
    res_hello = general_conversation_node(state_hello)
    assert res_hello["final_disposition"] == "DELIVERED"
    assert "AI Legal Helper" in res_hello["final_answer"]


def test_followup_action_node():
    """후속 조치 질의 시 직전 인용 출처를 보존하고, 실무 실행 가이드를 생성하는지 검증한다."""
    mock_source = {
        "source_id": "STATUTE:주택임대차보호법_제3조의3",
        "law_name": "주택임대차보호법",
        "article": "제3조의3",
        "snippet": "임차인은 임대차가 끝난 후 보증금을 반환받지 못한 경우 임차권등기명령을 신청할 수 있다.",
    }
    conv_context_dict = {
        "conversation_id": "conv-test-123",
        "current_question": "이제 뭘 해야 하죠?",
        "previous_turns": [
            {
                "turn_index": 1,
                "request_id": "req-1",
                "question": "보증금을 못 받았습니다.",
                "answer": "임차권등기명령을 신청하셔야 합니다.",
                "answer_status": "DELIVERED",
                "cited_sources": [mock_source],
            }
        ],
        "previously_cited_sources": [mock_source],
    }

    state = {
        "question": "이제 뭘 해야 하죠?",
        "conversation_context": conv_context_dict,
        "case_context": "보증금 1억 원 미반환 분쟁",
    }

    mock_llm_response = MagicMock()
    mock_llm_response.content = (
        "[1. 핵심 결론 및 우선순위 요약]\n"
        "즉시 임대차계약 해지 통보와 임차권등기명령 신청을 준비하셔야 합니다.\n\n"
        "[2. 단계별 구체적 실행 조치]\n"
        "1단계: 내용증명 발송\n2단계: 임차권등기명령 신청서 작성\n\n"
        "[3. 실무상 유의사항]\n"
        "등기 완료 전에는 절대로 이사하지 마십시오."
    )

    with patch("ai_legal_helper.workflows.legal_workflow.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = mock_llm_response
        mock_get_llm.return_value = mock_llm

        res = followup_action_node(state)

    assert "1단계: 내용증명 발송" in res["draft_answer"]
    assert res["retrieved_sources"] == [mock_source]
    assert res["categories"] == ["민법"]


def test_intent_analysis_node():
    """intent_analysis_node가 analyze_consultation_intent를 호출하고 상태를 올바르게 갱신하는지 검증한다."""
    state = {
        "question": "확정일자는 2022년 5월 1일입니다.",
        "case_context": "전세 계약 분쟁",
        "conversation_context": {
            "conversation_id": "conv-456",
            "current_question": "확정일자는 2022년 5월 1일입니다.",
            "previous_turns": [
                {
                    "turn_index": 1,
                    "request_id": "req-1",
                    "question": "우선변제권 질문",
                    "answer": "확정일자가 필요합니다.",
                    "answer_status": "DELIVERED",
                }
            ],
        },
    }

    res = intent_analysis_node(state)
    assert res["intent"] == ConsultationIntent.FACT_CLARIFICATION.value
    assert "2022년 5월 1일" in res["resolved_query"]
    assert "intent_decision" in res
    assert res["intent_decision"]["intent"] == ConsultationIntent.FACT_CLARIFICATION.value


def test_adaptive_graph_execution_general_conversation():
    """LangGraph 전체 실행 시 GENERAL_CONVERSATION은 Specialist나 RAG 없이 즉시 종료되는지 검증한다."""
    app = build_legal_graph()

    initial_state = {
        "question": "감사합니다!",
        "messages": [HumanMessage(content="감사합니다!")],
        "conversation_id": "conv-chat-001",
        "turn_index": 2,
    }

    config = {"configurable": {"thread_id": "test-chat-001"}}
    output = app.invoke(initial_state, config=config)

    # general_conversation 노드를 거쳐 바로 END로 도달해야 함
    assert output["final_disposition"] == "DELIVERED"
    assert output["intent"] == ConsultationIntent.GENERAL_CONVERSATION.value
    assert "도움이 되어 기쁩니다" in output["final_answer"]
    # 복합 Specialist나 분석 결과가 없어야 함
    assert output.get("results") is None or output.get("results") == {}

