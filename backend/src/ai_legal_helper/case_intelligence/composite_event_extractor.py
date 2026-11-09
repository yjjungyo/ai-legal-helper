# -*- coding: utf-8 -*-
"""LLM-assisted candidate grouping, with strict provenance checks.

The injected generate_json callback is the existing project's LLM adapter.
No DB/Neo4j writes happen here. Candidates require separate semantic review.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Set

from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.composite_event import (
    CompositeEventCandidate, GroundingError, validate_event_grounding,
)


class CompositeEventBatch(BaseModel):
    events: List[CompositeEventCandidate] = Field(default_factory=list)


class CompositeEventExtractionResult(BaseModel):
    candidates: List[CompositeEventCandidate] = Field(default_factory=list)
    rejected: List[str] = Field(default_factory=list)
    review_required: bool = True


SYSTEM_INSTRUCTIONS = """You extract coherent events from reviewed evidence claims.
Use only the supplied claims and linked evidence spans. Never add an unsupported
date, person, action, receipt, agreement, legal conclusion or fact.
Group claims describing ONE occurrence or communication into a composite event.
Preserve distinct modalities: a request is not an agreement; acknowledging
receipt is not accepting legal termination; proposal is not performance.
Separate the date an act occurred from the future date it mentions.
Keep mutually inconsistent claims distinct and mark uncertainty.
Cite exact supporting_claim_ids and supporting_span_ids supplied in the input.
Return JSON: {"events": [CompositeEventCandidate-shaped objects]}.
If evidence is insufficient, return {"events": []}.
Every candidate remains unapproved until semantic and human review.
"""


def extract_composite_event_candidates(
    *,
    case_id: str,
    reviewed_claims: List[Dict[str, Any]],
    spans: List[Dict[str, Any]],
    claim_span_links: Dict[str, Set[str]],
    generate_json: Callable[[str, Dict[str, Any]], Dict[str, Any]],
    max_events: int = 20,
) -> CompositeEventExtractionResult:
    """Generate candidates from reviewed evidence, then check all reference IDs.

    Callers must pass maps sourced from PostgreSQL with verified case ownership.
    This function checks reference grounding, NOT semantic entailment.
    """
    allowed_claims = {
        str(c["id"]): c for c in reviewed_claims
        if c.get("id") and c.get("case_id") == case_id
        and c.get("review_status") in {"APPROVED", "EDITED"}
    }
    allowed_spans = {
        str(s["id"]): s for s in spans
        if s.get("id") and s.get("case_id") == case_id
    }
    links = {
        claim_id: set(span_ids) & set(allowed_spans)
        for claim_id, span_ids in claim_span_links.items()
        if claim_id in allowed_claims
    }
    if not allowed_claims or not allowed_spans:
        return CompositeEventExtractionResult()

    payload = {
        "case_id": case_id,
        "claims": [
            {"id": c["id"], "statement": c.get("statement", ""),
             "assertion_status": c.get("assertion_status"),
             "linked_span_ids": sorted(links.get(cid, set()))}
            for cid, c in allowed_claims.items()
        ],
        "spans": [
            {"id": s["id"], "text": s.get("text", "")}
            for s in allowed_spans.values()
            if any(s["id"] in linked for linked in links.values())
        ],
        "max_events": max_events,
    }
    raw = generate_json(SYSTEM_INSTRUCTIONS, payload)
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), list):
        raise ValueError("LLM must return an object with events array")
    if len(raw["events"]) > max_events:
        raise ValueError("LLM exceeded max_events")

    accepted: List[CompositeEventCandidate] = []
    rejected: List[str] = []
    for index, item in enumerate(raw["events"]):
        try:
            candidate = CompositeEventCandidate.model_validate(item)
            if candidate.case_id != case_id:
                raise GroundingError("candidate case mismatch")
            validate_event_grounding(
                candidate, claims_by_id=allowed_claims,
                spans_by_id=allowed_spans, claim_span_links=links,
            )
            accepted.append(candidate)
        except (ValueError, TypeError) as exc:
            rejected.append(f"event[{index}]: {type(exc).__name__}: {exc}")
    return CompositeEventExtractionResult(candidates=accepted, rejected=rejected)
