# -*- coding: utf-8 -*-
"""
Case 관련 FastAPI 엔드포인트 라우터 (Case Routes)

P2.2에서 설계된 사건 기반 관리 API들을 제공한다.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
import logging

logger = logging.getLogger(__name__)

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import Case, Party, Fact, Event, LegalIssue, CaseRevision, User, AuditLog
from ai_legal_helper.api.schemas.case import (
    CaseSchema, CaseDetailSchema, CaseCreateRequest, StatementAddRequest,
    FactSchema, EventSchema, LegalIssueSchema
)
from ai_legal_helper.case_intelligence.manager import process_new_statement
from ai_legal_helper.database.graph_sync_worker import queue_sync_task
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user, AUTH_BYPASS

router = APIRouter(prefix="/cases", tags=["cases"])

@router.post("", response_model=CaseSchema)
def create_case(req: CaseCreateRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """새로운 사건을 생성한다. 생성 후 Case 루트 노드를 그래프에 동기화한다."""
    new_case = Case(
        title=req.title,
        case_type=req.case_type,
        description=req.description,
        user_id=current_user.id
    )
    db.add(new_case)
    db.flush()
    
    # Audit log
    audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="CREATE_CASE",
        resource_type="Case",
        resource_id=new_case.id,
        result="SUCCESS"
    )
    db.add(audit)
    
    queue_sync_task(db, new_case.id)
    db.commit()
    db.refresh(new_case)
    return new_case

@router.get("", response_model=List[CaseSchema])
def list_cases(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """현재 사용자의 사건 목록을 조회한다. 1인 테스트 모드 시 전체 사건을 표시한다."""
    if AUTH_BYPASS:
        cases = db.query(Case).order_by(Case.updated_at.desc()).all()
    else:
        cases = db.query(Case).filter(Case.user_id == current_user.id).order_by(Case.updated_at.desc()).all()
    return cases

@router.get("/{case_id}", response_model=CaseDetailSchema)
def get_case_detail(case: Case = Depends(get_case_for_user)):
    """사건 상세 정보를 조회한다 (당사자, 사실관계, 타임라인 등 포함)."""
    return case

@router.post("/{case_id}/statements", response_model=CaseDetailSchema)
def add_statement(
    case_id: str, 
    req: StatementAddRequest, 
    request: Request,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user), 
    db: Session = Depends(get_db)
):
    """새로운 진술을 추가하고 사실관계/타임라인을 갱신한다."""
    try:
        updated_case = process_new_statement(db, case_id, req.statement)
        
        # Audit log
        audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="ADD_STATEMENT",
        resource_type="Case",
        resource_id=case_id,
        result="SUCCESS"
    )
        db.add(audit)
        db.commit()
        db.refresh(updated_case)
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to add statement: {e}")
        raise HTTPException(status_code=500, detail="서버 오류가 발생했습니다.")
    return updated_case

from ai_legal_helper.api.schemas.action import LegalActionSchema
from ai_legal_helper.case_intelligence.action_service import generate_action_plan
from ai_legal_helper.database.models import LegalAction

@router.post("/{case_id}/actions/plan", response_model=List[LegalActionSchema])
def create_action_plan(
    case_id: str, 
    request: Request,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user), 
    db: Session = Depends(get_db)
):
    """현재 사건 정보를 기반으로 Action Plan을 생성(또는 갱신)한다."""
    try:
        actions = generate_action_plan(db, case_id)
        
        # Audit log
        audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="GENERATE_ACTION_PLAN",
        resource_type="Case",
        resource_id=case_id,
        result="SUCCESS"
    )
        db.add(audit)
        db.commit()
        
        queue_sync_task(db, case_id)
        return actions
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Action plan generation failed: {e}")
        raise HTTPException(status_code=500, detail="Action Plan 생성 중 오류가 발생했습니다.")

@router.get("/{case_id}/actions", response_model=List[LegalActionSchema])
def get_action_plan(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """사건의 현재 Action Plan을 조회한다."""
    actions = db.query(LegalAction).filter(LegalAction.case_id == case.id).all()
    return actions

