# -*- coding: utf-8 -*-
"""
모듈명: evidence_manager.py

[모듈 개요]
증거 및 사실관계 리뷰 매니저 (Evidence Review Manager).
사용자가 EvidenceClaim(추출된 사실 후보)을 검토(승인/수정/반려)할 때 이를 처리하며,
승인된 경우 기존 Fact와 상충 여부를 확인해 SUPPORTS/CONTRADICTS 링크를 생성하고 공식 Fact로 편입한다.
또한 사용자 승인(review_status)과 사실의 객관적 검증 수준(verification_status)을 분리하여
문서 기재 사실(DOCUMENT_VERIFIED), 일방 주장(PARTY_ASSERTED), 상충 사실(DISPUTED), AI 추론(UNVERIFIED)을 구분한다.
이 모든 과정은 단일 트랜잭션으로 처리되며 CaseRevision으로 이력을 남긴다.
"""

from typing import Optional, Tuple
from sqlalchemy.orm import Session

from ai_legal_helper.database.models import (
    Case,
    CaseRevision,
    EvidenceClaim,
    EvidenceReview,
    EvidenceLink,
    Fact,
    Event,
)
from ai_legal_helper.case_intelligence.evidence_extractor import detect_conflicting_fact


def derive_fact_trust_status(
    assertion_status: Optional[str],
    has_conflict: bool = False,
) -> Tuple[str, str]:
    """EvidenceClaim의 단언 상태(assertion_status)와 상충 여부에 따라 Fact의 검증 상태 및 출처 유형을 산출한다.

    사용자 승인(APPROVE/EDIT)과 객관적 사실 입증 수준을 분리하여,
    일방 당사자의 주장 문서나 상충 후보가 무조건 'VERIFIED'로 둔갑하는 문제를 방지한다.

    Args:
        assertion_status: EvidenceClaim.assertion_status 값.
        has_conflict: 기존 사건 Fact와의 상충 감지 여부.

    Returns:
        Tuple[str, str]: (Fact.verification_status, Fact.source_type) 튜플.
    """
    norm_status = (assertion_status or "DOCUMENT_STATES").strip().upper()
    if has_conflict or norm_status == "CONTRADICTION_CANDIDATE":
        return ("DISPUTED", "DOCUMENT_SUPPORTED")
    if norm_status == "PARTY_ALLEGES":
        return ("PARTY_ASSERTED", "PARTY_ALLEGATION")
    if norm_status in ("AI_INFERENCE", "UNCERTAIN"):
        return ("UNVERIFIED", "AI_INFERENCE")
    return ("DOCUMENT_VERIFIED", "DOCUMENT_SUPPORTED")


def process_evidence_review(
    db: Session,
    claim_id: str,
    action: str,
    new_statement: Optional[str] = None,
    review_reason: Optional[str] = None,
) -> EvidenceReview:
    """EvidenceClaim에 대한 사용자의 리뷰 액션(APPROVE, EDIT, REJECT)을 처리한다.

    트랜잭션으로 처리되며 변경 이력은 EvidenceReview와 CaseRevision에 남는다.
    승인(APPROVE) 또는 수정(EDIT) 시 공식 Fact로 편입하고, 기존 Fact와 상충하는 경우
    `CONTRADICTS` EvidenceLink를 함께 생성하여 불일치 탐지(EVT-024) 및 그래프 동기화에 반영한다.

    Args:
        db: 데이터베이스 세션.
        claim_id: 검토 대상 EvidenceClaim UUID.
        action: 리뷰 액션 ('APPROVE', 'EDIT', 'REJECT').
        new_statement: EDIT 액션 시 수정된 진술 문자열.
        review_reason: 검토 사유 메모.

    Returns:
        EvidenceReview: 생성된 리뷰 이력 레코드.
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
        changed_entity_ids={"claim_id": claim.id},
    )
    db.add(revision)
    db.flush()  # revision id 할당

    # Review 이력 기록
    review = EvidenceReview(
        claim_id=claim.id,
        case_revision_id=revision.id,
        previous_review_status=previous_status,
        new_review_status=claim.review_status,
        previous_statement=previous_statement,
        new_statement=new_statement,
        review_reason=review_reason,
    )
    db.add(review)

    # 승인 또는 수정된 경우 기존 Fact와의 상충 여부 확인 후 공식 Fact 승격 및 타임라인 재구축
    if claim.review_status in ["APPROVED", "EDITED"]:
        existing_facts = db.query(Fact).filter_by(case_id=case.id).all()
        conflicting_fact = detect_conflicting_fact(claim.statement, existing_facts)
        if conflicting_fact:
            claim.assertion_status = "CONTRADICTION_CANDIDATE"
            conflicting_fact.verification_status = "DISPUTED"
            existing_contra = (
                db.query(EvidenceLink)
                .filter_by(
                    claim_id=claim.id,
                    target_type="FACT",
                    target_id=conflicting_fact.id,
                    link_type="CONTRADICTS",
                )
                .first()
            )
            if not existing_contra:
                db.add(
                    EvidenceLink(
                        evidence_id=claim.evidence_id,
                        claim_id=claim.id,
                        target_type="FACT",
                        target_id=conflicting_fact.id,
                        link_type="CONTRADICTS",
                    )
                )

        ver_status, src_type = derive_fact_trust_status(
            claim.assertion_status,
            has_conflict=conflicting_fact is not None,
        )

        # 동일 문장 중복 Fact 생성 방지
        norm_stmt = "".join((claim.statement or "").split())
        matched_fact = next(
            (f for f in existing_facts if "".join((f.statement or "").split()) == norm_stmt),
            None,
        )
        if matched_fact:
            target_fact = matched_fact
            if ver_status == "DISPUTED":
                target_fact.verification_status = "DISPUTED"
        else:
            target_fact = Fact(
                case_id=case.id,
                statement=claim.statement,
                fact_type=claim.claim_type,
                confidence=claim.confidence,
                source_type=src_type,
                source_ref=claim.evidence_id,  # evidence_id를 참조로 남김
                verification_status=ver_status,
            )
            db.add(target_fact)
            db.flush()

            # 신규 Fact 추가 시 타임라인(Event) 자동 재구축 (EVT-011 일관성 유지)
            from ai_legal_helper.case_intelligence.timeline import build_timeline_from_facts

            all_facts = db.query(Fact).filter_by(case_id=case.id).all()
            db.query(Event).filter_by(case_id=case.id).delete()
            db.flush()
            for ev in build_timeline_from_facts(all_facts):
                ev.case_id = case.id
                db.add(ev)

        revision.changed_entity_ids = {"claim_id": claim.id, "fact_id": target_fact.id}

        # EvidenceLink 생성 (SUPPORTS, 중복 방지)
        existing_sup = (
            db.query(EvidenceLink)
            .filter_by(
                claim_id=claim.id,
                target_type="FACT",
                target_id=target_fact.id,
                link_type="SUPPORTS",
            )
            .first()
        )
        if not existing_sup:
            db.add(
                EvidenceLink(
                    evidence_id=claim.evidence_id,
                    claim_id=claim.id,
                    target_type="FACT",
                    target_id=target_fact.id,
                    link_type="SUPPORTS",
                )
            )

    from ai_legal_helper.database.graph_sync_worker import queue_sync_task

    queue_sync_task(db, case.id)

    db.commit()
    db.refresh(review)
    return review
