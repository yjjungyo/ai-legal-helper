"""
모듈명: retrieval.py

[모듈 개요]
Chroma 벡터 데이터베이스를 기반으로 법률 문서 청크를 검색하는 RAG 검색 모듈이다.

[주요 기능]
1. Chroma 클라이언트 연결 (HttpClient 또는 로컬 PersistentClient)
2. 법률 분야별 컬렉션(law_docs_*) 대상 유사도 검색
3. 검색 메타데이터(파일명, 페이지 번호 등) 보존 및 Span 추적
"""
import os
import re
from typing import List, Optional, Tuple, Any, Dict
from enum import Enum
from dataclasses import dataclass, field

import chromadb
from langchain_chroma import Chroma

from ai_legal_helper.llm.gateway import get_embeddings
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.agents.constants import collection_name_for
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span

ARTICLE_RE = re.compile(r"(제\s*\d+\s*조(?:\s*의\s*\d+)?)")
TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z0-9]{2,}")


def deduplicate_chunks(docs: List[Any], threshold: float = 0.85) -> List[Any]:
    """검색된 문서 청크 리스트에서 텍스트 유사도가 과도하게 높은 중복 청크를 제거한다.

    슬라이딩 윈도우나 인접 청크 분할로 인해 발생하는 동일 내용 반복을 배제하여,
    상위 K개 결과의 정보 다양성(Diversity)을 확보한다.

    Args:
        docs: 검색된 문서 객체(LangChain Document 또는 page_content 보유 객체) 리스트.
        threshold: 중복으로 간주할 자카드 유사도 임계치 (기본값: 0.85).

    Returns:
        List[Any]: 중복이 제거된 고유 문서 청크 리스트.
    """
    if not docs:
        return []

    unique_docs: List[Any] = []
    seen_token_sets: List[set[str]] = []
    seen_official_ids: set[str] = set()

    for d in docs:
        meta = getattr(d, "metadata", None) or {}
        # Different official articles may share most of their wording.
        # Do not collapse them using a text-similarity threshold.
        if meta.get("law_id") and meta.get("version_id") and meta.get("vector_id"):
            vector_id = str(meta["vector_id"])
            if vector_id not in seen_official_ids:
                unique_docs.append(d)
                seen_official_ids.add(vector_id)
            continue
        content = getattr(d, "page_content", "") or ""
        tokens = set(TOKEN_RE.findall(content.lower()))
        if not tokens:
            unique_docs.append(d)
            continue

        is_dup = False
        for seen in seen_token_sets:
            intersection = len(tokens.intersection(seen))
            union = len(tokens.union(seen))
            if union > 0 and (intersection / union) >= threshold:
                is_dup = True
                break

        if not is_dup:
            unique_docs.append(d)
            seen_token_sets.append(tokens)

    return unique_docs


def rerank_with_article_and_keywords(
    query: str,
    scored_docs: List[Tuple[Any, float]],
    top_k: int = 10,
) -> List[Tuple[Any, float]]:
    """질의에 포함된 법률 조문 번호(예: 제6조의2) 및 핵심 어휘와 문서 간의 일치도를 반영하여 재순위화(Re-ranking)한다.

    순수 벡터 유사도 점수에 조문 완전 일치 가중치(+0.25)와 키워드 어휘 중첩 가중치(+0.15)를 결합하여
    법률 특화 하이브리드 순위를 산출한다 (P2-01).

    Args:
        query: 사용자 법률 질의어.
        scored_docs: (문서 객체, 기본 유사도 점수) 튜플 리스트.
        top_k: 재정렬 후 반환할 상위 문서 개수.

    Returns:
        List[Tuple[Any, float]]: 가중치가 재조정된 (문서 객체, 최종 점수) 튜플 리스트.
    """
    if not scored_docs:
        return []

    # 질의에서 조문 번호 추출 (예: "제6조의2", "제6조")
    query_articles = [re.sub(r"\s+", "", m.group(1)) for m in ARTICLE_RE.finditer(query or "")]
    query_tokens = set(TOKEN_RE.findall((query or "").lower()))

    rescored: List[Tuple[Any, float]] = []

    for doc, base_score in scored_docs:
        content = getattr(doc, "page_content", "") or ""
        meta = getattr(doc, "metadata", {}) or {}

        doc_article = str(meta.get("article") or "").strip()
        doc_article_clean = re.sub(r"\s+", "", doc_article)
        doc_content_articles = [re.sub(r"\s+", "", m.group(1)) for m in ARTICLE_RE.finditer(content)]

        # 1. 조문 번호 일치 가중치 (+0.25)
        article_boost = 0.0
        if query_articles:
            for qa in query_articles:
                if qa == doc_article_clean or qa in doc_content_articles:
                    article_boost = 0.25
                    break

        # 2. 어휘 중첩 가중치 (최대 +0.15)
        lexical_boost = 0.0
        if query_tokens:
            doc_tokens = set(TOKEN_RE.findall(content.lower()))
            if doc_tokens:
                overlap = len(query_tokens.intersection(doc_tokens))
                lexical_boost = 0.15 * min(1.0, overlap / max(1, len(query_tokens)))

        final_score = (base_score * 0.6) + article_boost + lexical_boost
        rescored.append((doc, final_score))

    rescored.sort(key=lambda x: x[1], reverse=True)
    return rescored[:top_k]

