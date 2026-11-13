# -*- coding: utf-8 -*-
"""
테스트 모듈: test_stage3_subsumption_gate.py

[테스트 개요]
SC-013 근본 원인 수정 3단계(Verification 검증 및 포섭 게이트 강화) 검증 테스트.

[검증 항목]
1. 선순위 근저당권이 존재하는 사건에서 후순위 임차인이 낙찰자에게 보증금 반환을 청구할 수 있다고 잘못 결론 내린 경우,
   결정론적 QA 검사에서 경매 소멸주의(민사집행법 제91조 제3항) 위반으로 감지되어 REPAIR 판정 및 교정 대상 등록 검증.
2. 선순위 근저당권이 존재할 때 경매 매각으로 임차권이 소멸하며 낙찰자에게 대항할 수 없고 배당요구를 통해 매각대금에서
   회수해야 한다고 올바르게 작성된 답변은 정상 통과(PASS) 검증.
3. 선순위 담보권이 없는 선순위 대항력 임차인의 경우 낙찰자에게 대항/인수를 주장하는 결론이 오탐(False Positive)으로 차단되지 않는지 검증.
"""

import pytest
from ai_legal_helper.agents.qa_checker import check_deterministic_qa


def test_stage3_subordinate_tenant_buyer_assumption_detected_as_error():
    """1. 선순위 근저당권 후순위 임차인이 낙찰자에게 청구 가능하다고 주장 시 오류 감지 검증."""
    question = (
        "선순위 근저당권(2021.03.10 설정)이 있는 상태에서 제가 2023.05.20에 전입신고와 확정일자를 받았습니다. "
        "경매가 진행되면 보증금 1억 5천만 원 중 일부를 못 받게 되면 어떻게 회수해야 하나요?"
    )
    case_context = "선순위 근저당권: 2021.03.10 신한은행 채권최고액 2억원. 임차인 전입일: 2023.05.20."
    
    # 잘못된 초안 (낙찰자에게 대항 가능하다고 잘못 서술)
    bad_draft = (
        "주택임대차보호법 제3조의5 단서에 따르면 보증금이 모두 변제되지 아니한 대항력 있는 임차권은 매각으로 소멸하지 않습니다. "
        "따라서 경매에서 배당받지 못한 미회수 보증금 5천만 원은 낙찰자에게 보증금 반환을 청구할 수 있습니다."
    )
    
    retrieved_sources = [
        {"source_id": "STATUTE:001248:current:제3조의5:hash1", "source_type": "STATUTE", "statute_name": "주택임대차보호법", "article": "제3조의5", "content": "임차권은 경매로 소멸한다. 다만 보증금 미변제 대항력 있는 임차권은 소멸하지 아니한다."},
        {"source_id": "STATUTE:009290:current:제91조:hash2", "source_type": "STATUTE", "statute_name": "민사집행법", "article": "제91조", "content": "저당권에 대항할 수 없는 임차권은 매각으로 소멸된다."},
    ]

    result = check_deterministic_qa(
        question=question,
        draft_answer=bad_draft,
        retrieved_sources=retrieved_sources,
        case_context=case_context,
    )

    assert result.status == "REPAIR", "선순위 근저당 존재 시 낙찰자 대항 결론은 REPAIR여야 한다."
    assert result.reason_code == "LEGAL_APPLICATION_ERROR"
    assert any("민사집행법 제91조 제3항" in rt.repair_reason for rt in result.repair_targets), "민사집행법 제91조 제3항 위반이 교정 사유에 명시되어야 함"


