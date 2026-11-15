# -*- coding: utf-8 -*-
"""법제처 판례 list->detail + HITL + 검색 경로의 오프라인 회귀검증.

외부 OpenAPI 호출/LLM 호출은 절대 하지 않고 XML fixture와 mock으로
공식 API 응답·오류·승인 상태를 재현한다. 실API E2E는 사용자가 실행한다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

import pytest

from ai_legal_helper.tools.official_precedent_search import (
    normalize_precedent_query, parse_precedent_detail, search_official_precedents,
)
from ai_legal_helper.workflows.document_search import (
    pending_precedent_searches, pending_searches, precedent_search_is_approved,
    execute_document_search,
)
from ai_legal_helper.workflows.document_consultation import next_verification_step
from ai_legal_helper.workflows.legal_workflow import statute_search_result_condition


QUESTION = (
    "임대인의 자녀 3명이 상속인입니다. 상속재산분할 소송이 끝날 때까지 "
    "보증금을 지급할 수 없다고 합니다. 보증금 반환 채무는 지분대로 "
    "나눠서 청구해야 하나요, 아니면 누구에게나 전액 청구할 수 있나요?"
)
QUERY = "임대차보증금 반환채무 불가분채무"


def _list_xml(seq="226751", number="2015다59801"):
    return (
        f'<PrecSearch><totalCnt>1</totalCnt>'
        f'<prec id="{seq}"><판례일련번호>{seq}</판례일련번호>'
        f'<사건번호>{number}</사건번호><법원명>대법원</법원명></prec>'
        f'</PrecSearch>'
    ).encode("utf-8")


def _detail_xml(seq="226751", number="2015다59801", *,
                body="공동임대인의 채무가 불가분채무인지 검토한다.", date="20210128"):
    root = ET.Element("PrecInfo")
    fields = {
        "판례정보일련번호": seq,
        "사건명": "보증금반환",
        "사건번호": number,
        "선고일자": date,
        "법원명": "대법원",
        "판시사항": "공동임대인의 보증금반환채무 성질",
        "판결요지": "보증금 반환채무의 법적 성질 및 내부 분담 관계",
        "판례내용": body,
    }
    for key, value in fields.items():
        ET.SubElement(root, key).text = value
    return ET.tostring(root, encoding="utf-8")


def _approved_state(*, source_type="PRECEDENT", law_name="", query=QUERY):
    item = {
        "source_type": source_type,
        "law_name": law_name,
        "articles": [],
        "issue": "공동상속인의 반환채무 법적 성질 및 채권자에 대한 대외적 책임",
        "question_part": "보증금 반환 채무는 지분대로 나눠서 청구해야 하나요",
        "precedent_query": query,
    }
    return {
        "question": QUESTION,
        "resolved_query": QUESTION,
        "answer_mode": "DOCUMENT_GROUNDED",
        "draft_answer": "상속인의 책임을 검토합니다.",
        "verification_result": {
            "status": "REVISE",
            "reason_code": "LEGAL_SOURCE_INSUFFICIENT",
            "legal_search_requests": [item],
        },
        "retrieved_sources": [],
        "statute_search_count": 0,
        "statute_search_history": [],
        "precedent_search_history": [],
        "approval_status": "APPROVED",
        "approved_statute_laws": ["민법"] if law_name else [],
        "approved_precedent_search": True,
        "approved_precedent_queries": [query],
        "auto_approve_statute_search": False,
    }


def test_search_query_only_accepts_bounded_general_legal_terms():
    assert normalize_precedent_query(QUERY) == QUERY
    assert normalize_precedent_query("임대차보증금 010-1234-5678 불가분채무") == ""
    assert normalize_precedent_query("임차인 이름 이진우 2026-03-01") == ""
    assert normalize_precedent_query("공동상속인 보증금 반환채무가 누구에게나 전액 청구되나요?") == ""
    assert normalize_precedent_query("임대차보증금") == ""
    assert normalize_precedent_query(" ") == ""


def test_precedent_list_and_detail_are_separate_verified_requests(monkeypatch):
    monkeypatch.setenv("LAW_OPENAPI_KEY", "local-test-key")
    seen = []

    def fetch(url, **kwargs):
        params = parse_qs(urlparse(url).query)
        seen.append((urlparse(url).path, params, kwargs))
        assert kwargs["api_key"] == "local-test-key"
        assert params["target"] == ["prec"] and params["type"] == ["XML"]
        if "lawSearch" in url:
            assert params["search"] == ["2"]
            assert params["query"] == [QUERY]
            return _list_xml()
        assert params["ID"] == ["226751"]
        return _detail_xml()

    metrics = {}
    docs = search_official_precedents([QUERY], fetcher=fetch, diagnostic=metrics)
    assert len(seen) == 2
    assert len(docs) == 1
    doc = docs[0]
    assert doc["source_type"] == "PRECEDENT"
    assert doc["case_number"] == "2015다59801"
    assert doc["decision_date"] == "2021-01-28"
    assert doc["court"] == "대법원"
    assert doc["source_id"] == "PRECEDENT:226751"
    assert doc["source_url"].endswith("precSeq=226751")
    assert "판시사항" in doc["content"] and "판결요지" in doc["content"]
    assert metrics["status"] == "SUCCESS" and metrics["request_count"] == 2


def test_detail_id_mismatch_is_not_an_official_source():
    assert parse_precedent_detail(_detail_xml(seq="999999"), expected_id="226751") is None


def test_detail_missing_case_number_is_rejected():
    assert parse_precedent_detail(_detail_xml(number=""), expected_id="226751") is None


def test_detail_invalid_decision_date_is_rejected():
    assert parse_precedent_detail(_detail_xml(date="20261399"), expected_id="226751") is None


def test_detail_without_any_legal_text_is_rejected():
    root = ET.fromstring(_detail_xml())
    for field in ("판시사항", "판결요지", "판례내용"):
        root.find(field).text = ""
    assert parse_precedent_detail(ET.tostring(root), expected_id="226751") is None


def test_broken_xml_does_not_fabricate_precedent(monkeypatch):
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-key")
    results = search_official_precedents([QUERY], fetcher=lambda *_args, **_kw: b"<bad", diagnostic={})
    assert results == []


def test_absent_api_key_blocks_network(monkeypatch):
    monkeypatch.delenv("LAW_OPENAPI_KEY", raising=False)
    called = []
    res = search_official_precedents([QUERY], fetcher=lambda *_args, **_kw: called.append(1))
    assert res == [] and not called


def test_repeated_list_ids_only_fetch_once(monkeypatch):
    monkeypatch.setenv("LAW_OPENAPI_KEY", "test-key")
    list_bytes = b'<PrecSearch><prec id="226751"/><prec id="226751"/></PrecSearch>'
    calls = []

    def fetch(url, **_kwargs):
        calls.append(url)
        return list_bytes if "lawSearch" in url else _detail_xml()

    found = search_official_precedents([QUERY, QUERY], fetcher=fetch)
    assert len(found) == 1
    assert sum("lawService" in call for call in calls) == 1


def test_pending_precedent_type_is_explicit_and_statute_does_not_consume_it():
    state = _approved_state()
    precs = pending_precedent_searches(state)
    assert len(precs) == 1
    assert precs[0]["precedent_query"] == QUERY
    assert pending_searches(state) == []


def test_both_creates_independent_statute_and_precedent_requests():
    state = _approved_state(source_type="BOTH", law_name="민법")
    assert len(pending_searches(state)) == 1
    assert len(pending_precedent_searches(state)) == 1


def test_statute_only_does_not_search_for_precedent():
    state = _approved_state(source_type="STATUTE", law_name="민법")
    assert len(pending_precedent_searches(state)) == 0
    assert len(pending_searches(state)) == 1


def test_unapproved_or_wrong_scope_never_fetches_external_precedents(monkeypatch):
    state = _approved_state()
    state["approval_status"] = "REJECTED"
    assert not precedent_search_is_approved(state, pending_precedent_searches(state))
    assert next_verification_step(state) == "statute_search_approval"
    state["approval_status"] = "APPROVED"
    state["approved_precedent_queries"] = ["근로기준법 해고예고 위반"]
    assert not precedent_search_is_approved(state, pending_precedent_searches(state))
    with patch("ai_legal_helper.tools.official_precedent_search.search_official_precedents") as api:
        result = execute_document_search(state)
        api.assert_not_called()
    assert not result.get("precedent_search_results")


def test_case_party_name_in_query_is_blocked_even_without_digit_or_email():
    """한국어 성명은 중앙 PII 정규식이 완벽히 잡지 못하므로 등록 당사자명과 대조한다."""
    state = _approved_state(query="공동상속 이진우 보증금 반환채무")
    state["approved_precedent_queries"] = ["공동상속 이진우 보증금 반환채무"]
    state["case_evidence_briefing"] = {
        "parties": [{"name": "이진우", "role": "상속인"}],
    }
    assert pending_precedent_searches(state) == []


def test_precedent_only_can_be_searched_without_statute_name():
    state = _approved_state()
    assert next_verification_step(state) == "execute_statute_search"


def test_new_precedent_is_merged_and_routes_to_reanalysis_without_new_statute(monkeypatch):
    state = _approved_state()
    source = parse_precedent_detail(_detail_xml(), expected_id="226751")
    monkeypatch.setattr(
        "ai_legal_helper.tools.official_precedent_search.search_official_precedents",
        lambda queries, **kwargs: [source],
    )
    result = execute_document_search(state)
    assert result["statute_search_results"] == []
    assert len(result["precedent_search_results"]) == 1
    assert result["retrieved_sources"][0]["source_id"] == "PRECEDENT:226751"
    assert result["statute_search_status"] == "OFFICIAL_SUCCESS"
    assert result["precedent_search_history"]
    next_state = {**state, **result}
    assert statute_search_result_condition(next_state) == "re_analyze"
    assert pending_precedent_searches(next_state) == []


def test_second_case_law_search_without_new_result_does_not_invent_success(monkeypatch):
    state = _approved_state()
    monkeypatch.setattr(
        "ai_legal_helper.tools.official_precedent_search.search_official_precedents",
        lambda *_args, **_kwargs: [],
    )
    result = execute_document_search(state)
    assert result["precedent_search_results"] == []
    assert result["statute_search_status"] == "NOT_FOUND"
    assert not any(s.get("source_type") == "PRECEDENT" for s in result.get("retrieved_sources", []))


def test_no_new_request_after_history_hash():
    state = _approved_state()
    req = pending_precedent_searches(state)[0]
    state["precedent_search_history"] = [req["key"]]
    assert pending_precedent_searches(state) == []

def test_unverified_case_number_in_case_record_cannot_pass_citation_audit():
    from ai_legal_helper.agents.verification import audit_citations_and_claims
    claim = "대법원 2015다59801 판례에 따라 반환채무를 검토합니다."
    audit = audit_citations_and_claims(
        claim,
        retrieved_sources=[{
            "source_id": "E01_계약서.txt",
            "source_type": "CASE_EVIDENCE",
            "content": "임차인이 2015다59801을 참고하여 청구하겠다고 진술했다.",
            "file": "E01_계약서.txt",
        }],
        case_context="과거 사용자 질문에도 2015다59801 판례를 언급한 적이 있음",
    )
    assert "PRECEDENT:2015다59801" in audit["rejected_citation_ids"]
    assert audit["rejection_reasons"]["PRECEDENT:2015다59801"] == "UNVERIFIED_PRECEDENT_CASE_NUMBER"


def test_verified_precedent_source_allows_case_number_citation():
    from ai_legal_helper.agents.verification import audit_citations_and_claims
    source = parse_precedent_detail(_detail_xml(), expected_id="226751")
    audit = audit_citations_and_claims(
        "대법원 2015다59801 판결은 해당 보증금 반환채무의 성질을 검토합니다.",
        retrieved_sources=[source],
    )
    assert "PRECEDENT:2015다59801" in audit["validated_citation_ids"]
    assert "PRECEDENT:2015다59801" not in audit["rejected_citation_ids"]


def test_unrelated_statute_mention_does_not_validate_precedent_case_number():
    from ai_legal_helper.agents.verification import audit_citations_and_claims
    audit = audit_citations_and_claims(
        "대법원 2015다59801 판결을 참고합니다.",
        retrieved_sources=[{
            "source_id": "STATUTE:generic",
            "source_type": "STATUTE",
            "statute_name": "민법",
            "article": "제411조",
            "content": "참조판례: 2015다59801",
        }],
    )
    assert "PRECEDENT:2015다59801" in audit["rejected_citation_ids"]
