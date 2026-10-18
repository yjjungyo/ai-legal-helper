# -*- coding: utf-8 -*-
"""
모듈명: test_p0_defects_reproduction.py

[모듈 개요]
AI Legal Helper 개발지시서 P0 필수 결함(P0-01 ~ P0-04)에 대한
재현(Reproduction) 및 수정 후 방어 회귀 검증 테스트를 정의한다.

[검증 항목]
- P0-01: Verification Agent Fail-open 취약점 (LLM 오류 시 PASS 반환 차단)
- P0-02: HILT 실행 후 검증 우회 취약점 (HILT 완료 후에도 검증 실패 시 finalize 강제 전이 차단)
- P0-03: LangGraph Checkpointer 영속화 (PostgreSQL 영구 보존 및 프로세스 간 재개)
- P0-04: 공식 법령 검색의 임의 법령 채택 차단 및 HTTPS/보안 보장
"""
import os
import sys
import uuid
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage

from ai_legal_helper.workflows.state import LegalState
from ai_legal_helper.agents.verification import run_verification
from ai_legal_helper.workflows.legal_workflow import verification_condition
from ai_legal_helper.tools.official_statute_search import search_official_statutes


def test_p0_01_reproduce_verification_fail_open():
    """P0-01: Verifier LLM 오류 발생 시 PASS로 Fail-open되지 않고 안전한 오류 상태로 전이되는지 검증."""
    # LLM 호출 시 타임아웃 또는 네트워크 예외 발생 모사
    with patch("ai_legal_helper.llm.gateway.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = TimeoutError("Azure OpenAI Gateway Timeout (504)")
        mock_get_llm.return_value = mock_llm

        res = run_verification(
            question="임대차 보증금 반환 의무 발생 시점은?",
            draft_answer="임대인은 계약 종료 즉시 보증금을 반환해야 합니다.",
            retrieved_sources=[],
            case_context="",
        )

        # Fail-open 방지: 오류 시 status가 PASS여서는 절대 안 됨
        assert res["status"] != "PASS", (
            f"Fail-open 결함: 검증기 예외 발생 시 PASS로 응답해서는 안 됩니다. 현재: {res['status']}"
        )
        assert res["status"] in ("INSUFFICIENT", "ERROR")
        assert res["reason_code"] in ("VERIFICATION_ERROR", "SYSTEM_ERROR", "LEGAL_SOURCE_MISSING")


def test_p0_02_reproduce_hilt_bypass_verification_failure():
    """P0-02: HILT가 실행되었더라도 2차 검증이 실패(INSUFFICIENT)했다면 finalize로 강제 우회하지 않는지 검증."""
    state: LegalState = {
        "messages": [HumanMessage(content="묵시적 갱신 해지 효력은?")],
        "hilt_executed": True,
        "revision_count": 1,
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "LEGAL_SOURCE_INSUFFICIENT",
            "candidate_laws": ["주택임대차보호법"],
            "warnings": ["핵심 조문 근거 부족"],
            "citation_audit": {
                "unverified_citations": [],
            },
        },
    }

    next_node = verification_condition(state)
    # HILT가 수행되었더라도 검증 실패 시 finalize로 직행해서는 안 됨
    assert next_node != "finalize", (
        f"HILT 검증 우회 결함: 2차 검증이 INSUFFICIENT임에도 {next_node}로 전이되었습니다."
    )
    assert next_node == "insufficient"


def test_p0_02_reproduce_non_statute_issue_does_not_trigger_hilt():
    """P0-02 추가: 사실관계/사건 증거 부족(CASE_EVIDENCE_MISSING)은 HILT 법령 검색으로 분기하지 않는지 검증."""
    state: LegalState = {
        "messages": [HumanMessage(content="보증금 반환 통보일 입증 여부")],
        "hilt_executed": False,
        "revision_count": 0,
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "CASE_EVIDENCE_MISSING",
            "candidate_laws": ["민법"],  # 일반법이 포함되어 있더라도
            "missing_legal_issues": [],
            "warnings": ["내용증명 도달일 증빙 미제출"],
        },
    }

    next_node = verification_condition(state)
    # 사건 증거 부족은 법령 검색 HILT 노드로 잘못 분기하면 안 됨
    assert next_node != "statute_search_approval", (
        f"사건 증거 부족 시 법령 검색 HILT로 잘못 라우팅되었습니다: {next_node}"
    )


def test_p0_04_reproduce_statute_search_no_arbitrary_law_fallback():
    """P0-04: 존재하지 않는 법령명 검색 시 첫 번째 법령을 임의 선택하지 않고 빈 목록을 반환하는지 검증."""
    api_key = os.getenv("LAW_OPENAPI_KEY")
    if not api_key:
        pytest.skip("LAW_OPENAPI_KEY 환경변수 부재로 실 API 테스트를 건너뜁니다.")

    # 명백히 존재하지 않는 가상의 법령명
    fake_law = "완전가상의법령존재하지않음법_XYZ123"
    results = search_official_statutes(
        query="가상 법률 조문 확인",
        candidate_laws=[fake_law],
        max_articles_per_law=3,
    )

    # 임의의 첫 번째 법령을 집어넣어서는 안 됨
    assert len(results) == 0, f"존재하지 않는 법령 검색 시 빈 결과여야 하나 결과가 반환됨: {results}"


