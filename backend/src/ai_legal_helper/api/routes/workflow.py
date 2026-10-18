# -*- coding: utf-8 -*-
"""
사건 워크플로우 통합 API 라우터 (Workflow API Routes)

사건의 전반적인 진행 단계(Derived State)와 통계, 최근 활동,
다음 권장 행동(Next Recommended Action) 등 종합 대시보드 요약 정보를 제공한다.
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import (
    Case, Fact, Party, Event, LegalIssue,
    EvidenceDocument, EvidenceClaim, EvidenceLink,
    LegalAction, LegalDocument, ConsultationRecord
)
from ai_legal_helper.api.dependencies import get_case_for_user

router = APIRouter(prefix="/cases/{case_id}/workflow", tags=["workflow"])

class WorkflowStatusResponse(BaseModel):
    case_id: str
    status: str
    summary: str
    pending_tasks: int

class NextAction(BaseModel):
    title: str
    description: str
    tab_id: str

class WorkflowSummaryResponse(BaseModel):
    case_id: str
    title: str
    case_type: Optional[str] = None
    status: str
    created_at: str
    updated_at: str
    stage_code: str
    stage_name: str
    next_action: NextAction
    stats: Dict[str, Any]
    consultation_preview: Optional[Dict[str, Any]] = None
    recent_evidences: List[Dict[str, Any]] = []
    recent_claims: List[Dict[str, Any]] = []
    recent_actions: List[Dict[str, Any]] = []
    recent_documents: List[Dict[str, Any]] = []
    issues_preview: List[Dict[str, Any]] = []
    timeline_preview: List[Dict[str, Any]] = []
    recent_activities: List[Dict[str, Any]] = []

def calculate_derived_status(db: Session, case_id: str) -> str:
    """파생 상태(Derived State)를 계산하여 Workflow State를 반환한다.

    Args:
        db (Session): 데이터베이스 세션.
        case_id (str): 대상 사건 UUID.

    Returns:
        str: 현재 사건의 종합 워크플로우 단계 코드.
    """
    docs_count = db.query(LegalDocument).filter(LegalDocument.case_id == case_id).count()
    if docs_count > 0:
        return "DOCUMENT_DRAFTED"
        
    actions_count = db.query(LegalAction).filter(LegalAction.case_id == case_id).count()
    if actions_count > 0:
        return "ACTION_PLAN_READY"
        
    issues_count = db.query(LegalIssue).filter(LegalIssue.case_id == case_id).count()
    consults_count = db.query(ConsultationRecord).filter(ConsultationRecord.case_id == case_id).count()
    if issues_count > 0 or consults_count > 0:
        return "ANALYSIS_COMPLETED"

    evidence_count = db.query(EvidenceDocument).filter(EvidenceDocument.case_id == case_id).count()
    if evidence_count > 0:
        pending_claims = (
            db.query(EvidenceClaim)
            .filter(EvidenceClaim.case_id == case_id, EvidenceClaim.review_status == "PENDING")
            .count()
        )
        if pending_claims > 0:
            return "EVIDENCE_IN_REVIEW"
        return "READY_FOR_ANALYSIS"
        
    facts_count = db.query(Fact).filter(Fact.case_id == case_id).count()
    if facts_count > 0:
        return "FACTS_IN_REVIEW"
        
    return "CASE_CREATED"

@router.get("/status", response_model=WorkflowStatusResponse)
def get_workflow_status(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """사건의 현재 통합 워크플로우 진행 상태를 반환한다.

    Args:
        case (Case): 현재 접근 권한이 부여된 사건 엔티티.
        db (Session): 데이터베이스 세션.

    Returns:
        WorkflowStatusResponse: 상태 코드 및 설명.
    """
    derived_status = calculate_derived_status(db, case.id)
    
    return WorkflowStatusResponse(
        case_id=case.id,
        status=derived_status,
        summary=f"현재 단계: {derived_status}",
        pending_tasks=0
    )

@router.get("/summary", response_model=WorkflowSummaryResponse)
def get_workflow_summary(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """사건 개요(Overview) 화면에 표시할 종합 현황, 통계, 권장 행동, 최근 활동 정보를 반환한다.

    Args:
        case (Case): 현재 접근 권한이 부여된 사건 엔티티.
        db (Session): 데이터베이스 세션.

    Returns:
        WorkflowSummaryResponse: 워크플로우 진행 단계, 영역별 통계, 최근 활동 피드.
    """
    facts = db.query(Fact).filter(Fact.case_id == case.id).all()
    parties = db.query(Party).filter(Party.case_id == case.id).all()
    events = db.query(Event).filter(Event.case_id == case.id).order_by(Event.event_date.asc().nullslast()).all()
    issues = db.query(LegalIssue).filter(LegalIssue.case_id == case.id).all()
    evidences = db.query(EvidenceDocument).filter(EvidenceDocument.case_id == case.id).order_by(EvidenceDocument.uploaded_at.desc()).all()
    claims = db.query(EvidenceClaim).filter(EvidenceClaim.case_id == case.id).all()
    actions = db.query(LegalAction).filter(LegalAction.case_id == case.id).order_by(LegalAction.created_at.desc()).all()
    documents = db.query(LegalDocument).filter(LegalDocument.case_id == case.id).order_by(LegalDocument.created_at.desc()).all()
    consultations = db.query(ConsultationRecord).filter(ConsultationRecord.case_id == case.id).order_by(ConsultationRecord.created_at.desc()).all()
    
    conflicts_count = (
        db.query(EvidenceLink)
        .join(EvidenceDocument, EvidenceLink.evidence_id == EvidenceDocument.id)
        .filter(EvidenceDocument.case_id == case.id, EvidenceLink.link_type == "CONTRADICTS")
        .count()
    )

    pending_claims = [c for c in claims if c.review_status == "PENDING"]
    approved_claims = [c for c in claims if c.review_status == "APPROVED"]

    derived_status = calculate_derived_status(db, case.id)
    
    stage_meta = {
        "DOCUMENT_DRAFTED": (
            "문서 작성 완료 단계",
            NextAction(
                title="법률 문서 검토 및 발송/제출",
                description="작성된 법률 문서(내용증명, 소장 등)를 확인하고 인쇄 또는 발송을 준비하세요.",
                tab_id="docs"
            )
        ),
        "ACTION_PLAN_READY": (
            "대응 계획 수립 완료 단계",
            NextAction(
                title="법률 문서 초안 작성",
                description="수립된 대응 계획에 따라 내용증명이나 지급명령 신청서 등 공식 문서를 작성하세요.",
                tab_id="docs"
            )
        ),
        "ANALYSIS_COMPLETED": (
            "법률 분석 완료 단계",
            NextAction(
                title="대응 계획(Action Plan) 수립",
                description="분석된 법률 쟁점과 판례를 기반으로 실질적인 법적 조치 계획을 생성하세요.",
                tab_id="action"
            )
        ),
        "READY_FOR_ANALYSIS": (
            "법률 상담 및 분석 준비 완료",
            NextAction(
                title="AI 법률 상담 진행",
                description="확정된 증거와 사실관계를 바탕으로 AI와 상담하여 법률적 유불리와 쟁점을 분석하세요.",
                tab_id="chat"
            )
        ),
        "EVIDENCE_IN_REVIEW": (
            "증거 사실 검토(리뷰) 단계",
            NextAction(
                title="추출 사실 승인/검토",
                description=f"증거에서 추출된 사실관계 {len(pending_claims)}건을 검토하여 공식 사실(Fact)로 확정하세요.",
                tab_id="evidence"
            )
        ),
        "FACTS_IN_REVIEW": (
            "증거 자료 수집 단계",
            NextAction(
                title="증거 파일(계약서, 문자 등) 등록",
                description="주장을 입증할 계약서나 대화록 등 객관적 증거 문서를 업로드하세요.",
                tab_id="evidence"
            )
        ),
        "CASE_CREATED": (
            "사건 접수 단계",
            NextAction(
                title="AI 상담 시작 또는 증거 등록",
                description="상담 탭에서 사건 경위를 설명하거나 관련 증거 문서를 등록하세요.",
                tab_id="chat"
            )
        )
    }

    stage_name, next_action = stage_meta.get(
        derived_status, 
        ("사건 진행 중", NextAction(title="사건 검토", description="사건 내용을 확인하세요.", tab_id="chat"))
    )

    consultation_preview = None
    if consultations:
        last_c = consultations[0]
        # 비동기 상담 진행 중(IN_PROGRESS)이거나 오류(ERROR) 상태일 때 answer가 None일 수 있으므로 빈 문자열로 안전하게 보정
        raw_answer = last_c.answer or ""
        consultation_preview = {
            "total_count": len(consultations),
            "last_question": last_c.question or "",
            "last_answer_snippet": raw_answer[:120] + "..." if len(raw_answer) > 120 else raw_answer,
            "last_consulted_at": last_c.created_at.isoformat() if last_c.created_at else None
        }

    activities = []
    if consultations:
        q_preview = (consultations[0].question or "")[:30]
        activities.append({
            "type": "CHAT",
            "title": f"AI 법률 상담: '{q_preview}...'",
            "time": consultations[0].created_at.isoformat() if consultations[0].created_at else None,
            "tab_id": "chat"
        })
    if evidences:
        activities.append({
            "type": "EVIDENCE",
            "title": f"증거 파일 등록: '{evidences[0].original_filename}'",
            "time": evidences[0].uploaded_at.isoformat() if evidences[0].uploaded_at else None,
            "tab_id": "evidence"
        })
    if actions:
        activities.append({
            "type": "ACTION",
            "title": f"대응 계획 생성: {len(actions)}건의 조치 수립",
            "time": actions[0].created_at.isoformat() if actions[0].created_at else None,
            "tab_id": "action"
        })
    if documents:
        activities.append({
            "type": "DOCUMENT",
            "title": f"문서 작성: '{documents[0].title}'",
            "time": documents[0].created_at.isoformat() if documents[0].created_at else None,
            "tab_id": "docs"
        })
    if facts:
        activities.append({
            "type": "FACT",
            "title": f"사실관계 등록: {len(facts)}건 확정",
            "time": facts[0].created_at.isoformat() if facts[0].created_at else None,
            "tab_id": "facts"
        })

    activities.sort(key=lambda x: x["time"] or "", reverse=True)

    return WorkflowSummaryResponse(
        case_id=case.id,
        title=case.title,
        case_type=case.case_type,
        status=case.status,
        created_at=case.created_at.isoformat() if case.created_at else "",
        updated_at=case.updated_at.isoformat() if case.updated_at else "",
        stage_code=derived_status,
        stage_name=stage_name,
        next_action=next_action,
        stats={
            "facts_count": len(facts),
            "parties_count": len(parties),
            "events_count": len(events),
            "issues_count": len(issues),
            "evidences_count": len(evidences),
            "claims_pending_count": len(pending_claims),
            "claims_approved_count": len(approved_claims),
            "conflicts_count": conflicts_count,
            "actions_count": len(actions),
            "documents_count": len(documents),
            "consultations_count": len(consultations),
        },
        consultation_preview=consultation_preview,
        recent_evidences=[
            {"id": e.id, "filename": e.original_filename, "status": e.status, "uploaded_at": e.uploaded_at.isoformat() if e.uploaded_at else None}
            for e in evidences[:3]
        ],
        recent_claims=[
            {"id": c.id, "statement": c.statement, "claim_type": c.claim_type, "status": c.review_status}
            for c in claims[:3]
        ],
        recent_actions=[
            {
                "id": a.id,
                "title": a.title,
                "priority": getattr(a, "priority", "MEDIUM"),
                "risk_level": getattr(a, "risk_level", "NONE"),
                "action_type": a.action_type,
                "status": a.status,
            }
            for a in actions[:3]
        ],
        recent_documents=[
            # LegalDocument ORM 모델의 실제 컬럼명(document_type)을 조회하여 doc_type 필드로 매핑
            {"id": d.id, "title": d.title, "doc_type": getattr(d, "document_type", None) or getattr(d, "doc_type", ""), "status": d.status}
            for d in documents[:3]
        ],
        issues_preview=[
            {"id": i.id, "title": i.title, "status": i.status}
            for i in issues[:3]
        ],
        timeline_preview=[
            {"id": ev.id, "title": ev.title, "event_date": ev.event_date}
            for ev in events[:3]
        ],
        recent_activities=activities[:5]
    )
