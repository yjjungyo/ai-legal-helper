# -*- coding: utf-8 -*-
"""Isolated regression tests: official article recovery from PG coverage IDs.

No PostgreSQL, Chroma server, OpenLaw or LLM is contacted.
"""
import hashlib
from types import SimpleNamespace

from ai_legal_helper.legal_knowledge.retrieval_service import (
    LawRetrievalService, LawSourceStatus,
)


LAWS = [
    {"law_id": "L1", "law_name": "가상임대차법"},
    {"law_id": "L2", "law_name": "가상민법"},
]
MSTS = {"L1": "M1", "L2": "M2"}


def indexed_doc(law_id, article, *, body=None, bad_hash=False):
    mst = MSTS[law_id]
    body = body if body is not None else f"{law_id} {article} official body "
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    vector_id = f"official:{law_id}:{mst}:{article}:{digest[:16]}"
    return SimpleNamespace(
        id=vector_id,
        page_content=body,
        metadata={
            "source_type": "STATUTE", "law_id": law_id,
            "law_name": next(x["law_name"] for x in LAWS if x["law_id"] == law_id),
            "statute_name": next(x["law_name"] for x in LAWS if x["law_id"] == law_id),
            "version_id": mst, "article": article, "vector_id": vector_id,
            "content_hash": "bad" if bad_hash else digest,
        },
    )


def make_service(vector_docs, exact_docs, coverage_docs, *, exact_error=None):
    calls = []
    coverage = {
        (d.metadata["law_id"], d.metadata["version_id"], d.id):
            (d.metadata["article"], hashlib.sha256(d.page_content.encode("utf-8")).hexdigest())
        for d in coverage_docs
    }

    def retrieve(*, query, category, k, metadata_filter):
        return SimpleNamespace(status="SUCCESS" if vector_docs else "NO_MATCH",
                               documents=vector_docs)

    def index_fn(*, law_id, event_date, event_type, article_ids):
        return SimpleNamespace(
            status="INDEX_READY_CANDIDATE", mst=MSTS[law_id],
            as_dict=lambda: {"status": "INDEX_READY_CANDIDATE", "mst": MSTS[law_id]},
        )

    def temporal_fn(*, law_id, event_date, event_type, article_ids):
        return SimpleNamespace(as_dict=lambda: {}, reason_codes=[])

    def exact_fn(ids):
        calls.append(list(ids))
        if exact_error:
            raise exact_error
        return [d for d in exact_docs if d.id in ids]

    srv = LawRetrievalService(
        retrieval_fn=retrieve, index_fn=index_fn,
        article_temporal_fn=temporal_fn,
        coverage_fn=lambda versions: coverage,
        exact_fetch_fn=exact_fn,
    )
    return srv, calls


def search(srv, laws=LAWS, question="가상임대차법과 가상민법 제3조 및 제5조"):
    return srv.search(
        question, original_question=question, category="civil",
        required_laws=laws, as_of_date="2026-11-01",
        event_type="계약", k=1,
    )


def test_missing_similarity_hits_are_recovered_by_exact_ids():
    docs = [indexed_doc(law, article)
            for law in ("L1", "L2") for article in ("제3조", "제5조")]
    srv, calls = make_service(docs[:1], docs, docs)
    reply = search(srv)
    assert {(s["law_id"], s["article"]) for s in reply.sources} == {
        ("L1", "제3조"), ("L1", "제5조"),
        ("L2", "제3조"), ("L2", "제5조"),
    }
    assert len(calls) == 1
    assert set(calls[0]) == {d.id for d in docs[1:]}
    assert reply.missing_articles == []
    # A retrieved article is not automatically legally applicable.
    assert reply.status is LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED


def test_pg_coverage_without_chroma_document_remains_missing():
    d = indexed_doc("L1", "제3조")
    srv, calls = make_service([], [], [d])
    reply = search(srv, laws=LAWS[:1], question="가상임대차법 제3조")
    assert calls == [[d.id]]
    assert reply.sources == []
    assert reply.status is not LawSourceStatus.SOURCE_COMPLETE


def test_tampered_exact_content_is_rejected():
    expected = indexed_doc("L1", "제3조")
    tampered = indexed_doc("L1", "제3조", body="different text")
    tampered.id = expected.id
    tampered.metadata["vector_id"] = expected.id
    srv, _ = make_service([], [tampered], [expected])
    reply = search(srv, laws=LAWS[:1], question="가상임대차법 제3조")
    assert reply.sources == []
    assert "POSTGRES_VECTOR_COVERAGE_MISMATCH" in reply.reason_codes


def test_exact_fetch_error_is_not_silently_treated_as_complete():
    d = indexed_doc("L1", "제3조")
    srv, _ = make_service([], [], [d], exact_error=RuntimeError("offline"))
    reply = search(srv, laws=LAWS[:1], question="가상임대차법 제3조")
    assert reply.sources == []
    assert "EXACT_ARTICLE_FETCH_UNAVAILABLE" in reply.reason_codes
    assert reply.status is not LawSourceStatus.SOURCE_COMPLETE
