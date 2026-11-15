# -*- coding: utf-8 -*-
"""단위 테스트: 크로스 컬렉션 유사도 점수 병합 및 부칙 해석 호출 최적화 검증.

[검증 항목]
1. LawRetrievalService가 law_docs_global과 law_docs_{category}를 함께 조회할 때,
   단순 리스트 결합이 아닌 유사도 점수(score) 내림차순으로 정렬하여
   점수가 높은 도메인 특화 조문이 상위 슬롯을 선점하는지 검증한다.
2. 점수가 동일하거나 미제공된 경우, 도메인 전문 컬렉션이 글로벌 컬렉션보다 우선 배치되는지 검증한다.
3. evaluate_temporal_sources에 target_articles가 지정된 경우, 대상 조문만 LLM 부칙 해석을
   수행하고 나머지 비대상 조문은 신속한 결정론적 판정을 수행하는지 검증한다.
"""
from typing import Any
from unittest.mock import MagicMock
from langchain_core.documents import Document

from ai_legal_helper.legal_knowledge.retrieval_service import (
    LawRetrievalService,
    GLOBAL_LAW_COLLECTION,
)
from ai_legal_helper.legal_knowledge.temporal_resolver import (
    evaluate_temporal_sources,
)


def _make_doc(content: str, metadata: dict[str, Any]) -> Document:
    return Document(page_content=content, metadata=metadata)


def test_cross_collection_score_ranking_prioritizes_high_similarity_domain_doc():
    """글로벌 컬렉션의 낮은 유사도 문서보다 도메인 컬렉션의 높은 유사도 문서가 상위에 선별된다."""
    # 1. 글로벌 컬렉션: 주택임대차보호법 (score = 0.35)
    global_doc = _make_doc(
        "제3조(대항력 등) 주택임대차보호법 조문 내용",
        {
            "statute_name": "주택임대차보호법",
            "article": "제3조",
            "score": 0.35,
            "source_id": "주택임대차보호법_제3조",
        },
    )

    # 2. 행정 컬렉션: 민간임대주택에 관한 특별법 (score = 0.65)
    admin_doc = _make_doc(
        "제46조(임대차계약의 신고) 민간임대주택 특별법 조문 내용",
        {
            "statute_name": "민간임대주택에 관한 특별법",
            "article": "제46조",
            "score": 0.65,
            "source_id": "민간임대주택에 관한 특별법_제46조",
        },
    )

    def mock_retrieval(query: str, category: str, k: int = 10, metadata_filter=None):
        mock_res = MagicMock()
        mock_res.status = "SUCCESS"
        if category == "global":
            mock_res.documents = [global_doc]
        elif category == "administrative":
            mock_res.documents = [admin_doc]
        else:
            mock_res.documents = []
        return mock_res

    service = LawRetrievalService(
        retrieval_fn=mock_retrieval,
        enable_global=True,
        enable_catalog=False,
    )

    res = service.search(
        "등록 민간임대주택 임대차계약 신고 시 관리비 항목",
        category="administrative",
        k=5,
    )

    assert len(res.sources) >= 2
    # 1순위는 반드시 유사도가 높은 민간임대주택에 관한 특별법이어야 함
    first = res.sources[0]
    assert first["statute_name"] == "민간임대주택에 관한 특별법"
    assert first["article"] == "제46조"
    assert first["retrieval_collection"] == "law_docs_administrative"
    assert first["score"] == 0.65

    # 2순위는 글로벌의 주택임대차보호법
    second = res.sources[1]
    assert second["statute_name"] == "주택임대차보호법"
    assert second["article"] == "제3조"
    assert second["retrieval_collection"] == GLOBAL_LAW_COLLECTION
    assert second["score"] == 0.35


