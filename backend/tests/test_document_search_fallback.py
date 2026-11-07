"""OpenLaw 실패 시 검증된 기존 법령 출처만 재사용하는지 검사한다."""
from unittest.mock import MagicMock, patch
from ai_legal_helper.workflows.document_search import (
    _verified_local_fallback,
    _retrieve_from_local_index,
    execute_document_search,
)


def source(**kwargs):
    return {
        "source_id": "OFFICIAL:test:123:1",
        "source_type": "STATUTE",
        "statute_name": "테스트법",
        "article": "제1조",
        "content": "법령 원문",
        "version_id": "123",
        "content_hash": "abc",
        "temporal_status": "VERIFIED",
        "version_lookup_status": "AS_OF_RESOLVED",
        "version_date": "2026-01-01",
        "article_effective_date": "2026-01-01",
        "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
        **kwargs,
    }


def state(sources, as_of="2026-11-01"):
    return {"retrieved_sources": sources, "case_evidence_briefing": {"as_of_date": as_of}}


REQUESTS = [{"law_name": "테스트법", "articles": ["제1조"], "issue": "쟁점"}]


def test_verified_official_source_reusable():
    assert len(_verified_local_fallback(state([source()]), REQUESTS)) == 1


def test_unknown_temporal_version_rejected():
    candidate = source()
    candidate["temporal_status"] = "UNCONFIRMED"
    assert _verified_local_fallback(state([candidate]), REQUESTS) == []


def test_future_version_rejected():
    assert _verified_local_fallback(state([source()], "2025-12-31"), REQUESTS) == []


def test_wrong_article_rejected():
    assert _verified_local_fallback(state([source()]), [
        {"law_name": "테스트법", "articles": ["제2조"], "issue": "쟁점"}
    ]) == []


def test_no_reference_date_rejected():
    assert _verified_local_fallback(state([source()], None), REQUESTS) == []


def test_unresolved_lookup_rejected():
    candidate = source()
    candidate["version_lookup_status"] = "DATE_NOT_SPECIFIED"
    assert _verified_local_fallback(state([candidate]), REQUESTS) == []


def test_all_requests_must_be_satisfied():
    requests = REQUESTS + [{"law_name": "다른법", "articles": [], "issue": "쟁점"}]
    assert _verified_local_fallback(state([source()]), requests) == []


def test_retrieve_from_local_index_returns_all_requested_articles():
    """요청된 모든 조문이 로컬 인덱스에 존재할 때 즉시 정규화된 출처 목록을 반환한다."""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["OFFICIAL:001706:284415:제536조"],
        "documents": ["제536조(동시이행의 항변권) ..."],
        "metadatas": [{
            "law_name": "민법",
            "statute_name": "민법",
            "article": "제536조",
            "vector_id": "OFFICIAL:001706:284415:제536조",
            "temporal_status": "VERIFIED",
            "version_lookup_status": "AS_OF_RESOLVED",
            "law_id": "001706",
            "mst": "284415",
        }],
    }
    mock_client = MagicMock()
    mock_col_ref = MagicMock()
    mock_col_ref.name = "law_docs_global"
    mock_client.list_collections.return_value = [mock_col_ref]
    mock_client.get_collection.return_value = mock_collection

    with patch("ai_legal_helper.rag.retrieval._get_client", return_value=mock_client):
        res = _retrieve_from_local_index("민법", ["제536조"])
        assert len(res) == 1
        assert res[0]["statute_name"] == "민법"
        assert res[0]["article"] == "제536조"
        assert res[0]["retrieval_method"] == "OFFICIAL_STATUTE_SEARCH"


def test_retrieve_from_local_index_returns_empty_when_article_missing():
    """요청된 조문 중 하나라도 로컬 인덱스에 없으면 빈 목록을 반환하여 외부 API로 폴백한다."""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {
        "ids": ["OFFICIAL:001706:284415:제536조"],
        "documents": ["제536조(동시이행의 항변권) ..."],
        "metadatas": [{
            "law_name": "민법",
            "statute_name": "민법",
            "article": "제536조",
        }],
    }
    mock_client = MagicMock()
    mock_col_ref = MagicMock()
    mock_col_ref.name = "law_docs_global"
    mock_client.list_collections.return_value = [mock_col_ref]
    mock_client.get_collection.return_value = mock_collection

    with patch("ai_legal_helper.rag.retrieval._get_client", return_value=mock_client):
        res = _retrieve_from_local_index("민법", ["제536조", "제537조"])
        assert res == []


