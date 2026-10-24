# -*- coding: utf-8 -*-
"""
모듈명: fact_scorer.py

[역할]
AI Legal Helper Evaluation Harness의 사실관계 반영도(Fact Recall & Precision) 스코어러.
골드 시나리오의 기대 사실(ExpectedFact)들이 실제 상담 답변 및 구조화된 사실(Facts)에 얼마나 충실하게
반영되었는지(Recall), 왜곡이나 날조(모순 사실) 없이 정확하게 진술되었는지(Precision)를 독립적으로 채점한다.

[주요 기능]
1. `FactRecallScorer`:
   - 필수 요건사실(is_essential=True)의 반영율 측정
   - 골드 기대 사실 대비 실제 답변/추출 사실의 재현율(Recall) 계산
2. `FactPrecisionScorer`:
   - 답변 내 주장된 사실의 정확성 및 비모순성 검증
   - 보증금액 왜곡(예: 3억 원 대신 5억 원/1억 원 등), 허위 계약일자, 퇴거 오인, 날조된 당사자 탐지
   - 판단 유보(WITHHELD)로 사실 주장이 없는 경우 N/A 처리
"""

import re
from typing import Dict, Any, List, Set, Tuple
from evaluation_harness.scorers.base import BaseScorer, MetricScore
from evaluation_harness.gold.gold_schema import GoldCaseScenario, ExpectedFact


class FactRecallScorer(BaseScorer):
    """골드 기대 사실관계 재현율(Recall) 스코어러."""

    def __init__(self):
        super().__init__(metric_name="fact_recall")

    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """골드 기대 사실과 시스템 답변/추출 사실을 비교하여 재현율을 채점한다.

        Args:
            scenario: 골드 시나리오 객체
            actual_output: 시스템 결과 (answer, facts 등 포함)

        Returns:
            MetricScore: 사실 재현율 점수 및 누락 내역
        """
        expected_facts: List[ExpectedFact] = scenario.expected_facts
        if not expected_facts:
            return MetricScore(
                metric_name=self.metric_name,
                score=None,
                status="N/A",
                failure_reasons=[],
                details={"message": "검증할 기대 사실 없음"},
            )

        answer_text: str = actual_output.get("answer") or actual_output.get("raw_answer") or ""
        raw_facts = actual_output.get("facts", []) or []
        facts_text = " ".join([f.get("statement", "") if isinstance(f, dict) else str(f) for f in raw_facts])
        combined_text = f"{answer_text} {facts_text}"

        matched_facts: List[str] = []
        missing_essential_facts: List[str] = []

        for ef in expected_facts:
            is_matched = self._check_fact_match(ef, combined_text)
            if is_matched:
                matched_facts.append(ef.fact_id)
            else:
                if ef.is_essential:
                    missing_essential_facts.append(f"[{ef.fact_id}] {ef.statement}")

        total_essential = sum(1 for ef in expected_facts if ef.is_essential)
        matched_essential = total_essential - len(missing_essential_facts)

        if total_essential > 0:
            recall = matched_essential / float(total_essential)
        else:
            recall = len(matched_facts) / float(len(expected_facts))

        failure_reasons: List[str] = []
        if missing_essential_facts:
            failure_reasons.append(
                f"핵심 사실 {len(missing_essential_facts)}건 미반영: " + "; ".join(missing_essential_facts[:3])
            )

        if recall >= 0.85 and not missing_essential_facts:
            status = "PASS"
        elif recall >= 0.5:
            status = "PARTIAL"
        else:
            status = "FAIL"

        return MetricScore(
            metric_name=self.metric_name,
            score=round(recall, 4),
            raw_value=matched_essential,
            max_value=total_essential if total_essential > 0 else len(expected_facts),
            status=status,
            failure_reasons=failure_reasons,
            details={
                "total_expected": len(expected_facts),
                "matched_count": len(matched_facts),
                "matched_fact_ids": matched_facts,
                "missing_essential_count": len(missing_essential_facts),
                "missing_essential_statements": missing_essential_facts,
            },
        )

    def _check_fact_match(self, fact: ExpectedFact, text: str) -> bool:
        """단일 사실이 텍스트에 유의미하게 포함되어 있는지 키워드 집합으로 검사한다."""
        cat = fact.fact_category

        if cat == "PAYMENT" or "300,000,000" in fact.statement or "3억" in fact.statement:
            return ("3억" in text or "300,000,000" in text or "삼억" in text) and (
                "보증금" in text or "전세금" in text or "반환" in text or "지급" in text
            )

        if cat == "RESIDENCE" or "전입" in fact.statement or "확정일자" in fact.statement:
            return ("전입" in text or "주민등록" in text or "입주" in text or "거주" in text) and (
                "확정일자" in text or "대항" in text or "점유" in text
            )

        if cat == "NOTICE" or "2026년 4월 1일" in fact.statement or "해지통고" in fact.statement:
            return ("2026" in text or "4월" in text or "문자" in text) and ("해지" in text or "통고" in text or "퇴거" in text)

        if cat == "ATTACHMENT" or "가압류" in fact.statement:
            has_attachment = "가압류" in text
            has_creditor = "은행" in text or "HUG" in text or "도시보증" in text or "7,200" in text or "1억" in text or "120" in text
            return has_attachment and has_creditor

        if cat == "NEGOTIATION" or "분할" in fact.statement:
            return "분할" in text or "1년" in text or "새 세입자" in text or "신규 임차인" in text

        key_phrases = re.findall(r"[\w가-힣]{3,}", fact.statement)
        if not key_phrases:
            return True
        matched_tokens = sum(1 for p in key_phrases if p in text)
        return (matched_tokens / float(len(key_phrases))) >= 0.4


