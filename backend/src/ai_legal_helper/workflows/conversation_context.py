# -*- coding: utf-8 -*-
"""
모듈명: conversation_context.py

[모듈 개요]
연속된 법률 상담 대화(Multi-turn Consultation)의 맥락을 DB로부터 복원하고,
사용자·사건별 보안 격리 및 대화 메모리(ConversationContext)를 구성하는 핵심 모듈이다.

[주요 기능]
1. `ConversationTurn`: 개별 상담 턴의 질문, 답변, 검증 상태, 인용 출처 관리
2. `ConversationContext`: 다중 턴 대화 이력, 직전 답변, 이전 인용 출처 누적 요약 관리
3. `load_conversation_context`: DB에서 동일 conversation_id의 과거 이력을 안전하게 조회하고
   사건(case_id) 및 사용자(user_id) 소유권을 엄격히 검증
4. LangGraph 및 LLM 프롬프트에 주입하기 위한 메시지 변환(`to_chat_history_messages`) 및
   텍스트 포맷팅(`format_context_for_prompt`) 제공

[주의사항]
- 과거 답변이 `WITHHELD`(판단 유보)였던 경우, 해당 분석을 검증 완료된 법률 근거로 재사용하지 않는다.
- 과거 AI 답변은 '과거 대화 맥락'으로만 취급하며, 독립적으로 확인된 사건 사실(Fact)로 승격하지 않는다.
- 다른 사용자 또는 다른 사건의 대화 세션에 접근하려는 시도는 엄격히 차단한다(403/PermissionError).
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from langchain_core.messages import HumanMessage, AIMessage, AnyMessage

from ai_legal_helper.database.models import ConsultationRecord
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.utils.datetime_utils import get_kst_iso

logger = get_logger(__name__)


class ConversationTurn(BaseModel):
    """단일 상담 턴(Turn) 정보 모델.

    과거 진행된 한 번의 사용자 질문과 AI 답변, 당시의 검증 및 응답 처분 상태를 기록한다.
    """
    turn_index: int = Field(description="대화 내 턴 순서 (1부터 시작)")
    request_id: str = Field(description="해당 턴의 고유 요청 식별자")
    question: str = Field(description="사용자의 질문 원문")
    answer: str = Field(description="AI의 최종 답변 원문")
    answer_status: str = Field(
        default="DELIVERED",
        description="답변 처분 상태 ('DELIVERED', 'CAUTIONARY', 'WITHHELD')"
    )
    verification_status: Optional[str] = Field(
        default=None,
        description="법률 검증 상태 ('PASS', 'REVISE', 'INSUFFICIENT', 'UNVERIFIED')"
    )
    cited_sources: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="해당 턴에서 실제 인용·검증된 출처 목록"
    )
    created_at: Optional[str] = Field(
        default=None,
        description="상담 생성 일시 (ISO 문자열)"
    )
    case_delta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="해당 턴에서 식별된 사건 사실·증거 변동 및 법률 판단 비교 (P0-3)"
    )


class ConversationContext(BaseModel):
    """연속 상담 대화 세션의 전체 맥락 메모리 모델.

    현재 질문에 앞서 진행된 이전 질의응답 내역, 직전 답변의 처분 상태,
    누적된 인용 출처 및 대화 요약을 종합적으로 유지한다.
    """
    conversation_id: str = Field(description="연속 대화 세션 식별자 UUID")
    case_id: Optional[str] = Field(default=None, description="소속 사건 식별자")
    user_id: Optional[str] = Field(default=None, description="상담 소유자 사용자 식별자")
    current_question: str = Field(description="현재 사용자가 입력한 신규 질문")
    turn_index: int = Field(default=1, description="현재 질문이 해당하는 대화 턴 번호")
    previous_turns: List[ConversationTurn] = Field(
        default_factory=list,
        description="이전 완료된 상담 턴들의 시간순 목록"
    )
    last_answer: Optional[str] = Field(
        default=None,
        description="직전 턴의 AI 최종 답변"
    )
    last_answer_status: Optional[str] = Field(
        default=None,
        description="직전 턴의 답변 처분 상태 ('DELIVERED', 'CAUTIONARY', 'WITHHELD')"
    )
    previously_cited_sources: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="이전 상담들에서 누적 인용된 출처 목록"
    )
    conversation_summary: str = Field(
        default="",
        description="이전 대화들의 구조화된 핵심 요약문"
    )
    case_memory: Optional[Dict[str, Any]] = Field(
        default=None,
        description="사건 장기 메모리 (기본정보, 당사자, 확정사실수, 등록증거수 등)"
    )

    def find_relevant_turns(self, query: str, top_k: int = 2) -> List[ConversationTurn]:
        """현재 질문과 의미상 관련성이 높은 과거 상담 턴을 검색한다 (P0-08).

        Args:
            query: 현재 사용자의 신규 질문.
            top_k: 최대 반환할 관련 턴 수.

        Returns:
            List[ConversationTurn]: 질의 키워드와 매칭된 과거 턴 목록.
        """
        if not self.previous_turns or not query:
            return []

        import re
        tokens = [t for t in re.findall(r'[가-힣a-zA-Z0-9]{2,}', query) if t not in ("질문", "어떻게", "있나요", "해주세요", "관련", "대해", "대한", "저는")]
        if not tokens:
            return []

        scored = []
        # 최근 턴은 format_context_for_prompt에서 기본 포함되므로, 더 오래된 턴 위주로 검색
        candidate_turns = self.previous_turns[:-2] if len(self.previous_turns) > 2 else []
        for turn in candidate_turns:
            score = 0
            text_corpus = (turn.question or "") + " " + (turn.answer or "")
            for token in tokens:
                if token in text_corpus:
                    score += 1
            if score > 0:
                scored.append((score, turn))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    def to_chat_history_messages(self, max_turns: int = 5) -> List[AnyMessage]:
        """과거 대화 턴들을 LangGraph 및 LLM 호출에 적합한 AnyMessage 리스트로 변환한다.

        더미 메시지나 비정상 문자열 없이 순수한 HumanMessage와 AIMessage 객체 쌍으로 구성한다.

        Args:
            max_turns: 포함할 최근 턴 수 (기본값: 최근 5턴)

        Returns:
            List[AnyMessage]: [HumanMessage, AIMessage, ...] 형태의 정규화된 메시지 리스트
        """
        messages: List[AnyMessage] = []
        recent_turns = self.previous_turns[-max_turns:] if self.previous_turns else []

        for turn in recent_turns:
            # 1. 사용자 질문을 HumanMessage로 추가
            if turn.question:
                messages.append(HumanMessage(content=turn.question))

            # 2. AI 답변을 AIMessage로 추가 (WITHHELD 상태인 경우 안내문 포함)
            if turn.answer:
                ans_text = turn.answer
                if turn.answer_status == "WITHHELD":
                    ans_text = f"[참고: 이전 상담에서 법률 근거 부족으로 판단이 유보된 답변입니다]\n{ans_text}"
                messages.append(AIMessage(content=ans_text))

        return messages

    def format_context_for_prompt(self, max_turns: int = 3, max_chars_per_turn: int = 600) -> str:
        """프롬프트 템플릿(Router, Synthesizer 등)에 삽입하기 위한 마크다운 텍스트를 생성한다.

        Args:
            max_turns: 포함할 최근 턴 수
            max_chars_per_turn: 턴당 최대 글자 수 제한

        Returns:
            str: 정돈된 대화 이력 텍스트 (이력이 없으면 안내 문구 반환)
        """
        if not self.previous_turns:
            return "(이전 상담 대화 없음 — 신규 대화)"

        parts: List[str] = [
            f"[이전 상담 대화 이력 및 사건 연속 상담 맥락 (총 {len(self.previous_turns)}턴 중 최근 {min(len(self.previous_turns), max_turns)}턴 및 관련 이력)]",
            "■ 원칙: 과거 AI 답변은 작성 당시의 잠정 조언이며 사실 원본이 아닙니다. 최신 Fact 및 등록 증거가 과거 답변과 충돌할 경우 최신 증거가 항상 우선합니다."
        ]

        if self.case_memory:
            c_title = self.case_memory.get("title", "")
            c_facts = self.case_memory.get("confirmed_facts_count", 0)
            c_evs = self.case_memory.get("evidences_count", 0)
            parts.append(f"■ 사건 메모리: 사건명 '{c_title}' (등록증거 {c_evs}건, 확정사실 {c_facts}건)")

        if self.conversation_summary:
            parts.append(f"■ 이전 상담 핵심 요약:\n{self.conversation_summary}\n")

        # 현재 질문과 관련된 오래된 과거 턴 발췌 검색 (P0-08)
        relevant_turns = self.find_relevant_turns(self.current_question, top_k=2)
        if relevant_turns:
            parts.append("■ 현재 질문 관련 과거 상담 발췌:")
            for r_turn in relevant_turns:
                r_ans = r_turn.answer.strip()
                if len(r_ans) > 250:
                    r_ans = r_ans[:250] + "..."
                parts.append(f"- 턴 {r_turn.turn_index} 질의: {r_turn.question.strip()[:80]} → 답변 발췌: {r_ans}")

        parts.append("■ 최근 대화 진행:")
        recent_turns = self.previous_turns[-max_turns:]
        for turn in recent_turns:
            q_clean = turn.question.strip().replace("\n", " ")
            a_clean = turn.answer.strip()
            if len(a_clean) > max_chars_per_turn:
                a_clean = a_clean[:max_chars_per_turn] + f"... [이하 생략 (+{len(a_clean) - max_chars_per_turn}자)]"

            status_note = ""
            if turn.answer_status == "WITHHELD":
                status_note = " (⚠️ 당시 판단 유보됨)"
            elif turn.answer_status == "CAUTIONARY":
                status_note = " (⚠️ 주의 안내 포함)"

            parts.append(
                f"[Turn {turn.turn_index}]\n"
                f"의뢰인: {q_clean}\n"
                f"법률 도우미{status_note}:\n{a_clean}\n"
            )

        return "\n".join(parts).strip()



def build_conversation_summary(turns: List[ConversationTurn]) -> str:
    """과거 대화 턴들의 질문과 핵심 답변을 간결한 요약 문자열로 합성한다.

    Args:
        turns: 요약할 과거 상담 턴 리스트

    Returns:
        str: 1~3줄로 정돈된 대화 요약
    """
    if not turns:
        return ""

    summary_lines = []
    for t in turns[-3:]:  # 최근 최대 3턴 요약
        short_q = t.question[:80] + ("..." if len(t.question) > 80 else "")
        # 답변의 첫 문장 또는 핵심 추출
        first_line = t.answer.split("\n")[0] if t.answer else "(답변 없음)"
        short_a = first_line[:100] + ("..." if len(first_line) > 100 else "")
        summary_lines.append(f"- 턴 {t.turn_index}: 질의 '{short_q}' → 답변 요지: {short_a}")

    return "\n".join(summary_lines)


def load_conversation_context(
    db: Session,
    conversation_id: str,
    current_question: str,
    case_id: Optional[str] = None,
    user_id: Optional[str] = None,
    auth_bypass: bool = False,
) -> ConversationContext:
    """DB에서 지정된 conversation_id의 완료된 과거 상담 레코드를 조회하여 ConversationContext를 구축한다.

    사용자 권한 및 사건 소유권을 엄격히 검증하여 다른 사건이나 다른 사용자의 대화 맥락이
    혼입되는 것을 원천 차단한다.

    Args:
        db: SQLAlchemy 데이터베이스 세션
        conversation_id: 조회할 연속 대화 식별자
        current_question: 현재 사용자의 신규 질문
        case_id: 현재 사건 식별자 (제공 시 일치 여부 검증)
        user_id: 현재 로그인 사용자 식별자 (제공 시 소유권 검증)
        auth_bypass: 1인 로컬 테스트 환경 등에서 인증 검증 우회 여부

    Raises:
        PermissionError: 다른 사용자의 대화이거나 다른 사건의 대화 세션에 무단 접근한 경우

    Returns:
        ConversationContext: 구축된 대화 메모리 컨텍스트 객체
    """
    if not conversation_id:
        return ConversationContext(
            conversation_id="",
            case_id=case_id,
            user_id=user_id,
            current_question=current_question,
            turn_index=1,
            previous_turns=[],
        )

    # 1. 대화 세션 기준 상담 레코드 조회
    # (단일 사건 대화 구조에서는 case.primary_conversation_id를 conversation_id로 사용)
    records = (
        db.query(ConsultationRecord)
        .filter(ConsultationRecord.conversation_id == conversation_id)
        .order_by(ConsultationRecord.created_at.asc(), ConsultationRecord.turn_index.asc())
        .all()
    )

    # 2. 소유권 및 격리 검증 (Security & Context Isolation)
    if records:
        first_rec = records[0]
        if case_id and first_rec.case_id and first_rec.case_id != case_id:
            logger.error(
                f"[CONVERSATION_CONTEXT_SECURITY] Case mismatch for conversation {conversation_id}: "
                f"expected case {case_id}, found {first_rec.case_id}"
            )
            raise PermissionError(f"해당 대화 세션은 다른 사건(case_id: {first_rec.case_id})에 속해 있습니다.")

        if not auth_bypass and user_id and first_rec.user_id and first_rec.user_id != user_id:
            logger.error(
                f"[CONVERSATION_CONTEXT_SECURITY] User mismatch for conversation {conversation_id}: "
                f"requesting user {user_id}, owner {first_rec.user_id}"
            )
            raise PermissionError("해당 대화 세션에 대한 열람 및 작성 권한이 없습니다.")

    # 3. 사건 메모리 구성 (Case Memory - P0-08)
    case_memory = None
    if case_id:
        try:
            from ai_legal_helper.database.models import Case, Fact, EvidenceDocument
            case_obj = db.query(Case).filter(Case.id == case_id).first()
            if case_obj and hasattr(case_obj, "title"):
                # 실제 모델이거나 적절히 모킹된 객체인 경우
                if not auth_bypass and user_id and isinstance(case_obj.user_id, str) and case_obj.user_id != user_id:
                    raise PermissionError("해당 사건에 대한 열람 및 상담 권한이 없습니다.")

                title = case_obj.title if isinstance(case_obj.title, str) else ""
                case_type = case_obj.case_type if isinstance(case_obj.case_type, str) else ""
                status = case_obj.status if isinstance(case_obj.status, str) else ""

                facts_count = 0
                evs_count = 0
                try:
                    fc = db.query(Fact).filter(Fact.case_id == case_id).count()
                    ec = db.query(EvidenceDocument).filter(EvidenceDocument.case_id == case_id).count()
                    if isinstance(fc, int):
                        facts_count = fc
                    if isinstance(ec, int):
                        evs_count = ec
                except Exception:
                    pass

                case_memory = {
                    "title": title,
                    "case_type": case_type,
                    "status": status,
                    "confirmed_facts_count": facts_count,
                    "evidences_count": evs_count,
                }
        except PermissionError:
            raise
        except Exception as e:
            logger.debug(f"[CONVERSATION_CONTEXT] case_memory build skipped or failed: {e}")

    if not records:
        logger.debug(f"[CONVERSATION_CONTEXT] New conversation session started for case={case_id}, conv={conversation_id}")
        return ConversationContext(
            conversation_id=conversation_id,
            case_id=case_id,
            user_id=user_id,
            current_question=current_question,
            turn_index=1,
            previous_turns=[],
            case_memory=case_memory,
        )

    # 3. 완료된 턴들만 필터링하여 ConversationTurn 목록 구성
    turns: List[ConversationTurn] = []
    seen_sources: List[Dict[str, Any]] = []
    seen_source_ids = set()

    for rec in records:
        # 아직 진행 중이거나 거절/미완료된 건은 이전 답변으로 취급하지 않음
        if rec.status in ("IN_PROGRESS", "APPROVAL_REQUIRED") and not rec.answer:
            continue
        if not rec.answer:
            continue

        # 인용 출처 파싱
        rec_sources = rec.sources if isinstance(rec.sources, list) else []
        for s in rec_sources:
            if isinstance(s, dict):
                sid = s.get("source_id") or s.get("document_id") or s.get("file")
                if sid and sid not in seen_source_ids:
                    seen_source_ids.add(sid)
                    seen_sources.append(s)

        cdelta = None
        if isinstance(rec.verification_result, dict):
            cdelta = rec.verification_result.get("case_delta")

        turn = ConversationTurn(
            turn_index=rec.turn_index or (len(turns) + 1),
            request_id=rec.request_id,
            question=rec.question,
            answer=rec.answer,
            answer_status=rec.answer_status or "DELIVERED",
            verification_status=rec.verification_status,
            cited_sources=rec_sources,
            created_at=rec.created_at.isoformat() if rec.created_at else None,
            case_delta=cdelta,
        )
        turns.append(turn)

    # 4. 다음 턴 번호 및 직전 답변 정보 추출
    next_turn_index = len(turns) + 1
    last_turn = turns[-1] if turns else None
    last_answer = last_turn.answer if last_turn else None
    last_answer_status = last_turn.answer_status if last_turn else None

    # 5. 대화 요약문 구축
    summary = build_conversation_summary(turns)

    logger.info(
        f"[CONVERSATION_CONTEXT] Loaded context for conversation {conversation_id}: "
        f"{len(turns)} turns found, next turn_index={next_turn_index}"
    )

    return ConversationContext(
        conversation_id=conversation_id,
        case_id=case_id or first_rec.case_id,
        user_id=user_id or first_rec.user_id,
        current_question=current_question,
        turn_index=next_turn_index,
        previous_turns=turns,
        last_answer=last_answer,
        last_answer_status=last_answer_status,
        previously_cited_sources=seen_sources,
        conversation_summary=summary,
        case_memory=case_memory,
    )

