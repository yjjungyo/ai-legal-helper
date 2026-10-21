# -*- coding: utf-8 -*-
"""
AI Legal Helper - 청킹 전략(Fixed-size, Article-aware, Parent-Child) 단위 테스트.

이 모듈은 지시서에 명시된 3대 청킹 전략별 동작, 메타데이터 스키마 완비성,
해시 기반 고유성 및 Parent-Child 원문 보존을 결정론적으로 검증한다.
"""

import pytest

from ai_legal_helper.rag.chunker import (
    ChunkingStrategy,
    StatuteChunker,
    compute_content_hash,
)
from ai_legal_helper.rag.statute_parser import (
    ArticleSegment,
    LawMetadata,
    ParagraphSegment,
)


@pytest.fixture
def sample_law_metadata():
    """테스트용 기본 법령 메타데이터."""
    return LawMetadata(
        law_name="근로기준법",
        doc_type="법률",
        law_number="제20520호",
        effective_date="2025-10-23",
        category="노동",
        file_name="근로기준법(법률)(제20520호)(20251023).pdf",
        total_pages=23,
    )


@pytest.fixture
def sample_articles():
    """테스트용 조문 목록 (단문 1건, 복합문 1건, 긴 조문 1건)."""
    art1 = ArticleSegment(
        article_no="제1조",
        article_title="목적",
        title_line="제1조(목적)",
        start_page=1,
        end_page=1,
        body_lines=["이 법은 헌법에 따라 근로조건의 기준을 정함으로써 근로자의 기본적 생활을 보장함을 목적으로 한다."],
        paragraphs=[
            ParagraphSegment(
                paragraph_no="본문",
                text="이 법은 헌법에 따라 근로조건의 기준을 정함으로써 근로자의 기본적 생활을 보장함을 목적으로 한다.",
                start_page=1,
                end_page=1,
            )
        ],
    )

    art2 = ArticleSegment(
        article_no="제2조",
        article_title="정의",
        title_line="제2조(정의)",
        start_page=1,
        end_page=1,
        body_lines=[
            "① 이 법에서 사용하는 용어의 뜻은 다음과 같다.",
            "1. \"근로자\"란 임금을 목적으로 근로를 제공하는 사람을 말한다.",
            "2. \"사용자\"란 사업주 또는 경영담당자를 말한다.",
            "② 제1항 각 호 외의 용어는 관계 법령에 따른다.",
        ],
        paragraphs=[
            ParagraphSegment(
                paragraph_no="①",
                text="이 법에서 사용하는 용어의 뜻은 다음과 같다.",
                items=[
                    "1. \"근로자\"란 임금을 목적으로 근로를 제공하는 사람을 말한다.",
                    "2. \"사용자\"란 사업주 또는 경영담당자를 말한다.",
                ],
                start_page=1,
                end_page=1,
            ),
            ParagraphSegment(
                paragraph_no="②",
                text="제1항 각 호 외의 용어는 관계 법령에 따른다.",
                items=[],
                start_page=1,
                end_page=1,
            ),
        ],
    )

    # 1500자 초과 긴 조문
    long_body = ["매우 긴 법률 조문 본문 내용입니다. " * 50]
    art_long = ArticleSegment(
        article_no="제100조",
        article_title="특별규정",
        title_line="제100조(특별규정)",
        start_page=10,
        end_page=11,
        body_lines=long_body,
        paragraphs=[
            ParagraphSegment(
                paragraph_no="①",
                text="긴 조문 제1항입니다. " * 30,
                start_page=10,
                end_page=10,
            ),
            ParagraphSegment(
                paragraph_no="②",
                text="긴 조문 제2항입니다. " * 30,
                start_page=10,
                end_page=11,
            ),
        ],
    )

    return [art1, art2, art_long]


