"""최종 답변 단계에서 검색 상태 안내를 누락하지 않는지 확인."""
import hashlib
from unittest.mock import patch

from ai_legal_helper.workflows.document_consultation import finish_answer


def _state(status, draft="검증된 답변"):
    return {
        "statute_search_status": status,
        "draft_answer": draft,
        "retrieved_sources": [],
        "verification_result": {
            "status": "PASS",
            "verified_answer_sha256": hashlib.sha256(draft.encode()).hexdigest(),
            "source_manifest": {"content_sha256": "same"},
        },
    }


def test_api_error_never_delivers_prior_pass():
    state = _state("API_ERROR")
    with patch("ai_legal_helper.workflows.document_consultation.document_sources", return_value=[]), \
         patch("ai_legal_helper.workflows.document_consultation.format_grounding_sources",
               return_value=("", {"content_sha256": "same"})), \
         patch("ai_legal_helper.workflows.document_consultation.validate_document_snapshot"):
        result = finish_answer(state)
    assert result["final_disposition"] == "WITHHELD"
    assert "API 호출 중 오류" in result["final_answer"]


def test_missing_notice_never_delivers_pass():
    state = _state("PARTIAL_SUCCESS")
    with patch("ai_legal_helper.workflows.document_consultation.document_sources", return_value=[]), \
         patch("ai_legal_helper.workflows.document_consultation.format_grounding_sources",
               return_value=("", {"content_sha256": "same"})), \
         patch("ai_legal_helper.workflows.document_consultation.validate_document_snapshot"):
        result = finish_answer(state)
    assert result["final_disposition"] == "WITHHELD"


def test_verified_notice_pass_is_preserved():
    draft = "**안내:** 공식 법령 검색에서 일부를 확인하지 못했습니다.\\n\\n근거 기반 답변"
    state = _state("PARTIAL_SUCCESS", draft)
    with patch("ai_legal_helper.workflows.document_consultation.document_sources", return_value=[]), \
         patch("ai_legal_helper.workflows.document_consultation.format_grounding_sources",
               return_value=("", {"content_sha256": "same"})), \
         patch("ai_legal_helper.workflows.document_consultation.validate_document_snapshot"):
        result = finish_answer(state)
    assert result["final_disposition"] == "DELIVERED"
    assert result["final_answer"] == draft
