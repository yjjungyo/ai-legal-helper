# -*- coding: utf-8 -*-
"""
P1 공식 법령 검색의 조문 시행일 출처 보존 테스트.

공식 API는 XML 픽스처로 대체하여 외부 네트워크 없이 재현한다.
법령 공통 시행일이 조문 예외에 잘못 복사되는 회귀를 방지한다.
"""
import xml.etree.ElementTree as ET

from ai_legal_helper.rag.temporal_applicability import (
    ApplicabilityStatus, evaluate_statute_applicability,
)
from ai_legal_helper.tools.official_statute_search import search_official_statutes


LAW = "가상 특별법 시행령"
ADDENDUM = (
    "제1조(시행일) 이 영은 공포 후 6개월이 경과한 날부터 시행한다. "
    "다만, 제50조의 개정규정은 공포한 날부터 시행한다. "
    "제2조(적용례) 제4조의 개정규정은 시행 후 체결하는 계약부터 적용한다."
)


def _detail_payload():
    root = ET.Element("법령")
    for number in ("4", "50"):
        node = ET.SubElement(root, "조문단위")
        ET.SubElement(node, "조문번호").text = number
        ET.SubElement(node, "조문가지번호").text = "0"
        ET.SubElement(node, "조문제목").text = "계약신고" if number == "4" else "예외"
        ET.SubElement(node, "조문내용").text = f"제{number}조(시험) 해당 개정 규정"
    ad = ET.SubElement(root, "부칙단위")
    ET.SubElement(ad, "부칙공포번호").text = "9999"
    ET.SubElement(ad, "부칙공포일자").text = "20260601"
    ET.SubElement(ad, "부칙내용").text = ADDENDUM
    return ET.tostring(root, encoding="utf-8")


def test_official_article_date_does_not_use_law_wide_fallback(monkeypatch):
    """부칙 예외 조문에 법령 공통 시행일이 무단 복사되면 안 된다."""
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-api-key")

    def mock_fetch(url, **kwargs):
        if "lawSearch.do" in url:
            return (
                f"<LawSearch><law><법령명한글>{LAW}</법령명한글>"
                "<법령ID>TEST-LAW</법령ID><법령일련번호>TEST-MST</법령일련번호>"
                "<법령구분명>대통령령</법령구분명>"
                "<공포번호>9999</공포번호><공포일자>20260601</공포일자>"
                "<시행일자>20260601</시행일자></law></LawSearch>"
            ).encode("utf-8")
        return _detail_payload()

    monkeypatch.setattr(
        "ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", mock_fetch
    )
    sources = search_official_statutes(
        query="2026년 11월 1일 계약에 개정 조문 적용 여부",
        candidate_laws=[f"{LAW} 제4조", f"{LAW} 제50조"],
        max_articles_per_law=2,
    )
    article_four = next(s for s in sources if s.get("article") == "제4조")
    exception = next(s for s in sources if s.get("article") == "제50조")
    assert article_four["law_id"] == "TEST-LAW"
    assert article_four["version_id"] == "TEST-MST"
    assert article_four["law_effective_date"] == "2026-06-01"
    assert article_four["article_effective_date"] == "2026-12-02"
    assert article_four["effective_date_basis"] == "ADDENDUM_EFFECTIVE_DATE"
    assert article_four["temporal_status"] == "EFFECTIVE_DATE_VERIFIED"
    # 관련 적용례(체결/갱신 조건)는 이후 Temporal Resolver에서 별도로 검증한다.
    assert evaluate_statute_applicability(
        article_four, "2027-02-01"
    ).status is ApplicabilityStatus.UNCONFIRMED
    assert exception["article_effective_date"] is None
    assert exception["effective_date"] is None
    assert exception["effective_date_basis"] == "UNCONFIRMED"
    assert exception["law_effective_date"] == "2026-06-01"
    assert evaluate_statute_applicability(
        exception, "2027-02-01"
    ).status is ApplicabilityStatus.UNCONFIRMED
