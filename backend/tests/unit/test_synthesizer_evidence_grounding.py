# -*- coding: utf-8 -*-
"""
상담 시 증거 파일 원문 및 사실 승인/반려 내역 컨텍스트 연동 단위 테스트 모듈.

이 모듈은 증거 파일 등록 시 추출·검토된 사실 승인(APPROVED) 및 반려(REJECTED),
대기(PENDING) 내역이 사건 브리핑(case_evidence_briefing)을 통해 단일 권위 공급처로
Synthesizer 프롬프트에 주입되고 불필요한 증거 원문 중복 블록이 배제되는지 검증한다.
또한 정산 계산기 및 상담 의미 분석기의 Fast-Path 동작을 함께 검증한다.
"""

from typing import Any, Dict, List
import pytest
from langchain_core.messages import HumanMessage
from ai_legal_helper.agents.synthesizer import synthesize
import ai_legal_helper.agents.synthesizer as synth_mod
import ai_legal_helper.case_intelligence.settlement_calculator as sc
import ai_legal_helper.case_intelligence.consultation_semantics as cs
import ai_legal_helper.case_intelligence.semantic_judgment as sj
from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing, FactItemBrief


class MockCaptureLLM:
    """프롬프트 주입 내용을 캡처하는 테스트용 목(Mock) LLM."""

    def __init__(self) -> None:
        self.captured_prompt: str = ""

    def invoke(self, prompt: Any) -> Any:
        self.captured_prompt = str(prompt)
        class MockResponse:
            content = "종합 법률 분석 결과입니다."
        return MockResponse()


def test_synthesizer_injects_briefing_without_redundant_grounding_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """사건 증거가 존재할 때 사건 브리핑이 단일 권위 소스로 주입되고 중복 원문 블록은 배제되는지 검증한다."""
    mock_llm = MockCaptureLLM()
    monkeypatch.setattr(synth_mod, "get_llm", lambda **kwargs: mock_llm)

    fake_source_doc = {
        "evidence_id": "doc-001",
        "evidence_label": "E01",
        "document_name": "E01_주택임대차계약서.txt",
        "review_status": "REVIEW_REQUIRED",
        "source_kind": "TXT",
        "content": "임대차계약서\n보증금: 3억 원\n계약기간: 2022.03.01 ~ 2024.02.28",
        "approval_scope": "PARTIAL_APPROVED",
        "approval_scope_label": "일부 승인 완료",
        "claim_review_guide": (
            "사실 검토 승인 상태: [일부 승인 완료] (총 3건 중 승인 1건, 반려 1건, 대기 1건)\n"
            "- [승인된 주장 (APPROVED)] (법률 판단의 확정적 근거로 활용):\n"
            "  * \"보증금은 300,000,000원이다.\"\n"
            "- [반려된 주장 (REJECTED)] (사용자가 반려함. 절대 사실로 채택하지 마십시오):\n"
            "  * \"월세 50만 원이 존재한다.\"\n"
            "- [대기/미확인 주장 (PENDING)] (추가 확인 필요):\n"
            "  * \"관리비 10만 원 별도.\""
        ),
        "approved_claim_count": 1,
        "rejected_claim_count": 1,
        "pending_claim_count": 1,
    }

    briefing_payload = {
        "case_id": "case-test-123",
        "title": "전세보증금 반환 사건",
        "formatted_summary": (
            "### [1. 사건 개요 및 당사자 관계]\n- 임대차 계약\n"
            "### [2. 확정 사실관계 및 주요 타임라인]\n- [입증된 사실] 보증금은 300,000,000원이다. [E01_주택임대차계약서.txt]"
        ),
        "source_documents": [fake_source_doc],
    }

    messages = [HumanMessage(content="보증금 3억을 돌려받을 수 있나요?")]
    results = {"민법": "임대차 만료 시 반환 청구 가능"}

    # Synthesizer 실행
    synthesize(
        messages=messages,
        results=results,
        intent="NEW_LEGAL_ANALYSIS",
        case_evidence_briefing=briefing_payload,
    )

    prompt = mock_llm.captured_prompt
    assert prompt, "프롬프트가 생성되지 않았습니다."

    # 1. 단일 소스 브리핑 블록 정상 주입 확인
    assert "[등록된 사건 증거 및 확정 사실 브리핑]" in prompt
    assert "보증금은 300,000,000원이다. [E01_주택임대차계약서.txt]" in prompt
    assert "[중요 작성 및 인용 원칙]" in prompt
    assert "사건 브리핑의 확정 사실관계([입증된 사실])를 근거로 답변하고" in prompt

    # 2. 중복을 유발하던 별도의 원문 통째 주입 블록이 배제되었는지 검증
    assert "[등록된 사건 증거 파일 원문 및 사실 승인/반려 내역]" not in prompt


