# -*- coding: utf-8 -*-
"""
AI Legal Helper - Router v2.0 LangGraph 통합 및 워크플로우 분기 검증 테스트.

이 모듈은 LangGraph 실행 그래프에서 Router의 판단(CLASSIFIED, NEEDS_CLARIFICATION, ROUTER_ERROR)에
따른 조건부 엣지 분기 및 상태 전이(State Transition)를 모킹 기반으로 격리 검증한다.
"""

from unittest.mock import MagicMock, patch
import pytest
from langchain_core.messages import HumanMessage

from ai_legal_helper.agents.router import RouterDecision, RouterStatus
from ai_legal_helper.workflows.legal_workflow import run_legal_consultation


@pytest.mark.asyncio
async def test_workflow_routing_classified_flow():
    """CLASSIFIED 상태 시 plan -> run_agents -> synthesize 파이프라인으로 전이되어야 한다."""
    mock_decision = RouterDecision(
        status=RouterStatus.CLASSIFIED,
        categories=["민법"],
        reason="전세보증금 반환 쟁점",
    )

    with patch("ai_legal_helper.agents.router.route_categories_detailed", return_value=mock_decision), \
         patch("ai_legal_helper.workflows.legal_workflow.plan_tools", return_value=["tool_search"]) as mock_plan, \
         patch("ai_legal_helper.workflows.legal_workflow.run_specialist_agent", return_value=("민법", "민법 분석 결과", [])) as mock_specialist, \
         patch("ai_legal_helper.workflows.legal_workflow.synthesize", return_value=[HumanMessage(content="1. 핵심 결론\n보증금 반환 의무가 있습니다.")]), \
         patch("ai_legal_helper.agents.verification.run_verification", return_value={"status": "PASS", "claims": [], "warnings": []}):

        res = await run_legal_consultation(
            question="전세보증금을 집주인이 돌려주지 않습니다.",
            thread_id="test-router-classified-thread"
        )

        mock_plan.assert_called_once()
        mock_specialist.assert_called_once()
        assert res.get("routing_status") == "CLASSIFIED"
        assert res.get("selected_agents") == ["민법"]
        # 정상 분류 흐름이므로 routing_exit_node의 고정 문구가 아님
        assert "[안내: 추가 정보 필요]" not in res.get("answer", "")
        assert "[안내: 일시적 시스템 오류]" not in res.get("answer", "")


@pytest.mark.asyncio
async def test_workflow_routing_needs_clarification_flow():
    """NEEDS_CLARIFICATION 상태 시 Specialist를 호출하지 않고 routing_exit 노드에서 안전하게 종료되어야 한다."""
    mock_decision = RouterDecision(
        status=RouterStatus.NEEDS_CLARIFICATION,
        categories=[],
        reason="사건 맥락이 전혀 파악되지 않음",
    )

    with patch("ai_legal_helper.agents.router.route_categories_detailed", return_value=mock_decision), \
         patch("ai_legal_helper.workflows.legal_workflow.plan_tools") as mock_plan:

        res = await run_legal_consultation(
            question="어떻게 해야 하나요?",
            thread_id="test-router-clarification-thread"
        )

        # Specialist 플래너가 호출되지 않아야 함
        mock_plan.assert_not_called()

        assert res.get("routing_status") == "NEEDS_CLARIFICATION"
        assert res.get("final_disposition") == "WITHHELD"
        assert res.get("verification_status") == "UNVERIFIED"
        assert res.get("sources") == []
        assert res.get("selected_agents") == []
        assert "구체적인 법률 분야를 판단하기 어렵습니다" in res.get("answer", "")


@pytest.mark.asyncio
async def test_workflow_routing_error_flow():
    """ROUTER_ERROR 상태 시 Specialist를 호출하지 않고 routing_exit 노드에서 시스템 오류로 종료되어야 한다."""
    mock_decision = RouterDecision(
        status=RouterStatus.ROUTER_ERROR,
        categories=[],
        reason="LLM 응답 타임아웃",
        error_code="RTERR_LLM_FAILURE",
    )

    with patch("ai_legal_helper.agents.router.route_categories_detailed", return_value=mock_decision), \
         patch("ai_legal_helper.workflows.legal_workflow.plan_tools") as mock_plan:

        res = await run_legal_consultation(
            question="긴급 법률 문의",
            thread_id="test-router-error-thread"
        )

        mock_plan.assert_not_called()

        assert res.get("routing_status") == "ROUTER_ERROR"
        assert res.get("status") == "ERROR"
        assert res.get("execution_status") == "ERROR"
        assert res.get("final_disposition") == "WITHHELD"
        assert res.get("verification_status") == "UNVERIFIED"
        assert res.get("sources") == []
        assert "일시적인 문제가 발생했습니다" in res.get("answer", "")

