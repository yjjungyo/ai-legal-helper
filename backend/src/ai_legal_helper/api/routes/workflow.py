from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import Case, Fact, EvidenceDocument, LegalAction, LegalDocument
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user

router = APIRouter(prefix="/cases/{case_id}/workflow", tags=["workflow"])

class WorkflowStatusResponse(BaseModel):
    case_id: str
    status: str
    summary: str
    pending_tasks: int

def calculate_derived_status(db: Session, case_id: str) -> str:
    """파생 상태(Derived State)를 계산하여 Workflow State를 반환한다."""
    docs_count = db.query(LegalDocument).filter(LegalDocument.case_id == case_id).count()
    if docs_count > 0:
        return "DOCUMENT_DRAFTED"
        
    actions_count = db.query(LegalAction).filter(LegalAction.case_id == case_id).count()
    if actions_count > 0:
        return "ACTION_PLAN_READY"
        
    evidence_count = db.query(EvidenceDocument).filter(EvidenceDocument.case_id == case_id).count()
    if evidence_count > 0:
        return "EVIDENCE_IN_REVIEW"
        
    facts_count = db.query(Fact).filter(Fact.case_id == case_id).count()
    if facts_count > 0:
        return "FACTS_IN_REVIEW"
        
    return "CASE_CREATED"

@router.get("/status", response_model=WorkflowStatusResponse)
def get_workflow_status(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """사건의 현재 통합 워크플로우 진행 상태를 반환한다."""
    derived_status = calculate_derived_status(db, case.id)
    
    return WorkflowStatusResponse(
        case_id=case.id,
        status=derived_status,
        summary=f"현재 단계: {derived_status}",
        pending_tasks=0
    )

