"""Synthesis 통합 법령 충분성 검사 분기 회귀 테스트."""
import json

from ai_legal_helper.workflows.legal_workflow import synthesis_law_gate_condition


def test_ready_goes_to_verification():
    assert synthesis_law_gate_condition({"synthesis_law_gate": {"status": "READY"}}) == "verification"


def test_missing_law_requests_approval_before_verification():
    state = {"synthesis_law_gate": {"status": "NEED_MORE_LAW"}, "statute_search_count": 0, "hilt_executed": False}
    assert synthesis_law_gate_condition(state) == "statute_search_approval"


def test_missing_law_with_prior_approval_does_not_loop():
    state = {"synthesis_law_gate": {"status": "NEED_MORE_LAW"}, "statute_search_count": 1, "hilt_executed": True}
    assert synthesis_law_gate_condition(state) == "insufficient"


def test_document_writer_ready_single_call(monkeypatch):
    from ai_legal_helper.agents import document_answer as module
    from ai_legal_helper.llm import gateway

    class FakeLLM:
        def invoke(self, messages):
            return type("Reply", (), {"content": json.dumps({
                "status": "READY", "missing_laws": [], "answer": "근거에 따른 답변"
            }, ensure_ascii=False)})()

    monkeypatch.setattr(module, "get_llm", lambda **kwargs: FakeLLM())
    monkeypatch.setattr(module, "format_grounding_sources", lambda sources: ("근거 원문", {"content_sha256": "hash"}))
    out = module.write_document_answer("질문", [])
    assert out["draft_answer"] == "근거에 따른 답변"
    assert out.get("synthesis_law_gate") is None


def test_document_writer_missing_law_returns_no_draft(monkeypatch):
    from ai_legal_helper.agents import document_answer as module

    class FakeLLM:
        def invoke(self, messages):
            return type("Reply", (), {"content": json.dumps({
                "status": "NEED_MORE_LAW", "answer": "",
                "missing_laws": [{"law_name": "가상법", "issue": "핵심 쟁점", "articles": []}]
            }, ensure_ascii=False)})()

    monkeypatch.setattr(module, "get_llm", lambda **kwargs: FakeLLM())
    monkeypatch.setattr(module, "format_grounding_sources", lambda sources: ("근거 원문", {"content_sha256": "hash"}))
    out = module.write_document_answer("질문", [])
    assert out["draft_answer"] == ""
    assert out["synthesis_law_gate"]["status"] == "NEED_MORE_LAW"


def test_synthesis_missing_law_skips_verification(monkeypatch):
    from ai_legal_helper.workflows import legal_workflow as workflow

    monkeypatch.setattr(workflow, "generate_answer", lambda state: {
        "draft_answer": "",
        "answer_generation_error": None,
        "synthesis_law_gate": {
            "status": "NEED_MORE_LAW",
            "candidate_laws": ["가상법"],
            "legal_search_requests": [{
                "law_name": "가상법", "issue": "쟁점", "question_part": "질문", "articles": []
            }],
        },
    })
    out = workflow.synthesize_node({"answer_mode": "DOCUMENT_GROUNDED", "question": "질문"})
    assert out["draft_answer"] == ""
    assert out["verification_result"]["reason_code"] == "LEGAL_SOURCE_MISSING"
    assert workflow.synthesis_law_gate_condition(out) == "statute_search_approval"


def test_synthesis_failure_does_not_become_ready(monkeypatch):
    from ai_legal_helper.workflows import legal_workflow as workflow

    monkeypatch.setattr(workflow, "generate_answer", lambda state: {
        "draft_answer": "", "answer_generation_error": "INVALID_SYNTHESIS_GATE"
    })
    out = workflow.synthesize_node({"answer_mode": "DOCUMENT_GROUNDED"})
    assert out["synthesis_law_gate"]["status"] == "ERROR"
    assert workflow.synthesis_law_gate_condition(out) == "insufficient"


def test_post_search_returns_to_retrieval_before_first_draft():
    from ai_legal_helper.workflows.legal_workflow import statute_search_result_condition

    assert statute_search_result_condition({
        "statute_search_phase": "POST_VERIFICATION",
        "synthesis_law_gate": {"status": "NEED_MORE_LAW"},
        "statute_search_results": [{"source_id": "LAW:1", "content": "원문"}],
    }) == "run_agents"
    assert statute_search_result_condition({
        "statute_search_phase": "POST_VERIFICATION",
        "synthesis_law_gate": {"status": "NEED_MORE_LAW"},
        "statute_search_results": [],
    }) == "insufficient"
