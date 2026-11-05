# -*- coding: utf-8 -*-
"""
모듈명: intent_analyzer.py

[모듈 개요]
사용자의 현재 질문과 이전 상담 대화 맥락(ConversationContext)을 분석하여,
질문의 법률적 의도(ConsultationIntent)를 식별하고 후속 질문의 문맥을 복원한
`resolved_query` 및 최적의 적응형 워크플로우 실행 계획(IntentDecision)을 수립하는 모듈이다.

[주요 기능]
1. `ConsultationIntent`: 법률 상담 질문 의도 7대 유형 정의
   - FOLLOWUP_ACTION (행동/절차 질의), FOLLOWUP_QUESTION (쟁점 세부질의),
     FACT_CLARIFICATION (사실 정정/보강), NEW_LEGAL_ANALYSIS (신규 심층 분석),
     DOCUMENT_REQUEST (문서 작성 요청), GENERAL_CONVERSATION (인사/단순대화),
     NEEDS_CLARIFICATION (의도 불명확 보류)
2. `IntentDecision`: 의도 분석 결과, 해석된 내부 질의(`resolved_query`), 실행 플래그
   (`requires_specialist`, `requires_retrieval`, `requires_verification`, `requires_full_analysis`)
3. `analyze_consultation_intent`: LLM 프롬프트 분석 및 코드 레벨의 엄격한 결정론적 정책 검증
4. 첫 번째 질문(턴 1)에서의 후속 질문 방어, 단문 질문 문맥 해석, 무분별한 Specialist 실행 방지

[주의사항]
- 특정 법률 분야나 사건 유형을 코드에 하드코딩하지 않는다.
- 첫 번째 턴(이전 대화가 없는 경우)에서는 FOLLOWUP_ACTION이나 FOLLOWUP_QUESTION이 될 수 없다.
- "이제 뭘 해야 하죠?"와 같은 절차/행동 질의는 RAG와 병렬 Specialist를 생략하고
  기존에 검증된 사실과 권고를 재사용하여 즉각적인 우선순위 행동 플랜을 제시한다.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
import json
import re

from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate

from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.case_intelligence.consultation_semantics import (
    has_repayment_assertion, is_evidence_review_request,
)
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.workflows.conversation_context import ConversationContext

logger = get_logger(__name__)


class ConsultationIntent(str, Enum):
    """법률 상담 질문 목적 및 의도 분류 열거형."""
    FOLLOWUP_ACTION = "FOLLOWUP_ACTION"            # 조치/행동 질문 ("이제 뭘 해야 하죠?", "어디로 가야 하나요?")
    FOLLOWUP_QUESTION = "FOLLOWUP_QUESTION"        # 세부 쟁점 질문 ("임차권등기명령은 언제 신청하나요?")
    FACT_CLARIFICATION = "FACT_CLARIFICATION"      # 사실관계 추가/정정 ("확정일자는 2022년 3월 10일입니다.")
    NEW_LEGAL_ANALYSIS = "NEW_LEGAL_ANALYSIS"      # 신규 법률 쟁점 분석 또는 첫 법률 검토
    DOCUMENT_REQUEST = "DOCUMENT_REQUEST"          # 내용증명, 소장 등 법률 문서 작성 요청
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"  # 인사, 감사, 단순 대화 ("안녕하세요", "고맙습니다")
    OUT_OF_SCOPE = "OUT_OF_SCOPE"  # 법률 상담 범위 밖의 요청
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"    # 질문 맥락 부족으로 추가 정보 필요


class ConsultationMode(str, Enum):
    """질문의 답변 근거 범위. 사건 자료의 *존재*와 별개로 매 턴 결정한다.

    GENERAL_LEGAL: 사건의 증거를 주장 근거로 사용하지 않는 일반 법률 설명.
    CASE_EVIDENCE: 현재 사건의 사실·증거와 법률을 함께 적용하는 상담.
    기존 상담과의 호환을 위해 누락/오류 시 사건 기반으로 보수적으로 처리한다.
    """
    GENERAL_LEGAL = "GENERAL_LEGAL"
    CASE_EVIDENCE = "CASE_EVIDENCE"


class IntentDecision(BaseModel):
    """질문 의도 분석 및 적응형 실행 계획 모델."""
    intent: ConsultationIntent = Field(description="판정된 질문 의도")
    consultation_mode: ConsultationMode = Field(
        default=ConsultationMode.CASE_EVIDENCE,
        description="질문에서 현재 사건 증거를 실제 판단 근거로 사용할지 여부",
    )
    resolved_query: str = Field(description="이전 대화 맥락이 연결되어 명확해진 내부 검색/작업 질의")
    requires_specialist: bool = Field(default=True, description="법률 Specialist 에이전트 실행 필요 여부")
    requires_retrieval: bool = Field(default=True, description="새로운 법령/판례 RAG 검색 실행 필요 여부")
    requires_verification: bool = Field(default=True, description="답변 검증(Verifier) 실행 필요 여부")
    requires_full_analysis: bool = Field(default=True, description="5단계 심층 의견서 형식 필요 여부")
    referenced_previous_turn_ids: List[str] = Field(default_factory=list, description="참조한 이전 턴 ID 목록")
    reason: str = Field(default="", description="의도 분류 및 실행 경로 선택 사유")
    # P8/P0-LAW: 질문 내 의뢰인 행위 기준일(계약일 등)과 법령 시점(개정/공포일 등) 분리 보존
    event_date: Optional[str] = Field(
        default=None,
        description="질문에서 식별된 의뢰인의 실제 법률 행위 기준일(계약 체결일, 인도일, 통지일 등. 형식: YYYY-MM-DD). 법령 개정/공포일은 제외",
    )
    event_type: Optional[str] = Field(
        default=None,
        description="식별된 사건 행위 유형 (CONTRACT_SIGNED, NOTICE_GIVEN, MOVE_OUT 등)",
    )
    statute_mention_date: Optional[str] = Field(
        default=None,
        description="질문에서 언급된 법령 개정일, 공포일, 시행일 (형식: YYYY-MM-DD)",
    )


INTENT_PROMPT = PromptTemplate.from_template(
    """당신은 대한민국 법률 AI의 대화 의도 분석가(Legal Intent Analyzer)입니다.
