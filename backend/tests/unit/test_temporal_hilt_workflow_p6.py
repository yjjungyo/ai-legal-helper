# -*- coding: utf-8 -*-
"""P6 LangGraph 사전 법령 검색계획 → HILT 승인 → 공식 시점 조회 회귀 테스트."""
from unittest.mock import patch

import pytest

from ai_legal_helper.legal_knowledge.law_resolver import LawResolution, ResolvedLaw
from ai_legal_helper.workflows.temporal_search_plan import (
    build_temporal_search_plan, authorized_plan,
)
from ai_legal_helper.workflows.legal_workflow import (
    statute_search_plan_node, statute_search_plan_condition,
    statute_search_approval_node, execute_statute_search_node,
    statute_search_result_condition, run_agents_node, build_legal_graph,
)


def _catalog(name="가상 계약법 시행령", status="FOUND"):
    return LawResolution(status=status, laws=[
        ResolvedLaw(
            law_id="110", law_name=name, law_type="대통령령", source="OFFICIAL_NAME",
            matched_text=name, score=1000, current_mst="MST-1",
        )
    ])


def _plan():
    return {
        "status": "READY", "phase": "PRE_ANALYSIS",
        "candidate_laws": ["가상 계약법 시행령"],
        "law_ids": ["110"], "as_of_date": "2026-11-01",
        "event_type": "CONTRACT_SIGNED",
        "reason_code": "DATE_AND_OFFICIAL_LAW_IDENTIFIED",
    }


def test_known_law_and_event_date_create_preflight_plan_without_network():
    out = build_temporal_search_plan(
        "2026년 11월 1일 가상 계약법 시행령에 따라 계약 체결했습니다.",
        resolver_fn=lambda _: _catalog(),
    )
    assert out["status"] == "READY"
    assert out["as_of_date"] == "2026-11-01"
    assert out["law_ids"] == ["110"]
    assert out["event_type"] == "CONTRACT_SIGNED"


def test_unknown_catalog_and_ambiguous_dates_fail_open_to_old_agent_route():
    assert build_temporal_search_plan(
        "가상법 시행령에 2026년 11월 1일 계약 체결과 2027년 6월 1일 갱신",
        resolver_fn=lambda _: _catalog(),
    )["status"] == "SKIP"
    out = build_temporal_search_plan(
        "2026년 11월 1일 가상 계약법 시행령 계약 체결",
        resolver_fn=lambda _: _catalog(status="AMBIGUOUS"),
    )
    assert out["status"] == "SKIP"


def test_catalog_failure_does_not_call_openlaw_while_planning():
    def outage(_):
        raise ConnectionError("db")
    out = build_temporal_search_plan(
        "2026년 11월 1일 가상 계약법 시행령 계약 체결",
        resolver_fn=outage,
    )
    assert out["status"] == "SKIP"
    assert out["reason_code"] == "CATALOG_UNAVAILABLE"


def test_preflight_plan_routes_to_existing_hilt_node_only_when_ready():
    with patch(
        "ai_legal_helper.workflows.temporal_search_plan.build_temporal_search_plan",
        return_value=_plan(),
    ):
        state = statute_search_plan_node({"question": "가상 계약법 시행령"})
    assert state["statute_search_phase"] == "PRE_ANALYSIS"
    assert statute_search_plan_condition(state) == "statute_search_approval"
    assert statute_search_plan_condition({
        **state, "hilt_executed": True,
    }) == "run_agents"
    assert statute_search_plan_condition({
        "law_search_plan": {"status": "SKIP"},
    }) == "run_agents"


def test_approval_payload_shows_laws_and_asof_date_and_scope():
    seen = []
    def interrupt_stub(payload):
        seen.append(payload)
        return {"approved": True}
    with patch("ai_legal_helper.workflows.legal_workflow.interrupt", new=interrupt_stub):
        out = statute_search_approval_node({
            "law_search_plan": _plan(),
            "statute_search_phase": "PRE_ANALYSIS",
            "verification_result": {},
            "question": "기준일 개정법 질문",
            "warnings": [],
        })
    assert seen[0]["as_of_date"] == "2026-11-01"
    assert seen[0]["search_phase"] == "PRE_ANALYSIS"
    assert seen[0]["candidate_laws"] == ["가상 계약법 시행령"]
    assert out["approval_status"] == "APPROVED"
    assert out["approved_statute_laws"] == ["가상 계약법 시행령"]


