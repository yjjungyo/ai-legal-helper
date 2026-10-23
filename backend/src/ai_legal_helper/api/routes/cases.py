# -*- coding: utf-8 -*-
"""
모듈명: cases.py

[모듈 개요]
사건(Case) 생성, 목록 조회, 상세 조회, 정보 수정(PATCH/PUT), 진술(Statement) 추가,
대응 계획(Action Plan) 생성/조회, 사건 영구 삭제(DELETE)를 담당하는 FastAPI 라우터 모듈이다.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import Case, Party, Fact, Event, LegalIssue, CaseRevision, User, AuditLog
from ai_legal_helper.api.schemas.case import (
    CaseSchema, CaseDetailSchema, CaseCreateRequest, CaseUpdateRequest, StatementAddRequest,
    FactSchema, EventSchema, LegalIssueSchema
)
from ai_legal_helper.case_intelligence.manager import process_new_statement
from ai_legal_helper.database.graph_sync_worker import queue_sync_task
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user, AUTH_BYPASS
from ai_legal_helper.case_intelligence.classifier import classify_case_type

router = APIRouter(prefix="/cases", tags=["cases"])

@router.post("", response_model=CaseSchema)
def create_case(req: CaseCreateRequest, request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """새로운 사건을 생성한다. 
    
    사용자가 사건 유형을 수동으로 선택하지 않았거나 'AI_AUTO'인 경우, 
    사건 제목과 설명을 바탕으로 AI가 적합한 법률 분쟁 유형을 자동 분류하여 태깅한다.
    생성 후 Case 루트 노드를 지식 그래프에 동기화한다.
    """
    raw_type = (req.case_type or "").strip()
    if not raw_type or raw_type.upper() in ("AI_AUTO", "AUTO", "자동", "자동 분류"):
        final_case_type = classify_case_type(req.title or "", req.description)
    else:
        final_case_type = raw_type

    new_case = Case(
        title=req.title,
        case_type=final_case_type,
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
    logger.info(f"새로운 사건이 생성되었습니다: '{new_case.title}' (ID: {new_case.id})")
    return new_case

@router.get("", response_model=List[CaseSchema])
def list_cases(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """현재 사용자의 사건 목록을 조회한다. 1인 테스트 모드 시 전체 사건을 표시한다."""
    if AUTH_BYPASS:
        cases = db.query(Case).order_by(Case.updated_at.desc()).all()
    else:
        cases = db.query(Case).filter(Case.user_id == current_user.id).order_by(Case.updated_at.desc()).all()
    logger.info(f"사건 목록 조회 완료 (총 {len(cases)}건)")
    return cases

@router.get("/{case_id}", response_model=CaseDetailSchema)
def get_case_detail(
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건 상세 정보를 조회한다 (당사자, 사실관계, 타임라인 등 포함).

    확정 사실(Fact)이 존재하지만 당사자(Parties)와 타임라인(Events)이 모두 비어 있는
    레거시 사건의 경우 조회 시점에 `synchronize_case_entities`를 자동 실행하여 복구한다.
    """
    if case.facts and not case.parties and not case.events:
        try:
            from ai_legal_helper.case_intelligence.entity_sync import synchronize_case_entities

            sync_res = synchronize_case_entities(
                db=db,
                case_id=case.id,
                dry_run=False,
                queue_graph_sync=True,
            )
            if (
                sync_res["parties"]["total_derived"] > 0
                or sync_res["timeline"]["derived_events_count"] > 0
            ):
                db.commit()
                db.refresh(case)
        except Exception as e:
            db.rollback()
            logger.warning(f"Failed to auto-sync case entities on detail view for {case.id}: {e}")

    logger.info(f"사건 상세 정보 조회 완료: '{case.title}'")
    return case


