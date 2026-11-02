# -*- coding: utf-8 -*-
"""
P4 공식 법령 연혁·MST·조문별 시행일·부칙 출처 회귀.

테스트 법령/공포번호는 인공 픽스처다. 실 API/유료 LLM/운영 DB 호출 없음.
"""
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

import pytest

from ai_legal_helper.rag.temporal_applicability import (
    ApplicabilityStatus, evaluate_statute_applicability,
)
from ai_legal_helper.tools.official_statute_versions import (
    OfficialLawVersion, build_detail_url, build_history_url,
    lookup_versions_for_date, select_versions_at_date,
)
from ai_legal_helper.tools.official_statute_search import search_official_statutes


NAME = "가상 계약법 시행령"
LAW_ID = "110"
MST_OLD = "100"
MST_NEW = "200"
NEW_ADDENDUM = (
    "제1조(시행일) 이 영은 공포 후 6개월이 경과한 날부터 시행한다. "
    "다만, 제50조의 개정규정은 공포한 날부터 시행한다. "
    "제2조(적용례) 제36조의 개정규정은 이 영 시행 이후 계약을 체결하거나 "
    "갱신 또는 변경하는 경우부터 적용한다."
)
OLD_ADDENDUM = "제1조(시행일) 이 영은 공포한 날부터 시행한다."


def version(mst="100", eff="2024-01-01", prom="2023-12-01", law_id=LAW_ID, name=NAME):
    return OfficialLawVersion(
        law_id=law_id, law_name=name, mst=mst, law_type="대통령령",
        promulgation_date=prom, promulgation_number="12345" if mst == "100" else "99999",
        list_effective_date=eff,
    )


def history_xml(items, *, page=1, total=None):
    root = ET.Element("LawSearch")
    ET.SubElement(root, "totalCnt").text = str(len(items) if total is None else total)
    ET.SubElement(root, "page").text = str(page)
    for v in items:
        row = ET.SubElement(root, "law")
        for tag, val in (
            ("법령명한글", v.law_name),
            ("법령ID", v.law_id),
            ("법령일련번호", v.mst),
            ("법령구분명", v.law_type),
            ("시행일자", v.list_effective_date.replace("-", "")),
            ("공포일자", (v.promulgation_date or "").replace("-", "")),
            ("공포번호", v.promulgation_number),
            ("현행연혁코드", "현행" if v.mst == MST_OLD else "시행예정"),
        ):
            ET.SubElement(row, tag).text = val
    return ET.tostring(root, encoding="utf-8")


def body_xml(v, *, wrong_mst=False, missing_article=False, addendum=True):
    root = ET.Element("법령")
    info = ET.SubElement(root, "법령기본정보")
    ET.SubElement(info, "법령ID").text = v.law_id
    ET.SubElement(info, "법령일련번호").text = "WRONG" if wrong_mst else v.mst
    ET.SubElement(info, "법령명_한글").text = v.law_name
    articles = ["50"] if missing_article else ["36", "50"]
    for number in articles:
        node = ET.SubElement(root, "조문단위")
        ET.SubElement(node, "조문번호").text = number
        ET.SubElement(node, "조문가지번호").text = "0"
        ET.SubElement(node, "조문제목").text = "계약신고" if number == "36" else "예외"
        ET.SubElement(node, "조문내용").text = (
            f"제{number}조(시험) {'개정된' if v.mst == MST_NEW else '종전의'} 규정"
        )
        if number == "36" and v.mst == MST_OLD:
            ET.SubElement(node, "조문시행일자").text = "20240101"
    if addendum:
        node = ET.SubElement(root, "부칙단위")
        ET.SubElement(node, "부칙공포번호").text = v.promulgation_number
        ET.SubElement(node, "부칙공포일자").text = (v.promulgation_date or "").replace("-", "")
        ET.SubElement(node, "부칙내용").text = (
            OLD_ADDENDUM if v.mst == MST_OLD else NEW_ADDENDUM
        )
    return ET.tostring(root, encoding="utf-8")


