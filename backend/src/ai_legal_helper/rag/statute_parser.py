# -*- coding: utf-8 -*-
"""
모듈명: statute_parser.py

[모듈 개요]
대한민국 공식 법령 PDF(국가법령정보센터 서식)로부터 법령 기본 메타데이터(법령명, 법령구분, 법령번호, 시행일자)
및 조문(조·항·호·목) 구조화 세그먼트를 정밀 추출하는 법령 전문 파서 모듈이다.

[주요 기능]
1. PDF 파일명 및 헤더 기반 법령 메타데이터(LawMetadata) 자동 파싱
2. 페이지별 텍스트 추출 및 머리말/꼬리말(법제처 워터마크, 페이지 번호) 노이즈 제거
3. 법령 구조(편/장/절/관/조/항/호/목/부칙) 계층 정규식 파싱
4. 시작 페이지 및 종료 페이지(1-based) 추적을 통한 정확한 출처 메타데이터 보존
"""

from __future__ import annotations
from dataclasses import dataclass, field
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import fitz  # PyMuPDF

from ai_legal_helper.agents.constants import CATEGORIES


# ==============================================================================
# 정규식 패턴 정의 (대한민국 법령 표준 형식)
# ==============================================================================

# 파일명 패턴: 예) 근로기준법(법률)(제20520호)(20251023).pdf
FILE_NAME_RE = re.compile(
    r"^\s*(?P<law>[^()]+)\((?P<type>[^)]+)\)\((?P<number>[^)]+)\)\((?P<date>\d{8})\)\.pdf\s*$",
    re.IGNORECASE,
)

# 머리말 노이즈: 법제처  1  국가법령정보센터
HEADER_NOISE_RE = re.compile(r"^법제처\s+\d+\s+국가법령정보센터.*$")

# 법령 상위 구조 패턴
PART_RE = re.compile(r"^\s*제\s*(\d+)\s*편\b(?:\s+(.+))?")
CHAPTER_RE = re.compile(r"^\s*제\s*(\d+)\s*장\b(?:\s+(.+))?")
SECTION_RE = re.compile(r"^\s*제\s*(\d+)\s*절\b(?:\s+(.+))?")
SUBSECTION_RE = re.compile(r"^\s*제\s*(\d+)\s*관\b(?:\s+(.+))?")
ADDENDA_RE = re.compile(r"^\s*부\s*칙\b(?:\s*(<[^>]+>))?")

# 조문 패턴: 예) 제1조(목적), 제8조의2(재외공관의 역할), 제 12 조 (적용범위)
ARTICLE_RE = re.compile(
    r"^\s*제\s*(\d+)\s*(?:조의\s*(\d+)|조)\s*(?:\(([^)]+)\))?(?:\s*(.*))?"
)

# 항 번호 기호: ① ~ ⑳
PARAGRAPH_SYMBOL_RE = re.compile(r"^\s*([①-⑳])\s*(.*)")

# 호 번호: 1., 2., 3., 2의2.
ITEM_RE = re.compile(r"^\s*(\d+(?:의\d+)?)\.\s*(.*)")

# 목 번호: 가., 나., 다., 라.
SUBITEM_RE = re.compile(r"^\s*([가-하])\.\s*(.*)")

# 법령명 표준 카테고리 매핑 테이블
STATUTE_CATEGORY_MAP: Dict[str, str] = {
    "대한민국헌법": "헌법",
    "민법": "민법",
    "형법": "형법",
    "상법": "상법",
    "근로기준법": "노동",
    "노동조합 및 노동관계조정법": "노동",
    "고용보험법": "노동",
    "산업안전보건법": "노동",
    "행정기본법": "행정",
    "건축법": "행정",
    "공인중개사법": "행정",
    "농지법": "행정",
    "주택법": "행정",
    "소득세법": "조세",
    "법인세법": "조세",
    "상속세 및 증여세법": "조세",
    "지방세법": "조세",
    "공공외교법": "국제",
    "여권법": "국제",
}


# ==============================================================================
# 데이터 모델 정의
# ==============================================================================

@dataclass
class LawMetadata:
    """법령 파일 및 문서 기본 메타데이터 객체."""
    law_name: str
    doc_type: str = "법률"
    law_number: str = ""
    effective_date: str = ""
    promulgation_date: Optional[str] = None
    category: str = "민법"
    file_name: str = ""
    total_pages: int = 0


