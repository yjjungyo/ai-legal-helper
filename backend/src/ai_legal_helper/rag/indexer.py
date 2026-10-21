# -*- coding: utf-8 -*-
"""
모듈명: indexer.py

[모듈 개요]
대한민국 법령 PDF를 일괄 로드하여 조문/항·호 단위로 파싱·청킹하고,
Azure OpenAI Embedding을 생성하여 ChromaDB의 분야별 컬렉션(law_docs_*)에 인덱싱하는 파이프라인 모듈이다.

[주요 기능]
1. `docs/statute_pdf` 내 법령 PDF 일괄 로딩 및 실패 원인 추적
2. 3대 청킹 전략(Fixed-size, Article-aware, Parent-Child) 지원
3. Azure OpenAI `text-embedding-3-large` 배치 임베딩 및 지수 백오프 재시도
4. 분야별 컬렉션(law_docs_*) 재구축 및 `case_evidence` 등 타 컬렉션 절대 보존
5. 재색인 시 청크 해시(content_hash) 기반 중복 방지
6. 인덱싱 완료 후 BM25 어휘 인덱스 동시 웜업
7. CLI 인터페이스(`python -m ai_legal_helper.rag.indexer`) 지원
"""

from __future__ import annotations
import argparse
import os
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

import chromadb
from langchain_core.documents import Document

from ai_legal_helper.agents.constants import CATEGORIES, collection_name_for
from ai_legal_helper.llm.gateway import get_embeddings
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.rag.bm25_retriever import get_or_build_bm25_index, clear_bm25_cache
from ai_legal_helper.rag.chunker import ChunkingStrategy, StatuteChunker
from ai_legal_helper.rag.retrieval import _get_client
from ai_legal_helper.rag.statute_parser import parse_statute_pdf

logger = get_logger(__name__)

# 보호 대상 비법령 컬렉션 목록 (절대 삭제 금지)
PROTECTED_COLLECTIONS: Set[str] = {"case_evidence", "evidence_store"}


def check_chroma_connection(client: Any) -> bool:
    """연결 대상 ChromaDB 서버 상태를 사전 검증한다.

    Args:
        client: ChromaDB 클라이언트 인스턴스.

    Returns:
        bool: 연결 성공 여부.
    """
    try:
        cols = client.list_collections()
        col_names = [getattr(c, "name", "") for c in cols]
        logger.info(f"[INDEXER] ChromaDB 연결 확인 완료 (기존 컬렉션 {len(col_names)}개: {col_names})")
        return True
    except Exception as e:
        logger.error(f"[INDEXER] ChromaDB 연결 실패: {e}")
        return False


