"""Regression guard for Verification's non-invasive decision trace.

This test intentionally does not invoke an LLM or a database.
"""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "ai_legal_helper" / "agents" / "verification.py"


def _run_verification():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    return next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "run_verification")


def test_verification_retains_both_original_pass_normalization_paths():
    node = _run_verification()
    text = ast.unparse(node)
    assert "coverage_complete and consistency_complete" in text
    assert "has_supported_core_claims and has_no_defects" in text
    assert "result.status = 'PASS'" in text
    assert "result.status = 'REVISE'" in text


def test_decision_trace_records_llm_and_final_verdict():
    text = ast.unparse(_run_verification())
    for key in (
        "initial_llm_status = result.status",
        "initial_llm_reason_code = result.reason_code",
        "verification_decision_trace",
        "llm_status",
        "llm_reason_code",
        "final_status",
        "final_reason_code",
        "revision_instructions",
        "missing_legal_issues",
    ):
        assert key in text


def test_technical_verification_failure_stays_insufficient():
    text = ast.unparse(_run_verification())
    assert "'status': 'INSUFFICIENT'" in text
    assert "'reason_code': 'VERIFICATION_ERROR'" in text
    assert "'recommended_action': 'SAFE_FALLBACK'" in text