@dataclass
class ParagraphSegment:
    """조문 내 세부 항(Paragraph) 또는 호(Item) 세그먼트 객체."""
    paragraph_no: str  # "①", "②", 또는 "본문"
    text: str
    items: List[str] = field(default_factory=list)
    start_page: int = 1
    end_page: int = 1


@dataclass
class ArticleSegment:
    """법령 단일 조문(Article) 세그먼트 객체."""
    part: str = ""
    chapter: str = ""
    section: str = ""
    article_no: str = ""          # "제12조", "제8조의2"
    article_title: str = ""       # "(목적)"의 "목적"
    title_line: str = ""          # "제1조(목적)"
    start_page: int = 1
    end_page: int = 1
    body_lines: List[str] = field(default_factory=list)
    paragraphs: List[ParagraphSegment] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """조문 제목과 본문 전체를 단일 문자열로 결합한다."""
        body = "\n".join(self.body_lines).strip()
        if body:
            return f"{self.title_line}\n{body}"
        return self.title_line


# ==============================================================================
# 파서 헬퍼 함수
# ==============================================================================

def normalize_date(date_str: str) -> str:
    """8자리(YYYYMMDD) 또는 기타 날짜 형식을 표준 YYYY-MM-DD 로 정규화한다."""
    if not date_str:
        return ""
    clean = re.sub(r"[^\d]", "", str(date_str))
    if len(clean) == 8:
        return f"{clean[:4]}-{clean[4:6]}-{clean[6:8]}"
    return date_str.strip()


def parse_filename_metadata(pdf_path: str) -> LawMetadata:
    """파일명 정규식을 통해 법령명, 법령구분, 법령번호, 시행일자, 카테고리를 추출한다.

    Args:
        pdf_path: 대상 PDF 파일 경로.

    Returns:
        LawMetadata: 파싱된 법령 기본 메타데이터 객체.
    """
    file_name = os.path.basename(pdf_path)
    m = FILE_NAME_RE.match(file_name)
    if m:
        law_name = m.group("law").strip()
        doc_type = m.group("type").strip()
        law_number = m.group("number").strip()
        effective_date = normalize_date(m.group("date").strip())
    else:
        # 괄호 기반 느슨한 추출 폴백
        base = Path(file_name).stem
        parts = re.findall(r"\(([^)]+)\)", base)
        law_name = base.split("(")[0].strip() or base
        doc_type = parts[0].strip() if len(parts) > 0 else "법률"
        law_number = parts[1].strip() if len(parts) > 1 else ""
        effective_date = normalize_date(parts[2]) if len(parts) > 2 else ""

    category = STATUTE_CATEGORY_MAP.get(law_name, "민법")
    return LawMetadata(
        law_name=law_name,
        doc_type=doc_type,
        law_number=law_number,
        effective_date=effective_date,
        category=category,
        file_name=file_name,
    )


def extract_pages_from_pdf(pdf_path: str) -> List[Tuple[int, str]]:
    """PyMuPDF를 사용하여 PDF의 각 페이지 텍스트를 (1-based page_no, clean_text) 리스트로 추출한다.

    Args:
        pdf_path: 대상 법령 PDF 경로.

    Returns:
        List[Tuple[int, str]]: (페이지 번호, 페이지 본문 텍스트) 튜플 리스트.
    """
    results: List[Tuple[int, str]] = []
    with fitz.open(pdf_path) as doc:
        for idx, page in enumerate(doc):
            page_no = idx + 1
            raw_text = page.get_text("text") or ""
            # 머리말 노이즈 및 과도한 공백 정제
            clean_lines = []
            for line in raw_text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if HEADER_NOISE_RE.match(stripped):
                    continue
                clean_lines.append(stripped)
            results.append((page_no, "\n".join(clean_lines)))
    return results


