# -*- coding: utf-8 -*-
"""
P4: 법제처 '시행일 기준' 법령 목록에서 버전(MST)을 안전하게 선별한다.

[공식 API 사양]
- 법령 목록: /DRF/lawSearch.do?target=eflaw&type=XML
- law_id가 있으면 LID로 정확히 식별. 없다면 법령명 query로 조회한 후
  정식 이름의 완전 일치를 검증한다.
- nw=1,2,3: 연혁/시행예정/현행을 함께 수집
- 본문은 /DRF/lawService.do?target=eflaw&MST=...&efYd=... 로 조회한다.

[안전]
- 이 모듈이 반환하는 것은 검색할 '버전 후보'이지 법률상 적용 확정이 아니다.
- 목록 시행일은 조문별 시행일/부칙 적용례를 대신하지 않는다.
- totalCnt 누락, 미조회 페이지, 중복 MST, 동일 시행일 다중 MST, 날짜
  파싱 실패는 확인 가능한 후보를 만들어내지 않고 UNCONFIRMED로 보류한다.
- 법령명/ID 검증 없이 검색 결과 첫 항목을 임의 채택하지 않는다.
- 사용자 원문/사건정보는 목록 API에 전달하지 않는다.
"""
from __future__ import annotations

import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ai_legal_helper.rag.temporal_applicability import parse_legal_date
from ai_legal_helper.legal_knowledge.law_catalog import normalize_law_name

logger = logging.getLogger(__name__)
_SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
_DETAIL_URL = "https://www.law.go.kr/DRF/lawService.do"
_MAX_PAGES = 20
_MAX_XML_BYTES = 8 * 1024 * 1024
_IDENT_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


@dataclass(frozen=True)
class OfficialLawVersion:
    """공식 시행일 목록의 한 MST 기록; 특정 조문의 효력 판단 근거가 아니다."""

    law_id: str
    law_name: str
    mst: str
    law_type: str
    promulgation_date: str | None
    promulgation_number: str
    list_effective_date: str
    history_code: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "law_id": self.law_id,
            "law_name": self.law_name,
            "mst": self.mst,
            "law_type": self.law_type,
            "promulgation_date": self.promulgation_date,
            "promulgation_number": self.promulgation_number,
            "list_effective_date": self.list_effective_date,
            "history_code": self.history_code,
        }


@dataclass
class VersionLookup:
    """모든 페이지를 검증한 결과와 특정 기준일에 대한 후보 목록."""

    status: str
    versions: list[OfficialLawVersion] = field(default_factory=list)
    candidates: list[OfficialLawVersion] = field(default_factory=list)
    roles: dict[str, str] = field(default_factory=dict)
    total_count: int | None = None
    pages_fetched: int = 0
    reason_code: str = ""


def _valid_date(value: str | None) -> str | None:
    parsed = parse_legal_date(value)
    return parsed.isoformat() if parsed else None


def _safe_xml(payload: bytes) -> ET.Element:
    """XML 엔티티/DOCTYPE 및 비정상 본문을 거부한다."""
    if not payload or len(payload) > _MAX_XML_BYTES:
        raise ValueError("EMPTY_OR_OVERSIZED_XML")
    upper = payload.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("XML_ENTITY_DECLARATION_BLOCKED")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("MALFORMED_XML") from exc


def _field(node: ET.Element, name: str) -> str:
    return (node.findtext(name) or "").strip()


def build_history_url(
    api_key: str, *, page: int, law_id: str | None = None,
    law_name: str | None = None,
) -> str:
    """문서화된 시행일 법령목록 API 파라미터만 사용한다."""
    if not api_key:
        raise ValueError("LAW_OPENAPI_KEY_MISSING")
    if not 1 <= page <= _MAX_PAGES:
        raise ValueError("INVALID_PAGE")
    if law_id and not _IDENT_RE.fullmatch(law_id):
        raise ValueError("INVALID_LAW_ID")
    if not law_id and (not law_name or len(law_name.strip()) > 200):
        raise ValueError("INVALID_LAW_NAME")
    params = {
        "OC": api_key,
        "target": "eflaw",
        "type": "XML",
        "display": "100",
        "page": str(page),
        "nw": "1,2,3",
    }
    if law_id:
        params["LID"] = law_id
    else:
        params["query"] = law_name.strip()
    return _SEARCH_URL + "?" + urllib.parse.urlencode(params)


