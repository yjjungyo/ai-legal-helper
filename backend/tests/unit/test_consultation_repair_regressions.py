"""금액 검산·하위법령 연계·중복 판례·반복 결함의 오프라인 회귀 테스트.

가상 자료와 대역만 사용하며 실제 상담 기록·외부 API·모델을 변경하거나 호출하지 않는다.
"""

from copy import deepcopy
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest

from ai_legal_helper.rag.grounding_context import format_grounding_sources
from ai_legal_helper.workflows.monetary_checks import invalid_monetary_equations
from ai_legal_helper.workflows.verification_progress import same_unresolved_applications


@pytest.mark.parametrize("equation", [
    "35,000,000원 + 2,400,000원 = 37,400,000원",
    "2억원 - 1.65억원 + 240만원 = 3740만원",
    "**3500만원** + **240만원** = **3740만원**",
])
def test_correct_equations(equation):
    """원화 단위·강조 표기가 달라도 맞는 계산은 거부하지 않는다."""
    assert invalid_monetary_equations(equation) == []


def test_wrong_equation_and_payment_statement_distinguished():
    """명시적인 오산만 검출하고 지급 약속의 법적 의미는 추론하지 않는다."""
    assert invalid_monetary_equations("3500만원 + 240만원 = 2640만원")
    assert invalid_monetary_equations("1억원을 다음 달 지급하겠다고 합니다.") == []


def test_arithmetic_error_repairs_before_model_verification(monkeypatch):
    """오산 초안은 원문 명세를 확인한 뒤 모델 검증을 생략하고 수정으로 보낸다."""
    from ai_legal_helper.workflows import document_consultation as workflow

    sources = [{"source_id": "doc", "source_type": "CASE_EVIDENCE", "content": "금액 원문"}]
    monkeypatch.setattr(workflow, "document_sources", lambda state: sources)
    monkeypatch.setattr(workflow, "validate_document_snapshot", lambda state: None)
    verifier = Mock(side_effect=AssertionError("금액 오류를 모델에 보내면 안 됩니다"))
    monkeypatch.setattr("ai_legal_helper.agents.verification.run_verification", verifier)
    state = {"question": "합계는?", "draft_answer": "3500만원 + 240만원 = 2640만원",
             "answer_source_manifest": format_grounding_sources(sources)[1]}
    result = workflow.verify_answer(state)
    assert result["verification_result"]["status"] == "REVISE"
    assert workflow.next_verification_step({**state, **result}) == "revise"
    verifier.assert_not_called()


def test_delegated_local_laws_use_existing_issue_without_inventing_articles(monkeypatch):
    """실제 위임 문구가 있으면 같은 쟁점으로 하위법령을 조회한다."""
    from ai_legal_helper.workflows import document_search as search

    lookup = Mock(return_value=[{"source_id": "related", "content": "확보된 실제 조문"}])
    monkeypatch.setattr(search, "_retrieve_from_local_index", lookup)
    docs = search._retrieve_delegated_local_sources(
        "가상관리법", [{"content": "세부 사항은 대통령령으로 정한다."}], "반환 의무", "2025-01-01",
    )
    assert docs[0]["source_id"] == "related"
    assert lookup.call_args.kwargs == {
        "law_name": "가상관리법 시행령", "articles": [], "query": "반환 의무",
        "as_of_date": "2025-01-01", "limit": 2,
    }
    lookup.reset_mock()
    assert search._retrieve_delegated_local_sources("가상법", [{"content": "일반 본문"}], "쟁점", None) == []
    assert search._retrieve_delegated_local_sources("가상법 시행령", [{"content": "대통령령"}], "쟁점", None) == []
    lookup.assert_not_called()


def test_api_aliases_do_not_duplicate_same_decision(monkeypatch):
    """API 일련번호가 다른 같은 판결은 하나로 합치고 다른 본문은 유지한다."""
    from ai_legal_helper.tools import official_precedent_search as search

    monkeypatch.setenv("LAW_OPENAPI_KEY", "offline-test")
    monkeypatch.setattr(search, "parse_precedent_detail", lambda raw, expected_id: {
        "source_id": f"PRECEDENT:{expected_id}", "source_type": "PRECEDENT",
        "court": "가상법원", "case_number": "2020가단1", "decision_date": "2020-01-01",
        "content": "동일한 판결 원문" if expected_id in ("1", "2") else "별도 내용",
    })

    def fetch(url, **kwargs):
        """목록 세 건과 판결 상세 응답을 외부 요청 없이 제공한다."""
        if "ID" in parse_qs(urlparse(url).query):
            return b"detail"
        return b'<PrecSearch><prec id="1"/><prec id="2"/><prec id="3"/></PrecSearch>'

    sources = search.search_official_precedents(["반환채무 법적성질"], fetcher=fetch)
    assert [source["source_id"] for source in sources] == ["PRECEDENT:1", "PRECEDENT:3"]
    # 기존 이력에 두 ID가 이미 있더라도 인용 ID를 지우지 않고 본문만 공유한다.
    aliases = [sources[0], {**sources[0], "source_id": "PRECEDENT:2"}]
    rendered, manifest = format_grounding_sources(aliases, compact_repeated_bodies=True)
    assert rendered.count("동일한 판결 원문") == 1
    assert manifest["source_count"] == 2


def test_repeated_failure_requires_same_effect_sources_and_no_improvement():
    """같은 법률효과의 미지원 상태만 비교하며 새 근거와 개선을 차단하지 않는다."""
    before = {"status": "REVISE", "source_manifest": {"content_sha256": "same"},
              "claims": [{"claim": "기존 표현", "claim_type": "LEGAL_APPLICATION",
                          "grounding_status": "UNSUPPORTED", "source_ids": ["a", "b"]}],
              "application_checks": [{"claim": "기존 표현", "legal_effect": "반환청구권"}]}
    after = deepcopy(before)
    after["claims"][0]["claim"] = "문구만 바뀐 표현"
    after["application_checks"][0]["claim"] = "문구만 바뀐 표현"
    assert same_unresolved_applications(before, after)
    after["source_manifest"]["content_sha256"] = "new"
    assert not same_unresolved_applications(before, after)
    after["source_manifest"]["content_sha256"] = "same"
    after["application_checks"][0]["legal_effect"] = "다른 법률효과"
    assert not same_unresolved_applications(before, after)
    after["claims"][0]["grounding_status"] = "SUPPORTED"
    assert not same_unresolved_applications(before, after)
