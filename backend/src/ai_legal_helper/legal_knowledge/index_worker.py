# -*- coding: utf-8 -*-
"""P9 공식 법령 원문 버전별 증분 Chroma 인덱싱 Worker.

[안전]
- 사용자 승인 후 확보한 공식 law_id / MST / 목록 시행일이 있는 작업만 등록.
- API 재조회는 관리자가 독립 Worker를 명시 실행할 때만 가능. 상담 경로에서
  승인 없이 국가법령 API 호출하지 않는다.
- 공식 XML의 법령ID/MST/법령명이 충돌하면 인덱스 수정을 중단.
- 청크 ID는 law_id/MST/조문/본문 해시. 오래된 다른 버전은 삭제하지 않는다.
- 법령 전체 본문(XML)의 조문단위 전체를 인덱싱한다. 상담용 10개 조문 결과는 사용 금지.
- Chroma delete_collection 및 기존 분야 컬렉션 수정 금지.
- 외부 요청 재시도와 API 키 마스킹은 기존 공식 검색 유틸을 재사용.
"""
from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ai_legal_helper.legal_knowledge.index_jobs import OfficialLawIndexJob
from ai_legal_helper.tools.official_statute_asof import _check_detail_identity, _label, _parts
from ai_legal_helper.tools.official_statute_versions import OfficialLawVersion, build_detail_url, _safe_xml
from ai_legal_helper.tools.statute_temporal import article_effective_date, extract_addenda

logger = logging.getLogger(__name__)

COLLECTION_NAME = "law_docs_global"
MAX_ATTEMPTS = 3


def enqueue_version(session, version: OfficialLawVersion) -> tuple[str, bool]:
    """동일 법령 ID/MST 중복 작업 등록을 방지하고 기존 READY를 보존한다."""
    if not version.law_id or not version.mst or not version.list_effective_date:
        raise ValueError("MISSING_OFFICIAL_VERSION_IDENTITY")
    current = session.scalar(select(OfficialLawIndexJob).where(
        OfficialLawIndexJob.law_id == version.law_id,
        OfficialLawIndexJob.mst == version.mst,
    ))
    if current:
        return current.id, False
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job = OfficialLawIndexJob(
        id=str(uuid.uuid4()), law_id=version.law_id, law_name=version.law_name,
        mst=version.mst, law_type=version.law_type,
        promulgation_date=version.promulgation_date,
        promulgation_number=version.promulgation_number,
        list_effective_date=version.list_effective_date,
        status="PENDING", attempts=0, chunk_count=0, created_at=now, updated_at=now,
    )
    session.add(job)
    try:
        session.commit()
        return job.id, True
    except IntegrityError:
        # 동시 등록 경합 시 기존 작업을 채택한다. 실패한 트랜잭션은 반드시 롤백.
        session.rollback()
        row = session.scalar(select(OfficialLawIndexJob).where(
            OfficialLawIndexJob.law_id == version.law_id,
            OfficialLawIndexJob.mst == version.mst,
        ))
        if row is None:
            raise
        return row.id, False


