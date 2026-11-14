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
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ai_legal_helper.legal_knowledge.index_jobs import OfficialLawIndexJob, LawVersionIndex, LawArticleCoverage, LawArticleVersion, LawTransitionRule
from ai_legal_helper.tools.official_statute_asof import _check_detail_identity, _label, _parts
from ai_legal_helper.tools.official_statute_versions import OfficialLawVersion, build_detail_url, _safe_xml
from ai_legal_helper.tools.statute_temporal import article_effective_date, extract_addenda

logger = logging.getLogger(__name__)

COLLECTION_NAME = "law_docs_global"
DEFAULT_COLLECTION_NAME = "law_docs_global"
MAX_ATTEMPTS = 3

# 법령별 관할 도메인(민사, 행정, 형사, 노동, 상사, 조세, 헌법 등) 정규화 매핑 테이블
LAW_DOMAIN_MAPPING: dict[str, str] = {
    # 1. 민사 (civil)
    "민법": "law_docs_civil",
    "주택임대차보호법": "law_docs_civil",
    "상가건물임대차보호법": "law_docs_civil",
    "가등기담보등에관한법률": "law_docs_civil",
    "부동산실권리자명의등기에관한법률": "law_docs_civil",
    "집합건물의소유및관리에관한법률": "law_docs_civil",
    "민사소송법": "law_docs_civil",
    "민사집행법": "law_docs_civil",
    "채무자회생및파산에관한법률": "law_docs_civil",
    "소액사건심판법": "law_docs_civil",
    "이자제한법": "law_docs_civil",
    "대부업등의등록및금융이용자보호에관한법률": "law_docs_civil",

    # 2. 형사 (criminal)
    "형법": "law_docs_criminal",
    "형사소송법": "law_docs_criminal",
    "특정범죄가중처벌등에관한법률": "law_docs_criminal",
    "특정경제범죄가중처벌등에관한법률": "law_docs_criminal",
    "폭력행위등처벌에관한법률": "law_docs_criminal",
    "도로교통법": "law_docs_criminal",
    "교통사고처리특례법": "law_docs_criminal",
    "성폭력범죄의처벌등에관한특례법": "law_docs_criminal",
    "마약류관리에관한법률": "law_docs_criminal",

    # 3. 행정 (administrative)
    "민간임대주택에관한특별법": "law_docs_administrative",
    "공인중개사법": "law_docs_administrative",
    "부동산거래신고등에관한법률": "law_docs_administrative",
    "행정기본법": "law_docs_administrative",
    "행정절차법": "law_docs_administrative",
    "행정소송법": "law_docs_administrative",
    "행정심판법": "law_docs_administrative",
    "건축법": "law_docs_administrative",
    "국토의계획및이용에관한법률": "law_docs_administrative",
    "식품위생법": "law_docs_administrative",

    # 4. 상사 (commercial)
    "상법": "law_docs_commercial",
    "자본시장과금융투자업에관한법률": "law_docs_commercial",
    "어음법": "law_docs_commercial",
    "수표법": "law_docs_commercial",

    # 5. 노동 (labor)
    "근로기준법": "law_docs_labor",
    "노동조합및노동관계조정법": "law_docs_labor",
    "남녀고용평등과일가정양립지원에관한법률": "law_docs_labor",
    "산업안전보건법": "law_docs_labor",
    "산업재해보상보험법": "law_docs_labor",
    "근로자퇴직급여보장법": "law_docs_labor",

    # 6. 조세 (tax)
    "국세기본법": "law_docs_tax",
    "소득세법": "law_docs_tax",
    "법인세법": "law_docs_tax",
    "부가가치세법": "law_docs_tax",
    "상속세및증여세법": "law_docs_tax",
    "지방세법": "law_docs_tax",

    # 7. 헌법 (constitution)
    "대한민국헌법": "law_docs_constitution",
    "헌법재판소법": "law_docs_constitution",
    "국회법": "law_docs_constitution",
}


