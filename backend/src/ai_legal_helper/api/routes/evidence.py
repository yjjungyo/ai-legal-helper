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
from ai_legal_helper.database.models import (
    EvidenceDocument, EvidenceClaim, EvidenceSpan, EvidenceLink,
    Fact, Event, LegalIssue, Case, User, AuditLog
)
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user
from ai_legal_helper.case_intelligence.evidence_ingestion import ingest_evidence, extract_text_from_evidence
from ai_legal_helper.case_intelligence.evidence_extractor import (
    extract_claims_from_evidence, normalize_claim_type, normalize_to_claim_code
)
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
    """사건에 속한 모든 증거 문서 목록을 조회한다.
    
    프론트엔드 호환성을 위해 original_filename과 filename을 함께 제공한다.
    """
    docs = db.query(EvidenceDocument).filter_by(case_id=case.id).order_by(EvidenceDocument.uploaded_at.desc()).all()
    return [
        {
            "id": d.id,
            "filename": d.original_filename,
            "original_filename": d.original_filename,
            "media_type": d.media_type,
            "size_bytes": d.size_bytes,
            "status": d.status,
            "uploaded_at": d.uploaded_at,
            "created_at": d.uploaded_at
        }
        for d in docs
    ]

@router.get("/conflicts")
def get_evidence_conflicts(
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """사건 내 증거들 간의 상충 및 모순(충돌 후보) 목록을 조회한다.

    1. RDB EvidenceLink의 CONTRADICTS 관계 조회
    2. EvidenceClaim 중 상충 후보(CONTRADICTION_CANDIDATE / CONTRADICTION) 조회
    3. Neo4j GraphRAG의 find_contradictions 조회 (가능한 경우)

    Args:
        case (Case): 현재 로그인 사용자가 접근 권한을 가진 사건 엔티티.
        db (Session): 데이터베이스 세션.

    Returns:
        dict: {"conflicts": List[Dict]} 형태의 충돌 후보 목록.
    """
    conflicts = []
    seen_keys = set()

    # 1. RDB EvidenceLink (link_type == 'CONTRADICTS')
    links = (
        db.query(EvidenceLink)
        .join(EvidenceDocument, EvidenceLink.evidence_id == EvidenceDocument.id)
        .filter(EvidenceDocument.case_id == case.id, EvidenceLink.link_type == "CONTRADICTS")
        .all()
    )
    for link in links:
        doc = db.query(EvidenceDocument).filter_by(id=link.evidence_id).first()
        claim = db.query(EvidenceClaim).filter_by(id=link.claim_id).first() if link.claim_id else None

        target_desc = f"{link.target_type}:{link.target_id}"
        if link.target_type == "FACT":
            fact = db.query(Fact).filter_by(id=link.target_id).first()
            if fact:
                target_desc = f"사실 '{fact.statement}'"
        elif link.target_type == "EVENT":
            evt = db.query(Event).filter_by(id=link.target_id).first()
            if evt:
                target_desc = f"이벤트 '{evt.title}'"
        elif link.target_type == "LEGAL_ISSUE":
            issue = db.query(LegalIssue).filter_by(id=link.target_id).first()
            if issue:
                target_desc = f"쟁점 '{issue.title}'"

        item_key = f"link:{link.id}"
        seen_keys.add(item_key)
        conflicts.append({
            "conflict_id": link.id,
            "type": "LINK_CONTRADICTION",
            "evidence_id": link.evidence_id,
            "document_name": doc.original_filename if doc else None,
            "claim_statement": claim.statement if claim else None,
            "target_type": link.target_type,
            "target_id": link.target_id,
            "target_description": target_desc,
            "description": f"증거 주장 '{claim.statement if claim else ''}'이(가) {target_desc}와(과) 상충됩니다."
        })

    # 2. EvidenceClaim 중 상충 후보(CONTRADICTION_CANDIDATE 또는 CONTRADICTION)
    cand_claims = (
        db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == case.id,
            (EvidenceClaim.assertion_status == "CONTRADICTION_CANDIDATE") | (EvidenceClaim.claim_type == "CONTRADICTION")
        )
        .all()
    )
    for c in cand_claims:
        doc = db.query(EvidenceDocument).filter_by(id=c.evidence_id).first()
        item_key = f"claim:{c.id}"
        if item_key not in seen_keys:
            seen_keys.add(item_key)
            conflicts.append({
                "conflict_id": c.id,
                "type": "CLAIM_CONTRADICTION",
                "evidence_id": c.evidence_id,
                "document_name": doc.original_filename if doc else None,
                "claim_statement": c.statement,
                "confidence": c.confidence,
                "description": f"문서 '{doc.original_filename if doc else ''}'에서 상충 가능성이 있는 사실관계가 발견되었습니다: {c.statement}"
            })

    # 3. Neo4j GraphRAG (가능한 경우 보강: GraphRAGRetriever와 Neo4j 드라이버를 통해 상충 관계 조회)
    try:
        from ai_legal_helper.database.neo4j import get_neo4j_driver
        from ai_legal_helper.rag.graph_rag import GraphRAGRetriever

        driver = get_neo4j_driver()
        if driver:
            grag = GraphRAGRetriever(driver)
            g_conflicts = grag.find_contradictions(case.id)
            for gc in g_conflicts:
                item_key = f"graph:{gc.get('contradicting_id')}:{gc.get('target_id')}"
                if item_key not in seen_keys:
                    seen_keys.add(item_key)
                    conflicts.append({
                        "conflict_id": gc.get("contradicting_id"),
                        "type": "GRAPH_CONTRADICTION",
                        "target_type": gc.get("target_type"),
                        "target_id": gc.get("target_id"),
                        "target_description": gc.get("target_content"),
                        "supporting_claim_ids": gc.get("supporting_claim_ids", []),
                        "description": f"그래프 분석 상 충돌: {gc.get('target_content')}"
                    })
    except Exception:
        pass

    return {"conflicts": conflicts}

