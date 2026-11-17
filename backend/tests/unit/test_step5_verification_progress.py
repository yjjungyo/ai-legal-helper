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
    # [STEP5-TEST-01 / Gemini] CASE_EVIDENCE 원문은 검색 결과 리스트가
    # 아니라 승인된 사건 브리핑 문서를 통해 document_sources()에
    # 결합된다. Writer의 manifest도 반드시 그 동일한 공용 함수로
    # 산출해야 캐시 테스트가 허위 SOURCE_MISMATCH로 종료되지 않는다.
    state = {
        "question": "현재 보증금 반환이 가능한가요?",
        "draft_answer": "추가 법률요건의 확인이 필요합니다.",
        "answer_mode": dc.DOCUMENT_MODE,
        "case_evidence_briefing": {
            "as_of_date": "2026-11-15",
            "source_documents": [{
                "document_name": sources[0]["source_id"],
                "evidence_id": "ev1",
                "content": sources[0]["content"],
                "review_status": "APPROVED",
            }],
        },
        "retrieved_sources": [sources[1]],
        "revision_count": 0,
        "statute_search_count": 0,
        "verification_progress_history": [],
    }
    _, state["answer_source_manifest"] = format_grounding_sources(dc.document_sources(state))
    return state


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
    assert workflow.statute_search_result_condition(st) == "synthesize"


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


@pytest.mark.parametrize("added_type,expected_count", [
    ("NONE", 0), ("PRECEDENT", 1), ("STATUTE", 1),
])
def test_real_document_search_executor_tracks_actual_source_delta(
    document_state, added_type, expected_count,
):
    """기존법령 API 재반환 vs 새 판례·조문 추가를 검색 노드 계약으로 검증.

    [STEP5-TEST-02 / Gemini] 실제 `execute_statute_search_node`의
    조회/병합 반환을 모의한다. 법령·판례가 찾은 *개수*가 아닌
    Source Registry 신규 ID 개수만 다음 재분석의 진행 기준이다.
    """
    base = list(document_state["retrieved_sources"])
    extra = []
    if added_type == "PRECEDENT":
        extra = [{
            "source_id": "PRECEDENT:TEST-NEW", "source_type": "PRECEDENT",
            "case_number": "2023다100", "content": "공식 판례 법률요건",
        }]
    elif added_type == "STATUTE":
        extra = [{
            "source_id": "STATUTE:TEST-NEW", "source_type": "STATUTE",
            "statute_name": "민법", "article": "제2조", "content": "공식 조문",
        }]

    # API가 이전 원문을 1건 반복 반환해도 실제 신규 내용이 없을 수 있다.
    api_return = base[-1:] + extra
    combined = base + extra
    mock_out = {
        "retrieved_sources": combined,
        "statute_search_results": [x for x in api_return if x["source_type"] == "STATUTE"],
        "precedent_search_results": [x for x in api_return if x["source_type"] == "PRECEDENT"],
        "statute_search_status": "OFFICIAL_SUCCESS",
        "statute_search_count": 1,
        "statute_search_items": [],
        "precedent_search_items": [],
        "statute_search_channels": ["OPENLAW_API"],
    }
    state = {
        **document_state,
        "answer_mode": dc.DOCUMENT_MODE,
        "approval_status": "APPROVED",
        "approved_statute_laws": ["민법"],
        "auto_approve_statute_search": True,
        "verification_result": {
            "status":"REVISE", "reason_code":"LEGAL_SOURCE_INSUFFICIENT",
            "candidate_laws":["민법"],
            "claims": base_verification()["claims"],
            "legal_search_requests": [],
        },
        "statute_search_phase": "POST_VERIFICATION",
    }
    with patch("ai_legal_helper.workflows.document_search.execute_document_search",
               return_value=mock_out) as search:
        out = workflow.execute_statute_search_node(state)
    assert search.call_count == 1
    assert out["search_delta_count"] == expected_count
    assert len(out["search_added_source_ids"]) == expected_count
    merged = {**state, **out}
    expected_route = "re_analyze" if expected_count else "finalize"
    assert workflow.statute_search_result_condition(merged) == expected_route


