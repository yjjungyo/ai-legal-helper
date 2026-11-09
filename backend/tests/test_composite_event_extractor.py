"""LLM composite event extraction boundary regression tests."""
import pytest
from ai_legal_helper.case_intelligence.composite_event_extractor import extract_composite_event_candidates


def event(**updates):
    result = dict(
        case_id="case-1", event_type="COMMUNICATION",
        summary="Tenant requested return of deposit",
        actions=["requested deposit return"], modality="REQUESTED",
        supporting_claim_ids=["c1"], supporting_span_ids=["s1"],
    )
    result.update(updates)
    return result


def run(output, status="APPROVED", case="case-1"):
    return extract_composite_event_candidates(
        case_id="case-1",
        reviewed_claims=[{"id": "c1", "case_id": case, "review_status": status,
                          "statement": "Tenant requested deposit return"}],
        spans=[{"id": "s1", "case_id": "case-1", "text": "Please return my deposit"}],
        claim_span_links={"c1": {"s1"}},
        generate_json=lambda system, payload: output,
    )


def test_reviewed_grounded_event_is_candidate_not_approved():
    result = run({"events": [event()]})
    assert len(result.candidates) == 1
    assert result.review_required
    assert not result.rejected


def test_unreviewed_claim_is_not_sent_to_model():
    called = []
    result = extract_composite_event_candidates(
        case_id="case-1",
        reviewed_claims=[{"id": "c1", "case_id": "case-1", "review_status": "REJECTED"}],
        spans=[{"id": "s1", "case_id": "case-1"}],
        claim_span_links={"c1": {"s1"}},
        generate_json=lambda *args: called.append(True),
    )
    assert not called
    assert not result.candidates


def test_foreign_case_candidate_is_rejected():
    result = run({"events": [event(case_id="case-2")]})
    assert not result.candidates
    assert len(result.rejected) == 1


def test_hallucinated_span_id_is_rejected():
    result = run({"events": [event(supporting_span_ids=["made-up"])]})
    assert not result.candidates
    assert len(result.rejected) == 1


def test_bad_response_shape_is_rejected():
    with pytest.raises(ValueError, match="events array"):
        run({"unexpected": []})
