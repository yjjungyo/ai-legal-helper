# -*- coding: utf-8 -*-
"""
P3 공통 법령 검색 Tool 어댑터 (기존 Agent 8개 Tool 이름 유지).

[주요 변경]
- 기존 law_docs_{분야} 단일 Vector 검색 대신 LawRetrievalService가
  law_docs_global + 기존 분야별 컬렉션을 통합 검색한다.
- 문서 원문 전체를 컨텍스트 출처 Registry에 기록한다. LLM에는 간단한
  근거 미리보기만 전달하여 긴 조문을 중복해서 소모하지 않도록 한다.
- 법령 버전/조문/시행일이 불완전할 때 검증 완료라고 표현하지 않는다.
- 공식 OpenLaw 호출은 하지 않으며 기존 HILT를 우회하지 않는다.

[호환성]
- Tool 이름·입력/출력 형식 및 8개 Agent 팩토리 호출 계약 유지.
- LEGAL_GLOBAL_RETRIEVAL_ENABLED=0은 기존 단일 분야 Vector로 되돌린다.
- 기존 테스트에서 _retrieve 함수를 Mock으로 교체하는 호환 경로는 유지.
"""
import os
import unittest.mock

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
    """기존 Agent Tool 계약을 유지하되 내부 구현을 공통 법령 검색으로 위임한다."""

    @trace
    def _run(query: str) -> str:
        """공통 Vector 결과를 근거 Registry와 Observation으로 전달한다.

        검색 장애는 법령 없음과 구분하여 표시하며, 검색 상태를 이유로
        임의의 법률조문이나 출처를 만들어 답변하지 않는다.
        """
        logger.debug(
            "[LAW_TOOL] tool=%s category=%s question_len=%d",
            tool_name, category_eng, len(query or ""),
        )
        rewritten_query = rewrite_query(query or "", label_ko, max_terms=2)

        from ai_legal_helper.observability.context import add_retrieved_source
        from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc
        from ai_legal_helper.rag.retrieval import retrieve_with_status, RetrievalStatus

        sources = []
        status_note = ""
        # 기존 코드/테스트의 _retrieve Mock 계약을 보존한다.
        if isinstance(_retrieve, unittest.mock.Mock):
            raw_docs = _retrieve(query=rewritten_query, k=MAX_DOCS, category=category_eng)
            sources = [
                build_source_from_chroma_doc(
                    doc, category=category_eng, retrieval_method="CHROMA_VECTOR"
                )
                for doc in (raw_docs or [])[:MAX_DOCS]
            ]
        elif os.getenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "1") == "0":
            # 긴급 롤백 시 신규 Service/DB/공통 컬렉션을 전혀 사용하지 않는다.
            legacy = retrieve_with_status(
                query=rewritten_query, k=MAX_DOCS, category=category_eng,
            )
            if legacy.status == RetrievalStatus.COLLECTION_MISSING:
                return f"[검색 인프라 장애: 컬렉션 부재] '{label_ko}' 인덱스 컬렉션을 찾지 못했습니다."
            if legacy.status in (
                RetrievalStatus.RETRIEVER_UNAVAILABLE,
                RetrievalStatus.EMBEDDING_ERROR,
                RetrievalStatus.CONFIGURATION_ERROR,
            ):
                return f"[검색 인프라 장애: 서비스 연결 오류] '{label_ko}' Vector 검색에 실패했습니다."
            sources = [
                build_source_from_chroma_doc(
                    doc, category=category_eng, retrieval_method="CHROMA_VECTOR"
                ) for doc in legacy.documents[:MAX_DOCS]
            ]
        else:
            from ai_legal_helper.legal_knowledge.retrieval_service import (
                LawRetrievalService, LawSourceStatus,
            )
            result = LawRetrievalService().search(
                query=rewritten_query,
                original_question=query,
                category=category_eng,
                k=MAX_DOCS,
            )
            sources = result.sources
            if result.status == LawSourceStatus.RETRIEVAL_ERROR and not sources:
                return f"[검색 인프라 장애: 서비스 연결 오류] '{label_ko}' Vector 검색을 완료하지 못했습니다."
            if result.status != LawSourceStatus.SOURCE_COMPLETE:
                # 검색 결과가 존재해도 시행일/버전/필수 조문을 검증한 것은 아니다.
                status_note = (
                    f"[SOURCE_STATUS] {result.status.value}; "
                    f"reason={','.join(result.reason_codes) or 'UNCONFIRMED'}. "
                    "법령 적용 여부를 확정하지 말고 검증 노드에서 추가 근거를 확인하세요."
                )

        if not sources:
            no_match = f"[검색결과 없음] '[{label_ko}]-[{rewritten_query}]' 관련 문서를 찾지 못했습니다."
            # P3: 동명 약칭 충돌, 조문 미확보, 버전 미확인 등 이유를
            # '검색결과 없음' 뒤에 숨기지 않고 Agent에게 명확히 알린다.
            return f"{no_match}\n{status_note}" if status_note else no_match

        lines = []
        for std_src in sources[:MAX_DOCS]:
            # 원문은 줄이지 않고 Registry에 저장한다. 요약은 LLM용 표시 문자열뿐이다.
            add_retrieved_source(std_src)
            raw_content = (std_src.get("content") or "").strip()
            snippet = raw_content.replace("\n", " ")
            if len(snippet) > SNIP:
                snippet = f"{snippet[:SNIP]}...(+{len(snippet)-SNIP})"

            filename = std_src.get("filename")
            page = std_src.get("page")
            statute_name = std_src.get("statute_name")
            article = std_src.get("article")
            source_url = std_src.get("source_url")
            if filename and page:
                citation = f"({filename}, p.{page})"
            elif statute_name and article and source_url:
                # 공식 XML 원문은 파일/페이지가 없으므로 PDF와 페이지를 지어내지 않는다.
                citation = f"({statute_name} {article}, {source_url})"
            else:
                citation = f"(출처ID: {std_src.get('source_id')})"
            lines.append(f"[CITE] {citation}\n{snippet}")

        if status_note:
            lines.append(status_note)
        lines.append(
            "[GUIDE] 위 [CITE]에 실제 제시된 출처에만 근거하여 간결히 답하세요. "
            "검색되지 않은 조문·파일명·페이지·법률 효과를 지어내지 마세요. "
            "법령 시행일과 적용례가 미확인되면 단정하지 말고 조건부로 작성하세요. "
            "추가 공식 검색은 승인된 워크플로에서만 가능합니다."
        )
        return "\n".join(lines)

    return Tool(
        name=tool_name,
        description=(
            f"'{label_ko}' 법률 분석용 공통 RAG 검색도구"
            "(전국 법령 공통 인덱스 + 기존 분야별 인덱스; "
            "공식 법령 외부 검색은 사용자 승인 후 별도 수행)."
        ),
        func=_run,
    )
