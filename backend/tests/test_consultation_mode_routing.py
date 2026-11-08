# -*- coding: utf-8 -*-
"""상담 모드 분리 회귀 테스트.

PoC 대비 개선 요구:
1. 사건에 증거가 있어도 일반 법률 질문은 사건 원문 작성 경로로 강제하지 않는다.
2. 사건 증거 분석 질문은 기존 DOCUMENT_GROUNDED 경로를 보존한다.
3. 일반 법률 질문에서 이전 사건의 브리핑/그래프 근거가 최종 분석으로 누출되지 않는다.

이 테스트는 외부 LLM/DB를 호출하지 않는 결정론적 단위 테스트다.
실제 LLM의 의미 분류 정확도와 E2E 성공률을 증명하지는 않는다.
"""
from ai_legal_helper.agents.intent_analyzer import (
    ConsultationIntent, ConsultationMode, IntentDecision,
)
from ai_legal_helper.workflows import legal_workflow as workflow
from ai_legal_helper.workflows.document_consultation import DOCUMENT_MODE


def _state():
    # 등록 문서가 있는 사건: 질문별 모드 결정의 독립성을 확인하기 위한 입력.
    return {
        "question": "주택임대차보호법의 대항력 요건을 일반적으로 설명해 주세요.",
        "case_context": "사건의 민감한 사실관계",
        "case_evidence_briefing": {
            "case_type": "임대차",
            "source_documents": [{"document_name": "계약서.txt", "content": "원문", "review_status": "APPROVED"}],
        },
        "case_evidence_sources": [{"source_id": "계약서.txt"}],
        "graph_evidence": {"valid_paths": [{"id": "private"}]},
        "issue_tasks": [{"issue": "개인 사건 쟁점"}],
        "conversation_context": None,
        "answer_mode": None,
    }


def test_general_legal_does_not_inherit_document_mode(monkeypatch):
    monkeypatch.setattr(
        workflow, "analyze_consultation_intent",
        lambda **kwargs: IntentDecision(
            intent=ConsultationIntent.NEW_LEGAL_ANALYSIS,
            consultation_mode=ConsultationMode.GENERAL_LEGAL,
            resolved_query=kwargs["question"],
        ),
    )
    out = workflow.intent_analysis_node(_state())
    assert out["consultation_mode"] == "GENERAL_LEGAL"
    assert out["answer_mode"] is None
    assert out["case_context"] == ""
    assert out["case_evidence_briefing"] is None
    assert out["case_evidence_sources"] == []
    assert out["graph_evidence"] == {}
    assert out["issue_tasks"] == []


def test_case_question_keeps_document_grounding(monkeypatch):
    state = _state()
    state["question"] = "등록한 계약서와 입금 자료를 기준으로 내 사건을 분석해 주세요."
    monkeypatch.setattr(
        workflow, "analyze_consultation_intent",
        lambda **kwargs: IntentDecision(
            intent=ConsultationIntent.NEW_LEGAL_ANALYSIS,
            consultation_mode=ConsultationMode.CASE_EVIDENCE,
            resolved_query=kwargs["question"],
        ),
    )
    out = workflow.intent_analysis_node(state)
    assert out["consultation_mode"] == "CASE_EVIDENCE"
    assert out["answer_mode"] == DOCUMENT_MODE
    assert "case_evidence_briefing" in out  # 기존 조회 유지 확인  # 기존 조회 결과 유지


def test_missing_mode_defaults_to_case_evidence():
    # 구버전 IntentDecision/LLM 결과와 호환: 증거 기반 질문의 근거를 버리지 않는다.
    decision = IntentDecision(
        intent=ConsultationIntent.NEW_LEGAL_ANALYSIS,
        resolved_query="등록 자료를 검토해 주세요.",
    )
    assert decision.consultation_mode == ConsultationMode.CASE_EVIDENCE
