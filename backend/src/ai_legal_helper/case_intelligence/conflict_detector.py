# -*- coding: utf-8 -*-
"""
모듈명: conflict_detector.py

[모듈 개요]
다중 증거 문서 환경에서 추출된 사실 주장(EvidenceClaim)과 기존 사건 사실관계(Fact) 간의
일치(CONSISTENT), 별개 맥락(DIFFERENT_CONTEXT), 추가 경위 확인 필요(POTENTIAL_CONFLICT),
논리적 모순(CONTRADICTION)을 판별하는 3단계 증거 상충 탐지 엔진(Evidence Conflict Detection Engine)이다.

[핵심 설계 원칙]
1. 서로 다른 정보는 모순이 아니다: 동일한 대상(subject)과 동일한 속성(predicate) 및
   비교 가능한 시점(temporal context)에 대해 동시에 참일 수 없는 진술만 모순(CONTRADICTION)으로 판정한다.
2. 특정 문자열이나 특정 숫자에 대한 하드코딩을 일체 금지한다:
   한국어 수사 체계(일~구, 십·백·천·만·억·조)의 자릿수 연산 알고리즘과 표준 날짜 정규화,
   문법적 극성(긍정/부정) 분석, 그리고 선택적 LLM 의미 검증을 결합한다.
3. 3단계 파이프라인:
   - Stage 1 (Comparability Gate): 문서 고유 메타데이터(DOC_INFO / DOCUMENT_LOCAL) 분리 및
     서로 다른 값 차원(순수 날짜 진술 vs 순수 금액 진술 등)의 교차 비교 원천 차단.
   - Stage 2 (Normalized Rule Verification): 수학적으로 정규화된 금액(KRW 정수)·날짜(ISO YYYY-MM-DD)가
     일치하면 표현 방식(예: 한글 수사 vs 아라비아 숫자)이 달라도 즉시 CONSISTENT로 판정.
   - Stage 3 (Selective LLM Semantic Verification): 동일 대상·동일 차원에서 수치 불일치 또는
     극성 반전이 감지된 후보에 한해 두 원문과 출처 문서 맥락을 대조하여 최종 판정.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, Tuple

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai_legal_helper.database.models import (
    EvidenceClaim,
    EvidenceDocument,
    EvidenceLink,
    Fact,
)
from ai_legal_helper.llm.gateway import get_llm

logger = logging.getLogger(__name__)

ConflictStatusType = Literal[
    "CONSISTENT",
    "CONTRADICTION",
    "POTENTIAL_CONFLICT",
    "DIFFERENT_CONTEXT",
    "INSUFFICIENT_INFORMATION",
]

# 한국어 수사 자릿수 연산을 위한 언어 체계 상수 (특정 금액 하드코딩이 아닌 한국어 기수법 정의)
_KOR_DIGIT_MAP: Dict[str, int] = {
    "영": 0, "공": 0,
    "일": 1, "하나": 1,
    "이": 2, "둘": 2,
    "삼": 3, "셋": 3,
    "사": 4, "넷": 4,
    "오": 5, "다섯": 5,
    "육": 6, "륙": 6, "여섯": 6,
    "칠": 7, "일곱": 7,
    "팔": 8, "여덟": 8,
    "구": 9, "아홉": 9,
}
_SMALL_UNIT_MAP: Dict[str, int] = {
    "십": 10,
    "백": 100,
    "천": 1_000,
}
_LARGE_UNIT_MAP: Dict[str, int] = {
    "만": 10_000,
    "억": 100_000_000,
    "조": 1_000_000_000_000,
}

# 금액 표현 추출용 정규식: 아라비아 숫자/쉼표/소수점 + 한글 수사/단위 + 통화 접미사('원') 또는 큰 단위('만원', '억원' 등)
# 접두사 '금(金)'은 앞글자가 한글/영문/숫자가 아닌 독립 어절일 때만 매칭하여 '보증금', '계약금' 등의 어미 '금'이 잘리지 않도록 한다.
_AMOUNT_EXPR_RE = re.compile(
    r"(?:(?<![가-힣A-Za-z0-9])금\s+)?"
    r"((?:[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?|[일이삼사오육륙칠팔구십백천만억조\s])+)"
    r"\s*(원|만원|만\s*원|억원|억\s*원|천만원|천만\s*원|백만원|백만\s*원)",
)

# 날짜 표현 추출용 정규식 (YYYY년 M월 D일, YYYY-MM-DD, YYYY. M. D.)
_DATE_FULL_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})\s*(?:년|[-./])\s*(\d{1,2})\s*(?:월|[-./])\s*(\d{1,2})\s*일?(?!\d)"
)

# 일반 한국어 조사 제거용 정규식
_JOSA_STRIP_RE = re.compile(
    r"(으로부터|에서부터|에게서|으로서|으로써|이라도|이라고|이라며|이라서|"
    r"에게는|까지는|부터는|으로는|로서는|에서는|이라는|트로부터|"
    r"에게|에서|으로|로써|로서|까지|부터|보다|처럼|마다|조차|마저|밖에|대로|"
    r"은|는|이|가|을|를|의|에|로|와|과|도|만)$"
)

# 문법적 기능어·일반 서술 보조어 (주제어 토큰 비교 시 노이즈 제거용)
_FUNCTION_WORDS: Set[str] = {
    "문서", "제목", "내용", "사실", "주장", "경우", "관련", "특정", "부분",
    "이다", "있다", "없다", "한다", "하였다", "되었다", "대한", "위해", "따라",
    "통해", "대해", "맞춰", "재차", "확인", "해당", "기준", "일정", "가능",
}

# 한국어 문법상 부정 극성(Negation) 마커
_NEGATION_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"지\s*않"),
    re.compile(r"지\s*못"),
    re.compile(r"안\s+했|안\s+하"),
    re.compile(r"없었|없다|없음|없으며"),
    re.compile(r"아니다|아니었|아님"),
    re.compile(r"(?:^|\s)미[가-힣]{2,}"),  # 미지급, 미반환, 미이행 등 접두사 '미-'
    re.compile(r"거절|거부|부인|불응"),
)


class StructuredFactSlots(BaseModel):
    """문장에서 추출·정규화된 사실 비교 슬롯 모델."""
    statement: str = Field(description="원본 진술 문장")
    claim_type: str = Field(default="GENERAL", description="표준 분류 코드")
    scope: Literal["DOCUMENT_LOCAL", "CASE_GLOBAL"] = Field(
        default="CASE_GLOBAL",
        description="DOCUMENT_LOCAL(개별 문서 자체의 제목·형식 정보) vs CASE_GLOBAL(사건 실체 사실)",
    )
    subject_key: Optional[str] = Field(default=None, description="비교 대상 주체/객체")
    predicate_key: Optional[str] = Field(default=None, description="비교 대상 속성/행위")
    value_dimension: Literal["AMOUNT", "DATE", "AMOUNT_AND_DATE", "TEXT"] = Field(
        default="TEXT",
        description="진술이 포함하는 수치 값의 차원",
    )
    normalized_amounts: List[int] = Field(default_factory=list, description="원(KRW) 단위로 정규화된 금액 정수 목록")
    normalized_dates: List[str] = Field(default_factory=list, description="YYYY-MM-DD로 정규화된 날짜 목록")
    polarity: Literal["AFFIRMATIVE", "NEGATIVE"] = Field(
        default="AFFIRMATIVE",
        description="서술부의 긍정/부정 극성",
    )
    content_tokens: List[str] = Field(default_factory=list, description="조사 제거 내용어 토큰 목록")
    evidence_id: Optional[str] = Field(default=None, description="출처 증거 문서 ID")
    document_name: Optional[str] = Field(default=None, description="출처 증거 문서 파일명")


class ConflictDecision(BaseModel):
    """단일 Claim과 기존 Fact 간의 상충·일치 비교 판정 결과 모델."""
    claim_id: Optional[str] = Field(default=None, description="검토 대상 EvidenceClaim ID")
    target_fact_id: str = Field(description="비교 대상 Fact ID")
    status: ConflictStatusType = Field(description="비교 판정 상태")
    reason_code: str = Field(description="판정 사유 표준 코드")
    explanation: str = Field(description="사용자 및 감사 로그용 판정 근거 설명")
    confidence: float = Field(default=0.9, description="판정 신뢰도 (0.0 ~ 1.0)")
    source_span_ids: List[str] = Field(default_factory=list, description="근거 원문 Span ID 목록")


class _LLMConflictVerificationSchema(BaseModel):
    """선택적 LLM 2차 의미 검증 출력 스키마."""
    status: Literal[
        "CONSISTENT",
        "CONTRADICTION",
        "POTENTIAL_CONFLICT",
        "DIFFERENT_CONTEXT",
        "INSUFFICIENT_INFORMATION",
    ] = Field(description="두 진술의 논리적 관계 판정")
    reason_code: str = Field(description="판정 사유 코드 (예: SAME_AMOUNT_DIFFERENT_FORMAT, DIFFERENT_EVENT_DATE, RENEWAL_GAP, MUTUALLY_EXCLUSIVE_AMOUNT, MUTUALLY_EXCLUSIVE_ACTION)")
    explanation: str = Field(description="판정 근거에 대한 한국어 설명 (1~2문장)")
    confidence: float = Field(default=0.85, description="판정 신뢰도 (0.0 ~ 1.0)")


def parse_korean_number_phrase(phrase: str) -> Optional[int]:
    """아라비아 숫자와 한글 수사·자릿수 단위가 혼합된 문자열을 정수로 변환한다.

    특정 금액 하드코딩 없이 한국어 기수법(십·백·천 소단위 및 만·억·조 대단위)의
    수학적 자릿수 누적 연산으로 임의의 금액 문자열을 파싱한다.

    Args:
        phrase: 금액 수치 부분 문자열 (예: '3억', '300,000,000', '오천만', '1억 5,000만').

    Returns:
        Optional[int]: 변환된 양의 정수. 유효한 수치가 없으면 None.
    """
    if not phrase:
        return None
    cleaned = phrase.replace(",", "").replace(" ", "").strip()
    if not cleaned:
        return None

    # 순수 아라비아 정수인 경우
    if cleaned.isdigit():
        val = int(cleaned)
        return val if val > 0 else None

    total = 0
    section = 0
    current_num = 0
    has_any_number = False

    i = 0
    n = len(cleaned)
    while i < n:
        ch = cleaned[i]
        if ch.isdigit():
            j = i
            while j < n and (cleaned[j].isdigit() or cleaned[j] == "."):
                j += 1
            num_str = cleaned[i:j]
            try:
                num_val = float(num_str) if "." in num_str else int(num_str)
            except ValueError:
                i = j
                continue
            current_num += num_val
            has_any_number = True
            i = j
            continue

        if ch in _KOR_DIGIT_MAP:
            current_num += _KOR_DIGIT_MAP[ch]
            has_any_number = True
        elif ch in _SMALL_UNIT_MAP:
            unit_val = _SMALL_UNIT_MAP[ch]
            factor = current_num if current_num > 0 else 1
            section += int(factor * unit_val)
            current_num = 0
            has_any_number = True
        elif ch in _LARGE_UNIT_MAP:
            large_val = _LARGE_UNIT_MAP[ch]
            section += current_num
            factor = section if section > 0 else 1
            total += int(factor * large_val)
            section = 0
            current_num = 0
            has_any_number = True
        i += 1

    result = int(total + section + current_num)
    return result if (has_any_number and result > 0) else None


def extract_normalized_amounts(text: str) -> List[int]:
    """문장 내 모든 금액 표현을 원(KRW) 단위 정수로 정규화하여 추출한다.

    Args:
        text: 분석 대상 한국어 문장.

    Returns:
        List[int]: 중복 제거된 원 단위 정수 목록.
    """
    if not text:
        return []

    amounts: List[int] = []
    for match in _AMOUNT_EXPR_RE.finditer(text):
        num_part = (match.group(1) or "").strip()
        suffix = (match.group(2) or "").replace(" ", "").strip()
        if not num_part:
            continue

        # 접미사에 단위(만원, 억원 등)가 포함되어 있고 num_part 끝에 중복 단위가 없는 경우 결합
        combined_phrase = num_part
        if suffix.startswith("천만") and not num_part.endswith("천만"):
            combined_phrase = f"{num_part}천만"
        elif suffix.startswith("백만") and not num_part.endswith("백만"):
            combined_phrase = f"{num_part}백만"
        elif suffix.startswith("만") and not num_part.endswith(("만", "억", "조")):
            combined_phrase = f"{num_part}만"
        elif suffix.startswith("억") and not num_part.endswith(("억", "조")):
            combined_phrase = f"{num_part}억"

        val = parse_korean_number_phrase(combined_phrase)
        if val is not None and val >= 100 and val not in amounts:
            amounts.append(val)

    return amounts


def extract_normalized_dates(text: str) -> List[str]:
    """문장 내 모든 날짜 표현을 표준 ISO 형식(YYYY-MM-DD)으로 정규화하여 추출한다.

    Args:
        text: 분석 대상 한국어 문장.

    Returns:
        List[str]: 중복 제거된 'YYYY-MM-DD' 문자열 목록.
    """
    if not text:
        return []

    dates: List[str] = []
    for m in _DATE_FULL_RE.finditer(text):
        yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            iso = f"{yyyy:04d}-{mm:02d}-{dd:02d}"
            if iso not in dates:
                dates.append(iso)
    return dates


def detect_polarity(text: str) -> Literal["AFFIRMATIVE", "NEGATIVE"]:
    """문장의 문법적 서술 극성(긍정/부정)을 판별한다."""
    if not text:
        return "AFFIRMATIVE"
    for pat in _NEGATION_PATTERNS:
        if pat.search(text):
            return "NEGATIVE"
    return "AFFIRMATIVE"


def extract_content_tokens(text: str) -> List[str]:
    """날짜·숫자·조사를 제외한 핵심 내용어(명사/어근) 토큰을 추출한다."""
    if not text:
        return []
    # 날짜와 금액 부분을 제거한 뒤 한글/영문 토큰 추출
    without_dates = _DATE_FULL_RE.sub(" ", text)
    without_amounts = _AMOUNT_EXPR_RE.sub(" ", without_dates)
    raw_tokens = re.findall(r"[가-힣A-Za-z]{2,}", without_amounts)
    tokens: List[str] = []
    for tok in raw_tokens:
        stem = _JOSA_STRIP_RE.sub("", tok).strip()
        if len(stem) >= 2 and stem not in _FUNCTION_WORDS and stem not in tokens:
            tokens.append(stem)
    return tokens


def _find_shared_concepts(tokens_a: Sequence[str], tokens_b: Sequence[str]) -> Set[str]:
    """두 토큰 집합 간에 공유되는 핵심 개념어(완전 일치 및 한국어 합성명사 어근/핵 일치)를 반환한다.

    특정 단어 하드코딩 없이 한국어 합성명사의 우측 핵(Head-final) 및 접두 결합 특성을 활용하여
    2글자 이상의 토큰이 다른 합성명사 토큰의 접두사 또는 접미사로 포함되는 경우 공통 개념어로 인식한다.
    """
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    shared: Set[str] = set_a & set_b

    for ta in set_a:
        for tb in set_b:
            if ta == tb:
                continue
            short_tok, long_tok = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            if len(short_tok) >= 2 and (
                long_tok.endswith(short_tok) or long_tok.startswith(short_tok)
            ):
                shared.add(short_tok)
    return shared


def infer_scope(
    statement: str,
    claim_type: Optional[str] = None,
    explicit_scope: Optional[str] = None,
) -> Literal["DOCUMENT_LOCAL", "CASE_GLOBAL"]:
    """진술이 개별 증거 문서 자체의 메타데이터(DOCUMENT_LOCAL)인지 사건 전체 사실(CASE_GLOBAL)인지 판별한다."""
    if explicit_scope in ("DOCUMENT_LOCAL", "CASE_GLOBAL"):
        return explicit_scope  # type: ignore[return-value]
    norm_type = (claim_type or "").strip().upper()
    if norm_type in ("DOC_INFO", "DOCUMENT_INFO", "DOCUMENT", "문서정보", "문서"):
        return "DOCUMENT_LOCAL"
    # 문장 구조상 해당 문서 자체의 제목·형식을 설명하는 메타 진술인 경우
    if re.search(r"문서의\s*(?:제목|명칭|종류|형식)|본\s*문서는", statement or ""):
        return "DOCUMENT_LOCAL"
    return "CASE_GLOBAL"


def build_structured_slots(
    statement: str,
    claim_type: Optional[str] = None,
    subject: Optional[str] = None,
    predicate: Optional[str] = None,
    scope: Optional[str] = None,
    evidence_id: Optional[str] = None,
    document_name: Optional[str] = None,
) -> StructuredFactSlots:
    """단일 진술(Claim 또는 Fact)로부터 정규화된 비교 슬롯(StructuredFactSlots)을 생성한다."""
    amounts = extract_normalized_amounts(statement)
    dates = extract_normalized_dates(statement)
    if amounts and dates:
        dim: Literal["AMOUNT", "DATE", "AMOUNT_AND_DATE", "TEXT"] = "AMOUNT_AND_DATE"
    elif amounts:
        dim = "AMOUNT"
    elif dates:
        dim = "DATE"
    else:
        dim = "TEXT"

    resolved_scope = infer_scope(statement, claim_type=claim_type, explicit_scope=scope)
    tokens = extract_content_tokens(statement)

    return StructuredFactSlots(
        statement=statement or "",
        claim_type=(claim_type or "GENERAL").strip().upper(),
        scope=resolved_scope,
        subject_key=subject.strip() if subject else None,
        predicate_key=predicate.strip() if predicate else None,
        value_dimension=dim,
        normalized_amounts=amounts,
        normalized_dates=dates,
        polarity=detect_polarity(statement),
        content_tokens=tokens,
        evidence_id=evidence_id,
        document_name=document_name,
    )


def _verify_pair_with_llm(
    claim_slots: StructuredFactSlots,
    fact_slots: StructuredFactSlots,
) -> Optional[_LLMConflictVerificationSchema]:
    """규칙 필터에서 잠재적 충돌 후보로 좁혀진 쌍에 대해 선택적 LLM 의미 검증을 수행한다."""
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "당신은 법률 증거 상충(Contradiction) 검증 전문가입니다.\n"
            "한 사건에는 계약서, 영수증, 문자메시지, 내용증명 등 여러 증거 문서가 시간 순서에 따라 제출됩니다.\n"
            "두 진술을 비교하여 다음 5가지 중 하나로 정확히 판정하세요:\n"
            "1. CONSISTENT: 동일한 사실이나 금액·일자를 표현 방식만 다르게 서술했거나(예: 3억 원 vs 300,000,000원), "
            "계약서상 금액과 반환 요청 문자상 금액이 일치하는 등 서로 뒷받침하는 관계.\n"
            "2. DIFFERENT_CONTEXT: 서로 다른 문서의 고유 정보(예: 각 문서의 제목·발신일)이거나, "
            "하나는 금액이고 다른 하나는 반환 요청 날짜/통지 행위여서 비교 대상 속성이 다른 별개 사실.\n"
            "3. POTENTIAL_CONFLICT: 시간 경과에 따른 변화(예: 최초 계약 만기일 이후의 퇴거 요청으로 묵시적 갱신/재계약 경위 확인이 필요한 경우 등)로서 "
            "즉시 모순으로 단정할 수 없고 추가 확인이 필요한 경우.\n"
            "4. CONTRADICTION: 동일한 대상·동일한 속성·동일한 시점에 대해 두 진술이 논리적으로 동시에 참일 수 없는 명백한 모순인 경우만 해당 "
            "(예: 동일 계약의 보증금 원금이 한 문서에는 3억 원, 다른 문서에는 2억 원으로 기재된 경우, 또는 동일 일자 금전 지급 여부가 정반대인 경우).\n"
            "5. INSUFFICIENT_INFORMATION: 문맥만으로 동일 대상인지 판단할 수 없는 경우.\n\n"
            "핵심 원칙: '서로 다른 정보나 후속 행위는 모순이 아니다. 동일한 대상과 속성에 대해 동시에 참일 수 없는 진술만 CONTRADICTION이다.'",
        ),
        (
            "human",
            "[신규 증거 진술]\n"
            "- 출처 문서: {claim_doc}\n"
            "- 분류: {claim_type} (범위: {claim_scope})\n"
            "- 주어/대상: {claim_subject} | 속성/행위: {claim_predicate}\n"
            "- 정규화 금액(KRW): {claim_amounts} | 정규화 날짜: {claim_dates}\n"
            "- 진술 원문: {claim_stmt}\n\n"
            "[기존 사건 사실(Fact)]\n"
            "- 출처 문서/참조: {fact_doc}\n"
            "- 분류: {fact_type} (범위: {fact_scope})\n"
            "- 정규화 금액(KRW): {fact_amounts} | 정규화 날짜: {fact_dates}\n"
            "- 사실 원문: {fact_stmt}\n\n"
            "위 두 진술의 관계를 판정하세요.",
        ),
    ])

    llm = get_llm(temperature=0.0)
    payload = {
        "claim_doc": claim_slots.document_name or claim_slots.evidence_id or "신규 증거 문서",
        "claim_type": claim_slots.claim_type,
        "claim_scope": claim_slots.scope,
        "claim_subject": claim_slots.subject_key or "(미지정)",
        "claim_predicate": claim_slots.predicate_key or "(미지정)",
        "claim_amounts": claim_slots.normalized_amounts,
        "claim_dates": claim_slots.normalized_dates,
        "claim_stmt": claim_slots.statement,
        "fact_doc": fact_slots.document_name or fact_slots.evidence_id or "기존 사건 사실",
        "fact_type": fact_slots.claim_type,
        "fact_scope": fact_slots.scope,
        "fact_amounts": fact_slots.normalized_amounts,
        "fact_dates": fact_slots.normalized_dates,
        "fact_stmt": fact_slots.statement,
    }

    try:
        structured_llm = llm.with_structured_output(_LLMConflictVerificationSchema, method="function_calling")
        res = (prompt | structured_llm).invoke(payload)
        if isinstance(res, _LLMConflictVerificationSchema):
            return res
    except Exception as e:
        logger.debug(f"[CONFLICT_DETECTOR] LLM structured verification fallback: {e}")

    try:
        raw_res = (prompt | llm).invoke(payload)
        text = getattr(raw_res, "content", str(raw_res)).strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
        data = json.loads(text)
        return _LLMConflictVerificationSchema(**data)
    except Exception as e:
        logger.debug(f"[CONFLICT_DETECTOR] LLM verification skipped: {e}")
        return None


def evaluate_claim_against_fact(
    claim_slots: StructuredFactSlots,
    fact: Fact,
    fact_doc_name: Optional[str] = None,
    claim_id: Optional[str] = None,
    source_span_ids: Optional[List[str]] = None,
    enable_llm_verification: bool = False,
) -> ConflictDecision:
    """단일 Claim 슬롯과 단일 기존 Fact를 3단계 파이프라인으로 비교하여 ConflictDecision을 반환한다.

    Args:
        claim_slots: 신규 Claim의 구조화 슬롯.
        fact: 비교 대상 기존 Fact 엔티티.
        fact_doc_name: 기존 Fact의 출처 문서명 (있는 경우).
        claim_id: Claim 식별자.
        source_span_ids: 근거 원문 Span ID 목록.
        enable_llm_verification: 규칙 비교에서 모호한 후보가 나왔을 때 LLM 2차 검증 호출 여부.

    Returns:
        ConflictDecision: 구조화된 비교 판정 결과.
    """
    spans = list(source_span_ids or [])
    fact_slots = build_structured_slots(
        statement=fact.statement or "",
        claim_type=fact.fact_type,
        evidence_id=fact.source_ref,
        document_name=fact_doc_name,
    )

    # ------------------------------------------------------------------
    # Stage 1: Comparability Gate (비교 가능성 판별)
    # ------------------------------------------------------------------
    # 1-1. 완전히 동일한 문장인 경우 즉시 CONSISTENT
    norm_c = "".join(claim_slots.statement.split())
    norm_f = "".join(fact_slots.statement.split())
    if norm_c and norm_c == norm_f:
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="CONSISTENT",
            reason_code="IDENTICAL_STATEMENT",
            explanation="동일한 내용의 사실 진술입니다.",
            confidence=1.0,
            source_span_ids=spans,
        )

    # 1-2. 문서 고유 메타데이터(DOCUMENT_LOCAL / DOC_INFO)는 타 문서 사실과 비교 대상이 아님
    if claim_slots.scope == "DOCUMENT_LOCAL" or fact_slots.scope == "DOCUMENT_LOCAL":
        if (
            not claim_slots.evidence_id
            or not fact_slots.evidence_id
            or claim_slots.evidence_id != fact_slots.evidence_id
        ):
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="DIFFERENT_CONTEXT",
                reason_code="DOCUMENT_LOCAL_METADATA",
                explanation="각 증거 문서 고유의 형식·제목 정보이므로 다른 문서의 사실과 상충 비교 대상이 아닙니다.",
                confidence=1.0,
                source_span_ids=spans,
            )

    # 1-3. 값 차원(Value Dimension) 불일치 차단:
    # 한쪽은 순수 날짜(DATE)만 기술하고 다른 한쪽은 순수 금액(AMOUNT)만 기술하는 경우 교차 비교 금지
    if (
        (claim_slots.value_dimension == "DATE" and fact_slots.value_dimension == "AMOUNT")
        or (claim_slots.value_dimension == "AMOUNT" and fact_slots.value_dimension == "DATE")
    ):
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="DIFFERENT_CONTEXT",
            reason_code="INCOMPATIBLE_VALUE_DIMENSION",
            explanation="일자기한 정보와 금액비용 정보는 서로 다른 속성이므로 상충 대상이 아닙니다.",
            confidence=1.0,
            source_span_ids=spans,
        )

    # 1-4. 공통 내용어 토큰 확인 (최소 1개 이상의 실질적 법률/사실 주제어를 공유해야 비교 가능)
    shared_tokens = _find_shared_concepts(claim_slots.content_tokens, fact_slots.content_tokens)
    if not shared_tokens:
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="DIFFERENT_CONTEXT",
            reason_code="UNRELATED_SUBJECT",
            explanation="공유하는 사실 대상이나 핵심 속성이 없는 별개의 사실입니다.",
            confidence=0.95,
            source_span_ids=spans,
        )

    # 명시적 주어(subject_key)가 양쪽 모두 지정되어 있으나 전혀 개념을 공유하지 않는 경우 별개 대상으로 분리
    if claim_slots.subject_key and fact_slots.subject_key:
        subj_shared = _find_shared_concepts(
            extract_content_tokens(claim_slots.subject_key),
            extract_content_tokens(fact_slots.subject_key),
        )
        if not subj_shared:
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_EXPLICIT_SUBJECT",
                explanation="명시된 비교 대상(주어/항목)이 서로 다른 별개 사실입니다.",
                confidence=0.95,
                source_span_ids=spans,
            )

    # ------------------------------------------------------------------
    # Stage 2: Normalized Rule Verification (정규화 수치 및 극성 비교)
    # ------------------------------------------------------------------
    c_amounts = set(claim_slots.normalized_amounts)
    f_amounts = set(fact_slots.normalized_amounts)
    c_dates = set(claim_slots.normalized_dates)
    f_dates = set(fact_slots.normalized_dates)

    # 2-1. 양쪽 모두 금액을 포함하는 경우: 정규화된 원(KRW) 단위 정수 비교
    if c_amounts and f_amounts:
        if c_amounts == f_amounts and claim_slots.polarity == fact_slots.polarity:
            # 예: 계약서의 '보증금 300,000,000원'과 반환 요청 문자의 '2026년 9월 30일 전세보증금 3억 원 반환 요청'
            # 두 진술의 정규화 금액이 정확히 일치하므로(날짜 유무와 무관하게) 금액 측면에서 CONSISTENT!
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="CONSISTENT",
                reason_code="NORMALIZED_AMOUNT_MATCH",
                explanation=f"정규화된 금액({sorted(c_amounts)[0]:,}원)이 기존 사실과 일치합니다.",
                confidence=0.98,
                source_span_ids=spans,
            )

        if enable_llm_verification:
            llm_ver = _verify_pair_with_llm(claim_slots, fact_slots)
            if llm_ver:
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status=llm_ver.status,
                    reason_code=llm_ver.reason_code,
                    explanation=llm_ver.explanation,
                    confidence=llm_ver.confidence,
                    source_span_ids=spans,
                )
        # LLM 비활성 또는 호출 실패 시: 핵심 주제를 공유하고 금액이 완전히 다르면 CONTRADICTION 판정
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="CONTRADICTION",
            reason_code="MUTUALLY_EXCLUSIVE_AMOUNT",
            explanation=(
                f"동일 항목({', '.join(sorted(shared_tokens)[:3])})에 대해 "
                f"신규 진술 금액({', '.join(f'{a:,}원' for a in sorted(c_amounts))})과 "
                f"기존 사실 금액({', '.join(f'{a:,}원' for a in sorted(f_amounts))})이 상충합니다."
            ),
            confidence=0.9,
            source_span_ids=spans,
        )

    # 2-2. 양쪽 모두 날짜를 포함하고 금액 충돌이 없는 경우
    if c_dates and f_dates and not (c_amounts and f_amounts):
        if c_dates == f_dates and claim_slots.polarity == fact_slots.polarity:
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="CONSISTENT",
                reason_code="NORMALIZED_DATE_MATCH",
                explanation=f"정규화된 일자({', '.join(sorted(c_dates))})가 기존 사실과 일치합니다.",
                confidence=0.95,
                source_span_ids=spans,
            )
        # 날짜가 서로 다른 경우:
        # 사건에는 계약일, 이체일, 통지일, 반환요청일 등 서로 다른 이벤트 날짜가 공존한다.
        # 따라서 두 문장의 핵심 행위/이벤트 토큰이 거의 동일할 때만 후보로 삼고, 다르면 DIFFERENT_CONTEXT로 처리한다.
        union_tokens = set(claim_slots.content_tokens) | set(fact_slots.content_tokens)
        jaccard = len(shared_tokens) / max(len(union_tokens), 1)
        if jaccard < 0.6:
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_TIMELINE_EVENT",
                explanation="서로 다른 시점의 개별 이벤트 또는 후속 절차에 관한 일자입니다.",
                confidence=0.9,
                source_span_ids=spans,
            )
        if enable_llm_verification:
            llm_ver = _verify_pair_with_llm(claim_slots, fact_slots)
            if llm_ver:
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status=llm_ver.status,
                    reason_code=llm_ver.reason_code,
                    explanation=llm_ver.explanation,
                    confidence=llm_ver.confidence,
                    source_span_ids=spans,
                )
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="POTENTIAL_CONFLICT",
            reason_code="DATE_DIFFERENCE_NEEDS_CHECK",
            explanation=(
                f"유사한 항목({', '.join(sorted(shared_tokens)[:3])})에 대해 "
                f"일자({', '.join(sorted(c_dates))} vs {', '.join(sorted(f_dates))})가 달라 경위 확인이 필요합니다."
            ),
            confidence=0.8,
            source_span_ids=spans,
        )

    # 2-3. 동일 핵심 주제/행위에 대해 서술 극성(긍정 vs 부정)이 정반대인 경우
    if claim_slots.polarity != fact_slots.polarity and len(shared_tokens) >= 2:
        if enable_llm_verification:
            llm_ver = _verify_pair_with_llm(claim_slots, fact_slots)
            if llm_ver:
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status=llm_ver.status,
                    reason_code=llm_ver.reason_code,
                    explanation=llm_ver.explanation,
                    confidence=llm_ver.confidence,
                    source_span_ids=spans,
                )
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="CONTRADICTION",
            reason_code="OPPOSITE_POLARITY_ON_SAME_SUBJECT",
            explanation=(
                f"동일 사실 대상({', '.join(sorted(shared_tokens)[:3])})에 대해 "
                "긍정 진술과 부정 진술이 서로 상충합니다."
            ),
            confidence=0.88,
            source_span_ids=spans,
        )

    return ConflictDecision(
        claim_id=claim_id,
        target_fact_id=fact.id,
        status="DIFFERENT_CONTEXT",
        reason_code="COMPLEMENTARY_OR_DISTINCT_FACT",
        explanation="기존 사실과 모순되지 않는 별개 또는 보완적 사실입니다.",
        confidence=0.9,
        source_span_ids=spans,
    )


def evaluate_claim_conflicts(
    statement: str,
    existing_facts: Sequence[Fact],
    claim_type: Optional[str] = None,
    subject: Optional[str] = None,
    predicate: Optional[str] = None,
    scope: Optional[str] = None,
    evidence_id: Optional[str] = None,
    document_name: Optional[str] = None,
    claim_id: Optional[str] = None,
    source_span_ids: Optional[List[str]] = None,
    llm_suggested_fact_id: Optional[str] = None,
    fact_doc_names: Optional[Dict[str, str]] = None,
    enable_llm_verification: bool = False,
) -> Dict[str, List[ConflictDecision]]:
    """신규 Claim을 사건의 기존 Fact 전체와 비교하여 상태별 ConflictDecision 목록을 반환한다.

    중요: 1차 추출 LLM이 `llm_suggested_fact_id`를 상충 후보로 지목했더라도,
    본 검증 엔진(evaluate_claim_against_fact)에서 `CONTRADICTION`으로 검증되지 않으면
    오탐으로 간주하여 상충으로 반영하지 않는다.

    Returns:
        Dict[str, List[ConflictDecision]]:
            - "contradictions": 명백한 모순(CONTRADICTION) 목록
            - "potential_conflicts": 추가 경위 확인 필요(POTENTIAL_CONFLICT) 목록
            - "consistent": 정규화 수치/내용이 일치하여 상호 지지(CONSISTENT)하는 목록
    """
    result: Dict[str, List[ConflictDecision]] = {
        "contradictions": [],
        "potential_conflicts": [],
        "consistent": [],
    }
    if not statement or not existing_facts:
        return result

    claim_slots = build_structured_slots(
        statement=statement,
        claim_type=claim_type,
        subject=subject,
        predicate=predicate,
        scope=scope,
        evidence_id=evidence_id,
        document_name=document_name,
    )

    doc_name_map = fact_doc_names or {}

    for fact in existing_facts:
        # LLM이 1차 추출에서 지목한 Fact인 경우 선택적 LLM 2차 검증을 활성화할 수 있음
        use_llm = enable_llm_verification or (llm_suggested_fact_id == fact.id and enable_llm_verification)
        decision = evaluate_claim_against_fact(
            claim_slots=claim_slots,
            fact=fact,
            fact_doc_name=doc_name_map.get(fact.id),
            claim_id=claim_id,
            source_span_ids=source_span_ids,
            enable_llm_verification=use_llm,
        )
        if decision.status == "CONTRADICTION":
            result["contradictions"].append(decision)
        elif decision.status == "POTENTIAL_CONFLICT":
            result["potential_conflicts"].append(decision)
        elif decision.status == "CONSISTENT":
            result["consistent"].append(decision)

    return result


def reconcile_case_conflicts(
    db: Session,
    case_id: Optional[str] = None,
    sync_neo4j: bool = True,
) -> Dict[str, Any]:
    """기존 PostgreSQL 및 Neo4j에 저장된 오탐 상충(CONTRADICTS / CONTRADICTION_CANDIDATE / DISPUTED)을
    3단계 상충 탐지 엔진으로 재평가하여 복구·정리한다.

    원본 증거 문서(EvidenceDocument), 원문 구간(EvidenceSpan), 승인된 주장(EvidenceClaim),
    사용자 리뷰 이력(EvidenceReview)은 보존하면서 잘못 연결된 상충 링크와 상태만 정정한다.

    Args:
        db: SQLAlchemy 데이터베이스 세션.
        case_id: 특정 사건만 재정비할 경우 사건 ID (None이면 전체 사건 대상).
        sync_neo4j: 변경 발생 사건에 대해 Neo4j 그래프 재동기화 수행 여부.

    Returns:
        Dict[str, Any]: 정리된 링크·주장·사실 건수 및 영향받은 사건 ID 목록.
    """
    doc_query = db.query(EvidenceDocument)
    if case_id:
        doc_query = doc_query.filter(EvidenceDocument.case_id == case_id)
    docs = doc_query.all()
    target_case_ids = sorted({d.case_id for d in docs if d.case_id})
    if case_id and case_id not in target_case_ids:
        target_case_ids.append(case_id)

    removed_links = 0
    converted_supports = 0
    reset_claims = 0
    restored_facts = 0
    affected_cases: List[str] = []

    for cid in target_case_ids:
        case_changed = False
        case_docs = db.query(EvidenceDocument).filter_by(case_id=cid).all()
        doc_map = {d.id: d for d in case_docs}
        case_facts = db.query(Fact).filter_by(case_id=cid).all()
        fact_map = {f.id: f for f in case_facts}
        fact_doc_names = {
            f.id: doc_map[f.source_ref].original_filename
            for f in case_facts
            if f.source_ref and f.source_ref in doc_map
        }

        # 1. 기존 CONTRADICTS EvidenceLink 재검증
        contradicts_links = (
            db.query(EvidenceLink)
            .join(EvidenceDocument, EvidenceLink.evidence_id == EvidenceDocument.id)
            .filter(
                EvidenceDocument.case_id == cid,
                EvidenceLink.link_type == "CONTRADICTS",
            )
            .all()
        )
        for link in contradicts_links:
            claim = db.query(EvidenceClaim).filter_by(id=link.claim_id).first() if link.claim_id else None
            if not claim or claim.review_status == "REJECTED":
                db.delete(link)
                removed_links += 1
                case_changed = True
                continue

            if link.target_type == "FACT":
                target_fact = fact_map.get(link.target_id)
                if not target_fact:
                    db.delete(link)
                    removed_links += 1
                    case_changed = True
                    continue

                claim_doc = doc_map.get(claim.evidence_id)
                claim_slots = build_structured_slots(
                    statement=claim.statement or "",
                    claim_type=claim.claim_type,
                    evidence_id=claim.evidence_id,
                    document_name=claim_doc.original_filename if claim_doc else None,
                )
                decision = evaluate_claim_against_fact(
                    claim_slots=claim_slots,
                    fact=target_fact,
                    fact_doc_name=fact_doc_names.get(target_fact.id),
                    claim_id=claim.id,
                    enable_llm_verification=False,
                )
                if decision.status != "CONTRADICTION":
                    if (
                        decision.status == "CONSISTENT"
                        and claim.review_status in ("APPROVED", "EDITED")
                    ):
                        existing_sup = (
                            db.query(EvidenceLink)
                            .filter_by(
                                evidence_id=claim.evidence_id,
                                claim_id=claim.id,
                                target_type="FACT",
                                target_id=target_fact.id,
                                link_type="SUPPORTS",
                            )
                            .first()
                        )
                        if not existing_sup:
                            link.link_type = "SUPPORTS"
                            converted_supports += 1
                        else:
                            db.delete(link)
                            removed_links += 1
                    else:
                        db.delete(link)
                        removed_links += 1
                    case_changed = True

        db.flush()

        # 2. EvidenceClaim의 CONTRADICTION_CANDIDATE 상태 재검증
        cand_claims = (
            db.query(EvidenceClaim)
            .filter(
                EvidenceClaim.case_id == cid,
                (EvidenceClaim.assertion_status == "CONTRADICTION_CANDIDATE")
                | (EvidenceClaim.claim_type == "CONTRADICTION"),
            )
            .all()
        )
        for claim in cand_claims:
            if claim.review_status == "REJECTED":
                if claim.assertion_status == "CONTRADICTION_CANDIDATE":
                    claim.assertion_status = "DOCUMENT_STATES"
                    reset_claims += 1
                    case_changed = True
                continue

            other_facts = [
                f
                for f in case_facts
                if not (f.source_ref == claim.evidence_id and (f.statement or "").strip() == (claim.statement or "").strip())
            ]
            claim_doc = doc_map.get(claim.evidence_id)
            eval_res = evaluate_claim_conflicts(
                statement=claim.statement or "",
                existing_facts=other_facts,
                claim_type=claim.claim_type,
                evidence_id=claim.evidence_id,
                document_name=claim_doc.original_filename if claim_doc else None,
                claim_id=claim.id,
                fact_doc_names=fact_doc_names,
                enable_llm_verification=False,
            )
            if not eval_res["contradictions"]:
                if claim.assertion_status == "CONTRADICTION_CANDIDATE":
                    claim.assertion_status = "DOCUMENT_STATES"
                    reset_claims += 1
                    case_changed = True

        db.flush()

        # 3. 더 이상 CONTRADICTS 링크가 남아 있지 않은 DISPUTED Fact 복원
        for fact in case_facts:
            if fact.verification_status == "DISPUTED":
                remaining_contra = (
                    db.query(EvidenceLink)
                    .filter_by(
                        target_type="FACT",
                        target_id=fact.id,
                        link_type="CONTRADICTS",
                    )
                    .count()
                )
                if remaining_contra == 0:
                    fact.verification_status = (
                        "DOCUMENT_VERIFIED"
                        if fact.source_type == "EVIDENCE_DERIVED"
                        else "UNVERIFIED"
                    )
                    restored_facts += 1
                    case_changed = True

        if case_changed:
            affected_cases.append(cid)

    db.commit()

    if sync_neo4j and affected_cases:
        try:
            from ai_legal_helper.database.graph_sync import safe_sync_case
            for cid in affected_cases:
                safe_sync_case(cid)
        except Exception as e:
            logger.warning(f"[CONFLICT_DETECTOR] Neo4j sync after reconciliation warning: {e}")

    return {
        "removed_links": removed_links,
        "converted_supports_links": converted_supports,
        "reset_claims": reset_claims,
        "restored_facts": restored_facts,
        "affected_case_ids": affected_cases,
    }
