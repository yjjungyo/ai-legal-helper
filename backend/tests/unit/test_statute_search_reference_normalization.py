"""법령 후보에 섞인 조문·제목·설명을 외부 검색 전에 분리하는 회귀 검사.

실제 도구와 승인 후 검색 노드를 연결하며, 외부 API만 고정 XML로 대체한다.
다른 법령 임의 선택, 가지 조문 혼동, 요청 조문 부재 시 다른 조문 반환을 차단한다.
"""

import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlsplit

import pytest

from ai_legal_helper.tools.official_statute_search import (
    _prepare_search_targets, _split_statute_reference, search_official_statutes,
)


@pytest.mark.parametrize("reference, name, articles", [
    ("주택임대차보호법", "주택임대차보호법", []),
    ("주택임대차보호법 제3조(대항력 등)", "주택임대차보호법", ["제3조"]),
    ("주택임대차보호법 제3조의2(보증금의 회수 등)", "주택임대차보호법", ["제3조의2"]),
    ("주택임대차보호법 제6조의2 또는 관련 해지통고·묵시적 갱신 규정", "주택임대차보호법", ["제6조의2"]),
    ("민법상 임대차 종료 및 보증금 반환 관련 일반 규정", "민법", []),
    ("소송촉진 등에 관한 특례법 제3조", "소송촉진 등에 관한 특례법", ["제3조"]),
    ("「근로기준법 시행령」 제 03 조 의 02", "근로기준법 시행령", ["제3조의2"]),
    ("민법의 제536조", "민법", ["제536조"]),
    ("난민법", "난민법", []),
])
def test_law_name_and_requested_article_are_separated(reference, name, articles):
    """설명이나 가지 조문을 법령명에 붙여 API로 보내지 않도록 분리한다."""
    target = _split_statute_reference(reference)
    assert target.law_name == name
    assert target.articles == articles


@pytest.mark.parametrize("reference", ["", "제3조", "법령 확인 필요", None])
def test_unidentifiable_law_is_not_guessed(reference):
    """법령명 없이 조문만 있거나 설명만 있으면 임의의 법을 만들지 않는다."""
    assert _split_statute_reference(reference) is None


def test_same_law_merges_all_requested_articles():
    """동일 법령의 조문 요청은 합치되 제3조와 제3조의2는 구분한다."""
    targets = _prepare_search_targets([
        "주택임대차보호법 제3조(대항력 등)", "주택임대차보호법 제3조의2(보증금의 회수 등)",
        "주택임대차보호법 제3조 제1항", "민법상 임대차 종료 관련 규정",
    ])
    assert [t.law_name for t in targets] == ["주택임대차보호법", "민법"]
    assert targets[0].articles == ["제3조", "제3조의2"]


@pytest.fixture
def official_api(monkeypatch):
    """법령 검색어를 기록하고 명확히 구분되는 모의 조문 XML을 응답한다.

    Args:
        monkeypatch: 환경변수와 외부 HTTP 호출을 교체하는 pytest 도구.

    Returns:
        외부 호출의 파싱된 파라미터 목록.
    """
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-key-not-a-secret")
    calls = []

    def fetch(url, **_kwargs):
        """네트워크 대신 법령명·식별자에 대응하는 테스트 XML을 반환한다."""
        params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        calls.append(params)
        if "query" in params:
            root = ET.Element("LawSearch")
            # 민법보다 앞에 유사 이름을 배치하여 정확한 법령명 매칭을 유지하는지도 확인한다.
            for name, mst in [("난민법", "refugee"), ("민법", "civil"), ("주택임대차보호법", "housing")]:
                law = ET.SubElement(root, "law")
                ET.SubElement(law, "법령명한글").text = name
                ET.SubElement(law, "법령일련번호").text = mst
            return ET.tostring(root, encoding="utf-8")
        root = ET.Element("법령")
        rows = [("3", "", "대항력 등"), ("3", "2", "보증금의 회수 등"),
                ("3", "3", "임차권등기명령"), ("30", "", "테스트"),
                ("6", "", "계약의 갱신"), ("6", "2", "묵시적 갱신의 경우 계약의 해지")]
        if params.get("MST") == "civil":
            rows = [("623", "", "임대인의 의무")]
        for number, branch, title in rows:
            node = ET.SubElement(root, "조문단위")
            ET.SubElement(node, "조문번호").text = number
            ET.SubElement(node, "조문가지번호").text = branch
            ET.SubElement(node, "조문제목").text = title
            ET.SubElement(node, "조문내용").text = "외부 검색 경로 검사용 가상 조문 본문"
        return ET.tostring(root, encoding="utf-8")

    monkeypatch.setattr("ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", fetch)
    return calls


def test_annotated_candidates_search_once_and_return_exact_requested_articles(official_api):
    """법령별 한 번 조회 후 명시한 본조문·가지 조문만 원문으로 반환한다."""
    sources = search_official_statutes(
        query="전혀 다른 쟁점", candidate_laws=[
            "주택임대차보호법 제3조(대항력 등)", "주택임대차보호법 제3조의2(보증금의 회수 등)",
        ], max_articles_per_law=10,
    )
    assert [c["query"] for c in official_api if "query" in c] == ["주택임대차보호법"]
    assert len(official_api) == 2
    assert {s["article"] for s in sources} == {"제3조", "제3조의2"}
    assert all(s["statute_name"] == "주택임대차보호법" for s in sources)


