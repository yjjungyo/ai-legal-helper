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
    lines: List[str] = ["### 참고 : 카테고리별 전문 답변"]
    for cat, text in results.items():
        lines.append(f"\n#### {cat} 분야 전문가(Agent) 답변")
        lines.append(text or "(답변 없음)")
    return "\n".join(lines)

SYNTH_SYSTEM = """당신은 에이아이로 법률 전문가입니다.
- 사용자의 질문과 카테고리별 에이전트 답변을 바탕으로, 하나의 통합된 최종 답변을 한국어로 작성하세요.
- 사고 과정(Chain-of-Thought)을 출력하지 마세요. 최종 결론/근거 요약/주의사항을 명확하게 제시하세요.
- 중복 내용은 합치고 모순되는 부분은 조정하거나 '쟁점'으로 분리하세요.
- 법률 명칭/조문/판례 등 다른 에이전트가 찾은 출처(카테고리/문서/페이지 등)는 반드시 표기하세요.
- 출력은 Markdown 형식으로 간결하고 구조화(번호/불릿/소제목)해 주세요.
"""

SYNTH_FEWSHOT = """
예시)
[질문] 전세보증금 반환 절차가 궁금합니다.
[에이전트별 답변 요약]
- 민법: 임대차종료/퇴거와 내용증명/소송 절차.
- 행정: 주택도시보증 공사 보증 제도.
- 조세: 원천징수/소득세 이슈 없음.

[좋은 종합 답변의 특징]
1) 핵심 결론: 반환 요구 절차 (증거 확보 -> 내용증명 -> 소송/집행)
2) 선택지/분기: 보증보험 가입한 경로, 미가입 경로
3) 주의: 임대차기간/우선변제권/대항력 등 체크리스트
4) 참고: 민법 임대차규정, 관련제도 링크(가능시)
"""

SYNTH_PROMPT = PromptTemplate.from_template(
    """{system}

# 대화 요약
{chat_brief}

# 사용자 질문
{question}

# 카테고리별 에이전트 답변 (요약 입력)
{findings}

{fewshot}

# 지시
위 정보를 종합하여, 하나의 통일된 **최종 답변**을 작성하세요.
- 불확실한 부분은 가정/한계를 명시하세요.
- 핵심 조치/절차/기한/요건을 명확히 하세요.
- 마지막에 간단한 면책 문구를 포함하세요.
"""
)

@trace
def synthesize(messages: List[AnyMessage], results: Dict[str, str]) -> List[AnyMessage]:
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

    originals = _render_originals(results)
    final_md = f"{summary}\n\n---\n{originals}"

    return messages + [AIMessage(content=final_md)]
