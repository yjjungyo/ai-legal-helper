# -*- coding: utf-8 -*-
"""
증거 관리 API 라우터 (Evidence API Routes)

증거 파일 업로드, 목록 조회, 추출 및 사용자 검토(리뷰)를 위한 REST 엔드포인트를 제공한다.
FastAPI BackgroundTasks를 사용하여 텍스트/AI 추출 작업이 메인 스레드를 블로킹하지 않도록 한다.
"""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import EvidenceDocument, EvidenceClaim, EvidenceSpan, Case, User, AuditLog
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user
from ai_legal_helper.case_intelligence.evidence_ingestion import ingest_evidence, extract_text_from_evidence
from ai_legal_helper.case_intelligence.evidence_extractor import extract_claims_from_evidence
from ai_legal_helper.case_intelligence.evidence_manager import process_evidence_review
from ai_legal_helper.database.graph_sync import safe_sync_case

router = APIRouter(prefix="/cases/{case_id}/evidence", tags=["evidence"])

class ReviewRequest(BaseModel):
    action: str  # APPROVE, EDIT, REJECT
    new_statement: Optional[str] = None
    review_reason: Optional[str] = None

def run_extraction_pipeline(db_gen, doc_id: str):
    """백그라운드에서 텍스트 추출과 AI 추출 파이프라인을 실행한다."""
    db = next(db_gen())
    case_id = None
    try:
        doc = db.query(EvidenceDocument).filter_by(id=doc_id).first()
        case_id = doc.case_id if doc else None
        if extract_text_from_evidence(db, doc_id):
            extract_claims_from_evidence(db, doc_id)
        if case_id:
            from ai_legal_helper.database.graph_sync_worker import queue_sync_task
            queue_sync_task(db, case_id)
            db.commit()
    finally:
        db.close()

@router.post("")
async def upload_evidence(
    request: Request,
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...), 
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """새로운 증거 파일을 업로드하고 백그라운드 추출 작업을 시작한다."""
    doc = await ingest_evidence(db, case.id, file)
    
    audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="UPLOAD_EVIDENCE",
        resource_type="EvidenceDocument",
        resource_id=doc.id,
        result="SUCCESS"
    )
    db.add(audit)
    db.commit()
    
    background_tasks.add_task(run_extraction_pipeline, get_db, doc.id)
    return {"evidence_id": doc.id, "status": doc.status}

@router.get("")
def list_evidence(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """사건에 속한 모든 증거 문서 목록을 조회한다."""
    docs = db.query(EvidenceDocument).filter_by(case_id=case.id).all()
    return [{"id": d.id, "filename": d.original_filename, "status": d.status, "uploaded_at": d.uploaded_at} for d in docs]

@router.get("/{evidence_id}/claims")
def get_evidence_claims(evidence_id: str, case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """특정 증거 문서에서 도출된 주장(Claim) 후보들과 원문(Span) 정보를 반환한다."""
    doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="증거 문서를 찾을 수 없습니다.")
        
    claims = db.query(EvidenceClaim).filter_by(evidence_id=evidence_id).all()
    result = []
    for c in claims:
        spans = c.spans
        result.append({
            "claim_id": c.id,
            "statement": c.statement,
            "status": c.review_status,
            "confidence": c.confidence,
            "spans": [{"span_id": s.id, "text": s.text_excerpt, "page": s.page_number} for s in spans]
        })
    return result

@router.post("/{evidence_id}/claims/{claim_id}/review")
def review_evidence_claim(
    evidence_id: str, 
    claim_id: str, 
    req: ReviewRequest, 
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """
    추출된 주장 후보를 검토(승인/수정/거절)하고 공식 Fact로 편입한다.
    동시성 예외(Optimistic Locking)가 발생할 수 있다.

    P2.4: 커밋 성공 후 백그라운드로 사건 그래프를 재동기화한다(승인/반려가 그래프 근거 관계에 반영됨).
    """
    try:
        # Check if evidence belongs to the case
        doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case.id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="증거 문서를 찾을 수 없습니다.")

        review = process_evidence_review(db, claim_id, req.action, req.new_statement, req.review_reason)
        
        audit = AuditLog(
        actor_user_id=current_user.id,
        event_type=f"REVIEW_CLAIM_{req.action}",
        resource_type="EvidenceClaim",
        resource_id=claim_id,
        result="SUCCESS"
    )
        db.add(audit)
        db.commit()
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="동시 수정이 발생했거나 처리 중 오류가 발생했습니다.")
    return {"status": "SUCCESS", "review_id": review.id}

