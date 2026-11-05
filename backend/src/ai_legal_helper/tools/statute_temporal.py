# -*- coding: utf-8 -*-
"""P0-LAW-02: 조문별 시행일 및 부칙 적용시점 검증.

법령 전체의 시행일과 개별 조문의 시행일은 다를 수 있다. 특히 부칙의
시행일 예외 및 적용례를 보지 않고 '공포일 이후 계약'으로 단정하면 안 된다.
법령 고유명사나 특정 일자를 하드코딩하지 않고 XML 원문에서 확인한다.
"""
from __future__ import annotations

import calendar
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional


@dataclass(frozen=True)
class Addendum:
    """공포번호를 기준으로 연결된 공식 부칙의 원문과 공포일."""

    promulgation_number: str
    promulgation_date: str
    content: str


def parse_date(raw: object) -> Optional[date]:
    """YYYYMMDD / YYYY-MM-DD / YYYY.M.D.를 날짜로 안전하게 정규화한다."""
    if raw is None:
        return None
    s = str(raw).strip()
    found = re.fullmatch(r"(\d{4})[-./년\s]*(\d{1,2})[-./월\s]*(\d{1,2})(?:일|\.)?", s)
    if not found:
        return None
    try:
        return date(*map(int, found.groups()))
    except ValueError:
        return None


def iso_date(raw: object) -> Optional[str]:
    value = parse_date(raw)
    return value.isoformat() if value else None


def _text(node: ET.Element, name: str) -> str:
    child = node.find(".//" + name)
    return "".join(child.itertext()).strip() if child is not None else ""


def extract_addenda(root: ET.Element, promulgation_number: str) -> list[Addendum]:
    """현재 공포번호에 대응하는 부칙만 수집하여 다른 개정의 부칙과 혼합하지 않는다."""
    number = re.sub(r"\D", "", promulgation_number or "")
    if not number:
        return []
    found: list[Addendum] = []
    for node in root.findall(".//부칙단위"):
        no = re.sub(r"\D", "", _text(node, "부칙공포번호"))
        if no != number:
            continue
        content = _text(node, "부칙내용")
        if content:
            found.append(Addendum(
                promulgation_number=no,
                promulgation_date=iso_date(_text(node, "부칙공포일자")) or "",
                content=content,
            ))
    return found


def _add_months(value: date, months: int) -> date:
    """달력상 개월 가산. 날짜가 존재하지 않는 월이면 해당 월 말일 사용."""
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _effective_from_addendum(addendum: Addendum, article: str) -> Optional[str]:
    """Interpret an official effective-date rule semantically, then do math.

    The model decides the clause's legal meaning and exception scope using
    the COMPLETE addendum. Regex extracts *numbers* from already-classified
    quotes only; no Korean legal phrase regex decides an effective date.
    Unknown scope, unsupported arithmetic or model errors fail closed.
    """
    from ai_legal_helper.case_intelligence.semantic_judgment import classify_statement

    promulgated = parse_date(addendum.promulgation_date)
    if not promulgated or not addendum.content:
        return None
    interpretation = classify_statement(
        addendum.content,
        task="OFFICIAL_ADDENDUM_EFFECTIVE_DATE",
        labels=(
            "MONTHS_ELAPSED_AFTER_PROMULGATION",
            "ON_PROMULGATION",
            "EXPLICIT_FIXED_DATE",
            "REVIEW_REQUIRED",
        ),
        context=(
            "대상 조문: " + (article or "법령 공통 시행일") + ". "
            "부칙 전체에서 조문별 시행 예외, 다른 적용례, 법령 공통 시행일을 "
            "비교하고 대상 조문에 실제 적용되는 시행일만 결정하세요. "
            "MONTHS_ELAPSED_AFTER_PROMULGATION: 공포 후 N개월이 '경과한 날'부터 "
            "시행하는 문장이며 N은 인용문에 명시됨. "
            "ON_PROMULGATION: 공포한 날부터 시행함. "
            "EXPLICIT_FIXED_DATE: 달력상 시행일이 인용문에 명시됨. "
            "REVIEW_REQUIRED: 예외 적용 대상, 계산 방식 또는 조문 관계가 모호함. "
            "공포 후 N개월이 경과한 날은 공포일 기준 N개월 가산일 다음 날."
        ),
    )
    quote = interpretation.evidence_quote
    if interpretation.label == "ON_PROMULGATION":
        return promulgated.isoformat()
    if interpretation.label == "EXPLICIT_FIXED_DATE":
        # Only parse a literal date from the selected official quotation.
        spans = re.findall(
            r"(?<!\d)\d{4}\s*(?:년|[-./])\s*\d{1,2}\s*(?:월|[-./])\s*\d{1,2}\s*일?",
            quote,
        )
        dates = {iso_date(value) for value in spans}
        dates.discard(None)
        return next(iter(dates)) if len(dates) == 1 else None
    if interpretation.label == "MONTHS_ELAPSED_AFTER_PROMULGATION":
        # This is NUMERIC EXTRACTION from a model-identified time unit, not
        # regex interpretation of legal effect.
        months = re.findall(r"(?<!\d)(\d{1,3})\s*개월", quote)
        if len(months) != 1:
            return None
        count = int(months[0])
        if count < 0 or count > 240:
            return None
        return (_add_months(promulgated, count) + timedelta(days=1)).isoformat()
    return None