def test_cross_collection_tie_breaker_prefers_domain_collection():
    """점수가 동일한 경우 도메인 전문 컬렉션의 문서가 글로벌 컬렉션보다 우선 배치된다."""
    global_doc = _make_doc(
        "글로벌 컬렉션 조문",
        {
            "statute_name": "일반법",
            "article": "제1조",
            "score": 0.50,
            "source_id": "일반법_제1조",
        },
    )
    domain_doc = _make_doc(
        "도메인 전문 조문",
        {
            "statute_name": "행정특화법",
            "article": "제1조",
            "score": 0.50,
            "source_id": "행정특화법_제1조",
        },
    )

    def mock_retrieval(query: str, category: str, k: int = 10, metadata_filter=None):
        mock_res = MagicMock()
        mock_res.status = "SUCCESS"
        mock_res.documents = [global_doc] if category == "global" else [domain_doc]
        return mock_res

    service = LawRetrievalService(
        retrieval_fn=mock_retrieval,
        enable_global=True,
        enable_catalog=False,
    )

    res = service.search(
        "특화 조문 검색 질의",
        category="administrative",
        k=2,
    )

    assert len(res.sources) == 2
    # 동점일 때 도메인 컬렉션이 1순위
    assert res.sources[0]["statute_name"] == "행정특화법"
    assert res.sources[0]["retrieval_collection"] == "law_docs_administrative"
    assert res.sources[1]["statute_name"] == "일반법"
    assert res.sources[1]["retrieval_collection"] == GLOBAL_LAW_COLLECTION


def test_target_articles_limits_llm_addendum_interpretation():
    """target_articles가 지정된 경우 해당 조문만 LLM 부칙 해석을 수행하고 나머지는 결정론적 평가를 거친다."""
    sources = [
        {
            "source_type": "STATUTE",
            "source_id": "S1",
            "law_id": "L1",
            "version_id": "V1",
            "statute_name": "민간임대주택에 관한 특별법",
            "article": "제46조",
            "article_effective_date": "2026-01-01",
            "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
            "content": "제46조(임대차계약의 신고)",
        },
        {
            "source_type": "STATUTE",
            "source_id": "S2",
            "law_id": "L1",
            "version_id": "V1",
            "statute_name": "민간임대주택에 관한 특별법",
            "article": "제1조",
            "article_effective_date": "2026-01-01",
            "effective_date_basis": "ARTICLE_EFFECTIVE_DATE",
            "content": "제1조(목적)",
        },
        {
            "source_type": "STATUTE",
            "source_id": "S_ADD",
            "law_id": "L1",
            "version_id": "V1",
            "statute_name": "민간임대주택에 관한 특별법",
            "article": "부칙",
            "addendum_id": "ADD_1",
            "content": "부칙 제1조(시행일) 이 법은 공포한 날부터 시행한다.",
        },
    ]

    mock_llm_interpret = MagicMock(return_value=({"event_types": ["CONTRACT_SIGNED"], "condition": "신고", "event_evidence": "계약", "condition_evidence": "신고", "has_retroactivity": False}, "PASS"))

    # target_articles로 "제46조"만 지정
    resolution = evaluate_temporal_sources(
        "임대차계약 체결 시 제46조에 따른 신고 의무",
        sources,
        event_date="2026-11-01",
        event_type="CONTRACT_SIGNED",
        llm_addendum_interpretation=True,
        target_articles=["제46조"],
        addendum_invoke_fn=mock_llm_interpret,
        addendum_review_fn=mock_llm_interpret,
    )

    decisions = {d.article: d for d in resolution.decisions}
    assert "제46조" in decisions
    assert "제1조" in decisions

    # 제46조는 target_articles에 포함되어 있으므로 LLM 부칙 해석이 호출됨
    assert mock_llm_interpret.called
    # 제1조는 target_articles에 미포함되어 LLM 해석 없이 결정론적(LLM_ADDENDUM_DISABLED) 사유로 판정됨
    assert decisions["제1조"].reason_code == "LLM_ADDENDUM_DISABLED"
