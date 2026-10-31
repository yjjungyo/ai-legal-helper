"""STEP 5 경량 Verification 및 부분 교정(Targeted Repair) 단위 테스트.

[검증 항목]
1. test_pure_statute_query_skips_llm_and_passes:
   - 단순 법령 질문에서 출처와 조문이 정상일 때 불필요한 LLM 검증 호출 없이 조기 PASS 검증.
2. test_unverified_citation_detected_as_repair_target:
   - 존재하지 않는 가짜 출처 ID([E99])가 인용되었을 때 결정론적 검사에서 REPAIR 대상 문장으로 정확히 식별.
3. test_multi_part_question_coverage_detection:
   - 복합 질문(상태 확인 + 해지 절차) 중 일부가 누락되었을 때 질문 충족도 미달 및 REPAIR 판정 검증.
4. test_unconfirmed_termination_assertion_detected_and_repaired:
   - 통지 도달일 미확정 상태에서 종료일 확정 단정 문장을 위험 요소로 탐지하고 부분 교정 실행.
5. test_repair_preserves_other_sentences_100_percent:
   - 부분 교정 시 문제가 없는 정상 문장과 핵심 판단은 100% 원형 그대로 보존됨을 검증.
6. test_revise_node_integrates_targeted_repair:
   - LangGraph의 revise_node가 전체 초안 재작성 대신 repair_targets 기반의 부분 교정을 수행하는지 검증.
"""

import pytest
from unittest.mock import MagicMock, patch

from ai_legal_helper.agents.qa_checker import (
    check_deterministic_qa,
    repair_draft_answer,
    split_into_sentences,
    extract_question_demands,
    RepairTarget,
    QACheckResult,
)
from ai_legal_helper.agents.verification import run_verification


def test_split_into_sentences_preserves_structure():
    """번호 매김과 불릿이 포함된 법률 답변을 문장 단위로 정확히 분할하는지 검증한다."""
    text = (
        "1. 임대차보호법 제3조에 따라 대항력이 인정됩니다.\n"
        "2. 확정일자를 갖추었으므로 우선변제권이 발생합니다. 보증금은 3억원입니다.\n"
        "- 추가로 임차권등기명령을 신청할 수 있습니다."
    )
    sentences = split_into_sentences(text)
    assert len(sentences) >= 3
    assert any("대항력이 인정됩니다" in s for s in sentences)
    assert any("우선변제권이 발생합니다" in s for s in sentences)
    assert any("임차권등기명령" in s for s in sentences)


def test_pure_statute_query_skips_llm_and_passes(monkeypatch):
    """사건 맥락이 없는 단순 법령 질의는 결정론적 검사 통과 시 LLM 검증을 호출하지 않고 조기 PASS한다."""
    question = "주택임대차보호법 제3조 내용이 무엇인가요?"
    draft_answer = (
        "주택임대차보호법 제3조에 따르면 주택의 인도와 주민등록을 마친 때에는 "
        "그 다음 날부터 제3자에 대하여 대항력이 발생합니다. [STATUTE-001]"
    )
    retrieved_sources = [
        {
            "source_type": "STATUTE",
            "statute_name": "주택임대차보호법",
            "article": "제3조",
            "title": "대항력 등",
            "source_id": "STATUTE-001",
            "content": "제3조(대항력 등) ① 임대차는 그 등기가 없는 경우에도 임차인이 주택의 인도와 주민등록을 마친 때에는 그 다음 날부터 제삼자에 대하여 효력이 생긴다.",
        }
    ]

    mock_llm = MagicMock()
    monkeypatch.setattr("ai_legal_helper.llm.gateway.get_llm", MagicMock(return_value=mock_llm))

    res = run_verification(
        question=question,
        draft_answer=draft_answer,
        retrieved_sources=retrieved_sources,
        case_context="",
    )

    # 1. 검증 결과는 PASS여야 함
    assert res["status"] == "PASS"
    assert res["reason_code"] == "NONE"
    # 2. LLM이 호출되지 않았어야 함 (조기 PASS 최적화)
    assert mock_llm.invoke.call_count == 0


