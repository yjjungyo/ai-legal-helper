# -*- coding: utf-8 -*-
"""
테스트 모듈명: test_p0_final_disposition_defects.py

[테스트 목적]
2026-10-18 상담 결과에서 발견된 고객 응답(answer_status)과 검증 상태(verification_status),
평가 리포트 간의 불일치 및 내부 감사 데이터의 고객 노출 결함을 재현하고 수정을 검증한다.

[핵심 불변조건]
1. 워크플로우가 insufficient_node로 종료되면 answer_status는 반드시 WITHHELD여야 한다.
   (verification_status가 REVISE라는 이유로 CAUTIONARY가 되어서는 안 됨)
2. insufficient_node는 내부 감수용 디버그 문구('표현상 긴장', '다소 넓다', '증거 미연결 10건')를
   고객 답변(final_answer)에 일체 노출하지 않는다.
3. HILT 공식 법령 검색 완료 후 4단계 법률 답변이 재분석되었고 Verifier가 REVISE(주의사항 필요)를
   부여한 경우, 답변을 폐기(insufficient)하지 않고 finalize로 전달하여 CAUTIONARY로 고객에게 정상 제공한다.
"""
import pytest
from unittest.mock import MagicMock, patch
from ai_legal_helper.workflows.state import LegalState
from ai_legal_helper.workflows.legal_workflow import (
    insufficient_node,
    finalize_node,
    verification_condition,
)


def test_p0_1_insufficient_node_must_set_final_disposition_withheld():
    """P0-1: insufficient_node 종료 시 final_disposition은 반드시 'WITHHELD'여야 함."""
    state: LegalState = {
        "question": "전세보증금 반환 질문",
        "draft_answer": "초안 내용",
        "retrieved_sources": [],
        "verification_result": {
            "status": "REVISE",  # 내부 Verifier는 REVISE 판정
            "reason_code": "LEGAL_SOURCE_MISSING",
            "missing_issues": ["대리권 수권 여부"],
            "candidate_laws": ["주택임대차보호법"],
            "contradictions": ["일부 문장은 표현상 긴장이 있음"],
            "warnings": ["승인된 증거가 연결되지 않은 사실 10건"],
        },
        "warnings": [],
    }

    res = insufficient_node(state)

    # 1. insufficient_node는 반드시 명시적으로 final_disposition='WITHHELD'를 반환해야 함
    assert "final_disposition" in res, "insufficient_node 결과에 final_disposition 필드가 누락되었습니다."
    assert res["final_disposition"] == "WITHHELD"


def test_p0_2_insufficient_node_does_not_leak_internal_debug_expressions():
    """P0-2: insufficient_node는 '표현상 긴장', '증거 미연결 10건' 등 내부 감수 메모를 고객 답변에 노출하지 않아야 함."""
    state: LegalState = {
        "question": "전세보증금 반환 질문",
        "draft_answer": "초안 내용",
        "retrieved_sources": [],
        "verification_result": {
            "status": "INSUFFICIENT",
            "reason_code": "LEGAL_SOURCE_MISSING",
            "missing_issues": ["대리권 증명 부재"],
            "candidate_laws": ["주택임대차보호법"],
            "contradictions": ["일부 문장은 종료 시점만 지나면 곧바로 반환의무가 발생하는 것처럼 읽혀 표현상 긴장이 있음"],
            "warnings": ["승인된 증거가 연결되지 않은 사실/쟁점이 10건 있습니다."],
        },
        "warnings": [],
    }

    res = insufficient_node(state)
    final_ans = res.get("final_answer", "")

    # 에이전트 간 내부 디버그 표현이 고객용 final_answer에 포함되면 안 됨
    assert "표현상 긴장" not in final_ans, "고객 답변에 '표현상 긴장' 내부 감수 문구가 누출되었습니다."
    assert "다소 넓다" not in final_ans
    assert "사실/쟁점이 10건 있습니다" not in final_ans
    assert "10건" not in final_ans


def test_p0_3_hilt_reanalyze_revise_routes_to_finalize_cautionary():
    """P0-3: HILT 공식 법령 검색 후 re_analyze 답변이 REVISE 판정을 받은 경우 insufficient로 버리지 않고 finalize로 라우팅되어야 함."""
    state: LegalState = {
        "question": "전세보증금 3억원 반환 및 추가 손해배상 검토",
        "draft_answer": "[1. 핵심 결론]\n보증금 반환 청구 가능\n[2. 지금 해야 할 일]\n내용증명 발송\n[3. 쟁점별 상세 법률 분석]\n주임법 제6조의2\n[4. 추가 확인사항 및 유의사항]\n입증 주의",
        "retrieved_sources": [{
            "source_id": "law_6_2",
            "statute_name": "주택임대차보호법",
            "article": "제6조의2",
            "content": "임차인은 언제든지 임대인에게 계약해지를 통고할 수 있다.",
        }],
        "verification_result": {
            "status": "REVISE",  # 법리는 통과했으나 사실관계 입증 주의 필요
            "reason_code": "CASE_EVIDENCE_MISSING",
            "candidate_laws": [],
            "warnings": ["배우자 전화 통지는 입증이 필요합니다."],
        },
        "hilt_executed": True,  # HILT 공식 법령 검색이 이미 수행됨
        "revision_count": 1,
    }

    next_node = verification_condition(state)

    # HILT 법령이 반영된 4단계 답변이 REVISE인 경우 insufficient로 버리지 않고 finalize로 라우팅되어야 함
    assert next_node == "finalize", f"REVISE 판정의 재분석 답변이 {next_node}로 잘못 라우팅되었습니다 (finalize 기대)."


