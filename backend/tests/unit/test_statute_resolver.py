"""P0-LAW-01 법령명 공식 식별 독립 회귀 테스트 (네트워크/LLM 비용 0)."""
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

from ai_legal_helper.tools.statute_resolver import resolve_statute_candidates


QUESTION = (
    "저는 120세대 규모의 등록 민간임대주택을 운영하는 임대사업자입니다. "
    "2026년 11월 1일 임차인과 새로운 계약을 체결하려고 합니다. "
    "2026년 10월 27일 개정된 시행령에 따라 관리비와 전기·수도료의 "
    "부과금액 또는 산정방식을 임대차계약 신고에 반드시 포함해야 하나요?"
)


def _fake_search(calls):
    def fetch(url):
        query = parse_qs(urlsplit(url).query)["query"][0]
        calls.append(query)
        root = ET.Element("LawSearch")
        for name in (
            "민간임대주택에 관한 특별법",
            "민간임대주택에 관한 특별법 시행령",
            "민간임대주택에 관한 특별법 시행규칙",
            "부동산 거래신고 등에 관한 법률 시행령",
        ):
            law = ET.SubElement(root, "law")
            ET.SubElement(law, "법령명한글").text = name
            ET.SubElement(law, "법령ID").text = "test-id"
            ET.SubElement(law, "법령구분명").text = "대통령령" if name.endswith("시행령") else "법률"
        return ET.tostring(root, encoding="utf-8")
    return fetch


def test_private_rental_question_prioritizes_official_enforcement_decree(monkeypatch):
    """잘못된 LLM 후보보다 공식 법령명 색인과 질문 식별어가 우선한다."""
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-secret")
    calls = []
    result = resolve_statute_candidates(
        QUESTION, ["부동산 거래신고 등에 관한 법률 시행령"], fetch_xml=_fake_search(calls)
    )
    assert result.status == "FOUND"
    assert result.candidates[0].law_name == "민간임대주택에 관한 특별법 시행령"
    assert result.search_terms[0] == "민간임대주택"
    assert "부동산 거래신고 등에 관한 법률 시행령" in result.skipped_llm_candidates
    assert result.candidates[0].score > result.candidates[1].score
    assert len(calls) == 1


def test_unknown_law_is_never_fabricated(monkeypatch):
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-secret")
    result = resolve_statute_candidates(
        "존재하지 않는 특별법 내용", ["가상의 특별법 시행령"], fetch_xml=lambda _: b"<LawSearch/>"
    )
    assert result.status == "NO_MATCH"
    assert result.candidates == []


def test_no_key_fails_closed_without_network(monkeypatch):
    monkeypatch.delenv("LAW_OPENAPI_KEY", raising=False)
    result = resolve_statute_candidates("민간임대주택 시행령", ["민법"])
    assert result.status == "NO_API_KEY"
    assert result.candidates == []


def test_short_question_falls_back_to_proposed_law(monkeypatch):
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-secret")
    calls = []
    def fetch(url):
        calls.append(parse_qs(urlsplit(url).query)["query"][0])
        return ("<LawSearch><law><법령명한글>민법</법령명한글>"
                "<법령ID>001</법령ID></law></LawSearch>").encode()
    result = resolve_statute_candidates("민법 제6조", ["민법"], fetch_xml=fetch)
    assert calls == ["민법"]
    assert result.candidates[0].law_name == "민법"


def test_broken_xml_is_not_marked_verified(monkeypatch):
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-secret")
    result = resolve_statute_candidates(
        QUESTION, ["민간임대주택에 관한 특별법 시행령"],
        fetch_xml=lambda _: b"<badxml", max_queries=1,
    )
    assert result.status == "NO_MATCH"
    assert result.candidates == []
