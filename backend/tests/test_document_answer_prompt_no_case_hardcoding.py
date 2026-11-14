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


def test_prompt_removed_dangerous_temporal_and_termination_assumptions():
    """개정 법령의 소급 동일 적용 전제 및 단순 기일 도래 기반 계약종료 단정이 프롬프트에서 제거되었는지 검증한다."""
    prompt = DOCUMENT_ANSWER_SYSTEM
    # 위험 문장 1: 과거 체결·갱신 시점에도 동일한 취지로 적용된다는 위험한 전제 제거 검증
    assert "원칙적으로 동일한 취지로 적용됩니다" not in prompt
    # 위험 문장 2: 두 날짜 도래만으로 계약관계 종료 결론을 명쾌히 밝히라는 임의적 지시 제거 검증
    assert "두 날짜가 모두 도래하였다면 계약관계 종료" not in prompt

    # 5대 영역 핵심 원칙 반영 검증
    assert "5단계 법률 판단 절차 (Subsumption)" in prompt
    assert "실체적 요건 검토 없는 계약종료 단정 금지" in prompt
    assert "사건 발생 시점 이후 개정·시행된 조문을 부칙의 명시적 근거 없이 과거 사건이나 계약에 소급 적용하지 마세요" in prompt


def test_write_document_answer_injects_issue_tasks(monkeypatch):
    """write_document_answer 호출 시 issue_tasks가 LLM 입력 페이로드에 구조화되어 전달되는지 검증한다."""
    import json
    from ai_legal_helper.agents.document_answer import write_document_answer

    captured_messages = []

    class DummyResponse:
        content = json.dumps({"status": "READY", "missing_laws": [], "answer": "답변 내용입니다."})

    class DummyLLM:
        def invoke(self, messages):
            captured_messages.extend(messages)
            return DummyResponse()

    monkeypatch.setattr("ai_legal_helper.agents.document_answer.get_llm", lambda **kwargs: DummyLLM())

    mock_sources = [
        {
            "source_id": "01_계약서.txt",
            "filename": "01_계약서.txt",
            "source_type": "CASE_EVIDENCE",
            "review_status": "APPROVED",
            "content": "계약서 내용",
        }
    ]
    mock_issue_tasks = [
        {
            "issue_title": "차임 증액 청구 5% 상한 준수 여부",
            "legal_questions": ["임대인의 증액 요구가 주택임대차보호법상 5% 제한을 초과하는가?"],
            "required_statutes": ["주택임대차보호법 제7조", "주택임대차보호법 시행령 제8조"],
        }
    ]

    res = write_document_answer(
        question="임대인이 보증금을 올려달라는데 어떻게 되나요?",
        sources=mock_sources,
        issue_tasks=mock_issue_tasks,
    )

    assert res["draft_answer"] == "답변 내용입니다."
    assert len(captured_messages) == 2
    human_msg = captured_messages[1].content
    # HumanMessage의 JSON 페이로드 추출
    payload_json_str = human_msg.split("\n\n[전체 근거 원문]")[0]
    payload = json.loads(payload_json_str)

    assert "사건 분석 핵심 쟁점 계획(포섭 대상)" in payload
    injected_tasks = payload["사건 분석 핵심 쟁점 계획(포섭 대상)"]
    assert len(injected_tasks) == 1
    assert injected_tasks[0]["쟁점"] == "차임 증액 청구 5% 상한 준수 여부"
    assert "주택임대차보호법 제7조" in injected_tasks[0]["관련 법령"]


def test_document_verification_prompt_no_sc013_auction_hardcoding():
    """DOCUMENT_VERIFICATION_PROMPT에서 SC-013 전용 경매 결론 하드코딩이 제거되고 범용 포섭 절차로 대체되었는지 검증한다."""
    from ai_legal_helper.agents.document_verification_prompt import DOCUMENT_VERIFICATION_PROMPT

    prompt = DOCUMENT_VERIFICATION_PROMPT
    # 1. SC-013 특정 조문(제3조의5 단서) 및 결론 하드코딩 제거 검증
    assert "주택임대차보호법 제3조의5 단서 적용 한계 엄격 검증" not in prompt
    assert "보증금이 모두 변제되지 아니한 대항력 있는 임차권은 소멸하지 아니한다'는 단서 예외는, 애당초" not in prompt

    # 2. 범용 요건 포섭 및 시점 적용 원칙 반영 검증
    assert "[LEGAL_APPLICATION 주장의 4단계 포섭 검증 원칙]" in prompt
    assert "[법령 시행일자와 시점 적용 검증 원칙]" in prompt
    assert "사건 시점 이후 개정·시행된 조문을 부칙의 경과조치나 적용례 근거 없이 과거 사건에 소급 적용" in prompt


def test_finish_answer_blocks_fallback_when_fatal_legal_error_persists():
    """재작성 한도 도달 시 치명적인 미입증 법률 적용(LEGAL_APPLICATION)이 남아있으면 폴백 PASS 승인을 차단하고 WITHHELD 처리한다."""
    import hashlib
    from ai_legal_helper.workflows.document_consultation import finish_answer

    draft = "선순위 근저당권이 있어도 낙찰자에게 보증금을 전액 청구할 수 있습니다."
    draft_sha = hashlib.sha256(draft.encode("utf-8")).hexdigest()

    mock_sources = [
        {"source_id": "01_계약서.txt", "filename": "01_계약서.txt", "source_type": "CASE_EVIDENCE", "content": "계약 내용"}
    ]
    from ai_legal_helper.rag.grounding_context import format_grounding_sources
    _, manifest = format_grounding_sources(mock_sources)

    # 1건은 사실 지지(SUPPORTED), 1건은 치명적 법률 적용 오류(UNSUPPORTED)
    ver_result = {
        "status": "REVISE",
        "reason_code": "LEGAL_SOURCE_INSUFFICIENT",
        "claims": [
            {
                "claim": "2022년에 계약을 체결했습니다.",
                "claim_type": "CASE_FACT",
                "grounding_status": "SUPPORTED",
                "source_ids": ["01_계약서.txt"],
            },
            {
                "claim": "선순위 근저당권이 있어도 낙찰자에게 보증금을 전액 청구할 수 있습니다.",
                "claim_type": "LEGAL_APPLICATION",
                "grounding_status": "UNSUPPORTED",
                "source_ids": [],
            },
        ],
        "verified_answer_sha256": draft_sha,
        "source_manifest": manifest,
        "missing_legal_issues": ["경매 매각소멸주의"],
    }

    state = {
        "draft_answer": draft,
        "verification_result": ver_result,
        "case_evidence_sources": mock_sources,
        "legal_sources": [],
        "revision_count": 3,  # 재작성 한도 도달
    }

    out = finish_answer(state)

    # 치명적 법률 오류가 남아있으므로 PASS 폴백이 차단되고 WITHHELD로 확정되어야 함
    assert out["final_disposition"] == "WITHHELD"
    assert "질문에 대한 답변을 확정할 만큼 근거 확인을 마치지 못했습니다" in out["final_answer"]
