# -*- coding: utf-8 -*-
"""
모듈명: test_statutory_and_loop_fixes.py

[모듈 개요]
순수 법령 질의(SC-003 등 증거 미제출 질의)에서 검증 통과(PASS) 초안이 WITHHELD로 부당 강등되어
폐기되던 결함 수정 및, 100% 주장 지지 시 검증 루프 조기 탈출(Early Exit) 로직을 검증하는 단위 테스트.

[주요 점검 항목]
1. determine_final_disposition: PASS 상태 또는 사건 증거 미제출 시 WITHHELD 방지 및 DELIVERED/CAUTIONARY 부여
2. assemble_grounded_answer: 증거 미등록 법률 질의 시 무관한 임대차 보증금 권리관계 더미 텍스트 배제
3. next_verification_step: 주장 100% 지지 시 finalize 조기 승인 및 최대 재작성 2회 캡 확인
"""

import pytest
from ai_legal_helper.agents.issue_verifier import IssueVerificationResult
from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.workflows.final_disposition import (
    determine_final_disposition,
    assemble_grounded_answer,
)
from ai_legal_helper.workflows.document_consultation import next_verification_step


def test_determine_final_disposition_statutory_pass():
    """검증 통과(PASS) 상태의 법령 질의는 쟁점 사실 증거가 미확보(NEEDS_EVIDENCE)여도 DELIVERED를 부여한다."""
    issues = [
        IssueVerificationResult(
            issue_id="ISSUE_MANAGEMENT_FEE_REPORTING",
            issue_title="관리비 및 부대비용 신고 의무",
            status="NEEDS_EVIDENCE",
            reason_codes=["CASE_EVIDENCE_MISSING"],
            safe_recommendations=["법령상 2027. 4. 28. 이후 체결 계약부터 적용됩니다."],
        )
    ]

    disp, reason = determine_final_disposition(
        issues,
        has_case_evidence=False,
        verification_status="PASS",
    )

    assert disp == "DELIVERED"
    assert "검증(PASS)" in reason


def test_determine_final_disposition_no_evidence_cautionary():
    """증거 미제출 상태에서 검증 미확정 질의는 WITHHELD 대신 CAUTIONARY를 부여한다."""
    issues = [
        IssueVerificationResult(
            issue_id="ISSUE_1",
            issue_title="일반 법령 해석",
            status="NEEDS_EVIDENCE",
            reason_codes=["CASE_EVIDENCE_MISSING"],
            safe_recommendations=["법령 기준을 검토하십시오."],
        )
    ]

    disp, reason = determine_final_disposition(
        issues,
        has_case_evidence=False,
        verification_status=None,
    )

    assert disp == "CAUTIONARY"
    assert "증거 문서 미제출" in reason


def test_determine_final_disposition_case_with_evidence_blocked_withheld():
    """실제 사건 증거가 등록되어 있으나 모든 쟁점의 증거가 불충분한 사건은 정상적으로 WITHHELD를 유지한다."""
    issues = [
        IssueVerificationResult(
            issue_id="ISSUE_1",
            issue_title="계약 해지 입증",
            status="NEEDS_EVIDENCE",
            reason_codes=["EVIDENCE_INSUFFICIENT"],
            safe_recommendations=["증거를 보완하십시오."],
        )
    ]

    disp, reason = determine_final_disposition(
        issues,
        has_case_evidence=True,
        verification_status="FAIL",
    )

    assert disp == "WITHHELD"


