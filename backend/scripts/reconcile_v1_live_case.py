# -*- coding: utf-8 -*-
"""
라이브 사건 증거 신뢰성 평가 및 사실 확정 복구 스크립트
(backend/scripts/reconcile_v1_live_case.py)

기존에 승인된 EvidenceClaim 및 Fact들에 대해 Evidence Reliability & Fact Adjudication v1.0
엔진을 일괄 적용하여 EvidenceAssessment, FactAdjudication, EvidenceGap, FactComparisonAudit를
안전하고 멱등하게 생성 및 동기화한다.
"""

import sys
import os

# 패스 설정
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import (
    Case,
    EvidenceDocument,
    EvidenceClaim,
    Fact,
    EvidenceAssessment,
    FactAdjudication,
    EvidenceGap,
    FactComparisonAudit,
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


def reconcile_case_reliability_and_adjudications(case_id: str):
    db = SessionLocal()
    try:
        case = db.query(Case).filter_by(id=case_id).first()
        if not case:
            print(f"Case {case_id} not found.")
            return

        docs = {d.id: d for d in db.query(EvidenceDocument).filter_by(case_id=case_id).all()}
        facts = db.query(Fact).filter_by(case_id=case_id).all()
        claims = db.query(EvidenceClaim).filter_by(case_id=case_id).all()

        print(f"=== Reconciling Case {case_id} ===")
        print(f"Documents: {len(docs)}, Facts: {len(facts)}, Claims: {len(claims)}")

        assessments_created = 0
        adjudications_created = 0
        gaps_created = 0

        # 기존 평가/심리/공백 일괄 갱신을 위해 기존 기록 조회
        existing_assess_claims = {
            a.claim_id for a in db.query(EvidenceAssessment).filter_by(case_id=case_id).all() if a.claim_id
        }
        existing_adj_claims = {
            a.claim_id for a in db.query(FactAdjudication).filter_by(case_id=case_id).all() if a.claim_id
        }

        # 승인된 Claim 위주로 평가 및 심리 생성
        for claim in claims:
            doc = docs.get(claim.evidence_id)
            doc_name = doc.original_filename if doc else ""
            span_ids = [s.id for s in (claim.spans or [])]

            prop = extract_semantic_proposition(
                claim.statement or "",
                context={
                    "evidence_id": claim.evidence_id,
                    "claim_id": claim.id,
                    "source_span_ids": span_ids,
                    "document_name": doc_name,
                },
            )

            # 1. EvidenceAssessment
            if claim.id not in existing_assess_claims:
                assess_res = evaluate_evidence_reliability(
                    document_name=doc_name,
                    proposition=prop,
                    document_metadata=doc.metadata_json or {} if doc else {},
                )
                db.add(EvidenceAssessment(
                    case_id=case_id,
                    evidence_id=claim.evidence_id,
                    claim_id=claim.id,
                    proposition_hash=str(hash(claim.statement)),
                    source_authenticity=assess_res.source_authenticity,
                    directness=assess_res.directness,
                    relevance=assess_res.relevance,
                    completeness=assess_res.completeness,
                    temporal_applicability=assess_res.temporal_applicability,
                    corroboration=assess_res.corroboration,
                    provenance_quality=assess_res.provenance_quality,
                    assessment_status=assess_res.assessment_status,
                    reliability_score=assess_res.reliability_score,
                    proof_scope=assess_res.proof_scope,
                    summary=assess_res.summary,
                ))
                assessments_created += 1
            else:
                assess_res = None

            # 2. FactAdjudication
            if claim.review_status in ("APPROVED", "EDITED") and claim.id not in existing_adj_claims:
                norm_c = "".join((claim.statement or "").split())
                comp_facts = [
                    f for f in facts
                    if not (f.source_ref == claim.evidence_id and "".join((f.statement or "").split()) == norm_c)
                ]
                matched_fact = next(
                    (f for f in facts if "".join((f.statement or "").split()) == norm_c),
                    None,
                )

                fact_doc_names = {f.id: docs[f.source_ref].original_filename for f in facts if f.source_ref and f.source_ref in docs}
                adj_res = adjudicate_fact(
                    proposition=prop,
                    candidate_facts=comp_facts,
                    assessment=assess_res,
                    claim_id=claim.id,
                    fact_id=matched_fact.id if matched_fact else None,
                    fact_doc_names=fact_doc_names,
                )

                db.add(FactAdjudication(
                    case_id=case_id,
                    fact_id=matched_fact.id if matched_fact else None,
                    claim_id=claim.id,
                    adjudication_status=adj_res.adjudication_status,
                    primary_relation=adj_res.primary_relation,
                    confidence=adj_res.confidence,
                    adjudication_basis=adj_res.adjudication_basis,
                    supporting_evidence_ids=adj_res.supporting_evidence_ids,
                    contradicting_evidence_ids=adj_res.contradicting_evidence_ids,
                ))
                adjudications_created += 1

                # 3. EvidenceGap
                if adj_res.gap_item:
                    existing_gap = db.query(EvidenceGap).filter_by(
                        case_id=case_id,
                        gap_type=adj_res.gap_item.gap_type,
                    ).first()
                    if not existing_gap:
                        db.add(EvidenceGap(
                            case_id=case_id,
                            claim_id=claim.id,
                            fact_id=matched_fact.id if matched_fact else None,
                            gap_type=adj_res.gap_item.gap_type,
                            target_proposition=adj_res.gap_item.target_proposition,
                            description=adj_res.gap_item.description,
                            recommended_document_types=adj_res.gap_item.recommended_document_types,
                            recommended_action=adj_res.gap_item.recommended_action,
                            priority=adj_res.gap_item.priority,
                            is_resolved=False,
                        ))
                        gaps_created += 1

        db.commit()
        print(f"Reconciliation completed successfully:")
        print(f"  - EvidenceAssessments created: {assessments_created}")
        print(f"  - FactAdjudications created: {adjudications_created}")
        print(f"  - EvidenceGaps created: {gaps_created}")

        # 통계 출력
        total_adj = db.query(FactAdjudication).filter_by(case_id=case_id).all()
        status_counts = {}
        for a in total_adj:
            status_counts[a.adjudication_status] = status_counts.get(a.adjudication_status, 0) + 1
        print(f"Fact Adjudication Summary: {status_counts}")

        total_gaps = db.query(EvidenceGap).filter_by(case_id=case_id).all()
        print(f"Total Evidence Gaps in case: {len(total_gaps)}")
        for g in total_gaps:
            print(f"  - [{g.priority}] {g.gap_type}: {g.target_proposition}")

    finally:
        db.close()


if __name__ == "__main__":
    cid = sys.argv[1] if len(sys.argv) > 1 else "17c5bb1d-183e-450b-ab3e-64ced1e3d70e"
    reconcile_case_reliability_and_adjudications(cid)
