# -*- coding: utf-8 -*-
"""
모듈명: test_step3_statute_search.py

[모듈 개요]
STEP 3 공식 법령 검색 개선 개발지시서에 따른 10대 필수 테스트 스위트.

[검증 항목]
1. 명시적 조문 검색 (A)
2. 조문번호 없는 쟁점 기반 의미 검색 및 원천 조문 보강 (B, C)
3. 본조문 및 가지 조문(제3조 vs 제3조의2) 엄격 구분
4. 동일 법령의 여러 쟁점(대항력 vs 우선변제권) 동시 검색 및 pending_searches 보존
5. 서로 다른 법령의 조문 혼합(주임법 + 민법) 분리 처리
6. 이미 확보한 조문의 중복 요청 차단 (Deduplication)
7. 결과가 4개보다 많은 경우 원천 조문 누락 방지 및 max_articles_per_law 준수
8. 외부 Open API 네트워크 실패/타임아웃 시 안전 폴백(빈 목록 반환)
9. 사용자 승인 범위 밖 외부 검색 차단
10. 묵시적 갱신 외 노동법(근로기준법) 및 민법 영역의 일반화(Generalization) 동작 검증
"""
import pytest
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch

from ai_legal_helper.tools.official_statute_search import (
    search_official_statutes,
    extract_substantive_tokens,
    _article_references,
    _split_statute_reference,
)
from ai_legal_helper.workflows.document_search import (
    pending_searches,
    search_is_approved,
    execute_document_search,
    _is_safe_question_match,
)


@pytest.fixture
def mock_law_api(monkeypatch):
    """법제처 국가법령정보 Open API 모의 응답 픽스처."""
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-openapi-key")

    def fetch(url, **_kwargs):
        params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        if "query" in params:
            query = params["query"]
            root = ET.Element("LawSearch")
            law = ET.SubElement(root, "law")
            ET.SubElement(law, "법령명한글").text = query
            ET.SubElement(law, "법령일련번호").text = f"mst-{query}"
            return ET.tostring(root, encoding="utf-8")
        
        # 조문 상세 API
        mst = params.get("MST", "")
        root = ET.Element("법령")
        
        if "근로기준법" in mst:
            rows = [
                ("26", "", "해고의 예고", "사용자는 근로자를 해고하려면 적어도 30일 전에 예고를 하여야 한다."),
                ("34", "", "퇴직급여 제도", "사용자가 퇴직하는 근로자에게 지급하는 퇴직급여 제도에 대하여는 「근로자퇴직급여 보장법」이 정하는 대로 따른다."),
                ("36", "", "금품 청산", "사용자는 근로자가 사망 또는 퇴직한 경우에는 그 지급 사유가 발생한 때부터 14일 이내에 임금, 보상금, 그 밖의 모든 금품을 지급하여야 한다."),
            ]
        elif "민법" in mst:
            rows = [
                ("536", "", "동시이행의 항변권", "쌍무계약의 당사자 일방은 상대방이 그 채무이행을 제공할 때까지 자기의 채무이행을 거절할 수 있다."),
                ("623", "", "임대인의 의무", "임대인은 목적물을 임차인에게 인도하고 계약존속 중 그 사용, 수익에 필요한 상태를 유지하게 할 의무를 부담한다."),
            ]
        else:
            # 주택임대차보호법 기본 모의 데이터
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
    return fetch


def test_01_explicit_article_search(mock_law_api):
    """테스트 1: 명시적 조문 검색 - 특정 조문이 지정된 경우 정확히 해당 조문만 조회."""
    sources = search_official_statutes(
        query="보증금 반환 문의",
        candidate_laws=["주택임대차보호법 제3조"],
        max_articles_per_law=5,
    )
    assert len(sources) == 1
    assert sources[0]["article"] == "제3조"
    assert sources[0]["statute_name"] == "주택임대차보호법"


def test_02_unnumbered_semantic_search_with_foundational_articles(mock_law_api):
    """테스트 2: 조문번호 없는 쟁점 검색 - 대항력·우선변제권 질의 시 원천 조문(제3조, 제3조의2) 필수 확보."""
    sources = search_official_statutes(
        query="가압류가 걸렸는데 대항력과 우선변제권 효력 및 임차권등기명령 절차가 궁금합니다.",
        candidate_laws=["주택임대차보호법"],
        missing_issues=["대항력, 확정일자 우선변제권, 임차권등기명령"],
        max_articles_per_law=4,
    )
    articles = {s["article"] for s in sources}
    assert "제3조" in articles, "대항력 원천 조문(제3조) 누락"
    assert "제3조의2" in articles, "우선변제권 원천 조문(제3조의2) 누락"
    assert "제3조의3" in articles, "임차권등기명령 조문(제3조의3) 누락"


def test_03_branch_article_distinction(mock_law_api):
    """테스트 3: 가지 조문 구분 - 제3조와 제3조의2, 제3조의3이 접두어 혼동 없이 독립 식별됨."""
    sources = search_official_statutes(
        query="보증금 회수 요건",
        candidate_laws=["주택임대차보호법 제3조의2"],
        max_articles_per_law=1,
    )
    assert len(sources) == 1
    assert sources[0]["article"] == "제3조의2"
    assert sources[0]["article"] != "제3조"