def test_unapproved_preflight_does_not_call_network():
    with patch("ai_legal_helper.tools.official_statute_search.search_official_statutes") as search:
        out = execute_statute_search_node({
            "law_search_plan": _plan(),
            "statute_search_phase": "PRE_ANALYSIS",
            "approval_status": "REJECTED",
        })
    search.assert_not_called()
    assert out["statute_search_results"] == []


def test_approval_scope_tampering_is_blocked_before_network():
    with patch("ai_legal_helper.tools.official_statute_search.search_official_statutes") as search:
        out = execute_statute_search_node({
            "law_search_plan": _plan(), "statute_search_phase": "PRE_ANALYSIS",
            "approval_status": "APPROVED", "approved_statute_laws": ["민법"],
        })
    assert out["statute_search_results"] == []
    search.assert_not_called()


def test_preflight_search_passes_only_approved_laws_and_date_to_official_tool():
    with patch(
        "ai_legal_helper.tools.official_statute_search.search_official_statutes",
        return_value=[],
    ) as search:
        out = execute_statute_search_node({
            "law_search_plan": _plan(), "statute_search_phase": "PRE_ANALYSIS",
            "approval_status": "APPROVED",
            "approved_statute_laws": ["가상 계약법 시행령"],
            "verification_result": {},
            "question": "2026년 11월 1일 계약으로 손해배상 청구 가능한가요?",
            "retrieved_sources": [],
        })
    assert search.call_count == 1
    assert search.call_args.kwargs["candidate_laws"] == ["가상 계약법 시행령"]
    assert search.call_args.kwargs["effective_date"] == "2026-11-01"
    assert out["statute_search_results"] == []


def test_post_verification_damages_keyword_cannot_add_unapproved_civil_law():
    with patch(
        "ai_legal_helper.tools.official_statute_search.search_official_statutes",
        return_value=[],
    ) as search:
        execute_statute_search_node({
            "approval_status": "APPROVED",
            "approved_statute_laws": ["주택임대차보호법"],
            "verification_result": {"candidate_laws": ["주택임대차보호법"]},
            "question": "미반환 손해배상을 청구할 수 있나요?",
        })
    assert search.call_args.kwargs["candidate_laws"] == ["주택임대차보호법"]


def test_existing_post_search_routes_to_reanalysis_but_pre_search_to_agents():
    assert statute_search_result_condition({
        "statute_search_phase": "PRE_ANALYSIS",
        "statute_search_results": [],
    }) == "run_agents"
    assert statute_search_result_condition({
        "statute_search_phase": "PRE_ANALYSIS",
        "statute_search_results": [{"source_id": "x"}],
    }) == "run_agents"
    assert statute_search_result_condition({
        "statute_search_results": [{"source_id": "x"}],
    }) == "re_analyze"
    assert statute_search_result_condition({
        "statute_search_results": [],
    }) == "insufficient"


@pytest.mark.asyncio
async def test_preflight_sources_not_overwritten_by_specialist_search():
    async def noop(*args, **kwargs):
        return None
    with patch(
        "ai_legal_helper.workflows.legal_workflow.run_specialist_agent",
        return_value=("민법", "분석 결과", [{"source_id": "V:1", "content": "Vector"}]),
    ):
        out = await run_agents_node({
            "question": "계약일 법률 질문",
            "categories": ["민법"],
            "retrieved_sources": [{"source_id": "OFFICIAL:1", "content": "공식 원문"}],
        })
    assert {s["source_id"] for s in out["retrieved_sources"]} == {"V:1", "OFFICIAL:1"}


def test_new_preflight_node_is_in_compiled_graph():
    from langgraph.checkpoint.memory import MemorySaver
    graph = build_legal_graph(checkpointer=MemorySaver())
    assert "statute_search_plan" in graph.nodes
