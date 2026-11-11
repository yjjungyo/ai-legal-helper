"""Synthesis 통합 법령 충분성 검사 분기 회귀 테스트."""
import json

from ai_legal_helper.workflows.legal_workflow import synthesis_law_gate_condition


def test_ready_goes_to_verification():
    assert synthesis_law_gate_condition({"synthesis_law_gate": {"status": "READY"}}) == "verification"


def test_missing_law_requests_approval_before_verification():
    state = {"synthesis_law_gate": {"status": "NEED_MORE_LAW"}, "statute_search_count": 0, "hitl_executed": False}
    assert synthesis_law_gate_condition(state) == "statute_search_approval"


def test_missing_law_with_prior_approval_does_not_loop():
    state = {"synthesis_law_gate": {"status": "NEED_MORE_LAW"}, "statute_search_count": 1, "hitl_executed": True}
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


def test_post_search_synthesis_forces_draft_and_skips_need_more_law(monkeypatch):
    """공식 법령 검색이 이미 수행된 상태에서는 NEED_MORE_LAW 요청을 차단하고 초안 작성을 강제하는지 검증한다."""
    from ai_legal_helper.workflows import document_consultation as consultation_module

    captured_allow = {}
    def mock_write(question, sources, **kwargs):
        captured_allow["allow_need_more_law"] = kwargs.get("allow_need_more_law")
        return {"draft_answer": "검색된 법령에 따른 최종 답변 초안", "answer_source_manifest": {}}

    monkeypatch.setattr(consultation_module, "write_document_answer", mock_write)
    monkeypatch.setattr(consultation_module, "document_sources", lambda state: [{"source_id": "LAW:1"}])

    state = {
        "answer_mode": "DOCUMENT_GROUNDED",
        "question": "임대차 종료 및 보증금 반환",
        "statute_search_status": "OFFICIAL_SUCCESS",
        "statute_search_count": 1,
        "hitl_executed": True,
    }
    out = consultation_module.generate_answer(state)
    assert captured_allow["allow_need_more_law"] is False
    assert out["draft_answer"] == "검색된 법령에 따른 최종 답변 초안"
    assert out.get("synthesis_law_gate") is None

def test_document_writer_handles_unescaped_control_characters(monkeypatch):
    """LLM이 답변 본문에 이스케이프되지 않은 제어문자(줄바꿈 0x0A 등)를 반환해도 정상 파싱한다."""
    from ai_legal_helper.agents import document_answer as module

    # RFC 8259에 따라 일반 json.loads는 문자열 내 리터럴 개행(0x0A)을 거부하지만,
    # strict=False 파서가 이를 복원하여 유효한 READY 답변으로 채택해야 한다.
    raw_json_with_literal_newline = '{"status": "READY", "missing_laws": [], "answer": "첫 번째 줄\n두 번째 줄\n세 번째 줄"}'

    class FakeLLM:
        def invoke(self, messages):
            return type("Reply", (), {"content": raw_json_with_literal_newline})()

    monkeypatch.setattr(module, "get_llm", lambda **kwargs: FakeLLM())
    monkeypatch.setattr(module, "format_grounding_sources", lambda sources: ("근거 원문", {"content_sha256": "hash"}))

    out = module.write_document_answer("질문", [])
    assert "첫 번째 줄" in out["draft_answer"]
    assert "두 번째 줄" in out["draft_answer"]
    assert out.get("synthesis_law_gate") is None
    assert out.get("answer_generation_error") is None


def test_document_writer_regex_fallback_recovers_unescaped_quotes(monkeypatch):
    """답변 본문 내에 미이스케이프 따옴표가 포함되어 json.loads가 실패하더라도 정규식 폴백으로 답변을 온전히 복구한다."""
    from ai_legal_helper.agents import document_answer as module

    malformed_json = '{"status": "READY", "missing_laws": [], "answer": "임대인이 "보증금 1억"이라고 주장하며 미지급 상태입니다.\\n권리보전 절차를 안내합니다."}'

    class FakeLLM:
        def invoke(self, messages):
            return type("Reply", (), {"content": malformed_json})()

    monkeypatch.setattr(module, "get_llm", lambda **kwargs: FakeLLM())
    monkeypatch.setattr(module, "format_grounding_sources", lambda sources: ("근거 원문", {"content_sha256": "hash"}))

    out = module.write_document_answer("질문", [])
    assert '보증금 1억' in out["draft_answer"]
    assert out.get("synthesis_law_gate") is None
    assert out.get("answer_generation_error") is None


def test_apply_verified_draft_patches_handles_markdown_fence_and_control_chars():
    """부분 수정 패치 응답에 마크다운 코드 블록 및 제어문자가 포함되어 있어도 정상 적용한다."""
    from ai_legal_helper.agents.document_answer import apply_verified_draft_patches

    original = "임대차 계약 종료일은 2026-08-31입니다. 보증금 반환을 청구할 수 있습니다."
    patch_response = (
        "```json\n"
        '{\n  "patches": [\n    {\n      "old_text": "2026-08-31입니다",\n'
        '      "new_text": "2026-09-30입니다"\n    }\n  ]\n}\n'
        "```"
    )
    result = apply_verified_draft_patches(original, patch_response)
    assert result == "임대차 계약 종료일은 2026-09-30입니다. 보증금 반환을 청구할 수 있습니다."

