# -*- coding: utf-8 -*-
"""
모듈명: test_companion_addenda_retrieval.py

[테스트 개요]
법령 조문 검색 시 해당 법령 버전(MST)의 부칙(시행일·적용례·경과조치)이 질문의
키워드(날짜, 시행일 등) 유무와 무관하게 항상 동반 인출(Companion Retrieval)되는지 검증한다.

[주요 검증 항목]
1. `official_statute_search.search_official_statutes`:
   - 질문에 날짜/시행일 키워드가 없어도 조문이 검색되면 부칙이 항상 출처(sources)에 동반 포함되는지 검증.
2. `retrieval.retrieve_official_by_ids`:
   - 'law_docs_global'뿐만 아니라 분야별 컬렉션('law_docs_civil' 등)에 분산 적재된 조문/부칙도 올바르게 회수하는지 검증.
3. `LawRetrievalService`:
   - 조문 청크 검색 시 해당 법령의 부칙 청크가 항상 1+1 동반 인출되어 `response.sources`에 보존되는지 검증 (k 상한에 의해 잘리지 않음).
"""
from __future__ import annotations

import hashlib
from types import SimpleNamespace
import unittest.mock as mock
from typing import Any, Dict, List
import pytest
from langchain_core.documents import Document

from ai_legal_helper.tools.official_statute_search import search_official_statutes
from ai_legal_helper.rag.retrieval import retrieve_official_by_ids
from ai_legal_helper.legal_knowledge.retrieval_service import LawRetrievalService


def test_official_statute_search_always_includes_addenda_even_without_date_keywords():
    """질문에 날짜나 '시행일' 키워드가 전혀 없더라도, 조문이 검색되면 해당 부칙이 항상 포함되는지 검증한다."""
    search_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <LawSearch>
        <law>
            <법령일련번호>276291</법령일련번호>
            <법령명한글>주택임대차보호법</법령명한글>
            <법령구분명>법률</법령구분명>
            <법령ID>001248</법령ID>
            <공포번호>20432</공포번호>
            <시행일자>20250131</시행일자>
            <공포일자>20240731</공포일자>
        </law>
    </LawSearch>""".encode("utf-8")

    detail_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <법령>
        <기본정보>
            <법령명_한글>주택임대차보호법</법령명_한글>
            <법령일련번호>276291</법령일련번호>
            <법령ID>001248</법령ID>
            <공포번호>20432</공포번호>
        </기본정보>
        <조문단위>
            <조문여부>조문</조문여부>
            <조문번호>3</조문번호>
            <조문가지번호>0</조문가지번호>
            <조문제목>대항력 등</조문제목>
            <조문내용>대항력은 인도와 주민등록을 마친 때 발생한다.</조문내용>
        </조문단위>
        <부칙단위>
            <부칙공포일자>20240731</부칙공포일자>
            <부칙공포번호>20432</부칙공포번호>
            <부칙내용>제1조(시행일) 이 법은 공포 후 6개월이 경과한 날부터 시행한다. 제2조(적용례) 제3조의 개정규정은 이 법 시행 당시 존속 중인 임대차에 대하여도 적용한다.</부칙내용>
        </부칙단위>
    </법령>""".encode("utf-8")

    def mock_fetch(url, *args, **kwargs):
        if "lawSearch.do" in url:
            return search_xml
        if "lawService.do" in url:
            return detail_xml
        return None

    with mock.patch("ai_legal_helper.tools.official_statute_search._fetch_xml_with_retry", side_effect=mock_fetch):
        with mock.patch.dict("os.environ", {"LAW_OPENAPI_KEY": "test_key"}):
            # 질문에 '시행일'이나 '2024년' 같은 날짜 키워드가 전혀 없음
            sources = search_official_statutes(
                query="대항력 취득 요건이 어떻게 되나요?",
                candidate_laws=["주택임대차보호법"],
                max_articles_per_law=3,
            )

    articles = [s.get("article") for s in sources]
    # 조문(제3조)과 부칙이 모두 검색 출처에 존재해야 함
    assert "제3조" in articles, "제3조가 검색되어야 합니다."
    assert "부칙" in articles, "날짜 키워드가 없어도 부칙이 동반 인출되어야 합니다."

    addendum_source = next(s for s in sources if s.get("article") == "부칙")
    assert "공포 후 6개월" in addendum_source["content"]
    assert "적용례" in addendum_source["article_title"]


