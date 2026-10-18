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

SYNTH_SYSTEM = """당신은 에이아이로 법률 전문가입니다.
- 사용자의 질문과 카테고리별 에이전트 답변을 바탕으로, 하나의 통합된 최종 법률 의견서를 한국어로 작성하세요.
- 사고 과정(Chain-of-Thought)을 출력하지 마세요.
- 마크다운 특수문자(#, ##, ###, **, *, ---, > 등)를 절대 사용하지 마세요. 사용자 화면에 마크다운 기호가 그대로 노출되므로 플레인 텍스트 서식만 사용해야 합니다.
- 섹션 제목은 [1. 핵심 결론], [2. 법적 근거 요약], [3. 실무상 대응 방안 및 입증사항], [4. 주의사항]과 같이 대괄호와 번호 체계를 사용하세요.
- 세부 항목은 번호(1., 2., 3.) 또는 일반 불릿(- )으로 정돈하여 작성하세요.
- 중복 내용은 합치고 모순되는 부분은 조정하거나 '쟁점'으로 분리하세요.
- 법률 명칭/조문/판례 등 참고한 법령 출처는 반드시 [카테고리별 에이전트 답변]에 실제로 등장한 '(파일명.pdf, p.페이지)' 또는 '[GRAPH:...]' 출처만 그대로 인용하세요.
- 에이전트 답변에 출처 파일명이나 판례 사건번호가 없는데 임의로 파일명, 사건번호, 조문을 지어내어 기재하는 것은 엄격히 금지됩니다.
"""

SYNTH_FEWSHOT = """
[좋은 법률 종합 답변 작성 양식]
[1. 핵심 결론]
질문에 대한 명확한 법적 판단 및 핵심 결론을 제시합니다.

[2. 법적 근거 요약]
- 근거 조문 및 법률 원칙 요약
- 출처: (실제검색된파일명.pdf, p.페이지)

[3. 실무상 대응 방안 및 입증사항]
1) 사실관계 확인 및 증거 확보
2) 내용증명 발송 또는 절차 진행

[4. 주의사항 및 한계]
- 본 답변은 제공된 자료를 바탕으로 한 일반 법률정보이며 구체적 사실관계에 따라 결론이 달라질 수 있습니다.
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
위 정보를 종합하여, 마크다운 기호(#, **, ---, >) 없는 깔끔한 플레인 텍스트 [최종 법률 의견서]를 작성하세요.
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
    originals = clean_markdown_formatting(_render_originals(results))
    final_text = f"{summary}\n\n========================================\n\n{originals}"
    return messages + [AIMessage(content=final_text)]