logger = get_logger(__name__)

# P1.2 Local DB integration
LOCAL_CHROMA_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/chroma"))
CHROMA_PERSIST = os.getenv("CHROMA_PERSIST", LOCAL_CHROMA_PATH)

_client = None
_used_index_info = "UNKNOWN"


class RetrievalStatus(str, Enum):
    """RAG 벡터 검색 상태 구분 코드 (P1-01)."""
    SUCCESS = "SUCCESS"
    NO_MATCH = "NO_MATCH"
    COLLECTION_MISSING = "COLLECTION_MISSING"
    RETRIEVER_UNAVAILABLE = "RETRIEVER_UNAVAILABLE"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


@dataclass
class RetrievalResult:
    """구조화된 RAG 검색 결과 객체.

    검색된 문서 목록뿐만 아니라 검색 인프라의 성공/장애 상태, 에러 상세, 사용된 인덱스 정보를 함께 제공한다.
    """
    status: RetrievalStatus
    documents: List[Any] = field(default_factory=list)
    error_detail: Optional[str] = None
    collection_name: Optional[str] = None
    used_index_info: str = "UNKNOWN"


def get_used_index_info() -> str:
    """현재 연결된 ChromaDB 인덱스 종류(HTTP_REMOTE, LOCAL_PERSISTENT, EPHEMERAL_TEST 등)를 반환한다."""
    global _used_index_info
    return _used_index_info


