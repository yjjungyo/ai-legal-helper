# -*- coding: utf-8 -*-
"""P1: 기존 세 가지 청킹 전략 모두 PDF 파일명 날짜를 조문 시행일로 승격하지 않는다."""
import pytest

from ai_legal_helper.rag.chunker import ChunkingStrategy, StatuteChunker
from ai_legal_helper.rag.statute_parser import LawMetadata, ArticleSegment, ParagraphSegment


@pytest.mark.parametrize("strategy", list(ChunkingStrategy))
def test_legacy_pdf_date_is_only_unverified_hint(strategy):
    """법령 파일명에 나타난 날짜는 공식 XML 확인 전까지 검증된 시행일이 아니다."""
    meta = LawMetadata(
        law_name="테스트법",
        effective_date="2027-01-15",
        category="민법",
        file_name="테스트법(법률)(제9999호)(20270115).pdf",
    )
    art = ArticleSegment(
        article_no="제4조",
        article_title="시험",
        title_line="제4조(시험)",
        body_lines=["테스트 규정의 본문입니다."],
        paragraphs=[ParagraphSegment(paragraph_no="본문", text="테스트 규정의 본문입니다.")],
    )
    docs = StatuteChunker(strategy=strategy).chunk_statute(meta, [art])
    assert docs, f"{strategy}는 적어도 하나의 청크를 생성해야 합니다."
    for doc in docs:
        md = doc.metadata
        assert "effective_date" not in md, "파일명 날짜를 공식 시행일로 저장하면 안 됩니다."
        assert md["filename_date_hint"] == "2027-01-15"
        assert md["effective_date_basis"] == "FILENAME_INFERRED"
        assert md["temporal_status"] == "UNCONFIRMED"
