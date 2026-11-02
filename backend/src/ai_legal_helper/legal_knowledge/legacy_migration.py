# -*- coding: utf-8 -*-
"""P10 기존 PDF Vector 자료 감사 및 무손실 격리 이관.

[설계]
- 기존 8개 분야 컬렉션은 읽기 전용으로 접근; delete/update 절대 금지.
- 신규 검토용 컬렉션은 legacy_law_staging 으로 명명한다.
  기존 RAG는 law_docs_* 접두사만 검색하므로 검토 전 내용이 상담에
  유입되지 않도록 의도적으로 접두사를 다르게 사용한다.
- PDF 파일명 날짜, version_date, 기존 effective_date는 법적으로 확인된
  조문 시행일이 아니므로 이관 시에도 temporal_status=UNCONFIRMED 고정.
- Chroma ID는 원본 컬렉션+원본 ID의 SHA256으로 멱등 Upsert.
- 운영 이관은 명시된 --execute가 있을 때만 수행. 기본 실행은 감사 전용.
- 모든 인덱싱은 로컬 get_embeddings()를 통해 벡터화; 공식 조회/LLM 없음.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

LEGACY_CATEGORIES = (
    "constitution", "civil", "criminal", "commercial",
    "labor", "administrative", "tax", "international",
)
SOURCE_COLLECTIONS = tuple(f"law_docs_{category}" for category in LEGACY_CATEGORIES)
STAGING_COLLECTION = "legacy_law_staging"


@dataclass
class MigrationReport:
    scanned: int = 0
    staged: int = 0
    missing_content: int = 0
    missing_law_id: int = 0
    missing_version_id: int = 0
    duplicate_ids: int = 0
    sources: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return vars(self).copy()


def _safe_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def staging_record(collection_name: str, source_id: str, document: str, metadata: dict) -> dict:
    """레거시 날짜 신뢰도를 승격하지 않은 격리 Collection 청크 생성."""
    if collection_name not in SOURCE_COLLECTIONS:
        raise ValueError("UNKNOWN_SOURCE_COLLECTION")
    if not source_id or not document or not document.strip():
        raise ValueError("EMPTY_LEGACY_DOCUMENT")
    metadata = metadata or {}
    origin = f"{collection_name}:{source_id}"
    sha = hashlib.sha256(origin.encode("utf-8")).hexdigest()
    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
    version_hint = (
        metadata.get("filename_date_hint")
        or metadata.get("version_date")
        or metadata.get("effective_date")
        or ""
    )
    # 기존 자료에 VERIFIED 표시가 있더라도 별도 공식 검증 없이 신뢰하지 않는다.
    return {
        "id": "legacy:" + sha,
        "content": document,
        "metadata": {
            "source_type": "STATUTE",
            "law_id": _safe_str(metadata.get("law_id")),
            "law_name": _safe_str(metadata.get("law_name") or metadata.get("statute_name")),
            "statute_name": _safe_str(metadata.get("statute_name") or metadata.get("law_name")),
            "version_id": _safe_str(metadata.get("version_id")),
            "article": _safe_str(metadata.get("article")),
            "content_hash": digest,
            "filename_date_hint": _safe_str(version_hint),
            "article_effective_date": "",
            "effective_date_basis": "LEGACY_UNVERIFIED",
            "temporal_status": "UNCONFIRMED",
            "metadata_confidence": "LEGACY_STAGING_ONLY",
            "origin_collection": collection_name,
            "origin_id": source_id,
            "retrieval_collection": STAGING_COLLECTION,
        },
    }


def audit_and_stage(
    client,
    *,
    execute: bool = False,
    embeddings=None,
    batch_size: int = 100,
    max_rows: int = 100000,
) -> MigrationReport:
    """기존 8개 컬렉션의 자료를 감사하고, 명시 실행 시 격리 스테이징에만 복사.

    Chroma get() 페이징으로 메모리 사용량을 제한한다. 모든 Source를 재검색에
    바로 투입하거나 법적 시행일이 검증됐다고 표시하지 않는다.
    """
    if not 1 <= batch_size <= 200 or max_rows <= 0:
        raise ValueError("INVALID_LIMIT")
    if execute and embeddings is None:
        raise ValueError("EMBEDDINGS_REQUIRED_FOR_EXECUTION")
    report = MigrationReport()
    existing_names = {
        getattr(item, "name", item if isinstance(item, str) else "")
        for item in client.list_collections()
    }
    target = client.get_or_create_collection(STAGING_COLLECTION) if execute else None
    processed_ids: set[str] = set()

    for name in SOURCE_COLLECTIONS:
        if name not in existing_names:
            continue
        source = client.get_collection(name)
        offset = 0
        report.sources[name] = 0
        while offset < max_rows:
            page = source.get(
                limit=min(batch_size, max_rows - offset), offset=offset,
                include=["documents", "metadatas"],
            )
            ids = page.get("ids") or []
            documents = page.get("documents") or []
            metadatas = page.get("metadatas") or []
            if not ids:
                break
            if len(ids) != len(documents) or len(ids) != len(metadatas):
                raise ValueError("CHROMA_PAGE_LENGTH_MISMATCH")
            records = []
            for identifier, document, meta in zip(ids, documents, metadatas):
                report.scanned += 1
                report.sources[name] += 1
                if not document or not str(document).strip():
                    report.missing_content += 1
                    continue
                meta = meta or {}
                if not meta.get("law_id"):
                    report.missing_law_id += 1
                if not meta.get("version_id"):
                    report.missing_version_id += 1
                record = staging_record(name, identifier, document, meta)
                if record["id"] in processed_ids:
                    report.duplicate_ids += 1
                    continue
                processed_ids.add(record["id"])
                records.append(record)
            if execute and records:
                vectors = embeddings.embed_documents([x["content"] for x in records])
                if len(vectors) != len(records):
                    raise ValueError("EMBEDDING_COUNT_MISMATCH")
                target.upsert(
                    ids=[x["id"] for x in records],
                    documents=[x["content"] for x in records],
                    embeddings=vectors,
                    metadatas=[x["metadata"] for x in records],
                )
                report.staged += len(records)
            offset += len(ids)
            if len(ids) < batch_size:
                break
        logger.info("[P10_MIGRATION] collection=%s scanned=%d", name, report.sources[name])
    return report
