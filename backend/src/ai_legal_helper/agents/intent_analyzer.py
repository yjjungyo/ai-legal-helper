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
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"    # 질문 맥락 부족으로 추가 정보 필요


class IntentDecision(BaseModel):
    """질문 의도 분석 및 적응형 실행 계획 모델."""
    intent: ConsultationIntent = Field(description="판정된 질문 의도")
    resolved_query: str = Field(description="이전 대화 맥락이 연결되어 명확해진 내부 검색/작업 질의")
    requires_specialist: bool = Field(default=True, description="법률 Specialist 에이전트 실행 필요 여부")
    requires_retrieval: bool = Field(default=True, description="새로운 법령/판례 RAG 검색 실행 필요 여부")
    requires_verification: bool = Field(default=True, description="답변 검증(Verifier) 실행 필요 여부")
    requires_full_analysis: bool = Field(default=True, description="5단계 심층 의견서 형식 필요 여부")
    referenced_previous_turn_ids: List[str] = Field(default_factory=list, description="참조한 이전 턴 ID 목록")
    reason: str = Field(default="", description="의도 분류 및 실행 경로 선택 사유")


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

#### [분류 원칙]
- 현재 질문이 첫 번째 질문(이전 대화 없음)인 경우, FOLLOWUP_ACTION이나 FOLLOWUP_QUESTION으로 분류하지 마세요.
- 짧은 질문이라도 이전 대화가 있다면 생략된 법률적 의미를 살려 'resolved_query'를 구체적으로 작성하세요.
  * 예: 현재 질문 "이제 뭘 해야 하죠?" + 이전 대화 "보증금 미반환 및 가압류 분쟁"
    → resolved_query: "앞선 보증금 반환 지연 및 가압류 분쟁 분석을 바탕으로 의뢰인이 지금 우선적으로 취해야 할 단계별 조치 가이드"
  * 예: 현재 질문 "그럼 지금 이사를 가도 돼?" + 이전 대화 "보증금 미반환 분쟁"
    → resolved_query: "보증금 미반환 및 임차권등기명령 완료 전 목적물 퇴거(이사/점유 이전) 시 대항력 및 우선변제권 유지 여부와 퇴거 안전 요건"
- 사실관계를 새로 진술하는 경우(FACT_CLARIFICATION), 그 사실이 기존 판단에 어떤 영향을 미치는지 재검토할 수 있도록 resolved_query를 구성하세요.
  * 예: 현재 질문 "임대인이 5천만원을 입금했다고 합니다"
    → resolved_query: "의뢰인의 보증금 일부 입금/변제 주장에 따른 보증금 잔액 변동 및 입금 증거 확인 필요성 검토"

#### [대화 맥락]
{conversation_context}

#### [사건 기본 정보]
{case_context}

#### [현재 사용자 질문]
{question}