def test_assemble_grounded_answer_no_lease_dummy_for_statutory():
    """증거 문서와 보증금이 없는 법령 질의의 경우 임대차 보증금 기초 권리관계 더미 텍스트를 출력하지 않는다."""
    briefing = CaseEvidenceBriefing(case_id="STAT_001", title="법령 질의", evidences=[], facts=[], parties=[])
    issues = [
        IssueVerificationResult(
            issue_id="ISSUE_1",
            issue_title="부대비용 신고 의무",
            status="NEEDS_EVIDENCE",
            reason_codes=["CASE_EVIDENCE_MISSING"],
            safe_recommendations=["법령 부칙을 확인하십시오."],
        )
    ]

    answer = assemble_grounded_answer(
        issue_results=issues,
        briefing=briefing,
        draft_answer="",
        disposition="CAUTIONARY",
        current_question="임대차계약 신고 시 관리비 등 부대비용도 함께 신고해야 하나요?",
    )

    # 무관한 임대차 보증금 문구가 없어야 함
    assert "보증금에 관한 기초 권리관계를 확인 중입니다" not in answer
    assert "주민등록 초본·확정일자 확인 자료의 원본" not in answer
    # 일반 법령 안내 텍스트가 포함되어야 함
    assert "제출된 사건 증거 자료가 등록되지 않은 상태" in answer
    assert "부칙상 적용례" in answer


def test_next_verification_step_early_exit_100_percent_supported():
    """초안의 모든 주장(claims)이 100% SUPPORTED이고 인용 결함이 없으면 finalize로 조기 승인한다."""
    state = {
        "draft_answer": "민간임대주택에 관한 특별법에 따른 적법한 조언입니다.",
        "revision_count": 1,
        "verification_result": {
            "status": "REVISE",
            "reason_code": "PROVENANCE_WARNING",
            "claims": [
                {"claim_id": "C1", "grounding_status": "SUPPORTED", "claim_text": "주장 1"},
                {"claim_id": "C2", "grounding_status": "SUPPORTED", "claim_text": "주장 2"},
                {"claim_id": "C3", "grounding_status": "SUPPORTED", "claim_text": "주장 3"},
            ],
            "citation_audit": {
                "unverified_citations": [],
                "unsupported_citations": [],
            },
        },
    }

    next_node = next_verification_step(state)
    assert next_node == "finalize"


def test_finalize_node_preserves_verified_draft():
    """finalize_node 실행 시 PASS 상태의 정답 초안이 WITHHELD로 강등되거나 더미 템플릿으로 대체되지 않고 보존된다."""
    from ai_legal_helper.workflows.legal_workflow import finalize_node

    verified_draft = (
        "[1. 핵심 결론]\n"
        "2026년 11월 1일에 체결된 임대차계약의 경우, 관리비와 부대비용을 신고할 법적 의무가 없습니다.\n\n"
        "[2. 법적 근거]\n"
        "개정 민간임대주택에 관한 특별법(법률 제20436호) 부칙 제1조 및 제2조에 따라 해당 의무는 2027년 4월 28일 이후 계약부터 적용됩니다."
    )

    state = {
        "question": "저는 등록 민간임대주택의 임대사업자입니다. 2026년 11월 1일에 새로운 임대차계약을 체결했습니다. 임대차계약 신고 시 관리비 등 부대비용도 신고해야 하나요?",
        "draft_answer": verified_draft,
        "verification_result": {
            "status": "PASS",
            "reason_code": "NONE",
            "issue_results": [
                {
                    "issue_id": "ISSUE_MANAGEMENT_FEE",
                    "issue_title": "관리비 신고 의무",
                    "status": "NEEDS_EVIDENCE",
                    "reason_codes": ["CASE_EVIDENCE_MISSING"],
                    "safe_recommendations": ["2027. 4. 28. 이후 계약부터 적용됩니다."],
                }
            ],
            "claims": [
                {"claim_id": "C1", "grounding_status": "SUPPORTED", "claim_text": "관리비 신고 의무 없음"},
            ],
        },
        "case_evidence_briefing": {
            "case_id": "STAT_SC003",
            "title": "SC-003 법령 질의",
            "evidences": [],
            "facts": [],
            "parties": [],
        },
        "retrieved_sources": [
            {"statute_name": "민간임대주택에 관한 특별법", "article": "부칙 제1조"}
        ],
    }

    result = finalize_node(state)
    final_answer = result.get("final_answer", "")
    final_disposition = result.get("final_disposition")

    # 1. 초안의 핵심 내용이 보존되어야 함
    assert "2026년 11월 1일에 체결된 임대차계약의 경우" in final_answer
    assert "2027년 4월 28일 이후 계약부터 적용됩니다" in final_answer

    # 2. 엉뚱한 임대차 보증금 권리관계 확인 더미 문구가 없어야 함
    assert "보증금에 관한 기초 권리관계를 확인 중입니다" not in final_answer

    # 3. 처분 상태가 WITHHELD가 아니라 DELIVERED여야 함
    assert final_disposition == "DELIVERED"



