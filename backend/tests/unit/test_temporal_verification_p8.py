# -*- coding: utf-8 -*-
"""P8 기계식 시행일 최종 검증 게이트 및 LangGraph 차단 회귀."""
from unittest.mock import patch

from ai_legal_helper.legal_knowledge.temporal_verification import (
    evaluate_temporal_answer_gate, apply_temporal_gate_to_verification,
)
from ai_legal_helper.workflows.legal_workflow import (
    verification_condition, verification_node,
)


QUESTION = "2026년 11월 1일 계약 체결에 개정 시행령 제36조가 적용되나요?"
BAD = "네. 2026년 11월 1일 체결한 계약에도 개정 시행령 제36조가 적용됩니다."
GOOD = "아니요. 개정 규정은 아직 적용되지 않습니다. 2027년 시행 이후 체결 시 적용됩니다."
CAUTIOUS = "정확한 적용례와 경과조치 확인이 필요하므로 신법 적용 여부는 단정할 수 없습니다."


def source(version="200", effective="2027-04-28"):
    return {
        "source_type": "STATUTE", "source_id": f"S:{version}", "law_id": "L1",
        "version_id": version, "statute_name": "가상 계약법 시행령", "article": "제36조",
        "content": "제36조 신고 관련 법령 본문",
        "article_effective_date": effective,
        "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
        "version_relation": "NEXT_EFFECTIVE_CANDIDATE",
        "version_lookup_status": "HISTORY_COMPLETE",
    }


def result(status="NOT_APPLICABLE"):
    return {
        "event": {"status": "RESOLVED",
                  "selected": {"date": "2026-11-01", "event_type": "CONTRACT_SIGNED"}},
        "decisions": [{
            "source_id": "S:200", "law_id": "L1", "version_id": "200",
            "article": "제36조", "status": status,
            "reason_code": "BEFORE_ARTICLE_EFFECTIVE_DATE",
        }],
    }


def test_future_amendment_positive_application_is_blocked():
    gate = evaluate_temporal_answer_gate(
        QUESTION, BAD, [source()], temporal_resolution=result(),
    )
    assert gate.status == "BLOCK"
    assert "FUTURE_AMENDMENT_MISAPPLIED" in gate.reason_codes
    assert gate.affected_source_ids == ("S:200",)


def test_explicit_old_vs_future_distinction_is_allowed():
    gate = evaluate_temporal_answer_gate(
        QUESTION, GOOD, [source()], temporal_resolution=result(),
    )
    assert gate.status == "PASS"


def test_realistic_draft_with_negative_future_and_caution_passes():
    """트레이스 ab3cd359 재현: '아직 아닙니다/시행 전/보기 어렵습니다/최종 확인' 표현 시 PASS."""
    realistic_answer = (
        "네, 다만 2026년 11월 1일 체결 계약에는 아직 아닙니다. "
        "2026.10.27. 개정 시행령은 관리비 산정방식을 추가했지만, 공포 후 6개월 경과일이 시행일이므로 "
        "2026.11.1.에는 아직 시행 전입니다. 따라서 현행 시행 전 규정 기준으로는 해당 비용까지 법정 신고사항이라고 보기 어렵습니다. "
        "실제 신고 전 관할 지자체 입력항목을 최종 확인하십시오."
    )
    gate = evaluate_temporal_answer_gate(
        QUESTION, realistic_answer, [source()], temporal_resolution=result(),
    )
    assert gate.status == "PASS"
    assert not gate.reason_codes


def test_unconfirmed_addendum_categorical_positive_is_blocked():
    gate = evaluate_temporal_answer_gate(
        QUESTION, BAD, [source()], temporal_resolution=result("UNCONFIRMED"),
    )
    assert gate.status == "BLOCK"
    assert "APPLICABILITY_PROVISION_UNCONFIRMED" in gate.reason_codes


def test_cautious_unconfirmed_answer_remains_caution_not_verified_pass():
    gate = evaluate_temporal_answer_gate(
        QUESTION, CAUTIOUS, [source()], temporal_resolution=result("UNCONFIRMED"),
    )
    assert gate.status == "CAUTION"


def test_missing_official_law_evidence_cannot_support_positive_answer():
    gate = evaluate_temporal_answer_gate(
        QUESTION, BAD, [],
    )
    assert gate.status == "BLOCK"
    assert "TEMPORAL_OFFICIAL_EVIDENCE_MISSING" in gate.reason_codes


def test_general_civil_law_question_keeps_previous_path():
    gate = evaluate_temporal_answer_gate(
        "민법 제6조는 무엇인가요?", "네, 처분을 허락한 범위에서 처분 가능합니다.",
        [source()],
    )
    assert gate.status == "NOT_REQUIRED"


def test_guard_downgrades_llm_pass_and_preserves_reason():
    gate = evaluate_temporal_answer_gate(
        QUESTION, BAD, [source()], temporal_resolution=result(),
    )
    output = apply_temporal_gate_to_verification({"status": "PASS"}, gate)
    assert output["status"] == "INSUFFICIENT"
    assert output["reason_code"] == "TEMPORAL_APPLICABILITY_UNCONFIRMED"
    assert output["temporal_gate"]["status"] == "BLOCK"


def test_caution_never_becomes_full_pass():
    gate = evaluate_temporal_answer_gate(
        QUESTION, CAUTIOUS, [source()], temporal_resolution=result("UNCONFIRMED"),
    )
    output = apply_temporal_gate_to_verification({"status": "PASS"}, gate)
    assert output["status"] == "REVISE"
    assert output["reason_code"] == "TEMPORAL_REVIEW_REQUIRED"


def test_temporal_block_precedes_issue_level_partial_finalize():
    next_node = verification_condition({
        "verification_result": {
            "status": "PASS",
            "issue_results": [{"status": "VERIFIED", "issue_title": "법령"}],
            "temporal_gate": {"status": "BLOCK"},
        },
        "issue_results": [{"status": "VERIFIED"}],
        "hilt_executed": True,
    })
    assert next_node == "insufficient"


def test_temporal_block_precedes_document_mode_pass():
    next_node = verification_condition({
        "answer_mode": "DOCUMENT",
        "verification_result": {
            "status": "PASS", "temporal_gate": {"status": "BLOCK"},
        },
    })
    assert next_node == "insufficient"


def test_document_verification_result_is_downgraded_after_llm_pass():
    with patch(
        "ai_legal_helper.workflows.legal_workflow.verify_answer",
        return_value={
            "verification_result": {"status": "PASS", "reason_code": "NONE"},
            "retrieved_sources": [source()],
        },
    ):
        out = verification_node({
            "answer_mode": "DOCUMENT", "question": QUESTION, "draft_answer": BAD,
            "retrieved_sources": [source()],
            "temporal_resolution": result(),
        })
    assert out["verification_result"]["status"] == "INSUFFICIENT"
    assert out["verification_result"]["temporal_gate"]["status"] == "BLOCK"


def test_general_verification_result_is_downgraded_after_llm_pass():
    with patch(
        "ai_legal_helper.agents.verification.run_verification",
        return_value={
            "status": "PASS", "reason_code": "NONE", "candidate_laws": [],
            "warnings": [], "citation_audit": {"verified_sources": [source()]},
        },
    ):
        out = verification_node({
            "question": QUESTION, "draft_answer": BAD,
            "retrieved_sources": [source()],
            "temporal_resolution": result(),
        })
    assert out["verification_result"]["status"] == "INSUFFICIENT"
    assert out["verification_result"]["reason_code"] == "TEMPORAL_APPLICABILITY_UNCONFIRMED"
