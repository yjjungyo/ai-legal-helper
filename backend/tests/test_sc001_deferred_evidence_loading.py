# -*- coding: utf-8 -*-
"""SC-001: 일반 질문은 증거 조회를 생략하고 승인된 원문만 문서 상담으로 연결한다."""
from ai_legal_helper.agents.intent_analyzer import ConsultationIntent, ConsultationMode, IntentDecision
from ai_legal_helper.workflows import legal_workflow as workflow


def test_general_legal_does_not_load_case_evidence(monkeypatch):
    monkeypatch.setattr(
        workflow, "analyze_consultation_intent",
        lambda **kwargs: IntentDecision(
            intent=ConsultationIntent.NEW_LEGAL_ANALYSIS,
            consultation_mode=ConsultationMode.GENERAL_LEGAL,
            resolved_query=kwargs["question"],
        ),
    )
    state = {"question": "임차권등기명령의 일반적인 요건은?",
             "case_context": "", "case_evidence_briefing": None}
    result = workflow.intent_analysis_node(state)
    assert result["answer_mode"] is None
    assert result["case_evidence_briefing"] is None


def test_nonlegal_question_ends_without_case_loading(monkeypatch):
    monkeypatch.setattr(
        workflow, "analyze_consultation_intent",
        lambda **kwargs: IntentDecision(
            intent=ConsultationIntent.OUT_OF_SCOPE,
            consultation_mode=ConsultationMode.GENERAL_LEGAL,
            resolved_query=kwargs["question"],
        ),
    )
    result = workflow.intent_analysis_node({"question": "오늘 날씨는?", "case_evidence_briefing": None})
    assert workflow.intent_condition(result) == "general_conversation"
    assert result["case_evidence_briefing"] is None
