"""문서 상담에서 원문 전달, 질문 충족 검증, 최종 답변 보존을 확인한다.

LLM은 통제된 응답으로 대체하여 누락 법령·잘못된 사실·출력 덮어쓰기 반례를 검증한다.
실제 답변 품질 평가는 별도의 실제 모델 재현 기록으로 구분한다.
"""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ai_legal_helper.agents.verification import run_verification
from ai_legal_helper.rag.grounding_context import format_grounding_sources
from ai_legal_helper.rag.retrieval import RetrievalResult, RetrievalStatus
from ai_legal_helper.workflows import document_consultation as consultation
from ai_legal_helper.workflows import legal_workflow as workflow


@pytest.fixture
def document_state():
    """오염된 과거 답변·Fact와 승인 문서 원문이 공존하는 격리 상태를 만든다."""
    question = "등록된 계약서와 입금 자료로 당사자와 지급 여부를 설명해 주세요."
    return {"answer_mode": consultation.DOCUMENT_MODE, "question": question,
            "messages": [HumanMessage(content="계약 내용을 봐주세요."),
                         AIMessage(content="보증금 일부 반환 완료라는 잘못된 과거 답변"),
                         HumanMessage(content=question)],
            "case_context": "이미 계약이 종료되었다는 오염된 요약",
            "case_evidence_briefing": {"case_id": "isolated-case", "source_documents": [
                {"evidence_id": "doc-1", "document_name": "E01_계약서.txt", "review_status": "APPROVED",
                 "content": "임대인 갑, 임차인 을. 계약 종료 시 보증금 반환.", "sha256": "original", "extraction_version": "v1"},
                {"evidence_id": "doc-2", "document_name": "E02_입금.txt", "review_status": "APPROVED",
                 "content": "임차인 을이 임대인 갑에게 보증금 3억원 지급.", "sha256": "transfer", "extraction_version": "v1"},
                {"evidence_id": "other-pending", "document_name": "검토중.txt", "review_status": "REVIEW_REQUIRED",
                 "content": "검토하지 않은 자료의 본문"},
            ]}, "retrieved_sources": [], "revision_count": 0, "categories": []}


def verification_reply(**overrides):
    """질문별 충족 내역을 포함한 검증 응답의 기준값을 만든다."""
    return {"status": "PASS", "reason_code": "NONE", "claims": [
        {"claim": "임대인 갑과 임차인 을이 계약했다.", "claim_type": "CASE_FACT",
         "fact_status": "VERIFIED_FACT", "source_ids": ["E01_계약서.txt"], "grounding_status": "SUPPORTED"},
    ], "question_coverage": [{"question": "당사자와 지급 여부", "answered": True, "reason": "답변함"}],
        "consistency_checks": {key: {"passed": True, "reason": "대조 완료", "source_ids": ["E01_계약서.txt"]}
                               for key in ("opening_conclusion", "timeline", "expressed_intent", "provenance")},
        **overrides}


