# -*- coding: utf-8 -*-
"""
P3 공통 법령 검색 서비스 격리 회귀 테스트.

실제 Chroma/PostgreSQL/OpenLaw/LLM 없이 injected retrieve_fn으로
8개 Agent 공통 검색 계약과 SourceCoverage·버전·시행일 상태를 검증한다.
"""
from types import SimpleNamespace

import pytest

from ai_legal_helper.legal_knowledge.retrieval_service import (
    GLOBAL_LAW_COLLECTION, LawRetrievalService, LawSourceStatus,
)
from ai_legal_helper.legal_knowledge.law_resolver import (
    LawResolution, ResolvedLaw,
)


def doc(law_id="L1", name="가상주택임대차보호법", version="MST-2",
        article="제3조", body="제3조 테스트 법령 본문", **metadata):
    """법령ID·MST가 실제 공식 데이터가 아닌 인공 테스트 Vector 문서."""
    meta = {
        "source_type": "STATUTE", "law_id": law_id, "law_name": name,
        "version_id": version, "article": article,
        "source_id": f"{name}_{article}",
        "file_name": f"{name}.pdf", "page": "1",
    }
    meta.update(metadata)
    return SimpleNamespace(page_content=body, metadata=meta)


def result(status="SUCCESS", docs=()):
    return SimpleNamespace(status=status, documents=list(docs))


def catalog(*laws, status="FOUND"):
    return LawResolution(status=status, laws=[
        ResolvedLaw(law_id=law_id, law_name=name, law_type="법률",
                    source="OFFICIAL_NAME", matched_text=name, score=1000,
                    current_mst=mst)
        for law_id, name, mst in laws
    ])


class Backend:
    """요청 컬렉션별 벡터 검색 상태를 저장하고 호출 순서를 검증한다."""

    def __init__(self, global_result=None, legacy_result=None):
        self.responses = {
            "global": global_result if global_result is not None else result("COLLECTION_MISSING"),
            "civil": legacy_result if legacy_result is not None else result("NO_MATCH"),
        }
        self.calls = []

    def __call__(self, *, query, category, k):
        self.calls.append((category, k))
        response = self.responses[category]
        if isinstance(response, Exception):
            raise response
        return response


LAW = ("L1", "가상주택임대차보호법", "MST-2")
OTHER = ("L2", "가상민법", "MST-7")


def service(backend, laws=(LAW,), *, enabled=True):
    return LawRetrievalService(
        retrieval_fn=backend,
        catalog_fn=lambda _: catalog(*laws),
        enable_global=enabled,
        enable_catalog=True,
    )


def test_one_global_statute_can_be_found_from_civil_agent():
    """8개 Agent 중 어떤 분야를 선택해도 공통 벡터 법령을 활용할 수 있다."""
    backend = Backend(global_result=result(docs=[doc()]))
    reply = service(backend).search(
        "가상주택임대차보호법 제3조", category="civil", k=2,
    )
    assert reply.status is LawSourceStatus.SOURCE_COMPLETE
    assert reply.sources[0]["law_id"] == "L1"
    assert reply.sources[0]["retrieval_collection"] == GLOBAL_LAW_COLLECTION
    assert backend.calls == [("global", 4), ("civil", 4)]
    assert reply.official_search_recommended is False


def test_legacy_collection_continues_when_global_not_yet_created():
    backend = Backend(
        global_result=result("COLLECTION_MISSING"),
        legacy_result=result(docs=[doc()]),
    )
    reply = service(backend).search("가상주택임대차보호법 제3조", category="민법")
    assert reply.has_sources
    assert reply.sources[0]["retrieval_collection"] == "law_docs_civil"
    assert reply.status is LawSourceStatus.SOURCE_COMPLETE
    assert reply.collection_statuses[GLOBAL_LAW_COLLECTION] == "COLLECTION_MISSING"


def test_global_disabled_uses_only_legacy_collection():
    backend = Backend(legacy_result=result(docs=[doc()]))
    reply = service(backend, enabled=False).search("가상주택임대차보호법 제3조", category="civil")
    assert backend.calls == [("civil", 4)]
    assert reply.status is LawSourceStatus.SOURCE_COMPLETE