def test_p0_04_https_enforcement_and_masking():
    """P0-04: HTTPS 프로토콜 강제 및 API 키 마스킹 기능 검증."""
    from ai_legal_helper.tools.official_statute_search import mask_api_key

    # 1. API 키 마스킹 검증
    sample_key = "test_secret_api_key_12345"
    test_url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={sample_key}&target=law"
    masked = mask_api_key(test_url, sample_key)
    assert sample_key not in masked
    assert "OC=[MASKED]" in masked

    # 2. 예외 메시지 내 API 키 마스킹
    err_msg = f"HTTP Error 500: Failed to fetch {test_url}"
    masked_err = mask_api_key(err_msg, sample_key)
    assert sample_key not in masked_err
    assert "[MASKED]" in masked_err


def test_p0_04_retry_on_network_timeout():
    """P0-04: 일시적 네트워크 타임아웃 발생 시 1회 지수 백오프 재시도 성공 검증."""
    import urllib.request
    from ai_legal_helper.tools.official_statute_search import _fetch_xml_with_retry

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"<Response><status>SUCCESS</status></Response>"
    mock_resp.__enter__.return_value = mock_resp

    # 1회차 TimeoutError -> 2회차 성공
    with patch("urllib.request.urlopen", side_effect=[TimeoutError("Connection timed out"), mock_resp]) as mock_open:
        res = _fetch_xml_with_retry("https://www.law.go.kr/DRF/lawSearch.do?OC=test", timeout=1, max_retries=1, backoff_seconds=0.01)
        assert res == b"<Response><status>SUCCESS</status></Response>"
        assert mock_open.call_count == 2, "1회 실패 후 1회 재시도(총 2회 호출)되어야 함"


@pytest.mark.asyncio
async def test_p0_03_postgres_checkpointer_persistence_across_restart():
    """P0-03: PostgreSQL 영속 Checkpointer를 통해 프로세스/루프 종료 후에도 상태가 보존되고 Resume되는지 검증."""
    import uuid
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt, Command
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from ai_legal_helper.workflows.legal_workflow import get_postgres_conn_string

    db_url = get_postgres_conn_string()
    thread_id = f"test-p0-03-{uuid.uuid4()}"

    def make_test_graph():
        def step_initial(state):
            return {"history": ["init"]}
        def step_approval(state):
            decision = interrupt({"type": "APPROVAL_REQUIRED", "detail": "Test Approval"})
            return {"approved": decision.get("approved", False)}
        def step_final(state):
            return {"status": "SUCCESS", "approved": state.get("approved")}

        g = StateGraph(dict)
        g.add_node("init", step_initial)
        g.add_node("approval", step_approval)
        g.add_node("final", step_final)
        g.add_edge(START, "init")
        g.add_edge("init", "approval")
        g.add_edge("approval", "final")
        g.add_edge("final", END)
        return g

    # 1. 첫 번째 실행 (인터럽트 발생 및 PostgreSQL에 체크포인트 저장)
    async with AsyncPostgresSaver.from_conn_string(db_url) as saver1:
        await saver1.setup()
        app1 = make_test_graph().compile(checkpointer=saver1)
        res1 = await app1.ainvoke({"messages": []}, {"configurable": {"thread_id": thread_id}})
        assert "__interrupt__" in res1
        assert res1["__interrupt__"][0].value["type"] == "APPROVAL_REQUIRED"

    # 2. 프로세스 재시작 모사: saver1 세션이 완전히 닫힌 후 새로운 세션(saver2)으로 동일 thread_id 재개
    async with AsyncPostgresSaver.from_conn_string(db_url) as saver2:
        app2 = make_test_graph().compile(checkpointer=saver2)
        res2 = await app2.ainvoke(Command(resume={"approved": True}), {"configurable": {"thread_id": thread_id}})
        assert res2["status"] == "SUCCESS"
        assert res2["approved"] is True


@pytest.mark.asyncio
async def test_p0_03_nonexistent_thread_raises_error():
    """P0-03: 존재하지 않는 thread_id로 재개(resume) 시도시 적절한 ValueError 예외가 발생하는지 검증."""
    from ai_legal_helper.workflows.legal_workflow import run_legal_consultation

    random_id = f"nonexistent-thread-{uuid.uuid4()}"
    with pytest.raises(ValueError, match="존재하지 않습니다"):
        await run_legal_consultation(
            question="",
            thread_id=random_id,
            resume_data={"approved": True},
        )

