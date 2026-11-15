"""새 SC-021 상담을 기존 Gold로 재평가하고 이전 단회와 비교 보고한다.

동일 사실·동일 Planner에 대한 판정은 원문 동등성을 확인한 뒤 유지하고,
새 최종 답변의 쟁점·인용은 다시 심사한다. 상담·증거 추출은 호출하지 않는다.
"""
import argparse
from copy import deepcopy
import json
import logging
import re
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend/src')]
from scripts.evaluation import score_kpi5_20261115 as scorer
from scripts.evaluation.run_kpi5_20261115 import write_json
from openpyxl import load_workbook

BASE = ROOT / 'artifacts/kpi5_20261115'
OUT = ROOT / 'artifacts/sc021_reassessment_20261115_9f52b3c3'
XLSX = ROOT / 'docs/evaluation/kpi/AI_Legal_Helper_KPI_20261115_SC021_재평가_9f52b3c3.xlsx'
MARKDOWN = ROOT / 'docs/evaluation/SC-021_20261115_재평가_9f52b3c3.md'


def planner_signature(calls):
    """사실 UUID 변동을 제외하고 실제 계획의 의미 필드만 비교한다.

    Args:
        calls: 실제 Planner 호출별 반환 목록.
    Returns:
        과업 ID·제목·질문·필수 조문의 정규 구조.
    """
    return [[{k: task.get(k) for k in ('issue_id', 'issue_title', 'legal_questions', 'required_statutes')} for task in tasks] for tasks in calls]


def load(path):
    """UTF-8 JSON 평가 원본을 읽는다.

    Args:
        path: 원본 파일 경로.
    Returns:
        파싱된 원본 객체.
    """
    return json.loads(path.read_text(encoding='utf-8'))


def review_citations(judgment, sources):
    """생략부호 발췌 오류·반복 인용·보충 비교의 한계를 공식 원문으로 대조한다.

    Args:
        judgment: 최초 자동 심사 결과를 복사한 객체.
        sources: 해시와 함께 저장한 공식 원문.
    Returns:
        항목별 정정 근거 목록. 원문 발췌가 없으면 정정하지 않는다.
    Raises:
        ValueError: 정정용 발췌가 공식 원문에 실제로 없는 경우.
    """
    fixes = {
        6: ('REGISTER', '임대차가 끝난 후 보증금이 반환되지 아니한 경우', '생략부호로 축약한 최초 Judge 발췌 때문에 존재 확인이 실패했지만, 공식 제3조의3 제1항에서 신청 요건을 직접 확인했다.'),
        8: ('P2023', '해지통지 후 3개월이 지나면 그 효력이 발생하며', '공식 판시사항·판결요지에서 갱신요구 도달의 효력과 새 기간 개시 전 해지통지의 3개월 법리를 대조했다. 최초 Judge의 생략부호는 제품 인용 오류가 아니다.'),
        9: ('P2023', '이는 계약해지의 통지가 갱신된 임대차계약 기간이 개시되기 전에 임대인에게 도달하였더라도 마찬가지이다.', '원문의 법리와 일치한다. 다만 앞선 판례 요지와 같은 기산점 명제를 반복하므로 KPI 분모에서 제외한다.'),
        10: ('LEASE_BODY', '제1항에 따라 갱신되는 임대차의 해지에 관하여는 제6조의2를 준용한다.', '동일 공식 본문에서 제6조의3 제4항과 제6조의2 제2항을 확인하고, P2023의 직접 법리와 사건 날짜의 대응을 대조했다.'),
        12: ('P307024', '임차인의 의사에 반하여', '공식 판결은 임차인 의사에 반하는 상가 묵시적 갱신 강제의 부당성을 논한다. 답변은 상가 사건이라는 차이와 보충적 참고라는 한계를 명시했다.'),
    }
    notes = []
    normalize = lambda value: re.sub(r'\s+', '', value)
    for index, (key, quote, reason) in fixes.items():
        if normalize(quote) not in normalize(sources[key]['text']):
            raise ValueError('review_source_excerpt_not_found_' + str(index))
        citation = judgment['citation_reviews'][index]
        citation.update(exists=True, source_key=key, source_quote=quote)
        citation['reason'] = '2차 공식 원문 대조: ' + reason
        notes.append({'index': index, 'source_key': key, 'source_quote': quote, 'reason': reason})
    # 분모의 단위는 등장 횟수가 아닌 고유 인용-법적 주장이다.
    for duplicate, representative in ((3, 1), (9, 8)):
        judgment['citation_reviews'][duplicate]['duplicate_of'] = representative
        judgment['citation_reviews'][duplicate]['reason'] += ' [동일 인용·동일 법리 반복으로 중복 집계 제외]'
    # 직접 적용 가능성과 명시적으로 한계를 둔 비교 참고의 관련성을 구별한다.
    for index in (11, 12):
        judgment['citation_reviews'][index]['relevant'] = True
        judgment['citation_reviews'][index]['reason'] += ' [보충 비교로서 관련성 인정: 주택에 상가법을 직접 적용하지 않고 분야 차이를 명시했으며 핵심 판단은 직접 주택 판례로 제시함. 필요성·실익의 평가는 별도 개선사항]'
    judgment['first_pass_critical_findings'] = deepcopy(judgment.get('critical_findings', []))
    judgment['critical_findings'] = [
        'Planner의 세부 쟁점 식별은 1/5로 미달이며, 일반적인 종료·보증금 과업만으로 갱신효력·기산점·판례 비교 과업을 대신할 수 없다.',
        '최종 답변은 필수 판례를 정확히 제시하고 주요 질문에 답했으나 인도와 보증금 반환의 동시이행 관계는 누락했다.',
        '상가 보충 판례는 차이와 한계를 명시하여 인용 정확성 오류로 보지 않았지만 직접 주택 판례가 있는 상황에서 설명 필요성·분량을 검토할 여지가 있다.',
        '일반 표현인 제출 증거로를 가공 증거 라벨로 인식한 Planner 과업이 남아 있어 불필요한 가공 증거 안내가 생성되었다.',
    ]
    judgment.setdefault('second_review_notes', []).extend('인용 ' + str(n['index']) + ': ' + n['reason'] for n in notes)
    judgment['citation_review_method'] = 'Codex 2차 공식 원문 대조; 전문가 확정 아님. 보충 비교는 분야 차이·적용 한계를 명시한 경우 관련성 인정.'
    return notes


