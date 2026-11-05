# -*- coding: utf-8 -*-
"""
P4 시행일 기준 공식 조문·부칙 원문 검색.

반드시 기존 HILT 승인 후 official_statute_search.search_official_statutes()
경로에서 호출한다. 이 모듈은 승인 요청도, 사용자 질문에서 법령명 추측도,
원문 자동 임베딩도 하지 않는다.

[출처 보증]
- eflaw 목록을 완전히 확인하고 특정 사건일의 역사 버전 후보/인접 미래버전을
  선택한 후 각 버전을 MST+efYd로 조회한다.
- XML 본문에 법령ID/MST가 존재하면 선택 버전과 정확히 일치하는지 검증한다.
- 법령 전체 목록 시행일과 개별 조문 시행일을 분리한다.
- 공포번호가 일치하는 부칙 원문을 빠짐없이 제공한다.
- 이 단계의 날짜 판정은 '버전 검색 후보'이며 법률적 적용 확정이 아니다.
- 실제 PDF나 페이지가 존재하지 않으면 출처에 PDF·페이지를 만들지 않는다.
"""
from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from typing import Any, Callable, Optional

from ai_legal_helper.rag.source_schema import normalize_source_dict
from ai_legal_helper.tools.official_statute_versions import (
    OfficialLawVersion, _safe_xml, build_detail_url, lookup_versions_for_date,
)
from ai_legal_helper.tools.statute_temporal import (
    article_effective_date, extract_addenda, _effective_from_addendum,
)
from ai_legal_helper.legal_knowledge.law_catalog import normalize_law_name

logger = logging.getLogger(__name__)

_ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def _label(node: Any) -> str | None:
    """법제처 조문단위의 번호와 조가지번호로 고유 조문 식별자 구성."""
    number = (node.findtext("조문번호") or "").strip()
    if not number.isdigit():
        return None
    branch = (node.findtext("조문가지번호") or "").strip()
    if branch and not branch.isdigit():
        return None
    value = f"제{int(number)}조"
    if branch and int(branch):
        value += f"의{int(branch)}"
    return value


def _parts(node: Any) -> str:
    """조문내용과 하위 항/호를 수집하되 원문을 축약하지 않는다."""
    content = (node.findtext("조문내용") or "").strip()
    fragments = []
    for hang in node.findall(".//항"):
        value = (hang.findtext("항내용") or "").strip()
        if value:
            fragments.append(value)
        for ho in hang.findall(".//호"):
            value = (ho.findtext("호내용") or "").strip()
            if value:
                fragments.append(value)
    if fragments:
        content = "\n".join([content, *fragments]).strip()
    return content


def _check_detail_identity(root: Any, version: OfficialLawVersion) -> str | None:
    """본문의 MST/법령ID/법령명이 있으면 목록 메타와 교차확인한다."""
    # 공식 서비스는 기본정보를 하위 필드로 제공할 수 있으므로 상대 탐색을 사용한다.
    actual_mst = (root.findtext(".//법령일련번호") or "").strip()
    actual_id = (root.findtext(".//법령ID") or "").strip()
    actual_name = (
        root.findtext(".//법령명_한글")
        or root.findtext(".//법령명한글")
        or ""
    ).strip()
    if actual_mst and actual_mst != version.mst:
        return "DETAIL_MST_MISMATCH"
    if actual_id and actual_id != version.law_id:
        return "DETAIL_LAW_ID_MISMATCH"
    if actual_name and normalize_law_name(actual_name) != normalize_law_name(version.law_name):
        return "DETAIL_LAW_NAME_MISMATCH"
    return None