def fake_api(versions, *, fail_pages=(), tamper_mst=None, missing_article=None):
    calls = []

    def fetch(url, **kwargs):
        parts = parse_qs(urlsplit(url).query)
        calls.append(parts)
        if "lawSearch.do" in url:
            assert parts["target"] == ["eflaw"]
            assert parts["nw"] == ["1,2,3"]
            assert parts["type"] == ["XML"]
            page = int(parts["page"][0])
            if page in fail_pages:
                return None
            return history_xml(versions, total=len(versions), page=page)
        assert "lawService.do" in url
        assert parts["target"] == ["eflaw"]
        assert parts["type"] == ["XML"]
        assert "MST" in parts and "efYd" in parts
        matched = next(v for v in versions if v.mst == parts["MST"][0])
        assert parts["efYd"][0] == matched.list_effective_date.replace("-", "")
        return body_xml(
            matched, wrong_mst=(tamper_mst == matched.mst),
            missing_article=(missing_article == matched.mst),
        )

    return fetch, calls


def test_history_query_matches_documented_eflaw_params():
    url = build_history_url("fake-secret", page=2, law_id=LAW_ID)
    params = parse_qs(urlsplit(url).query)
    assert url.startswith("https://www.law.go.kr/DRF/lawSearch.do?")
    assert params["target"] == ["eflaw"]
    assert params["LID"] == [LAW_ID]
    assert params["nw"] == ["1,2,3"]
    assert params["page"] == ["2"]
    assert "query" not in params


def test_body_query_requires_exact_mst_and_efyd():
    params = parse_qs(urlsplit(build_detail_url("fake-secret", version())).query)
    assert params["MST"] == ["100"]
    assert params["efYd"] == ["20240101"]
    assert params["target"] == ["eflaw"]


def test_latest_effective_and_next_promulgated_amendment_are_distinct():
    old = version()
    future = version("200", eff="2027-04-28", prom="2026-10-27")
    out = select_versions_at_date([old, future], "2026-11-01")
    assert out.status == "CANDIDATES_FOUND"
    assert [v.mst for v in out.candidates] == ["100", "200"]
    assert out.roles == {"100": "AS_OF_CANDIDATE", "200": "NEXT_EFFECTIVE_CANDIDATE"}


def test_date_after_new_effective_uses_new_version_as_anchor():
    out = select_versions_at_date(
        [version(), version("200", eff="2027-04-28", prom="2026-10-27")],
        "2027-05-01",
    )
    assert [v.mst for v in out.candidates] == ["200"]
    assert out.roles == {"200": "AS_OF_CANDIDATE"}


def test_before_first_known_version_cannot_invent_earlier_law():
    out = select_versions_at_date([version()], "2020-01-01")
    assert out.status == "UNCONFIRMED"
    assert out.reason_code == "NO_VERSION_EFFECTIVE_BY_AS_OF_DATE"


def test_future_promulgated_retroactivity_needs_human_review():
    retro = version("200", eff="2026-01-01", prom="2026-10-27")
    out = select_versions_at_date([version(), retro], "2026-06-01")
    assert out.status == "UNCONFIRMED"
    assert out.reason_code == "RETROACTIVE_AMENDMENT_REVIEW_REQUIRED"


def test_identical_effective_date_for_distinct_mst_is_ambiguous():
    out = select_versions_at_date([
        version(), version("200", eff="2024-01-01", prom="2023-12-12"),
    ], "2026-11-01")
    assert out.status == "UNCONFIRMED"
    assert out.reason_code == "MULTIPLE_VERSIONS_SAME_EFFECTIVE_DATE"


def test_incomplete_history_page_does_not_select_partial_record():
    first, second = version(), version("200", eff="2027-04-28", prom="2026-10-27")
    def fetch(url):
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        return history_xml([first], page=1, total=2) if page == 1 else None
    out = lookup_versions_for_date(
        law_name=NAME, as_of_date="2026-11-01", api_key="fake-secret",
        fetch_xml=fetch,
    )
    assert out.status == "UNCONFIRMED"
    assert out.pages_fetched == 1
    assert out.candidates == []


