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
from ai_legal_helper.case_intelligence.conflict_detector import (
    build_structured_slots,
    evaluate_claim_against_fact,
    evaluate_claim_conflicts,
)
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
    """사건 내 증거들 간의 검증된 상충 및 모순 목록을 중복 없이 조회한다.

    1. RDB EvidenceLink의 CONTRADICTS 관계를 3단계 상충 탐지 엔진으로 검증하여 조회
    2. EvidenceClaim 중 미연결 상충 후보(CONTRADICTION_CANDIDATE)를 검증하여 조회
    3. Neo4j GraphRAG의 find_contradictions 결과를 PostgreSQL 원본과 대조 및 중복 제거하여 통합
    4. 반려(REJECTED)된 주장은 제외하며, (claim_id, target_id) 기준으로 단일화한다.

    Args:
        case (Case): 현재 로그인 사용자가 접근 권한을 가진 사건 엔티티.
        db (Session): 데이터베이스 세션.

    Returns:
        dict: {"conflicts": List[Dict]} 형태의 검증된 상충 목록.
    """
    conflicts = []
    seen_pairs = set()
    seen_claim_ids = set()

    case_docs = db.query(EvidenceDocument).filter_by(case_id=case.id).all()
    doc_map = {d.id: d for d in case_docs}
    case_facts = db.query(Fact).filter_by(case_id=case.id).all()
    fact_map = {f.id: f for f in case_facts}
    fact_doc_names = {
        f.id: doc_map[f.source_ref].original_filename
        for f in case_facts
        if f.source_ref and f.source_ref in doc_map
    }

    # 1. RDB EvidenceLink (link_type == 'CONTRADICTS')
    links = (
        db.query(EvidenceLink)
        .join(EvidenceDocument, EvidenceLink.evidence_id == EvidenceDocument.id)
        .filter(EvidenceDocument.case_id == case.id, EvidenceLink.link_type == "CONTRADICTS")
        .all()
    )
    for link in links:
        doc = doc_map.get(link.evidence_id)
        claim = db.query(EvidenceClaim).filter_by(id=link.claim_id).first() if link.claim_id else None
        if claim and claim.review_status == "REJECTED":
            continue

        target_desc = f"{link.target_type}:{link.target_id}"
        target_doc_name = None
        reason_code = "VERIFIED_LINK_CONFLICT"
        explanation = None

        if link.target_type == "FACT":
            fact = fact_map.get(link.target_id)
            if not fact:
                continue
            target_desc = fact.statement
            target_doc_name = fact_doc_names.get(fact.id)
            if claim:
                claim_slots = build_structured_slots(
                    statement=claim.statement or "",
                    claim_type=claim.claim_type,
                    evidence_id=claim.evidence_id,
                    document_name=doc.original_filename if doc else None,
                )
                decision = evaluate_claim_against_fact(
                    claim_slots=claim_slots,
                    fact=fact,
                    fact_doc_name=target_doc_name,
                    claim_id=claim.id,
                    enable_llm_verification=False,
                )
                if decision.status != "CONTRADICTION":
                    continue
                reason_code = decision.reason_code
                explanation = decision.explanation
        elif link.target_type == "EVENT":
            evt = db.query(Event).filter_by(id=link.target_id).first()
            if evt:
                target_desc = f"이벤트 '{evt.title}'"
        elif link.target_type == "LEGAL_ISSUE":
            issue = db.query(LegalIssue).filter_by(id=link.target_id).first()
            if issue:
                target_desc = f"쟁점 '{issue.title}'"

        pair_key = (link.claim_id or f"link:{link.id}", link.target_id)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        if link.claim_id:
            seen_claim_ids.add(link.claim_id)

        default_desc = f"증거 주장 '{claim.statement if claim else ''}'이(가) 기존 사실 '{target_desc}'와(과) 상충됩니다."
        conflicts.append({
            "conflict_id": link.id,
            "type": "LINK_CONTRADICTION",
            "status": "CONTRADICTION",
            "reason_code": reason_code,
            "evidence_id": link.evidence_id,
            "document_name": doc.original_filename if doc else None,
            "claim_id": link.claim_id,
            "claim_statement": claim.statement if claim else None,
            "target_type": link.target_type,
            "target_id": link.target_id,
            "target_description": target_desc,
            "target_document_name": target_doc_name,
            "explanation": explanation or default_desc,
            "description": explanation or default_desc,
        })

    # 2. EvidenceClaim 중 상충 후보(CONTRADICTION_CANDIDATE 또는 CONTRADICTION)
    cand_claims = (
        db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == case.id,
            EvidenceClaim.review_status != "REJECTED",
            (EvidenceClaim.assertion_status == "CONTRADICTION_CANDIDATE") | (EvidenceClaim.claim_type == "CONTRADICTION")
        )
        .all()
    )
    for c in cand_claims:
        if c.id in seen_claim_ids:
            continue
        doc = doc_map.get(c.evidence_id)
        other_facts = [
            f
            for f in case_facts
            if not (f.source_ref == c.evidence_id and (f.statement or "").strip() == (c.statement or "").strip())
        ]
        eval_res = evaluate_claim_conflicts(
            statement=c.statement or "",
            existing_facts=other_facts,
            claim_type=c.claim_type,
            evidence_id=c.evidence_id,
            document_name=doc.original_filename if doc else None,
            claim_id=c.id,
            fact_doc_names=fact_doc_names,
            enable_llm_verification=False,
        )
        for decision in eval_res["contradictions"]:
            pair_key = (c.id, decision.target_fact_id)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            seen_claim_ids.add(c.id)
            target_fact = fact_map.get(decision.target_fact_id)
            target_desc = target_fact.statement if target_fact else decision.target_fact_id
            target_doc_name = fact_doc_names.get(decision.target_fact_id)
            conflicts.append({
                "conflict_id": c.id,
                "type": "CLAIM_CONTRADICTION",
                "status": "CONTRADICTION",
                "reason_code": decision.reason_code,
                "evidence_id": c.evidence_id,
                "document_name": doc.original_filename if doc else None,
                "claim_id": c.id,
                "claim_statement": c.statement,
                "target_type": "FACT",
                "target_id": decision.target_fact_id,
                "target_description": target_desc,
                "target_document_name": target_doc_name,
                "confidence": c.confidence,
                "explanation": decision.explanation,
                "description": decision.explanation,
            })

    # 3. Neo4j GraphRAG (PostgreSQL 원본 대조 및 중복 제거 후 보강)
    try:
        from ai_legal_helper.database.neo4j import get_neo4j_driver
        from ai_legal_helper.rag.graph_rag import GraphRAGRetriever

        driver = get_neo4j_driver()
        if driver:
            grag = GraphRAGRetriever(driver)
            g_conflicts = grag.find_contradictions(case.id)
            for gc in g_conflicts:
                c_id = gc.get("contradicting_id")
                t_id = gc.get("target_id")
                pair_key = (c_id or "", t_id or "")
                if pair_key in seen_pairs or (c_id and c_id in seen_claim_ids):
                    continue
                claim = db.query(EvidenceClaim).filter_by(id=c_id, case_id=case.id).first() if c_id else None
                if not claim or claim.review_status == "REJECTED":
                    continue
                fact = fact_map.get(t_id) if t_id else None
                if not fact:
                    continue
                doc = doc_map.get(claim.evidence_id)
                claim_slots = build_structured_slots(
                    statement=claim.statement or "",
                    claim_type=claim.claim_type,
                    evidence_id=claim.evidence_id,
                    document_name=doc.original_filename if doc else None,
                )
                decision = evaluate_claim_against_fact(
                    claim_slots=claim_slots,
                    fact=fact,
                    fact_doc_name=fact_doc_names.get(fact.id),
                    claim_id=claim.id,
                    enable_llm_verification=False,
                )
                if decision.status != "CONTRADICTION":
                    continue
                seen_pairs.add(pair_key)
                seen_claim_ids.add(claim.id)
                conflicts.append({
                    "conflict_id": c_id,
                    "type": "GRAPH_CONTRADICTION",
                    "status": "CONTRADICTION",
                    "reason_code": decision.reason_code,
                    "evidence_id": claim.evidence_id,
                    "document_name": doc.original_filename if doc else None,
                    "claim_id": claim.id,
                    "claim_statement": claim.statement,
                    "target_type": gc.get("target_type") or "FACT",
                    "target_id": t_id,
                    "target_description": fact.statement,
                    "target_document_name": fact_doc_names.get(fact.id),
                    "supporting_claim_ids": gc.get("supporting_claim_ids", []),
                    "explanation": decision.explanation,
                    "description": decision.explanation,
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