def resolve_law_collection(law_name: str) -> str:
    """법령명을 기반으로 적재할 대상 Chroma 컬렉션을 판별한다.

    1. 시행령, 시행규칙 등 하위법령은 모법 명칭을 추출하여 관할 도메인을 판별한다.
    2. 매핑 테이블(민사, 행정, 형사, 노동, 상사, 조세, 헌법)에 해당하는 경우 해당 도메인 컬렉션을 반환한다.
    3. 도메인이 명확히 분류되지 않거나 미등록된 일반 법령은 기본 전역 컬렉션(law_docs_global)으로 폴백한다.

    Args:
        law_name: 판별할 법령명 (예: '민법', '주택임대차보호법', '민간임대주택에 관한 특별법 시행령').

    Returns:
        str: 적재할 ChromaDB 컬렉션 이름 (예: 'law_docs_civil', 'law_docs_administrative', 'law_docs_global').
    """
    if not law_name:
        return DEFAULT_COLLECTION_NAME

    clean = re.sub(r"[^가-힣A-Za-z0-9]", "", law_name)

    # 1. 완전 일치 검사
    if clean in LAW_DOMAIN_MAPPING:
        return LAW_DOMAIN_MAPPING[clean]

    # 2. 시행령, 시행규칙 등 접미어 제거 후 모법 일치 검사
    base_clean = re.sub(r"(시행령|시행규칙|규칙)$", "", clean)
    if base_clean and base_clean in LAW_DOMAIN_MAPPING:
        return LAW_DOMAIN_MAPPING[base_clean]

    # 3. 키워드 기반 포함 검사
    for mapped_law, col in LAW_DOMAIN_MAPPING.items():
        if mapped_law in clean:
            return col

    # 4. 도메인 미분류 법령은 전역 폴백
    return DEFAULT_COLLECTION_NAME


def validate_embedding_vectors(vectors, expected_count: int) -> None:
    if len(vectors) != expected_count:
        raise ValueError("EMBEDDING_COUNT_MISMATCH")
    dimensions = set()
    for vector in vectors:
        if vector is None or len(vector) == 0:
            raise ValueError("EMBEDDING_VECTOR_EMPTY")
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
            raise ValueError("EMBEDDING_VECTOR_INVALID")
        dimensions.add(len(vector))
    if len(dimensions) != 1:
        raise ValueError("EMBEDDING_DIMENSION_MISMATCH")