def test_duplicate_mst_across_pages_is_rejected():
    v = version()
    def fetch(url):
        page = int(parse_qs(urlsplit(url).query)["page"][0])
        return history_xml([v], page=page, total=2)
    out = lookup_versions_for_date(
        law_name=NAME, as_of_date="2026-11-01", api_key="fake-secret",
        fetch_xml=fetch,
    )
    assert out.status == "UNCONFIRMED"
    assert out.reason_code == "DUPLICATE_MST_IN_OFFICIAL_HISTORY"


def test_incomplete_history_page_cap_never_claims_full():
    v = version()
    out = lookup_versions_for_date(
        law_name=NAME, as_of_date="2026-11-01", api_key="fake-secret",
        fetch_xml=lambda u: history_xml([v], page=1, total=10000),
        max_pages=1,
    )
    assert out.status == "UNCONFIRMED"
    assert out.reason_code == "INCOMPLETE_OFFICIAL_HISTORY"


def test_same_name_different_law_ids_is_not_merged():
    v = version(law_id="999")
    out = lookup_versions_for_date(
        law_name=NAME, as_of_date="2026-11-01", api_key="fake-secret",
        fetch_xml=lambda u: history_xml([version(), v]),
    )
    assert out.status == "UNCONFIRMED"
    assert out.reason_code == "AMBIGUOUS_OFFICIAL_LAW_ID"


def test_lookalike_statute_name_is_never_selected():
    fake = version(name="외계인 가상 계약법 시행령")
    out = lookup_versions_for_date(
        law_name=NAME, as_of_date="2026-11-01", api_key="fake-secret",
        fetch_xml=lambda u: history_xml([fake]),
    )
    assert out.status == "NOT_FOUND" or out.status == "UNCONFIRMED"
    assert out.candidates == []


@pytest.mark.parametrize("invalid_date", ["2026-13-01", "2026/11/01", "", "2026-02-30"])
def test_invalid_asof_does_not_call_official_api(invalid_date):
    accessed = []
    out = lookup_versions_for_date(
        law_name=NAME, as_of_date=invalid_date, api_key="fake-secret",
        fetch_xml=lambda url: accessed.append(url),
    )
    assert out.status == "UNCONFIRMED"
    assert accessed == []


def test_doctype_and_external_entity_are_not_accepted():
    xml = b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><LawSearch/>'
    out = lookup_versions_for_date(
        law_name=NAME, as_of_date="2026-11-01", api_key="fake-secret",
        fetch_xml=lambda _: xml,
    )
    assert out.status == "UNCONFIRMED"


def test_end_to_end_explicit_date_requests_old_and_future_version_with_addenda(monkeypatch):
    """2026 계약에 2027 시행 조문을 현재법으로 오인하면 안 된다."""
    old = version()
    future = version("200", eff="2027-04-28", prom="2026-10-27")
    fake, calls = fake_api([old, future])
    monkeypatch.setenv("LAW_OPENAPI_KEY", "fake-secret")
    monkeypatch.setattr(
        "ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", fake
    )
    found = search_official_statutes(
        query="2026년 11월 1일 계약에 개정된 관리비 신고 적용되나요?",
        candidate_laws=[f"{NAME} 제36조"],
        as_of_date="2026-11-01", max_articles_per_law=3,
    )
    assert len(found) == 4  # 종전 조문/부칙 + 개정 조문/부칙
    assert {s["version_id"] for s in found} == {"100", "200"}
    old_article = next(s for s in found if s["version_id"] == "100" and s["article"] == "제36조")
    next_article = next(s for s in found if s["version_id"] == "200" and s["article"] == "제36조")
    assert "종전의" in old_article["content"]
    assert "개정된" in next_article["content"]
    assert old_article["version_relation"] == "AS_OF_CANDIDATE"
    assert next_article["version_relation"] == "NEXT_EFFECTIVE_CANDIDATE"
    assert next_article["article_effective_date"] == "2027-04-28"
    assert next_article["effective_date_basis"] == "ADDENDUM_EFFECTIVE_DATE"
    assert next_article["law_effective_date"] == "2027-04-28"
    assert next_article["requested_as_of_date"] == "2026-11-01"
    assert all(s["version_lookup_status"] == "HISTORY_COMPLETE" for s in found)
    assert all(s["metadata_confidence"] == "OFFICIAL_BODY_MST_CONFIRMED" for s in found)
    assert all(s["temporal_status"] != "VERIFIED" for s in found)
    assert all(s["filename"] is None and s["page"] is None for s in found)
    assert all(".pdf" not in s["source_id"] for s in found)
    assert all(len(s["content_hash"]) == 64 for s in found)
    assert len({s["source_id"] for s in found}) == 4
    assert {s["article"] for s in found if s["article"] == "부칙"} == {"부칙"}
    assert len([s for s in found if s["article"] == "부칙"]) == 2
    # 공식 정보 검색은 버전 및 근거를 확보했을 뿐 계약 체결/갱신 적용례는 P5에서 검증한다.
    assert evaluate_statute_applicability(next_article, "2027-05-01").status is ApplicabilityStatus.UNCONFIRMED
    assert all(x["target"] == ["eflaw"] for x in calls)