def build_detail_url(api_key: str, version: OfficialLawVersion) -> str:
    """시행일 목록에서 확보한 MST + 목록 시행일을 지정하여 정확한 XML 본문 조회."""
    if not api_key:
        raise ValueError("LAW_OPENAPI_KEY_MISSING")
    if not _IDENT_RE.fullmatch(version.mst):
        raise ValueError("INVALID_MST")
    parsed = parse_legal_date(version.list_effective_date)
    if parsed is None:
        raise ValueError("INVALID_VERSION_EFFECTIVE_DATE")
    return _DETAIL_URL + "?" + urllib.parse.urlencode({
        "OC": api_key, "target": "eflaw", "type": "XML",
        "MST": version.mst, "efYd": parsed.strftime("%Y%m%d"),
    })


def _read_history_page(
    payload: bytes, *,
    page: int, law_id: str | None, law_name: str,
) -> tuple[int, int, list[OfficialLawVersion], int]:
    """한 페이지에서 총건수, 실제 law 행 수, 유효한 정확일치 후보를 반환."""
    root = _safe_xml(payload)
    if root.tag != "LawSearch":
        raise ValueError("UNEXPECTED_LIST_ROOT")
    total_raw = _field(root, "totalCnt")
    current_raw = _field(root, "page")
    if not total_raw or not current_raw:
        raise ValueError("PAGINATION_UNCONFIRMED")
    try:
        total, current = int(total_raw), int(current_raw)
    except ValueError as exc:
        raise ValueError("INVALID_PAGINATION") from exc
    if current != page or total < 0:
        raise ValueError("PAGE_OR_TOTAL_MISMATCH")
    rows = root.findall(".//law")
    versions: list[OfficialLawVersion] = []
    skipped = 0
    for row in rows:
        name = _field(row, "법령명한글")
        identifier = _field(row, "법령ID")
        # API에서 exact 법령ID를 받더라도 이름이 다르면 응답/검색오류다.
        if law_id and identifier != law_id:
            skipped += 1
            continue
        if normalize_law_name(name) != normalize_law_name(law_name):
            skipped += 1
            continue
        mst = _field(row, "법령일련번호") or _field(row, "일련번호")
        raw_eff = _field(row, "시행일자")
        raw_prom = _field(row, "공포일자")
        eff = _valid_date(raw_eff)
        prom = _valid_date(raw_prom) if raw_prom else None
        if not identifier or not mst or not _IDENT_RE.fullmatch(mst) or not eff or (raw_prom and not prom):
            # 불완전/비정상 버전을 수집하지 않고 상위에서 전체 결과를 미확인 처리.
            raise ValueError("INVALID_OFFICIAL_VERSION_METADATA")
        versions.append(OfficialLawVersion(
            law_id=identifier, law_name=name, mst=mst,
            law_type=_field(row, "법령구분명"),
            promulgation_date=prom,
            promulgation_number=_field(row, "공포번호"),
            list_effective_date=eff,
            history_code=_field(row, "현행연혁코드"),
        ))
    return total, len(rows), versions, skipped


def select_versions_at_date(
    versions: list[OfficialLawVersion], as_of_date: str,
) -> VersionLookup:
    """시행일 기준 가장 가까운 1개 과거/현재 버전과 가까운 시행예정 버전 선택.

    단, 동일 시행일의 서로 다른 MST나 사건일 이후 공포한 소급 적용 후보가
    개입하면 일의적으로 확정할 수 없으므로 버전 선택 전체를 보류한다.
    """
    target = parse_legal_date(as_of_date)
    if target is None:
        return VersionLookup("UNCONFIRMED", reason_code="INVALID_AS_OF_DATE")
    if not versions:
        return VersionLookup("NOT_FOUND", reason_code="NO_EXACT_STATUTE_HISTORY")

    parsed: list[tuple[OfficialLawVersion, Any]] = []
    for version in versions:
        effective = parse_legal_date(version.list_effective_date)
        promulgated = parse_legal_date(version.promulgation_date) if version.promulgation_date else None
        if not effective or not promulgated:
            return VersionLookup("UNCONFIRMED", versions=versions,
                                 reason_code="HISTORY_DATE_METADATA_MISSING")
        # 소급효를 가진 개정이 사건 이후 공포되면 단순 시행일순으로
        # 과거 당시 적용 법령을 선택할 수 없으므로 검토를 중단한다.
        if effective <= target and promulgated > target:
            return VersionLookup("UNCONFIRMED", versions=versions,
                                 reason_code="RETROACTIVE_AMENDMENT_REVIEW_REQUIRED")
        parsed.append((version, effective))

    earlier = [(v, d) for v, d in parsed if d <= target]
    upcoming = [(v, d) for v, d in parsed if d > target]
    if not earlier:
        return VersionLookup("UNCONFIRMED", versions=versions,
                             reason_code="NO_VERSION_EFFECTIVE_BY_AS_OF_DATE")
    anchor_date = max(d for _, d in earlier)
    anchors = [v for v, d in earlier if d == anchor_date]
    if len({v.mst for v in anchors}) != 1:
        return VersionLookup("UNCONFIRMED", versions=versions,
                             reason_code="MULTIPLE_VERSIONS_SAME_EFFECTIVE_DATE")

    chosen = [anchors[0]]
    roles = {anchors[0].mst: "AS_OF_CANDIDATE"}
    if upcoming:
        next_date = min(d for _, d in upcoming)
        future = [v for v, d in upcoming if d == next_date]
        if len({v.mst for v in future}) != 1:
            return VersionLookup("UNCONFIRMED", versions=versions,
                                 reason_code="MULTIPLE_FUTURE_VERSIONS_SAME_DATE")
        chosen.append(future[0])
        roles[future[0].mst] = "NEXT_EFFECTIVE_CANDIDATE"

    return VersionLookup(
        status="CANDIDATES_FOUND", versions=versions, candidates=chosen,
        roles=roles, reason_code="APPLICATION_REQUIRES_ADDENDA_REVIEW",
    )


