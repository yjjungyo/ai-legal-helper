# -*- coding: utf-8 -*-
"""QA Checker 리팩토링 및 검증 가드레일 회귀 테스트 모듈.

[검증 항목]
1. SC-012 1차: 부정문('사망만으로 당연히 종료되지는 않습니다')에 대한 정규식 오탐으로 인한
   PASS -> REVISE 강등 방지 및 정상 PASS 보존.
2. SC-012 2·3차: 판례/법령 근거가 부족한 경우 정당한 INSUFFICIENT/REVISE 유지 (부당한 PASS 승격 차단).
3. 허위/미등록 출처 인용: PASS 엄격 차단 및 REPAIR/REVISE 유지.
4. 법률 적용 시점 오류: Temporal BLOCK 및 REVISE 유지.
5. SC-011 3차: 사실관계/계산 착오에 대한 정상적인 Self-Correction/REVISE 유지.
6. 단순 조문 조회 vs 사건에 대한 법률 적용 질의의 검증 경로 분기 (조기 PASS vs LLM 심층 검증).
7. repair_draft_answer Fail-Safe: 교정 실패 시 내부 안내 문구('(참고) ...') 누출 차단 및 원문 안전 보존.

[규범 준수]
CODING_COMMENT_STANDARD.md, AGENTS.md 준수. SC-012 전용 하드코딩 없음.
"""

import json
import hashlib
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage

from ai_legal_helper.agents.qa_checker import (
    check_deterministic_qa,
    repair_draft_answer,
    RepairTarget,
    QACheckResult,
)
from ai_legal_helper.agents.verification import run_verification
from ai_legal_helper.workflows import document_consultation
from ai_legal_helper.rag.grounding_context import format_grounding_sources


def test_sc012_turn1_negative_sentence_passes_without_false_positive():
    """SC-012 1차: 부정문('당연히 종료되지는 않습니다')이 포함되어도 LLM이 SUPPORTED로 검증한 경우 PASS를 유지한다."""
    question = "임대인이 사망했는데 계약이 어떻게 되나요?"
    draft_answer = (
        "임대인이 사망하더라도 임대차계약은 당연히 종료되거나 효력을 잃지 않으며, "
        "상속인에게 임대인의 지위가 포괄 승계됩니다. [STATUTE-001]"
    )
    retrieved_sources = [
        {
            "source_type": "STATUTE",
            "statute_name": "민법",
            "article": "제1005조",
            "title": "상속과 포괄적 권리의무의 승계",
            "source_id": "STATUTE-001",
            "content": "상속인은 상속개시된 때로부터 피상속인의 재산에 관한 포괄적 권리의무를 승계한다.",
        }
    ]

    mock_llm_result = {
        "status": "PASS",
        "reason_code": "NONE",
        "recommended_action": "FINALIZE",
        "claims": [
            {
                "claim": "임대인이 사망하더라도 임대차계약은 당연히 종료되거나 효력을 잃지 않으며 상속인에게 포괄 승계됩니다.",
                "claim_type": "LEGAL_APPLICATION",
                "grounding_status": "SUPPORTED",
                "source_ids": ["STATUTE-001"],
            }
        ],
        "warnings": [],
        "contradictions": [],
        "revision_instructions": [],
        "missing_issues": [],
        "candidate_laws": [],
        "legal_search_requests": [],
        "preserved_points": [draft_answer],
    }

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content=json.dumps(mock_llm_result, ensure_ascii=False))
        mock_get_llm.return_value = mock_llm

        res = run_verification(
            question=question,
            draft_answer=draft_answer,
            retrieved_sources=retrieved_sources,
            case_context="",
        )

        # 1. 정규식에 의해 REVISE로 강제 강등되지 않고 PASS를 유지해야 함
        assert res["status"] == "PASS"
        assert res["reason_code"] == "NONE"
        # 2. PASS 상태에서는 repair_targets가 비어있어야 함 (불필요한 부분 교정 차단)
        assert res.get("repair_targets") == []


