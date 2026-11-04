# -*- coding: utf-8 -*-
"""SC-001: 승인된 증거 원문 부재 시 사건 판단을 유보한다."""
from ai_legal_helper.workflows import legal_workflow as workflow


def test_case_question_without_approved_evidence_ends():
    state = {
        "intent": "NEW_LEGAL_ANALYSIS",
        "consultation_mode": "CASE_EVIDENCE",
        "evidence_unavailable": True,
        "case_evidence_briefing": {
            "source_documents": [
                {"review_status": "PENDING", "content": "미승인 계약서"}
            ]
        },
    }
    assert workflow.intent_condition(state) == "evidence_unavailable"
    result = workflow.evidence_unavailable_node(state)
    assert result["final_disposition"] == "WITHHELD"
    assert result["verification_status"] == "UNVERIFIED"
    assert "승인된 원문" in result["final_answer"]
    assert not result["retrieved_sources"]


def test_general_legal_question_still_routes_normally():
    state = {
        "intent": "NEW_LEGAL_ANALYSIS",
        "consultation_mode": "GENERAL_LEGAL",
        "evidence_unavailable": False,
    }
    assert workflow.intent_condition(state) == "route"


def test_approved_document_does_not_trigger_evidence_exit():
    state = {
        "intent": "NEW_LEGAL_ANALYSIS",
        "consultation_mode": "CASE_EVIDENCE",
        "evidence_unavailable": False,
        "answer_mode": workflow.DOCUMENT_MODE,
    }
    assert workflow.intent_condition(state) == "route"


def test_no_documents_provides_different_guidance():
    result = workflow.evidence_unavailable_node({"case_evidence_briefing": None})
    assert "등록하고 승인 상태" in result["final_answer"]
