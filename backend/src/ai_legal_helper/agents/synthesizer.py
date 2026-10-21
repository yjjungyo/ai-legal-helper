# -*- coding: utf-8 -*-
from typing import Dict, List
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
- [3. 쟁점별 법률 분석]에서는 각 주요 쟁점별로 다음 5가지 요소를 빠짐없이 구조화하여 분석하세요:
  1) 적용 법률요건: 관련 법령 조문 및 판례가 요구하는 법률적 성립 요건
  2) 사건 사실과의 연결: 의뢰인의 진술 및 확보된 사실이 위 요건에 부합하는지 여부
  3) 관련 법령 및 증거: 직접적인 근거가 되는 법조문 `(법령명 제O조)` 및 증거 자료 `(파일명.pdf, p.페이지)`
  4) 법률적 판단: 권리 발생, 소멸, 대항력 등 구체적인 법률 효과
  5) 남아 있는 불확실성: 상대방의 예상 항변, 추가 입증 필요 사실 등 법적 위험
- 세부 항목은 번호(1., 2., 3.) 또는 일반 불릿(- )으로 정돈하여 작성하고, 중요한 핵심 단어에는 **볼드** 강조를 적절히 사용하세요.
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
def synthesize(messages: List[AnyMessage], results: Dict[str, str]) -> List[AnyMessage]:
    from ai_legal_helper.utils.text_formatter import clean_markdown_formatting

    if not results:
        final = "관련 카테고리에서 유의미한 답변을 생성하지 못했습니다. 질문을 구체화해 주세요."
        logger.debug("[SYN] empty results -> fallback")
        return messages + [AIMessage(content=final)]

    chat_brief = _brief_history(messages)
    question = _extract_last_question(messages)
    findings = _format_findings(results, per_cat_limit=2400)

    try:
        llm = get_llm(temperature=0.0)
        prompt = SYNTH_PROMPT.format(
            system=SYNTH_SYSTEM,
            chat_brief=chat_brief,
            question=question or "(질문 없음)",
            findings=findings,
            fewshot=SYNTH_FEWSHOT,
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
