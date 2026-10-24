# -*- coding: utf-8 -*-
"""
모듈명: gold_validator.py

[역할]
AI Legal Helper Evaluation Harness의 정답 데이터셋(Gold Dataset) 유효성을 검증한다.
개발지시서 Section 4.2 규격 및 데이터 무결성 규칙을 강제하여, 정답 데이터 자체의 결함을 사전에 차단한다.

[주요 기능]
- GoldCaseScenario 인스턴스 검증 (필수 필드 누락, 빈 리스트, 금지 권고 누락 여부)
- review_status 상태 검증 ("PROVISIONAL" 또는 "VERIFIED_EXPERT")
- 법률 추론 및 결론의 비어있지 않음 검증
- 금지 권고(prohibited_recommendations) 목록의 충실도 검증
- 검증 보고서(ValidationReport) 반환

[설계상 주의]
- Gold 데이터는 인위적으로 조작되지 않아야 하며, 법률 전문가 검토 전까지 기본값은 PROVISIONAL이다.
"""

from typing import List, Dict, Any, Tuple
from pydantic import ValidationError
from evaluation_harness.gold.gold_schema import GoldCaseScenario


class GoldValidationError(Exception):
    """Gold 데이터 검증 실패 예외."""
    pass


class GoldValidator:
    """Gold 데이터셋 정합성 검증기."""

    @staticmethod
    def validate_scenario(scenario: GoldCaseScenario) -> Tuple[bool, List[str]]:
        """단일 Gold 시나리오의 유효성을 검증한다.

        Args:
            scenario: 검증 대상 GoldCaseScenario 객체

        Returns:
            Tuple[bool, List[str]]: (검증 통과 여부, 오류 및 경고 메시지 목록)
        """
        errors: List[str] = []

        # 1. 필수 식별자 및 질문 검증
        if not scenario.case_id or not scenario.case_id.strip():
            errors.append(f"[{scenario.scenario_id}] case_id가 비어 있습니다.")
        if not scenario.scenario_id or not scenario.scenario_id.strip():
            errors.append("scenario_id가 비어 있습니다.")
        if not scenario.user_question or len(scenario.user_question.strip()) < 5:
            errors.append(f"[{scenario.scenario_id}] user_question이 너무 짧거나 비어 있습니다.")

        # 2. 검토 상태 검증 (Section 4.2 필수)
        if scenario.review_status not in ("PROVISIONAL", "VERIFIED_EXPERT"):
            errors.append(
                f"[{scenario.scenario_id}] review_status는 'PROVISIONAL' 또는 'VERIFIED_EXPERT'여야 합니다: {scenario.review_status}"
            )

        # 3. 법률적 판단 및 추론 검증
        if not scenario.required_legal_reasoning:
            errors.append(f"[{scenario.scenario_id}] required_legal_reasoning(필수 법률 요건 포섭 추론)이 비어 있습니다.")
        if not scenario.expected_conclusions:
            errors.append(f"[{scenario.scenario_id}] expected_conclusions(기대 결론)이 비어 있습니다.")

        # 4. 실행 조치 및 안전성(Safety) 검증
        if not scenario.required_next_actions:
            errors.append(f"[{scenario.scenario_id}] required_next_actions(필수 실행 조치)가 비어 있습니다.")

        # 중요 안전 장치: 전세보증금 미반환 사건에서 금지 조치가 누락되었는지 검사
        if not scenario.prohibited_recommendations:
            errors.append(f"[{scenario.scenario_id}] prohibited_recommendations(금지 권고 사항)가 비어 있습니다. 고객가치 침해 위험.")

        # 5. 증거 인용 필수 목록 검증
        if not scenario.evidence_manifest:
            errors.append(f"[{scenario.scenario_id}] evidence_manifest가 비어 있어 관련 증거를 추적할 수 없습니다.")

        is_valid = len(errors) == 0
        return is_valid, errors

    @classmethod
    def validate_dataset(cls, scenarios: List[GoldCaseScenario]) -> Tuple[bool, Dict[str, List[str]]]:
        """시나리오 목록 전체를 검증한다.

        Args:
            scenarios: 검증할 GoldCaseScenario 목록

        Returns:
            Tuple[bool, Dict[str, List[str]]]: (전체 성공 여부, 시나리오 ID별 오류 목록)
        """
        all_errors: Dict[str, List[str]] = {}
        all_passed = True

        if not scenarios:
            all_errors["GLOBAL"] = ["시나리오 목록이 비어 있습니다."]
            return False, all_errors

        scenario_ids = set()
        for sc in scenarios:
            # ID 중복 검사
            if sc.scenario_id in scenario_ids:
                all_errors.setdefault(sc.scenario_id, []).append(f"중복된 scenario_id입니다: {sc.scenario_id}")
                all_passed = False
            scenario_ids.add(sc.scenario_id)

            passed, errs = cls.validate_scenario(sc)
            if not passed:
                all_passed = False
                all_errors[sc.scenario_id] = errs

        return all_passed, all_errors

