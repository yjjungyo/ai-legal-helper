# -*- coding: utf-8 -*-
from typing import List
import json
import re

from langchain_core.prompts import PromptTemplate
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

LLM_REWRITE_PROMPT = PromptTemplate.from_template(
    """당신은 한국 법률 **{category}** 분야 검색 전문가입니다.
다음 사용자 질문을 해당 분야의 핵심 **조문/법률용어 중심**으로 간결하게 보강하세요.

[출력]
- **JSON 한줄만**: {{"terms": ["키워드","키워드", ...]}}
- 2~3개. 중복/일반적인 말끝 조사 제외, 한국어 위주, 법조문 번호 허용(예: "민법 제47조")

[질문]
{question}

# FEW-SHOT
입력: (민법) "연대보증인데 주채무자 도피, 제 책임 범위?"
출력: {{"terms":["연대보증","연대채무","보증채무"]}}

입력: (형법) "사기죄로 고발, 준비할 것"
출력: {{"terms":["사기죄","고소","고발"]}}

입력: ({category}) "{question}"
출력:
"""
)

def _parse_terms(text: str) -> List[str]:
    if not text:
        return []
    i, j = text.find("{"), text.rfind("}")
    if i == -1 or j == -1 or j <= i:
        return []
    try:
        data = json.loads(text[i:j+1])
        terms = data.get("terms") or []
        return [t.strip() for t in terms if isinstance(t, str) and t.strip()]
    except Exception:
        return []

def _cheap_fallback_terms(q: str, k: int = 3) -> List[str]:
    q = (q or "").strip()
    tokens = re.findall(r"[가-힣0-9A-Za-z]{2,}", q)
    seen, out = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= k:
            break
    return out

@trace
def rewrite_query(question: str, category_ko: str, *, max_terms: int = 3) -> str:
    q = (question or "").strip().replace("\n", " ")

    terms: List[str] = []
    try:
        llm = get_llm(temperature=0.0)
        prompt = LLM_REWRITE_PROMPT.format(category=category_ko, question=q)
        raw = llm.invoke(prompt)
        text = (getattr(raw, "content", str(raw)) or "").strip()
        terms = _parse_terms(text)[:max_terms]
        logger.debug(f"[REWRITE] llm_terms={terms}")
    except Exception as e:
        logger.warning(f"[REWRITE] LLM 실패: {e}")

    if not terms:
        fb = _cheap_fallback_terms(q, k=min(3, max_terms))
        logger.debug(f"[REWRITE] fallback_terms={fb}")
        terms = fb

    final = q
    if terms:
        final = f"{q}\n키워드: {', '.join(terms)}"
    logger.debug(f"[REWRITE] final_len={len(final)} final=[{final}]")
    return final
