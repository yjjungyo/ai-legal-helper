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
