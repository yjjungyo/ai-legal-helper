# -*- coding: utf-8 -*-
"""
모듈명: query_rewrite.py

[모듈 개요]
사용자의 자연어 질문과 대화 맥락(resolved_query)을 바탕으로, 법률 분야별 핵심 법조문 및
전문 법률 용어 중심의 검색 키워드를 생성하여 RAG 검색 적중률을 극대화하는 모듈이다.

[주요 기능]
1. `rewrite_query`:
   - 단문 후속 질의("이제 뭘 해야 하죠?", "언제 신청하나요?") 발생 시, 문맥이 복원된 `resolved_query`를
     참조하여 정확한 조문/법률 키워드를 도출
   - 원문 사용자 질문(`question`)을 보존하면서 핵심 키워드를 보강
2. Zero-shot / Few-shot 프롬프트 기반의 고속 키워드 추출
3. LLM 장애 시 결정론적 명사 토큰 기반의 Fallback 지원

[주의사항]
- 원문 사용자 질문을 왜곡하지 않으며, 추가된 키워드는 검색용 보조 정보로만 활용한다.
"""

from typing import List, Optional
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
    """LLM 출력 텍스트에서 JSON 블록을 찾아 키워드 리스트를 파싱한다."""
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
    """LLM 호출 불가 시 질문 문자열에서 2글자 이상 명사 어근을 추출하는 폴백."""
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
def rewrite_query(
    question: str,
    category_ko: str,
    *,
    resolved_query: Optional[str] = None,
    max_terms: int = 3,
) -> str:
    """사용자의 질문을 법률 조문 및 전문 용어 중심의 검색 키워드로 보강한다.

    후속 질의의 경우 문맥이 복원된 resolved_query를 우선 활용하여,
    단문 질문('그다음은요?', '언제 신청하나요?')에서도 정확한 법률 검색어를 추출한다.
    원래 사용자의 원문 질문 형태를 보존하면서 키워드를 덧붙인다.

    Args:
        question: 사용자의 원문 질문
        category_ko: 법률 카테고리 한국어 명칭 (예: '민법')
        resolved_query: 이전 대화 맥락이 연결되어 구체화된 내부 질의문 (선택)
        max_terms: 추출할 최대 키워드 수 (기본값: 3)

    Returns:
        str: 키워드가 보강된 최종 검색 질의 문자열
    """
    effective_q = (resolved_query or question or "").strip().replace("\n", " ")
    user_orig = (question or "").strip().replace("\n", " ")

    terms: List[str] = []
    try:
        llm = get_llm(temperature=0.0)
        prompt = LLM_REWRITE_PROMPT.format(category=category_ko, question=effective_q)
        raw = llm.invoke(prompt)
        text = (getattr(raw, "content", str(raw)) or "").strip()
        terms = _parse_terms(text)[:max_terms]
        logger.debug(f"[질의어 확장] LLM 도출 법률 키워드={terms} (질의='{effective_q[:40]}...')")
    except Exception as e:
        logger.warning(f"[REWRITE] LLM 실패: {e}")

    if not terms:
        fb = _cheap_fallback_terms(effective_q, k=min(3, max_terms))
        logger.debug(f"[질의어 확장] 규칙 기반 폴백 키워드={fb}")
        terms = fb

    final = user_orig
    if terms:
        final = f"{user_orig}\n키워드: {', '.join(terms)}"
    logger.debug(f"[질의어 확장 완료] 최종 길이={len(final)}자, 확장 질의=[{final}]")
    return final
