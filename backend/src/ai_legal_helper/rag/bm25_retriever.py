# -*- coding: utf-8 -*-
"""
모듈명: bm25_retriever.py

[모듈 개요]
법령 조문 및 청크 텍스트에 대해 고속 어휘(Lexical) 검색을 수행하는 BM25 검색 엔진 모듈이다.
법률 조문 번호(예: 제6조, 제12조의2), 법령명, 법률 전문 용어를 고유 토큰으로 추출하여
희소 검색(Sparse Retrieval) 점수를 산출한다.

[주요 기능]
1. 한국어 법률 특화 토큰화 (조문번호, 법령명, 2글자 이상 한글 명사/단어 보존)
2. rank_bm25 (BM25Okapi) 인메모리 인덱스 구축 및 쿼리 점수화
3. 컬렉션별 BM25 인덱스 캐싱 및 증분 업데이트 지원
"""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document

# 조문 번호 패턴: 제12조, 제12조의2, 제1001조
ARTICLE_TOKEN_RE = re.compile(r"제\s*\d+\s*(?:조의\s*\d+|조)")
# 한글, 영문, 숫자 어휘 토큰 패턴
WORD_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z0-9]{2,}")


def tokenize_legal_text(text: str) -> List[str]:
    """법률 텍스트에서 검색용 고유 토큰 리스트를 추출한다.

    조문 번호(예: "제6조의2")는 공백을 제거하여 단일 독립 토큰으로 보존하며,
    일반 한국어 어휘 및 영문·숫자 키워드를 함께 추출한다.

    Args:
        text: 대상 원문 문자열.

    Returns:
        List[str]: 정규화된 토큰 문자열 리스트.
    """
    if not text:
        return []

    tokens: List[str] = []

    # 1. 조문 번호 토큰 추출 및 정규화
    for m in ARTICLE_TOKEN_RE.finditer(text):
        clean_art = re.sub(r"\s+", "", m.group(0))
        tokens.append(clean_art)

    # 2. 일반 단어 토큰 및 한국어 복합명사 서브토큰 추출
    lower_text = text.lower()
    for m in WORD_TOKEN_RE.finditer(lower_text):
        word = m.group(0)
        tokens.append(word)
        # 한국어 4음절 이상 복합명사에 대한 2~3음절 서브토큰 분해 (예: 부동산임차인은 -> 부동산, 임차인 등)
        if len(word) >= 4 and re.match(r"^[가-힣]+$", word):
            for sub_len in (2, 3):
                for i in range(len(word) - sub_len + 1):
                    tokens.append(word[i : i + sub_len])

    return tokens


class LegalBM25Index:
    """단일 법률 분야 컬렉션을 위한 BM25 검색 인덱스 클래스."""

    def __init__(self, collection_name: str):
        """인덱스 초기화.

        Args:
            collection_name: 대상 ChromaDB 컬렉션명 (예: 'law_docs_civil').
        """
        self.collection_name = collection_name
        self.documents: List[Document] = []
        self.corpus_tokens: List[List[str]] = []
        self.bm25: Optional[BM25Okapi] = None

    def build_index(self, documents: List[Document]) -> None:
        """주어진 Document 리스트로부터 BM25 인덱스를 구축한다.

        Args:
            documents: 인덱싱할 LangChain Document 객체 리스트.
        """
        self.documents = list(documents)
        self.corpus_tokens = []

        for doc in self.documents:
            # page_content + 조문 메타데이터 결합 텍스트 토큰화
            meta = getattr(doc, "metadata", {}) or {}
            law_name = meta.get("law_name", "")
            art = meta.get("article", "")
            art_title = meta.get("article_title", "")
            
            combined_text = f"{law_name} {art} {art_title}\n{doc.page_content}"
            tokens = tokenize_legal_text(combined_text)
            self.corpus_tokens.append(tokens)

        if self.corpus_tokens:
            self.bm25 = BM25Okapi(self.corpus_tokens)
        else:
            self.bm25 = None

    def search(self, query: str, top_k: int = 10) -> List[Tuple[Document, float]]:
        """질의어에 대한 BM25 유사도 검색을 수행하고 상위 K개 (문서, 점수) 튜플을 반환한다.

        Args:
            query: 사용자 검색 질의어.
            top_k: 반환할 상위 문서 개수.

        Returns:
            List[Tuple[Document, float]]: (Document, BM25 점수) 튜플 리스트 (점수 내림차순).
        """
        if not self.bm25 or not self.documents:
            return []

        query_tokens = tokenize_legal_text(query)
        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)
        
        scored_pairs: List[Tuple[Document, float]] = []
        for doc, score in zip(self.documents, scores):
            if score > 0.0:
                scored_pairs.append((doc, float(score)))

        scored_pairs.sort(key=lambda x: x[1], reverse=True)
        return scored_pairs[:top_k]


# 전역 인메모리 BM25 인덱스 캐시: {collection_name: LegalBM25Index}
_BM25_CACHE: Dict[str, LegalBM25Index] = {}


def get_or_build_bm25_index(collection_name: str, documents: Optional[List[Document]] = None) -> LegalBM25Index:
    """특정 컬렉션에 대한 BM25 인덱스를 캐시에서 획득하거나 새로 구축한다.

    Args:
        collection_name: 컬렉션명 (예: 'law_docs_labor').
        documents: 인덱스가 캐시되지 않았을 때 구축에 사용할 문서 리스트.

    Returns:
        LegalBM25Index: 활성화된 BM25 인덱스 객체.
    """
    global _BM25_CACHE
    if collection_name in _BM25_CACHE and _BM25_CACHE[collection_name].bm25 is not None:
        return _BM25_CACHE[collection_name]

    if collection_name in _BM25_CACHE:
        index = _BM25_CACHE[collection_name]
    else:
        index = LegalBM25Index(collection_name)
        _BM25_CACHE[collection_name] = index

    if documents:
        index.build_index(documents)
        _BM25_CACHE[collection_name] = index
    return index


def clear_bm25_cache(collection_name: Optional[str] = None) -> None:
    """BM25 인덱스 캐시를 무효화한다 (재인덱싱 후 호출).

    Args:
        collection_name: 특정 컬렉션명만 초기화할 경우 지정, None일 경우 전체 초기화.
    """
    global _BM25_CACHE
    if collection_name:
        _BM25_CACHE.pop(collection_name, None)
    else:
        _BM25_CACHE.clear()
