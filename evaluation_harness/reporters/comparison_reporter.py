# -*- coding: utf-8 -*-
"""
모듈명: comparison_reporter.py

[역할]
AI Legal Helper Evaluation Harness의 회귀 검증 및 버전 간 비교 리포터(Comparison Reporter).
Baseline Run과 Candidate Run 간의 KPI 변화, 개별 시나리오 점수 변동, 개선(Improvement) 및 회귀(Regression)를 추적한다.

[주요 기능]
- 두 평가 실행(Run A vs Run B)의 summary.json 및 scores.json 대조
- 회귀(PASS -> FAIL) 발생 시 P0 경고 플래그 생성
- 지표별 Delta (+/- %) 및 종합 마크다운 Diff 리포트 출력
"""

import json
from pathlib import Path
from typing import Dict, Any, List


class ComparisonReporter:
    """평가 버전 간 비교 및 회귀 분석기."""

    def __init__(self, baseline_dir: Path, candidate_dir: Path):
        self.baseline_dir = baseline_dir
        self.candidate_dir = candidate_dir

    def compare(self) -> Dict[str, Any]:
        """두 실행 결과를 비교하여 딕셔너리로 반환한다."""
        with open(self.baseline_dir / "summary.json", encoding="utf-8") as f:
            base_summary = json.load(f)
        with open(self.candidate_dir / "summary.json", encoding="utf-8") as f:
            cand_summary = json.load(f)

        with open(self.baseline_dir / "scores.json", encoding="utf-8") as f:
            base_scores = {item["scenario_id"]: item for item in json.load(f)}
        with open(self.candidate_dir / "scores.json", encoding="utf-8") as f:
            cand_scores = {item["scenario_id"]: item for item in json.load(f)}

        regressions: List[str] = []
        improvements: List[str] = []
        score_diffs: Dict[str, float] = {}

        for sc_id, base_item in base_scores.items():
            if sc_id in cand_scores:
                cand_item = cand_scores[sc_id]
                diff = round(cand_item["overall_score"] - base_item["overall_score"], 4)
                score_diffs[sc_id] = diff

                if base_item["is_pass"] and not cand_item["is_pass"]:
                    regressions.append(sc_id)
                elif not base_item["is_pass"] and cand_item["is_pass"]:
                    improvements.append(sc_id)

        # KPI Delta 계산
        kpi_deltas: Dict[str, float] = {}
        b_kpis = base_summary.get("kpis", {})
        c_kpis = cand_summary.get("kpis", {})
        for k in b_kpis:
            if k in c_kpis:
                kpi_deltas[k] = round(c_kpis[k] - b_kpis[k], 4)

        return {
            "baseline_run_id": base_summary.get("run_id"),
            "candidate_run_id": cand_summary.get("run_id"),
            "regressions_count": len(regressions),
            "regressions": regressions,
            "improvements_count": len(improvements),
            "improvements": improvements,
            "kpi_deltas": kpi_deltas,
            "scenario_score_diffs": score_diffs,
            "is_regression_detected": len(regressions) > 0,
        }

    def generate_comparison_markdown(self, diff: Dict[str, Any]) -> str:
        """비교 결과를 마크다운 형식으로 생성한다."""
        md: List[str] = []
        md.append("# AI Legal Helper — Run Comparison & Regression Analysis")
        md.append(f"**Baseline:** `{diff['baseline_run_id']}` ➡️ **Candidate:** `{diff['candidate_run_id']}`\n")

        status_text = "🚨 회귀(Regression) 발생!" if diff["is_regression_detected"] else "✅ 회귀 없음"
        md.append(f"### 회귀 판정: {status_text}\n")
        md.append(f"- **개선(Improvements):** {diff['improvements_count']}건 ({', '.join(diff['improvements']) if diff['improvements'] else '없음'})")
        md.append(f"- **회귀(Regressions):** {diff['regressions_count']}건 ({', '.join(diff['regressions']) if diff['regressions'] else '없음'})\n")

        md.append("### KPI 지표 변화")
        md.append("| 평가 지표 | 변화량 (Delta) |")
        md.append("|---|---|")
        for k, v in diff["kpi_deltas"].items():
            sign = "+" if v > 0 else ""
            md.append(f"| {k} | {sign}{v*100:.1f}% |")

        return "\n".join(md)