def test_legacy_effective_date_parameter_routes_to_same_history_api(monkeypatch):
    v = version()
    fake, calls = fake_api([v])
    monkeypatch.setenv("LAW_OPENAPI_KEY", "fake-secret")
    monkeypatch.setattr(
        "ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", fake
    )
    out = search_official_statutes(
        query="과거 계약", candidate_laws=[f"{NAME} 제36조"],
        effective_date="2025-01-01",
    )
    assert out and out[0]["version_id"] == MST_OLD
    assert calls[0]["target"] == ["eflaw"]


def test_mismatch_between_two_date_arguments_aborts_before_network(monkeypatch):
    accessed = []
    monkeypatch.setenv("LAW_OPENAPI_KEY", "fake-secret")
    monkeypatch.setattr(
        "ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry",
        lambda url, **k: accessed.append(url),
    )
    out = search_official_statutes(
        query="계약", candidate_laws=[NAME],
        effective_date="2026-11-01", as_of_date="2027-05-01",
    )
    assert out == [] and accessed == []


def test_wrong_mst_in_detail_aborts_all_versions_for_law(monkeypatch):
    old = version()
    future = version("200", eff="2027-04-28", prom="2026-10-27")
    fake, _ = fake_api([old, future], tamper_mst="200")
    monkeypatch.setenv("LAW_OPENAPI_KEY", "fake-secret")
    monkeypatch.setattr("ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", fake)
    out = search_official_statutes(
        query="2026년 11월 계약", candidate_laws=[f"{NAME} 제36조"],
        as_of_date="2026-11-01",
    )
    assert out == []


def test_missing_article_in_old_version_never_fabricates_it(monkeypatch):
    old = version()
    future = version("200", eff="2027-04-28", prom="2026-10-27")
    fake, _ = fake_api([old, future], missing_article="100")
    monkeypatch.setenv("LAW_OPENAPI_KEY", "fake-secret")
    monkeypatch.setattr("ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", fake)
    out = search_official_statutes(
        query="계약", candidate_laws=[f"{NAME} 제36조"],
        as_of_date="2026-11-01",
    )
    assert out
    assert not [s for s in out if s["version_id"] == "100" and s["article"] == "제36조"]
    assert [s for s in out if s["version_id"] == "200" and s["article"] == "제36조"]


def test_unknown_history_date_is_not_cured_by_current_law_search(monkeypatch):
    accessed = []
    monkeypatch.setenv("LAW_OPENAPI_KEY", "fake-secret")
    monkeypatch.setattr(
        "ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry",
        lambda url, **k: accessed.append(url) or b"<LawSearch><totalCnt>1</totalCnt><page>1</page><law><법령명한글>가상 계약법 시행령</법령명한글><법령ID>110</법령ID><법령일련번호>100</법령일련번호></law></LawSearch>",
    )
    out = search_official_statutes(
        query="질의", candidate_laws=[NAME], as_of_date="2026-11-01",
    )
    assert out == []
    assert len(accessed) == 1
    assert "target=eflaw" in accessed[0]
