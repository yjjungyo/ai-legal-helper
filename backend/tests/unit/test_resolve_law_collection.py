"""법령별 ChromaDB 적재 컬렉션 자동 판별 단위 테스트.

법령의 소관 분야(민사, 행정, 형사, 노동, 상사, 조세, 헌법 등)에 따라
올바른 도메인 컬렉션(law_docs_{category})으로 라우팅되고,
미식별/일반 법령의 경우 기본 전역 컬렉션(law_docs_global)으로 정상 폴백되는지 검증한다.
"""

import pytest
from ai_legal_helper.legal_knowledge.index_worker import resolve_law_collection


def test_resolve_law_collection_civil():
    """민사 관련 법령이 law_docs_civil 컬렉션으로 정상 매핑되는지 검증."""
    assert resolve_law_collection("민법") == "law_docs_civil"
    assert resolve_law_collection("주택임대차보호법") == "law_docs_civil"
    assert resolve_law_collection("상가건물 임대차보호법") == "law_docs_civil"
    assert resolve_law_collection("가등기담보 등에 관한 법률") == "law_docs_civil"
    assert resolve_law_collection("부동산 실권리자명의 등기에 관한 법률") == "law_docs_civil"
    assert resolve_law_collection("민사소송법") == "law_docs_civil"
    assert resolve_law_collection("민사집행법") == "law_docs_civil"


def test_resolve_law_collection_administrative():
    """행정 관련 법령 및 시행령/시행규칙이 law_docs_administrative 컬렉션으로 정상 매핑되는지 검증."""
    assert resolve_law_collection("민간임대주택에 관한 특별법") == "law_docs_administrative"
    assert resolve_law_collection("민간임대주택에 관한 특별법 시행령") == "law_docs_administrative"
    assert resolve_law_collection("민간임대주택에 관한 특별법 시행규칙") == "law_docs_administrative"
    assert resolve_law_collection("공인중개사법") == "law_docs_administrative"
    assert resolve_law_collection("건축법") == "law_docs_administrative"
    assert resolve_law_collection("행정기본법") == "law_docs_administrative"


def test_resolve_law_collection_criminal():
    """형사 관련 법령이 law_docs_criminal 컬렉션으로 정상 매핑되는지 검증."""
    assert resolve_law_collection("형법") == "law_docs_criminal"
    assert resolve_law_collection("형사소송법") == "law_docs_criminal"
    assert resolve_law_collection("도로교통법") == "law_docs_criminal"
    assert resolve_law_collection("특정범죄 가중처벌 등에 관한 법률") == "law_docs_criminal"


def test_resolve_law_collection_other_domains():
    """노동, 상사, 조세, 헌법 분야 법령이 각 전용 컬렉션으로 정상 매핑되는지 검증."""
    assert resolve_law_collection("근로기준법") == "law_docs_labor"
    assert resolve_law_collection("상법") == "law_docs_commercial"
    assert resolve_law_collection("국세기본법") == "law_docs_tax"
    assert resolve_law_collection("대한민국헌법") == "law_docs_constitution"


def test_resolve_law_collection_fallback_to_global():
    """도메인이 미분류된 일반 법령 및 결측값의 경우 기본 전역 컬렉션(law_docs_global)으로 폴백되는지 검증."""
    assert resolve_law_collection("미지의 신설 우주항공법") == "law_docs_global"
    assert resolve_law_collection("") == "law_docs_global"
    assert resolve_law_collection(None) == "law_docs_global"
