# -*- coding: utf-8 -*-
"""
AI Legal Helper - BM25 어휘 검색 및 하이브리드 재순위화 단위 테스트.

이 모듈은 한국어 법률 특화 토큰화, BM25 인덱싱, RRF 순위 융합,
조문/법령명 가중 재순위화 및 Parent-Child 원문 복원 기능을 결정론적으로 검증한다.
"""

from unittest.mock import MagicMock
import pytest
from langchain_core.documents import Document

from ai_legal_helper.rag.bm25_retriever import (
    LegalBM25Index,
    tokenize_legal_text,
)
from ai_legal_helper.rag.hybrid_retrieval import (
    HybridLegalRetriever,
    compute_rrf_score,
    rerank_legal_candidates,
    restore_parent_content,
)


class TestBM25Retriever:
    """법률 텍스트 토큰화 및 BM25 검색 로직 테스트."""

    def test_tokenize_legal_text_preserves_articles(self):
        """조문 번호(제6조, 제12조의2)가 단일 토큰으로 정규화되어 보존되어야 한다."""
        text = "근로기준법 제26조(해고의 예고) 및 제621조의2 규정에 따른 임금 지급."
        tokens = tokenize_legal_text(text)
        assert "제26조" in tokens
        assert "제621조의2" in tokens
        assert "근로기준법" in tokens
        assert "해고의" in tokens or "해고" in tokens

    def test_bm25_index_search(self):
        """BM25 인덱스를 통해 질의어와 일치하는 키워드를 포함한 문서가 상위에 랭크되어야 한다."""
        doc1 = Document(
            page_content="근로기준법 제26조 사용자는 근로자를 해고하려면 적어도 30일 전에 예고를 하여야 한다.",
            metadata={"article": "제26조", "law_name": "근로기준법"},
        )
        doc2 = Document(
            page_content="민법 제621조 부동산임차인은 당사자간에 반대약정이 없으면 임대차등기절차에 협력할 것을 청구할 수 있다.",
            metadata={"article": "제621조", "law_name": "민법"},
        )
        doc3 = Document(
            page_content="형법 제347조 사람을 기망하여 재물의 교부를 받거나 재산상의 이익을 취득한 자는 처벌한다.",
            metadata={"article": "제347조", "law_name": "형법"},
        )

        idx = LegalBM25Index(collection_name="test_col")
        idx.build_index([doc1, doc2, doc3])

        # "해고 예고 30일 전" 질의 시 doc1이 1위여야 함
        res1 = idx.search("해고 예고 30일 전", top_k=2)
        assert len(res1) > 0
        assert res1[0][0].metadata["article"] == "제26조"

        # "부동산 임대차 등기" 질의 시 doc2가 1위여야 함
        res2 = idx.search("부동산 임대차 등기", top_k=2)
        assert len(res2) > 0
        assert res2[0][0].metadata["article"] == "제621조"


class TestHybridFusionAndRerank:
    """RRF 순위 융합 및 Reranking 테스트."""

    def test_compute_rrf_score_formula(self):
        """Dense 순위와 BM25 순위가 결합되어 올바른 RRF 점수가 산출되어야 한다."""
        dense_ranks = {"doc_a": 1, "doc_b": 2}
        bm25_ranks = {"doc_a": 3, "doc_b": 1}

        # doc_a: (0.6 / (60 + 1)) + (0.4 / (60 + 3)) = (0.6/61) + (0.4/63) = 0.009836 + 0.006349 = 0.016185
        score_a = compute_rrf_score(dense_ranks, bm25_ranks, "doc_a", k_rrf=60, dense_weight=0.6, bm25_weight=0.4)
        assert score_a > 0.015

        # 양쪽 모두 없는 문서 점수는 0
        score_c = compute_rrf_score(dense_ranks, bm25_ranks, "doc_none", k_rrf=60)
        assert score_c == 0.0

    def test_rerank_with_exact_article_and_law_boost(self):
        """질의어에 포함된 조문 번호(제26조)와 법령명(근로기준법)이 일치할 경우 부스팅이 적용되어 1위로 상승해야 한다."""
        doc_generic = Document(
            page_content="근로조건의 기준 및 일반 해고 관련 판례 안내",
            metadata={"article": "제23조", "law_name": "근로기준법"},
        )
        doc_exact = Document(
            page_content="근로기준법 제26조(해고의 예고) 사용자는 근로자를 해고하려면 30일 전에 예고해야 한다.",
            metadata={"article": "제26조", "law_name": "근로기준법"},
        )

        candidates = [
            (doc_generic, 0.90),  # 기본 점수는 generic이 더 높음
            (doc_exact, 0.70),
        ]

        # 질의어: "근로기준법 제26조 해고예고 요건"
        reranked = rerank_legal_candidates(
            query="근로기준법 제26조 해고예고 요건",
            candidates=candidates,
            top_k=2,
            article_boost_weight=0.30,
            law_name_boost_weight=0.25,
        )

        # doc_exact가 부스팅을 받아 1위로 역전되어야 함
        assert reranked[0][0].metadata["article"] == "제26조"
        assert reranked[0][1] > reranked[1][1]

    def test_restore_parent_content(self):
        """Child 청크 검색 시 parent_content가 존재하면 전체 조문 본문으로 복원되고 원본 스니펫이 메타에 저장되어야 한다."""
        child_doc = Document(
            page_content="[근로기준법] 제2조(정의) ① 1. '근로자'란 직업의 종류와 관계없이 임금을 목적으로 근로를 제공하는 사람을 말한다.",
            metadata={
                "chunk_id": "근로기준법_제2조_c1",
                "article": "제2조",
                "law_name": "근로기준법",
                "parent_content": "제2조(정의) ① 이 법에서 사용하는 용어의 뜻은 다음과 같다.\n1. '근로자'란...\n2. '사용자'란...\n② 제1항 각 호 외의 용어는...",
            },
        )

        expanded = restore_parent_content(child_doc)
        # 본문이 parent_content로 확장되었는지 확인
        assert "[근로기준법] 제2조(정의) ① 이 법에서 사용하는 용어의 뜻은 다음과 같다." in expanded.page_content
        assert "② 제1항 각 호 외의 용어는" in expanded.page_content
        # child_snippet이 보존되었는지 확인
        assert expanded.metadata["child_snippet"] == child_doc.page_content


class TestHybridLegalRetriever:
    """HybridLegalRetriever 클래스 통합 동작 테스트."""

    def test_search_hybrid_e2e(self):
        """Mock 벡터스토어를 주입한 HybridLegalRetriever가 정상적으로 융합 검색을 수행하는지 검증한다."""
        mock_vs = MagicMock()
        doc_a = Document(
            page_content="근로기준법 제26조 해고의 예고 30일 전",
            metadata={"chunk_id": "c_26", "article": "제26조", "law_name": "근로기준법"},
        )
        mock_vs.similarity_search_with_relevance_scores.return_value = [(doc_a, 0.85)]
        mock_vs._collection.count.return_value = 1
        mock_vs._collection.get.return_value = {
            "documents": [doc_a.page_content],
            "metadatas": [doc_a.metadata],
        }

        retriever = HybridLegalRetriever(
            vectorstore=mock_vs,
            collection_name="test_col",
            dense_weight=0.6,
            bm25_weight=0.4,
            enable_reranking=True,
            enable_parent_restoration=True,
        )

        results = retriever.search_hybrid(query="근로기준법 제26조 해고예고", top_k=2)
        assert len(results) >= 1
        assert results[0].metadata["article"] == "제26조"

