# -*- coding: utf-8 -*-
"""
모듈명: evidence_manager.py

[모듈 개요]
증거 및 사실관계 리뷰 매니저 (Evidence Review Manager).
사용자가 EvidenceClaim(추출된 사실 후보)을 검토(승인/수정/반려)할 때 이를 처리하며,
승인된 경우 3단계 상충 검증 엔진(`conflict_detector.evaluate_claim_conflicts`)을 통해
기존 Fact와의 일치(CONSISTENT), 상충(CONTRADICTION), 잠재 상충(POTENTIAL_CONFLICT) 여부를 검증해
SUPPORTS/CONTRADICTS/POTENTIAL_CONFLICT 링크를 생성하고 공식 Fact로 편입한다.

[데이터 정합성 및 생명주기 관리 (v1.1)]
- 소유권 검증: 요청된 case_id, evidence_id, claim_id 간의 소속 일치 여부를 검증한다.
- 수정(EDIT)/반려(REJECT) 시 고아 데이터 정리:
  - 기존 Claim이 단독으로 지지하던 Fact는 삭제하고 LegalIssue/Event 참조 및 EvidenceLink를 정리한다.
  - 다른 승인된 Claim이나 사용자 직접 입력(USER_CLAIM)이 함께 지지하는 Fact는 유지하고 현재 Claim의 링크만 제거한다.
  - 상충 Claim이 수정·반려되어 더 이상 모순이 없어진 기존 Fact의 DISPUTED 상태를 정상 상태로 복원한다.
  - Fact 변경 후 사건의 타임라인(Event)을 즉시 재구축하고 Neo4j 동기화 큐를 등록한다.
- 모든 상태 전이는 단일 PostgreSQL 트랜잭션 내에서 원자적으로 수행된다.
"""

from typing import List, Optional, Set, Tuple
from sqlalchemy.orm import Session

from ai_legal_helper.database.models import (
    Case,
    CaseRevision,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceReview,
    EvidenceLink,
    Fact,
    Event,
    LegalIssue,
)
from ai_legal_helper.case_intelligence.conflict_detector import (
    build_structured_slots,
    evaluate_claim_conflicts,
)


