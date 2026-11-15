"""동결된 신규 5건으로 실제 추출·상담·Planner와 Langfuse 사용량을 수집한다.

[흐름]
합성 증거 등록 → 제품의 실제 주장 추출 → 테스트 자동승인 → DB 사실 스냅샷
→ 제품 상담 및 실제 Planner 반환값 관측 → Langfuse 원본 저장.
평가 정답은 제품에 전달하지 않으며 제품 소스나 반환값을 수정하지 않는다.
"""
import asyncio
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import base64
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend/src')]
from dotenv import load_dotenv
load_dotenv(ROOT / 'backend/.env')
os.environ['AUTO_APPROVE_STATUTE_SEARCH'] = 'true'
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import Case, User, EvidenceDocument, EvidenceClaim, Fact
from ai_legal_helper.case_intelligence.evidence_ingestion import get_storage_dir, compute_sha256, extract_text_from_evidence
from ai_legal_helper.case_intelligence.evidence_extractor import extract_claims_from_evidence
from ai_legal_helper.case_intelligence.evidence_manager import process_evidence_review, sync_evidence_document_status
from ai_legal_helper.workflows.legal_workflow import run_legal_consultation
from ai_legal_helper.workflows.conversation_context import ConversationContext
from ai_legal_helper.workflows import issue_planner
from ai_legal_helper.llm.usage import global_token_tracker
from ai_legal_helper.observability.context import set_trace_id, reset_trace_id, set_case_id, reset_case_id
from ai_legal_helper.observability.langfuse_client import start_trace, end_trace, flush_langfuse

DATA = ROOT / 'docs/testset/KPI5_20261115'
CASE_ROOT = ROOT / 'docs/testset'
OUT = ROOT / 'artifacts/kpi5_20261115'
OUT.mkdir(parents=True, exist_ok=True)
GOLD = json.loads((DATA / 'gold_v1.json').read_text(encoding='utf-8'))
PLANS = []
ORIGINAL_PLANNER = issue_planner.plan_legal_issues


