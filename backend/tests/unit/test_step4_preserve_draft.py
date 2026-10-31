# -*- coding: utf-8 -*-
"""
모듈명: test_step4_preserve_draft.py

[모듈 개요]
STEP 4 최종 답변 재조립 제거 및 초안 보존 개발지시서에 따른 8대 필수 검증 단위 테스트.

[검증 항목]
1. 정상 초안의 본문 유지 (assemble_grounded_answer로 덮어쓰지 않고 초안 유지)
2. 정상 초안과 최종 답변의 SHA256 해시 일치
3. 문서 상담(finish_answer)과 일반 상담(finalize_node)의 초안 보존 일관성
4. 전체 파일명 증거 인용([E01_주택임대차계약서.txt]) 및 출처 식별자 유지
5. 조문 인용(제3조, 제3조의2) 및 상세 출처 메타데이터 정상 유지
6. 사건 변동 분석(case_delta)이 답변 본문에 강제 삽입되지 않고 메타데이터로 안전 분리
7. 본문에 인용되지 않은 출처는 cited_sources에서 제외 (과잉 노출 방지)
8. 기존 API 응답 스키마 필드 전체(final_answer, answer, sources, cited_sources, claim_citations, case_delta 등) 정상 반환
"""
import pytest
import hashlib
from unittest.mock import patch
from langchain_core.messages import AIMessage, HumanMessage

from ai_legal_helper.workflows.legal_workflow import finalize_node
from ai_legal_helper.workflows import document_consultation as consultation
from ai_legal_helper.rag.grounding_context import format_grounding_sources


def test_01_natural_draft_preserved_without_assemble_grounded_answer():
    """테스트 1: Synthesizer가 작성한 정상 초안이 assemble_grounded_answer로 덮어씌워지지 않고 그대로 유지됨."""
    draft_text = (
        "임대차계약이 만료되었으므로 임대인은 보증금 2억 원을 반환할 의무가 있습니다. [E01_주택임대차계약서.txt] "
        "주택임대차보호법 제3조에 따라 대항력을 갖추었으므로 제3자에게도 대항할 수 있습니다. [주택임대차보호법 제3조(대항력 등)]"
    )
    briefing = {
        "case_id": "test-case-001",
        "title": "임대차 보증금 반환 분쟁",
        "source_registry": {
            "E01": {
                "evidence_id": "E01_주택임대차계약서.txt",
                "document_name": "E01_주택임대차계약서.txt",
                "file": "E01_주택임대차계약서.txt",
                "file_name": "E01_주택임대차계약서.txt",
            }
        },
        "facts": [],
    }
    issue_results = [
        {
            "issue_id": "ISSUE-01",
            "issue_title": "보증금 반환 의무",
            "status": "VERIFIED",
            "verification_status": "PASS",
            "confidence": 0.95,
            "relevant_evidence_labels": ["E01"],
            "missing_evidence": [],
            "grounding_sources": ["E01_주택임대차계약서.txt"],
            "legal_sources": ["주택임대차보호법 제3조(대항력 등)"],
        }
    ]
    retrieved = [
        {
            "source_id": "E01_주택임대차계약서.txt",
            "source_type": "CASE_EVIDENCE",
            "content": "보증금 2억원",
        },
        {
            "source_id": "주택임대차보호법 제3조(대항력 등)",
            "source_type": "STATUTE",
            "content": "대항력 요건",
        },
    ]

    state = {
        "question": "보증금 반환받을 수 있나요?",
        "draft_answer": draft_text,
        "verification_result": {
            "status": "PASS",
            "reason_code": "NONE",
            "issue_results": issue_results,
            "claims": [
                {
                    "claim": "임대인은 보증금 2억 원을 반환할 의무가 있습니다.",
                    "claim_type": "LEGAL_APPLICATION",
                    "grounding_status": "SUPPORTED",
                    "source_ids": ["E01_주택임대차계약서.txt"],
                }
            ],
        },
        "case_evidence_briefing": briefing,
        "issue_results": issue_results,
        "retrieved_sources": retrieved,
    }

    result = finalize_node(state)

    # 5섹션/6섹션 정형 보고서 템플릿(assemble_grounded_answer)으로 교체되지 않고 초안 문장이 그대로 유지되어야 함
    assert "[1. 검증된 핵심 쟁점 및 법률 판단]" not in result["final_answer"]
    assert "[3. 안전한 우선순위 대응 절차]" not in result["final_answer"]
    assert "보증금 2억 원을 반환할 의무가 있습니다." in result["final_answer"]


