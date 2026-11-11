# -*- coding: utf-8 -*-
"""모듈명: test_supervisor_init_consolidation.py

[모듈 개요]
`intent_analysis_node` 및 `plan_node` 완전 삭제(통폐합) 후
`supervisor_initialize_node`의 상담 준비 일원화 및 LangGraph 실행 경로를 검증하는 단위 테스트 모듈이다.

[주요 검증 항목]
1. `test_graph_structure_excludes_intent_and_plan`:
   - 컴파일된 LangGraph 노드 목록에서 `intent_analysis`와 `plan`이 완전히 제외되었는지 검증.
2. `test_pure_greeting_routes_to_general_conversation`:
   - 단순 인사말 입력 시 `supervisor_initialize`가 `GENERAL_CONVERSATION`으로 판정하고
     `supervisor_condition`이 `general_conversation` 노드로 즉시 분기하는지 검증.
3. `test_case_question_initializes_briefing_and_routes_to_route_node`:
   - 사건 질문 입력 시 증거 브리핑 및 쟁점 계획이 완비되고 `categories`는 비어있어
     `route_node`에게 전문 분류를 위임하는지 검증.
4. `test_route_condition_bypasses_plan_to_statute_search_plan`:
   - `route_condition`이 `plan`을 건너뛰고 `statute_search_plan`으로 직결 분기하는지 검증.
"""

import pytest
from unittest.mock import MagicMock, patch

from ai_legal_helper.workflows.legal_workflow import (
    build_legal_graph,
    supervisor_initialize_node,
    supervisor_condition,
    route_condition,
)
from ai_legal_helper.agents.router import RouterStatus
from ai_legal_helper.agents.intent_analyzer import ConsultationIntent, ConsultationMode


def test_graph_structure_excludes_intent_and_plan():
    """LangGraph 컴파일 시 intent_analysis와 plan 노드가 완전히 배제되었는지 검증한다."""
    app = build_legal_graph()
    node_keys = list(app.get_graph().nodes.keys())

    # intent_analysis 및 plan 노드가 그래프에 존재하지 않아야 함
    assert "intent_analysis" not in node_keys
    assert "plan" not in node_keys

    # 필수 노드들은 유지되어야 함
    assert "supervisor_initialize" in node_keys
    assert "route" in node_keys
    assert "statute_search_plan" in node_keys
    assert "run_agents" in node_keys
    assert "synthesize" in node_keys
    assert "verification" in node_keys
    assert "finalize" in node_keys


def test_pure_greeting_routes_to_general_conversation():
    """단순 인사말 입력 시 일반 대화(general_conversation) 노드로 즉시 분기하는지 검증한다."""
    state = {
        "question": "안녕하세요!",
        "case_id": None,
    }
    out = supervisor_initialize_node(state)

    assert out["intent"] == ConsultationIntent.GENERAL_CONVERSATION.value
    assert out["consultation_mode"] == ConsultationMode.GENERAL_LEGAL.value
    assert out["evidence_unavailable"] is False

    branch = supervisor_condition(out)
    assert branch == "general_conversation"


def test_case_question_initializes_briefing_and_routes_to_route_node():
    """법률 질문 입력 시 categories를 섣불리 채우지 않고 route_node로 정상 분기하는지 검증한다."""
    state = {
        "question": "계약 종료 후에도 보증금을 돌려받지 못했고 이사를 준비해야 합니다. 증거를 종합해 주세요.",
        "case_id": None,
    }
    out = supervisor_initialize_node(state)

    assert out["intent"] == ConsultationIntent.NEW_LEGAL_ANALYSIS.value
    # categories 추정을 생략하여 router가 전담하도록 비워둠
    assert out["categories"] == []

    branch = supervisor_condition(out)
    assert branch == "route"


def test_route_condition_bypasses_plan_to_statute_search_plan():
    """route_condition이 더미 plan 노드를 거치지 않고 statute_search_plan으로 직결하는지 검증한다."""
    state = {
        "router_status": RouterStatus.CLASSIFIED.value,
        "categories": ["민법"],
        "answer_mode": None,
    }
    branch = route_condition(state)
    assert branch == "statute_search_plan"
