# -*- coding: utf-8 -*-
"""
Temporal Legal RAG P0: 기존 기능을 보호하기 위한 기준선 계약 테스트.

[목적]
- 전문 Agent 8종의 명칭 및 기존 검색 Tool 매핑을 보호한다.
- 공식 법령의 ID/버전/공포/시행 메타데이터가 Source 정규화 과정에서 유실되지 않는지 확인한다.
- 명시적 조문 시행일과 공포번호별 부칙 연결을 회귀 검사한다.
- P1에서 반드시 해결할 시행일 미확인 정책을 xfail로 드러낸다.

[주의]
- 외부 OpenLaw·LLM·ChromaDB·PostgreSQL에 연결하지 않는 단위 테스트다.
- 임의의 법령과 날짜는 테스트 픽스처이며 특정 실제 법령에 대한 판단이 아니다.
- xfail은 해결된 기능이 아니다. 다음 Phase에서 정책 변경 후 정상 PASS로 전환한다.
"""
import xml.etree.ElementTree as ET

import pytest

from ai_legal_helper.agents.constants import (
    CATEGORIES,
    collection_name_for,
    get_agent_name,
    get_tool_name,
)
from ai_legal_helper.rag.source_schema import (
    is_statute_applicable_to_date,
    normalize_source_dict,
)
from ai_legal_helper.tools.statute_temporal import (
    article_effective_date,
    extract_addenda,
)


def test_existing_eight_agents_and_tools_remain_available():
    """검색 공통화 과정에서 기존 8개 전문 Agent의 계약을 삭제하지 않는다."""
    expected = {
        "헌법": "constitution",
        "민법": "civil",
        "형법": "criminal",
        "상법": "commercial",
        "노동": "labor",
        "행정": "administrative",
        "조세": "tax",
        "국제": "international",
    }
    assert set(CATEGORIES) == set(expected)
    for category, english in expected.items():
        assert get_agent_name(category) == f"{english}_agent"
        assert get_tool_name(category) == f"{english}_retrieval_tool"
        assert collection_name_for(category) == f"law_docs_{english}"


def test_official_source_metadata_survives_normalization():
    """공식 법령 원문 메타데이터가 공통 Source 변환 중 누락되지 않아야 한다."""
    original = {
        "source_id": "official-test-law-v2-art-3",
        "source_type": "STATUTE",
        "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
        "statute_name": "테스트법",
        "law_id": "TEST-LAW-ID",
        "version_id": "TEST-VERSION-2",
        "article": "제3조",
        "content": "제3조(시험) 이 조문은 테스트용입니다.",
        "promulgation_date": "2026-06-01",
        "promulgation_number": "제9999호",
        "effective_date": "2026-12-01",
        "source_url": "https://www.law.go.kr",
    }
    normalized = normalize_source_dict(original)
    for field in (
        "source_id", "source_type", "retrieval_method", "statute_name",
        "law_id", "version_id", "article", "content", "promulgation_date",
        "promulgation_number", "effective_date", "source_url",
    ):
        assert normalized[field] == original[field], field


def test_addenda_are_bound_to_matching_promulgation_number():
    """다른 공포번호의 부칙을 섞으면 안 된다."""
    root = ET.Element("법령")
    for number in ("9998", "9999"):
        node = ET.SubElement(root, "부칙단위")
        ET.SubElement(node, "부칙공포번호").text = number
        ET.SubElement(node, "부칙공포일자").text = "20260601"
        ET.SubElement(node, "부칙내용").text = f"제1조(시행일) 공포번호 {number} 관련 부칙."
    matched = extract_addenda(root, "제9999호")
    assert len(matched) == 1
    assert matched[0].promulgation_number == "9999"
    assert "9999" in matched[0].content
    assert "9998" not in matched[0].content


def test_explicit_article_effective_date_has_priority():
    """조문 시행일이 명시되어 있으면 법령 공통 날짜보다 우선해야 한다."""
    node = ET.Element("조문단위")
    ET.SubElement(node, "조문시행일자").text = "20270115"
    effective, origin = article_effective_date(node, "제3조", [])
    assert effective == "2027-01-15"
    assert origin == "ARTICLE_EFFECTIVE_DATE"


def test_explicit_effective_date_checks_before_and_after():
    """기존 판정 함수의 날짜 비교 동작을 기준선으로 확인한다."""
    source = {"source_type": "STATUTE", "effective_date": "2027-01-15"}
    assert is_statute_applicable_to_date(source, "2026-11-01") is False
    assert is_statute_applicable_to_date(source, "2027-02-01") is True


@pytest.mark.xfail(
    reason="P1 작업: 시행일·적용례 미확인은 True가 아닌 명시적 UNCONFIRMED여야 한다",
    strict=False,
)
def test_unknown_effective_date_must_not_be_auto_applicable():
    """현재 알려진 위험을 기록한다. P1에서 3상 판정 API로 교체 후 PASS로 전환."""
    source = {"source_type": "STATUTE", "statute_name": "테스트법"}
    assert is_statute_applicable_to_date(source, "2026-11-01") is not True


@pytest.mark.xfail(
    reason="P1 작업: 파일명 날짜만으로 공식 조문 시행일을 확정하면 안 된다",
    strict=False,
)
def test_filename_date_must_not_be_treated_as_verified_effective_date():
    """PDF 파일명에서 유추한 날짜는 공식 확인된 시행일과 분리해야 한다."""
    source = normalize_source_dict({
        "source_id": "legacy-test",
        "source_type": "STATUTE",
        "filename": "테스트법(법률)(제9999호)(20270115).pdf",
        "statute_name": "테스트법",
        "article": "제3조",
        "content": "제3조(시험) 테스트 내용",
    })
    assert source["effective_date"] is None
