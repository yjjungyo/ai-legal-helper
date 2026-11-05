# -*- coding: utf-8 -*-
"""P8 기계식 시행일 최종 검증 게이트 및 LangGraph 차단 회귀."""
import json
from unittest.mock import patch

from ai_legal_helper.legal_knowledge.temporal_verification import (
    evaluate_temporal_answer_gate, apply_temporal_gate_to_verification,
)
from ai_legal_helper.workflows.legal_workflow import (
    verification_condition, verification_node, revise_node,
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


def addendum_source():
    return {
        "source_type": "STATUTE", "source_id": "A:200", "law_id": "L1",
        "version_id": "200", "statute_name": "가상 계약법 시행령",
        "article": "부칙", "content": (
            "제2조(적용례) 제36조 개정규정은 이 영 시행 이후 "
            "체결하거나 갱신 또는 변경하는 계약부터 적용한다."
        ),
        "addendum_id": "200:9999:0",
    }


def review_answer(prompt):
    payload = json.loads(prompt.split("\n", 1)[1])
    answer = payload["answer"]
    bad = answer == BAD
    return json.dumps({
        "verdict": "CONTRADICTED" if bad else "SUPPORTED",
        "claim_quote": answer,
        "source_quote": "이 영 시행 이후",
        "explanation": "사건일과 부칙 시점에 따른 검토",
    })


def gate_for(answer, status="NOT_APPLICABLE"):
    return evaluate_temporal_answer_gate(
        QUESTION, answer, [source(), addendum_source()],
        temporal_resolution=result(status),
        review_invoke_fn=review_answer,
    )


def result(status="NOT_APPLICABLE"):
    return {
        "event": {"status": "RESOLVED",
                  "selected": {"date": "2026-11-01", "event_type": "CONTRACT_SIGNED"}},
        "decisions": [{
            "source_id": "S:200", "law_id": "L1", "version_id": "200",
            "article": "제36조", "status": status,
            "event_date": "2026-11-01", "event_type": "CONTRACT_SIGNED",
            "reason_code": "BEFORE_ARTICLE_EFFECTIVE_DATE",
        }],
    }


def test_future_amendment_positive_application_is_blocked():
    gate = gate_for(BAD)
    assert gate.status == "BLOCK"
    assert "TEMPORAL_SEMANTIC_CONTRADICTION" in gate.reason_codes
    assert gate.affected_source_ids == ("S:200",)


def test_explicit_old_vs_future_distinction_is_allowed():
    gate = gate_for(GOOD)
    assert gate.status == "PASS"


def test_realistic_draft_with_negative_future_and_caution_passes():
    """트레이스 ab3cd359 재현: '아직 아닙니다/시행 전/보기 어렵습니다/최종 확인' 표현 시 PASS."""
    realistic_answer = (
        "네, 다만 2026년 11월 1일 체결 계약에는 아직 아닙니다. "
        "2026.10.27. 개정 시행령은 관리비 산정방식을 추가했지만, 공포 후 6개월 경과일이 시행일이므로 "
        "2026.11.1.에는 아직 시행 전입니다. 따라서 현행 시행 전 규정 기준으로는 해당 비용까지 법정 신고사항이라고 보기 어렵습니다. "
        "실제 신고 전 관할 지자체 입력항목을 최종 확인하십시오."
    )
    gate = gate_for(realistic_answer)
    assert gate.status == "PASS"
    assert not gate.reason_codes


def test_unconfirmed_addendum_does_not_falsely_prove_conflict():
    gate = evaluate_temporal_answer_gate(
        QUESTION, BAD, [source()], temporal_resolution=result("UNCONFIRMED"),
    )
    assert gate.status == "CAUTION"
    assert "TEMPORAL_INTERPRETATION_UNCONFIRMED" in gate.reason_codes


def test_cautious_unconfirmed_answer_remains_caution_not_verified_pass():
    gate = evaluate_temporal_answer_gate(
        QUESTION, CAUTIOUS, [source()], temporal_resolution=result("UNCONFIRMED"),
    )
    assert gate.status == "CAUTION"


def test_missing_official_law_evidence_cannot_support_positive_answer():
    gate = evaluate_temporal_answer_gate(
        QUESTION, BAD, [],
    )
    assert gate.status == "CAUTION"
    assert gate.reason_codes


def test_general_civil_law_question_keeps_previous_path():
    gate = evaluate_temporal_answer_gate(
        "민법 제6조는 무엇인가요?", "네, 처분을 허락한 범위에서 처분 가능합니다.",
        [source()],
    )
    assert gate.status == "NOT_REQUIRED"


def test_guard_routes_proven_semantic_contradiction_for_revision():
    gate = gate_for(BAD)
    output = apply_temporal_gate_to_verification({"status": "PASS"}, gate)
    assert output["status"] == "REVISE"
    assert output["reason_code"] == "TEMPORAL_SEMANTIC_CONTRADICTION"
    assert output["temporal_gate"]["status"] == "BLOCK"


def test_caution_never_becomes_full_pass():
    gate = evaluate_temporal_answer_gate(
        QUESTION, CAUTIOUS, [source()], temporal_resolution=result("UNCONFIRMED"),
    )
    output = apply_temporal_gate_to_verification({"status": "PASS"}, gate)
    assert output["status"] == "REVISE"
    assert output["reason_code"] == "TEMPORAL_SEMANTIC_REVIEW_REQUIRED"


def test_temporal_block_precedes_issue_level_partial_finalize():
    next_node = verification_condition({
        "verification_result": {
            "status": "REVISE",
            "reason_code": "TEMPORAL_SEMANTIC_CONTRADICTION",
            "issue_results": [{"status": "VERIFIED", "issue_title": "법령"}],
            "temporal_gate": {"status": "BLOCK"},
        },
        "issue_results": [{"status": "VERIFIED"}],
        "hilt_executed": True,
    })
    assert next_node == "revise"


def test_temporal_block_precedes_document_mode_pass():
    next_node = verification_condition({
        "answer_mode": "DOCUMENT",
        "verification_result": {
            "status": "REVISE", "reason_code": "TEMPORAL_SEMANTIC_CONTRADICTION",
            "temporal_gate": {"status": "BLOCK"},
        },
    })
    assert next_node == "revise"


def test_document_verification_result_is_downgraded_after_llm_pass():
    with patch(
        "ai_legal_helper.legal_knowledge.temporal_verification._semantic_review",
        return_value=({"verdict": "CONTRADICTED", "claim_quote": BAD,
                       "source_quote": "이 영 시행 이후"}, "COMPLETE"),
    ), patch(
        "ai_legal_helper.workflows.legal_workflow.verify_answer",
        return_value={
            "verification_result": {"status": "PASS", "reason_code": "NONE"},
            "retrieved_sources": [source(), addendum_source()],
        },
    ):
        out = verification_node({
            "answer_mode": "DOCUMENT", "question": QUESTION, "draft_answer": BAD,
            "retrieved_sources": [source(), addendum_source()],
            "temporal_resolution": result(),
        })
    assert out["verification_result"]["status"] == "REVISE"
    assert out["verification_result"]["temporal_gate"]["status"] == "BLOCK"


def test_general_verification_result_is_downgraded_after_llm_pass():
    with patch(
        "ai_legal_helper.legal_knowledge.temporal_verification._semantic_review",
        return_value=({"verdict": "CONTRADICTED", "claim_quote": BAD,
                       "source_quote": "이 영 시행 이후"}, "COMPLETE"),
    ), patch(
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
    assert out["verification_result"]["status"] == "REVISE"
    assert out["verification_result"]["reason_code"] == "TEMPORAL_SEMANTIC_CONTRADICTION"



def test_parser_unconfirmed_cannot_destroy_twelve_grounded_pass_claims():
    gate = gate_for(GOOD, "UNCONFIRMED")
    verified = {
        "status": "PASS", "reason_code": "NONE",
        "claims": [
            {"claim_type": "LEGAL_APPLICATION", "grounding_status": "SUPPORTED",
             "source_ids": ["S:200", "A:200"]}
            for _ in range(12)
        ],
    }
    out = apply_temporal_gate_to_verification(
        verified, gate, official_sources_present=True,
    )
    assert out["status"] == "PASS"
    assert out["temporal_review_diagnostic"] == "AUTOMATED_SEMANTIC_REVIEW_INCOMPLETE"


def test_temporal_recheck_preserves_original_answer_verbatim():
    out = revise_node({
        "question": QUESTION, "draft_answer": GOOD,
        "revision_count": 0,
        "verification_result": {"temporal_recheck_only": True},
    })
    assert out["draft_answer"] == GOOD
    assert out["revision_method"] == "TEMPORAL_RECHECK_NO_REWRITE"



def test_unsupported_legal_claims_do_not_pass_on_parser_failure():
    gate = gate_for(GOOD, "UNCONFIRMED")
    result = {
        "status": "PASS", "reason_code": "NONE",
        "claims": [{"claim_type": "LEGAL_APPLICATION",
                    "grounding_status": "SUPPORTED",
                    "source_ids": ["GRAPH:ONLY"]}],
    }
    out = apply_temporal_gate_to_verification(
        result, gate,
        official_sources_present=True,
        official_source_ids=["S:200", "A:200"],
    )
    assert out["status"] == "REVISE"
    assert out["temporal_recheck_only"] is True
    assert out["reason_code"] == "TEMPORAL_SEMANTIC_REVIEW_REQUIRED"
