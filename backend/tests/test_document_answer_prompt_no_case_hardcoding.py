# -*- coding: utf-8 -*-
"""공통 문서 작성 프롬프트가 특정 사건 결론을 강제하지 않는지 검사."""
from ai_legal_helper.agents.document_answer import DOCUMENT_ANSWER_SYSTEM


def test_shared_prompt_has_no_fixed_lease_dates_or_priority_conclusion():
    prompt = DOCUMENT_ANSWER_SYSTEM
    assert "2022년 갖춘 대항력" not in prompt
    assert "2026년 후순위 가압류" not in prompt
    assert "보증금 전액을 우선 배당받으며" not in prompt
    assert "권리 순위와 실제 배당·회수 가능성은 별도 쟁점" in prompt


def test_shared_prompt_requires_evidence_and_law():
    prompt = DOCUMENT_ANSWER_SYSTEM
    assert "실제 법령/판례 본문" in prompt
    assert "사건별로 확인된 주택 인도" in prompt