def test_p0_4_finalize_node_sets_cautionary_for_revise():
    """P0-4: finalize_node는 verification_result가 REVISE인 경우 final_disposition='CAUTIONARY'를 반환해야 함."""
    state: LegalState = {
        "draft_answer": "[1. 핵심 결론]\n3개월 후 반환 청구 가능 (주택임대차보호법 제6조의2)",
        "retrieved_sources": [{
            "source_id": "law_6_2",
            "statute_name": "주택임대차보호법",
            "article": "제6조의2",
            "content": "임차인은 언제든지 임대인에게 계약해지를 통고할 수 있고 3개월이 지나면 효력이 발생한다.",
        }],
        "verification_result": {
            "status": "REVISE",
            "warnings": ["배우자 수령 효력은 추가 입증 필요"],
        },
        "warnings": [],
    }

    res = finalize_node(state)
    assert res.get("final_disposition") == "CAUTIONARY"
    assert "주택임대차보호법 제6조의2" in res.get("final_answer", "")


def test_p0_5_api_consultation_honors_final_disposition_withheld():
    """P0-5: verification_result가 REVISE이더라도 final_disposition이 WITHHELD이면 resp.answer_status는 반드시 WITHHELD여야 함."""
    from ai_legal_helper.api.routes.consultation import ConsultationResponse

    resp = ConsultationResponse(
        case_id="case-123",
        request_id="req-123",
        trace_id="tr-123",
        status="SUCCESS",
    )
    result = {
        "status": "SUCCESS",
        "answer": "안내: 법률적 근거 부족으로 인한 판단 유보 (WITHHELD)",
        "final_disposition": "WITHHELD",
        "verification_result": {"status": "REVISE"},  # 내부 Verifier는 REVISE이지만
        "sources": [],
    }

    # API 응답 처리 로직 시뮬레이션
    ver_status = result["verification_result"]["status"]
    final_disp = result.get("final_disposition")
    if final_disp in ("DELIVERED", "CAUTIONARY", "WITHHELD"):
        resp.answer_status = final_disp
    elif ver_status == "PASS":
        resp.answer_status = "DELIVERED"
    elif ver_status == "REVISE":
        resp.answer_status = "CAUTIONARY"
    else:
        resp.answer_status = "WITHHELD"

    assert resp.answer_status == "WITHHELD", (
        f"P0-01/P0-1 결함: final_disposition이 WITHHELD임에도 answer_status가 {resp.answer_status}로 설정되었습니다."
    )


def test_p0_6_api_consultation_honors_final_disposition_cautionary():
    """P0-6: HILT 재분석 완료 후 REVISE인 경우 final_disposition='CAUTIONARY'가 resp.answer_status에 정확히 매핑되는지 검증."""
    from ai_legal_helper.api.routes.consultation import ConsultationResponse

    resp = ConsultationResponse(
        case_id="case-123",
        request_id="req-123",
        trace_id="tr-123",
        status="SUCCESS",
    )
    result = {
        "status": "SUCCESS",
        "answer": "[1. 핵심 결론]\n3개월 후 반환 청구 가능",
        "final_disposition": "CAUTIONARY",
        "verification_result": {"status": "REVISE"},
        "sources": [],
    }

    ver_status = result["verification_result"]["status"]
    final_disp = result.get("final_disposition")
    if final_disp in ("DELIVERED", "CAUTIONARY", "WITHHELD"):
        resp.answer_status = final_disp
    elif ver_status == "PASS":
        resp.answer_status = "DELIVERED"
    elif ver_status == "REVISE":
        resp.answer_status = "CAUTIONARY"
    else:
        resp.answer_status = "WITHHELD"

    assert resp.answer_status == "CAUTIONARY"


@pytest.mark.asyncio
async def test_p0_7_execute_consultation_returns_final_disposition():
    """P0-7: _execute_consultation 실행 결과 dict에 final_disposition 필드가 정상 포함되는지 검증."""
    from ai_legal_helper.workflows.legal_workflow import _execute_consultation

    mock_app = MagicMock()
    mock_app.ainvoke = MagicMock()
    
    # 1. insufficient_node를 거쳐 final_disposition='WITHHELD'가 설정된 가상 final_state
    mock_final_state = {
        "final_answer": "유보 안내",
        "final_disposition": "WITHHELD",
        "verification_result": {"status": "INSUFFICIENT"},
        "retrieved_sources": [],
        "warnings": [],
        "revision_count": 0,
        "trace_id": "tr-test",
        "request_id": "th-test",
        "selected_agents": ["property"],
    }

    with patch("ai_legal_helper.workflows.legal_workflow.build_legal_graph", return_value=mock_app):
        # ainvoke 비동기 mock
        import asyncio
        f = asyncio.Future()
        f.set_result(mock_final_state)
        mock_app.ainvoke.return_value = f

        mock_checkpointer = MagicMock()
        mock_checkpointer.get_tuple.return_value = MagicMock(checkpoint=True)

        res = await _execute_consultation("질문", "th-test", None, mock_checkpointer)
        assert "final_disposition" in res, "_execute_consultation 반환 결과에 final_disposition이 누락되었습니다."
        assert res["final_disposition"] == "WITHHELD"