class TestChunkingStrategies:
    """3대 청킹 전략별 검증 테스트 클래스."""

    def test_strategy_a_fixed_size(self, sample_law_metadata, sample_articles):
        """[전략 A] Fixed-size 분할 시 800자 이내 크기로 분할되고 표준 메타데이터가 보존되어야 한다."""
        chunker = StatuteChunker(strategy=ChunkingStrategy.FIXED_SIZE, fixed_chunk_size=800, fixed_chunk_overlap=120)
        docs = chunker.chunk_statute(sample_law_metadata, sample_articles)

        assert len(docs) >= 1
        for d in docs:
            # 800자 + 헤더 길이 이내
            assert len(d.page_content) <= 900
            assert d.metadata["chunk_strategy"] == "FIXED_SIZE"
            assert d.metadata["law_name"] == "근로기준법"
            assert d.metadata["content_hash"] == compute_content_hash(d.page_content.replace(f"[{sample_law_metadata.law_name}] ", ""))

    def test_strategy_b_article_aware(self, sample_law_metadata, sample_articles):
        """[전략 B] Article-aware 분할 시 일반 조문은 1조문=1청크가 되고 긴 조문은 항 단위로 분할되어야 한다."""
        chunker = StatuteChunker(strategy=ChunkingStrategy.ARTICLE_AWARE, long_article_threshold=1000)
        docs = chunker.chunk_statute(sample_law_metadata, sample_articles)

        # 제1조와 제2조는 단일 청크, 제100조는 2개 항으로 분할되므로 총 4개 이상
        assert len(docs) == 4

        # 제1조 청크 검증
        d_art1 = docs[0]
        assert d_art1.metadata["article"] == "제1조"
        assert d_art1.metadata["article_title"] == "목적"
        assert "이 법은 헌법에 따라" in d_art1.page_content

        # 제100조 분할 청크 검증
        d_long_p1 = docs[2]
        d_long_p2 = docs[3]
        assert d_long_p1.metadata["article"] == "제100조"
        assert d_long_p1.metadata["paragraph_no"] == "①"
        assert d_long_p2.metadata["paragraph_no"] == "②"

    def test_strategy_c_parent_child(self, sample_law_metadata, sample_articles):
        """[전략 C] Parent-Child 분할 시 세부 항·호 검색 청크가 생성되고 parent_content에 전체 조문이 보존되어야 한다."""
        chunker = StatuteChunker(strategy=ChunkingStrategy.PARENT_CHILD)
        docs = chunker.chunk_statute(sample_law_metadata, sample_articles)

        # 제1조 (단문: 1개 Child) + 제2조 (2개 항: 2개 Child) + 제100조 (2개 항: 2개 Child) = 총 5개 Child
        assert len(docs) == 5

        # 메타데이터 완비성 검증 (source_id, chunk_id, document_id, parent_id, parent_content, content_hash 등)
        for d in docs:
            assert d.metadata["chunk_strategy"] == "PARENT_CHILD"
            assert d.metadata["chunk_type"] == "child"
            assert d.metadata["source_type"] == "STATUTE"
            assert "source_id" in d.metadata
            assert "chunk_id" in d.metadata
            assert "document_id" in d.metadata
            assert "parent_id" in d.metadata
            assert "parent_content" in d.metadata
            assert "content_hash" in d.metadata
            assert len(d.metadata["content_hash"]) == 64  # SHA-256

        # 제2조 Child 검증: page_content는 세부 항·호이고 parent_content는 조문 전체
        child_p1 = docs[1]
        assert child_p1.metadata["article"] == "제2조"
        assert child_p1.metadata["paragraph_no"] == "①"
        assert "제2조(정의) ①" in child_p1.page_content
        # parent_content 에는 제2항까지 포함된 전체 조문 보존
        assert "제1항 각 호 외의 용어" in child_p1.metadata["parent_content"]
        assert "이 법에서 사용하는 용어의 뜻" in child_p1.metadata["parent_content"]

    def test_content_hash_consistency(self):
        """동일 텍스트에 대한 SHA-256 해시가 일관되게 생성되어야 한다."""
        t1 = "제1조(목적) 이 법은 법률의 목적을 규정한다."
        t2 = "제1조(목적) 이 법은 법률의 목적을 규정한다."
        t3 = "제1조(목적) 다른 내용"
        assert compute_content_hash(t1) == compute_content_hash(t2)
        assert compute_content_hash(t1) != compute_content_hash(t3)