def test_official_source_after_six_and_long_body_reaches_verifier():
    """앞 여섯 개 뒤의 법령 및 400자 이후의 핵심 조문이 검증 입력에 남는다."""
    sources = [{"source_id": f"S{i}", "content": "보조 자료"} for i in range(6)]
    sources.append({"source_id": "OFFICIAL:7", "content": "가" * 800 + "누락되어서는 안 되는 핵심 원문"})
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(verification_reply(), ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification("질문", "답변", sources)
    prompt = llm.invoke.call_args.args[0]
    assert "누락되어서는 안 되는 핵심 원문" in prompt
    assert "OFFICIAL:7" in prompt
    assert result["source_manifest"]["source_count"] == 7


@pytest.mark.parametrize("coverage", [[], [{"question": "지급 여부", "answered": False}],
                                       [{"question": "지급 여부", "answered": "true"}]])
def test_question_omission_cannot_pass(document_state, coverage):
    """출처가 맞아도 질문 미응답 또는 불리언이 아닌 응답으로 PASS가 되지 않는다."""
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(verification_reply(question_coverage=coverage), ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification(document_state["question"], "답변", consultation.document_sources(document_state),
                                  require_question_coverage=True)
    assert result["status"] == "REVISE"


@pytest.mark.parametrize("checks", [{}, {"timeline": {"passed": False, "reason": "나중 통지를 무시함"}},
                                  {key: {"passed": True, "reason": ""}
                                   for key in ("timeline", "expressed_intent", "provenance")}])
def test_missing_or_failed_consistency_check_cannot_pass(document_state, checks):
    """질문 충족 판정이 있어도 시간 순서·의사표시 검사를 빠뜨리거나 실패하면 통과하지 않는다."""
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(verification_reply(consistency_checks=checks), ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification("현재 계약 상태는?", "계약은 유지됩니다.",
                                  consultation.document_sources(document_state), require_question_coverage=True)
    assert result["status"] == "REVISE"


def test_unsupported_case_fact_cannot_pass(document_state):
    """법률 주장 외에 사건 사실 오류가 남아도 검증 통과를 차단한다."""
    reply = verification_reply()
    reply["claims"][0]["grounding_status"] = "UNSUPPORTED"
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(reply, ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification("질문", "일부 보증금을 돌려받았다.", consultation.document_sources(document_state),
                                  require_question_coverage=True)
    assert result["status"] == "REVISE"


def test_case_document_cannot_be_sole_ground_for_legal_effect(document_state):
    """검증 LLM이 사건 문서만으로 법률 효과를 지지한다고 해도 PASS를 차단한다."""
    reply = verification_reply()
    reply["claims"][0].update(claim_type="LEGAL_APPLICATION", claim="법률상 계약 종료가 확정되었다.")
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(reply, ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification("계약 상태는?", "계약이 종료되었습니다.", consultation.document_sources(document_state),
                                  require_question_coverage=True)
    assert result["status"] == "REVISE"
    assert result["claims"][0]["grounding_status"] == "UNSUPPORTED"


def test_verifier_cannot_turn_categorical_sentence_into_conditional_quote(document_state):
    """검증기가 답변 단정을 조건부로 바꿔 인용한 뒤 통과시키는 것을 막는다."""
    reply = verification_reply()
    reply["claims"][0]["claim"] = "계약이 갱신되었다면 계속 중일 수 있습니다."
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(reply, ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification("현재 상태는?", "계약은 계속 중입니다.",
                                  consultation.document_sources(document_state), require_question_coverage=True)
    assert result["status"] == "REVISE"
    assert "실제 답변" in result["claims"][0]["reason"]


def test_document_writer_uses_originals_without_prior_ai_or_fact_summary(document_state):
    """원문을 전송하되 기존 잘못된 AI 답변과 파생 요약이 새 답변의 근거가 되지 않는다."""
    llm = MagicMock()
    llm.invoke.return_value.content = "임차인 을이 임대인 갑에게 지급한 내역입니다. [E02_입금.txt]"
    with patch("ai_legal_helper.agents.document_answer.get_llm", return_value=llm):
        written = workflow.synthesize_node(document_state)
    prompt = llm.invoke.call_args.args[0][1].content
    assert "임차인 을이 임대인 갑에게 보증금 3억원 지급" in prompt
    assert "잘못된 과거 답변" not in prompt
    assert "오염된 요약" not in prompt
    assert "검토하지 않은 자료의 본문" not in prompt
    assert written["answer_source_manifest"]["complete"] is True


def test_document_mode_retrieves_without_specialist_answer(document_state):
    """검색과 답변 작성을 분리하고 분야 분류가 비어 있어도 자료 검색을 시도한다."""
    with patch("ai_legal_helper.rag.retrieval.retrieve_with_status", return_value=RetrievalResult(
        status=RetrievalStatus.NO_MATCH,
    )) as retrieve, patch.object(workflow, "run_specialist_agent") as specialist:
        result = asyncio.run(workflow.run_agents_node(document_state))
    retrieve.assert_called_once()
    specialist.assert_not_called()
    assert result["agent_results"] == {}


def test_document_question_is_not_rewritten_or_action_template(document_state):
    """문서 질문은 과거 반환 결론을 주입하는 재해석·후속 행동 템플릿을 거치지 않는다."""
    updated = workflow.intent_analysis_node(document_state)
    assert updated["resolved_query"] == document_state["question"]
    assert workflow.intent_condition({**document_state, **updated}) == "route"
    assert workflow.route_condition(document_state) == "plan"


def test_pure_greeting_is_not_withheld_but_mixed_question_is_analyzed(document_state):
    """순수 인사만 기존 인사 경로로 보내고 인사 뒤의 법률 질문을 놓치지 않는다."""
    greeting = {**document_state, "question": "감사합니다."}
    mixed = {**document_state, "question": "감사합니다. 그런데 계약은 끝났나요?"}
    assert workflow.intent_condition({**greeting, **workflow.intent_analysis_node(greeting)}) == "general_conversation"
    assert workflow.intent_condition({**mixed, **workflow.intent_analysis_node(mixed)}) == "route"


def test_verified_answer_is_preserved_and_modified_answer_is_withheld(document_state):
    """최종 단계가 검증한 답변을 그대로 반환하며 검증 후 바뀐 문장은 보류한다."""
    draft = "임대인은 갑, 임차인은 을입니다. [E01_계약서.txt]\n\n최초 지급과 반환은 구분해야 합니다."
    _, manifest = format_grounding_sources(consultation.document_sources(document_state))
    verified = {**verification_reply(), "verified_answer_sha256": hashlib.sha256(draft.encode()).hexdigest(),
                "source_manifest": manifest}
    state = {**document_state, "draft_answer": draft, "verification_result": verified}
    with patch.object(consultation, "validate_document_snapshot"):
        final = workflow.finalize_node(state)
        changed = workflow.finalize_node({**state, "draft_answer": draft + " 이미 종료되었습니다."})
    assert final["final_answer"] == draft
    assert final["sources"][0]["evidence_id"] == "doc-1"
    assert changed["final_disposition"] == "WITHHELD"
    assert "이미 종료되었습니다" not in changed["final_answer"]


def test_missing_article_search_is_not_skipped_by_same_law_name(document_state):
    """같은 법의 일부 조문이 있어도 누락 조문 요청은 공식 검색으로 연결한다."""
    state = {**document_state, "retrieved_sources": [{"statute_name": "주택임대차보호법", "article": "제2조"}],
             "verification_result": {"status": "REVISE", "reason_code": "LEGAL_SOURCE_INSUFFICIENT",
                                     "candidate_laws": ["주택임대차보호법"]}}
    assert workflow.verification_condition(state) == "statute_search_approval"
    assert workflow.verification_condition({**state, "hilt_executed": True}) == "revise"
    assert workflow.verification_condition({**state, "hilt_executed": True, "revision_count": 2}) == "revise"
    assert workflow.verification_condition({**state, "hilt_executed": True, "revision_count": 3}) == "insufficient"


def test_context_limit_fails_without_silent_omission():
    """원문 예산 초과와 동일 ID의 다른 본문을 조용히 잘라 통과시키지 않는다."""
    with pytest.raises(ValueError, match="GROUNDING_CONTEXT_LIMIT_EXCEEDED"):
        format_grounding_sources([{"source_id": "S", "content": "가" * 100}], max_chars=50)
    with pytest.raises(ValueError, match="SOURCE_ID_CONTENT_CONFLICT"):
        format_grounding_sources([{"source_id": "S", "content": "원문A"}, {"source_id": "S", "content": "원문B"}])


def test_approved_document_changed_during_answer_is_rejected(document_state):
    """작성 이후 문서의 승인 철회나 추출 버전 변경을 검출한다."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [SimpleNamespace(
        id="doc-1", status="APPROVED", sha256="original", extraction_version="v2",
        original_filename="E01_계약서.txt", extracted_at=None,
    )]
    session = MagicMock()
    session.__enter__.return_value = db
    with patch("ai_legal_helper.database.session.SessionLocal", return_value=session):
        with pytest.raises(ValueError, match="CASE_DOCUMENT_SNAPSHOT_CHANGED"):
            consultation.validate_document_snapshot(document_state)


def test_writer_verifier_manifest_match_and_new_source_is_rejected(document_state):
    """작성·검증 원문을 같은 해시로 확인하고 작성 후 바뀐 출처를 차단한다."""
    llm = MagicMock()
    llm.invoke.side_effect = [SimpleNamespace(content="임대인 갑과 임차인 을이 계약했다. [E01_계약서.txt]"),
                              SimpleNamespace(content=json.dumps(verification_reply(), ensure_ascii=False))]
    with patch("ai_legal_helper.agents.document_answer.get_llm", return_value=llm), \
            patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm), \
            patch.object(consultation, "validate_document_snapshot"):
        state = {**document_state, **workflow.synthesize_node(document_state)}
        result = workflow.verification_node(state)
        changed = workflow.verification_node({**state, "retrieved_sources": state["retrieved_sources"] + [
            {"source_id": "NEW", "content": "작성 이후 추가된 근거"},
        ]})
    assert result["verification_result"]["status"] == "PASS"
    assert result["verification_result"]["source_manifest"] == state["answer_source_manifest"]
    assert changed["verification_result"]["reason_code"] == "VERIFICATION_ERROR"
    assert llm.invoke.call_count == 2


def test_workflow_does_not_mutate_verifier_output_while_trace_serializes(document_state):
    """비동기 추적에 전달된 검증 반환 객체에 후속 필드를 추가하지 않는다."""
    original = verification_reply()
    _, manifest = format_grounding_sources(consultation.document_sources(document_state))
    state = {**document_state, "draft_answer": "임대인은 갑입니다.", "answer_source_manifest": manifest}
    with patch.object(consultation, "validate_document_snapshot"), \
            patch("ai_legal_helper.agents.verification.run_verification", return_value=original):
        result = consultation.verify_answer(state)
    assert "source_manifest" not in original
    assert "verified_answer_sha256" not in original
    assert result["verification_result"]["verified_answer_sha256"]


def test_real_graph_document_mode_preserves_answer_despite_unclear_routing(document_state):
    """실제 그래프 연결에서도 분류 미확정이 원문 답변을 막거나 정형 문구로 덮지 않는다."""
    from langgraph.checkpoint.memory import MemorySaver
    from ai_legal_helper.agents.router import RouterDecision, RouterStatus

    def initialize(_state):
        """외부 DB를 대신해 격리 문서 상태를 그래프에 주입한다."""
        return document_state

    answer = "임대인 갑과 임차인 을이 계약했다. [E01_계약서.txt]"
    llm = MagicMock()
    llm.invoke.side_effect = [SimpleNamespace(content=answer),
                              SimpleNamespace(content=json.dumps(verification_reply(), ensure_ascii=False))]
    with patch.object(workflow, "supervisor_initialize_node", initialize), \
            patch("ai_legal_helper.agents.router.route_categories_detailed", return_value=RouterDecision(
                status=RouterStatus.NEEDS_CLARIFICATION)), \
            patch("ai_legal_helper.rag.retrieval.retrieve_with_status", return_value=RetrievalResult(
                status=RetrievalStatus.NO_MATCH)), \
            patch("ai_legal_helper.agents.document_answer.get_llm", return_value=llm), \
            patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm), \
            patch.object(consultation, "validate_document_snapshot"), \
            patch.object(workflow, "synthesize") as old_writer:
        graph = workflow.build_legal_graph(checkpointer=MemorySaver())
        result = asyncio.run(graph.ainvoke({"messages": [HumanMessage(content=document_state["question"])]},
                                          {"configurable": {"thread_id": "document-flow-isolated"}}))
    old_writer.assert_not_called()
    assert result["final_answer"] == answer
    assert result["verification_result"]["status"] == "PASS"
    assert result["final_disposition"] == "DELIVERED"


def test_full_filename_source_ids_and_detailed_statute_metadata(document_state):
    """사건 문서는 별칭 없이 전체 파일명을 source_id로 사용하고, RAG·OpenLaw 법조문은 상세 메타데이터를 보존한다."""
    from ai_legal_helper.rag.source_schema import build_source_from_chroma_doc

    doc_sources = consultation.document_sources(document_state)
    assert [s["source_id"] for s in doc_sources] == ["E01_계약서.txt", "E02_입금.txt", "검토중.txt"]
    assert all("evidence_label" not in s for s in doc_sources)

    chroma_doc = SimpleNamespace(
        page_content="[민법] 제639조(묵시적 갱신) ① 임대차기간이 만료한 후 임차인이 임차물의 사용, 수익을 계속하는 경우...",
        metadata={
            "source_id": "민법_제639조_c1",
            "chunk_id": "민법_제639조_c1",
            "file_name": "민법(법률)(제20432호)(20250131).pdf",
            "law_name": "민법",
            "article": "제639조",
            "article_title": "묵시적 갱신",
            "paragraph_no": "①",
            "part": "제3편 채권",
            "chapter": "제2장 계약",
            "section": "제7절 임대차",
            "page": "52",
            "effective_date": "2025-01-31",
        },
    )
    rag_src = build_source_from_chroma_doc(chroma_doc, category="civil")
    assert rag_src["source_id"] == "민법 제639조(묵시적 갱신) ① [민법(법률)(제20432호)(20250131).pdf, p.52]"
    assert rag_src["article_title"] == "묵시적 갱신"
    assert rag_src["promulgation_number"] == "제20432호"
    assert rag_src["part"] == "제3편 채권"
    assert rag_src["filename"] == "민법(법률)(제20432호)(20250131).pdf"


def test_case_risk_inference_not_downgraded_and_policy_change_preserves_model_reason(document_state):
    """사건 증거에 기반한 회수 위험 추론은 CASE_INFERENCE로 인정하고, 법적 단정 격하 시 원판정을 보존한다."""
    risk_sentence = (
        "이번 가압류로 보증금 반환채권이 바로 사라지는 것은 아니지만, "
        "실제 회수 위험은 기존보다 커졌다고 재평가하는 것이 맞습니다."
    )
    legal_sentence = "법률상 계약 종료가 확정되었다."
    draft = f"{risk_sentence} [E01_계약서.txt]\n\n{legal_sentence} [E01_계약서.txt]"
    reply = verification_reply(
        status="REVISE",
        reason_code="ANSWER_REVISION_REQUIRED",
        claims=[
            {
                "claim": risk_sentence,
                "claim_type": "LEGAL_APPLICATION",
                "fact_status": "INFERENCE",
                "source_ids": ["E01_계약서.txt"],
                "grounding_status": "SUPPORTED",
                "reason": "사건 문서상 가압류·시세 정황을 종합한 타당한 위험 평가다.",
            },
            {
                "claim": legal_sentence,
                "claim_type": "LEGAL_APPLICATION",
                "fact_status": "VERIFIED_FACT",
                "source_ids": ["E01_계약서.txt"],
                "grounding_status": "SUPPORTED",
                "reason": "모델이 잘못 통과시킨 법률 효과 단정",
            },
        ],
    )
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(reply, ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        result = run_verification(
            document_state["question"],
            draft,
            consultation.document_sources(document_state),
            require_question_coverage=True,
        )
    assert result["claims"][0]["claim_type"] == "CASE_INFERENCE"
    assert result["claims"][0]["grounding_status"] == "SUPPORTED"
    assert result["claims"][1]["grounding_status"] == "UNSUPPORTED"
    assert result["claims"][1]["model_grounding_status"] == "SUPPORTED"
    assert result["claims"][1]["model_reason"] == "모델이 잘못 통과시킨 법률 효과 단정"
    assert result["status"] == "REVISE"


def test_discovery_date_vs_registration_date_distinction_and_same_role_conflict(document_state):
    """질문상 발견일과 문서상 등기 접수일 차이는 허용하되, 동일 등기 접수일 오기재 반례는 차단한다."""
    state = {
        **document_state,
        "question": "등기부에서 2026년 8월 12일 은행 가압류 7,200만 원을 발견했습니다. 어떤 변화가 생겼나요?",
        "case_evidence_briefing": {
            "case_id": "isolated-case",
            "source_documents": [
                {
                    "evidence_id": "doc-9",
                    "document_name": "E09_등기부_권리변동_요약_202610.txt",
                    "review_status": "APPROVED",
                    "content": "등기 접수일: 2026-07-18\n열람 기준일: 2026-10-02\n청구금액: 72,000,000원",
                    "sha256": "e09",
                    "extraction_version": "v1",
                }
            ],
        },
    }
    sources = consultation.document_sources(state)
    valid_draft = "등기 접수일 2026년 7월 18일 은행 가압류 7,200만 원이 확인됩니다. [E09_등기부_권리변동_요약_202610.txt]"
    false_positive_reply = verification_reply(
        status="REVISE",
        reason_code="ANSWER_REVISION_REQUIRED",
        claims=[
            {
                "claim": "등기 접수일 2026년 7월 18일 은행 가압류 7,200만 원이 확인됩니다.",
                "claim_type": "CASE_FACT",
                "fact_status": "VERIFIED_FACT",
                "source_ids": ["E09_등기부_권리변동_요약_202610.txt"],
                "grounding_status": "SUPPORTED",
                "reason": "E09와 일치한다.",
            }
        ],
        consistency_checks={
            "opening_conclusion": {"passed": True, "reason": "통과", "source_ids": ["E09_등기부_권리변동_요약_202610.txt"]},
            "timeline": {
                "passed": False,
                "reason": "사건 경과를 시간순으로 반영했다. 다만 질문은 2026년 8월 12일 발견이라 했는데 E09는 등기 접수일 2026-07-18만 제시한다.",
                "source_ids": ["E09_등기부_권리변동_요약_202610.txt"],
            },
            "expressed_intent": {"passed": True, "reason": "통과", "source_ids": ["E09_등기부_권리변동_요약_202610.txt"]},
            "provenance": {"passed": True, "reason": "통과", "source_ids": ["E09_등기부_권리변동_요약_202610.txt"]},
        },
        missing_legal_issues=["주택임대차보호법 제8조 소액임차인 최우선변제 대통령령 기준"],
    )
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(false_positive_reply, ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        normal_res = run_verification(state["question"], valid_draft, sources, require_question_coverage=True)
    assert normal_res["consistency_checks"]["timeline"]["passed"] is True
    assert normal_res["consistency_checks"]["timeline"]["model_passed"] is False
    assert normal_res["missing_legal_issues"] == []
    assert normal_res["status"] == "PASS"
    assert any("발견일" in p for p in normal_res["preserved_points"])

    # 반례: 동일 날짜 역할(등기 접수일)을 문서(2026-07-18)와 다르게 2026-08-12로 주장한 경우
    conflict_draft = "등기 접수일 2026년 8월 12일 은행 가압류 7,200만 원이 확인됩니다. [E09_등기부_권리변동_요약_202610.txt]"
    conflict_reply = verification_reply(
        claims=[
            {
                "claim": "등기 접수일 2026년 8월 12일 은행 가압류 7,200만 원이 확인됩니다.",
                "claim_type": "CASE_FACT",
                "fact_status": "VERIFIED_FACT",
                "source_ids": ["E09_등기부_권리변동_요약_202610.txt"],
                "grounding_status": "SUPPORTED",
                "reason": "통과",
            }
        ]
    )
    llm.invoke.return_value.content = json.dumps(conflict_reply, ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        conflict_res = run_verification(state["question"], conflict_draft, sources, require_question_coverage=True)
    assert conflict_res["consistency_checks"]["timeline"]["passed"] is False
    assert conflict_res["status"] == "REVISE"


def test_year_range_is_not_classified_as_precedent_case_number(document_state):
    """'2024년과 2026년' 같은 일반 연도 문장은 판례 사건번호로 집계되지 않는다."""
    from ai_legal_helper.agents.verification import audit_citations_and_claims

    draft = "2024년과 2026년 모두 별도 재계약서 없이 계속 거주했습니다. [E01_계약서.txt] 대법원 2022다21580 판결 참조."
    audit = audit_citations_and_claims(draft, consultation.document_sources(document_state))
    assert "PRECEDENT:2024년과2026" not in audit["generated_citation_ids"]
    assert "PRECEDENT:2022다21580" in audit["generated_citation_ids"]


def test_re_analyze_preserves_points_without_consuming_revision_count_and_approved_followup_search(document_state):
    """공식 법령 검색 후 첫 재분석은 수정 횟수를 소모하지 않으며, 승인된 범위의 새 조문 요청은 즉시 검색으로 분기한다."""
    state = {
        **document_state,
        "draft_answer": "질문처럼 2026.08.12 발견했더라도 등기 접수일은 2026.07.18입니다.",
        "preserved_points": ["질문상 발견일과 문서상 등기 접수일의 역할 구분 유지"],
        "revision_count": 0,
        "hilt_executed": True,
        "approval_status": "APPROVED",
        "approved_statute_laws": ["주택임대차보호법"],
        "statute_search_count": 1,
        "verification_result": {
            "status": "REVISE",
            "reason_code": "LEGAL_SOURCE_INSUFFICIENT",
            "legal_search_requests": [
                {
                    "law_name": "주택임대차보호법",
                    "articles": ["제3조의2"],
                    "issue": "확정일자 우선변제권 요건",
                    "question_part": "당사자와 지급 여부",
                }
            ],
        },
    }
    assert consultation.next_verification_step(state) == "execute_statute_search"

    llm = MagicMock()
    llm.invoke.return_value.content = "보강된 법령 기반 답변입니다. [E01_계약서.txt]"
    with patch("ai_legal_helper.agents.document_answer.get_llm", return_value=llm):
        re_analyzed = workflow.re_analyze_node(state)
    assert re_analyzed.get("revision_count", 0) == 0
    prompt_payload = llm.invoke.call_args.args[0][1].content
    assert "질문상 발견일과 문서상 등기 접수일의 역할 구분 유지" in prompt_payload


def test_finish_answer_generates_verified_limited_answer_or_sanitizes_internal_critique(document_state):
    """재작성 후 미통과 시 제한 답변을 생성·재검증하여 CAUTIONARY로 제공하고, 실패 시 내부 검토 문구를 숨긴다."""
    draft = "초안 답변입니다. [E01_계약서.txt]"
    _, manifest = format_grounding_sources(consultation.document_sources(document_state))
    failed_ver = {
        **verification_reply(
            status="REVISE",
            reason_code="ANSWER_REVISION_REQUIRED",
            missing_issues=["답변은 2026-09-30 도과 의미를 밝혔어야 한다."],
            missing_legal_issues=["등기사항증명서 원본 확인 필요"],
        ),
        "verified_answer_sha256": hashlib.sha256(draft.encode()).hexdigest(),
        "source_manifest": manifest,
    }
    state = {**document_state, "draft_answer": draft, "verification_result": failed_ver}

    limited_draft = "임대인 갑과 임차인 을이 계약했다. [E01_계약서.txt] 종료 여부는 추가 자료가 필요합니다."
    limited_ver = verification_reply(
        claims=[
            {
                "claim": "임대인 갑과 임차인 을이 계약했다.",
                "claim_type": "CASE_FACT",
                "fact_status": "VERIFIED_FACT",
                "source_ids": ["E01_계약서.txt"],
                "grounding_status": "SUPPORTED",
            }
        ],
        question_coverage=[
            {
                "question": "당사자와 지급 여부",
                "answered": False,
                "answerable": False,
                "limitation_disclosed": True,
                "limitation_statement": "종료 여부는 추가 자료가 필요합니다.",
                "reason": "한계 명시",
            }
        ],
    )
    with patch.object(consultation, "validate_document_snapshot"), \
            patch.object(consultation, "write_document_answer", return_value={"draft_answer": limited_draft}), \
            patch("ai_legal_helper.agents.verification.run_verification", return_value=limited_ver):
        cautionary_out = consultation.finish_answer(state)
    assert cautionary_out["final_disposition"] == "CAUTIONARY"
    assert cautionary_out["final_answer"] == limited_draft
    assert len(cautionary_out["sources"]) == 1

    # 제한 답변도 통과하지 못한 경우 내부 검토자 문구('밝혔어야 한다' 등)는 노출하지 않고 정제된 항목만 안내한다.
    with patch.object(consultation, "validate_document_snapshot"), \
            patch.object(consultation, "write_document_answer", return_value={"draft_answer": limited_draft}), \
            patch("ai_legal_helper.agents.verification.run_verification", return_value={"status": "REVISE", "claims": []}):
        withheld_out = consultation.finish_answer(state)
    assert withheld_out["final_disposition"] == "WITHHELD"
    assert "밝혔어야" not in withheld_out["final_answer"]
    assert "등기사항증명서 원본 확인 필요" in withheld_out["final_answer"]


def test_trace_3bc30893_list_inference_basis_does_not_cause_verification_error(document_state):
    """검증 LLM이 inference_basis를 배열로 반환해도 VERIFICATION_ERROR가 발생하지 않고 후속 조문 검색으로 이어진다."""
    draft = (
        "이 가압류 때문에 보증금반환채권 자체가 바로 없어졌다고 볼 자료는 없지만, "
        "회수 위험과 지연 위험은 분명히 커졌습니다. [E01_계약서.txt]"
    )
    reply = verification_reply(
        status="REVISE",
        reason_code="LEGAL_SOURCE_MISSING",
        claims=[
            {
                "claim": "이 가압류 때문에 보증금반환채권 자체가 바로 없어졌다고 볼 자료는 없지만, 회수 위험과 지연 위험은 분명히 커졌습니다.",
                "claim_type": "CASE_INFERENCE",
                "fact_status": "INFERENCE",
                "source_ids": ["E01_계약서.txt"],
                "grounding_status": "SUPPORTED",
                "reason": "사건 자료 기반 위험 추론으로 타당하다.",
                "inference_basis": ["E01_계약서.txt"],
                "inference_limit": "보증금반환채권 자체가 바로 없어졌다고 볼 자료는 없지만",
            }
        ],
        legal_search_requests=[
            {
                "law_name": "주택임대차보호법",
                "articles": ["제3조", "제3조의2"],
                "issue": "대항력 성립 요건, 우선변제권 성립 요건",
                "question_part": "당사자와 지급 여부",
            }
        ],
    )
    llm = MagicMock()
    llm.invoke.return_value.content = json.dumps(reply, ensure_ascii=False)
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=llm):
        ver = run_verification(
            document_state["question"],
            draft,
            consultation.document_sources(document_state),
            require_question_coverage=True,
        )
    assert ver["reason_code"] != "VERIFICATION_ERROR"
    assert ver["status"] == "REVISE"
    assert ver["claims"][0]["inference_basis"] == "E01_계약서.txt"
    state = {
        **document_state,
        "draft_answer": draft,
        "verification_result": ver,
        "approval_status": "APPROVED",
        "approved_statute_laws": ["주택임대차보호법"],
        "statute_search_count": 1,
    }
    assert consultation.next_verification_step(state) == "execute_statute_search"



