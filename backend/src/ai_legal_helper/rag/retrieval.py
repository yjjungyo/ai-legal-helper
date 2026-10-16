# -*- coding: utf-8 -*-
from __future__ import annotations
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
    global _client
    if _client is None:
        if os.getenv("TESTING") == "1":
            _client = chromadb.EphemeralClient()
            logger.debug("[RET] EphemeralClient init for tests")
            return _client
            
        chroma_host = os.getenv("CHROMA_HOST")
        if chroma_host:
            chroma_port = os.getenv("CHROMA_PORT", "8000")
            _client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
            logger.debug(f"[RET] HttpClient init: {chroma_host}:{chroma_port}")
        else:
            os.makedirs(CHROMA_PERSIST, exist_ok=True)
            _client = chromadb.PersistentClient(path=CHROMA_PERSIST)
            logger.debug(f"[RET] PersistentClient init: {CHROMA_PERSIST}")
    return _client

@trace
def _get_vs(coll_name: str) -> Chroma:
    return Chroma(client=_get_client(), collection_name=coll_name, embedding_function=get_embeddings())

@trace
def _list_collections() -> List[str]:
    cols = _get_client().list_collections()
    names = [getattr(c, "name", "") for c in cols]
    logger.debug(f"[RET] collections={names}")
    return names

@trace
def retrieve(query: str, k: int = 3, category: Optional[str] = None) -> List:
    if not query:
        return []

    if category:
        coll = collection_name_for(category)
        if coll not in _list_collections():
            logger.warning(f"[RET] 컬렉션 없음: {coll}")
            return []
        vs = _get_vs(coll)
        docs = vs.similarity_search(query, k=k)
        logger.debug(f"[RET] hits={len(docs)} coll={coll}")
        try:
            update_span(get_current_span_id(), {"search_type": "Chroma_Single", "hits": len(docs), "collection": coll, "top_k": k})
        except:
            pass
        return docs

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
    return [d for d, _ in hits[:k]]
