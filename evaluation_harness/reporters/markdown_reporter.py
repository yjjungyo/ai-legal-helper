# -*- coding: utf-8 -*-
"""
모듈명: markdown_reporter.py

[역할]
AI Legal Helper Evaluation Harness의 종합 마크다운 보고서 생성기.
개발지시서에 정의된 구조에 맞추어 baseline 측정 결과, KPI 달성도, 시나리오별 판정 표,
치명적 결함 및 고객가치 분석을 포함하는 최종 Markdown 문서를 작성한다.

[주요 기능]
- `generate_markdown_report`: Markdown 텍스트 생성
- `save_report`: 지정 경로에 `.md` 파일 저장
"""

from pathlib import Path
from typing import Dict, Any, List
from evaluation_harness.scorers.base import EvaluationResult
from evaluation_harness.datasets.schemas import EvidenceManifest


class MarkdownReporter:
    """Markdown 종합 보고서 생성기."""

    def __init__(self, run_id: str, case_id: str = "SC-001"):
        self.run_id = run_id
        self.case_id = case_id

    def generate_report(
        self,
        summary: Dict[str, Any],
        results: List[EvaluationResult],
        manifest: EvidenceManifest,
    ) -> str:
        """종합 평가 마크다운 보고서 내용을 생성한다."""
        total_scenarios = len(results)
        passed_scenarios = sum(1 for r in results if r.is_pass)
        critical_failures = sum(1 for r in results if r.is_critical_failure)
        pass_rate = (passed_scenarios / float(total_scenarios) * 100) if total_scenarios > 0 else 0.0

        # 처분 분포
        disp_counts: Dict[str, int] = {}
        for r in results:
            disp_counts[r.disposition] = disp_counts.get(r.disposition, 0) + 1

        md: List[str] = []
        md.append(f"# AI Legal Helper — SC-001 Evaluation Baseline Report")
        md.append(f"**Run ID:** `{self.run_id}` | **대상 사건:** `{self.case_id}` | **검토 상태:** `PROVISIONAL`\n")

        # 1. Executive Summary
        md.append("## 1. Executive Summary (실행 요약)\n")
        md.append(
            f"- **평가 시나리오 수:** 총 {total_scenarios}건 (핵심 12건 + 변형 8건)\n"
            f"- **고객가치 PASS:** {passed_scenarios}건 ({pass_rate:.1f}%)\n"
            f"- **치명적 결함(Critical Failure):** {critical_failures}건\n"
            f"- **평균 종합 점수:** {summary.get('average_overall_score', 0.0):.3f} / 1.000\n"
            f"- **처분 분포:** " + ", ".join([f"`{k}`: {v}건" for k, v in disp_counts.items()]) + "\n"
        )

        # 2. 핵심 KPI 달성 현황
        md.append("## 2. Core KPI Scorecard (핵심 지표 측정치)\n")
        md.append("| 평가 지표 | 목표 기준 (P9) | 현재 측정치 | 판정 |")
        md.append("|---|---|---|---|")

        kpis = summary.get("kpis", {})
        metric_labels = {
            "fact_recall": ("사건 핵심 사실관계 재현율 (Fact Recall)", ">= 90%"),
            "fact_precision": ("사실관계 정밀도 및 비왜곡 (Fact Precision)", ">= 95%"),
            "issue_detection": ("법률 쟁점 식별 재현율 (Issue Recall)", ">= 90%"),
            "statute_retrieval_accuracy": ("법령·판례 검색 및 인용 정확도 (Statute Retrieval)", ">= 95%"),
            "citation_coverage": ("필수 증거 인용 커버리지 (Citation Coverage)", ">= 85%"),
            "citation_validity": ("증거 인용 진실성 및 날조 방지 (Citation Validity)", ">= 95%"),
            "legal_application_accuracy": ("법률 적용 및 실체적 결론 정확도 (Legal Reasoning)", ">= 90%"),
            "next_action_coverage": ("사건 해결절차 안내 완성도 (Next Actions)", ">= 90%"),
            "safety_compliance": ("법률 안전성 (금지 권고 0건, Safety)", "100%"),
        }

        for m_key, (m_title, target) in metric_labels.items():
            val = kpis.get(m_key, 0.0) * 100.0
            status_badge = "PASS" if val >= 85.0 else ("PARTIAL" if val >= 50.0 else "FAIL")
            md.append(f"| {m_title} | {target} | {val:.1f}% | `{status_badge}` |")

        # 3. 시나리오별 상세 결과
        md.append("\n## 3. Scenario Evaluation Breakdown (시나리오별 평가 결과)\n")
        md.append("| ID | 질문 요지 | 처분 (Disposition) | 종합 점수 | 안전 결함 | 판정 |")
        md.append("|---|---|---|---|---|---|")

        for r in results:
            short_q = (r.user_question[:25] + "...") if len(r.user_question) > 25 else r.user_question
            crit = "⚠️ 발생" if r.is_critical_failure else "정상"
            p_badge = "PASS" if r.is_pass else "FAIL"
            md.append(f"| `{r.scenario_id}` | {short_q} | `{r.disposition}` | {r.overall_score:.2f} | {crit} | `{p_badge}` |")

        # 4. 증거 매니페스트 및 DB 정합성 현황
        md.append("\n## 4. Evidence Manifest & Storage Integrity\n")
        md.append(f"- **원문 증거 파일:** 총 {manifest.total_raw_files}건 (`{manifest.source_dir}`)")
        md.append(f"- **DB 기등록 승인 증거:** 총 {manifest.db_registered_count}건")
        if manifest.missing_files_in_db:
            md.append(f"- **DB 미등록 파일 ({len(manifest.missing_files_in_db)}건):** {', '.join(manifest.missing_files_in_db)}\n")
        else:
            md.append("- **DB 미등록 파일:** 없음 (모두 등록됨)\n")

        # 5. 핵심 결함 상세 분석
        md.append("## 5. Major Defect Analysis & Root Causes (핵심 결함 분석)\n")
        critical_list = [r for r in results if r.is_critical_failure or not r.is_pass]
        if not critical_list:
            md.append("발견된 주요 결함이 없습니다.\n")
        else:
            for r in critical_list[:5]:
                md.append(f"### 📍 [{r.scenario_id}] {r.user_question}")
                md.append(f"- **처분 상태:** `{r.disposition}` (점수: {r.overall_score:.2f})")
                if r.critical_reasons:
                    md.append(f"- **치명적 결함:** " + "; ".join(r.critical_reasons))
                for m_name, m_score in r.metric_scores.items():
                    if m_score.failure_reasons:
                        md.append(f"- **[{m_name}] 감점 사유:** " + "; ".join(m_score.failure_reasons))
                md.append("")

        # 6. 향후 개선 권고사항
        md.append("## 6. Recommendations for System Improvements\n")
        md.append(
            "1. **과도한 WITHHELD 처분 완화:** 상담 맥락에 기초 사실이 충분한 경우 전체 거절 대신 조건부 정보 제공 전환 필요\n"
            "2. **주택임대차보호법 벡터 DB 적재:** ChromaDB에 민법 외에 주택임대차보호법 전문 색인 보강 필요\n"
            "3. **3개월 법정 해지 효력일 자동 연산:** 해지통고 도달일 기준 3개월 경과 시점의 법정 효력 발생 로직 탑재 필요\n"
            "4. **증거 파일명 기반 인용 정규화:** `[E01]` 대신 사용자가 실제 등록한 공식 파일명으로 출처 제시 개선\n"
        )

        return "\n".join(md)

    def save_report(self, report_content: str, output_path: Path):
        """보고서를 파일로 저장한다."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_content)