def _source(
    *,
    version: OfficialLawVersion,
    article: str,
    article_title: str,
    content: str,
    relation: str,
    as_of_date: str,
    article_date: str | None,
    date_basis: str,
    addendum_id: str | None = None,
    document_mst_confirmed: bool = False,
) -> dict[str, Any]:
    """MST+조문+내용 지문으로 유일한 공식 Source를 생성한다."""
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source_id = f"OFFICIAL:{version.law_id}:{version.mst}:{article}:{checksum[:16]}"
    # 공식 본문 XML은 PDF가 아니다. 기존 출력의 가짜 .pdf/p.1을 생성하지 않는다.
    return normalize_source_dict({
        "source_id": source_id,
        "source_type": "STATUTE",
        "document_id": f"LAW:{version.law_id}:MST:{version.mst}",
        "title": f"{version.law_name} {article} [{version.mst}]",
        "statute_name": version.law_name,
        "article": article,
        "article_title": article_title or None,
        "content": content,
        "content_hash": checksum,
        "law_id": version.law_id,
        "version_id": version.mst,
        "law_type": version.law_type or None,
        "promulgation_date": version.promulgation_date,
        "promulgation_number": f"제{version.promulgation_number}호" if
            version.promulgation_number and not version.promulgation_number.startswith("제")
            else version.promulgation_number or None,
        "law_effective_date": version.list_effective_date,
        "article_effective_date": article_date,
        "effective_date": article_date,
        "effective_date_basis": date_basis,
        "temporal_status": "EFFECTIVE_DATE_VERIFIED" if article_date else "UNCONFIRMED",
        "metadata_confidence": (
            "OFFICIAL_BODY_MST_CONFIRMED" if document_mst_confirmed
            else "OFFICIAL_LIST_MST_REQUESTED"
        ),
        "requested_as_of_date": as_of_date,
        "version_relation": relation,
        "version_lookup_status": "HISTORY_COMPLETE",
        "history_code": version.history_code or None,
        "addendum_id": addendum_id,
        "source_url": "https://www.law.go.kr/법령/" + urllib.parse.quote(version.law_name),
        "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
        "chunk_id": f"OFFICIAL:{version.mst}:{article}:{checksum[:16]}",
        "filename": None,
        "page": None,
        # 법적 효과를 검증했다는 표시가 아니다.
        "verified": False,
    })


def _relevance(query: str, title: str, content: str) -> int:
    """단순 법령 제목/본문 어휘 점수. 정책 판단을 하지 않는다."""
    from ai_legal_helper.tools.official_statute_search import extract_substantive_tokens

    tokens = extract_substantive_tokens(query)
    return sum(10 if t in title else 1 if t in content else 0 for t in tokens[:30])


def _version_sources(
    *,
    version: OfficialLawVersion,
    relation: str,
    as_of_date: str,
    requested_articles: list[str],
    query: str,
    api_key: str,
    fetch_xml: Callable[[str], Optional[bytes]],
    max_articles: int,
) -> list[dict[str, Any]] | None:
    """하나의 공식 MST 상세 본문·동일 공포번호 부칙을 수집한다.

    None은 조회/검증 실패, []는 본문은 정상이나 해당 조문이 존재하지 않음을 뜻한다.
    다른 MST나 법령의 본문은 절대 대체하지 않는다.
    """
    try:
        url = build_detail_url(api_key, version)
        raw = fetch_xml(url)
        if not raw:
            logger.warning("[OFFICIAL_P4] 본문 조회 실패 | mst=%s", version.mst)
            return None
        root = _safe_xml(raw)
        if root.tag not in ("법령", "Law", "법령정보"):
            logger.warning("[OFFICIAL_P4] 본문 XML 형태 불일치 | mst=%s", version.mst)
            return None
        mismatch = _check_detail_identity(root, version)
        if mismatch:
            logger.warning("[OFFICIAL_P4] 다른 법령/버전 본문 차단 | mst=%s code=%s",
                           version.mst, mismatch)
            return None
        document_mst_confirmed = bool((root.findtext(".//법령일련번호") or "").strip())
        articles = root.findall(".//조문단위")
        if not articles:
            return None
        addenda = extract_addenda(root, version.promulgation_number)
        candidates: list[tuple[int, Any, str, str]] = []
        requested = set(requested_articles)
        for node in articles:
            label = _label(node)
            if not label:
                continue
            if requested and label not in requested:
                continue
            content = _parts(node)
            if not content:
                continue
            title = (node.findtext("조문제목") or "").strip()
            score = 1000 if label in requested else _relevance(query, title, content)
            candidates.append((score, node, label, content))
        candidates.sort(key=lambda row: (-row[0], row[2]))
        # 명시 요청한 조문을 결과 상한보다 임의로 잘라내지 않는다.
        if requested and len(requested) > max_articles:
            logger.warning("[OFFICIAL_P4] 명시 조문이 조회 상한 초과 | mst=%s", version.mst)
            return None
        chosen = candidates[:max_articles]

        out: list[dict[str, Any]] = []
        for _, node, label, content in chosen:
            article_date, basis = article_effective_date(node, label, addenda)
            out.append(_source(
                version=version, article=label,
                article_title=(node.findtext("조문제목") or "").strip(),
                content=content, relation=relation, as_of_date=as_of_date,
                article_date=article_date, date_basis=basis,
                addendum_id=(f"{version.mst}:{version.promulgation_number}" if addenda else None),
                document_mst_confirmed=document_mst_confirmed,
            ))

        # 날짜가 중요한 질문이므로 부칙의 적용례·경과규정을 전부 확보한다.
        # 부칙 내용이 확인되지 않으면 조문 시행일이 있더라도 확정 적용 금지.
        for idx, addendum in enumerate(addenda):
            default_date = None  # unreviewed addendum: interpretation deferred
            out.append(_source(
                version=version, article="부칙",
                article_title="시행일·적용례·경과규정",
                content=addendum.content, relation=relation,
                as_of_date=as_of_date, article_date=default_date,
                date_basis="ADDENDUM_EFFECTIVE_DATE" if default_date else "UNCONFIRMED",
                addendum_id=f"{version.mst}:{version.promulgation_number}:{idx}",
                document_mst_confirmed=document_mst_confirmed,
            ))
        if requested and not {s["article"] for s in out if s["article"] != "부칙"}.issuperset(requested):
            logger.info(
                "[OFFICIAL_P4] 해당 버전에 요청 조문 일부 미존재 | mst=%s requested=%s",
                version.mst, sorted(requested),
            )
        return out
    except Exception as exc:
        logger.warning("[OFFICIAL_P4] 본문 처리 실패 | mst=%s exception=%s",
                       version.mst, type(exc).__name__)
        return None