사용자의 현재 질문과 이전 대화 맥락, 사건 정보를 분석하여 사용자가 원하는 목적을 정확히 분류하고,
후속 질문인 경우 생략된 주어와 핵심 법률 쟁점을 복원한 'resolved_query'를 생성하세요.

#### [질문 의도(Intent) 분류 체계]
1. FOLLOWUP_ACTION: 이전 분석 결과를 바탕으로 지금 당장 취해야 할 행동, 우선순위, 선행조건, 절차를 묻는 경우
   - 예: "이제 뭘 해야 하죠?", "그다음은요?", "어디에 신청해야 하나요?", "지금 당장 할 수 있는 조치는요?"
2. FOLLOWUP_QUESTION: 앞선 답변에서 언급된 특정 개념, 조문, 법적 요건에 대해 구체적으로 더 묻는 경우
   - 예: "그럼 임차권등기명령은 언제 신청하나요?", "앞에서 말한 두 번째 방법의 비용은요?", "소멸시효는 얼마인가요?"
3. FACT_CLARIFICATION: 사용자가 자신의 사건에 관한 사실관계, 날짜, 금액, 증빙 유무를 정정하거나 새로 보강하는 경우
   - 예: "아까 확정일자가 없다고 했는데 확인해보니 있습니다.", "보증금 액수는 1억이 아니라 8천만원입니다."
4. NEW_LEGAL_ANALYSIS: 새로운 법률 분쟁이 시작되었거나, 이전 분석과 다른 완전히 새로운 법률 쟁점의 심층 분석을 요구하는 경우
   - 예: "전세보증금을 반환받지 못했습니다. 법률상 대항력과 우선변제권을 분석해주세요."
5. DOCUMENT_REQUEST: 내용증명, 소장, 지급명령신청서 등 법률 문서 초안을 직접 작성해달라고 명시적으로 요청하는 경우
   - 예: "임대인에게 보낼 계약해지 내용증명을 작성해주세요."
