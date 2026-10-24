# -*- coding: utf-8 -*-
"""
모듈명: base.py

[역할]
AI Legal Helper Evaluation Harness의 스코어러(Scorer) 기본 추상 클래스 및 점수 데이터 모델.
모든 세부 평가 지표 계산 모듈은 본 베이스 클래스를 상속받아 일관된 평가 인터페이스를 제공한다.

[주요 기능]
- `MetricScore`: 단일 지표에 대한 점수(0.0~1.0), 상태(PASS/PARTIAL/FAIL), 세부 근거 모델
- `EvaluationResult`: 시나리오 단위 전체 평가 집계 모델 (Critical Failure 포함)
- `BaseScorer`: score() 추상 인터페이스 정의
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field
from evaluation_harness.gold.gold_schema import GoldCaseScenario


class MetricScore(BaseModel):
    """단일 평가 지표의 점수 및 세부 판정 결과."""

    metric_name: str = Field(..., description="지표 명칭 (예: fact_recall, citation_validity)")
    score: Optional[float] = Field(None, ge=0.0, le=1.0, description="정규화된 점수 (0.0 ~ 1.0, N/A인 경우 None)")
    raw_value: Optional[float] = Field(None, description="원시 측정값 (예: 일치 개수)")
    max_value: Optional[float] = Field(None, description="최대 가능값")
    status: Literal["PASS", "PARTIAL", "FAIL", "N/A"] = Field(..., description="고객가치 관점 판정")
    failure_reasons: List[str] = Field(default_factory=list, description="실패 원인 및 감점 사유")
    details: Dict[str, Any] = Field(default_factory=dict, description="상세 분석 메타데이터")


class EvaluationResult(BaseModel):
    """단일 시나리오에 대한 종합 평가 결과."""

    case_id: str = Field(..., description="사건 ID")
    scenario_id: str = Field(..., description="시나리오 ID (예: SC01-T01)")
    run_id: str = Field(..., description="평가 실행 고유 번호")
    user_question: str = Field(..., description="질문 원문")

    # 시스템 실제 응답 요약
    disposition: str = Field(..., description="최종 처리 처분 (PROCEED, WITHHELD, NEED_INFO 등)")
    raw_answer: str = Field("", description="AI 최종 답변 텍스트")

    # 개별 지표 점수
    metric_scores: Dict[str, MetricScore] = Field(default_factory=dict, description="지표별 평가 점수")

    # 종합 집계 점수
    overall_score: float = Field(0.0, ge=0.0, le=1.0, description="가중 종합 점수")
    is_pass: bool = Field(False, description="최종 통과 여부")

    # 치명적 안전 결함 (Critical Failure)
    is_critical_failure: bool = Field(False, description="금지 권고, 날조 등 치명적 결함 여부")
    critical_reasons: List[str] = Field(default_factory=list, description="치명적 결함 상세")

    # 실행 메타데이터
    latency_seconds: float = Field(0.0, description="응답 소요 시간(초)")
    token_usage: Dict[str, int] = Field(default_factory=dict, description="토큰 사용량")


class BaseScorer(ABC):
    """모든 평가 스코어러의 추상 기반 클래스."""

    def __init__(self, metric_name: str):
        """스코어러 초기화.

        Args:
            metric_name: 지표 식별자
        """
        self.metric_name = metric_name

    @abstractmethod
    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """골드 시나리오와 시스템 실제 출력을 비교하여 점수를 산출한다.

        Args:
            scenario: 정답 골드 시나리오
            actual_output: 시스템 실행 결과 딕셔너리 (answer, disposition, sources, facts, issues 등)

        Returns:
            MetricScore: 계산된 지표 점수 객체
        """
        pass

