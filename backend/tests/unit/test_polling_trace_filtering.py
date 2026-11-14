# -*- coding: utf-8 -*-
"""
모듈명: test_polling_trace_filtering.py

[테스트 개요]
FastAPI 미들웨어(trace_context_middleware)에서 프론트엔드의 단주기 폴링 요청
(GET /api/v1/consultations/{id}) 및 헬스체크 경로가 노이즈(is_noise)로 올바르게 분류되어,
Langfuse Root Trace 생성 및 콘솔 반복 로깅에서 안전하게 제외되는지 검증하는 단위 테스트.

[검증 항목]
1. GET /api/v1/consultations/{id} 단주기 폴링 시 Langfuse start_trace가 호출되지 않음
2. GET /api/v1/consultations/{id} 성공(200) 시 logger.info가 출력되지 않고 logger.debug로 처리됨
3. 일반 API 요청(POST /api/v1/consultations 등)은 정상적으로 Langfuse Trace 및 logger.info가 호출됨
4. 폴링 중 에러(4xx, 5xx) 발생 시에는 logger.warning이 호출되어 오류가 은폐되지 않음
"""

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from ai_legal_helper.api.main import app
from ai_legal_helper.api.schemas.consultation import ConsultationResponse
from ai_legal_helper.api.routes.consultation import _consultations


from ai_legal_helper.api.dependencies import get_current_user
from ai_legal_helper.database.models import User

mock_user = User(id='test-user-id', email='test@example.com', display_name='testuser')
app.dependency_overrides[get_current_user] = lambda: mock_user

client = TestClient(app)


def test_polling_consultation_skips_langfuse_and_info_log():
    """GET /api/v1/consultations/{id} 폴링 시 Langfuse Trace 및 INFO 로그가 생략되는지 검증한다."""
    req_id = "test-poll-12345"
    # 메모리에 모의 응답 등록
    mock_resp = ConsultationResponse(
        request_id=req_id,
        trace_id="tr-test-123",
        status="RUNNING",
        created_at="2026-10-27T12:00:00Z",
    )
    mock_resp._user_id = mock_user.id
    _consultations[req_id] = mock_resp

    with patch("ai_legal_helper.observability.langfuse_client.start_trace") as mock_start_trace, \
         patch("ai_legal_helper.api.main.logger.info") as mock_log_info, \
         patch("ai_legal_helper.api.main.logger.debug") as mock_log_debug:

        resp = client.get(f"/api/v1/consultations/{req_id}")
        assert resp.status_code == 200

        # Langfuse 최상위 Root Trace가 생성되지 않아야 함
        mock_start_trace.assert_not_called()

        # 터미널 스팸 방지를 위해 200 정상 폴링 시 logger.info가 호출되지 않아야 함 (완전 무음화)
        mock_log_info.assert_not_called()

    # 정리
    _consultations.pop(req_id, None)


def test_polling_consultation_logs_warning_on_error():
    """GET /api/v1/consultations/{id} 실패(404 등) 시에는 문제를 파악할 수 있도록 warning 로그를 남김을 검증한다."""
    req_id = "non-existent-poll-99999"
    _consultations.pop(req_id, None)

    with patch("ai_legal_helper.observability.langfuse_client.start_trace") as mock_start_trace, \
         patch("ai_legal_helper.api.main.logger.info") as mock_log_info, \
         patch("ai_legal_helper.api.main.logger.warning") as mock_log_warning:

        resp = client.get(f"/api/v1/consultations/{req_id}")
        assert resp.status_code == 404

        # Langfuse 트레이스는 여전히 제외
        mock_start_trace.assert_not_called()
        # INFO는 찍지 않되, 오류 추적을 위한 WARNING 로그는 기록되어야 함
        mock_log_info.assert_not_called()
        mock_log_warning.assert_called_once()
        assert f"/api/v1/consultations/{req_id}" in mock_log_warning.call_args[0][0]


def test_read_only_get_skips_langfuse_trace_but_keeps_info_log():
    """단순 DB 조회성 GET 요청(예: cases 목록 조회, claims 조회 등)은 빈 Langfuse Trace를 생성하지 않고, INFO 로그만 정상 기록함을 검증한다."""
    with patch("ai_legal_helper.observability.langfuse_client.start_trace") as mock_start_trace, \
         patch("ai_legal_helper.api.main.logger.info") as mock_log_info:

        resp = client.get("/api/v1/cases")
        # 단순 RDB 조회의 경우 Langfuse Root Trace를 생성하지 않아야 함 (빈 트레이스 노이즈 차단)
        mock_start_trace.assert_not_called()
        # 서버 액세스 로깅(INFO)은 정상 유지되어야 함
        assert mock_log_info.called
        assert "/api/v1/cases" in mock_log_info.call_args[0][0]


def test_consultation_post_records_langfuse_trace():
    """핵심 AI 상담 워크플로우(POST /api/v1/consultations)는 Langfuse Trace(LegalAgent)와 INFO 로그가 정상 기록됨을 검증한다."""
    with patch("ai_legal_helper.observability.langfuse_client.start_trace") as mock_start_trace, \
         patch("ai_legal_helper.api.main.logger.info") as mock_log_info, \
         patch("ai_legal_helper.api.routes.consultation.process_consultation") as mock_process:

        resp = client.post(
            "/api/v1/consultations",
            json={"question": "보증금 반환 문의드립니다.", "case_id": "test-case-id"},
        )
        # 상담 파이프라인은 'LegalAgent' 이름으로 Langfuse Root Trace가 생성되어야 함
        assert mock_start_trace.called
        assert mock_start_trace.call_args[1]["name"] == "LegalAgent"
        assert mock_log_info.called