def derive_fact_trust_status(
    assertion_status: Optional[str],
    has_conflict: bool = False,
) -> Tuple[str, str]:
    """EvidenceClaim의 단언 상태(assertion_status)와 상충 여부에 따라 Fact의 검증 상태 및 출처 유형을 산출한다.

    Args:
        assertion_status: EvidenceClaim.assertion_status 값.
        has_conflict: 검증 엔진을 통해 확인된 기존 사건 Fact와의 상충 여부.

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


def _restore_non_disputed_status(fact: Fact) -> str:
    """상충이 해소된 Fact의 원래 출처 유형(source_type)에 맞는 검증 상태를 반환한다."""
    if fact.source_type == "PARTY_ALLEGATION":
        return "PARTY_ASSERTED"
    if fact.source_type == "AI_INFERENCE":
        return "UNVERIFIED"
    if fact.source_type == "USER_CLAIM":
        return "VERIFIED"
    return "DOCUMENT_VERIFIED"


def _prune_deleted_fact_references(db: Session, case_id: str, deleted_fact_ids: Set[str]) -> None:
    """삭제된 Fact ID를 사건 내 LegalIssue.related_fact_ids 및 Event.related_fact_ids에서 제거한다."""
    if not deleted_fact_ids:
        return

    issues = db.query(LegalIssue).filter_by(case_id=case_id).all()
    for issue in issues:
        if isinstance(issue.related_fact_ids, list):
            updated_ids = [fid for fid in issue.related_fact_ids if fid not in deleted_fact_ids]
            if len(updated_ids) != len(issue.related_fact_ids):
                issue.related_fact_ids = updated_ids

    events = db.query(Event).filter_by(case_id=case_id).all()
    for ev in events:
        if isinstance(ev.related_fact_ids, list):
            updated_ids = [fid for fid in ev.related_fact_ids if fid not in deleted_fact_ids]
            if len(updated_ids) != len(ev.related_fact_ids):
                ev.related_fact_ids = updated_ids


def _cleanup_previous_claim_effects(
    db: Session,
    claim: EvidenceClaim,
    previous_statement: Optional[str],
    action: str,
    new_statement: Optional[str],
) -> List[str]:
    """Claim의 수정(EDIT) 또는 반려(REJECT) 시 이전 상태가 남긴 EvidenceLink와 단독 지지 Fact를 정리한다.

    Args:
        db: 데이터베이스 세션.
        claim: 검토 대상 EvidenceClaim.
        previous_statement: 변경 전 진술문.
        action: 수행 액션 ('APPROVE', 'EDIT', 'REJECT').
        new_statement: 변경 후 진술문.

    Returns:
        List[str]: 이번 정리 과정에서 삭제된 Fact ID 목록.
    """
    old_links = db.query(EvidenceLink).filter_by(claim_id=claim.id).all()
    previously_supported_fact_ids: Set[str] = {
        link.target_id
        for link in old_links
        if link.target_type == "FACT" and link.link_type == "SUPPORTS" and link.target_id
    }

    norm_prev = "".join((previous_statement or "").split())
    if norm_prev:
        matching_facts = (
            db.query(Fact)
            .filter_by(case_id=claim.case_id, source_ref=claim.evidence_id)
            .all()
        )
        for mf in matching_facts:
            if "".join((mf.statement or "").split()) == norm_prev:
                previously_supported_fact_ids.add(mf.id)

    # 현재 Claim의 기존 EvidenceLink 일괄 삭제 (APPROVE/EDIT 시에는 이후 최신 상태로 재생성됨)
    db.query(EvidenceLink).filter_by(claim_id=claim.id).delete(synchronize_session=False)
    db.flush()

    norm_new = "".join((new_statement or "").split())
    statement_kept_approved = (
        action == "APPROVE"
        or (action == "EDIT" and norm_new == norm_prev)
    )
    if statement_kept_approved or not previously_supported_fact_ids:
        return []

    deleted_fact_ids: Set[str] = set()
    other_approved_claims = (
        db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == claim.case_id,
            EvidenceClaim.id != claim.id,
            EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
        )
        .all()
    )

    for fact_id in previously_supported_fact_ids:
        fact = db.query(Fact).filter_by(id=fact_id, case_id=claim.case_id).first()
        if not fact:
            continue
        if fact.source_type == "USER_CLAIM":
            continue

        other_support_links = (
            db.query(EvidenceLink)
            .join(EvidenceClaim, EvidenceLink.claim_id == EvidenceClaim.id)
            .filter(
                EvidenceLink.target_type == "FACT",
                EvidenceLink.target_id == fact.id,
                EvidenceLink.link_type == "SUPPORTS",
                EvidenceLink.claim_id != claim.id,
                EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
            )
            .all()
        )
        norm_fact_stmt = "".join((fact.statement or "").split())
        same_stmt_other_claims = [
            oc for oc in other_approved_claims
            if "".join((oc.statement or "").split()) == norm_fact_stmt
        ]

        if not other_support_links and not same_stmt_other_claims:
            # 단독 지지 Fact이므로 고아 Fact가 되지 않도록 삭제 및 연관 링크 제거
            db.query(EvidenceLink).filter_by(
                target_type="FACT",
                target_id=fact.id,
            ).delete(synchronize_session=False)
            deleted_fact_ids.add(fact.id)
            db.delete(fact)
        else:
            # 다른 승인된 Claim이 여전히 지지하고 있으므로 Fact는 보존하되 source_ref를 유효한 증거로 갱신
            if fact.source_ref == claim.evidence_id:
                if other_support_links:
                    fact.source_ref = other_support_links[0].evidence_id
                elif same_stmt_other_claims:
                    fact.source_ref = same_stmt_other_claims[0].evidence_id

    db.flush()
    _prune_deleted_fact_references(db, claim.case_id, deleted_fact_ids)
    return list(deleted_fact_ids)


def _recalculate_case_disputed_facts(db: Session, case_id: str) -> None:
    """사건 내 모든 Fact의 상충(DISPUTED) 상태를 현재 유효한 CONTRADICTS 링크 기준으로 재계산한다."""
    case_facts = db.query(Fact).filter_by(case_id=case_id).all()
    if not case_facts:
        return

    active_contra_links = (
        db.query(EvidenceLink)
        .join(EvidenceClaim, EvidenceLink.claim_id == EvidenceClaim.id)
        .filter(
            EvidenceClaim.case_id == case_id,
            EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
            EvidenceLink.target_type == "FACT",
            EvidenceLink.link_type == "CONTRADICTS",
        )
        .all()
    )
    actively_contradicted_fact_ids: Set[str] = {link.target_id for link in active_contra_links}

    # 또한 승인된 Claim 자체가 active CONTRADICTS 링크를 가진 경우 그 Claim이 지지하는 Fact도 DISPUTED로 본다
    contradicting_claim_ids: Set[str] = {link.claim_id for link in active_contra_links if link.claim_id}
    if contradicting_claim_ids:
        sup_links_of_contradicting = (
            db.query(EvidenceLink)
            .filter(
                EvidenceLink.claim_id.in_(contradicting_claim_ids),
                EvidenceLink.target_type == "FACT",
                EvidenceLink.link_type == "SUPPORTS",
            )
            .all()
        )
        for sl in sup_links_of_contradicting:
            actively_contradicted_fact_ids.add(sl.target_id)

    for fact in case_facts:
        if fact.id in actively_contradicted_fact_ids:
            fact.verification_status = "DISPUTED"
        elif fact.verification_status == "DISPUTED":
            fact.verification_status = _restore_non_disputed_status(fact)


def _rebuild_case_timeline(db: Session, case_id: str) -> None:
    """사건의 현재 Fact 목록을 기준으로 Event 타임라인을 재구축한다."""
    from ai_legal_helper.case_intelligence.timeline import build_timeline_from_facts

    all_facts = db.query(Fact).filter_by(case_id=case_id).all()
    db.query(Event).filter_by(case_id=case_id).delete(synchronize_session=False)
    db.flush()
    for ev in build_timeline_from_facts(all_facts):
        ev.case_id = case_id
        db.add(ev)


def process_evidence_review(
    db: Session,
    claim_id: str,
    action: str,
    new_statement: Optional[str] = None,
    review_reason: Optional[str] = None,
    expected_case_id: Optional[str] = None,
    expected_evidence_id: Optional[str] = None,
) -> EvidenceReview:
    """EvidenceClaim에 대한 사용자의 리뷰 액션(APPROVE, EDIT, REJECT)을 원자적 트랜잭션으로 처리한다.

    Args:
        db: 데이터베이스 세션.
        claim_id: 검토 대상 EvidenceClaim UUID.
        action: 리뷰 액션 ('APPROVE', 'EDIT', 'REJECT').
        new_statement: EDIT 액션 시 수정된 진술 문자열.
        review_reason: 검토 사유 메모.
        expected_case_id: 소유권 검증을 위한 요청 경로의 사건 ID (선택).
        expected_evidence_id: 소유권 검증을 위한 요청 경로의 증거 문서 ID (선택).

    Returns:
        EvidenceReview: 생성된 리뷰 이력 레코드.

    Raises:
        ValueError: Claim 미존재, 소유권 불일치, 잘못된 액션/인자 입력 시 발생.
    """
    try:
        claim = db.query(EvidenceClaim).filter_by(id=claim_id).with_for_update().first()
        if not claim:
            raise ValueError(f"Claim {claim_id} not found.")

        if expected_case_id and claim.case_id != expected_case_id:
            raise ValueError("해당 증거 주장이 요청된 사건(case_id)에 속하지 않습니다.")
        if expected_evidence_id and claim.evidence_id != expected_evidence_id:
            raise ValueError("해당 증거 주장이 요청된 증거 문서(evidence_id)에 속하지 않습니다.")

        case = db.query(Case).filter_by(id=claim.case_id).with_for_update().first()
        if not case:
            raise ValueError(f"Case {claim.case_id} not found.")

        previous_status = claim.review_status
        previous_statement = claim.statement

        if action == "REJECT":
            claim.review_status = "REJECTED"
            if claim.assertion_status == "CONTRADICTION_CANDIDATE":
                claim.assertion_status = "DOCUMENT_STATES"
            new_statement = None
            change_type = "CLAIM_REJECTED"
        elif action == "EDIT":
            if not new_statement or not new_statement.strip():
                raise ValueError("new_statement is required for EDIT action.")
            new_statement = new_statement.strip()
            claim.review_status = "EDITED"
            claim.statement = new_statement
            change_type = "CLAIM_EDITED"
        elif action == "APPROVE":
            claim.review_status = "APPROVED"
            change_type = "CLAIM_APPROVED"
            new_statement = claim.statement
        else:
            raise ValueError(f"Unknown action {action}")

        # 1) 이전 Claim 상태가 남긴 EvidenceLink 및 단독 지지 Fact 정리
        deleted_fact_ids = _cleanup_previous_claim_effects(
            db=db,
            claim=claim,
            previous_statement=previous_statement,
            action=action,
            new_statement=new_statement,
        )

        # 2) Case Revision 기록 (Optimistic Locking 버전 증가)
        case.version += 1
        revision = CaseRevision(
            case_id=case.id,
            version=case.version,
            change_type=change_type,
            change_summary=f"Evidence claim {action}: {review_reason or ''}",
            changed_entity_ids={"claim_id": claim.id, "deleted_fact_ids": deleted_fact_ids},
        )
        db.add(revision)
        db.flush()

        # 3) Review 감사 이력 기록
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

        # 4) 승인(APPROVE) 또는 수정(EDIT)된 경우 구조화 슬롯 갱신, 상충 검증 및 Fact 승격
        if claim.review_status in ["APPROVED", "EDITED"]:
            doc = db.query(EvidenceDocument).filter_by(id=claim.evidence_id).first()
            span_ids = [s.id for s in (claim.spans or [])]

            # EDIT 시에는 수정된 문장에서 슬롯을 새로 추론하고, APPROVE 시에는 기존 추출 슬롯을 활용
            claim_slots = build_structured_slots(
                statement=claim.statement,
                claim_type=claim.claim_type,
                subject=None if action == "EDIT" else claim.subject_key,
                predicate=None if action == "EDIT" else claim.predicate_key,
                scope=claim.scope,
                temporal_context=None if action == "EDIT" else claim.temporal_context,
                evidence_id=claim.evidence_id,
                document_name=doc.original_filename if doc else None,
                source_span_ids=span_ids,
            )
            claim.subject_key = claim_slots.subject_key
            claim.predicate_key = claim_slots.predicate_key
            claim.scope = claim_slots.scope
            claim.temporal_context = claim_slots.temporal_context
            claim.structured_slots = claim_slots.model_dump()

            existing_facts = db.query(Fact).filter_by(case_id=case.id).all()
            facts_by_id = {f.id: f for f in existing_facts}
            norm_stmt = "".join((claim.statement or "").split())

            # 자기 자신과 동일한 진술의 Fact는 상충 비교 대상에서 제외
            comparison_facts = [
                f for f in existing_facts
                if not (f.source_ref == claim.evidence_id and "".join((f.statement or "").split()) == norm_stmt)
            ]

            eval_res = evaluate_claim_conflicts(
                statement=claim.statement,
                existing_facts=comparison_facts,
                claim_type=claim.claim_type,
                subject=claim.subject_key,
                predicate=claim.predicate_key,
                scope=claim.scope,
                temporal_context=claim.temporal_context,
                evidence_id=claim.evidence_id,
                document_name=doc.original_filename if doc else None,
                source_span_ids=span_ids,
                claim_id=claim.id,
                enable_llm_verification=None,
            )
            verified_contradictions = eval_res["contradictions"]
            potential_conflicts = eval_res.get("potential_conflicts", [])
            verified_consistent = eval_res["consistent"]

            if verified_contradictions:
                claim.assertion_status = "CONTRADICTION_CANDIDATE"
                for c_dec in verified_contradictions:
                    conflicting_fact = facts_by_id.get(c_dec.target_fact_id)
                    if not conflicting_fact:
                        continue
                    conflicting_fact.verification_status = "DISPUTED"
                    db.add(
                        EvidenceLink(
                            evidence_id=claim.evidence_id,
                            claim_id=claim.id,
                            target_type="FACT",
                            target_id=conflicting_fact.id,
                            link_type="CONTRADICTS",
                        )
                    )
            else:
                if claim.assertion_status == "CONTRADICTION_CANDIDATE":
                    claim.assertion_status = "DOCUMENT_STATES"
                for p_dec in potential_conflicts:
                    if p_dec.target_fact_id in facts_by_id:
                        db.add(
                            EvidenceLink(
                                evidence_id=claim.evidence_id,
                                claim_id=claim.id,
                                target_type="FACT",
                                target_id=p_dec.target_fact_id,
                                link_type="POTENTIAL_CONFLICT",
                            )
                        )

            ver_status, src_type = derive_fact_trust_status(
                claim.assertion_status,
                has_conflict=bool(verified_contradictions),
            )

            matched_fact = next(
                (f for f in existing_facts if "".join((f.statement or "").split()) == norm_stmt),
                None,
            )
            primary_date = claim_slots.normalized_dates[0] if claim_slots.normalized_dates else None

            if matched_fact:
                target_fact = matched_fact
                if ver_status == "DISPUTED":
                    target_fact.verification_status = "DISPUTED"
                if primary_date and not target_fact.occurred_at:
                    target_fact.occurred_at = primary_date
            else:
                target_fact = Fact(
                    case_id=case.id,
                    statement=claim.statement,
                    fact_type=claim.claim_type,
                    confidence=claim.confidence,
                    source_type=src_type,
                    source_ref=claim.evidence_id,
                    occurred_at=primary_date,
                    verification_status=ver_status,
                )
                db.add(target_fact)
                db.flush()

            revision.changed_entity_ids = {
                "claim_id": claim.id,
                "fact_id": target_fact.id,
                "deleted_fact_ids": deleted_fact_ids,
            }

            # 자기 자신의 Fact에 대한 SUPPORTS EvidenceLink 생성
            db.add(
                EvidenceLink(
                    evidence_id=claim.evidence_id,
                    claim_id=claim.id,
                    target_type="FACT",
                    target_id=target_fact.id,
                    link_type="SUPPORTS",
                )
            )

            # 다중 증거 교차 지지(CONSISTENT): 다른 문서의 기존 Fact와 정규화 금액/일자가 일치하면 교차 SUPPORTS 연결
            seen_sup_ids = {target_fact.id}
            for cons_dec in verified_consistent:
                if cons_dec.target_fact_id in seen_sup_ids:
                    continue
                seen_sup_ids.add(cons_dec.target_fact_id)
                db.add(
                    EvidenceLink(
                        evidence_id=claim.evidence_id,
                        claim_id=claim.id,
                        target_type="FACT",
                        target_id=cons_dec.target_fact_id,
                        link_type="SUPPORTS",
                    )
                )

        # 5) 사건 전체 Fact의 DISPUTED 상태 재계산 및 타임라인(Event) 재구축
        db.flush()
        _recalculate_case_disputed_facts(db, case.id)
        _rebuild_case_timeline(db, case.id)

        # 6) Neo4j 동기화 큐 등록
        from ai_legal_helper.database.graph_sync_worker import queue_sync_task

        queue_sync_task(db, case.id)

        db.commit()
        db.refresh(review)
        return review
    except Exception:
        db.rollback()
        raise
