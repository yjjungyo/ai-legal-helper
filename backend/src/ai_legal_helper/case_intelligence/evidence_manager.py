# -*- coding: utf-8 -*-
"""
증거 및 사실관계 리뷰 매니저 (Evidence Review Manager)

사용자가 EvidenceClaim(추출된 사실 후보)을 검토(승인/수정/반려)할 때 이를 처리하며,
승인된 경우 기존 Fact, Event와 연결하거나 새로 생성한다.
이 모든 과정은 단일 트랜잭션으로 처리되며 CaseRevision으로 이력을 남긴다.
"""

from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
import uuid

from ai_legal_helper.database.models import (
    Case, CaseRevision, EvidenceClaim, EvidenceReview, 
    EvidenceLink, Fact, Event
)

def process_evidence_review(
    db: Session, 
    claim_id: str, 
    action: str, 
    new_statement: Optional[str] = None, 
    review_reason: Optional[str] = None
) -> EvidenceReview:
    """
    EvidenceClaim에 대한 사용자의 리뷰 액션을 처리한다.
    
    action: "APPROVE", "EDIT", "REJECT"
    
    트랜잭션으로 처리되며 변경 이력은 EvidenceReview와 CaseRevision에 남는다.
    승인(APPROVE) 시 시스템의 공식 Fact로 편입된다.
    """
    claim = db.query(EvidenceClaim).filter_by(id=claim_id).with_for_update().first()
    if not claim:
        raise ValueError(f"Claim {claim_id} not found.")
        
    case = db.query(Case).filter_by(id=claim.case_id).with_for_update().first()
    
    previous_status = claim.review_status
    previous_statement = claim.statement
    
    if action == "REJECT":
        claim.review_status = "REJECTED"
        new_statement = None
        change_type = "CLAIM_REJECTED"
    elif action == "EDIT":
        if not new_statement:
            raise ValueError("new_statement is required for EDIT action.")
        claim.review_status = "EDITED"
        claim.statement = new_statement
        change_type = "CLAIM_EDITED"
    elif action == "APPROVE":
        claim.review_status = "APPROVED"
        change_type = "CLAIM_APPROVED"
        new_statement = claim.statement
    else:
        raise ValueError(f"Unknown action {action}")

    # Case Revision 기록 (버전 오를 때 Optimistic Locking 체크됨)
    case.version += 1
    revision = CaseRevision(
        case_id=case.id,
        version=case.version,
        change_type=change_type,
        change_summary=f"Evidence claim {action}: {review_reason or ''}",
        changed_entity_ids={"claim_id": claim.id}
    )
    db.add(revision)
    db.flush() # revision id 할당
    
    # Review 이력 기록
    review = EvidenceReview(
        claim_id=claim.id,
        case_revision_id=revision.id,
        previous_review_status=previous_status,
        new_review_status=claim.review_status,
        previous_statement=previous_statement,
        new_statement=new_statement,
        review_reason=review_reason
    )
    db.add(review)
    
    # 승인 또는 수정된 경우 공식 Fact로 승격 및 연결
    if claim.review_status in ["APPROVED", "EDITED"]:
        new_fact = Fact(
            case_id=case.id,
            statement=claim.statement,
            fact_type=claim.claim_type,
            confidence=claim.confidence,
            source_type="DOCUMENT_SUPPORTED",
            source_ref=claim.evidence_id,  # evidence_id를 참조로 남김
            verification_status="VERIFIED"
        )
        db.add(new_fact)
        db.flush()
        
        # EvidenceLink 생성
        link = EvidenceLink(
            evidence_id=claim.evidence_id,
            claim_id=claim.id,
            target_type="FACT",
            target_id=new_fact.id,
            link_type="SUPPORTS"
        )
        db.add(link)
    
    from ai_legal_helper.database.graph_sync_worker import queue_sync_task
    queue_sync_task(db, case.id)

    db.commit()
    db.refresh(review)
    return review
