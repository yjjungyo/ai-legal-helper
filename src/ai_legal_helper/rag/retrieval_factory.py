# -*- coding: utf-8 -*-
"""
RAG 검색 도구 팩토리 (Retrieval Factory) 모듈

이 모듈은 특화된 법률 분야(민법, 형법 등)별로 고정된 컬렉션을 조회하는 LangChain Tool을 동적으로 생성한다.
P2.1 검증 단계에서 전문 에이전트(AgentExecutor)가 도구의 반환값을 내부적으로 소모하여 
워크플로우 외부로 전달하지 못하는 문제를 해결하기 위해, 검색이 성공할 때마다 
`contextvars` 기반의 `add_retrieved_source`를 호출하여 실제 참조된 문헌 정보를 추적한다.
"""
from __future__ import annotations
from langchain_core.tools import Tool

from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.rag.retrieval import retrieve as _retrieve
from ai_legal_helper.rag.query_rewrite import rewrite_query

logger = get_logger(__name__)

MAX_DOCS = 2
SNIP = 240

@trace
def make_fixed_retrieval_tool(tool_name: str, category_eng: str, label_ko: str) -> Tool:
    """
    특정 법률 분야 전용 RAG 검색 도구(LangChain Tool)를 생성하여 반환한다.

    생성된 도구는 검색어 재작성(Rewrite)을 거쳐 Chroma DB에서 연관 문서를 검색하며, 
    검색된 각 문서는 `add_retrieved_source`를 통해 현재 실행 컨텍스트에 저장된다.
    이를 통해 상위 Supervisor 노드나 Verification 에이전트가 어떤 문서를 근거로 답변이 작성되었는지 파악할 수 있다.

    Args:
        tool_name (str): 생성될 도구의 이름 (예: "search_civil_law")
        category_eng (str): Chroma DB 컬렉션 식별을 위한 영문 카테고리 (예: "civil")
        label_ko (str): 검색어 재작성 및 로깅에 사용될 한글 분야명 (예: "민법")

    Returns:
        Tool: LangChain Agent에서 사용할 수 있는 Tool 인스턴스
    """
    @trace
    def _run(query: str) -> str:
        """
        실제 검색 도구가 호출될 때 실행되는 함수.
        
        흐름:
        1. 검색어 재작성 (rewrite_query)
        2. Chroma 문서 검색 (retrieve)
        3. 검색된 결과를 컨텍스트 변수에 저장 (add_retrieved_source)
        4. LLM이 이해하기 쉬운 문자열 형태로 요약하여 반환
        """
        logger.debug(f"[TOOL:{tool_name}] query_len={len(query or '')} label={label_ko} eng={category_eng}")
        
        rewritten_query = rewrite_query(query or "", label_ko, max_terms=2)
        
        from ai_legal_helper.observability.context import add_retrieved_source

        docs = _retrieve(query=rewritten_query, k=MAX_DOCS, category=category_eng)
        if not docs:
            return f"[검색결과 없음] '[{label_ko}]-[{rewritten_query}]' 관련 문서를 찾지 못했습니다."

        lines = []
        for d in docs[:MAX_DOCS]:
            m = d.metadata or {}
            fn = m.get("file_name", "?")
            p1 = m.get("page", "?")
            p2 = m.get("page_end", p1)
            page_disp = str(p1) if p1 == p2 or p2 in (None, "?", "") else f"{p1}-{p2}"
            source_id = f"{fn}_{page_disp}"

            snip = (d.page_content or "").strip().replace("\n", " ")
            
            # P2.1: AgentExecutor가 출처를 숨기는 문제를 우회하기 위해 전역 컨텍스트에 기록
            add_retrieved_source({
                "source_id": source_id,
                "file_name": fn,
                "page": page_disp,
                "content": snip,
                "category": category_eng
            })

            if len(snip) > SNIP:
                snip = f"{snip[:SNIP]}...(+{len(d.page_content)-SNIP})"

            lines.append(f"[CITE] file={fn} page={page_disp}\n{snip}")

        lines.append("[GUIDE] 위 1~3건을 근거로 즉시 최종 답변을 작성하세요. 추가 검색 금지.")
        return "\n".join(lines)

    return Tool(
        name=tool_name,
        description=f"'{label_ko}' 전용 RAG 검색도구(컬렉션 law_docs_{category_eng}).",
        func=_run,
    )
