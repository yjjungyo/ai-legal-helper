# -*- coding: utf-8 -*-
"""
모듈명: test_rag_citation_standard.py

[모듈 개요]
법률 RAG 출처 표준화 및 인용 검증(Citation Validator)의 T-01 ~ T-06 필수 테스트를 수행한다.

[검증 항목]
- T-01: 실제 검색한 문서만 인용되는지 확인
- T-02: 검색 결과에 없는 가짜 파일명을 LLM 출력에 삽입해 차단되는지 확인
- T-03: 존재하는 문서이지만 해당 주장을 뒷받침하지 않는 경우 검증 실패 확인
- T-04: 검색 결과가 없을 때 가짜 출처를 생성하지 않는지 확인
- T-05: 법령·판례·사건 증거의 메타데이터가 정확히 추출·표시되는지 확인
- T-06: ChromaDB에 없지만 다른 실제 검색 경로(GraphRAG, Hybrid Vector Fallback)로 조회한 문서의 출처 유형이 정확히 표시되는지 확인
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai_legal_helper.agents.verification import (
    audit_citations_and_claims,
    sanitize_unverified_citations,
    run_verification,
)
from ai_legal_helper.rag.source_schema import (
    build_source_from_chroma_doc,
    build_source_from_graph_path,
    build_source_from_vector_match,
    normalize_source_dict,
)


def test_t01_only_retrieved_documents_are_cited():
    """T-01: 실제 검색된 문서만 인용되고 검증 통과(PASS)하는지 확인한다."""
    retrieved_sources = [
        {
            "source_id": "주택임대차보호법.pdf_3",
            "file_name": "주택임대차보호법.pdf",
            "page": "3",
            "content": "제3조 대항력 등. 임대차는 그 등기가 없는 경우에도 주택의 인도와 주민등록을 마친 때에는 그 다음 날부터 제삼자에 대하여 효력이 생긴다.",
            "source_type": "STATUTE",
            "retrieval_method": "CHROMA_VECTOR",
        }
    ]
    draft_answer = "임차인은 주택 인도와 전입신고를 마치면 대항력이 발생합니다 (주택임대차보호법.pdf, p.3)."

    audit = audit_citations_and_claims(draft_answer, retrieved_sources)
    assert len(audit["rejected_citation_ids"]) == 0
    assert len(audit["validated_citation_ids"]) == 1
    assert audit["citation_existence_rate"] == 1.0
    assert audit["citation_support_rate"] == 1.0

    sanitized = sanitize_unverified_citations(draft_answer, retrieved_sources)
    assert "(주택임대차보호법.pdf, p.3)" in sanitized


def test_t02_hallucinated_filename_and_precedent_blocked():
    """T-02: 검색 결과에 없는 가짜 파일명과 허위 판례 번호가 정확히 차단·정화되는지 확인한다."""
    retrieved_sources = [
        {
            "source_id": "근로기준법.pdf_10",
            "file_name": "근로기준법.pdf",
            "page": "10",
            "content": "제23조 해고 등의 제한. 사용자는 정당한 이유 없이 근로자를 해고하지 못한다.",
            "source_type": "STATUTE",
            "retrieval_method": "CHROMA_VECTOR",
        }
    ]
    # 가짜 파일명 (민법...pdf) 및 가짜 판례 (2099다12345)
    draft_answer = (
        "부당해고 시 구제신청이 가능합니다 (근로기준법.pdf, p.10). "
        "또한 위자료 청구도 가능합니다 (민법(법률)(제20432호)(20250131).pdf, p.40). "
        "대법원 2099다12345 판결에 따릅니다."
    )

    audit = audit_citations_and_claims(draft_answer, retrieved_sources)
    assert any("민법(법률)(제20432호)(20250131).pdf" in cid for cid in audit["rejected_citation_ids"])
    assert "PRECEDENT:2099다12345" in audit["rejected_citation_ids"]
    assert audit["citation_existence_rate"] < 1.0

    sanitized = sanitize_unverified_citations(draft_answer, retrieved_sources)
    assert "민법(법률)(제20432호)(20250131).pdf" not in sanitized
    assert "2099다12345" not in sanitized
    assert "(근로기준법.pdf, p.10)" in sanitized


def test_t03_existing_document_but_unsupported_claim_fails():
    """T-03: 존재하는 문서이지만 해당 주장을 전혀 뒷받침하지 않는 경우 검증 실패(UNSUPPORTED)를 확인한다."""
    retrieved_sources = [
        {
            "source_id": "주택임대차보호법.pdf_3",
            "file_name": "주택임대차보호법.pdf",
            "page": "3",
            "content": "제3조 대항력 등. 주택 인도와 주민등록을 마친 때 대항력이 발생한다.",
            "source_type": "STATUTE",
            "retrieval_method": "CHROMA_VECTOR",
        }
    ]
    # 주택임대차보호법 p.3에는 음주운전 면허취소나 형사처벌 내용이 전혀 없음
    draft_answer = "음주운전 적발 시 혈중알코올농도에 따라 징역형이나 면허 취소 처분을 받습니다 (주택임대차보호법.pdf, p.3)."

    audit = audit_citations_and_claims(draft_answer, retrieved_sources)
    assert len(audit["rejected_citation_ids"]) >= 1
    assert any("UNSUPPORTED" in r or "ARTICLE_MISMATCH" in r for r in audit["rejection_reasons"].values())
    assert audit["citation_support_rate"] == 0.0

    # Verification Agent 전체 파이프라인에서 REVISE로 강등되는지 확인
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = SimpleNamespace(
        content='{"status": "PASS", "claims": [{"claim": "음주운전 처벌", "source_ids": ["주택임대차보호법.pdf_3"], "grounding_status": "SUPPORTED", "reason": "인용됨"}], "missing_issues": [], "contradictions": [], "revision_instructions": [], "warnings": []}'
    )
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=mock_llm):
        ver_res = run_verification("음주운전 질문", draft_answer, retrieved_sources)

    assert ver_res["status"] == "REVISE"
    assert any("뒷받침하지 않는" in w for w in ver_res["warnings"])


def test_t04_empty_retrieval_does_not_generate_fake_source():
    """T-04: 검색 결과가 없을 때 가짜 출처를 생성하거나 유효한 출처로 인정하지 않는지 확인한다."""
    retrieved_sources = []
    draft_answer = "상담 결과 손해배상이 가능합니다 (민법(법률)(제20432호)(20250131).pdf, p.40)."

    audit = audit_citations_and_claims(draft_answer, retrieved_sources)
    assert len(audit["validated_citation_ids"]) == 0
    assert len(audit["rejected_citation_ids"]) == 1
    assert audit["rejection_reasons"][audit["rejected_citation_ids"][0]] == "NOT_IN_SOURCE_REGISTRY"

    # 정화 시 가짜 파일명이 제거되는지 확인
    sanitized = sanitize_unverified_citations(draft_answer, retrieved_sources)
    assert "민법(법률)" not in sanitized
    assert "[근거 미확인]" in sanitized


def test_t05_metadata_extraction_for_statute_precedent_and_evidence():
    """T-05: 법령, 판례, 사건 증거 메타데이터가 실제 데이터로부터 정확히 파싱되는지 확인한다."""
    # 1. 법령 문서
    statute_doc = SimpleNamespace(
        page_content="제3조(대항력 등) 임대차는 등기가 없는 경우에도 인도와 전입신고로 대항력이 생긴다.",
        metadata={
            "file_name": "주택임대차보호법(법률)(제19920호)(20240101).pdf",
            "page": 3,
            "page_end": 4,
            "chunk_id": "chunk-101",
        },
    )
    src_statute = build_source_from_chroma_doc(statute_doc, category="housing_lease")
    assert src_statute["source_type"] == "STATUTE"
    assert src_statute["statute_name"] == "주택임대차보호법"
    assert src_statute["article"] == "제3조"
    assert src_statute["version_date"] == "2024-01-01"
    assert src_statute["effective_date"] == "2024-01-01"
    assert src_statute["page"] == "3-4"
    assert src_statute["chunk_id"] == "chunk-101"

    # 2. 판례 문서
    precedent_doc = SimpleNamespace(
        page_content="대법원 2022. 5. 12. 선고 2021다298765 판결. 임대인의 보증금 반환의무와 임차인의 목적물 인도의무는 동시이행관계에 있다.",
        metadata={
            "file_name": "대법원_2021다298765_판결.pdf",
            "page": 1,
            "court": "대법원",
            "case_number": "2021다298765",
            "decision_date": "2022. 5. 12.",
        },
    )
    src_precedent = build_source_from_chroma_doc(precedent_doc, category="civil")
    assert src_precedent["source_type"] == "PRECEDENT"
    assert src_precedent["court"] == "대법원"
    assert src_precedent["case_number"] == "2021다298765"
    assert src_precedent["decision_date"] == "2022. 5. 12."


def test_t06_graphrag_and_vector_fallback_sources_typed_correctly():
    """T-06: ChromaDB에 없지만 GraphRAG 및 Hybrid Vector Fallback으로 조회된 증거 문서의 출처 유형이 정확한지 확인한다."""
    # 1. Neo4j GraphRAG 경로 출처
    graph_path = {
        "span_id": "span-99",
        "claim_id": "claim-88",
        "evidence_id": "evi-77",
        "filename": "부동산임대차계약서.pdf",
        "page_or_section": "p.2",
        "evidence_text": "보증금 2억원은 2025. 4. 30. 반환한다.",
        "relation": "SUPPORTS",
        "target_content": "보증금 반환 기한",
    }
    src_graph = build_source_from_graph_path(graph_path)
    assert src_graph["source_type"] == "CASE_EVIDENCE"
    assert src_graph["retrieval_method"] == "NEO4J_GRAPH"
    assert src_graph["source_id"] == "GRAPH:span-99"
    assert src_graph["evidence_id"] == "evi-77"
    assert src_graph["filename"] == "부동산임대차계약서.pdf"
    assert src_graph["page"] == "p.2"

    # 2. Hybrid Vector Fallback 출처
    vec_match = {
        "node_id": "fact-42",
        "node_type": "Fact",
        "content": "임차인은 2025-03-01 계약 해지 통고를 발송함",
        "file_name": "문자메시지_캡처.pdf",
        "evidence_id": "evi-55",
        "page": "1",
    }
    src_vec = build_source_from_vector_match(vec_match)
    assert src_vec["source_type"] == "CASE_EVIDENCE"
    assert src_vec["retrieval_method"] == "HYBRID_VECTOR_FALLBACK"
    assert src_vec["source_id"] == "VECTOR:fact-42"
    assert src_vec["evidence_id"] == "evi-55"
    assert src_vec["filename"] == "문자메시지_캡처.pdf"


def test_t07_double_parentheses_and_punctuation_clean_citation():
    """T-07: 이중 괄호 `((파일명.pdf, p.1))` 또는 따옴표 혼입 시에도 출처가 정상 매칭되고 정화되는지 검증한다."""
    retrieved_sources = [
        {
            "source_id": "STATUTE:주택임대차보호법:제6조의2:276291",
            "file_name": "주택임대차보호법.pdf",
            "filename": "주택임대차보호법.pdf",
            "page": "1",
            "content": "제6조의2(묵시적 갱신의 경우 계약의 해지) ② 제1항에 따른 해지는 임대인이 그 통지를 받은 날부터 3개월이 지나면 그 효력이 발생한다.",
            "source_type": "STATUTE",
        }
    ]

    # 1. 이중 괄호 형태의 정상 출처 인용 검증
    draft_valid = "임대인이 통지를 받은 날부터 3개월이 지나면 해지의 효력이 발생합니다. ((주택임대차보호법.pdf, p.1))"
    audit_valid = audit_citations_and_claims(draft_valid, retrieved_sources)
    assert len(audit_valid["unverified_citations"]) == 0, f"이중 괄호 인용이 정상 매칭되어야 함: {audit_valid['unverified_citations']}"
    assert len(audit_valid["validated_citation_ids"]) >= 1

    # 2. 이중 괄호 형태의 미검증 가짜 출처가 깨끗하게 정화되는지 검증 (잔여 괄호 없음)
    draft_fake = "임의의 가짜 법령에 따른 주장입니다. ((가짜법령.pdf, p.1))"
    audit_fake = audit_citations_and_claims(draft_fake, retrieved_sources)
    assert len(audit_fake["unverified_citations"]) >= 1

    sanitized = sanitize_unverified_citations(draft_fake, retrieved_sources)
    assert "가짜법령.pdf" not in sanitized
    assert "[근거 미확인]" in sanitized
    assert "[근거 미확인])" not in sanitized, f"잔류 닫는 괄호가 없어야 함: {sanitized}"
    assert "([근거 미확인]" not in sanitized, f"잔류 여는 괄호가 없어야 함: {sanitized}"


