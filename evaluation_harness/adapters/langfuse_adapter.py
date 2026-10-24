# -*- coding: utf-8 -*-
"""
모듈명: langfuse_adapter.py

[역할]
AI Legal Helper Evaluation Harness의 Langfuse 관측성 연동 어댑터.
평가 실행 결과(지표 점수, 지연시간, 종합 판정)를 로컬 Langfuse v2.95.11 OSS 인스턴스에 기록한다.

[주요 기능]
- 평가 세션 및 트레이스(Trace) 스코어 태깅
- Langfuse 미가동 또는 비활성화 시 graceful skip (비차단)
"""

import os
import logging
from typing import Dict, Any, Optional
from evaluation_harness.scorers.base import EvaluationResult
from evaluation_harness.config import config

logger = logging.getLogger(__name__)


class LangfuseEvaluationAdapter:
    """Langfuse 평가 점수 기록 어댑터."""

    def __init__(self):
        self.host = config.langfuse_host
        self.public_key = config.langfuse_public_key or os.getenv("LANGFUSE_PUBLIC_KEY")
        self.secret_key = config.langfuse_secret_key or os.getenv("LANGFUSE_SECRET_KEY")
        self.is_enabled = bool(self.public_key and self.secret_key)
        self.client = None

        if self.is_enabled:
            try:
                from langfuse import Langfuse
                self.client = Langfuse(
                    public_key=self.public_key,
                    secret_key=self.secret_key,
                    host=self.host,
                )
            except Exception as e:
                logger.warning(f"Langfuse 클라이언트 초기화 실패 ({e}). 관측성 기록을 건너뜁니다.")
                self.is_enabled = False

    def log_evaluation_result(self, eval_result: EvaluationResult, trace_id: Optional[str] = None):
        """평가 결과를 Langfuse에 점수(Score)로 기록한다.

        Args:
            eval_result: 채점 완료된 EvaluationResult 객체
            trace_id: 원본 상담 trace_id (없을 경우 run_id와 scenario_id로 기록)
        """
        if not self.is_enabled or not self.client:
            return

        try:
            target_trace = trace_id or f"{eval_result.run_id}_{eval_result.scenario_id}"

            # 1. 종합 점수 기록
            self.client.score(
                trace_id=target_trace,
                name="overall_evaluation_score",
                value=eval_result.overall_score,
                comment=f"Pass: {eval_result.is_pass}, Critical: {eval_result.is_critical_failure}",
            )

            # 2. 세부 지표별 점수 기록 (N/A 지표는 value=None이므로 건너뜀)
            for m_name, m_score in eval_result.metric_scores.items():
                if m_score.score is not None:
                    self.client.score(
                        trace_id=target_trace,
                        name=m_name,
                        value=float(m_score.score),
                        comment=m_score.status,
                    )
        except Exception as e:
            logger.debug(f"Langfuse 점수 전송 중 예외 발생: {e}")

    def flush(self):
        """남은 이벤트를 동기화 플러시한다."""
        if self.is_enabled and self.client:
            try:
                self.client.flush()
            except Exception:
                pass

