# -*- coding: utf-8 -*-
"""
모듈명: test_step1_logging.py

[모듈 개요]
STEP 1에서 구현된 상담 프로세스 상세 구조화 로깅 및 PII 마스킹 모듈의 동작을 검증하는 단위 테스트.

[주요 기능]
1. `pii_masker`의 개인정보(주민등록번호, 전화번호, 계좌번호, 이메일) 및 비밀 키(API Key 등) 마스킹 검증.
2. `sanitize_diagnostic_text`의 진단 메시지 길이 제한 및 마스킹 안전성 검증.
3. `issue_planner.plan_legal_issues` 실행 시 리스트 문자열 결합 버그(`TypeError`) 재발 방지 및 구조화 로그 출력 검증.
4. `supervisor_initialize_node` 실행 시 구조화된 `[SUPERVISOR_INIT]` 로깅 필드(답변모드, 등록문서수, 단위쟁점수 등) 출력 검증.
"""
import pytest
import logging
from unittest.mock import MagicMock
from langchain_core.messages import HumanMessage

from ai_legal_helper.observability.pii_masker import mask_pii, sanitize_diagnostic_text
from ai_legal_helper.workflows.issue_planner import plan_legal_issues
from ai_legal_helper.workflows.legal_workflow import supervisor_initialize_node


def test_pii_masker_various_sensitive_patterns():
    """다양한 유형의 개인정보 및 인증 키가 올바르게 마스킹되는지 검증한다.

    검증 대상:
    - 주민등록번호 (생년월일 보존, 뒤 7자리 마스킹)
    - 휴대폰/유선 전화번호 (국번 및 가운데 자리 마스킹)
    - 은행 계좌번호 (중간 일련번호 마스킹)
    - 이메일 주소 (아이디 앞 2자리 제외 마스킹)
    - API Key / Secret Token (접두사 보존 후 마스킹)
    """
    raw_text = (
        "의뢰인 홍길동 900101-1234567, 연락처 010-1234-5678 및 02-123-4567, "
        "환불 계좌 110-123-456789 (신한은행), "
        "이메일 user@example.com, "
        "접근 토큰 Authorization: Bearer sk-1234567890abcdef1234567890abcdef "
        "OpenLaw 인증키 oc=testOpenLawKey1234567"
    )

    masked = mask_pii(raw_text)

    # 1. 주민등록번호 뒤 7자리 마스킹 확인
    assert "900101-*******" in masked
    assert "1234567" not in masked

    # 2. 휴대폰 및 유선 번호 마스킹 확인
    assert "010-****-5678" in masked
    assert "02-****-4567" in masked

    # 3. 계좌번호 마스킹 확인
    assert "***-**-******" in masked or "110-***-456789" in masked

    # 4. 이메일 마스킹 확인
    assert "user@example.com" not in masked
    assert "@" in masked

    # 5. 비밀 키 마스킹 확인
    assert "[MASKED_API_KEY]" in masked or "Bearer sk-***[SECRET]***" in masked
    assert "sk-1234567890abcdef1234567890abcdef" not in masked
    assert "testOpenLawKey1234567" not in masked


def test_sanitize_diagnostic_text_truncation_and_masking():
    """진단 로그 문자열 정제 시 길이 제한 및 PII 마스킹이 동시에 수행되는지 검증한다."""
    long_sensitive_text = "주민번호 950505-2345678 " + ("가나다라" * 200)

    sanitized = sanitize_diagnostic_text(long_sensitive_text, max_len=100)

    # PII 마스킹 확인
    assert "950505-*******" in sanitized
    assert "2345678" not in sanitized

    # 길이 제한 및 생략 표기 확인
    assert len(sanitized) <= 150
    assert "... (총" in sanitized


def test_issue_planner_logging_without_type_error(caplog):
    """쟁점 계획 수립(`plan_legal_issues`) 호출 시 `TypeError` 없이 구조화된 로그가 생성되는지 검증한다."""
    caplog.set_level(logging.INFO)

    # 최소한의 CaseEvidenceBriefing 목 객체 구성
    mock_briefing = MagicMock()
    mock_briefing.case_id = "test-case-001"
    mock_briefing.facts = []
    mock_briefing.events = []
    mock_briefing.evidences = []
    mock_briefing.evidence_documents = []
    mock_briefing.source_registry = {}
    mock_briefing.evidence_gaps = []

    tasks = plan_legal_issues("보증금을 돌려받을 수 있나요?", mock_briefing)

    # TypeError 없이 쟁점 생성 확인
    assert len(tasks) >= 1
    assert any("보증금" in t.issue_title for t in tasks)

    # caplog에서 구조화된 로그 출력 여부 확인
    planner_logs = [record.message for record in caplog.records if "[ISSUE_PLANNER]" in record.message]
    assert len(planner_logs) >= 2
    assert any("단위 쟁점 도출 완료" in log for log in planner_logs)
    assert any("단위 쟁점 상세" in log for log in planner_logs)


def test_supervisor_initialize_node_structured_logging(caplog):
    """`supervisor_initialize_node` 실행 시 구조화된 `[SUPERVISOR_INIT]` 로그가 기록되는지 검증한다."""
    caplog.set_level(logging.INFO)

    state = {
        "messages": [HumanMessage(content="안녕하세요. 질문입니다.")],
        "conversation_id": "conv-test-123",
        "turn_index": 1,
        "case_id": None,
    }

    result = supervisor_initialize_node(state)

    assert result["answer_mode"] is None
    assert result["turn_index"] == 1

    init_logs = [record.message for record in caplog.records if "[SUPERVISOR_INIT]" in record.message]
    assert len(init_logs) >= 1
    assert any("초기화 완료" in log and "답변모드=STANDARD" in log for log in init_logs)
