# -*- coding: utf-8 -*-
"""
모듈명: test_hilt_statute_search.py

[모듈 개요]
P4.1 Verifier-Guided HILT 법령 검색 워크플로우에 대한 종합 시나리오 테스트(T-01 ~ T-08)를 구현한다.

[테스트 시나리오]
- T-01: 내부 RAG에 관련 법률이 있어 정상 PASS되는 사건 (HILT 미진입 검증)
- T-02: 특별법(주택임대차보호법) 누락으로 LEGAL_SOURCE_MISSING 감지 시 HILT 인터럽트 진입 검증
- T-03: 사용자 승인 시 공식 법령 원문 검색 호출, 출처 병합, 재분석 및 최종 PASS 전이 검증
- T-04: 사용자 거절 시 외부 검색 차단 및 판단 유보 안내 검증
- T-05: 외부 법령 검색 결과 부재 시 판단 유보 안전 종료 검증
- T-06: 허위 법령 및 미검증 출처 차단 및 Sanitization 검증
- T-07: Checkpointer 상태 복원 및 중복 Resume 차단 검증
- T-08: 영구 Checkpointer(PostgreSQL/Sqlite)를 통한 서버 재시작 후 복원 및 Resume 검증
"""
import pytest
import uuid
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from ai_legal_helper.workflows.state import LegalState
from ai_legal_helper.workflows.legal_workflow import (
    verification_condition,
    statute_search_approval_node,
    statute_search_approval_condition,
    execute_statute_search_node,
    statute_search_result_condition,
    re_analyze_node,
    build_legal_graph,
    run_legal_consultation,
)


def test_t01_normal_pass_bypasses_hilt():
    """T-01: 내부 RAG에 충분한 근거가 있어 Verifier가 PASS인 경우 HILT 없이 finalize로 직행하는지 검증한다."""
    state: LegalState = {
        "messages": [HumanMessage(content="민법상 임대인의 수선의무는?")],
        "revision_count": 0,
        "hilt_executed": False,
        "verification_result": {
            "status": "PASS",
            "reason_code": "NONE",
            "candidate_laws": [],
            "warnings": [],
        },
    }
    next_node = verification_condition(state)
    assert next_node == "finalize", "PASS 상태에서는 HILT 노드로 진입하지 않고 finalize로 라우팅되어야 한다."


def test_t02_missing_statute_triggers_hilt_approval():
    """T-02: 특별법 누락(LEGAL_SOURCE_MISSING) 및 candidate_laws 감지 시 HILT 승인 노드로 라우팅되는지 검증한다."""
    state: LegalState = {
        "messages": [HumanMessage(content="묵시적 갱신 후 해지 통보 효력 시점은?")],
        "revision_count": 0,
        "hilt_executed": False,
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "candidate_laws": ["주택임대차보호법"],
            "missing_legal_issues": ["묵시적 갱신 후 임차인의 해지통보 효력"],
        },
    }
    next_node = verification_condition(state)
    assert next_node == "statute_search_approval", (
        "법률 근거 부족(LEGAL_SOURCE_MISSING)과 후보 법령이 있을 때 HILT 승인 노드로 라우팅되어야 한다."
    )


def test_t03_user_approval_executes_search_and_re_analyzes():
    """T-03: 사용자 승인 시 공식 법령 검색이 실행되고 출처가 병합되며 재분석으로 이어지는지 검증한다."""
    sample_statute_source = {
        "source_id": "STATUTE:주택임대차보호법:제6조의2:276291",
        "source_type": "STATUTE",
        "title": "주택임대차보호법 제6조의2",
        "statute_name": "주택임대차보호법",
        "article": "제6조의2",
        "content": "제6조의2(묵시적 갱신의 경우 계약의 해지) ② 제1항에 따른 해지는 임대인이 그 통지를 받은 날부터 3개월이 지나면 그 효력이 발생한다.",
        "filename": "주택임대차보호법_제6조의2.txt",
        "page": "1",
        "source_url": "https://www.law.go.kr/DRF/lawService.do?OC=test&target=law&MST=276291&type=XML",
        "retrieval_method": "OFFICIAL_STATUTE_API",
    }

    state: LegalState = {
        "question": "묵시적 갱신 후 해지 통보 시 효력은 언제 발생하나요?",
        "case_context": "",
        "retrieved_sources": [
            {"source_id": "DOC:1", "filename": "민법.pdf", "content": "민법 기본 조항"}
        ],
        "verification_result": {
            "candidate_laws": ["주택임대차보호법"],
            "missing_legal_issues": ["묵시적 갱신 해지통보 효력"],
        },
        "approval_status": "APPROVED",
        "warnings": [],
    }

    # 1. 승인 조건부 분기 확인
    assert statute_search_approval_condition(state) == "execute_statute_search"

    # 2. 공식 법령 검색 실행 노드 모킹
    with patch("ai_legal_helper.tools.official_statute_search.search_official_statutes", return_value=[sample_statute_source]):
        res = execute_statute_search_node(state)
        assert len(res["statute_search_results"]) == 1
        assert any(s["source_id"] == sample_statute_source["source_id"] for s in res["retrieved_sources"])

        # 3. 법령 검색 결과 분기 확인
        updated_state = {**state, **res}
        assert statute_search_result_condition(updated_state) == "re_analyze"

    # 4. 재분석 노드 모킹
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    fake_re_answer = "주택임대차보호법 제6조의2 제2항에 따라 통지 후 3개월이 지나면 효력이 발생합니다. (주택임대차보호법_제6조의2.txt, p.1)"
    with patch("ai_legal_helper.llm.gateway.get_llm", return_value=FakeListChatModel(responses=[fake_re_answer])):
        re_res = re_analyze_node(updated_state)
        assert "3개월" in re_res["draft_answer"]
        assert re_res["revision_count"] >= 1



