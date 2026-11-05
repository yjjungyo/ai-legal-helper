# -*- coding: utf-8 -*-
"""
P3 공통 Law Retrieval Service — 8개 전문 Agent와 법령 저장소의 결합 해소.

[설계 이유]
기존 Agent Tool은 자신에게 할당된 law_docs_{분야}만 검색한다. 이 상태에서
주택임대차보호법을 law_docs_global에 적재하면 민법 Agent가 찾을 수 없다.
본 모듈은 동일한 검색 인터페이스에서 공통 컬렉션 및 레거시 컬렉션을
조회하고, 법령ID/조문/버전/시행일 정보의 존재 여부를 함께 반환한다.

[범위]
- Vector 검색과 출처 정규화, 법령 후보 및 검색 근거 완전성 상태 판단만 담당한다.
- OpenLaw 네트워크 호출, HILT 우회, 법률적 효력 판단, 자동 임베딩은 수행하지 않는다.
- P2 Law Catalog가 아직 적재되지 않아도 기존 Agent 검색을 중단하지 않는다.
- 전체 법률 판단의 충분성은 Verification에서 재확인해야 한다.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from ai_legal_helper.agents.constants import CATEGORY_ENG_TO_KO, to_eng
from ai_legal_helper.legal_knowledge.law_catalog import normalize_law_name
from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc
from ai_legal_helper.rag.temporal_applicability import (
    ApplicabilityStatus,
    evaluate_statute_applicability,
    parse_legal_date,
)

logger = logging.getLogger(__name__)

GLOBAL_LAW_COLLECTION = "law_docs_global"
_ARTICLE_PATTERN = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")
_CATALOG_SIGNAL = re.compile(r"(?:법률|특별법|보호법|시행령|시행규칙|민법|형법|상법|헌법|근로기준법)")
_SOURCE_ERROR_CODES = {
    "RETRIEVER_UNAVAILABLE", "EMBEDDING_ERROR", "CONFIGURATION_ERROR",
}


class LawSourceStatus(str, Enum):
    """답변에 필요한 근거의 확보 상태. '충분'은 제한된 검색 범위에서만 의미한다."""

    SOURCE_COMPLETE = "SOURCE_COMPLETE"
    SOURCE_PARTIAL = "SOURCE_PARTIAL"
    SOURCE_MISSING = "SOURCE_MISSING"
    SOURCE_VERSION_UNCONFIRMED = "SOURCE_VERSION_UNCONFIRMED"
    SOURCE_TEMPORAL_UNCONFIRMED = "SOURCE_TEMPORAL_UNCONFIRMED"
    RETRIEVAL_ERROR = "RETRIEVAL_ERROR"


@dataclass
class LawRetrievalResponse:
    """Agent와 LangGraph가 공유하는 구조화된 출처·부족 원인 기록."""

    status: LawSourceStatus
    sources: list[dict[str, Any]] = field(default_factory=list)
    missing_laws: list[str] = field(default_factory=list)
    missing_articles: list[str] = field(default_factory=list)
    collection_statuses: dict[str, str] = field(default_factory=dict)
    searched_collections: list[str] = field(default_factory=list)
    resolved_laws: list[dict[str, Any]] = field(default_factory=list)
    catalog_status: str = "NOT_REQUESTED"
    reason_codes: list[str] = field(default_factory=list)
    official_search_recommended: bool = False
    index_decisions: list[dict[str, Any]] = field(default_factory=list)
    article_temporal_decisions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_sources(self) -> bool:
        return bool(self.sources)


def _status_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _normalized_article(value: str | None) -> str:
    match = _ARTICLE_PATTERN.search(str(value or ""))
    return re.sub(r"\s+", "", match.group(0)) if match else ""


def _source_identity(source: dict) -> tuple:
    """동일 법령/버전/조문/내용을 묶되 과거·현재 다른 버전을 절대 혼합하지 않는다."""
    raw = source.get("content") or ""
    content_hash = source.get("content_hash") or hashlib.sha256(raw.encode("utf-8")).hexdigest()
    law_key = str(source.get("law_id") or normalize_law_name(source.get("statute_name") or ""))
    version_key = str(source.get("version_id") or source.get("filename_date_hint") or "UNVERSIONED")
    return (
        source.get("source_type"), law_key, version_key,
        _normalized_article(source.get("article")), str(source.get("paragraph_no") or ""),
        content_hash,
    )


def _canonical_source_id(source: dict) -> str:
    """공식 버전별 서로 다른 본문이 같은 source_id를 공유하지 않도록 한다."""
    law_id = str(source.get("law_id") or "").strip()
    version_id = str(source.get("version_id") or "").strip()
    if law_id and version_id and source.get("source_type") == "STATUTE":
        article = _normalized_article(source.get("article")) or "article"
        content_hash = source.get("content_hash") or hashlib.sha256(
            (source.get("content") or "").encode("utf-8")
        ).hexdigest()
        return f"STATUTE:{law_id}:{version_id}:{article}:{str(content_hash)[:12]}"
    return str(source.get("source_id") or "").strip()


def _source_matches_law(source: dict, law: dict) -> bool:
    """정확한 법령명 또는 공식 법령 ID가 일치한 출처만 해당 후보에 귀속한다."""
    if source.get("source_type") != "STATUTE":
        return False
    target_id = str(law.get("law_id") or "").strip()
    actual_id = str(source.get("law_id") or "").strip()
    # An officially resolved law ID must match an explicitly identified source.
    # Name-only legacy PDF chunks cannot establish official law identity.
    if target_id:
        return bool(actual_id) and target_id == actual_id
    return bool(
        normalize_law_name(source.get("statute_name") or "")
        and normalize_law_name(source.get("statute_name") or "")
        == normalize_law_name(law.get("law_name") or "")
    )


def _should_query_catalog(question: str) -> bool:
    """명시 법령명을 가진 질문에서만 DB 카탈로그 전체 이름 조회 비용을 지불한다."""
    return bool(question and _CATALOG_SIGNAL.search(question))


def _resolve_index_locally(*, law_id: str, event_date: str, event_type: str,
                           article_ids: list[str]) -> Any:
    """Read-only PostgreSQL preflight; no OpenLaw calls or embedding."""
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.legal_knowledge.law_index_resolver import LawIndexResolver

    with SessionLocal() as session:
        return LawIndexResolver(session).resolve(
            law_id=law_id, event_date=event_date, event_type=event_type,
            article_ids=article_ids,
        )


def _resolve_article_temporal_locally(*, law_id: str, event_date: str,
                                      event_type: str, article_ids: list[str]) -> Any:
    """DB-only article and addendum gate; no remote API or model calls."""
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.legal_knowledge.article_temporal_resolver import ArticleTemporalResolver

    with SessionLocal() as session:
        return ArticleTemporalResolver(session).resolve(
            law_id=law_id, event_date=event_date, event_type=event_type,
            article_ids=article_ids,
        )


def _resolve_catalog_locally(question: str) -> Any:
    """P2 로컬 카탈로그만 접근한다. DB 미설치 시 호출자가 기존 검색으로 복귀한다."""
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.legal_knowledge.catalog_store import LawCatalogStore
    from ai_legal_helper.legal_knowledge.law_resolver import LawResolver

    with SessionLocal() as session:
        return LawResolver(LawCatalogStore(session)).resolve(question)


class LawRetrievalService:
    """공통 Vector/기존 분야 Vector와 법령명 Resolver를 결합하는 경량 서비스.

    검색 함수와 카탈로그 Resolver를 주입할 수 있어 실제 Chroma/DB 없이
    단위 테스트한다. 외부 검색은 어떠한 상황에서도 이 서비스가 실행하지 않는다.
    """

    def __init__(
        self,
        *,
        retrieval_fn: Optional[Callable[..., Any]] = None,
        catalog_fn: Optional[Callable[[str], Any]] = None,
        enable_global: Optional[bool] = None,
        enable_catalog: Optional[bool] = None,
        index_fn: Optional[Callable[..., Any]] = None,
        article_temporal_fn: Optional[Callable[..., Any]] = None,
    ):
        if retrieval_fn is None:
            from ai_legal_helper.rag.retrieval import retrieve_with_status
            retrieval_fn = retrieve_with_status
        self.retrieval_fn = retrieval_fn
        self.catalog_fn = catalog_fn or _resolve_catalog_locally
        self.index_fn = index_fn or _resolve_index_locally
        self.article_temporal_fn = article_temporal_fn or _resolve_article_temporal_locally
        self.enable_global = (
            os.getenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "1") == "1"
            if enable_global is None else bool(enable_global)
        )
        self.enable_catalog = (
            os.getenv("LEGAL_CATALOG_RESOLUTION_ENABLED", "1") == "1"
            if enable_catalog is None else bool(enable_catalog)
        )

    def search(
        self,
        query: str,
        *,
        category: str,
        k: int = 2,
        original_question: Optional[str] = None,
        as_of_date: Optional[str] = None,
        required_laws: Optional[list[dict[str, str]]] = None,
        event_type: Optional[str] = None,
    ) -> LawRetrievalResponse:
        """관련 출처와 근거 불충분 상태를 계산한다.

        `category`는 기존 Agent의 8개 영문/한글 분야명이다.
        `required_laws`는 기존 계획/Resolver에서 확인된 공식 ID+이름 목록이며
        조회된 Vector 조문이 해당 법령인지 엄격히 검사한다.
        `as_of_date`는 사건의 법률적 기준일을 호출자가 명시한 경우에만 사용한다.

        P3는 실행 결과를 일반 상담 프롬프트에 제공하지만, 불충분 상태만으로
        자체적으로 OpenLaw를 요청하거나 승인 워크플로를 시작하지 않는다.
        """
        if not isinstance(query, str) or not query.strip() or k < 1:
            return LawRetrievalResponse(
                status=LawSourceStatus.SOURCE_MISSING, reason_codes=["EMPTY_QUERY"],
            )
        category_eng = to_eng(category)
        if category_eng not in CATEGORY_ENG_TO_KO:
            return LawRetrievalResponse(
                status=LawSourceStatus.RETRIEVAL_ERROR, reason_codes=["INVALID_CATEGORY"],
            )

        question = original_question or query
        response = LawRetrievalResponse(status=LawSourceStatus.SOURCE_MISSING)
        selected = list(required_laws or [])
        if selected:
            response.catalog_status = "PROVIDED_BY_CALLER"
        elif self.enable_catalog and _should_query_catalog(question):
            try:
                resolution = self.catalog_fn(question)
                response.catalog_status = str(resolution.status)
                response.resolved_laws = [item.as_dict() for item in resolution.laws]
                if resolution.status in ("FOUND", "MULTIPLE", "SUGGESTED"):
                    selected = response.resolved_laws
                elif resolution.status == "AMBIGUOUS":
                    # 같은 별칭에 복수 법령ID가 연결되면 Vector 유사도로
                    # 임의 법령을 채택하지 않는다. 검증 가능한 법령 후보가
                    # 명확해진 후 별도 조회해야 한다.
                    response.status = LawSourceStatus.SOURCE_MISSING
                    response.reason_codes.append("LAW_IDENTITY_AMBIGUOUS")
                    response.official_search_recommended = True
                    return response
            except Exception as exc:
                # 신규 DB 테이블이 아직 마이그레이션되지 않았거나 DB가 잠시 불능이어도
                # 기존 Vector 검색을 포기하지 않는다. 인증 URL/사건 자료는 로그에 남기지 않는다.
                response.catalog_status = "CATALOG_UNAVAILABLE"
                logger.warning("[LAW_RETRIEVAL] 카탈로그 조회 불가 | exception=%s",
                               type(exc).__name__)
        elif not self.enable_catalog:
            response.catalog_status = "DISABLED"

        # Index-first for explicitly resolved law identities and event semantics.
        # Unresolved law names can still use Vector for *candidate discovery*,
        # never as a verified legal basis.
        ready_mst: dict[str, str] = {}
        temporal_gate_unconfirmed = False
        if selected:
            requested_articles = list(dict.fromkeys(
                _normalized_article(x) for x in _ARTICLE_PATTERN.findall(question)
                if _normalized_article(x)
            ))
            if not as_of_date or not event_type:
                response.status = LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED
                response.reason_codes.append("EVENT_DATE_OR_TYPE_MISSING")
                response.official_search_recommended = True
                return response
            for law in selected:
                law_id = str(law.get("law_id") or "").strip()
                if not law_id:
                    response.status = LawSourceStatus.SOURCE_VERSION_UNCONFIRMED
                    response.reason_codes.append("LAW_ID_MISSING")
                    response.official_search_recommended = True
                    return response
                try:
                    decision = self.index_fn(
                        law_id=law_id, event_date=as_of_date,
                        event_type=event_type, article_ids=requested_articles,
                    )
                except Exception as exc:
                    logger.warning("[LAW_RETRIEVAL] index unavailable type=%s",
                                   type(exc).__name__)
                    response.status = LawSourceStatus.SOURCE_VERSION_UNCONFIRMED
                    response.reason_codes.append("LAW_INDEX_UNAVAILABLE")
                    response.official_search_recommended = True
                    return response
                response.index_decisions.append(decision.as_dict())
                if decision.status == "ARTICLE_BRANCH_REVIEW_REQUIRED" and decision.mst:
                    # Diagnostic-only branch review: do not expose a selected
                    # MST as a verified legal source before transition review.
                    try:
                        temporal = self.article_temporal_fn(
                            law_id=law_id, event_date=as_of_date,
                            event_type=event_type, article_ids=requested_articles,
                        )
                        response.article_temporal_decisions.append(temporal.as_dict())
                        response.reason_codes.extend(temporal.reason_codes)
                    except Exception as exc:
                        logger.warning("[LAW_RETRIEVAL] branch review unavailable type=%s",
                                       type(exc).__name__)
                        response.reason_codes.append("ARTICLE_BRANCH_GATE_UNAVAILABLE")
                    response.status = LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED
                    response.reason_codes.extend(decision.reason_codes)
                    response.reason_codes = list(dict.fromkeys(response.reason_codes))
                    response.official_search_recommended = True
                    return response
                if decision.status != "INDEX_READY_CANDIDATE" or not decision.mst:
                    response.status = LawSourceStatus.SOURCE_VERSION_UNCONFIRMED
                    response.reason_codes.extend(decision.reason_codes)
                    response.official_search_recommended = True
                    return response
                ready_mst[law_id] = decision.mst
                # Article/date applicability is separate from index availability.
                # Preserve the MST for filtered retrieval even when the
                # applicability gate requires review; never promote to PASS.
                try:
                    temporal = self.article_temporal_fn(
                        law_id=law_id, event_date=as_of_date,
                        event_type=event_type, article_ids=requested_articles,
                    )
                    response.article_temporal_decisions.append(temporal.as_dict())
                    # The resolver never asserts legal applicability; even a
                    # matching article date still requires transition review.
                    temporal_gate_unconfirmed = True
                    response.reason_codes.extend(temporal.reason_codes)
                except Exception as exc:
                    logger.warning("[LAW_RETRIEVAL] article temporal gate unavailable type=%s",
                                   type(exc).__name__)
                    temporal_gate_unconfirmed = True
                    response.reason_codes.append("ARTICLE_TEMPORAL_GATE_UNAVAILABLE")

        collections = []
        if self.enable_global:
            collections.append(GLOBAL_LAW_COLLECTION)
        collections.append(f"law_docs_{category_eng}")

        seen: set[tuple] = set()
        found: list[dict[str, Any]] = []
        failures: list[str] = []
        unavailable: list[str] = []
        # 컬렉션이 이미 전역으로 적재됐어도 같은 검색 결과를 인덱스별로 중복 반환하지 않는다.
        for collection in collections:
            response.searched_collections.append(collection)
            source_category = "global" if collection == GLOBAL_LAW_COLLECTION else category_eng
            try:
                # Chroma WHERE applies *before* top-k. Without this filter,
                # obsolete versions could occupy all result slots.
                if ready_mst:
                    clauses = [
                        {"$and": [{"law_id": law_id}, {"version_id": mst}]}
                        for law_id, mst in ready_mst.items()
                    ]
                    metadata_filter = clauses[0] if len(clauses) == 1 else {"$or": clauses}
                    ret = self.retrieval_fn(
                        query=query, category=source_category,
                        k=max(k * 2, 4), metadata_filter=metadata_filter,
                    )
                else:
                    ret = self.retrieval_fn(
                        query=query, category=source_category, k=max(k * 2, 4),
                    )
                status = _status_value(getattr(ret, "status", "RETRIEVER_UNAVAILABLE"))
                response.collection_statuses[collection] = status
                if status == "COLLECTION_MISSING":
                    unavailable.append(collection)
                elif status in _SOURCE_ERROR_CODES:
                    failures.append(collection)
                if status not in ("SUCCESS", "NO_MATCH"):
                    continue
                for doc in (getattr(ret, "documents", None) or []):
                    src = build_source_from_chroma_doc(
                        doc, category=category_eng, retrieval_method="CHROMA_VECTOR",
                    )
                    if not src.get("content") or not src.get("source_id"):
                        continue
                    # 공식 법령 후보가 확인된 질문에서 검색 상위권에 나타난
                    # 무관한 법령이 근거로 유입되지 않도록 검사한다.
                    if selected and not any(_source_matches_law(src, law) for law in selected):
                        continue
                    if ready_mst and not any(
                        _source_matches_law(src, law)
                        and str(src.get("version_id") or "") == ready_mst.get(str(law.get("law_id") or ""))
                        for law in selected
                    ):
                        # Similarity search must not reintroduce an outdated MST.
                        continue
                    src["retrieval_collection"] = collection
                    src["source_id"] = _canonical_source_id(src)
                    marker = _source_identity(src)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    found.append(src)
            except Exception as exc:
                response.collection_statuses[collection] = "RETRIEVER_UNAVAILABLE"
                failures.append(collection)
                logger.warning("[LAW_RETRIEVAL] 벡터 검색 장애 | collection=%s exception=%s",
                               collection, type(exc).__name__)

        # 복합 질문에서 첫 번째 법령이 모든 slot을 채워 다른 법령을
        # 누락시키지 않도록 요청 법령마다 최소 1건씩 먼저 배정한다.
        # 동일 law/버전이 중복되어도 위 fingerprint로 이미 제거했다.
        prioritized = []
        if selected:
            for law in selected:
                candidate = next(
                    (src for src in found
                     if _source_matches_law(src, law) and src not in prioritized),
                    None,
                )
                if candidate is not None:
                    prioritized.append(candidate)
        prioritized.extend(src for src in found if src not in prioritized)
        response.sources = prioritized[:k]
        if unavailable:
            response.reason_codes.append("COLLECTION_MISSING")
        if failures:
            response.reason_codes.append("RETRIEVAL_INFRA_ERROR")

        if not response.sources:
            response.status = (
                LawSourceStatus.RETRIEVAL_ERROR
                if failures or (len(unavailable) == len(collections))
                else LawSourceStatus.SOURCE_MISSING
            )
            response.missing_laws = [str(law.get("law_name") or "") for law in selected]
            response.reason_codes.append(
                "VECTOR_UNAVAILABLE" if response.status == LawSourceStatus.RETRIEVAL_ERROR
                else "NO_RELEVANT_VECTOR_SOURCE"
            )
        elif failures:
            response.status = LawSourceStatus.SOURCE_PARTIAL
        elif not selected:
            # 법령명 후보를 찾지 못하고 Vector만 조회한 경우 전체 질문에 필요한
            # 법령이 확보됐다고 가정하지 않는다.
            response.status = LawSourceStatus.SOURCE_PARTIAL
            response.reason_codes.append("LEGAL_ISSUES_NOT_FULLY_RESOLVED")
        else:
            present = {
                str(law.get("law_name") or ""): any(
                    _source_matches_law(src, law) for src in response.sources
                ) for law in selected
            }
            response.missing_laws = [name for name, hit in present.items() if not hit]
            if response.missing_laws:
                response.status = LawSourceStatus.SOURCE_PARTIAL
                response.reason_codes.append("REQUIRED_LAW_NOT_RETRIEVED")
            else:
                requested_articles = {
                    _normalized_article(x) for x in _ARTICLE_PATTERN.findall(question)
                }
                # 복수 법령 질문에서 A법의 제3조를 찾았다고 B법의 제3조까지
                # 확보된 것으로 간주하지 않는다. 법령ID × 조문 단위로 점검한다.
                response.missing_articles = sorted({
                    f"{law.get('law_name') or law.get('law_id')}:{article}"
                    for law in selected for article in requested_articles
                    if not any(
                        _source_matches_law(src, law)
                        and _normalized_article(src.get("article")) == article
                        for src in response.sources
                    )
                })
                if response.missing_articles:
                    response.status = LawSourceStatus.SOURCE_PARTIAL
                    response.reason_codes.append("REQUIRED_ARTICLE_NOT_RETRIEVED")
                elif any(
                    not src.get("version_id") or (
                        not ready_mst and law.get("current_mst")
                        and _source_matches_law(src, law)
                        and str(src.get("version_id") or "") != str(law["current_mst"])
                    )
                    for src in response.sources for law in selected
                    if _source_matches_law(src, law)
                ):
                    response.status = LawSourceStatus.SOURCE_VERSION_UNCONFIRMED
                    response.reason_codes.append("VERSION_NOT_CURRENTLY_CONFIRMED")
                elif requested_articles:
                    # 특정 조문이 검색되었다는 것과 그 조문이 사건에 적용된다는
                    # 판단은 별개다. 날짜 요청 시 반드시 아래 Temporal Gate 수행.
                    response.status = LawSourceStatus.SOURCE_COMPLETE
                else:
                    response.status = LawSourceStatus.SOURCE_PARTIAL
                    response.reason_codes.append("ARTICLE_SCOPE_UNCONFIRMED")

        # 모든 법령 검색 결과에 시점 검증 상태를 부여한다.
        # 사건 기준일이 없는 경우에도 SOURCE_COMPLETE로 승격하지 않는다.
        valid_as_of = parse_legal_date(as_of_date) if as_of_date else None
        if response.sources:
            temporal_unconfirmed = False
            for src in response.sources:
                if src.get("source_type") != "STATUTE":
                    continue
                src["requested_as_of_date"] = valid_as_of.isoformat() if valid_as_of else None
                if valid_as_of is None:
                    src["applicability_status"] = "UNCONFIRMED"
                    temporal_unconfirmed = True
                    continue
                applicability = evaluate_statute_applicability(src, valid_as_of.isoformat())
                src["applicability_status"] = _status_value(applicability.status)
                src["applicability_reason"] = applicability.reason_code
                # A basic date comparison is not an addendum/transition review.
                # Do not expose an APPLICABLE source label when the stricter
                # article-level resolver has not established legal applicability.
                if temporal_gate_unconfirmed and ready_mst:
                    src["applicability_status"] = "UNCONFIRMED"
                    src["applicability_reason"] = "ARTICLE_TRANSITION_REVIEW_REQUIRED"
                    temporal_unconfirmed = True
                if applicability.status is not ApplicabilityStatus.APPLICABLE:
                    temporal_unconfirmed = True
            if temporal_unconfirmed and response.status not in (
                LawSourceStatus.RETRIEVAL_ERROR, LawSourceStatus.SOURCE_MISSING,
            ):
                response.status = LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED
                response.reason_codes.append(
                    "EVENT_DATE_REQUIRED" if valid_as_of is None
                    else "TEMPORAL_LEGAL_REVIEW_REQUIRED"
                )
        if temporal_gate_unconfirmed and response.status not in (
            LawSourceStatus.RETRIEVAL_ERROR, LawSourceStatus.SOURCE_MISSING,
            LawSourceStatus.SOURCE_VERSION_UNCONFIRMED,
        ):
            response.status = LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED
            response.reason_codes.append("ARTICLE_TEMPORAL_APPLICABILITY_NOT_CONFIRMED")
        response.reason_codes = list(dict.fromkeys(response.reason_codes))
        # Temporal legal review is not the same as missing official sources.
        # Avoid repeatedly requesting the same official law when indexed
        # article and addendum texts are already available locally.
        local_temporal_review_only = (
            bool(response.article_temporal_decisions)
            and len(response.article_temporal_decisions) == len(ready_mst)
            and all(item.get("status") == "TEMPORAL_REVIEW_REQUIRED"
                    for item in response.article_temporal_decisions)
            and bool(response.sources)
            and not response.missing_laws
            and not response.missing_articles
            and not failures and not unavailable
        )
        response.official_search_recommended = (
            response.status in (
                LawSourceStatus.SOURCE_PARTIAL,
                LawSourceStatus.SOURCE_MISSING,
                LawSourceStatus.SOURCE_VERSION_UNCONFIRMED,
                LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED,
            )
            and not local_temporal_review_only
        )
        # Infrastructure failures are not proof that a law is absent.
        if response.status == LawSourceStatus.RETRIEVAL_ERROR or failures:
            response.official_search_recommended = False
        logger.info(
            "[LAW_RETRIEVAL] status=%s category=%s source_count=%d "
            "catalog=%s collection_statuses=%s reason_codes=%s",
            response.status.value, category_eng, len(response.sources),
            response.catalog_status, response.collection_statuses, response.reason_codes,
        )
        return response