def test_02_draft_and_final_sha256_match():
    """테스트 2: 정상 초안과 최종 답변의 SHA256 해시가 일치함."""
    draft_text = "주택임대차보호법 제3조에 따라 대항력이 인정됩니다. [주택임대차보호법 제3조]"
    retrieved = [{
        "source_id": "주택임대차보호법 제3조",
        "source_type": "STATUTE",
        "content": "대항력 조항 본문",
    }]
    state = {
        "question": "대항력 성립 요건이 어떻게 되나요?",
        "draft_answer": draft_text,
        "verification_result": {"status": "PASS", "claims": []},
        "retrieved_sources": retrieved,
    }

    result = finalize_node(state)

    draft_sha = hashlib.sha256(draft_text.strip().encode("utf-8")).hexdigest()
    final_sha = hashlib.sha256(result["final_answer"].strip().encode("utf-8")).hexdigest()
    assert draft_sha == final_sha, "초안 본문이 변경 없이 그대로 확정되어야 함"


def test_03_consistency_between_document_and_general_consultation():
    """테스트 3: 문서 상담(finish_answer)과 일반 상담(finalize_node)의 초안 보존 일관성 검증."""
    draft_text = "확인된 서류에 따르면 임대차 계약이 적법하게 체결되었습니다. [E01_계약서.txt]"
    briefing = {
        "case_id": "test-doc-case",
        "source_documents": [
            {
                "evidence_id": "doc-1",
                "document_name": "E01_계약서.txt",
                "review_status": "APPROVED",
                "content": "임대차 계약 체결 본문",
                "sha256": "original",
                "extraction_version": "v1",
            }
        ],
    }
    doc_state = {
        "answer_mode": consultation.DOCUMENT_MODE,
        "question": "계약서 확인해 주세요.",
        "draft_answer": draft_text,
        "case_evidence_briefing": briefing,
        "retrieved_sources": [],
        "approved_document_ids": ["E01_계약서.txt"],
    }
    sources_list = consultation.document_sources(doc_state)
    _, manifest = format_grounding_sources(sources_list)
    ver_res = {
        "status": "PASS",
        "reason_code": "NONE",
        "verified_answer_sha256": hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
        "source_manifest": manifest,
        "claims": [
            {
                "claim": "임대차 계약이 적법하게 체결되었습니다.",
                "claim_type": "CASE_FACT",
                "grounding_status": "SUPPORTED",
                "source_ids": ["E01_계약서.txt"],
            }
        ],
    }
    doc_state["verification_result"] = ver_res

    # 1. 문서 상담 경로
    with patch.object(consultation, "validate_document_snapshot", return_value=None):
        doc_res = consultation.finish_answer(doc_state)

    # 2. 일반 상담 경로
    gen_state = {
        "question": "계약서 확인해 주세요.",
        "draft_answer": draft_text,
        "verification_result": ver_res,
        "retrieved_sources": sources_list,
    }
    gen_res = finalize_node(gen_state)

    assert doc_res["final_answer"] == gen_res["final_answer"] == draft_text
    assert doc_res["final_disposition"] == gen_res["final_disposition"] == "DELIVERED"


def test_04_full_filename_evidence_citations_preserved():
    """테스트 4: 전체 파일명 증거 인용([E01_주택임대차계약서.txt])이 최종 답변 및 출처에 보존됨."""
    draft_text = "계약 기간은 2024년 12월까지입니다. [E01_주택임대차계약서.txt]"
    retrieved = [{
        "source_id": "E01_주택임대차계약서.txt",
        "document_name": "E01_주택임대차계약서.txt",
        "source_type": "CASE_EVIDENCE",
        "content": "2024년 12월 만료",
    }]
    state = {
        "question": "계약 만료일이 언제인가요?",
        "draft_answer": draft_text,
        "verification_result": {"status": "PASS", "claims": []},
        "retrieved_sources": retrieved,
    }
    result = finalize_node(state)
    assert "[E01_주택임대차계약서.txt]" in result["final_answer"]
    assert any(s.get("source_id") == "E01_주택임대차계약서.txt" for s in result["cited_sources"])


