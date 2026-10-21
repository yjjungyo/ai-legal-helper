# -*- coding: utf-8 -*-
"""
AI Legal Helper - 법령 인덱싱 및 RAG 엔드-투-엔드 통합 테스트.

이 모듈은 ChromaDB 환경에서 법령 PDF 파싱, 청킹, 임베딩 적재,
비법령 컬렉션(case_evidence)의 안전한 보존, 그리고 검색 상태 조회를 엔드-투-엔드로 검증한다.
"""

from unittest.mock import MagicMock, patch
import pytest
import chromadb
from langchain_core.documents import Document

from ai_legal_helper.rag.indexer import build_statute_index, PROTECTED_COLLECTIONS
from ai_legal_helper.rag.retrieval import retrieve_with_status, RetrievalStatus


@pytest.fixture
def mock_chroma_client():
    """테스트용 인메모리 Ephemeral ChromaClient 생성 및 초기 컬렉션 시딩."""
    client = chromadb.EphemeralClient()
    # case_evidence 컬렉션 사전 생성 (보존 대상 검증용)
    ev_col = client.get_or_create_collection(name="case_evidence")
    ev_col.add(
        ids=["ev_1", "ev_2"],
        documents=["임대차계약서 보증금 3억원", "전화 통화 녹취록"],
        metadatas=[{"case_id": "c1"}, {"case_id": "c1"}],
        embeddings=[[0.1] * 128, [0.2] * 128],
    )
    return client


class TestRAGIndexingE2E:
    """법령 RAG 인덱싱 및 검색 통합 테스트."""

    def test_indexing_preserves_case_evidence(self, mock_chroma_client):
        """법령 인덱싱 시 case_evidence 등 비법령 컬렉션이 절대 삭제되지 않고 데이터가 온전히 보존되어야 한다."""
        ev_col = mock_chroma_client.get_collection("case_evidence")
        initial_ev_count = ev_col.count()
        assert initial_ev_count == 2

        # 가짜 임베딩 모델 (128차원)
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.side_effect = lambda texts: [[0.05] * 128 for _ in texts]

        with patch("ai_legal_helper.rag.indexer._get_client", return_value=mock_chroma_client), \
             patch("ai_legal_helper.rag.indexer.get_embeddings", return_value=mock_embeddings):

            res = build_statute_index(
                data_dir="docs/statute_pdf",
                target_categories=["국제"],  # 빠른 테스트를 위해 공공외교법/여권법만 색인
                reindex=True,
                batch_size=20,
            )

            assert res["total_chunks"] > 0
            assert "law_docs_international" in res["collections"]

            # case_evidence 컬렉션 확인: 삭제되거나 영향받지 않아야 함
            ev_col_after = mock_chroma_client.get_collection("case_evidence")
            assert ev_col_after.count() == initial_ev_count
            assert "case_evidence" in [c.name for c in mock_chroma_client.list_collections()]

    def test_retrieve_with_status_after_indexing(self, mock_chroma_client):
        """인덱싱 완료 후 retrieve_with_status를 통해 SUCCESS 상태와 문서를 획득할 수 있어야 한다."""
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.side_effect = lambda texts: [[0.05] * 128 for _ in texts]
        mock_embeddings.embed_query.return_value = [0.05] * 128

        with patch("ai_legal_helper.rag.indexer._get_client", return_value=mock_chroma_client), \
             patch("ai_legal_helper.rag.retrieval._get_client", return_value=mock_chroma_client), \
             patch("ai_legal_helper.rag.indexer.get_embeddings", return_value=mock_embeddings), \
             patch("ai_legal_helper.rag.retrieval.get_embeddings", return_value=mock_embeddings), \
             patch("ai_legal_helper.llm.gateway.get_embeddings", return_value=mock_embeddings):

            # 국제 분야 인덱싱
            build_statute_index(
                data_dir="docs/statute_pdf",
                target_categories=["국제"],
                reindex=True,
                batch_size=20,
            )

            # 검색 질의
            res = retrieve_with_status(query="공공외교 기본계획 수립", k=3, category="국제")
            assert res.status == RetrievalStatus.SUCCESS
            assert len(res.documents) > 0
            assert res.collection_name == "law_docs_international"

            # 미존재 카테고리 검색 시 COLLECTION_MISSING 반환 확인
            res_missing = retrieve_with_status(query="민법 질문", k=3, category="민법")
            assert res_missing.status == RetrievalStatus.COLLECTION_MISSING