# 내부 싱글톤 클라이언트 반환 헬퍼이므로 불필요한 Langfuse Span 생성을 방지하기 위해 @trace를 적용하지 않는다.
def _get_client():
    """Chroma 클라이언트 인스턴스를 반환한다.

    테스트 환경에서는 EphemeralClient, 분산 환경에서는 HttpClient를 시도하며,
    원격 서버에 법령 컬렉션이 없거나 연결에 실패할 경우 로컬 PersistentClient(data/chroma)로 전환한다.

    Returns:
        chromadb.Client: 구성된 Chroma 클라이언트 객체
    """
    global _client, _used_index_info
    if _client is None:
        if os.getenv("TESTING") == "1":
            _client = chromadb.EphemeralClient()
            _used_index_info = "EPHEMERAL_TEST"
            logger.debug("[벡터DB] 테스트용 메모리 클라이언트(EphemeralClient) 초기화")
            return _client
            
        chroma_host = os.getenv("CHROMA_HOST")
        persist_dir = os.getenv("CHROMA_PERSIST", LOCAL_CHROMA_PATH)
        if not os.path.isabs(persist_dir):
            persist_dir = os.path.abspath(persist_dir)

        if chroma_host:
            chroma_port = os.getenv("CHROMA_PORT", "8000")
            try:
                client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
                # 원격 서버 생존 여부(Heartbeat) 확인: 서버가 정상 응답하면 컬렉션 유무와 무관하게 사용
                client.heartbeat()
                _client = client
                _used_index_info = f"HTTP_REMOTE:{chroma_host}:{chroma_port}"
                cols = client.list_collections()
                names = [getattr(c, "name", "") for c in cols]
                logger.debug(f"[벡터DB] 원격 ChromaDB 연결 완료: {chroma_host}:{chroma_port} (컬렉션 {len(names)}개)")
                return _client
            except Exception as e:
                # 원격 서버가 완전히 다운되었거나 통신 불가인 경우에만 로컬 파일 저장소로 전환
                logger.warning(f"[RET] HttpClient 연결 실패: {e}. 로컬 PersistentClient({persist_dir})로 전환합니다.")

        # 로컬 data/chroma 우선 확인
        if not os.path.exists(persist_dir) and os.path.exists(LOCAL_CHROMA_PATH):
            persist_dir = LOCAL_CHROMA_PATH
        try:
            os.makedirs(persist_dir, exist_ok=True)
            _client = chromadb.PersistentClient(path=persist_dir)
            _used_index_info = f"LOCAL_PERSISTENT:{persist_dir}"
            logger.debug(f"[벡터DB] 로컬 ChromaDB(PersistentClient) 초기화: {persist_dir}")
        except Exception as e:
            logger.warning(f"[RET] PersistentClient 초기화 실패({e}), EphemeralClient 폴백으로 전환합니다.")
            _client = chromadb.EphemeralClient()
            _used_index_info = "EPHEMERAL_FALLBACK"
    return _client

# retrieve_with_status 내부에서 호출되는 벡터스토어 래퍼이므로 중복 Span 방지를 위해 @trace를 제외한다.
def _get_vs(coll_name: str) -> Chroma:
    """특정 컬렉션에 대한 LangChain Chroma 벡터스토어 객체를 반환한다."""
    return Chroma(client=_get_client(), collection_name=coll_name, embedding_function=get_embeddings())

# retrieve_with_status 내부에서 호출되는 컬렉션 목록 조회 헬퍼이므로 중복 Span 방지를 위해 @trace를 제외한다.
def _list_collections() -> List[str]:
    """현재 연결된 Chroma 클라이언트의 컬렉션 이름 목록을 반환한다."""
    try:
        cols = _get_client().list_collections()
        names = [getattr(c, "name", "") if hasattr(c, "name") else str(c) for c in cols]
        logger.debug(f"[벡터DB] 조회된 컬렉션 목록={names}")
        return names
    except Exception as e:
        logger.warning(f"[RET] 컬렉션 목록 조회 실패: {e}")
        return []


def _normalize_doc(d: Any) -> Any:
    """검색된 문서 객체의 파일명 메타데이터를 표준화하고 누락된 Document ID를 보정한다.

    LangChain의 기본 Chroma VectorStore 래퍼는 검색 결과를 Document 객체로 변환할 때
    Chroma의 레코드 Key(ids)를 Document.id로 전달하지 않고 누락(None)시키는 한계가 있다.
    따라서 메타데이터에 보존된 'vector_id', 'chunk_id', 'source_id' 중 유효한 식별자를
    Document.id로 주입하여 Langfuse 추적 및 다운스트림 처리 시 일관성을 보장한다.

    Args:
        d: 검색된 Document 또는 유사 문서 객체.

    Returns:
        Any: 파일명 및 id가 정규화된 문서 객체.
    """
    if hasattr(d, "metadata") and isinstance(d.metadata, dict):
        fn = d.metadata.get("file_name")
        if fn:
            d.metadata["file_name"] = os.path.basename(fn)
        if getattr(d, "id", None) is None:
            doc_id = (
                d.metadata.get("vector_id")
                or d.metadata.get("chunk_id")
                or d.metadata.get("source_id")
            )
            if doc_id:
                try:
                    d.id = str(doc_id)
                except Exception:
                    pass
    return d



