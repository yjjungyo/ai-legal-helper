# -*- coding: utf-8 -*-
import logging
from typing import List, Dict, Any

from langchain_core.documents import Document

from ai_legal_helper.rag.retrieval import _get_client, _get_vs
from ai_legal_helper.observability.decorators import trace

logger = logging.getLogger(__name__)

EVIDENCE_COLLECTION_NAME = "case_evidence"

@trace
def sync_evidence_to_vector_store(case_id: str, documents: List[Document]):
    """해당 사건의 기존 벡터를 모두 지우고 새 문서를 삽입한다 (멱등)."""
    try:
        vs = _get_vs(EVIDENCE_COLLECTION_NAME)
        # 삭제
        try:
            # ChromaDB v0.4+ _collection.delete
            vs._collection.delete(where={"case_id": case_id})
        except Exception as e:
            logger.warning(f"Chroma delete error for case {case_id}: {e}")
        
        # 삽입
        if documents:
            vs.add_documents(documents)
            logger.info(f"Vector sync completed for case {case_id}, inserted {len(documents)} docs.")
    except Exception as e:
        logger.error(f"Failed to sync vector store for case {case_id}: {e}")
        raise e

@trace
def retrieve_evidence_vector(case_id: str, query: str, k: int = 5) -> List[Document]:
    """해당 사건의 증거 벡터를 검색한다."""
    try:
        vs = _get_vs(EVIDENCE_COLLECTION_NAME)
        # similarity_search with metadata filter
        docs = vs.similarity_search(query, k=k, filter={"case_id": case_id})
        return docs
    except Exception as e:
        logger.error(f"Vector retrieval failed for case {case_id}: {e}")
        return []