def test_unverified_citation_detected_as_repair_target():
    """출처 목록에 없는 허위 인용([E99])이 포함된 경우 REPAIR 대상 문장으로 정확히 식별된다."""
    question = "보증금 반환 관련 증거가 있나요?"
    draft_answer = (
        "1. 임대차계약서에 따라 보증금은 3억원입니다. [E01]\n"
        "2. 등록되지 않은 가짜 문서에 따라 추가 합의가 있었습니다. [E99]"
    )
    retrieved_sources = [
        {
            "source_type": "CASE_EVIDENCE",
            "source_id": "E01",
            "filename": "임대차계약서.pdf",
            "content": "보증금 300,000,000원",
        }
    ]

    qa_res = check_deterministic_qa(
        question=question,
        draft_answer=draft_answer,
        retrieved_sources=retrieved_sources,
        case_context="사건 보증금: 3억원 [E01]",
    )

    assert qa_res.source_check_passed is False
    assert qa_res.status == "REPAIR"
    assert qa_res.reason_code == "CITATION_INVALID"
    assert len(qa_res.repair_targets) >= 1
    # [E99]가 포함된 문장이 repair_targets에 들어있는지 확인
    assert any("E99" in rt.original_sentence for rt in qa_res.repair_targets)


def test_multi_part_question_coverage_detection():
    """다중 질문에서 한 가지 요청이 완전히 누락된 경우 질문 충족 미달로 REPAIR가 도출된다."""
    question = "현재 계약은 어떤 상태인가요? 그리고 종료하려면 어떻게 해야 하나요?"
    # 상태에 대해서만 답변하고 종료 방법에 대해서는 전혀 언급하지 않은 초안
    draft_answer = (
        "현재 고객님의 임대차 계약은 주택임대차보호법 제6조에 따라 묵시적으로 갱신된 상태입니다."
    )
    retrieved_sources = [
        {
            "source_type": "STATUTE",
            "statute_name": "주택임대차보호법",
            "article": "제6조",
            "content": "임대인이 임대차기간이 끝나기 6개월 전부터 2개월 전까지의 기간에...",
        }
    ]

    qa_res = check_deterministic_qa(
        question=question,
        draft_answer=draft_answer,
        retrieved_sources=retrieved_sources,
        case_context="",
    )

    demands = extract_question_demands(question)
    assert len(demands) >= 2
    # 상태(갱신)는 답변되었으나 종료 절차는 미답변되어 question_items_answered < demands_total 확인
    assert qa_res.question_items_answered < qa_res.question_items_total


def test_unconfirmed_termination_assertion_detected_and_repaired(monkeypatch):
    """통지 도달일이 미확인된 상태에서 종료일을 확정한 문장을 위험 요소로 감지하고 안전하게 부분 교정한다."""
    question = "묵시적 갱신 상태에서 해지 통보하면 언제 끝나나요?"
    draft_answer = (
        "1. 임차인은 묵시적 갱신 중 언제든지 계약 해지를 통지할 수 있습니다.\n"
        "2. 따라서 2026년 11월 1일에 계약이 완전히 종료됩니다.\n"
        "3. 종료 후 보증금 반환을 청구할 수 있습니다."
    )
    retrieved_sources = [
        {
            "source_type": "STATUTE",
            "statute_name": "주택임대차보호법",
            "article": "제6조의2",
            "content": "제6조의2(묵시적 갱신의 경우 계약의 해지) ② 임대인이 통지를 받은 날부터 3개월이 지나면 그 효력이 발생한다.",
        }
    ]

    qa_res = check_deterministic_qa(
        question=question,
        draft_answer=draft_answer,
        retrieved_sources=retrieved_sources,
        case_context="임차인이 내용증명을 발송하였으나 임대인 수령 여부는 확인되지 않음.",
    )

    # 1. 법률 적용 위험 검사 실패 확인
    assert qa_res.legal_risk_passed is False
    assert len(qa_res.repair_targets) >= 1
    target = qa_res.repair_targets[0]
    assert "2026년 11월 1일" in target.original_sentence

    # 2. 부분 교정 Mock 설정 (LLM이 조건부 문장으로 교체 반환)
    from langchain_core.messages import AIMessage
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = AIMessage(
        content="따라서 임대인이 통지를 실제로 수령한 날부터 3개월이 경과해야 해지 효력이 발생합니다."
    )
    monkeypatch.setattr("ai_legal_helper.llm.gateway.get_llm", MagicMock(return_value=mock_llm))

    repaired_answer, meta = repair_draft_answer(
        draft_answer=draft_answer,
        repair_targets=qa_res.repair_targets,
        preserved_points=qa_res.preserved_points,
        case_context="수령 미확인",
        retrieved_sources=retrieved_sources,
    )

    # 3. 위험한 단정 문장만 교체되었고 정상 문장(1번, 3번)은 그대로 보존되었는지 검증
    assert "2026년 11월 1일에 계약이 완전히 종료됩니다" not in repaired_answer
    assert "임대인이 통지를 실제로 수령한 날부터 3개월이 경과해야" in repaired_answer
    assert "1. 임차인은 묵시적 갱신 중 언제든지 계약 해지를 통지할 수 있습니다." in repaired_answer
    assert "3. 종료 후 보증금 반환을 청구할 수 있습니다." in repaired_answer
    assert meta["repaired"] is True
    assert meta["replaced_count"] == 1


