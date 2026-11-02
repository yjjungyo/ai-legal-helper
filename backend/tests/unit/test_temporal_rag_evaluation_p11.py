# -*- coding: utf-8 -*-
"""P11 시나리오 한 사건 1회·미측정 분리·정확도/성능 집계 검증."""
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluation" / "temporal_rag_eval.py"
spec = importlib.util.spec_from_file_location("p11_temporal_eval", SCRIPT)
assert spec and spec.loader
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


def gold():
    return [
        {"scenario_id": "FX-1", "question": "가상 개정법 시행일?", "expected_temporal_status": "NOT_APPLICABLE"},
        {"scenario_id": "FX-2", "question": "적용례 확인?", "expected_temporal_status": "UNCONFIRMED"},
    ]


def run(sid, status, *, system="LEGALAGENT", latency_ms=1000, reviewed=None):
    return {
        "system": system,
        "scenario_id": sid, "run_id": f"{system}:{sid}",
        "temporal_status": status,
        "retrieved_sources": [{"source_id": "OFFICIAL:1:100:제3조:abc"}],
        "cited_sources": [{"source_id": "OFFICIAL:1:100:제3조:abc"}],
        "latency_ms": latency_ms,
        "input_tokens": 100,
        "output_tokens": 200,
        "manual_legal_correct": reviewed,
        "manual_unsafe": False,
    }


def test_no_results_means_not_measured_not_zero_latency():
    summary = evaluator.evaluate_system(gold(), [], "LEGALAGENT")
    assert summary["measured_count"] == 0
    assert summary["missing_count"] == 2
    assert summary["latency_ms_p50"] is None
    assert summary["input_tokens_sum"] is None
    assert summary["temporal_status_accuracy"] is None
    assert summary["manual_legal_accuracy"] is None


def test_exact_temporal_pass_manual_review_and_latency():
    rows = [
        run("FX-1", "NOT_APPLICABLE", reviewed=True, latency_ms=200),
        run("FX-2", "APPLICABLE", reviewed=False, latency_ms=800),
    ]
    summary = evaluator.evaluate_system(gold(), rows, "LEGALAGENT")
    assert summary["temporal_status_accuracy"] == .5
    assert summary["manual_legal_accuracy"] == .5
    assert summary["citation_id_integrity"] == 1
    assert summary["latency_ms_p50"] == 500
    assert summary["latency_ms_p95"] == 770
    assert summary["input_tokens_sum"] == 200
    assert summary["output_tokens_sum"] == 400


def test_duplicate_scenario_run_is_rejected_for_one_case_one_count():
    one = run("FX-1", "NOT_APPLICABLE")
    with pytest.raises(ValueError, match="DUPLICATE_SCENARIO_RUN"):
        evaluator.evaluate_system(gold(), [one, one], "LEGALAGENT")


def test_fabricated_citation_not_counted_as_grounded():
    one = run("FX-1", "NOT_APPLICABLE")
    one["cited_sources"] = [{"source_id": "FAKE"}]
    summary = evaluator.evaluate_system(gold(), [one], "LEGALAGENT")
    assert summary["citation_id_integrity"] == 0


def test_missing_manual_review_is_not_automatic_success():
    one = run("FX-1", "NOT_APPLICABLE")
    summary = evaluator.evaluate_system(gold(), [one], "LEGALAGENT")
    assert summary["manual_review_count"] == 0
    assert summary["manual_legal_accuracy"] is None


def test_unmeasured_abc_is_marked_incomplete_without_claims():
    output = evaluator.compare_systems(gold(), [
        run("FX-1", "NOT_APPLICABLE", reviewed=True),
    ])
    assert output["full_abc_comparison_ready"] is False
    assert output["results"]["LLMCHAT"]["measured_count"] == 0
    assert output["results"]["LEGALAGENT"]["missing_count"] == 1
    md = evaluator.to_markdown(output)
    assert "LLMCHAT" in md and "LLMRAG" in md and "LEGALAGENT" in md


@pytest.mark.parametrize("field,bad", [
    ("latency_ms", -1), ("input_tokens", True), ("output_tokens", "500"),
])
def test_invalid_measurement_does_not_pollute_kpis(field, bad):
    one = run("FX-1", "NOT_APPLICABLE")
    one[field] = bad
    with pytest.raises(ValueError, match="INVALID_MEASUREMENT"):
        evaluator.evaluate_system(gold(), [one], "LEGALAGENT")


def test_fixture_has_no_claim_of_real_law_review():
    path = Path(__file__).resolve().parents[1] / "fixtures" / "temporal_rag_p11_fixture_gold.jsonl"
    items = evaluator.read_jsonl(path)
    assert len(items) >= 10
    assert all(x["fixture_only"] and not x["legal_reviewed"] for x in items)
    assert len(evaluator.validate_gold(items)) == len(items)
