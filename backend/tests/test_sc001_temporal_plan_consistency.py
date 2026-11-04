# -*- coding: utf-8 -*-
"""SC-001 후속 질문의 법령 검색 계획과 문서 모드 Planner 회귀 테스트."""
from ai_legal_helper.workflows import legal_workflow as workflow


def test_temporal_plan_uses_resolved_query(monkeypatch):
    captured = []
    def fake_plan(question):
        captured.append(question)
        return {"status": "SKIP", "candidate_laws": [], "reason_code": "NO_CANDIDATE"}
    import ai_legal_helper.workflows.temporal_search_plan as temporal
    monkeypatch.setattr(temporal, "build_temporal_search_plan", fake_plan)
    result = workflow.statute_search_plan_node({
        "question": "그 법은 언제 적용돼요?",
        "resolved_query": "임대차 사건에 적용되는 개정 시행령의 시행일은?",
    })
    assert captured == ["임대차 사건에 적용되는 개정 시행령의 시행일은?"]
    assert result["statute_search_phase"] is None


def test_document_mode_skips_unused_specialist_planner(monkeypatch):
    def fail_if_called(_categories):
        raise AssertionError("document mode must not plan specialist execution")
    monkeypatch.setattr(workflow, "plan_tools", fail_if_called)
    result = workflow.plan_node({
        "answer_mode": workflow.DOCUMENT_MODE,
        "categories": ["임대차"],
    })
    assert result["plan"] == []
    assert result["analysis_plan"] == []