def test_retrieve_official_by_ids_cross_collections():
    """'law_docs_global' 외에 분야별 컬렉션에 저장된 벡터 ID도 교차 탐색하여 회수하는지 검증한다."""
    mock_client = mock.MagicMock()
    mock_global_col = mock.MagicMock()
    mock_civil_col = mock.MagicMock()

    # global 컬렉션에는 id-1만 존재, civil 컬렉션에는 id-2가 존재
    mock_global_col.get.return_value = {
        "ids": ["id-1"],
        "documents": ["글로벌 조문 본문"],
        "metadatas": [{"vector_id": "id-1", "article": "제1조"}],
    }
    mock_civil_col.get.return_value = {
        "ids": ["id-2"],
        "documents": ["민법 부칙 본문"],
        "metadatas": [{"vector_id": "id-2", "article": "부칙"}],
    }

    def get_collection_mock(name):
        if name == "law_docs_global":
            return mock_global_col
        if name == "law_docs_civil":
            return mock_civil_col
        raise ValueError(f"Unknown collection {name}")

    mock_client.get_collection.side_effect = get_collection_mock

    with mock.patch("ai_legal_helper.rag.retrieval._get_client", return_value=mock_client):
        with mock.patch("ai_legal_helper.rag.retrieval._list_collections", return_value=["law_docs_global", "law_docs_civil"]):
            docs = retrieve_official_by_ids(["id-1", "id-2"])

    assert len(docs) == 2, "두 개 컬렉션에서 각각 1개씩 총 2개의 문서가 회수되어야 합니다."
    articles = [d.metadata.get("article") for d in docs]
    assert "제1조" in articles
    assert "부칙" in articles


def test_law_retrieval_service_companion_addenda_always_attached():
    """LawRetrievalService에서 조문이 검색되면 부칙이 k 상한에 잘리지 않고 항상 동반 출처로 보존되는지 검증한다."""
    law_id = "L1"
    mst = "MST-1"

    # 조문 청크와 부칙 청크 구성
    art3_body = "제3조(대항력 등) 대항력 요건 본문"
    art3_hash = hashlib.sha256(art3_body.encode("utf-8")).hexdigest()
    art3_vid = f"official:{law_id}:{mst}:제3조:{art3_hash[:16]}"
    doc_art3 = SimpleNamespace(
        id=art3_vid, page_content=art3_body,
        metadata={
            "source_type": "STATUTE", "law_id": law_id, "law_name": "가상임대차법",
            "statute_name": "가상임대차법", "version_id": mst, "article": "제3조",
            "vector_id": art3_vid, "content_hash": art3_hash,
        },
    )

    addendum_body = "제1조(시행일) 공포 후 즉시 시행. 제2조(적용례) 모든 계약에 적용."
    addendum_hash = hashlib.sha256(addendum_body.encode("utf-8")).hexdigest()
    addendum_vid = f"official:{law_id}:{mst}:addendum:0:{addendum_hash[:16]}"
    doc_addendum = SimpleNamespace(
        id=addendum_vid, page_content=addendum_body,
        metadata={
            "source_type": "STATUTE", "law_id": law_id, "law_name": "가상임대차법",
            "statute_name": "가상임대차법", "version_id": mst, "article": "부칙",
            "vector_id": addendum_vid, "content_hash": addendum_hash,
        },
    )

    coverage = {
        (law_id, mst, art3_vid): ("제3조", art3_hash),
        (law_id, mst, addendum_vid): ("부칙", addendum_hash),
    }

    # 벡터 검색 결과에는 조문(제3조)만 반환됨 (부칙은 유사도 부족으로 미반환 상황 모사)
    def fake_retrieve(*, query, category, k, metadata_filter):
        return SimpleNamespace(status="SUCCESS", documents=[doc_art3])

    def fake_index(*, law_id, event_date, event_type, article_ids):
        return SimpleNamespace(
            status="INDEX_READY_CANDIDATE", mst=mst,
            as_dict=lambda: {"status": "INDEX_READY_CANDIDATE", "mst": mst},
            reason_codes=[],
        )

    def fake_temporal(*, law_id, event_date, event_type, article_ids):
        return SimpleNamespace(as_dict=lambda: {}, reason_codes=[])

    exact_calls = []
    def fake_exact(ids):
        exact_calls.append(list(ids))
        all_exact = [doc_art3, doc_addendum]
        return [d for d in all_exact if d.id in ids]

    srv = LawRetrievalService(
        retrieval_fn=fake_retrieve,
        index_fn=fake_index,
        article_temporal_fn=fake_temporal,
        coverage_fn=lambda versions: coverage,
        exact_fetch_fn=fake_exact,
    )

    # k=1 로 검색 요청 (기존 방식이라면 부칙이 잘려나갈 수 있는 설정)
    reply = srv.search(
        "가상임대차법 제3조 요건 안내",
        original_question="가상임대차법 제3조 요건 안내",
        category="civil",
        required_laws=[{"law_id": law_id, "law_name": "가상임대차법"}],
        as_of_date="2026-11-01",
        event_type="계약",
        k=1,
    )

    # exact_fn에 부칙 ID(addendum_vid)가 요청되었어야 함
    flattened_calls = [item for sub in exact_calls for item in sub]
    assert addendum_vid in flattened_calls, "부칙 벡터 ID가 동반 인출(Companion Fetch) 대상에 포함되어야 합니다."

    # reply.sources에 제3조 조문과 부칙이 모두 포함되어 있어야 함
    articles = [s.get("article") for s in reply.sources]
    assert "제3조" in articles, "제3조가 출처에 있어야 합니다."
    assert "부칙" in articles, "k=1 제한에도 불구하고 부칙이 잘리지 않고 동반 보존되어야 합니다."


