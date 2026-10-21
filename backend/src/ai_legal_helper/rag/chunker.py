# -*- coding: utf-8 -*-
"""
모듈명: chunker.py

[모듈 개요]
법령 조문 및 세그먼트를 RAG 검색용 청크(Document)로 분할하는 청킹 전략 모듈이다.
지시서에 정의된 3대 청킹 전략(Fixed-size, Article-aware, Parent-Child)을 모두 제공하며,
각 전략에 부합하는 표준 메타데이터(source_id, chunk_id, document_id, content_hash 등)를 자동 생성한다.

[청킹 전략 정의]
1. Strategy A: Fixed-size (800자 분할, 120자 Overlap)
2. Strategy B: Article-aware (조문 단위 분할, 1,200자 초과 시 문맥 보존 보조 분할)
3. Strategy C: Parent-Child (기본 후보 - 항·호 중심 세부 검색 청크 + 전체 조문 원문 보존)
"""

from __future__ import annotations
from enum import Enum
import hashlib
from typing import Dict, List, Optional, Tuple
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ai_legal_helper.rag.statute_parser import ArticleSegment, LawMetadata


class ChunkingStrategy(str, Enum):
    """법령 RAG 청킹 전략 열거형."""
    FIXED_SIZE = "FIXED_SIZE"          # 전략 A (800자 / 120 overlap)
    ARTICLE_AWARE = "ARTICLE_AWARE"    # 전략 B (조문 단위)
    PARENT_CHILD = "PARENT_CHILD"      # 전략 C (항·호 검색 + 조문 원문 복원)


