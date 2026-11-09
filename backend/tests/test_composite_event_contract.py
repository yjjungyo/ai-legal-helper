"""Regression tests for composite event referential grounding."""
import pytest

from ai_legal_helper.case_intelligence.composite_event import (
    CompositeEventCandidate,
    GroundingError,
    validate_event_grounding,
)


def candidate(**overrides):
    data = dict(
        case_id="case-1", event_type="COMMUNICATION",
        summary="Tenant requested return during a call",
        actions=["requested deposit return"],
        modality="REQUESTED",
        supporting_claim_ids=["claim-1"], supporting_span_ids=["span-1"],
    )
    data.update(overrides)
    return CompositeEventCandidate(**data)


def grounding(c, *, status="APPROVED", case_id="case-1", links=None):
    validate_event_grounding(
        c,
        claims_by_id={"claim-1": {"case_id": case_id, "review_status": status}},
        spans_by_id={"span-1": {"case_id": "case-1"}},
        claim_span_links={"claim-1": {"span-1"} if links is None else links},
    )


def test_approved_claim_and_linked_span_pass():
    grounding(candidate())


@pytest.mark.parametrize("status", ["PENDING", "REJECTED", None])
def test_unapproved_claim_rejected(status):
    with pytest.raises(GroundingError, match="not reviewed"):
        grounding(candidate(), status=status)


def test_foreign_case_claim_rejected():
    with pytest.raises(GroundingError, match="cross-case"):
        grounding(candidate(), case_id="case-2")


def test_unlinked_span_rejected():
    with pytest.raises(GroundingError, match="not linked"):
        grounding(candidate(), links=set())


def test_event_requires_atomic_provenance():
    with pytest.raises(ValueError):
        candidate(supporting_claim_ids=[])


def test_duplicate_provenance_rejected():
    with pytest.raises(ValueError):
        candidate(supporting_span_ids=["span-1", "span-1"])
