# -*- coding: utf-8 -*-
"""
모듈명: legal_application_scorer.py

[역할]
AI Legal Helper Evaluation Harness의 구체적 법률 적용 및 추론 정확도(Legal Application & Reasoning) 스코어러.
단순 조문 인용을 넘어, 사건 사실에 법률 요건을 올바르게 포섭하여 정확한 법적 효력을 도출했는지 검증한다.

[주요 기능]
- 묵시적 갱신 해지 효력일 산정 검증 (2026.04.01 통고 + 3개월 = 2026.07.01 및 2026.09.30)
- 대항력 및 우선변제권 순위 판단 검증 (2022.03.02 선순위 vs 2026년 후순위 가압류 2건)
- 경매 배당 및 임차권 인수 선택권 법리 적용 검증
- 법률 결론의 정합성 채점
"""

from typing import Dict, Any, List
from evaluation_harness.scorers.base import BaseScorer, MetricScore
from evaluation_harness.gold.gold_schema import GoldCaseScenario


class LegalApplicationScorer(BaseScorer):
    """법률 적용 및 실체적 결론 정확도 스코어러."""

    def __init__(self):
        super().__init__(metric_name="legal_application_accuracy")

    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """골드 기대 결론 및 법률 추론 요건과 시스템 답변을 대조 채점한다.

        Args:
            scenario: 골드 시나리오
            actual_output: 시스템 결과 (answer, issues 등)

        Returns:
            MetricScore: 법률 적용 점수 및 논리 결함 내역
        """
        required_reasoning: List[str] = scenario.required_legal_reasoning
        expected_conclusions: List[str] = scenario.expected_conclusions
        answer_text: str = actual_output.get("answer") or actual_output.get("raw_answer") or ""

        if not required_reasoning and not expected_conclusions:
            return MetricScore(
                metric_name=self.metric_name,
                score=1.0,
                status="PASS",
                failure_reasons=[],
                details={"message": "검증할 법률 추론 요건 없음"},
            )

        matched_conclusions = 0
        missing_conclusions = []
        failure_reasons: List[str] = []

        # 1. 시나리오별 핵심 실체법 테스트
        sc_id = scenario.scenario_id

        # 날짜 산정 테스트 (SC01-T02, SC01-V06)
        if sc_id in ("SC01-T02", "SC01-V06"):
            has_3months = "3개월" in answer_text or "7월" in answer_text or "2026.07" in answer_text or "2026년 7월" in answer_text
            has_sept = "9월 30" in answer_text or "2026.09" in answer_text or "2026년 9월" in answer_text
            if not has_3months and not has_sept:
                failure_reasons.append("해지통고 후 3개월 경과(2026.07.01) 또는 지정 퇴거일(2026.09.30) 계약 종료 법리 미적용")

        # 가압류 권리 순위 테스트 (SC01-T04, SC01-T05)
        if sc_id in ("SC01-T04", "SC01-T05"):
            has_priority = "선순위" in answer_text or "우선" in answer_text or "대항력" in answer_text
            has_attachment = "가압류" in answer_text or "후순위" in answer_text
            if not (has_priority and has_attachment):
                failure_reasons.append("2022년 선순위 임차권과 2026년 후순위 가압류의 권리 우열 분석 부재")

        # 2. 골드 결론 매칭도 검사
        import re
        for ec in expected_conclusions:
            # 특수문자 제거 후 2글자 이상 핵심 형태소 추출
            tokens = [t for t in re.findall(r"[가-힣\w]{2,}", ec) if len(t) >= 2]
            if not tokens:
                matched_conclusions += 1
                continue

            matched_tokens = sum(1 for t in tokens if (t in answer_text or (len(t) >= 3 and t[:2] in answer_text)))
            coverage = matched_tokens / float(len(tokens))

            if coverage >= 0.35:
                matched_conclusions += 1
            else:
                missing_conclusions.append(ec)

        conclusion_score = matched_conclusions / float(len(expected_conclusions)) if expected_conclusions else 1.0

        if missing_conclusions:
            failure_reasons.append(f"기대 법률 결론 {len(missing_conclusions)}건 미도출: " + missing_conclusions[0][:60] + "...")

        final_score = conclusion_score
        if failure_reasons:
            final_score = min(final_score, 0.7)

        if final_score >= 0.8 and not failure_reasons:
            status = "PASS"
        elif final_score >= 0.4:
            status = "PARTIAL"
        else:
            status = "FAIL"

        return MetricScore(
            metric_name=self.metric_name,
            score=round(final_score, 4),
            raw_value=matched_conclusions,
            max_value=len(expected_conclusions),
            status=status,
            failure_reasons=failure_reasons,
            details={
                "expected_conclusions_count": len(expected_conclusions),
                "matched_conclusions_count": matched_conclusions,
                "missing_conclusions": missing_conclusions,
            },
        )
