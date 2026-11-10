"""Regression coverage for single citation-audit reuse."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_legal_helper" / "agents"


def _function(file, name):
    module = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    return next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == name)


def test_verification_passes_precomputed_audit_to_qa():
    function = _function("verification.py", "run_verification")
    calls = [
        n for n in ast.walk(function)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "check_deterministic_qa"
    ]
    assert len(calls) == 1
    kwargs = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    assert kwargs["citation_audit"] == "audit"


def test_qa_supports_precomputed_audit_and_standalone_fallback():
    function = _function("qa_checker.py", "check_deterministic_qa")
    assert "citation_audit" in function.args.kwonlyargs[0].arg
    assignments = [
        n for n in ast.walk(function)
        if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "audit" for t in n.targets
        )
    ]
    assert len(assignments) == 1
    expression = ast.unparse(assignments[0].value)
    assert "citation_audit if citation_audit is not None else audit_citations_and_claims" in expression
