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
        
        # 2. 당사자 병합 (이름·역할 정규화 기준 중복 삽입 방지)
        existing_parties = db.query(Party).filter(Party.case_id == case.id).all()
        existing_party_map = {
            ((p.name or "").strip(), (p.role or "").strip()): p
            for p in existing_parties
        }
        for ep in extracted.parties:
            p_key = ((ep.name or "").strip(), (ep.role or "").strip())
            if not p_key[0]:
                continue
            if p_key in existing_party_map:
                existing_p = existing_party_map[p_key]
                if not existing_p.party_relationship and ep.relationship:
                    existing_p.party_relationship = ep.relationship
                continue
            party = Party(
                case_id=case.id,
                name=ep.name.strip(),
                role=ep.role.strip() if ep.role else None,
                party_relationship=ep.relationship
            )
            db.add(party)
            existing_party_map[p_key] = party
            new_parties.append(party)
            
        # 3. 사실관계 병합 (공백 제거 정규화 문자열 기준 중복 삽입 방지)
        existing_facts = db.query(Fact).filter(Fact.case_id == case.id).all()
        seen_fact_statements = {
            "".join((f.statement or "").split())
            for f in existing_facts
            if f.statement
        }
        for ef in extracted.facts:
            norm_stmt = "".join((ef.statement or "").split())
            if not norm_stmt or norm_stmt in seen_fact_statements:
                continue
            fact = Fact(
                case_id=case.id,
                statement=ef.statement.strip(),
                fact_type=ef.fact_type,
                occurred_at=ef.occurred_at,
                source_type=ef.source_type,
                source_ref=statement  # 원문 참조 (AOP 로깅에서는 가려지지만 DB에는 저장)
            )
            db.add(fact)
            seen_fact_statements.add(norm_stmt)
            new_facts.append(fact)
            
        # 4. 플러시하여 ID를 생성받음
        db.flush()
        
        # 5. 모든 사실을 모아 당사자(Party) 보강 및 타임라인(Event) 동기화 (수동 Party/Event 보존)
        from ai_legal_helper.case_intelligence.entity_sync import synchronize_case_entities
        synchronize_case_entities(
            db=db,
            case_id=case.id,
            dry_run=False,
            queue_graph_sync=False,
        )
            
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
        logger.error(f"[사건 매니저] 사건({case_id}) 진술 분석 처리 실패: {str(e)}")
        raise e
