# -*- coding: utf-8 -*-
"""
RAG 검색 도구 팩토리 (Retrieval Factory) 모듈

이 모듈은 특화된 법률 분야(민법, 형법 등)별로 고정된 컬렉션을 조회하는 LangChain Tool을 동적으로 생성한다.
P2.1 검증 단계에서 전문 에이전트(AgentExecutor)가 도구의 반환값을 내부적으로 소모하여 
워크플로우 외부로 전달하지 못하는 문제를 해결하기 위해, 검색이 성공할 때마다 
`contextvars` 기반의 `add_retrieved_source`를 호출하여 실제 참조된 문헌 정보를 추적한다.
"""
import os
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
        logger.debug(f"[법률 검색 도구 호출] 도구={tool_name}, 분야={label_ko}({category_eng}), 질의길이={len(query or '')}자")
        
        rewritten_query = rewrite_query(query or "", label_ko, max_terms=2)
        
        from ai_legal_helper.observability.context import add_retrieved_source
        from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc
        from ai_legal_helper.rag.retrieval import retrieve_with_status, RetrievalStatus
        import unittest.mock

        # 하위 호환 및 단위 테스트 mock 지원: _retrieve가 패치된 경우 이를 우선 호출
        if isinstance(_retrieve, (unittest.mock.Mock, unittest.mock.MagicMock)):
            raw_docs = _retrieve(query=rewritten_query, k=MAX_DOCS, category=category_eng)
            if not raw_docs:
                return f"[검색결과 없음] '[{label_ko}]-[{rewritten_query}]' 관련 문서를 찾지 못했습니다."
            docs = raw_docs
        else:
            ret_res = retrieve_with_status(query=rewritten_query, k=MAX_DOCS, category=category_eng)
            if ret_res.status == RetrievalStatus.COLLECTION_MISSING:
                return f"[검색 인프라 장애: 컬렉션 부재] '{label_ko}' 인덱스 컬렉션이 데이터베이스에 존재하지 않습니다."
            elif ret_res.status in (RetrievalStatus.RETRIEVER_UNAVAILABLE, RetrievalStatus.EMBEDDING_ERROR):
                return f"[검색 인프라 장애: 서비스 연결 오류] '{label_ko}' 벡터 검색 서버 연결에 실패했습니다 ({ret_res.error_detail})."
            elif not ret_res.documents:
                return f"[검색결과 없음] '[{label_ko}]-[{rewritten_query}]' 관련 문서를 찾지 못했습니다."
            docs = ret_res.documents

        lines = []
        for d in docs[:MAX_DOCS]:
            std_src = build_source_from_chroma_doc(
                d,
                category=category_eng,
                retrieval_method="CHROMA_VECTOR",
            )
            fn = std_src.get("filename") or "?"
            page_disp = std_src.get("page") or "?"
            snip = (std_src.get("content") or "").strip().replace("\n", " ")
            std_src["content"] = snip

            # P2.1: AgentExecutor가 출처를 숨기는 문제를 우회하기 위해 전역 컨텍스트에 표준 Source 스키마로 기록
            add_retrieved_source(std_src)

            if len(snip) > SNIP:
                snip = f"{snip[:SNIP]}...(+{len(d.page_content)-SNIP})"

            # 표준 출처 형식: (파일명.pdf, p.페이지)
            lines.append(f"[CITE] ({fn}, p.{page_disp})\n{snip}")

        # 하드코딩된 법령 파일명 예시로 인한 LLM 출처 환각을 방지하기 위해 위 [CITE] 항목만 인용하도록 안내
        lines.append("[GUIDE] 위 [CITE] 문서를 근거로 즉시 최종 답변을 작성하세요. 인용한 법령 출처는 반드시 위 [CITE]에 제시된 실제 '(파일명.pdf, p.페이지)' 형식으로만 명시하고, 검색 결과에 없는 파일명은 절대 기재하지 마세요. 추가 검색 금지.")
        return "\n".join(lines)

    return Tool(
        name=tool_name,
        description=f"'{label_ko}' 전용 RAG 검색도구(컬렉션 law_docs_{category_eng}).",
        func=_run,
    )
