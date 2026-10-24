# -*- coding: utf-8 -*-
"""
모듈명: runner.py

[역할]
AI Legal Helper Evaluation Harness의 핵심 오케스트레이터 및 실행 엔진(Runner).
시나리오 로드, 어댑터 실행, 스코어러 채점, 결과 리포트 저장 및 Langfuse 관측성 연동까지
전체 평가 라이프사이클을 무인 자동화 방식으로 통제한다.

[주요 기능]
- `run_evaluation`: 지정된 데이터셋 및 시나리오 일괄 평가 실행
- 운영 DB 파괴 방지(Non-destructive isolation) 원칙 보장
- 핵심 KPI(사실, 쟁점, 법령, 인용, 법률적용, 절차안내, 안전성) 통계 집계
- 산출물(JSON, Markdown) 자동 저장
"""

import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from evaluation_harness.config import config
from evaluation_harness.datasets.loader import load_gold_case, load_evidence_manifest
from evaluation_harness.adapters.consultation_adapter import ConsultationAdapter
from evaluation_harness.adapters.langfuse_adapter import LangfuseEvaluationAdapter
from evaluation_harness.scorers import evaluate_scenario, EvaluationResult
from evaluation_harness.reporters.json_reporter import JSONReporter
from evaluation_harness.reporters.markdown_reporter import MarkdownReporter

logger = logging.getLogger(__name__)


class EvaluationRunSummary(BaseModel):
    """단일 평가 실행의 종합 요약 모델."""

    run_id: str
    case_id: str
    dataset_name: str
    started_at: str
    completed_at: str
    duration_seconds: float
    total_scenarios: int
    passed_scenarios: int
    pass_rate: float
    critical_failures_count: int
    average_overall_score: float
    disposition_distribution: Dict[str, int]
    kpis: Dict[str, float]
    output_directory: str


class EvaluationRunner:
    """평가 하네스 메인 러너 클래스."""

    def __init__(self, case_id: str = config.default_case_id):
        self.case_id = case_id
        self.adapter = ConsultationAdapter(case_id=case_id)
        self.langfuse_adapter = LangfuseEvaluationAdapter()

    def run_evaluation(
        self,
        dataset_name: str = "sc001_dev",
        scenario_ids: Optional[List[str]] = None,
        run_id: Optional[str] = None,
        output_dir: Optional[Path] = None,
        auto_approve_hilt: bool = True,
    ) -> EvaluationRunSummary:
        """평가 시나리오들을 순차 실행하고 종합 성적표를 생성한다.

        Args:
            dataset_name: 평가 데이터셋 식별자
            scenario_ids: 실행할 시나리오 ID 목록 (None인 경우 전체 실행)
            run_id: 평가 실행 식별자 (미지정 시 타임스탬프 기반 자동 생성)
            output_dir: 산출물 저장 디렉토리
            auto_approve_hilt: HILT 승인 요청 시 자동 승인 및 완료 여부

        Returns:
            EvaluationRunSummary: 실행 결과 통계 요약
        """
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        active_run_id = run_id or f"run_{now_str}"
        target_dir = output_dir or (config.results_dir / active_run_id)
        target_dir.mkdir(parents=True, exist_ok=True)

        start_time = time.perf_counter()
        started_at = datetime.now().isoformat()

        # 1. 시나리오 및 증거 매니페스트 로드
        all_scenarios = load_gold_case()
        if scenario_ids:
            scenarios = [s for s in all_scenarios if s.scenario_id in scenario_ids]
        else:
            scenarios = all_scenarios

        manifest = load_evidence_manifest(case_id=self.case_id)

        # 2. 개별 시나리오 실행 및 채점
        results: List[EvaluationResult] = []
        for idx, sc in enumerate(scenarios, 1):
            logger.info(f"[{idx}/{len(scenarios)}] 시나리오 실행 중: {sc.scenario_id} - {sc.title}")
            try:
                # 비파괴적 파이프라인 호출
                actual_output = self.adapter.run_scenario(sc, auto_approve_hilt=auto_approve_hilt)
                # 결정론적 스코어러 채점
                eval_res = evaluate_scenario(sc, actual_output, run_id=active_run_id)
            except Exception as e:
                logger.error(f"시나리오 {sc.scenario_id} 실행 중 오류 발생: {e}")
                eval_res = EvaluationResult(
                    case_id=sc.case_id,
                    scenario_id=sc.scenario_id,
                    run_id=active_run_id,
                    user_question=sc.user_question,
                    disposition="ERROR",
                    raw_answer=f"실행 중 예외 발생: {str(e)}",
                    is_pass=False,
                    is_critical_failure=True,
                    critical_reasons=[f"시스템 예외: {str(e)}"],
                )

            # Langfuse 점수 기록
            self.langfuse_adapter.log_evaluation_result(eval_res)
            results.append(eval_res)

        self.langfuse_adapter.flush()
        duration = round(time.perf_counter() - start_time, 2)
        completed_at = datetime.now().isoformat()

        # 3. KPI 및 통계 집계
        total_count = len(results)
        passed_count = sum(1 for r in results if r.is_pass)
        critical_count = sum(1 for r in results if r.is_critical_failure)
        pass_rate = round((passed_count / float(total_count) * 100.0) if total_count > 0 else 0.0, 2)
        avg_score = round(sum(r.overall_score for r in results) / float(total_count) if total_count > 0 else 0.0, 4)

        disp_dist: Dict[str, int] = {}
        for r in results:
            disp_dist[r.disposition] = disp_dist.get(r.disposition, 0) + 1

        # 세부 지표별 평균 점수 계산 (N/A 지표는 분모/분자에서 제외)
        metric_sums: Dict[str, float] = {}
        metric_counts: Dict[str, int] = {}
        for r in results:
            for m_name, m_score in r.metric_scores.items():
                if m_score.status != "N/A" and m_score.score is not None:
                    metric_sums[m_name] = metric_sums.get(m_name, 0.0) + m_score.score
                    metric_counts[m_name] = metric_counts.get(m_name, 0) + 1

        kpis = {m: round(metric_sums[m] / float(metric_counts[m]), 4) for m in metric_sums if metric_counts[m] > 0}

        summary_dict = {
            "run_id": active_run_id,
            "case_id": self.case_id,
            "dataset_name": dataset_name,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": duration,
            "total_scenarios": total_count,
            "passed_scenarios": passed_count,
            "pass_rate": pass_rate,
            "critical_failures_count": critical_count,
            "average_overall_score": avg_score,
            "disposition_distribution": disp_dist,
            "kpis": kpis,
            "output_directory": str(target_dir),
        }

        # 4. JSON 산출물 저장
        json_reporter = JSONReporter(output_dir=target_dir)
        json_reporter.save_run_artifacts(manifest=manifest, summary=summary_dict, results=results)

        # 5. Markdown 보고서 생성 및 저장
        md_reporter = MarkdownReporter(run_id=active_run_id, case_id=self.case_id)
        report_content = md_reporter.generate_report(summary=summary_dict, results=results, manifest=manifest)
        report_path = target_dir / "SC001_EVALUATION_REPORT.md"
        md_reporter.save_report(report_content, report_path)

        return EvaluationRunSummary(**summary_dict)

