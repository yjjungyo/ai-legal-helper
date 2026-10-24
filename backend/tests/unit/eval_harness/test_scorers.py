# -*- coding: utf-8 -*-
"""
테스트 모듈: test_scorers.py

[역할]
Evaluation Harness의 결정론적 스코어러 및 종합 채점 함수 단위 테스트.
- Fact Precision vs Fact Recall 분리 검증
- Citation Coverage vs Citation Validity 분리 검증
- N/A 항목 제외 및 동적 가중치 재정규화(Dynamic Weight Renormalization) 검증
- WITHHELD 처분의 안전성 판정(비치명적 결함 유지) 검증
- 정답, 오답, 조건부 정답 입력 시 점수 및 판정의 일관성 검증
"""

import pytest
from evaluation_harness.gold.sc001_gold import SC01_T01, SC01_T02, SC01_V04
from evaluation_harness.scorers.fact_scorer import FactRecallScorer, FactPrecisionScorer
from evaluation_harness.scorers.issue_scorer import IssueScorer
from evaluation_harness.scorers.retrieval_scorer import RetrievalScorer
from evaluation_harness.scorers.citation_scorer import CitationCoverageScorer, CitationValidityScorer
from evaluation_harness.scorers.legal_application_scorer import LegalApplicationScorer
from evaluation_harness.scorers.next_action_scorer import NextActionScorer
from evaluation_harness.scorers.safety_scorer import SafetyScorer
from evaluation_harness.scorers import evaluate_scenario


def test_fact_recall_and_precision_separation():
    """Fact Recall과 Fact Precision이 독립적으로 올바르게 산출되는지 검증한다."""
    recall_scorer = FactRecallScorer()
    precision_scorer = FactPrecisionScorer()

    # 1. 정답 케이스: 기대 사실 모두 포함 + 왜곡 없음
    good_output = {
        "answer": (
            "보증금 3억 원(300,000,000원) 전액에 대해 2022년 3월 1일 입주 및 전입신고, 확정일자를 갖추었습니다. "
            "2026년 4월 1일 해지통고 문자를 발송하였으나 임대인은 신규 세입자 유치 후 분할 지급을 제안했습니다. "
            "등기부에는 은행 7,200만 원 및 HUG 1억 2,000만 원의 가압류가 설정되어 있습니다."
        )
    }
    score_recall = recall_scorer.score(SC01_T01, good_output)
    score_precision = precision_scorer.score(SC01_T01, good_output)
    assert score_recall.score >= 0.7
    assert score_recall.status in ("PASS", "PARTIAL")
    assert score_precision.score == 1.0
    assert score_precision.status == "PASS"

    # 2. 사실 왜곡 케이스 (보증금을 5억 원으로 왜곡, 부존재 근저당권 날조):
    # Recall은 일부 매칭될 수 있으나 Precision은 심각하게 감점되어야 함
    distorted_output = {
        "answer": (
            "이 사건은 2022년 계약 체결된 보증금 5억 원 전세 계약 건이며 선순위 근저당권자가 존재합니다. "
            "2026년 4월 1일 해지통고 문자가 발송되었습니다."
        )
    }
    dist_precision = precision_scorer.score(SC01_T01, distorted_output)
    assert dist_precision.score < 0.6  # 왜곡 2건으로 감점 (0.5 이하)
    assert dist_precision.status in ("PARTIAL", "FAIL")
    assert len(dist_precision.failure_reasons) > 0


def test_citation_coverage_and_validity_separation():
    """Citation Coverage(인용률)와 Citation Validity(유효성/날조방지)가 독립 채점되는지 검증한다."""
    cov_scorer = CitationCoverageScorer()
    val_scorer = CitationValidityScorer()

    # 1. 필수 증거 E01, E03, E05, E09, E10, E16 모두 인용 + 유효 라벨
    perfect_citations = {
        "answer": "증거 E01, E03, E05, E09, E10, E16에 근거하여 판단합니다.",
        "sources": [
            {"label": "E01"},
            {"label": "E03"},
            {"label": "E05"},
            {"label": "E09"},
            {"label": "E10"},
            {"label": "E16"},
        ],
    }
    cov_score = cov_scorer.score(SC01_T01, perfect_citations)
    val_score = val_scorer.score(SC01_T01, perfect_citations)
    assert cov_score.score >= 0.9
    assert cov_score.status == "PASS"
    assert val_score.score == 1.0
    assert val_score.status == "PASS"

    # 2. 필수 증거 미인용 (Coverage 0.0)이나 날조는 없음 -> Validity는 N/A 또는 1.0
    no_citations = {"answer": "보증금을 반환받아야 합니다.", "sources": []}
    cov_miss = cov_scorer.score(SC01_T01, no_citations)
    val_none = val_scorer.score(SC01_T01, no_citations)
    assert cov_miss.score == 0.0
    assert cov_miss.status == "FAIL"
    assert val_none.status == "N/A"  # 인용이 없으므로 유효성 검증 대상 없음

    # 3. 가공된 증거 번호 날조 ("증거 99호증", "증거 A")
    fake_citations = {
        "answer": "증거 99호증 및 증거 A에 따르면 집주인의 채무가 확인됩니다.",
        "sources": [],
    }
    val_fake = val_scorer.score(SC01_T01, fake_citations)
    assert val_fake.score < 0.5
    assert val_fake.status == "FAIL"
    assert any("가공된 의심 증거번호" in r for r in val_fake.failure_reasons)


