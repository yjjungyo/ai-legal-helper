# -*- coding: utf-8 -*-
"""
모듈명: retrieval_scorer.py

[역할]
AI Legal Helper Evaluation Harness의 법령 검색 및 인용 정확도(Statute Retrieval Recall & Accuracy) 스코어러.
사건 해결에 필수적인 법령 조문(주택임대차보호법 제3조, 제3조의2, 제6조의2, 제3조의3 등)이 실제로 검색되고
답변의 법적 근거로 활용되었는지 검증한다.

[주요 기능]
- 골드 필수 법령(applicable_statutes) 대비 실제 검색된 출처(sources) 및 인용 조문 재현율 측정
- 허위 조문 검색 여부 판별
- 법령명 및 조항 번호 정규화 비교
"""

import re
from typing import Dict, Any, List
from evaluation_harness.scorers.base import BaseScorer, MetricScore
from evaluation_harness.gold.gold_schema import GoldCaseScenario, ExpectedStatute


class RetrievalScorer(BaseScorer):
    """법령 검색 및 인용 정확도 스코어러."""

    def __init__(self):
        super().__init__(metric_name="statute_retrieval_accuracy")

    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """골드 적용 법령과 시스템의 검색/인용 법령을 비교 채점한다.

        Args:
            scenario: 골드 시나리오
            actual_output: 시스템 결과 (sources, answer 등)

        Returns:
            MetricScore: 법령 검색 점수 및 누락 내역
        """
        expected_statutes: List[ExpectedStatute] = scenario.applicable_statutes
        if not expected_statutes:
            return MetricScore(
                metric_name=self.metric_name,
                score=None,
                status="N/A",
                failure_reasons=[],
                details={"message": "검증할 필수 법령 없음 (허위 법령 검증 또는 비법령 시나리오)"},
            )

        answer_text: str = actual_output.get("answer") or actual_output.get("raw_answer") or ""
        sources = actual_output.get("sources", []) or []
        source_texts = " ".join([
            (s.get("title", "") + " " + s.get("content", "") + " " + s.get("law_name", "") + " " + s.get("article", ""))
            if isinstance(s, dict) else str(s)
            for s in sources
        ])
        search_corpus = f"{answer_text} {source_texts}"

        matched_statutes: List[str] = []
        missing_statutes: List[str] = []

        for es in expected_statutes:
            if self._is_statute_referenced(es, search_corpus):
                matched_statutes.append(es.statute_id)
            else:
                missing_statutes.append(f"{es.law_name} {es.article}")

        recall = len(matched_statutes) / float(len(expected_statutes))

        failure_reasons: List[str] = []
        if missing_statutes:
            failure_reasons.append(f"필수 법령 {len(missing_statutes)}건 미검색/미인용: " + "; ".join(missing_statutes))

        if recall >= 0.8:
            status = "PASS"
        elif recall >= 0.4:
            status = "PARTIAL"
        else:
            status = "FAIL"

        return MetricScore(
            metric_name=self.metric_name,
            score=round(recall, 4),
            raw_value=len(matched_statutes),
            max_value=len(expected_statutes),
            status=status,
            failure_reasons=failure_reasons,
            details={
                "expected_count": len(expected_statutes),
                "matched_count": len(matched_statutes),
                "matched_statutes": matched_statutes,
                "missing_statutes": missing_statutes,
            },
        )

    def _is_statute_referenced(self, statute: ExpectedStatute, corpus: str) -> bool:
        """단일 법령 조문이 텍스트에 실질적으로 인용 또는 검색되었는지 판별한다."""
        # 1. 법령명 확인 (예: 주택임대차보호법 or 주임법)
        law_name_found = False
        if statute.law_name in corpus:
            law_name_found = True
        elif "주택임대차" in statute.law_name and ("주택임대차" in corpus or "주임법" in corpus):
            law_name_found = True
        elif "민법" in statute.law_name and "민법" in corpus:
            law_name_found = True

        if not law_name_found:
            return False

        # 2. 조문 번호 확인 (예: 제3조, 제6조의2 등)
        article_match = re.search(r"제\s*(\d+)(조의\s*\d+|조)?", statute.article)
        if article_match:
            main_art = article_match.group(1)
            sub_art = article_match.group(2)
            if sub_art:
                clean_sub = sub_art.replace(" ", "")
                pattern = rf"제\s*{main_art}\s*{re.escape(clean_sub)}"
                return bool(re.search(pattern, corpus))
            else:
                pattern = rf"제\s*{main_art}\s*조"
                return bool(re.search(pattern, corpus))

        return True

