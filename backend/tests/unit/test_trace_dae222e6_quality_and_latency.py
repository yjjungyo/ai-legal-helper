"""Trace dae222e6 품질, 선순위 대항력 법리, 상담 전제 채택 및 지연 단축 회귀 테스트.

이 모듈은 Trace dae222e6-857b-4991-a78f-5c885f37c917에서 보고된 3가지 핵심 결함을 검증한다:
1. 선순위 대항요건·확정일자 임차인의 후순위 가압류 대비 권리 안전성 법리 정상성 (주택임대차보호법 제3조, 제3조의2).
2. 의뢰인 등록 증거 및 질문 진술 사실의 상담 기초 전제(Stipulated Facts) 채택 및 USER_STATEMENT 결함 오탐 방지.
3. 소제목·의문형 문장에 대한 qa_checker 허위 결함(도달일 미확인 상태의 종료일 확정 단정) 방지 및 재작성 루프 단축.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from ai_legal_helper.agents.qa_checker import check_deterministic_qa
from ai_legal_helper.agents.verification import run_verification
from ai_legal_helper.workflows import document_consultation as consultation
from ai_legal_helper.workflows import legal_workflow as workflow


@pytest.fixture
def sample_dae222e6_sources():
    """Trace dae222e6 상담에 등록된 사건 문서 및 검색 법령 출처 픽스처."""
    return [
        {
            "source_id": "E01_주택임대차계약서.txt",
            "filename": "E01_주택임대차계약서.txt",
            "document_name": "E01_주택임대차계약서.txt",
            "source_type": "CASE_EVIDENCE",
            "review_status": "APPROVED",
            "content": "임대차계약서: 임대인 홍길동, 임차인 김철수. 보증금 300,000,000원. 계약기간 2022.04.01~2024.03.31. 인도 및 전입 2022.03.03, 확정일자 2022.04.01.",
            "sha256": "hash_contract",
            "extraction_version": "v1",
        },
        {
            "source_id": "E02_등기부등본_메모.txt",
            "filename": "E02_등기부등본_메모.txt",
            "document_name": "E02_등기부등본_메모.txt",
            "source_type": "CASE_EVIDENCE",
            "review_status": "APPROVED",
            "content": "등기사항전부증명서 갑구: 2026.07.18 가압류 권리자 주식회사 동진은행 청구금액 72,000,000원. 2026.07.25 가압류 권리자 주택도시보증공사 120,000,000원.",
            "sha256": "hash_registry",
            "extraction_version": "v1",
        },
        {
            "source_id": "STATUTE:주택임대차보호법_제3조",
            "statute_name": "주택임대차보호법",
            "article": "제3조",
            "title": "대항력 등",
            "source_type": "STATUTE",
            "content": "제3조(대항력 등) ① 임대차는 그 등기가 없는 경우에도 임차인이 주택의 인도와 주민등록을 마친 때에는 그 다음 날부터 제3자에 대하여 효력이 생긴다.",
        },
        {
            "source_id": "STATUTE:주택임대차보호법_제3조의2",
            "statute_name": "주택임대차보호법",
            "article": "제3조의2",
            "title": "보증금의 회수",
            "source_type": "STATUTE",
            "content": "제3조의2(보증금의 회수) ② 제3조제1항의 대항요건과 임대차계약증서상의 확정일자를 갖춘 임차인은 경매 시 후순위권리자나 그 밖의 채권자보다 우선하여 보증금을 변제받을 권리가 있다.",
        },
    ]


def test_qa_checker_ignores_markdown_heading_and_question_sentences(sample_dae222e6_sources):
    """소제목 및 의문/검토형 종결 문장이 도달일 미확인 상태의 확정 단정으로 오탐되지 않는지 검증한다.

    Trace dae222e6에서 '- **현재 즉시 전액 반환청구가 성숙했는지**'라는 소제목이
    UNCONFIRMED_TERMINATION_PATTERNS에 걸려 불필요하게 검증 실패(REVIEW_REQUIRED)로 이어졌던
    오탐 문제를 방지하는지 확인한다.
    """
    question = "등기부에서 2026년 8월 12일 은행 가압류 7,200만 원을 발견했습니다. 제 보증금 반환에 어떤 변화가 생기나요?"
    draft_answer = (
        "### 1. 핵심 결론\n"
        "- 2022년 갖춘 대항력과 확정일자 순위는 묵시적 갱신 중에도 그대로 유지되므로 보증금 3억 원의 법률상 우선변제 순위는 안전하게 보호됩니다.\n\n"
        "### 2. 쟁점별 검토\n"
        "- **현재 즉시 전액 반환청구가 성숙했는지**: 해지 통지의 상대방 도달 시점 및 3개월 경과 여부를 확인할 필요가 있습니다.\n"
        "- **즉시 반환 가능 여부**: 임대인의 자금 사정에 따라 임의 반환이 지연될 실무적 위험이 존재합니다. [E01_주택임대차계약서.txt]\n"
    )

    qa_result = check_deterministic_qa(
        question=question,
        draft_answer=draft_answer,
        retrieved_sources=sample_dae222e6_sources,
        case_context="검토 기준일: 2026-11-01",
    )

    # 법률 적용 위험 검사에서 소제목/의문형 문장이 허위 결함으로 감지되지 않아야 함
    assert qa_result.legal_risk_passed is True
    # repair_targets에 '도달일 미확인 상태의 종료일 확정 단정'이 포함되지 않아야 함
    for target in qa_result.repair_targets:
        assert "도달일이 객관적으로 확인되지 않았는데 종료일을 확정" not in target.repair_reason


def test_consultation_stipulated_facts_and_user_statement_pass(sample_dae222e6_sources):
    """의뢰인의 질문 진술(USER_STATEMENT)이 공적 원본 부재만을 이유로 결함 주장으로 분류되지 않고 통과하는지 검증한다.

    의뢰인이 등록한 전제나 발견일 진술이 defective_claims에 포함되어 REVISE를 유발하던 문제를 방지한다.
    """
    question = "2026년 8월 12일 등기부에서 가압류를 발견했습니다. 보증금 3억을 돌려받을 수 있나요?"
    draft = (
        "의뢰인의 진술상 2026년 8월 12일 가압류를 발견하셨으며, "
        "2022년 갖춘 대항요건과 확정일자에 따라 보증금 3억 원의 우선변제권이 유지됩니다. "
        "[E01_주택임대차계약서.txt], (주택임대차보호법 제3조의2)"
    )

    mock_llm_reply = {
        "status": "REVISE",
        "reason_code": "ANSWER_REVISION_REQUIRED",
        "claims": [
            {
                "claim": "의뢰인의 진술상 2026년 8월 12일 가압류를 발견하셨으며",
                "claim_type": "USER_STATEMENT",
                "fact_status": "USER_STATEMENT",
                "source_ids": [],
                "grounding_status": "UNCERTAIN",
                "reason": "사용자 질문에 기재된 발견 시점 진술임",
            },
            {
                "claim": "2022년 갖춘 대항요건과 확정일자에 따라 보증금 3억 원의 우선변제권이 유지됩니다.",
                "claim_type": "LEGAL_APPLICATION",
                "fact_status": "VERIFIED_FACT",
                "source_ids": ["E01_주택임대차계약서.txt", "STATUTE:주택임대차보호법_제3조의2"],
                "grounding_status": "SUPPORTED",
                "reason": "계약서 및 법 제3조의2로 뒷받침됨",
            },
        ],
        "question_coverage": [{"question": "가압류 발견과 보증금 반환 영향", "answered": True, "reason": "설명함"}],
        "consistency_checks": {
            "opening_conclusion": {"passed": True, "reason": "첫 결론 일치", "source_ids": ["E01_주택임대차계약서.txt"]},
            "timeline": {"passed": True, "reason": "시간순서 부합", "source_ids": ["E01_주택임대차계약서.txt"]},
            "expressed_intent": {"passed": True, "reason": "의사표시 일치", "source_ids": ["E01_주택임대차계약서.txt"]},
            "provenance": {"passed": True, "reason": "출처 수준 구분", "source_ids": ["E01_주택임대차계약서.txt"]},
        },
        "missing_issues": ["가압류 이의신청 절차 안내 권고"],
        "missing_legal_issues": [],
        "candidate_laws": [],
        "contradictions": [],
        "revision_instructions": [],
        "warnings": [],
    }

    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(mock_llm_reply, ensure_ascii=False)

    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification(
            question=question,
            draft_answer=draft,
            retrieved_sources=sample_dae222e6_sources,
            require_question_coverage=True,
        )

    # USER_STATEMENT는 defective_claims에서 제외되고, 부수적인 missing_issues는 warnings로 이관되어 PASS 확정되어야 함
    assert result["status"] == "PASS"
    assert result["reason_code"] == "NONE"
    assert any("가압류 이의신청" in w for w in result["warnings"])


def test_next_verification_step_finalizes_draft_at_revision_limit():
    """재작성 상한 도달 시 초안과 주장이 존재하면 insufficient로 버리지 않고 finalize로 확정하는지 검증한다.

    12분 이상 루프를 돌고도 마지막에 '근거 확인을 마치지 못했습니다'로 답변이 폐기되던 UX 병목을 방지한다.
    """
    state_at_limit = {
        "draft_answer": "선순위 보증금 3억 원의 대항력과 우선변제권은 확고히 유지됩니다.",
        "revision_count": 3,
        "statute_search_count": 1,
        "verification_result": {
            "status": "REVISE",
            "reason_code": "ANSWER_REVISION_REQUIRED",
            "claims": [
                {
                    "claim": "선순위 보증금 3억 원의 대항력과 우선변제권은 확고히 유지됩니다.",
                    "claim_type": "LEGAL_APPLICATION",
                    "grounding_status": "SUPPORTED",
                    "source_ids": ["E01_주택임대차계약서.txt"],
                }
            ],
            "missing_legal_issues": [],
            "candidate_laws": [],
        },
    }

    target = consultation.next_verification_step(state_at_limit)
    # 기존 초안과 검증 주장이 있으므로 최종화 노드로 라우팅되어야 함
    assert target == "finalize"


def test_senior_priority_over_junior_attachment_prompt_guidance():
    """DOCUMENT_ANSWER_SYSTEM 프롬프트에 선순위 대항력 vs 후순위 가압류 및 상담 전제 원칙이 명시되어 있는지 검증한다."""
    from ai_legal_helper.agents.document_answer import DOCUMENT_ANSWER_SYSTEM

    assert "선순위 대항요건·확정일자 임차인과 후순위 가압류 권리관계 원칙" in DOCUMENT_ANSWER_SYSTEM
    assert "주택임대차보호법 제3조" in DOCUMENT_ANSWER_SYSTEM
    assert "제3조의2" in DOCUMENT_ANSWER_SYSTEM
    assert "후순위 가압류" in DOCUMENT_ANSWER_SYSTEM
    assert "상담 전제 사실(Stipulated Facts) 채택 원칙" in DOCUMENT_ANSWER_SYSTEM
    assert "보증금을 전액 반환받을 위험이 커졌다" in DOCUMENT_ANSWER_SYSTEM
