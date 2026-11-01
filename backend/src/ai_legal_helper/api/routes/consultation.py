"""
모듈명: consultation.py

[모듈 개요]
React 프론트엔드와 통신하는 FastAPI 라우터 모듈이다.
사용자의 법률 상담 요청을 비동기 BackgroundTask로 넘기고 상태를 반환한다.

[주요 기능]
1. 상담 요청(POST) 접수 및 trace_id, request_id 발급
2. 비동기 LangGraph 워크플로우(run_legal_consultation) 실행
3. 주기적 상태 확인을 위한 GET 엔드포인트 제공
4. TokenTracker를 이용해 Trace 범위 내의 사용량 집계

[주의사항]
- P1 단계 구조로 In-memory 딕셔너리(`_consultations`)를 사용하므로 
  서버 재시작 시 상태가 초기화된다.
- BackgroundTask 실패 시 에러가 조용히 무시되지 않도록 로깅 및 상태 업데이트를 수행한다.
"""
import os
import uuid
import time
import threading
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional

from ai_legal_helper.api.schemas.consultation import (
    ConsultationRequest, ConsultationResponse, Source, UsageSummary, ApprovalDecisionRequest,
    ConversationSummary, ConversationDetail, ConsultationStepStatus, ConsultationStep,
    ConsultationProgress, create_initial_progress
)
from ai_legal_helper.observability.context import (
    set_trace_id, reset_trace_id, set_case_id, reset_case_id
)
from ai_legal_helper.llm.usage import global_token_tracker
from ai_legal_helper.workflows.legal_workflow import run_legal_consultation
from ai_legal_helper.observability.langfuse_client import start_trace, end_trace, flush_langfuse, get_git_commit, get_system_name
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.observability.pii_masker import mask_pii
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user, AUTH_BYPASS

logger = get_logger(__name__)
from ai_legal_helper.database.session import get_db, SessionLocal
from ai_legal_helper.database.models import User, Case, ConsultationRecord
from ai_legal_helper.utils.datetime_utils import get_kst_iso

router = APIRouter()

# In-memory store for consultation tasks (ephemeral for P1)
_consultations: Dict[str, ConsultationResponse] = {}

# 대화 세션 단위 동시성 제어 락 (P0-3.1 작업 4)
_conversation_locks: Dict[str, threading.Lock] = {}
_global_conv_lock = threading.Lock()


def _get_conversation_lock(conversation_id: str) -> threading.Lock:
    """대화 세션(conversation_id) 단위의 동시성 제어 뮤텍스 락을 반환한다.

    복수의 비동기 요청이나 스레드가 동일 대화 세션에 동시 접근 시,
    턴 번호(turn_index)의 단조 증가와 고유성을 원자적으로 보장한다 (P0-3.1).
    """
    with _global_conv_lock:
        if conversation_id not in _conversation_locks:
            _conversation_locks[conversation_id] = threading.Lock()
        return _conversation_locks[conversation_id]

NODE_TO_PROGRESS_STEP: Dict[str, tuple[str, str]] = {
    "supervisor_initialize": ("step_1", "사건 기본정보 및 대화 맥락 확인 완료"),
    "intent_analysis": ("step_1", "의뢰인 질의 의도 분석 완료"),
    "general_conversation": ("step_6", "일반 안내 답변 생성 완료"),
    "followup_action": ("step_4", "후속 실행 조치 분석 완료"),
    "route": ("step_2", "사실관계 및 타임라인 조회 중"),
    "plan": ("step_2", "증거 및 사실관계 조회 완료"),
    "run_agents": ("step_3", "법령 및 판례 검색 중"),
    "synthesize": ("step_4", "법률 쟁점별 분석 중"),
    "verification": ("step_5", "증거 및 법률 근거 검증 중"),
    "revise": ("step_5", "검증 피드백 기반 보강 중"),
    "statute_search_approval": ("step_3", "공식 법령 원문 검색 승인 대기 중"),
    "execute_statute_search": ("step_3", "공식 법령 정보 조회 중"),
    "re_analyze": ("step_4", "법령 검색 결과 기반 재분석 중"),
    "finalize": ("step_6", "최종 상담 답변 작성 중"),
    "insufficient": ("step_6", "판단 유보 및 보완 안내 작성 완료"),
}


def update_progress_step(
    request_id: str,
    active_step_id: str,
    status: ConsultationStepStatus = ConsultationStepStatus.RUNNING,
    message: Optional[str] = None
) -> None:
    """지정된 상담의 6단계 진행 상태를 갱신하고 메모리와 DB에 즉시 반영한다 (P0-05)."""
    now_str = get_kst_iso()
    step_order = ["step_1", "step_2", "step_3", "step_4", "step_5", "step_6"]
    curr_idx = step_order.index(active_step_id) if active_step_id in step_order else -1

    resp = _consultations.get(request_id)
    if resp and resp.progress:
        resp.progress.current_step = active_step_id
        resp.progress.updated_at = now_str
        for s in resp.progress.steps:
            s_idx = step_order.index(s.step_id) if s.step_id in step_order else -1
            if s_idx < curr_idx:
                s.status = ConsultationStepStatus.COMPLETED
                if not s.completed_at:
                    s.completed_at = now_str
            elif s_idx == curr_idx:
                s.status = status
                if status == ConsultationStepStatus.RUNNING and not s.started_at:
                    s.started_at = now_str
                elif status in (ConsultationStepStatus.COMPLETED, ConsultationStepStatus.WAITING_APPROVAL, ConsultationStepStatus.FAILED):
                    s.completed_at = now_str
                if message:
                    s.message = message
            else:
                s.status = ConsultationStepStatus.PENDING

    # DB에도 실시간 반영
    try:
        with SessionLocal() as db_session:
            rec = db_session.query(ConsultationRecord).filter(ConsultationRecord.request_id == request_id).first()
            if rec and resp and resp.progress:
                rec.progress = resp.progress.model_dump()
                db_session.commit()
    except Exception as e:
        logger.warning(f"[진행 상태 저장 실패] DB 진행 단계 업데이트 오류: {e}")