def test_normalize_doc_populates_missing_document_id():
    """LangChain Chroma 래퍼가 id=None으로 반환한 Document의 id를 metadata에서 보정하는지 검증한다."""
    from ai_legal_helper.rag.retrieval import _normalize_doc

    # 1. chunk_id 보유 문서 (PDF 인덱싱 청크)
    doc1 = Document(page_content="내용1", metadata={"chunk_id": "민법_제626조_c1", "file_name": "dir/민법.pdf"})
    assert doc1.id is None
    res1 = _normalize_doc(doc1)
    assert res1.id == "민법_제626조_c1"
    assert res1.metadata["file_name"] == "민법.pdf"

    # 2. vector_id 보유 문서 (공식 법령 청크)
    doc2 = Document(page_content="내용2", metadata={"vector_id": "official:001707:284415:제626조:d92f", "file_name": "dir/민법.pdf"})
    assert doc2.id is None
    res2 = _normalize_doc(doc2)
    assert res2.id == "official:001707:284415:제626조:d92f"

    # 3. 기존 id가 이미 설정된 문서의 보존
    doc3 = Document(id="already_set_id", page_content="내용3", metadata={"chunk_id": "ignored_chunk_id"})
    res3 = _normalize_doc(doc3)
    assert res3.id == "already_set_id"


def test_restore_parent_content_preserves_document_id():
    """Parent-Child 원문 복원 시 생성되는 새 Document 객체에도 doc.id가 누락 없이 계승되는지 검증한다."""
    from ai_legal_helper.rag.hybrid_retrieval import restore_parent_content

    # 1. doc.id가 설정되어 있는 경우
    doc_with_id = Document(
        id="official:001707:284415:제626조:d92f",
        page_content="필요비 지출 시 상환청구 가능",
        metadata={
            "law_name": "민법",
            "parent_content": "제626조 ①임차인이 임차물의 보존에 관한 필요비를 지출한 때에는...",
            "vector_id": "official:001707:284415:제626조:d92f",
        },
    )
    restored1 = restore_parent_content(doc_with_id)
    assert restored1.id == "official:001707:284415:제626조:d92f"
    assert "[민법] 제626조" in restored1.page_content
    assert restored1.metadata["child_snippet"] == "필요비 지출 시 상환청구 가능"

    # 2. doc.id가 None이지만 metadata에 chunk_id가 있는 경우
    doc_without_id = Document(
        page_content="차임 증감 청구",
        metadata={
            "law_name": "민법",
            "parent_content": "제628조 경제사정의 변동으로 인하여...",
            "chunk_id": "민법_제628조_c1",
        },
    )
    restored2 = restore_parent_content(doc_without_id)
    assert restored2.id == "민법_제628조_c1"
    assert "[민법] 제628조" in restored2.page_content