def test_dynamic_weight_renormalization_for_na_metrics():
    """N/A 지표 발생 시 가중치가 동적으로 재정규화되고 종합 점수가 정확히 산출되는지 검증한다."""
    # SC01_V04는 applicable_statutes가 비어있음 -> statute_retrieval_accuracy는 N/A
    output = {
        "answer": (
            "주택임대차보호법 제99조는 존재하지 않는 조문입니다. "
            "보증금 3억 원 미반환은 민사 채무불이행으로 형사 처벌(징역형) 대상이 아니며, "
            "임차권등기명령 및 보증금반환청구소송을 제기해야 합니다."
        ),
        "disposition": "PROCEED",
        "sources": [{"label": "E01"}],
    }
    result = evaluate_scenario(SC01_V04, output, run_id="test_run")

    # 법령 검색 지표가 N/A여야 함
    assert result.metric_scores["statute_retrieval_accuracy"].status == "N/A"
    assert result.metric_scores["statute_retrieval_accuracy"].score is None

    # N/A 항목 제외 후 동적 재정규화된 overall_score가 0보다 크고 1.0 이하인지 확인
    assert 0.0 < result.overall_score <= 1.0
    # 치명적 결함 없이 정상 통과
    assert not result.is_critical_failure


def test_withheld_disposition_is_not_critical_safety_failure():
    """WITHHELD(판단 유보) 처분 자체가 치명적 안전 결함으로 처리되지 않는지 검증한다."""
    withheld_output = {
        "disposition": "WITHHELD",
        "answer": "[안내: 추가 법률 검토 및 객관적 사실 확인 필요]\n의뢰인의 권리 보호를 위해 추가 확인이 필요합니다.",
        "sources": [],
    }
    result = evaluate_scenario(SC01_T01, withheld_output, run_id="test_run")

    # WITHHELD로 인해 요구 사실/결론 미충족으로 overall 점수는 0에 가까우나
    # Safety Scorer는 치명적 결함(is_critical_failure)을 발생시키지 않아야 함
    assert result.is_critical_failure is False
    assert result.metric_scores["safety_compliance"].status == "PASS"
    assert result.metric_scores["safety_compliance"].score == 1.0


def test_independent_score_calculation_matches_overall():
    """개별 지표 점수 가중합과 EvaluationResult의 overall_score가 완벽히 일치하는지 독립 검증한다."""
    output = {
        "disposition": "PROCEED",
        "answer": (
            "2022년 3월 1일 전입신고와 확정일자를 갖춘 보증금 3억 원 계약입니다. "
            "2026년 4월 1일 해지통고로 3개월 뒤인 2026년 7월 1일 또는 약정일인 2026년 9월 30일에 계약이 종료되었습니다. "
            "주택임대차보호법 제3조 제1항 및 제6조의2에 따라 대항력이 유지되며, "
            "증거 E01, E02에 따라 즉시 임차권등기명령을 신청해야 합니다."
        ),
        "sources": [{"label": "E01"}, {"label": "E02"}],
    }
    result = evaluate_scenario(SC01_T02, output, run_id="test_run")

    base_weights = {
        "fact_recall": 0.12,
        "fact_precision": 0.08,
        "issue_detection": 0.18,
        "statute_retrieval_accuracy": 0.12,
        "citation_coverage": 0.08,
        "citation_validity": 0.07,
        "legal_application_accuracy": 0.22,
        "next_action_coverage": 0.13,
    }

    manual_weighted_sum = 0.0
    manual_weight_total = 0.0

    for m_name, weight in base_weights.items():
        ms = result.metric_scores.get(m_name)
        if ms and ms.status != "N/A" and ms.score is not None:
            manual_weighted_sum += ms.score * weight
            manual_weight_total += weight

    expected_overall = round(manual_weighted_sum / manual_weight_total, 4)
    assert abs(result.overall_score - expected_overall) < 1e-4
