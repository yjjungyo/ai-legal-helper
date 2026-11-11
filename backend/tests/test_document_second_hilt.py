"""검증 중 신규 법령 발견 시 재승인 라우팅 회귀 테스트."""
from unittest.mock import patch

from ai_legal_helper.workflows.document_consultation import next_verification_step


def test_second_hitl_for_new_law_after_first_approval():
    state = {
        "draft_answer": "초안",
        "question": "임대차 보증금 반환과 손해배상",
        "verification_result": {
            "status": "REVISE",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "legal_search_requests": [
                {"law_name": "민법", "articles": ["제390조"],
                 "issue": "손해배상", "question_part": "임대차 보증금 반환과 손해배상"}
            ],
        },
        "approval_status": "APPROVED",
        "approved_statute_laws": ["주택임대차보호법"],
        "hitl_executed": True,
        "statute_search_count": 1,
    }
    assert next_verification_step(state) == "statute_search_approval"


def test_existing_approval_skips_reapproval():
    state = {
        "draft_answer": "초안",
        "question": "임대차 보증금 반환과 손해배상",
        "verification_result": {
            "status": "REVISE",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "legal_search_requests": [
                {"law_name": "민법", "articles": ["제390조"],
                 "issue": "손해배상", "question_part": "임대차 보증금 반환과 손해배상"}
            ],
        },
        "approval_status": "APPROVED",
        "approved_statute_laws": ["주택임대차보호법", "민법"],
        "hitl_executed": True,
        "statute_search_count": 1,
    }
    assert next_verification_step(state) == "execute_statute_search"
