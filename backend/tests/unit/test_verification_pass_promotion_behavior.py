"""Execute the production PASS-promotion block against controlled verdicts.

These are characterization tests, not a replacement for end-to-end LLM tests.
"""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[2] / "src" / "ai_legal_helper" / "agents" / "verification.py"


def _promotion_block():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "run_verification")
    matches = [
        n for n in ast.walk(function)
        if isinstance(n, ast.If)
        and "coverage_satisfied and has_supported_core_claims and has_no_defects" in ast.unparse(n.test)
        and "result.status == 'REVISE'" in ast.unparse(n.test)
    ]
    assert len(matches) == 1, "PASS promotion policy moved or changed; review this test"
    return compile(ast.fix_missing_locations(ast.Module(body=[matches[0]], type_ignores=[])), str(SOURCE), "exec")


def _execute(*, status="REVISE", reason="ANSWER_REVISION_REQUIRED",
             supported=True, defects=False, coverage=True,
             revision_instructions=None, missing_legal_issues=None):
    result = SimpleNamespace(
        status=status,
        reason_code=reason,
        recommended_action="REVISE_DRAFT",
        revision_instructions=list(revision_instructions or []),
        missing_legal_issues=list(missing_legal_issues or []),
    )
    env = {
        "result": result,
        "coverage_satisfied": coverage,
        "has_supported_core_claims": supported,
        "has_no_defects": not defects,
        "logger": logging.getLogger(__name__),
    }
    exec(_promotion_block(), env)
    return result


def test_supported_revise_is_normalized_to_pass():
    verdict = _execute()
    assert (verdict.status, verdict.reason_code, verdict.recommended_action) == (
        "PASS", "NONE", "FINALIZE"
    )


def test_unverified_claims_or_missing_coverage_block_promotion():
    assert _execute(defects=True).status == "REVISE"
    assert _execute(supported=False).status == "REVISE"
    assert _execute(coverage=False).status == "REVISE"


def test_non_allowlisted_reason_is_not_overridden():
    assert _execute(reason="CITATION_INVALID").status == "REVISE"
    assert _execute(reason="EVIDENCE_CONFLICT").status == "REVISE"


def test_insufficient_does_not_get_promoted():
    assert _execute(status="INSUFFICIENT").status == "INSUFFICIENT"


def test_characterize_remaining_revision_instructions():
    # Current policy intentionally does not use revision_instructions as a gate.
    # Do not change this expectation without checking whether instructions are stale.
    verdict = _execute(revision_instructions=["추가 확인 필요"])
    assert verdict.status == "PASS"
    assert verdict.revision_instructions == ["추가 확인 필요"]


def test_characterize_remaining_missing_legal_issues():
    # This documents a potential risk, not a confirmed real-world legal defect:
    # the later promotion block itself does not inspect missing_legal_issues.
    verdict = _execute(missing_legal_issues=["핵심 법률 쟁점"])
    assert verdict.status == "PASS"
    assert verdict.missing_legal_issues == ["핵심 법률 쟁점"]


def test_characterize_first_and_second_pass_gates_together():
    """Show that a missing legal issue blocks the first gate but not the second.

    This is a reproducible policy gap, not evidence of an actual wrong answer.
    """
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    function = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "run_verification")
    first = [
        n for n in ast.walk(function)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.BoolOp)
        and "not result.missing_legal_issues" in ast.unparse(n.test)
        and "coverage_complete and consistency_complete" in ast.unparse(n.test)
        and "result.status == 'REVISE'" in ast.unparse(n.test)
    ]
    assert len(first) == 1
    second = [
        n for n in ast.walk(function)
        if isinstance(n, ast.If)
        and "coverage_satisfied and has_supported_core_claims and has_no_defects" in ast.unparse(n.test)
        and "result.status == 'REVISE'" in ast.unparse(n.test)
    ]
    assert len(second) == 1

    result = SimpleNamespace(
        status="REVISE", reason_code="ANSWER_REVISION_REQUIRED",
        recommended_action="REVISE_DRAFT", claims=[object()],
        contradictions=[], missing_legal_issues=["핵심 법률 쟁점"],
        missing_issues=[], warnings=[],
    )
    env = {
        "result": result, "coverage_complete": True,
        "consistency_complete": True, "defective_claims": [],
        "malformed_claims": [], "same_role_date_conflict": False,
        "coverage_satisfied": True, "has_supported_core_claims": True,
        "has_no_defects": True, "logger": logging.getLogger(__name__),
    }
    nodes = [first[0], second[0]]
    code = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SOURCE), "exec")
    env["has_no_defects"] = not result.missing_legal_issues
    exec(code, env)
    assert result.status == "REVISE"
    assert result.missing_legal_issues == ["핵심 법률 쟁점"]
