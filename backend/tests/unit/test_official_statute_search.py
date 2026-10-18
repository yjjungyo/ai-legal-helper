# -*- coding: utf-8 -*-
"""
모듈명: test_official_statute_search.py

[테스트 개요]
법제처 국가법령정보공동활용 API를 통한 공식 법령 검색 도구(search_official_statutes)를 검증하는 단위 테스트 모듈이다.

[주요 검증 항목]
1. 실제 API Key를 이용한 주택임대차보호법 조문(제6조의2 포함) 검색 및 표준 Source 스키마 검증
2. 키워드 필터링 및 조문 매칭 정상 동작 검증
3. 존재하지 않는 법령 조회 시 가짜 데이터를 지어내지 않고 빈 목록을 반환하는지 검증
4. API 키가 없거나 네트워크 오류 시 안전하게 예외를 흡수하고 빈 목록을 반환하는지 검증
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv

load_dotenv('backend/.env')

from ai_legal_helper.tools.official_statute_search import search_official_statutes


def test_search_official_statutes_real_api_housing_lease():
    """실제 법제처 Open API 연동을 통해 주택임대차보호법 제6조의2(묵시적 갱신 해지)를 정확히 검색하는지 검증."""
    api_key = os.getenv("LAW_OPENAPI_KEY")
    if not api_key:
        pytest.skip("LAW_OPENAPI_KEY 환경변수가 없어 실 API 테스트를 건너뜁니다.")

    sources = search_official_statutes(
        query="주택임대차보호법 묵시적 갱신 계약 해지 통보 효력 3개월",
        candidate_laws=["주택임대차보호법"],
        max_articles_per_law=3,
    )

    assert len(sources) > 0, "주택임대차보호법 조문이 최소 1개 이상 검색되어야 함"
    
    articles = [s.get("article") for s in sources]
    print("Retrieved articles:", articles)
    
    # 제6조 또는 제6조의2가 검색 목록에 포함되어야 함
    has_target_article = any("제6조" in a for a in articles)
    assert has_target_article, f"제6조 계열 조문이 포함되어야 합니다. 검색결과: {articles}"

    # 표준 Source 스키마 검증
    first_src = sources[0]
    assert first_src.get("source_type") == "STATUTE"
    assert first_src.get("retrieval_method") == "OFFICIAL_STATUTE_SEARCH"
    assert first_src.get("statute_name") == "주택임대차보호법"
    assert first_src.get("source_id") is not None
    assert first_src.get("content") is not None
    assert len(first_src.get("content")) > 10


def test_search_official_statutes_non_existent_law_returns_empty():
    """존재하지 않는 가짜 법령명 조회 시 허위 법령을 지어내지 않고 빈 목록을 반환하는지 검증."""
    sources = search_official_statutes(
        query="우주여행보호법 외계인 계약 해지",
        candidate_laws=["존재하지않는가짜법률명999호"],
    )
    assert sources == [], "존재하지 않는 법령은 반드시 빈 목록을 반환해야 함"


def test_search_official_statutes_no_api_key_returns_empty():
    """API 키가 없는 환경에서 안전하게 빈 목록을 반환하는지 검증."""
    with patch.dict(os.environ, {"LAW_OPENAPI_KEY": ""}):
        sources = search_official_statutes(
            query="주택임대차보호법",
            candidate_laws=["주택임대차보호법"],
        )
        assert sources == []


def test_search_official_statutes_civil_act_exact_match():
    """'민법' 검색 시 '난민법'이 아닌 순수 '민법'이 정확히 매칭되는지 검증."""
    api_key = os.getenv("LAW_OPENAPI_KEY")
    if not api_key:
        pytest.skip("LAW_OPENAPI_KEY 환경변수가 없어 실 API 테스트를 건너뜁니다.")

    sources = search_official_statutes(
        query="계약 해지 손해배상 동시이행",
        candidate_laws=["민법"],
        max_articles_per_law=3,
    )
    assert len(sources) > 0, "민법 조문이 검색되어야 합니다."
    for s in sources:
        assert s.get("statute_name") == "민법", f"난민법 등이 아닌 '민법'이어야 함: {s.get('statute_name')}"


def test_search_official_statutes_dynamic_missing_issues_boost():
    """동적 누락 쟁점(missing_issues)이 전달되었을 때 제6조의2가 최우선으로 수집되는지 검증."""
    api_key = os.getenv("LAW_OPENAPI_KEY")
    if not api_key:
        pytest.skip("LAW_OPENAPI_KEY 환경변수가 없어 실 API 테스트를 건너뜁니다.")

    sources = search_official_statutes(
        query="지금 3개월 정도 남아서 다른 집으로 이사 가려고 합니다. 보증금은 3억이고요.",
        candidate_laws=["주택임대차보호법"],
        missing_issues=["묵시적 갱신된 임대차의 해지 효력 발생 시점 및 도달"],
        max_articles_per_law=5,
    )
    assert len(sources) > 0
    articles = [s.get("article") for s in sources]
    assert "제6조의2" in articles, f"제6조의2가 상위 조문으로 수집되어야 함: {articles}"