def _parse_or_build_progress(
    raw_progress: Any,
    status: str,
    request_id: str,
    timestamp: Optional[str] = None
) -> Optional[ConsultationProgress]:
    """저장된 raw_progress를 파싱하거나 완료 상태에 부합하는 ConsultationProgress를 생성한다."""
    if raw_progress and isinstance(raw_progress, dict):
        try:
            return ConsultationProgress(**raw_progress)
        except Exception:
            pass
    if status == "SUCCESS":
        ts = timestamp or get_kst_iso()
        return ConsultationProgress(
            request_id=request_id,
            current_step=None,
            steps=[
                ConsultationStep(step_id="step_1", title="사건 정보와 이전 상담 맥락 확인", status=ConsultationStepStatus.COMPLETED, completed_at=ts),
                ConsultationStep(step_id="step_2", title="사실관계·타임라인·증거 조회", status=ConsultationStepStatus.COMPLETED, completed_at=ts),
                ConsultationStep(step_id="step_3", title="관련 법령 및 판례 검색", status=ConsultationStepStatus.COMPLETED, completed_at=ts),
                ConsultationStep(step_id="step_4", title="법률 쟁점별 분석", status=ConsultationStepStatus.COMPLETED, completed_at=ts),
                ConsultationStep(step_id="step_5", title="증거·법률 근거 검증", status=ConsultationStepStatus.COMPLETED, completed_at=ts),
                ConsultationStep(step_id="step_6", title="최종 상담 답변 작성", status=ConsultationStepStatus.COMPLETED, completed_at=ts),
            ],
            updated_at=ts,
        )
    return None


def _attach_presentation(
    resp: ConsultationResponse, source_records: Optional[List[Dict[str, Any]]] = None,
) -> ConsultationResponse:
    """Prefer the exact frozen snapshot over rebuilding the current presentation code.

    NULL snapshots from old consultations are explicitly marked LEGACY_REBUILT.
    Invalid snapshots are never repaired or silently regenerated.
    """
    if resp.status != "SUCCESS":
        resp.presentation = None
        resp.presentation_origin = "UNAVAILABLE"
        return resp

    try:
        if resp.presentation_snapshot is not None:
            from ai_legal_helper.presentation.snapshot import validate_presentation_snapshot
            verified = validate_presentation_snapshot(
                resp.presentation_snapshot,
                answer=resp.answer,
                verification_result=resp.verification_result,
                sources=source_records if source_records is not None else resp.sources,
                request_id=resp.request_id,
                case_id=resp.case_id,
                verification_status=resp.verification_status,
                answer_status=resp.answer_status,
            )
            if resp.verification_status != "PASS" or resp.answer_status not in ("DELIVERED", "CAUTIONARY", "REVISED"):
                verified = None
            resp.presentation = verified
            resp.presentation_origin = "FROZEN" if verified is not None else "INVALID_SNAPSHOT"
            if verified is None:
                logger.error(
                    "[PRESENTATION_SNAPSHOT] request=%s INVALID_SNAPSHOT; original answer retained",
                    (resp.request_id or "")[:8],
                )
            return resp

        from ai_legal_helper.presentation.builder import build_consultation_presentation
        resp.presentation = build_consultation_presentation(
            answer=resp.answer,
            verification_result=resp.verification_result,
            verification_status=resp.verification_status,
            answer_status=resp.answer_status,
            sources=resp.sources,
        )
        resp.presentation_origin = "LEGACY_REBUILT" if resp.presentation else "UNAVAILABLE"
        if resp.presentation:
            logger.info(
                "[PRESENTATION_LEGACY] request=%s binding=%s blocks=%d claims=%d sources=%d",
                (resp.request_id or "")[:8],
                resp.presentation.verification_binding,
                len(resp.presentation.blocks),
                len(resp.presentation.claims),
                len(resp.presentation.sources),
            )
    except Exception as exc:
        resp.presentation = None
        resp.presentation_origin = "INVALID_SNAPSHOT" if resp.presentation_snapshot is not None else "UNAVAILABLE"
        logger.warning(
            "[PRESENTATION_READ] request=%s fallback=ANSWER_TEXT error=%s",
            (resp.request_id or "")[:8], type(exc).__name__,
        )
    return resp


def _freeze_record_presentation(rec: ConsultationRecord, resp: ConsultationResponse) -> Optional[dict]:
    """Prepare a one-time frozen snapshot inside the consultation DB transaction."""
    from ai_legal_helper.presentation.snapshot import freeze_record_once
    try:
        frozen = freeze_record_once(rec, resp)
    except Exception as exc:
        # 이미 확정된 스냅샷이 바뀌었다면 DB 트랜잭션을 롤백해야 한다.
        if rec.presentation_snapshot is not None:
            raise
        logger.warning(
            "[PRESENTATION_FREEZE] request=%s legacy_fallback reason=%s",
            (resp.request_id or "")[:8], type(exc).__name__,
        )
        return None
    if frozen is not None:
        logger.info(
            "[PRESENTATION_FREEZE] request=%s version=%s binding=%s",
            (resp.request_id or "")[:8], frozen["snapshot_version"],
            frozen["presentation"].get("verification_binding", "UNKNOWN"),
        )
    return frozen