def retrieve_official_by_ids(
    vector_ids: List[str],
    collection_names: Optional[List[str]] = None,
) -> List[Any]:
    """PostgreSQL 커버리지 ID 목록(vector_ids)을 기반으로 ChromaDB에서 공식 조문·부칙 청크를 직접 인출한다.

    글로벌 컬렉션('law_docs_global')뿐만 아니라 분야별 컬렉션('law_docs_civil', 'law_docs_administrative' 등)에
    분산 적재된 조문 및 부칙 청크도 누락 없이 탐색하여 회수한다.
    """
    from langchain_core.documents import Document

    if not vector_ids:
        return []
    client = _get_client()
    remaining_ids = set(vector_ids)
    documents: List[Any] = []

    all_cols = _list_collections()
    target_cols = collection_names or [
        "law_docs_global",
        *[c for c in all_cols if c.startswith("law_docs_") and c != "law_docs_global"],
    ]

    for col_name in target_cols:
        if not remaining_ids:
            break
        try:
            col = client.get_collection(col_name)
        except Exception:
            continue
        req_list = list(remaining_ids)
        for start in range(0, len(req_list), 200):
            chunk_req = req_list[start:start + 200]
            try:
                rows = col.get(ids=chunk_req, include=["documents", "metadatas"])
            except Exception:
                continue
            for vector_id, body, metadata in zip(
                rows.get("ids") or [], rows.get("documents") or [],
                rows.get("metadatas") or [],
            ):
                meta = dict(metadata or {})
                if meta.get("vector_id") != vector_id:
                    continue
                documents.append(Document(id=vector_id, page_content=body or "", metadata=meta))
                remaining_ids.discard(vector_id)
    return documents


