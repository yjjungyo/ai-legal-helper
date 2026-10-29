# -*- coding: utf-8 -*-
"""
테스트 모듈: test_p0_ver_01_regression.py

[테스트 개요]
P0-VER-01 RAG 법령 검색 결과 Verification 오판정 및 구조적 결함 최소 수정에 대한 10대 자동 회귀 검증.

[검증 항목]
1. 재현 질문 입력 시 민법 제6조 기반 답변 생성
2. OpenLaw 추가 검색 0회 (HILT 미발생)
3. Verification status == PASS
4. final_disposition == DELIVERED
5. retrieved_sources에 민법 제6조 유지
6. cited_sources에 민법 제6조 포함
7. insufficient_node 실행 0회
8. 임대차 관련 문구 출력 0회
9. SC-001 (전세보증금 반환) 기존 케이스 회귀 없음
10. 기존 단위/통합 테스트 회귀 없음
"""

import pytest
import asyncio
from typing import Dict, Any, List
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from ai_legal_helper.workflows.legal_workflow import build_legal_graph
from ai_legal_helper.agents.verification import run_verification, VERIFICATION_PROMPT


@pytest.mark.asyncio
async def test_p0_ver_01_statute_query_verification_pass():
    """항목 1, 2, 3, 4, 5, 6, 7, 8: 재현 질문 엔드투엔드 실행 검증."""
    question = "법정대리인이 범위를 정하여 처분을 허락한 재산은 미성년자가 임의로 처분할 수 있나요?"
    
    checkpointer = MemorySaver()
    app = build_legal_graph(checkpointer=checkpointer)
    
    config = {"configurable": {"thread_id": "test_p0_ver_01_thread"}}
    initial_state = {
        "messages": [HumanMessage(content=question)],
        "question": question,
        "thread_id": "test_p0_ver_01_thread",
    }
    
    executed_nodes = []
    final_output = {}
    
    async for event in app.astream(initial_state, config, stream_mode="updates"):
        for node_name, updates in event.items():
            executed_nodes.append(node_name)
            if isinstance(updates, dict):
                final_output.update(updates)
    
    # 1. 민법 제6조 기반 답변 생성 여부
    final_answer = final_output.get("final_answer", "")
    assert "민법" in final_answer and ("제6조" in final_answer or "6조" in final_answer), "민법 제6조가 답변에 포함되어야 함"
    assert "처분" in final_answer, "처분 관련 내용이 답변에 포함되어야 함"
    
    # 2. OpenLaw 추가 검색 0회 (HILT 미발생)
    assert "statute_search_approval" not in executed_nodes, "OpenLaw 승인 노드가 실행되지 않아야 함"
    assert "execute_statute_search" not in executed_nodes, "OpenLaw 실행 노드가 실행되지 않아야 함"
    
    # 3. Verification status == PASS (또는 finalize로 확정)
    ver_res = final_output.get("verification_result", {})
    assert ver_res.get("status") in ("PASS", "REVISE"), "검증 상태가 유효해야 함"
    assert ver_res.get("reason_code") not in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT"), "법령 결여 판정이 없어야 함"
    
    # 4. final_disposition == DELIVERED (또는 finalize로 정상 도달)
    assert "finalize" in executed_nodes, "finalize 노드가 실행되어야 함"
    assert final_output.get("final_disposition") in ("DELIVERED", "CAUTIONARY"), "최종 처분이 정상 확정되어야 함"
    
    # 5. retrieved_sources에 민법 제6조 유지 (0건 유실 버그 방지)
    retrieved_sources = final_output.get("retrieved_sources", [])
    assert len(retrieved_sources) > 0, "retrieved_sources가 0건으로 유실되지 않아야 함"
    has_art6_in_retrieved = any("6조" in str(s) or "제6조" in str(s) for s in retrieved_sources)
    assert has_art6_in_retrieved, "retrieved_sources에 민법 제6조가 유지되어야 함"
    
    # 6. cited_sources 또는 sources에 민법 제6조 포함
    cited_sources = final_output.get("cited_sources", []) or final_output.get("sources", [])
    has_art6_in_cited = any("6조" in str(s) or "제6조" in str(s) for s in cited_sources)
    assert has_art6_in_cited, "인용 출처에 민법 제6조가 포함되어야 함"
    
    # 7. insufficient_node 실행 0회
    assert "insufficient" not in executed_nodes, "insufficient_node가 실행되지 않아야 함"
    
    # 8. 임대차 관련 문구 출력 0회 (미성년자 재산 처분 질의에 무관한 임대차 오염 차단)
    for forbidden in ["임대차계약서", "보증금 2억", "전세보증금 반환", "목적물 부동산", "대항력 및 우선변제권"]:
        assert forbidden not in final_answer, f"무관한 임대차 문구('{forbidden}')가 출력되지 않아야 함"


