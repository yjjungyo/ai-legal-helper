# -*- coding: utf-8 -*-
"""P10 레거시 Vector 무삭제 스테이징 이관 회귀."""
from types import SimpleNamespace

import pytest

from ai_legal_helper.legal_knowledge.legacy_migration import (
    audit_and_stage, staging_record, STAGING_COLLECTION,
)


class FakeCollection:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.written = {}
        self.deleted = False
    def get(self, *, limit, offset, include):
        rows = self.items[offset:offset + limit]
        return {
            "ids": [r[0] for r in rows],
            "documents": [r[1] for r in rows],
            "metadatas": [r[2] for r in rows],
        }
    def upsert(self, *, ids, documents, embeddings, metadatas):
        for i, d, e, m in zip(ids, documents, embeddings, metadatas):
            self.written[i] = (d, e, m)
    def delete(self, *args, **kwargs):
        raise AssertionError("NO_DELETE")
    def delete_collection(self, *args, **kwargs):
        raise AssertionError("NO_DELETE")


class FakeClient:
    def __init__(self, sources):
        self.collections = sources
        self.created = []
    def list_collections(self):
        return [SimpleNamespace(name=name) for name in self.collections]
    def get_collection(self, name):
        return self.collections[name]
    def get_or_create_collection(self, name):
        self.created.append(name)
        return self.collections.setdefault(name, FakeCollection())
    def delete_collection(self, **kwargs):
        raise AssertionError("NO_DELETE")


class FakeEmbeddings:
    def embed_documents(self, docs):
        return [[float(len(x)), 0.1] for x in docs]


def client():
    return FakeClient({
        "law_docs_civil": FakeCollection([
            ("old:1", "제3조의2 종전의 내용", {
                "law_name": "가상법", "article": "제3조의2",
                "file_name": "가상법_20260101.pdf",
                "version_date": "20260101",
                "effective_date": "20260101", "temporal_status": "VERIFIED",
            }),
            ("old:2", "제3조의2 새로운 내용", {
                "law_name": "가상법", "law_id": "100", "version_id": "MST2",
                "article": "제3조의2", "article_effective_date": "20261201",
            }),
        ]),
        "law_docs_labor": FakeCollection([
            ("labor:1", "노동 법령 원문", {"law_name": "가상근로법"}),
            ("empty:2", "", {"law_name": "빈법"}),
        ]),
    })


def test_default_audit_never_creates_or_changes_collection():
    db = client()
    report = audit_and_stage(db, execute=False, batch_size=1)
    assert report.scanned == 4
    assert report.staged == 0
    assert report.missing_content == 1
    assert report.missing_law_id == 2
    assert report.missing_version_id == 2
    assert db.created == []
    assert all(not x.written for x in db.collections.values())


def test_explicit_staging_is_isolated_and_repeatable():
    db = client()
    one = audit_and_stage(db, execute=True, embeddings=FakeEmbeddings(), batch_size=2)
    assert one.staged == 3
    assert db.created == [STAGING_COLLECTION]
    stage = db.collections[STAGING_COLLECTION]
    assert len(stage.written) == 3
    assert all(x[2]["temporal_status"] == "UNCONFIRMED" for x in stage.written.values())
    assert all(x[2]["effective_date_basis"] == "LEGACY_UNVERIFIED" for x in stage.written.values())
    assert all(x[2]["retrieval_collection"] == STAGING_COLLECTION for x in stage.written.values())
    assert not db.collections["law_docs_civil"].written
    assert not db.collections["law_docs_labor"].written
    two = audit_and_stage(db, execute=True, embeddings=FakeEmbeddings(), batch_size=2)
    assert two.staged == 3
    assert len(stage.written) == 3  # idempotent Upsert; originals untouched


def test_legacy_date_can_never_become_verified_article_effective_date():
    record = staging_record("law_docs_civil", "c1", "제3조 가상법 원문", {
        "law_name": "가상법", "version_date": "20261027",
        "article_effective_date": "20261027",
        "effective_date": "20261027",
        "temporal_status": "VERIFIED",
        "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
    })
    meta = record["metadata"]
    assert meta["article_effective_date"] == ""
    assert meta["filename_date_hint"] == "20261027"
    assert meta["temporal_status"] == "UNCONFIRMED"
    assert meta["metadata_confidence"] == "LEGACY_STAGING_ONLY"


def test_staging_collection_does_not_match_existing_rag_prefix():
    assert not STAGING_COLLECTION.startswith("law_docs_")


def test_invalid_source_and_missing_embeddings_fails_without_writes():
    with pytest.raises(ValueError, match="UNKNOWN_SOURCE_COLLECTION"):
        staging_record("law_docs_global", "id", "본문", {})
    db = client()
    with pytest.raises(ValueError, match="EMBEDDINGS_REQUIRED_FOR_EXECUTION"):
        audit_and_stage(db, execute=True)
    assert db.created == []
