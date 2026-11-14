# -*- coding: utf-8 -*-
"""
P3 기존 LangChain Tool 어댑터/AgentExecutor 호환 회귀 테스트.

[의도]
8개 Agent 명칭·Tool 계약을 변경하지 않고 공통 검색 결과가 실제 LLM
Observation과 검증용 출처 Registry에 동시에 전달되는지 확인한다.

LLM/Vector/OpenLaw는 모두 Mock으로 대체하므로 인증키/운영 DB가 필요 없다.
"""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from ai_legal_helper.agents.constants import CATEGORIES, get_tool_name, to_eng
from ai_legal_helper.agents.legal.base_agent import AgentExecutor, REACT_TEMPLATE
from ai_legal_helper.legal_knowledge.retrieval_service import (
    LawRetrievalResponse, LawSourceStatus,
)
from ai_legal_helper.observability.context import (
    get_retrieved_sources, reset_retrieved_sources,
)
from ai_legal_helper.rag.retrieval_factory import make_fixed_retrieval_tool
from langchain_core.prompts import PromptTemplate


def source(*, official=False):
    return {
        "source_id": "STATUTE:TEST-ID:VERSION-A:제3조:123456789abc",
        "source_type": "STATUTE",
        "law_id": "TEST-ID",
        "version_id": "VERSION-A",
        "statute_name": "가상임대차법",
        "article": "제3조",
        "filename": None if official else "가상임대차법.pdf",
        "page": None if official else "3",
        "source_url": "https://www.law.go.kr/법령/가상임대차법/제3조" if official else None,
        "content": "제3조(시험) " + "증거에 필요한 원문 " * 30,
    }


def response(*, status=LawSourceStatus.SOURCE_COMPLETE, sources=None):
    return LawRetrievalResponse(status=status, sources=sources if sources is not None else [source()])


def _make_tool():
    return make_fixed_retrieval_tool("civil_retrieval_tool", "civil", "민법")


def test_eight_existing_tool_names_are_unchanged():
    for cat in CATEGORIES:
        tool = make_fixed_retrieval_tool(get_tool_name(cat), to_eng(cat), cat)
        assert tool.name == get_tool_name(cat)
        assert "공통" in tool.description


def test_shared_search_source_is_injected_without_truncating_verification_registry(monkeypatch):
    monkeypatch.setenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "1")
    reset_retrieved_sources()
    observed = {}
    def shared(self, **kwargs):
        observed.update(kwargs)
        return response()
    with patch("ai_legal_helper.rag.retrieval_factory.rewrite_query",
               return_value="가상임대차법 제3조"), patch(
        "ai_legal_helper.legal_knowledge.retrieval_service.LawRetrievalService.search",
        new=shared,
    ):
        output = _make_tool().func("가상임대차법 제3조를 알려줘")
    assert observed["original_question"] == "가상임대차법 제3조를 알려줘"
    assert observed["category"] == "civil"
    assert "[CITE] (가상임대차법.pdf, p.3)" in output
    assert "추가 공식 검색은 승인된 워크플로" in output
    recorded = get_retrieved_sources()
    assert len(recorded) == 1
    assert len(recorded[0]["content"]) > 240  # Observation과 달리 원문 그대로 검증기에 제공
    assert "[GUIDE]" not in recorded[0]["content"]


def test_official_xml_citation_does_not_fabricate_pdf_or_page(monkeypatch):
    monkeypatch.setenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "1")
    reset_retrieved_sources()
    with patch("ai_legal_helper.rag.retrieval_factory.rewrite_query", return_value="제3조"), patch(
        "ai_legal_helper.legal_knowledge.retrieval_service.LawRetrievalService.search",
        return_value=response(sources=[source(official=True)]),
    ):
        output = _make_tool().func("가상임대차법 제3조")
    assert "(가상임대차법 제3조, https://www.law.go.kr/법령/가상임대차법/제3조)" in output
    assert "p.?" not in output
    assert ".pdf" not in output
    assert get_retrieved_sources()[0]["source_url"].startswith("https://www.law.go.kr")


def test_partial_coverage_is_explicit_and_no_official_search_is_executed(monkeypatch):
    monkeypatch.setenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "1")
    reset_retrieved_sources()
    with patch("ai_legal_helper.rag.retrieval_factory.rewrite_query", return_value="제3조"), patch(
        "ai_legal_helper.legal_knowledge.retrieval_service.LawRetrievalService.search",
        return_value=response(status=LawSourceStatus.SOURCE_TEMPORAL_UNCONFIRMED),
    ):
        output = _make_tool().func("가상임대차법 제3조")
    assert "[SOURCE_STATUS] SOURCE_TEMPORAL_UNCONFIRMED" in output
    assert "승인된 워크플로" in output
    assert len(get_retrieved_sources()) == 1


