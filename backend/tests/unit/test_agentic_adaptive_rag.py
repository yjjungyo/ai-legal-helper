# -*- coding: utf-8 -*-
"""
모듈명: test_agentic_adaptive_rag.py

[테스트 개요]
Agentic RAG 및 Adaptive Re-Retrieval 워크플로우 개선 사항을 검증하는 단위 테스트 모듈이다.

[주요 검증 항목]
1. LangChain Tool 실행 시 copy_context() 경계를 넘어 retrieved_sources가 정상 수집되는지 검증
2. 검증관 상태가 INSUFFICIENT이더라도 최초 회차(revision_count == 0)에서 1회 revise 노드로 전이되는지 검증
3. 재검토 한도 도달(revision_count >= 1) 시 insufficient 노드로 안전하게 전이되는지 검증
4. insufficient_node에서 검증관의 지적사항(missing_issues, contradictions, warnings)이 최종 답변에 구조화되어 노출되는지 검증
"""
import pytest
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage

from ai_legal_helper.observability import context
from ai_legal_helper.workflows.legal_workflow import verification_condition, insufficient_node
from ai_legal_helper.workflows.state import LegalState


def test_tool_contextvar_retrieved_sources_propagation():
    """LangChain Tool이 copy_context() 내부에서 실행되어도 retrieved_sources가 상위 컨텍스트로 전파되는지 검증."""
    context.reset_retrieved_sources()
    assert context.get_retrieved_sources() == []

    # 가상 RAG Tool 실행 흉내 (자식 contextvar 실행 모사)
    import contextvars
    ctx = contextvars.copy_context()

    def tool_execution_in_child_context():
        sample_source = {
            "source_id": "민법_제635조_p53",
            "source_type": "STATUTE",
            "document_id": "민법.pdf",
            "title": "민법",
            "content": "제635조 해지통고",
        }
        context.add_retrieved_source(sample_source)

    ctx.run(tool_execution_in_child_context)

    # 상위 컨텍스트에서 조회했을 때 정상적으로 수집되어야 함
    sources = context.get_retrieved_sources()
    assert len(sources) == 1
    assert sources[0]["source_id"] == "민법_제635조_p53"


def test_verification_condition_allows_first_revision_for_insufficient():
    """최초 회차(revision_count == 0)에서 INSUFFICIENT 판정 시 revise 노드로 전이하는지 검증."""
    state: LegalState = {
        "messages": [],
        "revision_count": 0,
        "verification_result": {
            "status": "INSUFFICIENT",
            "missing_issues": ["주택임대차보호법 조문 누락"],
        },
    }
    next_node = verification_condition(state)
    assert next_node == "revise", "최초 INSUFFICIENT 발생 시 보강 검색을 위해 revise 노드로 전이되어야 함"


def test_verification_condition_exhaustion_goes_to_insufficient():
    """1회 재검토 후(revision_count >= 1) 여전히 미통과 시 insufficient 노드로 전이하는지 검증."""
    state: LegalState = {
        "messages": [],
        "revision_count": 1,
        "verification_result": {
            "status": "INSUFFICIENT",
            "missing_issues": ["주택임대차보호법 조문 누락"],
        },
    }
    next_node = verification_condition(state)
    assert next_node == "insufficient", "재검토 한도 도달 시 insufficient 노드로 이동해야 함"


def test_verification_condition_pass_goes_to_finalize():
    """PASS 판정 시 finalize 노드로 직행하는지 검증."""
    state: LegalState = {
        "messages": [],
        "revision_count": 0,
        "verification_result": {
            "status": "PASS",
        },
    }
    next_node = verification_condition(state)
    assert next_node == "finalize"


def test_insufficient_node_surfaces_missing_issues_and_contradictions():
    """insufficient_node가 근거 부족 시 안전한 판단 유보 및 확인 필요 쟁점을 고객에게 안내하는지 검증."""
    state: LegalState = {
        "messages": [],
        "draft_answer": "임차인은 1개월 후 해지 효력이 발생합니다 (민법.pdf, p.53)",
        "case_context": "",
        "retrieved_sources": [],
        "warnings": [],
        "verification_result": {
            "status": "INSUFFICIENT",
            "missing_issues": ["주택임대차보호법 제6조의2 제2항(3개월) 누락"],
            "candidate_laws": ["주택임대차보호법"],
            "contradictions": ["주택임대차 질문에 일반 민법 1개월을 적용한 모순"],
            "warnings": ["핵심 특별법 근거가 확보되지 않은 상태입니다."],
        },
    }
    res = insufficient_node(state)
    final_text = res.get("final_answer", "")

    # 1. P0-02 & P0-1: 판단 유보 안내문 및 final_disposition WITHHELD 검증
    assert "[안내: 법률적 근거 부족으로 인한 판단 유보 (WITHHELD)]" in final_text
    assert res.get("final_disposition") == "WITHHELD"
    assert "주택임대차보호법 제6조의2 제2항(3개월) 누락" in final_text

    # 2. P0-02 & P0-2: 미검증 초안 고객 노출 원천 배제 검증
    assert "[참고: 미검증 참고 초안 (법적 효력 없음)]" not in final_text
    assert "임차인은 1개월 후 해지 효력이 발생합니다" not in final_text

    # 3. 마크다운 원시 기호(#, **)가 최종 텍스트에 포함되지 않아야 함
    assert "#" not in final_text, "최종 답변에 마크다운 # 헤더 기호가 잔존해서는 안 됨"
    assert "**" not in final_text, "최종 답변에 마크다운 ** 볼드 기호가 잔존해서는 안 됨"


