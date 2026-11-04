# -*- coding: utf-8 -*-
"""SC-001 후속 질문의 문맥 복원과 Router 안전 종료에 대한 회귀 테스트."""
from ai_legal_helper.workflows import legal_workflow as workflow
from ai_legal_helper.workflows.document_consultation import consultation_question
from ai_legal_helper.agents.router import RouterStatus


def test_document_question_uses_resolved_query_without_overwriting_original():
    state = {"question": "그럼 지금은 어떻게 해야 하나요?",
             "resolved_query": "임대차보증금 미반환 사건에서 임차권등기명령을 언제 신청할 수 있나요?"}
    assert consultation_question(state) == state["resolved_query"]
    assert state["question"] == "그럼 지금은 어떻게 해야 하나요?"
    assert consultation_question({"question": state["question"]}) == state["question"]


def test_document_router_failure_ends_without_agent_execution():
    state = {"answer_mode": workflow.DOCUMENT_MODE, "router_status": RouterStatus.ROUTER_ERROR.value,
             "categories": []}
    assert workflow.route_condition(state) == "routing_exit"


def test_document_router_success_proceeds():
    state = {"answer_mode": workflow.DOCUMENT_MODE, "router_status": RouterStatus.CLASSIFIED.value,
             "categories": ["임대차"]}
    assert workflow.route_condition(state) == "plan"
