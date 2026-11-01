"""P0-LAW-02: 공포일/조문시행일/부칙 적용례 구분 회귀 테스트.

공식 API 응답은 고정 XML로 대체한다. 특정 법령/날짜를 운영 코드에
하드코딩하지 않고 법령 자료와 사건 기준일의 정합성을 평가한다.
"""
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

from ai_legal_helper.tools.statute_temporal import (
    article_effective_date, extract_addenda, find_contract_date, temporal_answer_errors,
)
from ai_legal_helper.tools.official_statute_search import search_official_statutes


QUESTION = (
    "저는 120세대 규모의 등록 민간임대주택을 운영하는 임대사업자입니다. "
    "2026년 11월 1일 임차인과 새로운 계약을 체결하려고 합니다. "
    "2026년 10월 27일 개정된 시행령에 따라 관리비와 전기·수도료의 "
    "부과금액 또는 산정방식을 임대차계약 신고에 반드시 포함해야 하나요?"
)

BAD_ANSWER = (
    "네. 2026년 11월 1일 계약은 시행일 이후 체결되는 신규 계약이므로 "
    "민간임대주택에 관한 특별법 시행령 제36조가 적용됩니다. "
    "시행령 개정 시행일: 2026.10.27."
)

GOOD_ANSWER = (
    "아니요. 민간임대주택에 관한 특별법 시행령 제36조의 해당 신설 신고 항목은 "
    "2027년 4월 28일부터 적용되므로 2026년 11월 1일 계약에는 적용되지 않습니다."
)

ADDENDUM = (
    "제1조(시행일) 이 영은 공포 후 6개월이 경과한 날부터 시행한다. "
    "다만, 제50조제8항 및 별표 2 제2호나목의 개정규정은 공포한 날부터 시행한다. "
    "제2조(임대차신고에 관한 적용례) 제36조제1항제2호의2 및 제2호의3의 개정규정은 "
    "이 영 시행 이후 임대차계약을 체결하거나 임대차계약을 갱신 또는 변경하는 경우부터 적용한다."
)


def _api_payload():
    root = ET.Element("법령")
    article = ET.SubElement(root, "조문단위")
    ET.SubElement(article, "조문번호").text = "36"
    ET.SubElement(article, "조문가지번호").text = "0"
    ET.SubElement(article, "조문제목").text = "임대차계약의 신고"
    ET.SubElement(article, "조문내용").text = (
        "제36조(임대차계약의 신고) 관리비, 부과금액 또는 산정방식"
    )
    ad = ET.SubElement(root, "부칙단위")
    ET.SubElement(ad, "부칙공포번호").text = "36796"
    ET.SubElement(ad, "부칙공포일자").text = "20261027"
    ET.SubElement(ad, "부칙내용").text = ADDENDUM
    return root


def test_promulgation_is_not_effective_date_for_specific_reporting_rule():
    root = _api_payload()
    addenda = extract_addenda(root, "제36796호")
    article = root.find(".//조문단위")
    assert len(addenda) == 1
    effective, provenance = article_effective_date(article, "제36조", addenda)
    assert effective == "2027-04-28"
    assert provenance == "ADDENDUM_EFFECTIVE_DATE"


def test_exception_article_is_not_assigned_default_effective_date():
    root = _api_payload()
    addenda = extract_addenda(root, "36796")
    article = root.find(".//조문단위")
    effective, provenance = article_effective_date(article, "제50조", addenda)
    assert effective is None
    assert provenance == "UNCONFIRMED"


def test_actual_article_effective_date_beats_addendum():
    root = _api_payload()
    article = root.find(".//조문단위")
    ET.SubElement(article, "조문시행일자").text = "20270428"
    effective, provenance = article_effective_date(article, "제36조", extract_addenda(root, "36796"))
    assert effective == "2027-04-28"
    assert provenance == "ARTICLE_EFFECTIVE_DATE"


def test_contract_date_not_confused_with_promulgation_date():
    assert find_contract_date(QUESTION).isoformat() == "2026-11-01"


def test_wrong_applicability_is_blocked_by_official_addendum():
    source = {"source_type": "STATUTE", "statute_name": "민간임대주택에 관한 특별법 시행령",
              "article": "부칙", "content": ADDENDUM, "effective_date": "2027-04-28"}
    assert temporal_answer_errors(QUESTION, BAD_ANSWER, [source])
    assert temporal_answer_errors(QUESTION, GOOD_ANSWER, [source]) == []


def test_official_tool_includes_matching_addendum_and_correct_date(monkeypatch):
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-value")
    def mock_fetch(url, **kwargs):
        params = parse_qs(urlsplit(url).query)
        if "query" in params:
            return (
                "<LawSearch><law><법령명한글>민간임대주택에 관한 특별법 시행령</법령명한글>"
                "<법령일련번호>test-mst</법령일련번호><법령구분명>대통령령</법령구분명>"
                "<공포번호>36796</공포번호><공포일자>20261027</공포일자>"
                "<시행일자>20261027</시행일자></law></LawSearch>"
            ).encode("utf-8")
        return ET.tostring(_api_payload(), encoding="utf-8")
    monkeypatch.setattr(
        "ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", mock_fetch
    )
    sources = search_official_statutes(
        query=QUESTION,
        candidate_laws=["민간임대주택에 관한 특별법 시행령 제36조"],
        max_articles_per_law=5,
    )
    addenda = [s for s in sources if s.get("article") == "부칙"]
    assert len(addenda) == 1
    assert addenda[0]["effective_date"] == "2027-04-28"
    assert "제2조(임대차신고에 관한 적용례)" in addenda[0]["content"]
    assert temporal_answer_errors(QUESTION, BAD_ANSWER, sources)


def test_wrong_law_addendum_not_attached(monkeypatch):
    """공포번호가 다르면 임의로 다른 법령의 부칙을 붙이지 않는다."""
    root = _api_payload()
    assert extract_addenda(root, "36795") == []


def test_amendment_answer_cannot_pass_without_official_addenda():
    """조문만 확보하고 부칙을 누락했다면 긍정·부정 결론 모두 검증 보류."""
    source = {"source_type": "STATUTE", "statute_name": "민간임대주택에 관한 특별법 시행령",
              "article": "제36조", "effective_date": "2026-10-27",
              "content": "제36조(임대차계약의 신고)"}
    assert "부칙" in " ".join(temporal_answer_errors(QUESTION, BAD_ANSWER, [source]))
    assert "부칙" in " ".join(temporal_answer_errors(QUESTION, GOOD_ANSWER, [source]))


def test_question_without_contract_date_has_no_false_conflict():
    """날짜가 없는 일반 법령 설명 질의는 이전 응답을 회귀시키지 않는다."""
    question = "민법 제6조는 무슨 뜻인가요?"
    assert temporal_answer_errors(question, "민법 제6조에 해당합니다.", []) == []