def claim_job(session, worker_id: str) -> OfficialLawIndexJob | None:
    """PostgreSQL FOR UPDATE SKIP LOCKED로 중복 Worker의 동일 작업 선점 방지."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stmt = (select(OfficialLawIndexJob)
            .where(OfficialLawIndexJob.status.in_(("PENDING", "RETRY")))
            .where(OfficialLawIndexJob.attempts < MAX_ATTEMPTS)
            .order_by(OfficialLawIndexJob.created_at, OfficialLawIndexJob.id)
            .with_for_update(skip_locked=True).limit(1))
    job = session.scalar(stmt)
    if not job:
        return None
    job.status = "INDEXING"
    job.attempts += 1
    job.lease_owner = worker_id[:64]
    job.updated_at = now
    session.commit()
    return job


def official_xml_chunks(xml_bytes: bytes, version: OfficialLawVersion) -> list[dict]:
    """특정 공식 MST의 조문 전체를 구조화하여 삭제 없는 Upsert 후보로 변환."""
    root = _safe_xml(xml_bytes)
    if root.tag not in ("법령", "Law", "법령정보"):
        raise ValueError("INVALID_OFFICIAL_XML_ROOT")
    mismatch = _check_detail_identity(root, version)
    if mismatch:
        raise ValueError(mismatch)
    # 공식 확인 불가능한 XML을 마치 검증된 MST 원문처럼 저장하지 않는다.
    if not (root.findtext(".//법령ID") and root.findtext(".//법령일련번호")):
        raise ValueError("OFFICIAL_BODY_VERSION_IDENTITY_MISSING")
    addenda = extract_addenda(root, version.promulgation_number)
    chunks = []
    for node in root.findall(".//조문단위"):
        label = _label(node)
        content = _parts(node)
        if not label or not content:
            continue
        effective, basis = article_effective_date(node, label, addenda)
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunk_id = f"official:{version.law_id}:{version.mst}:{label}:{checksum[:16]}"
        chunks.append({
            "id": chunk_id,
            "content": content,
            "metadata": {
                "source_type": "STATUTE",
                "law_id": version.law_id,
                "law_name": version.law_name,
                "statute_name": version.law_name,
                "version_id": version.mst,
                "article": label,
                "content_hash": checksum,
                "law_effective_date": version.list_effective_date,
                "article_effective_date": effective or "",
                "effective_date_basis": basis,
                "temporal_status": "EFFECTIVE_DATE_VERIFIED" if effective else "UNCONFIRMED",
                "promulgation_date": version.promulgation_date or "",
                "promulgation_number": version.promulgation_number,
                "retrieval_collection": COLLECTION_NAME,
            }
        })
    # 부칙은 해당 MST의 법적 효력 판단에 필요하므로 일반 조문과 별도 청크로 보존한다.
    # 같은 버전의 부칙이 여러 개면 idx/원문 해시로 각각 식별한다.
    for idx, addendum in enumerate(addenda):
        checksum = hashlib.sha256(addendum.content.encode("utf-8")).hexdigest()
        chunks.append({
            "id": f"official:{version.law_id}:{version.mst}:addendum:{idx}:{checksum[:16]}",
            "content": addendum.content,
            "metadata": {
                "source_type": "STATUTE", "law_id": version.law_id,
                "law_name": version.law_name, "statute_name": version.law_name,
                "version_id": version.mst, "article": "부칙",
                "content_hash": checksum,
                "law_effective_date": version.list_effective_date,
                "article_effective_date": "",
                "effective_date_basis": "UNCONFIRMED",
                "temporal_status": "UNCONFIRMED",
                "promulgation_date": addendum.promulgation_date or "",
                "promulgation_number": version.promulgation_number,
                "addendum_id": f"{version.mst}:{version.promulgation_number}:{idx}",
                "retrieval_collection": COLLECTION_NAME,
            },
        })
    if not chunks:
        raise ValueError("OFFICIAL_XML_HAS_NO_ARTICLES")
    return chunks


def index_one_version(
    version: OfficialLawVersion,
    *,
    api_key: str,
    fetch_xml: Callable[[str], Optional[bytes]],
    chroma_collection,
    embeddings,
    batch_size: int = 64,
) -> int:
    """전체 공식 XML을 인덱스에 Upsert. 다른 MST의 청크를 삭제하지 않는다."""
    if not api_key:
        raise ValueError("LAW_OPENAPI_KEY_MISSING")
    if not 1 <= batch_size <= 200:
        raise ValueError("INVALID_BATCH_SIZE")
    payload = fetch_xml(build_detail_url(api_key, version))
    if not payload:
        raise ValueError("OFFICIAL_XML_FETCH_FAILED")
    chunks = official_xml_chunks(payload, version)
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        texts = [entry["content"] for entry in batch]
        vectors = embeddings.embed_documents(texts)
        if len(vectors) != len(batch):
            raise ValueError("EMBEDDING_COUNT_MISMATCH")
        chroma_collection.upsert(
            ids=[entry["id"] for entry in batch],
            documents=texts,
            embeddings=vectors,
            metadatas=[entry["metadata"] for entry in batch],
        )
    return len(chunks)


def process_next_job(
    session, *,
    worker_id: str, api_key: str,
    fetch_xml: Callable[[str], Optional[bytes]],
    chroma_collection, embeddings,
) -> dict:
    """한 번에 작업 하나만 실행. 실패 기록 뒤 재시도 가능 상태로 전환."""
    job = claim_job(session, worker_id)
    if job is None:
        return {"status": "EMPTY"}
    v = OfficialLawVersion(
        law_id=job.law_id, law_name=job.law_name, mst=job.mst,
        law_type=job.law_type or "", promulgation_date=job.promulgation_date,
        promulgation_number=job.promulgation_number or "",
        list_effective_date=job.list_effective_date,
    )
    try:
        count = index_one_version(
            v, api_key=api_key, fetch_xml=fetch_xml,
            chroma_collection=chroma_collection, embeddings=embeddings,
        )
        job.status = "READY"
        job.chunk_count = count
        job.error_code = None
    except Exception as exc:
        job.error_code = type(exc).__name__[:100]
        job.status = "RETRY" if job.attempts < MAX_ATTEMPTS else "FAILED"
        logger.warning("[OFFICIAL_INDEX] job=%s error_type=%s", job.id, type(exc).__name__)
    job.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    job.finished_at = job.updated_at if job.status in ("READY", "FAILED") else None
    session.commit()
    return {"status": job.status, "job_id": job.id, "chunk_count": job.chunk_count}


def run_worker_once() -> dict:
    """관리자 CLI 실행용. 자동 기동/승인 없는 백그라운드 실행은 하지 않는다."""
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.rag.retrieval import _get_client
    from ai_legal_helper.llm.gateway import get_embeddings
    from ai_legal_helper.tools.official_statute_search import _fetch_xml_with_retry

    key = os.getenv("LAW_OPENAPI_KEY", "")
    if not key:
        raise ValueError("LAW_OPENAPI_KEY_MISSING")
    collection = _get_client().get_or_create_collection(COLLECTION_NAME)
    with SessionLocal() as session:
        return process_next_job(
            session, worker_id=f"worker-{os.getpid()}", api_key=key,
            fetch_xml=lambda url: _fetch_xml_with_retry(url, api_key=key),
            chroma_collection=collection, embeddings=get_embeddings(),
        )
