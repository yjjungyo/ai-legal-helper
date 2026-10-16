# -*- coding: utf-8 -*-
import json
from langchain_core.prompts import PromptTemplate
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.agents.constants import CATEGORIES

logger = get_logger(__name__)

ROUTER_PROMPT = PromptTemplate.from_template(
    """당신은 한국 법률 질의를 **카테고리**로 분류하는 라우터입니다.
가능한 카테고리: {categories}

규칙:
- 반드시 위 목록 중 하나 이상을 반환하세요.
- 애매하면 2~3개를 고르세요.
- JSON 한 줄만 출력하세요. 예: {{"categories": ["민법","부동산"], "reason": "임대차보증금 분쟁이므로 민법/부동산"}}

[질문]
{question}

# FEW-SHOT
입력: "퇴직금 산정 기준이 궁금해요"
출력: {{"categories": ["노동"], "reason": "근로기준법 노동법"}}

입력: "법인 간 주식 인수권 분쟁"
출력: {{"categories": ["상법","민법"], "reason": "회사/계약 분쟁"}}

입력: "{question}"
출력:
"""
)

@trace
def route_categories(question: str) -> list[str]:
    llm = get_llm(temperature=0.0)
    prompt = ROUTER_PROMPT.format(categories=", ".join(CATEGORIES), question=question)
    res = llm.invoke(prompt)
    text = (getattr(res, "content", str(res)) or "").strip()
    try:
        i, j = text.find("{"), text.rfind("}")
        if i != -1 and j != -1:
            text = text[i:j+1]
        data = json.loads(text)
        out = [c for c in data.get("categories", []) if c in CATEGORIES]
        if out:
            return out
    except Exception as e:
        logger.warning(f"[ROUTER] parse failed: {e}")
    return ["민법"]
