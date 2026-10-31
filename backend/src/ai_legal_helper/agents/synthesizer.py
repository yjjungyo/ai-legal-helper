# -*- coding: utf-8 -*-
from typing import Any, Dict, List, Optional
from langchain_core.messages import AIMessage, HumanMessage, AnyMessage
from langchain_core.prompts import PromptTemplate
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

__all__ = ["synthesize"]

def _brief_history(messages: List[AnyMessage], max_chars: int = 800) -> str:
    if not messages:
        return "(이전 대화 없음)"
    parts: List[str] = []
    for m in messages[-10:]:
        role = "사용자" if isinstance(m, HumanMessage) else "도우미"
        text = m.content if isinstance(m.content, str) else str(m.content)
        text = text.replace("\n", " ")
        if len(text) > 160:
            text = text[:160] + f"...(+{len(text)-160})"
        parts.append(f"{role}: {text}")
    s = " / ".join(parts)
    return s[:max_chars] + ("... (trunc)" if len(s) > max_chars else "")

def _extract_last_question(messages: List[AnyMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return m.content if isinstance(m.content, str) else str(m.content)
    return ""

def _format_findings(results: Dict[str, str], per_cat_limit: int = 2400) -> str:
    lines: List[str] = []
    for cat, text in results.items():
        t = (text or "").strip()
        if len(t) > per_cat_limit:
            t = t[:per_cat_limit] + f"...(+{len(text)-per_cat_limit})"
        lines.append(f"### {cat}\n{t}\n")
    return "\n".join(lines).strip()

def _render_originals(results: Dict[str, str]) -> str:
    lines: List[str] = ["[참고 : 분야별 전문가 상세 답변]"]
    for cat, text in results.items():
        lines.append(f"\n[분야: {cat}]")
        lines.append(text or "(답변 없음)")
    return "\n".join(lines)

SYNTH_SYSTEM = """당신은 대한민국 법률 전문가입니다.
사용자의 질문과 각 전문 에이전트의 분석을 바탕으로, 의뢰인이 한눈에 이해할 수 있는 명쾌하고 사용자 친화적인 법률 상담 답변을 작성하세요.
사고 과정(Chain-of-Thought)을 출력하지 마세요.

[답변 작성 4대 핵심 원칙 (STEP 6)]
1. 첫 번째: 질문에 바로 직접 답변
   - 답변 첫 부분에 핵심 결론을 바로 제시하세요.
   - 불필요하게 '사건 증거 기반 AI 분석 결과', '검증 완료', '6단계 검증 수행', '쟁점별 교차 검증 결과', '법률 분석 보고서' 같은 내부 시스템 서론으로 시작하지 마세요.
2. 두 번째: 필요한 만큼만 설명 (동적 섹션 구성)
   - 단순 법률 질문: 핵심 결론 답변 + 관련 법률 조문 간결 설명
   - 사건 기반 상담: 현재 상황에 대한 판단 + 이유와 근거 + 지금 필요한 조치 + 결론에 영향을 주는 미확인 사항
   - 복합 분쟁 질문: 핵심 결론 + 주요 쟁점별 설명 + 필요한 대응 순서 + 관련 증거 및 법률
   - 소제목은 딱딱한 번호 매김 대신 마크다운 헤더(예: `### 현재 계약 상태`, `### 계약을 종료하려면`, `### 지금 해야 할 일`, `### 확인할 사항`)로 자연스럽게 구성하세요.
3. 세 번째: 불필요한 반복 제거
   - 동일한 결론을 앞에서 쓰고 뒤에서 다시 반복하지 마세요.
   - 모든 질문에 무조건 소송/지급명령 절차 안내를 강제하지 마세요.
   - 불필요한 면책 문구를 여러 번 반복하지 마세요.
4. 네 번째: 출처를 자연스럽게 표시
   - 사건 증거: 반드시 전체 파일명을 보존하여 `[E01_주택임대차계약서.txt]`, `[E05_퇴거_및_보증금_반환_요청_문자.pdf]` 형태로 표기하세요.
   - 법령 조문: 긴 공포번호나 시행일을 나열하지 말고, `(주택임대차보호법 제6조의2)` 또는 `주택임대차보호법 제6조의2`와 같이 간결하고 자연스럽게 표기하세요.

[사실 및 근거 구분 원칙]
- 객관적 증거가 확인된 사실과 의뢰인의 주관적 진술을 엄격히 구분하세요.
- 등록되지 않은 가상의 증거 번호('증거 1호', '증거 2' 등)나 허위 출처를 절대 생성하지 마세요.
- 중요한 핵심 요건, 금액, 날짜는 `**볼드**`로 강조하세요.
"""

SYNTH_FEWSHOT = """
[좋은 법률 상담 답변 예시]
현재 고객님의 임대차 계약은 계약서를 새로 쓰지 않았다는 사유만으로 종료되는 것은 아니며, 관련 법령상 묵시적으로 갱신된 상태로 볼 수 있습니다.

### 현재 계약 상태
주택임대차보호법 제6조에 따라 임대차 만료 2개월 전까지 갱신 거절 통지가 없었다면 종전과 동일한 조건으로 계약이 갱신된 것으로 봅니다. [E01_주택임대차계약서.txt]

### 계약을 종료하려면
묵시적으로 갱신된 상태에서 임차인은 언제든지 임대인에게 해지를 통지할 수 있으며, 임대인이 통지를 받은 날부터 3개월이 지나면 해지 효력이 발생합니다. (주택임대차보호법 제6조의2)

### 확인할 사항
기존에 임대인에게 발송한 해지 의사표시가 있다면 그 통지가 임대인에게 도달했는지 확인하는 것이 가장 중요합니다. [E05_퇴거_및_보증금_반환_요청_문자.txt]
"""
SYNTH_FOLLOWUP_SYSTEM = """당신은 대한민국 법률 전문가입니다.
- 의뢰인의 후속 세부 질문에 대해 직전 상담 내용을 바탕으로 직접적이고 명쾌하게 한국어로 답변하세요.
- 사고 과정(Chain-of-Thought)을 출력하지 마세요.
- 중요 원칙:
  1. 이전 상담의 서론이나 일반 법리를 처음부터 장황하게 반복하지 마세요.
  2. 5단계 의견서 형식을 강제하지 마세요. 질문받은 세부 쟁점에 집중하여 다음 3개 핵심 구조로 간결하게 답변하세요:
     [1. 질문에 대한 핵심 결론 및 직접 답변]
     [2. 세부 법적 요건 및 근거] (관련 조문 및 판례 근거만 간결하게 설명)
     [3. 실무상 유의사항 및 다음 조치]
  3. 사실 상태를 엄격히 구분하여 작성하고, 실제 등록되지 않은 가상의 증거 번호('증거 1', '증거 2' 등)를 절대 생성하지 마세요.
  4. 중요한 핵심 단어에는 **볼드** 강조를 적절히 사용하세요.
  5. 법률 조문은 '(법령명 제O조)', 증거는 '(파일명.pdf, p.페이지)' 형태로만 인용하세요.
"""

SYNTH_FOLLOWUP_FEWSHOT = """
[후속 질문 답변 양식 예시]
[1. 질문에 대한 핵심 결론 및 직접 답변]
- 의뢰인이 질문하신 임차권등기명령은 임대차계약 기간이 만료된 익일부터 신청할 수 있습니다. 계약 존속 중에는 신청할 수 없습니다.

[2. 세부 법적 요건 및 근거]
- 법적 요건: (1) 임대차계약의 종료, (2) 임차보증금 전액 또는 일부의 미반환
- 근거 법령: (주택임대차보호법 제3조의3 제1항)
- 대항력 유지 효과: 등기명령이 집행 완료되면 이사를 가거나 주민등록을 이전하더라도 기존에 취득한 대항력과 우선변제권이 상실되지 않고 유지됩니다.

[3. 실무상 유의사항 및 다음 조치]
- 유의사항: 관할 법원에 신청서를 제출한 후 등기부등본(을구)에 임차권등기가 실제로 기재된 것을 확인한 후에 퇴거(이사)하셔야 대항력이 안전하게 유지됩니다.
- 구비 서류: 임대차계약서 사본, 계약 해지 통지 증빙(문자/내용증명), 부동산등기부등본, 주민등록초본
"""

SYNTH_FACT_CLARIFICATION_SYSTEM = """당신은 대한민국 법률 전문가입니다.
- 의뢰인이 추가로 진술하거나 정정한 사실관계에 대해, 이것이 기존 법률 분석 결론 및 권리 관계에 미치는 영향을 신속하고 명쾌하게 분석하세요.
- 사고 과정(Chain-of-Thought)을 출력하지 마세요.
- 다음 3가지 핵심 구조로 작성하세요:
  [1. 정정/추가된 사실관계가 결론에 미치는 영향]
  [2. 변경된 법률 요건 검토 및 관련 근거]
  [3. 향후 입증 및 권리 행사 시 유의점]
- 임의의 가상 증거번호를 생성하지 마세요.
"""

SYNTH_DOCUMENT_SYSTEM = """당신은 대한민국 법률 전문가입니다.
- 의뢰인이 요청한 법률 서식(내용증명, 계약서, 신청서 등)의 실무 표준 초안과 작성 가이드를 작성하세요.
- 사고 과정(Chain-of-Thought)을 출력하지 마세요.
- 다음 구조로 작성하세요:
  [1. 법률 문서 표준 초안]
  (제목, 발신인, 수신인, 목적물 표시, 본문, 작성일자, 발신인 서명란)
  [2. 작성 및 발송/제출 시 실무 유의사항]
- 임의의 가상 증거번호를 생성하지 마세요.
"""

SYNTH_PROMPT = PromptTemplate.from_template(
    """{system}

[대화 요약]
{chat_brief}

[사용자 질문]
{question}

[카테고리별 에이전트 답변 (요약 입력)]
{findings}

{fewshot}

[지시]
위 정보를 종합하여, 의뢰인이 즉시 활용할 수 있는 명확하고 전문적인 [최종 법률 의견서]를 작성하세요.
- 불확실한 부분은 가정/한계를 명시하세요.
- 핵심 조치/절차/기한/요건을 명확히 하세요.
- 마지막에 간단한 면책 문구를 포함하세요.
"""
)

@trace
def synthesize(
    messages: List[AnyMessage],
    results: Dict[str, str],
    intent: Optional[str] = None,
    case_evidence_briefing: Optional[Dict[str, Any]] = None,
    issue_tasks: Optional[List[Dict[str, Any]]] = None,
    source_registry: Optional[Dict[str, Any]] = None,
) -> List[AnyMessage]:
    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting

    if not results:
        final = "관련 카테고리에서 유의미한 답변을 생성하지 못했습니다. 질문을 구체화해 주세요."
        logger.debug("[종합 분석] 전문 에이전트 분석 결과가 비어 있어 기본 안내로 대체합니다.")
        return messages + [AIMessage(content=final)]

    chat_brief = _brief_history(messages)
    question = _extract_last_question(messages)
    # [P0-05/Gate 3] 프롬프트 토큰 최적화: per_cat_limit 1500자, briefing 2500자 제한
    findings = _format_findings(results, per_cat_limit=1500)

    # 사건 증거 브리핑 텍스트 구성 (P0-01, P0-02, P0-07)
    briefing_text = "(등록된 사건 증거 정보 없음)"
    if case_evidence_briefing:
        b_summary = case_evidence_briefing.get("formatted_summary", "")
        if len(b_summary) > 2500:
            briefing_text = b_summary[:2500] + "\n...(후략)"
        else:
            briefing_text = b_summary or "(등록된 사건 증거 정보 없음)"

    # 계획된 법률 쟁점 목록 텍스트 구성 (P0-03)
    issues_text = "(전체 종합 검토)"
    if issue_tasks:
        lines = []
        for it in issue_tasks:
            evs = ", ".join(it.get("relevant_evidence_labels", []))
            lbl_part = f" [증거: {evs}]" if evs else ""
            lines.append(f"- {it.get('issue_title', '')}{lbl_part}")
        issues_text = "\n".join(lines)

    try:
        llm = get_llm(temperature=0.0)
        # 의도(intent)에 따른 적응형 프롬프트 및 양식 선택 (P1 / Section 8)
        cur_system = SYNTH_SYSTEM
        cur_fewshot = SYNTH_FEWSHOT
        if intent == "FOLLOWUP_QUESTION":
            cur_system = SYNTH_FOLLOWUP_SYSTEM
            cur_fewshot = SYNTH_FOLLOWUP_FEWSHOT
        elif intent == "FACT_CLARIFICATION":
            cur_system = SYNTH_FACT_CLARIFICATION_SYSTEM
            cur_fewshot = ""
        elif intent == "DOCUMENT_REQUEST":
            cur_system = SYNTH_DOCUMENT_SYSTEM
            cur_fewshot = ""

        # 등록 증거 및 쟁점 목록 프롬프트 주입
        cur_system = (
            f"{cur_system}\n\n"
            f"[등록된 사건 증거 및 확정 사실 브리핑]\n{briefing_text}\n\n"
            f"[검토 대상 핵심 법률 쟁점 목록]\n{issues_text}\n\n"
            f"[중요 작성 원칙]\n"
            f"- 입증된 사실을 기술할 때는 [E01]과 같은 단순 라벨 대신 사용자가 등록한 정확한 파일명 그대로 `[파일명]` (예: `[E01_주택임대차계약서.txt]`)을 인용하세요.\n"
            f"- 쟁점별 법률 분석에서는 위 [검토 대상 핵심 법률 쟁점 목록]의 각 항목을 독립적으로 분석하세요."
        )

        prompt = SYNTH_PROMPT.format(
            system=cur_system,
            chat_brief=chat_brief,
            question=question or "(질문 없음)",
            findings=findings,
            fewshot=cur_fewshot,
        )
        resp = llm.invoke(prompt)
        summary = (getattr(resp, "content", str(resp)) or "").strip()
    except Exception as e:
        logger.exception("[SYN] LLM 생성 실패, 원문만 반환")
        summary = "종합 답변 생성 중 오류가 발생했습니다. 아래 카테고리별 답변을 참고해 주세요."

    summary = clean_markdown_formatting(summary)
    # P0-4 & P1: 원시 에이전트 초안(render_originals) 중복 첨부를 배제하고 정제된 5단계 종합의견서만 고객용 초안으로 전달
    final_text = summary
    return messages + [AIMessage(content=final_text)]
