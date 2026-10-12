# -*- coding: utf-8 -*-
"""
Case Manager (사건 관리자)

사용자 진술을 받아 Extractor와 Timeline Builder를 조율하고, 
결과를 SQLite 데이터베이스에 영속화(트랜잭션 기반)하는 역할을 담당한다.
"""
import json
from sqlalchemy.orm import Session
from ai_legal_helper.database.models import Case, Party, Fact, Event, CaseRevision, LegalIssue
from ai_legal_helper.case_intelligence.extractor import extract_case_info
from ai_legal_helper.case_intelligence.timeline import build_timeline_from_facts
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

@trace
def process_new_statement(db: Session, case_id: str, statement: str) -> Case:
    """
    사용자의 새로운 진술을 받아 기존 사건에 통합하고, 
    당사자, 사실, 타임라인을 갱신한다.
    
    데이터베이스 트랜잭션을 사용하여 처리 중 오류 발생 시 롤백되도록 안전성을 보장한다.
    
    Args:
        db (Session): SQLAlchemy 데이터베이스 세션
        case_id (str): 대상 사건 ID
        statement (str): 사용자의 새로운 진술 텍스트
        
    Returns:
        Case: 갱신된 사건 객체
    """
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise ValueError(f"Case {case_id} not found")
        
    try:
        # 1. 정보 추출
        extracted = extract_case_info(statement)
        
        new_facts = []
        new_parties = []
        
        # 2. 당사자 병합 (간단히 새 당사자 추가, 중복 방지는 향후 고도화)
        for ep in extracted.parties:
            party = Party(
                case_id=case.id,
                name=ep.name,
                role=ep.role,
                party_relationship=ep.relationship
            )
            db.add(party)
            new_parties.append(party)
            
        # 3. 사실관계 병합
        for ef in extracted.facts:
            fact = Fact(
                case_id=case.id,
                statement=ef.statement,
                fact_type=ef.fact_type,
                occurred_at=ef.occurred_at,
                source_type=ef.source_type,
                source_ref=statement  # 원문 참조 (AOP 로깅에서는 가려지지만 DB에는 저장)
            )
            db.add(fact)
            new_facts.append(fact)
            
        # 4. 플러시하여 ID를 생성받음
        db.flush()
        
        # 5. 모든 사실을 모아 타임라인 재구축
        all_facts = db.query(Fact).filter(Fact.case_id == case.id).all()
        
        # 기존 이벤트 삭제 후 재생성 (간소화된 방식)
        db.query(Event).filter(Event.case_id == case.id).delete()
        db.flush()
        
        new_events = build_timeline_from_facts(all_facts)
        for ev in new_events:
            ev.case_id = case.id
            db.add(ev)
            
        # 6. 추가 질문(Missing Info)은 LegalIssue 형태로 임시 저장
        # 실무에서는 별도 테이블이 좋지만, 여기서는 이슈로 처리
        for q in extracted.missing_info_questions:
            issue = LegalIssue(
                case_id=case.id,
                title="추가 확인 필요",
                description=q,
                status="OPEN"
            )
            db.add(issue)
            
        # 7. 사건 버전 업 및 Revision 기록
        case.version = int(case.version or 0) + 1  # type: ignore
        
        rev = CaseRevision(
            case_id=case.id,
            version=case.version,
            change_type="STATEMENT_ADDED",
            change_summary=f"새로운 진술 추가됨: 사실 {len(new_facts)}건 추출",
            changed_entity_ids=[f.id for f in new_facts]
        )
        db.add(rev)
        
        # 8. 커밋 전 동기화 태스크 큐 추가 (Outbox 패턴)
        from ai_legal_helper.database.graph_sync_worker import queue_sync_task
        queue_sync_task(db, case.id)

        # 9. 커밋
        db.commit()
        db.refresh(case)
        return case
        
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to process statement for case {case_id}: {str(e)}")
        raise e