def test_05_statute_citation_and_metadata_preserved():
    """테스트 5: 조문 인용(제3조) 및 상세 출처 메타데이터가 정상 유지됨."""
    statute_id = "주택임대차보호법 제3조(대항력 등) [법률, 제18833호, 시행 2022-02-03]"
    draft_text = f"임차인은 주택의 인도와 주민등록을 마치면 대항력을 취득합니다. [{statute_id}]"
    retrieved = [{
        "source_id": statute_id,
        "statute_name": "주택임대차보호법",
        "article": "제3조",
        "source_type": "STATUTE",
        "content": "대항력 요건 본문",
    }]
    state = {
        "question": "대항력 요건 안내해 주세요.",
        "draft_answer": draft_text,
        "verification_result": {"status": "PASS", "claims": []},
        "retrieved_sources": retrieved,
    }
    result = finalize_node(state)
    assert statute_id in result["final_answer"]
    assert any(s.get("article") == "제3조" for s in result["cited_sources"])


def test_06_case_delta_not_inserted_into_answer_body():
    """테스트 6: 사건 변동 분석(case_delta)이 답변 본문에 강제 삽입되지 않고 메타데이터로 분리됨."""
    draft_text = "현재 임대차 계약은 만료되어 보증금 반환을 청구할 수 있습니다. [E01_계약서.txt]"
    state = {
        "question": "저번이랑 상황이 달라졌나요?",
        "draft_answer": draft_text,
        "verification_result": {"status": "PASS", "claims": []},
        "case_evidence_briefing": {
            "case_id": "c1",
            "source_registry": {},
            "facts": [],
        },
        "retrieved_sources": [{
            "source_id": "E01_계약서.txt",
            "source_type": "CASE_EVIDENCE",
            "content": "만료 조항",
        }],
    }
    result = finalize_node(state)
    # 답변 본문에 변동 사항 비교 섹션 헤더가 강제로 들어가지 않아야 함
    assert "[사건 변동 사항 및 법률 판단 비교]" not in result["final_answer"]
    assert "[이전 상담 대비 변동 사실]" not in result["final_answer"]
    assert result["final_answer"] == draft_text


def test_07_uncited_sources_excluded_from_cited_sources():
    """테스트 7: 답변 본문에 실제로 인용되지 않은 출처는 cited_sources에서 제외됨."""
    draft_text = "임대인은 보증금을 반환해야 합니다. [E01_계약서.txt]"
    retrieved = [
        {"source_id": "E01_계약서.txt", "source_type": "CASE_EVIDENCE", "content": "계약서"},
        {"source_id": "E02_등기부등본.pdf", "source_type": "CASE_EVIDENCE", "content": "등기부"},
        {"source_id": "민법 제536조", "source_type": "STATUTE", "content": "동시이행"},
    ]
    state = {
        "question": "보증금 받을 수 있나요?",
        "draft_answer": draft_text,
        "verification_result": {"status": "PASS", "claims": []},
        "retrieved_sources": retrieved,
    }
    result = finalize_node(state)
    cited_ids = {s.get("source_id") for s in result["cited_sources"]}
    assert "E01_계약서.txt" in cited_ids
    assert "E02_등기부등본.pdf" not in cited_ids, "인용되지 않은 등기부는 제외되어야 함"
    assert "민법 제536조" not in cited_ids, "인용되지 않은 민법 조문은 제외되어야 함"


def test_08_api_response_schema_compatibility():
    """테스트 8: 기존 API 응답 스키마 필드가 모두 누락 없이 정상 반환됨."""
    draft_text = "적법한 임대차계약에 근거하여 보증금 반환 청구가 가능합니다."
    state = {
        "question": "청구 가능한가요?",
        "draft_answer": draft_text,
        "verification_result": {"status": "PASS", "claims": []},
        "retrieved_sources": [],
    }
    result = finalize_node(state)

    expected_keys = [
        "final_answer",
        "answer",
        "sources",
        "cited_sources",
        "claim_citations",
        "case_delta",
        "warnings",
        "final_disposition",
        "messages",
        "issue_results",
        "verification_result",
    ]
    for key in expected_keys:
        assert key in result, f"필수 API 응답 필드 누락: {key}"

    assert isinstance(result["messages"][0], AIMessage)
    assert result["final_answer"] == draft_text
    assert result["answer"] == draft_text
    assert result["final_disposition"] == "DELIVERED"
