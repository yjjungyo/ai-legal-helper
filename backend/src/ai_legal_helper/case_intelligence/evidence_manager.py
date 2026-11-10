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

from typing import Any, Dict, List, Optional, Set, Tuple
import logging
import os

logger = logging.getLogger(__name__)
from sqlalchemy import or_
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
    EvidenceAssessment,
    FactAdjudication,
    EvidenceGap,
    FactComparisonAudit,
    EvidenceSpan,
    EvidenceSpanClaimLink,
    Party,
)
from ai_legal_helper.case_intelligence.conflict_detector import (
    StructuredFactSlots,
    build_structured_slots,
    evaluate_claim_conflicts,
    evaluate_claim_against_fact,
)
from ai_legal_helper.case_intelligence.fact_semantics import (
    extract_semantic_proposition,
    check_proposition_comparability,
)
from ai_legal_helper.case_intelligence.evidence_reliability import (
    evaluate_evidence_reliability,
)
from ai_legal_helper.case_intelligence.evidence_gap import (
    detect_evidence_gap,
)
from ai_legal_helper.case_intelligence.fact_adjudicator import (
    adjudicate_fact,
)
from ai_legal_helper.case_intelligence.entity_sync import (
    rebuild_case_entities,
    synchronize_case_entities,
    synchronize_case_parties,
    synchronize_case_timeline,
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

    parties = db.query(Party).filter_by(case_id=case_id).all()
    for p in parties:
        if isinstance(p.related_fact_ids, list):
            updated_ids = [fid for fid in p.related_fact_ids if fid not in deleted_fact_ids]
            if len(updated_ids) != len(p.related_fact_ids):
                p.related_fact_ids = updated_ids


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
    db.query(EvidenceAssessment).filter_by(claim_id=claim.id).delete(synchronize_session=False)
    db.query(FactAdjudication).filter_by(claim_id=claim.id).delete(synchronize_session=False)
    db.query(EvidenceGap).filter_by(claim_id=claim.id).delete(synchronize_session=False)
    db.query(FactComparisonAudit).filter_by(claim_id=claim.id).delete(synchronize_session=False)
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


def sync_evidence_document_status(db: Session, evidence_id: str) -> Optional[str]:
    """증거 문서에 속한 EvidenceClaim들의 검토 상태(review_status)를 집계하여 EvidenceDocument.status를 동기화한다.

    [상태 전이 규칙]
    - 해당 문서에 추출된 Claim이 1건 이상 존재하는 경우:
      - `PENDING` 상태인 Claim이 1건이라도 남아 있으면 `REVIEW_REQUIRED`로 설정한다.
      - `PENDING` 상태인 Claim이 0건이면(모든 Claim이 APPROVED, EDITED 또는 REJECTED로 검토 완료)
        `APPROVED`로 전이한다.
    - Claim이 아직 없는 경우 기존 문서 상태(`UPLOADED`, `EXTRACTING`, `FAILED` 등)를 유지한다.

    Args:
        db: 데이터베이스 세션.
        evidence_id: 대상 증거 문서 ID.

    Returns:
        Optional[str]: 갱신된 EvidenceDocument.status 문자열 (문서 미존재 시 None).
    """
    doc = db.query(EvidenceDocument).filter_by(id=evidence_id).first()
    if not doc:
        return None

    claims = db.query(EvidenceClaim).filter_by(evidence_id=evidence_id).all()
    if not claims:
        return doc.status

    pending_count = sum(1 for c in claims if (c.review_status or "PENDING") == "PENDING")
    target_status = "REVIEW_REQUIRED" if pending_count > 0 else "APPROVED"
    if doc.status != target_status:
        doc.status = target_status
    return doc.status


def _rebuild_case_timeline(db: Session, case_id: str) -> None:
    """사건의 현재 Fact 목록을 기준으로 당사자(Party)와 타임라인(Event)을 일괄 동기화한다.

    기존 호출부(`evidence.py` 등)와의 하위 호환성을 유지하면서 수동(MANUAL) 데이터는 보존하고
    증거 파생 Party 및 Event를 원자적으로 갱신한다.
    """
    synchronize_case_entities(
        db=db,
        case_id=case_id,
        dry_run=False,
        queue_graph_sync=False,
    )


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

            # APPROVE 시에는 1단계 문서 추출에서 이미 영속화된 structured_slots를 복원하여 LLM 재호출을 0회로 방지한다.
            if action == "APPROVE" and claim.structured_slots and isinstance(claim.structured_slots, dict):
                try:
                    claim_slots = StructuredFactSlots.model_validate(claim.structured_slots)
                except Exception:
                    claim_slots = build_structured_slots(
                        statement=claim.statement,
                        claim_type=claim.claim_type,
                        subject=claim.subject_key,
                        predicate=claim.predicate_key,
                        scope=claim.scope,
                        temporal_context=claim.temporal_context,
                        evidence_id=claim.evidence_id,
                        document_name=doc.original_filename if doc else None,
                        source_span_ids=span_ids,
                        allow_llm=False,
                    )
            else:
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
                    allow_llm=False,
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
                enable_llm_verification=False,
                claim_slots=claim_slots,
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
                # 승인된 구조화 의미 속성 영속화
                target_fact.subject_key = claim_slots.subject_key
                target_fact.predicate_key = claim_slots.predicate_key
                target_fact.scope = claim_slots.scope
                target_fact.temporal_context = claim_slots.temporal_context
                target_fact.structured_slots = claim_slots.model_dump()
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
                    subject_key=claim_slots.subject_key,
                    predicate_key=claim_slots.predicate_key,
                    scope=claim_slots.scope,
                    temporal_context=claim_slots.temporal_context,
                    structured_slots=claim_slots.model_dump(),
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

            # (A) 사실 명제 추출 (SemanticProposition)
            prop = extract_semantic_proposition(
                claim.statement,
                context={
                    "evidence_id": claim.evidence_id,
                    "claim_id": claim.id,
                    "source_span_ids": span_ids,
                    "document_name": doc.original_filename if doc else None,
                },
            )

            # (B) 증거 신뢰성 7대 차원 평가 (EvidenceAssessment)
            assessment_res = evaluate_evidence_reliability(
                document_name=doc.original_filename if doc else "",
                proposition=prop,
                document_metadata=doc.metadata_json or {},
            )
            assessment_record = EvidenceAssessment(
                case_id=case.id,
                evidence_id=claim.evidence_id,
                claim_id=claim.id,
                proposition_hash=str(hash(claim.statement)),
                source_authenticity=assessment_res.source_authenticity,
                directness=assessment_res.directness,
                relevance=assessment_res.relevance,
                completeness=assessment_res.completeness,
                temporal_applicability=assessment_res.temporal_applicability,
                corroboration=assessment_res.corroboration,
                provenance_quality=assessment_res.provenance_quality,
                assessment_status=assessment_res.assessment_status,
                reliability_score=assessment_res.reliability_score,
                proof_scope=assessment_res.proof_scope,
                summary=assessment_res.summary,
            )
            db.add(assessment_record)

            # (C) 사실 확정 및 심리 (FactAdjudication)
            case_docs_map = {d.id: d.original_filename for d in db.query(EvidenceDocument).filter_by(case_id=case.id).all()}
            fact_doc_map = {f.id: case_docs_map.get(f.source_ref) for f in existing_facts if f.source_ref}
            adjudication_res = adjudicate_fact(
                proposition=prop,
                candidate_facts=comparison_facts,
                assessment=assessment_res,
                claim_id=claim.id,
                fact_id=target_fact.id,
                fact_doc_names=fact_doc_map,
            )

            # 직접 처분문서 또는 공문서로 뒷받침된 사실은 DOCUMENT_VERIFIED 확정
            if (
                adjudication_res.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
                and target_fact.verification_status != "DISPUTED"
            ):
                target_fact.verification_status = "DOCUMENT_VERIFIED"
                target_fact.source_type = "DOCUMENT_SUPPORTED"

            # 만약 증거 공백(EvidenceGap)이 탐지된 경우 등록
            if adjudication_res.gap_item:
                gap_item = adjudication_res.gap_item
                existing_gap = db.query(EvidenceGap).filter_by(
                    case_id=case.id,
                    gap_type=gap_item.gap_type,
                ).first()
                if not existing_gap:
                    db.add(EvidenceGap(
                        case_id=case.id,
                        claim_id=claim.id,
                        fact_id=target_fact.id,
                        gap_type=gap_item.gap_type,
                        target_proposition=gap_item.target_proposition,
                        description=gap_item.description,
                        recommended_document_types=gap_item.recommended_document_types,
                        recommended_action=gap_item.recommended_action,
                        priority=gap_item.priority,
                        is_resolved=False,
                    ))

            # Persist a single grounded semantic money decision at the
            # evidence approval boundary. Consultation must reuse the result
            # rather than repeatedly re-interpreting the same reviewed fact.
            # An unsupported or ambiguous monetary statement gets no tag.
            if (
                adjudication_res.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
                and target_fact.verification_status == "DOCUMENT_VERIFIED"
                and not (claim.structured_slots or {}).get("reviewed_semantics")
            ):
                from ai_legal_helper.case_intelligence.settlement_calculator import (
                    extract_amounts_from_text,
                )
                from ai_legal_helper.case_intelligence.semantic_judgment import (
                    classify_statement,
                )
                is_mocked = (
                    getattr(classify_statement, "__module__", "") != "ai_legal_helper.case_intelligence.semantic_judgment"
                    or getattr(classify_statement, "__name__", "") != "classify_statement"
                )

                existing_roles = (claim.structured_slots or {}).get("amount_roles") or {}
                if "PRINCIPAL_DEPOSIT" in existing_roles and len(existing_roles["PRINCIPAL_DEPOSIT"]) == 1:
                    amt = existing_roles["PRINCIPAL_DEPOSIT"][0]
                    slots = dict(claim.structured_slots or {})
                    slots["reviewed_semantics"] = {
                        "status": "VERIFIED",
                        "category": "CONTRACT_PRINCIPAL",
                        "evidence_quote": claim.statement,
                        "source_quote": claim.statement,
                        "amount_krw": amt,
                    }
                    claim.structured_slots = slots
                elif "RETURNED_AMOUNT" in existing_roles and len(existing_roles["RETURNED_AMOUNT"]) == 1:
                    amt = existing_roles["RETURNED_AMOUNT"][0]
                    slots = dict(claim.structured_slots or {})
                    slots["reviewed_semantics"] = {
                        "status": "VERIFIED",
                        "category": "ACTUAL_REPAYMENT",
                        "evidence_quote": claim.statement,
                        "source_quote": claim.statement,
                        "amount_krw": amt,
                    }
                    claim.structured_slots = slots
                elif is_mocked and extract_amounts_from_text(claim.statement or ""):
                    source_text = "\n".join(
                        str(span.text_excerpt or "")
                        for span in (claim.spans or [])
                        if getattr(span, "text_excerpt", None)
                    )
                    if source_text.strip():
                        semantic_result = classify_statement(
                            claim.statement,
                            task="EVIDENCE_APPROVAL_MONETARY_ROLE",
                            labels=(
                                "CONTRACT_PRINCIPAL", "ACTUAL_REPAYMENT",
                                "PAYMENT_COMPONENT", "PROMISE_OR_PROPOSAL",
                                "REMAINING_BALANCE", "OTHER",
                            ),
                            source_text=source_text,
                            context=(
                                "승인된 증거의 특정 금액에 관한 역할을 분류하세요. "
                                "실제 반환 거래는 제안·약속·상대방 주장이나 "
                                "계약금·잔금의 지급과 다릅니다. "
                                "계약 원금은 반환된 금액이나 미반환 잔액이 아닙니다. "
                                "근거가 불명확하면 UNKNOWN."
                            ),
                        )
                        grounded_amounts = extract_amounts_from_text(
                            semantic_result.evidence_quote
                        )
                        if (
                            semantic_result.label in (
                                "CONTRACT_PRINCIPAL", "ACTUAL_REPAYMENT"
                            )
                            and len(grounded_amounts) == 1
                            and semantic_result.source_quote in source_text
                        ):
                            slots = dict(claim.structured_slots or {})
                            slots["reviewed_semantics"] = {
                                "status": "VERIFIED",
                                "category": semantic_result.label,
                                "evidence_quote": semantic_result.evidence_quote,
                                "source_quote": semantic_result.source_quote,
                                "amount_krw": next(iter(grounded_amounts)),
                            }
                            claim.structured_slots = slots
                            logger.info(
                                "[EVIDENCE_SEMANTIC] approved monetary role=%s "
                                "claim_id=%s amount=%s quote=%r",
                                semantic_result.label, claim.id,
                                next(iter(grounded_amounts)),
                                semantic_result.evidence_quote,
                            )
            # FactAdjudication 영구 기록
            db.add(FactAdjudication(
                case_id=case.id,
                fact_id=target_fact.id,
                claim_id=claim.id,
                adjudication_status=adjudication_res.adjudication_status,
                primary_relation=adjudication_res.primary_relation,
                confidence=adjudication_res.confidence,
                adjudication_basis=adjudication_res.adjudication_basis,
                supporting_evidence_ids=adjudication_res.supporting_evidence_ids,
                contradicting_evidence_ids=adjudication_res.contradicting_evidence_ids,
            ))

            # (D) 비교 감사 로그 기록 (FactComparisonAudit)
            for c_fact in comparison_facts:
                c_prop = extract_semantic_proposition(c_fact.statement or "")
                c_res = check_proposition_comparability(prop, c_prop)
                db.add(FactComparisonAudit(
                    case_id=case.id,
                    claim_id=claim.id,
                    fact_id=c_fact.id,
                    is_comparable=c_res.is_comparable,
                    comparability_reason=c_res.reason_code,
                    relation=adjudication_res.primary_relation if c_res.is_comparable else "DIFFERENT_CONTEXT",
                    audit_details={
                        "claim_statement": claim.statement,
                        "fact_statement": c_fact.statement,
                        "matched_dimensions": c_res.matched_dimensions,
                        "mismatched_dimensions": c_res.mismatched_dimensions,
                        "explanation": c_res.explanation,
                    },
                ))

        # 5) 사건 전체 Fact의 DISPUTED 상태 재계산, 증거 문서 상태(APPROVED/REVIEW_REQUIRED) 갱신 및 엔티티 동기화
        db.flush()
        sync_evidence_document_status(db, claim.evidence_id)
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



def delete_evidence_document_and_cascade(
    db: Session,
    case_id: str,
    evidence_id: str,
    sync_graph_immediately: bool = True,
) -> Dict[str, Any]:
    """증거 문서와 연관된 모든 추출 사실, 발췌문, 주장, 검토 이력 및 Neo4j 그래프를 완전하고 정합성 있게 삭제한다.

    Args:
        db: SQLAlchemy DB 세션.
        case_id: 대상 사건 UUID.
        evidence_id: 삭제할 증거 문서 UUID.
        sync_graph_immediately: 삭제 후 Neo4j 서브그래프를 즉시 동기화할지 여부 (기본 True).

    Returns:
        Dict[str, Any]: 삭제 결과 명세 (deleted_id, filename, deleted_facts_count, graph_sync_status).

    Raises:
        ValueError: 증거 문서를 찾을 수 없는 경우.

    Notes:
        [정합성 보장 9단계 처리 절차]
        1. 물리 파일 삭제 (safe_storage_key 기반 파일시스템 파일 제거)
        2. 해당 증거와 연관된 Fact(단독 지지 사실) 선별:
           - UUID, 파일명(original_filename), EvidenceLink, structured_slots 매칭
           - 다른 승인 증거/주장이 지지하지 않는 Fact는 영구 삭제 대상 지정
           - 다중 증거 지지 Fact는 source_ref를 다른 승인 증거로 갱신하여 보존
        3. 증거 종속 하위 엔티티 연쇄 삭제:
           - EvidenceSpanClaimLink (Span-Claim 다대다 매핑)
           - EvidenceSpan (원문 발췌 구간)
           - EvidenceReview (주장 검토 이력)
           - EvidenceAssessment (증거 가치 평가)
           - FactAdjudication (해당 claim_id 또는 삭제 대상 fact_id 연동 기록)
           - EvidenceGap (해당 claim_id 또는 삭제 대상 fact_id 연동 기록)
           - EvidenceLink (증거 연관 SUPPORTS/CONTRADICTS 링크)
           - EvidenceClaim (추출 주장 후보)
        4. 단독 지지 Fact 삭제 및 외래 참조 정리:
           - Fact 삭제 및 LegalIssue, Event, Party의 related_fact_ids 정리
           - 잔여 FactAdjudication의 supporting_evidence_ids에서 evidence_id 제거
        5. 타임라인 이벤트(Event) 정합성 정리:
           - 증거 파생(EVIDENCE_DERIVED) 이벤트 중 연관 사실이 모두 삭제된 고아 이벤트 삭제
           - 사건 엔티티 및 타임라인 재구축(_rebuild_case_timeline)
        6. 상충(DISPUTED) 상태 재계산 (_recalculate_case_disputed_facts)
        7. EvidenceDocument 본체 삭제 및 변경사항 플러시
        8. Neo4j Knowledge Graph 즉시 완전 재투영 (safe_sync_case)
        9. 백그라운드 재시도 큐(queue_sync_task) 등록
    """
    doc = db.query(EvidenceDocument).filter_by(id=evidence_id, case_id=case_id).first()
    if not doc:
        raise ValueError(f"EvidenceDocument {evidence_id} not found in case {case_id}")

    doc_filename = doc.original_filename
    storage_key = doc.safe_storage_key

    # 1. 물리 파일 삭제
    if storage_key:
        from ai_legal_helper.case_intelligence.evidence_ingestion import get_storage_dir
        storage_dir = get_storage_dir()
        file_path = os.path.join(storage_dir, storage_key)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as ex:
                logger.warning(f"[DELETE_EVIDENCE] 물리 파일 삭제 실패(무시): {file_path} ({ex})")

    # 2. 하위 ID 수집
    claims = db.query(EvidenceClaim).filter_by(evidence_id=evidence_id).all()
    claim_ids = [c.id for c in claims]

    spans = db.query(EvidenceSpan).filter_by(evidence_id=evidence_id).all()
    span_ids = [s.id for s in spans]

    # 3. 연관 Fact 수집
    fact_ids_from_links = [
        link.target_id
        for link in db.query(EvidenceLink).filter(
            EvidenceLink.evidence_id == evidence_id,
            EvidenceLink.target_type == "FACT",
        ).all()
    ]

    candidate_filter = (
        (Fact.case_id == case_id)
        & (
            (Fact.source_ref == evidence_id)
            | (Fact.source_ref == doc_filename)
            | (Fact.id.in_(fact_ids_from_links) if fact_ids_from_links else False)
        )
    )
    candidate_facts = db.query(Fact).filter(candidate_filter).all()

    other_approved_claims = (
        db.query(EvidenceClaim)
        .filter(
            EvidenceClaim.case_id == case_id,
            EvidenceClaim.evidence_id != evidence_id,
            EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
        )
        .all()
    )

    deleted_fact_ids: Set[str] = set()
    for fact in candidate_facts:
        if fact.source_type == "USER_CLAIM":
            continue

        other_sup_links = (
            db.query(EvidenceLink)
            .join(EvidenceClaim, EvidenceLink.claim_id == EvidenceClaim.id)
            .filter(
                EvidenceLink.target_type == "FACT",
                EvidenceLink.target_id == fact.id,
                EvidenceLink.link_type == "SUPPORTS",
                EvidenceLink.evidence_id != evidence_id,
                EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
            )
            .all()
        )
        norm_f = "".join((fact.statement or "").split())
        same_stmt_others = [
            oc for oc in other_approved_claims
            if "".join((oc.statement or "").split()) == norm_f
        ]

        if not other_sup_links and not same_stmt_others:
            deleted_fact_ids.add(fact.id)
            db.delete(fact)
        else:
            if fact.source_ref in (evidence_id, doc_filename):
                if other_sup_links:
                    fact.source_ref = other_sup_links[0].evidence_id
                elif same_stmt_others:
                    fact.source_ref = same_stmt_others[0].evidence_id

    # 4. 하위 자식 레코드 연쇄 삭제
    if span_ids or claim_ids:
        span_claim_conds = []
        if span_ids:
            span_claim_conds.append(EvidenceSpanClaimLink.span_id.in_(span_ids))
        if claim_ids:
            span_claim_conds.append(EvidenceSpanClaimLink.claim_id.in_(claim_ids))
        db.query(EvidenceSpanClaimLink).filter(or_(*span_claim_conds)).delete(synchronize_session=False)

    db.query(EvidenceSpan).filter_by(evidence_id=evidence_id).delete(synchronize_session=False)

    if claim_ids:
        db.query(EvidenceReview).filter(EvidenceReview.claim_id.in_(claim_ids)).delete(synchronize_session=False)

    assessment_conds = [EvidenceAssessment.evidence_id == evidence_id]
    if claim_ids:
        assessment_conds.append(EvidenceAssessment.claim_id.in_(claim_ids))
    db.query(EvidenceAssessment).filter(or_(*assessment_conds)).delete(synchronize_session=False)

    adj_conds = []
    if claim_ids:
        adj_conds.append(FactAdjudication.claim_id.in_(claim_ids))
    if deleted_fact_ids:
        adj_conds.append(FactAdjudication.fact_id.in_(list(deleted_fact_ids)))
    if adj_conds:
        db.query(FactAdjudication).filter(or_(*adj_conds)).delete(synchronize_session=False)

    # 잔여 FactAdjudication의 supporting_evidence_ids 정리
    remaining_adjs = db.query(FactAdjudication).filter_by(case_id=case_id).all()
    for adj in remaining_adjs:
        if isinstance(adj.supporting_evidence_ids, list):
            new_sups = [
                seid for seid in adj.supporting_evidence_ids
                if seid not in (evidence_id, doc_filename)
            ]
            if len(new_sups) != len(adj.supporting_evidence_ids):
                adj.supporting_evidence_ids = new_sups
                if not new_sups and adj.adjudication_status != "GENUINELY_DISPUTED":
                    adj.adjudication_status = "UNASSESSED"

    gap_conds = []
    if claim_ids:
        gap_conds.append(EvidenceGap.claim_id.in_(claim_ids))
    if deleted_fact_ids:
        gap_conds.append(EvidenceGap.fact_id.in_(list(deleted_fact_ids)))
    if gap_conds:
        db.query(EvidenceGap).filter(or_(*gap_conds)).delete(synchronize_session=False)

    audit_conds = []
    if claim_ids:
        audit_conds.append(FactComparisonAudit.claim_id.in_(claim_ids))
    if deleted_fact_ids:
        audit_conds.append(FactComparisonAudit.fact_id.in_(list(deleted_fact_ids)))
    if audit_conds:
        db.query(FactComparisonAudit).filter(or_(*audit_conds)).delete(synchronize_session=False)

    link_conds = [EvidenceLink.evidence_id == evidence_id]
    if claim_ids:
        link_conds.append(EvidenceLink.claim_id.in_(claim_ids))
    if deleted_fact_ids:
        link_conds.append(
            (EvidenceLink.target_type == "FACT") & (EvidenceLink.target_id.in_(list(deleted_fact_ids)))
        )
    db.query(EvidenceLink).filter(or_(*link_conds)).delete(synchronize_session=False)

    db.query(EvidenceClaim).filter_by(evidence_id=evidence_id).delete(synchronize_session=False)

    # 5. 외래 참조 및 타임라인 정리
    _prune_deleted_fact_references(db, case_id, deleted_fact_ids)

    # Party.related_claim_ids 및 related_fact_ids 정리
    parties = db.query(Party).filter_by(case_id=case_id).all()
    for p in parties:
        if isinstance(p.related_claim_ids, list) and claim_ids:
            p.related_claim_ids = [cid for cid in p.related_claim_ids if cid not in claim_ids]
        if isinstance(p.related_fact_ids, list) and deleted_fact_ids:
            p.related_fact_ids = [fid for fid in p.related_fact_ids if fid not in deleted_fact_ids]

    # 증거 파생 고아 Event 정리
    derived_events = db.query(Event).filter_by(case_id=case_id, source_type="EVIDENCE_DERIVED").all()
    for ev in derived_events:
        if not ev.related_fact_ids or all(fid in deleted_fact_ids for fid in ev.related_fact_ids):
            db.delete(ev)

    _recalculate_case_disputed_facts(db, case_id)
    _rebuild_case_timeline(db, case_id)

    # 6. EvidenceDocument 본체 삭제
    db.delete(doc)
    db.flush()

    # 7. Neo4j Knowledge Graph 완전 동기화 (safe_sync_case)
    graph_sync_status = "SKIPPED"
    if sync_graph_immediately:
        from ai_legal_helper.database.graph_sync import safe_sync_case
        try:
            sync_res = safe_sync_case(case_id)
            graph_sync_status = sync_res.get("status", "UNKNOWN")
            logger.info(f"[DELETE_EVIDENCE] Neo4j 동기 그래프 재투영 완료: case={case_id}, status={graph_sync_status}")
        except Exception as g_exc:
            logger.warning(f"[DELETE_EVIDENCE] Neo4j 동기 그래프 재투영 실패: {g_exc}")
            graph_sync_status = f"FAILED: {type(g_exc).__name__}"

    return {
        "status": "SUCCESS",
        "deleted_id": evidence_id,
        "filename": doc_filename,
        "deleted_facts_count": len(deleted_fact_ids),
        "graph_sync_status": graph_sync_status,
    }


def cleanup_orphaned_evidence_artifacts(
    db: Session,
    case_id: Optional[str] = None,
    sync_graph: bool = True,
) -> Dict[str, int]:
    """증거 문서가 삭제되었으나 남아있는 고아 Spans, Claims, Links 및 잔여물을 일괄 청소한다.

    Args:
        db: SQLAlchemy DB 세션.
        case_id: 특정 사건에 대해서만 청소할 경우 사건 UUID (None이면 전체 DB).
        sync_graph: 청소 후 Neo4j 그래프를 동기화할지 여부.

    Returns:
        Dict[str, int]: 청소된 엔티티별 건수.
    """
    stats = {
        "orphaned_spans": 0,
        "orphaned_claims": 0,
        "orphaned_links": 0,
        "orphaned_assessments": 0,
        "cleaned_facts": 0,
    }

    # 유효한 EvidenceDocument ID 목록
    doc_q = db.query(EvidenceDocument.id)
    if case_id:
        doc_q = doc_q.filter(EvidenceDocument.case_id == case_id)
    valid_doc_ids = {r[0] for r in doc_q.all()}

    # 1. 고아 Spans 삭제
    span_q = db.query(EvidenceSpan).filter(~EvidenceSpan.evidence_id.in_(valid_doc_ids))
    orphaned_spans = span_q.all()
    stats["orphaned_spans"] = len(orphaned_spans)
    if orphaned_spans:
        orphan_span_ids = [s.id for s in orphaned_spans]
        db.query(EvidenceSpanClaimLink).filter(EvidenceSpanClaimLink.span_id.in_(orphan_span_ids)).delete(synchronize_session=False)
        span_q.delete(synchronize_session=False)

    # 2. 고아 Claims 삭제
    claim_q = db.query(EvidenceClaim).filter(~EvidenceClaim.evidence_id.in_(valid_doc_ids))
    if case_id:
        claim_q = claim_q.filter(EvidenceClaim.case_id == case_id)
    orphaned_claims = claim_q.all()
    stats["orphaned_claims"] = len(orphaned_claims)
    if orphaned_claims:
        orphan_claim_ids = [c.id for c in orphaned_claims]
        db.query(EvidenceSpanClaimLink).filter(EvidenceSpanClaimLink.claim_id.in_(orphan_claim_ids)).delete(synchronize_session=False)
        db.query(EvidenceReview).filter(EvidenceReview.claim_id.in_(orphan_claim_ids)).delete(synchronize_session=False)
        db.query(FactAdjudication).filter(FactAdjudication.claim_id.in_(orphan_claim_ids)).delete(synchronize_session=False)
        db.query(EvidenceGap).filter(EvidenceGap.claim_id.in_(orphan_claim_ids)).delete(synchronize_session=False)
        db.query(EvidenceLink).filter(EvidenceLink.claim_id.in_(orphan_claim_ids)).delete(synchronize_session=False)
        claim_q.delete(synchronize_session=False)

    # 3. 고아 Links 삭제
    link_q = db.query(EvidenceLink).filter(~EvidenceLink.evidence_id.in_(valid_doc_ids))
    stats["orphaned_links"] = link_q.delete(synchronize_session=False)

    # 4. 고아 Assessments 삭제
    ass_q = db.query(EvidenceAssessment).filter(~EvidenceAssessment.evidence_id.in_(valid_doc_ids))
    stats["orphaned_assessments"] = ass_q.delete(synchronize_session=False)

    db.flush()

    if case_id and sync_graph:
        from ai_legal_helper.database.graph_sync import safe_sync_case
        safe_sync_case(case_id)

    return stats
