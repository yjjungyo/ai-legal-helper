"""사용자가 새로 진행한 SC-021 상담과 현재 사건 자료를 읽기 전용으로 수집한다.

[흐름]
상담 DB 최신 완료 기록 → 실제 사실·증거 스냅샷 → Langfuse 원본 → 재평가 입력.
기존 시험·보고서를 덮어쓰지 않으며, 상담이나 증거 추출을 다시 실행하지 않는다.
"""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend/src')]
from dotenv import load_dotenv
load_dotenv(ROOT / 'backend/.env')
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import Case, ConsultationRecord, Fact, EvidenceClaim, EvidenceDocument
from scripts.evaluation.run_kpi5_20261115 import fetch_trace, write_json

CASE_ID = 'kpi5_sc-021_13e152bbbc'


def row_dict(row):
    """ORM 행을 평가 산출물용 사전으로 복사한다.

    Args:
        row: 읽기 전용으로 조회한 ORM 객체.
    Returns:
        DB 컬럼명·값 사전. 로그에는 출력하지 않는다.
    """
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def collect(request_id=None):
    """해당 사건의 최신 완료 상담 및 출처 데이터를 별도 디렉터리에 저장한다.

    Args:
        request_id: 특정 상담 요청 ID. 생략 시 최신 완료 상담.
    Returns:
        저장 디렉터리.
    Raises:
        RuntimeError: 완료 상담이나 Trace ID가 없는 경우.
    """
    db = SessionLocal()
    try:
        query = db.query(ConsultationRecord).filter_by(case_id=CASE_ID)
        if request_id:
            query = query.filter_by(request_id=request_id)
        else:
            query = query.filter(ConsultationRecord.status.in_(['SUCCESS', 'ERROR', 'REJECTED']))
        record = query.order_by(ConsultationRecord.updated_at.desc()).first()
        if record is None or not record.trace_id:
            raise RuntimeError('completed_consultation_with_trace_not_found')
        case = db.query(Case).filter_by(id=CASE_ID).one()
        out = ROOT / 'artifacts' / ('sc021_reassessment_20261115_' + record.request_id[:8])
        out.mkdir(parents=True, exist_ok=True)
        facts = [row_dict(row) for row in db.query(Fact).filter_by(case_id=CASE_ID).order_by(Fact.created_at, Fact.id).all()]
        claims = [row_dict(row) for row in db.query(EvidenceClaim).filter_by(case_id=CASE_ID).all()]
        documents = [row_dict(row) for row in db.query(EvidenceDocument).filter_by(case_id=CASE_ID).all()]
        consultation = row_dict(record)
        write_json(out / 'consultation_db_snapshot.json', consultation)
        write_json(out / 'evidence_db_snapshot.json', documents)
        write_json(out / 'facts_db_snapshot.json', facts)
        write_json(out / 'claims_db_snapshot.json', claims)
        trace = fetch_trace(record.trace_id)
        write_json(out / ('trace_' + record.trace_id + '.json'), trace)
        if trace.get('fetch_error'):
            raise RuntimeError('langfuse_trace_fetch_failed_' + trace['fetch_error'])
        original = json.loads((ROOT / 'artifacts/kpi5_20261115/SC-021_result.json').read_text(encoding='utf-8'))
        old_facts = {f['id']: f['statement'] for f in original['facts']}
        current_facts = {f['id']: f['statement'] for f in facts}
        # 현재 DB의 정렬 순서는 최초 시험과 다를 수 있으므로 의미 대조의 index를 안정화한다.
        by_id = {f['id']: f for f in facts}
        ordered = [by_id.pop(f['id']) for f in original['facts'] if f['id'] in by_id]
        ordered.extend(by_id.values())
        planner_candidates = []
        for observation in trace.get('observations', []):
            if observation.get('name') == 'supervisor_initialize_node':
                planner_candidates.append({'observation_id': observation['id'], 'output': observation.get('output')})
        write_json(out / 'planner_trace_candidates.json', planner_candidates)
        result = {'id': 'SC-021', 'case_id': CASE_ID, 'title': case.title, 'status': record.status,
                  'request_id': record.request_id, 'facts': ordered, 'claims': claims, 'ingestion': [],
                  'trace_ids': [record.trace_id], 'planner_calls': [],
                  'total_execution_sec': record.elapsed_ms / 1000 if record.elapsed_ms is not None else trace.get('latency'),
                  'consultation_latency_sec': record.elapsed_ms / 1000 if record.elapsed_ms is not None else trace.get('latency'),
                  'consultation': {'question': record.question, 'answer': record.answer,
                                   'trace_id': record.trace_id, 'verification_status': record.verification_status,
                                   'verification_result': record.verification_result, 'final_disposition': record.answer_status,
                                   'sources': record.sources, 'presentation_snapshot': record.presentation_snapshot,
                                   'case_evidence_manifest': record.case_evidence_manifest},
                  'reassessment_metadata': {'question_same_as_gold': record.question.strip() == json.loads((ROOT / 'docs/testset/KPI5_20261115/gold_v1.json').read_text(encoding='utf-8'))['cases'][0]['question'].strip(),
                                            'facts_unchanged_since_initial_run': old_facts == current_facts,
                                            'scope': 'existing evidence/facts + user-initiated latest consultation; extraction not rerun',
                                            'gold_sha256': hashlib.sha256((ROOT / 'docs/testset/KPI5_20261115/gold_v1.json').read_bytes()).hexdigest()}}
        for candidate in planner_candidates:
            output = candidate.get('output')
            if isinstance(output, dict) and isinstance(output.get('issue_tasks'), list):
                result['planner_calls'].append(output['issue_tasks'])
        result['reassessment_metadata']['planner_source'] = 'Langfuse supervisor_initialize_node.output.issue_tasks'
        write_json(out / 'SC-021_result.json', result)
        print(json.dumps({'directory': str(out), 'trace_id': record.trace_id, 'status': record.status,
                          'verification': record.verification_status, 'answer_status': record.answer_status,
                          'facts': len(facts), 'documents': len(documents), 'observations': len(trace.get('observations', [])),
                          'metadata': result['reassessment_metadata']}, ensure_ascii=False))
        return out
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--request-id')
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    collect(args.request_id)
