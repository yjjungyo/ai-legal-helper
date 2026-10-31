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

class SemanticProposition(BaseModel):
    """
    구조화된 법적 사실 명제 모델 (Semantic Proposition Model).

    Section 5 (P0-01) 요구사항 반영:
    단순 문자열 텍스트가 아니라 법적 명제의 주체, 객체, 속성, 범주, 세부 단계,
    고유 인스턴스 식별자(event_instance_key), 화행(speech_act), 인식 상태(epistemic_status),
    시간 의미 유형 및 시계열 구간, 조건/양상을 다차원 정규화하여 보관한다.
    """

    statement: str = Field(default="", description="원본 진술문 문자열")
    subject_key: Optional[str] = Field(None, description="명제의 주체 (예: 임대인, 임차인, 채무자 등)")
    object_key: Optional[str] = Field(None, description="명제의 객체/대상 (예: 특정 가압류, 특정 계약 등)")
    predicate_key: Optional[str] = Field(None, description="핵심 서술어 또는 행위 속성 (예: 반환, 지급, 체결 등)")

    semantic_category: Literal[
        "EVENT",
        "STATE",
        "OBLIGATION",
        "RIGHT",
        "CONDITION",
        "DOCUMENT_METADATA",
        "SOURCE_AVAILABILITY",
        "EPISTEMIC_STATUS",
        "ASSERTION",
        "UNKNOWN",
    ] = Field("UNKNOWN", description="명제의 법적 의미 범주")

    event_type: Optional[str] = Field(None, description="사건 대분류 (PAYMENT, RESIDENCE, LOAN 등)")
    event_subtype: Optional[str] = Field(None, description="사건 소분류 (DOWN_PAYMENT, BALANCE_PAYMENT 등)")
    event_instance_key: Optional[str] = Field(
        None,
        description="동일 사건·거래 인스턴스 구분을 위한 고유 키 (예: ENCUMBRANCE:HUG:72M vs ENCUMBRANCE:BANK:50M)",
    )

    value: Optional[Dict[str, Any]] = Field(None, description="정규화된 값 딕셔너리 (amount, unit 등)")
    value_role: Optional[str] = Field(None, description="값의 의미적 역할 (TOTAL_AMOUNT, DOWN_PAYMENT 등)")

    temporal_type: Optional[Literal[
        "OCCURRED_AT",
        "DUE_AT",
        "SCHEDULED_AT",
        "REQUESTED_AT",
        "REPORTED_AT",
        "VALID_AT",
        "VALID_INTERVAL",
        "EFFECTIVE_FROM",
        "EFFECTIVE_TO",
        "NONE",
    ]] = Field("NONE", description="시간 정보의 법적 의미 역할")
    temporal_value: Optional[str] = Field(None, description="정규화된 일자 (YYYY-MM-DD)")
    temporal_interval: Optional[Dict[str, Any]] = Field(None, description="시작일과 종료일로 구성된 유효 구간")

    condition: Optional[str] = Field(None, description="조건부 명제의 조건 표현")
    modality: Optional[str] = Field(None, description="양상 표현 (의무, 가능, 금지 등)")

    polarity: Literal[
        "AFFIRMATIVE",
        "NEGATIVE",
        "DOUBLE_NEGATIVE",
        "REPORTED_NEGATIVE",
        "UNKNOWN",
    ] = Field("UNKNOWN", description="서술 극성")

    epistemic_status: Literal[
        "ASSERTED",
        "REPORTED",
        "DOCUMENT_STATES",
        "UNKNOWN",
        "NOT_VERIFIED",
        "INFERRED",
    ] = Field("UNKNOWN", description="인식 상태 (직접 단언, 인용 보고, 문서 기재, 미확인/정보부족 등)")

    speech_act: Optional[Literal[
        "STATEMENT",
        "REQUEST",
        "PROPOSAL",
        "ACCEPTANCE",
        "REJECTION",
        "NOTICE",
        "QUESTION",
        "PROMISE",
    ]] = Field("STATEMENT", description="화행 유형 (단순 진술, 이행 청구, 분할 제안, 거절 등)")
    speaker_key: Optional[str] = Field(None, description="발화자 또는 의사표시 주체")

    source_evidence_id: Optional[str] = Field(None, description="출처 증거 문서 ID")
    source_claim_id: Optional[str] = Field(None, description="출처 Claim ID")
    source_span_ids: List[str] = Field(default_factory=list, description="근거 원문 Span ID 목록")
    confidence: float = Field(1.0, description="추출 신뢰도")
    provenance: Optional[Dict[str, Any]] = Field(default_factory=dict, description="추가 출처 메타데이터")

    def to_semantic_fact(self) -> "SemanticFact":
        """SemanticFact 레거시 호환 모델로 변환한다."""
        raw_amount = None
        if isinstance(self.value, dict) and "amount" in self.value:
            raw_amount = self.value["amount"]
        elif isinstance(self.value, (int, float)):
            raw_amount = int(self.value)

        # semantic_category 매핑
        sem_cat = self.semantic_category
        if sem_cat in ("RIGHT", "ASSERTION"):
            sem_cat = "STATE"
        elif sem_cat == "SOURCE_AVAILABILITY":
            sem_cat = "EPISTEMIC_STATUS"

        # occurrence_status 매핑
        occ = "ACTUAL"
        if self.speech_act == "PROPOSAL":
            occ = "PROPOSED"
        elif self.speech_act == "REQUEST":
            occ = "REQUESTED"
        elif self.temporal_type in ("DUE_AT", "SCHEDULED_AT"):
            occ = "SCHEDULED"
        elif self.epistemic_status == "NOT_VERIFIED":
            occ = "UNCONFIRMED"

        # polarity 매핑
        pol = self.polarity
        if self.epistemic_status == "NOT_VERIFIED":
            pol = "UNCONFIRMED"
        elif pol == "UNKNOWN":
            pol = "AFFIRMATIVE"

        return SemanticFact(
            statement=self.statement,
            subject_key=self.subject_key,
            object_key=self.object_key,
            predicate=self.predicate_key,
            semantic_category=sem_cat if sem_cat in ("EVENT", "STATE", "OBLIGATION", "CONDITION", "EPISTEMIC_STATUS", "IDENTITY", "METADATA", "UNKNOWN") else "UNKNOWN",
            event_type=self.event_type,
            event_subtype=self.event_subtype,
            temporal_type=self.temporal_type,
            temporal_value=self.temporal_value,
            temporal_qualifier=None,
            occurrence_status=occ,
            polarity=pol if pol in ("AFFIRMATIVE", "NEGATIVE", "DOUBLE_NEGATIVE", "REPORTED_NEGATIVE", "UNCONFIRMED") else "AFFIRMATIVE",
            is_repeatable_event=(self.event_type == "COMMUNICATION"),
            value=raw_amount,
            condition=self.condition,
            confidence=self.confidence,
            provenance=self.provenance,
        )


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

    def to_proposition(self) -> SemanticProposition:
        """새로운 SemanticProposition 모델로 변환한다."""
        speech_act: Literal[
            "STATEMENT", "REQUEST", "PROPOSAL", "ACCEPTANCE", "REJECTION", "NOTICE", "QUESTION", "PROMISE"
        ] = "STATEMENT"
        if self.occurrence_status == "PROPOSED":
            speech_act = "PROPOSAL"
        elif self.occurrence_status == "REQUESTED":
            speech_act = "REQUEST"
        elif self.event_type == "NOTICE":
            speech_act = "NOTICE"

        epistemic: Literal[
            "ASSERTED", "REPORTED", "DOCUMENT_STATES", "UNKNOWN", "NOT_VERIFIED", "INFERRED"
        ] = "ASSERTED"
        if self.polarity == "UNCONFIRMED" or self.semantic_category == "EPISTEMIC_STATUS":
            epistemic = "NOT_VERIFIED"
        elif self.occurrence_status == "ALLEGED":
            epistemic = "REPORTED"

        val_dict = None
        if self.value is not None:
            if isinstance(self.value, (int, float)):
                val_dict = {"amount": int(self.value), "currency": "KRW"}
            elif isinstance(self.value, dict):
                val_dict = self.value

        inst_key = None
        if self.event_type == "ENCUMBRANCE":
            inst_key = f"ENCUMBRANCE:{self.object_key or 'GENERIC'}:{self.value or 'ANY'}"
        elif self.event_type == "COMMUNICATION":
            inst_key = f"COMMUNICATION:{self.temporal_value or 'ANY'}:{self.event_subtype or 'MSG'}"

        pol: Literal["AFFIRMATIVE", "NEGATIVE", "DOUBLE_NEGATIVE", "REPORTED_NEGATIVE", "UNKNOWN"] = "UNKNOWN"
        if self.polarity == "AFFIRMATIVE":
            pol = "AFFIRMATIVE"
        elif self.polarity == "NEGATIVE":
            pol = "NEGATIVE"
        elif self.polarity == "DOUBLE_NEGATIVE":
            pol = "DOUBLE_NEGATIVE"
        elif self.polarity == "REPORTED_NEGATIVE":
            pol = "REPORTED_NEGATIVE"
        elif self.polarity == "UNCONFIRMED":
            pol = "UNKNOWN"

        sem_cat: Literal[
            "EVENT", "STATE", "OBLIGATION", "RIGHT", "CONDITION", "DOCUMENT_METADATA", "SOURCE_AVAILABILITY", "EPISTEMIC_STATUS", "ASSERTION", "UNKNOWN"
        ] = "UNKNOWN"
        if self.semantic_category in ("EVENT", "STATE", "OBLIGATION", "CONDITION", "UNKNOWN"):
            sem_cat = self.semantic_category  # type: ignore
        elif self.semantic_category == "IDENTITY":
            sem_cat = "STATE"
        elif self.semantic_category == "METADATA":
            sem_cat = "DOCUMENT_METADATA"
        elif self.semantic_category == "EPISTEMIC_STATUS":
            sem_cat = "EPISTEMIC_STATUS"

        prov = self.provenance or {}

        return SemanticProposition(
            statement=self.statement,
            subject_key=self.subject_key,
            object_key=self.object_key,
            predicate_key=self.predicate,
            semantic_category=sem_cat,
            event_type=self.event_type,
            event_subtype=self.event_subtype,
            event_instance_key=inst_key,
            value=val_dict,
            value_role=self.event_subtype,
            temporal_type=self.temporal_type,
            temporal_value=self.temporal_value,
            condition=self.condition,
            polarity=pol,
            epistemic_status=epistemic,
            speech_act=speech_act,
            speaker_key=self.subject_key,
            source_evidence_id=prov.get("evidence_id"),
            source_claim_id=prov.get("claim_id"),
            source_span_ids=prov.get("span_ids", []),
            confidence=self.confidence,
            provenance=prov,
        )