def fallback_state(document_state, **changes):
    """같은 원문을 검증한 정상 스냅샷으로 Finalize 경로를 재현한다."""
    draft = document_state["draft_answer"]
    result = {
        "status": "REVISE", "reason_code": "ANSWER_REVISION_REQUIRED",
        "verified_answer_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
        "source_manifest": document_state["answer_source_manifest"],
        "claims": [{
            "claim": "원문 계약이 등록되어 있습니다.", "claim_type": "CASE_FACT",
            "fact_status": "VERIFIED_FACT", "grounding_status": "SUPPORTED",
            "source_ids": ["E01_계약서.txt"],
        }],
        "missing_legal_issues": [], "missing_issues": [],
        "contradictions": [],
        # [STEP5-TEST-03 / Gemini] 실제 문서 Verifier가 요구하는
        # 질문 Coverage + 4개 일관성 점검을 완비한 경우만
        # 지지된 부분 답변을 CAUTIONARY로 보존할 수 있다.
        "required_question_coverage": True,
        "question_coverage": [{"question": "반환 여부", "answered": True}],
        "consistency_checks": {
            name: {"passed": True, "reason": "문서 대조 완료"}
            for name in ("opening_conclusion", "timeline", "expressed_intent", "provenance")
        },
        **changes,
    }
    return {**document_state, "verification_result": result,
            "verification_no_progress": True, "revision_count": 1}


def finish_without_external_dependencies(state):
    with patch.object(dc, "validate_document_snapshot"), \
         patch("ai_legal_helper.utils.text_formatter.expand_evidence_citations",
               side_effect=lambda draft, _sources: draft), \
         patch("ai_legal_helper.utils.text_formatter.extract_all_registered_evidence_sources",
               return_value=[]):
        return dc.finish_answer(state)


def test_early_finalize_does_not_promote_unanswered_core_question(document_state):
    """지원되는 사례사실 하나로 질문 핵심 미답변을 PASS 승격하면 안 된다."""
    state = fallback_state(document_state, question_coverage=[
        {"question": "반환 청구", "answered": False, "answerable": True},
    ])
    out = finish_without_external_dependencies(state)
    assert out["final_disposition"] == "WITHHELD"
    assert out["verification_result"]["status"] == "INSUFFICIENT"


def test_early_finalize_preserves_actual_disclosed_partial_answer(document_state):
    """정확하게 한계가 고지된 근거 있는 부분 답변은 기존 CAUTIONARY를 유지."""
    state = fallback_state(document_state, question_coverage=[
        {"question": "반환 청구", "answered": False, "answerable": False,
         "limitation_disclosed": True,
         "limitation_statement": "추가 법률요건의 확인이 필요합니다."},
    ])
    out = finish_without_external_dependencies(state)
    assert out["final_disposition"] == "CAUTIONARY"
    assert out["verification_result"]["status"] == "PASS"
    assert out["final_answer"] == document_state["draft_answer"]


def test_early_finalize_bans_failed_law_subsumption(document_state):
    """[방법 2: 참고 신호 전환] 포섭 감사는 참고/경고 신호이므로 단순 감사 결함만으로 초안을 WITHHELD로 전면 폐기하지 않고 CAUTIONARY 보존한다."""
    state = fallback_state(document_state, application_audit={
        "failed_claims": 1,
        "findings": [{"claim_index": 1, "reason_codes": ["FACT_PREMISE_UNGROUNDED"]}],
    })
    assert finish_without_external_dependencies(state)["final_disposition"] == "CAUTIONARY"


def test_early_finalize_bans_failed_timeline_consistency(document_state):
    state = fallback_state(document_state, consistency_checks={
        "timeline": {"passed": False, "reason": "선후 검토 불일치"},
    })
    assert finish_without_external_dependencies(state)["final_disposition"] == "WITHHELD"


def test_early_finalize_bans_invalid_citation(document_state):
    state = fallback_state(document_state, citation_audit={
        "unverified_citations": ["PRECEDENT:FAKE"],
    })
    assert finish_without_external_dependencies(state)["final_disposition"] == "WITHHELD"


def test_early_finalize_bans_unsupported_case_fact(document_state):
    state = fallback_state(document_state)
    state["verification_result"]["claims"].append({
        "claim": "입증되지 않은 지급사실", "claim_type": "CASE_FACT",
        "fact_status": "VERIFIED_FACT", "grounding_status": "UNSUPPORTED",
        "source_ids": [],
    })
    assert finish_without_external_dependencies(state)["final_disposition"] == "WITHHELD"


def test_early_finalize_bans_missing_mandatory_coverage(document_state):
    """Verifier가 질문별 coverage 정보를 반환하지 않았는데도 PASS하지 못한다."""
    state = fallback_state(document_state, question_coverage=[])
    assert finish_without_external_dependencies(state)["final_disposition"] == "WITHHELD"


def test_early_finalize_bans_missing_mandatory_consistency(document_state):
    """임의 주장의 SUPPORTED만으로 시간/의사표시/출처 대조 누락을 숨길 수 없다."""
    state = fallback_state(document_state, consistency_checks={})
    assert finish_without_external_dependencies(state)["final_disposition"] == "WITHHELD"
