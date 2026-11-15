# -*- coding: utf-8 -*-
"""5단계: 검색/재작성/검증의 무진전 반복 제거와 법률 안전성 회귀.

실제 LLM·법제처 API·DB 없이, 기존 Graph 상태전이를 재현한다.
법리 판정의 정확도를 Mock PASS로 증명하려는 테스트가 아니라
동일 입력 재호출을 제거하되 *신규 판례/법령 및 문서/질문 변경을
절대 생략하지 않는* 실행 정책을 검증하는 테스트.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_legal_helper.rag.grounding_context import format_grounding_sources
from ai_legal_helper.workflows.verification_progress import (
    added_legal_source_ids,
    can_reuse_verification,
    verification_input_hash,
    verification_defect_signature,
)
from ai_legal_helper.workflows import document_consultation as dc
from ai_legal_helper.workflows import legal_workflow as workflow


@pytest.fixture
def sources():
    return [
        {"source_id": "E01_계약서.txt", "source_type": "CASE_EVIDENCE", "review_status": "APPROVED",
         "content": "임대인 갑, 임차인 을. 보증금 300,000,000원."},
        {"source_id": "STATUTE:1", "source_type": "STATUTE", "statute_name": "민법",
         "article": "제1조", "content": "민법 제1조 법원의 적용에 관한 규정"},
    ]


@pytest.fixture
def document_state(sources):
    _, manifest = format_grounding_sources(sources)
    return {
        "question": "현재 보증금 반환이 가능한가요?",
        "draft_answer": "추가 법률요건의 확인이 필요합니다.",
        "answer_mode": dc.DOCUMENT_MODE,
        "answer_source_manifest": manifest,
        "case_evidence_briefing": {"as_of_date": "2026-11-15", "source_documents": []},
        "retrieved_sources": sources,
        "revision_count": 0,
        "statute_search_count": 0,
        "verification_progress_history": [],
    }


def base_verification(status="REVISE"):
    return {
        "status": status, "reason_code": "ANSWER_REVISION_REQUIRED",
        "claims": [
            {"claim": "추가 법률요건의 확인이 필요합니다.", "claim_type": "LEGAL_APPLICATION",
             "grounding_status": "UNSUPPORTED", "source_ids": ["STATUTE:1"]},
        ],
        "application_audit": {"findings": [
            {"claim_index": 0, "reason_codes": ["REQUIREMENTS_MISSING"]},
        ]},
        "missing_legal_issues": ["추가 요건 사실 확인"],
        "question_coverage": [{"question": "반환 여부", "answered": False}],
        "consistency_checks": {
            "timeline": {"passed": False, "reason": "선후 확인 필요"},
        },
    }


def test_source_delta_counts_only_new_statute_and_precedent(sources):
    newer = sources + [
        sources[-1],
        {"source_id": "PRECEDENT:X", "source_type": "PRECEDENT", "content": "대법원 판시법리"},
        {"source_id": "STATUTE:2", "source_type": "STATUTE", "content": "실제 조문"},
        {"source_id": "E02", "source_type": "CASE_EVIDENCE", "content": "사건 원문"},
        {"source_id": "STATUTE:EMPTY", "source_type": "STATUTE", "content": ""},
    ]
    assert added_legal_source_ids(sources, newer) == ["PRECEDENT:X", "STATUTE:2"]
    assert added_legal_source_ids(sources, sources) == []


def test_source_delta_rejects_same_id_changed_content_as_new_source(sources):
    modified = [dict(x) for x in sources]
    modified[-1]["content"] = "같은 ID로 임의 덮어쓴 본문"
    assert added_legal_source_ids(sources, modified) == []


def test_missing_source_id_never_counts_as_new(sources):
    after = sources + [{"source_type": "STATUTE", "content": "내용만 있고 식별자 누락"}]
    assert added_legal_source_ids(sources, after) == []


@pytest.mark.parametrize("field,value", [
    ("question", "다른 질문입니다"), ("draft_answer", "다른 초안입니다"),
    ("as_of_date", "2026-11-16"), ("require_question_coverage", False),
])
def test_verifier_input_hash_invalidates_any_changed_contract(field, value):
    base = {
        "question": "질문", "draft_answer": "답변",
        "manifest": {"content_sha256": "a", "source_count": 2},
        "as_of_date": "2026-11-15", "require_question_coverage": True,
    }
    changed = deepcopy(base)
    changed[field] = value
    assert verification_input_hash(**base) != verification_input_hash(**changed)


def test_verifier_input_hash_invalidates_source_manifest():
    base = {
        "question": "질문", "draft_answer": "답변",
        "manifest": {"content_sha256": "a", "source_count": 2},
        "as_of_date": "2026-11-15", "require_question_coverage": True,
    }
    changed = deepcopy(base)
    changed["manifest"]["content_sha256"] = "b"
    assert verification_input_hash(**base) != verification_input_hash(**changed)


def test_defect_signature_ignores_rephrasing_but_detects_claim_progress():
    a = base_verification()
    b = deepcopy(a)
    b["claims"][0]["claim"] = "표현만 달라진 같은 미확인 법률효과"
    x = verification_defect_signature(a, question="질문", sources_sha256="sha")
    assert verification_defect_signature(b, question="질문", sources_sha256="sha") == x
    b["claims"][0]["grounding_status"] = "SUPPORTED"
    assert verification_defect_signature(b, question="질문", sources_sha256="sha") != x


def test_defect_signature_distinguishes_source_precedent_and_temporal(sources):
    a = base_verification()
    base = verification_defect_signature(a, question="질문", sources_sha256="old")
    assert verification_defect_signature(a, question="질문", sources_sha256="new") != base
    a["application_audit"]["findings"][0]["reason_codes"].append("PRECEDENT_COMPARISON_MISSING")
    assert verification_defect_signature(a, question="질문", sources_sha256="old") != base
    a["temporal_gate"] = {"status": "BLOCK"}
    assert verification_defect_signature(a, question="질문", sources_sha256="old") != base


def cache_payload():
    draft = "법률적 판단을 확정할 수 없습니다."
    manifest = {"content_sha256": "abc", "source_count": 2}
    signature = verification_input_hash(
        question="질문", draft_answer=draft, manifest=manifest,
        as_of_date="2026-11-15", require_question_coverage=True,
    )
    previous = {**base_verification(),
                "verified_answer_sha256": hashlib.sha256(draft.encode()).hexdigest(),
                "verification_input_hash": signature,
                "source_manifest": manifest}
    return previous, signature, draft, manifest


def test_cache_requires_complete_verifier_snapshot():
    p, h, draft, manifest = cache_payload()
    assert can_reuse_verification(previous=p, expected_input_hash=h,
                                  current_draft=draft, current_manifest=manifest)
    p["verification_input_hash"] = "untrusted"
    assert not can_reuse_verification(previous=p, expected_input_hash=h,
                                      current_draft=draft, current_manifest=manifest)


@pytest.mark.parametrize("reason", [
    "VERIFICATION_ERROR", "OFFICIAL_STATUTE_API_ERROR",
    "TEMPORAL_SEMANTIC_CONTRADICTION",
])
def test_cache_bans_errors_and_temporal_conflicts(reason):
    p,h,d,m = cache_payload()
    p["reason_code"] = reason
    assert not can_reuse_verification(previous=p,expected_input_hash=h,
                                      current_draft=d,current_manifest=m)


@pytest.mark.parametrize("field,value", [
    ("temporal_recheck_only", True),
    ("temporal_repair_only", True),
    ("temporal_gate", {"status": "BLOCK"}),
])
def test_cache_bans_unfinished_temporal_review(field, value):
    p,h,d,m = cache_payload()
    p[field] = value
    assert not can_reuse_verification(previous=p,expected_input_hash=h,
                                      current_draft=d,current_manifest=m)


def test_cache_invalidates_changed_answer_and_source_manifest():
    p,h,d,m = cache_payload()
    assert not can_reuse_verification(previous=p, expected_input_hash=h,
                                      current_draft=d+"추가 내용", current_manifest=m)
    assert not can_reuse_verification(previous=p, expected_input_hash=h,
                                      current_draft=d,current_manifest={"content_sha256":"another"})


def test_rewrite_marks_identical_answer_and_unchanged_sources(document_state):
    state = {**document_state, "verification_result": base_verification()}
    prior = state["draft_answer"]
    old_manifest = state["answer_source_manifest"]
    with patch("ai_legal_helper.workflows.document_consultation.write_document_answer",
               return_value={"draft_answer": prior, "answer_source_manifest": old_manifest}):
        out = dc.generate_answer(state, repair=True)
    assert out["revision_no_progress"] is True
    assert out["revision_count"] == 1
    assert out["draft_answer"] == prior


def test_rewrite_after_new_sources_does_not_claim_no_progress(document_state):
    state = {**document_state, "verification_result": base_verification()}
    with patch("ai_legal_helper.workflows.document_consultation.write_document_answer",
               return_value={"draft_answer": state["draft_answer"],
                             "answer_source_manifest": {"content_sha256":"different"}}):
        out = dc.generate_answer(state, repair=True,increment_revision=False)
    assert out["revision_no_progress"] is False
    assert "revision_count" not in out


def test_rewrite_after_new_answer_does_not_claim_no_progress(document_state):
    with patch("ai_legal_helper.workflows.document_consultation.write_document_answer",
               return_value={"draft_answer": "새로운 요건 검토", "answer_source_manifest": state_manifest(document_state)}):
        out = dc.generate_answer(document_state, repair=True)
    assert out["revision_no_progress"] is False


def state_manifest(state):
    return state["answer_source_manifest"]


def test_document_verifier_reuses_previous_identical_failure_without_llm(document_state):
    mock = MagicMock(return_value=base_verification())
    with patch.object(dc, "validate_document_snapshot"), \
         patch("ai_legal_helper.agents.verification.run_verification", mock):
        initial = dc.verify_answer(document_state)
        assert mock.call_count == 1
        old = initial["verification_result"]
        updated = dc.verify_answer({
            **document_state, **initial, "verification_result": old,
            "revision_no_progress": True,
        })
    assert mock.call_count == 1
    assert updated["verification_reused"] is True
    assert updated["verification_no_progress"] is True
    assert updated["verification_result"]["status"] == "REVISE"


def test_document_verifier_rechecks_when_question_changes(document_state):
    mock = MagicMock(return_value=base_verification())
    with patch.object(dc, "validate_document_snapshot"), \
         patch("ai_legal_helper.agents.verification.run_verification", mock):
        initial = dc.verify_answer(document_state)
        changed = dc.verify_answer({
            **document_state, **initial,
            "question": "수정된 새로운 사용자 질문",
            "revision_no_progress": True,
        })
    assert mock.call_count == 2
    assert changed["verification_reused"] is False


def test_document_verifier_rechecks_when_temporal_review_unresolved(document_state):
    mock = MagicMock(return_value=base_verification())
    with patch.object(dc, "validate_document_snapshot"), \
         patch("ai_legal_helper.agents.verification.run_verification", mock):
        initial = dc.verify_answer(document_state)
        previous = dict(initial["verification_result"])
        previous["temporal_recheck_only"] = True
        changed = dc.verify_answer({
            **document_state, **initial,
            "verification_result": previous,
            "revision_no_progress": True,
        })
    assert mock.call_count == 2
    assert changed["verification_reused"] is False


def test_document_verifier_fails_if_source_changed_after_writer(document_state, sources):
    mock = MagicMock(return_value=base_verification())
    changed_sources = sources + [{
        "source_id": "PRECEDENT:NEW", "source_type": "PRECEDENT", "content": "새 판시법리",
    }]
    with patch.object(dc, "validate_document_snapshot"), \
         patch("ai_legal_helper.agents.verification.run_verification", mock):
        result = dc.verify_answer({
            **document_state, "retrieved_sources": changed_sources,
            "revision_no_progress": True,
        })
    assert mock.call_count == 0
    assert result["verification_result"]["status"] == "INSUFFICIENT"
    assert result["verification_result"]["reason_code"] == "VERIFICATION_ERROR"


def test_document_verifier_repeated_unresolved_defect_stops_even_if_draft_differs(document_state):
    mock = MagicMock(return_value=base_verification())
    with patch.object(dc, "validate_document_snapshot"), \
         patch("ai_legal_helper.agents.verification.run_verification", mock):
        initial = dc.verify_answer(document_state)
        changed = dc.verify_answer({
            **document_state, **initial,
            "draft_answer": "다른 문구로 바꾼 초안",
            "revision_no_progress": False,
        })
    assert mock.call_count == 2
    assert changed["verification_no_progress"] is True


def test_routing_first_failure_gets_repair_opportunity(document_state):
    state = {**document_state, "verification_result": base_verification(),
             "verification_no_progress": False, "statute_search_count": 2}
    assert dc.next_verification_step(state) == "revise"


def test_routing_repeated_failure_stops_but_does_not_fake_pass(document_state):
    state = {**document_state, "verification_result": base_verification(),
             "verification_no_progress": True, "revision_count": 1,
             "statute_search_count": 2}
    assert dc.next_verification_step(state) == "finalize"
    with patch.object(dc, "validate_document_snapshot"):
        result = dc.finish_answer(state)
    assert result["final_disposition"] == "WITHHELD"
    assert result["verification_result"]["status"] == "INSUFFICIENT"


def test_routing_new_search_takes_priority_over_no_progress(document_state):
    state = {**document_state, "verification_result": base_verification(),
             "verification_no_progress": True, "statute_search_count": 0}
    request = [{"law_name":"민법", "articles":["제1조"], "key":"key"}]
    with patch.object(dc, "pending_searches", return_value=request), \
         patch.object(dc, "pending_precedent_searches", return_value=[]), \
         patch.object(dc, "search_is_approved", return_value=True):
        assert dc.next_verification_step(state) == "execute_statute_search"


def test_routing_new_search_requires_hitl_approval_even_if_progress_stalled(document_state):
    state = {**document_state, "verification_result": base_verification(),
             "verification_no_progress": True, "statute_search_count": 0}
    requests = [{"law_name":"민법", "articles":["제1조"], "key":"key"}]
    with patch.object(dc, "pending_searches", return_value=requests), \
         patch.object(dc, "pending_precedent_searches", return_value=[]), \
         patch.object(dc, "search_is_approved", return_value=False):
        assert dc.next_verification_step(state) == "statute_search_approval"


def test_search_results_no_new_sources_skip_reanalyze(document_state):
    st={**document_state, "statute_search_status":"NOT_FOUND",
        "statute_search_phase":"POST_VERIFICATION",
        "search_delta_count":0,"verification_result":base_verification()}
    assert workflow.statute_search_result_condition(st) == "finalize"


def test_search_results_pre_analysis_keeps_required_retrieval(document_state):
    st={**document_state, "statute_search_status":"NOT_FOUND",
        "statute_search_phase":"PRE_ANALYSIS", "search_delta_count":0}
    assert workflow.statute_search_result_condition(st) == "run_agents"


def test_search_results_new_precedent_keeps_reanalysis(document_state):
    st={**document_state, "statute_search_status":"OFFICIAL_SUCCESS",
        "statute_search_phase":"POST_VERIFICATION", "search_delta_count":1,
        "precedent_search_results":[{"source_id":"PRECEDENT:NEW","content":"판시법리"}]}
    assert workflow.statute_search_result_condition(st) == "re_analyze"


def test_search_results_new_statute_keeps_reanalysis(document_state):
    st={**document_state, "statute_search_status":"OFFICIAL_SUCCESS",
        "statute_search_phase":"POST_VERIFICATION", "search_delta_count":1,
        "statute_search_results":[{"source_id":"STATUTE:NEW","content":"법률 원문"}]}
    assert workflow.statute_search_result_condition(st) == "re_analyze"


def test_search_results_legacy_state_without_delta_preserves_routing(document_state):
    st={**document_state, "statute_search_status":"NOT_FOUND",
        "statute_search_phase":"POST_VERIFICATION"}
    assert workflow.statute_search_result_condition(st) == "re_analyze"


def test_search_api_error_never_finalizes(document_state):
    st={**document_state, "statute_search_status":"API_ERROR",
        "statute_search_phase":"POST_VERIFICATION",
        "search_delta_count":0}
    assert workflow.statute_search_result_condition(st) == "insufficient"


def test_graph_compiles_search_result_finalization_edge():
    from langgraph.checkpoint.memory import MemorySaver
    app = workflow.build_legal_graph(checkpointer=MemorySaver())
    assert app is not None


def test_supervisor_initialize_exposes_progress_reset_fields():
    from ai_legal_helper.workflows.state import LegalState
    assert "verification_no_progress" in LegalState.__annotations__
    assert "verification_progress_history" in LegalState.__annotations__
    assert "search_delta_count" in LegalState.__annotations__
