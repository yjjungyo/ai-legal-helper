# -*- coding: utf-8 -*-
"""Read-only PostgreSQL adapter for composite event extraction.

This module deliberately does not invoke an LLM, write events, or mutate a case.
It converts the real ORM schema (Span has evidence_id, not case_id) into the
case-scoped maps required by the provenance validator.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Set

from sqlalchemy.orm import Session

from ai_legal_helper.database.models import (
    EvidenceClaim, EvidenceDocument, EvidenceSpan, EvidenceSpanClaimLink,
)


def load_reviewed_event_inputs(db: Session, case_id: str) -> Dict[str, Any]:
    """Only reviewed claims and their linked spans from this case are exposed."""
    claims = db.query(EvidenceClaim).filter(
        EvidenceClaim.case_id == case_id,
        EvidenceClaim.review_status.in_(("APPROVED", "EDITED")),
    ).all()
    claim_ids = [c.id for c in claims]
    if not claim_ids:
        return {"reviewed_claims": [], "spans": [], "claim_span_links": {}}

    links = db.query(EvidenceSpanClaimLink).filter(
        EvidenceSpanClaimLink.claim_id.in_(claim_ids),
    ).all()
    span_ids = {l.span_id for l in links}
    if not span_ids:
        return {"reviewed_claims": [], "spans": [], "claim_span_links": {}}

    # Join on the owning document, not a nonexistent EvidenceSpan.case_id.
    rows = db.query(EvidenceSpan).join(
        EvidenceDocument, EvidenceSpan.evidence_id == EvidenceDocument.id,
    ).filter(
        EvidenceDocument.case_id == case_id,
        EvidenceSpan.id.in_(span_ids),
    ).all()
    spans_by_id = {s.id: s for s in rows}
    claim_links: Dict[str, Set[str]] = defaultdict(set)
    for link in links:
        if link.span_id in spans_by_id:
            claim_links[link.claim_id].add(link.span_id)

    valid_claims = [c for c in claims if claim_links.get(c.id)]
    valid_ids = {c.id for c in valid_claims}
    valid_spans = set().union(*(claim_links[cid] for cid in valid_ids)) if valid_ids else set()
    return {
        "reviewed_claims": [
            {"id": c.id, "case_id": case_id, "review_status": c.review_status,
             "statement": c.statement, "assertion_status": c.assertion_status}
            for c in valid_claims
        ],
        "spans": [
            {"id": s.id, "case_id": case_id, "text": s.text_excerpt,
             "evidence_id": s.evidence_id}
            for s in rows if s.id in valid_spans
        ],
        "claim_span_links": {cid: claim_links[cid] for cid in valid_ids},
    }
