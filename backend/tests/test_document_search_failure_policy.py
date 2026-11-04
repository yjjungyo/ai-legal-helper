"""OpenLaw 오류와 법령 미검색을 구분하는 회귀 테스트."""
from ai_legal_helper.workflows.legal_workflow import statute_search_result_condition


def test_api_error_ends_without_draft():
    state = {"synthesis_law_gate": {"status": "NEED_MORE_LAW"},
             "statute_search_status": "API_ERROR", "statute_search_results": []}
    assert statute_search_result_condition(state) == "insufficient"


def test_law_not_found_uses_rag_path():
    state = {"synthesis_law_gate": {"status": "NEED_MORE_LAW"},
             "statute_search_status": "NOT_FOUND", "statute_search_results": []}
    assert statute_search_result_condition(state) == "run_agents"


def test_verified_fallback_uses_rag_path():
    state = {"synthesis_law_gate": {"status": "NEED_MORE_LAW"},
             "statute_search_status": "VERIFIED_LOCAL_FALLBACK",
             "statute_search_results": [{"source_id": "OFFICIAL:1"}]}
    assert statute_search_result_condition(state) == "run_agents"
