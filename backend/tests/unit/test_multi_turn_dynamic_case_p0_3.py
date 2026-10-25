# -*- coding: utf-8 -*-
"""
모듈명: test_multi_turn_dynamic_case_p0_3.py

[테스트 모듈 개요]
AI Legal Helper P0-3(Multi-turn Context Continuity & Dynamic Case Update)의
8대 필수 검증 시나리오(S01~S08) 및 사실 상태(FactTrustLevel) 체계를 엄격하게 검증하는 테스트 스위트.

[검증 대상 시나리오 (Section 6)]
- S01 (일부 변제): 보증금 3억 원 중 5천만 원 입금 진술 시 증빙 확인 전에는 잠정 잔액(2.5억 원)으로 표시하고,
  객관적 금융 증거(계좌이체확인증) 확인 후 공식 잔액 2억 5천만 원 및 변동 전후 비교를 반영한다.
- S02 (가압류 추가): 목적물에 후순위 가압류 추가 등기 시 권리관계를 재분석하되 임차인의 기존 1순위 대항력을
  임의로 강등하거나 상실시키지 않는다.
- S03 (기존 사실 정정): 사용자가 구두로 통지일을 정정할 때 기존 등록 서면 증거와 대조하며,
  객관적 증빙 없는 발언만으로 확정된 법률효과 발생일을 변경하지 않는다.
- S04 (증거 충돌): 등록 증거 간 실질적 대립 및 모순 발생 시 단정적 판단을 유보하고 분쟁(DISPUTED) 상태 및
  추가 객관적 확인사항을 명시한다.
- S05 (후속 질문): "그럼 지금 이사를 가도 돼?" 질문에서 보증금 미반환 및 임차권등기 미완료 상태를 복원하고,
  조기 점유 상실 시 대항력 소멸에 관한 강력한 안전 경고를 제공한다.
- S06 (사건 간 격리): 사건 A의 대화 세션에 사건 B로 접근 시 403 권한 거부 및 증거 혼입을 원천 차단한다.
- S07 (재시작 후 연속성): DB에 영구 저장된 상담 기록으로부터 턴 순서, 직전 답변, 사건 메모리를 완벽 복원한다.
- S08 (변경 취소 및 복구): 상충 증거 반려 또는 삭제 시 고아 데이터를 정리하고 이전 유효 사실 상태를 복구한다.
"""

import uuid
import pytest
from datetime import datetime
from sqlalchemy.orm import Session

