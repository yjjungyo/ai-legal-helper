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
    """부칙 제1조의 단순 시행일 규칙만 계산한다. 예외는 판단 유보한다.

    지원하지 않는 상대시점이나 개별 조문 예외를 추측하지 않는다. '공포 후 N개월이
    경과한 날'이라는 확정 패턴만 계산하며, 다만 절에 해당 조문이 포함되면 None.
    """
    text = re.sub(r"\s+", " ", addendum.content)
    first_article = re.search(r"제\s*1\s*조\s*\(\s*시행일\s*\)(.*?)(?=제\s*2\s*조\s*\(|$)", text)
    if not first_article:
        return None
    clause = first_article.group(1)
    if "다만" in clause:
        exception = clause.split("다만", 1)[1]
        # 개별 시행일 예외에 해당하면 일반 시행일을 강제로 적용하지 않는다.
        number = re.search(r"제\s*\d+\s*조(?:\s*의\s*\d+)?", article)
        if number and re.sub(r"\s+", "", number.group()) in re.sub(r"\s+", "", exception):
            return None
    promulgated = parse_date(addendum.promulgation_date)
    if not promulgated:
        return None
    relative = re.search(r"공포\s*후\s*(\d+)\s*개월이\s*경과한\s*날부터\s*시행", clause)
    if relative:
        months = int(relative.group(1))
        if not 0 <= months <= 240:
            return None
        return (_add_months(promulgated, months) + timedelta(days=1)).isoformat()
    if re.search(r"이\s*영은\s*공포한\s*날부터\s*시행", clause):
        return promulgated.isoformat()
    return None


def article_effective_date(
    article_node: ET.Element,
    article_label: str,
    addenda: list[Addendum],
) -> tuple[Optional[str], str]:
    """명시 조문 시행일 > 해당 개정부칙의 안전하게 계산 가능한 시행일 순서."""
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
    """법령 출처의 개별 조문 시행일과 정면 충돌하는 단정만 검출한다.

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
    positive = bool(re.search(
        r"시행일\s*이후|적용됩니다|적용된다|적용됩니다|포함해야\s*합니다|포함해야\s*한다",
        answer or "",
    ))
    # '적용되지 않습니다' 같은 부정 결론은 이 규칙으로 거절하지 않는다.
    if re.search(r"적용되지\s*않|적용하지\s*않|의무가\s*없", answer or ""):
        positive = False
    if not positive:
        return errors
    for source in sources or []:
        if source.get("source_type") != "STATUTE":
            continue
        article = str(source.get("article") or "")
        if not article:
            continue
        if article == "부칙":
            # 부칙의 적용례가 언급한 실제 조문이 답변에도 있는 경우에만 비교한다.
            referenced = set(re.findall(r"제\s*\d+\s*조(?:\s*의\s*\d+)?", str(source.get("content") or "")))
            if not any(ref in answer for ref in referenced):
                continue
        elif article not in answer and article not in question:
            continue
        effective = parse_date(source.get("effective_date"))
        if effective and target < effective:
            errors.append(
                f"{source.get('statute_name')} {article} 시행일 {effective.isoformat()}은 "
                f"계약일 {target.isoformat()}보다 늦습니다. 해당 조항을 이미 적용된 것으로 단정하지 마세요."
            )
    return list(dict.fromkeys(errors))