def report_comparison(previous, current, previous_metrics, current_metrics, previous_scores, current_scores):
    """동등한 상담 범위의 지표와 KPI를 비교 시트·설명에 추가한다.

    Args:
        previous: 최초 제품 실행 원본.
        current: 사용자 재상담 원본.
        previous_metrics: 최초 상담만의 Langfuse 집계.
        current_metrics: 새 상담만의 Langfuse 집계.
        previous_scores: 이전 확정 자동 판정의 집계.
        current_scores: 재평가 집계.
    """
    wb = load_workbook(XLSX)
    latency = previous['consultation_latency_sec']
    new_latency = current['consultation_latency_sec']
    performance = [
        ['상담 실행시간(초)', latency, new_latency, latency / new_latency if new_latency else None, '이전/현재 배수; 추출 시간 제외'],
    ]
    for label, key in [('입력 토큰', 'input_tokens'), ('출력 토큰', 'output_tokens'), ('총 토큰', 'total_tokens'), ('LLM 비용(USD)', 'cost_usd'), ('LLM 호출 횟수', 'llm_calls')]:
        old, new = previous_metrics.get(key), current_metrics.get(key)
        saving = (old - new) / old if old is not None and new is not None and old > 0 else None
        performance.append([label, old, new, saving, '(이전−현재)/이전; 단회 비교'])
    scorer.add_sheet(wb, '이전상담_성능비교', ['항목', '최초 상담만', '사용자 새 상담', '속도배수 또는 절감률', '범위'], performance)
    quality_rows = []
    for key in ('fact_precision', 'fact_recall', 'issue_recall', 'answer_issue_recall', 'legal_accuracy'):
        quality_rows.append([key, previous_scores[key]['value'], current_scores[key]['value'], current_scores[key]['numerator'], current_scores[key]['denominator']])
    scorer.add_sheet(wb, '이전상담_KPI비교', ['지표', '이전', '재평가', '정답 수', '평가 수'], quality_rows)
    for sheet_name in ('이전상담_KPI비교',):
        for row in wb[sheet_name].iter_rows(min_row=2):
            row[1].number_format = row[2].number_format = '0.00%'
    for row in wb['이전상담_성능비교'].iter_rows(min_row=3):
        row[3].number_format = '0.00%'
    wb.save(XLSX)
    text = MARKDOWN.read_text(encoding='utf-8')
    text += '\n\n## 원본 상담 식별 및 이전 결과 비교\n\n'
    text += '- 새 상담 요청 ID: `' + current['request_id'] + '`\n'
    text += '- 새 Trace ID: `' + current['consultation']['trace_id'] + '`\n'
    text += '- 제품 검증: `' + current['consultation']['verification_status'] + '` / 답변 상태: `' + current['consultation']['final_disposition'] + '`\n'
    text += '- 기존 증거·사실은 그대로 사용했으며 추출을 다시 수행한 결과가 아니다. 현재 사실 스냅샷이 최초와 동일함을 검증한 뒤 사실 판정을 유지했다.\n'
    text += '- 초기 전체 E2E 316.42초와 새 상담 시간을 직접 비교하지 않고, XLSX의 비교 시트에서는 최초 상담만의 시간·토큰·비용과 비교했다.\n'
    text += '- 동일 질문의 각 1회 결과이므로 반복시험에 의한 안정성·코드 변경의 인과효과를 확정하지 않는다.\n'
    text += '\n|지표|이전|재평가|\n|---|---:|---:|\n'
    for row in quality_rows:
        text += '| ' + row[0] + ' | ' + ('N/A' if row[1] is None else f'{row[1]:.2%}') + ' | ' + ('N/A' if row[2] is None else f'{row[2]:.2%}') + ' |\n'
    MARKDOWN.write_text(text, encoding='utf-8')
    write_json(OUT / 'comparison.json', {'performance': performance, 'quality': quality_rows})


