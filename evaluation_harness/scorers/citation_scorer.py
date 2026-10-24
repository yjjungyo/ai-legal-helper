# -*- coding: utf-8 -*-
"""
모듈명: citation_scorer.py

[역할]
AI Legal Helper Evaluation Harness의 증거 인용 커버리지 및 유효성(Citation Coverage & Validity) 스코어러.
골드 시나리오의 필수 증거(required_evidence_citations)가 누락 없이 인용되었는지(Coverage),
그리고 인용된 증거 라벨이 실제 존재하는 유효한 증거(E01~E18)이며 가공의 증거번호를 날조하지 않았는지(Validity)를
독립적으로 분리하여 채점한다.

[주요 기능]
1. `CitationCoverageScorer`:
   - 필수 기대 인용 증거 대비 실제 인용된 증거 비율(Coverage) 산출
   - 필수 증거가 없는 시나리오의 경우 N/A 처리
2. `CitationValidityScorer`:
   - 인용된 증거 라벨의 유효성(E01~E18 여부) 검증
   - 허위 증거 라벨("증거 99호증", "증거 A", "E99" 등) 적발 및 엄격한 감점
   - 증거 인용이 전혀 없는 경우 N/A 처리
"""

import re
from typing import Dict, Any, List, Set
from evaluation_harness.scorers.base import BaseScorer, MetricScore
from evaluation_harness.gold.gold_schema import GoldCaseScenario


class CitationCoverageScorer(BaseScorer):
    """필수 증거 인용 충실도(Coverage) 스코어러."""

    VALID_LABEL_REGEX = re.compile(r"\b(E0[1-9]|E1[0-8])\b")

    def __init__(self):
        super().__init__(metric_name="citation_coverage")

    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """골드 필수 인용 증거가 실제 답변/출처에 얼마나 포함되었는지 채점한다."""
        required_citations: List[str] = scenario.required_evidence_citations
        if not required_citations:
            return MetricScore(
                metric_name=self.metric_name,
                score=None,
                status="N/A",
                failure_reasons=[],
                details={"message": "필수 인용 증거 없음 (커버리지 검증 비대상)"},
            )

        answer_text: str = actual_output.get("answer") or actual_output.get("raw_answer") or ""
        sources = actual_output.get("sources", []) or []

        extracted_labels: Set[str] = set(self.VALID_LABEL_REGEX.findall(answer_text))
        for s in sources:
            label = s.get("label") or s.get("evidence_label") or s.get("title", "")
            found = self.VALID_LABEL_REGEX.findall(str(label))
            extracted_labels.update(found)

        matched_required = [c for c in required_citations if c in extracted_labels or any(c in str(s) for s in sources)]
        missing_required = [c for c in required_citations if c not in matched_required]
        coverage = len(matched_required) / float(len(required_citations))

        failure_reasons: List[str] = []
        if missing_required:
            failure_reasons.append(f"필수 증거 미인용 ({len(missing_required)}건): " + ", ".join(missing_required))

        if coverage >= 0.8 and not missing_required:
            status = "PASS"
        elif coverage >= 0.4:
            status = "PARTIAL"
        else:
            status = "FAIL"

        return MetricScore(
            metric_name=self.metric_name,
            score=round(coverage, 4),
            raw_value=len(matched_required),
            max_value=len(required_citations),
            status=status,
            failure_reasons=failure_reasons,
            details={
                "required_citations": required_citations,
                "matched_citations": matched_required,
                "missing_required": missing_required,
            },
        )


class CitationValidityScorer(BaseScorer):
    """증거 인용 진실성 및 날조 방지(Validity) 스코어러."""

    VALID_LABEL_REGEX = re.compile(r"\b(E0[1-9]|E1[0-8])\b")
    # 날조 의심 패턴 ("증거 99", "증거 100", "증거 A", "증거 1호증", "E99", "E50" 등)
    # 단, '증거 E01' 등 유효한 E01~E18 라벨 선행 언급은 정상 인용으로 제외
    FABRICATED_LABEL_REGEX = re.compile(
        r"(?:증거\s*(?![eE]0[1-9]|[eE]1[0-8])(?:[0-9]{2,}|[A-Za-z]+|[1-9]호증)|E(?!0[1-9]|1[0-8])[0-9]{2,})"
    )

    def __init__(self):
        super().__init__(metric_name="citation_validity")

    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """인용된 증거 중 유효하지 않거나 날조된 증거 라벨이 있는지 검증한다."""
        answer_text: str = actual_output.get("answer") or actual_output.get("raw_answer") or ""
        sources = actual_output.get("sources", []) or []

        # 1. 텍스트 및 출처에서 인용된 모든 정규 증거 라벨 추출
        extracted_labels: Set[str] = set(self.VALID_LABEL_REGEX.findall(answer_text))
        for s in sources:
            label = s.get("label") or s.get("evidence_label") or s.get("title", "")
            found = self.VALID_LABEL_REGEX.findall(str(label))
            extracted_labels.update(found)

        # 2. 날조된 가공 증거번호 검출
        fabricated_matches = [m.group(0) for m in self.FABRICATED_LABEL_REGEX.finditer(answer_text)]
        suspicious_fabricated = [m for m in fabricated_matches if not any(f"E{m}" in l for l in extracted_labels)]

        # 인용 자체가 없고 날조도 없는 경우
        if not extracted_labels and not suspicious_fabricated:
            return MetricScore(
                metric_name=self.metric_name,
                score=None,
                status="N/A",
                failure_reasons=[],
                details={"message": "인용된 증거 없음 (유효성 검증 대상 없음)"},
            )

        failure_reasons: List[str] = []
        if suspicious_fabricated:
            # 날조된 증거 라벨 검출 시
            total_citations = len(extracted_labels) + len(suspicious_fabricated)
            validity = len(extracted_labels) / float(total_citations) if total_citations > 0 else 0.0
            validity = max(0.0, validity - (0.3 * len(suspicious_fabricated)))
            failure_reasons.append(f"가공된 의심 증거번호 인용 검출: {suspicious_fabricated}")
            status = "FAIL" if validity < 0.5 else "PARTIAL"
        else:
            validity = 1.0
            status = "PASS"

        return MetricScore(
            metric_name=self.metric_name,
            score=round(validity, 4),
            raw_value=len(extracted_labels),
            max_value=len(extracted_labels) + len(suspicious_fabricated),
            status=status,
            failure_reasons=failure_reasons,
            details={
                "extracted_valid_labels": list(extracted_labels),
                "suspicious_fabricated": suspicious_fabricated,
            },
        )


# 하위 호환성을 위한 기본 별칭
CitationScorer = CitationValidityScorer
