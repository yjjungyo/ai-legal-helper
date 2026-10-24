# -*- coding: utf-8 -*-
"""
모듈명: conflict_detector.py

[모듈 개요]
다중 증거 문서 환경에서 추출된 사실 주장(EvidenceClaim)과 기존 사건 사실관계(Fact) 간의
일치(CONSISTENT), 별개 맥락(DIFFERENT_CONTEXT), 추가 경위 확인 필요(POTENTIAL_CONFLICT),
논리적 모순(CONTRADICTION), 정보 부족(INSUFFICIENT_INFORMATION)을 판별하는
3단계 증거 상충 탐지 엔진(Evidence Conflict Detection Engine v1.1)이다.

[핵심 설계 원칙]
1. 서로 다른 정보는 모순이 아니다: 동일한 대상(Subject), 동일한 속성(Predicate),
   양립 불가능한 시점(Temporal Context)에 대해 동시에 참일 수 없는 진술만 모순(CONTRADICTION)으로 판정한다.
2. 특정 문자열이나 특정 숫자에 대한 하드코딩을 일체 금지한다:
   한국어 수사 체계(일~구, 십·백·천·만·억·조)의 자릿수 연산 알고리즘, 달력 유효성 검증(datetime.date),
   금액·날짜의 의미 역할(Semantic Role) 분류, 부정 범위(Polarity Scope) 분석, 선택적 LLM 의미 검증을 결합한다.
3. 3단계 파이프라인:
   - Stage 1 (Comparability Gate): 문서 고유 메타데이터(DOC_INFO / DOCUMENT_LOCAL) 분리,
     값 차원 불일치 차단, 주어·속성 역할 비교 가능성 검증.
   - Stage 2 (Normalized Rule Verification): 금액 역할별 원(KRW) 단위 정수 비교,
     날짜 역할별 ISO(YYYY-MM-DD) 및 달력 유효성 비교, 부정 적용 범위(단순 부정·이중 부정·인용 통지) 비교.
   - Stage 3 (Selective LLM Semantic Verification): 모호한 후보 쌍에 대해 원문·슬롯·출처 맥락을
     전달하여 검증하고 Langfuse에 기록하며, LLM 장애 시 확정 모순 판정을 강행하지 않고 안전 폴백한다.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
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
from ai_legal_helper.case_intelligence.fact_semantics import (
    ComparabilityResult,
    SemanticFact,
    compare_fact_identity,
    evaluate_temporal_relation,
    extract_semantic_fact,
)
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span

logger = logging.getLogger(__name__)

ConflictStatusType = Literal[
    "CONSISTENT",
    "CONTRADICTION",
    "POTENTIAL_CONFLICT",
    "DIFFERENT_CONTEXT",
    "INSUFFICIENT_INFORMATION",
]

PolarityType = Literal[
    "AFFIRMATIVE",
    "NEGATIVE",
    "DOUBLE_NEGATIVE",
    "REPORTED_NEGATIVE",
    "UNCONFIRMED",
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

# 금액 표현 추출용 정규식: 접두사 '금(金)'은 독립 어절일 때만 매칭하여 '보증금', '계약금' 등의 어미 '금'이 잘리지 않도록 함
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
    r"에게는|까지는|부터는|으로는|로서는|에서는|이라는|"
    r"에게|에서|으로|로써|로서|까지|부터|보다|처럼|마다|조차|마저|밖에|대로|"
    r"은|는|이|가|을|를|의|에|로|와|과|도|만)$"
)

# 문법적 기능어·일반 서술 보조어
_FUNCTION_WORDS: Set[str] = {
    "문서", "제목", "내용", "사실", "주장", "경우", "관련", "특정", "부분",
    "이다", "있다", "없다", "한다", "하였다", "되었다", "대한", "위해", "따라",
    "통해", "대해", "맞춰", "재차", "확인", "해당", "기준", "일정", "가능",
    "금액", "일자", "날짜", "원금", "전액", "금원",
}

# 금액의 의미적 역할(Semantic Role) 분류 패턴 (우선순위 순)
_AMOUNT_ROLE_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("MODIFIED_CONTRACT_AMOUNT", re.compile(r"증액|감액|변경\s*보증금|갱신\s*보증금|인상|인하")),
    ("TOTAL_AMOUNT", re.compile(r"합계|총액|전체\s*보증금|보증금\s*전액")),
    ("RETURN_REQUEST_AMOUNT", re.compile(r"반환\s*요청|반환을\s*요청|반환\s*청구")),
    ("RETURNED_AMOUNT", re.compile(r"일부\s*반환|반환한\s*금액|반환된\s*금액|반환받은|돌려받은|돌려준|회수한|공제\s*후\s*반환|원을\s*반환하|원을\s*반환했")),
    ("REMAINING_DEBT", re.compile(r"미반환|미지급|잔여\s*채무|잔존\s*채무|남은\s*금액|못\s*받은|연체액|체불액")),
    ("DAMAGES_OR_PENALTY", re.compile(r"손해배상|위약금|지연손해금|수리비|원상복구|배상액|청구액")),
    ("DOWN_PAYMENT", re.compile(r"계약금|가계약금")),
    ("INTERIM_OR_BALANCE", re.compile(r"중도금|잔금")),
    ("PERIODIC_RENT_OR_FEE", re.compile(r"차임|월세|관리비|임대료|이자")),
    ("ACTUAL_PAYMENT", re.compile(r"송금|이체|입금|납부|지급한\s*금액|지급액")),
    ("PRINCIPAL_DEPOSIT", re.compile(r"전세보증금|임대차보증금|보증금|전세금|차용금|대여금|매매대금")),
)

# 날짜의 의미적 역할(Date Role) 분류 패턴 (우선순위 순)
_DATE_ROLE_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("RENEWAL_DATE", re.compile(r"묵시적\s*갱신|갱신\s*후|갱신일|연장\s*만기|재계약")),
    ("RETURN_REQUEST_DATE", re.compile(r"반환\s*요청|퇴거\s*요청|퇴거\s*예정|퇴거일|명도\s*예정|반환\s*기일")),
    ("NOTICE_RECEIVED_DATE", re.compile(r"도달|수령|수신|받은\s*날")),
    ("NOTICE_SENT_DATE", re.compile(r"통지|통보|내용증명|발송|보낸\s*날|갱신\s*거절|해지\s*통고")),
    ("EXPIRATION_DATE", re.compile(r"계약\s*만기|임대차\s*만기|만료일|계약\s*종료일|임대차\s*종료|기간\s*만료")),
    ("START_OR_DELIVERY_DATE", re.compile(r"인도|입주|전입\s*(?:신고)?일|개시일")),
    ("DOWN_PAYMENT_DUE_DATE", re.compile(r"계약금\s*(?:지급|납부)?\s*기일|계약금\s*지급\s*예정")),
    ("BALANCE_PAYMENT_DUE_DATE", re.compile(r"잔금\s*(?:지급|납부)?\s*기일|잔금\s*지급\s*예정")),
    ("PAYMENT_DUE_DATE", re.compile(r"지급기일|지급예정일|납부기일|변제기")),
    ("ACTUAL_PAYMENT_OR_RETURN_DATE", re.compile(r"지급하|이체하|송금하|입금하|반환하")),
    ("CONTRACT_DATE", re.compile(r"체결|계약일|작성일")),
)

# 인용·통보절 내부의 부정(Reported Negation) 패턴: "반환할 수 없다고 통보하였다" 등
_REPORTED_NEGATION_RE = re.compile(
    r"(?:없다|수\s*없다|지\s*않겠다|지\s*못한다|어렵다|불가하다|거절한다|안\s*된다)고\s*"
    r"(?:통보|통지|연락|말|전달|회신|답변|문자|주장|고지)"
)

# 이중 부정(Double Negation) 패턴: "거절하지 않았다", "부인하지 않았다" 등
_DOUBLE_NEGATION_RE = re.compile(
    r"(거절|거부|부인|불응|해태|지체|누락)하?지\s*(?:않|못)|"
    r"없지\s*않|아니지\s*않"
)

# 부정 극성 및 부정 대상 서술어 추출 패턴
_DIRECT_NEGATION_TARGET_RE = re.compile(
    r"([가-힣]{2,6}?)하?지\s*(?:않|못)|"
    r"([가-힣]{2,6}?)\s*안\s+했|"
    r"(?:^|\s)미([가-힣]{2,4})"
)

# 한국어 문법상 일반 부정 극성 마커
_NEGATION_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"지\s*않"),
    re.compile(r"지\s*못"),
    re.compile(r"안\s+했|안\s+하"),
    re.compile(r"없었|없다|없음|없으며"),
    re.compile(r"아니다|아니었|아님"),
    re.compile(r"(?:^|\s)미[가-힣]{2,}"),
    re.compile(r"거절|거부|부인|불응"),
)


class StructuredFactSlots(BaseModel):
    """문장에서 추출·정규화된 사실 비교 슬롯 모델 (P0-01 & P0-02)."""
    statement: str = Field(description="원본 진술 문장")
    claim_type: str = Field(default="GENERAL", description="표준 분류 코드")
    scope: Literal["DOCUMENT_LOCAL", "CASE_GLOBAL"] = Field(
        default="CASE_GLOBAL",
        description="DOCUMENT_LOCAL(개별 문서 자체의 제목·형식 정보) vs CASE_GLOBAL(사건 실체 사실)",
    )
    subject_key: Optional[str] = Field(default=None, description="비교 대상 주체/객체/계약 항목")
    predicate_key: Optional[str] = Field(default=None, description="비교 대상 속성/행위 의미")
    temporal_context: Optional[str] = Field(default=None, description="사실이 적용되는 시점·기간·이벤트 역할")
    value_dimension: Literal["AMOUNT", "DATE", "AMOUNT_AND_DATE", "TEXT"] = Field(
        default="TEXT",
        description="진술이 포함하는 수치 값의 차원",
    )
    normalized_amounts: List[int] = Field(default_factory=list, description="원(KRW) 단위로 정규화된 금액 정수 목록")
    amount_roles: Dict[str, List[int]] = Field(
        default_factory=dict,
        description="금액의 의미 역할(예: PRINCIPAL_DEPOSIT, RETURNED_AMOUNT, DOWN_PAYMENT)별 정규화 금액 목록",
    )
    normalized_dates: List[str] = Field(default_factory=list, description="YYYY-MM-DD로 정규화된 유효 날짜 목록")
    invalid_dates: List[str] = Field(default_factory=list, description="달력상 존재하지 않는 잘못된 날짜 표현 목록")
    date_roles: Dict[str, List[str]] = Field(
        default_factory=dict,
        description="날짜의 의미 역할(예: CONTRACT_DATE, EXPIRATION_DATE, RETURN_REQUEST_DATE)별 정규화 날짜 목록",
    )
    polarity: PolarityType = Field(
        default="AFFIRMATIVE",
        description="서술부의 극성 (AFFIRMATIVE, NEGATIVE, DOUBLE_NEGATIVE, REPORTED_NEGATIVE, UNCONFIRMED)",
    )
    core_predicate: Optional[str] = Field(default=None, description="문장의 핵심 서술 행위/속성 어근")
    negated_predicate: Optional[str] = Field(default=None, description="부정 표현이 직접 수식하는 대상 행위 어근")
    content_tokens: List[str] = Field(default_factory=list, description="조사 제거 내용어 토큰 목록")
    evidence_id: Optional[str] = Field(default=None, description="출처 증거 문서 ID")
    document_name: Optional[str] = Field(default=None, description="출처 증거 문서 파일명")
    source_span_ids: List[str] = Field(default_factory=list, description="출처 원문 Span ID 목록")
    semantic_fact: Optional[SemanticFact] = Field(default=None, description="정규화된 사실 의미 구조 모델")
    semantic_category: Optional[str] = Field(default=None, description="의미 범주 (EVENT, STATE, OBLIGATION 등)")
    event_type: Optional[str] = Field(default=None, description="이벤트 대분류")
    event_subtype: Optional[str] = Field(default=None, description="이벤트 세부 항목")
    temporal_type: Optional[str] = Field(default=None, description="시간 의미 유형")


class ConflictDecision(BaseModel):
    """단일 Claim과 기존 Fact 간의 상충·일치 비교 판정 결과 모델."""
    claim_id: Optional[str] = Field(default=None, description="검토 대상 EvidenceClaim ID")
    target_fact_id: str = Field(description="비교 대상 Fact ID")
    status: ConflictStatusType = Field(description="비교 판정 상태 (5단계)")
    reason_code: str = Field(description="판정 사유 표준 코드")
    explanation: str = Field(description="사용자 및 감사 로그용 판정 근거 설명")
    confidence: float = Field(default=0.9, description="판정 신뢰도 (0.0 ~ 1.0)")
    source_span_ids: List[str] = Field(default_factory=list, description="근거 원문 Span ID 목록")
    llm_verified: bool = Field(default=False, description="Stage 3 LLM 검증 수행 여부")
    subject_match_basis: Optional[str] = Field(default=None, description="동일 대상 판단 근거")
    predicate_match_basis: Optional[str] = Field(default=None, description="동일 속성·행위 판단 근거")
    temporal_semantics: Optional[str] = Field(default=None, description="시점 의미 판단 근거")


class _LLMConflictVerificationSchema(BaseModel):
    """선택적 LLM 2차 의미 검증 출력 스키마."""
    status: Literal[
        "CONSISTENT",
        "CONTRADICTION",
        "POTENTIAL_CONFLICT",
        "DIFFERENT_CONTEXT",
        "INSUFFICIENT_INFORMATION",
    ] = Field(description="두 진술의 논리적 관계 판정")
    reason_code: str = Field(
        description="판정 사유 코드 (예: SAME_AMOUNT_DIFFERENT_FORMAT, DIFFERENT_EVENT_DATE, RENEWAL_GAP, MUTUALLY_EXCLUSIVE_AMOUNT, MUTUALLY_EXCLUSIVE_ACTION)"
    )
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

    if cleaned.isdigit():
        val = int(cleaned)
        return val if val > 0 else None

    total = 0
    section = 0
    current_num: float = 0
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
            section += int(current_num)
            factor = section if section > 0 else 1
            total += int(factor * large_val)
            section = 0
            current_num = 0
            has_any_number = True
        i += 1

    result = int(total + section + current_num)
    return result if (has_any_number and result > 0) else None


def _classify_amount_role(pre_window: str, immediate_window: str, context_window: str, full_text: str) -> str:
    """단일 금액 표현의 직전 수식 명사(pre_window), 인접 문맥(immediate_window), 주변 문맥(context_window), 전체 문장을 순차 분석하여 금액의 의미적 역할(Role)을 분류한다."""
    for role_code, pattern in _AMOUNT_ROLE_PATTERNS:
        if pattern.search(pre_window):
            return role_code
    for role_code, pattern in _AMOUNT_ROLE_PATTERNS:
        if pattern.search(immediate_window):
            return role_code
    for role_code, pattern in _AMOUNT_ROLE_PATTERNS:
        if pattern.search(context_window):
            return role_code
    for role_code, pattern in _AMOUNT_ROLE_PATTERNS:
        if pattern.search(full_text):
            return role_code
    return "GENERAL_AMOUNT"


def extract_amount_roles(text: str) -> Tuple[List[int], Dict[str, List[int]]]:
    """문장 내 모든 금액 표현을 원(KRW) 단위로 정규화하고 의미 역할별로 매핑한다.

    Args:
        text: 분석 대상 한국어 문장.

    Returns:
        Tuple[List[int], Dict[str, List[int]]]: (전체 정규화 금액 리스트, 역할별 금액 딕셔너리).
    """
    if not text:
        return [], {}

    amounts: List[int] = []
    roles: Dict[str, List[int]] = {}

    for match in _AMOUNT_EXPR_RE.finditer(text):
        num_part = (match.group(1) or "").strip()
        suffix = (match.group(2) or "").replace(" ", "").strip()
        if not num_part:
            continue

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
        if val is None or val < 100:
            continue

        if val not in amounts:
            amounts.append(val)

        # 한국어 금액 구문에서는 금액 직전 명사구(예: '보증금 3억', '계약금 3천만', '잔금 2억 7천만')가 역할을 가장 정확히 나타내므로
        # 직전 문맥(pre_ctx)을 1순위로 검사하고, 직후 서술어('반환하였다', '반환을 요청하였다')를 포함한 인접 문맥을 2순위로 검사한다.
        pre_ctx = text[max(0, match.start() - 12):match.start()]
        imm_start = max(0, match.start() - 10)
        imm_end = min(len(text), match.end() + 12)
        immediate_ctx = text[imm_start:imm_end]

        start_idx = max(0, match.start() - 20)
        end_idx = min(len(text), match.end() + 16)
        local_ctx = text[start_idx:end_idx]
        role = _classify_amount_role(pre_ctx, immediate_ctx, local_ctx, text)
        role_list = roles.setdefault(role, [])
        if val not in role_list:
            role_list.append(val)

    return amounts, roles


def extract_normalized_amounts(text: str) -> List[int]:
    """문장 내 모든 금액 표현을 원(KRW) 단위 정수로 정규화하여 추출한다."""
    amounts, _ = extract_amount_roles(text)
    return amounts


def _classify_date_role(context_window: str, full_text: str) -> str:
    """날짜 표현 주변 문맥과 전체 문장을 분석하여 날짜의 의미적 역할(Date Role)을 분류한다."""
    for role_code, pattern in _DATE_ROLE_PATTERNS:
        if pattern.search(context_window):
            return role_code
    for role_code, pattern in _DATE_ROLE_PATTERNS:
        if pattern.search(full_text):
            return role_code
    return "GENERAL_DATE"


def extract_dates_with_validation(text: str) -> Tuple[List[str], List[str], Dict[str, List[str]]]:
    """문장 내 날짜 표현을 추출하고 실제 달력 유효성(윤년·월별 말일)을 검증한 뒤 역할별로 분류한다.

    Args:
        text: 분석 대상 한국어 문장.

    Returns:
        Tuple[List[str], List[str], Dict[str, List[str]]]:
            (유효한 YYYY-MM-DD 목록, 잘못된 날짜 원문 목록, 날짜 역할별 YYYY-MM-DD 딕셔너리)
    """
    if not text:
        return [], [], {}

    valid_dates: List[str] = []
    invalid_dates: List[str] = []
    date_roles: Dict[str, List[str]] = {}

    for m in _DATE_FULL_RE.finditer(text):
        yyyy, mm, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        raw_token = m.group(0).strip()
        try:
            valid_dt = datetime.date(yyyy, mm, dd)
            iso = valid_dt.isoformat()
            if iso not in valid_dates:
                valid_dates.append(iso)
            start_idx = max(0, m.start() - 24)
            end_idx = min(len(text), m.end() + 24)
            local_ctx = text[start_idx:end_idx]
            role = _classify_date_role(local_ctx, text)
            r_list = date_roles.setdefault(role, [])
            if iso not in r_list:
                r_list.append(iso)
        except ValueError:
            if raw_token not in invalid_dates:
                invalid_dates.append(raw_token)

    return valid_dates, invalid_dates, date_roles


def extract_normalized_dates(text: str) -> List[str]:
    """문장 내 유효한 모든 날짜 표현을 표준 ISO 형식(YYYY-MM-DD)으로 정규화하여 추출한다."""
    valid_dates, _, _ = extract_dates_with_validation(text)
    return valid_dates


def analyze_polarity_and_predicate(
    text: str,
    explicit_predicate: Optional[str] = None,
) -> Tuple[PolarityType, Optional[str], Optional[str]]:
    """문장의 부정 범위(단순 부정·이중 부정·인용절 통보)와 핵심 서술어·부정 대상 행위를 분석한다.

    Section 3.5 요구사항 반영:
    - '보증금을 반환하지 않았다' -> (NEGATIVE, core='반환', negated='반환')
    - '보증금 반환을 거절하지 않았다' -> (DOUBLE_NEGATIVE, core='거절', negated='거절')
    - '보증금을 반환할 수 없다고 통보하였다' -> (REPORTED_NEGATIVE, core='통보', negated='반환')
    """
    if not text:
        return "AFFIRMATIVE", explicit_predicate, None

    # 1. 인용절 부정('~없다고 통보하였다') 검사
    if _REPORTED_NEGATION_RE.search(text):
        comm_match = re.search(r"(통보|통지|연락|전달|회신|답변|고지)", text)
        core_pred = explicit_predicate or (comm_match.group(1) if comm_match else "통보")
        neg_match = _DIRECT_NEGATION_TARGET_RE.search(text)
        neg_target = None
        if neg_match:
            neg_target = neg_match.group(1) or neg_match.group(2) or neg_match.group(3)
        elif "반환" in text:
            neg_target = "반환"
        return "REPORTED_NEGATIVE", core_pred, neg_target

    # 2. 이중 부정('거절하지 않았다', '부인하지 않았다') 검사
    dbl_match = _DOUBLE_NEGATION_RE.search(text)
    if dbl_match:
        target = dbl_match.group(1) or explicit_predicate or "거절"
        return "DOUBLE_NEGATIVE", target, target

    # 3. 직접 부정('반환하지 않았다', '미반환', '지급하지 못했다') 검사
    dir_match = _DIRECT_NEGATION_TARGET_RE.search(text)
    if dir_match:
        neg_verb = dir_match.group(1) or dir_match.group(2) or dir_match.group(3)
        if neg_verb:
            neg_verb = _JOSA_STRIP_RE.sub("", neg_verb).strip()
        core_pred = explicit_predicate or neg_verb
        return "NEGATIVE", core_pred, neg_verb

    for pat in _NEGATION_PATTERNS:
        if pat.search(text):
            return "NEGATIVE", explicit_predicate, explicit_predicate

    # 4. 긍정문 핵심 서술어 추론
    if explicit_predicate:
        return "AFFIRMATIVE", explicit_predicate, None

    verb_match = re.search(
        r"(반환|지급|이체|송금|체결|해지|해제|갱신|통지|통보|인도|퇴거|청구|수령)",
        text,
    )
    inferred_pred = verb_match.group(1) if verb_match else None
    return "AFFIRMATIVE", inferred_pred, None


def detect_polarity(text: str) -> PolarityType:
    """문장의 문법적 서술 극성을 반환한다."""
    pol, _, _ = analyze_polarity_and_predicate(text)
    return pol


def extract_content_tokens(text: str) -> List[str]:
    """날짜·숫자·조사를 제외한 핵심 내용어(명사/어근) 토큰을 추출한다."""
    if not text:
        return []
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
    """두 토큰 집합 간에 공유되는 핵심 개념어(완전 일치 및 한국어 합성명사 어근/핵 일치)를 반환한다."""
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
    if re.search(r"문서의\s*(?:제목|명칭|종류|형식)|본\s*문서는|이\s*문서는", statement or ""):
        return "DOCUMENT_LOCAL"
    return "CASE_GLOBAL"


def build_structured_slots(
    statement: str,
    claim_type: Optional[str] = None,
    subject: Optional[str] = None,
    predicate: Optional[str] = None,
    scope: Optional[str] = None,
    temporal_context: Optional[str] = None,
    evidence_id: Optional[str] = None,
    document_name: Optional[str] = None,
    source_span_ids: Optional[List[str]] = None,
) -> StructuredFactSlots:
    """단일 진술(Claim 또는 Fact)로부터 정규화된 비교 슬롯(StructuredFactSlots)을 생성한다."""
    amounts, amount_roles = extract_amount_roles(statement)
    dates, invalid_dates, date_roles = extract_dates_with_validation(statement)

    if amounts and (dates or invalid_dates):
        dim: Literal["AMOUNT", "DATE", "AMOUNT_AND_DATE", "TEXT"] = "AMOUNT_AND_DATE"
    elif amounts:
        dim = "AMOUNT"
    elif dates or invalid_dates:
        dim = "DATE"
    else:
        dim = "TEXT"

    resolved_scope = infer_scope(statement, claim_type=claim_type, explicit_scope=scope)
    tokens = extract_content_tokens(statement)
    pol, core_pred, neg_pred = analyze_polarity_and_predicate(statement, explicit_predicate=predicate)

    # Fact Semantics 연계 추출
    sem_fact = extract_semantic_fact(
        statement,
        context={
            "document_name": document_name,
            "claim_type": claim_type,
            "subject_key": subject,
            "predicate_key": predicate,
            "evidence_id": evidence_id,
        },
    )
    if sem_fact.polarity in ("UNCONFIRMED", "REPORTED_NEGATIVE", "DOUBLE_NEGATIVE"):
        pol = sem_fact.polarity

    inferred_subject = subject.strip() if subject and subject.strip() else (sem_fact.subject_key or None)
    if not inferred_subject and amount_roles:
        primary_amt_role = next(iter(amount_roles.keys()))
        if primary_amt_role != "GENERAL_AMOUNT":
            inferred_subject = primary_amt_role
    if not inferred_subject and tokens:
        inferred_subject = tokens[0]

    inferred_temporal = temporal_context.strip() if temporal_context and temporal_context.strip() else (sem_fact.temporal_type if sem_fact.temporal_type != "NONE" else None)
    if not inferred_temporal and date_roles:
        inferred_temporal = next(iter(date_roles.keys()))

    return StructuredFactSlots(
        statement=statement or "",
        claim_type=(claim_type or "GENERAL").strip().upper(),
        scope=resolved_scope,
        subject_key=inferred_subject,
        predicate_key=(predicate.strip() if predicate and predicate.strip() else core_pred),
        temporal_context=inferred_temporal,
        value_dimension=dim,
        normalized_amounts=amounts,
        amount_roles=amount_roles,
        normalized_dates=dates,
        invalid_dates=invalid_dates,
        date_roles=date_roles,
        polarity=pol,
        core_predicate=core_pred,
        negated_predicate=neg_pred,
        content_tokens=tokens,
        evidence_id=evidence_id,
        document_name=document_name,
        source_span_ids=list(source_span_ids or []),
        semantic_fact=sem_fact,
        semantic_category=sem_fact.semantic_category,
        event_type=sem_fact.event_type,
        event_subtype=sem_fact.event_subtype,
        temporal_type=sem_fact.temporal_type,
    )


def _should_use_llm_verification(explicit_flag: Optional[bool]) -> bool:
    """Stage 3 선택적 LLM 검증 활성화 여부를 결정한다."""
    if explicit_flag is not None:
        return explicit_flag
    env_val = os.getenv("CONFLICT_LLM_VERIFICATION_ENABLED", "false").strip().lower()
    return env_val in ("1", "true", "yes", "on")


def _verify_pair_with_llm(
    claim_slots: StructuredFactSlots,
    fact_slots: StructuredFactSlots,
) -> Optional[_LLMConflictVerificationSchema]:
    """규칙 필터에서 잠재적 충돌 후보로 좁혀진 쌍에 대해 선택적 LLM 의미 검증을 수행하고 Langfuse에 기록한다."""
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "당신은 법률 증거 상충(Contradiction) 검증 전문가입니다.\n"
            "한 사건에는 계약서, 영수증, 문자메시지, 내용증명 등 여러 증거 문서가 시간 순서에 따라 제출됩니다.\n"
            "두 진술을 비교하여 다음 5가지 중 하나로 정확히 판정하세요:\n"
            "1. CONSISTENT: 동일한 사실이나 금액·일자를 표현 방식만 다르게 서술했거나 서로 뒷받침하는 관계.\n"
            "2. DIFFERENT_CONTEXT: 서로 다른 문서의 고유 정보이거나, 계약 보증금 원금 vs 일부 반환금, 계약 체결일 vs 반환 요청일처럼 비교 대상 속성이 다른 별개 사실.\n"
            "3. POTENTIAL_CONFLICT: 시간 경과에 따른 변화(예: 최초 계약 만기일 이후의 퇴거 요청으로 묵시적 갱신/재계약 경위 확인이 필요한 경우, 또는 동일 행위 일자 차이)로서 "
            "즉시 모순으로 단정할 수 없고 추가 확인이 필요한 경우.\n"
            "4. CONTRADICTION: 동일한 대상·동일한 속성·동일한 시점에 대해 두 진술이 논리적으로 동시에 참일 수 없는 명백한 모순인 경우만 해당 "
            "(예: 동일 계약의 보증금 원금이 한 문서에는 3억 원, 다른 문서에는 2억 원으로 기재된 경우, 또는 동일 시점·동일 대상의 금전 지급 여부가 정반대인 경우).\n"
            "5. INSUFFICIENT_INFORMATION: 문맥만으로 동일 대상인지 판단할 수 없는 경우.\n\n"
            "핵심 원칙: '서로 다른 정보나 후속 행위는 모순이 아니다. 동일한 대상과 속성에 대해 동시에 참일 수 없는 진술만 CONTRADICTION이다.'",
        ),
        (
            "human",
            "[신규 증거 진술]\n"
            "- 출처 문서: {claim_doc}\n"
            "- 분류: {claim_type} (범위: {claim_scope})\n"
            "- 주어/대상: {claim_subject} | 속성/행위: {claim_predicate} | 시점맥락: {claim_temporal}\n"
            "- 역할별 정규화 금액(KRW): {claim_amounts} | 역할별 정규화 날짜: {claim_dates} | 극성: {claim_polarity}\n"
            "- 진술 원문: {claim_stmt}\n\n"
            "[기존 사건 사실(Fact)]\n"
            "- 출처 문서/참조: {fact_doc}\n"
            "- 분류: {fact_type} (범위: {fact_scope})\n"
            "- 주어/대상: {fact_subject} | 속성/행위: {fact_predicate} | 시점맥락: {fact_temporal}\n"
            "- 역할별 정규화 금액(KRW): {fact_amounts} | 역할별 정규화 날짜: {fact_dates} | 극성: {fact_polarity}\n"
            "- 사실 원문: {fact_stmt}\n\n"
            "위 두 진술의 관계를 판정하세요.",
        ),
    ])

    payload = {
        "claim_doc": claim_slots.document_name or claim_slots.evidence_id or "신규 증거 문서",
        "claim_type": claim_slots.claim_type,
        "claim_scope": claim_slots.scope,
        "claim_subject": claim_slots.subject_key or "(미지정)",
        "claim_predicate": claim_slots.predicate_key or "(미지정)",
        "claim_temporal": claim_slots.temporal_context or "(미지정)",
        "claim_amounts": claim_slots.amount_roles or claim_slots.normalized_amounts,
        "claim_dates": claim_slots.date_roles or claim_slots.normalized_dates,
        "claim_polarity": claim_slots.polarity,
        "claim_stmt": claim_slots.statement,
        "fact_doc": fact_slots.document_name or fact_slots.evidence_id or "기존 사건 사실",
        "fact_type": fact_slots.claim_type,
        "fact_scope": fact_slots.scope,
        "fact_subject": fact_slots.subject_key or "(미지정)",
        "fact_predicate": fact_slots.predicate_key or "(미지정)",
        "fact_temporal": fact_slots.temporal_context or "(미지정)",
        "fact_amounts": fact_slots.amount_roles or fact_slots.normalized_amounts,
        "fact_dates": fact_slots.date_roles or fact_slots.normalized_dates,
        "fact_polarity": fact_slots.polarity,
        "fact_stmt": fact_slots.statement,
    }

    cur_span = get_current_span_id()
    try:
        llm = get_llm(temperature=0.0)
        try:
            structured_llm = llm.with_structured_output(_LLMConflictVerificationSchema, method="function_calling")
            res = (prompt | structured_llm).invoke(payload)
            if isinstance(res, _LLMConflictVerificationSchema):
                if cur_span:
                    try:
                        update_span(cur_span, {
                            "stage3_llm_called": True,
                            "stage3_status": res.status,
                            "stage3_reason_code": res.reason_code,
                        })
                    except Exception:
                        pass
                return res
        except Exception as e:
            logger.debug(f"[CONFLICT_DETECTOR] LLM structured verification fallback: {e}")

        raw_res = (prompt | llm).invoke(payload)
        text = getattr(raw_res, "content", str(raw_res)).strip()
        if text.startswith("```json"):
            text = text[7:-3].strip()
        elif text.startswith("```"):
            text = text[3:-3].strip()
        data = json.loads(text)
        parsed = _LLMConflictVerificationSchema(**data)
        if cur_span:
            try:
                update_span(cur_span, {
                    "stage3_llm_called": True,
                    "stage3_status": parsed.status,
                    "stage3_reason_code": parsed.reason_code,
                })
            except Exception:
                pass
        return parsed
    except Exception as e:
        logger.warning(f"[CONFLICT_DETECTOR] Stage 3 LLM verification failed safely: {type(e).__name__}: {e}")
        if cur_span:
            try:
                update_span(cur_span, {
                    "stage3_llm_called": True,
                    "stage3_error": type(e).__name__,
                })
            except Exception:
                pass
        return None


def _are_amount_roles_compatible(role_a: str, role_b: str, amounts_equal: bool) -> bool:
    """두 금액 역할(Semantic Role)이 동일 속성이어서 직접 비교 가능한지 판별한다."""
    if role_a == role_b:
        return True
    if "GENERAL_AMOUNT" in (role_a, role_b):
        return True
    # 보증금 원금(PRINCIPAL_DEPOSIT)과 반환 요청 금액(RETURN_REQUEST_AMOUNT)은
    # 전액 반환을 요청하는 경우(금액이 같을 때) 상호 일치(CONSISTENT)로 볼 수 있음
    if {role_a, role_b} == {"PRINCIPAL_DEPOSIT", "RETURN_REQUEST_AMOUNT"} and amounts_equal:
        return True
    return False


def evaluate_claim_against_fact(
    claim_slots: StructuredFactSlots,
    fact: Fact,
    fact_doc_name: Optional[str] = None,
    claim_id: Optional[str] = None,
    source_span_ids: Optional[List[str]] = None,
    enable_llm_verification: Optional[bool] = None,
) -> ConflictDecision:
    """단일 Claim 슬롯과 단일 기존 Fact를 3단계 파이프라인으로 비교하여 ConflictDecision을 반환한다.

    Args:
        claim_slots: 신규 Claim의 구조화 슬롯.
        fact: 비교 대상 기존 Fact 엔티티.
        fact_doc_name: 기존 Fact의 출처 문서명 (있는 경우).
        claim_id: Claim 식별자.
        source_span_ids: 근거 원문 Span ID 목록.
        enable_llm_verification: Stage 3 선택적 LLM 검증 활성화 여부 (None이면 환경변수 따름).

    Returns:
        ConflictDecision: 구조화된 비교 판정 결과.
    """
    spans = list(source_span_ids or [])
    use_llm = _should_use_llm_verification(enable_llm_verification)

    fact_slots = build_structured_slots(
        statement=getattr(fact, "statement", "") or "",
        claim_type=getattr(fact, "fact_type", "GENERAL"),
        evidence_id=getattr(fact, "source_ref", None),
        document_name=fact_doc_name,
    )

    # ------------------------------------------------------------------
    # Stage 0: 빈 문장 또는 잘못된 날짜(달력상 존재하지 않는 날짜) 검증 (Section 3.4)
    # ------------------------------------------------------------------
    if not (claim_slots.statement or "").strip() or not (fact_slots.statement or "").strip():
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="INSUFFICIENT_INFORMATION",
            reason_code="EMPTY_STATEMENT",
            explanation="비교할 진술 내용이 비어 있어 상충 여부를 판단할 수 없습니다.",
            confidence=1.0,
            source_span_ids=spans,
        )

    if claim_slots.invalid_dates or fact_slots.invalid_dates:
        bad = claim_slots.invalid_dates or fact_slots.invalid_dates
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="INSUFFICIENT_INFORMATION",
            reason_code="INVALID_CALENDAR_DATE",
            explanation=f"달력상 존재하지 않는 비정상 일자({', '.join(bad)})가 포함되어 있어 정확한 비교를 위해 원문 일자 확인이 필요합니다.",
            confidence=1.0,
            source_span_ids=spans,
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

    # 1-2. Fact Semantic & Temporal Comparability Gate (v1.2 P0-01 ~ P0-04)
    claim_sem = claim_slots.semantic_fact or extract_semantic_fact(
        claim_slots.statement,
        context={
            "document_name": claim_slots.document_name,
            "claim_type": claim_slots.claim_type,
            "subject_key": claim_slots.subject_key,
            "predicate_key": claim_slots.predicate_key,
            "evidence_id": claim_slots.evidence_id,
        },
    )
    fact_sem = fact_slots.semantic_fact or extract_semantic_fact(
        fact_slots.statement,
        context={
            "document_name": fact_doc_name or fact_slots.document_name,
            "claim_type": fact.fact_type,
            "subject_key": fact_slots.subject_key,
            "predicate_key": fact_slots.predicate_key,
            "evidence_id": fact.source_ref or fact_slots.evidence_id,
        },
    )
    comp_gate = compare_fact_identity(claim_sem, fact_sem)
    if not comp_gate.is_comparable:
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status=comp_gate.status,
            reason_code=comp_gate.reason_code,
            explanation=comp_gate.explanation,
            confidence=0.95,
            source_span_ids=spans,
            subject_match_basis=comp_gate.subject_match_basis,
            predicate_match_basis=comp_gate.predicate_match_basis,
            temporal_semantics=comp_gate.temporal_semantics,
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

    # 1-3. 값 차원(Value Dimension) 불일치 차단: 순수 날짜(DATE) vs 순수 금액(AMOUNT)
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

    # 1-4. 공통 내용어 토큰 확인 (단, 양쪽 모두 구체적 금액 역할이 식별된 경우에는 금액 역할 비교를 우선 수행)
    shared_tokens = _find_shared_concepts(claim_slots.content_tokens, fact_slots.content_tokens)
    if not shared_tokens:
        if claim_slots.normalized_amounts and fact_slots.normalized_amounts:
            c_spec_roles = set(claim_slots.amount_roles.keys()) - {"GENERAL_AMOUNT"}
            f_spec_roles = set(fact_slots.amount_roles.keys()) - {"GENERAL_AMOUNT"}
            if c_spec_roles and f_spec_roles and c_spec_roles != f_spec_roles:
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="DIFFERENT_CONTEXT",
                    reason_code="DIFFERENT_AMOUNT_ATTRIBUTE",
                    explanation="비교 대상 금액의 성격(예: 약정 원금 vs 일부 반환금·계약금·차임 등)이 서로 다른 별개 사실입니다.",
                    confidence=0.95,
                    source_span_ids=spans,
                )
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="DIFFERENT_CONTEXT",
            reason_code="UNRELATED_SUBJECT",
            explanation="공유하는 사실 대상이나 핵심 속성이 없는 별개의 사실입니다.",
            confidence=0.95,
            source_span_ids=spans,
        )

    # ------------------------------------------------------------------
    # Stage 2: Normalized Rule Verification (역할별 금액·날짜 및 부정 범위 비교)
    # ------------------------------------------------------------------
    c_amounts = claim_slots.normalized_amounts
    f_amounts = fact_slots.normalized_amounts
    c_dates = claim_slots.normalized_dates
    f_dates = fact_slots.normalized_dates

    # 2-1. 양쪽 모두 금액을 포함하는 경우: 금액의 의미적 역할(Role) 기반 비교 (Section 3.3 & 3.4)
    if c_amounts and f_amounts:
        c_roles = claim_slots.amount_roles or {"GENERAL_AMOUNT": c_amounts}
        f_roles = fact_slots.amount_roles or {"GENERAL_AMOUNT": f_amounts}

        # 변경/갱신 계약 금액이 포함된 경우 추가 경위 확인(POTENTIAL_CONFLICT)
        if "MODIFIED_CONTRACT_AMOUNT" in c_roles or "MODIFIED_CONTRACT_AMOUNT" in f_roles:
            if set(c_amounts) != set(f_amounts):
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="POTENTIAL_CONFLICT",
                    reason_code="CONTRACT_MODIFICATION_OR_RENEWAL_CHECK",
                    explanation="최초 약정 금액과 변경·갱신 금액 간의 차이일 수 있으므로 계약 변경 경위 확인이 필요합니다.",
                    confidence=0.85,
                    source_span_ids=spans,
                )

        # 역할별 매칭 탐색
        matched_same_role_equal = False
        matched_same_role_diff: Optional[Tuple[str, List[int], List[int]]] = None
        only_different_roles = True

        for cr, c_vals in c_roles.items():
            for fr, f_vals in f_roles.items():
                vals_equal = set(c_vals) == set(f_vals)
                if _are_amount_roles_compatible(cr, fr, vals_equal):
                    only_different_roles = False
                    if vals_equal:
                        matched_same_role_equal = True
                    else:
                        matched_same_role_diff = (cr if cr != "GENERAL_AMOUNT" else fr, c_vals, f_vals)

        # 서로 다른 금액 속성인 경우 (예: T03 계약 보증금 3억 vs 일부 반환금 2억) -> DIFFERENT_CONTEXT
        if only_different_roles:
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_AMOUNT_ATTRIBUTE",
                explanation="비교 대상 금액의 성격(예: 약정 원금 vs 일부 반환금·계약금·차임 등)이 서로 다른 별개 사실입니다.",
                confidence=0.95,
                source_span_ids=spans,
            )

        # 가압류 / 근저당권 등 부동산 등기부상 권리 설정 금액인 경우 복수 건 공존 가능
        if (
            claim_sem.event_type == "ENCUMBRANCE"
            or fact_sem.event_type == "ENCUMBRANCE"
            or any(kw in (claim_slots.statement + " " + fact_slots.statement) for kw in ("가압류", "근저당권", "압류"))
        ):
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_EVENT_INSTANCE",
                explanation="부동산 등기부상 채권자 또는 청구금액이 서로 다른 별개의 가압류·권리설정 건입니다.",
                confidence=0.95,
                source_span_ids=spans,
            )

        # 동일 역할 금액이 다른 경우 (예: T02 동일 계약 보증금 3억 vs 2억)
        if matched_same_role_diff is not None and not matched_same_role_equal:
            _, diff_c_vals, diff_f_vals = matched_same_role_diff
            if use_llm:
                llm_ver = _verify_pair_with_llm(claim_slots, fact_slots)
                if llm_ver is not None:
                    return ConflictDecision(
                        claim_id=claim_id,
                        target_fact_id=fact.id,
                        status=llm_ver.status,
                        reason_code=llm_ver.reason_code,
                        explanation=llm_ver.explanation,
                        confidence=llm_ver.confidence,
                        source_span_ids=spans,
                        llm_verified=True,
                    )
                # T13: Stage 3 LLM 검증이 활성화되었으나 호출 실패 시 확정 모순을 강행하지 않고 안전 폴백
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="POTENTIAL_CONFLICT",
                    reason_code="LLM_VERIFICATION_UNAVAILABLE",
                    explanation=(
                        f"동일 항목({', '.join(sorted(shared_tokens)[:3])})의 금액 차이"
                        f"({', '.join(f'{a:,}원' for a in diff_c_vals)} vs {', '.join(f'{a:,}원' for a in diff_f_vals)})가 "
                        "감지되어 추가 확인이 필요합니다."
                    ),
                    confidence=0.75,
                    source_span_ids=spans,
                )

            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="CONTRADICTION",
                reason_code="MUTUALLY_EXCLUSIVE_AMOUNT",
                explanation=(
                    f"동일 항목({', '.join(sorted(shared_tokens)[:3])})에 대해 "
                    f"신규 진술 금액({', '.join(f'{a:,}원' for a in sorted(diff_c_vals))})과 "
                    f"기존 사실 금액({', '.join(f'{a:,}원' for a in sorted(diff_f_vals))})이 상충합니다."
                ),
                confidence=0.92,
                source_span_ids=spans,
            )

        # 동일 역할 금액이 일치하는 경우 (matched_same_role_equal == True)
        if matched_same_role_equal and claim_slots.polarity == fact_slots.polarity:
            # Section 3.4: 양쪽 모두 날짜가 있는 경우에는 날짜도 호환되어야 CONSISTENT로 확정
            if c_dates and f_dates and set(c_dates) != set(f_dates):
                c_date_roles = set(claim_slots.date_roles.keys())
                f_date_roles = set(fact_slots.date_roles.keys())
                if c_date_roles & f_date_roles:
                    return ConflictDecision(
                        claim_id=claim_id,
                        target_fact_id=fact.id,
                        status="POTENTIAL_CONFLICT",
                        reason_code="SAME_AMOUNT_BUT_DATE_DISCREPANCY",
                        explanation=(
                            f"금액({sorted(c_amounts)[0]:,}원)은 일치하나 "
                            f"동일 행위의 일자({', '.join(c_dates)} vs {', '.join(f_dates)})가 달라 확인이 필요합니다."
                        ),
                        confidence=0.82,
                        source_span_ids=spans,
                    )
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="DIFFERENT_CONTEXT",
                    reason_code="COMPATIBLE_AMOUNT_DIFFERENT_TIMELINE_EVENT",
                    explanation="언급된 금액은 동일하며 서로 다른 시점의 후속 절차·이벤트를 설명하는 진술입니다.",
                    confidence=0.92,
                    source_span_ids=spans,
                )

            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="CONSISTENT",
                reason_code="NORMALIZED_AMOUNT_MATCH",
                explanation=f"정규화된 금액({sorted(c_amounts)[0]:,}원)이 기존 사실과 일치합니다.",
                confidence=0.98,
                source_span_ids=spans,
            )

    # 2-2. 양쪽 모두 날짜를 포함하는 경우: 날짜 역할(Date Role) 기반 비교 (Section 3.4)
    if c_dates and f_dates:
        if set(c_dates) == set(f_dates):
            if claim_slots.polarity == fact_slots.polarity:
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="CONSISTENT",
                    reason_code="NORMALIZED_DATE_MATCH",
                    explanation=f"정규화된 일자({', '.join(sorted(c_dates))})가 기존 사실과 일치합니다.",
                    confidence=0.95,
                    source_span_ids=spans,
                )
            # 날짜가 동일하나 서술 극성(polarity)이 다른 경우: 날짜 불일치가 아니므로 아래 2-3 서술 극성 비교로 위임
        else:
            c_d_roles = set(claim_slots.date_roles.keys()) - {"GENERAL_DATE"}
            f_d_roles = set(fact_slots.date_roles.keys()) - {"GENERAL_DATE"}

            # T06: 최초 만기일(EXPIRATION_DATE) vs 갱신일(RENEWAL_DATE) 또는 갱신 후 퇴거/반환 요청일
            has_renewal_clue = (
                "RENEWAL_DATE" in (c_d_roles | f_d_roles)
                or bool(re.search(r"갱신|연장|재계약|만기\s*이후", claim_slots.statement + " " + fact_slots.statement))
            )
            if has_renewal_clue and ("EXPIRATION_DATE" in (c_d_roles | f_d_roles) or "RETURN_REQUEST_DATE" in (c_d_roles | f_d_roles)):
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="POTENTIAL_CONFLICT",
                    reason_code="TEMPORAL_GAP_OR_RENEWAL_CHECK",
                    explanation=(
                        f"최초 약정 일자({', '.join(sorted(f_dates))})와 후속 일자({', '.join(sorted(c_dates))}) 사이에 "
                        "묵시적 갱신 또는 계약 연장 경위에 대한 추가 확인이 필요합니다."
                    ),
                    confidence=0.85,
                    source_span_ids=spans,
                )

            # T04: 날짜 역할이 명확히 서로 다른 경우 (예: 계약 체결일 CONTRACT_DATE vs 반환 요청일 RETURN_REQUEST_DATE)
            if c_d_roles and f_d_roles and not (c_d_roles & f_d_roles):
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="DIFFERENT_CONTEXT",
                    reason_code="DIFFERENT_DATE_ROLE",
                    explanation="서로 다른 성격의 일자(예: 계약 체결일·만기일·통지일·반환 요청일 등)에 관한 별개 사실입니다.",
                    confidence=0.95,
                    source_span_ids=spans,
                )

            # T05: 동일한 날짜 역할(예: 동일 지급행위 ACTUAL_PAYMENT_OR_RETURN_DATE)이거나 핵심 토큰 유사도가 높은 경우
            same_date_role = bool(c_d_roles and f_d_roles and (c_d_roles & f_d_roles))
            union_tokens = set(claim_slots.content_tokens) | set(fact_slots.content_tokens)
            jaccard = len(shared_tokens) / max(len(union_tokens), 1)

            if not same_date_role and jaccard < 0.5:
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="DIFFERENT_CONTEXT",
                    reason_code="DIFFERENT_TIMELINE_EVENT",
                    explanation="서로 다른 시점의 개별 이벤트 또는 후속 절차에 관한 일자입니다.",
                    confidence=0.9,
                    source_span_ids=spans,
                )

            if use_llm:
                llm_ver = _verify_pair_with_llm(claim_slots, fact_slots)
                if llm_ver is not None:
                    return ConflictDecision(
                        claim_id=claim_id,
                        target_fact_id=fact.id,
                        status=llm_ver.status,
                        reason_code=llm_ver.reason_code,
                        explanation=llm_ver.explanation,
                        confidence=llm_ver.confidence,
                        source_span_ids=spans,
                        llm_verified=True,
                    )

            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="POTENTIAL_CONFLICT",
                reason_code="SAME_EVENT_DATE_DISCREPANCY",
                explanation=(
                    f"동일하거나 유사한 행위({', '.join(sorted(shared_tokens)[:3])})에 대해 "
                    f"일자({', '.join(sorted(c_dates))} vs {', '.join(sorted(f_dates))})가 달라 경위 재검증이 필요합니다."
                ),
                confidence=0.82,
                source_span_ids=spans,
            )

    # 2-3. 서술 극성(긍정 vs 부정) 및 부정 적용 범위 비교 (Section 3.5 & T07 & v1.2)
    if claim_slots.polarity != fact_slots.polarity:
        # 1) 인식 불확실성(UNCONFIRMED: 미확인, 확인되지 않음)은 부정이 아니므로 상충 금지
        if "UNCONFIRMED" in (claim_slots.polarity, fact_slots.polarity):
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="DIFFERENT_CONTEXT",
                reason_code="EPISTEMIC_STATUS_NOT_CONTRADICTION",
                explanation="사실의 확인 여부(미확인 또는 확인 불가)에 관한 진술은 긍정 사실과 상충하지 않는 별개 진술입니다.",
                confidence=0.95,
                source_span_ids=spans,
                subject_match_basis="Epistemic status check",
            )

        # 2) 인용절 통지(REPORTED_NEGATIVE: '반환할 수 없다고 통보하였다')나 이중 부정(DOUBLE_NEGATIVE: '거절하지 않았다')은
        # 단순 이행/불이행(AFFIRMATIVE/NEGATIVE)과 서술 층위가 다르므로 즉시 모순으로 단정하지 않음
        if "REPORTED_NEGATIVE" in (claim_slots.polarity, fact_slots.polarity) or "DOUBLE_NEGATIVE" in (
            claim_slots.polarity,
            fact_slots.polarity,
        ):
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_NEGATION_SCOPE_OR_SPEECH_ACT",
                explanation="의사표시 통지 사실 또는 이중 부정 표현으로 실제 이행 여부와 서술 범위가 다른 별개 진술입니다.",
                confidence=0.9,
                source_span_ids=spans,
            )

        # 3) 한쪽은 AFFIRMATIVE, 다른 한쪽은 NEGATIVE인 경우:
        # 가. 급부 대상(Object) 차이 검증: 열쇠·출입카드(목적물 인도) vs 보증금·차임(금전 지급)
        c_is_key = any(kw in claim_slots.statement for kw in ("출입카드", "열쇠", "비밀번호", "목적물 인도", "명도"))
        f_is_key = any(kw in fact_slots.statement for kw in ("출입카드", "열쇠", "비밀번호", "목적물 인도", "명도"))
        c_is_deposit = any(kw in claim_slots.statement for kw in ("보증금", "전세금", "차임", "월세", "청구금액"))
        f_is_deposit = any(kw in fact_slots.statement for kw in ("보증금", "전세금", "차임", "월세", "청구금액"))
        if (c_is_key and f_is_deposit) or (f_is_key and c_is_deposit):
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_PERFORMANCE_OBJECT",
                explanation="목적물 인도(열쇠·출입카드 반환) 의무와 보증금 반환 의무는 서로 다른 별개의 법률상 급부 대상입니다.",
                confidence=0.98,
                source_span_ids=spans,
            )

        # 나. 화행 차이 검증: 이행 청구·반환 요청 vs 미이행·미반환 상태 (요청과 불이행은 양립)
        c_is_req = any(kw in claim_slots.statement for kw in ("요청", "청구", "독촉", "통지", "알려달라", "알려달라고"))
        f_is_req = any(kw in fact_slots.statement for kw in ("요청", "청구", "독촉", "통지", "알려달라", "알려달라고"))
        c_is_non_perf = claim_slots.polarity in ("NEGATIVE", "REPORTED_NEGATIVE") or any(
            kw in claim_slots.statement for kw in ("반환되지 않", "미반환", "지급되지 않", "돌려받지 못", "반환하지 않")
        )
        f_is_non_perf = fact_slots.polarity in ("NEGATIVE", "REPORTED_NEGATIVE") or any(
            kw in fact_slots.statement for kw in ("반환되지 않", "미반환", "지급되지 않", "돌려받지 못", "반환하지 않")
        )
        if (c_is_req and f_is_non_perf) or (f_is_req and c_is_non_perf):
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="CONSISTENT",
                reason_code="REQUEST_ACCOMPANIES_NON_PERFORMANCE",
                explanation="이행 청구·반환 요청 사실과 미반환·불이행 상태는 법률적으로 양립 가능하며 모순이 아닙니다.",
                confidence=0.95,
                source_span_ids=spans,
            )

        # 부정 대상 서술어(negated_predicate)와 긍정 핵심 서술어(core_predicate)가 실제로 일치하고,
        # 이벤트 유형이 호환될 때만 상충 검토 (토큰 수 2개 이상만으로 모순 판정 금지)
        c_pred = claim_slots.negated_predicate or claim_slots.core_predicate or claim_slots.predicate_key
        f_pred = fact_slots.negated_predicate or fact_slots.core_predicate or fact_slots.predicate_key
        predicates_match = bool(c_pred and f_pred and (c_pred == f_pred or c_pred in f_pred or f_pred in c_pred))
        event_types_compatible = (
            claim_sem.event_type == fact_sem.event_type
            and (claim_sem.event_subtype == fact_sem.event_subtype or not claim_sem.event_subtype or not fact_sem.event_subtype)
        )
        # 서술어 외에 행위 대상(목적어 또는 실질 체언)이 공유되는지 확인
        shared_entity_tokens = set(shared_tokens) - {c_pred, f_pred, "하다", "되다", "이다", "않다", "없다"}
        has_common_entity = bool(shared_entity_tokens) or (
            claim_slots.subject_key
            and fact_slots.subject_key
            and claim_slots.subject_key == fact_slots.subject_key
            and claim_slots.subject_key not in ("하다", "되다", "이다")
        )

        if predicates_match and event_types_compatible and has_common_entity:
            # 만약 두 진술의 날짜가 명시적으로 서로 다르면 시점 변화에 따른 상태 변화(POTENTIAL_CONFLICT)
            if c_dates and f_dates and set(c_dates) != set(f_dates):
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="POTENTIAL_CONFLICT",
                    reason_code="TEMPORAL_SEQUENCE_POLARITY_CHANGE",
                    explanation="서로 다른 시점에서의 이행·불이행 상태 변화일 수 있으므로 시간 순서 확인이 필요합니다.",
                    confidence=0.82,
                    source_span_ids=spans,
                )

            if use_llm:
                llm_ver = _verify_pair_with_llm(claim_slots, fact_slots)
                if llm_ver is not None:
                    return ConflictDecision(
                        claim_id=claim_id,
                        target_fact_id=fact.id,
                        status=llm_ver.status,
                        reason_code=llm_ver.reason_code,
                        explanation=llm_ver.explanation,
                        confidence=llm_ver.confidence,
                        source_span_ids=spans,
                        llm_verified=True,
                    )
                return ConflictDecision(
                    claim_id=claim_id,
                    target_fact_id=fact.id,
                    status="POTENTIAL_CONFLICT",
                    reason_code="LLM_VERIFICATION_UNAVAILABLE",
                    explanation="동일 사실 대상에 대해 긍정·부정 진술 차이가 감지되어 추가 확인이 필요합니다.",
                    confidence=0.75,
                    source_span_ids=spans,
                )

            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status="CONTRADICTION",
                reason_code="OPPOSITE_POLARITY_ON_SAME_SUBJECT",
                explanation=(
                    f"동일 사실 대상({', '.join(sorted(shared_tokens)[:3])})에 대해 "
                    "긍정 진술과 부정 진술이 동시에 참일 수 없어 상충합니다."
                ),
                confidence=0.9,
                source_span_ids=spans,
            )

    # ------------------------------------------------------------------
    # Stage 3: Selective LLM Semantic Verification (일반 텍스트 조건·의무 비교)
    # ------------------------------------------------------------------
    if use_llm and len(shared_tokens) >= 2:
        llm_ver = _verify_pair_with_llm(claim_slots, fact_slots)
        if llm_ver is not None:
            return ConflictDecision(
                claim_id=claim_id,
                target_fact_id=fact.id,
                status=llm_ver.status,
                reason_code=llm_ver.reason_code,
                explanation=llm_ver.explanation,
                confidence=llm_ver.confidence,
                source_span_ids=spans,
                llm_verified=True,
            )
        return ConflictDecision(
            claim_id=claim_id,
            target_fact_id=fact.id,
            status="POTENTIAL_CONFLICT",
            reason_code="LLM_VERIFICATION_UNAVAILABLE",
            explanation=(
                f"동일 사실 대상({', '.join(sorted(shared_tokens)[:3])})에 관한 진술이나 "
                "세부 조건의 양립 가능 여부에 대해 추가 확인이 필요합니다."
            ),
            confidence=0.75,
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
    temporal_context: Optional[str] = None,
    evidence_id: Optional[str] = None,
    document_name: Optional[str] = None,
    claim_id: Optional[str] = None,
    source_span_ids: Optional[List[str]] = None,
    llm_suggested_fact_id: Optional[str] = None,
    fact_doc_names: Optional[Dict[str, str]] = None,
    enable_llm_verification: Optional[bool] = None,
) -> Dict[str, List[ConflictDecision]]:
    """신규 Claim을 사건의 기존 Fact 전체와 비교하여 5단계 상태별 ConflictDecision 목록을 반환한다.

    Returns:
        Dict[str, List[ConflictDecision]]:
            - "contradictions": 명백한 모순(CONTRADICTION) 목록
            - "potential_conflicts": 추가 경위 확인 필요(POTENTIAL_CONFLICT) 목록
            - "consistent": 정규화 수치/내용이 일치하여 상호 지지(CONSISTENT)하는 목록
            - "different_context": 별개 맥락(DIFFERENT_CONTEXT) 목록
            - "insufficient_information": 정보 부족/비정상 날짜(INSUFFICIENT_INFORMATION) 목록
    """
    result: Dict[str, List[ConflictDecision]] = {
        "contradictions": [],
        "potential_conflicts": [],
        "consistent": [],
        "different_context": [],
        "insufficient_information": [],
    }
    if not statement or not existing_facts:
        return result

    claim_slots = build_structured_slots(
        statement=statement,
        claim_type=claim_type,
        subject=subject,
        predicate=predicate,
        scope=scope,
        temporal_context=temporal_context,
        evidence_id=evidence_id,
        document_name=document_name,
    )

    doc_name_map = fact_doc_names or {}

    for fact in existing_facts:
        decision = evaluate_claim_against_fact(
            claim_slots=claim_slots,
            fact=fact,
            fact_doc_name=doc_name_map.get(fact.id),
            claim_id=claim_id,
            source_span_ids=source_span_ids,
            enable_llm_verification=enable_llm_verification,
        )
        if decision.status == "CONTRADICTION":
            result["contradictions"].append(decision)
        elif decision.status == "POTENTIAL_CONFLICT":
            result["potential_conflicts"].append(decision)
        elif decision.status == "CONSISTENT":
            result["consistent"].append(decision)
        elif decision.status == "INSUFFICIENT_INFORMATION":
            result["insufficient_information"].append(decision)
        else:
            result["different_context"].append(decision)

    return result


def reconcile_case_conflicts(
    db: Session,
    case_id: Optional[str] = None,
    allow_all_cases: bool = False,
    dry_run: bool = False,
    sync_neo4j: bool = True,
) -> Dict[str, Any]:
    """기존 PostgreSQL 및 Neo4j에 저장된 오탐 상충 데이터를 3단계 엔진으로 재평가하여 복구한다 (P1-04).

    [안전 및 정합성 보장 원칙]
    1. 사건 단위 복구를 기본으로 하며, `case_id=None`으로 전체 사건을 일괄 복구하려면
       반드시 `allow_all_cases=True`를 명시해야 한다.
    2. `dry_run=True`일 때는 변경 예정 내역(`changes`)과 통계만 계산하고 트랜잭션을 롤백하여
       DB를 수정하지 않는다.
    3. 원본 문서(EvidenceDocument), Span, 승인 상태(APPROVED/EDITED/REJECTED),
       리뷰 감사 이력(EvidenceReview)은 절대 삭제·훼손하지 않는다.
    4. 변경된 사건은 PostgreSQL `GraphSyncTask` 큐에 등록하여 Neo4j 장애 시에도 재시도 가능하게 보장한다.

    Args:
        db: SQLAlchemy 데이터베이스 세션.
        case_id: 복구할 대상 사건 ID (None이면 allow_all_cases=True 필요).
        allow_all_cases: 전체 사건 일괄 복구 허용 여부.
        dry_run: True이면 실제 커밋 없이 변경 전후 시뮬레이션 결과만 반환.
        sync_neo4j: 커밋 후 즉시 Neo4j 동기화 시도 여부.

    Returns:
        Dict[str, Any]: 정리 통계, 영향받은 사건 ID 목록, 상세 변경 전후 기록(changes).
    """
    if case_id is None and not allow_all_cases:
        raise ValueError("전체 사건 일괄 복구를 수행하려면 case_id를 지정하거나 allow_all_cases=True를 명시해야 합니다.")

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
    changes: List[Dict[str, Any]] = []

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

        # 1. 기존 CONTRADICTS 및 POTENTIAL_CONFLICT EvidenceLink 재검증
        conflict_links = (
            db.query(EvidenceLink)
            .join(EvidenceDocument, EvidenceLink.evidence_id == EvidenceDocument.id)
            .filter(
                EvidenceDocument.case_id == cid,
                EvidenceLink.link_type.in_(["CONTRADICTS", "POTENTIAL_CONFLICT"]),
            )
            .all()
        )
        for link in conflict_links:
            claim = db.query(EvidenceClaim).filter_by(id=link.claim_id).first() if link.claim_id else None
            if not claim or claim.review_status == "REJECTED":
                changes.append({
                    "entity": "EvidenceLink",
                    "id": link.id,
                    "before": link.link_type,
                    "after": "DELETED (REJECTED_OR_MISSING_CLAIM)",
                })
                db.delete(link)
                removed_links += 1
                case_changed = True
                continue

            if link.target_type == "FACT":
                target_fact = fact_map.get(link.target_id)
                if not target_fact:
                    changes.append({
                        "entity": "EvidenceLink",
                        "id": link.id,
                        "before": link.link_type,
                        "after": "DELETED (MISSING_TARGET_FACT)",
                    })
                    db.delete(link)
                    removed_links += 1
                    case_changed = True
                    continue

                claim_doc = doc_map.get(claim.evidence_id)
                claim_slots = build_structured_slots(
                    statement=claim.statement or "",
                    claim_type=claim.claim_type,
                    subject=claim.subject_key,
                    predicate=claim.predicate_key,
                    scope=claim.scope,
                    temporal_context=claim.temporal_context,
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
                if decision.status != link.link_type:
                    if decision.status == "CONTRADICTION":
                        changes.append({
                            "entity": "EvidenceLink",
                            "id": link.id,
                            "before": link.link_type,
                            "after": "CONTRADICTION",
                            "reason_code": decision.reason_code,
                        })
                        link.link_type = "CONTRADICTION"
                        case_changed = True
                    elif decision.status == "POTENTIAL_CONFLICT":
                        changes.append({
                            "entity": "EvidenceLink",
                            "id": link.id,
                            "before": link.link_type,
                            "after": "POTENTIAL_CONFLICT",
                            "reason_code": decision.reason_code,
                        })
                        link.link_type = "POTENTIAL_CONFLICT"
                        case_changed = True
                    elif decision.status == "CONSISTENT" and claim.review_status in ("APPROVED", "EDITED"):
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
                            changes.append({
                                "entity": "EvidenceLink",
                                "id": link.id,
                                "before": link.link_type,
                                "after": "SUPPORTS",
                                "reason_code": decision.reason_code,
                            })
                            link.link_type = "SUPPORTS"
                            converted_supports += 1
                        else:
                            changes.append({
                                "entity": "EvidenceLink",
                                "id": link.id,
                                "before": link.link_type,
                                "after": "DELETED (DUPLICATE_SUPPORTS)",
                                "reason_code": decision.reason_code,
                            })
                            db.delete(link)
                            removed_links += 1
                        case_changed = True
                    else:
                        changes.append({
                            "entity": "EvidenceLink",
                            "id": link.id,
                            "before": link.link_type,
                            "after": f"DELETED ({decision.status}:{decision.reason_code})",
                            "reason_code": decision.reason_code,
                        })
                        db.delete(link)
                        removed_links += 1
                        case_changed = True

        db.flush()

        # 2. EvidenceClaim의 구조화 슬롯 백필 및 CONTRADICTION_CANDIDATE 상태 재검증
        all_case_claims = db.query(EvidenceClaim).filter(EvidenceClaim.case_id == cid).all()
        for claim in all_case_claims:
            claim_doc = doc_map.get(claim.evidence_id)
            slots = build_structured_slots(
                statement=claim.statement or "",
                claim_type=claim.claim_type,
                subject=claim.subject_key,
                predicate=claim.predicate_key,
                scope=claim.scope,
                temporal_context=claim.temporal_context,
                evidence_id=claim.evidence_id,
                document_name=claim_doc.original_filename if claim_doc else None,
            )
            if not claim.subject_key and slots.subject_key:
                claim.subject_key = slots.subject_key
            if not claim.predicate_key and slots.predicate_key:
                claim.predicate_key = slots.predicate_key
            if not claim.scope or claim.scope != slots.scope:
                claim.scope = slots.scope
            if not claim.temporal_context and slots.temporal_context:
                claim.temporal_context = slots.temporal_context
            claim.structured_slots = slots.model_dump()

            if claim.assertion_status != "CONTRADICTION_CANDIDATE" and claim.claim_type != "CONTRADICTION":
                continue

            if claim.review_status == "REJECTED":
                if claim.assertion_status == "CONTRADICTION_CANDIDATE":
                    changes.append({
                        "entity": "EvidenceClaim",
                        "id": claim.id,
                        "before": "CONTRADICTION_CANDIDATE",
                        "after": "DOCUMENT_STATES",
                    })
                    claim.assertion_status = "DOCUMENT_STATES"
                    reset_claims += 1
                    case_changed = True
                continue

            other_facts = [
                f
                for f in case_facts
                if not (f.source_ref == claim.evidence_id and (f.statement or "").strip() == (claim.statement or "").strip())
            ]
            eval_res = evaluate_claim_conflicts(
                statement=claim.statement or "",
                existing_facts=other_facts,
                claim_type=claim.claim_type,
                subject=claim.subject_key,
                predicate=claim.predicate_key,
                scope=claim.scope,
                temporal_context=claim.temporal_context,
                evidence_id=claim.evidence_id,
                document_name=claim_doc.original_filename if claim_doc else None,
                claim_id=claim.id,
                fact_doc_names=fact_doc_names,
                enable_llm_verification=False,
            )
            if not eval_res["contradictions"] and not eval_res.get("potential_conflicts"):
                if claim.assertion_status == "CONTRADICTION_CANDIDATE":
                    changes.append({
                        "entity": "EvidenceClaim",
                        "id": claim.id,
                        "before": "CONTRADICTION_CANDIDATE",
                        "after": "DOCUMENT_STATES",
                    })
                    claim.assertion_status = "DOCUMENT_STATES"
                    reset_claims += 1
                    case_changed = True

        db.flush()

        # 3. 더 이상 승인된 CONTRADICTS 링크가 남아 있지 않은 DISPUTED Fact 복원
        for fact in case_facts:
            if fact.verification_status == "DISPUTED":
                remaining_contra = (
                    db.query(EvidenceLink)
                    .join(EvidenceClaim, EvidenceLink.claim_id == EvidenceClaim.id)
                    .filter(
                        EvidenceLink.target_type == "FACT",
                        EvidenceLink.target_id == fact.id,
                        EvidenceLink.link_type == "CONTRADICTS",
                        EvidenceClaim.review_status != "REJECTED",
                    )
                    .count()
                )
                if remaining_contra == 0:
                    new_ver_status = (
                        "DOCUMENT_VERIFIED"
                        if fact.source_type in ("DOCUMENT_SUPPORTED", "EVIDENCE_DERIVED")
                        else ("PARTY_ASSERTED" if fact.source_type == "PARTY_ALLEGATION" else "UNVERIFIED")
                    )
                    changes.append({
                        "entity": "Fact",
                        "id": fact.id,
                        "before": "DISPUTED",
                        "after": new_ver_status,
                    })
                    fact.verification_status = new_ver_status
                    restored_facts += 1
                    case_changed = True

        if case_changed:
            affected_cases.append(cid)

    if dry_run:
        db.rollback()
        return {
            "dry_run": True,
            "removed_links": removed_links,
            "removed_false_contradict_links": removed_links,
            "converted_supports_links": converted_supports,
            "reset_claims": reset_claims,
            "restored_facts": restored_facts,
            "restored_disputed_facts": restored_facts,
            "affected_case_ids": affected_cases,
            "changes": changes,
        }

    if affected_cases:
        from ai_legal_helper.database.graph_sync_worker import queue_sync_task
        for cid in affected_cases:
            queue_sync_task(db, cid)

    db.commit()

    if sync_neo4j and affected_cases:
        try:
            from ai_legal_helper.database.graph_sync import safe_sync_case
            for cid in affected_cases:
                safe_sync_case(cid)
        except Exception as e:
            logger.warning(f"[CONFLICT_DETECTOR] Neo4j sync after reconciliation warning: {e}")

    return {
        "dry_run": False,
        "removed_links": removed_links,
        "removed_false_contradict_links": removed_links,
        "converted_supports_links": converted_supports,
        "reset_claims": reset_claims,
        "restored_facts": restored_facts,
        "restored_disputed_facts": restored_facts,
        "affected_case_ids": affected_cases,
        "changes": changes,
    }
