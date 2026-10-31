# -*- coding: utf-8 -*-
"""
모듈명: test_step2_verification_schema.py

[모듈 개요]
STEP 2 개발지시서에 따른 Verification 출력 스키마 안정화 및 9대 필수 반례 검증 단위 테스트.

[주요 기능]
1. `inference_basis` 자료형 다양성(배열, 문자열, None) 정규화 검증
2. `source_ids` 자료형 다양성(단일 문자열, 콤마 구분 문자열, None) 정규화 검증
3. 빈 JSON 및 JSON 구문 오류(JSON_PARSE_ERROR) 시 기술 오류 격리 및 VERIFICATION_ERROR 처리 검증
4. 출처 근거 없는 허위 SUPPORTED 주장의 결정론적 UNSUPPORTED 강등 및 REVISE 전환 검증
5. 실패 Trace `3bc30893-8851-4264-adcf-0fa0f39d96da` 응답 재현 시 스키마 복구 및 정상 후속 분기 검증
"""
import pytest
import json
from unittest.mock import MagicMock, patch

from ai_legal_helper.agents.verification import (
    ClaimVerification,
    VerificationOutput,
    run_verification,
)
from ai_legal_helper.workflows import document_consultation as consultation


def test_01_inference_basis_as_array():
    """반례 1: inference_basis가 배열로 반환된 경우 문자열로 안전하게 정규화되는지 검증."""
    claim_dict = {
        "claim": "보증금 회수 위험이 증가했습니다.",
        "claim_type": "CASE_INFERENCE",
        "fact_status": "INFERENCE",
        "source_ids": ["E01_계약서.txt"],
        "grounding_status": "SUPPORTED",
        "inference_basis": ["E01_계약서.txt", "E02_등기부등본.pdf"],
        "inference_limit": "회수 위험에 관한 정황 평가임",
    }
    claim = ClaimVerification(**claim_dict)
    assert isinstance(claim.inference_basis, str)
    assert "E01_계약서.txt" in claim.inference_basis
    assert "E02_등기부등본.pdf" in claim.inference_basis


def test_02_inference_basis_as_string():
    """반례 2: inference_basis가 정상 문자열인 경우 원본 텍스트가 유지되는지 검증."""
    claim_dict = {
        "claim": "보증금 반환 의무가 있습니다.",
        "claim_type": "CASE_FACT",
        "source_ids": ["E01_계약서.txt"],
        "grounding_status": "SUPPORTED",
        "inference_basis": "E01_계약서 제4조에 명시된 반환 조항",
    }
    claim = ClaimVerification(**claim_dict)
    assert claim.inference_basis == "E01_계약서 제4조에 명시된 반환 조항"


def test_03_inference_basis_as_none():
    """반례 3: inference_basis가 None으로 반환된 경우 빈 문자열로 정규화되는지 검증."""
    claim_dict = {
        "claim": "단순 법령 규칙 설명입니다.",
        "claim_type": "LEGAL_RULE",
        "source_ids": ["주택임대차보호법_제3조"],
        "grounding_status": "SUPPORTED",
        "inference_basis": None,
    }
    claim = ClaimVerification(**claim_dict)
    assert claim.inference_basis == ""


def test_04_source_ids_as_single_string_and_csv():
    """반례 4: source_ids가 단일 문자열 또는 콤마 구분 문자열인 경우 문자열 리스트로 정규화되는지 검증."""
    # 단일 문자열
    c1 = ClaimVerification(claim="주장 1", source_ids="E01_계약서.txt")
    assert c1.source_ids == ["E01_계약서.txt"]

    # 콤마 구분 문자열
    c2 = ClaimVerification(claim="주장 2", source_ids="E01_계약서.txt, E02_주민등록초본.pdf")
    assert c2.source_ids == ["E01_계약서.txt", "E02_주민등록초본.pdf"]


def test_05_source_ids_as_none():
    """반례 5: source_ids가 None인 경우 빈 리스트([])로 정규화되는지 검증."""
    c = ClaimVerification(claim="출처 없는 일반 진술", source_ids=None)
    assert c.source_ids == []


def test_06_empty_json_fallback():
    """반례 6: 빈 JSON 객체('{}') 수신 시 기본 스키마가 적용되며 예외 없이 정규화되는지 검증."""
    output = VerificationOutput(**{})
    assert output.status == "REVISE"
    assert output.reason_code == "NONE"
    assert output.claims == []
    assert output.candidate_laws == []