def test_stage3_subordinate_tenant_extinction_and_dividend_payout_pass():
    """2. 선순위 근저당권 후순위 임차인이 매각으로 소멸하고 배당요구로 회수해야 한다고 올바르게 작성된 경우 통과 검증."""
    question = (
        "선순위 근저당권(2021.03.10 설정)이 있는 상태에서 제가 2023.05.20에 전입신고와 확정일자를 받았습니다. "
        "경매가 진행되면 보증금 1억 5천만 원 중 일부를 못 받게 되면 어떻게 회수해야 하나요?"
    )
    case_context = "선순위 근저당권: 2021.03.10 신한은행 채권최고액 2억원. 임차인 전입일: 2023.05.20."

    # 올바른 초안 (경매 매각으로 임차권 소멸, 낙찰자에게 대항할 수 없음, 배당요구로 회수)
    good_draft = (
        "민사집행법 제91조 제3항에 따라 선순위 근저당권에 대항할 수 없는 후순위 임차권은 경매 매각으로 소멸합니다. "
        "따라서 임차인은 낙찰자에게 대항할 수 없으며 미회수 보증금의 인수를 청구할 수 없습니다. "
        "보증금을 회수하기 위해서는 배당요구 종기까지 법원에 권리신고 및 배당요구를 하여 매각대금에서 우선변제권(주택임대차보호법 제3조의2 제2항)에 따라 배당받아야 하며, "
        "미배당 잔액은 원래 임대인을 상대로 지급명령 등 집행권원을 확보하여 일반재산에 강제집행해야 합니다."
    )

    retrieved_sources = [
        {"source_id": "STATUTE:001248:current:제3조의2:hash1", "source_type": "STATUTE", "statute_name": "주택임대차보호법", "article": "제3조의2", "content": "우선변제권"},
        {"source_id": "STATUTE:001248:current:제3조의5:hash2", "source_type": "STATUTE", "statute_name": "주택임대차보호법", "article": "제3조의5", "content": "임차권은 경매로 소멸한다."},
        {"source_id": "STATUTE:009290:current:제91조:hash3", "source_type": "STATUTE", "statute_name": "민사집행법", "article": "제91조", "content": "저당권에 대항할 수 없는 임차권은 매각으로 소멸된다."},
        {"source_id": "STATUTE:009290:current:제88조:hash4", "source_type": "STATUTE", "statute_name": "민사집행법", "article": "제88조", "content": "배당요구"},
    ]

    result = check_deterministic_qa(
        question=question,
        draft_answer=good_draft,
        retrieved_sources=retrieved_sources,
        case_context=case_context,
    )

    # 결정론적 검사에서 legal_risk_passed는 True여야 함
    # (LLM 심층 검토 사유는 존재하더라도 REPAIR 차단은 발생하지 않음)
    assert not any("소멸주의" in rt.repair_reason for rt in result.repair_targets), "올바른 답변에는 소멸주의 위반 repair_target이 없어야 함"


def test_stage3_senior_tenant_without_mortgage_assumption_allowed():
    """3. 선순위 대항력 임차인의 경우 낙찰자 인수 설명이 오탐으로 차단되지 않는지 검증."""
    question = "선순위 담보권이 전혀 없는 상태에서 대항력을 갖추었는데 경매 시 보증금을 전액 돌려받을 수 있나요?"
    case_context = "선순위 권리 없음. 임차인 1순위 대항력 확보."

    draft = (
        "주택임대차보호법 제3조의5 단서에 따르면 선순위 대항력을 갖춘 임차인은 매각대금에서 전액 배당받지 못한 경우 "
        "잔여 보증금에 관하여 낙찰자에게 대항할 수 있으며, 낙찰자가 보증금을 인수해야 합니다."
    )

    retrieved_sources = [
        {"source_id": "STATUTE:001248:current:제3조의5:hash1", "source_type": "STATUTE", "statute_name": "주택임대차보호법", "article": "제3조의5", "content": "보증금 미변제 대항력 있는 임차권은 소멸하지 아니한다."},
    ]

    result = check_deterministic_qa(
        question=question,
        draft_answer=draft,
        retrieved_sources=retrieved_sources,
        case_context=case_context,
    )

    # 선순위 담보권이 없으므로 오탐 없이 통과
    assert not any("선순위 담보권 존재 시" in rt.repair_reason for rt in result.repair_targets), "선순위 임차인은 차단되지 않아야 함"
