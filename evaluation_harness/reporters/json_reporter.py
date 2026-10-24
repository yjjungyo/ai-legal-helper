# -*- coding: utf-8 -*-
"""
모듈명: json_reporter.py

[역할]
AI Legal Helper Evaluation Harness의 기계 판독형 JSON 결과 리포터.
평가 실행 결과, 매니페스트, 지표 점수, 실패 내역, 응답 원문을 표준 JSON 포맷으로 저장한다.

[주요 기능]
- `save_run_artifacts`:
  - `manifest.json`: 증거 매니페스트
  - `summary.json`: 실행 요약 및 KPI
  - `scores.json`: 시나리오별 지표 점수
  - `failures.json`: 실패 및 치명적 결함 상세
  - `responses.json`: 입출력 및 최종 처분 덤프
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from evaluation_harness.scorers.base import EvaluationResult
from evaluation_harness.datasets.schemas import EvidenceManifest


class JSONReporter:
    """JSON 리포트 파일 생성기."""

    def __init__(self, output_dir: Path):
        """리포터 초기화.

        Args:
            output_dir: 결과 파일들이 저장될 디렉토리 경로
        """
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_run_artifacts(
        self,
        manifest: EvidenceManifest,
        summary: Dict[str, Any],
        results: List[EvaluationResult],
    ) -> Dict[str, Path]:
        """모든 평가 산출물을 5대 JSON 파일로 분할 저장한다.

        Args:
            manifest: 증거 매니페스트 객체
            summary: KPI 요약 딕셔너리
            results: 시나리오별 평가 결과 목록

        Returns:
            Dict[str, Path]: 저장된 파일명과 절대 경로 매핑
        """
        saved_paths: Dict[str, Path] = {}

        # 1. manifest.json
        manifest_path = self.output_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest.model_dump(), f, ensure_ascii=False, indent=2)
        saved_paths["manifest"] = manifest_path

        # 2. summary.json
        summary_path = self.output_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        saved_paths["summary"] = summary_path

        # 3. scores.json
        scores_data = [r.model_dump(exclude={"raw_answer"}) for r in results]
        scores_path = self.output_dir / "scores.json"
        with open(scores_path, "w", encoding="utf-8") as f:
            json.dump(scores_data, f, ensure_ascii=False, indent=2)
        saved_paths["scores"] = scores_path

        # 4. failures.json
        failures_data = []
        for r in results:
            if not r.is_pass or r.is_critical_failure:
                failures_data.append({
                    "scenario_id": r.scenario_id,
                    "overall_score": r.overall_score,
                    "is_critical_failure": r.is_critical_failure,
                    "critical_reasons": r.critical_reasons,
                    "failed_metrics": {
                        m_name: m.model_dump()
                        for m_name, m in r.metric_scores.items()
                        if m.status in ("FAIL", "PARTIAL")
                    },
                })
        failures_path = self.output_dir / "failures.json"
        with open(failures_path, "w", encoding="utf-8") as f:
            json.dump(failures_data, f, ensure_ascii=False, indent=2)
        saved_paths["failures"] = failures_path

        # 5. responses.json
        responses_data = [
            {
                "scenario_id": r.scenario_id,
                "user_question": r.user_question,
                "disposition": r.disposition,
                "raw_answer": r.raw_answer,
                "latency_seconds": r.latency_seconds,
            }
            for r in results
        ]
        responses_path = self.output_dir / "responses.json"
        with open(responses_path, "w", encoding="utf-8") as f:
            json.dump(responses_data, f, ensure_ascii=False, indent=2)
        saved_paths["responses"] = responses_path

        return saved_paths

