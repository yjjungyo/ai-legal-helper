# -*- coding: utf-8 -*-
"""
AI Legal Helper - 법령 PDF 구조 파서 단위 테스트.

이 모듈은 국가법령정보센터 표준 서식의 법령 PDF 파싱, 파일명 정규식,
조문(Article), 항(Paragraph), 호(Item) 계층 구조 분할 및 페이지 보존 기능을 결정론적으로 검증한다.
"""

import os
import pytest

from ai_legal_helper.rag.statute_parser import (
    FILE_NAME_RE,
    LawMetadata,
    ArticleSegment,
    ParagraphSegment,
    normalize_date,
    parse_filename_metadata,
    parse_article_paragraphs,
    parse_statute_pdf,
)


class TestStatuteParser:
    """법령 파일명 정규식 및 메타데이터 추출 테스트."""

    def test_filename_metadata_exact_match(self):
        """표준 법령 파일명으로부터 법령명, 구분, 법령번호, 시행일자를 정확히 추출해야 한다."""
        filename = "근로기준법(법률)(제20520호)(20251023).pdf"
        meta = parse_filename_metadata(filename)
        assert meta.law_name == "근로기준법"
        assert meta.doc_type == "법률"
        assert meta.law_number == "제20520호"
        assert meta.effective_date == "2025-10-23"
        assert meta.category == "노동"

    def test_filename_constitution_match(self):
        """대한민국헌법 파일명에서 헌법 카테고리와 메타데이터를 추출해야 한다."""
        filename = "대한민국헌법(헌법)(제00010호)(19880225).pdf"
        meta = parse_filename_metadata(filename)
        assert meta.law_name == "대한민국헌법"
        assert meta.category == "헌법"
        assert meta.effective_date == "1988-02-25"

    def test_normalize_date_formats(self):
        """8자리 숫자 및 다양한 날짜 형식을 YYYY-MM-DD로 정규화해야 한다."""
        assert normalize_date("20251023") == "2025-10-23"
        assert normalize_date("2024. 6. 27.") == "2024. 6. 27."
        assert normalize_date("") == ""


class TestArticleParagraphParsing:
    """조문 본문의 항(①, ②) 및 호(1., 2.) 분할 로직 테스트."""

    def test_multi_paragraphs_and_items(self):
        """조문에 복수 항과 호가 포함된 경우 각각의 ParagraphSegment로 정밀 분할되어야 한다."""
        article = ArticleSegment(
            article_no="제2조",
            article_title="정의",
            title_line="제2조(정의)",
            start_page=1,
            end_page=1,
            body_lines=[
                "① 이 법에서 사용하는 용어의 뜻은 다음과 같다.",
                "1. \"근로자\"란 직업의 종류와 관계없이 임금을 목적으로 사업이나 사업장에 근로를 제공하는 사람을 말한다.",
                "2. \"사용자\"란 사업주 또는 사업 경영 담당자를 말한다.",
                "② 제1항 각 호 외의 용어는 관계 법령에 따른다.",
            ],
        )

        paragraphs = parse_article_paragraphs(article)
        assert len(paragraphs) == 2
        # 제1항
        assert paragraphs[0].paragraph_no == "①"
        assert "이 법에서 사용하는 용어" in paragraphs[0].text
        assert len(paragraphs[0].items) == 2
        assert "1. \"근로자\"" in paragraphs[0].items[0]
        assert "2. \"사용자\"" in paragraphs[0].items[1]
        # 제2항
        assert paragraphs[1].paragraph_no == "②"
        assert "제1항 각 호 외의 용어" in paragraphs[1].text
        assert len(paragraphs[1].items) == 0

    def test_single_paragraph_simple_article(self):
        """항 번호가 없는 단문 조문의 경우 '본문'으로 단일 ParagraphSegment가 생성되어야 한다."""
        article = ArticleSegment(
            article_no="제1조",
            article_title="목적",
            title_line="제1조(목적)",
            start_page=1,
            end_page=1,
            body_lines=["이 법은 근로조건의 기준을 정함으로써 근로자의 기본적 생활을 보장하는 것을 목적으로 한다."],
        )

        paragraphs = parse_article_paragraphs(article)
        assert len(paragraphs) == 1
        assert paragraphs[0].paragraph_no == "본문"
        assert "근로조건의 기준" in paragraphs[0].text


class TestRealPDFParsing:
    """실제 docs/statute_pdf 내 파일 파싱 테스트."""

    def test_parse_public_diplomacy_pdf(self):
        """공공외교법 PDF를 파싱하여 기본 메타데이터와 조문이 정상 생성되는지 검증한다."""
        pdf_path = "docs/statute_pdf/공공외교법(법률)(제19272호)(20230629).pdf"
        if not os.path.exists(pdf_path):
            pytest.skip("테스트용 PDF 파일이 로컬에 없습니다.")

        meta, articles = parse_statute_pdf(pdf_path)
        assert meta.law_name == "공공외교법"
        assert meta.category == "국제"
        assert meta.total_pages == 3
        assert len(articles) >= 13

        # 제1조 목적 확인
        art1 = articles[0]
        assert art1.article_no == "제1조"
        assert art1.article_title == "목적"
        assert art1.start_page == 1
        assert "공공외교 활동에 필요한 사항" in art1.full_text

        # 제8조의2 본조신설 조문 파싱 확인
        branch_art = [a for a in articles if a.article_no == "제8조의2"]
        assert len(branch_art) == 1
        assert branch_art[0].article_title == "재외공관의 역할"