@router.post("/{evidence_id}/extract")
def trigger_evidence_extraction(
    evidence_id: str,
    background_tasks: BackgroundTasks,
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """지정된 증거 문서에 대해 텍스트 및 AI 사실 추출(또는 재추출) 작업을 백그라운드로 실행한다.

    Args:
        evidence_id (str): 추출 작업을 수행할 증거 문서의 UUID.
        background_tasks (BackgroundTasks): FastAPI 비동기 백그라운드 태스크 러너.
        case (Case): 현재 로그인 사용자가 접근 권한을 가진 사건 엔티티.
        db (Session): 데이터베이스 세션.

    Returns:
        dict: 작업 성공 여부, 대상 증거 ID 및 안내 메시지.

    Raises:
        HTTPException: 해당 증거 문서를 찾을 수 없는 경우 404 상태 코드 반환.
    """
    doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="증거 문서를 찾을 수 없습니다.")

    doc.status = "EXTRACTING"
    doc.error_code = None
    db.commit()

    background_tasks.add_task(run_extraction_pipeline, get_db, doc.id)
    return {
        "status": "SUCCESS",
        "evidence_id": doc.id,
        "message": "추출 작업이 시작되었습니다."
    }

@router.get("/{evidence_id}/claims")
def get_evidence_claims(evidence_id: str, case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """특정 증거 문서에서 도출된 주장(Claim) 후보들과 원문(Span) 정보를 반환한다.

    프론트엔드 인터페이스(EvidenceClaim, EvidenceSpan)와의 호환성을 위해 
    표준 필드명(id, claim_type, review_status, text_excerpt, page_number 등)과 
    기존 필드명(claim_id, status, text, page)을 함께 제공한다.
    """
    doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="증거 문서를 찾을 수 없습니다.")
        
    claims = db.query(EvidenceClaim).filter_by(evidence_id=evidence_id).all()
    result = []
    for c in claims:
        spans = c.spans
        result.append({
            "id": c.id,
            "claim_id": c.id,
            "statement": c.statement,
            "claim_type": normalize_to_claim_code(c.claim_type),
            "assertion_status": c.assertion_status,
            "review_status": c.review_status,
            "status": c.review_status,
            "confidence": c.confidence,
            "spans": [
                {
                    "id": s.id,
                    "span_id": s.id,
                    "text_excerpt": s.text_excerpt,
                    "text": s.text_excerpt,
                    "page_number": s.page_number,
                    "page": s.page_number,
                    "paragraph_index": s.paragraph_index,
                }
                for s in spans
            ]
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

@router.delete("/{evidence_id}")
def delete_evidence(
    evidence_id: str,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """사건에 등록된 증거 문서 및 관련 추출 데이터를 삭제한다.

    1. 증거 문서 및 물리 파일 삭제
    2. 해당 증거 문서에 근거하여 공식 승격된 사건 Fact 레코드 연쇄 삭제
    3. 데이터베이스 레코드 삭제 (Cascade를 통해 Claim, Span, Link 자동 삭제)
    4. 사건 그래프 재동기화 작업 큐 등록
    """
    import os
    from ai_legal_helper.case_intelligence.evidence_ingestion import get_storage_dir
    from ai_legal_helper.database.graph_sync_worker import queue_sync_task

    doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="삭제할 증거 문서를 찾을 수 없습니다.")

    # 1. 물리 파일 삭제
    if doc.safe_storage_key:
        storage_dir = get_storage_dir()
        file_path = os.path.join(storage_dir, doc.safe_storage_key)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

    # 2. 해당 증거 문서에 근거하여 공식 승격되었던 사건 Fact 조회 및 일괄 삭제
    fact_ids_from_links = [
        link.target_id
        for link in db.query(EvidenceLink).filter_by(evidence_id=evidence_id, target_type="FACT").all()
    ]
    facts_to_delete = (
        db.query(Fact)
        .filter(
            (Fact.case_id == case.id) &
            ((Fact.source_ref == evidence_id) | (Fact.id.in_(fact_ids_from_links)))
        )
        .all()
    )
    for fact in facts_to_delete:
        db.delete(fact)

    doc_filename = doc.original_filename
    db.delete(doc)

    audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="DELETE_EVIDENCE",
        resource_type="EvidenceDocument",
        resource_id=evidence_id,
        result="SUCCESS"
    )
    db.add(audit)
    queue_sync_task(db, case.id)
    db.commit()

    return {"status": "SUCCESS", "deleted_id": evidence_id, "filename": doc_filename}

