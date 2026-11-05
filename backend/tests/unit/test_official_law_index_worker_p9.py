# -*- coding: utf-8 -*-
"""P9 공식 법령 버전별 전체 XML 임베딩 — Mock Chroma/SQLite 회귀."""
import xml.etree.ElementTree as ET
from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ai_legal_helper.legal_knowledge.index_jobs import Base, OfficialLawIndexJob
from ai_legal_helper.legal_knowledge.index_worker import (
    enqueue_version, claim_job, index_one_version, official_xml_chunks,
    process_next_job,
)
from ai_legal_helper.tools.official_statute_versions import OfficialLawVersion


def version(mst="100", law_id="1"):
    return OfficialLawVersion(
        law_id=law_id, law_name="가상 시험법 시행령", mst=mst,
        law_type="대통령령", promulgation_date="2026-06-01",
        promulgation_number="12345", list_effective_date="2026-12-02",
    )


def xml(v, *, wrong_id=False):
    root = ET.Element("법령")
    basic = ET.SubElement(root, "기본정보")
    ET.SubElement(basic, "법령ID").text = "WRONG" if wrong_id else v.law_id
    ET.SubElement(basic, "법령일련번호").text = v.mst
    ET.SubElement(basic, "법령명_한글").text = v.law_name
    for n in range(1, 7):
        node = ET.SubElement(root, "조문단위")
        ET.SubElement(node, "조문번호").text = str(n)
        ET.SubElement(node, "조문내용").text = f"제{n}조 안전한 시험 법률 본문"
    add = ET.SubElement(root, "부칙단위")
    ET.SubElement(add, "부칙공포번호").text = "12345"
    ET.SubElement(add, "부칙공포일자").text = "20260601"
    ET.SubElement(add, "부칙내용").text = (
        "제1조(시행일) 이 영은 공포 후 6개월이 경과한 날부터 시행한다."
    )
    return ET.tostring(root, encoding="utf-8")


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


class FakeVectors:
    def embed_documents(self, documents):
        return [[float(len(x)), 0.5] for x in documents]


class FakeCollection:
    def __init__(self):
        self.items = {}
        self.calls = 0
    def upsert(self, *, ids, documents, embeddings, metadatas):
        self.calls += 1
        for i, text, vector, meta in zip(ids, documents, embeddings, metadatas):
            self.items[i] = (text, vector, meta)
    def get(self, *, ids, include=None):
        return {"ids": [item_id for item_id in ids if item_id in self.items]}
    def delete_collection(self, **kwargs):
        raise AssertionError("데이터 파괴 API 호출 불가")


def test_queue_upsert_same_version_is_idempotent(db):
    job1, created1 = enqueue_version(db, version())
    job2, created2 = enqueue_version(db, version())
    assert created1 and not created2 and job1 == job2
    assert len(db.scalars(select(OfficialLawIndexJob)).all()) == 1
    row = db.get(OfficialLawIndexJob, job1)
    assert row.promulgation_number == "12345"


def test_full_statute_xml_indexes_every_article_in_incremental_batches():
    v = version()
    collection = FakeCollection()
    count = index_one_version(
        v, api_key="mock-key",
        fetch_xml=lambda _: xml(v),
        chroma_collection=collection, embeddings=FakeVectors(), batch_size=2,
    )
    assert count == 7
    assert len(collection.items) == 7
    assert collection.calls == 4
    assert {x[2]["version_id"] for x in collection.items.values()} == {"100"}
    assert all(x[2]["law_id"] == "1" for x in collection.items.values())
    assert all(x[2]["temporal_status"] != "VERIFIED" for x in collection.items.values())


def test_same_article_two_mst_do_not_overwrite():
    collection = FakeCollection()
    for mst in ("100", "200"):
        v = version(mst=mst)
        assert index_one_version(
            v, api_key="mock",
            fetch_xml=lambda _, v=v: xml(v),
            chroma_collection=collection, embeddings=FakeVectors(),
        ) == 7
    assert len(collection.items) == 14
    assert {x[2]["version_id"] for x in collection.items.values()} == {"100", "200"}


def test_original_mst_cannot_be_replaced_by_other_law_xml():
    v = version()
    collection = FakeCollection()
    with pytest.raises(ValueError, match="DETAIL_LAW_ID_MISMATCH"):
        index_one_version(
            v, api_key="mock",
            fetch_xml=lambda _: xml(v, wrong_id=True),
            chroma_collection=collection, embeddings=FakeVectors(),
        )
    assert collection.calls == 0


def test_retry_after_failure_and_ready_after_recovery(db):
    v = version()
    job_id, _ = enqueue_version(db, v)
    collection = FakeCollection()
    first = process_next_job(
        db, worker_id="worker-a", api_key="mock",
        fetch_xml=lambda _: None,
        chroma_collection=collection, embeddings=FakeVectors(),
    )
    assert first["status"] == "RETRY"
    assert db.get(OfficialLawIndexJob, job_id).attempts == 1
    second = process_next_job(
        db, worker_id="worker-b", api_key="mock",
        fetch_xml=lambda _: xml(v),
        chroma_collection=collection, embeddings=FakeVectors(),
    )
    assert second["status"] == "READY"
    assert second["chunk_count"] == 7
    assert process_next_job(
        db, worker_id="worker-c", api_key="mock",
        fetch_xml=lambda _: xml(v),
        chroma_collection=collection, embeddings=FakeVectors(),
    )["status"] == "EMPTY"


def test_invalid_identifiers_and_missing_xml_rejected():
    v = version()
    with pytest.raises(ValueError):
        official_xml_chunks(b"<LawSearch/>", v)
    with pytest.raises(ValueError):
        official_xml_chunks(b"", v)
    with pytest.raises(ValueError):
        official_xml_chunks("<!DOCTYPE law><법령 />".encode("utf-8"), v)


def test_queue_schema_has_strict_unique_key(db):
    _, created = enqueue_version(db, version())
    assert created
    # 다른 MST는 별도 작업이다.
    _, created2 = enqueue_version(db, version("200"))
    assert created2
    assert len(db.scalars(select(OfficialLawIndexJob)).all()) == 2