class ComparabilityResult(BaseModel):
    """
    두 명제 간의 비교 가능성(Comparability Gate) 판정 결과 모델.

    Section 8.3 (P0-04) 요구사항 반영:
    비교 가능 여부뿐만 아니라 동일성 평가 상태(identity_status), 일치/불일치/누락 차원 목록을 제공한다.
    """

    is_comparable: bool = Field(..., description="두 명제가 상충 여부를 비교할 수 있는 동일 명제인지 여부")
    status: Literal[
        "COMPARABLE",
        "DIFFERENT_CONTEXT",
        "INSUFFICIENT_INFORMATION",
        "CONSISTENT",
    ] = Field(..., description="비교 관문 통과 상태")
    identity_status: Literal[
        "IDENTICAL",
        "COMPATIBLE",
        "DIFFERENT",
        "UNCERTAIN",
    ] = Field("DIFFERENT", description="동일성 상태 분류")
    reason_code: str = Field(..., description="구체적 사유 코드")
    explanation: str = Field(..., description="사용자 친화적 설명")
    matched_dimensions: List[str] = Field(default_factory=list, description="일치한 평가 차원 목록")
    mismatched_dimensions: List[str] = Field(default_factory=list, description="불일치한 평가 차원 목록")
    missing_dimensions: List[str] = Field(default_factory=list, description="비교에 누락된 차원 목록")
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

    # (A) METADATA: 문서 정보, 제목, 작성일, 발급일
    if claim_type in ("DOC_INFO", "DOCUMENT_INFO") or any(
        kw in compact for kw in (
            "문서의제목", "문서제목", "본문서는", "이문서는", "작성된전사본", "원음파일",
            "문서작성일", "작성일은", "작성일자", "작성일이", "발급일은", "발급일자", "발급일이", "작성되었다", "문서의작성"
        )
    ):
        sem_category = "METADATA"
        event_type = "DOCUMENT_METADATA"
        if any(kw in compact for kw in ("작성일", "발급일", "작성일자", "발급일자")):
            event_subtype = "DOCUMENT_CREATION_DATE"
        else:
            event_subtype = "DOCUMENT_TITLE"
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
    elif any(kw in compact for kw in ("의무가있다", "의무를부담", "이행할의무", "해야한다", "책임이자신에게", "의무를이행")):
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

    # (E) PAYMENT: 금원 지급 관련 (계약금, 중도금, 잔금, 보증금 총액, 차임, 급여 등)
    # 단, 출입카드/열쇠(KEY_DELIVERY) 및 가압류/근저당(ENCUMBRANCE)은 별도 유형으로 분리
    elif any(kw in compact for kw in (
        "지급", "반환", "이체", "납부", "입금", "청구금액", "보증금", "전세금", "계약금", "잔금", "중도금", "차임", "월세", "급여", "임금", "합계는"
    )) and not any(kw in compact for kw in ("임대차기간", "계약기간", "존속기간", "가입여부", "출입카드", "열쇠", "가압류", "근저당", "소유권")):
        event_type = "PAYMENT"
        
        # 합계 / 총액 / 보증금 전체
        if "합계" in compact or "총액" in compact or "전체" in compact:
            event_subtype = "TOTAL_AMOUNT"
        elif "보증금" in compact and ("계약금" in compact or "잔금" in compact) and ("중" in compact or "포함" in compact):
            event_subtype = "PRINCIPAL_DEPOSIT"
        elif "계약금" in compact and not ("보증금" in compact and "중" in compact):
            event_subtype = "DOWN_PAYMENT"
        elif "중도금" in compact:
            event_subtype = "INTERIM_PAYMENT"
        elif "잔금" in compact and not ("보증금" in compact and "중" in compact):
            event_subtype = "BALANCE_PAYMENT"
        elif "차임" in compact or "월세" in compact:
            event_subtype = "RENT"
        elif "급여" in compact or "임금" in compact:
            event_subtype = "WAGE"
        elif ("반환" in compact or "변제" in compact or "돌려" in compact) and (
            "일부" in compact or "중" in compact or not ("보증금" in compact and ("계약" in compact or "원금" in compact))
        ):
            event_subtype = "RETURN_AMOUNT"
        else:
            event_subtype = "PRINCIPAL_DEPOSIT"

        # 시점 및 발생 성격 구분
        if any(kw in compact for kw in ("기일", "예정일", "약정", "하기로함", "지급한다", "반환한다", "지급하기로", "반환하기로")):
            sem_category = "OBLIGATION"
            temporal_type = "DUE_AT" if primary_date else "SCHEDULED_AT"
            occurrence_status = "SCHEDULED"
        elif any(kw in compact for kw in ("요청", "요구", "청구")):
            sem_category = "EVENT"
            temporal_type = "REQUESTED_AT" if primary_date else "NONE"
            occurrence_status = "REQUESTED"
        elif any(kw in compact for kw in ("지급하였", "지급함", "지급되었", "지급됐", "지급된", "이체", "납부", "입금", "반환하였", "반환함", "반환되었")):
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT" if primary_date else "NONE"
            occurrence_status = "ACTUAL"
        elif any(kw in compact for kw in ("기준", "현재", "미반환상태", "미반환", "못했다", "반환되지", "지급되지", "돌려받지")):
            sem_category = "STATE"
            temporal_type = "VALID_AT" if primary_date else "NONE"
            occurrence_status = "ACTUAL"
        else:
            sem_category = "EVENT"
            temporal_type = "OCCURRED_AT" if primary_date else "NONE"
            occurrence_status = "ACTUAL"

        # 지급·반환의 '제안'은 실제 지급행위가 아니라 앞으로의 이행방식에 대한 의사표시이다.
        # 반환하지 않고 분할 반환을 제안했다는 문장을 실제 미반환/반환 완료와 동일한 행위로 비교하지 않는다.
        if any(kw in compact for kw in ("제안하", "제안했다", "제안함", "방안을제시", "분할반환을제시")) and not any(
            kw in compact for kw in ("제안하지않", "제안한적없", "제안을거절")
        ):
            occurrence_status = "PROPOSED"
            sem_category = "EVENT"
            temporal_type = "REPORTED_AT" if primary_date else "NONE"

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
# 3-1. 사실 명제 추출 함수 (extract_semantic_proposition)
# ==============================================================================

