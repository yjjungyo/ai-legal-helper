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
    """재작성 한도 도달 시 치명적인 미입증 법률 적용(LEGAL_APPLICATION)이 남아있으면 폴백 PASS 승인을 차단하고 WITHHELD 처리한다.
    
    [Red-Green 실증]:
    출처 스냅샷(source_manifest)이 온전히 일치하여 snapshot_valid=True인 정상 조건에서,
    has_fatal_legal_error 검사 로직에 의해 정밀하게 WITHHELD로 차단되는지 검증한다.
    """
    import hashlib
    from ai_legal_helper.workflows.document_consultation import finish_answer
    from ai_legal_helper.rag.grounding_context import format_grounding_sources

    draft = "2022년에 계약을 체결했습니다. 선순위 근저당권이 있어도 낙찰자에게 보증금을 전액 청구할 수 있습니다."
    draft_sha = hashlib.sha256(draft.encode("utf-8")).hexdigest()

    mock_doc = {
        "source_id": "01_계약서.txt",
        "document_name": "01_계약서.txt",
        "filename": "01_계약서.txt",
        "review_status": "APPROVED",
        "content": "임대차계약서: 보증금 300,000,000원.",
    }
    # document_sources(state) 규약에 맞춰 정상적인 출처 목록 산출
    mock_sources = [
        {
            "source_id": "01_계약서.txt",
            "document_name": "01_계약서.txt",
            "source_type": "CASE_EVIDENCE",
            "retrieval_method": "CASE_DOCUMENT_SPANS",
            "content": "임대차계약서: 보증금 300,000,000원.",
        }
    ]
    _, manifest = format_grounding_sources(mock_sources)

    # 1. 법률 오류가 없는 정상 상태: 폴백을 통해 PASS 및 CAUTIONARY 승인 가능 실증 (Green)
    clean_ver_result = {
        "status": "REVISE",
        "reason_code": "ANSWER_REVISION_REQUIRED",
        "claims": [
            {
                "claim": "2022년에 계약을 체결했습니다.",
                "claim_type": "CASE_FACT",
                "grounding_status": "SUPPORTED",
                "source_ids": ["01_계약서.txt"],
            }
        ],
        "verified_answer_sha256": draft_sha,
        "source_manifest": manifest,
        "missing_legal_issues": [],
    }
    clean_state = {
        "draft_answer": draft,
        "verification_result": clean_ver_result,
        "case_evidence_briefing": {"source_documents": [mock_doc]},
        "retrieved_sources": [],
        "revision_count": 3,
    }
    from unittest.mock import patch
    with patch("ai_legal_helper.workflows.document_consultation.validate_document_snapshot"):
        clean_out = finish_answer(clean_state)
    assert clean_out["final_disposition"] == "CAUTIONARY", "치명적 법률 오류가 없으면 정상 폴백 승인되어야 함"

    # 2. 치명적 법률 오류(UNSUPPORTED LEGAL_APPLICATION)가 포함된 상태: 폴백 차단 및 WITHHELD (Red)
    fatal_ver_result = {
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
    fatal_state = {
        "draft_answer": draft,
        "verification_result": fatal_ver_result,
        "case_evidence_briefing": {"source_documents": [mock_doc]},
        "retrieved_sources": [],
        "revision_count": 3,
    }
    with patch("ai_legal_helper.workflows.document_consultation.validate_document_snapshot"):
        fatal_out = finish_answer(fatal_state)
    assert fatal_out["final_disposition"] == "WITHHELD", "UNSUPPORTED 법률 오류 잔존 시 WITHHELD로 엄격 차단되어야 함"


def test_finish_answer_blocks_fallback_when_core_legal_claim_uncertain():
    """핵심 법률 주장(LEGAL_APPLICATION)이 UNCERTAIN인 경우에도 폴백 PASS 승인을 차단하고 WITHHELD 처리한다."""
    import hashlib
    from ai_legal_helper.workflows.document_consultation import finish_answer
    from ai_legal_helper.rag.grounding_context import format_grounding_sources

    draft = "2022년에 계약을 체결했습니다. 낙찰자에게 대항할 수 있는지는 불확실합니다."
    draft_sha = hashlib.sha256(draft.encode("utf-8")).hexdigest()

    mock_doc = {
        "source_id": "01_계약서.txt",
        "document_name": "01_계약서.txt",
        "review_status": "APPROVED",
        "content": "임대차계약서 내용",
    }
    mock_sources = [
        {"source_id": "01_계약서.txt", "document_name": "01_계약서.txt", "source_type": "CASE_EVIDENCE", "retrieval_method": "CASE_DOCUMENT_SPANS", "content": "임대차계약서 내용"}
    ]
    _, manifest = format_grounding_sources(mock_sources)

    ver_result = {
        "status": "REVISE",
        "reason_code": "LEGAL_SOURCE_INSUFFICIENT",
        "claims": [
            {"claim": "2022년에 계약을 체결했습니다.", "claim_type": "CASE_FACT", "grounding_status": "SUPPORTED", "source_ids": ["01_계약서.txt"]},
            {"claim": "낙찰자에게 대항할 수 있는지는 불확실합니다.", "claim_type": "LEGAL_APPLICATION", "grounding_status": "UNCERTAIN", "source_ids": ["01_계약서.txt"]},
        ],
        "verified_answer_sha256": draft_sha,
        "source_manifest": manifest,
        "missing_legal_issues": ["대항력 소멸 여부 확인 필요"],
    }
    state = {
        "draft_answer": draft,
        "verification_result": ver_result,
        "case_evidence_briefing": {"source_documents": [mock_doc]},
        "retrieved_sources": [],
        "revision_count": 3,
    }
    from unittest.mock import patch
    with patch("ai_legal_helper.workflows.document_consultation.validate_document_snapshot"):
        out = finish_answer(state)
    assert out["final_disposition"] == "WITHHELD", "UNCERTAIN 법률 판단 잔존 시 폴백 PASS 차단 및 WITHHELD 확정"


def test_verification_demotes_llm_pass_when_qa_check_fails(monkeypatch):
    """LLM이 최초에 PASS를 반환했더라도, 1차 경량 QA에서 법률 위험(legal_risk_passed=False)이 감지되면 REVISE로 강등한다."""
    import json
    from ai_legal_helper.agents.verification import run_verification

    class DummyResponse:
        content = json.dumps({
            "status": "PASS",
            "reason_code": "NONE",
            "claims": [
                {
                    "claim": "선순위 근저당권이 있어도 낙찰자에게 보증금 반환을 청구할 수 있습니다.",
                    "claim_type": "LEGAL_APPLICATION",
                    "fact_status": "VERIFIED_FACT",
                    "grounding_status": "SUPPORTED",
                    "source_ids": ["STATUTE:001248:current:제3조:hash1"],
                    "reason": "대항력이 인정됩니다.",
                    "inference_basis": "",
                    "inference_limit": "",
                }
            ],
            "question_coverage": [{"question": "질문", "answered": True, "reason": "답변됨"}],
            "consistency_checks": {
                "opening_conclusion": {"passed": True, "reason": "일치", "source_ids": ["STATUTE:001248:current:제3조:hash1"]},
                "timeline": {"passed": True, "reason": "일치", "source_ids": []},
                "expressed_intent": {"passed": True, "reason": "일치", "source_ids": []},
                "provenance": {"passed": True, "reason": "일치", "source_ids": []},
            },
            "missing_issues": [],
            "missing_legal_issues": [],
            "candidate_laws": [],
            "contradictions": [],
            "revision_instructions": [],
            "warnings": [],
            "legal_search_requests": [],
            "preserved_points": [],
            "recommended_action": "FINALIZE",
            "explanation": "통과 설명",
        })

    class DummyLLM:
        def invoke(self, prompt):
            return DummyResponse()

    monkeypatch.setattr("ai_legal_helper.llm.gateway.get_llm", lambda **kwargs: DummyLLM())

    retrieved_sources = [
        {"source_id": "STATUTE:001248:current:제3조:hash1", "source_type": "STATUTE", "statute_name": "주택임대차보호법", "article": "제3조", "content": "대항력 조문"}
    ]
    question = "선순위 근저당권(2021.3 설정)이 있는데 낙찰자에게 보증금을 받을 수 있나요?"
    bad_draft = "선순위 근저당권이 있어도 낙찰자에게 보증금 반환을 청구할 수 있습니다. [주택임대차보호법 제3조]"

    result = run_verification(
        question=question,
        draft_answer=bad_draft,
        retrieved_sources=retrieved_sources,
        case_context="선순위 근저당권 설정 후 임차인 전입",
        require_question_coverage=True,
    )

    # LLM이 status=PASS를 냈더라도 경량 QA에서 소멸주의 위반(legal_risk_passed=False)이 잡혀 REVISE로 강등되어야 함
    assert result["status"] == "REVISE"
    assert result["reason_code"] == "LEGAL_SOURCE_INSUFFICIENT"
    assert any("소멸" in inst for inst in result["revision_instructions"])


def test_grounding_context_preserves_deep_evidence_beyond_400_chars():
    """등기부 을구 등 400자 이후에 위치한 핵심 권리 증거가 prune_sources_for_verification에서 유실되지 않고 보존되는지 검증한다."""
    from ai_legal_helper.rag.grounding_context import prune_sources_for_verification

    # 1,000자 길이의 등기부등본 (을구 근저당권 설정 내역이 600자 위치에 존재)
    padding = "갑구 소유권 이전 및 주소 변경 내역... " * 20  # 약 500자
    mortgage_clause = "을구 순위번호 1번 근저당권설정 2021년 3월 10일 채권최고액 200,000,000원 근저당권자 신한은행."
    tail = " 기타 등기 사항... " * 20
    full_content = padding + mortgage_clause + tail

    sources = [
        {
            "source_id": "E02_등기사항전부증명서.txt",
            "filename": "E02_등기사항전부증명서.txt",
            "source_type": "CASE_EVIDENCE",
            "content": full_content,
        }
    ]

    # 초안에는 등기사항전부증명서가 직접 인용되지 않은 상태
    draft = "임대차계약서를 검토한 결과 보증금 반환 청구가 가능합니다."

    pruned = prune_sources_for_verification(sources, draft_answer=draft, max_unreferenced_snippet=150)

    assert len(pruned) == 1
    preserved_content = pruned[0]["content"]
    # 400자 이후에 위치한 을구 근저당권 설정 내역이 1,500자 보존 한도 내에 온전히 포함되어야 함
    assert "을구 순위번호 1번 근저당권설정" in preserved_content
    assert "채권최고액 200,000,000원" in preserved_content


def test_write_document_answer_preserves_third_question_and_key_statutes(monkeypatch):
    """issue_tasks의 3번째 핵심 질문(매수인 인수·소멸 여부)과 필수 조문(민사집행법 제91조)이 슬라이싱으로 잘리지 않고 온전히 주입되는지 검증한다."""
    import json
    from ai_legal_helper.agents.document_answer import write_document_answer

    captured_messages = []

    class DummyResponse:
        content = json.dumps({"status": "READY", "missing_laws": [], "answer": "완성 답변입니다."})

    class DummyLLM:
        def invoke(self, messages):
            captured_messages.extend(messages)
            return DummyResponse()

    monkeypatch.setattr("ai_legal_helper.agents.document_answer.get_llm", lambda **kwargs: DummyLLM())

    mock_sources = [
        {"source_id": "01_계약서.txt", "filename": "01_계약서.txt", "source_type": "CASE_EVIDENCE", "content": "계약서 본문"}
    ]
    # 3개 이상의 질문과 4개 이상의 법령을 포함한 쟁점 태스크
    mock_issue_tasks = [
        {
            "issue_title": "경매 시 대항력 및 배당 순위",
            "legal_questions": [
                "1. 임차인의 대항요건 구비 시점은 언제인가?",
                "2. 우선변제권 배당 순위는 어떻게 되는가?",
                "3. 경매 매수인(낙찰자)에게 보증금 인수를 청구할 수 있는가?",  # 3번째 핵심 질문
            ],
            "required_statutes": [
                "주택임대차보호법 제3조",
                "주택임대차보호법 제3조의2",
                "주택임대차보호법 제3조의5",
                "민사집행법 제91조",  # 4번째 핵심 법령
            ],
        }
    ]

    res = write_document_answer(
        question="경매 시 낙찰자에게 보증금을 받을 수 있나요?",
        sources=mock_sources,
        issue_tasks=mock_issue_tasks,
    )

    assert res["draft_answer"] == "완성 답변입니다."
    human_msg = captured_messages[1].content
    payload = json.loads(human_msg.split("\n\n[전체 근거 원문]")[0])
    injected_task = payload["사건 분석 핵심 쟁점 계획(포섭 대상)"][0]

    # 3번째 핵심 질문과 4번째 법령(민사집행법 제91조)이 잘리지 않고 보존되었는지 검증
    assert len(injected_task["핵심 법률 질문"]) == 3
    assert "3. 경매 매수인(낙찰자)에게 보증금 인수를 청구할 수 있는가?" in injected_task["핵심 법률 질문"]
    assert "민사집행법 제91조" in injected_task["관련 법령"]
