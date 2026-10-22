# -*- coding: utf-8 -*-
"""증거 정확성 강화 및 Claim 단위 검증 단위 테스트 모듈 (Phase 3).

[역할]
Phase 3에서 구현된 실제 증거 ID 검증, 임의 가상 증거번호 차단, 사실 상태(FactStatus) 구분,
적응형 Claim 단위 검증(Adaptive Claim-level Scope), 및 동적 판단 유보 안내를 검증한다.

[주요 테스트 항목]
1. `test_unregistered_arbitrary_evidence_numbers_blocked`: DB에 등록되지 않은 임의 가상 증거번호('증거 1', '증거 7호', '[증거 2]')가 차단되고 REVISE 강등되는지 검증 (T05)
2. `test_registered_evidence_numbers_accepted`: 실제 등록된 증거 출처가 존재할 때 정상 검증되는지 검증
3. `test_sanitize_unverified_citations_cleans_fake_evidence_numbers`: 정화 시 임의 증거번호가 안전하게 제거/치환되는지 검증
4. `test_claim_level_adaptive_scope_recommendation_not_blocked`: 실무 조치 권고(RECOMMENDATION) 및 사용자 진술(USER_STATEMENT)에 대해 법령 조문 부재를 이유로 부당 차단되지 않는지 검증
5. `test_core_legal_rule_missing_source_triggers_revision`: 핵심 법률 규범(LEGAL_RULE, LEGAL_APPLICATION)의 근거 부재 시 엄격히 REVISE가 작동하는지 검증
6. `test_insufficient_node_dynamic_guidance_and_no_system_keywords`: 판단 유보 시 고객용 답변에 WITHHELD, INSUFFICIENT 등 시스템 내부 코드가 노출되지 않고 사건별 맞춤형 서류가 동적 안내되는지 검증 (T06)
"""

import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from ai_legal_helper.agents.verification import (
    audit_citations_and_claims,
    sanitize_unverified_citations,
    run_verification,
    ClaimVerification,
)
from ai_legal_helper.workflows.legal_workflow import insufficient_node


def test_unregistered_arbitrary_evidence_numbers_blocked():
    """T05: 실제 DB에 등록되지 않은 임의의 가상 증거번호('증거 1', '증거 7호', '[증거 2]')가 감지되면 CITATION_INVALID 및 REVISE로 강등되는지 검증한다."""
    # 출처에는 법령만 있고 사건 증거는 없음
    retrieved_sources = [
        {
            "source_id": "주택임대차보호법_제3조",
            "statute_name": "주택임대차보호법",
            "article": "제3조",
            "content": "제3조 대항력 등. 주택 인도와 주민등록을 마친 때 대항력이 생긴다.",
            "source_type": "STATUTE",
            "retrieval_method": "CHROMA_VECTOR",
        }
    ]

    # 모델이 임의로 가상의 증거번호를 지어낸 초안
    draft_answer = (
        "임차인은 대항력을 취득하였습니다 (주택임대차보호법 제3조). "
        "확인된 사실 — 증거 7: 등기사항전부증명서에 따르면 가압류가 있습니다. "
        "증거 1에 의하면 계약이 체결되었고, [증거 2] 영수증도 확인됩니다."
    )

    # 1. 결정론적 인용 및 증거번호 감사 검증
    audit = audit_citations_and_claims(draft_answer, retrieved_sources, case_context="")
    assert any("UNREGISTERED_EVIDENCE_NUMBER" == r for r in audit["rejection_reasons"].values())
    assert any("증거 7" in label or "증거 1" in label for label in audit["unverified_citations"])

    # 2. LLM이 PASS를 반환하더라도 가드레일에 의해 REVISE 강등 및 CITATION_INVALID 설정 검증
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = SimpleNamespace(
        content='{"status": "PASS", "claims": [{"claim": "임차인 대항력 취득", "claim_type": "LEGAL_APPLICATION", "fact_status": "VERIFIED_FACT", "source_ids": ["주택임대차보호법_제3조"], "grounding_status": "SUPPORTED", "reason": "법조문 일치"}], "missing_issues": [], "contradictions": [], "revision_instructions": [], "warnings": []}'
    )

    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=mock_llm):
        ver_res = run_verification("대항력 및 가압류 쟁점", draft_answer, retrieved_sources)

    assert ver_res["status"] == "REVISE"
    assert ver_res["reason_code"] == "CITATION_INVALID"
    assert any("임의의 가상 증거번호" in w for w in ver_res["warnings"])