def extract_semantic_proposition(
    statement: str,
    context: Optional[Dict[str, Any]] = None,
) -> SemanticProposition:
    """단일 진술문(statement)과 문맥으로부터 다차원 정규화된 SemanticProposition을 추출한다.

    Section 5 (P0-01) 요구사항 반영:
    1. 화행(Speech Act: STATEMENT, REQUEST, PROPOSAL, ACCEPTANCE, REJECTION, NOTICE 등) 분석
    2. 인식 상태(Epistemic Status: ASSERTED, REPORTED, DOCUMENT_STATES, NOT_VERIFIED, INFERRED) 분석
    3. 고유 인스턴스 키(event_instance_key) 생성으로 동일 채권/사건/메시지 인스턴스 식별
    4. 정보 부족(NOT_VERIFIED/SOURCE_AVAILABILITY)과 실체적 부정(NEGATIVE)의 엄격한 분리

    Args:
        statement: 분석 대상 진술문.
        context: 선택적 문맥 딕셔너리.

    Returns:
        SemanticProposition: 정규화된 법적 사실 명제 인스턴스.
    """
    stmt = (statement or "").strip()
    ctx = context or {}
    compact = re.sub(r"\s+", "", stmt)

    sem_fact = extract_semantic_fact(stmt, context=ctx)
    prop = sem_fact.to_proposition()

    # 1. 화행(Speech Act) 정밀 추출 (CASE-04: 제안 vs 거절 분리)
    if any(kw in compact for kw in ("방안을제안", "제안하였", "조건을제안", "제안함", "제시하였", "제안했다")):
        prop.speech_act = "PROPOSAL"
    elif any(kw in compact for kw in ("동의하지않", "거절하였", "거부하였", "받아들이지않", "응하지않", "거절함", "거부함")):
        prop.speech_act = "REJECTION"
    elif any(kw in compact for kw in ("요청하였", "요구하였", "촉구하였", "청구하였", "달라고요구", "해달라고요구")):
        prop.speech_act = "REQUEST"
    elif any(kw in compact for kw in ("동의하였", "수락하였", "합의하였", "승낙하였")):
        prop.speech_act = "ACCEPTANCE"
    elif any(kw in compact for kw in ("통보하였", "통지하였", "고지하였", "알렸")):
        prop.speech_act = "NOTICE"

    # 2. 인식 상태(Epistemic Status) 및 정보 부족 분리 (CASE-01, CASE-05, CASE-06)
    if any(kw in compact for kw in (
        "확인되지않았", "확인되지않음", "미확인이다", "미확인.", "확인하지못",
        "자료가제출되지", "자료가없", "원본이제출되지", "제출되지않았", "판단할수없",
        "가입여부는확인되지", "별도확인이필요", "알수없"
    )):
        prop.epistemic_status = "NOT_VERIFIED"
        prop.polarity = "UNKNOWN"  # 증거 부족은 부정 사실(NEGATIVE)이 아님! (원칙 2.1)
        if any(kw in compact for kw in ("제출되지않았", "자료가없", "원본이제출되지")):
            prop.semantic_category = "SOURCE_AVAILABILITY"
        else:
            prop.semantic_category = "EPISTEMIC_STATUS"
    elif any(kw in compact for kw in ("기억한다", "들었다", "진술상", "주장한다", "말했다")):
        prop.epistemic_status = "REPORTED"
    elif any(kw in compact for kw in ("기재되어있", "명시되어있", "기재됨", "명시됨")):
        prop.epistemic_status = "DOCUMENT_STATES"

    # 3. 인스턴스 키(event_instance_key) 생성 (CASE-02, CASE-07 등 별개 인스턴스 분리)
    if prop.event_type == "ENCUMBRANCE":
        amt_str = str(sem_fact.value) if sem_fact.value else "UNKNOWN"
        prop.event_instance_key = f"ENCUMBRANCE:{prop.object_key or 'GENERIC'}:{amt_str}"
    elif prop.event_type == "COMMUNICATION":
        prop.event_instance_key = f"COMMUNICATION:{prop.temporal_value or 'ANY'}:{prop.speech_act or 'MSG'}"
    elif prop.speech_act in ("PROPOSAL", "REJECTION"):
        prop.event_instance_key = f"SPEECH_ACT:{prop.speech_act}:{prop.speaker_key or 'PARTY'}"

    # 출처 및 Span 정보
    prop.source_evidence_id = ctx.get("evidence_id")
    prop.source_claim_id = ctx.get("claim_id")
    prop.source_span_ids = ctx.get("source_span_ids", [])

    return prop


