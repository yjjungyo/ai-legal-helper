# -*- coding: utf-8 -*-
"""Evidence-grounded composite event contract.

A composite event describes a coherent occurrence supported by approved atomic
claims. It is NOT a legal finding and does not replace the existing timeline Event.
This module has no DB writes or consultation side effects.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, Field, model_validator


class EventParticipant(BaseModel):
    party_id: Optional[str] = None
    role: str = Field(min_length=1)
    name: Optional[str] = None


class CompositeEventCandidate(BaseModel):
    case_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    participants: List[EventParticipant] = Field(default_factory=list)
    actions: List[str] = Field(min_length=1)
    occurred_at: Optional[str] = None
    referenced_effective_date: Optional[str] = None
    modality: Literal[
        "OBSERVED", "REPORTED", "REQUESTED", "PROPOSED", "ACKNOWLEDGED",
        "AGREED", "DENIED", "DISPUTED", "UNKNOWN"
    ] = "REPORTED"
    certainty: Literal["SUPPORTED", "DISPUTED", "UNCERTAIN"] = "UNCERTAIN"
    supporting_claim_ids: List[str] = Field(min_length=1)
    supporting_span_ids: List[str] = Field(min_length=1)
    unresolved_questions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_references(self) -> "CompositeEventCandidate":
        for field in ("supporting_claim_ids", "supporting_span_ids"):
            refs = getattr(self, field)
            if any(not ref.strip() for ref in refs) or len(refs) != len(set(refs)):
                raise ValueError(f"{field} must contain unique non-empty IDs")
        return self


class GroundingError(ValueError):
    """Candidate refers to unreviewed, foreign-case or unlinked evidence."""


def validate_event_grounding(
    candidate: CompositeEventCandidate,
    *,
    claims_by_id: Dict[str, Dict[str, Any]],
    spans_by_id: Dict[str, Dict[str, Any]],
    claim_span_links: Dict[str, Set[str]],
) -> None:
    """Check provenance IDs against trusted DB-derived lookup maps.

    This checks *referential* grounding only. Semantic entailment of the summary
    must be evaluated separately against the cited spans before approval.
    """
    for claim_id in candidate.supporting_claim_ids:
        claim = claims_by_id.get(claim_id)
        if not claim or str(claim.get("case_id")) != candidate.case_id:
            raise GroundingError(f"unknown or cross-case claim: {claim_id}")
        if claim.get("review_status") not in {"APPROVED", "EDITED"}:
            raise GroundingError(f"claim not reviewed: {claim_id}")
    linked: Set[str] = set()
    for claim_id in candidate.supporting_claim_ids:
        linked.update(claim_span_links.get(claim_id, set()))
    for span_id in candidate.supporting_span_ids:
        span = spans_by_id.get(span_id)
        if not span or str(span.get("case_id")) != candidate.case_id:
            raise GroundingError(f"unknown or cross-case span: {span_id}")
        if span_id not in linked:
            raise GroundingError(f"span not linked to cited claim: {span_id}")
