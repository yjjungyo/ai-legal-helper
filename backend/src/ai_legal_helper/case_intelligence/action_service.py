# -*- coding: utf-8 -*-
"""
모듈명: action_service.py

[모듈 개요]
사건 정보(사실, 증거, 쟁점)를 기반으로 Action Plan을 생성/갱신하고,
결과를 데이터베이스 모델(LegalAction 등)에 저장하는 비즈니스 로직을 제공한다.
"""

from typing import List, Dict, Any
from sqlalchemy.orm import Session
from datetime import datetime

from ai_legal_helper.database.models import (
    Case, Fact, Event, EvidenceDocument, EvidenceClaim, LegalIssue,
    LegalAction, ActionRequirement, ActionDependency, ActionDeadline, ActionRevision, LegalDocument
)
from ai_legal_helper.agents.action_planner import plan_legal_actions
from ai_legal_helper.agents.deadline_engine import DeadlineEngine
from ai_legal_helper.rag.graph_rag import GraphRAGRetriever
from ai_legal_helper.database.neo4j import get_neo4j_driver
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

def _build_context_for_planner(db: Session, case_id: str) -> str:
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found")
        
    facts = db.query(Fact).filter(Fact.case_id == case_id).all()
    events = db.query(Event).filter(Event.case_id == case_id).order_by(Event.event_date).all()
    
    # 승인(APPROVED) 및 수정 승인(EDITED)된 증거 주장 모두 포함
    approved_claims = db.query(EvidenceClaim).filter(
        EvidenceClaim.case_id == case_id,
        EvidenceClaim.review_status.in_(["APPROVED", "EDITED"])
    ).all()
    
    issues = db.query(LegalIssue).filter(LegalIssue.case_id == case_id, LegalIssue.status == "OPEN").all()
    
    context_parts = [f"[사건: {case.title}]"]
    
    if facts:
        context_parts.append("[사실관계]")
        for f in facts:
            context_parts.append(f"- {f.statement}")
            
    if events:
        context_parts.append("[타임라인]")
        for e in events:
            date_str = e.event_date or '날짜미상'
            context_parts.append(f"- {date_str}: {e.title}")
            
    if approved_claims:
        context_parts.append("[승인된 증거]")
        for c in approved_claims:
            context_parts.append(f"- {c.statement}")
            
    if issues:
        context_parts.append("[법률 쟁점]")
        for i in issues:
            context_parts.append(f"- {i.title}: {i.description}")
            
    return "\n".join(context_parts)

def generate_action_plan(db: Session, case_id: str) -> List[LegalAction]:
    """기존의 Action Plan을 정리하고 사건 최신 맥락에 맞춰 새로 생성/갱신한다.

    벌크 DELETE 시 하위 ActionRequirement, ActionDeadline, ActionDependency가 고아 레코드로 남거나
    LegalDocument.action_id 외래키 제약 조건이 깨지는 문제를 방지하기 위해,
    연결된 문서의 action_id 참조를 먼저 해제하고 ORM cascade 삭제를 수행한다.
    """
    context_text = _build_context_for_planner(db, case_id)
    
    # 1. LLM Planner 실행
    plan_response = plan_legal_actions(context_text)
    
    # 타임라인 이벤트 조회 (기한 계산용)
    events = db.query(Event).filter(Event.case_id == case_id).all()
    deadline_engine = DeadlineEngine(events)
    
    # 기존 Action을 참조하는 법률 문서의 외래키 연결 해제 후 ORM Cascade로 하위 요건·기한·의존성 일괄 정리
    existing_actions = db.query(LegalAction).filter(LegalAction.case_id == case_id).all()
    if existing_actions:
        old_action_ids = [a.id for a in existing_actions]
        db.query(LegalDocument).filter(LegalDocument.action_id.in_(old_action_ids)).update(
            {LegalDocument.action_id: None}, synchronize_session=False
        )
        db.query(ActionDependency).filter(
            (ActionDependency.action_id.in_(old_action_ids))
            | (ActionDependency.depends_on_action_id.in_(old_action_ids))
        ).delete(synchronize_session=False)
        for old_act in existing_actions:
            db.delete(old_act)
        db.flush()
    
    new_actions = []
    action_map = {}
    
    # 2. DB 모델화
    for planned in plan_response.actions:
        action = LegalAction(
            case_id=case_id,
            action_type=planned.action_type,
            title=planned.title,
            description=planned.description,
            priority=planned.priority,
            rationale=planned.rationale,
            risk_level=planned.risk_level,
            confidence=0.9
        )
        db.add(action)
        db.flush()
        action_map[planned.title] = action.id
        new_actions.append(action)
        
        # Requirements
        for req in planned.requirements:
            action_req = ActionRequirement(
                action_id=action.id,
                requirement_type=req.requirement_type,
                description=req.description,
                satisfaction_status=req.satisfaction_status
            )
            db.add(action_req)
            
        # Deadline 계산
        dl_info = deadline_engine.calculate_deadline(planned.title)
        
        action_dl = ActionDeadline(
            action_id=action.id,
            deadline_type=dl_info["deadline_type"],
            deadline_date=dl_info["deadline_date"],
            calculation_basis=dl_info["calculation_basis"],
            verification_status=dl_info["verification_status"]
        )
        db.add(action_dl)
    
    # 의존성 연결
    for planned in plan_response.actions:
        action_id = action_map.get(planned.title)
        if not action_id: continue
        for dep in planned.dependencies:
            dep_id = action_map.get(dep.depends_on_action_title)
            if dep_id:
                action_dep = ActionDependency(
                    action_id=action_id,
                    depends_on_action_id=dep_id,
                    dependency_type=dep.dependency_type
                )
                db.add(action_dep)
                
    db.commit()
    
    # 3. ActionRevision 기록
    latest_revision = db.query(ActionRevision).filter(ActionRevision.case_id == case_id).order_by(ActionRevision.action_plan_version.desc()).first()
    new_version = latest_revision.action_plan_version + 1 if latest_revision else 1
    
    rev = ActionRevision(
        case_id=case_id,
        action_plan_version=new_version,
        change_summary=f"Action Plan {'Created' if new_version == 1 else 'Updated'} (AI Generation)"
    )
    db.add(rev)
    db.commit()
    
    return new_actions