@trace
def retrieve_with_status(query: str, k: int = 10, category: Optional[str] = None, metadata_filter: Optional[Dict[str, Any]] = None) -> RetrievalResult:
    """질의에 대해 연관 법률 문서 청크를 검색하고 구조화된 상태(RetrievalResult)를 반환한다.

    검색 결과 부재(NO_MATCH)와 인프라 장애(COLLECTION_MISSING, RETRIEVER_UNAVAILABLE, EMBEDDING_ERROR)를
    명확히 구분하여 반환한다 (P1-01).

    Args:
        query: 법률 검색 질의어.
        k: 반환할 상위 문서 개수 (기본 3개).
        category: 법률 카테고리 (지정 시 해당 컬렉션 대상 단일 검색).

    Returns:
        RetrievalResult: 검색 상태, 문서 리스트, 에러 상세 및 인덱스 정보.
    """
    if not query or not query.strip():
        return RetrievalResult(
            status=RetrievalStatus.NO_MATCH,
            documents=[],
            error_detail="검색 질의어가 비어 있습니다.",
            used_index_info=get_used_index_info(),
        )

    if metadata_filter is not None and not category:
        return RetrievalResult(
            status=RetrievalStatus.CONFIGURATION_ERROR, documents=[],
            error_detail="MST 필터는 단일 컬렉션 검색에서만 허용됩니다.",
        )
    used_info = get_used_index_info()

    if category:
        coll = collection_name_for(category)
        avail_colls = _list_collections()
        if coll not in avail_colls:
            logger.warning(f"[RET] 컬렉션 부재(COLLECTION_MISSING): {coll}")
            return RetrievalResult(
                status=RetrievalStatus.COLLECTION_MISSING,
                documents=[],
                error_detail=f"해당 분야 인덱스 컬렉션('{coll}')이 데이터베이스에 존재하지 않습니다.",
                collection_name=coll,
                used_index_info=used_info,
            )
        try:
            vs = _get_vs(coll)
            fetch_k = max(k * 2, 10)
            raw_scored: List[Tuple[Any, float]] = []
            try:
                raw_scored = vs.similarity_search_with_relevance_scores(query, k=fetch_k, filter=metadata_filter)
            except Exception:
                raw_docs = vs.similarity_search(query, k=fetch_k, filter=metadata_filter)
                raw_scored = [(d, 0.8) for d in raw_docs]

            reranked = rerank_with_article_and_keywords(query, raw_scored, top_k=fetch_k)
            candidate_docs = [d for d, _ in reranked]
            from ai_legal_helper.rag.hybrid_retrieval import restore_parent_content
            restored_candidates = [restore_parent_content(d) for d in candidate_docs]
            deduped_docs = deduplicate_chunks(restored_candidates)[:k]
            norm_docs = [_normalize_doc(d) for d in deduped_docs]
            st = RetrievalStatus.SUCCESS if norm_docs else RetrievalStatus.NO_MATCH
            logger.debug(f"[벡터 검색 완료] 컬렉션={coll}, 검색된 문서={len(norm_docs)}건")
            try:
                update_span(get_current_span_id(), {
                    "search_type": "Chroma_Single",
                    "hits": len(norm_docs),
                    "collection": coll,
                    "top_k": k,
                    "retrieval_status": st.value,
                })
            except Exception:
                pass
            return RetrievalResult(
                status=st,
                documents=norm_docs,
                collection_name=coll,
                used_index_info=used_info,
            )
        except Exception as e:
            logger.error(f"[RET] 단일 컬렉션 검색 실패(coll={coll}): {type(e).__name__}: {str(e)}")
            err_msg = str(e).lower()
            st = RetrievalStatus.EMBEDDING_ERROR if "embedding" in err_msg else RetrievalStatus.RETRIEVER_UNAVAILABLE
            return RetrievalResult(
                status=st,
                documents=[],
                error_detail=f"{type(e).__name__}: {str(e)}",
                collection_name=coll,
                used_index_info=used_info,
            )

    colls = [n for n in _list_collections() if n.startswith("law_docs_")]
    if not colls:
        return RetrievalResult(
            status=RetrievalStatus.COLLECTION_MISSING,
            documents=[],
            error_detail="법률 컬렉션('law_docs_*')이 하나도 존재하지 않습니다.",
            used_index_info=used_info,
        )

    per = max(1, k // max(1, len(colls)) + 1)
    hits: List[Tuple] = []
    has_error = False
    last_err = ""
    for coll in colls:
        try:
            vs = _get_vs(coll)
            for doc, score in vs.similarity_search_with_relevance_scores(query, k=per):
                hits.append((doc, score))
        except Exception as e:
            has_error = True
            last_err = f"{type(e).__name__}: {str(e)}"
            logger.warning(f"[벡터 검색] 컬렉션({coll}) 검색 건너뜀: {e}")

    if not hits and has_error:
        st = RetrievalStatus.EMBEDDING_ERROR if "embedding" in last_err.lower() else RetrievalStatus.RETRIEVER_UNAVAILABLE
        return RetrievalResult(
            status=st,
            documents=[],
            error_detail=last_err,
            used_index_info=used_info,
        )

    reranked = rerank_with_article_and_keywords(query, hits, top_k=max(k * 2, 10))
    candidate_docs = [d for d, _ in reranked]
    from ai_legal_helper.rag.hybrid_retrieval import restore_parent_content
    restored_candidates = [restore_parent_content(d) for d in candidate_docs]
    deduped_docs = deduplicate_chunks(restored_candidates)[:k]
    norm_docs = [_normalize_doc(d) for d in deduped_docs]
    st = RetrievalStatus.SUCCESS if norm_docs else RetrievalStatus.NO_MATCH

    try:
        update_span(get_current_span_id(), {
            "search_type": "Chroma_Multi",
            "hits": len(hits),
            "top_k": k,
            "retrieval_status": st.value,
        })
    except Exception:
        pass

    return RetrievalResult(
        status=st,
        documents=norm_docs,
        used_index_info=used_info,
    )


@trace
def retrieve(query: str, k: int = 10, category: Optional[str] = None) -> List:
    """질의에 대해 연관 법률 문서 청크를 검색한다 (하위 호환성 유지 함수).

    Args:
        query: 법률 검색 질의어
        k: 반환할 상위 문서 개수 (기본 3개)
        category: 법률 카테고리 (지정 시 단일 컬렉션 대상 검색)

    Returns:
        List[Document]: 검색된 LangChain Document 객체 리스트
    """
    res = retrieve_with_status(query=query, k=k, category=category)
    return res.documents