def test_settlement_calculator_fast_path_skips_non_monetary_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    """금액이 없는 비금액 사실에 대해 LLM 분류를 호출하지 않고 Fast-Path로 스킵하는지 검증한다."""
    llm_called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> Any:
        nonlocal llm_called
        llm_called = True
        raise AssertionError("비금액 사실에 대해 LLM이 호출되면 안 됩니다.")

    monkeypatch.setattr(sj, "classify_statement", fail_if_called)

    briefing = CaseEvidenceBriefing(
        case_id="case-001",
        title="테스트 사건",
        facts=[
            FactItemBrief(fact_id="f1", statement="임대인은 계약 해지 통지를 2024년 1월 10일 수령하였다.", verification_status="EVIDENCE_SUPPORTED"),
            FactItemBrief(fact_id="f2", statement="목적물 주택은 서울시 마포구에 위치한다.", verification_status="EVIDENCE_SUPPORTED"),
            FactItemBrief(fact_id="f3", statement="임차인은 열쇠를 반환하고 퇴거를 완료하였다.", verification_status="EVIDENCE_SUPPORTED"),
        ],
    )

    # 비금액 사실만 있는 경우 LLM이 단 한 번도 호출되지 않아야 함
    deposit = sc.extract_case_contract_deposit(briefing)

    assert not llm_called
    assert deposit == 0


def test_settlement_calculator_caches_result_on_same_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    """동일한 사건 사실 목록에 대해 정산 계산 결과가 브리핑 인스턴스 캐시를 통해 즉시 재사용되는지 검증한다."""
    class FakeVerdict:
        label = "CONTRACT_PRINCIPAL"
        evidence_quote = "300,000,000원"

    monkeypatch.setattr(sj, "classify_statement", lambda *args, **kwargs: FakeVerdict())

    briefing = CaseEvidenceBriefing(
        case_id="case-002",
        title="테스트 사건",
        facts=[
            FactItemBrief(fact_id="f1", statement="계약서 상 임대차 보증금은 300,000,000원이다.", adjudication_status="EVIDENCE_SUPPORTED"),
        ],
    )

    # 최초 계산
    deposit1 = sc.extract_case_contract_deposit(briefing)
    assert deposit1 == 300000000
    assert hasattr(briefing, "_cached_contract_deposit")

    # 브리핑의 사실 목록을 임의로 비워도 캐시된 결과가 반환되는지 검증
    briefing.facts = []
    deposit2 = sc.extract_case_contract_deposit(briefing)
    assert deposit2 == 300000000


def test_consultation_semantics_fast_path_skips_non_termination(monkeypatch: pytest.MonkeyPatch) -> None:
    """종료·반환 관련 키워드가 없는 질문/답변에 대해 LLM을 호출하지 않고 Fast-Path로 스킵하는지 검증한다."""
    called = False

    def fail_llm(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("비종료 키워드 텍스트에 대해 LLM이 호출되면 안 됩니다.")

    monkeypatch.setattr(sj, "classify_statement", fail_llm)

    # 단순 안부나 행정 절차 문의 등 계약 종료 키워드가 없는 텍스트
    status = cs.termination_statement_status("안녕하세요, 주민센터 위치와 서류 발급 절차를 알려주세요.")

    assert not called
    assert status == "OTHER"