from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import (
    User,
    Case,
    Fact,
    Event,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceSpan,
    FactAdjudication,
    ConsultationRecord,
)
from ai_legal_helper.case_intelligence.fact_adjudicator import (
    FactTrustLevel,
    map_to_fact_trust_level,
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
from ai_legal_helper.agents.intent_analyzer import (
    analyze_consultation_intent,
    ConsultationIntent,
)
from ai_legal_helper.workflows.conversation_context import (
    ConversationContext,
    ConversationTurn,
    load_conversation_context,
)
from ai_legal_helper.workflows.final_disposition import (
    detect_case_delta,
    assemble_grounded_answer,
    select_grounded_facts_for_display,
)
from ai_legal_helper.agents.issue_verifier import IssueVerificationResult


@pytest.fixture
def db_session():
    """테스트용 격리된 DB 세션 픽스처."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def test_user(db_session: Session) -> User:
    """테스트 사용자 생성 픽스처."""
    uid = f"user_{uuid.uuid4().hex[:8]}"
    user = User(
        id=uid,
        email=f"{uid}@legal.test",
        password_hash="mock_hash",
        display_name="홍길동",
        status="ACTIVE",
    )
    db_session.add(user)
    db_session.commit()
    return user


class TestFactTrustLevelMapping:
    """P0-3 사실 논리 상태(FactTrustLevel) 매핑 단위 테스트."""

    def test_trust_level_mapping_rules(self):
        """다양한 검증 상태 및 출처 유형이 5대 논리 상태로 정확히 매핑되는지 검증."""
        # 1. SUPERSEDED
        assert map_to_fact_trust_level(verification_status="SUPERSEDED") == FactTrustLevel.SUPERSEDED.value
        assert map_to_fact_trust_level(adjudication_status="SUPERSEDED") == FactTrustLevel.SUPERSEDED.value

        # 2. DISPUTED
        assert map_to_fact_trust_level(verification_status="DISPUTED") == FactTrustLevel.DISPUTED.value
        assert map_to_fact_trust_level(adjudication_status="GENUINELY_DISPUTED") == FactTrustLevel.DISPUTED.value

        # 3. EVIDENCE_SUPPORTED
        assert map_to_fact_trust_level(adjudication_status="EVIDENCE_SUPPORTED") == FactTrustLevel.EVIDENCE_SUPPORTED.value
        assert map_to_fact_trust_level(adjudication_status="CORROBORATED") == FactTrustLevel.EVIDENCE_SUPPORTED.value
        assert map_to_fact_trust_level(verification_status="DOCUMENT_VERIFIED") == FactTrustLevel.EVIDENCE_SUPPORTED.value

        # 4. EVIDENCE_PENDING
        assert map_to_fact_trust_level(adjudication_status="EVIDENCE_INCOMPLETE") == FactTrustLevel.EVIDENCE_PENDING.value
        assert map_to_fact_trust_level(verification_status="UNVERIFIED", source_type="DOCUMENT_SUPPORTED") == FactTrustLevel.EVIDENCE_PENDING.value

        # 5. USER_ALLEGED
        assert map_to_fact_trust_level(source_type="PARTY_ALLEGATION") == FactTrustLevel.USER_ALLEGED.value
        assert map_to_fact_trust_level(adjudication_status="PARTY_ALLEGED") == FactTrustLevel.USER_ALLEGED.value
        assert map_to_fact_trust_level(verification_status="PARTY_ASSERTED") == FactTrustLevel.USER_ALLEGED.value


class TestScenarioS01PartialRepayment:
    """S01 시나리오: 보증금 일부 변제에 따른 잠정 잔액 및 입증 후 확정 잔액 분리 검증."""

    def test_s01_step_a_user_alleged_partial_payment_without_evidence(self):
        """입금 증빙 서류가 등록되지 않은 구두 진술 상태에서는 잠정 잔액(USER_ALLEGED)으로 안내한다."""
        briefing = CaseEvidenceBriefing(
            case_id="case_s01",
            title="보증금 3억 원 반환 사건",
            evidences=[
                EvidenceItemBrief(
                    evidence_id="ev_01",
                    evidence_label="E01",
                    document_name="E01_주택임대차계약서.txt",
                )
            ],
            facts=[
                FactItemBrief(
                    fact_id="fact_01",
                    statement="임대차계약상 보증금은 300,000,000원 약정이다",
                    adjudication_status="EVIDENCE_SUPPORTED",
                    evidence_label="E01",
                    document_name="E01_주택임대차계약서.txt",
                    trust_level="EVIDENCE_SUPPORTED",
                )
            ],
        )

        delta = detect_case_delta(
            briefing=briefing,
            current_question="임대인이 5천만원을 입금했다고 합니다. 남은 보증금은 얼마인가요?",
            resolved_query="의뢰인의 보증금 일부 입금/변제 주장에 따른 보증금 잔액 변동 및 입금 증거 확인 필요성 검토",
        )

        assert delta is not None
        assert delta["has_delta"] is True
        # 증빙 미제출 및 USER_ALLEGED 명시
        assert any("USER_ALLEGED" in f for f in delta["changed_facts"])
        assert any("잠정 잔액이 250,000,000원" in idet for idet in delta["impacted_determinations"])
        # 대항력 및 반환 청구 권한은 온전히 유지됨 명시
        assert any("임차인의 대항력, 우선변제권" in pdet for pdet in delta["preserved_determinations"])
        # 이체확인증 등록 권고
        assert any("이체확인증 또는 영수증을 증거로 등록" in act for act in delta["new_next_actions"])

        # assemble_grounded_answer 조립 결과에 [사건 변동 사항 및 법률 판단 비교] 및 [잠정] 안내가 포함되는지 검증
        final_answer = assemble_grounded_answer(
            issue_results=[],
            briefing=briefing,
            draft_answer="5천만원 입금 진술 관련",
            disposition="CAUTIONARY",
            case_delta=delta,
        )
        assert "[사건 변동 사항 및 법률 판단 비교]" in final_answer
        assert "USER_ALLEGED" in final_answer
        assert "[잠정]" in final_answer
        assert "250,000,000원" in final_answer

    def test_s01_step_b_verified_partial_payment_with_bank_transfer_evidence(self):
        """계좌이체확인증 증거가 등록·확인되면 잔액 2억 5천만 원이 확정되고 과거 3억 잔액은 대체(SUPERSEDED)된다."""
        briefing = CaseEvidenceBriefing(
            case_id="case_s01",
            title="보증금 3억 원 반환 사건",
            evidences=[
                EvidenceItemBrief(
                    evidence_id="ev_01",
                    evidence_label="E01",
                    document_name="E01_주택임대차계약서.txt",
                ),
                EvidenceItemBrief(
                    evidence_id="ev_02",
                    evidence_label="E02",
                    document_name="E02_계좌이체확인증_5천만원.txt",
                ),
            ],
            facts=[
                FactItemBrief(
                    fact_id="fact_01",
                    statement="임대차계약상 보증금은 300,000,000원 약정이다",
                    adjudication_status="EVIDENCE_SUPPORTED",
                    evidence_label="E01",
                    document_name="E01_주택임대차계약서.txt",
                    trust_level="EVIDENCE_SUPPORTED",
                ),
                FactItemBrief(
                    fact_id="fact_02",
                    statement="임대인이 50,000,000원을 일부 변제 입금하여 남은 잔액은 250,000,000원이다",
                    adjudication_status="EVIDENCE_SUPPORTED",
                    evidence_label="E02",
                    document_name="E02_계좌이체확인증_5천만원.txt",
                    trust_level="EVIDENCE_SUPPORTED",
                ),
                FactItemBrief(
                    fact_id="fact_old",
                    statement="임차인이 반환받지 못한 보증금 잔액은 300,000,000원이다",
                    adjudication_status="UNASSESSED",
                    trust_level="SUPERSEDED",  # 이전 전액 사실 대체
                ),
            ],
        )

        delta = detect_case_delta(
            briefing=briefing,
            current_question="이제 남은 보증금 2억 5천만 원에 대해 어떻게 해야 하나요?",
            resolved_query="일부 변제 후 잔여 보증금 2억 5천만 원에 대한 법적 청구 절차",
        )

        assert delta is not None
        assert delta["has_delta"] is True
        # 증거 확인 및 2.5억 감축 확정 명시
        assert any("50,000,000원 일부 변제 입금 확인 [계좌이체확인증]" in f for f in delta["changed_facts"])
        assert any("250,000,000원으로 감축 확정됨" in idet for idet in delta["impacted_determinations"])
        assert any("미반환 잔액 250,000,000원에 대한 지급명령 신청" in act for act in delta["new_next_actions"])

        # SUPERSEDED 사실은 표시 대상에서 제외되는지 검증
        displayed_facts = select_grounded_facts_for_display(briefing)
        displayed_stmts = [f.statement for f in displayed_facts]
        assert "임차인이 반환받지 못한 보증금 잔액은 300,000,000원이다" not in displayed_stmts
        assert any("250,000,000원이다" in s for s in displayed_stmts)


class TestScenarioS02AdditionalAttachment:
    """S02 시나리오: 가압류 추가 등록 시 권리관계 재분석 및 기존 선순위 보존 검증."""

    def test_s02_additional_attachment_preserves_tenant_priority(self):
        """새로운 후순위 가압류가 추가되어도 임차인의 2022.03.10 대항요건 및 1순위 지위는 유지된다."""
        briefing = CaseEvidenceBriefing(
            case_id="case_s02",
            title="가압류 추가 사건",
            evidences=[
                EvidenceItemBrief(
                    evidence_id="ev_09",
                    evidence_label="E09",
                    document_name="E09_부동산등기사항전부증명서_을구.txt",
                )
            ],
            facts=[
                FactItemBrief(
                    fact_id="fact_01",
                    statement="임차인은 2022년 3월 10일 전입신고 및 확정일자를 갖추었다",
                    adjudication_status="EVIDENCE_SUPPORTED",
                    evidence_label="E01",
                    trust_level="EVIDENCE_SUPPORTED",
                ),
                FactItemBrief(
                    fact_id="fact_02",
                    statement="2024년 5월 10일 목적물에 채권자 주식회사의 가압류 등기가 추가되었다",
                    adjudication_status="EVIDENCE_SUPPORTED",
                    evidence_label="E09",
                    trust_level="EVIDENCE_SUPPORTED",
                ),
            ],
        )

        delta = detect_case_delta(
            briefing=briefing,
            current_question="등기부를 떼어보니 2024년 가압류가 추가되었는데 제 순위가 밀리나요?",
            resolved_query="후순위 가압류 추가에 따른 임차인의 대항력 및 배당 우선순위 영향 분석",
        )

        assert delta is not None
        assert delta["has_delta"] is True
        # 가압류 추가 확인
        assert any("후순위 가압류 등기 사실 추가 확인" in f for f in delta["changed_facts"])
        # 선순위 유지 및 대항력 불상실 명시
        assert any("기존 우선순위 보존" in idet for idet in delta["impacted_determinations"])
        assert any("1순위 대항력 및 우선변제권" in pdet for pdet in delta["preserved_determinations"])
        # 경매 시 배당요구종기 내 권리신고 지침
        assert any("배당요구 신청서 접수" in act for act in delta["new_next_actions"])


class TestScenarioS03FactCorrection:
    """S03 시나리오: 사용자의 구두 날짜 정정 시 기존 증거 대조 및 무단 법률효과 변경 방지 검증."""

    def test_s03_fact_correction_preserves_evidence_delivery_date(self):
        """사용자가 통지일을 구두로 다르게 말하더라도 등록된 배달증명서 도달일(2024.02.05)을 유지한다."""
        briefing = CaseEvidenceBriefing(
            case_id="case_s03",
            title="내용증명 도달일 정정 사건",
            evidences=[
                EvidenceItemBrief(
                    evidence_id="ev_05",
                    evidence_label="E05",
                    document_name="E05_내용증명_배달증명서.txt",
                )
            ],
            facts=[
                FactItemBrief(
                    fact_id="fact_01",
                    statement="내용증명 우편이 2024년 2월 5일 임대인에게 도달 완료되었다",
                    adjudication_status="EVIDENCE_SUPPORTED",
                    evidence_label="E05",
                    trust_level="EVIDENCE_SUPPORTED",
                )
            ],
        )

        delta = detect_case_delta(
            briefing=briefing,
            current_question="제가 잘못 알았는데, 계약 해지 통지일이 2024년 3월 20일이에요.",
            resolved_query="의뢰인의 계약 해지 통지일 정정 진술과 기존 등록된 서면 증거 대조",
        )

        assert delta is not None
        assert delta["has_delta"] is True
        # 진술 접수(USER_ALLEGED)
        assert any("USER_ALLEGED" in f for f in delta["changed_facts"])
        # 서면 증거 도달일(2024.02.05) 기준 법률효과 유지
        assert any("2024.02.05" in idet for idet in delta["impacted_determinations"])
        assert any("임의 변경하지 않음" in idet for idet in delta["impacted_determinations"])
        # 객관적 서면 등록 필요 안내
        assert any("서면 증거" in act for act in delta["new_next_actions"])


class TestScenarioS04EvidenceConflict:
    """S04 시나리오: 등록 증거 간 실질적 대립 발생 시 DISPUTED 판정 및 단정적 판단 유보 검증."""

    def test_s04_conflicting_evidence_marked_disputed(self):
        """서로 다른 증거에서 보증금 액수가 대립할 경우 DISPUTED 상태로 관리하고 추가 확인을 요구한다."""
        from ai_legal_helper.case_intelligence.case_briefing import DisputedConflictBrief

        briefing = CaseEvidenceBriefing(
            case_id="case_s04",
            title="증거 상충 사건",
            facts=[
                FactItemBrief(
                    fact_id="fact_01",
                    statement="계약서상 보증금은 300,000,000원이다",
                    adjudication_status="GENUINELY_DISPUTED",
                    trust_level="DISPUTED",
                )
            ],
            genuinely_disputed=[
                DisputedConflictBrief(
                    fact_id="fact_01",
                    statement="계약서상 보증금 3억 원",
                    opposing_statement="임대인 제출 영수증상 보증금 2억 원",
                    reason="보증금 액수에 대한 직접적 수치 불일치",
                )
            ],
        )

        delta = detect_case_delta(
            briefing=briefing,
            current_question="집주인이 제출한 영수증과 제 계약서 보증금이 다른데 어떻게 되나요?",
            resolved_query="증거 간 보증금 액수 상충에 대한 법률적 지위 검토",
        )

        assert delta is not None
        assert delta["has_delta"] is True
        # DISPUTED 명시
        assert any("DISPUTED" in f for f in delta["changed_facts"])
        # 단정적 판단 유보 및 조건부 판단 안내
        assert any("단정적 법률 판단을 내릴 수 없으며" in idet for idet in delta["impacted_determinations"])
        # 객관적 금융거래원장 확보 안내
        assert any("금융거래원장" in act for act in delta["new_next_actions"])


class TestScenarioS05FollowUpQuestionPrematureMoveOut:
    """S05 시나리오: "그럼 지금 이사를 가도 돼?" 후속 질의 문맥 복원 및 대항력 상실 경고 검증."""

    def test_s05_move_out_inquiry_restores_context_and_warns(self):
        """조기 퇴거/이사 질문 시 사건의 미반환 및 등기명령 미기재 맥락을 복원하여 점유 상실 위험을 경고한다."""
        # 1. intent_analyzer의 resolved_query 복원 검증
        decision = analyze_consultation_intent(
            question="그럼 지금 이사를 가도 돼?",
            conversation_context=ConversationContext(
                conversation_id="conv_s05",
                case_id="case_s05",
                current_question="그럼 지금 이사를 가도 돼?",
                turn_index=2,
                previous_turns=[
                    ConversationTurn(
                        turn_index=1,
                        request_id="req_01",
                        question="보증금을 돌려받지 못하고 있습니다.",
                        answer="임차권등기명령을 신청하셔야 합니다.",
                    )
                ],
            ),
        )
        assert decision.intent in (ConsultationIntent.FOLLOWUP_QUESTION, ConsultationIntent.FOLLOWUP_ACTION)
        assert ("임차권등기" in decision.resolved_query or "대항력" in decision.resolved_query)
        assert ("퇴거" in decision.resolved_query or "이사" in decision.resolved_query)

        # 2. Case Delta 및 법률 판단 경고 검증
        briefing = CaseEvidenceBriefing(
            case_id="case_s05",
            title="보증금 미반환 사건",
        )
        delta = detect_case_delta(
            briefing=briefing,
            current_question="그럼 지금 이사를 가도 돼?",
            resolved_query=decision.resolved_query,
        )
        assert delta is not None
        # 절대 점유 이전 금지 경고
        assert any("절대 점유를 이전해서는 안 됨" in idet for idet in delta["impacted_determinations"])
        assert any("대항력 및 우선변제권이 즉시 소멸" in idet for idet in delta["impacted_determinations"])
        # 등기부 기재 확인 후 이사 지침
        assert any("임차권등기" in act and "확인한 후에" in act for act in delta["new_next_actions"])


class TestScenarioS06CaseAndConversationIsolation:
    """S06 시나리오: 사건 및 사용자 간 엄격한 대화 격리 검증 (403 PermissionError)."""

    def test_s06_cross_case_access_rejected_with_permission_error(self, db_session: Session, test_user: User):
        """사건 A 소속 대화 세션에 사건 B로 조회를 시도하면 PermissionError가 발생한다."""
        case_a = Case(id=f"case_a_{uuid.uuid4().hex[:6]}", user_id=test_user.id, title="사건 A")
        case_b = Case(id=f"case_b_{uuid.uuid4().hex[:6]}", user_id=test_user.id, title="사건 B")
        db_session.add_all([case_a, case_b])
        db_session.commit()

        conv_id = f"conv_{uuid.uuid4().hex[:8]}"
        rec = ConsultationRecord(
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            case_id=case_a.id,
            user_id=test_user.id,
            conversation_id=conv_id,
            turn_index=1,
            question="사건 A 질문",
            answer="사건 A 답변",
            status="SUCCESS",
            execution_status="COMPLETED",
            answer_status="DELIVERED",
        )
        db_session.add(rec)
        db_session.commit()

        # 사건 A로 조회 -> 정상 통과
        ctx_ok = load_conversation_context(
            db=db_session,
            conversation_id=conv_id,
            current_question="후속 질문",
            case_id=case_a.id,
            user_id=test_user.id,
        )
        assert ctx_ok.turn_index == 2

        # 사건 B로 조회 -> PermissionError 발생 (사건 불일치 차단)
        with pytest.raises(PermissionError) as exc_info:
            load_conversation_context(
                db=db_session,
                conversation_id=conv_id,
                current_question="사건 B에서 불법 접근",
                case_id=case_b.id,
                user_id=test_user.id,
            )
        assert "다른 사건" in str(exc_info.value)


class TestScenarioS07RestartRefreshContinuity:
    """S07 시나리오: DB 영속성 기반 새로고침 및 재시작 후 연속성 검증."""

    def test_s07_multi_turn_continuity_restores_from_db(self, db_session: Session, test_user: User):
        """DB에 기록된 2개의 이전 턴 정보가 재진입 시 턴 인덱스 3으로 정확히 복원된다."""
        cid = f"case_{uuid.uuid4().hex[:6]}"
        conv_id = f"conv_{uuid.uuid4().hex[:8]}"

        case_obj = Case(id=cid, user_id=test_user.id, title="지속성 테스트 사건")
        db_session.add(case_obj)

        rec1 = ConsultationRecord(
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            case_id=cid,
            user_id=test_user.id,
            conversation_id=conv_id,
            turn_index=1,
            question="첫 번째 질문: 보증금 미반환",
            answer="첫 번째 답변: 계약 해지 내용증명 발송",
            status="SUCCESS",
            execution_status="COMPLETED",
            answer_status="DELIVERED",
        )
        rec2 = ConsultationRecord(
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            case_id=cid,
            user_id=test_user.id,
            conversation_id=conv_id,
            turn_index=2,
            question="두 번째 질문: 임차권등기명령 요건",
            answer="두 번째 답변: 계약 만료 후 신청 가능",
            status="SUCCESS",
            execution_status="COMPLETED",
            answer_status="DELIVERED",
        )
        db_session.add_all([rec1, rec2])
        db_session.commit()

        # 서버 재시작을 모사하여 새로운 컨텍스트 로드
        ctx = load_conversation_context(
            db=db_session,
            conversation_id=conv_id,
            current_question="세 번째 질문: 이제 뭘 해야 하죠?",
            case_id=cid,
            user_id=test_user.id,
        )

        assert ctx.turn_index == 3
        assert len(ctx.previous_turns) == 2
        assert ctx.last_answer == "두 번째 답변: 계약 만료 후 신청 가능"
        assert "첫 번째 질문" in ctx.previous_turns[0].question
        assert "두 번째 질문" in ctx.previous_turns[1].question


class TestScenarioS08CancellationAndRollback:
    """S08 시나리오: 증거 반려 또는 오류 수정 시 고아 사실 정리 및 이전 상태 복구 검증."""

    def test_s08_evidence_claim_rejection_restores_clean_state(self, db_session: Session, test_user: User):
        """잘못된 상충 Claim이 반려(REJECT)되면 연관 고아 Fact가 삭제되고 사건 상태가 정상 복원된다."""
        cid = f"case_{uuid.uuid4().hex[:6]}"
        case_obj = Case(id=cid, user_id=test_user.id, title="롤백 테스트 사건")
        db_session.add(case_obj)

        doc_id = f"doc_{uuid.uuid4().hex[:8]}"
        doc = EvidenceDocument(
            id=doc_id,
            case_id=cid,
            original_filename="오류_문서.txt",
            safe_storage_key=f"storage/{doc_id}.txt",
            media_type="text/plain",
            size_bytes=100,
            sha256=f"sha_{uuid.uuid4().hex[:16]}",
            status="UPLOADED",
        )
        db_session.add(doc)
        db_session.flush()

        claim = EvidenceClaim(
            id=f"claim_{uuid.uuid4().hex[:8]}",
            case_id=cid,
            evidence_id=doc.id,
            statement="보증금은 1억 원이다",
            assertion_status="CONTRADICTION_CANDIDATE",
        )
        db_session.add(claim)
        db_session.flush()

        # 임의로 생성되었던 고아 Fact
        fact = Fact(
            id=f"fact_{uuid.uuid4().hex[:8]}",
            case_id=cid,
            statement="보증금은 1억 원이다",
            source_type="DOCUMENT_SUPPORTED",
            source_ref=doc.id,
            verification_status="DISPUTED",
        )
        db_session.add(fact)
        db_session.flush()

        from ai_legal_helper.database.models import EvidenceLink
        link = EvidenceLink(
            id=f"link_{uuid.uuid4().hex[:8]}",
            evidence_id=doc.id,
            claim_id=claim.id,
            target_type="FACT",
            target_id=fact.id,
            link_type="SUPPORTS",
        )
        db_session.add(link)
        db_session.commit()

        # EvidenceReview 검토 거절(REJECT) 수행
        process_evidence_review(
            db=db_session,
            claim_id=claim.id,
            action="REJECT",
            expected_case_id=cid,
            expected_evidence_id=doc.id,
        )

        # 검증: 반려 처리 후 사건 브리핑에 고아 사실이 잔존하지 않는지 확인
        briefing = build_case_evidence_briefing(db_session, cid)
        assert not any("1억 원" in f.statement for f in briefing.facts)


class TestPartialRepaymentCalculations:
    """부분 변제에 따른 잔액 계산 및 지연손해금 원금 산정 단위 테스트."""

    def test_partial_repayment_math(self):
        """3억 원 계약 보증금에서 5천만 원 입금 시 잔액 2억 5천만 원 및 지연손해금 원금 2.5억 원 산출 검증."""
        original_deposit = 300_000_000
        repaid_amount = 50_000_000
        remaining_balance = original_deposit - repaid_amount
        assert remaining_balance == 250_000_000

        # 민법상 지연손해금 연 5% (원금 250,000,000원 기준 연간 12,500,000원)
        civil_annual_interest = int(remaining_balance * 0.05)
        assert civil_annual_interest == 12_500_000

        # 소송촉진등에관한특례법 연 12% (원금 250,000,000원 기준 연간 30,000,000원)
        litigation_annual_interest = int(remaining_balance * 0.12)
        assert litigation_annual_interest == 30_000_000


class TestConcurrentTurnConsistency:
    """동일 사건 대화 세션의 동시 요청 및 일관성 검증."""

    def test_concurrent_turn_index_increment(self, db_session: Session, test_user: User):
        """동일 conversation_id에 대해 완료된 레코드가 누적될 때 turn_index가 정확히 1씩 순차 증가한다."""
        cid = f"case_{uuid.uuid4().hex[:6]}"
        conv_id = f"conv_{uuid.uuid4().hex[:8]}"

        case_obj = Case(id=cid, user_id=test_user.id, title="동시성 테스트 사건")
        db_session.add(case_obj)
        db_session.commit()

        for t in range(1, 4):
            rec = ConsultationRecord(
                request_id=f"req_{uuid.uuid4().hex[:8]}",
                case_id=cid,
                user_id=test_user.id,
                conversation_id=conv_id,
                turn_index=t,
                question=f"질문 {t}",
                answer=f"답변 {t}",
                status="SUCCESS",
                execution_status="COMPLETED",
                answer_status="DELIVERED",
            )
            db_session.add(rec)
            db_session.commit()

        ctx = load_conversation_context(
            db=db_session,
            conversation_id=conv_id,
            current_question="네 번째 질문",
            case_id=cid,
            user_id=test_user.id,
        )
        assert ctx.turn_index == 4
        assert len(ctx.previous_turns) == 3