def embed_documents_with_retry(
    embeddings_model: Any,
    texts: List[str],
    batch_size: int = 50,
    max_retries: int = 3,
) -> List[List[float]]:
    """텍스트 리스트를 배치 단위로 분할하여 임베딩 벡터를 생성하며 실패 시 지수 백오프로 재시도한다.

    Args:
        embeddings_model: LangChain Embeddings 인스턴스 (AzureOpenAIEmbeddings).
        texts: 임베딩할 문자열 리스트.
        batch_size: 단일 요청 배치 크기 (기본값: 50).
        max_retries: 일시적 네트워크/API 실패 시 최대 재시도 횟수.

    Returns:
        List[List[float]]: 생성된 실수형 임베딩 벡터 리스트.
    """
    all_vectors: List[List[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        for attempt in range(max_retries):
            try:
                vectors = embeddings_model.embed_documents(batch)
                all_vectors.extend(vectors)
                break
            except Exception as e:
                wait_sec = 2 ** attempt
                logger.warning(
                    f"[INDEXER] 임베딩 배치({i}~{i+len(batch)}) 시도 {attempt + 1}/{max_retries} 실패: {e}. {wait_sec}초 대기 후 재시도."
                )
                if attempt == max_retries - 1:
                    logger.error(f"[INDEXER] 임베딩 최종 실패: {e}")
                    raise e
                time.sleep(wait_sec)

    return all_vectors


def build_statute_index(
    data_dir: str = "docs/statute_pdf",
    strategy: ChunkingStrategy = ChunkingStrategy.PARENT_CHILD,
    target_categories: Optional[List[str]] = None,
    reindex: bool = True,
    batch_size: int = 50,
    collection_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """법령 PDF를 스캔하여 분야별 ChromaDB 컬렉션을 구축/재구축한다.

    Args:
        data_dir: 법령 PDF가 위치한 디렉터리 경로.
        strategy: 적용할 청킹 전략 (기본값: PARENT_CHILD).
        target_categories: 색인 대상 특정 법률 카테고리 목록 (None일 경우 전체 8개 분야).
        reindex: True일 경우 기존 법령 컬렉션을 삭제 후 깨끗이 덮어씀 (case_evidence 보존).
        batch_size: 임베딩 생성 시 배치 크기.
        collection_prefix: 커스텀 컬렉션 접두사 (비교 실험용, 예: 'law_docs_fixed_').

    Returns:
        Dict[str, Any]: 인덱싱 통계 (처리 파일 수, 청크 수, 소요시간, 카테고리별 현황 등).
    """
    start_time = time.time()
    client = _get_client()

    if not check_chroma_connection(client):
        raise ConnectionError("ChromaDB 서버에 연결할 수 없습니다. CHROMA_HOST 및 포트 설정을 확인하세요.")

    if not os.path.exists(data_dir):
        raise FileNotFoundError(f"법령 PDF 디렉터리를 찾을 수 없습니다: {data_dir}")

    # 대상 PDF 파일 수집
    pdf_files = [
        os.path.join(data_dir, f)
        for f in sorted(os.listdir(data_dir))
        if f.lower().endswith(".pdf")
    ]
    logger.info(f"[INDEXER] 총 {len(pdf_files)}개의 법령 PDF 파일을 발견했습니다. (전략: {strategy.value})")

    chunker = StatuteChunker(strategy=strategy)
    embeddings_model = get_embeddings()

    # 카테고리별 Document 청크 그룹화
    category_docs: Dict[str, List[Document]] = {cat: [] for cat in CATEGORIES}
    failed_files: List[Tuple[str, str]] = []

    for pdf_path in pdf_files:
        try:
            meta, articles = parse_statute_pdf(pdf_path)
            if target_categories and meta.category not in target_categories:
                continue

            docs = chunker.chunk_statute(meta, articles)
            category_docs[meta.category].extend(docs)
            logger.info(
                f"[INDEXER] 파싱 완료: {meta.law_name} ({meta.category}) -> 조문 {len(articles)}개, 청크 {len(docs)}개"
            )
        except Exception as ex:
            logger.error(f"[INDEXER] PDF 파싱 오류 ({pdf_path}): {ex}")
            failed_files.append((pdf_path, str(ex)))

    stats: Dict[str, Any] = {
        "strategy": strategy.value,
        "total_files": len(pdf_files),
        "failed_files": failed_files,
        "collections": {},
        "total_chunks": 0,
    }

    # 카테고리별 컬렉션 생성 및 임베딩 투입
    from ai_legal_helper.agents.constants import CATEGORY_KO_TO_ENG

    for category, docs in category_docs.items():
        if target_categories and category not in target_categories:
            continue
        if not docs:
            logger.info(f"[INDEXER] 분야 '{category}'에 해당하는 청크가 없습니다. 건너뜁니다.")
            continue

        cat_eng = CATEGORY_KO_TO_ENG.get(category, category)
        if collection_prefix:
            coll_name = f"{collection_prefix}{cat_eng}"
        else:
            coll_name = collection_name_for(category)

        # 1. 재구축 모드 시 기존 법령 컬렉션 안전 초기화 (case_evidence 등 비법령 컬렉션 보호)
        if reindex:
            if coll_name in PROTECTED_COLLECTIONS:
                raise ValueError(f"보호 대상 컬렉션 '{coll_name}'은 재구축할 수 없습니다.")
            try:
                client.delete_collection(name=coll_name)
                logger.info(f"[INDEXER] 기존 컬렉션 '{coll_name}' 삭제 완료 (덮어쓰기 재구축).")
            except Exception:
                pass  # 기존 컬렉션이 없었던 경우 정상 통과

        collection = client.get_or_create_collection(
            name=coll_name,
            metadata={"hnsw:space": "cosine", "strategy": strategy.value},
        )

        # 2. 내용 해시 기반 중복 청크 배제
        unique_docs: List[Document] = []
        seen_hashes = set()
        for d in docs:
            chash = d.metadata.get("content_hash")
            if chash and chash in seen_hashes:
                continue
            if chash:
                seen_hashes.add(chash)
            unique_docs.append(d)

        # 3. ID 유일성 보장 (ChromaDB DuplicateIDError 방지)
        seen_ids = set()
        safe_ids = []
        for idx, d in enumerate(unique_docs):
            cid = str(d.metadata.get("chunk_id") or f"{coll_name}_{idx+1}")
            if cid in seen_ids:
                counter = 2
                while f"{cid}_{counter}" in seen_ids:
                    counter += 1
                cid = f"{cid}_{counter}"
                d.metadata["chunk_id"] = cid
                d.metadata["source_id"] = cid
            seen_ids.add(cid)
            safe_ids.append(cid)

        texts = [d.page_content for d in unique_docs]
        ids = safe_ids
        metadatas = [d.metadata for d in unique_docs]

        logger.info(f"[INDEXER] '{coll_name}' 임베딩 생성 시작: 고유 청크 {len(unique_docs)}개")
        vectors = embed_documents_with_retry(embeddings_model, texts, batch_size=batch_size)

        # ChromaDB 배치 추가 (최대 200건씩 add)
        add_step = 200
        for i in range(0, len(unique_docs), add_step):
            collection.add(
                ids=ids[i : i + add_step],
                embeddings=vectors[i : i + add_step],
                metadatas=metadatas[i : i + add_step],
                documents=texts[i : i + add_step],
            )

        # BM25 인메모리 인덱스 캐시 웜업
        clear_bm25_cache(coll_name)
        get_or_build_bm25_index(coll_name, unique_docs)

        stats["collections"][coll_name] = {
            "category": category,
            "chunks_count": len(unique_docs),
            "vector_dimension": len(vectors[0]) if vectors else 0,
        }
        stats["total_chunks"] += len(unique_docs)
        logger.info(f"[INDEXER] '{coll_name}' 인덱싱 완료: {len(unique_docs)}개 청크 저장됨.")

    elapsed_sec = time.time() - start_time
    stats["elapsed_seconds"] = round(elapsed_sec, 2)
    logger.info(
        f"[INDEXER] 전체 인덱싱 파이프라인 완료! (총 {stats['total_chunks']}개 청크, 소요시간: {elapsed_sec:.2f}초)"
    )
    return stats


def main():
    """인덱싱 CLI 메인 함수."""
    parser = argparse.ArgumentParser(description="AI Legal Helper - 법령 ChromaDB 인덱싱 CLI")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="docs/statute_pdf",
        help="법령 PDF 디렉터리 경로 (기본값: docs/statute_pdf)",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["FIXED_SIZE", "ARTICLE_AWARE", "PARENT_CHILD"],
        default="PARENT_CHILD",
        help="적용할 청킹 전략 (기본값: PARENT_CHILD)",
    )
    parser.add_argument(
        "--categories",
        type=str,
        default="",
        help="인덱싱할 카테고리 쉼표 구분 (예: 민법,노동. 생략 시 전체)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="임베딩 생성 배치 크기 (기본값: 50)",
    )
    parser.add_argument(
        "--no-reindex",
        action="store_true",
        help="기존 컬렉션을 삭제하지 않고 추가 (기본값: 덮어쓰기 재구축)",
    )
    parser.add_argument(
        "--collection-prefix",
        type=str,
        default=None,
        help="커스텀 컬렉션 접두사 (비교 실험용, 예: law_docs_fixed_)",
    )

    args = parser.parse_args()
    strat = ChunkingStrategy(args.strategy)
    cats = [c.strip() for c in args.categories.split(",") if c.strip()] or None

    res = build_statute_index(
        data_dir=args.data_dir,
        strategy=strat,
        target_categories=cats,
        reindex=not args.no_reindex,
        batch_size=args.batch_size,
        collection_prefix=args.collection_prefix,
    )
    print("\n================== 인덱싱 완료 요약 ==================")
    print(f"청킹 전략: {res['strategy']}")
    print(f"처리 파일: {res['total_files']}개 (실패: {len(res['failed_files'])}개)")
    print(f"총 청크 수: {res['total_chunks']}개")
    print(f"총 소요시간: {res['elapsed_seconds']}초")
    for col, cinfo in res["collections"].items():
        print(f"  - {col}: {cinfo['chunks_count']} 청크 (차원: {cinfo['vector_dimension']})")
    print("======================================================")


if __name__ == "__main__":
    main()