def test_infrastructure_error_does_not_masquerade_as_no_search_match(monkeypatch):
    monkeypatch.setenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "1")
    reset_retrieved_sources()
    with patch("ai_legal_helper.rag.retrieval_factory.rewrite_query", return_value="제3조"), patch(
        "ai_legal_helper.legal_knowledge.retrieval_service.LawRetrievalService.search",
        return_value=response(status=LawSourceStatus.RETRIEVAL_ERROR, sources=[]),
    ):
        output = _make_tool().func("가상임대차법 제3조")
    assert "검색 인프라 장애" in output
    assert "검색결과 없음" not in output
    assert get_retrieved_sources() == []


def test_feature_flag_disabled_restores_legacy_single_category_search(monkeypatch):
    monkeypatch.setenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "0")
    reset_retrieved_sources()
    doc = SimpleNamespace(
        page_content="제3조(대항력) 가상 본문",
        metadata={"law_name": "가상임대차법", "article": "제3조",
                  "file_name": "가상임대차법.pdf", "page": "3"},
    )
    calls = []
    def legacy(*, query, k, category):
        calls.append((k, category))
        return SimpleNamespace(status="SUCCESS", documents=[doc])
    with patch("ai_legal_helper.rag.retrieval_factory.rewrite_query", return_value="제3조"), patch(
        "ai_legal_helper.rag.retrieval.retrieve_with_status", new=legacy,
    ):
        output = _make_tool().func("가상임대차법 제3조")
    from ai_legal_helper.rag.retrieval_factory import MAX_DOCS
    assert calls == [(MAX_DOCS, "civil")]
    assert "[CITE] (가상임대차법.pdf, p.3)" in output
    assert len(get_retrieved_sources()) == 1


def test_agent_executor_receives_common_tool_observation_without_extra_tool(monkeypatch):
    monkeypatch.setenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "1")
    reset_retrieved_sources()
    llm = MagicMock()
    llm.invoke.return_value = SimpleNamespace(
        content="Final Answer: 근거에 따른 조건부 안내입니다."
    )
    tool = _make_tool()
    prompt = PromptTemplate.from_template(REACT_TEMPLATE).partial(
        system="법령 확인과 적용례 검증 규칙",
        tools=f"{tool.name}: 공통 법령검색",
        tool_names=tool.name,
    )
    agent = AgentExecutor(prompt, [tool])
    with patch("ai_legal_helper.agents.legal.base_agent.get_llm", return_value=llm), patch(
        "ai_legal_helper.rag.retrieval_factory.rewrite_query", return_value="제3조",
    ), patch(
        "ai_legal_helper.legal_knowledge.retrieval_service.LawRetrievalService.search",
        return_value=response(),
    ):
        answer = agent.invoke({"input": "가상임대차법 제3조", "chat_brief": "사건 요약"})
    assert "조건부 안내" in answer["output"]
    prompt_text = llm.invoke.call_args.args[0]
    assert "[CITE] (가상임대차법.pdf, p.3)" in prompt_text
    assert "사건 요약" in prompt_text
    assert len(get_retrieved_sources()) == 1


def test_no_sources_exposes_ambiguous_law_status_to_agent(monkeypatch):
    """공식 약칭 충돌 시 근거 없음만 표시하지 않고 모호성 사유를 전달한다."""
    monkeypatch.setenv("LEGAL_GLOBAL_RETRIEVAL_ENABLED", "1")
    reset_retrieved_sources()
    response_data = LawRetrievalResponse(
        status=LawSourceStatus.SOURCE_MISSING,
        sources=[],
        reason_codes=["LAW_IDENTITY_AMBIGUOUS"],
        official_search_recommended=True,
    )
    with patch("ai_legal_helper.rag.retrieval_factory.rewrite_query", return_value="공식 약칭"), patch(
        "ai_legal_helper.legal_knowledge.retrieval_service.LawRetrievalService.search",
        return_value=response_data,
    ):
        output = _make_tool().func("주택임대차보호법상?")
    assert "[검색결과 없음]" in output
    assert "[SOURCE_STATUS] SOURCE_MISSING" in output
    assert "LAW_IDENTITY_AMBIGUOUS" in output
    assert get_retrieved_sources() == []