@router.post("/consultations", response_model=ConsultationResponse)
async def start_consultation(
    req: ConsultationRequest, 
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """법률 상담 프로세스를 비동기적으로 시작한다."""
    conversation_id: str
    if req.case_id:
        # Verify case ownership 및 사건 대표 Conversation ID 확립 (P0-02)
        case = get_case_for_user(req.case_id, current_user, db)
        if not case.primary_conversation_id:
            case.primary_conversation_id = f"conv_{case.id}"
            db.commit()
        conversation_id = case.primary_conversation_id
    else:
        conversation_id = req.conversation_id or str(uuid.uuid4())

    from ai_legal_helper.observability.context import get_trace_id, get_request_id

    # 미들웨어에서 주입된 전역 trace_id와 request_id를 승계하여 로그와 Langfuse를 1:1 매핑
    request_id = get_request_id() or str(uuid.uuid4())
    trace_id = get_trace_id() or str(uuid.uuid4())
    
    # 대화 세션별 뮤텍스 락 획득을 통한 동시 요청 간 turn_index 순차 보장 및 경합 방지 (P0-3.1 작업 4)
    conv_lock = _get_conversation_lock(conversation_id)
    with conv_lock:
        # 연속 대화 세션 식별자 결정 및 대화 맥락 복원 (Phase 1/2)
        from ai_legal_helper.workflows.conversation_context import load_conversation_context
        try:
            conv_context = load_conversation_context(
                db=db,
                conversation_id=conversation_id,
                current_question=req.question,
                case_id=req.case_id,
                user_id=current_user.id,
                auth_bypass=AUTH_BYPASS,
            )
        except PermissionError as pe:
            raise HTTPException(status_code=403, detail=str(pe))

        # DB와 메모리 내 활성 상담을 통틀어 최신 턴 번호를 원자적으로 계산
        max_turn_db = db.query(func.max(ConsultationRecord.turn_index)).filter(
            ConsultationRecord.conversation_id == conversation_id
        ).scalar() or 0

        in_flight_turns = [
            c.turn_index for c in _consultations.values()
            if c.conversation_id == conversation_id and c.turn_index is not None
        ]
        max_turn = max(max_turn_db, max(in_flight_turns) if in_flight_turns else 0)
        turn_index = max(conv_context.turn_index, max_turn + 1)
        conv_context.turn_index = turn_index

        now_kst = get_kst_iso()
        initial_progress = create_initial_progress(request_id, now_kst)

        # Initial status (P1-05 3-tier status model + Case-Centric Progress P0-05)
        resp = ConsultationResponse(
            request_id=request_id,
            conversation_id=conversation_id,
            turn_index=turn_index,
            trace_id=trace_id,
            status="IN_PROGRESS",
            execution_status="IN_PROGRESS",
            verification_status="UNVERIFIED",
            answer_status="WITHHELD",
            routing_status=None,
            question=req.question,
            case_id=req.case_id,
            created_at=now_kst,
            progress=initial_progress,
        )
        # Store user_id to authorize GET later
        _consultations[request_id] = resp
        setattr(resp, "_user_id", current_user.id)

        # DB에 초기 상담 레코드 영구 저장 (DB 수준 고유 제약조건 및 재시도 정책 적용)
        retry_turn = turn_index
        record_saved = False
        max_retries = 3
        for attempt in range(max_retries):
            try:
                record = ConsultationRecord(
                    case_id=req.case_id,
                    user_id=current_user.id,
                    request_id=request_id,
                    conversation_id=conversation_id,
                    turn_index=retry_turn,
                    trace_id=trace_id,
                    question=req.question,
                    status="IN_PROGRESS",
                    execution_status="IN_PROGRESS",
                    verification_status="UNVERIFIED",
                    answer_status="WITHHELD",
                    routing_status=None,
                    progress=initial_progress.model_dump(),
                )
                db.add(record)
                db.commit()
                resp.turn_index = retry_turn
                conv_context.turn_index = retry_turn
                record_saved = True
                break
            except Exception as e:
                db.rollback()
                logger.warning(
                    f"[START_CONSULTATION] 상담 기록 초기 저장 실패 (시도 {attempt+1}/{max_retries}): {e}"
                )
                # 다중 프로세스 동시 경합 시 선점된 DB의 최신 turn_index 재조회
                max_turn_db_retry = db.query(func.max(ConsultationRecord.turn_index)).filter(
                    ConsultationRecord.conversation_id == conversation_id
                ).scalar() or 0
                retry_turn = max(retry_turn + 1, max_turn_db_retry + 1)

        if not record_saved:
            # 최종 저장 실패 시 메모리 캐시 정리 및 백그라운드 작업 차단
            _consultations.pop(request_id, None)
            logger.error(
                f"[START_CONSULTATION] 상담 기록 DB 저장 실패: request_id={request_id}, "
                f"conversation_id={conversation_id} ({max_retries}회 재시도 실패). 백그라운드 작업을 실행하지 않고 HTTP 500을 반환합니다."
            )
            raise HTTPException(
                status_code=500,
                detail="상담 기록을 데이터베이스에 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            )

    # DB에 성공적으로 저장된 경우에만 백그라운드 워크플로우 스케줄링
    background_tasks.add_task(process_consultation, request_id, trace_id, req, conv_context)
    
    return resp

async def process_consultation(request_id: str, trace_id: str, req: ConsultationRequest, conv_context: Optional[Any] = None):
    """실제 LangGraph 워크플로우를 실행하고 결과를 업데이트하는 백그라운드 태스크."""
    t_token = set_trace_id(trace_id)
    c_token = None
    if req.case_id:
        c_token = set_case_id(req.case_id)
        
    sys_name = get_system_name()
    git_sha = get_git_commit()
    start_trace(
        trace_id=trace_id,
        name="LegalConsultation",
        session_id=req.case_id,
        metadata={
            "question": mask_pii(req.question[:120]),
            "request_id": request_id,
            "case_id": req.case_id,
            "session_id": req.case_id,
            "run_id": request_id,
            "git_commit": git_sha,
            "system_name": sys_name,
        },
        tags=[sys_name],
    )
    start_time = time.time()
    try:
        # LangGraph 노드 실행 단계별 진행 상태 실시간 콜백 및 한국어 로그 출력
        logger.info(f"[상담 분석 시작] 의뢰인 질문 접수 (사건: {req.case_id or '단독상담'}, 요청: {request_id[:8]})")

        async def on_step(node_name: str):
            if node_name in NODE_TO_PROGRESS_STEP:
                step_id, msg = NODE_TO_PROGRESS_STEP[node_name]
                step_num = step_id.replace("step_", "")
                logger.info(f"[{step_num}단계 진행 상태] {msg} (노드: {node_name})")
                update_progress_step(request_id, step_id, ConsultationStepStatus.RUNNING, msg)

        # Run unified workflow
        result = await run_legal_consultation(
            req.question,
            thread_id=request_id,
            conversation_context=conv_context,
            on_step_callback=on_step
        )
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Aggregate token usage for this trace
        agg = global_token_tracker.aggregate_by("trace_id").get(trace_id, {})
        
        # Agent usage specifically for this trace
        agent_usage = {}
        for r in global_token_tracker.records:
            if r.trace_id == trace_id:
                agent = r.agent_name or "unknown"
                if agent not in agent_usage:
                    agent_usage[agent] = 0
                if r.total_tokens:
                    agent_usage[agent] += r.total_tokens
        
        usage_summary = UsageSummary(
            total_calls=agg.get("total_calls", 0),
            actual_calls=agg.get("actual_calls", 0),
            estimated_calls=agg.get("estimated_calls", 0),
            unavailable_calls=agg.get("unavailable_calls", 0),
            input_tokens=agg.get("input_tokens", 0),
            output_tokens=agg.get("output_tokens", 0),
            total_tokens=agg.get("total_tokens", 0),
            agent_usage=agent_usage,
        )
        
        resp = _consultations[request_id]
        if hasattr(result, "get"):
            if result.get("conversation_id"):
                resp.conversation_id = result.get("conversation_id")
            if result.get("turn_index"):
                resp.turn_index = result.get("turn_index")
            if result.get("intent"):
                resp.intent = result.get("intent")
            if result.get("resolved_query"):
                resp.resolved_query = result.get("resolved_query")
        is_approval_required = (result.get("status") == "APPROVAL_REQUIRED")
        is_error = (result.get("status") == "ERROR")
        ver_res = result.get("verification_result") or {}
        ver_status = ver_res.get("status") or "UNVERIFIED"
        resp.routing_status = result.get("routing_status")

        if is_error:
            resp.status = "ERROR"
            resp.execution_status = "ERROR"
            resp.verification_status = ver_status
            resp.answer_status = "WITHHELD"
            resp.approval_request = None
            resp.answer = result.get("answer", "처리 중 오류가 발생했습니다.")
            if resp.progress:
                resp.progress.updated_at = get_kst_iso()
                if resp.progress.current_step:
                    for s in resp.progress.steps:
                        if s.step_id == resp.progress.current_step:
                            s.status = ConsultationStepStatus.FAILED
        elif is_approval_required:
            resp.status = "APPROVAL_REQUIRED"
            resp.execution_status = "APPROVAL_REQUIRED"
            resp.verification_status = ver_status
            resp.answer_status = "WITHHELD"
            resp.approval_request = result.get("approval_request")
            resp.answer = result.get("answer", "해당 쟁점에 필요한 공식 법령(특별법 등) 원문 검색 진행을 위해 사용자 승인이 필요합니다.")
            update_progress_step(request_id, "step_3", ConsultationStepStatus.WAITING_APPROVAL, "공식 법령 원문 검색 승인 대기 중")
        else:
            resp.status = "SUCCESS"
            resp.execution_status = "COMPLETED"
            resp.verification_status = ver_status
            final_disp = result.get("final_disposition")
            if final_disp in ("DELIVERED", "CAUTIONARY", "WITHHELD"):
                resp.answer_status = final_disp
            elif ver_status == "PASS":
                resp.answer_status = "DELIVERED"
            elif ver_status == "REVISE":
                resp.answer_status = "CAUTIONARY"
            else:
                resp.answer_status = "WITHHELD"
            resp.answer = result.get("answer", "")
            resp.approval_request = result.get("approval_request")
            if resp.progress:
                resp.progress.current_step = None
                now_iso = get_kst_iso()
                resp.progress.updated_at = now_iso
                for s in resp.progress.steps:
                    s.status = ConsultationStepStatus.COMPLETED
                    if not s.completed_at:
                        s.completed_at = now_iso
        
        # Map sources (서버 Source Registry 기반 표준 Source 스키마 정규화 및 의미 기반 중복 제거)
        from ai_legal_helper.rag.source_schema import normalize_source_dict
        sources_data = result.get("cited_sources") or result.get("sources", [])
        dedup_sources = []
        seen_source_keys = set()
        for s in sources_data:
            std_dict = normalize_source_dict(s)
            stype = std_dict.get("source_type")
            if stype == "CASE_EVIDENCE":
                key = (stype, std_dict.get("file"), str(std_dict.get("page") or "1"))
            elif stype == "STATUTE":
                key = (stype, std_dict.get("statute_name") or std_dict.get("title"), std_dict.get("article"))
            else:
                key = (std_dict.get("source_id"), std_dict.get("file"), str(std_dict.get("page") or ""))

            if key not in seen_source_keys:
                seen_source_keys.add(key)
                dedup_sources.append(Source(**std_dict))
        resp.sources = dedup_sources
        
        resp.elapsed_ms = elapsed_ms
        resp.usage_summary = usage_summary
        
        # P2.1 Fields
        resp.verification_result = result.get("verification_result", {})
        resp.revision_count = result.get("revision_count", 0)
        resp.selected_agents = result.get("selected_agents", [])
        resp.warnings.extend(result.get("warnings", []))

        # Issue-level Verification v1.0 & P0-2 Grounding Fields
        resp.issue_results = result.get("issue_results", [])
        resp.verified_facts = result.get("verified_facts", [])
        resp.missing_evidence = result.get("missing_evidence", [])
        resp.evidence_citations = result.get("evidence_citations", [])
        from ai_legal_helper.api.schemas.consultation import ClaimCitation
        resp.claim_citations = [
            ClaimCitation(**c) if isinstance(c, dict) else c
            for c in (result.get("claim_citations") or (resp.verification_result or {}).get("claim_citations") or [])
        ]
        resp.case_delta = result.get("case_delta") or (resp.verification_result or {}).get("case_delta")

        logger.info(
            f"[상담 분석 완료] 6단계 분석 및 검증 완료 (요청: {request_id[:8]} | 소요: {elapsed_ms:.1f}ms | "
            f"처분: {resp.answer_status} | 검증: {resp.verification_status} | 인용출처: {len(resp.sources)}건)"
        )

        # 요구사항 5: Langfuse 루트 Span/Trace에 최종 출처·검증·실행시간·토큰 요약 기록 (P2-02)
        try:
            from ai_legal_helper.observability.context import get_current_span_id
            from ai_legal_helper.observability.langfuse_client import update_span, build_consultation_trace_summary
            audit_meta = (resp.verification_result or {}).get("citation_audit", {})
            import hashlib
            draft_txt = (result.get("draft_answer") or "") if isinstance(result, dict) else ""
            final_txt = (result.get("answer") or "") if isinstance(result, dict) else ""
            summary_dict = build_consultation_trace_summary(
                request_id=request_id,
                case_id=req.case_id,
                execution_status=resp.execution_status or "COMPLETED",
                verification_status=resp.verification_status or "UNVERIFIED",
                answer_status=resp.answer_status or "DELIVERED",
                selected_agents=resp.selected_agents,
                revision_count=resp.revision_count,
                retrieval_info={
                    "methods": audit_meta.get("retrieval_methods", []),
                    "hits_count": len(resp.sources),
                    "source_ids": [s.source_id for s in resp.sources if s.source_id],
                },
                verification_info={
                    "status": (resp.verification_result or {}).get("status"),
                    "reason_code": (resp.verification_result or {}).get("reason_code"),
                    "citation_existence_rate": audit_meta.get("citation_existence_rate", 1.0),
                    "citation_support_rate": audit_meta.get("citation_support_rate", 1.0),
                    "citation_coverage_rate": audit_meta.get("citation_coverage_rate", 1.0),
                    "rejected_citations": audit_meta.get("rejected_citation_ids", []),
                },
                usage_info={
                    "total_calls": usage_summary.total_calls,
                    "total_tokens": usage_summary.total_tokens,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
                conversation_id=getattr(resp, "conversation_id", None),
                turn_index=getattr(resp, "turn_index", 1) or 1,
                intent=getattr(resp, "intent", None),
                resolved_query=getattr(resp, "resolved_query", None),
            )
            # STEP 1.7 Langfuse 품질 메타데이터 추가
            summary_dict.update({
                "draft_hash": hashlib.sha256(draft_txt.encode("utf-8")).hexdigest()[:16] if draft_txt else None,
                "final_answer_hash": hashlib.sha256(final_txt.encode("utf-8")).hexdigest()[:16] if final_txt else None,
                "draft_preserved": bool(draft_txt and draft_txt == final_txt),
                "final_disposition": resp.answer_status,
                "revision_reason": (resp.verification_result or {}).get("reason_code"),
                "llm_call_count": usage_summary.total_calls,
                "total_duration_ms": round(elapsed_ms, 2),
            })
            update_span(get_current_span_id(), summary_dict)

            # Langfuse Scores/Evaluation 탭에 정량 평가 점수 기록
            from ai_legal_helper.observability.langfuse_client import log_score
            exist_raw = audit_meta.get("citation_existence_rate")
            exist_rate = float(exist_raw) if exist_raw not in (None, "N/A") else 0.0
            supp_raw = audit_meta.get("citation_support_rate")
            supp_rate = float(supp_raw) if supp_raw not in (None, "N/A") else 0.0
            score_val = 1.0 if ver_status == "PASS" else (0.5 if ver_status == "REVISE" else 0.0)
            log_score(trace_id, "citation_existence_rate", exist_rate)
            log_score(trace_id, "citation_support_rate", supp_rate)
            log_score(trace_id, "verification_status", score_val, comment=ver_status)
        except Exception:
            pass
        
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.exception(
            f"[상담 처리 실패] 백그라운드 워크플로우 실행 중 치명적 예외 발생 "
            f"(요청: {request_id[:8]}, 사건: {req.case_id or '단독상담'}, 경과: {elapsed_ms:.1f}ms): {e}"
        )
        resp = _consultations[request_id]
        resp.status = "ERROR"
        resp.execution_status = "ERROR"
        resp.verification_status = "UNVERIFIED"
        resp.answer_status = "WITHHELD"
        resp.warnings.append(str(e))
        resp.elapsed_ms = elapsed_ms
    finally:
        # DB에 상담 결과 및 답변 영구 저장
        try:
            with SessionLocal() as db_session:
                rec = db_session.query(ConsultationRecord).filter(
                    ConsultationRecord.request_id == request_id
                ).first()
                if rec:
                    rec.status = resp.status
                    rec.execution_status = getattr(resp, "execution_status", resp.status)
                    rec.verification_status = getattr(resp, "verification_status", None)
                    rec.answer_status = getattr(resp, "answer_status", None)
                    rec.routing_status = getattr(resp, "routing_status", None)
                    rec.answer = resp.answer
                    rec.approval_request = resp.approval_request
                    rec.sources = [s.model_dump() for s in resp.sources] if resp.sources else []
                    rec.verification_result = resp.verification_result
                    rec.warnings = resp.warnings
                    rec.selected_agents = resp.selected_agents
                    rec.elapsed_ms = resp.elapsed_ms
                    if getattr(resp, "progress", None):
                        rec.progress = resp.progress.model_dump()
                    if getattr(resp, "conversation_id", None):
                        rec.conversation_id = resp.conversation_id
                    if getattr(resp, "turn_index", None):
                        rec.turn_index = resp.turn_index
                    frozen = _freeze_record_presentation(rec, resp)
                    db_session.commit()
                    resp.presentation_snapshot = frozen
        except Exception as db_err:
            logger.error(f"[상담 DB 저장 실패] 상담 결과 데이터베이스 커밋 실패 (요청: {request_id[:8]}): {db_err}")

        end_trace(trace_id)
        flush_langfuse()
        reset_trace_id(t_token)
        if c_token:
            reset_case_id(c_token)

def _resolve_legacy_answer_status(raw_answer_status: Optional[str], verification_status: Optional[str], status: str) -> str:
    """레거시 DB 기록의 answer_status를 안전하게 보정한다 (P0-02 호환성)."""
    if raw_answer_status in ("DELIVERED", "CAUTIONARY", "WITHHELD"):
        return raw_answer_status
    if status == "APPROVAL_REQUIRED":
        return "WITHHELD"
    if verification_status == "PASS":
        return "DELIVERED"
    if verification_status == "REVISE":
        return "CAUTIONARY"
    return "WITHHELD"


@router.get("/consultations/{request_id}", response_model=ConsultationResponse)
async def get_consultation(
    request_id: str, 
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if request_id in _consultations:
        resp = _consultations[request_id]
        if not AUTH_BYPASS and getattr(resp, "_user_id", None) != current_user.id:
            raise HTTPException(status_code=403, detail="해당 상담에 접근할 권한이 없습니다.")
        if resp.progress is None:
            resp.progress = _parse_or_build_progress(None, resp.status, resp.request_id, resp.created_at)
        return _attach_presentation(resp)
        
    record = db.query(ConsultationRecord).filter(
        ConsultationRecord.request_id == request_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Consultation not found")
        
    if not AUTH_BYPASS and record.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="해당 상담에 접근할 권한이 없습니다.")
        
    from ai_legal_helper.rag.source_schema import normalize_source_dict
    sources = []
    seen_keys = set()
    for s in (record.sources or []):
        std_dict = normalize_source_dict(s)
        key = (std_dict.get("source_id"), std_dict.get("file"), str(std_dict.get("page") or ""))
        if key not in seen_keys:
            seen_keys.add(key)
            sources.append(Source(**std_dict))

    ans_status = _resolve_legacy_answer_status(
        getattr(record, "answer_status", None),
        getattr(record, "verification_status", None),
        record.status,
    )

    ver_res = record.verification_result or {}
    prog = _parse_or_build_progress(
        record.progress,
        record.status,
        record.request_id,
        get_kst_iso(record.created_at) if record.created_at else None
    )
    response = ConsultationResponse(
        request_id=record.request_id,
        conversation_id=record.conversation_id,
        turn_index=record.turn_index or 1,
        trace_id=record.trace_id or "",
        status=record.status,
        execution_status=getattr(record, "execution_status", record.status) or "COMPLETED",
        verification_status=getattr(record, "verification_status", None),
        answer_status=ans_status,
        routing_status=getattr(record, "routing_status", None),
        answer=record.answer,
        presentation_snapshot=getattr(record, "presentation_snapshot", None),
        approval_request=record.approval_request,
        sources=sources,
        elapsed_ms=record.elapsed_ms,
        warnings=record.warnings or [],
        verification_result=ver_res,
        selected_agents=record.selected_agents or [],
        question=record.question,
        case_id=record.case_id,
        created_at=get_kst_iso(record.created_at) if record.created_at else None,
        issue_results=ver_res.get("issue_results", []),
        verified_facts=ver_res.get("verified_facts", []),
        missing_evidence=ver_res.get("missing_evidence", []),
        evidence_citations=ver_res.get("evidence_citations", []),
        claim_citations=ver_res.get("claim_citations", []),
        case_delta=ver_res.get("case_delta"),
        progress=prog,
    )
    return _attach_presentation(response, source_records=record.sources or [])

@router.get("/consultations/{request_id}/status")
async def get_consultation_status(
    request_id: str, 
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if request_id in _consultations:
        resp = _consultations[request_id]
        if not AUTH_BYPASS and getattr(resp, "_user_id", None) != current_user.id:
            raise HTTPException(status_code=403, detail="해당 상담에 접근할 권한이 없습니다.")
        return {"request_id": request_id, "status": resp.status}
        
    record = db.query(ConsultationRecord).filter(
        ConsultationRecord.request_id == request_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Consultation not found")
    if not AUTH_BYPASS and record.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="해당 상담에 접근할 권한이 없습니다.")
    return {"request_id": request_id, "status": record.status}

@router.post("/consultations/{request_id}/approve", response_model=ConsultationResponse)
async def decide_statute_search_approval(
    request_id: str,
    decision: ApprovalDecisionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """HILT 법령 원문 검색 승인/거절 결정을 접수하고 상담 워크플로우를 재개(Resume)한다.

    Args:
        request_id: 대상 상담 요청 ID (thread_id).
        decision: 승인 여부(`approved: bool`) 및 사유.
        background_tasks: 비동기 재개 태스크 스케줄러.
        current_user: 현재 로그인 사용자.
        db: 데이터베이스 세션.

    Returns:
        ConsultationResponse: 상태가 'IN_PROGRESS'로 전이된 상담 응답 객체.
    """
    record = db.query(ConsultationRecord).filter(
        ConsultationRecord.request_id == request_id
    ).first()

    if not record and request_id not in _consultations:
        raise HTTPException(status_code=404, detail="상담 기록을 찾을 수 없습니다.")

    # 권한 검사
    user_id = record.user_id if record else getattr(_consultations.get(request_id), "_user_id", None)
    if not AUTH_BYPASS and user_id != current_user.id:
        raise HTTPException(status_code=403, detail="해당 상담에 접근할 권한이 없습니다.")

    current_status = record.status if record else _consultations[request_id].status
    if current_status != "APPROVAL_REQUIRED":
        raise HTTPException(
            status_code=400, 
            detail=f"현재 승인 대기 상태가 아닙니다. (현재 상태: {current_status})"
        )

    trace_id = record.trace_id if record else _consultations[request_id].trace_id
    case_id = record.case_id if record else _consultations[request_id].case_id

    # 원자적 상태 변경 및 중복 Resume 방지 (P1-06)
    # [P2-03] 재개(Resume) 접수 즉시 기존의 승인 요청 안내 임시 텍스트를 클리어하여
    # 재분석 진행 중 사용자에게 이전 임시 문구가 노출되지 않고 진행 상태 UI가 표시되도록 함
    if record:
        updated_rows = db.query(ConsultationRecord).filter(
            ConsultationRecord.request_id == request_id,
            ConsultationRecord.status == "APPROVAL_REQUIRED",
        ).update({
            "status": "IN_PROGRESS",
            "execution_status": "IN_PROGRESS",
            "answer": None,
        })
        db.commit()
        if updated_rows == 0:
            raise HTTPException(
                status_code=409,
                detail="이미 다른 요청에 의해 승인/거절 처리가 진행 중이거나 완료되었습니다.",
            )

    # 메모리 캐시 상태 동기화 및 임시 답변 초기화
    if request_id in _consultations:
        resp = _consultations[request_id]
        resp.status = "IN_PROGRESS"
        resp.execution_status = "IN_PROGRESS"
        resp.answer = None
        if decision.approved:
            update_progress_step(request_id, "step_3", ConsultationStepStatus.RUNNING, "공식 법령 원문 검색 승인 접수 및 재분석 진행 중")
        else:
            update_progress_step(request_id, "step_3", ConsultationStepStatus.SKIPPED, "법령 원문 검색 거절 및 현 상태 종결")
    else:
        resp = ConsultationResponse(
            request_id=request_id,
            trace_id=trace_id or "",
            status="IN_PROGRESS",
            execution_status="IN_PROGRESS",
            verification_status="UNVERIFIED",
            answer_status="WITHHELD",
            routing_status="CLASSIFIED",
            answer=None,
            question=record.question if record else None,
            case_id=case_id,
            created_at=get_kst_iso(record.created_at) if record and record.created_at else None,
        )
        _consultations[request_id] = resp
        setattr(resp, "_user_id", current_user.id)

    # 비동기 백그라운드 태스크로 재개(Resume) 파이프라인 가동
    background_tasks.add_task(
        process_consultation_resume, 
        request_id, 
        trace_id or "", 
        case_id,
        decision
    )

    return resp


async def process_consultation_resume(
    request_id: str, 
    trace_id: str, 
    case_id: Optional[str],
    decision: ApprovalDecisionRequest
):
    """승인/거절 결정을 바탕으로 중단된 LangGraph 워크플로우를 재개(Resume)하는 백그라운드 태스크."""
    t_token = set_trace_id(trace_id)
    c_token = set_case_id(case_id) if case_id else None
    sys_name = get_system_name()
    git_sha = get_git_commit()
    start_trace(
        trace_id=trace_id,
        name="LegalConsultation",
        session_id=case_id,
        metadata={
            "request_id": request_id,
            "case_id": case_id,
            "session_id": case_id,
            "run_id": request_id,
            "git_commit": git_sha,
            "system_name": sys_name,
            "resumed": True,
        },
        tags=[sys_name],
    )
    start_time = time.time()

    try:
        async def on_step(node_name: str):
            if node_name in NODE_TO_PROGRESS_STEP:
                step_id, msg = NODE_TO_PROGRESS_STEP[node_name]
                step_num = step_id.replace("step_", "")
                logger.info(f"[{step_num}단계 재개 상태] {msg} (노드: {node_name})")
                update_progress_step(request_id, step_id, ConsultationStepStatus.RUNNING, msg)

        # LangGraph Command(resume=...) 호출로 인터럽트된 노드 재개
        result = await run_legal_consultation(
            question="",
            thread_id=request_id,
            resume_data={"approved": decision.approved, "reason": decision.reason},
            on_step_callback=on_step
        )

        elapsed_ms = (time.time() - start_time) * 1000

        # 사용량 집계
        agg = global_token_tracker.aggregate_by("trace_id").get(trace_id, {})
        agent_usage = {}
        for r in global_token_tracker.records:
            if r.trace_id == trace_id:
                agent = r.agent_name or "unknown"
                agent_usage[agent] = agent_usage.get(agent, 0) + (r.total_tokens or 0)

        usage_summary = UsageSummary(
            total_calls=agg.get("total_calls", 0),
            actual_calls=agg.get("actual_calls", 0),
            estimated_calls=agg.get("estimated_calls", 0),
            unavailable_calls=agg.get("unavailable_calls", 0),
            input_tokens=agg.get("input_tokens", 0),
            output_tokens=agg.get("output_tokens", 0),
            total_tokens=agg.get("total_tokens", 0),
            agent_usage=agent_usage,
        )

        resp = _consultations.get(request_id)
        if not resp:
            resp = ConsultationResponse(
                request_id=request_id,
                trace_id=trace_id,
                status="SUCCESS",
            )
            _consultations[request_id] = resp

        ver_res = result.get("verification_result") or {}
        ver_status = ver_res.get("status") or "UNVERIFIED"

        resp.status = "SUCCESS"
        resp.execution_status = "COMPLETED"
        resp.verification_status = ver_status
        resp.routing_status = result.get("routing_status", "CLASSIFIED")
        final_disp = result.get("final_disposition")
        if final_disp in ("DELIVERED", "CAUTIONARY", "WITHHELD"):
            resp.answer_status = final_disp
        elif ver_status == "PASS":
            resp.answer_status = "DELIVERED"
        elif ver_status == "REVISE":
            resp.answer_status = "CAUTIONARY"
        else:
            resp.answer_status = "WITHHELD"
        resp.answer = result.get("answer", "")
        resp.elapsed_ms = elapsed_ms
        resp.usage_summary = usage_summary
        resp.verification_result = ver_res
        resp.revision_count = result.get("revision_count", 0)
        resp.selected_agents = result.get("selected_agents", [])
        resp.warnings.extend(result.get("warnings", []))
        resp.approval_request = result.get("approval_request")
        if resp.progress:
            resp.progress.current_step = None
            now_iso = get_kst_iso()
            resp.progress.updated_at = now_iso
            for s in resp.progress.steps:
                s.status = ConsultationStepStatus.COMPLETED
                if not s.completed_at:
                    s.completed_at = now_iso

        # Sources 정규화 (의미 기반 중복 제거)
        from ai_legal_helper.rag.source_schema import normalize_source_dict
        sources_data = result.get("cited_sources") or result.get("sources", [])
        dedup_sources = []
        seen_source_keys = set()
        for s in sources_data:
            std_dict = normalize_source_dict(s)
            stype = std_dict.get("source_type")
            if stype == "CASE_EVIDENCE":
                key = (stype, std_dict.get("file"), str(std_dict.get("page") or "1"))
            elif stype == "STATUTE":
                key = (stype, std_dict.get("statute_name") or std_dict.get("title"), std_dict.get("article"))
            else:
                key = (std_dict.get("source_id"), std_dict.get("file"), str(std_dict.get("page") or ""))

            if key not in seen_source_keys:
                seen_source_keys.add(key)
                dedup_sources.append(Source(**std_dict))
        resp.sources = dedup_sources

        # Langfuse span 업데이트 (P2-02)
        try:
            from ai_legal_helper.observability.context import get_current_span_id
            from ai_legal_helper.observability.langfuse_client import update_span, build_consultation_trace_summary
            audit_meta = (resp.verification_result or {}).get("citation_audit", {})
            summary_dict = build_consultation_trace_summary(
                request_id=request_id,
                case_id=case_id,
                execution_status=resp.execution_status or "COMPLETED",
                verification_status=resp.verification_status or "UNVERIFIED",
                answer_status=resp.answer_status or "DELIVERED",
                selected_agents=resp.selected_agents,
                revision_count=resp.revision_count,
                retrieval_info={
                    "methods": audit_meta.get("retrieval_methods", []),
                    "hits_count": len(resp.sources),
                    "source_ids": [s.source_id for s in resp.sources if s.source_id],
                },
                verification_info={
                    "status": (resp.verification_result or {}).get("status"),
                    "reason_code": (resp.verification_result or {}).get("reason_code"),
                    "citation_existence_rate": audit_meta.get("citation_existence_rate", 1.0),
                    "citation_support_rate": audit_meta.get("citation_support_rate", 1.0),
                    "citation_coverage_rate": audit_meta.get("citation_coverage_rate", 1.0),
                    "rejected_citations": audit_meta.get("rejected_citation_ids", []),
                },
                usage_info={
                    "total_calls": usage_summary.total_calls,
                    "total_tokens": usage_summary.total_tokens,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )
            update_span(get_current_span_id(), summary_dict)

            from ai_legal_helper.observability.langfuse_client import log_score
            exist_raw = audit_meta.get("citation_existence_rate")
            exist_rate = float(exist_raw) if exist_raw not in (None, "N/A") else 0.0
            supp_raw = audit_meta.get("citation_support_rate")
            supp_rate = float(supp_raw) if supp_raw not in (None, "N/A") else 0.0
            score_val = 1.0 if ver_status == "PASS" else (0.5 if ver_status == "REVISE" else 0.0)
            log_score(trace_id, "citation_existence_rate", exist_rate)
            log_score(trace_id, "citation_support_rate", supp_rate)
            log_score(trace_id, "verification_status", score_val, comment=ver_status)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[상담 재개 오류] 상담({request_id}) 재개 처리 실패: {e}")
        resp = _consultations.get(request_id)
        if resp:
            resp.status = "ERROR"
            resp.execution_status = "ERROR"
            resp.verification_status = "UNVERIFIED"
            resp.answer_status = "WITHHELD"
            resp.warnings.append(str(e))
    finally:
        # DB에 상담 결과 및 답변 영구 저장
        try:
            with SessionLocal() as db_session:
                rec = db_session.query(ConsultationRecord).filter(
                    ConsultationRecord.request_id == request_id
                ).first()
                if rec and request_id in _consultations:
                    resp = _consultations[request_id]
                    rec.status = resp.status
                    rec.execution_status = getattr(resp, "execution_status", resp.status)
                    rec.verification_status = getattr(resp, "verification_status", None)
                    rec.answer_status = getattr(resp, "answer_status", None)
                    rec.routing_status = getattr(resp, "routing_status", None)
                    rec.answer = resp.answer
                    rec.approval_request = resp.approval_request
                    rec.sources = [s.model_dump() for s in resp.sources] if resp.sources else []
                    rec.verification_result = resp.verification_result
                    rec.warnings = resp.warnings
                    rec.selected_agents = resp.selected_agents
                    rec.elapsed_ms = resp.elapsed_ms
                    if getattr(resp, "progress", None):
                        rec.progress = resp.progress.model_dump()
                    frozen = _freeze_record_presentation(rec, resp)
                    db_session.commit()
                    resp.presentation_snapshot = frozen
        except Exception as db_err:
            logger.error(f"[상담 재개 DB 저장 실패] 상담 재개 결과 DB 커밋 실패 (요청: {request_id[:8]}): {db_err}")

        end_trace(trace_id)
        flush_langfuse()
        reset_trace_id(t_token)
        if c_token:
            reset_case_id(c_token)


@router.get("/cases/{case_id}/consultations", response_model=List[ConsultationResponse])
async def list_case_consultations(
    case_id: str,
    conversation_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """특정 사건에 저장된 모든 상담 내역을 시간순(ASC)으로 통합 조회한다 (Case = One Persistent Conversation)."""
    from ai_legal_helper.rag.source_schema import normalize_source_dict
    query = db.query(ConsultationRecord).filter(ConsultationRecord.case_id == case_id)
    if conversation_id:
        query = query.filter(ConsultationRecord.conversation_id == conversation_id)
    records = query.order_by(ConsultationRecord.created_at.asc(), ConsultationRecord.turn_index.asc()).all()
    
    results = []
    for rec in records:
        if rec.request_id in _consultations:
            live_resp = _consultations[rec.request_id]
            if getattr(rec, "presentation_snapshot", None) is not None:
                live_resp.presentation_snapshot = rec.presentation_snapshot
            if live_resp.progress is None:
                live_resp.progress = _parse_or_build_progress(rec.progress, live_resp.status, rec.request_id, live_resp.created_at)
            results.append(live_resp)
            continue

        sources = []
        seen_keys = set()
        for s in (rec.sources or []):
            std_dict = normalize_source_dict(s)
            key = (std_dict.get("source_id"), std_dict.get("file"), str(std_dict.get("page") or ""))
            if key not in seen_keys:
                seen_keys.add(key)
                sources.append(Source(**std_dict))
        ans_status = _resolve_legacy_answer_status(
            getattr(rec, "answer_status", None),
            getattr(rec, "verification_status", None),
            rec.status,
        )
        prog = _parse_or_build_progress(
            rec.progress,
            rec.status,
            rec.request_id,
            get_kst_iso(rec.created_at) if rec.created_at else None
        )
        results.append(ConsultationResponse(
            request_id=rec.request_id,
            conversation_id=rec.conversation_id,
            turn_index=rec.turn_index or 1,
            trace_id=rec.trace_id or "",
            status=rec.status,
            execution_status=getattr(rec, "execution_status", rec.status) or "COMPLETED",
            verification_status=getattr(rec, "verification_status", None),
            answer_status=ans_status,
            routing_status=getattr(rec, "routing_status", None),
            answer=rec.answer,
            presentation_snapshot=getattr(rec, "presentation_snapshot", None),
            approval_request=rec.approval_request,
            sources=sources,
            elapsed_ms=rec.elapsed_ms,
            warnings=rec.warnings or [],
            verification_result=rec.verification_result or {},
            selected_agents=rec.selected_agents or [],
            question=rec.question,
            case_id=rec.case_id,
            created_at=get_kst_iso(rec.created_at) if rec.created_at else None,
            issue_results=(rec.verification_result or {}).get("issue_results", []),
            verified_facts=(rec.verification_result or {}).get("verified_facts", []),
            missing_evidence=(rec.verification_result or {}).get("missing_evidence", []),
            evidence_citations=(rec.verification_result or {}).get("evidence_citations", []),
            claim_citations=(rec.verification_result or {}).get("claim_citations", []),
            progress=prog,
        ))
    record_sources = {rec.request_id: (rec.sources or []) for rec in records}
    return [_attach_presentation(item, source_records=record_sources.get(item.request_id)) for item in results]




@router.get("/cases/{case_id}/conversations", response_model=List[ConversationSummary])
async def list_case_conversations(
    case_id: str,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """특정 사건 내의 모든 대화 세션(Conversation) 목록을 최신 활동순으로 요약 조회한다."""
    records = (
        db.query(ConsultationRecord)
        .filter(ConsultationRecord.case_id == case_id)
        .order_by(ConsultationRecord.created_at.asc())
        .all()
    )

    # conversation_id별로 레코드 그룹화
    conv_groups: Dict[str, List[ConsultationRecord]] = {}
    for r in records:
        cid = r.conversation_id or r.request_id
        if cid not in conv_groups:
            conv_groups[cid] = []
        conv_groups[cid].append(r)

    summaries: List[ConversationSummary] = []
    for cid, items in conv_groups.items():
        first_item = items[0]
        last_item = items[-1]
        summaries.append(
            ConversationSummary(
                conversation_id=cid,
                case_id=case_id,
                first_question=first_item.question,
                last_question=last_item.question,
                last_answer=last_item.answer,
                turns_count=len(items),
                last_status=last_item.status,
                last_answer_status=getattr(last_item, "answer_status", None),
                created_at=get_kst_iso(first_item.created_at) if first_item.created_at else None,
                updated_at=get_kst_iso(last_item.updated_at or last_item.created_at) if last_item.created_at else None,
            )
        )

    # 최신 대화 순으로 정렬
    summaries.sort(key=lambda s: s.updated_at or s.created_at or "", reverse=True)
    return summaries


@router.get("/cases/{case_id}/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_case_conversation_detail(
    case_id: str,
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """특정 대화 세션의 모든 턴(Turn) 질의응답 이력을 시간순으로 상세 조회한다."""
    from ai_legal_helper.rag.source_schema import normalize_source_dict

    records = (
        db.query(ConsultationRecord)
        .filter(
            ConsultationRecord.case_id == case_id,
            ConsultationRecord.conversation_id == conversation_id
        )
        .order_by(ConsultationRecord.created_at.asc(), ConsultationRecord.turn_index.asc())
        .all()
    )

    if not records:
        raise HTTPException(status_code=404, detail="해당 대화 세션을 찾을 수 없습니다.")

    # 권한 검증: 첫 번째 레코드의 user_id 확인
    if not AUTH_BYPASS and records[0].user_id and records[0].user_id != current_user.id:
        raise HTTPException(status_code=403, detail="해당 대화에 접근할 권한이 없습니다.")

    turns: List[ConsultationResponse] = []
    for rec in records:
        sources = []
        seen_keys = set()
        for s in (rec.sources or []):
            std_dict = normalize_source_dict(s)
            key = (std_dict.get("source_id"), std_dict.get("file"), str(std_dict.get("page") or ""))
            if key not in seen_keys:
                seen_keys.add(key)
                sources.append(Source(**std_dict))

        ans_status = _resolve_legacy_answer_status(
            getattr(rec, "answer_status", None),
            getattr(rec, "verification_status", None),
            rec.status,
        )

        turns.append(
            ConsultationResponse(
                request_id=rec.request_id,
                conversation_id=rec.conversation_id,
                turn_index=rec.turn_index or 1,
                trace_id=rec.trace_id or "",
                status=rec.status,
                execution_status=getattr(rec, "execution_status", rec.status) or "COMPLETED",
                verification_status=getattr(rec, "verification_status", None),
                answer_status=ans_status,
                routing_status=getattr(rec, "routing_status", None),
                answer=rec.answer,
                presentation_snapshot=getattr(rec, "presentation_snapshot", None),
                approval_request=rec.approval_request,
                sources=sources,
                elapsed_ms=rec.elapsed_ms,
                warnings=rec.warnings or [],
                verification_result=rec.verification_result or {},
                issue_results=(rec.verification_result or {}).get("issue_results", []),
                verified_facts=(rec.verification_result or {}).get("verified_facts", []),
                missing_evidence=(rec.verification_result or {}).get("missing_evidence", []),
                evidence_citations=(rec.verification_result or {}).get("evidence_citations", []),
                claim_citations=(rec.verification_result or {}).get("claim_citations", []),
                case_delta=(rec.verification_result or {}).get("case_delta"),
                selected_agents=rec.selected_agents or [],
                question=rec.question,
                case_id=rec.case_id,
                created_at=get_kst_iso(rec.created_at) if rec.created_at else None,
            )
        )

    original_sources = {rec.request_id: (rec.sources or []) for rec in records}
    return ConversationDetail(
        conversation_id=conversation_id,
        case_id=case_id,
        turns=[_attach_presentation(turn, source_records=original_sources.get(turn.request_id)) for turn in turns],
    )
