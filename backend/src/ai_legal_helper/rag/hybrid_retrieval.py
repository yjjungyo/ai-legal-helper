# -*- coding: utf-8 -*-
"""
모듈명: hybrid_retrieval.py

[모듈 개요]
Dense 벡터 검색(ChromaDB)과 Sparse 어휘 검색(BM25)을 결합하고,
법률 특화 재순위화(Reranking) 및 Parent-Child 원문 복원을 수행하는 고도화 하이브리드 RAG 검색 모듈이다.

[주요 기능]
1. Dense + BM25 하이브리드 검색 및 상호 순위 융합(Reciprocal Rank Fusion, RRF)
2. 법령명 및 조문 번호(예: 제6조, 제26조) 완전 일치 부스팅(+0.30, +0.25)
3. 어휘 중첩도(Lexical Overlap) 기반 관련성 재평가
4. Parent-Child 원문 복원: 세부 Child 청크 매칭 시 조문 전체 원문(Parent Content)으로 확장 복원
5. 중복 청크 제거(Deduplication)를 통한 상위 K개 결과의 정보 다양성 확보
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple
from langchain_core.documents import Document

from ai_legal_helper.rag.bm25_retriever import (
    ARTICLE_TOKEN_RE,
    tokenize_legal_text,
    get_or_build_bm25_index,
)
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


def compute_rrf_score(
    dense_ranks: Dict[str, int],
    bm25_ranks: Dict[str, int],
    doc_id: str,
    k_rrf: int = 60,
    dense_weight: float = 0.6,
    bm25_weight: float = 0.4,
) -> float:
    """RRF (Reciprocal Rank Fusion) 알고리즘을 통해 단일 문서의 융합 순위 점수를 계산한다.

    Score = (w_dense / (k_rrf + rank_dense)) + (w_bm25 / (k_rrf + rank_bm25))

    Args:
        dense_ranks: Dense 검색 결과의 {chunk_id: 1-based rank} 매핑.
        bm25_ranks: BM25 검색 결과의 {chunk_id: 1-based rank} 매핑.
        doc_id: 평가 대상 문서 chunk_id.
        k_rrf: 순위 평활화 상수 (기본값: 60).
        dense_weight: Dense 검색 가중치 (기본값: 0.6).
        bm25_weight: BM25 검색 가중치 (기본값: 0.4).

    Returns:
        float: 계산된 RRF 융합 점수.
    """
    score = 0.0
    if doc_id in dense_ranks:
        score += dense_weight / (k_rrf + dense_ranks[doc_id])
    if doc_id in bm25_ranks:
        score += bm25_weight / (k_rrf + bm25_ranks[doc_id])
    return score


def rerank_legal_candidates(
    query: str,
    candidates: List[Tuple[Document, float]],
    top_k: int = 3,
    article_boost_weight: float = 0.30,
    law_name_boost_weight: float = 0.25,
    lexical_boost_weight: float = 0.15,
) -> List[Tuple[Document, float]]:
    """하이브리드 후보군에 대해 법령명, 조문 번호 일치 및 어휘 겹침 가중치를 반영하여 최종 재순위화한다.

    Args:
        query: 사용자 법률 질의어.
        candidates: (Document, 융합 점수) 튜플 리스트.
        top_k: 반환할 상위 결과 수.
        article_boost_weight: 조문 번호 일치 가중치 (기본 0.30).
        law_name_boost_weight: 법령명 일치 가중치 (기본 0.25).
        lexical_boost_weight: 어휘 중첩 가중치 (기본 0.15).

    Returns:
        List[Tuple[Document, float]]: 재순위화된 상위 K개 (Document, 최종 점수) 튜플 리스트.
    """
    if not candidates:
        return []

    # 질의어 분석
    clean_query = query or ""
    query_articles = [re.sub(r"\s+", "", m.group(0)) for m in ARTICLE_TOKEN_RE.finditer(clean_query)]
    query_tokens = set(tokenize_legal_text(clean_query))

    rescored: List[Tuple[Document, float]] = []

    for doc, base_score in candidates:
        meta = getattr(doc, "metadata", {}) or {}
        content = getattr(doc, "page_content", "") or ""

        doc_art = str(meta.get("article") or "").strip().replace(" ", "")
        doc_law = str(meta.get("law_name") or "").strip()

        # 1. 조문 번호 일치 부스팅 (+0.30)
        art_boost = 0.0
        if query_articles and doc_art:
            for qa in query_articles:
                if qa == doc_art or qa in content.replace(" ", ""):
                    art_boost = article_boost_weight
                    break

        # 2. 법령명 일치 부스팅 (+0.25)
        law_boost = 0.0
        if doc_law and (doc_law in clean_query or clean_query in doc_law):
            law_boost = law_name_boost_weight

        # 3. 어휘 중첩도 부스팅 (+0.15)
        lex_boost = 0.0
        if query_tokens:
            doc_tokens = set(tokenize_legal_text(content))
            if doc_tokens:
                overlap = len(query_tokens.intersection(doc_tokens))
                lex_boost = lexical_boost_weight * min(1.0, overlap / max(1, len(query_tokens)))

        final_score = base_score + art_boost + law_boost + lex_boost
        rescored.append((doc, final_score))

    rescored.sort(key=lambda x: x[1], reverse=True)
    return rescored[:top_k]


def restore_parent_content(doc: Document) -> Document:
    """Parent-Child 청크인 경우 전체 조문 원문(parent_content)을 복원한 새 Document를 반환한다.

    다운스트림 Specialist LLM이 잘리지 않은 완전한 법률 조문 맥락을 검토할 수 있도록 보장한다.

    Args:
        doc: 검색된 원본 Document (Child 청크).

    Returns:
        Document: 본문이 전체 조문 원문으로 복원되고 검색 스니펫이 메타데이터에 보존된 Document.
    """
    meta = getattr(doc, "metadata", {}) or {}
    parent_content = meta.get("parent_content")
    if parent_content and isinstance(parent_content, str) and parent_content.strip():
        # 원본 child snippet은 메타에 보존하고, page_content는 전체 parent_content로 확장
        new_meta = dict(meta)
        new_meta["child_snippet"] = doc.page_content
        law_name = meta.get("law_name", "")
        formatted_content = (
            f"[{law_name}] {parent_content}"
            if law_name and not parent_content.startswith(f"[{law_name}]")
            else parent_content
        )
        return Document(page_content=formatted_content, metadata=new_meta)
    return doc


class HybridLegalRetriever:
    """Dense + BM25 + Reranking + Parent-Child 통합 법률 검색 엔진."""

    def __init__(
        self,
        vectorstore: Any,
        collection_name: str,
        dense_weight: float = 0.6,
        bm25_weight: float = 0.4,
        enable_reranking: bool = True,
        enable_parent_restoration: bool = True,
    ):
        """하이브리드 리트리버 초기화.

        Args:
            vectorstore: LangChain Chroma 벡터스토어 객체.
            collection_name: ChromaDB 컬렉션명 (예: 'law_docs_civil').
            dense_weight: Dense 벡터 검색 가중치 (기본 0.6).
            bm25_weight: BM25 어휘 검색 가중치 (기본 0.4).
            enable_reranking: 조문/법령명 일치 가중 재순위화 적용 여부 (기본 True).
            enable_parent_restoration: Parent-Child 전체 조문 원문 복원 적용 여부 (기본 True).
        """
        self.vs = vectorstore
        self.collection_name = collection_name
        self.dense_weight = dense_weight
        self.bm25_weight = bm25_weight
        self.enable_reranking = enable_reranking
        self.enable_parent_restoration = enable_parent_restoration

    def search_hybrid(self, query: str, top_k: int = 3, fetch_k: int = 15) -> List[Document]:
        """하이브리드 RAG 검색을 수행하고 최종 정렬된 문서 리스트를 반환한다.

        Args:
            query: 법률 검색 질의어.
            top_k: 반환할 최종 상위 문서 개수.
            fetch_k: 1차 후보군 수집 개수 (기본 15개).

        Returns:
            List[Document]: 재순위화 및 원문 복원이 완료된 최종 Document 리스트.
        """
        if not query or not query.strip():
            return []

        # 1. Dense 검색 수행 (유사도 점수 획득)
        dense_docs_scored: List[Tuple[Document, float]] = []
        try:
            dense_docs_scored = self.vs.similarity_search_with_relevance_scores(query, k=fetch_k)
        except Exception:
            try:
                raw_dense = self.vs.similarity_search(query, k=fetch_k)
                dense_docs_scored = [(d, 0.75) for d in raw_dense]
            except Exception as ex:
                logger.warning(f"[HYBRID] Dense search error: {ex}")

        # 2. BM25 검색 수행
        bm25_docs_scored: List[Tuple[Document, float]] = []
        try:
            bm25_index = get_or_build_bm25_index(self.collection_name)
            if bm25_index.bm25 is not None:
                bm25_docs_scored = bm25_index.search(query, top_k=fetch_k)
            else:
                # BM25 인덱스가 비어있는 경우 vectorstore에서 초기 로드 시도
                col = self.vs._collection
                if col.count() > 0:
                    records = col.get(include=["documents", "metadatas"], limit=2000)
                    all_docs = []
                    texts = records.get("documents", []) or []
                    metas = records.get("metadatas", []) or []
                    for t, m in zip(texts, metas):
                        all_docs.append(Document(page_content=t, metadata=m or {}))
                    bm25_index.build_index(all_docs)
                    from ai_legal_helper.rag.bm25_retriever import _BM25_CACHE
                    _BM25_CACHE[self.collection_name] = bm25_index
                    bm25_docs_scored = bm25_index.search(query, top_k=fetch_k)
        except Exception as ex:
            logger.warning(f"[HYBRID] BM25 search error: {ex}")

        # 3. 문서 고유 식별자 기준 매핑
        doc_pool: Dict[str, Document] = {}
        dense_ranks: Dict[str, int] = {}
        bm25_ranks: Dict[str, int] = {}

        for rank_idx, (doc, _) in enumerate(dense_docs_scored):
            meta = getattr(doc, "metadata", {}) or {}
            c_id = meta.get("chunk_id") or meta.get("source_id") or f"dense_{rank_idx}"
            doc_pool[c_id] = doc
            dense_ranks[c_id] = rank_idx + 1

        for rank_idx, (doc, _) in enumerate(bm25_docs_scored):
            meta = getattr(doc, "metadata", {}) or {}
            c_id = meta.get("chunk_id") or meta.get("source_id") or f"bm25_{rank_idx}"
            if c_id not in doc_pool:
                doc_pool[c_id] = doc
            bm25_ranks[c_id] = rank_idx + 1

        # 4. RRF 융합 점수 계산
        fused_candidates: List[Tuple[Document, float]] = []
        for c_id, doc in doc_pool.items():
            rrf = compute_rrf_score(
                dense_ranks=dense_ranks,
                bm25_ranks=bm25_ranks,
                doc_id=c_id,
                dense_weight=self.dense_weight,
                bm25_weight=self.bm25_weight,
            )
            fused_candidates.append((doc, rrf))

        # 5. Reranking 수행 (또는 단순 RRF 정렬)
        if self.enable_reranking:
            final_scored = rerank_legal_candidates(query, fused_candidates, top_k=top_k * 2)
        else:
            fused_candidates.sort(key=lambda x: x[1], reverse=True)
            final_scored = fused_candidates[: top_k * 2]

        # 6. 조문 중복 제거 (상위 결과에서 동일 조문이 반복되는 현상 방지)
        seen_articles = set()
        dedup_docs: List[Document] = []
        for doc, _ in final_scored:
            meta = getattr(doc, "metadata", {}) or {}
            art_key = (meta.get("law_name"), meta.get("article"))
            if art_key[1] and art_key in seen_articles:
                continue
            if art_key[1]:
                seen_articles.add(art_key)
            dedup_docs.append(doc)
            if len(dedup_docs) >= top_k:
                break

        # 7. Parent-Child 원문 복원 (활성화 시)
        if self.enable_parent_restoration:
            return [restore_parent_content(d) for d in dedup_docs]
        return dedup_docs