def parse_article_paragraphs(article: ArticleSegment) -> List[ParagraphSegment]:
    """조문의 body_lines를 분석하여 항(Paragraph) 및 호(Item) 세그먼트로 세분화한다.

    항 번호 기호(①, ②...)가 명시된 경우 항 단위로 분할하며,
    단일 항인 경우 전체를 단일 ParagraphSegment로 묶는다.

    Args:
        article: 대상 조문 세그먼트.

    Returns:
        List[ParagraphSegment]: 분석된 세부 항 세그먼트 리스트.
    """
    paragraphs: List[ParagraphSegment] = []
    cur_para_no = ""
    cur_para_lines: List[str] = []
    cur_items: List[str] = []

    def flush_para():
        if cur_para_lines or cur_items:
            p_text = "\n".join(cur_para_lines).strip()
            p_no = cur_para_no or "본문"
            paragraphs.append(
                ParagraphSegment(
                    paragraph_no=p_no,
                    text=p_text,
                    items=list(cur_items),
                    start_page=article.start_page,
                    end_page=article.end_page,
                )
            )

    for line in article.body_lines:
        line_clean = line.strip()
        if not line_clean:
            continue

        # 항(①, ②...) 감지
        m_para = PARAGRAPH_SYMBOL_RE.match(line_clean)
        if m_para:
            flush_para()
            cur_para_no = m_para.group(1)
            cur_para_lines = [m_para.group(2).strip()] if m_para.group(2).strip() else []
            cur_items = []
            continue

        # 호(1., 2...) 감지
        m_item = ITEM_RE.match(line_clean)
        if m_item:
            cur_items.append(line_clean)
            continue

        # 일반 본문 누적
        if cur_items:
            # 이전 호의 부속 내용 누적
            cur_items[-1] += " " + line_clean
        else:
            cur_para_lines.append(line_clean)

    flush_para()

    # 항이 하나도 분할되지 않은 경우 (단문 조문 등)
    if not paragraphs:
        fallback_text = "\n".join(article.body_lines).strip()
        paragraphs.append(
            ParagraphSegment(
                paragraph_no="본문",
                text=fallback_text or article.title_line,
                items=[],
                start_page=article.start_page,
                end_page=article.end_page,
            )
        )

    return paragraphs


def parse_statute_pdf(pdf_path: str) -> Tuple[LawMetadata, List[ArticleSegment]]:
    """단일 법령 PDF를 파싱하여 기본 메타데이터와 조문 세그먼트 목록을 반환한다.

    Args:
        pdf_path: 파싱 대상 PDF 경로.

    Returns:
        Tuple[LawMetadata, List[ArticleSegment]]: 법령 메타데이터 및 조문 세그먼트 리스트.
    """
    meta = parse_filename_metadata(pdf_path)
    pages_data = extract_pages_from_pdf(pdf_path)
    meta.total_pages = len(pages_data)

    articles: List[ArticleSegment] = []
    cur_part, cur_chapter, cur_section = "", "", ""
    cur_article: Optional[ArticleSegment] = None
    last_page = 1

    for page_no, page_text in pages_data:
        last_page = page_no
        lines = page_text.splitlines()

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # 상위 계층 구조 갱신
            if ADDENDA_RE.match(line_str):
                cur_part, cur_chapter, cur_section = "부칙", "", ""
                continue
            m_part = PART_RE.match(line_str)
            if m_part:
                cur_part = line_str
                continue
            m_chap = CHAPTER_RE.match(line_str)
            if m_chap:
                cur_chapter = line_str
                continue
            m_sec = SECTION_RE.match(line_str)
            if m_sec:
                cur_section = line_str
                continue

            # 조문 경계 판정
            ma = ARTICLE_RE.match(line_str)
            if ma:
                # 이전 조문 완료 처리
                if cur_article is not None:
                    cur_article.end_page = page_no
                    cur_article.paragraphs = parse_article_paragraphs(cur_article)
                    articles.append(cur_article)

                num = ma.group(1) or ""
                sub = ma.group(2)  # '의2'
                title = (ma.group(3) or "").strip()
                trailing = (ma.group(4) or "").strip()

                if sub:
                    article_no = f"제{num}조의{sub}"
                else:
                    article_no = f"제{num}조"

                title_line = f"{article_no}({title})" if title else article_no

                body_lines = [trailing] if trailing else []
                cur_article = ArticleSegment(
                    part=cur_part,
                    chapter=cur_chapter,
                    section=cur_section,
                    article_no=article_no,
                    article_title=title,
                    title_line=title_line,
                    start_page=page_no,
                    end_page=page_no,
                    body_lines=body_lines,
                )
            else:
                # 조문 본문 누적
                if cur_article is not None:
                    cur_article.body_lines.append(line_str)

    # 마지막 조문 플러시
    if cur_article is not None:
        cur_article.end_page = last_page
        cur_article.paragraphs = parse_article_paragraphs(cur_article)
        articles.append(cur_article)

    return meta, articles

