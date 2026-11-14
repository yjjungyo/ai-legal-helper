# -*- coding: utf-8 -*-
"""P7 공식 법령 버전별 근거 전달과 Synthesizer/Agent 계약 회귀."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from ai_legal_helper.legal_knowledge.evidence_bundle import build_legal_evidence_bundle
from ai_legal_helper.workflows.legal_workflow import (
    legal_evidence_bundle_node, synthesize_node, run_agents_node, build_legal_graph,
)


def source(version, role, article="제36조", content="제36조(계약신고) 공식 조문 본문"):
    return {
        "source_type": "STATUTE", "source_id": f"OFFICIAL:L1:{version}:{article}",
        "law_id": "L1", "statute_name": "가상 계약법 시행령", "article": article,
        "version_id": version, "version_relation": role,
        "article_effective_date": "2027-04-28" if version == "200" else "2024-01-01",
        "content": content,
        "source_url": "https://www.law.go.kr/법령/가상계약법시행령",
        "retrieval_method": "OFFICIAL_STATUTE_SEARCH",
    }


def temporal(status="NOT_APPLICABLE"):
    return {"status": status, "decisions": [{
        "source_id": "OFFICIAL:L1:200:제36조",
        "status": status, "reason_code": "BEFORE_ARTICLE_EFFECTIVE_DATE",
    }]}


def test_two_versions_kept_separately_and_future_not_assumed_applicable():
    bundle = build_legal_evidence_bundle(
        [source("100", "AS_OF_CANDIDATE"),
         source("200", "NEXT_EFFECTIVE_CANDIDATE")],
        temporal_resolution=temporal(),
    )
    assert bundle.source_count == 2
    assert {x.version_id for x in bundle.items} == {"100", "200"}
    assert bundle.items[1].rule_status == "NOT_APPLICABLE"
    assert "NEXT_EFFECTIVE_CANDIDATE" in bundle.digest
    assert "FUTURE_VERSION_NOT_CURRENT" in bundle.warning_codes


def test_uncertain_sources_label_uncertainty_and_retain_full_registry():
    text = "개정 법령 원문 " * 500
    raw = [source("200", "NEXT_EFFECTIVE_CANDIDATE", content=text)]
    original = deepcopy(raw)
    bundle = build_legal_evidence_bundle(raw, temporal_resolution={})
    assert raw == original
    assert bundle.items[0].rule_status == "UNCONFIRMED"
    assert len(bundle.items[0].preview) < len(text)
    assert "TEMPORAL_APPLICABILITY_UNCONFIRMED" in bundle.warning_codes


def test_duplicate_source_id_collapsed_but_versions_remain_distinct():
    one = source("100", "AS_OF_CANDIDATE")
    two = source("200", "NEXT_EFFECTIVE_CANDIDATE")
    bundle = build_legal_evidence_bundle([one, one, two, dict(two)])
    assert bundle.source_count == 2


def test_nonstatute_and_missing_content_not_promoted_to_law():
    evidence = source("100", "AS_OF_CANDIDATE")
    evidence["source_type"] = "CASE_EVIDENCE"
    output = build_legal_evidence_bundle(
        [evidence, {**source("200", "NEXT_EFFECTIVE_CANDIDATE"), "content": ""}]
    )
    assert output.source_count == 0
    assert output.digest == ""


def test_bundle_digest_char_budget_is_enforced_with_warning():
    bundle = build_legal_evidence_bundle(
        [source("100", "AS_OF_CANDIDATE"), source("200", "NEXT_EFFECTIVE_CANDIDATE")],
        max_chars=100,
    )
    assert bundle.truncated
    assert bundle.source_count == 2
    assert "DIGEST_TRUNCATED" in bundle.warning_codes


def test_official_source_bundle_node_does_not_replace_retrieved_sources():
    src = source("200", "NEXT_EFFECTIVE_CANDIDATE")
    state = {"retrieved_sources": [src], "temporal_resolution": temporal()}
    output = legal_evidence_bundle_node(state)
    assert output["legal_evidence_bundle"]["source_count"] == 1
    assert state["retrieved_sources"] == [src]
    assert output["legal_evidence_bundle"]["items"][0]["version_id"] == "200"


def test_synthesizer_receives_bundle_without_extra_llm_roundtrip():
    from ai_legal_helper.agents.synthesizer import synthesize
    prompts = []
    class FakeLLM:
        def invoke(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(content="시행예정 규정은 아직 적용 여부가 확인되지 않았습니다.")
    bundle = build_legal_evidence_bundle(
        [source("200", "NEXT_EFFECTIVE_CANDIDATE")], temporal_resolution=temporal(),
    )
    with patch("ai_legal_helper.agents.synthesizer.get_llm", return_value=FakeLLM()):
        messages = synthesize(
            [HumanMessage(content="2026년 계약에 적용되나요?")],
            {"민법": "관련 조문 검토"},
            legal_evidence_bundle=bundle.as_dict(),
        )
    assert len(prompts) == 1
    assert "MST=200" in prompts[0]
    assert "NEXT_EFFECTIVE_CANDIDATE" in prompts[0]
    assert "UNCONFIRMED" in prompts[0] or "NOT_APPLICABLE" in prompts[0]
    assert "시행예정" in messages[-1].content


def test_workflow_synthesize_forwards_bundle_to_synthesizer():
    got = {}
    def fake_synthesize(messages, results, **kwargs):
        got.update(kwargs)
        return [*messages, AIMessage(content="법률 기준 확인 필요")]
    with patch("ai_legal_helper.workflows.legal_workflow.synthesize", new=fake_synthesize):
        result = synthesize_node({
            "messages": [HumanMessage(content="상담")],
            "results": {"민법": "법리"},
            "legal_evidence_bundle": {"source_count": 1, "digest": "MST-200"},
        })
    assert result["draft_answer"] == "법률 기준 확인 필요"
    assert got["legal_evidence_bundle"]["digest"] == "MST-200"


@pytest.mark.asyncio
async def test_specialist_brief_contains_preapproved_official_version():
    seen = []
    def mock_specialist(category, question, brief):
        seen.append(brief)
        return category, "전문 분석", []
    src = source("200", "NEXT_EFFECTIVE_CANDIDATE")
    with patch("ai_legal_helper.workflows.legal_workflow.run_specialist_agent",
               new=mock_specialist):
        result = await run_agents_node({
            "question": "계약에 개정 시행령 적용 여부",
            "categories": ["민법"],
            "retrieved_sources": [src],
            "temporal_resolution": temporal(),
        })
    assert seen
    assert "NEXT_EFFECTIVE_CANDIDATE" in seen[0]
    assert "MST=200" in seen[0]
    assert result["retrieved_sources"][0]["source_id"] == src["source_id"]


def test_compiled_graph_has_evidence_bundle_before_synthesizer():
    from langgraph.checkpoint.memory import MemorySaver
    compiled = build_legal_graph(checkpointer=MemorySaver())
    assert "legal_evidence_bundle" in compiled.nodes



def test_evidence_bundle_node_skips_in_document_mode():
    """DOCUMENT_MODE에서는 generate_answer가 직접 출처를 포맷팅하므로 legal_evidence_bundle 생성을 생략하는지 검증한다."""
    src = source("200", "NEXT_EFFECTIVE_CANDIDATE")
    state = {
        "answer_mode": "DOCUMENT_GROUNDED",
        "retrieved_sources": [src],
        "temporal_resolution": temporal(),
    }
    output = legal_evidence_bundle_node(state)
    assert output == {"legal_evidence_bundle": None}
