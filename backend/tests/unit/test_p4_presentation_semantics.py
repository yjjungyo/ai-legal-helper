"""P4 verified claim semantics: statements and inferences must not become certified facts."""
import hashlib

from ai_legal_helper.presentation.semantics import classify_claim
from ai_legal_helper.presentation.builder import build_consultation_presentation


def test_classification_is_conservative():
    assert classify_claim("CASE_FACT", "VERIFIED_FACT") == "FACT"
    assert classify_claim("CASE_FACT", "USER_STATEMENT") == "USER_STATEMENT"
    assert classify_claim("USER_STATEMENT", "VERIFIED_FACT") == "USER_STATEMENT"
    assert classify_claim("CASE_FACT", "INFERENCE") == "INFERENCE"
    assert classify_claim("CASE_INFERENCE", "VERIFIED_FACT") == "INFERENCE"
    assert classify_claim("CASE_FACT", "EVIDENCE_NEEDED") == "UNCERTAINTY"
    assert classify_claim("LEGAL_APPLICATION", "CONFLICTED") == "UNCERTAINTY"
    assert classify_claim("LEGAL_RULE", None) == "LEGAL_RULE"
    assert classify_claim("LEGAL_APPLICATION", None) == "LEGAL_APPLICATION"
    assert classify_claim("RECOMMENDATION", None) == "ACTION"
    assert classify_claim("UNKNOWN", "VERIFIED_FACT") == "OTHER"


def test_grounded_presentation_claim_has_exact_semantics():
    answer = "가압류 등기 확인 자료가 추가로 필요합니다."
    verification = {
        "status": "PASS",
        "verified_answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "claims": [
            {"claim": answer, "claim_type": "CASE_FACT", "fact_status": "EVIDENCE_NEEDED",
             "grounding_status": "SUPPORTED", "source_ids": ["SOURCE-A", "missing-source"]},
        ],
    }
    result = build_consultation_presentation(
        answer=answer, verification_result=verification,
        verification_status="PASS", answer_status="DELIVERED",
        sources=[{"source_id": "SOURCE-A", "source_type": "CASE_EVIDENCE",
                  "original_filename": "E10_등기열람메모.txt", "evidence_id": "doc-uuid"}],
    )
    assert result is not None
    assert result.verification_binding == "HASH_MATCHED"
    assert len(result.claims) == 1
    assert result.claims[0].semantic_type == "UNCERTAINTY"
    assert result.claims[0].source_binding == "SOURCE_LINKED"
    assert result.claims[0].source_refs == ["SOURCE-A"]
    assert "".join(block.markdown for block in result.blocks) == answer


def test_unlinked_claim_is_never_marked_source_linked():
    text = "송금했다고 진술했습니다."
    result = build_consultation_presentation(
        answer=text, verification_result={
            "status": "PASS", "claims": [
                {"claim": text, "claim_type": "USER_STATEMENT", "fact_status": "USER_STATEMENT",
                 "grounding_status": "SUPPORTED", "source_ids": ["missing"]},
            ],
        }, verification_status="PASS", answer_status="CAUTIONARY", sources=[],
    )
    assert result is not None
    assert result.claims[0].semantic_type == "USER_STATEMENT"
    assert result.claims[0].source_binding == "NOT_LINKED"


def test_unsupported_claim_never_becomes_presentation_claim():
    text = "보증금 전액 회수가 확정되었습니다."
    result = build_consultation_presentation(
        answer=text, verification_result={"status": "PASS", "claims": [
            {"claim": text, "claim_type": "CASE_FACT", "fact_status": "VERIFIED_FACT",
             "grounding_status": "UNSUPPORTED", "source_ids": ["SOURCE-A"]},
        ]},
        verification_status="PASS", answer_status="DELIVERED",
        sources=[{"source_id": "SOURCE-A", "source_type": "CASE_EVIDENCE"}],
    )
    assert result is not None
    assert result.claims == []