def lookup_versions_for_date(
    *,
    law_name: str, as_of_date: str, api_key: str,
    law_id: str | None = None,
    fetch_xml: Callable[[str], Optional[bytes]],
    max_pages: int = _MAX_PAGES,
) -> VersionLookup:
    """명시 승인된 공식검색에서만 호출; 끝까지 검증한 목록만 버전 선별."""

    if not parse_legal_date(as_of_date):
        return VersionLookup("UNCONFIRMED", reason_code="INVALID_AS_OF_DATE")
    if not law_name or not normalize_law_name(law_name):
        return VersionLookup("UNCONFIRMED", reason_code="INVALID_LAW_NAME")
    if not api_key:
        return VersionLookup("UNCONFIRMED", reason_code="LAW_OPENAPI_KEY_MISSING")

    versions: list[OfficialLawVersion] = []
    total_expected: int | None = None
    seen_count = 0
    skipped_count = 0
    seen_mst: set[str] = set()
    pages = 0
    limit = min(max(1, max_pages), _MAX_PAGES)
    for page in range(1, limit + 1):
        try:
            url = build_history_url(api_key, page=page, law_id=law_id, law_name=law_name)
            raw = fetch_xml(url)
            if not raw:
                raise ValueError("OFFICIAL_HISTORY_EMPTY_RESPONSE")
            total, row_count, items, skipped = _read_history_page(
                raw, page=page, law_id=law_id, law_name=law_name,
            )
            if total_expected is None:
                total_expected = total
            if total != total_expected:
                raise ValueError("HISTORY_TOTAL_CHANGED_DURING_PAGINATION")
            if row_count == 0 and seen_count < total:
                raise ValueError("HISTORY_PREMATURE_EMPTY_PAGE")
            for item in items:
                if item.mst in seen_mst:
                    raise ValueError("DUPLICATE_MST_IN_OFFICIAL_HISTORY")
                seen_mst.add(item.mst)
                versions.append(item)
            skipped_count += skipped
            seen_count += row_count
            pages += 1
            if seen_count >= total:
                break
        except (ValueError, OSError) as exc:
            logger.warning("[OFFICIAL_HISTORY] 목록 확인 실패 | page=%d reason=%s",
                           page, type(exc).__name__)
            return VersionLookup(
                "UNCONFIRMED", versions=versions, total_count=total_expected,
                pages_fetched=pages, reason_code=str(exc) if isinstance(exc, ValueError)
                else "HISTORY_NETWORK_ERROR",
            )
        except Exception as exc:
            logger.warning("[OFFICIAL_HISTORY] 조회 장애 | page=%d exception=%s",
                           page, type(exc).__name__)
            return VersionLookup(
                "UNCONFIRMED", versions=versions, total_count=total_expected,
                pages_fetched=pages, reason_code="HISTORY_UNAVAILABLE",
            )

    if total_expected is None or seen_count != total_expected:
        return VersionLookup(
            "UNCONFIRMED", versions=versions, total_count=total_expected,
            pages_fetched=pages, reason_code="INCOMPLETE_OFFICIAL_HISTORY",
        )
    if skipped_count and law_id:
        # 법령ID를 명시했는데 다른 법령이 섞여 오는 것은 검색 결과 불일치다.
        return VersionLookup("UNCONFIRMED", versions=versions,
                             total_count=total_expected, pages_fetched=pages,
                             reason_code="LAW_ID_OR_NAME_MISMATCH")
    if len({v.law_id for v in versions}) > 1:
        return VersionLookup("UNCONFIRMED", versions=versions,
                             total_count=total_expected, pages_fetched=pages,
                             reason_code="AMBIGUOUS_OFFICIAL_LAW_ID")
    result = select_versions_at_date(versions, as_of_date)
    result.total_count = total_expected
    result.pages_fetched = pages
    return result