def search_official_statutes_by_date(
    *,
    query: str,
    candidate_laws: list[str],
    as_of_date: str,
    api_key: str,
    missing_issues: Optional[list[str]] = None,
    max_articles_per_law: int = 10,
    fetch_xml: Optional[Callable[[str], Optional[bytes]]] = None,
    diagnostic: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """승인된 법령명 목록을 시행일 시점 후보별로 조회하여 표준 Source 반환.

    조회가 불완전할 때는 검색된 일부 버전만으로 단정할 수 없으므로 해당
    법령의 출처를 비워 둔다. HILT 미승인 상태로 직접 호출하면 안 된다.
    """
    from ai_legal_helper.tools.official_statute_search import (
        _prepare_search_targets, _fetch_xml_with_retry,
    )

    if not api_key or not candidate_laws or not max_articles_per_law > 0:
        return []
    if fetch_xml is None:
        # 기존 재시도 및 API 키 마스킹 활용. 호출자는 반드시 HILT 승인 후 진입.
        fetch_xml = lambda url: _fetch_xml_with_retry(url, api_key=api_key)

    collected: list[dict[str, Any]] = []
    targets = _prepare_search_targets(candidate_laws)
    for target in targets:
        # 법령명만 API에 보낸다. 사건 맥락·누락 쟁점은 조문 내부 순위화에만 사용.
        lookup = lookup_versions_for_date(
            law_name=target.law_name, as_of_date=as_of_date,
            api_key=api_key, fetch_xml=fetch_xml,
        )
        if diagnostic is not None:
            diagnostic.setdefault("lookups", []).append({
                "law_name": target.law_name, "status": lookup.status,
                "reason_code": lookup.reason_code,
            })
        if lookup.status != "CANDIDATES_FOUND":
            logger.warning("[OFFICIAL_P4] 시행일 연혁 미확인 | law=%s status=%s reason=%s",
                           target.law_name, lookup.status, lookup.reason_code)
            continue
        # The call site is reached only after existing HILT approval. Cache the
        # complete eflaw history independently of the immediate article response.
        # DB failures must not suppress already-authorized official retrieval.
        from ai_legal_helper.legal_knowledge.history_snapshot import store_approved_lookup
        snapshot_result = store_approved_lookup(lookup)
        if diagnostic is not None:
            diagnostic.setdefault("history_cache", []).append({
                "law_name": target.law_name,
                "status": snapshot_result.get("status"),
                "reason_code": snapshot_result.get("reason_code"),
            })
        version_sources: list[dict[str, Any]] = []
        okay = True
        for version in lookup.candidates:
            relation = lookup.get_role(version) if hasattr(lookup, "get_role") else lookup.roles.get(version.mst, "AS_OF_CANDIDATE")
            sources = _version_sources(
                version=version, relation=relation,
                as_of_date=as_of_date, requested_articles=target.articles,
                query=" ".join([query, *(missing_issues or [])]),
                api_key=api_key, fetch_xml=fetch_xml,
                max_articles=max_articles_per_law,
            )
            if sources is None:
                if diagnostic is not None:
                    diagnostic["api_error"] = True
                okay = False
                break
            version_sources.extend(sources)
        if not okay or not version_sources:
            logger.warning("[OFFICIAL_P4] 법령의 전체 선택 버전을 확보하지 못함 | law=%s",
                           target.law_name)
            continue
        collected.extend(version_sources)
        logger.info(
            "[OFFICIAL_P4] 승인 법령 시점 검색 완료 | law=%s versions=%s sources=%d as_of=%s",
            target.law_name, [v.mst for v in lookup.candidates],
            len(version_sources), as_of_date,
        )
    return collected