def test_07_json_syntax_error_handling():
    """반례 7: JSON 구문 오류 시 VERIFICATION_ERROR 및 JSON_PARSE_ERROR로 안전 격리되는지 검증."""
    llm = MagicMock()
    llm.invoke.return_value.content = "이것은 JSON 형식이 아닌 일반 텍스트 설명입니다."

    sources = [{"source_id": "E01_계약서.txt", "content": "임대차 계약 내용"}]
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        res = run_verification(
            question="보증금 반환 시기는 언제인가요?",
            draft_answer="계약 만료 시 즉시 반환해야 합니다.",
            retrieved_sources=sources,
        )

    # Fail-open(PASS)이 아니며 기술 오류 코드로 격리되었는지 확인
    assert res["status"] == "INSUFFICIENT"
    assert res["reason_code"] == "VERIFICATION_ERROR"
    assert res["verification_error_type"] == "JSON_PARSE_ERROR"
    # 기술 오류 시 candidate_laws를 비워 불필요한 외부 법령 검색을 원천 차단함
    assert res["candidate_laws"] == []


def test_08_unsupported_claim_without_sources_demoted():
    """반례 8: 뒷받침 출처가 전혀 없는데 SUPPORTED로 반환된 법률 주장은 UNSUPPORTED로 강등되고 PASS가 차단되는지 검증."""
    output_dict = {
        "status": "PASS",
        "reason_code": "NONE",
        "claims": [
            {
                "claim": "임대인은 보증금 전액에 대해 12%의 지연손해금을 즉시 지급해야 합니다.",
                "claim_type": "LEGAL_APPLICATION",
                "source_ids": [],  # 출처 부재
                "grounding_status": "SUPPORTED",  # 모델의 잘못된 지원 판정
            }
        ],
    }
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(output_dict, ensure_ascii=False)

    sources = [{"source_id": "E01_계약서.txt", "content": "보증금 2억 원"}]
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        res = run_verification(
            question="지연이자 받을 수 있나요?",
            draft_answer="임대인은 보증금 전액에 대해 12%의 지연손해금을 즉시 지급해야 합니다.",
            retrieved_sources=sources,
        )

    # 1. 근거 없는 주장은 UNSUPPORTED로 강등됨
    assert res["claims"][0]["grounding_status"] == "UNSUPPORTED"
    # 2. 결과적으로 PASS가 취소되고 REVISE로 변경됨
    assert res["status"] == "REVISE"


def test_09_trace_3bc30893_reproduction():
    """반례 9: 실제 실패 Trace 3bc30893-8851-4264-adcf-0fa0f39d96da 응답 재현 시 정상 복구 및 승인 분기 검증."""
    # Trace 3bc30893 실패 당시 LLM이 반환했던 원본 payload 재현
    trace_payload = {
        "status": "REVISE",
        "reason_code": "LEGAL_SOURCE_MISSING",
        "candidate_laws": ["주택임대차보호법"],
        "missing_legal_issues": ["대항력 성립 요건 및 우선변제권 배당 순위"],
        "claims": [
            {
                "claim": "가압류 때문에 보증금반환채권 자체가 소멸하지는 않지만 회수 위험은 증가했습니다.",
                "claim_type": "CASE_INFERENCE",
                "fact_status": "INFERENCE",
                "source_ids": ["E01_퇴거_문자.txt"],
                "grounding_status": "SUPPORTED",
                "inference_basis": ["E01_퇴거_문자.txt"],  # 배열 자료형
                "inference_limit": "회수 위험에 관한 정황 평가에 한함",
            }
        ],
        "legal_search_requests": [
            {
                "law_name": "주택임대차보호법",
                "articles": ["제3조", "제3조의2"],
                "issue": "대항력 및 우선변제권 성립 요건",
                "question_part": "보증금 순위",
            }
        ],
    }

    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(trace_payload, ensure_ascii=False)

    sources = [{
        "source_id": "E01_퇴거_문자.txt",
        "filename": "E01_퇴거_문자.txt",
        "content": "보증금 반환 요청 문자 원문",
        "source_type": "CASE_EVIDENCE",
    }]

    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        ver = run_verification(
            question="가압류가 걸렸는데 제 보증금 순위는 어떻게 되나요?",
            draft_answer="가압류 때문에 보증금반환채권 자체가 소멸하지는 않지만 회수 위험은 증가했습니다. [E01_퇴거_문자.txt]",
            retrieved_sources=sources,
            require_question_coverage=False,
        )

    # 1. 스키마 오류 없이 정상 복구 및 정규화 확인
    assert ver["reason_code"] == "LEGAL_SOURCE_MISSING"
    assert ver["status"] == "REVISE"
    assert ver["claims"][0]["inference_basis"] == "E01_퇴거_문자.txt"

    # 2. 법령 검색 승인 상태에서 execute_statute_search로 올바르게 전이되는지 워크플로우 분기 검증
    state = {
        "question": "가압류가 걸렸는데 제 보증금 순위는 어떻게 되나요?",
        "answer_mode": "DOCUMENT_GROUNDED",
        "verification_result": ver,
        "approval_status": "APPROVED",
        "approved_statute_laws": ["주택임대차보호법"],
        "statute_search_count": 1,
    }
    assert consultation.next_verification_step(state) == "execute_statute_search"
