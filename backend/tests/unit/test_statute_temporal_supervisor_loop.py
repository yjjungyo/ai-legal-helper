"""Supervisor 검증 후 라우팅 루프 차단 및 QA Checker 정규식 성능 단위 테스트.

OpenLaw 검색 실패 또는 법령 부칙 미확보로 인한 WITHHELD 판정 시,
불필요한 revise -> verification 무한/반복 루프를 차단하고 즉시 insufficient 노드로
안전 종료되는지 검증한다. 또한 qa_checker의 ReDoS(지수 백트래킹) 방지를 검증한다.
"""

import time
import pytest
from ai_legal_helper.agents.qa_checker import UNCONFIRMED_TERMINATION_PATTERNS
from ai_legal_helper.workflows.legal_workflow import supervisor_verification_decision
from ai_legal_helper.workflows.state import LegalState


def test_qa_checker_regex_redos_prevention():
    """긴 법률 설명 문장에서도 정규식이 지수 백트래킹 없이 100ms 이내에 즉시 수행되는지 검증."""
    # 과거 catastrophic backtracking을 유발하던 구조의 긴 문장 (매칭되지 않는 끝단)
    long_sentence = (
        "2026년 11월 1일에 체결된 임대차계약의 경우 개정 시행령 제12조의2에 따른 "
        "임대차계약 신고 시 관리비 및 전기 수도료 등 임차인 부담 비용의 금액과 산정방식을 "
        "구체적으로 기재하여 관할 지방자치단체장에게 성실하게 신고하여야 할 행정적 주의의무가 부과될 수 있습니다."
    )
    start_time = time.perf_counter()
    for pat in UNCONFIRMED_TERMINATION_PATTERNS:
        _ = pat.search(long_sentence)
    elapsed = time.perf_counter() - start_time

    # 100ms 이내 완료 검증 (과거 112초 소요 결함 방지)
    assert elapsed < 0.1, f"Regex search took too long: {elapsed:.4f}s"


def test_supervisor_verification_decision_blocks_revise_loop_on_missing_statute():
    """법령 원문/부칙 미확보로 인한 WITHHELD 시 외부 검색 후 revise 루프를 차단하고 insufficient로 직행하는지 검증."""
    state: LegalState = {
        "question": "등록 민간임대주택 2026.10.27 개정 시행령 부칙 적용 여부 질문",
        "hitl_executed": True,
        "statute_search_count": 1,
        "revision_count": 0,
        "candidate_laws": ["민간임대주택에 관한 특별법 시행령"],
        "retrieved_sources": [],
        "warnings": ["개정 법령의 부칙(시행일·적용례) 원문이 검색 출처에 없습니다."],
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "issue_results": [
                {
                    "issue_id": "ISSUE_GENERAL_ANALYSIS",
                    "issue_title": "개정 시행령 적용 여부",
                    "status": "NEEDS_LEGAL_SOURCE",
                    "missing_statutes": ["민간임대주택에 관한 특별법 시행령"],
                    "reason_code": "LEGAL_SOURCE_MISSING",
                }
            ],
            "claims": [],
            "citation_audit": {},
            "warnings": ["개정 법령의 부칙(시행일·적용례) 원문이 검색 출처에 없습니다."],
        },
    }

    decision = supervisor_verification_decision(state)
    assert decision == "insufficient", f"Expected 'insufficient' but got '{decision}'"


def test_supervisor_verification_decision_allows_revise_for_normal_revisions():
    """법령 출처 부재가 아닌 일반 문맥 보강 요구 시에는 정상적으로 revise로 라우팅되는지 검증."""
    state: LegalState = {
        "question": "임대차계약 해지 통지 효력 발생 시점 질문",
        "hitl_executed": False,
        "statute_search_count": 0,
        "revision_count": 0,
        "candidate_laws": [],
        "retrieved_sources": [
            {
                "source_id": "STATUTE-001",
                "statute_name": "주택임대차보호법",
                "article": "제6조",
                "content": "임대차기간 끝나기 6개월 전부터 2개월 전까지",
            }
        ],
        "warnings": [],
        "verification_result": {
            "status": "REVISE",
            "reason_code": "ANSWER_REVISION_REQUIRED",
            "claims": [
                {
                    "claim_text": "주택임대차보호법 제6조에 따라 계약이 종료됩니다.",
                    "claim_type": "LEGAL_RULE",
                    "grounding_status": "SUPPORTED",
                }
            ],
            "citation_audit": {},
            "warnings": [],
        },
    }

    decision = supervisor_verification_decision(state)
    assert decision == "revise", f"Expected 'revise' but got '{decision}'"