# ==============================================================================
# 4. 사실 명제 비교 함수 (check_proposition_comparability & compare_fact_identity)
# ==============================================================================

def check_proposition_comparability(
    proposition_a: SemanticProposition,
    proposition_b: SemanticProposition,
) -> ComparabilityResult:
    """두 SemanticProposition이 상충 여부를 검증할 수 있는 동일 명제인지 8대 차원으로 판정한다.

    Section 8 (P0-04) 요구사항 반영:
    1. 동일 주체(Subject) 비교
    2. 동일 객체/거래(Object) 비교
    3. 동일 속성/행위(Predicate) 비교
    4. 행위 인스턴스(Event Instance) 비교
    5. 거래 단계(Transaction Stage) 비교
    6. 시간적 의미(Temporal Semantics) 비교
    7. 상태 기준(State Criteria) 비교
    8. 화행/의사표시(Speech Act) 비교

    Args:
        proposition_a: 첫 번째 SemanticProposition.
        proposition_b: 두 번째 SemanticProposition.

    Returns:
        ComparabilityResult: 비교 관문 판정 결과.
    """
    matched: List[str] = []
    mismatched: List[str] = []
    missing: List[str] = []

    pa, pb = proposition_a, proposition_b

    # 1. 문서 고유 메타데이터 (DOC_INFO / DOCUMENT_METADATA / 작성일자 / 발급일자)
    is_meta_a = (
        pa.semantic_category in ("METADATA", "DOCUMENT_METADATA")
        or pa.event_type == "DOCUMENT_METADATA"
        or any(kw in (pa.statement or "") for kw in ("문서 작성일", "작성일자", "작성일", "발급일자", "발급일"))
    )
    is_meta_b = (
        pb.semantic_category in ("METADATA", "DOCUMENT_METADATA")
        or pb.event_type == "DOCUMENT_METADATA"
        or any(kw in (pb.statement or "") for kw in ("문서 작성일", "작성일자", "작성일", "발급일자", "발급일"))
    )

    if is_meta_a and is_meta_b:
        doc_a = (pa.provenance or {}).get("document_name") or (pa.provenance or {}).get("evidence_id")
        doc_b = (pb.provenance or {}).get("document_name") or (pb.provenance or {}).get("evidence_id")
        # 개별 문서마다 고유한 작성일·제목이 존재하므로 두 문서가 다르거나 진술문이 다른 경우 비상충(DIFFERENT_CONTEXT)
        if (doc_a and doc_b and doc_a != doc_b) or pa.statement != pb.statement:
            mismatched.append("DOCUMENT_LOCAL_METADATA")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DOCUMENT_LOCAL_METADATA",
                explanation="서로 다른 증거 문서의 고유 메타데이터(문서 제목·작성일·발급일)는 각 문서에 국한된 개별 사실입니다.",
                matched_dimensions=matched,
                mismatched_dimensions=mismatched,
                subject_match_basis=f"DocA: {doc_a} vs DocB: {doc_b}",
            )

    # 2. 증거 부족 및 인식 상태 (원칙 2.1: 증거 부족은 상충이 아님, CASE-01, CASE-05, CASE-06)
    if (
        pa.epistemic_status == "NOT_VERIFIED"
        or pb.epistemic_status == "NOT_VERIFIED"
        or pa.semantic_category in ("EPISTEMIC_STATUS", "SOURCE_AVAILABILITY")
        or pb.semantic_category in ("EPISTEMIC_STATUS", "SOURCE_AVAILABILITY")
    ):
        mismatched.append("EPISTEMIC_STATUS")
        reason_code = "EPISTEMIC_STATUS_NOT_CONTRADICTION"
        if pa.semantic_category == "SOURCE_AVAILABILITY" or pb.semantic_category == "SOURCE_AVAILABILITY":
            reason_code = "SOURCE_AVAILABILITY_NOT_FACT_NEGATION"
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            identity_status="DIFFERENT",
            reason_code=reason_code,
            explanation="진술이 사실의 확인 여부(미확인, 자료 미제출)에 관한 메타 진술이므로 실체적 사실과 상충하지 않으며 증거 공백(EVIDENCE_GAP)에 해당합니다.",
            matched_dimensions=matched,
            mismatched_dimensions=mismatched,
            predicate_match_basis="Epistemic status vs Factual assertion",
        )

    # 3. 화행(Speech Act) 분리: 제안(PROPOSAL) vs 거절(REJECTION) (CASE-04)
    if {pa.speech_act, pb.speech_act} == {"PROPOSAL", "REJECTION"}:
        mismatched.append("SPEECH_ACT")
        return ComparabilityResult(
            is_comparable=False,
            status="CONSISTENT",
            identity_status="COMPATIBLE",
            reason_code="PROPOSAL_VS_REJECTION",
            explanation="임대인의 분할 반환 제안(PROPOSAL)과 임차인의 거절(REJECTION)은 서로 다른 별개 의사표시로서 양립 가능하며 모순이 아닙니다.",
            matched_dimensions=matched,
            mismatched_dimensions=mismatched,
            predicate_match_basis="Proposal responds to Rejection",
        )

    # 3-0. 분할 지급·반환 제안과 즉시 이행 곤란 진술은 서로 설명 가능한 별개 사실이다.
    # 두 진술 모두 실제 지급 여부를 확정하지 않으므로 상충 및 교차 입증(SUPPORTS)으로 승격하지 않는다.
    # 특정 사건/인물/금액이 아니라 화행, 행위 대상, 지급 능력 표현으로 판정한다.
    proposals = [p for p in (pa, pb) if p.speech_act == "PROPOSAL"]
    if len(proposals) == 1:
        proposal = proposals[0]
        other = pb if proposal is pa else pa
        proposal_text = proposal.statement or ""
        other_text = other.statement or ""
        payment_actions = ("반환", "지급", "상환", "변제", "돌려")
        difficulty_terms = ("어렵", "곤란", "불가능", "힘들", "자금부족", "여의치않")
        same_actor = not (
            proposal.subject_key and other.subject_key
            and proposal.subject_key != other.subject_key
        )
        if (
            same_actor
            and proposal.event_type in ("PAYMENT", "LOAN", "PAYMENT_OBLIGATION")
            and other.event_type in ("PAYMENT", "LOAN", "PAYMENT_OBLIGATION")
            and other.speech_act not in ("REJECTION", "ACCEPTANCE")
            and any(word in proposal_text and word in other_text for word in payment_actions)
            and any(term in other_text.replace(" ", "") for term in difficulty_terms)
        ):
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="COMPATIBLE",
                reason_code="PAYMENT_PROPOSAL_VS_CAPACITY_STATEMENT",
                explanation=(
                    "분할 지급·반환 방안을 제안한 사실과 즉시 전액 이행이 어렵다는 진술은 "
                    "동시에 참일 수 있는 별개의 의사표시이며 실제 지급 여부를 증명하지 않습니다."
                ),
                matched_dimensions=["PAYMENT_CONTEXT", "COMPATIBLE_SPEECH_ACT"],
                mismatched_dimensions=["PROPOSAL_VS_CAPACITY_STATEMENT"],
                predicate_match_basis="Proposal speech act vs reported ability to perform",
            )

    # 3-1. 화행(Speech Act) 분리: 의사표시/해지 통지(NOTICE) vs 이행/퇴거 예정일(STATEMENT/SCHEDULE)
    # 설명: 임차인이 임대인에게 퇴거 의사를 통지한 행위(통지일)와 실제 퇴거 예정일(목표일)은 서로 다른 시점 차원의 양립 가능한 사실이다.
    is_notice_a = pa.speech_act == "NOTICE" or any(kw in (pa.statement or "") for kw in ("알렸", "통지", "통보", "고지", "보냈다"))
    is_notice_b = pb.speech_act == "NOTICE" or any(kw in (pb.statement or "") for kw in ("알렸", "통지", "통보", "고지", "보냈다"))
    if is_notice_a != is_notice_b:
        mismatched.append("COMMUNICATION_NOTICE_VS_SCHEDULE")
        return ComparabilityResult(
            is_comparable=False,
            status="CONSISTENT",
            identity_status="COMPATIBLE",
            reason_code="NOTICE_DATE_VS_TARGET_DATE",
            explanation="의사표시·해지 통지를 발송한 일자와 퇴거·이행을 예정한 목표일자는 서로 다른 시점 차원의 양립 가능한 사실입니다.",
            matched_dimensions=matched,
            mismatched_dimensions=mismatched,
            temporal_semantics="Notice Date vs Scheduled Target Date",
        )

    # 3-2. 급부 대상(Object) 분리: 열쇠·출입카드(목적물 인도) vs 보증금·차임(금전 지급)
    # 설명: 임차인의 열쇠·출입카드 반환 의무와 임대인의 보증금 반환 의무는 동시이행 관계에 있는
    # 서로 다른 독립된 급부 대상이므로 상충 대상이 아니다.
    c_is_key = any(kw in (pa.statement or "") for kw in ("출입카드", "열쇠", "비밀번호", "목적물 인도", "명도"))
    f_is_key = any(kw in (pb.statement or "") for kw in ("출입카드", "열쇠", "비밀번호", "목적물 인도", "명도"))
    c_is_deposit = any(kw in (pa.statement or "") for kw in ("보증금", "전세금", "차임", "월세", "청구금액"))
    f_is_deposit = any(kw in (pb.statement or "") for kw in ("보증금", "전세금", "차임", "월세", "청구금액"))
    if (c_is_key and f_is_deposit) or (f_is_key and c_is_deposit):
        mismatched.append("PERFORMANCE_OBJECT")
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            identity_status="DIFFERENT",
            reason_code="DIFFERENT_PERFORMANCE_OBJECT",
            explanation="목적물 인도(열쇠·출입카드 반환) 의무와 보증금 반환 의무는 서로 다른 별개의 법률상 급부 대상입니다.",
            mismatched_dimensions=mismatched,
            predicate_match_basis="Key delivery vs Deposit refund",
        )

    # 3-3. 화행 및 이행 상태 분리: 이행 청구·반환 요청(REQUEST) vs 미이행·미반환 상태(NEGATIVE/STATE)
    # 설명: 보증금 반환을 청구·요청한 사실(REQUEST)과 현재까지 보증금이 반환되지 않은 상태(NEGATIVE)는
    # 서로 모순되는 것이 아니라, 반환되지 않았기 때문에 반환을 요청하거나 소송을 제기하는 정상적·보완적 사실관계이다.
    is_request_a = (
        pa.speech_act == "REQUEST"
        or pa.temporal_type == "REQUESTED_AT"
        or any(kw in (pa.statement or "") for kw in ("반환을 요청", "반환 요청", "청구하였", "요구하였", "촉구하였", "반환 일정을", "알려달라고"))
    )
    is_request_b = (
        pb.speech_act == "REQUEST"
        or pb.temporal_type == "REQUESTED_AT"
        or any(kw in (pb.statement or "") for kw in ("반환을 요청", "반환 요청", "청구하였", "요구하였", "촉구하였", "반환 일정을", "알려달라고"))
    )
    is_negative_perf_a = (
        pa.polarity in ("NEGATIVE", "REPORTED_NEGATIVE")
        or any(kw in (pa.statement or "") for kw in ("반환되지 않", "미반환", "지급되지 않", "돌려받지 못", "받지 못"))
    )
    is_negative_perf_b = (
        pb.polarity in ("NEGATIVE", "REPORTED_NEGATIVE")
        or any(kw in (pb.statement or "") for kw in ("반환되지 않", "미반환", "지급되지 않", "돌려받지 못", "받지 못"))
    )

    if (is_request_a and is_negative_perf_b) or (is_request_b and is_negative_perf_a):
        matched.append("DEPOSIT_CLAIM_HARMONY")
        return ComparabilityResult(
            is_comparable=False,
            status="CONSISTENT",
            identity_status="COMPATIBLE",
            reason_code="REQUEST_ACCOMPANIES_NON_PERFORMANCE",
            explanation="보증금 반환을 요청한 사실과 보증금이 반환되지 않은 상태는 서로 모순되지 않고 양립하는 정상적 사실관계입니다.",
            matched_dimensions=matched,
            predicate_match_basis="Demand for payment accompanies default/unpaid state",
        )

    # 3-4. 등기부상 권리 설정(ENCUMBRANCE: 가압류, 근저당권) 건별 분리
    # 설명: 부동산 등기부에는 채권자 또는 청구금액이 다른 여러 건의 가압류·근저당권이 공존할 수 있으며,
    # 이는 상충이 아니라 복수의 권리설정 인스턴스이다.
    if pa.event_type == "ENCUMBRANCE" and pb.event_type == "ENCUMBRANCE":
        val_a = (pa.value or {}).get("amount") if isinstance(pa.value, dict) else pa.value
        val_b = (pb.value or {}).get("amount") if isinstance(pb.value, dict) else pb.value
        if pa.object_key and pb.object_key and pa.object_key != pb.object_key:
            mismatched.append("OBJECT_QUALIFIER")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_OBJECT_QUALIFIER",
                explanation=f"등기부상 서로 다른 권리 또는 채권자 건입니다 ({pa.object_key} vs {pb.object_key}).",
                mismatched_dimensions=mismatched,
                subject_match_basis=f"Encumbrance: {pa.object_key} vs {pb.object_key}",
            )
        if (
            (val_a is not None and val_b is not None and val_a != val_b)
            or (pa.event_instance_key and pb.event_instance_key and pa.event_instance_key != pb.event_instance_key)
        ):
            mismatched.append("ENCUMBRANCE_INSTANCE")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_EVENT_INSTANCE",
                explanation="부동산 등기부상 채권자 또는 청구금액이 서로 다른 별개의 가압류·권리설정 건입니다.",
                mismatched_dimensions=mismatched,
                subject_match_basis=f"Encumbrance: {pa.event_instance_key} vs {pb.event_instance_key}",
            )

    # 4. 거래 단계 및 구성항목 분리: 계약금/잔금 vs 보증금 총액 (CASE-03, S01, S06, S07)
    subtypes = {pa.event_subtype, pb.event_subtype} - {None}
    if pa.event_type == "PAYMENT" and pb.event_type == "PAYMENT":
        # (A) 계약금 또는 잔금과 보증금 총액의 관계: COMPONENT_OF / SUM_OF
        # 총액/합계가 명시되었거나 value_role이 TOTAL_AMOUNT/SUM_OF인 경우 COMPONENT_OF_SUM 판정
        is_component_relation = False
        if ("DOWN_PAYMENT" in subtypes or "BALANCE_PAYMENT" in subtypes) and (
            "TOTAL_AMOUNT" in subtypes or "SUM_OF" in subtypes
        ):
            is_component_relation = True
        elif ("DOWN_PAYMENT" in subtypes or "BALANCE_PAYMENT" in subtypes) and "PRINCIPAL_DEPOSIT" in subtypes:
            if any("합계" in (p.statement or "") or "총" in (p.statement or "") for p in (pa, pb)):
                is_component_relation = True

        if is_component_relation:
            return ComparabilityResult(
                is_comparable=False,
                status="CONSISTENT",
                identity_status="COMPATIBLE",
                reason_code="COMPONENT_OF_SUM",
                explanation="계약금이나 잔금은 보증금 총액의 구성항목(PART_OF)이므로 총액과 모순되지 않고 양립합니다.",
                matched_dimensions=["PAYMENT_DOMAIN"],
                mismatched_dimensions=["PAYMENT_COMPONENT_STAGE"],
                predicate_match_basis=f"Component: {pa.event_subtype} vs {pb.event_subtype}",
            )

        # (B) 보증금 원금과 반환 요청 금액의 동일 금액인 경우
        if subtypes in (
            {"PRINCIPAL_DEPOSIT", "RETURN_AMOUNT"},
            {"PRINCIPAL_DEPOSIT", "TOTAL_AMOUNT"},
            {"RETURN_AMOUNT", "TOTAL_AMOUNT"},
        ):
            val_a = (pa.value or {}).get("amount") if isinstance(pa.value, dict) else pa.value
            val_b = (pb.value or {}).get("amount") if isinstance(pb.value, dict) else pb.value
            if val_a is not None and val_b is not None and val_a == val_b:
                matched.extend(["PAYMENT_AMOUNT", "PAYMENT_DOMAIN"])
                return ComparabilityResult(
                    is_comparable=False,
                    status="CONSISTENT",
                    identity_status="COMPATIBLE",
                    reason_code="PAYMENT_AMOUNT_MATCH",
                    explanation="계약상 보증금 원금과 반환 요청 금액의 정규화 수치가 일치하여 상호 지지(CONSISTENT)합니다.",
                    matched_dimensions=matched,
                    predicate_match_basis="PrincipalDeposit matches ReturnAmount",
                )
            else:
                return ComparabilityResult(
                    is_comparable=False,
                    status="DIFFERENT_CONTEXT",
                    identity_status="DIFFERENT",
                    reason_code="DIFFERENT_AMOUNT_ATTRIBUTE",
                    explanation=f"지급 구성 항목이 서로 다른 별개 거래 단계입니다 ({pa.event_subtype} vs {pb.event_subtype}).",
                    mismatched_dimensions=["PAYMENT_SUBTYPE"],
                )
        elif len(subtypes) >= 2 and pa.event_subtype != pb.event_subtype:
            mismatched.append("PAYMENT_SUBTYPE")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_PAYMENT_COMPONENT",
                explanation=f"지급 구성 항목이 서로 다른 별개 거래 단계입니다 ({pa.event_subtype} vs {pb.event_subtype}).",
                mismatched_dimensions=mismatched,
                predicate_match_basis=f"Subtypes: {pa.event_subtype} != {pb.event_subtype}",
            )

    # 5. 근로계약 단계 분리: 입사(HIRE) vs 퇴사(RESIGNATION)
    if pa.event_type == "EMPLOYMENT" and pb.event_type == "EMPLOYMENT":
        if len(subtypes) >= 2 and pa.event_subtype != pb.event_subtype:
            mismatched.append("EMPLOYMENT_STAGE")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_EMPLOYMENT_STAGE",
                explanation=f"근로관계 단계가 서로 다른 별개 사건입니다 ({pa.event_subtype} vs {pb.event_subtype}).",
                mismatched_dimensions=mismatched,
                predicate_match_basis=f"EmploymentSubtypes: {pa.event_subtype} != {pb.event_subtype}",
            )

    # 6. 채권채무 단계 분리: 대여(LOAN_ORIGINATION) vs 일부 변제(PARTIAL_REPAYMENT)
    if pa.event_type == "LOAN" and pb.event_type == "LOAN":
        if len(subtypes) >= 2 and pa.event_subtype != pb.event_subtype:
            mismatched.append("LOAN_STAGE")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_TRANSACTION_STAGE",
                explanation=f"채권채무 거래 단계가 서로 다른 별개 사실입니다 ({pa.event_subtype} vs {pb.event_subtype}).",
                mismatched_dimensions=mismatched,
                predicate_match_basis=f"LoanSubtypes: {pa.event_subtype} != {pb.event_subtype}",
            )

    # 7. 통지/의사소통 단계 분리: 발송(NOTICE_SENT) vs 도달(NOTICE_REACHED)
    if pa.event_type == "COMMUNICATION" and pb.event_type == "COMMUNICATION":
        if "NOTICE_SENT" in subtypes and "NOTICE_REACHED" in subtypes:
            mismatched.append("COMMUNICATION_STAGE")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_COMMUNICATION_STAGE",
                explanation="의사표시 발송 시점과 도달·수령 시점은 구별되는 별개의 절차입니다.",
                mismatched_dimensions=mismatched,
                predicate_match_basis="NoticeSent vs NoticeReached",
            )

    # 8. 고유 사건 인스턴스(event_instance_key) 및 객체 한정자 불일치 (CASE-02, CASE-07)
    if pa.object_key and pb.object_key and pa.object_key != pb.object_key:
        mismatched.append("OBJECT_QUALIFIER")
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            identity_status="DIFFERENT",
            reason_code="DIFFERENT_OBJECT_QUALIFIER",
            explanation=f"등기부상 서로 다른 권리 또는 채권자 건입니다 ({pa.object_key} vs {pb.object_key}).",
            mismatched_dimensions=mismatched,
            subject_match_basis=f"ObjectQualifier: {pa.object_key} != {pb.object_key}",
        )

    if pa.event_instance_key and pb.event_instance_key and pa.event_instance_key != pb.event_instance_key:
        mismatched.append("EVENT_INSTANCE")
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            identity_status="DIFFERENT",
            reason_code="DIFFERENT_EVENT_INSTANCE",
            explanation=f"서로 다른 별개의 사건·거래 인스턴스입니다 ({pa.event_instance_key} vs {pb.event_instance_key}).",
            mismatched_dimensions=mismatched,
        )

    # 9. 서로 다른 사건 대분류
    if pa.event_type and pb.event_type and pa.event_type != pb.event_type:
        mismatched.append("EVENT_TYPE")
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            identity_status="DIFFERENT",
            reason_code="DIFFERENT_EVENT_TYPE",
            explanation=f"서로 다른 법률 행위 및 사건 유형입니다 ({pa.event_type} vs {pb.event_type}).",
            mismatched_dimensions=mismatched,
            predicate_match_basis=f"EventType: {pa.event_type} != {pb.event_type}",
        )

    # 10. 행위(EVENT) vs 지속 상태(STATE) 분리 (CASE-01, CASE-05, S04, S05)
    categories = {pa.semantic_category, pb.semantic_category}
    if "EVENT" in categories and "STATE" in categories:
        mismatched.append("SEMANTIC_CATEGORY")
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            identity_status="DIFFERENT",
            reason_code="EVENT_VS_STATE",
            explanation="과거 특정 시점에 발생한 행위(EVENT)와 이후 특정 시점의 유지 상태(STATE)는 서로 다른 범주의 진술입니다.",
            mismatched_dimensions=mismatched,
            temporal_semantics=f"Category A: {pa.semantic_category} vs Category B: {pb.semantic_category}",
        )

    # 11. 시점 의미 중 약정기일(DUE_AT)과 실제 이행(OCCURRED_AT)이 동일 일자인 경우 (S03)
    tt_pair = {pa.temporal_type, pb.temporal_type}
    if "DUE_AT" in tt_pair and "OCCURRED_AT" in tt_pair:
        if pa.temporal_value and pb.temporal_value and pa.temporal_value == pb.temporal_value:
            matched.extend(["TEMPORAL_VALUE", "PAYMENT_PERFORMANCE"])
            return ComparabilityResult(
                is_comparable=False,
                status="CONSISTENT",
                identity_status="COMPATIBLE",
                reason_code="TEMPORALLY_COMPATIBLE",
                explanation="약정된 지급기일과 실제 지급일이 동일하여 정상적으로 이행된 양립 가능한 사실입니다.",
                matched_dimensions=matched,
                temporal_semantics=f"Both on {pa.temporal_value} (DUE_AT == OCCURRED_AT)",
            )

    # 12. 의무(OBLIGATION) vs 실제 이행/미이행(EVENT/STATE) 분리
    if "OBLIGATION" in categories and ("EVENT" in categories or "STATE" in categories):
        # 단, 금액 사실 간에 동일 금액인 경우는 서술어 형태 차이이므로 제외
        is_same_payment_amount = False
        if pa.event_type == "PAYMENT" and pb.event_type == "PAYMENT":
            val_a = (pa.value or {}).get("amount") if isinstance(pa.value, dict) else pa.value
            val_b = (pb.value or {}).get("amount") if isinstance(pb.value, dict) else pb.value
            if val_a is not None and val_b is not None and val_a == val_b:
                is_same_payment_amount = True

        if not is_same_payment_amount:
            mismatched.append("OBLIGATION_VS_PERFORMANCE")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_OBLIGATION_VS_PERFORMANCE",
                explanation="계약상 의무 부담 사실과 실제 이행/미이행 상태는 서술 층위가 다른 별개 사실입니다.",
                mismatched_dimensions=mismatched,
                predicate_match_basis="Obligation vs Performance status",
            )

    # 13. 기타 시점 의미 차이
    if (
        pa.temporal_type != pb.temporal_type
        and "NONE" not in (pa.temporal_type, pb.temporal_type)
    ):
        if "DUE_AT" in tt_pair and "OCCURRED_AT" in tt_pair:
            mismatched.append("TEMPORAL_SEMANTICS")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_TRANSACTION_STAGE",
                explanation="약정된 지급기일(DUE_AT)과 실제 지급 발생일(OCCURRED_AT)은 서로 다른 시간적 의미를 가집니다.",
                mismatched_dimensions=mismatched,
                temporal_semantics=f"TemporalTypes: {pa.temporal_type} vs {pb.temporal_type}",
            )
        if "REQUESTED_AT" in tt_pair and ("OCCURRED_AT" in tt_pair or "REPORTED_AT" in tt_pair):
            mismatched.append("TEMPORAL_SEMANTICS")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="DIFFERENT_TEMPORAL_SEMANTICS",
                explanation="반환/퇴거를 요청한 목표일자와 통지 의사표시를 발송한 일자는 서로 다른 시점 의미입니다.",
                mismatched_dimensions=mismatched,
                temporal_semantics=f"TemporalTypes: {pa.temporal_type} vs {pb.temporal_type}",
            )
        if "VALID_AT" in tt_pair and "OCCURRED_AT" in tt_pair:
            mismatched.append("TEMPORAL_SEMANTICS")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="EVENT_VS_STATE",
                explanation="상태 확인 기준일(VALID_AT)과 최초 행위 발생일(OCCURRED_AT)은 양립 가능한 별개 시점입니다.",
                mismatched_dimensions=mismatched,
                temporal_semantics=f"TemporalTypes: {pa.temporal_type} vs {pb.temporal_type}",
            )

    # 14. 반복 발생 의사소통 사건 (COMMUNICATION: 문자, 통화 등) (CASE-07)
    if (pa.event_type == "COMMUNICATION" or (pa.provenance or {}).get("is_repeatable")) and (
        pb.event_type == "COMMUNICATION" or (pb.provenance or {}).get("is_repeatable")
    ):
        if pa.temporal_value != pb.temporal_value:
            mismatched.append("COMMUNICATION_DATE")
            return ComparabilityResult(
                is_comparable=False,
                status="DIFFERENT_CONTEXT",
                identity_status="DIFFERENT",
                reason_code="REPEATABLE_COMMUNICATION_EVENT",
                explanation="사건 진행 경과 중 각기 다른 일시에 발송·수신된 별개의 의사소통(문자·통화·문의) 기록입니다.",
                mismatched_dimensions=mismatched,
                temporal_semantics=f"Dates: {pa.temporal_value} != {pb.temporal_value}",
            )

    # 15. 신원 정보(IDENTITY)와 일반 사건(EVENT)의 극성 오탐 차단 (CASE-01)
    if pa.semantic_category == "STATE" and pa.predicate_key in ("임차인", "임대인", "당사자") and pb.polarity == "NEGATIVE":
        mismatched.append("IDENTITY_VS_EVENT")
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            identity_status="DIFFERENT",
            reason_code="IDENTITY_VS_EVENT_POLARITY",
            explanation="당사자 신원 사실과 사건 이행 여부에 관한 부정 진술은 대상 범주가 다릅니다.",
            mismatched_dimensions=mismatched,
        )

    # 16. 공통 핵심 개념어(토큰) 존재 여부 검증 (전혀 다른 주제 간의 거짓 비교 승인 차단)
    from ai_legal_helper.case_intelligence.conflict_detector import extract_content_tokens, _find_shared_concepts
    tokens_a = extract_content_tokens(pa.statement or "")
    tokens_b = extract_content_tokens(pb.statement or "")
    shared_tokens = _find_shared_concepts(tokens_a, tokens_b)

    has_explicit_same_event = (
        pa.event_type
        and pb.event_type
        and pa.event_type != "GENERAL_FACT"
        and pa.event_type == pb.event_type
        and pa.event_subtype == pb.event_subtype
        and pa.event_subtype is not None
    )

    if not shared_tokens and not has_explicit_same_event:
        mismatched.append("CONTENT_TOPIC")
        return ComparabilityResult(
            is_comparable=False,
            status="DIFFERENT_CONTEXT",
            identity_status="DIFFERENT",
            reason_code="NO_SHARED_CONCEPT",
            explanation="두 사실 간에 공유되는 핵심 주제어 및 대상 개념이 존재하지 않는 별개의 진술입니다.",
            mismatched_dimensions=mismatched,
        )

    # 모든 관문 통과 시 상충 여부 검증 대상(COMPARABLE)으로 승인
    matched.extend(["SUBJECT_OR_CATEGORY", "EVENT_TYPE", "TEMPORAL_FRAME"])
    return ComparabilityResult(
        is_comparable=True,
        status="COMPARABLE",
        identity_status="IDENTICAL",
        reason_code="IDENTICAL_PROPOSITION_CANDIDATE",
        explanation="동일 대상·동일 행위·동일 시점 의미를 공유하므로 상충 여부 검증 대상입니다.",
        matched_dimensions=matched,
        subject_match_basis=f"Category: {pa.semantic_category}, EventType: {pa.event_type}",
        predicate_match_basis=f"Subtype: {pa.event_subtype}",
    )


def compare_fact_identity(
    fact_a: SemanticFact,
    fact_b: SemanticFact,
) -> ComparabilityResult:
    """두 SemanticFact가 상충 가능 여부를 검증할 수 있는 동일 명제인지 판정한다 (SemanticProposition 위임)."""
    prop_a = fact_a.to_proposition()
    prop_b = fact_b.to_proposition()
    return check_proposition_comparability(prop_a, prop_b)


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
