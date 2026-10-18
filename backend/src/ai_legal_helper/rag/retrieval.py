"""
모듈명: retrieval.py

[모듈 개요]
Chroma 벡터 데이터베이스를 기반으로 법률 문서 청크를 검색하는 RAG 검색 모듈이다.

[주요 기능]
1. Chroma 클라이언트 연결 (HttpClient 또는 로컬 PersistentClient)
2. 법률 분야별 컬렉션(law_docs_*) 대상 유사도 검색
3. 검색 메타데이터(파일명, 페이지 번호 등) 보존 및 Span 추적
"""
import os
from typing import List, Optional, Tuple

import chromadb
from langchain_chroma import Chroma

from ai_legal_helper.llm.gateway import get_embeddings
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.agents.constants import collection_name_for
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span

logger = get_logger(__name__)

# P1.2 Local DB integration
LOCAL_CHROMA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/chroma"))
CHROMA_PERSIST = os.getenv("CHROMA_PERSIST", LOCAL_CHROMA_PATH)

_client = None

@trace
def _get_client():
    """Chroma 클라이언트 인스턴스를 반환한다.

    테스트 환경에서는 EphemeralClient, 분산 환경에서는 HttpClient를 시도하며,
    원격 서버에 법령 컬렉션이 없거나 연결에 실패할 경우 로컬 PersistentClient(data/chroma)로 전환한다.

    Returns:
        chromadb.Client: 구성된 Chroma 클라이언트 객체
    """
    global _client
    if _client is None:
        if os.getenv("TESTING") == "1":
            _client = chromadb.EphemeralClient()
            logger.debug("[RET] EphemeralClient init for tests")
            return _client
            
        chroma_host = os.getenv("CHROMA_HOST")
        persist_dir = os.getenv("CHROMA_PERSIST", LOCAL_CHROMA_PATH)
        if not os.path.isabs(persist_dir):
            persist_dir = os.path.abspath(persist_dir)

        if chroma_host:
            chroma_port = os.getenv("CHROMA_PORT", "8000")
            try:
                client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
                cols = client.list_collections()
                names = [getattr(c, "name", "") for c in cols]
                if any(n.startswith("law_docs_") for n in names):
                    _client = client
                    logger.debug(f"[RET] HttpClient connected: {chroma_host}:{chroma_port} ({len(names)} collections)")
                    return _client
                logger.warning(f"[RET] HttpClient({chroma_host}:{chroma_port})에 law_docs 컬렉션 부재. 로컬 PersistentClient({persist_dir})로 전환합니다.")
            except Exception as e:
                logger.warning(f"[RET] HttpClient 연결 실패: {e}. 로컬 PersistentClient({persist_dir})로 전환합니다.")

        # 로컬 data/chroma 우선 확인
        if not os.path.exists(persist_dir) and os.path.exists(LOCAL_CHROMA_PATH):
            persist_dir = LOCAL_CHROMA_PATH
        try:
            os.makedirs(persist_dir, exist_ok=True)
            _client = chromadb.PersistentClient(path=persist_dir)
            logger.debug(f"[RET] PersistentClient init: {persist_dir}")
        except Exception as e:
            logger.warning(f"[RET] PersistentClient 초기화 실패({e}), EphemeralClient 폴백으로 전환합니다.")
            _client = chromadb.EphemeralClient()
    return _client

@trace
def _get_vs(coll_name: str) -> Chroma:
    """특정 컬렉션에 대한 LangChain Chroma 벡터스토어 객체를 반환한다."""
    return Chroma(client=_get_client(), collection_name=coll_name, embedding_function=get_embeddings())

@trace
def _list_collections() -> List[str]:
    """현재 연결된 Chroma 클라이언트의 컬렉션 이름 목록을 반환한다."""
    try:
        cols = _get_client().list_collections()
        names = [getattr(c, "name", "") if hasattr(c, "name") else str(c) for c in cols]
        logger.debug(f"[RET] collections={names}")
        return names
    except Exception as e:
        logger.warning(f"[RET] 컬렉션 목록 조회 실패: {e}")
        return []

@trace
def retrieve(query: str, k: int = 3, category: Optional[str] = None) -> List:
    """질의에 대해 연관 법률 문서 청크를 검색한다.

    Args:
        query: 법률 검색 질의어
        k: 반환할 상위 문서 개수 (기본 3개)
        category: 법률 카테고리 (지정 시 단일 컬렉션 대상 검색)

    Returns:
        List[Document]: 검색된 LangChain Document 객체 리스트
    """
    if not query:
        return []

    def _normalize_doc(d):
        if hasattr(d, "metadata") and isinstance(d.metadata, dict):
            fn = d.metadata.get("file_name")
            if fn:
                d.metadata["file_name"] = os.path.basename(fn)
        return d

    if category:
        coll = collection_name_for(category)
        if coll not in _list_collections():
            logger.warning(f"[RET] 컬렉션 없음: {coll}")
            return []
        try:
            vs = _get_vs(coll)
            docs = vs.similarity_search(query, k=k)
            docs = [_normalize_doc(d) for d in docs]
            logger.debug(f"[RET] hits={len(docs)} coll={coll}")
            try:
                update_span(get_current_span_id(), {"search_type": "Chroma_Single", "hits": len(docs), "collection": coll, "top_k": k})
            except Exception:
                pass
            return docs
        except Exception as e:
            logger.warning(f"[RET] 단일 컬렉션 검색 실패(coll={coll}): {e}")
            return []

    colls = [n for n in _list_collections() if n.startswith("law_docs_")]
    if not colls:
        return []
    per = max(1, k // max(1, len(colls)) + 1)
    hits: List[Tuple] = []
    for coll in colls:
        try:
            vs = _get_vs(coll)
            for doc, score in vs.similarity_search_with_relevance_scores(query, k=per):
                hits.append((doc, score))
        except Exception as e:
            logger.warning(f"[RET] skip coll={coll}: {e}")
    hits.sort(key=lambda x: x[1], reverse=True)
    try:
        update_span(get_current_span_id(), {"search_type": "Chroma_Multi", "hits": len(hits), "top_k": k})
    except:
        pass
    return [_normalize_doc(d) for d, _ in hits[:k]]
