"""OpenLaw 실패 시 검증된 기존 법령 출처만 재사용하는지 검사한다."""
from ai_legal_helper.workflows.document_search import _verified_local_fallback


def source(**kwargs):
    return {
        "source_id": "OFFICIAL:test:123:1",
        "source_type": "STATUTE",
        "statute_name": "테스트법",
        "article": "제1조",
        "content": "법령 원문",
        "version_id": "123",
        "content_hash": "abc",
        "temporal_status": "EFFECTIVE_DATE_VERIFIED",
        "version_lookup_status": "AS_OF_RESOLVED",
        "version_date": "2026-01-01",
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
