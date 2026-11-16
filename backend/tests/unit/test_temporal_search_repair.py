"""사건일 전달과 중복 검색 후 최초 수정 기회의 회귀 테스트.

모델·외부 법령 API는 대역으로 검사하며 과거 법령의 법적 적용을 임의 확정하지 않는다.
"""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from ai_legal_helper.rag.grounding_context import format_grounding_sources
from ai_legal_helper.workflows.document_search import pending_searches, execute_document_search


def search_state():
    """같은 법령의 서로 다른 사건일 요청을 생성한다."""
    question = "사건 당시 반환 의무를 확인해 주세요."
    return {"question": question, "approval_status": "APPROVED",
            "auto_approve_statute_search": True, "retrieved_sources": [],
            "case_evidence_briefing": {"as_of_date": "2026-11-16"},
            "verification_result": {"legal_search_requests": [
                {"law_name": "민법", "articles": ["제1조"], "question_part": question,
                 "issue": "사건 당시 반환 의무", "as_of_date": day}
                for day in ("2024-03-01", "2026-02-28")
            ]}}


def test_dates_preserved_in_history_and_forwarded_to_official_search(monkeypatch):
    """과거 날짜별 요청은 합쳐지지 않고 실제 연혁 API 인자로 전달된다."""
    from ai_legal_helper.workflows import document_search as search

    state = search_state()
    requests = pending_searches(state)
    assert len(requests) == 2
    assert requests[0]["key"] != requests[1]["key"]
    # 최신본 로컬 히트가 있어도 과거 사건일의 적합성을 충족하지 못하면 공식 연혁 조회한다.
    monkeypatch.setattr(search, "_retrieve_from_local_index", lambda **kw: [{
        "source_id": "latest", "content": "최신본", "source_type": "STATUTE",
        "article_effective_date": "2026-07-01", "temporal_status": "EFFECTIVE_DATE_VERIFIED",
        "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
    }])
    official = Mock(return_value=[])
    monkeypatch.setattr("ai_legal_helper.tools.official_statute_search.search_official_statutes", official)
    execute_document_search(state)
    assert [call.kwargs["as_of_date"] for call in official.call_args_list] == ["2024-03-01", "2026-02-28"]
    state["statute_search_history"] = [requests[0]["key"]]
    assert [r["as_of_date"] for r in pending_searches(state)] == ["2026-02-28"]


def test_invalid_explicit_date_does_not_fall_back_to_current_date():
    """잘못 지정한 사건일은 최신본 검색으로 바꾸지 않는다."""
    state = search_state()
    state["verification_result"]["legal_search_requests"] = [
        {**state["verification_result"]["legal_search_requests"][0], "as_of_date": "2024-99-99"}]
    assert pending_searches(state) == []


def test_initial_writer_keeps_structured_event_date(monkeypatch):
    """작성 모델의 날짜가 검색 요청 정규화 과정에서 소실되지 않는다."""
    from ai_legal_helper.agents.document_answer import write_document_answer

    result = {"status": "NEED_MORE_LAW", "missing_laws": [{
        "law_name": "민법", "articles": ["제1조"], "issue": "사건일 기준 확인",
        "as_of_date": "2024-03-01"}], "answer": ""}
    monkeypatch.setattr("ai_legal_helper.agents.document_answer.get_llm", lambda **kw:
                        SimpleNamespace(invoke=lambda messages: SimpleNamespace(content=json.dumps(result))))
    written = write_document_answer("사건 당시 규정을 확인해 주세요.", [])
    assert written["synthesis_law_gate"]["legal_search_requests"][0]["as_of_date"] == "2024-03-01"


def test_zero_delta_allows_one_repair_without_approving_failed_draft():
    """새 근거가 없어도 최초 수정은 허용하고 이미 수정한 실패 초안은 반복하지 않는다."""
    from ai_legal_helper.workflows.legal_workflow import statute_search_result_condition

    state = {"answer_mode": "DOCUMENT_GROUNDED", "draft_answer": "확정할 수 있습니다.",
             "statute_search_status": "OFFICIAL_SUCCESS", "search_delta_count": 0,
             "verification_result": {"status": "REVISE", "claims": [{"grounding_status": "UNSUPPORTED"}],
                                     "revision_instructions": ["근거 없는 확정 표현을 고치세요."]}}
    assert statute_search_result_condition(state) == "revise"
    assert statute_search_result_condition({**state, "revision_count": 1}) == "finalize"
    assert statute_search_result_condition({**state, "verification_no_progress": True}) == "finalize"


def test_law_date_is_not_promoted_to_article_date():
    """법령 전체 시행일만 있을 때 개별 조문 시행일을 생성하지 않는다."""
    rendered, _ = format_grounding_sources([{
        "source_id": "law", "source_type": "STATUTE", "content": "원문",
        "law_effective_date": "2026-07-01",
    }])
    metadata = json.loads(rendered.splitlines()[0])
    assert "article_effective_date" not in metadata
    assert metadata["law_effective_date"] == "2026-07-01"


def test_fallback_uses_each_request_date_instead_of_review_date():
    """공식 연혁 조회 실패 후 최신본을 과거 요청의 대체 근거로 승격하지 않는다."""
    from ai_legal_helper.workflows.document_search import _verified_local_fallback

    state = search_state()
    state["retrieved_sources"] = [{
        "source_id": "current", "source_type": "STATUTE", "statute_name": "민법",
        "article": "제1조", "content": "최신 원문", "content_hash": "hash", "version_id": "v",
        "article_effective_date": "2026-07-01", "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
        "temporal_status": "VERIFIED", "version_lookup_status": "AS_OF_RESOLVED",
    }]
    assert _verified_local_fallback(state, pending_searches(state)) == []
