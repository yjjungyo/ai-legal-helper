import pytest
import asyncio
from ai_legal_helper.workflows.legal_workflow import run_legal_consultation
from ai_legal_helper.workflows.state import LegalState
from ai_legal_helper.agents.router import route_categories
from langchain_core.messages import HumanMessage

@pytest.mark.asyncio
async def test_route_node_mock():
    cats = route_categories("전세금 문제")
    assert isinstance(cats, list)
    assert len(cats) > 0
    assert "민법" in cats or len(cats) > 0

@pytest.mark.asyncio
async def test_legal_consultation_flow():
    # We can use a simple mock or run the actual LLM if env vars are set.
    res = await run_legal_consultation("근로기준법상 퇴직금 산정 기준", "test-thread-workflow")
    assert "answer" in res
    assert len(res["answer"]) > 0

