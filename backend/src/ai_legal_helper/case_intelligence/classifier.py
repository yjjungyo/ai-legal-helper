# -*- coding: utf-8 -*-
"""
모듈명: classifier.py

[모듈 개요]
사건(Case)의 제목(Title)과 설명(Description)을 바탕으로 법률 분쟁 유형을 자동 추론·분류하는 모듈이다.
사용자가 사건 유형을 수동으로 선택하지 않거나 "AI 자동 분류"를 지정했을 때,
LLM 기반의 정밀 분류와 휴리스틱 키워드 매칭 폴백을 통해 적합한 사건 유형을 도출한다.
"""

from typing import Optional
import json
import re
from langchain_core.prompts import PromptTemplate
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 표준 권장 사건 유형 목록
STANDARD_CASE_TYPES = [
    "주택임대차 (보증금/원상복구/계약갱신)",
    "상가임대차 (권리금/임대료 분쟁)",
    "대여금 및 채권추심 (차용증/미수금)",
    "손해배상 청구 (교통사고/불법행위/채무불이행)",
    "근로 및 임금체불 (퇴직금/부당해고/산재)",
    "형사 사건 (사기/횡령/폭행/고소)",
    "가사 분쟁 (이혼/재산분할/상속/유류분)",
    "상사 및 기업 (계약서/주주분쟁/공정거래)",
    "행정 및 조세 (영업정지/처분취소/과징금)",
    "일반 민사 분쟁",
]

CASE_CLASSIFICATION_PROMPT = PromptTemplate.from_template(
    """당신은 한국 법률 사건의 제목과 내용을 분석하여 가장 적합한 법률 분쟁 유형을 분류하는 AI 어시스턴트입니다.

가능한 표준 분류 목록:
1. 주택임대차 (보증금/원상복구/계약갱신)
2. 상가임대차 (권리금/임대료 분쟁)
3. 대여금 및 채권추심 (차용증/미수금)
4. 손해배상 청구 (교통사고/불법행위/채무불이행)
5. 근로 및 임금체불 (퇴직금/부당해고/산재)
6. 형사 사건 (사기/횡령/폭행/고소)
7. 가사 분쟁 (이혼/재산분할/상속/유류분)
8. 상사 및 기업 (계약서/주주분쟁/공정거래)
9. 행정 및 조세 (영업정지/처분취소/과징금)
10. 일반 민사 분쟁

규칙:
- 사건 제목과 사건 설명을 종합하여 가장 적합한 유형 1개를 표준 분류 목록 중에서 선택하세요.
- JSON 단일 객체 형식으로만 응답하세요: {{"case_type": "선택한 유형", "reason": "분류 이유"}}

[사건 정보]
사건 제목: {title}
사건 설명: {description}

응답:
"""
)


def _heuristic_fallback(text: str) -> str:
    """LLM 호출이 불가능하거나 실패했을 때 텍스트 키워드 기반으로 사건 유형을 추론한다.

    Args:
        text: 사건 제목 및 설명의 결합 문자열.

    Returns:
        추론된 사건 유형 문자열.
    """
    t = text.lower()

    if any(k in t for k in ["상가", "권리금", "영업용 건물"]):
        return "상가임대차 (권리금/임대료 분쟁)"
    if any(k in t for k in ["보증금", "임대차", "전세", "월세", "임차권", "원상복구", "명도", "묵시적"]):
        return "주택임대차 (보증금/원상복구/계약갱신)"
    if any(k in t for k in ["퇴직금", "해고", "임금", "근로", "야간수당", "산재", "노동"]):
        return "근로 및 임금체불 (퇴직금/부당해고/산재)"
    if any(k in t for k in ["사기", "횡령", "배임", "폭행", "상해", "고소", "피의", "성범죄", "음주운전", "모욕"]):
        return "형사 사건 (사기/횡령/폭행/고소)"
    if any(k in t for k in ["이혼", "재산분할", "위자료", "양육권", "상속", "유류분", "친권"]):
        return "가사 분쟁 (이혼/재산분할/상속/유류분)"
    if any(k in t for k in ["차용", "대여금", "빌려", "미수금", "채권", "추심", "각서"]):
        return "대여금 및 채권추심 (차용증/미수금)"
    if any(k in t for k in ["손해배상", "교통사고", "하자보수", "불법행위", "의료과실"]):
        return "손해배상 청구 (교통사고/불법행위/채무불이행)"
    if any(k in t for k in ["주주", "정관", "법인", "영업비밀", "독점", "상합", "가맹"]):
        return "상사 및 기업 (계약서/주주분쟁/공정거래)"
    if any(k in t for k in ["영업정지", "과징금", "처분취소", "세무", "국세", "행정심판"]):
        return "행정 및 조세 (영업정지/처분취소/과징금)"

    return "일반 민사 분쟁"


@trace
def classify_case_type(title: str, description: Optional[str] = None) -> str:
    """사건 제목과 설명을 바탕으로 법률 사건 유형을 분류한다.

    사용자가 유형을 직접 고르지 않았거나 'AI 자동 분류'를 요청한 경우 호출된다.
    LLM을 우선 사용하며, 실패 시 키워드 매칭으로 안전하게 폴백한다.

    Args:
        title: 사건 제목.
        description: 사건 개요 설명 (선택 사항).

    Returns:
        str: 자동 추론된 사건 분류 명칭.
    """
    clean_title = (title or "").strip()
    clean_desc = (description or "").strip()
    combined_text = f"{clean_title} {clean_desc}".strip()

    if not combined_text:
        return "일반 민사 분쟁"

    try:
        llm = get_llm(temperature=0.0)
        prompt = CASE_CLASSIFICATION_PROMPT.format(
            title=clean_title or "(제목 없음)",
            description=clean_desc or "(설명 없음)"
        )
        res = llm.invoke(prompt)
        content = (getattr(res, "content", str(res)) or "").strip()

        # JSON 파싱
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            predicted_type = data.get("case_type")
            if predicted_type and isinstance(predicted_type, str):
                cleaned_predicted = predicted_type.strip()
                # 표준 분류 목록과의 정합성 검사
                for std in STANDARD_CASE_TYPES:
                    if cleaned_predicted in std or std in cleaned_predicted:
                        return std
                return cleaned_predicted
    except Exception as e:
        logger.warning(f"[CASE_CLASSIFIER] LLM classification failed, falling back to heuristic: {e}")

    # 휴리스틱 폴백
    return _heuristic_fallback(combined_text)