def test_deduplicate_across_collections_but_keep_full_source_content():
    body = "법령 원문 " * 80
    backend = Backend(
        global_result=result(docs=[doc(body=body)]),
        legacy_result=result(docs=[doc(body=body)]),
    )
    reply = service(backend).search("가상주택임대차보호법 제3조", category="civil")
    assert len(reply.sources) == 1
    assert reply.sources[0]["content"] == body
    assert reply.sources[0]["retrieval_collection"] == GLOBAL_LAW_COLLECTION


def test_same_article_two_versions_not_merged_and_source_ids_not_collide():
    backend = Backend(
        global_result=result(docs=[
            doc(version="MST-1", body="옛 법령 원문"),
            doc(version="MST-2", body="새 법령 원문"),
        ]),
    )
    reply = service(backend).search("가상주택임대차보호법 제3조", category="civil", k=3)
    assert len(reply.sources) == 2
    assert {s["version_id"] for s in reply.sources} == {"MST-1", "MST-2"}
    assert len({s["source_id"] for s in reply.sources}) == 2
    assert reply.status is LawSourceStatus.SOURCE_VERSION_UNCONFIRMED


def test_mismatched_official_id_is_rejected_even_if_name_is_same():
    backend = Backend(global_result=result(docs=[doc(law_id="WRONG")]))
    reply = service(backend).search("가상주택임대차보호법 제3조", category="civil")
    assert reply.sources == []
    assert reply.status is LawSourceStatus.SOURCE_MISSING
    assert reply.missing_laws == ["가상주택임대차보호법"]


def test_article_missing_is_partial_not_complete():
    backend = Backend(global_result=result(docs=[doc(article="제4조")]))
    reply = service(backend).search("가상주택임대차보호법 제3조", category="civil")
    assert reply.status is LawSourceStatus.SOURCE_PARTIAL
    assert reply.missing_articles == ["제3조"]


def test_version_absent_or_stale_requires_confirmation():
    backend = Backend(global_result=result(docs=[doc(version=None)]))
    reply = service(backend).search("가상주택임대차보호법 제3조", category="civil")
    assert reply.status is LawSourceStatus.SOURCE_VERSION_UNCONFIRMED
    assert "VERSION_NOT_CURRENTLY_CONFIRMED" in reply.reason_codes


def test_no_article_scope_never_claims_full_coverage():
    backend = Backend(global_result=result(docs=[doc()]))
    reply = service(backend).search("가상주택임대차보호법상 권리는?", category="civil")
    assert reply.status is LawSourceStatus.SOURCE_PARTIAL
    assert reply.official_search_recommended is True


def test_no_catalog_match_with_vector_hits_remains_partial():
    backend = Backend(global_result=result(docs=[doc()]))
    srv = service(backend, laws=())
    reply = srv.search("이 경우 어떻게 하나요?", category="civil")
    assert reply.status is LawSourceStatus.SOURCE_PARTIAL
    assert reply.catalog_status == "NOT_REQUESTED"


def test_required_laws_take_priority_in_truncated_results():
    backend = Backend(global_result=result(docs=[
        doc(body="가상주택임대차보호법 제3조 A"),
        doc(article="제3조", body="가상주택임대차보호법 제3조 B"),
        doc(law_id="L2", name="가상민법", version="MST-7", body="가상민법 제3조"),
    ]))
    reply = service(backend, laws=(LAW, OTHER)).search(
        "가상주택임대차보호법과 가상민법 제3조", category="civil", k=2,
    )
    assert {s["law_id"] for s in reply.sources} == {"L1", "L2"}
    assert reply.missing_laws == []


def test_ambiguous_catalog_does_not_select_one_law_from_vector():
    backend = Backend(global_result=result(docs=[doc()]))
    srv = LawRetrievalService(
        retrieval_fn=backend,
        catalog_fn=lambda _: catalog(LAW, OTHER, status="AMBIGUOUS"),
    )
    reply = srv.search("가상주택임대차보호법 제3조", category="civil")
    assert reply.status is LawSourceStatus.SOURCE_MISSING
    assert reply.reason_codes == ["LAW_IDENTITY_AMBIGUOUS"]
    assert reply.official_search_recommended is True
    assert backend.calls == []


