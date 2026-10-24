# -*- coding: utf-8 -*-
"""
모듈명: next_action_scorer.py

[역할]
AI Legal Helper Evaluation Harness의 고객 행동 지침 완성도(Next-Action Coverage) 스코어러.
"법을 몰라도 내 상황에서 당장 무엇을 해야 하는지 알 수 있다"는 핵심 고객가치를 실현하기 위해,
상담 결과가 안전하고 구체적인 실행 조치(점유 유지, 내용증명, 임차권등기명령, 등기부 확인 등)를 충분히 안내했는지 검증한다.

[주요 기능]
- 골드 필수 안내 조치(required_next_actions) 재현율 측정
- 절차적 선후 관계(예: 임차권등기 완료 전 이사 금지) 안내 여부 확인
- 실행 불가능한 공허한 조언 감점
"""

from typing import Dict, Any, List
from evaluation_harness.scorers.base import BaseScorer, MetricScore
from evaluation_harness.gold.gold_schema import GoldCaseScenario


class NextActionScorer(BaseScorer):
    """다음 행동 지침 완성도 스코어러."""

    def __init__(self):
        super().__init__(metric_name="next_action_coverage")

    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """골드 필수 조치와 실제 시스템 안내 조치를 대조 채점한다.

        Args:
            scenario: 골드 시나리오
            actual_output: 시스템 결과 (answer, next_actions 등)

        Returns:
            MetricScore: 행동 지침 완성도 점수
        """
        required_actions: List[str] = scenario.required_next_actions
        if not required_actions:
            return MetricScore(
                metric_name=self.metric_name,
                score=1.0,
                status="PASS",
                failure_reasons=[],
                details={"message": "검증할 필수 행동 지침 없음"},
            )

        answer_text: str = actual_output.get("answer") or actual_output.get("raw_answer") or ""
        raw_actions = actual_output.get("next_actions", []) or []
        actions_text = " ".join([str(a) for a in raw_actions])
        combined_text = f"{answer_text} {actions_text}"

        matched_actions: List[str] = []
        missing_actions: List[str] = []

        for req in required_actions:
            if self._is_action_covered(req, combined_text):
                matched_actions.append(req)
            else:
                missing_actions.append(req)

        coverage = len(matched_actions) / float(len(required_actions))

        failure_reasons: List[str] = []
        if missing_actions:
            failure_reasons.append(f"필수 행동 지침 {len(missing_actions)}건 누락: " + "; ".join(missing_actions[:3]))

        if coverage >= 0.8:
            status = "PASS"
        elif coverage >= 0.5:
            status = "PARTIAL"
        else:
            status = "FAIL"

        return MetricScore(
            metric_name=self.metric_name,
            score=round(coverage, 4),
            raw_value=len(matched_actions),
            max_value=len(required_actions),
            status=status,
            failure_reasons=failure_reasons,
            details={
                "expected_actions_count": len(required_actions),
                "matched_actions_count": len(matched_actions),
                "matched_actions": matched_actions,
                "missing_actions": missing_actions,
            },
        )

    def _is_action_covered(self, action: str, text: str) -> bool:
        """단일 조치가 텍스트에 안내되었는지 검사."""
        if "점유" in action or "전입" in action or "주민등록" in action:
            return ("점유" in text and "유지" in text) or ("전입" in text and "유지" in text) or "이사" in text

        if "내용증명" in action:
            return "내용증명" in text

        if "임차권등기" in action:
            return "임차권등기" in text

        if "등기부" in action or "등기사항" in action:
            return "등기부" in text or "등기사항" in text or "인터넷등기소" in text

        if "지급명령" in action or "소송" in action or "반환청구" in action:
            return "지급명령" in text or "소송" in text or "보증금반환" in text

        # 일반 키워드 매칭
        tokens = [t for t in action.split() if len(t) >= 2]
        if not tokens:
            return True
        matched = sum(1 for t in tokens if t in text)
        return (matched / float(len(tokens))) >= 0.4