def article_effective_date(
    article_node: ET.Element,
    article_label: str,
    addenda: list[Addendum],
) -> tuple[Optional[str], str]:
    """공식 XML의 조문 시행일 우선; 부칙 해석은 의미 검증과 계산 분리."""
    article_date = iso_date(article_node.findtext("조문시행일자"))
    if article_date:
        return article_date, "ARTICLE_EFFECTIVE_DATE"
    if len(addenda) == 1:
        calculated = _effective_from_addendum(addenda[0], article_label)
        if calculated:
            return calculated, "ADDENDUM_EFFECTIVE_DATE"
    return None, "UNCONFIRMED"


def find_contract_date(question: str) -> Optional[date]:
    """질문의 계약 체결·갱신 날짜만 추출하고 개정 공포일과 섞지 않는다."""
    pattern = re.compile(
        r"(20\d{2})\s*(?:년|[-./])\s*(\d{1,2})\s*(?:월|[-./])\s*(\d{1,2})\s*일?"
        r"[^.\n]{0,30}?(?:계약|체결|갱신|변경)"
    )
    for match in pattern.finditer(question or ""):
        result = parse_date("-".join(match.groups()))
        if result:
            return result
    return None


def temporal_answer_errors(question: str, answer: str, sources: list[dict]) -> list[str]:
    """법령 적용시점 검증에 필요한 공식 자료의 완전성만 확인한다.

    동의어 전반의 법률 판단을 규칙으로 대체하지 않는다. 검색된 시행일이 없으면
    이 함수가 정답을 보증하지 않으며, 부칙 확인은 별도 선행 요건이다.
    """
    errors: list[str] = []
    target = find_contract_date(question)
    if not target:
        return errors
    # 공포 후 유예된 개정의 적용 여부가 핵심이면 부칙 원문 없이는
    # 어떤 방향의 단정도 검증 완료(PASS)로 표시하지 않는다.
    amendment_question = "개정" in question and any(
        term in question for term in ("시행령", "시행규칙", "법률", "개정법")
    )
    has_addendum_evidence = any(
        s.get("source_type") == "STATUTE"
        and (s.get("article") == "부칙" or "부칙" in str(s.get("title") or ""))
        and bool(str(s.get("content") or "").strip())
        for s in (sources or [])
    )
    if amendment_question and not has_addendum_evidence:
        errors.append(
            "개정 법령의 부칙(시행일·적용례) 원문이 검색 출처에 없습니다. "
            "공포일만으로 계약일의 신법 적용 여부를 확정하지 마세요."
        )
    if amendment_question and has_addendum_evidence and not any(
        (s.get("article") == "부칙" or "부칙" in str(s.get("title") or ""))
        and parse_date(s.get("effective_date"))
        for s in (sources or [])
    ):
        errors.append(
            "부칙 원문은 확보했지만 시행일을 구조화하여 확정하지 못했습니다. "
            "부칙의 원문·예외·적용례를 확인하기 전 적용 여부를 단정하지 마세요."
        )
    # Legal assertion polarity and applicability are assessed by the semantic
    # temporal verifier. This lightweight helper checks source completeness
    # only; phrase matching must not reject correct legal conclusions.
    return list(dict.fromkeys(errors))