class FactPrecisionScorer(BaseScorer):
    """답변 내 사실 주장의 정밀도(Precision) 및 왜곡 방지 스코어러."""

    # SC-001 사건의 사실관계 왜곡 패턴들 (잘못된 보증금, 잘못된 계약일자, 오인된 퇴거 등)
    CONTRADICTORY_PATTERNS = [
        # 보증금 왜곡: 3억 원이 아닌 5억, 2억, 1억 등을 보증금으로 오인
        (
            re.compile(r"보증금\s*(5억|2억|1억|5,000|50,000,000|200,000,000|100,000,000)"),
            "보증금 액수 왜곡 (실제: 300,000,000원)",
        ),
        # 계약 시점 왜곡: 2022년이 아닌 2023년, 2025년에 계약 체결되었다고 주장
        (
            re.compile(r"202[3-5]년\s*(2월|3월)?\s*(체결|계약한)"),
            "임대차 계약 체결 연도 왜곡 (실제: 2022년)",
        ),
        # 선순위 근저당권 날조 (SC-001은 근저당권 없음)
        (
            re.compile(r"(선순위\s*근저당|근저당권자|근저당이\s*설정)"),
            "부존재 선순위 근저당권 설정 사실 날조 (SC-001은 가압류만 2건 존재)",
        ),
        # 이미 퇴거했다고 단정 (임차인은 현재 503호 거주 및 열쇠 소지 중)
        (
            re.compile(r"(이미\s*퇴거하셨|열쇠를\s*반환하였|집을\s*비워준\s*상태)"),
            "임차인 점유 상태 왜곡 (실제: 미퇴거 및 점유 유지 중)",
        ),
    ]

    def __init__(self):
        super().__init__(metric_name="fact_precision")

    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """답변 내 언급된 사실 중 왜곡/날조된 사실이 없는지 검사하여 정밀도를 채점한다."""
        answer_text: str = actual_output.get("answer") or actual_output.get("raw_answer") or ""
        disposition = actual_output.get("disposition", "")

        # 답변이 완전히 유보되었거나 사실 진술이 전혀 없는 경우
        if disposition == "WITHHELD" and not any(k in answer_text for k in ("보증금", "임대차", "계약", "가압류")):
            return MetricScore(
                metric_name=self.metric_name,
                score=None,
                status="N/A",
                failure_reasons=[],
                details={"message": "답변 내 사실 주장 부재 (판단 유보 상태로 정밀도 검증 비대상)"},
            )

        contradictions: List[str] = []
        for pat, desc in self.CONTRADICTORY_PATTERNS:
            if pat.search(answer_text):
                contradictions.append(desc)

        # 정밀도 계산: 기본 1.0에서 사실 왜곡 건당 0.25 감점
        precision = max(0.0, 1.0 - (0.25 * len(contradictions)))

        failure_reasons = []
        if contradictions:
            failure_reasons.append(f"사실관계 왜곡 {len(contradictions)}건 검출: " + "; ".join(contradictions))

        if precision >= 0.85 and not contradictions:
            status = "PASS"
        elif precision >= 0.5:
            status = "PARTIAL"
        else:
            status = "FAIL"

        return MetricScore(
            metric_name=self.metric_name,
            score=round(precision, 4),
            raw_value=len(contradictions),
            max_value=len(self.CONTRADICTORY_PATTERNS),
            status=status,
            failure_reasons=failure_reasons,
            details={
                "contradictions_count": len(contradictions),
                "contradictions": contradictions,
            },
        )


# 하위 호환성을 위한 기본 별칭
FactScorer = FactRecallScorer