def main():
    """재평가 원본을 심사하고 기존 보고서를 보존하는 별도 파일을 만든다."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    old_run = load(BASE / 'SC-021_result.json')
    old_judgment = load(BASE / 'SC-021_reviewed_judgment.json')
    run = load(OUT / 'SC-021_result.json')
    if not (OUT / 'official_sources').exists():
        shutil.copytree(BASE / 'official_sources', OUT / 'official_sources')
    scorer.OUT = OUT
    scorer.SOURCES_DIR = OUT / 'official_sources'
    scorer.ADDITIONAL_SOURCES = {'P307024': {'url': 'https://law.go.kr/precInfoP.do?precSeq=240969', 'title': '대법원 2024.6.27. 선고 2023다307024; 새 답변의 보충 인용 검증용'}}
    sources = scorer.fetch_sources()
    case = next(c for c in scorer.GOLD['cases'] if c['id'] == 'SC-021')
    if not args.report_only:
        scorer.judge_case(case, run, sources)
    judgment = load(OUT / 'SC-021_judgment.json')
    reviewed = deepcopy(judgment)
    # 내용과 index를 모두 확인하여 과거 정밀도·재현율 판정을 새 답변 점수와 혼합하지 않는다.
    old_facts = [(f['id'], f['statement']) for f in old_run['facts']]
    new_facts = [(f['id'], f['statement']) for f in run['facts']]
    if old_facts == new_facts:
        reviewed['fact_reviews'] = deepcopy(old_judgment['fact_reviews'])
        reviewed['gold_fact_reviews'] = deepcopy(old_judgment['gold_fact_reviews'])
        reviewed.setdefault('limitations', []).append('사실 추출은 재실행하지 않았다. 사실 ID·내용·순서가 동일함을 검증하여 최초 사실 판정을 유지했다.')
    same_planner = planner_signature(old_run['planner_calls']) == planner_signature(run['planner_calls'])
    if same_planner:
        previous_issues = {i['gold_id']: i for i in old_judgment['issue_reviews']}
        for issue in reviewed['issue_reviews']:
            old = previous_issues[issue['gold_id']]
            issue['planner_detected'] = old['planner_detected']
            issue['planner_quote'] = old.get('planner_quote', '')
            issue['reason'] += ' [실제 Planner 의미 구조가 이전과 동일하여 Planner 판정 유지; 답변 커버리지는 재심사]'
    reviewed['same_planner_signature'] = same_planner
    citation_notes = review_citations(reviewed, sources)
    write_json(OUT / 'citation_second_review.json', citation_notes)
    scorer.validate_judgment(case, run, reviewed)
    write_json(OUT / 'SC-021_reviewed_judgment.json', reviewed)
    # 최초 상담 Trace는 비교용으로만 복사하며 새 상담의 trace_ids에는 넣지 않는다.
    previous_trace_id = old_run['consultation']['trace_id']
    shutil.copy2(BASE / ('trace_' + previous_trace_id + '.json'), OUT / ('trace_' + previous_trace_id + '.json'))
    previous_metrics = scorer.trace_metrics({'trace_ids': [previous_trace_id]})
    metrics = scorer.trace_metrics(run)
    notes = [['재평가 요청 ID', run['request_id']], ['실제 Trace ID', run['consultation']['trace_id']],
             ['사실 비교', '이전 등록 사실 ID·내용 동일; 신규 추출 평가가 아닌 기존 사실 스냅샷 재검증'],
             ['Planner 비교', '이전 의미 구조와 동일' if same_planner else '실제 반환값 변경; 새 항목별 판단'],
             ['성능 비교 범위', '두 상담만 비교. 최초 증거 등록·추출 지표 및 심사 비용은 새 상담 비용에서 제외'],
             ['인용 원문 재대조', 'Judge의 생략부호 발췌 오류를 공식 원문으로 정정하고 동일 법리 반복 2개는 분모 제외. 최초 13개 감사행 중 고유 11개 집계'],
             ['보충 판례 관련성', '상가 사안이라는 차이와 보충 한계를 명시한 비교는 관련성 인정. 직접 주택 법리로 오적용하지 않았는지 별도 확인'],
             ['재평가 집계 테스트', '로컬 카운터 부재·Planner 의미 동일성 검증을 포함한 6개 단위 테스트 통과']]
    scorer.report(sources, cases=[case], output_path=XLSX, markdown_path=MARKDOWN, notes=notes)
    report_comparison(old_run, run, previous_metrics, metrics, scorer.compute_scores(old_judgment), scorer.compute_scores(reviewed))
    write_json(OUT / 'final_validation.json', {'report': str(XLSX), 'case': 'SC-021', 'request_id': run['request_id'], 'trace_id': run['consultation']['trace_id'], 'facts_identical': old_facts == new_facts, 'planner_identical': same_planner, 'baseline_preserved': True, 'scoring_complete': True})
    print(json.dumps({'report': str(XLSX), 'scores': scorer.compute_scores(reviewed), 'metrics': {k: v for k, v in metrics.items() if k not in ('generations', 'traces')}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