def test_both_collections_missing_is_infrastructure_error_not_missing_law():
    backend = Backend(
        global_result=result("COLLECTION_MISSING"),
        legacy_result=result("COLLECTION_MISSING"),
    )
    reply = service(backend).search("가상주택임대차보호법 제3조", category="civil")
    assert reply.status is LawSourceStatus.RETRIEVAL_ERROR
    assert reply.official_search_recommended is False


def test_one_vector_fails_but_legacy_succeeds_without_auto_openlaw():
    backend = Backend(
        global_result=ConnectionError("cannot connect"),
        legacy_result=result(docs=[doc()]),
    )
    reply = service(backend).search("가상주택임대차보호법 제3조", category="civil")
    assert reply.has_sources
    assert reply.status is LawSourceStatus.SOURCE_PARTIAL
    assert reply.official_search_recommended is False
    assert "RETRIEVAL_INFRA_ERROR" in reply.reason_codes


def test_unconfirmed_temporal_status_blocks_verified_legal_application():
    backend = Backend(global_result=result(docs=[
        doc(article_effective_date="2026-11-01", effective_date_basis="ARTICLE_EFFECTIVE_DATE",
            temporal_status="EFFECTIVE_DATE_VERIFIED")
    ]))
    reply = service(backend).search(
        "가상주택임대차보호법 제3조", category="civil", as_of_date="2026-11-02",
    )
    assert reply.status is LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED
    assert reply.official_search_recommended is True


def test_verified_temporal_source_passes_only_after_review():
    backend = Backend(global_result=result(docs=[
        doc(article_effective_date="2026-11-01",
            effective_date_basis="ARTICLE_EFFECTIVE_DATE", temporal_status="VERIFIED")
    ]))
    reply = service(backend).search(
        "가상주택임대차보호법 제3조", category="civil", as_of_date="2026-11-02",
    )
    assert reply.status is LawSourceStatus.SOURCE_COMPLETE


def test_unknown_event_date_is_not_assumed_current():
    backend = Backend(global_result=result(docs=[doc()]))
    reply = service(backend).search(
        "가상주택임대차보호법 제3조", category="civil", as_of_date="2026-13-01",
    )
    assert reply.status is LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED


def test_catalog_database_failure_does_not_stop_existing_search():
    backend = Backend(legacy_result=result(docs=[doc()]))
    def unavailable(_):
        raise RuntimeError("database unavailable")
    srv = LawRetrievalService(retrieval_fn=backend, catalog_fn=unavailable)
    reply = srv.search("가상주택임대차보호법 제3조", category="civil")
    assert reply.catalog_status == "CATALOG_UNAVAILABLE"
    assert reply.has_sources
    assert reply.status is LawSourceStatus.SOURCE_PARTIAL


def test_invalid_agent_category_is_rejected_without_network_or_sql():
    backend = Backend()
    srv = service(backend)
    reply = srv.search("가상주택임대차보호법 제3조", category="invalid-agent")
    assert reply.status is LawSourceStatus.RETRIEVAL_ERROR
    assert backend.calls == []


def test_search_does_not_automatically_call_external_law_api(monkeypatch):
    backend = Backend()
    def forbidden(*_, **__):
        raise AssertionError("OpenLaw network MUST NOT be invoked by P3")
    monkeypatch.setattr(
        "ai_legal_helper.tools.statute_resolver.resolve_statute_candidates",
        forbidden,
    )
    reply = service(backend, laws=()).search("단순 계약 분쟁", category="civil")
    assert reply.status in (LawSourceStatus.SOURCE_MISSING, LawSourceStatus.RETRIEVAL_ERROR)


def test_preselected_official_laws_do_not_require_runtime_catalog_db():
    backend = Backend(global_result=result(docs=[doc()]))
    def forbidden(_):
        raise AssertionError("Catalog lookup should be bypassed")
    srv = LawRetrievalService(retrieval_fn=backend, catalog_fn=forbidden)
    reply = srv.search(
        "가상주택임대차보호법 제3조", category="civil",
        required_laws=[{"law_id": "L1", "law_name": "가상주택임대차보호법", "current_mst": "MST-2"}],
    )
    assert reply.status is LawSourceStatus.SOURCE_COMPLETE
    assert reply.catalog_status == "PROVIDED_BY_CALLER"