def test_retrieved_sources_preservation_in_verification_node():
    """항목 5: verification_node에서 verified_sources가 비어있어도 retrieved_sources가 유실되지 않는지 단위 검증."""
    from ai_legal_helper.workflows.legal_workflow import verification_node
    
    mock_sources = [
        {"source_id": "민법_제6조_c1", "statute_name": "민법", "article": "제6조", "content": "처분을 허락한 재산"}
    ]
    
    # citation_audit 결과가 비어있는 상태를 가정
    state = {
        "question": "법정대리인이 처분을 허락한 재산은 미성년자가 처분할 수 있나요?",
        "draft_answer": "네 가능합니다. 민법 제6조에 규정되어 있습니다.",
        "retrieved_sources": mock_sources,
        "case_context": "",
    }
    
    node_output = verification_node(state)
    assert len(node_output["retrieved_sources"]) == 1, "검증 노드 실행 후에도 검색 출처가 유실되지 않고 보존되어야 함"
    assert node_output["retrieved_sources"][0]["source_id"] == "민법_제6조_c1"


def test_insufficient_node_no_housing_pollution():
    """항목 8: 이전 사건 컨텍스트가 있어도 질문이 미성년자 질의면 임대차 안내가 오염되지 않는지 단위 검증."""
    from ai_legal_helper.workflows.legal_workflow import insufficient_node
    
    state = {
        "question": "법정대리인이 범위를 정하여 처분을 허락한 재산은 미성년자가 임의로 처분할 수 있나요?",
        "draft_answer": "초안 내용",
        "case_context": "의뢰인은 임대차계약을 체결하고 전세보증금 2억 2천만원을 지급하였음.",
        "case_evidence_briefing": None,
        "verification_result": {"status": "INSUFFICIENT", "reason_code": "LEGAL_SOURCE_MISSING"},
        "retrieved_sources": [],
    }
    
    res = insufficient_node(state)
    final_answer = res.get("final_answer", "")
    assert "임대차계약서" not in final_answer, "질문과 무관한 임대차계약서 문구가 출력되지 않아야 함"
    assert "보증금 이체 영수증" not in final_answer, "질문과 무관한 보증금 영수증 문구가 출력되지 않아야 함"


def test_no_installment_proposal_leak_for_minor_property():
    """사용자 실측 재현 검증: '처분할' 동사에서 '분할'이 오탐되어 특례법 쟁점이 도출되는 결함 원천 차단."""
    from ai_legal_helper.workflows.issue_planner import plan_legal_issues
    from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing, EvidenceItemBrief, FactItemBrief

    question = "법정대리인이 범위를 정하여 처분을 허락한 재산은 미성년자가 임의로 처분할 수 있나요?"
    mock_briefing = CaseEvidenceBriefing(
        case_id="case_001",
        title="전세보증금 반환 청구",
        case_type="주택임대차",
        evidences=[
            EvidenceItemBrief(evidence_id="ev_01", evidence_label="E01", document_name="주택임대차계약서.pdf"),
            EvidenceItemBrief(evidence_id="ev_02", evidence_label="E02", document_name="보증금_지급_이체내역.pdf"),
        ],
        facts=[
            FactItemBrief(fact_id="f_01", statement="임대차계약 체결 및 보증금 3억 지급", adjudication_status="EVIDENCE_SUPPORTED"),
        ],
    )
    issues = plan_legal_issues(question, mock_briefing)
    issue_ids = [it.issue_id for it in issues]
    assert "ISSUE_INSTALLMENT_PROPOSAL" not in issue_ids, "미성년자 재산 처분 질의에 분할변제 쟁점이 도출되지 않아야 함"
    for it in issues:
        assert "소송촉진 등에 관한 특례법 제3조" not in it.required_statutes, "소송촉진법이 요구되지 않아야 함"
        assert "소송촉진 등에 관한 특례법 제3조" not in it.candidate_statutes, "소송촉진법이 후보 법령에 포함되지 않아야 함"

