# -*- coding: utf-8 -*-
"""
테스트 모듈: test_statute_alias_and_search_fallback.py

[테스트 목적]
1. 국가법령정보센터(open.law.go.kr) 공식 법령 검색 시 LLM 및 실무 약칭('특례법', '주임법' 등)이
   공식 법령명('소송촉진 등에 관한 특례법', '주택임대차보호법' 등)으로 올바르게 정규화되는지 검증한다.
2. 검증 모델(VerificationOutput) 파싱 단계에서 약칭이 들어오더라도 공식 법령명으로 자동 교정되는지 검증한다.
3. 법령 검색 결과가 0건일 때 `statute_search_status`가 'NOT_FOUND'로 명시 설정되는지 검증한다.
4. 사후 검증 단계에서 외부 법령 검색 결과가 없더라도, 기존 초안(draft_answer)이 확보된 경우
   상담을 'insufficient'(판단 유보)로 폐기하지 않고 're_analyze'로 안전하게 분기하는지 검증한다.
"""
from typing import Dict, Any
import pytest
from unittest.mock import patch

from ai_legal_helper.tools.official_statute_search import (
    normalize_statute_name,
    _prepare_search_targets,
    _split_statute_reference,
)
from ai_legal_helper.agents.verification import VerificationOutput
from ai_legal_helper.workflows.legal_workflow import (
    execute_statute_search_node,
    statute_search_result_condition,
)


def test_normalize_statute_name_aliases():
    """주요 법률 약칭이 국가법령정보센터 공식 법령명으로 정확히 정규화되는지 테스트."""
    # 소송촉진 등에 관한 특례법 계열
    assert normalize_statute_name("특례법") == "소송촉진 등에 관한 특례법"
    assert normalize_statute_name("소촉법") == "소송촉진 등에 관한 특례법"
    assert normalize_statute_name("소송촉진특례법") == "소송촉진 등에 관한 특례법"

    # 주임법 및 상임법
    assert normalize_statute_name("주임법") == "주택임대차보호법"
    assert normalize_statute_name("상임법") == "상가건물 임대차보호법"

    # 민사집행법 및 소송법
    assert normalize_statute_name("민집법") == "민사집행법"
    assert normalize_statute_name("민소법") == "민사소송법"

    # 일반 법령명은 그대로 보존
    assert normalize_statute_name("민법") == "민법"
    assert normalize_statute_name("형법") == "형법"


def test_verification_output_normalizes_candidate_laws():
    """LLM이 약칭을 출력하더라도 VerificationOutput Pydantic 모델에서 공식 명칭으로 자동 교정되는지 테스트."""
    vo = VerificationOutput(
        status="REVISE",
        reason_code="LEGAL_SOURCE_MISSING",
        candidate_laws=["특례법", "주임법", "민법"],
    )
    assert vo.candidate_laws == ["소송촉진 등에 관한 특례법", "주택임대차보호법", "민법"]


def test_split_statute_reference_with_alias():
    """약칭과 조문이 함께 입력되었을 때 공식 법령명 및 조문이 정상 분리되는지 테스트."""
    target = _split_statute_reference("특례법 제3조")
    assert target is not None
    assert target.law_name == "소송촉진 등에 관한 특례법"
    assert target.articles == ["제3조"]

    target_juim = _split_statute_reference("주임법 제3조의2")
    assert target_juim is not None
    assert target_juim.law_name == "주택임대차보호법"
    assert target_juim.articles == ["제3조의2"]


def test_prepare_search_targets_normalizes_aliases():
    """후보 법령 목록 전체가 공식 명칭으로 정규화되고 병합되는지 테스트."""
    candidates = ["특례법 제3조", "민법 제536조", "특례법 제3조제1항"]
    targets = _prepare_search_targets(candidates)

    law_names = [t.law_name for t in targets]
    assert "소송촉진 등에 관한 특례법" in law_names
    assert "민법" in law_names
    assert "특례법" not in law_names  # 약칭이 공식 명칭으로 치환됨


@patch("ai_legal_helper.tools.official_statute_search.search_official_statutes")
def test_execute_statute_search_node_status_not_found(mock_search):
    """법제처 검색 결과가 0건일 때 statute_search_status가 NOT_FOUND로 반환되는지 테스트."""
    mock_search.return_value = []

    state: Dict[str, Any] = {
        "question": "보증금 반환 지연이자 계산법 알려줘",
        "approval_status": "APPROVED",
        "approved_statute_laws": ["소송촉진 등에 관한 특례법"],
        "verification_result": {
            "candidate_laws": ["특례법"],
            "missing_legal_issues": ["소송촉진 등에 관한 특례법 제3조"],
        },
        "retrieved_sources": [],
    }

    result = execute_statute_search_node(state)

    assert result["statute_search_status"] == "NOT_FOUND"
    assert result["statute_search_results"] == []
    assert any("조문을 찾지 못했습니다" in w for w in result["warnings"])


@patch("ai_legal_helper.tools.official_statute_search.search_official_statutes")
def test_execute_statute_search_node_status_success(mock_search):
    """법제처 검색 결과가 존재할 때 statute_search_status가 SUCCESS로 반환되는지 테스트."""
    mock_search.return_value = [
        {"source_id": "OFFICIAL:1234:1", "statute_name": "소송촉진 등에 관한 특례법", "article": "제3조"}
    ]

    state: Dict[str, Any] = {
        "question": "보증금 지연손해금 이율",
        "approval_status": "APPROVED",
        "approved_statute_laws": ["소송촉진 등에 관한 특례법"],
        "verification_result": {
            "candidate_laws": ["특례법"],
        },
        "retrieved_sources": [],
    }

    result = execute_statute_search_node(state)

    assert result["statute_search_status"] == "SUCCESS"
    assert len(result["statute_search_results"]) == 1


def test_statute_search_result_condition_fallback_preserves_draft():
    """검색 결과가 0건(NOT_FOUND)이더라도 기존 초안이 있으면 insufficient 대신 re_analyze로 분기함을 테스트."""
    state_with_draft: Dict[str, Any] = {
        "draft_answer": "1차 완성된 초안 답변 내용...",
        "statute_search_status": "NOT_FOUND",
        "statute_search_results": [],
    }

    # 초안이 있으므로 기존 사실/법률 범위 내에서 안전하게 재분석 진행
    assert statute_search_result_condition(state_with_draft) == "re_analyze"


def test_statute_search_result_condition_insufficient_when_no_draft_and_api_error():
    """초안도 없고 API 에러인 경우 insufficient로 정상 분기함을 테스트."""
    state_without_draft: Dict[str, Any] = {
        "draft_answer": "",
        "statute_search_status": "API_ERROR",
        "statute_search_results": [],
    }

    assert statute_search_result_condition(state_without_draft) == "insufficient"
