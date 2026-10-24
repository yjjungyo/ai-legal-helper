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
- 사용자의 질문과 카테고리별 에이전트 답변을 바탕으로, 실제 의뢰인에게 실질적인 도움이 되는 전문적인 최종 법률 의견서를 한국어로 작성하세요.
- 사고 과정(Chain-of-Thought)을 출력하지 마세요.
- 섹션 제목은 반드시 다음 5단계 표준 구조 체계를 사용하세요:
  [1. 핵심 결론]
  [2. 사건 사실관계 및 증거]
  [3. 쟁점별 법률 분석]
  [4. 우선순위별 다음 행동]
  [5. 추가 확인사항]
- [2. 사건 사실관계 및 증거]에서는 사실 상태를 엄격히 구분하여 작성하세요:
  1) [확인된 객관적 사실]: 실제 등록된 증거 자료(파일명.pdf, p.페이지)로 확인된 사실만 명시
  2) [사용자 진술 사실]: 독립적 증거가 확인되지 않은 의뢰인의 진술은 "사용자 진술에 따르면...", "의뢰인께서 말씀하신 정황에 비추어..."로 명시
  3) [확보 필요 자료]: 상대방의 항변을 방어하거나 입증을 위해 추가 확보가 필요한 서류 목록 명시
  4) 주의: 실제 등록되지 않은 가상의 증거 번호(예: '증거 1', '증거 2', '증거 7호' 등)를 절대 임의로 붙이지 마세요.
- [3. 쟁점별 법률 분석]에서는 각 주요 쟁점별로 다음 5가지 요소를 빠짐없이 구조화하여 분석하세요:
  1) 적용 법률요건: 관련 법령 조문 및 판례가 요구하는 법률적 성립 요건
  2) 사건 사실과의 연결: 의뢰인의 진술 및 확보된 사실이 위 요건에 부합하는지 여부
  3) 관련 법령 및 증거: 직접적인 근거가 되는 법조문 `(법령명 제O조)` 및 증거 자료 `(파일명.pdf, p.페이지)`
  4) 법률적 판단: 권리 발생, 소멸, 대항력 등 구체적인 법률 효과
  5) 남아 있는 불확실성: 상대방의 예상 항변, 추가 입증 필요 사실 등 법적 위험
- 세부 항목은 번호(1., 2., 3.) 또는 일반 불릿(- )으로 정돈하여 작성하고, 중요한 핵심 단어에는 **볼드** 강조를 적절히 사용하세요.
- 복합 쟁점 심층 분석 원칙 (Section 11, P1-01):
  1) 계약 종료일 산정: 당초 약정 만료일과 해지 통고 도달일(주택임대차보호법 제6조의2 제2항에 따른 3개월 경과 효력 등)을 상호 비교하여 정확한 보증금 반환 채무의 이행기를 확정하세요.
  2) 대항력 및 가압류 선후관계: 임차인의 대항요건(주택인도+전입신고 익일 0시) 및 확정일자 부여 시점과 가압류 기입등기 접수일자를 일자 단위로 대조하여 우선순위를 판단하세요.
  3) 경매 및 배당위험: 임차인의 대항력 유지(배당요구 시와 미요구 시 낙찰자 인수 관계)와 실제 배당 순위(소액임차보증금 최우선변제, 당해세, 선순위 근저당, 가압류 안분배당 등)의 법률효과를 명확히 구분하여 설명하세요.
- 중복 내용은 합치고 모순되는 부분은 조정하거나 '쟁점'으로 분리하세요.
- 법률 명칭/조문/판례 등 참고한 법령 출처는 '(법령명 제O조)' 형태(예: `(주택임대차보호법 제6조의2)`, `(근로기준법 제36조)`, `(민법 제393조)`)로 인용하고, 사건 증거는 '(파일명.pdf, p.페이지)' 형태로 인용하세요.
- 에이전트 답변에 출처 파일명이나 판례 사건번호가 없는데 임의로 가상 파일명, 사건번호, 조문을 지어내어 기재하는 것은 엄격히 금지됩니다.
"""

SYNTH_FEWSHOT = """
[좋은 법률 종합 답변 5단계 표준 양식 예시]
[1. 핵심 결론]
- 의뢰인의 핵심 질문에 대한 명확한 법률적 결론과 판단 요지를 3줄 이내로 명쾌하게 제시합니다.

[2. 사건 사실관계 및 증거]
- 확인된 핵심 사실: 계약 또는 분쟁의 발생 경위, 주요 법률행위 일자, 당사자 간 의사표시 도달 여부 등
- 관련 증거 자료: 계약서 원본, 통지 내역(문자, 내용증명 등), 금융거래 증빙 등 (파일명.pdf, p.페이지)

[3. 쟁점별 법률 분석]
■ 쟁점 1: 핵심 법률 권리의 발생 요건 충족 여부
- 적용 법률요건: 관련 법령 조문 및 판례상 요구되는 법률적 성립 요건
- 사건 사실과의 연결: 의뢰인의 진술 및 확보된 사실관계가 위 요건에 부합하는지 여부
- 관련 법령 및 증거: (관련법령명 제O조), (증거자료명.pdf, p.페이지)
- 법률적 판단: 권리 발생, 소멸, 항변사유 등 구체적인 법률 효과
- 남아 있는 불확실성: 상대방의 예상 항변, 추가 입증 필요 사실 등 법적 위험

[4. 우선순위별 다음 행동]
1) 1단계: 핵심 사실관계 및 의사표시 도달을 증명할 수 있는 객관적 증빙(내용증명 등) 확보
2) 2단계: 합의 또는 조정 등 상호 원만한 분쟁 해결 절차 모색
3) 3단계: 불이행 시 지급명령, 본안 소송 또는 보전처분 등 법적 구제 절차 진행

[5. 추가 확인사항]
- 소송 및 분쟁 해결 시 주의해야 할 입증 책임 및 법원/기관의 판단 기준을 명확히 안내합니다.
- 본 답변은 제공된 자료를 바탕으로 한 법률정보이며 구체적 사실관계에 따라 결론이 달라질 수 있습니다.
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
        logger.debug("[SYN] empty results -> fallback")
        return messages + [AIMessage(content=final)]

    chat_brief = _brief_history(messages)
    question = _extract_last_question(messages)
    findings = _format_findings(results, per_cat_limit=2400)

    # 사건 증거 브리핑 텍스트 구성 (P0-01, P0-02, P0-07)
    briefing_text = "(등록된 사건 증거 정보 없음)"
    if case_evidence_briefing:
        b_summary = case_evidence_briefing.get("formatted_summary", "")
        if len(b_summary) > 4000:
            briefing_text = b_summary[:4000] + "\n...(후략)"
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
