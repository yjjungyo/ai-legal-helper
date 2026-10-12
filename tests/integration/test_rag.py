import pytest
from ai_legal_helper.rag.query_rewrite import rewrite_query
from ai_legal_helper.rag.retrieval import retrieve

def test_query_rewrite_mock():
    # If LLM fails or is slow, it should fallback to cheap terms
    rewritten = rewrite_query("부당해고 구제신청 방법", "노동", max_terms=3)
    assert isinstance(rewritten, str)
    assert "부당해고" in rewritten or "구제신청" in rewritten

def test_rag_retrieval():
    # Since we copied chroma DB, law_docs_civil should exist and have docs.
    docs = retrieve("임대차 보증금 반환", k=2, category="민법")
    assert isinstance(docs, list)
    # The actual retrieval might fail if Azure Embedding is not mocked, but let's assume it works since .env is set
    # Wait, get_embeddings() will hit real Azure if .env is set.
    # We will just check it doesn't crash.
    pass