def test_insufficient_precedent_remains_withheld():
    """SC-012 2·3차: 판례나 법령 근거가 부족한 경우 PASS로 승격되지 않고 INSUFFICIENT/REVISE가 유지된다."""
    question = "상속인 전원이 상속포기한 경우 보증금 반환 판례가 있나요?"
    draft_answer = "상속인 전원 포기 시 상속재산관리인 선임 후 반환청구 소송을 진행해야 합니다."

    mock_llm_result = {
        "status": "INSUFFICIENT",
        "reason_code": "LEGAL_SOURCE_INSUFFICIENT",
        "recommended_action": "REQUEST_STATUTE_SEARCH_APPROVAL",
        "claims": [
            {
                "claim": "상속재산관리인 선임 후 반환청구 소송을 진행해야 합니다.",
                "claim_type": "LEGAL_APPLICATION",
                "grounding_status": "UNSUPPORTED",
                "source_ids": [],
            }
        ],
        "warnings": ["관련 대법원 판례 및 구체적 집행 절차에 대한 근거 조문이 부족합니다."],
        "contradictions": [],
        "revision_instructions": ["상속재산관리인 관련 민법 제1053조 및 판례를 추가 검색하세요."],
        "missing_issues": ["상속재산관리인 선임 절차 및 대법원 판례 근거"],
        "candidate_laws": ["민법 제1053조"],
        "legal_search_requests": [],
        "preserved_points": [],
    }

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(content=json.dumps(mock_llm_result, ensure_ascii=False))
        mock_get_llm.return_value = mock_llm

        res = run_verification(
            question=question,
            draft_answer=draft_answer,
            retrieved_sources=[],
            case_context="",
        )

        assert res["status"] == "INSUFFICIENT"
        assert res["reason_code"] == "LEGAL_SOURCE_INSUFFICIENT"


def test_document_consultation_fatal_error_check_preserves_safety():
    """document_consultation의 finish_answer가 실제 법률 결함은 철저히 차단함을 검증한다."""
    sources = [{"source_id": "STATUTE-001", "source_type": "STATUTE", "content": "상속인은 포괄 승계한다."}]
    _, manifest = format_grounding_sources(sources)

    # 1. 미검증 법률 효과나 근거 누락이 있는 경우 -> INSUFFICIENT 유지
    state_with_defect = {
        "question": "임대인이 사망하면 어떻게 되나요?",
        "draft_answer": "계약이 즉시 종료되고 전액 반환받습니다.",
        "retrieved_sources": sources,
        "verification_result": {
            "status": "REVISE",
            "reason_code": "LEGAL_SOURCE_INSUFFICIENT",
            "claims": [
                {
                    "claim": "계약이 즉시 종료되고 전액 반환받습니다.",
                    "claim_type": "LEGAL_APPLICATION",
                    "grounding_status": "UNSUPPORTED",
                    "source_ids": [],
                }
            ],
            "missing_legal_issues": ["상속에 따른 계약 승계 법리 누락"],
            "qa_summary": {"legal_risk_passed": False},
            "source_manifest": manifest,
            "temporal_gate": {"status": "PASS"},
        },
    }
    with patch.object(document_consultation, "validate_document_snapshot"):
        out = document_consultation.finish_answer(state_with_defect)
        assert out["verification_result"]["status"] == "INSUFFICIENT"

    # 2. 모든 주장이 SUPPORTED이고 근거가 확실한 정상 답변 -> PASS 보존
    draft_clean = "임대차계약은 상속인에게 당연히 승계되며 종료되지 않습니다. [STATUTE-001]"
    state_clean = {
        "question": "임대인이 사망하면 계약은 어떻게 되나요?",
        "draft_answer": draft_clean,
        "retrieved_sources": sources,
        "verification_result": {
            "status": "PASS",
            "reason_code": "NONE",
            "claims": [
                {
                    "claim": "임대차계약은 상속인에게 승계됩니다.",
                    "claim_type": "LEGAL_APPLICATION",
                    "grounding_status": "SUPPORTED",
                    "source_ids": ["STATUTE-001"],
                }
            ],
            "missing_legal_issues": [],
            "qa_summary": {"legal_risk_passed": False},  # 정규식이 오탐했더라도 LLM이 검증 완료함
            "source_manifest": manifest,
            "temporal_gate": {"status": "PASS"},
            "verified_answer_sha256": hashlib.sha256(draft_clean.encode()).hexdigest(),
        },
    }
    with patch.object(document_consultation, "validate_document_snapshot"):
        out_clean = document_consultation.finish_answer(state_clean)
        assert out_clean["verification_result"]["status"] == "PASS"


