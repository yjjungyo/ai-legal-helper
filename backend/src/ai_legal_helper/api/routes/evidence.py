# -*- coding: utf-8 -*-
"""
증거 관리 API 라우터 (Evidence API Routes)

증거 파일 업로드, 목록 조회, 추출, 상충 조회 및 사용자 검토(리뷰)를 위한 REST 엔드포인트를 제공한다.
FastAPI BackgroundTasks를 사용하여 텍스트/AI 추출 작업이 메인 스레드를 블로킹하지 않도록 한다.
"""

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import (
    EvidenceDocument,
    EvidenceClaim,
    EvidenceSpan,
    EvidenceLink,
    Fact,
    Event,
    LegalIssue,
    Case,
    User,
    AuditLog,
    EvidenceAssessment,
    FactAdjudication,
    EvidenceGap,
    FactComparisonAudit,
)
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user
from ai_legal_helper.case_intelligence.evidence_ingestion import ingest_evidence, extract_text_from_evidence
from ai_legal_helper.case_intelligence.evidence_extractor import (
    extract_claims_from_evidence,
    normalize_claim_type,
    normalize_to_claim_code,
)
from ai_legal_helper.case_intelligence.evidence_manager import (
    process_evidence_review,
    sync_evidence_document_status,
    _prune_deleted_fact_references,
    _recalculate_case_disputed_facts,
    _rebuild_case_timeline,
)
from ai_legal_helper.case_intelligence.conflict_detector import (
    build_structured_slots,
    evaluate_claim_against_fact,
    evaluate_claim_conflicts,
)
from ai_legal_helper.database.graph_sync import safe_sync_case

router = APIRouter(prefix="/cases/{case_id}/evidence", tags=["evidence"])


class ReviewRequest(BaseModel):
    """증거 주장(Claim) 검토 요청 스키마."""
    action: str  # APPROVE, EDIT, REJECT
    new_statement: Optional[str] = None
    review_reason: Optional[str] = None


def _extract_primary_span_info(claim: Optional[EvidenceClaim]) -> Dict[str, Any]:
    """Claim에 연결된 첫 번째 원문 Span 위치 정보를 반환한다."""
    if not claim or not claim.spans:
        return {
            "span_id": None,
            "page_number": None,
            "paragraph_index": None,
            "text_excerpt": None,
        }
    first_span = claim.spans[0]
    return {
        "span_id": first_span.id,
        "page_number": first_span.page_number,
        "paragraph_index": first_span.paragraph_index,
        "text_excerpt": first_span.text_excerpt,
    }


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
    db: Session = Depends(get_db),
):
    """새로운 증거 파일을 업로드하고 백그라운드 추출 작업을 시작한다."""
    doc = await ingest_evidence(db, case.id, file)

    audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="UPLOAD_EVIDENCE",
        resource_type="EvidenceDocument",
        resource_id=doc.id,
        result="SUCCESS",
    )
    db.add(audit)
    db.commit()

    background_tasks.add_task(run_extraction_pipeline, get_db, doc.id)
    return {"evidence_id": doc.id, "status": doc.status}