def write_json(path, value):
    """원문은 콘솔 로그와 분리된 평가 산출물에만 저장한다.

    Args:
        path: 저장 경로.
        value: JSON 직렬화 대상.
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def observed_planner(*args, **kwargs):
    """실제 호출의 반환값을 복사 보존하며 Planner의 동작은 변경하지 않는다.

    Args:
        *args: 제품 Planner 위치 인자.
        **kwargs: 제품 Planner 키워드 인자.
    Returns:
        원본 Planner가 반환한 과업 목록.
    """
    tasks = ORIGINAL_PLANNER(*args, **kwargs)
    PLANS.append([t.model_dump() for t in tasks])
    return tasks


def fetch_trace(trace_id):
    """인증정보를 노출하지 않고 Langfuse REST 원본을 조회한다.

    Args:
        trace_id: 이번 시험의 추적 ID.
    Returns:
        서버의 추적 원본. 실패 시 예외 종류만 기록한 객체.
    """
    host = os.environ.get('LANGFUSE_HOST', 'http://localhost:3001').rstrip('/')
    key = os.environ.get('LANGFUSE_PUBLIC_KEY', '')
    secret = os.environ.get('LANGFUSE_SECRET_KEY', '')
    if not key or not secret:
        return {'fetch_error': 'credentials_unavailable'}
    request = urllib.request.Request(host + '/api/public/traces/' + trace_id)
    request.add_header('Authorization', 'Basic ' + base64.b64encode(f'{key}:{secret}'.encode()).decode())
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        return {'fetch_error': type(exc).__name__}


def ingest(db, case_id, path):
    """실제 증거 추출 후 테스트 자동승인하고 추출 성공 여부를 검사한다.

    Args:
        db: 제품 DB 세션.
        case_id: 격리 사건 ID.
        path: 합성 증거 경로.
    Returns:
        증거 등록 및 주장 추출 수.
    Raises:
        RuntimeError: 텍스트/주장 추출 실패 또는 추출 주장 부재.
    """
    key = uuid.uuid4().hex + '.txt'
    target = Path(get_storage_dir()) / key
    shutil.copy2(path, target)
    doc = EvidenceDocument(case_id=case_id, original_filename=path.name, safe_storage_key=key,
                           media_type='text/plain', size_bytes=target.stat().st_size,
                           sha256=compute_sha256(str(target)), status='UPLOADED')
    db.add(doc)
    db.commit()
    extract_text_from_evidence(db, doc.id)
    if not extract_claims_from_evidence(db, doc.id):
        raise RuntimeError('evidence_claim_extraction_failed')
    claims = db.query(EvidenceClaim).filter_by(case_id=case_id, evidence_id=doc.id).all()
    if not claims:
        raise RuntimeError('no_extracted_claims')
    # 승인 자체의 정확도는 평가 범위가 아니며 추출 결과를 정답에 맞춰 편집하지 않는다.
    for claim in claims:
        process_evidence_review(db=db, claim_id=claim.id, action='APPROVE', expected_case_id=case_id, expected_evidence_id=doc.id)
    sync_evidence_document_status(db, doc.id)
    db.commit()
    return {'evidence_id': doc.id, 'filename': path.name, 'claims': len(claims)}


async def run_case(case):
    """한 사건의 원본 출력·지연·전체 호출을 보존하고 다음 사건과 격리한다.

    Args:
        case: 동결된 사건 메타데이터. 정답 필드는 제품에 전달하지 않음.
    Returns:
        실제 실행 결과와 오류·측정 메타데이터.
    """
    cid = 'kpi5_' + case['id'].lower() + '_' + uuid.uuid4().hex[:10]
    trace_id = str(uuid.uuid4())
    trace_token = set_trace_id(trace_id)
    case_token = set_case_id(cid)
    start_trace(trace_id, 'KPI5_EVIDENCE_EXTRACTION', session_id=cid, metadata={'scenario': case['id'], 'gold_input': False}, tags=['KPI5_20261115'])
    before = len(global_token_tracker.records)
    plan_before = len(PLANS)
    started = time.perf_counter()
    result = {'id': case['id'], 'case_id': cid, 'title': case['title'] + ' 20261115_E2E_V6_KPI5', 'ingestion_trace_id': trace_id, 'ingestion': []}
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == 'tester@local').first()
        if user is None:
            raise RuntimeError('test_user_missing')
        db.add(Case(id=cid, user_id=user.id, title=result['title'], description='합성 신규 KPI 5건 평가', case_type='HOUSING_LEASE', status='ACTIVE'))
        db.commit()
        for path in sorted((CASE_ROOT / case['id'] / 'evidence').glob('*.txt')):
            result['ingestion'].append(ingest(db, cid, path))
            write_json(OUT / (case['id'] + '_partial.json'), result)
        result['facts'] = [{'id': f.id, 'statement': f.statement, 'source_type': f.source_type, 'source_ref': f.source_ref, 'structured_slots': f.structured_slots} for f in db.query(Fact).filter_by(case_id=cid).all()]
        result['claims'] = [{'id': c.id, 'statement': c.statement, 'claim_type': c.claim_type, 'review_status': c.review_status} for c in db.query(EvidenceClaim).filter_by(case_id=cid).all()]
        result['ingestion_latency_sec'] = time.perf_counter() - started
        end_trace(trace_id)
        reset_trace_id(trace_token)
        trace_token = None
        print('KPI5_PROGRESS', case['id'], 'ingestion_complete', len(result['facts']), flush=True)
        consult_start = time.perf_counter()
        context = ConversationContext(conversation_id=cid, case_id=cid, current_question=case['question'], turn_index=1)
        answer = await run_legal_consultation(question=case['question'], thread_id=cid, conversation_context=context)
        for _ in range(3):
            if answer.get('status') != 'APPROVAL_REQUIRED':
                break
            answer = await run_legal_consultation(question=case['question'], thread_id=cid, conversation_context=context, resume_data={'approved': True})
        result['consultation_latency_sec'] = time.perf_counter() - consult_start
        result['consultation'] = answer
        result['status'] = answer.get('status', 'UNKNOWN')
    except Exception as exc:
        db.rollback()
        result['status'] = 'ERROR'
        result['error_type'] = type(exc).__name__
    finally:
        result['total_execution_sec'] = time.perf_counter() - started
        result['planner_calls'] = PLANS[plan_before:]
        result['usage'] = [r.model_dump() for r in global_token_tracker.records[before:]]
        result['trace_ids'] = sorted({trace_id, *[r['trace_id'] for r in result['usage'] if r.get('trace_id')], *([result['consultation']['trace_id']] if result.get('consultation', {}).get('trace_id') else [])})
        if trace_token is not None:
            end_trace(trace_id)
            reset_trace_id(trace_token)
        reset_case_id(case_token)
        db.close()
        flush_langfuse()
        write_json(OUT / (case['id'] + '_result.json'), result)
        for tid in result['trace_ids']:
            write_json(OUT / ('trace_' + tid + '.json'), fetch_trace(tid))
    print('KPI5_PROGRESS', case['id'], result['status'], round(result['total_execution_sec'], 2), flush=True)
    return result


async def main():
    """Gold 해시를 확인하고 명시적으로 선택한 한 사건만 실행한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=[c['id'] for c in GOLD['cases']], default='SC-021')
    args = parser.parse_args()
    expected = (DATA / 'gold_v1.sha256').read_text().strip()
    assert hashlib.sha256((DATA / 'gold_v1.json').read_bytes()).hexdigest() == expected
    paths = subprocess.check_output(['git', 'ls-files', 'backend/src'], cwd=ROOT, text=True).splitlines()
    write_json(OUT / 'manifest.json', {'gold_sha256': expected, 'gold_version': GOLD['version'], 'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths if (ROOT / p).is_file()}, 'mode': 'actual extraction + auto approval + consultation; no gold injection; no UI/action/document test'})
    issue_planner.plan_legal_issues = observed_planner
    # 라이브러리 로그에 상담·증거 원문을 남기지 않고 상태 코드만 직접 출력한다.
    logging.disable(logging.CRITICAL)
    for case in GOLD['cases']:
        if case['id'] != args.case:
            continue
        target = OUT / (case['id'] + '_result.json')
        if target.exists():
            print('KPI5_PROGRESS', case['id'], 'already_recorded_not_rerun', flush=True)
            continue
        await run_case(case)


if __name__ == '__main__':
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
