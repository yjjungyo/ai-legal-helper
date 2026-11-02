# -*- coding: utf-8 -*-
"""
P2 공식 법령 목록 XML 파서 및 조회 클라이언트.

[목적]
대한민국 법제처 API의 '법령 목록'을 읽고 정식 법령명·법령ID·공식 약칭을
LLM과 독립적으로 확보한다. 법령 '본문' 검색 또는 시행일 적용 판단은 하지 않는다.

[안전 원칙]
- law_id(지속 법령 식별자)와 MST(목록의 특정 버전 일련번호)를 혼동하지 않는다.
- 시행일은 **목록의 표시 값**으로만 보관한다. 조문 적용 판단 근거가 아니다.
- 오류·빈 응답·비정상 XML을 완료된 카탈로그로 표시하지 않는다.
- API 인증값은 URL/로그/예외 메시지에 노출하지 않는다.
- 단순 이름 검색은 외부로 사건 내용이나 사용자 질문을 보내지 않는다.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable, Optional

from ai_legal_helper.rag.temporal_applicability import parse_legal_date

logger = logging.getLogger(__name__)

_BASE = "https://www.law.go.kr/DRF/lawSearch.do"
_MAX_XML_BYTES = 4 * 1024 * 1024
_MAX_PAGE = 1000


class CatalogError(Exception):
    """법령 목록 요청·파싱 실패를 정상 검색 결과 없음과 구별한다."""


class CatalogFetchError(CatalogError):
    """공식 API 응답을 정상적으로 확보하지 못했다."""


class CatalogParseError(CatalogError):
    """공식 API 응답이 지원되는 법령 목록 XML이 아니다."""


def normalize_law_name(value: str) -> str:
    """공백·기본 구두점만 무시하는 법령명 색인 키를 생성한다.

    조사가 섞인 질문 전체를 그대로 정규화하여 짧은 법 이름을 무작정 부분
    매칭하는 데 사용하면 '민법'과 '난민법'을 혼동하므로 Resolver가 별도
    단어 경계 검사를 수행한다.
    """
    return re.sub(r"[^가-힣A-Za-z0-9]", "", value or "").lower()


def _iso(raw: str | None) -> Optional[str]:
    """공식 목록 날짜를 파싱하되 유효하지 않으면 NULL을 남긴다."""
    parsed = parse_legal_date(raw)
    return parsed.isoformat() if parsed else None


@dataclass(frozen=True)
class LawCatalogItem:
    """공식 목록 한 건. 법령명 검증 및 검색 후보 도출에만 사용한다."""

    law_id: str
    official_name: str
    law_type: str = ""
    mst: str = ""
    short_name: str = ""
    promulgation_date: Optional[str] = None
    list_effective_date: Optional[str] = None
    promulgation_number: str = ""
    ministry_name: str = ""
    history_code: str = ""
    detail_url: str = ""

    @property
    def name_key(self) -> str:
        return normalize_law_name(self.official_name)


@dataclass(frozen=True)
class LawCatalogPage:
    """목록 전체 건수·페이지를 함께 보존하여 부분 동기화를 구분한다."""

    page: int
    total_count: Optional[int]
    returned_count: int
    skipped_count: int
    items: tuple[LawCatalogItem, ...]


def _field(node: ET.Element, tag: str) -> str:
    return (node.findtext(tag) or "").strip()


def parse_law_catalog_page(data: bytes, *, expected_page: int = 1) -> LawCatalogPage:
    """법제처 lawSearch.do?target=law XML에서 검증 가능한 법령 목록을 추출한다.

    법령명이 있어도 공식 법령ID가 없다면 임의 ID를 만들지 않고 건너뛴다.
    결과 총건수가 없는 응답은 부분 조회에는 활용할 수 있지만 전체 동기화 완료
    근거로는 인정하지 않는다.
    """
    if not data or len(data) > _MAX_XML_BYTES:
        raise CatalogParseError("EMPTY_OR_OVERSIZED_XML")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise CatalogParseError("XML_ENTITY_DECLARATION_BLOCKED")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise CatalogParseError("INVALID_XML") from exc
    if root.tag != "LawSearch":
        raise CatalogParseError("UNEXPECTED_XML_ROOT")
    total_raw = _field(root, "totalCnt")
    page_raw = _field(root, "page")
    try:
        total = int(total_raw) if total_raw else None
        page = int(page_raw) if page_raw else expected_page
    except ValueError as exc:
        raise CatalogParseError("INVALID_PAGINATION_METADATA") from exc
    if total is not None and total < 0:
        raise CatalogParseError("NEGATIVE_TOTAL_COUNT")
    if page != expected_page:
        raise CatalogParseError("PAGE_MISMATCH")

    items: list[LawCatalogItem] = []
    records = root.findall(".//law")
    for node in records:
        name = _field(node, "법령명한글")
        law_id = _field(node, "법령ID")
        if not name or not law_id or len(law_id) > 64 or len(name) > 500:
            continue
        # 링크는 표시용 공식 도메인 주소만 채택한다. 비공식 링크·상대경로는 버린다.
        raw_url = _field(node, "법령상세링크")
        raw_url = raw_url.replace("http://www.law.go.kr/", "https://www.law.go.kr/", 1)
        detail_url = raw_url if raw_url.startswith("https://www.law.go.kr/") else ""
        items.append(LawCatalogItem(
            law_id=law_id,
            official_name=name,
            law_type=_field(node, "법령구분명"),
            mst=_field(node, "법령일련번호"),
            short_name=_field(node, "법령약칭명"),
            promulgation_date=_iso(_field(node, "공포일자")),
            list_effective_date=_iso(_field(node, "시행일자")),
            promulgation_number=_field(node, "공포번호"),
            ministry_name=_field(node, "소관부처명"),
            history_code=_field(node, "현행연혁코드"),
            detail_url=detail_url,
        ))
    return LawCatalogPage(
        page=page,
        total_count=total,
        returned_count=len(records),
        skipped_count=len(records) - len(items),
        items=tuple(items),
    )


def build_law_catalog_url(api_key: str, page: int, *, query: Optional[str] = None) -> str:
    """공식 API가 문서화한 display=100/page 파라미터를 사용한다."""
    if not api_key:
        raise CatalogFetchError("LAW_OPENAPI_KEY_MISSING")
    if not isinstance(page, int) or not 1 <= page <= _MAX_PAGE:
        raise ValueError("INVALID_PAGE")
    params = {"OC": api_key, "target": "law", "type": "XML", "display": "100", "page": str(page)}
    if query is not None:
        query = query.strip()
        if not query or len(query) > 100:
            raise ValueError("INVALID_SEARCH_TERM")
        params["query"] = query
    return f"{_BASE}?{urllib.parse.urlencode(params)}"


def fetch_law_catalog_page(
    page: int,
    *,
    api_key: str,
    query: Optional[str] = None,
    fetch_xml: Optional[Callable[[str], Optional[bytes]]] = None,
) -> LawCatalogPage:
    """명시적 호출에서만 공식 목록을 조회한다. Agent 런타임에서 자동 실행 금지.

    fetch_xml 주입은 네트워크/인증키 비노출 회귀 테스트용이다.
    """
    url = build_law_catalog_url(api_key, page, query=query)
    if fetch_xml is None:
        from ai_legal_helper.tools.official_statute_search import _fetch_xml_with_retry
        fetch_xml = lambda request_url: _fetch_xml_with_retry(request_url, api_key=api_key)
    try:
        response = fetch_xml(url)
    except Exception as exc:
        logger.warning("[LAW_CATALOG] 목록 조회 오류 | page=%d | type=%s", page, type(exc).__name__)
        raise CatalogFetchError("OFFICIAL_CATALOG_FETCH_FAILED") from exc
    if not response:
        raise CatalogFetchError("OFFICIAL_CATALOG_EMPTY_RESPONSE")
    return parse_law_catalog_page(response, expected_page=page)
