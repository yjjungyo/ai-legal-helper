"""초안 작성 전 법령 충분성 검사 분기 회귀 테스트."""
from ai_legal_helper.workflows.pre_synthesis_coverage import coverage_next, check_legal_coverage


def test_general_mode_skips_precoverage():
    assert check_legal_coverage({"answer_mode": "GENERAL"}) == {}


def test_document_mode_runs_once():
    assert check_legal_coverage({
        "answer_mode": "DOCUMENT_GROUNDED", "pre_coverage_checked": True
    }) == {}


def test_missing_law_routes_to_approval():
    state = {
        "statute_search_phase": "PRE_ANALYSIS",
        "verification_result": {
            "reason_code": "LEGAL_SOURCE_MISSING",
            "candidate_laws": ["임의의법률"],
        },
        "hilt_executed": False,
    }
    assert coverage_next(state) == "statute_search_approval"


def test_approved_or_completed_search_does_not_repeat():
    state = {
        "statute_search_phase": "PRE_ANALYSIS",
        "verification_result": {
            "reason_code": "LEGAL_SOURCE_MISSING",
            "candidate_laws": ["임의의법률"],
        },
        "hilt_executed": True,
    }
    assert coverage_next(state) == "legal_evidence_bundle"
