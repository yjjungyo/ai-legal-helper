# -*- coding: utf-8 -*-
"""Verified GraphRAG case evidence pack: short source spans, not whole documents.

Only paths already validated by validate_graph_paths may enter this function.
It rechecks PostgreSQL claim approval and document ownership, then retrieves
the exact EvidenceSpan text. This module never makes legal-effect judgments.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from ai_legal_helper.database.models import (
    EvidenceClaim, EvidenceDocument, EvidenceSpan, EvidenceSpanClaimLink,
)


def build_verified_graph_source_pack(
    db: Session,
    case_id: str,
    validated_paths: List[Dict[str, Any]],
    *,
    max_spans: int = 24,
    max_chars_per_span: int = 1800,
) -> List[Dict[str, Any]]:
    if not validated_paths:
        return []
    approved = {"APPROVED", "EDITED"}
    sources: List[Dict[str, Any]] = []
    seen = set()
    for path in validated_paths:
        if len(sources) >= max_spans:
            break
        span_id = str(path.get("span_id") or "")
        claim_id = str(path.get("claim_id") or "")
        if not span_id or not claim_id or (span_id, claim_id) in seen:
            continue
        row = db.query(EvidenceSpan, EvidenceClaim, EvidenceDocument).join(
            EvidenceDocument, EvidenceSpan.evidence_id == EvidenceDocument.id,
        ).join(
            EvidenceSpanClaimLink, EvidenceSpanClaimLink.span_id == EvidenceSpan.id,
        ).join(
            EvidenceClaim, EvidenceClaim.id == EvidenceSpanClaimLink.claim_id,
        ).filter(
            EvidenceSpan.id == span_id,
            EvidenceClaim.id == claim_id,
            EvidenceClaim.case_id == case_id,
            EvidenceDocument.case_id == case_id,
            EvidenceDocument.status == "APPROVED",
            EvidenceClaim.evidence_id == EvidenceDocument.id,
            EvidenceClaim.review_status.in_(tuple(approved)),
        ).first()
        if not row:
            continue
        span, claim, document = row
        excerpt = str(span.text_excerpt or "").strip()
        if not excerpt:
            continue
        # Never silently truncate a span that is needed to understand the claim.
        if len(excerpt) > max_chars_per_span:
            continue
        filename = str(getattr(document, "original_filename", None)
                       or getattr(document, "filename", None)
                       or getattr(document, "document_name", None) or document.id)
        sources.append({
            "source_id": filename,
            "source_type": "CASE_EVIDENCE",
            "title": filename,
            "document_name": filename,
            "filename": filename,
            "file_name": filename,
            "file": filename,
            "content": excerpt,
            "evidence_id": document.id,
            "document_id": document.id,
            "span_id": span.id,
            "claim_id": claim.id,
            "retrieval_method": "VERIFIED_GRAPH_EXACT_SPAN",
        })
        seen.add((span_id, claim_id))
    return sources
