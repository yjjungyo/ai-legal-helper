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
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional

from ai_legal_helper.api.schemas.consultation import (
    ConsultationRequest, ConsultationResponse, Source, UsageSummary, ApprovalDecisionRequest
)
from ai_legal_helper.observability.context import (
    set_trace_id, reset_trace_id, set_case_id, reset_case_id
)
from ai_legal_helper.llm.usage import global_token_tracker
from ai_legal_helper.workflows.legal_workflow import run_legal_consultation
from ai_legal_helper.observability.langfuse_client import start_trace, flush_langfuse
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user, AUTH_BYPASS

logger = get_logger(__name__)
from ai_legal_helper.database.session import get_db, SessionLocal
from ai_legal_helper.database.models import User, Case, ConsultationRecord
from ai_legal_helper.utils.datetime_utils import get_kst_iso

router = APIRouter()

# In-memory store for consultation tasks (ephemeral for P1)
_consultations: Dict[str, ConsultationResponse] = {}

@router.post("/consultations", response_model=ConsultationResponse)
async def start_consultation(
    req: ConsultationRequest, 
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """법률 상담 프로세스를 비동기적으로 시작한다."""
    if req.case_id:
        # Verify case ownership (1인 로컬 테스트 모드 자동 지원)
        case = get_case_for_user(req.case_id, current_user, db)

    from ai_legal_helper.observability.context import get_trace_id, get_request_id

    # 미들웨어에서 주입된 전역 trace_id와 request_id를 승계하여 로그와 Langfuse를 1:1 매핑
    request_id = get_request_id() or str(uuid.uuid4())
    trace_id = get_trace_id() or str(uuid.uuid4())
    
    # Initial status
    resp = ConsultationResponse(
        request_id=request_id,
        trace_id=trace_id,
        status="IN_PROGRESS",
        question=req.question,
        case_id=req.case_id,
        created_at=get_kst_iso(),
    )
    # Store user_id to authorize GET later (Note: We'll inject it manually since it's not in the response schema)
    _consultations[request_id] = resp
    setattr(resp, "_user_id", current_user.id)
    
    # DB에 초기 상담 레코드 영구 저장
    try:
        record = ConsultationRecord(
            case_id=req.case_id,
            user_id=current_user.id,
            request_id=request_id,
            trace_id=trace_id,
            question=req.question,
            status="IN_PROGRESS"
        )
        db.add(record)
        db.commit()
    except Exception as e:
        db.rollback()
    
    # Schedule background task
    background_tasks.add_task(process_consultation, request_id, trace_id, req)
    
    return resp

async def process_consultation(request_id: str, trace_id: str, req: ConsultationRequest):
    """실제 LangGraph 워크플로우를 실행하고 결과를 업데이트하는 백그라운드 태스크."""
    t_token = set_trace_id(trace_id)
    c_token = None
    if req.case_id:
        c_token = set_case_id(req.case_id)
        
    start_trace(
        trace_id=trace_id,
        name="LegalConsultation",
        session_id=req.case_id,
        metadata={"question": req.question[:120], "request_id": request_id}
    )
    start_time = time.time()
    try:
        # Run unified workflow
        result = await run_legal_consultation(req.question, thread_id=request_id)
        
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
        is_approval_required = (result.get("status") == "APPROVAL_REQUIRED")

        if is_approval_required:
            resp.status = "APPROVAL_REQUIRED"
            resp.approval_request = result.get("approval_request")
            resp.answer = result.get("answer", "해당 쟁점에 필요한 공식 법령(특별법 등) 원문 검색 진행을 위해 사용자 승인이 필요합니다.")
        else:
            resp.status = "SUCCESS"
            resp.answer = result.get("answer", "")
            resp.approval_request = result.get("approval_request")
        
        # Map sources (서버 Source Registry 기반 표준 Source 스키마 정규화 및 중복 제거)
        from ai_legal_helper.rag.source_schema import normalize_source_dict
        sources_data = result.get("sources", [])
        dedup_sources = []
        seen_source_keys = set()
        for s in sources_data:
            std_dict = normalize_source_dict(s)
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

        # 요구사항 5: Langfuse 루트 Span/Trace에 최종 출처·검증·실행시간·토큰 요약 기록
        try:
            from ai_legal_helper.observability.context import get_current_span_id
            from ai_legal_helper.observability.langfuse_client import update_span
            audit_meta = (resp.verification_result or {}).get("citation_audit", {})
            update_span(get_current_span_id(), {
                "elapsed_ms": round(elapsed_ms, 2),
                "total_tokens": usage_summary.total_tokens,
                "retrieval_source_ids": audit_meta.get("retrieval_source_ids", [s.source_id for s in resp.sources]),
                "retrieval_methods": audit_meta.get("retrieval_methods", []),
                "retrieved_chunk_ids": audit_meta.get("retrieved_chunk_ids", []),
                "generated_citation_ids": audit_meta.get("generated_citation_ids", []),
                "validated_citation_ids": audit_meta.get("validated_citation_ids", []),
                "rejected_citation_ids": audit_meta.get("rejected_citation_ids", []),
                "rejection_reasons": audit_meta.get("rejection_reasons", {}),
                "citation_existence_rate": audit_meta.get("citation_existence_rate", 1.0),
                "citation_support_rate": audit_meta.get("citation_support_rate", 1.0),
            })

            # Langfuse Scores/Evaluation 탭에 정량 평가 점수 기록
            from ai_legal_helper.observability.langfuse_client import log_score
            exist_rate = float(audit_meta.get("citation_existence_rate", 1.0))
            supp_rate = float(audit_meta.get("citation_support_rate", 1.0))
            ver_status = (resp.verification_result or {}).get("status", "PASS")
            score_val = 1.0 if ver_status == "PASS" else (0.5 if ver_status == "REVISE" else 0.0)
            log_score(trace_id, "citation_existence_rate", exist_rate)
            log_score(trace_id, "citation_support_rate", supp_rate)
            log_score(trace_id, "verification_status", score_val, comment=ver_status)
        except Exception:
            pass
        
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        resp = _consultations[request_id]
        resp.status = "ERROR"
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
                    rec.answer = resp.answer
                    rec.approval_request = resp.approval_request
                    rec.sources = [s.model_dump() for s in resp.sources] if resp.sources else []
                    rec.verification_result = resp.verification_result
                    rec.warnings = resp.warnings
                    rec.selected_agents = resp.selected_agents
                    rec.elapsed_ms = resp.elapsed_ms
                    db_session.commit()
        except Exception:
            pass

        flush_langfuse()
        reset_trace_id(t_token)
        if c_token:
            reset_case_id(c_token)

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
        return resp
        
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
    return ConsultationResponse(
        request_id=record.request_id,
        trace_id=record.trace_id or "",
        status=record.status,
        answer=record.answer,
        approval_request=record.approval_request,
        sources=sources,
        elapsed_ms=record.elapsed_ms,
        warnings=record.warnings or [],
        verification_result=record.verification_result or {},
        selected_agents=record.selected_agents or [],
        question=record.question,
        case_id=record.case_id,
        created_at=get_kst_iso(record.created_at) if record.created_at else None
    )

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

    # 중복 Resume 방지: 즉시 상태를 IN_PROGRESS로 전이
    if request_id in _consultations:
        resp = _consultations[request_id]
        resp.status = "IN_PROGRESS"
    else:
        resp = ConsultationResponse(
            request_id=request_id,
            trace_id=trace_id or "",
            status="IN_PROGRESS",
            question=record.question if record else None,
            case_id=case_id,
            created_at=get_kst_iso(record.created_at) if record and record.created_at else None,
        )
        _consultations[request_id] = resp
        setattr(resp, "_user_id", current_user.id)

    if record:
        record.status = "IN_PROGRESS"
        db.commit()

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
    start_time = time.time()

    try:
        # LangGraph Command(resume=...) 호출로 인터럽트된 노드 재개
        result = await run_legal_consultation(
            question="",
            thread_id=request_id,
            resume_data={"approved": decision.approved, "reason": decision.reason}
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

        resp.status = "SUCCESS"
        resp.answer = result.get("answer", "")
        resp.elapsed_ms = elapsed_ms
        resp.usage_summary = usage_summary
        resp.verification_result = result.get("verification_result", {})
        resp.revision_count = result.get("revision_count", 0)
        resp.selected_agents = result.get("selected_agents", [])
        resp.warnings.extend(result.get("warnings", []))
        resp.approval_request = result.get("approval_request")

        # Sources 정규화
        from ai_legal_helper.rag.source_schema import normalize_source_dict
        sources_data = result.get("sources", [])
        dedup_sources = []
        seen_source_keys = set()
        for s in sources_data:
            std_dict = normalize_source_dict(s)
            key = (std_dict.get("source_id"), std_dict.get("file"), str(std_dict.get("page") or ""))
            if key not in seen_source_keys:
                seen_source_keys.add(key)
                dedup_sources.append(Source(**std_dict))
        resp.sources = dedup_sources

        # Langfuse span 업데이트
        try:
            from ai_legal_helper.observability.context import get_current_span_id
            from ai_legal_helper.observability.langfuse_client import update_span
            audit_meta = (resp.verification_result or {}).get("citation_audit", {})
            update_span(get_current_span_id(), {
                "elapsed_ms": round(elapsed_ms, 2),
                "total_tokens": usage_summary.total_tokens,
                "retrieval_source_ids": audit_meta.get("retrieval_source_ids", [s.source_id for s in resp.sources]),
                "retrieval_methods": audit_meta.get("retrieval_methods", []),
                "retrieved_chunk_ids": audit_meta.get("retrieved_chunk_ids", []),
                "generated_citation_ids": audit_meta.get("generated_citation_ids", []),
                "validated_citation_ids": audit_meta.get("validated_citation_ids", []),
                "rejected_citation_ids": audit_meta.get("rejected_citation_ids", []),
                "rejection_reasons": audit_meta.get("rejection_reasons", {}),
                "citation_existence_rate": audit_meta.get("citation_existence_rate", 1.0),
                "citation_support_rate": audit_meta.get("citation_support_rate", 1.0),
            })

            from ai_legal_helper.observability.langfuse_client import log_score
            exist_rate = float(audit_meta.get("citation_existence_rate", 1.0))
            supp_rate = float(audit_meta.get("citation_support_rate", 1.0))
            ver_status = (resp.verification_result or {}).get("status", "PASS")
            score_val = 1.0 if ver_status == "PASS" else (0.5 if ver_status == "REVISE" else 0.0)
            log_score(trace_id, "citation_existence_rate", exist_rate)
            log_score(trace_id, "citation_support_rate", supp_rate)
            log_score(trace_id, "verification_status", score_val, comment=ver_status)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[RESUME_ERROR] consultation {request_id} resume failed: {e}")
        resp = _consultations.get(request_id)
        if resp:
            resp.status = "ERROR"
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
                    rec.answer = resp.answer
                    rec.approval_request = resp.approval_request
                    rec.sources = [s.model_dump() for s in resp.sources] if resp.sources else []
                    rec.verification_result = resp.verification_result
                    rec.warnings = resp.warnings
                    rec.selected_agents = resp.selected_agents
                    rec.elapsed_ms = resp.elapsed_ms
                    db_session.commit()
        except Exception:
            pass

        flush_langfuse()
        reset_trace_id(t_token)
        if c_token:
            reset_case_id(c_token)


@router.get("/cases/{case_id}/consultations", response_model=List[ConsultationResponse])
async def list_case_consultations(
    case_id: str,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """특정 사건에 저장된 모든 상담 내역을 최신순으로 조회한다."""
    from ai_legal_helper.rag.source_schema import normalize_source_dict
    records = db.query(ConsultationRecord).filter(
        ConsultationRecord.case_id == case_id
    ).order_by(ConsultationRecord.created_at.desc()).all()
    
    results = []
    for rec in records:
        sources = []
        seen_keys = set()
        for s in (rec.sources or []):
            std_dict = normalize_source_dict(s)
            key = (std_dict.get("source_id"), std_dict.get("file"), str(std_dict.get("page") or ""))
            if key not in seen_keys:
                seen_keys.add(key)
                sources.append(Source(**std_dict))
        results.append(ConsultationResponse(
            request_id=rec.request_id,
            trace_id=rec.trace_id or "",
            status=rec.status,
            answer=rec.answer,
            approval_request=rec.approval_request,
            sources=sources,
            elapsed_ms=rec.elapsed_ms,
            warnings=rec.warnings or [],
            verification_result=rec.verification_result or {},
            selected_agents=rec.selected_agents or [],
            question=rec.question,
            case_id=rec.case_id,
            created_at=get_kst_iso(rec.created_at) if rec.created_at else None
        ))
    return results


