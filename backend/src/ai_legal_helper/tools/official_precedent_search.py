# -*- coding: utf-8 -*-
"""법제처 국가법령정보 공동활용: 판례 목록 검색 → 공식 판결 원문 조회.

[PRECEDENT-03 / Gemini+ChatGPT 인계]
- STATUTE(조문/부칙/시행일) 검색과 PRECEDENT(판시사항/요지/원문)를 혼용하지 않는다.
- lawSearch.do?target=prec&search=2 로 *목록만* 조회해서는 판례 Source를
  만들 수 없다. 목록에서 취득한 ID로 lawService.do?target=prec&ID=..를
  다시 조회하고 일련번호·사건번호·법원을 검증한 후에만 인용 가능한 Source 생성.
- 판례가 존재한다는 사실은 해당 사건에 판례 법리가 적용된다는 의미가 아니다.
  이 적용 판단은 Synthesizer/Verifier와 후속 4단계 법률요건 포섭의 책임이다.
- 외부 API로 사건 원문/계약서/사용자 이름을 전송하지 않는다. Verifier가
  별도 출력한 짧은 '일반 법률 개념 검색어'만 허용한다.
- 조회 실패/불완전 결과는 빈 목록. 허위 출처 생성 및 LLM 지식 폴백 금지.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html import unescape
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode
from typing import Any, Callable

from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.observability.pii_masker import mask_pii
from ai_legal_helper.rag.source_schema import normalize_source_dict
from ai_legal_helper.tools.official_statute_search import _fetch_xml_with_retry

logger = get_logger(__name__)
_LIST_URL = "https://www.law.go.kr/DRF/lawSearch.do"
_DETAIL_URL = "https://www.law.go.kr/DRF/lawService.do"
_MAX_RESPONSE = 2_000_000
_CASE_NUMBER = re.compile(r"^\d{2,4}[가-힣]{1,4}\d+[가-힣0-9,]*$")


def normalize_precedent_query(query: str) -> str:
    """법적 쟁점 일반명사만 전송. 개인식별 값·문장·시나리오 메타데이터는 거부.

    완벽한 한국어 인명 인식기가 아니므로 이 함수는 *외부 전송 허용 게이트*
    에 그치며, 생성 프롬프트가 개인정보 없는 법리 검색어만 내야 한다.
    문장/파일명/계약일/계좌/사건 일련번호를 쿼리로 조립하지 않는다.
    """
    if not isinstance(query, str):
        return ""
    q = " ".join(query.split()).strip()
    if not (4 <= len(q) <= 95) or q != mask_pii(q):
        return ""
    if re.search(r"\d|[@/\\]|[.?？！!;:]|[\[\]{}()]", q):
        return ""
    parts = q.split()
    if not (2 <= len(parts) <= 7):
        return ""
    # 외부 전송 전에 문자 범위를 한글/영문 일반 검색어로 제한.
    if not all(re.fullmatch(r"[가-힣A-Za-z]+", p) and 2 <= len(p) <= 22 for p in parts):
        return ""
    return " ".join(parts)


def _field(node: ET.Element, *names: str) -> str:
    for name in names:
        found = node.find(name)
        if found is not None:
            text = "".join(found.itertext()).strip()
            if text:
                return text
    return ""


def _xml(raw: bytes | None) -> ET.Element | None:
    if not raw or len(raw) > _MAX_RESPONSE:
        return None
    try:
        return ET.fromstring(raw)
    except (ET.ParseError, ValueError):
        return None


def _list_hits(root: ET.Element) -> list[dict[str, str]]:
    """목록 응답은 <prec id='...'>와 판례일련번호를 모두 지원한다."""
    hits = []
    for node in root.iter():
        if node.tag.lower() not in ("prec", "판례"):
            continue
        number = _field(node, "판례일련번호", "판례정보일련번호") or node.attrib.get("id", "")
        if not number.isdigit():
            continue
        hits.append({
            "id": number,
            "case_number": _field(node, "사건번호"),
            "court": _field(node, "법원명"),
        })
    return hits


def _plain(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _date(raw: str) -> str | None:
    numbers = re.sub(r"[^0-9]", "", raw)
    if len(numbers) != 8:
        return None
    try:
        return datetime.strptime(numbers, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def parse_precedent_detail(payload: bytes | None, *, expected_id: str) -> dict[str, Any] | None:
    """원문 ID/사건번호 검증 완료 후 PRECEDENT Source 생성.

    판례 상세조회 XML의 실제 메타/판시사항/요지/원문만 사용한다.
    미존재 사건번호를 추측해 만들지 않고, 목록 메타만으로 내용 생성하지 않는다.
    """
    root = _xml(payload)
    if root is None:
        return None
    seq = _field(root, "판례정보일련번호", "판례일련번호") or root.attrib.get("id", "")
    cn = _field(root, "사건번호")
    court = _field(root, "법원명")
    decided = _date(_field(root, "선고일자"))
    if not (seq.isdigit() and seq == expected_id and cn and _CASE_NUMBER.fullmatch(cn.replace(" ", "")) and court and decided):
        return None
    points = _plain(_field(root, "판시사항"))
    summary = _plain(_field(root, "판결요지"))
    body = _plain(_field(root, "판례내용"))
    # 반환된 사건명만 있고 판시·요지·본문이 모두 공란이면 인용 가능한 법리 없음.
    if not (points or summary or body):
        return None
    # Verifier에게 판결요지/판시사항을 선두 제공, 원문은 bounded payload.
    sections = [
        f"[판시사항] {points}" if points else "",
        f"[판결요지] {summary}" if summary else "",
        f"[판결원문] {body[:8000]}" if body else "",
    ]
    content = "\n".join(x for x in sections if x)
    title = _field(root, "사건명") or f"판례 {cn}"
    sid = f"PRECEDENT:{seq}"
    return normalize_source_dict({
        "source_id": sid,
        "source_type": "PRECEDENT",
        "document_id": sid,
        "title": f"{court} {decided} 선고 {cn} {title}",
        "content": content,
        "retrieval_method": "OFFICIAL_PRECEDENT_SEARCH",
        "source_url": f"https://www.law.go.kr/LSW/precInfoP.do?precSeq={seq}",
        "court": court,
        "case_number": cn.replace(" ", ""),
        "decision_date": decided,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "file": sid,
        "chunk_id": f"{sid}#decision",
    })


def search_official_precedents(
    queries: list[str],
    *,
    max_results: int = 3,
    fetcher: Callable[..., bytes | None] | None = None,
    diagnostic: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """공식 판례 API 검색. 실패시 출처 0건으로 반환해 검증 실패를 숨기지 않는다.

    쿼리/판례 수·응답 크기를 제한해 비용/응답시간 폭증을 막는다. API 인증
    없는 상태에서는 전송을 시도하지 않는다. 동일 판례는 id로 중복 제거.
    """
    meta = diagnostic if diagnostic is not None else {}
    api_key = os.getenv("LAW_OPENAPI_KEY", "").strip()
    if not api_key:
        meta["status"] = "API_KEY_MISSING"
        return []
    if fetcher is None:
        fetcher = _fetch_xml_with_retry
    valid = list(dict.fromkeys(q for raw in (queries or [])[:6]
                               if (q := normalize_precedent_query(raw))))[:2]
    if not valid:
        meta["status"] = "QUERY_REJECTED"
        return []
    limit = max(1, min(int(max_results), 5))
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    calls = 0
    failed = False
    for q in valid:
        if len(sources) >= limit:
            break
        url = _LIST_URL + "?" + urlencode({
            "OC": api_key, "target": "prec", "type": "XML",
            "search": 2, "query": q, "display": 8, "page": 1, "sort": "ddes",
        })
        try:
            raw = fetcher(url, api_key=api_key, timeout=7, max_retries=1)
            calls += 1
        except Exception as exc:
            logger.warning("[PRECEDENT] 목록조회 실패 type=%s", type(exc).__name__)
            failed = True
            continue
        root = _xml(raw)
        if root is None:
            failed = True
            continue
        for hit in _list_hits(root):
            if len(sources) >= limit:
                break
            seq = hit["id"]
            if seq in seen:
                continue
            seen.add(seq)
            detail_url = _DETAIL_URL + "?" + urlencode({
                "OC": api_key, "target": "prec", "type": "XML", "ID": seq,
            })
            try:
                detail = fetcher(detail_url, api_key=api_key, timeout=7, max_retries=1)
                calls += 1
            except Exception as exc:
                logger.warning("[PRECEDENT] 원문조회 실패 type=%s", type(exc).__name__)
                failed = True
                continue
            source = parse_precedent_detail(detail, expected_id=seq)
            if source and (not hit["case_number"] or hit["case_number"].replace(" ", "") == source["case_number"]):
                sources.append(source)
        # 다른 query는 첫 결과가 부족할 때에만 수행.
    meta.update(status="SUCCESS" if sources else "API_ERROR" if failed else "NOT_FOUND",
                query_count=len(valid), request_count=calls, source_count=len(sources))
    logger.info("[PRECEDENT] 공식 검색 종료 status=%s queries=%d calls=%d sources=%d",
                meta["status"], len(valid), calls, len(sources))
    return sources