@router.post("/{case_id}/rebuild-entities")
def trigger_rebuild_case_entities(
    case_id: str,
    dry_run: bool = False,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건의 확정 사실(Fact) 및 승인된 증거 주장(EvidenceClaim)을 재스캔하여 Parties와 Timeline을 복구한다."""
    from ai_legal_helper.case_intelligence.entity_sync import rebuild_case_entities

    return rebuild_case_entities(db=db, case_id=case.id, dry_run=dry_run)


@router.patch("/{case_id}", response_model=CaseDetailSchema)
@router.put("/{case_id}", response_model=CaseDetailSchema)
def update_case(
    case_id: str,
    req: CaseUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """사건 기본 정보(제목, 사건 유형, 설명, 진행 상태)를 수정하고 리비전 및 그래프 동기화를 기록한다 (EVT-006).

    Args:
        case_id: 수정할 사건 UUID.
        req: 수정할 필드(title, case_type, description, status)를 담은 요청 스키마.
        request: FastAPI Request 객체.
        current_user: 현재 인증된 사용자.
        case: 접근 권한이 검증된 Case 엔티티.
        db: 데이터베이스 세션.

    Returns:
        CaseDetailSchema: 수정이 반영된 사건 상세 정보.
    """
    changed_fields = []
    if req.title is not None and req.title.strip():
        case.title = req.title.strip()
        changed_fields.append("title")
    if req.case_type is not None:
        case.case_type = req.case_type.strip() or None
        changed_fields.append("case_type")
    if req.description is not None:
        case.description = req.description
        changed_fields.append("description")
    if req.status is not None and req.status.strip():
        case.status = req.status.strip()
        changed_fields.append("status")

    if changed_fields:
        case.version = (case.version or 1) + 1
        revision = CaseRevision(
            case_id=case.id,
            version=case.version,
            change_type="CASE_UPDATED",
            change_summary=f"Updated fields: {', '.join(changed_fields)}",
            changed_entity_ids={"fields": changed_fields},
        )
        db.add(revision)

        audit = AuditLog(
            actor_user_id=current_user.id,
            event_type="UPDATE_CASE",
            resource_type="Case",
            resource_id=case.id,
            result="SUCCESS",
        )
        db.add(audit)
        queue_sync_task(db, case.id)
        db.commit()
        db.refresh(case)

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

from ai_legal_helper.api.schemas.action import (
    LegalActionSchema, ActionRequirementSchema, ActionStatusUpdateRequest, RequirementStatusUpdateRequest
)
from ai_legal_helper.case_intelligence.action_service import generate_action_plan
from ai_legal_helper.database.models import LegalAction, ActionRequirement

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
        
        # Audit log 및 그래프 동기화 큐잉을 단일 트랜잭션으로 커밋 (Issue #9)
        audit = AuditLog(
            actor_user_id=current_user.id,
            event_type="GENERATE_ACTION_PLAN",
            resource_type="Case",
            resource_id=case_id,
            result="SUCCESS"
        )
        db.add(audit)
        queue_sync_task(db, case_id)
        db.commit()
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

@router.patch("/{case_id}/actions/{action_id}", response_model=LegalActionSchema)
def update_action_status(
    case_id: str,
    action_id: str,
    req: ActionStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """특정 법률 대응 조치(LegalAction)의 진행 상태(PENDING, IN_PROGRESS, COMPLETED)를 변경한다."""
    action = db.query(LegalAction).filter(
        LegalAction.id == action_id,
        LegalAction.case_id == case.id,
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="대응 조치를 찾을 수 없습니다.")

    action.status = req.status.strip().upper()
    queue_sync_task(db, case.id)
    db.commit()
    db.refresh(action)
    return action

@router.patch(
    "/{case_id}/actions/{action_id}/requirements/{requirement_id}",
    response_model=ActionRequirementSchema,
)
def update_action_requirement_status(
    case_id: str,
    action_id: str,
    requirement_id: str,
    req: RequirementStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """대응 조치의 사전 필요 요건(ActionRequirement) 충족 여부(SATISFIED/UNSATISFIED)를 갱신한다."""
    action = db.query(LegalAction).filter(
        LegalAction.id == action_id,
        LegalAction.case_id == case.id,
    ).first()
    if not action:
        raise HTTPException(status_code=404, detail="대응 조치를 찾을 수 없습니다.")

    requirement = db.query(ActionRequirement).filter(
        ActionRequirement.id == requirement_id,
        ActionRequirement.action_id == action.id,
    ).first()
    if not requirement:
        raise HTTPException(status_code=404, detail="사전 필요 요건을 찾을 수 없습니다.")

    requirement.satisfaction_status = req.satisfaction_status.strip().upper()
    db.commit()
    db.refresh(requirement)
    return requirement

@router.delete("/{case_id}")
def delete_case(
    case_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db)
):
    """사건 및 관련된 모든 데이터(증거 파일, 상담, 대응계획, 그래프, 벡터 등)를 영구 삭제한다.
    
    1. 로컬 파일 저장소의 실제 증거 파일 및 다운로드 문서 삭제
    2. Neo4j Knowledge Graph 내 사건 서브그래프 노드/관계 삭제
    4. RDB 내 연관 동기화 작업 큐(GraphSyncTask) 삭제
    5. RDB Cascade를 통한 Case 및 하위 전체 레코드(증거, 사실, 상담, 대응계획 등) 영구 삭제
    """
    import os
    from ai_legal_helper.case_intelligence.evidence_ingestion import get_storage_dir
    from ai_legal_helper.database.graph_sync import delete_case_graph
    from ai_legal_helper.database.neo4j import get_neo4j_driver
    from ai_legal_helper.database.models import GraphSyncTask

    case_title = case.title

    # 1. 증거 문서 물리 파일 삭제
    try:
        storage_dir = get_storage_dir()
        for doc in case.evidences:
            if doc.safe_storage_key:
                file_path = os.path.join(storage_dir, doc.safe_storage_key)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete evidence file {file_path}: {e}")
    except Exception as e:
        logger.warning(f"Error while cleaning up evidence files: {e}")

    # 2. 법률 문서 내보내기 물리 파일 삭제
    try:
        for doc in case.legal_documents:
            for rev in doc.revisions:
                for exp in rev.exports:
                    if exp.file_path and os.path.exists(exp.file_path):
                        try:
                            os.remove(exp.file_path)
                        except Exception as e:
                            logger.warning(f"Failed to delete export file {exp.file_path}: {e}")
    except Exception as e:
        logger.warning(f"Error while cleaning up document exports: {e}")

    # 3. Neo4j 지식 그래프 서브그래프 삭제
    try:
        driver = get_neo4j_driver()
        if driver:
            delete_case_graph(driver, case.id)
    except Exception as e:
        logger.warning(f"Failed to delete Neo4j graph for case {case.id}: {e}")

    # 5. 비동기 작업 큐 정리
    try:
        db.query(GraphSyncTask).filter_by(case_id=case.id).delete()
    except Exception as e:
        logger.warning(f"Failed to delete sync tasks for case {case.id}: {e}")

    # 6. RDB Case 레코드 삭제 (Cascade로 parties, facts, events, evidences, claims, actions, documents, consultations 일괄 삭제)
    db.delete(case)

    # 7. 감사 로그 기록
    audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="DELETE_CASE",
        resource_type="Case",
        resource_id=case_id,
        result="SUCCESS"
    )
    db.add(audit)
    db.commit()

    logger.info(f"Case {case_id} ('{case_title}') and all associated data permanently deleted.")
    return {"status": "SUCCESS", "deleted_id": case_id, "title": case_title}


