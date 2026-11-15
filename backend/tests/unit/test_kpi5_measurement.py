"""신규 KPI 평가의 분모·중복·빈 데이터 처리에 대한 회귀 테스트.

제품 응답의 품질을 조작하지 않고 집계기가 누락·중복을 합격으로 바꾸지 않는지 검증한다.
"""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.evaluation import score_kpi5_20261115 as scorer
from scripts.evaluation.score_kpi5_20261115 import compute_scores, validate_judgment
from scripts.evaluation.reevaluate_sc021_20261115 import planner_signature


def test_empty_denominators_remain_unmeasured():
    """분모가 없는 지표는 100%가 아닌 미측정이어야 한다."""
    scores = compute_scores({'fact_reviews': [], 'gold_fact_reviews': [], 'issue_reviews': [], 'citation_reviews': []})
    assert all(score['value'] is None for score in scores.values())


def test_duplicates_and_metadata_do_not_inflate_precision():
    """중복·메타정보는 제외하고 잘못된 실질 사실은 분모와 오답으로 유지한다."""
    judgment = {
        'fact_reviews': [
            {'index': 0, 'supported': True, 'duplicate_of': None},
            {'index': 1, 'supported': True, 'duplicate_of': 0},
            {'index': 2, 'supported': False, 'duplicate_of': None},
            {'index': 3, 'supported': True, 'excluded': True},
        ],
        'gold_fact_reviews': [{'covered': True}, {'covered': False}],
        'issue_reviews': [{'planner_detected': False, 'answer_detected': True}],
        'citation_reviews': [{'exists': True, 'content_correct': True, 'relevant': True, 'temporal_valid': True, 'application_valid': True}, {'exists': None, 'content_correct': True, 'relevant': True, 'temporal_valid': True, 'application_valid': True}],
    }
    scores = compute_scores(judgment)
    assert scores['fact_precision'] == {'numerator': 1, 'denominator': 2, 'value': .5}
    assert scores['fact_recall']['value'] == .5
    assert scores['issue_recall']['value'] == 0
    assert scores['answer_issue_recall']['value'] == 1
    assert scores['legal_accuracy']['value'] == .5


def test_unverifiable_planner_quote_cannot_pass():
    """답변으로부터 지어낸 Planner 근거는 식별 성공으로 인정하지 않는다."""
    case = {'gold_facts': [{'id': 'F1'}], 'gold_issues': [{'id': 'I1'}]}
    run = {'facts': [{'statement': '사실'}], 'planner_calls': [], 'consultation': {'answer': '답변 쟁점'}}
    judgment = {'fact_reviews': [{'index': 0, 'duplicate_of': None}], 'gold_fact_reviews': [{'gold_id': 'F1', 'covered': True, 'indices': [0]}], 'issue_reviews': [{'gold_id': 'I1', 'planner_detected': True, 'planner_quote': '답변 쟁점', 'answer_detected': True, 'answer_quote': '답변 쟁점', 'reason': ''}], 'citation_reviews': []}
    validate_judgment(case, run, judgment)
    assert judgment['issue_reviews'][0]['planner_detected'] is False
    assert judgment['issue_reviews'][0]['answer_detected'] is True


def test_langfuse_generations_deduplicate_and_preserve_measured_zero(tmp_path, monkeypatch):
    """동일 Generation의 중복 합산을 막고 실제 0과 누락 값을 구분한다.

    Args:
        tmp_path: pytest 임시 디렉터리.
        monkeypatch: pytest 환경 교체 도구.
    """
    monkeypatch.setattr(scorer, 'OUT', tmp_path)
    generation = {'id': 'g1', 'type': 'GENERATION', 'promptTokens': 0, 'completionTokens': 0, 'calculatedTotalCost': 0}
    for tid in ('t1', 't2'):
        (tmp_path / f'trace_{tid}.json').write_text(json.dumps({'observations': [generation]}), encoding='utf-8')
    metrics = scorer.trace_metrics({'trace_ids': ['t1', 't2'], 'usage': [{}]})
    assert metrics['llm_calls'] == 1
    assert metrics['total_tokens'] == 0
    assert metrics['cost_usd'] == 0


def test_reassessment_does_not_invent_local_usage(tmp_path, monkeypatch):
    """다른 프로세스의 로컬 추적기를 조회하지 못한 경우 0회로 오인하지 않는다.

    Args:
        tmp_path: pytest 임시 디렉터리.
        monkeypatch: pytest 환경 교체 도구.
    """
    monkeypatch.setattr(scorer, 'OUT', tmp_path)
    (tmp_path / 'trace_t1.json').write_text(json.dumps({'observations': [{'id': 'g1', 'type': 'GENERATION', 'promptTokens': 4, 'completionTokens': 2, 'calculatedTotalCost': .01}]}), encoding='utf-8')
    metrics = scorer.trace_metrics({'trace_ids': ['t1']})
    assert metrics['llm_calls'] == 1
    assert metrics['local_calls'] is None
    assert metrics['local_input_tokens'] is None


def test_planner_reuse_requires_identical_semantic_tasks():
    """사실 ID 차이는 허용하되 법률 질문이 달라지면 과거 판정을 재사용하지 않는다."""
    first = [[{'issue_id': 'I1', 'issue_title': '해지', 'legal_questions': ['기산점은?'], 'required_statutes': ['법 제1조'], 'relevant_fact_ids': ['a']}]]
    same = [[dict(first[0][0], relevant_fact_ids=['b'])]]
    changed = [[dict(first[0][0], legal_questions=['다른 쟁점은?'])]]
    assert planner_signature(first) == planner_signature(same)
    assert planner_signature(first) != planner_signature(changed)