def enqueue_version(session, version: OfficialLawVersion) -> tuple[str, bool]:
    """동일 법령 ID/MST 중복 작업 등록을 방지하고 기존 READY를 보존한다."""
    if not version.law_id or not version.mst or not version.list_effective_date:
        raise ValueError("MISSING_OFFICIAL_VERSION_IDENTITY")
    current = session.scalar(select(OfficialLawIndexJob).where(
        OfficialLawIndexJob.law_id == version.law_id,
        OfficialLawIndexJob.mst == version.mst,
    ))
    if current:
        version_row = session.scalar(select(LawVersionIndex).where(
            LawVersionIndex.law_id == version.law_id,
            LawVersionIndex.mst == version.mst,
        ))
        if (version_row is not None and version_row.index_status == "STALE"
                and current.status in ("READY", "FAILED")):
            current.status = "PENDING"
            current.attempts = 0
            current.error_code = None
            current.chunk_count = 0
            current.lease_owner = None
            current.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            current.finished_at = None
            current.list_effective_date = version.list_effective_date
            current.promulgation_date = version.promulgation_date
            current.promulgation_number = version.promulgation_number
            session.commit()
            return current.id, True
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
    """특정 공식 MST의 조문 전체를 구조화하여 삭제 없는 Upsert 후보로 변환한다.

    Args:
        xml_bytes: 국가법령정보센터에서 수신한 공식 법령 상세 XML 원문 바이트.
        version: 법령 식별 정보(law_id, mst, 법령명, 시행일 등)가 검증된 공식 법령 버전 객체.

    Returns:
        list[dict]: Chroma 벡터 DB 및 관계형 DB 커버리지 인덱스에 적재할 고유 청크 딕셔너리 리스트.

    Raises:
        ValueError: XML 루트 태그 불일치, 법령 식별자 불일치, 조문 누락 등의 오류 발생 시.
    """
    root = _safe_xml(xml_bytes)
    if root.tag not in ("법령", "Law", "법령정보"):
        raise ValueError("INVALID_OFFICIAL_XML_ROOT")
    mismatch = _check_detail_identity(root, version)
    if mismatch:
        raise ValueError(mismatch)
    # 공식 확인 불가능한 XML을 마치 검증된 MST 원문처럼 저장하지 않는다.
    # OpenLaw eflaw 상세조회 XML(<기본정보>)은 <법령ID>를 필수로 제공하나 <법령일련번호>는
    # 생략될 수 있으므로, XML 내 법령ID와 요청된 version.mst의 존재를 함께 확인한다.
    law_id_in_xml = (root.findtext(".//법령ID") or "").strip()
    mst_in_xml = (root.findtext(".//법령일련번호") or "").strip()
    if not (law_id_in_xml and (mst_in_xml or version.mst)):
        raise ValueError("OFFICIAL_BODY_VERSION_IDENTITY_MISSING")
    if law_id_in_xml != version.law_id:
        raise ValueError("DETAIL_LAW_ID_MISMATCH")
    if mst_in_xml and mst_in_xml != version.mst:
        raise ValueError("DETAIL_MST_MISMATCH")
    addenda = extract_addenda(root, version.promulgation_number)
    chunks = []
    article_nodes = root.findall(".//조문단위")
    if not article_nodes:
        raise ValueError("OFFICIAL_XML_HAS_NO_ARTICLES")
    seen_articles = set()
    for node in article_nodes:
        # 편·장·절 구분 표제어(전문)는 본 조문이 아니므로 인덱싱 대상에서 제외
        if (node.findtext("조문여부") or "").strip() == "전문":
            continue
        label = _label(node)
        content = _parts(node)
        if not label or not content:
            raise ValueError("OFFICIAL_XML_ARTICLE_INCOMPLETE")
        if label in seen_articles:
            raise ValueError("OFFICIAL_XML_DUPLICATE_ARTICLE")
        seen_articles.add(label)
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
                "vector_id": chunk_id,
                "law_effective_date": version.list_effective_date,
                "article_effective_date": effective or "",
                "effective_date_basis": basis,
                "temporal_status": "EFFECTIVE_DATE_VERIFIED" if effective else "UNCONFIRMED",
                "promulgation_date": version.promulgation_date or "",
                "promulgation_number": version.promulgation_number,
                "retrieval_collection": resolve_law_collection(version.law_name),
            }
        })
    # 부칙은 해당 MST의 법적 효력 판단에 필요하므로 일반 조문과 별도 청크로 보존한다.
    # 같은 버전의 부칙이 여러 개면 idx/원문 해시로 각각 식별한다.
    for idx, addendum in enumerate(addenda):
        checksum = hashlib.sha256(addendum.content.encode("utf-8")).hexdigest()
        addendum_vector_id = f"official:{version.law_id}:{version.mst}:addendum:{idx}:{checksum[:16]}"
        chunks.append({
            "id": addendum_vector_id,
            "content": addendum.content,
            "metadata": {
                "source_type": "STATUTE", "law_id": version.law_id,
                "law_name": version.law_name, "statute_name": version.law_name,
                "version_id": version.mst, "article": "부칙",
                "content_hash": checksum,
                "vector_id": addendum_vector_id,
                "law_effective_date": version.list_effective_date,
                "article_effective_date": "",
                "effective_date_basis": "UNCONFIRMED",
                "temporal_status": "UNCONFIRMED",
                "promulgation_date": addendum.promulgation_date or "",
                "promulgation_number": version.promulgation_number,
                "addendum_id": f"{version.mst}:{version.promulgation_number}:{idx}",
                "retrieval_collection": resolve_law_collection(version.law_name),
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
        validate_embedding_vectors(vectors, len(batch))
        chroma_collection.upsert(
            ids=[entry["id"] for entry in batch],
            documents=texts,
            embeddings=vectors,
            metadatas=[entry["metadata"] for entry in batch],
        )
    return len(chunks)


def persist_index_coverage(session, version: OfficialLawVersion, xml_bytes: bytes,
                           chunks: list[dict]) -> None:
    """Persist verified Chroma upserts as relational coverage in same job transaction.

    Do not assert a history snapshot or legal applicability: official-history
    snapshots must be populated separately from a complete eflaw lookup.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    xml_hash = hashlib.sha256(xml_bytes).hexdigest()
    row = session.scalar(select(LawVersionIndex).where(
        LawVersionIndex.law_id == version.law_id,
        LawVersionIndex.mst == version.mst,
    ))
    if row is None:
        row = LawVersionIndex(
            id=str(uuid.uuid4()), law_id=version.law_id, mst=version.mst,
            list_effective_date=version.list_effective_date,
        )
        session.add(row)
    elif row.official_xml_hash and row.official_xml_hash != xml_hash:
        raise ValueError("OFFICIAL_XML_HASH_CHANGED_FOR_MST")
    row.promulgation_date = version.promulgation_date
    row.list_effective_date = version.list_effective_date
    row.history_code = version.history_code
    row.official_xml_hash = xml_hash
    row.xml_identity_status = "VERIFIED"
    row.index_status = "READY"
    row.indexed_at = now
    row.chunk_count = len(chunks)

    # Update in place: deleting and re-inserting identical unique keys in
    # one flush can violate PostgreSQL uniqueness. Preserve reviewed metadata.
    existing_coverage = {
        c.vector_id: c for c in session.scalars(select(LawArticleCoverage).where(
            LawArticleCoverage.law_id == version.law_id,
            LawArticleCoverage.mst == version.mst,
        )).all()
    }
    existing_articles = {
        c.source_vector_id: c for c in session.scalars(select(LawArticleVersion).where(
            LawArticleVersion.law_id == version.law_id,
            LawArticleVersion.mst == version.mst,
        )).all()
    }
    existing_rules = {
        c.source_vector_id: c for c in session.scalars(select(LawTransitionRule).where(
            LawTransitionRule.law_id == version.law_id,
            LawTransitionRule.mst == version.mst,
        )).all()
    }
    seen = set()
    for chunk in chunks:
        meta = chunk["metadata"]
        vector_id = chunk["id"]
        if vector_id in seen:
            raise ValueError("DUPLICATE_VECTOR_ID")
        seen.add(vector_id)
        coverage = existing_coverage.pop(vector_id, None)
        if coverage is None:
            coverage = LawArticleCoverage(
                id=str(uuid.uuid4()), law_id=version.law_id, mst=version.mst,
                vector_id=vector_id, indexed_at=now,
            )
            session.add(coverage)
        coverage.article_id = meta["article"]
        coverage.content_hash = meta["content_hash"]
        coverage.article_effective_date = meta.get("article_effective_date") or None
        coverage.effective_date_basis = meta.get("effective_date_basis")
        coverage.indexed_at = now

        if meta["article"] == "부칙":
            rule = existing_rules.pop(vector_id, None)
            if rule is None:
                rule = LawTransitionRule(
                    id=str(uuid.uuid4()), law_id=version.law_id, mst=version.mst,
                    source_vector_id=vector_id, indexed_at=now,
                )
                session.add(rule)
            rule.rule_hash = meta["content_hash"]
            rule.rule_text = chunk["content"]
            rule.promulgation_date = meta.get("promulgation_date") or None
            rule.promulgation_number = meta.get("promulgation_number") or None
            rule.indexed_at = now
        else:
            article = existing_articles.pop(vector_id, None)
            if article is None:
                article = LawArticleVersion(
                    id=str(uuid.uuid4()), law_id=version.law_id, mst=version.mst,
                    source_vector_id=vector_id, indexed_at=now,
                )
                session.add(article)
            article.article_id = meta["article"]
            article.content_hash = meta["content_hash"]
            # Preserve previously reviewed/candidate dates on re-index.
            if not article.effective_from:
                effective = meta.get("article_effective_date") or None
                article.effective_from = effective
                article.effective_date_basis = meta.get("effective_date_basis")
                article.effective_date_status = (
                    "SOURCE_DERIVED" if effective else "UNCONFIRMED"
                )
            article.indexed_at = now
    for stale in (*existing_coverage.values(), *existing_articles.values(),
                  *existing_rules.values()):
        session.delete(stale)


def enrich_article_dates_from_addenda(
    session, version: OfficialLawVersion, chunks: list[dict], *,
    llm_invoke=None,
) -> dict:
    """Optional, grounded post-index enrichment using the already fetched XML.

    The caller explicitly supplies the LLM function. No official network call
    or implicit model invocation occurs here. Candidates never become a legal
    applicability PASS and source-derived dates are never overwritten.
    """
    from ai_legal_helper.legal_knowledge.article_effective_interpreter import interpret_article_dates

    addenda = [c["content"] for c in chunks if c["metadata"]["article"] == "부칙"]
    articles = list(dict.fromkeys(
        c["metadata"]["article"] for c in chunks
        if c["metadata"]["article"] != "부칙"
    ))
    results = interpret_article_dates(
        article_ids=articles, official_addenda=addenda,
        promulgation_date=version.promulgation_date, llm_invoke=llm_invoke,
    )
    updated = 0
    unresolved = 0
    for result in results:
        rows = list(session.scalars(select(LawArticleVersion).where(
            LawArticleVersion.law_id == version.law_id,
            LawArticleVersion.mst == version.mst,
            LawArticleVersion.article_id == result.article_id,
        )).all())
        if result.status != "SOURCE_GROUNDED_CANDIDATE":
            unresolved += 1
            continue
        for row in rows:
            if row.effective_from:
                continue
            row.effective_from = result.effective_from
            row.effective_date_basis = "LLM_SOURCE_QUOTE_VERIFIED"
            row.effective_date_status = "SOURCE_GROUNDED_CANDIDATE"
            updated += 1
    return {"updated": updated, "unresolved": unresolved, "articles": len(articles)}


def process_next_job(
    session, *,
    worker_id: str, api_key: str,
    fetch_xml: Callable[[str], Optional[bytes]],
    chroma_collection, embeddings,
    article_date_llm_invoke=None,
) -> dict:
    """한 번에 작업 하나만 실행. 실패 기록 뒤 재시도 가능 상태로 전환.

    article_date_llm_invoke is opt-in; a model is never invoked by default.
    """
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
        # Fetch and validate once, then use the same immutable XML for both
        # Chroma upserts and relational coverage. No second API round-trip.
        payload = fetch_xml(build_detail_url(api_key, v))
        if not payload:
            raise ValueError("OFFICIAL_XML_FETCH_FAILED")
        chunks = official_xml_chunks(payload, v)
        # Reject a changed official body before touching Chroma.
        existing_version = session.scalar(select(LawVersionIndex).where(
            LawVersionIndex.law_id == v.law_id,
            LawVersionIndex.mst == v.mst,
        ))
        payload_hash = hashlib.sha256(payload).hexdigest()
        if (existing_version is not None and existing_version.official_xml_hash
                and existing_version.official_xml_hash != payload_hash):
            raise ValueError("OFFICIAL_XML_HASH_CHANGED_FOR_MST")
        # 법령별 관할 도메인 컬렉션 결정 (식별 시 law_docs_{category}, 미식별 시 law_docs_global)
        target_col_name = resolve_law_collection(v.law_name)
        actual_collection = chroma_collection
        if getattr(chroma_collection, "name", None) != target_col_name and hasattr(chroma_collection, "name"):
            # ChromaDB 고수준 클라이언트를 통해 실제 upsert 메서드를 보유한 Collection 모델을 획득한다.
            # chroma_collection._client는 저수준 FastAPI 클라이언트이므로 pydantic 모델(upsert 부재)을 반환하는 문제를 방지한다.
            try:
                from ai_legal_helper.rag.retrieval import _get_client
                actual_collection = _get_client().get_or_create_collection(target_col_name)
            except Exception as col_err:
                logger.warning(
                    "[INDEX_WORKER] 도메인 컬렉션({}) 획득 실패, 기본 컬렉션 유지: {}".format(
                        target_col_name, col_err
                    )
                )
                if hasattr(chroma_collection, "_client") and hasattr(chroma_collection._client, "get_or_create_collection"):
                    cand = chroma_collection._client.get_or_create_collection(target_col_name)
                    if hasattr(cand, "upsert"):
                        actual_collection = cand

        count = index_one_version(
            v, api_key=api_key, fetch_xml=lambda _url: payload,
            chroma_collection=actual_collection, embeddings=embeddings,
        )
        persist_index_coverage(session, v, payload, chunks)
        # PostgreSQL coverage is not yet committed. Recheck that Chroma
        # contains every vector ID before publishing the READY state.
        expected_ids = {entry["id"] for entry in chunks}
        if len(expected_ids) != count:
            raise ValueError("DUPLICATE_INDEXED_VECTOR_ID")
        for start in range(0, len(chunks), 200):
            batch_ids = [entry["id"] for entry in chunks[start:start + 200]]
            observed = actual_collection.get(ids=batch_ids, include=[])
            if set(observed.get("ids") or []) != set(batch_ids):
                raise ValueError("CHROMA_COVERAGE_NOT_CONFIRMED")
        # Flush first so the source rows are queryable in this transaction.
        # A failed flush is rolled back by the surrounding error handler.
        session.flush()
        if article_date_llm_invoke is not None:
            enrich_article_dates_from_addenda(
                session, v, chunks, llm_invoke=article_date_llm_invoke,
            )
        job.status = "READY"
        job.chunk_count = count
        job.error_code = None
    except Exception as exc:
        # A partial SQLAlchemy flush must never be committed as successful
        # coverage after a failed vector upsert or duplicate coverage row.
        session.rollback()
        job = session.get(OfficialLawIndexJob, job.id)
        job.error_code = type(exc).__name__[:100]
        job.status = "RETRY" if job.attempts < MAX_ATTEMPTS else "FAILED"
        logger.warning("[OFFICIAL_INDEX] job=%s error_type=%s", job.id, type(exc).__name__)
    job.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    job.finished_at = job.updated_at if job.status in ("READY", "FAILED") else None
    session.commit()
    return {"status": job.status, "job_id": job.id, "chunk_count": job.chunk_count}



def enqueue_approved_sources(sources: list[dict]) -> dict:
    """사용자 승인 완료 후 확보한 공식 법령 버전(MST)을 백그라운드 인덱싱 작업 큐에 등록한다.

    실시간 상담 스레드에서 무거운 임베딩이나 외부 API 조회를 동기 실행하지 않고,
    작업 큐(OfficialLawIndexJob)에 등록하여 독립된 Worker가 비동기로 안전하게 영구 적재하도록 한다.

    Args:
        sources: 공식 법령 검색 결과로 반환된 출처 딕셔너리 리스트.

    Returns:
        dict: 작업 등록 결과 요약 {"registered": 신규등록수, "duplicate": 중복수, "failed": 실패수}.
    """
    from ai_legal_helper.database.session import SessionLocal

    candidates = {}
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        # 법령(STATUTE) 출처만 법령 인덱싱 대상이다.
        if source.get("source_type") != "STATUTE":
            continue
        law_id = str(source.get("law_id") or "").strip()
        mst = str(source.get("version_id") or "").strip()
        name = str(source.get("statute_name") or "").strip()
        date = (
            source.get("law_effective_date")
            or source.get("article_effective_date")
            or source.get("effective_date")
            or source.get("version_date")
        )
        # 필수 식별 정보(법령ID, MST, 법령명, 시행일)가 완전히 확인된 법령만 큐에 추가
        if not (law_id and mst and name and date):
            continue
        # 모의 데이터나 결측치 문자열 배제
        if law_id.lower() in ("none", "null") or mst.lower() in ("none", "null"):
            continue

        prom_no = str(source.get("promulgation_number") or "").strip()
        if prom_no.startswith("제") and prom_no.endswith("호"):
            prom_no = prom_no[1:-1]
        candidates[(law_id, mst)] = OfficialLawVersion(
            law_id=law_id, law_name=name, mst=mst,
            law_type=str(source.get("law_type") or ""),
            promulgation_date=source.get("promulgation_date"),
            promulgation_number=prom_no,
            list_effective_date=str(date).strip(),
        )
    registered = 0
    duplicate = 0
    failed = 0
    for candidate in candidates.values():
        try:
            with SessionLocal() as session:
                _, created = enqueue_version(session, candidate)
            if created:
                registered += 1
            else:
                duplicate += 1
        except Exception as exc:
            failed += 1
            logger.warning("[OFFICIAL_INDEX] 작업 등록 실패 | law_id=%s mst=%s type=%s",
                           candidate.law_id, candidate.mst, type(exc).__name__)
    return {"registered": registered, "duplicate": duplicate, "failed": failed}


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