@router.get("")
def list_evidence(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """사건에 속한 모든 증거 문서 목록을 조회한다.

    각 문서에 속한 EvidenceClaim의 검토 상태(PENDING 잔여 여부)와 EvidenceDocument.status가
    불일치하는 경우(예: 모든 Claim이 승인되었으나 문서 상태가 REVIEW_REQUIRED로 남아 있는 경우)
    자동으로 APPROVED 상태로 동기화하여 반환한다.
    """
    docs = (
        db.query(EvidenceDocument)
        .filter_by(case_id=case.id)
        .order_by(EvidenceDocument.uploaded_at.desc())
        .all()
    )
    status_changed = False
    for d in docs:
        prev_st = d.status
        new_st = sync_evidence_document_status(db, d.id)
        if new_st != prev_st:
            status_changed = True
    if status_changed:
        db.commit()

    return [
        {
            "id": d.id,
            "filename": d.original_filename,
            "original_filename": d.original_filename,
            "media_type": d.media_type,
            "size_bytes": d.size_bytes,
            "status": d.status,
            "uploaded_at": d.uploaded_at,
            "created_at": d.uploaded_at,
        }
        for d in docs
    ]


@router.get("/conflicts")
def get_evidence_conflicts(
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건 내 증거들 간의 검증된 확정 상충(CONTRADICTION) 및 잠재 상충(POTENTIAL_CONFLICT) 목록을 중복 없이 조회한다.

    1. RDB EvidenceLink의 CONTRADICTS 및 POTENTIAL_CONFLICT 관계를 3단계 상충 탐지 엔진으로 검증하여 조회
    2. EvidenceClaim 중 미연결 상충 후보(CONTRADICTION_CANDIDATE)를 검증하여 조회
    3. Neo4j GraphRAG의 find_contradictions 결과를 PostgreSQL 원본과 대조 및 중복 제거하여 통합
    4. 반려(REJECTED)된 주장은 제외하며, (claim_id, target_id) 기준으로 단일화하고 원문 Span 위치 정보를 함께 반환한다.

    Args:
        case (Case): 현재 로그인 사용자가 접근 권한을 가진 사건 엔티티.
        db (Session): 데이터베이스 세션.

    Returns:
        dict: conflicts(전체), contradictions(확정 상충), potential_conflicts(잠재 상충) 및 건수 요약.
    """
    conflicts: List[Dict[str, Any]] = []
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

    # 1. RDB EvidenceLink (link_type in ('CONTRADICTS', 'POTENTIAL_CONFLICT'))
    links = (
        db.query(EvidenceLink)
        .join(EvidenceDocument, EvidenceLink.evidence_id == EvidenceDocument.id)
        .filter(
            EvidenceDocument.case_id == case.id,
            EvidenceLink.link_type.in_(["CONTRADICTS", "POTENTIAL_CONFLICT"]),
        )
        .all()
    )
    for link in links:
        doc = doc_map.get(link.evidence_id)
        claim = db.query(EvidenceClaim).filter_by(id=link.claim_id).first() if link.claim_id else None
        if claim and claim.review_status == "REJECTED":
            continue

        target_desc = f"{link.target_type}:{link.target_id}"
        target_doc_name = None
        conflict_status = "CONTRADICTION" if link.link_type == "CONTRADICTS" else "POTENTIAL_CONFLICT"
        reason_code = "VERIFIED_LINK_CONFLICT" if conflict_status == "CONTRADICTION" else "POTENTIAL_LINK_CONFLICT"
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
                    subject=claim.subject_key,
                    predicate=claim.predicate_key,
                    scope=claim.scope,
                    temporal_context=claim.temporal_context,
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
                if decision.status not in ("CONTRADICTION", "POTENTIAL_CONFLICT"):
                    continue
                conflict_status = decision.status
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

        span_info = _extract_primary_span_info(claim)
        default_desc = (
            f"증거 주장 '{claim.statement if claim else ''}'이(가) 기존 사실 '{target_desc}'와(과) "
            f"{'상충됩니다.' if conflict_status == 'CONTRADICTION' else '추가 사실 확인이 필요합니다.'}"
        )
        conflicts.append({
            "conflict_id": link.id,
            "type": "LINK_CONTRADICTION" if conflict_status == "CONTRADICTION" else "LINK_POTENTIAL_CONFLICT",
            "status": conflict_status,
            "reason_code": reason_code,
            "evidence_id": link.evidence_id,
            "document_name": doc.original_filename if doc else None,
            "claim_id": link.claim_id,
            "claim_statement": claim.statement if claim else None,
            "span_id": span_info["span_id"],
            "page_number": span_info["page_number"],
            "paragraph_index": span_info["paragraph_index"],
            "text_excerpt": span_info["text_excerpt"],
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
            (EvidenceClaim.assertion_status == "CONTRADICTION_CANDIDATE")
            | (EvidenceClaim.claim_type == "CONTRADICTION"),
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
            subject=c.subject_key,
            predicate=c.predicate_key,
            scope=c.scope,
            temporal_context=c.temporal_context,
            evidence_id=c.evidence_id,
            document_name=doc.original_filename if doc else None,
            claim_id=c.id,
            fact_doc_names=fact_doc_names,
            enable_llm_verification=False,
        )
        span_info = _extract_primary_span_info(c)
        for decision in eval_res["contradictions"] + eval_res.get("potential_conflicts", []):
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
                "type": "CLAIM_CONTRADICTION" if decision.status == "CONTRADICTION" else "CLAIM_POTENTIAL_CONFLICT",
                "status": decision.status,
                "reason_code": decision.reason_code,
                "subject_match_basis": decision.subject_match_basis,
                "predicate_match_basis": decision.predicate_match_basis,
                "temporal_semantics": decision.temporal_semantics,
                "evidence_id": c.evidence_id,
                "document_name": doc.original_filename if doc else None,
                "claim_id": c.id,
                "claim_statement": c.statement,
                "span_id": span_info["span_id"],
                "page_number": span_info["page_number"],
                "paragraph_index": span_info["paragraph_index"],
                "text_excerpt": span_info["text_excerpt"],
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
                    subject=claim.subject_key,
                    predicate=claim.predicate_key,
                    scope=claim.scope,
                    temporal_context=claim.temporal_context,
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
                span_info = _extract_primary_span_info(claim)
                conflicts.append({
                    "conflict_id": c_id,
                    "type": "GRAPH_CONTRADICTION",
                    "status": "CONTRADICTION",
                    "reason_code": decision.reason_code,
                    "subject_match_basis": decision.subject_match_basis,
                    "predicate_match_basis": decision.predicate_match_basis,
                    "temporal_semantics": decision.temporal_semantics,
                    "evidence_id": claim.evidence_id,
                    "document_name": doc.original_filename if doc else None,
                    "claim_id": claim.id,
                    "claim_statement": claim.statement,
                    "span_id": span_info["span_id"],
                    "page_number": span_info["page_number"],
                    "paragraph_index": span_info["paragraph_index"],
                    "text_excerpt": span_info["text_excerpt"],
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

    contradictions_only = [c for c in conflicts if c.get("status") == "CONTRADICTION"]
    potential_only = [c for c in conflicts if c.get("status") == "POTENTIAL_CONFLICT"]

    return {
        "conflicts": conflicts,
        "contradictions": contradictions_only,
        "potential_conflicts": potential_only,
        "contradiction_count": len(contradictions_only),
        "potential_conflict_count": len(potential_only),
    }


@router.get("/adjudications")
def get_case_fact_adjudications(
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건의 모든 확정 사실 심리 결과(FactAdjudication) 및 증거 신뢰성 목록을 반환한다."""
    adjudications = db.query(FactAdjudication).filter_by(case_id=case.id).all()
    facts = {f.id: f for f in db.query(Fact).filter_by(case_id=case.id).all()}
    claims = {c.id: c for c in db.query(EvidenceClaim).filter_by(case_id=case.id).all()}
    docs = {d.id: d for d in db.query(EvidenceDocument).filter_by(case_id=case.id).all()}

    results = []
    for adj in adjudications:
        fact = facts.get(adj.fact_id) if adj.fact_id else None
        claim = claims.get(adj.claim_id) if adj.claim_id else None
        doc = docs.get(claim.evidence_id) if (claim and claim.evidence_id) else None
        results.append({
            "id": adj.id,
            "fact_id": adj.fact_id,
            "claim_id": adj.claim_id,
            "statement": fact.statement if fact else (claim.statement if claim else ""),
            "adjudication_status": adj.adjudication_status,
            "primary_relation": adj.primary_relation,
            "confidence": adj.confidence,
            "adjudication_basis": adj.adjudication_basis,
            "document_name": doc.original_filename if doc else None,
            "supporting_evidence_ids": adj.supporting_evidence_ids or [],
            "contradicting_evidence_ids": adj.contradicting_evidence_ids or [],
            "created_at": adj.created_at.isoformat() if adj.created_at else None,
        })
    return {"adjudications": results, "total_count": len(results)}


@router.get("/gaps")
def get_case_evidence_gaps(
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건의 증거 공백(EvidenceGap) 및 권장 보완 조치 목록을 반환한다."""
    gaps = db.query(EvidenceGap).filter_by(case_id=case.id).all()
    results = []
    for g in gaps:
        results.append({
            "id": g.id,
            "gap_type": g.gap_type,
            "target_proposition": g.target_proposition,
            "description": g.description,
            "recommended_document_types": g.recommended_document_types or [],
            "recommended_action": g.recommended_action,
            "priority": g.priority,
            "is_resolved": g.is_resolved,
            "created_at": g.created_at.isoformat() if g.created_at else None,
        })
    return {"gaps": results, "total_count": len(results)}


@router.post("/{evidence_id}/extract")
def trigger_evidence_extraction(
    evidence_id: str,
    background_tasks: BackgroundTasks,
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """지정된 증거 문서에 대해 텍스트 및 AI 사실 추출(또는 재추출) 작업을 백그라운드로 실행한다."""
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
        "message": "추출 작업이 시작되었습니다.",
    }


@router.get("/{evidence_id}/claims")
def get_evidence_claims(
    evidence_id: str,
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """특정 증거 문서에서 도출된 주장(Claim) 후보들과 원문(Span) 정보를 반환한다."""
    doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="증거 문서를 찾을 수 없습니다.")

    claims = db.query(EvidenceClaim).filter_by(evidence_id=evidence_id, case_id=case.id).all()
    result = []
    for c in claims:
        spans = c.spans
        result.append({
            "id": c.id,
            "claim_id": c.id,
            "statement": c.statement,
            "claim_type": normalize_to_claim_code(c.claim_type),
            "subject_key": c.subject_key,
            "predicate_key": c.predicate_key,
            "scope": c.scope,
            "temporal_context": c.temporal_context,
            "structured_slots": c.structured_slots,
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
            ],
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
    db: Session = Depends(get_db),
):
    """추출된 주장 후보를 검토(승인/수정/거절)하고 공식 Fact 및 사건 그래프 상태를 원자적으로 갱신한다.

    [소유권 검증 (P0-03)]
    - evidence_id가 현재 case_id에 속하는지 확인한다.
    - claim_id가 요청된 case_id 및 evidence_id에 속하는지 엄격히 검증한다 (불일치 시 404/400 반환).
    """
    doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="증거 문서를 찾을 수 없습니다.")

    claim = db.query(EvidenceClaim).filter_by(id=claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="검토할 주장(Claim)을 찾을 수 없습니다.")
    if claim.case_id != case.id or claim.evidence_id != evidence_id:
        raise HTTPException(
            status_code=400,
            detail="요청된 주장(claim_id)이 해당 사건 또는 증거 문서에 속하지 않습니다.",
        )

    try:
        review = process_evidence_review(
            db=db,
            claim_id=claim_id,
            action=req.action,
            new_statement=req.new_statement,
            review_reason=req.review_reason,
            expected_case_id=case.id,
            expected_evidence_id=evidence_id,
        )

        audit = AuditLog(
            actor_user_id=current_user.id,
            event_type=f"REVIEW_CLAIM_{req.action}",
            resource_type="EvidenceClaim",
            resource_id=claim_id,
            result="SUCCESS",
        )
        db.add(audit)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="동시 수정이 발생했거나 처리 중 오류가 발생했습니다.")
    return {"status": "SUCCESS", "review_id": review.id}


@router.delete("/{evidence_id}")
def delete_evidence(
    evidence_id: str,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건에 등록된 증거 문서 및 단독 지지 추출 데이터를 정합성 있게 삭제한다.

    1. 증거 문서 및 물리 파일 삭제
    2. 해당 증거 문서가 단독으로 지지하던 Fact만 선별 삭제하고 다른 승인 증거가 지지하는 Fact는 보존
    3. 삭제된 Fact 참조(LegalIssue, Event) 정리, DISPUTED 상태 재계산 및 타임라인 재구축
    4. 사건 그래프 재동기화 작업 큐 등록
    """
    import os
    from ai_legal_helper.case_intelligence.evidence_ingestion import get_storage_dir
    from ai_legal_helper.database.graph_sync_worker import queue_sync_task

    doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="삭제할 증거 문서를 찾을 수 없습니다.")

    if doc.safe_storage_key:
        storage_dir = get_storage_dir()
        file_path = os.path.join(storage_dir, doc.safe_storage_key)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

    fact_ids_from_links = [
        link.target_id
        for link in db.query(EvidenceLink).filter_by(evidence_id=evidence_id, target_type="FACT").all()
    ]
    candidate_facts = (
        db.query(Fact)
        .filter(
            (Fact.case_id == case.id)
            & ((Fact.source_ref == evidence_id) | (Fact.id.in_(fact_ids_from_links)))
        )
        .all()
    )

    other_approved_claims = (
        db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == case.id,
            EvidenceClaim.evidence_id != evidence_id,
            EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
        )
        .all()
    )

    deleted_fact_ids = set()
    for fact in candidate_facts:
        if fact.source_type == "USER_CLAIM":
            continue
        other_sup_links = (
            db.query(EvidenceLink)
            .join(EvidenceClaim, EvidenceLink.claim_id == EvidenceClaim.id)
            .filter(
                EvidenceLink.target_type == "FACT",
                EvidenceLink.target_id == fact.id,
                EvidenceLink.link_type == "SUPPORTS",
                EvidenceLink.evidence_id != evidence_id,
                EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
            )
            .all()
        )
        norm_f = "".join((fact.statement or "").split())
        same_stmt_others = [
            oc for oc in other_approved_claims
            if "".join((oc.statement or "").split()) == norm_f
        ]
        if not other_sup_links and not same_stmt_others:
            deleted_fact_ids.add(fact.id)
            db.delete(fact)
        else:
            if fact.source_ref == evidence_id:
                if other_sup_links:
                    fact.source_ref = other_sup_links[0].evidence_id
                elif same_stmt_others:
                    fact.source_ref = same_stmt_others[0].evidence_id

    doc_filename = doc.original_filename
    db.delete(doc)
    db.flush()

    _prune_deleted_fact_references(db, case.id, deleted_fact_ids)
    _recalculate_case_disputed_facts(db, case.id)
    _rebuild_case_timeline(db, case.id)

    audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="DELETE_EVIDENCE",
        resource_type="EvidenceDocument",
        resource_id=evidence_id,
        result="SUCCESS",
    )
    db.add(audit)
    queue_sync_task(db, case.id)
    db.commit()

    return {"status": "SUCCESS", "deleted_id": evidence_id, "filename": doc_filename}
