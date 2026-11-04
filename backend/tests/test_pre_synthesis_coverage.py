"""초안 작성 전 법령 충분성 검사 분기 회귀 테스트."""
from ai_legal_helper.workflows.pre_synthesis_coverage import coverage_next, check_legal_coverage


def test_general_mode_skips_precoverage():
    assert check_legal_coverage({"answer_mode": "GENERAL"}) == {}


def test_document_mode_runs_once():
    assert check_legal_coverage({
        "answer_mode": "DOCUMENT_GROUNDED", "pre_coverage_checked": True
    }) == {}


def test_missing_law_routes_to_approval():
    state = {
        "statute_search_phase": "PRE_ANALYSIS",
        "verification_result": {
            "reason_code": "LEGAL_SOURCE_MISSING",
            "candidate_laws": ["임의의법률"],
        },
        "hilt_executed": False,
    }
    assert coverage_next(state) == "statute_search_approval"


def test_approved_or_completed_search_does_not_repeat():
    state = {
        "statute_search_phase": "PRE_ANALYSIS",
        "verification_result": {
            "reason_code": "LEGAL_SOURCE_MISSING",
            "candidate_laws": ["임의의법률"],
        },
        "hilt_executed": True,
    }
    assert coverage_next(state) == "legal_evidence_bundle"


def test_case_facts_and_issues_included_in_coverage_prompt(monkeypatch):
    from ai_legal_helper.llm import gateway

    captured = {}
    class FakeLLM:
        def invoke(self, prompt):
            captured["prompt"] = prompt
            return type("Response", (), {"content": '{"missing_laws":[]}'})()

    monkeypatch.setattr(gateway, "get_llm", lambda **kwargs: FakeLLM())
    state = {
        "answer_mode": "DOCUMENT_GROUNDED",
        "question": "계약 종료 후 권리는?",
        "case_evidence_briefing": {
            "case_type": "테스트 사건",
            "as_of_date": "2026-08-31",
            "facts": [{"content": "확정된 계약 종료", "status": "CONFIRMED"}],
            "timeline": [{"date": "2026-08-31", "event": "계약 종료"}],
            "evidence_gaps": [{"issue": "통지 증거 부족"}],
        },
        "issue_tasks": [{"issue": "권리보전"}],
        "retrieved_sources": [{"source_type": "STATUTE", "statute_name": "테스트법", "content": "조문"}],
    }
    assert check_legal_coverage(state)["pre_coverage_checked"] is True
    for expected in ("확정된 계약 종료", "권리보전", "2026-08-31", "테스트법", "통지 증거 부족"):
        assert expected in captured["prompt"]


def test_invalid_llm_requests_not_treated_as_complete(monkeypatch):
    from ai_legal_helper.llm import gateway

    class FakeLLM:
        def invoke(self, prompt):
            return type("Response", (), {"content": '{"missing_laws":[{"law_name":"","issue":"x"}]}'})()

    monkeypatch.setattr(gateway, "get_llm", lambda **kwargs: FakeLLM())
    result = check_legal_coverage({
        "answer_mode": "DOCUMENT_GROUNDED",
        "question": "질문",
        "retrieved_sources": [],
    })
    assert any("완료하지 못해" in w for w in result.get("warnings", []))