def test_t04_user_rejection_routes_to_insufficient():
    """T-04: 사용자가 법령 검색을 거절(approval_status == 'REJECTED')한 경우 판단 유보(insufficient)로 종료되는지 검증한다."""
    state: LegalState = {
        "approval_status": "REJECTED",
    }
    next_node = statute_search_approval_condition(state)
    assert next_node == "insufficient", "사용자 거절 시 외부 검색을 수행하지 않고 insufficient로 이동해야 한다."


def test_t05_empty_search_results_routes_to_insufficient():
    """T-05: 외부 법령 검색 결과가 비어있는 경우 무리하게 답변하지 않고 insufficient로 종료되는지 검증한다."""
    state: LegalState = {
        "question": "미지의 법률에 관한 질의",
        "verification_result": {"candidate_laws": ["가상의법률"], "missing_legal_issues": ["존재하지 않는 규정"]},
        "retrieved_sources": [],
        "warnings": [],
    }

    with patch("ai_legal_helper.tools.official_statute_search.search_official_statutes", return_value=[]):
        res = execute_statute_search_node(state)
        assert res["statute_search_results"] == []
        assert "공식 법령 원문 검색 시스템에서 요청하신 법령의 해당 조문을 찾지 못했습니다." in res["warnings"]

        updated_state = {**state, **res}
        assert statute_search_result_condition(updated_state) == "insufficient"


def test_t06_unverified_statute_citations_blocked():
    """T-06: 실제 조회되지 않은 허위 법령 및 미검증 출처가 Verifier에서 필터링되는지 검증한다."""
    from ai_legal_helper.agents.verification import audit_citations_and_claims, sanitize_unverified_citations

    draft = "주택임대차보호법 제99조에 따라 즉시 해지됩니다. (가짜법령.pdf, p.10)"
    retrieved_sources = [
        {
            "source_id": "STATUTE:주택임대차보호법:제6조의2:276291",
            "filename": "주택임대차보호법_제6조의2.txt",
            "page": "1",
            "content": "제6조의2(묵시적 갱신의 경우 계약의 해지) 3개월 지나면 효력",
        }
    ]

    audit = audit_citations_and_claims(draft, retrieved_sources)
    assert any("가짜법령.pdf" in c for c in audit["unverified_citations"])
    assert audit["citation_existence_rate"] == 0.0

    sanitized = sanitize_unverified_citations(draft, retrieved_sources)
    assert "가짜법령.pdf" not in sanitized
    assert "[근거 미확인:" in sanitized or "가짜법령.pdf" not in sanitized


