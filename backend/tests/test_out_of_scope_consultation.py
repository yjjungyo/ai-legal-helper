# -*- coding: utf-8 -*-
"""법률 무관 요청의 종료 경로 회귀 테스트.

사건 증거 유무는 질문의 법률 관련성에 영향을 주지 않아야 한다.
실제 LLM의 의미 분류 정확도는 별도 통합 실행에서 검증한다.
"""
from ai_legal_helper.agents.intent_analyzer import ConsultationIntent, ConsultationMode, IntentDecision
from ai_legal_helper.workflows import legal_workflow as workflow


def test_out_of_scope_skips_legal_pipeline():
    state = {"intent": ConsultationIntent.OUT_OF_SCOPE.value, "question": "오늘 날씨 어때?"}
    assert workflow.intent_condition(state) == "general_conversation"
    result = workflow.general_conversation_node(state)
    assert "법률 상담" in result["final_answer"]
    assert result["categories"] == []
    assert result["selected_agents"] == []
    assert result["sources"] == []
    assert result["verification_status"] == "UNVERIFIED"


def test_out_of_scope_independent_of_case_documents(monkeypatch):
    monkeypatch.setattr(
        workflow, "analyze_consultation_intent",
        lambda **kwargs: IntentDecision(
            intent=ConsultationIntent.OUT_OF_SCOPE,
            consultation_mode=ConsultationMode.GENERAL_LEGAL,
            resolved_query=kwargs["question"],
        ),
    )
    for briefing in (None, {"source_documents": [{"filename": "contract.pdf"}]}):
        state = {
            "question": "오늘 날씨 어때?",
            "case_evidence_briefing": briefing,
            "case_context": "민감한 사건 내용",
            "case_evidence_sources": [],
            "graph_evidence": {},
            "issue_tasks": [],
        }
        updates = workflow.intent_analysis_node(state)
        assert updates["intent"] == ConsultationIntent.OUT_OF_SCOPE.value
        assert updates["answer_mode"] is None
        assert updates["case_context"] == ""
        assert workflow.intent_condition(updates) == "general_conversation"
