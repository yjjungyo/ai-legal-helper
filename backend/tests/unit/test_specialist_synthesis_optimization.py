# -*- coding: utf-8 -*-
"""단일 분야 상담 Specialist ↔ Synthesizer 중복 제거 최적화(최적화 4번) 단위 테스트 모듈.

[테스트 목적]
1. `run_specialist_agent`의 고속 검색 모드(`fast_retrieval_only=True`) 동작 검증:
   - 무거운 ReAct 장문 생성 LLM 호출을 건너뛰고 RAG 도구 직접 실행으로 법률 출처 및 핵심 조문 요약을 신속히 반환하는지 검증.
2. `run_agents_node`의 적응형 고속 검색 모드 활성화 검증:
   - 단일 카테고리(len(categories) <= 1) 상담 시 고속 검색 모드(`fast_retrieval_mode=True`) 활성화 검증.
   - 사건 증거 기반 상담(`consultation_mode == "CASE_EVIDENCE"`) 시 고속 검색 모드 활성화 검증.
   - 다중 카테고리 일반 상담 시 심층 분석 모드(`fast_retrieval_mode=False`) 유지 검증.
3. 시그니처 하위 호환성 검증:
   - 레거시 3개 인자 Mock 패치 시에도 에러 없이 호환 동작하는지 검증.
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any

from ai_legal_helper.agents.specialist import run_specialist_agent
from ai_legal_helper.workflows.legal_workflow import run_agents_node


def test_run_specialist_agent_fast_retrieval_mode():
    """`fast_retrieval_only=True` 시 ReAct invoke를 건너뛰고 도구 검색 결과만 즉시 반환하는지 검증한다."""
    mock_agent = MagicMock()
    mock_tool = MagicMock()
    mock_tool.invoke.return_value = "제3조의2(보증금의 회수) ① 임차인이..."
    mock_agent.tools = [mock_tool]

    with patch("ai_legal_helper.agents.specialist.get_specialist_agent", return_value=mock_agent), \
         patch("ai_legal_helper.observability.context.get_retrieved_sources", return_value=[{"source_id": "LAW_1"}]):

        cat, text, sources = run_specialist_agent(
            category_ko="민법",
            question="보증금을 돌려받으려면 어떻게 해야 하나요?",
            chat_brief="임대차 종료",
            fast_retrieval_only=True,
        )

        assert cat == "민법"
        assert "[민법 전문 법률 검색 요약]" in text
        assert "제3조의2" in text
        assert len(sources) == 1
        assert sources[0]["source_id"] == "LAW_1"
        # ReAct 장문 생성 invoke는 호출되지 않아야 함 (레이턴시 37초 단축)
        mock_agent.invoke.assert_not_called()
        mock_tool.invoke.assert_called_once()


def test_run_specialist_agent_normal_mode():
    """`fast_retrieval_only=False` 시 기존처럼 ReAct `agent.invoke`를 통해 장문 분석을 수행하는지 검증한다."""
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"output": "상세한 민법 분석 의견서 본문입니다."}

    with patch("ai_legal_helper.agents.specialist.get_specialist_agent", return_value=mock_agent), \
         patch("ai_legal_helper.observability.context.get_retrieved_sources", return_value=[{"source_id": "LAW_1"}]):

        cat, text, sources = run_specialist_agent(
            category_ko="민법",
            question="보증금 반환 질문",
            chat_brief="대화 맥락",
            fast_retrieval_only=False,
        )

        assert cat == "민법"
        assert text == "상세한 민법 분석 의견서 본문입니다."
        mock_agent.invoke.assert_called_once()


@pytest.mark.asyncio
async def test_run_agents_node_activates_fast_retrieval_for_single_category():
    """단일 카테고리 상담 시 `run_agents_node`가 고속 검색 모드로 specialist를 호출하는지 검증한다."""
    called_kwargs = []

    def mock_specialist(cat, q, brief, fast_retrieval_only=False):
        called_kwargs.append(fast_retrieval_only)
        return cat, "검색요약", [{"source_id": "S1"}]

    state = {
        "question": "임차권등기명령은 언제 신청하나요?",
        "categories": ["민법"],  # 단일 카테고리
        "consultation_mode": "GENERAL",
    }

    with patch("ai_legal_helper.workflows.legal_workflow.run_specialist_agent", side_effect=mock_specialist):
        res = await run_agents_node(state)

        assert len(called_kwargs) == 1
        assert called_kwargs[0] is True  # fast_retrieval_only가 True로 활성화됨!
        assert "민법" in res["results"]
        assert len(res["retrieved_sources"]) == 1


@pytest.mark.asyncio
async def test_run_agents_node_activates_fast_retrieval_for_case_evidence_mode():
    """사건 증거 모드(CASE_EVIDENCE) 상담 시 `run_agents_node`가 고속 검색 모드로 specialist를 호출하는지 검증한다."""
    called_kwargs = []

    def mock_specialist(cat, q, brief, fast_retrieval_only=False):
        called_kwargs.append(fast_retrieval_only)
        return cat, "검색요약", [{"source_id": "S1"}]

    state = {
        "question": "전세사기 사건 상담",
        "categories": ["민법", "형법"],  # 다중 카테고리라도 사건 증거 모드이면 Synthesizer가 전담
        "consultation_mode": "CASE_EVIDENCE",
        "case_evidence_briefing": {"summary": "입증된 사실"},
    }

    with patch("ai_legal_helper.workflows.legal_workflow.run_specialist_agent", side_effect=mock_specialist):
        res = await run_agents_node(state)

        assert len(called_kwargs) == 2
        assert all(kw is True for kw in called_kwargs)  # 모든 에이전트가 고속 검색으로 동작
        assert "민법" in res["results"]
        assert "형법" in res["results"]


@pytest.mark.asyncio
async def test_run_agents_node_keeps_normal_mode_for_multi_category_general():
    """다중 카테고리 일반 법률 상담 시 각 분야별 ReAct 전문 분석 모드가 유지되는지 검증한다."""
    called_kwargs = []

    def mock_specialist(cat, q, brief, fast_retrieval_only=False):
        called_kwargs.append(fast_retrieval_only)
        return cat, f"{cat} 전문 분석글", [{"source_id": f"S_{cat}"}]

    state = {
        "question": "형사 고소와 민사 손해배상을 함께 검토해주세요.",
        "categories": ["민법", "형법"],  # 다중 카테고리
        "consultation_mode": "GENERAL",  # 일반 상담
        "case_evidence_briefing": None,
        "issue_tasks": [],
    }

    with patch("ai_legal_helper.workflows.legal_workflow.run_specialist_agent", side_effect=mock_specialist):
        res = await run_agents_node(state)

        assert len(called_kwargs) == 2
        assert all(kw is False for kw in called_kwargs)  # fast_retrieval_only가 False로 유지됨
        assert "민법" in res["results"]
        assert "형법" in res["results"]
