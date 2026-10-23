# -*- coding: utf-8 -*-
"""
모듈명: fact_semantics.py

[모듈 개요]
사건의 사실(Fact) 및 증거 주장(EvidenceClaim) 문장으로부터
법적 의미 구조(SemanticFact), 거래 단계(Transaction Stage), 발생 사건 vs 지속 상태(Event vs State),
그리고 시점 의미(Temporal Semantics)를 정밀하게 추출하고 비교하는 의미 분석 핵심 엔진 모듈이다.

[배경 및 설계 원칙 (v1.2 P0-01 ~ P0-04, P1-01, P1-02)]
1. 날짜·금액 비교 전 사실 동일성(Fact Identity) 선행 검증:
   - 두 진술이 동일한 법률 사건에 속하거나 키워드를 공유한다는 이유만으로 상충 관계를 성립시키지 않는다.
   - 거래 단계(예: 계약금 vs 중도금 vs 잔금), 시점 의미(예: 지급기일 vs 실제지급일 vs 반환요청일),
     의미 범주(행위 Event vs 상태 State vs 의무 Obligation vs 인식상태 Epistemic Status)가 다르면
     비교 불가(DIFFERENT_CONTEXT)로 즉시 분류한다.
2. Event vs State 분리:
   - 특정 시점 행위(예: 최초 전입신고일 2022-03-02)와 이후 특정 시점 상태(예: 2026-10-15 기준 전입 유지 진술)는
     동일 명제가 아니므로 날짜 차이로 인한 POTENTIAL_CONFLICT를 원천 차단한다.
3. 반복적 의사소통 사건(Repeatable Communication Events) 보존:
   - 통지 발송, 문자 송수신, 통화, 방문 문의 등 시점마다 반복 발생 가능한 행위는 단일 고유 사건이 아니므로
     발생일시가 다르다고 해서 모순으로 판정하지 않는다.
4. 인식적 불확실성(Epistemic Status) 및 화행(Speech Act) 왜곡 방지:
   - '확인되지 않았다', '미확인이다', '알 수 없다' 등 증거 부존재·인식 상태는 부정 사실(NEGATIVE)이 아니며
     POLARITY='UNCONFIRMED'로 처리하여 일반 긍정 사실과의 OPPOSITE_POLARITY 상충 오탐을 방지한다.
5. 다중 도메인 일반화(Cross-Domain Generalization):
   - 주택임대차뿐만 아니라 부동산 매매(계약금/중도금/잔금/소유권이전등기), 근로계약(입사/급여/퇴사/체불),
     채권채무(대여/변제기/일부변제/잔존채무), 소송절차(소장제출/송달/변론기일/선고) 전반에 일관 적용된다.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from pydantic import BaseModel, Field

from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


# ==============================================================================
# 1. 사실 의미 데이터 모델 (SemanticFact, ComparabilityResult, TemporalRelationResult)
# ==============================================================================

class SemanticFact(BaseModel):
    """
    단일 Fact 또는 Claim의 법적 의미 구조 모델.
    
    진술문(statement)으로부터 추출된 대상, 행위, 범주, 거래 단계, 시점 의미,
    양립 가능성 판단에 필요한 메타데이터를 정규화하여 보관한다.
    """

    statement: str = Field(..., description="원본 진술문 문자열")
    subject_key: Optional[str] = Field(None, description="사실의 주체(행위자, 당사자, 채권자 등)")
    object_key: Optional[str] = Field(None, description="사실의 객체/대상(특정 계약, 가압류 건, 목적물 등)")
    predicate: Optional[str] = Field(None, description="핵심 서술어 또는 행위")
    
    # 의미 범주: 행위/사건(EVENT), 상태(STATE), 법적의무(OBLIGATION), 조건(CONDITION),
    # 인식/확인상태(EPISTEMIC_STATUS), 신원/자격(IDENTITY), 문서정보(METADATA)
    semantic_category: Literal[
        "EVENT",
        "STATE",
        "OBLIGATION",
        "CONDITION",
        "EPISTEMIC_STATUS",
        "IDENTITY",
        "METADATA",
        "UNKNOWN",
    ] = Field("UNKNOWN", description="사실의 법적 의미 범주")

    # 사건/행위 대분류
    event_type: Optional[str] = Field(
        None,
        description="이벤트 유형 (PAYMENT, RESIDENCE_REGISTRATION, CONTRACT_PERIOD, NOTICE, ENCUMBRANCE 등)",
    )

    # 거래 단계 및 세부 항목 (중요: 동일 event_type 내 상충 여부 가르는 핵심 슬롯)
    event_subtype: Optional[str] = Field(
        None,
        description="이벤트 세부 항목 (DOWN_PAYMENT, BALANCE_PAYMENT, PRINCIPAL_DEPOSIT, MOVE_IN, MOVEOUT 등)",
    )

    # 시간적 의미 유형
    temporal_type: Optional[Literal[
        "OCCURRED_AT",      # 실제 발생 시점
        "DUE_AT",           # 약정된 이행 기일 / 변제기 / 지급기일
        "SCHEDULED_AT",     # 예정된 시점
        "REQUESTED_AT",     # 요청 / 요구 기준 시점
        "EFFECTIVE_FROM",   # 기간 시작 (입주일, 계약시작일, 입사일)
        "EFFECTIVE_TO",     # 기간 종료 (만료일, 퇴거일, 퇴사일)
        "VALID_AT",         # 특정 시점의 지속 상태 확인 기준일
        "VALID_INTERVAL",   # 유효 기간 전체
        "REPORTED_AT",      # 통지·작성·열람 등 보고 시점
        "NONE",
    ]] = Field("NONE", description="시간 정보의 법적 의미 역할")

    temporal_value: Optional[str] = Field(None, description="정규화된 날짜/시점/기간 (YYYY-MM-DD 또는 범위)")
    temporal_qualifier: Optional[str] = Field(None, description="시점 수식어 (기준, 현재, 당시, 무렵 등)")

    # 발생 성격
    occurrence_status: Literal[
        "ACTUAL",               # 실제 발생 완료
        "SCHEDULED",            # 약정 기일 또는 미래 예정
        "REQUESTED",            # 일방의 반환/이행 요청
        "PROPOSED",             # 제안/협의안
        "ALLEGED",              # 일방 당사자의 진술/주장
        "UNCONFIRMED",          # 미확인 또는 확인 불가
    ] = Field("ACTUAL", description="사건의 발생·성립 성격")

    # 극성 (긍정/부정)
    polarity: Literal[
        "AFFIRMATIVE",          # 긍정 서술
        "NEGATIVE",             # 명시적 직접 부정
        "DOUBLE_NEGATIVE",      # 이중 부정 (예: 거절하지 않았다)
        "REPORTED_NEGATIVE",    # 간접 인용 부정
        "UNCONFIRMED",          # 인식 불확실 (미확인, 확인되지 않음)
    ] = Field("AFFIRMATIVE", description="진술의 긍정/부정 극성")

    # 반복 가능 사건 여부 (통지, 문자, 통화, 방문문의 등 다수 발생이 정상인 사건)
    is_repeatable_event: bool = Field(
        False,
        description="동일 계약 내에서 시점마다 여러 번 발생 가능한 행위(통지, 문자 등)인지 여부",
    )

    # 값 (금액 정수 원화, 특정 문자열 값 등)
    value: Optional[Any] = Field(None, description="정규화된 값(금액 정수 등)")
    condition: Optional[str] = Field(None, description="조건부 사실의 조건문")
    assertion_status: Optional[str] = Field(None, description="문서 기재, 당사자 주장 등")
    confidence: float = Field(1.0, description="추출 신뢰도")
    provenance: Optional[Dict[str, Any]] = Field(default_factory=dict, description="출처 문서 및 Span 정보")


class ComparabilityResult(BaseModel):
    """
    두 SemanticFact 간의 비교 가능성(Comparability Gate) 판정 결과.
    """

    is_comparable: bool = Field(..., description="두 명제가 상충 여부를 비교할 수 있는 동일 명제인지 여부")
    status: Literal[
        "COMPARABLE",
        "DIFFERENT_CONTEXT",
        "INSUFFICIENT_INFORMATION",
        "CONSISTENT",
    ] = Field(..., description="비교 관문 통과 상태")
    reason_code: str = Field(..., description="구체적 사유 코드")
    explanation: str = Field(..., description="사용자 친화적 설명")
    subject_match_basis: Optional[str] = Field(None, description="주체 비교 근거")
    predicate_match_basis: Optional[str] = Field(None, description="행위/속성 비교 근거")
    temporal_semantics: Optional[str] = Field(None, description="시간 의미 차이 요약")


class TemporalRelationResult(BaseModel):
    """
    두 사실 간 시계열적 선후 관계 판정 결과.
    """

    relation: Literal[
        "BEFORE",
        "AFTER",
        "SAME_TIME",
        "OVERLAPS",
        "DURING",
        "STARTS",
        "ENDS",
        "CONTINUES",
        "INCOMPARABLE",
    ] = Field("INCOMPARABLE", description="시간적 관계")
    explanation: str = Field("", description="시간 관계 설명")


# ==============================================================================
# 2. 정규식 및 어휘 사전 (도메인 일반화 규칙)
# ==============================================================================

# 날짜 패턴: YYYY-MM-DD, YYYY.MM.DD, YYYY년 M월 D일
_DATE_REGEX = re.compile(
    r"(?<!\d)(\d{4})\s*(?:년|[-./])\s*(\d{1,2})\s*(?:월|[-./])\s*(\d{1,2})(?:\s*일)?"
)

# 금액 정규화 정규식
_KR_NUM_CHUNK = re.compile(
    r"(?:(?P<eog>\d+(?:\.\d+)?)\s*억)?\s*(?:(?P<man>\d+(?:\.\d+)?)\s*만)?\s*원"
)
_PURE_DIGIT_KRW = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,12})\s*원")


# ==============================================================================
# 3. 사실 의미 추출 함수 (extract_semantic_fact)
# ==============================================================================

def extract_semantic_fact(
    statement: str,
    context: Optional[Dict[str, Any]] = None,
) -> SemanticFact:
    """단일 진술문(statement)과 문서 문맥으로부터 정규화된 SemanticFact를 추출한다.

    Args:
        statement: 분석 대상 진술문 (예: '잔금 지급기일은 2022년 3월 1일이다.').
        context: 선택적 문맥 딕셔너리 (document_name, claim_type, subject_key 등).

    Returns:
        SemanticFact: 정규화된 사실 의미 모델 인스턴스.
    """
    stmt = (statement or "").strip()
    ctx = context or {}
    compact = re.sub(r"\s+", "", stmt)

    # 1. 출처 및 기본 메타데이터
    doc_name = ctx.get("document_name") or ""
    claim_type = (ctx.get("claim_type") or "").upper()
    explicit_subject = ctx.get("subject_key")
    explicit_predicate = ctx.get("predicate_key")

    # 2. 날짜 추출
    dates: List[str] = []
    for m in _DATE_REGEX.finditer(stmt):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            dates.append(f"{y:04d}-{mo:02d}-{d:02d}")
    primary_date = dates[0] if dates else None

    # 3. 금액 추출
    extracted_amount: Optional[int] = None
    digit_match = _PURE_DIGIT_KRW.search(stmt)
    if digit_match:
        try:
            extracted_amount = int(digit_match.group(1).replace(",", ""))
        except Exception:
            pass
    if extracted_amount is None:
        chunk_m = _KR_NUM_CHUNK.search(stmt)
        if chunk_m and (chunk_m.group("eog") or chunk_m.group("man")):
            eog_val = float(chunk_m.group("eog")) if chunk_m.group("eog") else 0.0
            man_val = float(chunk_m.group("man")) if chunk_m.group("man") else 0.0
            extracted_amount = int(eog_val * 100_000_000 + man_val * 10_000)

    # 4. 극성(Polarity) 분석 (인식 불확실/미확인 분리)
    polarity: Literal["AFFIRMATIVE", "NEGATIVE", "DOUBLE_NEGATIVE", "REPORTED_NEGATIVE", "UNCONFIRMED"] = "AFFIRMATIVE"
    if any(kw in compact for kw in (
        "미확인이다", "미확인.", "확인되지않았다", "확인되지않음", "확인하지못함",
        "알수없다", "알수없음", "확보되지않았다", "확보되지않음", "제출되지않았다",
        "확정할수없다", "확정할수없음", "가입여부는확인되지"
    )):
        polarity = "UNCONFIRMED"
    elif any(kw in compact for kw in ("거절하지않았다", "부인하지않았다", "반대하지않았다")):
        polarity = "DOUBLE_NEGATIVE"
    elif any(kw in compact for kw in ("통보하였다", "알렸다", "말했다")) and any(
        kw in compact for kw in ("없다고", "않겠다고", "어렵다고")
    ):
        polarity = "REPORTED_NEGATIVE"
    elif any(kw in compact for kw in (
        "않았다", "아니다", "없다", "못했다", "않는다", "아니며", "없으며", "미반환"
    )):
        # 단, 조건절('~하지 못할 가능성이 있으면')이나 의문문('~않겠다는 뜻인지')은 주 서술어가 아니므로 AFFIRMATIVE 유지
        if any(kw in compact for kw in ("가능성이있으면", "가능성이급", "뜻인지확인", "뜻인지물", "조건으로")):
            polarity = "AFFIRMATIVE"
        else:
            polarity = "NEGATIVE"

    # 5. 의미 범주(semantic_category), 이벤트 유형(event_type), 세부 항목(event_subtype), 시점 유형(temporal_type)
    sem_category: Literal[
        "EVENT", "STATE", "OBLIGATION", "CONDITION", "EPISTEMIC_STATUS", "IDENTITY", "METADATA", "UNKNOWN"
    ] = "UNKNOWN"
    event_type: Optional[str] = None
    event_subtype: Optional[str] = None
    temporal_type: Literal[
        "OCCURRED_AT", "DUE_AT", "SCHEDULED_AT", "REQUESTED_AT", "EFFECTIVE_FROM", "EFFECTIVE_TO", "VALID_AT", "VALID_INTERVAL", "REPORTED_AT", "NONE"
    ] = "NONE"
    occurrence_status: Literal["ACTUAL", "SCHEDULED", "REQUESTED", "PROPOSED", "ALLEGED", "UNCONFIRMED"] = "ACTUAL"
    is_repeatable = False
    object_qualifier: Optional[str] = None

    # (A) METADATA: 문서 정보, 제목
    if claim_type in ("DOC_INFO", "DOCUMENT_INFO") or any(
        kw in compact for kw in ("문서의제목", "문서제목", "본문서는", "이문서는", "작성된전사본", "원음파일")
    ):
        sem_category = "METADATA"
        event_type = "DOCUMENT_METADATA"
        temporal_type = "REPORTED_AT" if primary_date else "NONE"
        occurrence_status = "ACTUAL"

    # (B) EPISTEMIC_STATUS: 인식 상태, 미확인 사실, 자료 미제출
    elif polarity == "UNCONFIRMED":
        sem_category = "EPISTEMIC_STATUS"
        event_type = "EPISTEMIC_STATUS"
        occurrence_status = "UNCONFIRMED"
        temporal_type = "VALID_AT" if primary_date else "NONE"

    # (C) IDENTITY: 당사자, 소유자, 채권자 등 신원 정보
    elif (
        claim_type == "PARTY_INFO"
        or (
            any(
                re.search(rf"{kw}(?:은|는|이|가|으로서|로서)", stmt)
                for kw in ("임대인", "임차인", "채권자", "채무자", "소유자", "소유권자", "원고", "피고", "매도인", "매수인", "근로자", "사용자")
            )
            and any(kw in compact for kw in ("이다", "입니다", "기재되어있", "서명란이존재", "연락처는"))
            and not any(kw in compact for kw in ("거주", "점유", "근무", "지급", "반환", "인도", "명도", "퇴거", "이사", "체결", "발송", "도달"))
        )
    ):
        sem_category = "IDENTITY"
        event_type = "IDENTITY"
        occurrence_status = "ACTUAL"
        temporal_type = "NONE"

    # (D) OBLIGATION: 법률상/계약상 의무, 약정 의무
    elif any(kw in compact for kw in ("의무가있다", "의무를부담", "이행할의무", "해야한다", "책임이자신에게")):
        sem_category = "OBLIGATION"
        occurrence_status = "SCHEDULED"
        if "지급" in compact or "반환" in compact:
            event_type = "PAYMENT_OBLIGATION"
            if "계약금" in compact:
                event_subtype = "DOWN_PAYMENT"
            elif "잔금" in compact:
                event_subtype = "BALANCE_PAYMENT"
            elif "보증금" in compact:
                event_subtype = "PRINCIPAL_DEPOSIT"
            temporal_type = "DUE_AT" if primary_date else "NONE"
        elif "인도" in compact or "명도" in compact:
            event_type = "DELIVERY_OBLIGATION"
            temporal_type = "DUE_AT" if primary_date else "NONE"
        else:
            event_type = "LEGAL_OBLIGATION"
            temporal_type = "NONE"

    # (E) PAYMENT: 금원 지급 관련 (계약금, 중도금, 잔금, 보증금 총액, 차임, 급여, 가압류 청구금액 등)
    elif any(kw in compact for kw in (
        "지급기일", "지급일", "지급예정일", "지급하였다", "지급함", "이체되었다", "이체했", "반환기일",
        "반환일", "반환을요청", "반환요청", "반환채무", "청구금액", "보증금은", "전세금은", "계약금은", "잔금은", "차임은", "합계는"
    )):
        event_type = "PAYMENT"
        
        # 합계 / 총액 / 보증금 전체
        if "합계" in compact or "총액" in compact or "전체" in compact:
            event_subtype = "TOTAL_AMOUNT"
        elif "계약금" in compact:
            event_subtype = "DOWN_PAYMENT"
        elif "중도금" in compact:
            event_subtype = "INTERIM_PAYMENT"
        elif "잔금" in compact:
            event_subtype = "BALANCE_PAYMENT"
        elif "가압류" in compact or "청구금액" in compact:
            event_subtype = "CLAIM_AMOUNT"
        elif "차임" in compact or "월세" in compact:
            event_subtype = "RENT"
        elif "급여" in compact or "임금" in compact:
            event_subtype = "WAGE"
        elif "반환" in compact:
            event_subtype = "RETURN_AMOUNT"
        else:
            event_subtype = "PRINCIPAL_DEPOSIT"

        # 시점 및 발생 성격 구분
        if any(kw in compact for kw in ("기일은", "지급기일", "예정일", "하기로약정", "하기로함")):
            sem_category = "OBLIGATION"
            temporal_type = "DUE_AT"
            occurrence_status = "SCHEDULED"
        elif any(kw in compact for kw in ("요청하였다", "요구하였다", "요청한")):
            sem_category = "EVENT"
            temporal_type = "REQUESTED_AT" if primary_date else "NONE"
            occurrence_status = "REQUESTED"
        elif any(kw in compact for kw in ("지급하였다", "지급함", "이체되었다", "이체하였다", "납부하였다", "입금되었다")):
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT" if primary_date else "NONE"
            occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("기준", "현재", "미반환상태", "못했다")):
            sem_category = "STATE"
            temporal_type = "VALID_AT" if primary_date else "NONE"
            occurrence_status = "ACTUAL"
        else:
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT" if primary_date else "NONE"
            occurrence_status = "ACTUAL"

    # (F) RESIDENCE / OCCUPANCY / DELIVERY / MOVEOUT
    elif any(kw in compact for kw in (
        "전입신고", "전입유지", "전입", "주민등록", "확정일자", "입주", "거주", "인도", "퇴거", "이사", "명도", "점유", "출입카드", "열쇠"
    )):
        if "전입신고" in compact:
            event_type = "RESIDENCE_REGISTRATION"
            event_subtype = "INITIAL_REGISTRATION"
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT"
            occurrence_status = "ACTUAL"
        elif "전입유지" in compact or "전입상태" in compact or "유지중" in compact:
            event_type = "RESIDENCE_REGISTRATION"
            event_subtype = "MAINTAINED_STATUS"
            sem_category = "STATE"
            temporal_type = "VALID_AT"
            occurrence_status = "ALLEGED" if "진술" in compact else "ACTUAL"
        elif any(kw in compact for kw in ("실제거주", "계속거주", "거주하고있다", "거주중")):
            event_type = "OCCUPANCY_STATUS"
            sem_category = "STATE"
            temporal_type = "VALID_AT"
            occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("퇴거예정", "이사예정", "이사할계획", "퇴거의사")):
            event_type = "MOVEOUT_SCHEDULE"
            sem_category = "EVENT"
            temporal_type = "SCHEDULED_AT"
            occurrence_status = "SCHEDULED"
        elif any(kw in compact for kw in ("퇴거하였다", "이사하였다", "명도하였다")):
            event_type = "MOVEOUT_PERFORMANCE"
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT"
            occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("출입카드", "열쇠")):
            event_type = "KEY_DELIVERY"
            if "수령" in compact or "받았다" in compact:
                event_subtype = "KEY_RECEIPT"
                sem_category = "EVENT"
                temporal_type = "OCCURRED_AT"
                occurrence_status = "ACTUAL"
            else:
                event_subtype = "KEY_RETURN"
                sem_category = "STATE" if polarity == "NEGATIVE" else "EVENT"
                temporal_type = "VALID_AT" if polarity == "NEGATIVE" else "OCCURRED_AT"
                occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("입주하였다", "인도받았다", "인도예정일")):
            event_type = "DELIVERY"
            if "예정" in compact:
                sem_category = "OBLIGATION"
                temporal_type = "SCHEDULED_AT"
                occurrence_status = "SCHEDULED"
            else:
                sem_category = "EVENT"
                temporal_type = "OCCURRED_AT"
                occurrence_status = "ACTUAL"
        else:
            event_type = "OCCUPANCY"
            sem_category = "STATE" if "기준" in compact else "EVENT"
            temporal_type = "VALID_AT" if "기준" in compact else "OCCURRED_AT"

    # (G) COMMUNICATION: 메시지, 통지, 통화, 문의 (반복 발생 사건)
    elif any(kw in compact for kw in (
        "메시지", "문자", "통화", "문의", "답변", "회신", "통지", "도달", "송달", "발송"
    )):
        event_type = "COMMUNICATION"
        is_repeatable = True
        sem_category = "EVENT"
        occurrence_status = "ACTUAL"
        if "도달" in compact or "수령" in compact or "송달" in compact:
            event_subtype = "NOTICE_REACHED"
            temporal_type = "OCCURRED_AT"
        elif "발송" in compact or "보냈" in compact:
            event_subtype = "NOTICE_SENT"
            temporal_type = "REPORTED_AT"
        elif "문자" in compact or "메시지" in compact:
            event_subtype = "MESSAGE"
            temporal_type = "REPORTED_AT"
        elif "통화" in compact:
            event_subtype = "PHONE_CALL"
            temporal_type = "OCCURRED_AT"
        elif "문의" in compact:
            event_subtype = "INQUIRY"
            temporal_type = "OCCURRED_AT"
        else:
            event_subtype = "NOTICE"
            temporal_type = "REPORTED_AT"

    # (H) ENCUMBRANCE / REGISTRY: 가압류, 근저당권, 등기 접수, 소유권이전등기
    elif any(kw in compact for kw in ("가압류", "근저당권", "등기접수일", "소유권이전등기", "갑구", "을구")):
        event_type = "ENCUMBRANCE"
        sem_category = "EVENT"
        if "가압류" in compact:
            event_subtype = "PROVISIONAL_ATTACHMENT"
        elif "근저당" in compact:
            event_subtype = "MORTGAGE"
        elif "소유권이전등기" in compact:
            event_subtype = "TITLE_TRANSFER"
        elif "소유권" in compact:
            event_subtype = "OWNERSHIP"
        else:
            event_subtype = "REGISTRATION"

        if "접수일" in compact or "접수" in compact:
            temporal_type = "OCCURRED_AT"
        elif "열람일" in compact:
            temporal_type = "REPORTED_AT"
        else:
            temporal_type = "OCCURRED_AT" if primary_date else "NONE"
        occurrence_status = "ACTUAL"

    # (I) LABOR / EMPLOYMENT: 근로계약, 입사일, 퇴사일, 급여일, 체불
    elif any(kw in compact for kw in ("입사일", "입사하였", "채용일", "퇴사일", "퇴사하였", "사직일", "해고일", "체불기준일", "임금체불")):
        event_type = "EMPLOYMENT"
        if any(kw in compact for kw in ("입사", "채용", "취업")):
            event_subtype = "HIRE"
            sem_category = "EVENT"
            temporal_type = "EFFECTIVE_FROM"
            occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("퇴사", "사직", "해고")):
            event_subtype = "RESIGNATION"
            sem_category = "EVENT"
            temporal_type = "EFFECTIVE_TO"
            occurrence_status = "ACTUAL"
        elif "체불" in compact:
            event_subtype = "OVERDUE_WAGE_STATUS"
            sem_category = "STATE"
            temporal_type = "VALID_AT"
            occurrence_status = "ACTUAL"
        else:
            event_subtype = "EMPLOYMENT_STATUS"
            sem_category = "STATE"
            temporal_type = "VALID_AT" if primary_date else "NONE"

    # (J) LOAN / DEBT: 대여일, 대출일, 차용일, 변제기, 일부 변제, 잔존 채무
    elif any(kw in compact for kw in ("대여", "대출", "차용", "변제", "상환", "잔존채무", "미변제잔액")):
        event_type = "LOAN"
        if any(kw in compact for kw in ("일부변제", "일부상환", "변제하였다", "상환하였다")):
            event_subtype = "PARTIAL_REPAYMENT"
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT"
            occurrence_status = "ACTUAL"
        elif "변제기" in compact or "상환기일" in compact:
            event_subtype = "DUE_DATE"
            sem_category = "OBLIGATION"
            temporal_type = "DUE_AT"
            occurrence_status = "SCHEDULED"
        elif any(kw in compact for kw in ("잔존채무", "미변제", "잔액")):
            event_subtype = "REMAINING_DEBT"
            sem_category = "STATE"
            temporal_type = "VALID_AT"
            occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("대여", "차용", "대출")):
            event_subtype = "LOAN_ORIGINATION"
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT"
            occurrence_status = "ACTUAL"
        else:
            event_subtype = "LOAN_STATUS"
            sem_category = "STATE"
            temporal_type = "VALID_AT" if primary_date else "NONE"

    # (K) LITIGATION: 소송 절차 (소장 제출, 소장 송달, 변론기일, 판결 선고)
    elif any(kw in compact for kw in ("소장제출", "소제기", "소장송달", "변론기일", "조정기일", "판결선고")):
        event_type = "LITIGATION"
        sem_category = "EVENT"
        occurrence_status = "ACTUAL"
        if any(kw in compact for kw in ("소장제출", "소제기", "소를제기")):
            event_subtype = "COMPLAINT_FILING"
            temporal_type = "OCCURRED_AT"
        elif any(kw in compact for kw in ("소장송달", "송달일")):
            event_subtype = "COMPLAINT_SERVICE"
            temporal_type = "OCCURRED_AT"
        elif any(kw in compact for kw in ("변론기일", "조정기일")):
            event_subtype = "HEARING_DATE"
            temporal_type = "SCHEDULED_AT" if "예정" in compact else "OCCURRED_AT"
        elif any(kw in compact for kw in ("판결선고", "선고일")):
            event_subtype = "JUDGMENT_PRONOUNCEMENT"
            temporal_type = "OCCURRED_AT"
        else:
            event_subtype = "LEGAL_PROCEDURE"
            temporal_type = "OCCURRED_AT" if primary_date else "NONE"

    # (L) CONTRACT_PERIOD: 임대차 기간, 근로 기간, 계약 기간
    elif any(kw in compact for kw in ("임대차기간", "계약기간", "근로계약기간", "만기일", "계약체결", "계약체결일", "개시일", "시작일", "종료일", "만료일", "임대차개시")):
        if "체결" in compact:
            event_type = "CONTRACT_EXECUTION"
            event_subtype = "CONTRACT_SIGNING"
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT"
            occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("개시일", "시작일", "임대차개시")):
            event_type = "CONTRACT_PERIOD"
            event_subtype = "START_DATE"
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT"
            occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("만기일", "종료일", "만료일")):
            event_type = "CONTRACT_PERIOD"
            event_subtype = "END_DATE"
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT"
            occurrence_status = "ACTUAL"
        elif "기간" in compact and len(dates) >= 2:
            event_type = "CONTRACT_PERIOD"
            sem_category = "STATE"
            temporal_type = "VALID_INTERVAL"
            occurrence_status = "ACTUAL"
        else:
            event_type = "CONTRACT_PERIOD"
            sem_category = "STATE"
            temporal_type = "VALID_INTERVAL" if primary_date else "NONE"

    # (J) 기타 일반
    else:
        sem_category = "EVENT" if primary_date else "UNKNOWN"
        event_type = "GENERAL_FACT"
        temporal_type = "OCCURRED_AT" if primary_date else "NONE"
        occurrence_status = "ACTUAL"

    # 6. 객체 한정자(object_key) 정밀 추출 (가압류 채권자, 계약 구분 등)
    # 예: '동진은행 가압류', 'HUG 가압류', '은행 채권 가압류'
    if "HUG" in stmt or "주택도시보증공사" in stmt or "HUG" in doc_name:
        object_qualifier = "CREDITOR:HUG"
    elif "동진은행" in stmt or "은행" in stmt or "은행" in doc_name:
        object_qualifier = "CREDITOR:BANK"

    # 7. 주체(subject_key) 및 서술어(predicate) 보강
    subject_key = explicit_subject
    if not subject_key:
        subj_match = re.search(r"([가-힣]{2,8}|주식회사\s*[가-힣A-Za-z0-9]+)(?:은|는|이|가)\s+", stmt)
        if subj_match:
            subject_key = subj_match.group(1).strip()

    return SemanticFact(
        statement=stmt,
        subject_key=subject_key,
        object_key=object_qualifier,
        predicate=explicit_predicate,
        semantic_category=sem_category,
        event_type=event_type,
        event_subtype=event_subtype,
        temporal_type=temporal_type,
        temporal_value=primary_date,
        temporal_qualifier="기준" if "기준" in stmt else None,
        occurrence_status=occurrence_status,
        polarity=polarity,
        is_repeatable_event=is_repeatable,
        value=extracted_amount,
        assertion_status=ctx.get("assertion_status"),
        confidence=float(ctx.get("confidence", 1.0)),
        provenance={"document_name": doc_name, "evidence_id": ctx.get("evidence_id")},
    )


# ==============================================================================
# 4. 사실 동일성 비교 함수 (compare_fact_identity)
# ==============================================================================

def compare_fact_identity(
    fact_a: SemanticFact,
    fact_b: SemanticFact,
) -> ComparabilityResult:
    """두 SemanticFact가 상충 가능 여부를 검증할 수 있는 동일 명제인지 판정한다.

    비교 관문(Comparability Gate)의 핵심 함수로서, 다음 조건을 단계별로 검증한다:
    1. 문서 로컬 메타데이터(METADATA)는 문서 간 다름이 정상이므로 DIFFERENT_CONTEXT.
    2. 인식 불확실성(EPISTEMIC_STATUS: '미확인', '확인되지 않음')은 일반 긍정 사실과 상충 금지 (DIFFERENT_CONTEXT).
    3. 거래 단계(event_subtype) 차이 (예: 계약금 vs 중도금 vs 잔금 vs 합계): DIFFERENT_CONTEXT.
    4. 의미 범주 차이 (행위 EVENT vs 상태 STATE vs 의무 OBLIGATION): DIFFERENT_CONTEXT.
    5. 시점 의미 차이 (약정기일 DUE_AT vs 실제발생 OCCURRED_AT vs 상태기준 VALID_AT): DIFFERENT_CONTEXT 또는 TEMPORALLY_COMPATIBLE.
    6. 반복 발생 의사소통 사건 (COMMUNICATION: 문자, 통화 등)은 시점이 달라도 별개 사건 (DIFFERENT_CONTEXT).
    7. 별개의 가압류 건 (은행 가압류 vs HUG 가압류): DIFFERENT_CONTEXT.

    Args:
        fact_a: 첫 번째 SemanticFact.
        fact_b: 두 번째 SemanticFact.

    Returns:
        ComparabilityResult: 비교 관문 판정 결과.
    """
    # 1. 문서 고유 메타데이터 (DOC_INFO / METADATA)
    if fact_a.semantic_category == "METADATA" and fact_b.semantic_category == "METADATA":
        # 서로 다른 파일명이거나 문서 제목이면 DIFFERENT_CONTEXT
        doc_a = fact_a.provenance.get("document_name")
        doc_b = fact_b.provenance.get("document_name")
        if doc_a and doc_b and doc_a != doc_b:
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="DOCUMENT_LOCAL_METADATA",
                explanation="서로 다른 증거 문서의 고유 메타데이터(문서 제목·형식)는 개별 문서에 국한된 별개 진술입니다.",
                subject_match_basis=f"DocA: {doc_a} vs DocB: {doc_b}",
            )

    # 2. 인식 상태(EPISTEMIC_STATUS)는 사실의 존재 여부를 다투는 긍정 사실과 모순되지 않음
    if fact_a.polarity == "UNCONFIRMED" or fact_b.polarity == "UNCONFIRMED" or \
       fact_a.semantic_category == "EPISTEMIC_STATUS" or fact_b.semantic_category == "EPISTEMIC_STATUS":
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            reason_code="EPISTEMIC_STATUS_NOT_CONTRADICTION",
            explanation="진술이 사실의 확인 여부(미확인, 부존재)에 관한 메타 진술이므로 다른 확정 사실과 상충하지 않습니다.",
            predicate_match_basis="Epistemic status vs Factual assertion",
        )

    # 3. 거래 단계 및 세부 항목 분리
    # (A) 금원 지급 구성 항목 (Payment Component) 분리 (예: 계약금 vs 잔금 vs 보증금 총액)
    subtypes = {fact_a.event_subtype, fact_b.event_subtype} - {None}
    if fact_a.event_type == "PAYMENT" and fact_b.event_type == "PAYMENT":
        if len(subtypes) >= 2 and fact_a.event_subtype != fact_b.event_subtype:
            # 보증금 총액(PRINCIPAL_DEPOSIT / TOTAL_AMOUNT)과 반환 요청 금액(RETURN_AMOUNT)이
            # 동일한 금액을 가리키는 경우(전액 반환 청구), 동일 명목 금액 비교로 승인
            is_compatible_deposit = False
            if subtypes in (
                {"PRINCIPAL_DEPOSIT", "RETURN_AMOUNT"},
                {"PRINCIPAL_DEPOSIT", "TOTAL_AMOUNT"},
                {"RETURN_AMOUNT", "TOTAL_AMOUNT"},
            ):
                if fact_a.value is not None and fact_b.value is not None and fact_a.value == fact_b.value:
                    is_compatible_deposit = True

            if not is_compatible_deposit:
                return ComparabilityResult(
                    is_comparable=False,
                    status="DIFFERENT_CONTEXT",
                    reason_code="DIFFERENT_PAYMENT_COMPONENT",
                    explanation=f"지급 구성 항목이 서로 다른 별개 거래 단계입니다 ({fact_a.event_subtype} vs {fact_b.event_subtype}).",
                    predicate_match_basis=f"Subtypes: {fact_a.event_subtype} != {fact_b.event_subtype}",
                )

    # (B) 근로계약 단계 분리: 입사(HIRE) vs 퇴사(RESIGNATION)
    if fact_a.event_type == "EMPLOYMENT" and fact_b.event_type == "EMPLOYMENT":
        if len(subtypes) >= 2 and fact_a.event_subtype != fact_b.event_subtype:
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_EMPLOYMENT_STAGE",
                explanation=f"근로관계 단계가 서로 다른 별개 사건입니다 ({fact_a.event_subtype} vs {fact_b.event_subtype}).",
                predicate_match_basis=f"EmploymentSubtypes: {fact_a.event_subtype} != {fact_b.event_subtype}",
            )

    # (C) 채권채무 단계 분리: 대여(LOAN_ORIGINATION) vs 일부 변제(PARTIAL_REPAYMENT)
    if fact_a.event_type == "LOAN" and fact_b.event_type == "LOAN":
        if len(subtypes) >= 2 and fact_a.event_subtype != fact_b.event_subtype:
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_TRANSACTION_STAGE",
                explanation=f"채권채무 거래 단계가 서로 다른 별개 사실입니다 ({fact_a.event_subtype} vs {fact_b.event_subtype}).",
                predicate_match_basis=f"LoanSubtypes: {fact_a.event_subtype} != {fact_b.event_subtype}",
            )

    # (D) 통지/의사소통 단계 분리: 발송(NOTICE_SENT) vs 도달(NOTICE_REACHED)
    if fact_a.event_type == "COMMUNICATION" and fact_b.event_type == "COMMUNICATION":
        if "NOTICE_SENT" in subtypes and "NOTICE_REACHED" in subtypes:
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_COMMUNICATION_STAGE",
                explanation="의사표시 발송 시점과 도달·수령 시점은 구별되는 별개의 절차입니다.",
                predicate_match_basis="NoticeSent vs NoticeReached",
            )

    # (E) 서로 다른 사건 대분류 (예: 계약 체결 CONTRACT_EXECUTION vs 등기 접수 ENCUMBRANCE/REGISTRATION)
    if (
        fact_a.event_type
        and fact_b.event_type
        and fact_a.event_type != "GENERAL_FACT"
        and fact_b.event_type != "GENERAL_FACT"
        and fact_a.event_type != fact_b.event_type
    ):
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            reason_code="DIFFERENT_EVENT_TYPE",
            explanation=f"서로 다른 법률 행위 및 사건 유형입니다 ({fact_a.event_type} vs {fact_b.event_type}).",
            predicate_match_basis=f"EventType: {fact_a.event_type} != {fact_b.event_type}",
        )

    # 4. 행위(EVENT) vs 지속 상태(STATE) 분리
    # 예: 전입신고일(EVENT) vs 전입유지 여부(STATE), 임대차 시작일(EVENT) vs 갱신 후 유지 상태(STATE)
    categories = {fact_a.semantic_category, fact_b.semantic_category}
    if "EVENT" in categories and "STATE" in categories:
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            reason_code="EVENT_VS_STATE",
            explanation=f"과거 특정 시점에 발생한 행위(EVENT)와 이후 특정 시점의 유지 상태(STATE)는 서로 다른 범주의 진술입니다.",
            temporal_semantics=f"Category A: {fact_a.semantic_category} vs Category B: {fact_b.semantic_category}",
        )

    # 5. 시점 의미 중 약정기일(DUE_AT)과 실제 이행(OCCURRED_AT)이 동일 일자인 경우 (S03)
    # 이는 계약 약정에 따른 적시 이행으로 양립 가능한 일치(CONSISTENT) 사실임
    tt_pair = {fact_a.temporal_type, fact_b.temporal_type}
    if "DUE_AT" in tt_pair and "OCCURRED_AT" in tt_pair:
        if fact_a.temporal_value and fact_b.temporal_value and fact_a.temporal_value == fact_b.temporal_value:
            return ComparabilityResult(
                is_comparable=False,
                status="CONSISTENT",
                reason_code="TEMPORALLY_COMPATIBLE",
                explanation="약정된 지급기일과 실제 지급일이 동일하여 정상적으로 이행된 양립 가능한 사실입니다.",
                temporal_semantics=f"Both on {fact_a.temporal_value} (DUE_AT == OCCURRED_AT)",
            )

    # 6. 의무(OBLIGATION) vs 실제 이행/미이행(EVENT/STATE) 분리
    # 예: '임대인은 보증금을 반환할 의무가 있다' vs '임차인은 보증금을 돌려받지 못했다'
    if "OBLIGATION" in categories and ("EVENT" in categories or "STATE" in categories):
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            reason_code="DIFFERENT_OBLIGATION_VS_PERFORMANCE",
            explanation="계약상 의무 부담 사실과 실제 이행/미이행 상태는 서술 층위가 다른 별개 사실입니다.",
            predicate_match_basis="Obligation vs Performance status",
        )

    # 7. 시점 의미 차이 (약정기일 DUE_AT vs 실제발생 OCCURRED_AT vs 상태기준일 VALID_AT vs 요청기한 REQUESTED_AT)
    if (
        fact_a.temporal_type != fact_b.temporal_type
        and "NONE" not in (fact_a.temporal_type, fact_b.temporal_type)
    ):
        # 기일(DUE_AT) vs 실제지급(OCCURRED_AT) - 날짜가 다른 경우
        if "DUE_AT" in tt_pair and "OCCURRED_AT" in tt_pair:
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_TRANSACTION_STAGE",
                explanation="약정된 지급기일(DUE_AT)과 실제 지급 발생일(OCCURRED_AT)은 서로 다른 시간적 의미를 가집니다.",
                temporal_semantics=f"TemporalTypes: {fact_a.temporal_type} vs {fact_b.temporal_type}",
            )
        # 요청기한(REQUESTED_AT) vs 실제통지발송일(REPORTED_AT/OCCURRED_AT)
        if "REQUESTED_AT" in tt_pair and ("OCCURRED_AT" in tt_pair or "REPORTED_AT" in tt_pair):
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="DIFFERENT_TEMPORAL_SEMANTICS",
                explanation="반환/퇴거를 요청한 목표일자와 통지 의사표시를 발송한 일자는 서로 다른 시점 의미입니다.",
                temporal_semantics=f"TemporalTypes: {fact_a.temporal_type} vs {fact_b.temporal_type}",
            )
        # 상태 기준일(VALID_AT) vs 실제 행위일(OCCURRED_AT)
        if "VALID_AT" in tt_pair and "OCCURRED_AT" in tt_pair:
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="EVENT_VS_STATE",
                explanation="상태 확인 기준일(VALID_AT)과 최초 행위 발생일(OCCURRED_AT)은 양립 가능한 별개 시점입니다.",
                temporal_semantics=f"TemporalTypes: {fact_a.temporal_type} vs {fact_b.temporal_type}",
            )

    # 7. 반복 발생 의사소통 사건 (COMMUNICATION: 문자, 통화, 문의)
    if fact_a.is_repeatable_event and fact_b.is_repeatable_event:
        if fact_a.temporal_value != fact_b.temporal_value:
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="REPEATABLE_COMMUNICATION_EVENT",
                explanation="사건 진행 경과 중 각기 다른 일시에 발송·수신된 별개의 의사소통(문자·통화·문의) 기록입니다.",
                temporal_semantics=f"Dates: {fact_a.temporal_value} != {fact_b.temporal_value}",
            )

    # 8. 객체 한정자(object_key) 불일치 (예: 은행 가압류 vs HUG 가압류)
    if fact_a.object_key and fact_b.object_key and fact_a.object_key != fact_b.object_key:
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            reason_code="DIFFERENT_OBJECT_QUALIFIER",
            explanation=f"등기부상 서로 다른 권리 또는 채권자 건입니다 ({fact_a.object_key} vs {fact_b.object_key}).",
            subject_match_basis=f"ObjectQualifier: {fact_a.object_key} != {fact_b.object_key}",
        )

    # 9. 신원 정보(IDENTITY)와 일반 사건(EVENT)의 극성 오탐 차단
    if fact_a.semantic_category == "IDENTITY" and fact_b.semantic_category != "IDENTITY":
        if fact_b.polarity == "NEGATIVE":
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="IDENTITY_VS_EVENT_POLARITY",
                explanation="당사자 신원 사실과 사건 이행 여부에 관한 부정 진술은 대상 범주가 다릅니다.",
            )
    if fact_b.semantic_category == "IDENTITY" and fact_a.semantic_category != "IDENTITY":
        if fact_a.polarity == "NEGATIVE":
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                reason_code="IDENTITY_VS_EVENT_POLARITY",
                explanation="당사자 신원 사실과 사건 이행 여부에 관한 부정 진술은 대상 범주가 다릅니다.",
            )

    # 위 관문을 모두 통과하면 본격적인 상충/일치 검증 대상(COMPARABLE)으로 승인
    return ComparabilityResult(
        is_comparable=True,
        status="COMPARABLE",
        reason_code="IDENTICAL_FACT_CANDIDATE",
        explanation="동일 대상·동일 행위·동일 시점 의미를 공유하므로 상충 여부 검증 대상입니다.",
        subject_match_basis=f"Category: {fact_a.semantic_category}, EventType: {fact_a.event_type}",
        predicate_match_basis=f"Subtype: {fact_a.event_subtype}",
    )


# ==============================================================================
# 5. 시간 관계 추론 함수 (evaluate_temporal_relation)
# ==============================================================================

def evaluate_temporal_relation(
    fact_a: SemanticFact,
    fact_b: SemanticFact,
) -> TemporalRelationResult:
    """두 SemanticFact의 정규화된 시점을 비교하여 시계열적 선후 관계를 추론한다."""
    da = fact_a.temporal_value
    db = fact_b.temporal_value

    if not da or not db:
        return TemporalRelationResult(relation="INCOMPARABLE", explanation="시점 정보가 누락되어 비교할 수 없습니다.")

    if da == db:
        return TemporalRelationResult(relation="SAME_TIME", explanation=f"동일 시점 ({da})입니다.")
    elif da < db:
        return TemporalRelationResult(relation="BEFORE", explanation=f"{da}가 {db}보다 이전입니다.")
    else:
        return TemporalRelationResult(relation="AFTER", explanation=f"{da}가 {db}보다 이후입니다.")