def test_execute_document_search_local_first_hit_bypasses_openlaw():
    """로컬 인덱스 히트 시 외부 OpenLaw API를 호출하지 않고 로컬 결과를 즉시 반환한다."""
    mock_sources = [source(statute_name="민법", article="제536조")]
    search_state = {
        "question": "보증금 반환 시 동시이행 항변권",
        "approval_status": "APPROVED",
        "approved_statute_laws": ["민법"],
        "verification_result": {
            "legal_search_requests": [{"law_name": "민법", "articles": ["제536조"], "issue": "동시이행", "question_part": "보증금 반환 시 동시이행 항변권"}],
        },
        "retrieved_sources": [],
        "statute_search_count": 0,
        "case_evidence_briefing": {"as_of_date": "2026-11-01"},
    }

    with patch("ai_legal_helper.workflows.document_search._retrieve_from_local_index", return_value=mock_sources) as mock_local, \
         patch("ai_legal_helper.tools.official_statute_search.search_official_statutes") as mock_openlaw:
        result = execute_document_search(search_state)
        mock_local.assert_called_once()
        mock_openlaw.assert_not_called()
        assert len(result["statute_search_results"]) == 1
        assert result["statute_search_results"][0]["article"] == "제536조"


def test_execute_document_search_falls_back_to_openlaw_when_local_miss():
    """로컬 인덱스 미스 시 실시간 OpenLaw API로 폴백하여 조문을 조회한다."""
    mock_sources = [source(statute_name="민법", article="제536조")]
    search_state = {
        "question": "보증금 반환 시 동시이행 항변권",
        "approval_status": "APPROVED",
        "approved_statute_laws": ["민법"],
        "verification_result": {
            "legal_search_requests": [{"law_name": "민법", "articles": ["제536조"], "issue": "동시이행", "question_part": "보증금 반환 시 동시이행 항변권"}],
        },
        "retrieved_sources": [],
        "statute_search_count": 0,
        "case_evidence_briefing": {"as_of_date": "2026-11-01"},
    }

    with patch("ai_legal_helper.workflows.document_search._retrieve_from_local_index", return_value=[]) as mock_local, \
         patch("ai_legal_helper.tools.official_statute_search.search_official_statutes", return_value=mock_sources) as mock_openlaw:
        result = execute_document_search(search_state)
        mock_local.assert_called_once()
        mock_openlaw.assert_called_once()
        assert len(result["statute_search_results"]) == 1
        assert result["statute_search_results"][0]["article"] == "제536조"



def test_can_satisfy_requests_locally_success():
    """모든 요청이 로컬 인덱스에 존재하면 True를 반환한다."""
    from ai_legal_helper.workflows.document_search import can_satisfy_requests_locally
    mock_sources = [source(statute_name="민법", article="제536조")]
    with patch("ai_legal_helper.workflows.document_search._retrieve_from_local_index", return_value=mock_sources):
        reqs = [{"law_name": "민법", "articles": ["제536조"], "issue": "동시이행"}]
        assert can_satisfy_requests_locally(reqs) is True


def test_can_satisfy_requests_locally_failure():
    """요청 중 하나라도 로컬에 없으면 False를 반환한다."""
    from ai_legal_helper.workflows.document_search import can_satisfy_requests_locally
    with patch("ai_legal_helper.workflows.document_search._retrieve_from_local_index", return_value=[]):
        reqs = [{"law_name": "민법", "articles": ["제999조"], "issue": "미보유"}]
        assert can_satisfy_requests_locally(reqs) is False


def test_run_agents_node_prefetches_planned_statutes():
    """1단계 쟁점 계획(issue_tasks)의 필수 법령 조문을 3단계 run_agents_node에서 사전 적재한다."""
    import asyncio
    from ai_legal_helper.workflows import legal_workflow
    from ai_legal_helper.rag.retrieval import RetrievalResult, RetrievalStatus

    mock_statute_source = source(statute_name="주택임대차보호법", article="제6조")
    state = {
        "answer_mode": "DOCUMENT_GROUNDED",
        "question": "임대차 계약 묵시적 갱신 해지",
        "categories": ["민법"],
        "retrieved_sources": [],
        "issue_tasks": [
            {
                "issue_id": "ISSUE_LEASE_TERMINATION",
                "required_statutes": ["주택임대차보호법 제6조"],
                "candidate_statutes": [],
            }
        ],
    }

    with patch("ai_legal_helper.rag.retrieval.retrieve_with_status", return_value=RetrievalResult(status=RetrievalStatus.NO_MATCH)), \
         patch("ai_legal_helper.workflows.document_search._retrieve_from_local_index", return_value=[mock_statute_source]) as mock_fetch:
        result = asyncio.run(legal_workflow.run_agents_node(state))
        mock_fetch.assert_called_once()
        prefetched = [s for s in result["retrieved_sources"] if s.get("article") == "제6조"]
        assert len(prefetched) == 1
        assert prefetched[0]["statute_name"] == "주택임대차보호법"