def test_repair_preserves_other_sentences_100_percent():
    """부분 교정 시 문제가 없는 정상 문장과 핵심 판단은 100% 원형 그대로 보존된다."""
    sent1 = "1. 의뢰인의 임대차 보증금은 3억원이며 우선변제권 요건을 갖추고 있습니다."
    sent2 = "2. 임대인은 현재 가압류가 설정되어 있어 주의가 필요합니다."
    sent3 = "3. 무조건 보증금을 전액 돌려받을 수 있습니다."  # 문제 문장
    draft = f"{sent1}\n{sent2}\n{sent3}"

    repair_target = RepairTarget(
        sentence_index=2,
        original_sentence=sent3,
        repair_reason="경매 배당 순위에 따라 일부 미회수 위험이 있으므로 무조건 전액 반환 단정 불가",
        recommended_fix="선순위 권리관계 확인 후 배당 가능 여부를 판단해야 합니다.",
    )

    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get_llm:
        from langchain_core.messages import AIMessage
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = AIMessage(
            content="선순위 권리관계 확인 후 배당 가능 여부를 신중히 판단해야 합니다."
        )
        mock_get_llm.return_value = mock_llm

        repaired, meta = repair_draft_answer(
            draft_answer=draft,
            repair_targets=[repair_target],
            preserved_points=[sent1, sent2],
            case_context="",
        )

        # sent1과 sent2는 완전 무결하게 보존
        assert sent1 in repaired
        assert sent2 in repaired
        assert sent3 not in repaired
        assert "선순위 권리관계 확인 후 배당 가능 여부를 신중히 판단해야 합니다." in repaired


def test_revise_node_integrates_targeted_repair():
    """legal_workflow의 revise_node가 repair_targets가 있을 때 부분 교정을 호출하는지 검증한다."""
    from ai_legal_helper.workflows.legal_workflow import revise_node

    sent1 = "1. 대항력 요건이 충족되었습니다."
    sent2 = "2. 2026년 12월 1일에 계약이 완전히 종료됩니다."
    draft = f"{sent1}\n{sent2}"

    mock_state = {
        "question": "계약 언제 끝나나요?",
        "draft_answer": draft,
        "retrieved_sources": [
            {"source_id": "S1", "statute_name": "주택임대차보호법", "article": "제3조"}
        ],
        "case_context": "",
        "revision_count": 0,
        "verification_result": {
            "status": "REVISE",
            "repair_targets": [
                {
                    "sentence_index": 1,
                    "original_sentence": sent2,
                    "repair_reason": "도달일 미확인",
                    "recommended_fix": "도달일 기준 3개월 설명",
                }
            ],
            "preserved_points": [sent1],
        },
    }

    with patch("ai_legal_helper.agents.qa_checker.repair_draft_answer") as mock_repair:
        mock_repair.return_value = (
            f"{sent1}\n2. 도달일 기준 3개월 설명",
            {"repaired": True, "replaced_count": 1},
        )
        res = revise_node(mock_state)

        # revise_node가 repair_draft_answer를 호출하여 부분 교정했는지 확인
        assert mock_repair.call_count == 1
        assert res["revision_method"] == "TARGETED_REPAIR"
        assert res["revision_count"] == 1
        assert sent1 in res["draft_answer"]
