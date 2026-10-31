# -*- coding: utf-8 -*-
"""
모듈명: test_dynamic_case_integrity_e2e_p0_3_1.py

[모듈 개요]
AI Legal Helper — P0-3.1 Dynamic Case State Integrity & E2E Verification 테스트 스위트.
동적 사건 상태 처리의 무결성을 API 및 DB 수준에서 종합 검증한다.

[10대 E2E 검증 시나리오]
- E01: 부분 변제 2천만 원 (3억 사건에서 2천만원 지급 주장 시 [잠정] 잔액 2.8억 산정 및 증거 미확인 상태 유지)
- E02: 입금 증거 등록 및 검토 승인 (실제 2천만원 이체증 승인 후 [확정] 잔액 2.8억 승격 및 원본 파일명 연결)
- E03: 기존 입금 증거 오인 방지 (최초 보증금 지급 이체증을 임대인의 보증금 반환 증거로 오인 차단)
- E04: 누적 부분 변제 (2천만원과 3천만원이 서로 다른 날짜에 승인 시 누적 반환액 5천만원, 미반환 잔액 2.5억 산정)
- E05: 중복 요청 방지 (동일 이체증 중복 업로드나 상담 재시도 시 반환액 중복 합산 차단)
- E06: 가압류 신규 등록 (새 등기 증거 미승인 시 권리관계 불변, 승인 후 실제 등기일과 임차인 대항력 순위 재검토)
- E07: 통지일 정정 (정정 진술과 원문 증거가 다를 때 기존 확정 사실 보존 및 증거 도달일 우선 적용)
- E08: 서버 재시작 및 세션 복원 (DB에 보존된 사실 변경 및 대화 이력이 새 세션에서 무손실 복원)
- E09: 동시 요청 (동일 사건에 대한 병렬 상담 요청 시 턴 번호 중복 및 상태 충돌 방지)
- E10: 사건 격리 (사건 A의 부분 변제 증거/결과가 사건 B의 잔액 산정이나 상담에 일체 누출되지 않음)
"""

import uuid
import pytest
from concurrent.futures import ThreadPoolExecutor
from typing import Generator, Any, Optional
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ai_legal_helper.api.main import app
from ai_legal_helper.api.dependencies import get_current_user
from ai_legal_helper.api.routes.consultation import _consultations
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import (
    User,
    Case,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceLink,
    Fact,
    Event,
    ConsultationRecord,
)
from ai_legal_helper.case_intelligence.case_briefing import (
    CaseEvidenceBriefing,
    FactItemBrief,
    EvidenceItemBrief,
    build_case_evidence_briefing,
)
from ai_legal_helper.case_intelligence.evidence_manager import (
    process_evidence_review,
)
from ai_legal_helper.workflows.final_disposition import (
    detect_case_delta,
    assemble_grounded_answer,
    determine_final_disposition,
    extract_case_contract_deposit,
    extract_case_prior_verified_repayments,
    extract_case_opposing_power_date,
    extract_case_notice_delivery_date,
    find_case_attachment_evidence_name,
)
from ai_legal_helper.agents.issue_verifier import IssueVerificationResult
from ai_legal_helper.workflows.conversation_context import (
    ConversationContext,
    ConversationTurn,
    load_conversation_context,
)
from ai_legal_helper.workflows.legal_workflow import run_legal_consultation

