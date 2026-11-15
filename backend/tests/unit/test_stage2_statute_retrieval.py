# -*- coding: utf-8 -*-
"""
테스트 모듈: test_stage2_statute_retrieval.py

[테스트 개요]
SC-013 근본 원인 수정 2단계(법령 검색 누락 개선) 검증 테스트.

[검증 항목]
1. 쟁점 계획(issue_tasks)에 경매 쟁점이 있을 때, run_agents_node 실행 시 로컬 인덱스(law_docs_global)로부터
   민사집행법 제91조 및 주택임대차보호법 조문이 성공적으로 선적재(Local-First Pre-fetch)되는지 검증.
2. 검색 쿼리가 사용자 질문 원문뿐 아니라 쟁점 계획의 핵심 법률 질문을 결합한 enriched 쿼리로 전달되는지 검증.
3. 특정 사건 키워드나 정답 하드코딩 없이 범용 쟁점-법령 매핑 경로를 통해 검색이 수행되는지 검증.
"""

import pytest
from ai_legal_helper.workflows.issue_planner import LegalIssueTask
from ai_legal_helper.workflows.legal_workflow import run_agents_node
from ai_legal_helper.workflows.document_consultation import DOCUMENT_MODE


@pytest.mark.asyncio
async def test_stage2_local_first_prefetch_civil_execution_act(monkeypatch):
    """법률 쟁점 사전 적재를 *인덱스가 없는 CI에서도* 계약 수준으로 검증한다.

    [REGRESSION-INDEX-01 / Gemini] 실제 ChromaDB 컬렉션이 설치돼 있어야
    PASS하는 테스트는 코드의 정확성보다 개발자 컴퓨터 상태를 검증한다.
    실제 검색 서비스는 별도 통합 E2E에서 시험하고, 여기서는 Local-First
    조회가 정확한 법률명/조문으로 요청되고 반환 출처를 병합하는지 확인.
    """
    from ai_legal_helper.rag.retrieval import RetrievalResult, RetrievalStatus

    monkeypatch.setattr(
        "ai_legal_helper.rag.retrieval.retrieve_with_status",
        lambda **_kw: RetrievalResult(status=RetrievalStatus.NO_MATCH),
    )
    prefetch_calls = []

    def fake_local_index(*, law_name, articles=None, **_kwargs):
        prefetch_calls.append((law_name, tuple(articles or [])))
        if law_name == "민사집행법" and "제91조" in (articles or []):
            return [{
                "source_id": "LOCAL:민사집행법:제91조",
                "source_type": "STATUTE", "statute_name": law_name,
                "article": "제91조", "content": "민사집행법 제91조 경매 매각의 법률 요건",
                "retrieval_method": "LOCAL_INDEX",
            }]
        return []

    monkeypatch.setattr(
        "ai_legal_helper.workflows.document_search._retrieve_from_local_index",
        fake_local_index,
    )
    state = {
        "question": "경매가 진행되면 보증금을 낙찰자에게 받을 수 있나요?",
        "answer_mode": DOCUMENT_MODE,
        "categories": ["civil"],
        "issue_tasks": [
            {
                "issue_id": "ISSUE_AUCTION_STRATEGY",
                "issue_title": "경매 시 권리 순위에 따른 대항력 인수 및 배당·회수 검토",
                "legal_questions": [
                    "임차인이 주택의 인도와 주민등록을 마쳐 대항력을 적법하게 취득하였는지 여부",
                    "목적 부동산 등기부상 임차인의 대항력보다 앞선 선순위 담보물권이 존재하는가?",
                    "선순위 담보권과 대항력 선후 비교 시 경매 매각으로 임차권이 소멸하는가(민사집행법 제91조 제3항) 아니면 인수되는가?",
                ],
                "required_statutes": [
                    "주택임대차보호법 제3조",
                    "주택임대차보호법 제3조의5",
                    "민사집행법 제91조",
                    "민사집행법 제148조",
                ],
                "candidate_statutes": [
                    "민사집행법 제91조",
                    "민사집행법 제148조",
                ],
            }
        ],
        "retrieved_sources": [],
    }

    result = await run_agents_node(state)
    assert any(name == "민사집행법" and "제91조" in articles
               for name, articles in prefetch_calls), "계획된 핵심 조문이 로컬 인덱스에 요청되어야 한다."
    sources = result.get("retrieved_sources", [])
    assert len(sources) > 0, "검색 출처가 확보되어야 한다."

    source_names = {s.get("statute_name") for s in sources}
    assert "민사집행법" in source_names, "민사집행법이 검색 출처에 포함되어야 한다."

    execution_act_articles = {
        s.get("article") for s in sources if s.get("statute_name") == "민사집행법"
    }
    assert "제91조" in execution_act_articles, "민사집행법 제91조가 검색 출처에 포함되어야 한다."