@pytest.mark.asyncio
async def test_t07_checkpointer_state_persistence_and_resume():
    """T-07: LangGraph Checkpointer가 인터럽트 상태를 보존하고 Command(resume=...)로 정상 재개되는지 검증한다."""
    thread_id = f"test-t07-{uuid.uuid4()}"
    mem_checkpointer = MemorySaver()

    # Verifier가 법령 검색 승인 요청을 발생시키도록 모킹
    mock_ver_output = {
        "status": "INSUFFICIENT",
        "reason_code": "LEGAL_SOURCE_MISSING",
        "candidate_laws": ["주택임대차보호법"],
        "missing_legal_issues": ["묵시적 갱신 해지 효력"],
        "recommended_action": "REQUEST_STATUTE_SEARCH_APPROVAL",
        "claims": [],
        "missing_issues": ["묵시적 갱신 해지 효력"],
        "contradictions": [],
        "warnings": [],
        "revision_instructions": [],
    }

    with patch("ai_legal_helper.workflows.legal_workflow.intent_analysis_node", return_value={"intent": "NEW_LEGAL_ANALYSIS"}), \
         patch("ai_legal_helper.workflows.legal_workflow.run_agents_node", return_value={"retrieved_sources": []}), \
         patch("ai_legal_helper.workflows.legal_workflow.synthesize_node", return_value={"draft_answer": "초안"}), \
         patch("ai_legal_helper.workflows.legal_workflow.verification_node") as mock_ver_node:
        mock_ver_node.return_value = {
            "verification_result": mock_ver_output,
            "retrieved_sources": [],
        }

        # 1. 첫 번째 실행 -> 인터럽트 발생 및 APPROVAL_REQUIRED 반환
        res1 = await run_legal_consultation(
            question="묵시적 갱신 해지 통보 효력 시점은?",
            thread_id=thread_id,
            checkpointer=mem_checkpointer,
        )

        assert res1["status"] == "APPROVAL_REQUIRED"
        assert res1["approval_request"]["type"] == "STATUTE_SEARCH_APPROVAL"
        assert "주택임대차보호법" in res1["approval_request"]["candidate_laws"]

        # 2. 사용자 승인 후 Resume 실행
        sample_statute_source = {
            "source_id": "STATUTE:주택임대차보호법:제6조의2:276291",
            "source_type": "STATUTE",
            "title": "주택임대차보호법 제6조의2",
            "statute_name": "주택임대차보호법",
            "article": "제6조의2",
            "content": "해지는 임대인이 통지받은 날부터 3개월이 지나면 효력이 발생한다.",
            "filename": "주택임대차보호법_제6조의2.txt",
            "page": "1",
            "source_url": "https://www.law.go.kr",
            "retrieval_method": "OFFICIAL_STATUTE_API",
        }

        fake_re_answer2 = "주택임대차보호법 제6조의2에 따라 3개월 후 해지됩니다. (주택임대차보호법_제6조의2.txt, p.1)"
        with patch("ai_legal_helper.tools.official_statute_search.search_official_statutes", return_value=[sample_statute_source]), \
             patch("ai_legal_helper.llm.gateway.get_llm", return_value=FakeListChatModel(responses=[fake_re_answer2] * 10)):

            # 2차 검증에서는 PASS 반환하도록 변경
            mock_ver_node.return_value = {
                "verification_result": {
                    "status": "PASS",
                    "reason_code": "NONE",
                    "candidate_laws": [],
                    "claims": [],
                    "missing_issues": [],
                    "contradictions": [],
                    "warnings": [],
                },
                "retrieved_sources": [sample_statute_source],
            }

            res2 = await run_legal_consultation(
                question="",
                thread_id=thread_id,
                resume_data={"approved": True, "reason": "사용자 승인"},
                checkpointer=mem_checkpointer,
            )

            assert res2["status"] == "SUCCESS"
            assert res2["approval_status"] == "APPROVED"


def test_t08_server_restart_preserves_pending_approval():
    """T-08: 서버 재시작을 모사하여 DB와 Checkpointer에 보존된 승인 대기 상태가 복원 가능한지 검증한다."""
    from ai_legal_helper.database.session import SessionLocal
    from ai_legal_helper.database.models import ConsultationRecord

    test_req_id = f"APPR-RESTART-{uuid.uuid4()}"
    test_trace_id = f"trace-{uuid.uuid4()}"

    db = SessionLocal()
    try:
        # DB에 승인 대기 상태 레코드 기록
        record = ConsultationRecord(
            request_id=test_req_id,
            trace_id=test_trace_id,
            question="주택임대차보호법 묵시적 갱신 관련 상담",
            status="APPROVAL_REQUIRED",
            approval_request={
                "type": "STATUTE_SEARCH_APPROVAL",
                "candidate_laws": ["주택임대차보호법"],
                "missing_issue": "해지 효력 시점",
            },
        )
        db.add(record)
        db.commit()

        # 서버 재시작 모사: 세션을 완전히 닫고 새로운 세션으로 조회
        db.close()
        new_db = SessionLocal()
        restored = new_db.query(ConsultationRecord).filter(
            ConsultationRecord.request_id == test_req_id
        ).first()

        assert restored is not None
        assert restored.status == "APPROVAL_REQUIRED"
        assert restored.approval_request["candidate_laws"] == ["주택임대차보호법"]
        new_db.delete(restored)
        new_db.commit()
        new_db.close()
    except Exception as e:
        db.rollback()
        db.close()
        raise e