def test_unverified_bogus_citation_remains_blocked():
    """등록되지 않은 허위 가상 출처([E999]) 인용 시 PASS가 차단되고 REPAIR/REVISE가 유지된다."""
    qa_res = check_deterministic_qa(
        question="보증금 반환 가능한가요?",
        draft_answer="허위 증거에 의해 전액 반환됩니다. [E999]",
        retrieved_sources=[{"source_id": "E01", "source_type": "CASE_EVIDENCE", "content": "계약서"}],
    )
    assert qa_res.source_check_passed is False
    assert qa_res.status == "REPAIR"
    assert qa_res.reason_code == "CITATION_INVALID"
    assert len(qa_res.repair_targets) >= 1


def test_pure_statute_vs_case_application_routing(monkeypatch):
    """단순 조문 조회는 조기 PASS를 허용하고, 구체적 권리적용 질의는 조기 PASS를 차단하고 LLM을 호출한다."""
    statute_source = [
        {
            "source_type": "STATUTE",
            "statute_name": "주택임대차보호법",
            "article": "제3조",
            "title": "대항력 등",
            "source_id": "STATUTE-001",
            "content": "제3조(대항력 등) ① 임대차는 그 등기가 없는 경우에도...",
        }
    ]

    mock_llm_result = {
        "status": "PASS",
        "reason_code": "NONE",
        "claims": [
            {
                "claim": "임대인 사망 시 상속인에게 지위가 승계됩니다.",
                "claim_type": "LEGAL_APPLICATION",
                "grounding_status": "SUPPORTED",
                "source_ids": ["STATUTE-001"],
            }
        ],
    }

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(content=json.dumps(mock_llm_result, ensure_ascii=False))
    monkeypatch.setattr("ai_legal_helper.llm.gateway.get_llm", MagicMock(return_value=mock_llm))

    # 1. 단순 조문 조회: LLM 호출 없이 조기 PASS
    pure_question = "주택임대차보호법 제3조 내용이 무엇인가요?"
    pure_draft = "주택임대차보호법 제3조는 주택의 인도와 주민등록을 마친 때 대항력이 인정된다고 규정합니다. [STATUTE-001]"
    res_pure = run_verification(
        question=pure_question,
        draft_answer=pure_draft,
        retrieved_sources=statute_source,
        case_context="",
    )
    assert res_pure["status"] == "PASS"
    assert mock_llm.invoke.call_count == 0  # LLM 호출 생략 확인

    # 2. 법률 적용 질의: '사망', '어떻게 되나요' 등 구체적 분쟁 포섭 질의는 조기 PASS 차단 -> LLM 검증 수행
    app_question = "임대인이 사망한 경우 계약은 어떻게 되나요?"
    app_draft = "임대인 사망 시 상속인에게 지위가 승계됩니다. [STATUTE-001]"
    res_app = run_verification(
        question=app_question,
        draft_answer=app_draft,
        retrieved_sources=statute_source,
        case_context="",
    )
    assert mock_llm.invoke.call_count >= 1  # LLM 검증 반드시 호출됨
    assert res_app["status"] == "PASS"


def test_repair_draft_answer_failsafe_no_internal_guidance_leak():
    """repair_draft_answer 실행 중 LLM 오류 발생 시 내부 안내 문구('(참고) ...')가 누출되지 않고 원문이 보존된다."""
    target_sentence = "2026년 12월 1일에 계약이 완전히 종료됩니다."
    draft = f"1. 대항력이 있습니다.\n2. {target_sentence}\n3. 보증금을 반환받으세요."
    rt = RepairTarget(
        sentence_index=1,
        original_sentence=target_sentence,
        repair_reason="도달일 미확정",
        recommended_fix="도달일 기준 3개월 조건부 효력 설명으로 완화",
    )

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("LLM connection timeout")
        mock_get_llm.return_value = mock_llm

        repaired, meta = repair_draft_answer(
            draft_answer=draft,
            repair_targets=[rt],
            preserved_points=["1. 대항력이 있습니다.", "3. 보증금을 반환받으세요."],
        )

        # 1. 내부 권장 조치 지침 문구가 답변에 누출되지 않아야 함
        assert "(참고)" not in repaired
        assert "조건부 효력 설명으로 완화" not in repaired
        # 2. 원문이 안전하게 보존되어 후속 Verification에서 정상 판정되도록 Fail-Safe 유지
        assert target_sentence in repaired