def test_registered_evidence_numbers_accepted():
    """실제 DB 또는 case_context에 등록된 증거 식별자가 존재할 때는 유효한 증거로 승인되는지 검증한다."""
    retrieved_sources = [
        {
            "source_id": "EVIDENCE:doc-lease-01",
            "file_name": "임대차계약서.pdf",
            "filename": "임대차계약서.pdf",
            "page": "1",
            "content": "보증금 1억 원, 계약기간 2022년 3월부터 2년.",
            "source_type": "CASE_EVIDENCE",
            "retrieval_method": "CHROMA_VECTOR",
        }
    ]
    draft_answer = "계약서에 따라 보증금은 1억 원입니다 (임대차계약서.pdf, p.1)."

    audit = audit_citations_and_claims(draft_answer, retrieved_sources, case_context="사건 증거 등록됨: EVIDENCE:doc-lease-01")
    assert len(audit["rejected_citation_ids"]) == 0
    assert len(audit["validated_citation_ids"]) == 1


def test_sanitize_unverified_citations_cleans_fake_evidence_numbers():
    """최종 정화(sanitize) 함수가 허위 파일명 및 가상 증거번호를 고객 화면에서 제거·정제하는지 검증한다."""
    draft_answer = (
        "확인된 사실 — 증거 7: 등기사항전부증명서에 따르면 가압류가 설정되어 있습니다. "
        "증거 1에 의하면 계약이 체결되었습니다."
    )
    retrieved_sources = []

    sanitized = sanitize_unverified_citations(draft_answer, retrieved_sources)
    assert "증거 7" not in sanitized
    assert "증거 1" not in sanitized
    assert "등기사항전부증명서" in sanitized  # 본문 맥락은 보존


def test_claim_level_adaptive_scope_recommendation_not_blocked():
    """실무 권고(RECOMMENDATION)나 사용자 진술(USER_STATEMENT)에 법령 조문 출처가 없더라도 부당하게 차단되지 않는지 검증한다."""
    retrieved_sources = [
        {
            "source_id": "주택임대차보호법_제3조의3",
            "statute_name": "주택임대차보호법",
            "article": "제3조의3",
            "content": "임차인은 임대차가 끝난 후 보증금을 반환받지 못한 경우 임차권등기명령을 신청할 수 있다.",
            "source_type": "STATUTE",
            "retrieval_method": "CHROMA_VECTOR",
        }
    ]
    draft_answer = (
        "임차권등기명령을 신청할 수 있습니다 (주택임대차보호법 제3조의3). "
        "실무상 주민센터를 방문하여 확정일자 부여현황을 확인하시고, 내용증명을 우체국에서 발송하시기 바랍니다."
    )

    mock_llm = MagicMock()
    # 핵심 법리는 SUPPORTED, 실무 권고는 NOT_APPLICABLE (출처 없음)
    mock_llm.invoke.return_value = SimpleNamespace(
        content='''{
            "status": "PASS",
            "reason_code": "NONE",
            "claims": [
                {
                    "claim": "임차권등기명령 신청 가능",
                    "claim_type": "LEGAL_APPLICATION",
                    "fact_status": "VERIFIED_FACT",
                    "source_ids": ["주택임대차보호법_제3조의3"],
                    "grounding_status": "SUPPORTED",
                    "reason": "법조문 일치"
                },
                {
                    "claim": "주민센터 방문 및 내용증명 발송 권고",
                    "claim_type": "RECOMMENDATION",
                    "fact_status": "EVIDENCE_NEEDED",
                    "source_ids": [],
                    "grounding_status": "NOT_APPLICABLE",
                    "reason": "실무상 조치 권고"
                }
            ],
            "missing_issues": [],
            "contradictions": [],
            "revision_instructions": [],
            "warnings": []
        }'''
    )

    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=mock_llm):
        ver_res = run_verification("보증금 미반환 조치", draft_answer, retrieved_sources)

    # 실무 권고에 조문 출처가 없다는 이유로 REVISE로 강등되지 않고 PASS를 유지해야 함
    assert ver_res["status"] == "PASS"