6. GENERAL_CONVERSATION: 인사말, 감사 표현, 법률 분석과 무관한 일상 대화인 경우
   - 예: "안녕하세요", "고마워요", "도움이 많이 되었습니다", "알겠습니다"
7. NEEDS_CLARIFICATION: 질문이 지나치게 모호하여 과거 대화 맥락을 고려해도 질문의 의도를 전혀 파악할 수 없는 경우
8. OUT_OF_SCOPE: 날씨, 스포츠 등 법률과 무관한 정보 요청. 사건 증거 유무와 관계없이 법률 상담 범위만 안내하고 종료

#### [분류 원칙]
- 현재 질문이 첫 번째 질문(이전 대화 없음)인 경우, FOLLOWUP_ACTION이나 FOLLOWUP_QUESTION으로 분류하지 마세요.
- 짧은 질문이라도 이전 대화가 있다면 생략된 법률적 의미를 살려 'resolved_query'를 구체적으로 작성하세요.
  * 예: 현재 질문 "이제 뭘 해야 하죠?" + 이전 대화 "보증금 미반환 및 가압류 분쟁"
    → resolved_query: "앞선 보증금 반환 지연 및 가압류 분쟁 분석을 바탕으로 의뢰인이 지금 우선적으로 취해야 할 단계별 조치 가이드"
  * 예: 현재 질문 "그럼 지금 이사를 가도 돼?" + 이전 대화 "보증금 미반환 분쟁"
    → resolved_query: "보증금 미반환 상황에서 현재 이사할 경우의 권리 유지 조건과 확인할 사항 검토 (임차권등기 신청·완료 여부는 미확인)"
- 사실관계를 새로 진술하는 경우(FACT_CLARIFICATION), 그 사실이 기존 판단에 어떤 영향을 미치는지 재검토할 수 있도록 resolved_query를 구성하세요.
- 사용자 진술, 상대방의 주장, 증거로 확인된 사실을 혼동하지 마세요. 특히 누군가 입금했다고 말했다는 진술을 실제 입금 완료로 확정하거나, 법률효과를 미리 결론 내리지 마세요.
- resolved_query는 현재 질문의 목적과 확인된 대화 맥락만 복원하세요. 이전 사건의 법률 분야·사실·법률 요건을 무관한 새 질문에 끌어오거나, 사용자 질문에 없는 새로운 사실을 만들어 넣지 마세요.
  * 예: 현재 질문 "집주인이 2천만 원을 입금했다고 합니다" (또는 "임대인이 일부 변제했습니다")
    → resolved_query: "의뢰인의 보증금 일부 입금/변제 주장에 따른 보증금 잔액 변동 및 입금 증거 확인 필요성 검토"

#### [상담 근거 범위 판단: consultation_mode]
- CASE_EVIDENCE: '내 사건', '등록된 자료', '계약서 분석', '앞선 사건에서' 등 현재 사건의 사실이나 증거를 적용해야 답할 수 있는 질문.
- GENERAL_LEGAL: 법률 제도·조문·판례에 대한 일반적인 설명으로 충분하며 사건 사실을 적용해 달라는 요청이 없는 질문.
- 사건에 증거가 존재한다는 사실만으로 CASE_EVIDENCE를 선택하지 마세요.
- 법률 분야와 근거 범위는 별개입니다. 같은 민법 질문도 일반 설명이면 GENERAL_LEGAL입니다.
- 모호한 후속 질문이 앞선 사건 상담을 가리키면 CASE_EVIDENCE로 판단하세요.
- 판단 근거는 사용자 질문의 의미와 대화 맥락입니다. 법률 분야별 키워드 규칙을 만들지 마세요.
- 법률과 무관한 정보 요청은 intent=OUT_OF_SCOPE로 분류하세요. 법률 쟁점으로 억지 해석하지 마세요.