def compute_content_hash(text: str) -> str:
    """텍스트 내용의 SHA-256 고유 해시값을 산출한다."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


class StatuteChunker:
    """법령 청킹 엔진 클래스."""

    def __init__(
        self,
        strategy: ChunkingStrategy = ChunkingStrategy.PARENT_CHILD,
        fixed_chunk_size: int = 800,
        fixed_chunk_overlap: int = 120,
        long_article_threshold: int = 1200,
    ):
        """청킹 파라미터 초기화.

        Args:
            strategy: 적용할 청킹 전략 (기본값: PARENT_CHILD).
            fixed_chunk_size: Fixed-size 전략의 청크 크기 (기본 800자).
            fixed_chunk_overlap: Fixed-size 전략의 오버랩 크기 (기본 120자).
            long_article_threshold: Article-aware 전략에서 조문 2차 분할 임계치 (기본 1,200자).
        """
        self.strategy = strategy
        self.fixed_chunk_size = fixed_chunk_size
        self.fixed_chunk_overlap = fixed_chunk_overlap
        self.long_article_threshold = long_article_threshold

        self._fixed_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.fixed_chunk_size,
            chunk_overlap=self.fixed_chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def chunk_statute(
        self,
        meta: LawMetadata,
        articles: List[ArticleSegment],
        include_header_in_content: bool = True,
    ) -> List[Document]:
        """주어진 법령 메타데이터와 조문 목록을 설정된 전략에 따라 Document 청크 리스트로 변환한다.

        Args:
            meta: 법령 파일 메타데이터.
            articles: 파싱된 조문 세그먼트 리스트.
            include_header_in_content: 청크 본문에 '[법령명] 제X조(제목)' 헤더를 포함할지 여부 (기본 True).

        Returns:
            List[Document]: 표준 메타데이터가 완비된 LangChain Document 청크 리스트.
        """
        if self.strategy == ChunkingStrategy.FIXED_SIZE:
            return self._chunk_fixed_size(meta, articles, include_header_in_content)
        elif self.strategy == ChunkingStrategy.ARTICLE_AWARE:
            return self._chunk_article_aware(meta, articles, include_header_in_content)
        elif self.strategy == ChunkingStrategy.PARENT_CHILD:
            return self._chunk_parent_child(meta, articles, include_header_in_content)
        else:
            raise ValueError(f"지원되지 않는 청킹 전략입니다: {self.strategy}")

    # --------------------------------------------------------------------------
    # 전략 A: Fixed-size (800자 / 120 Overlap)
    # --------------------------------------------------------------------------
    def _chunk_fixed_size(
        self,
        meta: LawMetadata,
        articles: List[ArticleSegment],
        include_header: bool,
    ) -> List[Document]:
        """고정 크기 윈도우 기반 청킹."""
        docs: List[Document] = []
        doc_id = f"statute_{meta.law_name}"

        # 법령 전체 텍스트 및 조문별 페이지 매핑 구성
        combined_text_parts = []
        for a in articles:
            combined_text_parts.append(a.full_text)
        full_statute_text = "\n\n".join(combined_text_parts)

        raw_splits = self._fixed_splitter.split_text(full_statute_text)

        for idx, text_chunk in enumerate(raw_splits):
            chunk_id = f"{meta.law_name}_fixed_{idx + 1}"
            chash = compute_content_hash(text_chunk)
            
            # 본문 내 첫 번째 등장하는 조문 번호 추정
            import re
            m = re.search(r"(제\s*\d+\s*(?:조의\s*\d+|조))", text_chunk)
            approx_art = m.group(1).replace(" ", "") if m else ""

            content = f"[{meta.law_name}] {text_chunk}" if include_header else text_chunk

            md: Dict[str, Optional[str]] = {
                "source_id": chunk_id,
                "chunk_id": chunk_id,
                "document_id": doc_id,
                "law_name": meta.law_name,
                "article": approx_art,
                "article_title": "",
                "page": "1",
                "effective_date": meta.effective_date,
                "version_date": meta.effective_date,
                "content_hash": chash,
                "category": meta.category,
                "source_type": "STATUTE",
                "file_name": meta.file_name,
                "chunk_strategy": ChunkingStrategy.FIXED_SIZE.value,
            }
            docs.append(Document(page_content=content, metadata=md))
        return docs

    # --------------------------------------------------------------------------
    # 전략 B: Article-aware (조문 단위 + 초과 시 문맥 보존 분할)
    # --------------------------------------------------------------------------
    def _chunk_article_aware(
        self,
        meta: LawMetadata,
        articles: List[ArticleSegment],
        include_header: bool,
    ) -> List[Document]:
        """조문(Article) 경계 보존 기반 청킹."""
        docs: List[Document] = []
        doc_id = f"statute_{meta.law_name}"
        used_chunk_ids: set[str] = set()

        def make_unique_id(candidate: str) -> str:
            if candidate not in used_chunk_ids:
                used_chunk_ids.add(candidate)
                return candidate
            seq = 2
            while f"{candidate}_{seq}" in used_chunk_ids:
                seq += 1
            unique_id = f"{candidate}_{seq}"
            used_chunk_ids.add(unique_id)
            return unique_id

        for a_idx, article in enumerate(articles):
            full_art_text = article.full_text
            is_addenda = "부칙" in (article.part or "") or "부칙" in (article.chapter or "")
            art_prefix = f"{meta.law_name}_{'부칙_' if is_addenda else ''}{article.article_no}"
            
            # 1,200자 이하인 경우 1개 조문 = 1개 청크
            if len(full_art_text) <= self.long_article_threshold:
                chunk_id = make_unique_id(art_prefix)
                chash = compute_content_hash(full_art_text)
                
                content = (
                    f"[{meta.law_name}] {full_art_text}"
                    if include_header and not full_art_text.startswith(f"[{meta.law_name}]")
                    else full_art_text
                )
                md = {
                    "source_id": chunk_id,
                    "chunk_id": chunk_id,
                    "document_id": doc_id,
                    "law_name": meta.law_name,
                    "article": article.article_no,
                    "article_title": article.article_title,
                    "page": str(article.start_page),
                    "effective_date": meta.effective_date,
                    "version_date": meta.effective_date,
                    "content_hash": chash,
                    "category": meta.category,
                    "source_type": "STATUTE",
                    "file_name": meta.file_name,
                    "chunk_strategy": ChunkingStrategy.ARTICLE_AWARE.value,
                    "part": article.part,
                    "chapter": article.chapter,
                    "section": article.section,
                }
                docs.append(Document(page_content=content, metadata=md))
            else:
                # 긴 조문: 하위 항(Paragraph) 단위 분할
                for p_idx, para in enumerate(article.paragraphs):
                    para_body = para.text
                    if para.items:
                        para_body += "\n" + "\n".join(para.items)

                    chunk_id = make_unique_id(f"{art_prefix}_p{p_idx + 1}")
                    chash = compute_content_hash(para_body)
                    
                    header_line = f"[{meta.law_name}] {article.title_line} {para.paragraph_no}".strip()
                    content = f"{header_line}\n{para_body}" if include_header else para_body

                    md = {
                        "source_id": chunk_id,
                        "chunk_id": chunk_id,
                        "document_id": doc_id,
                        "law_name": meta.law_name,
                        "article": article.article_no,
                        "article_title": article.article_title,
                        "page": str(para.start_page),
                        "effective_date": meta.effective_date,
                        "version_date": meta.effective_date,
                        "content_hash": chash,
                        "category": meta.category,
                        "source_type": "STATUTE",
                        "file_name": meta.file_name,
                        "chunk_strategy": ChunkingStrategy.ARTICLE_AWARE.value,
                        "part": article.part,
                        "chapter": article.chapter,
                        "section": article.section,
                        "paragraph_no": para.paragraph_no,
                    }
                    docs.append(Document(page_content=content, metadata=md))
        return docs

    # --------------------------------------------------------------------------
    # 전략 C: Parent-Child (세부 항·호 검색 + 전체 조문 원문 복원) - 기본 후보
    # --------------------------------------------------------------------------
    def _chunk_parent_child(
        self,
        meta: LawMetadata,
        articles: List[ArticleSegment],
        include_header: bool,
    ) -> List[Document]:
        """Parent-Child 계층 청킹.

        - Child 청크: 항(①, ②...) 및 각 호(Item) 단위의 정밀 검색용 청크.
        - Parent 원문: 해당 조문 전체 텍스트(full_text)를 metadata['parent_content']에 보관하여
          검색 시 최적의 의미 벡터 매칭과 완전한 법률 맥락 복원을 동시 달성.
        """
        docs: List[Document] = []
        doc_id = f"statute_{meta.law_name}"
        used_chunk_ids: set[str] = set()

        def make_unique_id(candidate: str) -> str:
            if candidate not in used_chunk_ids:
                used_chunk_ids.add(candidate)
                return candidate
            seq = 2
            while f"{candidate}_{seq}" in used_chunk_ids:
                seq += 1
            unique_id = f"{candidate}_{seq}"
            used_chunk_ids.add(unique_id)
            return unique_id

        for article in articles:
            is_addenda = "부칙" in (article.part or "") or "부칙" in (article.chapter or "")
            parent_id = f"{meta.law_name}_{'부칙_' if is_addenda else ''}{article.article_no}"
            full_parent_content = article.full_text

            # 만약 조문에 항 분할이 1개뿐인 단문 조문인 경우
            if len(article.paragraphs) == 1 and article.paragraphs[0].paragraph_no == "본문" and not article.paragraphs[0].items:
                chunk_id = make_unique_id(f"{parent_id}_c1")
                chash = compute_content_hash(full_parent_content)

                content = (
                    f"[{meta.law_name}] {full_parent_content}"
                    if include_header and not full_parent_content.startswith(f"[{meta.law_name}]")
                    else full_parent_content
                )
                md = {
                    "source_id": chunk_id,
                    "chunk_id": chunk_id,
                    "document_id": doc_id,
                    "parent_id": parent_id,
                    "parent_content": full_parent_content,
                    "law_name": meta.law_name,
                    "article": article.article_no,
                    "article_title": article.article_title,
                    "page": str(article.start_page),
                    "effective_date": meta.effective_date,
                    "version_date": meta.effective_date,
                    "content_hash": chash,
                    "category": meta.category,
                    "source_type": "STATUTE",
                    "file_name": meta.file_name,
                    "chunk_strategy": ChunkingStrategy.PARENT_CHILD.value,
                    "chunk_type": "child",
                    "part": article.part,
                    "chapter": article.chapter,
                    "section": article.section,
                }
                docs.append(Document(page_content=content, metadata=md))
                continue

            # 복수 항(Paragraph) 또는 호(Item)가 존재하는 경우
            child_idx = 1
            for para in article.paragraphs:
                # 항 본문 텍스트
                para_clean = para.text.strip()
                para_label = "" if para.paragraph_no == "본문" else para.paragraph_no

                # 각 호(Item)가 많은 경우(예: 3개 이상), 호 단위로 추가 Child 생성하여 검색 정밀도 극대화
                if len(para.items) >= 4:
                    # 1. 항 개괄 청크
                    header_label = f"[{meta.law_name}] {article.title_line} {para_label}".strip()
                    main_body = f"{header_label}\n{para_clean}" if include_header else para_clean
                    chash = compute_content_hash(main_body)
                    c_id = make_unique_id(f"{parent_id}_c{child_idx}")
                    child_idx += 1

                    md = {
                        "source_id": c_id,
                        "chunk_id": c_id,
                        "document_id": doc_id,
                        "parent_id": parent_id,
                        "parent_content": full_parent_content,
                        "law_name": meta.law_name,
                        "article": article.article_no,
                        "article_title": article.article_title,
                        "page": str(para.start_page),
                        "effective_date": meta.effective_date,
                        "version_date": meta.effective_date,
                        "content_hash": chash,
                        "category": meta.category,
                        "source_type": "STATUTE",
                        "file_name": meta.file_name,
                        "chunk_strategy": ChunkingStrategy.PARENT_CHILD.value,
                        "chunk_type": "child",
                        "paragraph_no": para.paragraph_no,
                        "part": article.part,
                        "chapter": article.chapter,
                        "section": article.section,
                    }
                    docs.append(Document(page_content=main_body, metadata=md))

                    # 2. 호(Item) 묶음 청크 (2~3개씩 그룹화하여 적정 의미 단위 유지)
                    batch_size = 3
                    for i in range(0, len(para.items), batch_size):
                        sub_items = para.items[i : i + batch_size]
                        items_body = "\n".join(sub_items)
                        sub_content = f"{header_label}\n[관련 호]\n{items_body}" if include_header else items_body
                        c_id = make_unique_id(f"{parent_id}_c{child_idx}")
                        child_idx += 1
                        chash = compute_content_hash(sub_content)

                        sub_md = dict(md)
                        sub_md["source_id"] = c_id
                        sub_md["chunk_id"] = c_id
                        sub_md["content_hash"] = chash
                        docs.append(Document(page_content=sub_content, metadata=sub_md))
                else:
                    # 항과 호를 하나의 완결된 Child 청크로 결합
                    all_lines = [para_clean] if para_clean else []
                    if para.items:
                        all_lines.extend(para.items)
                    para_full = "\n".join(all_lines).strip()

                    header_label = f"[{meta.law_name}] {article.title_line} {para_label}".strip()
                    content = f"{header_label}\n{para_full}" if include_header else para_full

                    c_id = make_unique_id(f"{parent_id}_c{child_idx}")
                    child_idx += 1
                    chash = compute_content_hash(content)

                    md = {
                        "source_id": c_id,
                        "chunk_id": c_id,
                        "document_id": doc_id,
                        "parent_id": parent_id,
                        "parent_content": full_parent_content,
                        "law_name": meta.law_name,
                        "article": article.article_no,
                        "article_title": article.article_title,
                        "page": str(para.start_page),
                        "effective_date": meta.effective_date,
                        "version_date": meta.effective_date,
                        "content_hash": chash,
                        "category": meta.category,
                        "source_type": "STATUTE",
                        "file_name": meta.file_name,
                        "chunk_strategy": ChunkingStrategy.PARENT_CHILD.value,
                        "chunk_type": "child",
                        "paragraph_no": para.paragraph_no,
                        "part": article.part,
                        "chapter": article.chapter,
                        "section": article.section,
                    }
                    docs.append(Document(page_content=content, metadata=md))

        return docs