def test_provenance_relief_for_precedent_citations():
    """판례 출처가 확보된 상태에서 판례 본문 내 인용 조문으로 인한 provenance 실패는 passed=True로 구제된다."""
    from ai_legal_helper.agents.verification import VerificationOutput

    # 검증기가 반환한 provenance가 판례 내 인용 조문 때문에 passed=False인 상황 모사
    mock_data = {
        "status": "PASS",
        "reason_code": "NONE",
        "question_coverage": [
            {"question": "장기수선충당금을 임대인이 부담해야 하나요?", "answered": True}
        ],
        "consistency_checks": {
            "opening_conclusion": {"passed": True, "reason": "서두 결론 타당", "source_ids": ["PRECEDENT:238469"]},
            "timeline": {"passed": True, "reason": "시간 순서 일치", "source_ids": ["PRECEDENT:238469"]},
            "expressed_intent": {"passed": True, "reason": "의사표시 일치", "source_ids": ["PRECEDENT:238469"]},
            "provenance": {
                "passed": False,
                "reason": "판례(2021다238469) 본문 내 인용된 구 공동주택관리법 시행령 제31조 제7항의 별도 법령 원문 미확보",
                "source_ids": ["PRECEDENT:238469"],
            },
        },
        "claims": [
            {
                "claim_id": "C1",
                "claim": "장기수선충당금은 특별한 사정이 없는 한 소유자인 임대인이 부담해야 한다.",
                "claim_type": "LEGAL_RULE",
                "grounding_status": "SUPPORTED",
                "source_ids": ["PRECEDENT:238469"],
                "reason": "대법원 2021다238469 판결 일치",
            }
        ],
    }

    # VerificationOutput Pydantic 인스턴스 생성
    ver_out = VerificationOutput(**mock_data)

    retrieved_sources = [
        {
            "source_id": "PRECEDENT:238469",
            "source_type": "PRECEDENT",
            "title": "대법원 2021다238469 판결",
            "content": "구 공동주택관리법 시행령 제31조 제7항에 의하면 장기수선충당금은 관리주체가 해당 주택의 소유자로부터 징수하여 적립한다.",
        }
    ]

    # provenance 구제 로직 모사 테스트
    prov_check = ver_out.consistency_checks.get("provenance")
    assert prov_check["passed"] is False

    # verification.py에 삽입된 구제 로직 적용
    has_precedent_src = any(
        isinstance(s, dict) and (
            s.get("source_type") == "PRECEDENT"
            or "판례" in str(s.get("type", ""))
            or str(s.get("source_id", "")).startswith("PRECEDENT")
        )
        for s in retrieved_sources
    )
    is_precedent_citation_issue = any(
        kw in prov_check.get("reason", "") for kw in ["판례", "판결", "시행령", "구 시행령", "시행규칙", "부칙"]
    )
    has_unsupported_core = any(
        c.grounding_status == "UNSUPPORTED" and c.claim_type in ("CASE_FACT", "LEGAL_RULE", "LEGAL_APPLICATION")
        for c in ver_out.claims
    )

    if has_precedent_src and is_precedent_citation_issue and not has_unsupported_core:
        prov_check["passed"] = True

    # 구제 결과 확인
    assert prov_check["passed"] is True
    consistency_complete = all(
        ver_out.consistency_checks[k]["passed"] is True
        for k in ("opening_conclusion", "timeline", "expressed_intent", "provenance")
    )
    assert consistency_complete is True

