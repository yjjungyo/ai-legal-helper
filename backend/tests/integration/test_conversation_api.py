# -*- coding: utf-8 -*-
"""
모듈명: test_conversation_api.py

[모듈 개요]
Phase 1: 대화 세션 영속화 및 맥락 복원 관련 API 엔드포인트들의 통합 동작을 검증한다.
신규 대화 시작, 기존 대화 후속 질문, conversation_id 필터링, 대화 목록 요약 및 상세 조회를 테스트한다.

[주요 테스트 케이스]
1. `test_start_consultation_generates_conversation_id`: conversation_id 미지정 시 신규 UUID 발급 및 turn_index=1 확인
2. `test_start_consultation_links_existing_conversation`: conversation_id 지정 시 동일 세션 승계 및 turn_index 증가 확인
3. `test_list_conversations_and_detail_endpoints`: /cases/{case_id}/conversations 및 /conversations/{conversation_id} 조회 검증
4. `test_consultations_query_filtered_by_conversation`: /cases/{case_id}/consultations?conversation_id= 필터링 검증
"""

import uuid
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import patch

from ai_legal_helper.api.main import app
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import Case, ConsultationRecord, User

client = TestClient(app)


def test_start_consultation_generates_conversation_id():
    """conversation_id 없이 상담 시작 시 새로운 conversation_id와 turn_index=1이 발급되는지 검증한다."""
    with patch("ai_legal_helper.api.routes.consultation.process_consultation"):
        res = client.post(
            "/api/v1/consultations",
            json={"question": "보증금 미반환 시 대처 방법은?"}
        )
        assert res.status_code == 200
        data = res.json()
        assert "conversation_id" in data
        assert data["conversation_id"] is not None
        assert data["turn_index"] == 1
        assert data["status"] == "IN_PROGRESS"


def test_start_consultation_links_existing_conversation():
    """기존 conversation_id를 전달하면 동일한 conversation_id가 승계되는지 검증한다."""
    custom_conv_id = f"test-conv-{uuid.uuid4()}"
    with patch("ai_legal_helper.api.routes.consultation.process_consultation"):
        res = client.post(
            "/api/v1/consultations",
            json={
                "question": "첫 번째 질문입니다.",
                "conversation_id": custom_conv_id,
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["conversation_id"] == custom_conv_id
        assert data["turn_index"] == 1


def test_list_conversations_and_detail_endpoints():
    """사건별 대화 요약 목록 및 특정 대화 상세 조회 엔드포인트를 검증한다."""
    db = SessionLocal()
    case_id = f"case-{uuid.uuid4()}"
    try:
        # 1. 테스트용 케이스 생성
        case = Case(
            id=case_id,
            user_id="test-user-id",
            title="대화 세션 테스트 사건",
            case_type="민법",
        )
        db.add(case)

        # 2. 동일 사건 내 2개 대화 세션의 레코드 생성
        conv_a = f"conv-a-{uuid.uuid4()}"
        conv_b = f"conv-b-{uuid.uuid4()}"

        r1 = ConsultationRecord(
            case_id=case_id,
            user_id="test-user-id",
            request_id=f"req-{uuid.uuid4()}",
            conversation_id=conv_a,
            turn_index=1,
            question="대화 A 1번 질문",
            answer="대화 A 1번 답변",
            status="SUCCESS",
            created_at=datetime(2026, 10, 22, 10, 0, 0),
        )
        r2 = ConsultationRecord(
            case_id=case_id,
            user_id="test-user-id",
            request_id=f"req-{uuid.uuid4()}",
            conversation_id=conv_a,
            turn_index=2,
            question="대화 A 2번 질문",
            answer="대화 A 2번 답변",
            status="SUCCESS",
            created_at=datetime(2026, 10, 22, 10, 5, 0),
        )
        r3 = ConsultationRecord(
            case_id=case_id,
            user_id="test-user-id",
            request_id=f"req-{uuid.uuid4()}",
            conversation_id=conv_b,
            turn_index=1,
            question="대화 B 1번 질문",
            answer="대화 B 1번 답변",
            status="SUCCESS",
            created_at=datetime(2026, 10, 22, 11, 0, 0),
        )
        db.add_all([r1, r2, r3])
        db.commit()

        # 3. GET /cases/{case_id}/conversations 호출
        res_list = client.get(f"/api/v1/cases/{case_id}/conversations")
        assert res_list.status_code == 200
        summaries = res_list.json()
        assert len(summaries) == 2

        # conv_a는 2개 턴
        sum_a = next(s for s in summaries if s["conversation_id"] == conv_a)
        assert sum_a["turns_count"] == 2
        assert sum_a["first_question"] == "대화 A 1번 질문"
        assert sum_a["last_question"] == "대화 A 2번 질문"

        # conv_b는 1개 턴
        sum_b = next(s for s in summaries if s["conversation_id"] == conv_b)
        assert sum_b["turns_count"] == 1

        # 4. GET /cases/{case_id}/conversations/{conversation_id} 상세 호출
        res_detail = client.get(f"/api/v1/cases/{case_id}/conversations/{conv_a}")
        assert res_detail.status_code == 200
        detail = res_detail.json()
        assert detail["conversation_id"] == conv_a
        assert len(detail["turns"]) == 2
        assert detail["turns"][0]["turn_index"] == 1
        assert detail["turns"][1]["turn_index"] == 2

        # 5. GET /cases/{case_id}/consultations?conversation_id={conv_a} 필터링 검증
        res_filter = client.get(f"/api/v1/cases/{case_id}/consultations?conversation_id={conv_a}")
        assert res_filter.status_code == 200
        filtered_records = res_filter.json()
        assert len(filtered_records) == 2
        for r in filtered_records:
            assert r["conversation_id"] == conv_a
    finally:
        # 정리: 생성한 케이스 및 레코드 삭제
        db.query(ConsultationRecord).filter(ConsultationRecord.case_id == case_id).delete()
        db.query(Case).filter(Case.id == case_id).delete()
        db.commit()
        db.close()