def test_explicit_missing_article_does_not_fall_back_to_other_article(official_api):
    """존재하지 않는 요청 조문을 총칙이나 비슷한 가지 조문으로 대신하지 않는다."""
    sources = search_official_statutes(query="대항력", candidate_laws=["주택임대차보호법 제9999조"])
    assert sources == []


def test_article_number_boost_does_not_match_prefix(official_api):
    """질의의 제3조의2를 제3조·제3조의3·제30조와 혼동하지 않는다."""
    sources = search_official_statutes(query="제3조의2", candidate_laws=["주택임대차보호법"], max_articles_per_law=1)
    assert [s["article"] for s in sources] == ["제3조의2"]


def test_actual_trace_candidate_values_flow_through_approval_search_node(official_api):
    """실제 실패 trace의 다섯 후보를 승인 후 검색 노드에 넣어 법령 두 개로 조회한다."""
    from ai_legal_helper.workflows.legal_workflow import execute_statute_search_node

    candidates = [
        "주택임대차보호법 제3조(대항력 등)", "주택임대차보호법 제3조의2(보증금의 회수 등)",
        "주택임대차보호법 제6조(계약의 갱신)", "주택임대차보호법 제6조의2 또는 관련 해지통고·묵시적 갱신 규정",
        "민법상 임대차 종료 및 보증금 반환 관련 일반 규정",
    ]
    result = execute_statute_search_node({
        "question": "등록 자료를 분석해 주세요.", "approval_status": "APPROVED",
        "verification_result": {"candidate_laws": list(candidates)}, "retrieved_sources": [], "warnings": [],
    })
    assert [c["query"] for c in official_api if "query" in c] == ["주택임대차보호법", "민법"]
    sources = result["statute_search_results"]
    assert {s["article"] for s in sources if s["statute_name"] == "주택임대차보호법"} == {
        "제3조", "제3조의2", "제6조", "제6조의2",
    }
    assert any(s["statute_name"] == "민법" for s in sources)
    assert result["warnings"] == []


def test_trace_3bc30893_unnumbered_issue_retains_foundational_articles(monkeypatch):
    """조문 번호 없이 대항력·우선변제권·임차권등기명령 쟁점으로 검색해도 제3조·제3조의2가 후속 조문에 밀려 누락되지 않는다."""
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-key-not-a-secret")

    def fetch(url, **_kwargs):
        params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        if "query" in params:
            root = ET.Element("LawSearch")
            law = ET.SubElement(root, "law")
            ET.SubElement(law, "법령명한글").text = "주택임대차보호법"
            ET.SubElement(law, "법령일련번호").text = "housing"
            return ET.tostring(root, encoding="utf-8")
        root = ET.Element("법령")
        rows = [
            ("3", "", "대항력 등", "① 임대차는 그 등기가 없는 경우에도 임차인이 주택의 인도와 주민등록을 마친 때에는 그 다음 날부터 제3자에 대하여 효력이 생긴다."),
            ("3", "2", "보증금의 회수", "② 제3조제1항에 따른 대항요건과 임대차계약증서상의 확정일자를 갖춘 임차인은 경매 시 후순위권리자보다 우선하여 보증금을 변제받을 권리가 있다."),
            ("3", "3", "임차권등기명령", "① 임대차가 끝난 후 보증금이 반환되지 아니한 경우 임차권등기명령을 신청할 수 있다. ⑤ 제3조제1항에 따른 대항력과 제3조의2제2항에 따른 우선변제권을 취득한다."),
            ("3", "5", "경매에 의한 임차권의 소멸", "임차권은 경매가 행하여진 경우에는 소멸한다. 다만 보증금이 모두 변제되지 아니한 대항력이 있는 임차권은 그러하지 아니하다."),
            ("3", "6", "확정일자 부여 및 임대차 정보제공 등", "확정일자 부여기관은 주택의 소재지, 확정일자 부여일, 차임 및 보증금 등을 기재하여야 한다."),
            ("8", "", "보증금 중 일정액의 보호", "임차인은 보증금 중 일정액을 다른 담보물권자보다 우선하여 변제받을 권리가 있다."),
        ]
        for number, branch, title, body in rows:
            node = ET.SubElement(root, "조문단위")
            ET.SubElement(node, "조문번호").text = number
            ET.SubElement(node, "조문가지번호").text = branch
            ET.SubElement(node, "조문제목").text = title
            ET.SubElement(node, "조문내용").text = body
        return ET.tostring(root, encoding="utf-8")

    monkeypatch.setattr("ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", fetch)
    issue = "대항력, 확정일자에 의한 우선변제권, 임대차 종료 후 보증금 반환 및 임차권등기명령 관련 법리"
    sources = search_official_statutes(
        query=issue,
        candidate_laws=["주택임대차보호법"],
        missing_issues=[issue],
        max_articles_per_law=4,
    )
    articles = {s["article"] for s in sources}
    assert "제3조" in articles
    assert "제3조의2" in articles
    assert "제3조의3" in articles

