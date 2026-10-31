"""계약서 약정 기반 주장의 검증 정규화 및 허위 결함 방지 단위 테스트.

이 모듈은 처분문서(계약서 원문) 조항 및 약정에 직접 기초한 권리·의무 주장이
검증기에 의해 부당하게 UNSUPPORTED로 강등되어 무한 재작성 루프나 답변 보류로 빠지는 현상을
방지하고, 정상적으로 CASE_FACT로 인정되어 PASS 판정을 받는지 검증한다.
(Trace: 45d9a33c-ca7e-4896-8d59-2bb86eda8451 대응)
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from ai_legal_helper.agents.verification import run_verification


@pytest.fixture
def sample_sources():
    """문서 기반 상담의 기본 사건 문서 및 검색 법률 출처 목록을 반환한다."""
    return [
        {
            "source_id": "E01_주택임대차계약서.txt",
            "source_type": "CASE_EVIDENCE",
            "filename": "E01_주택임대차계약서.txt",
            "content": "제4조 (보증금의 반환) 임대차계약이 종료된 경우 임대인은 지체 없이 임차인에게 보증금을 반환한다.",
        },
        {
            "source_id": "주택임대차보호법_제3조",
            "source_type": "STATUTE",
            "statute_name": "주택임대차보호법",
            "article": "제3조",
            "content": "주택임대차는 그 등기가 없는 경우에도 임차인이 주택의 인도와 주민등록을 마친 때에는 그 다음 날부터 제삼자에 대하여 효력이 생긴다.",
        },
    ]


def test_contract_terms_claim_normalized_to_case_fact_and_supported(sample_sources):
    """계약서 원문 약정에 직접 기초한 주장은 CASE_FACT로 정규화되어 SUPPORTED를 유지한다.

    Trace 45d9a33c에서 '임차인은 계약서상 약정에 따라 보증금 반환을 요구할 수 있는 자료를 가지고 있습니다'
    주장이 법령 근거가 없다는 이유로 UNSUPPORTED로 강등되던 버그를 검증한다.
    """
    question = "등록된 계약서를 기준으로 현재까지 확인되는 계약 사실과 권리를 분석해 주세요."
    draft = (
        "등록된 계약서에 따르면 임대차계약이 체결되었습니다. [E01_주택임대차계약서.txt]\n"
        "따라서 계약이 종료되었다는 점이 확인되면, 임차인은 계약서상 약정에 따라 "
        "보증금 반환을 요구할 수 있는 자료를 가지고 있습니다. [E01_주택임대차계약서.txt]"
    )

    mock_llm_response = {
        "status": "PASS",
        "reason_code": "NONE",
        "recommended_action": "FINALIZE",
        "claims": [
            {
                "claim": "등록된 계약서에 따르면 임대차계약이 체결되었습니다.",
                "claim_type": "CASE_FACT",
                "fact_status": "VERIFIED_FACT",
                "source_ids": ["E01_주택임대차계약서.txt"],
                "grounding_status": "SUPPORTED",
                "reason": "계약서에 명시되어 있습니다.",
            },
            {
                "claim": "따라서 계약이 종료되었다는 점이 확인되면, 임차인은 계약서상 약정에 따라 보증금 반환을 요구할 수 있는 자료를 가지고 있습니다.",
                "claim_type": "LEGAL_APPLICATION",
                "fact_status": "VERIFIED_FACT",
                "source_ids": ["E01_주택임대차계약서.txt"],
                "grounding_status": "SUPPORTED",
                "reason": "E01 제4조에 계약 종료 시 임대인은 보증금을 반환한다고 기재되어 있습니다.",
            },
        ],
        "question_coverage": [
            {
                "question": "계약 사실과 권리 분석",
                "answered": True,
                "answerable": True,
                "limitation_disclosed": False,
                "limitation_statement": "",
                "reason": "계약 사실과 약정상 권리가 충실히 분석됨",
            }
        ],
        "consistency_checks": {
            "opening_conclusion": {"passed": True, "reason": "일치", "source_ids": ["E01_주택임대차계약서.txt"]},
            "timeline": {"passed": True, "reason": "일치", "source_ids": ["E01_주택임대차계약서.txt"]},
            "expressed_intent": {"passed": True, "reason": "일치", "source_ids": ["E01_주택임대차계약서.txt"]},
            "provenance": {"passed": True, "reason": "일치", "source_ids": ["E01_주택임대차계약서.txt"]},
        },
        "contradictions": [],
        "missing_issues": [],
        "missing_legal_issues": [],
        "revision_instructions": [],
        "warnings": [],
        "legal_search_requests": [],
        "preserved_points": [],
    }

    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(mock_llm_response, ensure_ascii=False)

    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification(
            question=question,
            draft_answer=draft,
            retrieved_sources=sample_sources,
            case_context="",
            require_question_coverage=True,
        )

    # 계약서상 약정에 기초한 주장이 CASE_FACT로 정규화되고 SUPPORTED 상태를 유지해야 한다.
    contract_claim = result["claims"][1]
    assert contract_claim["claim_type"] == "CASE_FACT"
    assert contract_claim["fact_status"] == "VERIFIED_FACT"
    assert contract_claim["grounding_status"] == "SUPPORTED"
    # 검증 결과는 REVISE로 강제 번복되지 않고 PASS를 유지해야 한다.
    assert result["status"] == "PASS"
    assert result["recommended_action"] == "FINALIZE"


def test_unsupported_legal_rule_without_statute_remains_unsupported(sample_sources):
    """계약서 약정 키워드가 없고 법령 출처가 없는 순수 법률 효과 단정 주장은 여전히 UNSUPPORTED로 강등된다.

    계약서 약정과 무관한 일반 법률 규정 주장에 대한 안전 검증이 무력화되지 않았음을 확인한다.
    """
    question = "대항력 요건을 알려주세요."
    draft = "대항력은 주택 인도와 주민등록을 마치면 익일 0시부터 법률상 당연히 발생합니다. [E01_주택임대차계약서.txt]"

    mock_llm_response = {
        "status": "PASS",
        "reason_code": "NONE",
        "recommended_action": "FINALIZE",
        "claims": [
            {
                "claim": "대항력은 주택 인도와 주민등록을 마치면 익일 0시부터 법률상 당연히 발생합니다.",
                "claim_type": "LEGAL_RULE",
                "fact_status": "VERIFIED_FACT",
                "source_ids": ["E01_주택임대차계약서.txt"],  # 법령이 아닌 계약서만 인용
                "grounding_status": "SUPPORTED",
                "reason": "일반 법률 지식에 부합함",
            }
        ],
        "question_coverage": [
            {
                "question": "대항력 요건",
                "answered": True,
                "answerable": True,
                "limitation_disclosed": False,
                "limitation_statement": "",
                "reason": "답변됨",
            }
        ],
        "consistency_checks": {
            "opening_conclusion": {"passed": True, "reason": "일치", "source_ids": ["E01_주택임대차계약서.txt"]},
            "timeline": {"passed": True, "reason": "일치", "source_ids": ["E01_주택임대차계약서.txt"]},
            "expressed_intent": {"passed": True, "reason": "일치", "source_ids": ["E01_주택임대차계약서.txt"]},
            "provenance": {"passed": True, "reason": "일치", "source_ids": ["E01_주택임대차계약서.txt"]},
        },
        "contradictions": [],
        "missing_issues": [],
        "missing_legal_issues": [],
        "revision_instructions": [],
        "warnings": [],
        "legal_search_requests": [],
        "preserved_points": [],
    }

    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(mock_llm_response, ensure_ascii=False)

    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification(
            question=question,
            draft_answer=draft,
            retrieved_sources=sample_sources,
            case_context="",
            require_question_coverage=True,
        )

    # 순수 법령 효과에 법령 출처가 연결되지 않은 주장은 UNSUPPORTED로 강등되어야 한다.
    claim = result["claims"][0]
    assert claim["grounding_status"] == "UNSUPPORTED"
    assert "법률 효과로 분류된 주장에 법령·판례 근거가 연결되지 않았습니다" in claim["reason"]
    assert result["status"] == "REVISE"