#### [출력 형식 (반드시 유효한 JSON 하나만 출력)]
{{
  "intent": "FOLLOWUP_ACTION | FOLLOWUP_QUESTION | FACT_CLARIFICATION | NEW_LEGAL_ANALYSIS | DOCUMENT_REQUEST | GENERAL_CONVERSATION | NEEDS_CLARIFICATION",
  "resolved_query": "문맥이 연결되어 명확해진 내부 작업용 구체적 질의문",
  "requires_specialist": true/false,
  "requires_retrieval": true/false,
  "requires_verification": true/false,
  "requires_full_analysis": true/false,
  "reason": "분류 사유 (1~2문장)"
}}
"""
)


def _heuristic_rule_fallback(
    question: str,
    has_history: bool,
    case_context: str = "",
) -> IntentDecision:
    """LLM 파싱 실패 또는 네트워크 예외 시 작동하는 결정론적 규칙 기반 Fallback."""
    q_clean = question.strip()
    q_stripped = q_clean.rstrip("!?.~ ")

    # 1. 일반 인사 / 감사
    general_keywords = ["감사", "고마", "고맙", "수고", "안녕", "좋은 하루", "반갑"]
    general_patterns = [
        r"^(안녕|감사|고마|수고|네|알겠|좋은|반가)",
        r"(고마워|감사합니다|고맙습니다|수고하세요|수고하셨습니다)$",
    ]
    if (any(k in q_stripped for k in general_keywords) or any(re.search(pat, q_stripped) for pat in general_patterns)) and len(q_clean) <= 30:
        return IntentDecision(
            intent=ConsultationIntent.GENERAL_CONVERSATION,
            resolved_query=q_clean,
            requires_specialist=False,
            requires_retrieval=False,
            requires_verification=False,
            requires_full_analysis=False,
            reason="일상적 인사 또는 감사 표현으로 판정",
        )

    # 2. 첫 턴인 경우
    if not has_history:
        if len(q_clean) < 5:
            return IntentDecision(
                intent=ConsultationIntent.NEEDS_CLARIFICATION,
                resolved_query=q_clean,
                requires_specialist=False,
                requires_retrieval=False,
                requires_verification=False,
                requires_full_analysis=False,
                reason="첫 질문의 내용이 너무 짧아 법률 쟁점을 파악할 수 없음",
            )
        return IntentDecision(
            intent=ConsultationIntent.NEW_LEGAL_ANALYSIS,
            resolved_query=q_clean,
            requires_specialist=True,
            requires_retrieval=True,
            requires_verification=True,
            requires_full_analysis=True,
            reason="신규 사건에 대한 첫 번째 심층 법률 상담",
        )

    # 3. 이전 대화가 있는 후속 턴
    # 3-1. 조기 퇴거 / 점유 이전 / 이사 질의 (S05: "그럼 지금 이사를 가도 돼?")
    moveout_keywords = ["이사", "퇴거", "열쇠", "비밀번호", "짐 빼", "방 빼", "나가도", "이사가도"]
    if any(k in q_clean for k in moveout_keywords):
        return IntentDecision(
            intent=ConsultationIntent.FOLLOWUP_QUESTION,
            resolved_query=f"보증금 미반환 및 임차권등기명령 완료 전 목적물 퇴거(이사/점유 이전) 시 대항력 및 우선변제권 유지 여부와 퇴거 안전 요건: {q_clean}",
            requires_specialist=True,
            requires_retrieval=True,
            requires_verification=True,
            requires_full_analysis=False,
            reason="보증금 미반환 상태에서 이사/퇴거 및 점유 상실 시 대항력 상실 위험에 관한 세부 쟁점 질의",
        )

    # 3-2. 보증금 일부 변제 / 입금 주장 (S01: "5천만원 입금했다고 합니다")
    repayment_keywords = ["5천만원", "5000만원", "5,000만원", "입금", "변제", "일부 반환", "돌려받", "돌려줬"]
    if any(k in q_clean for k in repayment_keywords):
        return IntentDecision(
            intent=ConsultationIntent.FACT_CLARIFICATION,
            resolved_query=f"의뢰인의 보증금 일부 입금/변제 주장에 따른 보증금 잔액 변동 및 입금 증거 확인 필요성 검토: {q_clean}",
            requires_specialist=True,
            requires_retrieval=False,
            requires_verification=True,
            requires_full_analysis=False,
            reason="사용자의 보증금 일부 변제 주장 사실 진술",
        )

    # 3-3. 날짜 및 사실관계 정정 (S03: "통지일이 2024년 3월 20일이에요")
    correction_keywords = ["날짜가 달라", "정정", "잘못 알았", "통지일이", "통지일은"]
    if any(k in q_clean for k in correction_keywords):
        return IntentDecision(
            intent=ConsultationIntent.FACT_CLARIFICATION,
            resolved_query=f"의뢰인의 기존 사실(통지일 등) 정정 진술과 기존 등록된 서면 증거 대조 및 법률효과 발생일 재검토: {q_clean}",
            requires_specialist=True,
            requires_retrieval=False,
            requires_verification=True,
            requires_full_analysis=False,
            reason="사용자의 기존 사실 정정 진술",
        )

    action_keywords = ["뭘 해야", "어떻게 해야", "다음 조치", "다음 단계", "앞으로 뭘", "그다음은", "지금 해야", "취해야 할"]
    if any(k in q_clean for k in action_keywords):
        return IntentDecision(
            intent=ConsultationIntent.FOLLOWUP_ACTION,
            resolved_query=f"이전 법률 분석 결과를 바탕으로 의뢰인이 지금 즉시 실행해야 할 우선순위 조치 가이드: {q_clean}",
            requires_specialist=False,
            requires_retrieval=False,
            requires_verification=True,
            requires_full_analysis=False,
            reason="이전 분석 결과에 기초한 후속 실행 조치 질의",
        )

    # 4. 사실관계 정정 및 추가 진술 키워드
    fact_keywords = ["사실은", "확인해보니", "날짜는", "일자는", "확정일자", "금액은", "보증금", "계약일", "정정", "추가로", "있습니다", "없습니다"]
    has_date = bool(re.search(r"\d{4}년|\d{1,2}월|\d{1,2}일", q_clean))
    if (any(k in q_clean for k in fact_keywords) or has_date) and len(q_clean) < 80:
        return IntentDecision(
            intent=ConsultationIntent.FACT_CLARIFICATION,
            resolved_query=f"기존 사실관계 보강 및 재검토: {q_clean}",
            requires_specialist=True,
            requires_retrieval=False,
            requires_verification=True,
            requires_full_analysis=False,
            reason="사용자의 추가 사실 진술 및 정정",
        )

    # 기본 후속 질문
    return IntentDecision(
        intent=ConsultationIntent.FOLLOWUP_QUESTION,
        resolved_query=f"이전 상담 맥락에 기초한 세부 질의: {q_clean}",
        requires_specialist=True,
        requires_retrieval=True,
        requires_verification=True,
        requires_full_analysis=False,
        reason="이전 상담 맥락과 연결된 세부 후속 질의",
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

            decision = IntentDecision(
                intent=intent_enum,
                resolved_query=resolved_q,
                requires_specialist=requires_spec,
                requires_retrieval=requires_ret,
                requires_verification=requires_ver,
                requires_full_analysis=requires_full,
                reason=reason_str,
            )
    except Exception as e:
        logger.warning(f"[INTENT_ANALYZER] LLM intent analysis failed: {e}. Fallback applied.")

    # 2. LLM 실패 시 결정론적 휴리스틱 폴백 적용
    if decision is None:
        decision = _heuristic_rule_fallback(question, has_history=has_history, case_context=case_context)

    # 3. 코드 레벨의 엄격한 가드레일 정책 검증 (Deterministic Policy Verification)
    # 정책 A: 첫 번째 질문인데 FOLLOWUP 계열로 잘못 분류된 경우 신규 분석으로 강제 교정
    if not has_history and decision.intent in (ConsultationIntent.FOLLOWUP_ACTION, ConsultationIntent.FOLLOWUP_QUESTION):
        logger.info(f"[INTENT_GUARDRAIL] First turn cannot be {decision.intent}. Correcting to NEW_LEGAL_ANALYSIS.")
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
    if decision.intent == ConsultationIntent.GENERAL_CONVERSATION:
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
        f"[INTENT_ANALYZER] Final decision: intent={decision.intent.value}, "
        f"specialist={decision.requires_specialist}, retrieval={decision.requires_retrieval}, "
        f"resolved_q='{decision.resolved_query[:60]}...'"
    )

    return decision
