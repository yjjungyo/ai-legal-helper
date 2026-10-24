# -*- coding: utf-8 -*-
"""
패키지명: evaluation_harness.scorers

[역할]
AI Legal Helper Evaluation Harness의 스코어러 패키지 진입점.
모든 결정론적 평가 스코어러(Fact, Issue, Retrieval, Citation, LegalApplication, NextAction, Safety)를
제공하고, N/A 가중치 동적 재정규화(Dynamic Weight Renormalization)를 통해 종합 성적표(EvaluationResult)를 산출한다.

[주요 기능]
1. 개별 스코어러 분리 실행:
   - 사실: FactRecallScorer, FactPrecisionScorer
   - 쟁점: IssueScorer
   - 법령: RetrievalScorer
   - 인용: CitationCoverageScorer, CitationValidityScorer
   - 적용: LegalApplicationScorer
   - 후속: NextActionScorer
   - 안전: SafetyScorer (치명적 결함 게이트키퍼)
2. N/A 동적 재정규화:
   - 해당 시나리오에서 검증 대상이 아닌 지표(N/A)는 가중치 분모에서 제외하고 남은 유효 지표들의 가중치를 1.0으로 재정규화
3. 안전성 결함 독립 판정:
   - 단순 판단 유보(WITHHELD)를 치명적 안전 결함으로 오인하지 않음
"""

from typing import Dict, Any, List
from evaluation_harness.scorers.base import BaseScorer, MetricScore, EvaluationResult
from evaluation_harness.scorers.fact_scorer import FactRecallScorer, FactPrecisionScorer, FactScorer
from evaluation_harness.scorers.issue_scorer import IssueScorer
from evaluation_harness.scorers.retrieval_scorer import RetrievalScorer
from evaluation_harness.scorers.citation_scorer import CitationCoverageScorer, CitationValidityScorer, CitationScorer
from evaluation_harness.scorers.legal_application_scorer import LegalApplicationScorer
from evaluation_harness.scorers.next_action_scorer import NextActionScorer
from evaluation_harness.scorers.safety_scorer import SafetyScorer
from evaluation_harness.gold.gold_schema import GoldCaseScenario


def evaluate_scenario(scenario: GoldCaseScenario, actual_output: Dict[str, Any], run_id: str = "run_default") -> EvaluationResult:
    """단일 시나리오에 대해 모든 분리된 스코어러를 실행하고 동적 가중치 재정규화로 종합 점수를 산출한다.

    Args:
        scenario: 골드 시나리오
        actual_output: 시스템 실행 결과 딕셔너리
        run_id: 평가 실행 ID

    Returns:
        EvaluationResult: 지표별 점수 및 종합 판정
    """
    scorers: List[BaseScorer] = [
        FactRecallScorer(),
        FactPrecisionScorer(),
        IssueScorer(),
        RetrievalScorer(),
        CitationCoverageScorer(),
        CitationValidityScorer(),
        LegalApplicationScorer(),
        NextActionScorer(),
        SafetyScorer(),
    ]

    metric_scores: Dict[str, MetricScore] = {}
    is_critical_failure = False
    critical_reasons: List[str] = []

    for scorer in scorers:
        mscore = scorer.score(scenario, actual_output)
        metric_scores[scorer.metric_name] = mscore

        # 안전성 스코어러에서 치명적 결함 검출 시 기록
        if isinstance(scorer, SafetyScorer):
            if mscore.details.get("is_critical_failure", False):
                is_critical_failure = True
                critical_reasons.extend(mscore.failure_reasons)

    # 8대 핵심 평가 지표의 기본 가중치 (합계: 1.0)
    base_weights = {
        "fact_recall": 0.12,
        "fact_precision": 0.08,
        "issue_detection": 0.18,
        "statute_retrieval_accuracy": 0.12,
        "citation_coverage": 0.08,
        "citation_validity": 0.07,
        "legal_application_accuracy": 0.22,
        "next_action_coverage": 0.13,
    }

    # N/A 항목 제외 및 가중치 동적 재정규화
    applicable_weighted_sum = 0.0
    total_applicable_weight = 0.0

    for name, weight in base_weights.items():
        if name in metric_scores:
            ms = metric_scores[name]
            if ms.status != "N/A" and ms.score is not None:
                applicable_weighted_sum += ms.score * weight
                total_applicable_weight += weight

    overall = (applicable_weighted_sum / total_applicable_weight) if total_applicable_weight > 0 else 0.0

    if is_critical_failure:
        overall = 0.0
        is_pass = False
    else:
        # P0 개발지시서 기준: 핵심 KPI 80% 이상 & N/A가 아닌 지표 중 FAIL이 없을 때 PASS
        is_pass = (overall >= 0.8) and all(
            ms.status != "FAIL" for ms in metric_scores.values() if ms.status != "N/A"
        )

    disposition = actual_output.get("disposition", "UNKNOWN")
    raw_answer = actual_output.get("answer") or actual_output.get("raw_answer") or ""

    return EvaluationResult(
        case_id=scenario.case_id,
        scenario_id=scenario.scenario_id,
        run_id=run_id,
        user_question=scenario.user_question,
        disposition=disposition,
        raw_answer=raw_answer,
        metric_scores=metric_scores,
        overall_score=round(overall, 4),
        is_pass=is_pass,
        is_critical_failure=is_critical_failure,
        critical_reasons=critical_reasons,
        latency_seconds=actual_output.get("latency_seconds", 0.0),
        token_usage=actual_output.get("token_usage", {}),
    )


__all__ = [
    "BaseScorer",
    "MetricScore",
    "EvaluationResult",
    "FactRecallScorer",
    "FactPrecisionScorer",
    "FactScorer",
    "IssueScorer",
    "RetrievalScorer",
    "CitationCoverageScorer",
    "CitationValidityScorer",
    "CitationScorer",
    "LegalApplicationScorer",
    "NextActionScorer",
    "SafetyScorer",
    "evaluate_scenario",
]
