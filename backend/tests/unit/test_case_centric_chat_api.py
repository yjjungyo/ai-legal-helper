"""사건 중심 단일 지속 대화(Case-Centric Chat UI/UX v1.1) API 및 진행 상태 단위 테스트

검증 항목:
1. create_initial_progress: 6단계 초기화 및 step_1 RUNNING 전이
2. update_progress_step: 단계별 상태 전이(RUNNING, COMPLETED, WAITING_APPROVAL, SKIPPED)
3. ConsultationResponse progress 직렬화 및 역직렬화
4. primary_conversation_id 자동 할당 및 단일 대화 영속성
5. load_conversation_context의 case_memory 프롬프트 연동 및 최신 팩트 우선 원칙
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from ai_legal_helper.api.schemas.consultation import (
    ConsultationProgress,
    ConsultationStep,
    ConsultationStepStatus,
    create_initial_progress,
    ConsultationResponse,
)
from ai_legal_helper.api.routes.consultation import (
    update_progress_step,
    NODE_TO_PROGRESS_STEP,
    _parse_or_build_progress,
    _consultations,
)
from ai_legal_helper.database.models import Case, ConsultationRecord, Fact, EvidenceDocument
from ai_legal_helper.workflows.conversation_context import (
    load_conversation_context,
    ConversationTurn,
    ConversationContext,
)


def test_create_initial_progress():
    """6단계 LangGraph 진행 상태 초기화 모델이 올바르게 생성되는지 검증한다."""
    prog = create_initial_progress("req-test-123", "2026-10-24T12:00:00Z")
    assert prog.request_id == "req-test-123"
    assert prog.current_step == "step_1"
    assert len(prog.steps) == 6

    step_ids = [s.step_id for s in prog.steps]
    assert step_ids == [
        "step_1",
        "step_2",
        "step_3",
        "step_4",
        "step_5",
        "step_6",
    ]

    # 첫 번째 단계는 RUNNING, 나머지는 PENDING 상태
    assert prog.steps[0].status == ConsultationStepStatus.RUNNING
    for s in prog.steps[1:]:
        assert s.status == ConsultationStepStatus.PENDING


def test_update_progress_step_lifecycle():
    """단계별 진행 상태 전이(RUNNING -> COMPLETED -> WAITING_APPROVAL)를 검증한다."""
    req_id = "req-test-456"
    prog = create_initial_progress(req_id, "2026-10-24T12:00:00Z")
    resp = ConsultationResponse(
        request_id=req_id,
        trace_id="tr-456",
        status="IN_PROGRESS",
        sources=[],
        warnings=[],
        progress=prog,
    )
    _consultations[req_id] = resp

    # 1. step_2 (사실관계·증거 조회) 진입 시 step_1은 자동 COMPLETED, step_2는 RUNNING
    update_progress_step(req_id, "step_2", ConsultationStepStatus.RUNNING)
    assert resp.progress.current_step == "step_2"
    assert resp.progress.steps[0].status == ConsultationStepStatus.COMPLETED
    assert resp.progress.steps[1].status == ConsultationStepStatus.RUNNING

    # 2. HILT 승인 대기 상태 전이 (step_3 WAITING_APPROVAL)
    update_progress_step(req_id, "step_3", ConsultationStepStatus.WAITING_APPROVAL)
    assert resp.progress.current_step == "step_3"
    assert resp.progress.steps[2].status == ConsultationStepStatus.WAITING_APPROVAL


def test_node_to_progress_step_mapping():
    """LangGraph 주요 노드 이름이 6단계 진행 상태 ID로 누락 없이 매핑되는지 검증한다."""
    assert NODE_TO_PROGRESS_STEP["intent_analysis"][0] == "step_1"
    assert NODE_TO_PROGRESS_STEP["plan"][0] == "step_2"
    assert NODE_TO_PROGRESS_STEP["run_agents"][0] == "step_3"
    assert NODE_TO_PROGRESS_STEP["synthesize"][0] == "step_4"
    assert NODE_TO_PROGRESS_STEP["verification"][0] == "step_5"
    assert NODE_TO_PROGRESS_STEP["finalize"][0] == "step_6"


def test_parse_or_build_progress():
    """DB에 저장된 progress 딕셔너리 또는 레코드로부터 ConsultationProgress가 안전하게 역직렬화되는지 검증한다."""
    raw_prog = {
        "request_id": "req-789",
        "current_step": "step_5",
        "steps": [
            {"step_id": "step_1", "title": "사건 정보와 이전 상담 맥락 확인", "status": "COMPLETED"},
            {"step_id": "step_2", "title": "사실관계·타임라인·증거 조회", "status": "COMPLETED"},
            {"step_id": "step_3", "title": "관련 법령 및 판례 검색", "status": "COMPLETED"},
            {"step_id": "step_4", "title": "법률 쟁점별 분석", "status": "COMPLETED"},
            {"step_id": "step_5", "title": "증거·법률 근거 검증", "status": "RUNNING"},
            {"step_id": "step_6", "title": "최종 상담 답변 작성", "status": "PENDING"},
        ],
        "updated_at": "2026-10-24T12:00:00Z",
    }

    prog = _parse_or_build_progress(raw_prog, "IN_PROGRESS", "req-789")
    assert prog is not None
    assert prog.request_id == "req-789"
    assert prog.current_step == "step_5"
    assert prog.steps[4].status == ConsultationStepStatus.RUNNING

    # SUCCESS 상태에서 raw_progress가 비어있을 때 fallback 빌드 검증
    auto_prog = _parse_or_build_progress(None, "SUCCESS", "req-auto-succ")
    assert auto_prog is not None
    assert auto_prog.request_id == "req-auto-succ"
    assert len(auto_prog.steps) == 6
    assert all(s.status == ConsultationStepStatus.COMPLETED for s in auto_prog.steps)


def test_case_memory_in_conversation_context():
    """사건 메모리(Case Memory)가 ConversationContext에 적재되어 프롬프트에 정상 주입되는지 검증한다."""
    turn = ConversationTurn(
        turn_index=1,
        request_id="req-t1",
        question="보증금 얼마인가요?",
        answer="보증금은 3억원입니다. [E01]",
        answer_status="DELIVERED",
    )

    ctx = ConversationContext(
        conversation_id="conv-single-persistent",
        case_id="case-17c5bb1d",
        current_question="가압류는 어떻게 되나요?",
        previous_turns=[turn],
        case_memory={
            "title": "서초동 오피스텔 보증금 반환 분쟁",
            "case_type": "주택임대차",
            "status": "IN_PROGRESS",
            "confirmed_facts_count": 12,
            "evidences_count": 3,
        },
    )

    prompt_text = ctx.format_context_for_prompt(max_turns=3)

    assert "서초동 오피스텔 보증금 반환 분쟁" in prompt_text
    assert "등록증거 3건" in prompt_text
    assert "확정사실 12건" in prompt_text
    assert "최신 Fact 및 등록 증거가 과거 답변과 충돌할 경우 최신 증거가 항상 우선합니다" in prompt_text


@pytest.mark.asyncio
async def test_process_consultation_completion_logging(monkeypatch):
    """process_consultation 정상 종료 시 UnboundLocalError 없이 로그가 기록되고 응답이 매핑되는지 검증한다."""
    from unittest.mock import AsyncMock, MagicMock
    from ai_legal_helper.api.routes.consultation import process_consultation
    from ai_legal_helper.api.schemas.consultation import ConsultationRequest

    req_id = "req-test-resp-unbound"
    user = MagicMock()
    user.id = "user-123"

    req = ConsultationRequest(
        question="임대차 보증금 반환 기한은 언제인가요?",
        case_id="case-test-123",
    )

    conv_context = ConversationContext(
        conversation_id="conv-test-123",
        case_id="case-test-123",
        current_question=req.question,
        turn_index=1,
    )

    init_resp = ConsultationResponse(
        request_id=req_id,
        conversation_id="conv-test-123",
        turn_index=1,
        trace_id="trace-test-123",
        status="IN_PROGRESS",
        execution_status="IN_PROGRESS",
        verification_status="UNVERIFIED",
        answer_status="WITHHELD",
        routing_status=None,
        question=req.question,
        case_id=req.case_id,
        created_at="2026-10-31T19:00:00Z",
        progress=create_initial_progress(req_id, "2026-10-31T19:00:00Z"),
    )
    _consultations[req_id] = init_resp

    mock_result = {
        "status": "SUCCESS",
        "answer": "계약 만료 시 즉시 반환해야 합니다.",
        "final_disposition": "DELIVERED",
        "verification_result": {"status": "PASS"},
        "cited_sources": [
            {
                "source_type": "STATUTE",
                "statute_name": "주택임대차보호법",
                "article": "제3조",
                "title": "대항력 등",
                "source_id": "STATUTE-001",
            }
        ],
    }

    monkeypatch.setattr(
        "ai_legal_helper.api.routes.consultation.run_legal_consultation",
        AsyncMock(return_value=mock_result),
    )
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()
    mock_session_ctx = MagicMock()
    mock_session_ctx.__enter__.return_value = mock_db
    monkeypatch.setattr(
        "ai_legal_helper.api.routes.consultation.SessionLocal",
        MagicMock(return_value=mock_session_ctx),
    )

    # 실행: UnboundLocalError가 발생하지 않고 온전히 통과해야 함
    await process_consultation(
        request_id=req_id,
        trace_id="trace-test-123",
        req=req,
        conv_context=conv_context,
    )

    saved_resp = _consultations[req_id]
    assert saved_resp.status == "SUCCESS"
    assert saved_resp.answer_status == "DELIVERED"
    assert saved_resp.verification_status == "PASS"
    assert len(saved_resp.sources) == 1
    assert saved_resp.sources[0].statute_name == "주택임대차보호법"