def test_core_legal_rule_missing_source_triggers_revision():
    """핵심 법률 규범(LEGAL_RULE)이나 구체적 효과 판단(LEGAL_APPLICATION)이 출처 본문과 불일치할 때는 엄격히 REVISE로 강등되는지 검증한다."""
    retrieved_sources = [
        {
            "source_id": "주택임대차보호법_제3조",
            "statute_name": "주택임대차보호법",
            "article": "제3조",
            "content": "대항력 요건",
            "source_type": "STATUTE",
            "retrieval_method": "CHROMA_VECTOR",
        }
    ]
    draft_answer = "임대인은 3배의 징벌적 손해배상금을 지급해야 합니다."

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = SimpleNamespace(
        content='''{
            "status": "PASS",
            "reason_code": "NONE",
            "claims": [
                {
                    "claim": "임대인의 3배 징벌적 손해배상 책임",
                    "claim_type": "LEGAL_APPLICATION",
                    "fact_status": "INFERENCE",
                    "source_ids": ["주택임대차보호법_제3조"],
                    "grounding_status": "UNSUPPORTED",
                    "reason": "주택임대차보호법 제3조에 징벌적 손해배상 조항 전혀 없음"
                }
            ],
            "missing_issues": [],
            "contradictions": [],
            "revision_instructions": [],
            "warnings": []
        }'''
    )

    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=mock_llm):
        ver_res = run_verification("손해배상 질문", draft_answer, retrieved_sources)

    # 핵심 법적 판단이 UNSUPPORTED이므로 PASS가 취소되고 REVISE로 강등되어야 함
    assert ver_res["status"] == "REVISE"
    assert ver_res["recommended_action"] == "REVISE_DRAFT"


def test_insufficient_node_dynamic_guidance_and_no_system_keywords():
    """T06: insufficient_node 출력에서 내부 시스템 용어(WITHHELD, INSUFFICIENT)가 배제되고 사건 맥락별 동적 안내가 이루어지는지 검증한다."""
    # 시나리오 1: 임대차 사건 근거 부족
    state_housing = {
        "question": "전세보증금을 언제 돌려받을 수 있나요?",
        "case_context": "전세 계약 만료 후 보증금 미반환",
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "candidate_laws": ["주택임대차보호법"],
            "missing_issues": ["초안은 계약 해지 통보 도달 시점 검토 필요"],
        },
    }
    res_housing = insufficient_node(state_housing)
    answer_housing = res_housing["final_answer"]

    # 내부 시스템 코드 노출 금지 검증
    assert "WITHHELD" not in answer_housing
    assert "INSUFFICIENT" not in answer_housing
    assert "LEGAL_SOURCE_MISSING" not in answer_housing
    assert "초안" not in answer_housing  # 감수 단어 정제 확인

    # 임대차 맞춤형 서류 안내 포함 검증
    assert "임대차계약서" in answer_housing or "보증금" in answer_housing
    assert res_housing["final_disposition"] == "WITHHELD"  # 상태 머신 내부 값은 안전하게 유지

    # 시나리오 2: 근로/노동 사건 근거 부족
    state_labor = {
        "question": "부당해고 구제신청을 할 수 있나요?",
        "case_context": "수습기간 중 구두 해고 통보",
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "CASE_EVIDENCE_MISSING",
            "candidate_laws": ["근로기준법"],
            "missing_issues": ["서면 해고 통지 존재 여부"],
        },
    }
    res_labor = insufficient_node(state_labor)
    answer_labor = res_labor["final_answer"]

    # 노동 사건 맞춤형 서류 안내 포함 검증
    assert "근로계약서" in answer_labor or "급여명세서" in answer_labor
    assert "WITHHELD" not in answer_labor