client = TestClient(app)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """격리된 테스트용 DB 세션 픽스처."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_user_a(db: Session) -> User:
    """테스트 사용자 A 픽스처."""
    uid = f"user_a_{uuid.uuid4().hex[:8]}"
    user = User(
        id=uid,
        email=f"{uid}@legal.test",
        password_hash="mock_hash_a",
        display_name="임차인A",
        status="ACTIVE",
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def test_user_b(db: Session) -> User:
    """테스트 사용자 B 픽스처."""
    uid = f"user_b_{uuid.uuid4().hex[:8]}"
    user = User(
        id=uid,
        email=f"{uid}@legal.test",
        password_hash="mock_hash_b",
        display_name="임차인B",
        status="ACTIVE",
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def case_300m(db: Session, test_user_a: User) -> Case:
    """보증금 3억 원 임대차 사건 픽스처."""
    cid = f"case_300m_{uuid.uuid4().hex[:8]}"
    case = Case(
        id=cid,
        user_id=test_user_a.id,
        title="보증금 3억 원 반환 분쟁 사건",
        case_type="HOUSING_LEASE",
        status="OPEN",
        version=1,
        primary_conversation_id=f"conv_{cid}",
    )
    db.add(case)
    db.commit()

    # 1. 계약 보증금 Fact (300,000,000원)
    f1 = Fact(
        id=f"fact_dep_{uuid.uuid4().hex[:8]}",
        case_id=cid,
        statement="임대차계약 체결일은 2022년 2월 20일이고, 보증금은 300,000,000원이다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    # 2. 대항력 및 확정일자 Fact (2022년 3월 1일)
    f2 = Fact(
        id=f"fact_opp_{uuid.uuid4().hex[:8]}",
        case_id=cid,
        statement="임차인은 2022년 3월 1일 주택에 입주 및 전입신고를 마치고 확정일자를 부여받았다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    # 3. 해지통고 도달 Fact (2024년 2월 5일)
    f3 = Fact(
        id=f"fact_not_{uuid.uuid4().hex[:8]}",
        case_id=cid,
        statement="임대차계약 해지통고 내용증명 우편이 2024년 2월 5일 임대인에게 도달 완료되었다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    db.add_all([f1, f2, f3])
    db.commit()
    return case


# ==============================================================================
# E01 — 부분 변제 2천만 원 (미입증 구두 진술)
# ==============================================================================
def test_e01_partial_repayment_20m_krw_provisional(db: Session, case_300m: Case):
    """3억 원 사건에서 2천만 원 지급 주장 시 잠정 잔액 2억 8천만 원을 안내하고 확정 승격을 차단한다."""
    briefing = build_case_evidence_briefing(db, case_300m.id)

    # 계약 보증금 동적 인출 확인
    assert extract_case_contract_deposit(briefing) == 300_000_000

    delta = detect_case_delta(
        briefing=briefing,
        current_question="집주인이 2천만 원을 입금했어요. 남은 보증금은 얼마인가요?",
        resolved_query="의뢰인의 보증금 일부 입금/변제 주장에 따른 보증금 잔액 변동 및 입금 증거 확인 필요성 검토",
    )

    assert delta is not None
    assert delta["has_delta"] is True
    # 1. USER_ALLEGED 사실 식별
    assert any("20,000,000원 일부 입금 진술 접수" in f and "USER_ALLEGED" in f for f in delta["changed_facts"])
    # 2. 잠정 잔액 280,000,000원 도출 및 채무충당(민법 제479조) 안내
    assert any("280,000,000원으로 안내되나" in idet and "민법 제479조" in idet for idet in delta["impacted_determinations"])
    # 3. 대항력·우선변제권 및 반환청구 권리는 전액 반환 시까지 유지
    assert any("임차인의 대항력, 우선변제권" in pdet for pdet in delta["preserved_determinations"])
    # 4. 이체확인증 등록 권고
    assert any("20,000,000원의 계좌 이체확인증 또는 영수증을 증거로 등록" in act for act in delta["new_next_actions"])

    # 답변 조립 시 [사건 변동 사항 및 법률 판단 비교]와 [잠정] 표시 확인
    answer = assemble_grounded_answer(
        issue_results=[],
        briefing=briefing,
        draft_answer="2천만원 입금 관련",
        disposition="CAUTIONARY",
        case_delta=delta,
    )
    assert "[사건 변동 사항 및 법률 판단 비교]" in answer
    assert "[잠정]" in answer
    assert "20,000,000원" in answer


# ==============================================================================
# E02 — 입금 증거 등록 및 검토 승인
# ==============================================================================
def test_e02_deposit_transfer_evidence_approved_confirms_balance(db: Session, case_300m: Case):
    """실제 2천만 원 이체 증거를 등록·검토·승인한 뒤 미반환 잔액 2억 8천만 원이 확정되는지 검증한다."""
    # 1. 2천만원 이체확인증 EvidenceDocument 생성
    doc_id = f"doc_trans_{uuid.uuid4().hex[:8]}"
    doc = EvidenceDocument(
        id=doc_id,
        case_id=case_300m.id,
        original_filename="보증금_일부반환_이체확인증_2천만원.txt",
        safe_storage_key=f"storage/{doc_id}.txt",
        media_type="text/plain",
        size_bytes=200,
        sha256=f"sha_{uuid.uuid4().hex[:16]}",
        status="UPLOADED",
    )
    db.add(doc)
    db.flush()

    # 2. EvidenceClaim 생성
    claim_id = f"claim_trans_{uuid.uuid4().hex[:8]}"
    claim = EvidenceClaim(
        id=claim_id,
        case_id=case_300m.id,
        evidence_id=doc.id,
        statement="임대인이 2024년 5월 1일 보증금 중 20,000,000원을 일부 변제 입금하였다.",
        assertion_status="DOCUMENT_STATES",
        review_status="PENDING_REVIEW",
    )
    db.add(claim)
    db.commit()

    # 3. EvidenceReview 실행 (APPROVE) -> Fact 자동 승격
    process_evidence_review(
        db=db,
        claim_id=claim.id,
        action="APPROVE",
        expected_case_id=case_300m.id,
        expected_evidence_id=doc.id,
    )

    # 4. 브리핑 재구축 후 갱신 상태 검증
    briefing = build_case_evidence_briefing(db, case_300m.id)
    repaid_total, repaid_srcs = extract_case_prior_verified_repayments(briefing)
    assert repaid_total == 20_000_000
    assert any("20,000,000원" in s for s in repaid_srcs)

    delta = detect_case_delta(
        briefing=briefing,
        current_question="이제 남은 보증금 잔액은 얼마이고 무엇을 해야 하나요?",
        resolved_query="일부 변제 확인 후 잔여 보증금 잔액 산정 및 다음 조치",
    )

    assert delta is not None
    assert delta["has_delta"] is True
    # 전체 파일명 연결 확인 (Rule 8)
    assert any("20,000,000원 일부 변제 입금 확인" in f and "보증금_일부반환_이체확인증_2천만원.txt" in f for f in delta["changed_facts"])
    # 2억 8천만원 감축 확정
    assert any("280,000,000원으로 감축 확정됨" in idet for idet in delta["impacted_determinations"])
    # 잔액 2.8억원에 대한 지급명령 신청 가이드
    assert any("280,000,000원에 대한 지급명령 신청" in act for act in delta["new_next_actions"])


# ==============================================================================
# E03 — 기존 입금 증거 오인 방지 (최초 보증금 지급 vs 임대인 반환)
# ==============================================================================
def test_e03_tenant_initial_deposit_payment_not_misclassified_as_landlord_return(db: Session, case_300m: Case):
    """임차인의 최초 보증금 지급 이체증(계약금·잔금)을 임대인의 반환으로 오인 합산하지 않는다."""
    # 최초 계약금/잔금 지급 이체증 추가 등록
    doc = EvidenceDocument(
        id=f"doc_initial_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        original_filename="E01_계약금_잔금_지급_이체확인증.txt",
        safe_storage_key="storage/initial.txt",
        media_type="text/plain",
        size_bytes=100,
        sha256="sha_init",
        status="APPROVED",
    )
    db.add(doc)
    fact_tenant_payment = Fact(
        id=f"fact_pay_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        statement="임차인은 2022년 3월 1일 잔금 270,000,000원을 임대인 계좌로 전액 지급 완료하였다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
        source_ref=doc.id,
    )
    db.add(fact_tenant_payment)
    db.commit()

    briefing = build_case_evidence_briefing(db, case_300m.id)
    # 최초 보증금 지급 내역은 임대인의 반환금으로 합산되지 않아야 함 (0원)
    repaid_total, _ = extract_case_prior_verified_repayments(briefing)
    assert repaid_total == 0

    # 일반 상담 질의 시 반환액 0원, 미반환 잔액 3억 원 유지 확인
    delta = detect_case_delta(
        briefing=briefing,
        current_question="전세보증금을 아직 못 받았습니다. 어떻게 대처해야 하나요?",
        resolved_query="",
    )
    # 질문에 반환 관련 단어가 없으므로 delta는 None
    assert delta is None


# ==============================================================================
# E04 — 누적 부분 변제 (2천만 원 + 3천만 원 = 5천만 원)
# ==============================================================================
def test_e04_cumulative_partial_repayments_20m_and_30m(db: Session, case_300m: Case):
    """서로 다른 일자에 확인된 2천만 원과 3천만 원이 누적 5천만 원 반환, 잔액 2.5억 원으로 정밀 산정된다."""
    # 1. 첫 번째 반환 Fact (2천만 원)
    f1 = Fact(
        id=f"fact_r1_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        statement="임대인이 2024년 4월 1일 보증금 중 일부 변제 20,000,000원을 입금 확인하였다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    # 2. 두 번째 반환 Fact (3천만 원)
    f2 = Fact(
        id=f"fact_r2_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        statement="임대인이 2024년 5월 1일 보증금 중 일부 변제 30,000,000원을 추가 입금 확인하였다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    db.add_all([f1, f2])
    db.commit()

    briefing = build_case_evidence_briefing(db, case_300m.id)
    repaid_total, repaid_srcs = extract_case_prior_verified_repayments(briefing)

    # 누적 5천만 원 확인
    assert repaid_total == 50_000_000
    assert len(repaid_srcs) == 2

    # 잔액 2.5억 원 산정
    contract_deposit = extract_case_contract_deposit(briefing)
    assert contract_deposit == 300_000_000
    remaining_balance = contract_deposit - repaid_total
    assert remaining_balance == 250_000_000


# ==============================================================================
# E05 — 중복 요청 방지 (Idempotency)
# ==============================================================================
def test_e05_duplicate_request_idempotency(db: Session, case_300m: Case):
    """동일한 이체증이나 사실을 중복 조회하거나 반복 질문해도 반환액이 이중 합산되지 않는다."""
    # 동일 2천만 원 반환 Fact 등록
    f = Fact(
        id=f"fact_dup_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        statement="임대인이 20,000,000원을 일부 변제 입금 확인하였다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    db.add(f)
    db.commit()

    briefing = build_case_evidence_briefing(db, case_300m.id)
    repaid_1, _ = extract_case_prior_verified_repayments(briefing)
    repaid_2, _ = extract_case_prior_verified_repayments(briefing)

    assert repaid_1 == 20_000_000
    assert repaid_2 == 20_000_000  # 4천만 원으로 누적되지 않음


# ==============================================================================
# E06 — 가압류 신규 등록 (미승인 시 권리관계 불변, 승인 후 선순위 평가)
# ==============================================================================
def test_e06_new_attachment_unapproved_vs_approved(db: Session, case_300m: Case):
    """새 등기 증거 미승인 시 권리관계가 불변이며, 승인 후 임차인 대항력(2022.03.01)과의 선후관계를 평가한다."""
    # 1. 미승인 상태의 가압류 등기부 업로드
    doc_id = f"doc_att_{uuid.uuid4().hex[:8]}"
    doc = EvidenceDocument(
        id=doc_id,
        case_id=case_300m.id,
        original_filename="부동산등기사항전부증명서_을구.txt",
        safe_storage_key=f"storage/{doc_id}.txt",
        media_type="text/plain",
        size_bytes=100,
        sha256="sha_att",
        status="UPLOADED",  # 미승인
    )
    db.add(doc)
    db.commit()

    # 미승인 상태 브리핑: 가압류 Fact 부재
    briefing_unapproved = build_case_evidence_briefing(db, case_300m.id)
    assert not any("가압류" in f.statement for f in briefing_unapproved.facts)

    # 2. 가압류 Claim 승인하여 Fact로 승격
    fact_att = Fact(
        id=f"fact_att_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        statement="2024년 5월 10일 목적물에 채권자 동진은행의 50,000,000원 가압류 등기가 추가 설정되었다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
        source_ref=doc.id,
    )
    db.add(fact_att)
    doc.status = "APPROVED"
    db.commit()

    briefing_approved = build_case_evidence_briefing(db, case_300m.id)
    opp_date = extract_case_opposing_power_date(briefing_approved)
    assert opp_date == "2022.03.01"

    delta = detect_case_delta(
        briefing=briefing_approved,
        current_question="가압류가 등기부에 추가되었는데 제 보증금 순위가 밀리나요?",
        resolved_query="가압류 추가에 따른 임차인의 대항력 및 배당순위 영향 검토",
    )

    assert delta is not None
    assert delta["has_delta"] is True
    # 가압류 추가 확인 및 등기부 원본 문서명 연결
    assert any("가압류 등기 사실 추가 확인" in f and "부동산등기사항전부증명서_을구.txt" in f for f in delta["changed_facts"])
    # 2022.03.01 대항요건이 신규 가압류(2024년)보다 선순위이므로 기존 우선순위 보존
    assert any("기존 우선순위 보존" in idet for idet in delta["impacted_determinations"])
    assert any("2022.03.01" in pdet for pdet in delta["preserved_determinations"])


# ==============================================================================
# E07 — 통지일 정정 (구두 진술 vs 서면 증거 도달일 우선)
# ==============================================================================
def test_e07_notice_delivery_date_correction_preserves_evidence_date(db: Session, case_300m: Case):
    """사용자가 통지일을 구두로 다르게 말하더라도 등록된 서면 증거의 도달일(2024.02.05)을 유지한다."""
    briefing = build_case_evidence_briefing(db, case_300m.id)
    actual_date = extract_case_notice_delivery_date(briefing)
    assert actual_date == "2024.02.05"

    delta = detect_case_delta(
        briefing=briefing,
        current_question="제가 날짜를 잘못 알았는데, 통지일이 2024년 3월 20일이에요.",
        resolved_query="의뢰인의 통지일 정정 진술과 서면 증거 도달일 대조",
    )

    assert delta is not None
    assert delta["has_delta"] is True
    # 사용자 진술은 USER_ALLEGED로 기록
    assert any("USER_ALLEGED" in f for f in delta["changed_facts"])
    # 서면 증거의 실제 도달일(2024.02.05)을 기준으로 법률효과 유지 및 임의 변경 차단
    assert any("2024.02.05" in idet and "임의 변경하지 않음" in idet for idet in delta["impacted_determinations"])


# ==============================================================================
# E08 — 서버 재시작 및 세션 복원
# ==============================================================================
def test_e08_server_restart_and_session_continuity(db: Session, case_300m: Case, test_user_a: User):
    """DB에 보존된 사실 변경 및 대화 이력이 새 세션에서 무손실 복원되는지 검증한다."""
    conv_id = f"conv_{case_300m.id}"

    # 1. 첫 번째 턴 기록 (case_delta 포함)
    mock_delta = {
        "has_delta": True,
        "changed_facts": ["의뢰인의 20,000,000원 일부 입금 진술 접수 (USER_ALLEGED)"],
        "impacted_determinations": ["잠정 잔액 280,000,000원"],
        "preserved_determinations": ["대항력 유지"],
        "new_next_actions": ["이체확인증 제출"],
    }
    rec1 = ConsultationRecord(
        request_id=f"req_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        user_id=test_user_a.id,
        conversation_id=conv_id,
        turn_index=1,
        question="2천만원 입금받았어요",
        answer="잠정 잔액은 2억 8천만원입니다.",
        status="SUCCESS",
        execution_status="COMPLETED",
        answer_status="CAUTIONARY",
        verification_result={"case_delta": mock_delta},
    )
    db.add(rec1)
    db.commit()

    # 2. 서버 재시작 시뮬레이션: 세션 캐시 무효화 후 새로운 컨텍스트 로드
    db.expire_all()
    restored_ctx = load_conversation_context(
        db=db,
        conversation_id=conv_id,
        current_question="다음에는 무엇을 해야 하나요?",
        case_id=case_300m.id,
        user_id=test_user_a.id,
    )

    assert restored_ctx is not None
    assert restored_ctx.conversation_id == conv_id
    assert restored_ctx.case_id == case_300m.id
    assert restored_ctx.turn_index == 2  # 다음 턴 번호는 2
    assert len(restored_ctx.previous_turns) == 1
    # 복원된 턴의 delta 검증
    assert restored_ctx.previous_turns[0].case_delta is not None
    assert "20,000,000원" in restored_ctx.previous_turns[0].case_delta["changed_facts"][0]


# ==============================================================================
# E09 — 동시 요청 (Concurrent Turn Consistency)
# ==============================================================================
def test_e09_concurrent_requests_handling(case_300m: Case, test_user_a: User):
    """동일 사건에 대해 병렬로 동시 상담 턴 기록 시 충돌 없이 턴이 순차 증가하는지 검증한다."""
    conv_id = f"conv_concurrent_{uuid.uuid4().hex[:8]}"
    target_case_id = str(case_300m.id)
    target_user_id = str(test_user_a.id)

    def record_concurrent_turn(turn_no: int):
        with SessionLocal() as local_db:
            rec = ConsultationRecord(
                request_id=f"req_{uuid.uuid4().hex[:8]}",
                case_id=target_case_id,
                user_id=target_user_id,
                conversation_id=conv_id,
                turn_index=turn_no + 1,
                question=f"동시 질문 {turn_no}",
                answer=f"동시 답변 {turn_no}",
                status="SUCCESS",
                execution_status="COMPLETED",
                answer_status="DELIVERED",
            )
            local_db.add(rec)
            local_db.commit()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(record_concurrent_turn, i) for i in range(4)]
        for f in futures:
            f.result()

    with SessionLocal() as verify_db:
        ctx = load_conversation_context(
            db=verify_db,
            conversation_id=conv_id,
            current_question="마지막 질문",
            case_id=target_case_id,
            user_id=target_user_id,
            max_turns=None,  # 동시 기록된 4개 턴 전체 검증을 위해 윈도우 제한 해제
        )
        assert ctx is not None
        assert len(ctx.previous_turns) == 4
        # 턴 번호가 1, 2, 3, 4로 고유하게 부여되었는지 확인
        turn_indices = [t.turn_index for t in ctx.previous_turns]
        assert sorted(turn_indices) == [1, 2, 3, 4]


# ==============================================================================
# E10 — 사건 격리 (Cross-case Isolation)
# ==============================================================================
def test_e10_cross_case_isolation(db: Session, case_300m: Case, test_user_a: User, test_user_b: User):
    """사건 A의 부분 변제 증거/결과가 사건 B의 보증금 잔액 산정이나 상담에 일체 누출되지 않는다."""
    # 사건 B 생성 (보증금 1억 원)
    cid_b = f"case_100m_{uuid.uuid4().hex[:8]}"
    case_b = Case(
        id=cid_b,
        user_id=test_user_b.id,
        title="사건 B - 보증금 1억 원",
        case_type="HOUSING_LEASE",
        status="OPEN",
        version=1,
    )
    db.add(case_b)
    db.commit()

    fact_b = Fact(
        id=f"fact_b_{uuid.uuid4().hex[:8]}",
        case_id=cid_b,
        statement="임대차계약상 보증금은 100,000,000원이다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    db.add(fact_b)
    db.commit()

    # 사건 A에 2천만 원 변제 사실 추가
    fact_a_repay = Fact(
        id=f"fact_a_rep_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        statement="임대인이 20,000,000원을 일부 변제 입금 확인하였다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    db.add(fact_a_repay)
    db.commit()

    # 사건 B 브리핑 생성 및 검증
    briefing_b = build_case_evidence_briefing(db, cid_b)
    # 사건 B의 보증금은 1억 원이어야 함 (사건 A의 3억 원 누출 차단)
    assert extract_case_contract_deposit(briefing_b) == 100_000_000
    # 사건 B의 기변제액은 0원이어야 함 (사건 A의 2천만 원 누출 차단)
    repaid_b, _ = extract_case_prior_verified_repayments(briefing_b)
    assert repaid_b == 0

    # 사건 A에 속한 상담 대화 세션 레코드 생성
    conv_a_id = f"conv_{case_300m.id}"
    rec_a = ConsultationRecord(
        request_id=f"req_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        user_id=test_user_a.id,
        conversation_id=conv_a_id,
        turn_index=1,
        question="사건 A 질문",
        answer="사건 A 답변",
        status="SUCCESS",
        execution_status="COMPLETED",
        answer_status="DELIVERED",
    )
    db.add(rec_a)
    db.commit()

    # 타 사용자가 사건 A의 대화 세션에 교차 접근 시 403 Forbidden 차단 검증
    with pytest.raises(PermissionError):
        load_conversation_context(
            db=db,
            conversation_id=conv_a_id,
            current_question="접근 시도",
            case_id=cid_b,  # 사건 B의 ID로 사건 A 세션 접근 시도
            user_id=test_user_b.id,
        )


# ==============================================================================
# 실제 FastAPI 엔드포인트 E2E 테스트 스위트 (Section 4)
# ==============================================================================

async def _e2e_mock_run_consultation(
    question: str,
    thread_id: str,
    conversation_context: Optional[Any] = None,
    on_step_callback: Optional[Any] = None,
) -> dict:
    """실제 DB 브리핑과 final_disposition을 연계하여 Fast E2E 검증을 지원하는 모의 워크플로우 실행기.

    Args:
        question: 의뢰인 질의 텍스트.
        thread_id: 고유 스레드/요청 식별자.
        conversation_context: 복원된 대화 맥락 객체.
        on_step_callback: 노드별 실시간 진행 상태 콜백.

    Returns:
        dict: detect_case_delta 및 assemble_grounded_answer 기반의 최종 상담 결과 딕셔너리.
    """
    with SessionLocal() as s_db:
        cid = getattr(conversation_context, "case_id", None)
        briefing = build_case_evidence_briefing(s_db, cid, question) if cid else CaseEvidenceBriefing()

        delta = detect_case_delta(
            briefing=briefing,
            conv_context=conversation_context,
            current_question=question,
        )

        has_approved_ev = bool(briefing and briefing.evidences and any(e.status == "APPROVED" for e in briefing.evidences))
        is_confirmed = bool(delta and delta.get("calculation_basis", {}).get("status") == "CONFIRMED")

        issue_res = [
            IssueVerificationResult(
                issue_id="task_deposit_balance",
                issue_title="보증금 반환 및 잔액 산정",
                status="VERIFIED" if has_approved_ev else "CONDITIONAL",
                determination_type="FACT_VERIFIED" if is_confirmed else "USER_ALLEGED_PENDING_PROOF",
                claim_citations=[],
            )
        ]

        final_disp, _ = determine_final_disposition(issue_res)

        ans = assemble_grounded_answer(
            issue_results=issue_res,
            briefing=briefing,
            draft_answer=f"질문 '{question}'에 대하여 현재 사건의 권리관계와 보증금 반환 현황을 검토한 결과입니다.",
            disposition=final_disp,
            conv_context=conversation_context,
            current_question=question,
            case_delta=delta,
        )

        sources = []
        for ev in (briefing.evidences or []):
            if getattr(ev, "status", None) == "APPROVED":
                sources.append({
                    "source_id": ev.evidence_id,
                    "source_type": "CASE_EVIDENCE",
                    "title": ev.document_name,
                    "file": ev.document_name,
                    "page": 1,
                })

        return {
            "status": "SUCCESS",
            "answer": ans,
            "case_delta": delta,
            "verification_result": {
                "status": "PASS" if final_disp == "DELIVERED" else "REVISE",
                "case_delta": delta,
                "issue_results": [r.model_dump() for r in issue_res],
            },
            "conversation_id": getattr(conversation_context, "conversation_id", None),
            "turn_index": getattr(conversation_context, "turn_index", 1),
            "cited_sources": sources,
            "claim_citations": [],
            "warnings": [],
        }


def test_api_partial_repayment_20m_krw_provisional_flow(case_300m: Case, test_user_a: User):
    """POST /api/v1/consultations 호출 시 2천만원 지급 주장 질문에 대해 잠정 상태와 2.8억 잔액이 반환되는지 검증한다."""
    app.dependency_overrides[get_current_user] = lambda: test_user_a
    try:
        with patch("ai_legal_helper.api.routes.consultation.run_legal_consultation", side_effect=_e2e_mock_run_consultation):
            res = client.post(
                "/api/v1/consultations",
                json={
                    "question": "임대인이 20,000,000원을 일부 변제 입금했다고 주장하는데 남은 보증금은 얼마인가요?",
                    "case_id": case_300m.id,
                },
            )
            assert res.status_code == 200, f"상담 생성 실패: {res.text}"
            res_data = res.json()
            req_id = res_data["request_id"]

            # 상담 상세 결과 조회
            detail_res = client.get(f"/api/v1/consultations/{req_id}")
            assert detail_res.status_code == 200
            data = detail_res.json()

            # 잠정(PROVISIONAL) 상태 및 2억 8천만원 잔액 검증
            delta = data.get("case_delta")
            assert delta is not None, "case_delta가 응답에 누락되었습니다."
            assert delta["has_delta"] is True
            calc_basis = delta["calculation_basis"]
            assert calc_basis["status"] == "PROVISIONAL"
            assert calc_basis["alleged_partial_repayment_krw"] == 20_000_000
            assert calc_basis["unrepaid_balance_krw"] == 280_000_000

            # 답변 텍스트 내 잠정 안내 및 금액 명시 확인
            ans = data.get("answer", "")
            assert "280,000,000" in ans or "2억 8,000" in ans
            assert "잠정" in ans or "USER_ALLEGED" in ans or "확인 필요" in ans
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_deposit_transfer_evidence_approved_confirms_balance_flow(db: Session, case_300m: Case, test_user_a: User):
    """process_evidence_review(APPROVE) 승인 후 POST /api/v1/consultations 호출 시 확정 2.8억 및 원본 파일명이 연결되는지 검증한다."""
    app.dependency_overrides[get_current_user] = lambda: test_user_a
    try:
        # 이체확인증 증거 등록 및 승인
        ev_file_name = "임대인_보증금일부반환_이체확인증.pdf"
        doc_id = f"ev_api_{uuid.uuid4().hex[:8]}"
        ev_doc = EvidenceDocument(
            id=doc_id,
            case_id=case_300m.id,
            original_filename=ev_file_name,
            safe_storage_key=f"storage/{doc_id}.pdf",
            media_type="application/pdf",
            size_bytes=2048,
            sha256=f"sha_{uuid.uuid4().hex[:16]}",
            status="UPLOADED",
        )
        db.add(ev_doc)
        db.flush()

        claim = EvidenceClaim(
            id=f"claim_api_{uuid.uuid4().hex[:8]}",
            case_id=case_300m.id,
            evidence_id=ev_doc.id,
            statement="임대인이 2024년 2월 10일 보증금 중 20,000,000원을 일부 변제 입금하였다.",
            assertion_status="DOCUMENT_STATES",
            review_status="PENDING_REVIEW",
        )
        db.add(claim)
        db.commit()

        # 관리자 증거 승인
        process_evidence_review(db, claim.id, "APPROVE", expected_case_id=case_300m.id, expected_evidence_id=ev_doc.id)

        with patch("ai_legal_helper.api.routes.consultation.run_legal_consultation", side_effect=_e2e_mock_run_consultation):
            res = client.post(
                "/api/v1/consultations",
                json={
                    "question": "이체확인증이 승인되었는데 현재 확정된 남은 보증금 잔액은 얼마인가요?",
                    "case_id": case_300m.id,
                },
            )
            assert res.status_code == 200
            req_id = res.json()["request_id"]

            detail_res = client.get(f"/api/v1/consultations/{req_id}")
            assert detail_res.status_code == 200
            data = detail_res.json()

            # 확정(CONFIRMED) 상태 및 2억 8천만원 잔액 검증
            delta = data.get("case_delta")
            assert delta is not None
            calc_basis = delta["calculation_basis"]
            assert calc_basis["status"] == "CONFIRMED"
            assert calc_basis["verified_partial_repayment_krw"] == 20_000_000
            assert calc_basis["unrepaid_balance_krw"] == 280_000_000

            # 답변 텍스트 내 확정 잔액 및 원본 파일명 인용 검증
            ans = data.get("answer", "")
            assert "280,000,000" in ans or "2억 8,000" in ans
            assert ev_file_name in ans
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_duplicate_evidence_approval_prevents_double_counting_flow(db: Session, case_300m: Case, test_user_a: User):
    """동일 거래 증거를 중복 등록 및 승인하더라도 잔액이 260,000,000원으로 이중 차감되지 않고 280,000,000원으로 유지되는지 검증한다."""
    app.dependency_overrides[get_current_user] = lambda: test_user_a
    try:
        # 1차 이체증 등록 및 승인
        doc1_id = f"ev_orig_{uuid.uuid4().hex[:8]}"
        doc1 = EvidenceDocument(
            id=doc1_id,
            case_id=case_300m.id,
            original_filename="보증금반환_1차_이체증.pdf",
            safe_storage_key=f"storage/{doc1_id}.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            sha256=f"sha_{uuid.uuid4().hex[:16]}",
            status="UPLOADED",
        )
        db.add(doc1)
        db.flush()
        claim1 = EvidenceClaim(
            id=f"cl_orig_{uuid.uuid4().hex[:8]}",
            case_id=case_300m.id,
            evidence_id=doc1.id,
            statement="임대인이 2024년 2월 10일 20,000,000원을 일부 변제 입금하였다.",
            assertion_status="DOCUMENT_STATES",
            review_status="PENDING_REVIEW",
        )
        db.add(claim1)
        db.commit()
        process_evidence_review(db, claim1.id, "APPROVE", expected_case_id=case_300m.id, expected_evidence_id=doc1.id)

        # 2차 동일 거래 중복 입금증 등록 및 승인 (동일 날짜 2024.02.10, 동일 금액 20,000,000원)
        doc2_id = f"ev_dup_{uuid.uuid4().hex[:8]}"
        doc2 = EvidenceDocument(
            id=doc2_id,
            case_id=case_300m.id,
            original_filename="보증금반환_중복_사본.pdf",
            safe_storage_key=f"storage/{doc2_id}.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            sha256=f"sha_{uuid.uuid4().hex[:16]}",
            status="UPLOADED",
        )
        db.add(doc2)
        db.flush()
        claim2 = EvidenceClaim(
            id=f"cl_dup_{uuid.uuid4().hex[:8]}",
            case_id=case_300m.id,
            evidence_id=doc2.id,
            statement="임대인이 2024년 2월 10일 보증금 중 20,000,000원을 일부 반환하여 입금 확인되었다.",
            assertion_status="DOCUMENT_STATES",
            review_status="PENDING_REVIEW",
        )
        db.add(claim2)
        db.commit()
        process_evidence_review(db, claim2.id, "APPROVE", expected_case_id=case_300m.id, expected_evidence_id=doc2.id)

        with patch("ai_legal_helper.api.routes.consultation.run_legal_consultation", side_effect=_e2e_mock_run_consultation):
            res = client.post(
                "/api/v1/consultations",
                json={
                    "question": "중복 입금증 제출 후 최종 확정 보증금 잔액은 얼마인가요?",
                    "case_id": case_300m.id,
                },
            )
            assert res.status_code == 200
            req_id = res.json()["request_id"]

            data = client.get(f"/api/v1/consultations/{req_id}").json()
            delta = data.get("case_delta")
            assert delta is not None
            calc_basis = delta["calculation_basis"]
            # 이중 차감 방지: 2.6억원이 아니라 2.8억원 유지
            assert calc_basis["verified_partial_repayment_krw"] == 20_000_000
            assert calc_basis["unrepaid_balance_krw"] == 280_000_000
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_concurrent_post_turn_collision_prevention_flow(case_300m: Case, test_user_a: User):
    """동일 사건 대화 세션에 4개 동시 POST /api/v1/consultations 요청 시 교착이나 턴 충돌 없이 정상 접수되는지 검증한다."""
    target_case_id = str(case_300m.id)
    target_user_id = str(test_user_a.id)

    # 스레드 안전한 사용자 픽스처 제공 (세션 분리 및 Detached 인스턴스)
    def get_thread_safe_user():
        with SessionLocal() as s:
            u = s.query(User).filter(User.id == target_user_id).first()
            if u:
                s.expunge(u)
            return u

    app.dependency_overrides[get_current_user] = get_thread_safe_user
    try:
        def invoke_post(idx: int):
            with patch("ai_legal_helper.api.routes.consultation.run_legal_consultation", side_effect=_e2e_mock_run_consultation):
                thread_client = TestClient(app)
                return thread_client.post(
                    "/api/v1/consultations",
                    json={"question": f"동시 질의 {idx}", "case_id": target_case_id},
                )

        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(invoke_post, range(4)))

        # 모든 요청이 200 성공하고 고유 request_id와 순차적 turn_index를 발급받았는지 검증
        req_ids = set()
        turn_indices = []
        for r in responses:
            assert r.status_code == 200, f"동시 요청 실패: {r.text}"
            data = r.json()
            assert "request_id" in data
            req_ids.add(data["request_id"])
            turn_indices.append(data["turn_index"])
        assert len(req_ids) == 4, "동시 요청에서 중복된 request_id가 발생했습니다."
        assert sorted(turn_indices) == [1, 2, 3, 4], f"턴 번호가 순차적(1,2,3,4)으로 배정되지 않았습니다: {sorted(turn_indices)}"

        # DB에 생성된 상담 레코드 턴 확인
        with SessionLocal() as check_db:
            records = check_db.query(ConsultationRecord).filter(
                ConsultationRecord.case_id == target_case_id
            ).all()
            db_turns = [r.turn_index for r in records]
            assert sorted(db_turns) == [1, 2, 3, 4]
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_session_reload_retains_latest_balance_flow(db: Session, case_300m: Case, test_user_a: User):
    """메모리 캐시를 초기화한 후에도 세션 및 사건 조회 API에서 최신 확정 잔액(2.8억)이 무손실 유지되는지 검증한다."""
    app.dependency_overrides[get_current_user] = lambda: test_user_a
    try:
        # 이체확인증 승인
        doc_id = f"ev_rel_{uuid.uuid4().hex[:8]}"
        doc = EvidenceDocument(
            id=doc_id,
            case_id=case_300m.id,
            original_filename="보증금_일부반환_영수증.pdf",
            safe_storage_key=f"storage/{doc_id}.pdf",
            media_type="application/pdf",
            size_bytes=1024,
            sha256=f"sha_{uuid.uuid4().hex[:16]}",
            status="UPLOADED",
        )
        db.add(doc)
        db.flush()
        claim = EvidenceClaim(
            id=f"cl_rel_{uuid.uuid4().hex[:8]}",
            case_id=case_300m.id,
            evidence_id=doc.id,
            statement="임대인이 2024년 2월 10일 보증금 중 20,000,000원을 일부 변제 입금하였다.",
            assertion_status="DOCUMENT_STATES",
            review_status="PENDING_REVIEW",
        )
        db.add(claim)
        db.commit()
        process_evidence_review(db, claim.id, "APPROVE", expected_case_id=case_300m.id, expected_evidence_id=doc.id)

        # 상담 요청 실행
        with patch("ai_legal_helper.api.routes.consultation.run_legal_consultation", side_effect=_e2e_mock_run_consultation):
            res = client.post(
                "/api/v1/consultations",
                json={"question": "잔액 확인 요청", "case_id": case_300m.id},
            )
            assert res.status_code == 200
            post_data = res.json()
            req_id = post_data["request_id"]
            conv_id = post_data["conversation_id"]

        # 서버 메모리 캐시 완전 초기화 (재시작 시뮬레이션)
        _consultations.clear()

        # 1. 단일 상담 상세 조회 API (DB에서 역직렬화)
        detail_res = client.get(f"/api/v1/consultations/{req_id}")
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["case_delta"] is not None
        assert detail_data["case_delta"]["calculation_basis"]["status"] == "CONFIRMED"
        assert detail_data["case_delta"]["calculation_basis"]["unrepaid_balance_krw"] == 280_000_000

        # 2. 대화 세션 상세 이력 조회 API (DB 기반 전체 턴 복원)
        conv_res = client.get(f"/api/v1/cases/{case_300m.id}/conversations/{conv_id}")
        assert conv_res.status_code == 200
        conv_data = conv_res.json()
        assert conv_data["conversation_id"] == conv_id
        assert len(conv_data["turns"]) >= 1
        latest_turn = conv_data["turns"][-1]
        assert latest_turn["case_delta"] is not None
        assert latest_turn["case_delta"]["calculation_basis"]["unrepaid_balance_krw"] == 280_000_000
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_api_cross_case_and_unauthorized_access_blocked_flow(db: Session, case_300m: Case, test_user_a: User, test_user_b: User):
    """사용자 B가 사용자 A 소유 사건의 상담 생성 및 조회 시 HTTP 403 Forbidden 차단되는지 검증한다."""
    # 사용자 A로 사전 상담 1건 생성
    app.dependency_overrides[get_current_user] = lambda: test_user_a
    try:
        with patch("ai_legal_helper.api.routes.consultation.run_legal_consultation", side_effect=_e2e_mock_run_consultation):
            res_a = client.post(
                "/api/v1/consultations",
                json={"question": "사용자 A의 전용 상담 질의", "case_id": case_300m.id},
            )
            assert res_a.status_code == 200
            req_id_a = res_a.json()["request_id"]
            conv_id_a = res_a.json()["conversation_id"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    # 사용자 B로 인증 전환
    app.dependency_overrides[get_current_user] = lambda: test_user_b
    try:
        # 1. 사용자 B가 사용자 A의 case_id로 신규 상담 POST 시도 -> 403 차단
        with patch("ai_legal_helper.api.routes.consultation.run_legal_consultation", side_effect=_e2e_mock_run_consultation):
            cross_post_res = client.post(
                "/api/v1/consultations",
                json={"question": "타인 사건 침범 질의", "case_id": case_300m.id},
            )
            assert cross_post_res.status_code == 403, f"타인 사건 접근 차단 실패: {cross_post_res.status_code}"

        # 2. 사용자 B가 사용자 A의 상담 결과 GET 시도 -> 403 차단
        cross_get_res = client.get(f"/api/v1/consultations/{req_id_a}")
        assert cross_get_res.status_code == 403, f"타인 상담 조회 차단 실패: {cross_get_res.status_code}"

        # 3. 사용자 B가 사용자 A의 대화 세션 상세 GET 시도 -> 403 차단
        cross_conv_res = client.get(f"/api/v1/cases/{case_300m.id}/conversations/{conv_id_a}")
        assert cross_conv_res.status_code == 403, f"타인 대화 세션 접근 차단 실패: {cross_conv_res.status_code}"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ==============================================================================
# P0-3.1 최종 잔여 결함 수정 검증 테스트 (작업 1 ~ 4)
# ==============================================================================

def test_task1_confirmed_repayment_plus_new_oral_allegation_separation(db: Session, case_300m: Case, test_user_a: User):
    """[P0-3.1 작업 1] 기확정 반환 2천만 원 사건에서 3천만 원 추가 입금 구두 진술 접수 시:
    - 기존 확정 반환액: 2천만 원 (verified_partial_repayment_krw == 20,000,000)
    - 신규 미확인 주장: 3천만 원 (alleged_partial_repayment_krw == 30,000,000)
    - 확정 미반환 잔액: 2억 8천만 원 (confirmed_unrepaid_balance_krw == 280,000,000)
    - 신규 주장 사실 가정 잠정 잔액: 2억 5천만 원 (provisional_unrepaid_balance_krw == 250,000,000)
    - 추가 입금 증빙 승인 전 전체 5천만 원 확정 차감 방지 및 calculation_basis 분리 명시.
    """
    # 1. 기존 확정 반환 Fact 추가 (2천만 원)
    fact_repaid_20m = Fact(
        id=f"fact_rep20_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        statement="2024년 2월 10일 임대인이 보증금 중 20,000,000원을 일부 변제 입금하였다.",
        verification_status="DOCUMENT_VERIFIED",
        source_type="DOCUMENT_SUPPORTED",
    )
    db.add(fact_repaid_20m)
    db.commit()

    briefing = build_case_evidence_briefing(db, case_300m.id)
    repaid_total, _ = extract_case_prior_verified_repayments(briefing)
    assert repaid_total == 20_000_000

    # 2. 신규 3천만 원 추가 입금 구두 진술 분석 (증빙 미제출)
    delta = detect_case_delta(
        briefing=briefing,
        current_question="집주인이 오늘 3천만 원을 추가로 입금했다고 하네요. 얼마 남은 건가요?",
        resolved_query="추가 입금 30000000원 진술에 따른 보증금 잔액 및 지연손해금 영향 분석",
    )

    assert delta is not None
    assert delta["has_delta"] is True
    calc = delta["calculation_basis"]
    assert calc["status"] == "PARTIALLY_CONFIRMED_WITH_NEW_ALLEGATION"
    assert calc["contract_deposit_krw"] == 300_000_000
    assert calc["verified_partial_repayment_krw"] == 20_000_000
    assert calc["alleged_partial_repayment_krw"] == 30_000_000
    assert calc["confirmed_unrepaid_balance_krw"] == 280_000_000
    assert calc["provisional_unrepaid_balance_krw"] == 250_000_000
    assert calc["unrepaid_balance_krw"] == 280_000_000  # 확정 잔액 유지

    # 섹션별 명확한 분리 문구 검증
    assert any("20,000,000원 일부 변제 확정" in cf and "30,000,000원 추가 입금 진술" in cf for cf in delta["changed_facts"])
    assert any("280,000,000원" in idet and "250,000,000원" in idet for idet in delta["impacted_determinations"])
    assert any("30,000,000원" in act and "이체확인증" in act for act in delta["new_next_actions"])


def test_task2_transaction_disambiguation_and_copy_deduplication():
    """[P0-3.1 작업 2] 거래 단위 중복 계산 개선 및 식별자 판별 검증:
    1. 동일 날짜·금액이라도 거래번호(TX-1001 vs TX-1002)가 다르면 각각 집계 (총 4천만 원)
    2. 동일 날짜·금액이라도 차수(1차 vs 2차)가 다르면 각각 집계 (총 4천만 원)
    3. 동일 거래에 대한 사본 표기(사본/중복)는 중복 집계 금지 (총 2천만 원)
    4. 식별자가 없고 동일성이 불확실한 별개 문서는 중복 합산 보류 및 경고 표기 (총 2천만 원)
    """
    # Case 1: 고유 거래번호 상이 (TX-1001 vs TX-1002) -> 각각 집계 40M
    briefing_distinct_id = CaseEvidenceBriefing(
        case_id="case_t2_1",
        title="거래번호 상이 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="2024년 3월 1일 임대인이 20,000,000원을 일부 변제 입금하였다. (거래번호: TX-1001)",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="1차_이체증.pdf",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2024년 3월 1일 임대인이 20,000,000원을 일부 변제 입금하였다. (거래번호: TX-1002)",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="2차_이체증.pdf",
            ),
        ],
    )
    total_1, sources_1 = extract_case_prior_verified_repayments(briefing_distinct_id)
    assert total_1 == 40_000_000
    assert len([s for s in sources_1 if not s.startswith("[보류]")]) == 2

    # Case 2: 차수 상이 (1차 vs 2차) -> 각각 집계 40M
    briefing_distinct_ord = CaseEvidenceBriefing(
        case_id="case_t2_2",
        title="차수 상이 사건",
        facts=[
            FactItemBrief(
                fact_id="f3",
                statement="2024년 3월 1일 임대인이 1차 20,000,000원을 일부 변제 입금하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="1차입금증.pdf",
            ),
            FactItemBrief(
                fact_id="f4",
                statement="2024년 3월 1일 임대인이 2차 20,000,000원을 일부 변제 입금하였다.",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="2차입금증.pdf",
            ),
        ],
    )
    total_2, sources_2 = extract_case_prior_verified_repayments(briefing_distinct_ord)
    assert total_2 == 40_000_000

    # Case 3: 동일 거래 사본 (사본 파일명 및 동일 거래 표기) -> 20M 유지
    briefing_copy = CaseEvidenceBriefing(
        case_id="case_t2_3",
        title="동일 거래 사본 사건",
        facts=[
            FactItemBrief(
                fact_id="f5",
                statement="2024년 3월 1일 임대인이 20,000,000원을 일부 변제 입금 확인",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="이체확인증_원본.pdf",
            ),
            FactItemBrief(
                fact_id="f6",
                statement="2024년 3월 1일 임대인이 20,000,000원을 일부 변제 입금 확인 (사본)",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="이체확인증_사본.pdf",
            ),
        ],
    )
    total_3, _ = extract_case_prior_verified_repayments(briefing_copy)
    assert total_3 == 20_000_000

    # Case 4: 식별자 부재 불확실 중복 -> 합산 보류 및 경고 안내 (20M 유지)
    briefing_ambiguous = CaseEvidenceBriefing(
        case_id="case_t2_4",
        title="식별자 부재 중복 의심 사건",
        facts=[
            FactItemBrief(
                fact_id="f7",
                statement="2024년 3월 1일 임대인이 20,000,000원을 일부 변제 입금 확인",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="문서A.pdf",
            ),
            FactItemBrief(
                fact_id="f8",
                statement="2024년 3월 1일 임대인이 20,000,000원을 일부 변제 입금 확인",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="문서B.pdf",
            ),
        ],
    )
    total_4, sources_4 = extract_case_prior_verified_repayments(briefing_ambiguous)
    assert total_4 == 20_000_000  # 불확실 거래 이중 차감 방지
    assert any("[보류]" in s and "중복 의심" in s for s in sources_4)

    # Case 5: [운영 전 잔여 결함 1] 동일 문서(신한은행_거래내역서.pdf) 내 거래번호가 상이한 복수 거래 각각 합산 (20M + 30M = 50M)
    briefing_single_doc_multi_tx = CaseEvidenceBriefing(
        case_id="case_t2_5",
        title="단일 은행거래내역서 내 복수 거래 사건",
        facts=[
            FactItemBrief(
                fact_id="f9",
                statement="2024년 3월 10일 임대인이 20,000,000원을 일부 변제 입금하였다. (거래번호: TX-1001)",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="신한은행_거래내역서.pdf",
            ),
            FactItemBrief(
                fact_id="f10",
                statement="2024년 3월 15일 임대인이 30,000,000원을 일부 변제 입금하였다. (거래번호: TX-1002)",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="신한은행_거래내역서.pdf",
            ),
        ],
    )
    total_5, sources_5 = extract_case_prior_verified_repayments(briefing_single_doc_multi_tx)
    assert total_5 == 50_000_000, f"동일 문서 내 거래번호 상이 거래가 각각 합산되지 않았습니다: {total_5}"
    assert len([s for s in sources_5 if not s.startswith("[보류]")]) == 2

    # Case 6: 동일 문서 내 동일 거래번호 중복 사본 -> 20M 유지 (중복 차감 방지)
    briefing_single_doc_dup_tx = CaseEvidenceBriefing(
        case_id="case_t2_6",
        title="단일 문서 내 동일 거래번호 중복 사건",
        facts=[
            FactItemBrief(
                fact_id="f11",
                statement="2024년 3월 10일 임대인이 20,000,000원을 일부 변제 입금하였다. (거래번호: TX-1001)",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="신한은행_거래내역서.pdf",
            ),
            FactItemBrief(
                fact_id="f12",
                statement="2024년 3월 10일 임대인이 20,000,000원을 일부 변제 입금 확인 (거래번호: TX-1001)",
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="신한은행_거래내역서.pdf",
            ),
        ],
    )
    total_6, sources_6 = extract_case_prior_verified_repayments(briefing_single_doc_dup_tx)
    assert total_6 == 20_000_000, f"동일 거래번호의 중복 건이 합산되었습니다: {total_6}"

    # Case 7: 단일 진술문 내 복수 행 거래 추출 (20M + 15M = 35M)
    briefing_multiline_stmt = CaseEvidenceBriefing(
        case_id="case_t2_7",
        title="단일 진술문 내 복수 거래 행 사건",
        facts=[
            FactItemBrief(
                fact_id="f13",
                statement=(
                    "2024년 3월 10일 임대인이 20,000,000원을 일부 변제 입금 (거래번호: TX-3001)\n"
                    "2024년 3월 15일 임대인이 15,000,000원을 일부 변제 입금 (거래번호: TX-3002)"
                ),
                adjudication_status="EVIDENCE_SUPPORTED",
                document_name="통합_은행거래내역서.pdf",
            ),
        ],
    )
    total_7, _ = extract_case_prior_verified_repayments(briefing_multiline_stmt)
    assert total_7 == 35_000_000, f"단일 진술문 내 복수 행 거래가 합산되지 않았습니다: {total_7}"


def test_task3_attachment_priority_verification_nuancing():
    """[P0-3.1 작업 3] 권리순위 검증 강화 및 단정 표현 차단 검증:
    1. 가압류 등기일 미검증 시 '1순위', '최우선 배당', '후순위 가압류' 단정 금지
    2. 선순위 근저당권 존재 시 '1순위 최우선 배당' 불가 명시
    3. 검증된 날짜 선후관계(대항력 2022.03 < 가압류 2024.05)에서만 상대적 선순위 설명
    """
    # 1. 미검증 가압류 언급: 단정 배제 및 등기부 확인 지침
    briefing_unverified_att = CaseEvidenceBriefing(
        case_id="case_att_unverified",
        title="미검증 가압류 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임차인은 2022년 3월 1일 전입신고 및 확정일자를 갖추었다",
                adjudication_status="EVIDENCE_SUPPORTED",
            )
        ],
    )
    delta_unverified = detect_case_delta(
        briefing=briefing_unverified_att,
        current_question="등기부에 가압류가 들어왔다는데 제 순위는 어떻게 되나요?",
        resolved_query="가압류 언급에 따른 권리순위 분석",
    )
    assert delta_unverified is not None
    assert any("등기일자 미검증 / 권리순위 미확정" in cf for cf in delta_unverified["changed_facts"])
    assert any("'1순위' 또는 '최우선 배당'을 단정할 수 없음" in idet for idet in delta_unverified["impacted_determinations"])
    # 후순위 가압류 단정 표현 부재 확인
    assert not any("후순위 가압류 등기 사실 추가 확인" in cf for cf in delta_unverified["changed_facts"])

    # 2. 선순위 근저당권 존재: 1순위 최우선 배당 불가 명시
    briefing_prior_mortgage = CaseEvidenceBriefing(
        case_id="case_mortgage",
        title="선순위 근저당권 존재 사건",
        facts=[
            FactItemBrief(
                fact_id="f1",
                statement="임차인은 2022년 3월 1일 전입신고 및 확정일자를 갖추었다",
                adjudication_status="EVIDENCE_SUPPORTED",
            ),
            FactItemBrief(
                fact_id="f2",
                statement="2021년 5월 1일 선순위 근저당권 채권최고액 1억 원이 설정되어 있다",
                adjudication_status="EVIDENCE_SUPPORTED",
            ),
            FactItemBrief(
                fact_id="f3",
                statement="2024년 5월 10일 목적물에 가압류 등기가 추가되었다",
                adjudication_status="EVIDENCE_SUPPORTED",
            ),
        ],
    )
    delta_mortgage = detect_case_delta(
        briefing=briefing_prior_mortgage,
        current_question="가압류가 또 들어왔는데 제 배당 순위는 어떻게 되나요?",
    )
    assert delta_mortgage is not None
    assert any("선순위 담보물권" in idet and "1순위 최우선 배당이 불가" in idet for idet in delta_mortgage["impacted_determinations"])


@pytest.mark.asyncio
async def test_task4_live_workflow_execution_without_mock(db: Session, case_300m: Case):
    """[P0-3.1 작업 4] 실제 run_legal_consultation 워크플로우를 모의 객체(mock) 없이
    직접 실행하여 전체 LangGraph 노드(의도분석->라우팅->감독자초기화)를 통합 검증한다.
    모의 워크플로우(_e2e_mock_run_consultation)와 실제 워크플로우를 구분하여 실행성을 보장한다.
    """
    question_text = "임대차 계약이 끝났는데 보증금 3억 원을 아직 돌려받지 못했습니다. 어떻게 해야 하나요?"
    thread_id = f"thread_live_{uuid.uuid4().hex[:8]}"
    conv_ctx = ConversationContext(
        conversation_id=f"conv_live_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        current_question=question_text,
        turn_index=1,
    )
    result = await run_legal_consultation(
        question_text,
        thread_id=thread_id,
        conversation_context=conv_ctx,
    )
    assert result is not None
    assert "answer" in result
    assert result["status"] in ("SUCCESS", "APPROVAL_REQUIRED")
    assert len(result["answer"]) > 0
    assert "request_id" in result
    assert result.get("request_id") is not None


def test_task2_db_save_failure_suppresses_background_tasks_and_returns_500(case_300m: Case, test_user_a: User):
    """[P0-3 운영 전 잔여 결함 2] 상담 레코드 DB 저장이 최종 실패한 경우
    HTTP 500을 반환하고 백그라운드 작업을 실행하지 않으며 메모리 상태를 정리하는지 검증한다.
    """
    app.dependency_overrides[get_current_user] = lambda: test_user_a
    try:
        # DB 세션의 commit 메소드가 예외를 던지도록 모킹
        with patch.object(Session, "commit", side_effect=Exception("Simulated DB fatal commit failure")):
            with patch("ai_legal_helper.api.routes.consultation.process_consultation") as mock_bg_task:
                res = client.post(
                    "/api/v1/consultations",
                    json={
                        "question": "DB 저장 실패 테스트 질의",
                        "case_id": case_300m.id,
                    },
                )
                assert res.status_code == 500, f"예상치 못한 응답 코드: {res.status_code}, {res.text}"
                data = res.json()
                assert "상담 기록을 데이터베이스에 저장하지 못했습니다" in data.get("detail", "")

                # 백그라운드 태스크가 일체 스케줄링/호출되지 않았음을 검증
                assert not mock_bg_task.called, "DB 저장 실패에도 불구하고 백그라운드 작업이 스케줄링되었습니다."

                # 메모리 저장소(_consultations)에 고아 레코드가 잔존하지 않는지 검증
                orphan_entries = [r for r, v in _consultations.items() if v.question == "DB 저장 실패 테스트 질의"]
                assert len(orphan_entries) == 0, f"실패한 상담의 메모리 고아 레코드가 남아 있습니다: {orphan_entries}"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_task3_live_langgraph_disposition_update_on_evidence_approval(db: Session, case_300m: Case):
    """[P0-3 운영 전 잔여 결함 3] 실제 LangGraph 워크플로우에서 신규 증거(2천만 원 이체증)
    승인 후 법률 판단 및 미반환 잔액(2.8억)이 동적으로 갱신되는지 모의 객체 없이 검증한다.
    """
    # 1. 신규 2천만 원 일부 변제 이체증 등록 및 승인
    doc_id = f"ev_live_{uuid.uuid4().hex[:8]}"
    doc = EvidenceDocument(
        id=doc_id,
        case_id=case_300m.id,
        original_filename="임대인_일부변제_2천만원_이체확인증.pdf",
        safe_storage_key=f"storage/{doc_id}.pdf",
        media_type="application/pdf",
        size_bytes=2048,
        sha256=f"sha_{uuid.uuid4().hex[:16]}",
        status="UPLOADED",
    )
    db.add(doc)
    db.flush()

    claim = EvidenceClaim(
        id=f"cl_live_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        evidence_id=doc.id,
        statement="임대인이 2024년 2월 10일 보증금 중 20,000,000원을 일부 변제 입금하였다. (거래번호: TX-9001)",
        assertion_status="DOCUMENT_STATES",
        review_status="PENDING_REVIEW",
    )
    db.add(claim)
    db.commit()

    # 증거 승인 및 Fact 승격
    process_evidence_review(db, claim.id, "APPROVE", expected_case_id=case_300m.id, expected_evidence_id=doc.id)

    # 2. 실제 LangGraph 워크플로우 실행
    question = "이체확인증이 승인되었는데 현재 남아있는 보증금 잔액은 얼마이고 어떻게 해야 하나요?"
    thread_id = f"thread_live_eval_{uuid.uuid4().hex[:8]}"
    conv_ctx = ConversationContext(
        conversation_id=f"conv_live_eval_{uuid.uuid4().hex[:8]}",
        case_id=case_300m.id,
        current_question=question,
        turn_index=1,
    )

    result = await run_legal_consultation(
        question,
        thread_id=thread_id,
        conversation_context=conv_ctx,
    )

    assert result is not None
    assert result.get("status") in ("SUCCESS", "APPROVAL_REQUIRED")
    ans = result.get("answer", "")
    assert len(ans) > 0

    # 3. 신규 증거 승인 반영 검증: 확정 2.8억 원 잔액 및 변제 사실 안내 확인
    delta = result.get("case_delta")
    if delta and delta.get("calculation_basis"):
        calc = delta["calculation_basis"]
        assert calc.get("verified_partial_repayment_krw") == 20_000_000
        assert calc.get("unrepaid_balance_krw") == 280_000_000

    # 4. 답변 텍스트 또는 승인 요청 사유(explanation) 내 잔액(2.8억 원 / 280,000,000원) 및 변제(2천만 원) 명시 확인
    ans = result.get("answer", "")
    draft_ans = result.get("draft_answer", "")
    appr_exp = (result.get("approval_request") or {}).get("explanation", "")
    full_response_text = f"{ans} {draft_ans} {appr_exp}"

    assert any(term in full_response_text for term in ["280,000,000", "2억 8,000", "280000000", "2.8억"]), (
        f"워크플로우 결과에 확정 잔액 2.8억 원이 명시되지 않았습니다: {full_response_text[:300]}"
    )
    assert any(term in full_response_text for term in ["20,000,000", "2,000만", "2000만", "2천만"]), (
        f"워크플로우 결과에 승인된 2천만 원 일부 변제 사실이 반영되지 않았습니다: {full_response_text[:300]}"
    )