def test_04_same_law_multiple_issues_deduplication():
    """테스트 4: 동일 법령의 복수 쟁점 - pending_searches에서 대항력과 우선변제권이 둘 다 보존됨."""
    state = {
        "question": "대항력과 우선변제권이 어떻게 되나요?",
        "verification_result": {
            "status": "REVISE",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "candidate_laws": ["주택임대차보호법"],
            "legal_search_requests": [
                {
                    "law_name": "주택임대차보호법",
                    "articles": [],
                    "issue": "대항력 요건",
                    "question_part": "대항력",
                },
                {
                    "law_name": "주택임대차보호법",
                    "articles": [],
                    "issue": "우선변제권 효력",
                    "question_part": "우선변제권",
                },
            ],
        },
        "retrieved_sources": [],
        "statute_search_history": [],
    }
    pending = pending_searches(state)
    assert len(pending) == 2, f"동일 법령의 서로 다른 쟁점 2건이 모두 유지되어야 함: {len(pending)}"
    issues = {p["issue"] for p in pending}
    assert "대항력 요건" in issues
    assert "우선변제권 효력" in issues


def test_05_cross_statute_mixing(mock_law_api):
    """테스트 5: 서로 다른 법령의 조문 혼합 - 주택임대차보호법과 민법이 각각 분리되어 조회됨."""
    sources = search_official_statutes(
        query="임대인의 목적물 인도 의무 및 보증금 대항력",
        candidate_laws=["주택임대차보호법 제3조", "민법 제623조"],
        max_articles_per_law=5,
    )
    names = {s["statute_name"] for s in sources}
    assert "주택임대차보호법" in names
    assert "민법" in names
    articles_by_name = {s["statute_name"]: s["article"] for s in sources}
    assert articles_by_name["주택임대차보호법"] == "제3조"
    assert articles_by_name["민법"] == "제623조"


def test_06_already_retrieved_statute_not_duplicated():
    """테스트 6: 이미 확보한 조문의 중복 요청 차단 - known 출처에 있으면 pending_searches에서 제외."""
    state = {
        "question": "대항력 조항 다시 확인해 주세요.",
        "verification_result": {
            "status": "REVISE",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "legal_search_requests": [
                {
                    "law_name": "주택임대차보호법",
                    "articles": ["제3조"],
                    "issue": "대항력",
                    "question_part": "대항력",
                }
            ],
        },
        "retrieved_sources": [
            {
                "statute_name": "주택임대차보호법",
                "article": "제3조",
                "source_type": "STATUTE",
                "content": "이미 확보된 제3조 본문",
            }
        ],
        "statute_search_history": [],
    }
    pending = pending_searches(state)
    assert len(pending) == 0, "이미 확보된 조문은 pending_searches에 담기지 않아야 함"


def test_07_max_articles_per_law_cap_preserves_foundational(mock_law_api):
    """테스트 7: max_articles_per_law 한도(4개)가 있어도 원천 조문이 말초 조문에 밀려 탈락하지 않음."""
    sources = search_official_statutes(
        query="임대차 보증금 회수 및 대항력 보호",
        candidate_laws=["주택임대차보호법"],
        missing_issues=["대항력, 확정일자 우선변제권, 경매에 의한 소멸, 보증금 회수"],
        max_articles_per_law=4,
    )
    assert len(sources) <= 4
    articles = {s["article"] for s in sources}
    assert "제3조" in articles
    assert "제3조의2" in articles


def test_08_api_failure_safe_fallback(monkeypatch):
    """테스트 8: 외부 법령 API 장애/타임아웃 시 크래시 없이 안전하게 빈 목록 반환."""
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-key")
    monkeypatch.setattr("ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", lambda *a, **k: None)

    sources = search_official_statutes(
        query="임대차 대항력",
        candidate_laws=["주택임대차보호법 제3조"],
    )
    assert sources == []


def test_09_unapproved_statute_blocked():
    """테스트 9: 사용자 승인 범위 밖 검색 차단 - 승인되지 않은 법령은 execute_document_search에서 차단."""
    state = {
        "question": "보증금 관련 법령 검색해 주세요.",
        "approval_status": "DENIED",  # 미승인
        "approved_statute_laws": ["민법"],
        "verification_result": {
            "candidate_laws": ["주택임대차보호법"],
            "legal_search_requests": [
                {
                    "law_name": "주택임대차보호법",
                    "articles": ["제3조"],
                    "issue": "대항력",
                    "question_part": "보증금",
                }
            ],
        },
        "retrieved_sources": [],
        "statute_search_count": 0,
    }
    res = execute_document_search(state)
    assert res["statute_search_results"] == []


def test_10_generalization_labor_and_civil_domains(mock_law_api):
    """테스트 10: 노동법(근로기준법) 및 민법 영역의 일반화 - 특정 도메인 하드코딩 없이 동일 알고리즘으로 조문 확보."""
    # 근로기준법 쟁점 검색 (퇴직금, 금품 청산)
    labor_sources = search_official_statutes(
        query="퇴직 후 임금 및 퇴직금 지급 기한이 어떻게 되나요?",
        candidate_laws=["근로기준법"],
        missing_issues=["퇴직급여 제도 및 14일 이내 금품 청산 의무"],
        max_articles_per_law=3,
    )
    labor_articles = {s["article"] for s in labor_sources}
    assert "제36조" in labor_articles, "금품 청산 조문(제36조) 확보 필요"

    # 민법 쟁점 검색 (동시이행 항변권)
    civil_sources = search_official_statutes(
        query="상대방이 이행할 때까지 제 채무 이행을 거절할 수 있나요?",
        candidate_laws=["민법"],
        missing_issues=["동시이행의 항변권 요건"],
        max_articles_per_law=3,
    )
    civil_articles = {s["article"] for s in civil_sources}
    assert "제536조" in civil_articles, "동시이행의 항변권 조문(제536조) 확보 필요"

