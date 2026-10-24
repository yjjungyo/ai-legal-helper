# -*- coding: utf-8 -*-
"""
모듈명: loader.py

[역할]
AI Legal Helper Evaluation Harness의 평가 데이터셋 로더 모듈.
Gold Set 시나리오 및 증거 매니페스트를 로드하여 Runner와 Scorer에 제공한다.

[주요 기능]
- `load_gold_case`: SC-001 또는 지정된 시나리오 로드 (P9 요구사항 준수)
- `get_scenario_by_id`: scenario_id 기준 단일 시나리오 반환
- `list_scenarios`: 사용 가능한 시나리오 식별자 목록 반환
- `load_evidence_manifest`: 원문 증거 디렉토리와 DB를 대조한 매니페스트 생성/로드
"""

from typing import List, Optional, Dict, Any
from evaluation_harness.gold.gold_schema import GoldCaseScenario
from evaluation_harness.gold.sc001_gold import ALL_SC001_SCENARIOS, ALL_CORE_SCENARIOS, ALL_VARIATION_SCENARIOS
from evaluation_harness.datasets.manifest import build_evidence_manifest
from evaluation_harness.datasets.schemas import EvidenceManifest


def load_gold_case(scenario_id: Optional[str] = None) -> List[GoldCaseScenario]:
    """P9 인터페이스 규격: Gold 케이스 시나리오 목록을 반환한다.

    Args:
        scenario_id: 특정 시나리오만 필터링할 경우 지정 (예: 'SC01-T01')

    Returns:
        List[GoldCaseScenario]: 조건에 맞는 Gold 시나리오 목록
    """
    if scenario_id:
        matched = [s for s in ALL_SC001_SCENARIOS if s.scenario_id == scenario_id]
        return matched
    return list(ALL_SC001_SCENARIOS)


def get_scenario_by_id(scenario_id: str) -> Optional[GoldCaseScenario]:
    """scenario_id에 해당하는 단일 시나리오를 반환한다.

    Args:
        scenario_id: 시나리오 ID (예: 'SC01-T01', 'SC01-V02')

    Returns:
        Optional[GoldCaseScenario]: 해당 시나리오 또는 None
    """
    for s in ALL_SC001_SCENARIOS:
        if s.scenario_id == scenario_id:
            return s
    return None


def list_scenarios(category: str = "ALL") -> List[str]:
    """사용 가능한 시나리오 ID 목록을 반환한다.

    Args:
        category: 'ALL', 'CORE', 'VARIATION' 중 하나

    Returns:
        List[str]: 시나리오 ID 목록
    """
    if category == "CORE":
        return [s.scenario_id for s in ALL_CORE_SCENARIOS]
    elif category == "VARIATION":
        return [s.scenario_id for s in ALL_VARIATION_SCENARIOS]
    return [s.scenario_id for s in ALL_SC001_SCENARIOS]


def load_evidence_manifest(case_id: str = "fa8f215a-1c55-44e6-9af8-50f336a85717") -> EvidenceManifest:
    """원문 디렉토리와 DB 상태를 비교하여 증거 매니페스트를 빌드한다.

    Args:
        case_id: 대상 사건의 UUID 문자열

    Returns:
        EvidenceManifest: 원본 및 DB 상태가 기록된 매니페스트
    """
    return build_evidence_manifest(case_id=case_id)

