"""Temporal verification snapshot consistency regression tests (not executed yet)."""
from ai_legal_helper.legal_knowledge.temporal_verification import evaluate_temporal_answer_gate


def _snapshot(date="2026-11-01", decision_date="2026-11-01"):
    return {
        "event": {"selected": {"date": date, "event_type": "CONTRACT_SIGNED"}},
        "decisions": [{
            "status": "APPLICABLE",
            "source_id": "official-1",
            "article": "제1조",
            "event_date": decision_date,
            "event_type": "CONTRACT_SIGNED",
        }],
    }


def test_matching_snapshot_retains_applicability():
    gate = evaluate_temporal_answer_gate(
        "개정법 적용 여부", "제1조는 적용됩니다.", [],
        temporal_resolution=_snapshot(),
    )
    assert gate.decisions[0]["status"] == "APPLICABLE"


def test_mismatched_event_date_fails_closed():
    gate = evaluate_temporal_answer_gate(
        "개정법 적용 여부", "제1조는 적용됩니다.", [],
        temporal_resolution=_snapshot(decision_date="2026-10-31"),
    )
    assert gate.decisions[0]["status"] == "UNCONFIRMED"
    assert gate.decisions[0]["reason_code"] == "TEMPORAL_SNAPSHOT_INCONSISTENT"


def test_missing_event_selection_fails_closed():
    snapshot = _snapshot()
    snapshot["event"]["selected"] = None
    gate = evaluate_temporal_answer_gate(
        "개정법 적용 여부", "제1조는 적용됩니다.", [],
        temporal_resolution=snapshot,
    )
    assert gate.decisions[0]["status"] == "UNCONFIRMED"
