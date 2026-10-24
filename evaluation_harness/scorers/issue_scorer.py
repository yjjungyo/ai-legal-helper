# -*- coding: utf-8 -*-
"""
모듈명: issue_scorer.py

[역할]
AI Legal Helper Evaluation Harness의 법률 쟁점 식별 정확도(Issue Precision & Recall) 스코어러.
사건에 내포된 핵심 법률 쟁점(계약 종료, 대항력 우열, 경매 인수, 임차권등기명령 등)이 누락 없이 포섭되었는지 검증한다.

[주요 기능]
- 골드 기대 쟁점(expected_issues) 대비 실제 추출/답변된 쟁점의 재현율(Recall) 및 정확도 측정
- 쟁점별 핵심 법률 키워드 매칭
- 누락 쟁점에 대한 구체적 실패 사유 반환
"""

from typing import Dict, Any, List
from evaluation_harness.scorers.base import BaseScorer, MetricScore
from evaluation_harness.gold.gold_schema import GoldCaseScenario, ExpectedIssue


class IssueScorer(BaseScorer):
    """법률 쟁점 식별 스코어러."""

    def __init__(self):
        super().__init__(metric_name="issue_detection")

    def score(self, scenario: GoldCaseScenario, actual_output: Dict[str, Any]) -> MetricScore:
        """골드 기대 쟁점과 실제 시스템 분석 쟁점을 비교 채점한다.

        Args:
            scenario: 골드 시나리오
            actual_output: 시스템 결과 딕셔너리

        Returns:
            MetricScore: 쟁점 탐지 점수 및 결과
        """
        expected_issues: List[ExpectedIssue] = scenario.expected_issues
        if not expected_issues:
            return MetricScore(
                metric_name=self.metric_name,
                score=1.0,
                status="PASS",
                failure_reasons=[],
                details={"message": "검증할 기대 쟁점 없음"},
            )

        answer_text: str = actual_output.get("answer") or actual_output.get("raw_answer") or ""
        issues_list = actual_output.get("issues", []) or []
        issue_texts = " ".join([i.get("title", "") + " " + i.get("description", "") if isinstance(i, dict) else str(i) for i in issues_list])
        combined_text = f"{answer_text} {issue_texts}"

        matched_issues: List[str] = []
        missing_issues: List[str] = []

        for ei in expected_issues:
            if self._check_issue_present(ei, combined_text):
                matched_issues.append(ei.issue_id)
            else:
                missing_issues.append(f"[{ei.issue_id}] {ei.issue_title}")

        recall = len(matched_issues) / float(len(expected_issues))

        failure_reasons: List[str] = []
        if missing_issues:
            failure_reasons.append(f"핵심 법률 쟁점 {len(missing_issues)}건 누락: " + "; ".join(missing_issues))

        if recall >= 0.9:
            status = "PASS"
        elif recall >= 0.5:
            status = "PARTIAL"
        else:
            status = "FAIL"

        return MetricScore(
            metric_name=self.metric_name,
            score=round(recall, 4),
            raw_value=len(matched_issues),
            max_value=len(expected_issues),
            status=status,
            failure_reasons=failure_reasons,
            details={
                "expected_count": len(expected_issues),
                "matched_count": len(matched_issues),
                "matched_issue_ids": matched_issues,
                "missing_issues": missing_issues,
            },
        )

    def _check_issue_present(self, issue: ExpectedIssue, text: str) -> bool:
        """단일 쟁점의 핵심 키워드가 텍스트에 포함되어 있는지 검사."""
        issue_id = issue.issue_id.upper()
        title = issue.issue_title

        if "TERMINATION" in issue_id or "종료" in title:
            return ("종료" in text or "해지" in text) and ("효력" in text or "시점" in text or "3개월" in text or "묵시적" in text or "만료" in text)

        if "PRIORITY" in issue_id or "우선" in title or "가압류" in title:
            return ("대항력" in text or "우선변제" in text or "선순위" in text) and ("가압류" in text or "순위" in text or "배당" in text)

        if "AUCTION" in issue_id or "경매" in title:
            return "경매" in text and ("배당" in text or "인수" in text or "낙찰" in text or "대항력" in text)

        if "PRESERVATION" in issue_id or "등기명령" in title or "대항력 상실" in title:
            return "임차권등기" in text or ("점유" in text and "유지" in text) or "대항력 유지" in text

        if "INSTALLMENT" in issue_id or "분할" in title:
            return "분할" in text and ("거절" in text or "전액" in text or "일시" in text or "위험" in text)

        if "PROOF_OF_CONTENTS" in issue_id or "내용증명" in title:
            return "내용증명" in text and ("최고" in text or "도달" in text or "발송" in text or "해지" in text)

        if "EVIDENCE_GAP" in issue_id or "미확인" in title or "보완" in title:
            return "등기부" in text or "발급" in text or "확인" in text or "보완" in text or "서류" in text

        if "IMMEDIATE" in issue_id or "최우선" in title:
            return "점유" in text or "내용증명" in text or "임차권등기" in text

        # 일반 제목 내 단어 매칭
        words = [w for w in title.split() if len(w) >= 2]
        if not words:
            return True
        matched = sum(1 for w in words if w in text)
        return (matched / float(len(words))) >= 0.5
