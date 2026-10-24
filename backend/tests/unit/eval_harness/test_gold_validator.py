# -*- coding: utf-8 -*-
"""
테스트 모듈: test_gold_validator.py

[역할]
Evaluation Harness의 정답 데이터셋 검증기(GoldValidator)의 단위 테스트.
정상적인 시나리오가 올바르게 PASS하는지, 누락 또는 규격 위반 데이터가 정확히 감지되는지 검증한다.

[테스트 케이스]
1. `test_valid_sc001_gold_dataset`: SC-001 20개 시나리오 전체 유효성 검증
2. `test_invalid_scenario_detection`: 필수 필드 누락 및 금지 권고 누락 감지 검증
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest
from evaluation_harness.gold.gold_validator import GoldValidator
from evaluation_harness.gold.sc001_gold import ALL_SC001_SCENARIOS, SC01_T01
from evaluation_harness.gold.gold_schema import GoldCaseScenario


def test_valid_sc001_gold_dataset():
    """SC-001 전체 골드 시나리오 20건이 모두 유효성 검사를 통과해야 한다."""
    is_valid, errors = GoldValidator.validate_dataset(ALL_SC001_SCENARIOS)
    assert is_valid is True, f"검증 실패 내역: {errors}"
    assert len(errors) == 0


def test_invalid_scenario_detection():
    """필수 필드가 누락되었거나 금지 권고가 없는 비정상 시나리오를 감지해야 한다."""
    # prohibited_recommendations가 누락된 시나리오 복제 생성
    bad_scenario = SC01_T01.model_copy(update={"prohibited_recommendations": []})
    is_valid, errors = GoldValidator.validate_scenario(bad_scenario)

    assert is_valid is False
    assert any("prohibited_recommendations" in e for e in errors)

    # question이 비어 있는 시나리오
    bad_q_scenario = SC01_T01.model_copy(update={"user_question": "   "})
    is_valid_q, errors_q = GoldValidator.validate_scenario(bad_q_scenario)

    assert is_valid_q is False
    assert any("user_question" in e for e in errors_q)