#### [질문 내 날짜의 법률적 역할 분리 (매우 중요)]
- 질문에 날짜가 등장하는 경우, 해당 날짜의 법률적 역할을 명확히 구분하세요:
  1. event_date: 의뢰인의 실제 법률 행위 기준일 (예: 계약 체결일, 통지일, 입금일, 퇴거일 등. 형식: YYYY-MM-DD). 법령이 개정/공포된 날짜는 절대로 event_date로 지정하지 마세요.
  2. event_type: 식별된 행위 유형 ("CONTRACT_SIGNED", "CONTRACT_RENEWED", "CONTRACT_MODIFIED", "NOTICE_GIVEN", "MOVE_OUT" 등 또는 null)
  3. statute_mention_date: 질문자가 언급한 법령·시행령·규칙의 개정일, 공포일, 시행일 (예: "2026년 10월 27일 개정된 시행령" -> 2026-10-27). 날짜가 없으면 null.

#### [대화 맥락]
{conversation_context}

#### [사건 기본 정보]
{case_context}

#### [현재 사용자 질문]
{question}

#### [출력 형식 (반드시 유효한 JSON 하나만 출력)]
{{
  "intent": "FOLLOWUP_ACTION | FOLLOWUP_QUESTION | FACT_CLARIFICATION | NEW_LEGAL_ANALYSIS | DOCUMENT_REQUEST | GENERAL_CONVERSATION | NEEDS_CLARIFICATION | OUT_OF_SCOPE",
  "consultation_mode": "GENERAL_LEGAL | CASE_EVIDENCE",
  "resolved_query": "문맥이 연결되어 명확해진 내부 작업용 구체적 질의문",
  "requires_specialist": true/false,
  "requires_retrieval": true/false,
  "requires_verification": true/false,
  "requires_full_analysis": true/false,
  "reason": "분류 사유 (1~2문장)",
  "event_date": "YYYY-MM-DD 또는 null",
  "event_type": "CONTRACT_SIGNED | NOTICE_GIVEN | MOVE_OUT | null",
  "statute_mention_date": "YYYY-MM-DD 또는 null"
}}
"""
)


def _heuristic_rule_fallback(
    question: str,
    has_history: bool,
    case_context: str = "",
) -> IntentDecision:
    """Fallback for UI routing only, never a legal or factual verdict.

    Keep the exact question unchanged for all legal analyses. Short explicit
    UI requests (review, thanks, next actions, corrections) are recognized
    without inferring repayment, contract effect, dates or missing facts.
    """
    q = (question or "").strip()
    if not q:
        return IntentDecision(
            intent=ConsultationIntent.NEEDS_CLARIFICATION,
            resolved_query=q, requires_specialist=False,
            requires_retrieval=False, requires_verification=False,
            requires_full_analysis=False, reason="원질문 미입력",
        )
    normalized = q.replace(" ", "").rstrip(".!?~")
    if len(normalized) <= 30 and any(
        normalized.endswith(word) for word in (
            "감사합니다", "고맙습니다", "고마워요", "수고하셨습니다",
            "안녕하세요", "알겠습니다", "도움주셔서감사합니다",
        )
    ):
        return IntentDecision(
            intent=ConsultationIntent.GENERAL_CONVERSATION,
            resolved_query=q, requires_specialist=False,
            requires_retrieval=False, requires_verification=False,
            requires_full_analysis=False, reason="명시적인 인사·감사 메시지",
        )

    # These are explicit *requests* to inspect already submitted data,
    # not claims that the landlord actually repaid any money.
    material_review = (
        any(term in q for term in ("등록된", "제출된", "계약서와", "증거자료", "이체 자료"))
        and any(term in q for term in ("분석", "검토", "확인해", "정리", "대조"))
    )
    if material_review:
        return IntentDecision(
            intent=ConsultationIntent.NEW_LEGAL_ANALYSIS,
            resolved_query=q, requires_specialist=True,
            requires_retrieval=True, requires_verification=True,
            requires_full_analysis=True,
            reason="등록 자료의 사실·법률 분석 요청(반환 사실 주장은 아님)",
        )

    if not has_history:
        return IntentDecision(
            intent=ConsultationIntent.NEW_LEGAL_ANALYSIS,
            resolved_query=q, requires_specialist=True,
            requires_retrieval=True, requires_verification=True,
            requires_full_analysis=True,
            reason="사건의 첫 법률 상담",
        )

    if any(term in q for term in (
        "뭘 해야", "어떻게 해야", "다음 조치", "우선순위", "다음 단계",
        "그다음은", "지금 해야", "취해야 할",
    )):
        return IntentDecision(
            intent=ConsultationIntent.FOLLOWUP_ACTION,
            resolved_query="이전 상담에 따라 지금 실행할 우선순위 조치: " + q,
            requires_specialist=False, requires_retrieval=False,
            requires_verification=True, requires_full_analysis=False,
            reason="명시적인 다음 행동 요청(기존 검증 결과 재사용)",
        )
    if (
        any(term in q for term in ("정정", "잘못 알았", "확정일자는", "날짜가 달라"))
        and not q.endswith("?")
    ):
        return IntentDecision(
            intent=ConsultationIntent.FACT_CLARIFICATION,
            resolved_query=q,
            requires_specialist=True, requires_retrieval=False,
            requires_verification=True, requires_full_analysis=False,
            reason="사용자의 명시적인 사실 정정 요청(원문은 USER_ALLEGED)",
        )
    return IntentDecision(
        intent=ConsultationIntent.FOLLOWUP_QUESTION,
        resolved_query=q, requires_specialist=True,
        requires_retrieval=True, requires_verification=True,
        requires_full_analysis=False,
        reason="의도 모델 미응답: 법률 의미를 추정하지 않고 후속 질의 검토",
    )

@trace
def analyze_consultation_intent(
    question: str,
    conversation_context: Optional[ConversationContext] = None,
    case_context: str = "",
) -> IntentDecision:
    """사용자 질문의 법률적 의도를 분석하고, 문맥이 연결된 resolved_query 및 실행 플래그를 결정한다.

    LLM을 통한 맥락 분석과 코드 레벨의 엄격한 정책 검증(Guardrail)을 결합하여,
    환각이나 엉뚱한 분기를 원천 차단한다.

    Args:
        question: 사용자의 현재 질문 문자열
        conversation_context: 이전 상담 턴들이 담긴 ConversationContext 객체 (선택)
        case_context: 현재 사건의 기본 사실관계 및 타임라인 문자열 (선택)

    Returns:
        IntentDecision: 질문 의도, 해석된 쿼리, 실행 필요 플래그를 담은 결정 객체
    """
    has_history = bool(conversation_context and conversation_context.previous_turns)
    conv_text = conversation_context.format_context_for_prompt(max_turns=3) if conversation_context else "(이전 상담 대화 없음 — 신규 대화)"

    # 1. LLM 호출 준비
    decision: Optional[IntentDecision] = None
    try:
        llm = get_llm(temperature=0.0)
        prompt_val = INTENT_PROMPT.format(
            question=question.strip(),
            conversation_context=conv_text,
            case_context=case_context[:1000] if case_context else "(사건 정보 없음)",
        )
        response = llm.invoke(prompt_val)
        raw_content = getattr(response, "content", str(response)).strip()

        # JSON 블록 추출
        match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            intent_raw = parsed.get("intent", "NEW_LEGAL_ANALYSIS")
            try:
                intent_enum = ConsultationIntent(intent_raw)
            except ValueError:
                intent_enum = ConsultationIntent.NEW_LEGAL_ANALYSIS

            resolved_q = parsed.get("resolved_query") or question
            requires_spec = bool(parsed.get("requires_specialist", True))
            requires_ret = bool(parsed.get("requires_retrieval", True))
            requires_ver = bool(parsed.get("requires_verification", True))
            requires_full = bool(parsed.get("requires_full_analysis", True))
            reason_str = parsed.get("reason", "")

            # 오래된 LLM 응답이 consultation_mode를 생략하면 사건 상담을 유지한다.
            # 알 수 없는 값도 사건 증거를 버리는 방향으로 추측하지 않는다.
            try:
                consultation_mode = ConsultationMode(parsed.get("consultation_mode", "CASE_EVIDENCE"))
            except (ValueError, TypeError):
                consultation_mode = ConsultationMode.CASE_EVIDENCE

            event_d = parsed.get("event_date")
            event_t = parsed.get("event_type")
            statute_d = parsed.get("statute_mention_date")
            # If LLM did not identify an event, retain UNKNOWN.
            # Keyword/date extraction must not invent a law-applicability date.

            decision = IntentDecision(
                intent=intent_enum,
                consultation_mode=consultation_mode,
                resolved_query=resolved_q,
                requires_specialist=requires_spec,
                requires_retrieval=requires_ret,
                requires_verification=requires_ver,
                requires_full_analysis=requires_full,
                reason=reason_str,
                event_date=event_d,
                event_type=event_t,
                statute_mention_date=statute_d,
            )
    except Exception as e:
        logger.warning(f"[INTENT_ANALYZER] LLM 질문 의도 분석 실패(규칙 폴백 적용): {e}")

    # On model failure, the product must not dispose of a potentially valid
    # legal question as unknown merely because intent classification failed.
    # This fallback selects a workflow, NEVER proves a case fact.
    if decision is None:
        decision = _heuristic_rule_fallback(
            question, has_history=has_history, case_context=case_context,
        )

    # Current user request, not a rewritten LLM query, controls whether the
    # user explicitly asked to analyze registered documents. A model must not
    # turn that request into a new unverified repayment event.
    explicit_route = _heuristic_rule_fallback(
        question, has_history=has_history, case_context=case_context,
    )
    if (explicit_route.intent == ConsultationIntent.NEW_LEGAL_ANALYSIS
            and "등록 자료의 사실" in explicit_route.reason):
        decision = explicit_route
        decision.consultation_mode = ConsultationMode.CASE_EVIDENCE

    # 3. 코드 레벨의 엄격한 가드레일 정책 검증 (Deterministic Policy Verification)
    # 정책 A: 첫 번째 질문인데 FOLLOWUP 계열로 잘못 분류된 경우 신규 분석으로 강제 교정
    if not has_history and decision.intent in (ConsultationIntent.FOLLOWUP_ACTION, ConsultationIntent.FOLLOWUP_QUESTION):
        logger.info(f"[INTENT_GUARDRAIL] 첫 번째 턴 의도({decision.intent})를 신규 법률 분석(NEW_LEGAL_ANALYSIS)으로 보정합니다.")
        decision.intent = ConsultationIntent.NEW_LEGAL_ANALYSIS
        decision.requires_specialist = True
        decision.requires_retrieval = True
        decision.requires_full_analysis = True

    # 정책 B: FOLLOWUP_ACTION인 경우 Specialist와 RAG는 비활성화하되, Verifier는 유지
    if decision.intent == ConsultationIntent.FOLLOWUP_ACTION:
        decision.requires_specialist = False
        decision.requires_retrieval = False
        decision.requires_verification = True
        decision.requires_full_analysis = False

    # 정책 C: GENERAL_CONVERSATION인 경우 모든 무거운 파이프라인 비활성화
    # 법률 무관 요청은 일반 인사와 별도 의도로 유지하고 무거운 분석을 중지한다.
    if decision.intent in (ConsultationIntent.GENERAL_CONVERSATION, ConsultationIntent.OUT_OF_SCOPE):
        decision.consultation_mode = ConsultationMode.GENERAL_LEGAL
        decision.requires_specialist = False
        decision.requires_retrieval = False
        decision.requires_verification = False
        decision.requires_full_analysis = False

    # 정책 D: 참조 턴 ID 목록 등록
    if conversation_context and conversation_context.previous_turns:
        decision.referenced_previous_turn_ids = [
            t.request_id for t in conversation_context.previous_turns[-3:]
        ]

    # 정책 E: resolved_query 안전성 검증 (비어있으면 현재 질문으로 보정)
    if not decision.resolved_query or len(decision.resolved_query.strip()) < 2:
        decision.resolved_query = question.strip()

    logger.info(
        f"[INTENT_ANALYZER] 질문 의도 판정 완료: 의도={decision.intent.value}, "
        f"전문분석={decision.requires_specialist}, 자료검색={decision.requires_retrieval}, "
        f"복원질의길이={len(decision.resolved_query)}자"
    )

    return decision
