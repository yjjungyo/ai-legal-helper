# -*- coding: utf-8 -*-
"""
증거 신뢰성 평가 모듈 (Evidence Reliability Assessment Engine)

이 모듈은 AI Legal Helper의 증거 문서 및 추출 사실(EvidenceClaim / SemanticProposition)에 대해
문서 유형, 작성 주체, 증거의 직접성, 관련성, 완전성, 시점 적합성, 보강(Corroboration) 여부 등
7대 신뢰성 차원을 다각도로 평가하여 정량적 신뢰도 점수와 입증 범위(Proof Scope)를 산출한다.

[설계 원칙]
1. 문서 유형만으로 일률 평가하지 않고, 특정 사실(명제)에 대한 증명력을 개별 평가한다.
   (예: 임대차계약서는 '계약 체결 및 보증금 약정'에 대해서는 처분문서로서 완벽한 증명력을 가지나,
    '실제 전입신고'나 '보증보험 가입 여부'는 입증할 수 없음).
2. 직접 처분문서(BILATERAL_SIGNED, OFFICIAL_PUBLIC)가 뒷받침하는 핵심 사실은 무관한
   증거 부족(HUG 메모 미확인 등) 때문에 신뢰도나 확정 상태가 격하되지 않는다.
3. 한국어 코딩 주석 표준(CODING_COMMENT_STANDARD.md)을 엄격히 준수한다.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.fact_semantics import SemanticProposition


# ==============================================================================
# 1. 증거 신뢰성 평가 결과 Pydantic 모델
# ==============================================================================

class EvidenceAssessmentResult(BaseModel):
    """
    단일 증거 문서 및 명제에 대한 7대 차원 신뢰성 평가 결과 모델.
    """

    # 1. 출처 및 진정성 (Source Authenticity)
    source_authenticity: Literal[
        "OFFICIAL_PUBLIC",             # 공공기관·법원·등기소 등 공적 문서
        "BILATERAL_SIGNED",            # 양 당사자 서명/날인 쌍무 계약서
        "THIRD_PARTY_RECORD",          # 공인중개사, 금융기관, 우체국 등 제3자 객관적 기록
        "DISPUTED_PARTY_DOCUMENT",     # 진정성·위조 여부가 다투어지는 당사자 문서
        "PRIVATE_UNILATERAL",          # 일방 당사자 작성 서면 (내용증명 원문, 일방 메모)
        "INFORMAL_COMMUNICATION",      # 카카오톡, 문자메시지, 통화 녹취록
        "UNVERIFIED",                  # 출처 불명 또는 미확인
    ] = Field("UNVERIFIED", description="출처 공신력 및 진정성 등급")

    # 2. 증거 직접성 (Directness)
    directness: Literal[
        "DIRECT_DISPOSITIVE",          # 처분문서 (법률행위 자체를 성립·직접 증명)
        "DIRECT_REPORTED",             # 당사자 직접 의사표시 및 도달 사실의 직접 증명
        "INDIRECT_CIRCUMSTANTIAL",     # 간접 정황 사실 (추론 필요)
        "HEARSAY_UNSUPPORTED",         # 전언·전문 진술, 단순 기억
    ] = Field("INDIRECT_CIRCUMSTANTIAL", description="명제에 대한 증거의 직접성")

    # 3. 실체적 관련성 (Relevance)
    relevance: Literal[
        "DIRECTLY_RELEVANT",           # 소송물 및 주요 요건사실에 직접 결부
        "BACKGROUND",                  # 사건 경위 및 배경 사실
        "TANGENTIAL",                  # 부수적 정황 사실
        "IRRELEVANT",                  # 사건과 무관한 사실
    ] = Field("DIRECTLY_RELEVANT", description="사건 쟁점과의 관련성")

    # 4. 정보 완전성 (Completeness)
    completeness: Literal[
        "COMPLETE",                    # 전문 및 필수 기재사항 완비
        "PARTIAL_DEFICIENT",           # 일부 페이지 누락 또는 중요 항목 미기재
        "SUMMARY_ONLY",                # 요약본만 존재
    ] = Field("COMPLETE", description="문서의 완전성")

    # 5. 시간적 적합성 (Temporal Applicability)
    temporal_applicability: Literal[
        "CONTEMPORANEOUS",             # 법률행위 발생 당시 실시간 작성
        "SUBSEQUENT_RECORD",           # 사후 확인·정산 기록
        "RETROSPECTIVE_CLAIM",         # 분쟁 발생 후 일방적 사후 작성 주장
        "EXPIRED_OBSOLETE",            # 실효되거나 효력이 소멸한 과거 문서
    ] = Field("CONTEMPORANEOUS", description="시점 일치도 및 시간적 적합성")

    # 6. 타 증거와의 보강성 (Corroboration)
    corroboration: Literal[
        "FULLY_CORROBORATED",          # 다른 독립적 공적/처분문서에 의해 상호 뒷받침됨
        "PARTIALLY_CORROBORATED",      # 부분적으로 보강됨
        "UNCORROBORATED",              # 단독 증거 (반대 증거 없음)
        "DIRECTLY_CONTRADICTED",       # 더 신뢰성 높은 증거와 직접 대립함
    ] = Field("UNCORROBORATED", description="타 증거와의 상호 보강성")

    # 7. 디지털 출처 품질 (Provenance Quality)
    provenance_quality: Literal[
        "HIGH",                        # 원본 파일 해시, 추출 좌표 및 Span 온전
        "MEDIUM",                      # 일반 업로드 텍스트
        "LOW",                         # 불완전 추출 텍스트
    ] = Field("MEDIUM", description="데이터 원본성 및 출처 품질")

    # 종합 평가 지표
    reliability_score: float = Field(0.5, description="정규화된 종합 신뢰도 점수 (0.0 ~ 1.0)")
    assessment_status: Literal[
        "CONCLUSIVE",                  # 완벽한 증명력 (처분문서 및 공적 증명)
        "RELIABLE",                    # 높은 신뢰도 (우수한 증명력)
        "PROVISIONAL",                 # 잠정적 채택 (추가 보강 권장)
        "DEFICIENT",                   # 증거 부족 또는 신뢰성 취약
        "REJECTED",                    # 채택 불가 (위조 의심 또는 배척)
    ] = Field("PROVISIONAL", description="종합 증거 평가 상태")

    proof_scope: Dict[str, Any] = Field(
        default_factory=dict,
        description="해당 증거가 입증할 수 있는 사실 범위 및 입증 불가능한 한계",
    )
    summary: str = Field("", description="한국어 종합 평가 요약문")


# ==============================================================================
# 2. 증거 신뢰성 평가 계산 로직
# ==============================================================================

# 차원별 가중치 상수
_AUTHENTICITY_SCORES: Dict[str, float] = {
    "OFFICIAL_PUBLIC": 1.0,
    "BILATERAL_SIGNED": 0.95,
    "THIRD_PARTY_RECORD": 0.90,
    "PRIVATE_UNILATERAL": 0.70,
    "INFORMAL_COMMUNICATION": 0.65,
    "DISPUTED_PARTY_DOCUMENT": 0.50,
    "UNVERIFIED": 0.30,
}

_DIRECTNESS_SCORES: Dict[str, float] = {
    "DIRECT_DISPOSITIVE": 1.0,
    "DIRECT_REPORTED": 0.85,
    "INDIRECT_CIRCUMSTANTIAL": 0.60,
    "HEARSAY_UNSUPPORTED": 0.35,
}

_RELEVANCE_SCORES: Dict[str, float] = {
    "DIRECTLY_RELEVANT": 1.0,
    "BACKGROUND": 0.70,
    "TANGENTIAL": 0.40,
    "IRRELEVANT": 0.10,
}

_COMPLETENESS_SCORES: Dict[str, float] = {
    "COMPLETE": 1.0,
    "PARTIAL_DEFICIENT": 0.60,
    "SUMMARY_ONLY": 0.40,
}

_TEMPORAL_SCORES: Dict[str, float] = {
    "CONTEMPORANEOUS": 1.0,
    "SUBSEQUENT_RECORD": 0.85,
    "RETROSPECTIVE_CLAIM": 0.50,
    "EXPIRED_OBSOLETE": 0.30,
}

_CORROBORATION_SCORES: Dict[str, float] = {
    "FULLY_CORROBORATED": 1.0,
    "PARTIALLY_CORROBORATED": 0.80,
    "UNCORROBORATED": 0.60,
    "DIRECTLY_CONTRADICTED": 0.20,
}

_PROVENANCE_SCORES: Dict[str, float] = {
    "HIGH": 1.0,
    "MEDIUM": 0.80,
    "LOW": 0.50,
}


def evaluate_evidence_reliability(
    document_name: str,
    proposition: SemanticProposition,
    document_metadata: Optional[Dict[str, Any]] = None,
    other_evidence_propositions: Optional[List[SemanticProposition]] = None,
) -> EvidenceAssessmentResult:
    """단일 증거 문서와 명제 간의 7대 차원 신뢰성을 평가하여 EvidenceAssessmentResult를 생성한다.

    Args:
        document_name: 원본 증거 문서명 (예: '주택임대차계약서.pdf', '등기사항전부증명서.pdf').
        proposition: 증거 문서에서 추출된 정규화 사실 명제.
        document_metadata: 선택적 문서 부가 정보 (작성일자, 페이지 수 등).
        other_evidence_propositions: 동일 사건의 다른 증거 문서들에서 추출된 명제 목록 (상호 보강성 평가용).

    Returns:
        EvidenceAssessmentResult: 7대 차원 평가 및 종합 점수, 입증 한계가 기술된 객체.
    """
    doc_meta = document_metadata or {}
    other_props = other_evidence_propositions or []
    doc_name_lower = (document_name or "").lower()

    # --------------------------------------------------------------------------
    # 1. 문서 출처 및 진정성 (Source Authenticity) 판별
    # --------------------------------------------------------------------------
    authenticity: Literal[
        "OFFICIAL_PUBLIC", "BILATERAL_SIGNED", "THIRD_PARTY_RECORD",
        "DISPUTED_PARTY_DOCUMENT", "PRIVATE_UNILATERAL", "INFORMAL_COMMUNICATION", "UNVERIFIED"
    ] = "UNVERIFIED"

    if any(kw in doc_name_lower for kw in ("등기", "등기부", "판결", "결정문", "주민등록", "전입세대", "법원", "공공기관")):
        authenticity = "OFFICIAL_PUBLIC"
    elif any(kw in doc_name_lower for kw in ("계약서", "합의서", "임대차계약", "근로계약서", "협약서")):
        authenticity = "BILATERAL_SIGNED"
    elif any(kw in doc_name_lower for kw in ("이체", "영수증", "배달증명", "확인설명서", "공인중개", "통장", "잔액증명")):
        authenticity = "THIRD_PARTY_RECORD"
    elif any(kw in doc_name_lower for kw in ("내용증명", "통고서", "통지서", "최고서", "진술서", "각서")):
        authenticity = "PRIVATE_UNILATERAL"
    elif any(kw in doc_name_lower for kw in ("문자", "카톡", "카카오톡", "메시지", "녹취", "통화")):
        authenticity = "INFORMAL_COMMUNICATION"
    else:
        authenticity = "PRIVATE_UNILATERAL" if doc_name_lower else "UNVERIFIED"

    # --------------------------------------------------------------------------
    # 2. 증거 직접성 (Directness) 판별 (처분문서 vs 보고적 진술)
    # --------------------------------------------------------------------------
    directness: Literal[
        "DIRECT_DISPOSITIVE", "DIRECT_REPORTED", "INDIRECT_CIRCUMSTANTIAL", "HEARSAY_UNSUPPORTED"
    ] = "INDIRECT_CIRCUMSTANTIAL"

    # 계약서, 등기부 등 처분문서가 핵심 법률행위(계약 당사자, 보증금, 차임, 기간)를 증명하는 경우
    is_dispositive_doc = authenticity in ("BILATERAL_SIGNED", "OFFICIAL_PUBLIC")
    is_dispositive_prop = proposition.event_type in (
        "PAYMENT", "CONTRACT_PERIOD", "CONTRACT_EXECUTION", "ENCUMBRANCE"
    ) or proposition.semantic_category in ("OBLIGATION", "STATE")

    if is_dispositive_doc and is_dispositive_prop and proposition.epistemic_status != "NOT_VERIFIED":
        directness = "DIRECT_DISPOSITIVE"
    elif authenticity in ("INFORMAL_COMMUNICATION", "PRIVATE_UNILATERAL"):
        if proposition.event_type == "COMMUNICATION" or proposition.speech_act in ("NOTICE", "REQUEST", "PROPOSAL", "REJECTION"):
            # 문자메시지 자체가 의사표시의 발송/도달을 직접 증명하는 경우
            directness = "DIRECT_REPORTED"
        elif proposition.epistemic_status == "REPORTED":
            directness = "HEARSAY_UNSUPPORTED"
        else:
            directness = "INDIRECT_CIRCUMSTANTIAL"
    elif proposition.epistemic_status == "NOT_VERIFIED":
        directness = "INDIRECT_CIRCUMSTANTIAL"
    else:
        directness = "DIRECT_DISPOSITIVE" if authenticity == "OFFICIAL_PUBLIC" else "INDIRECT_CIRCUMSTANTIAL"

    # --------------------------------------------------------------------------
    # 3. 실체적 관련성 (Relevance) 판별
    # --------------------------------------------------------------------------
    relevance: Literal["DIRECTLY_RELEVANT", "BACKGROUND", "TANGENTIAL", "IRRELEVANT"] = "DIRECTLY_RELEVANT"
    if proposition.semantic_category in ("DOCUMENT_METADATA", "SOURCE_AVAILABILITY"):
        relevance = "BACKGROUND"
    elif proposition.event_type in ("PAYMENT", "RESIDENCE_REGISTRATION", "CONTRACT_PERIOD", "DELIVERY", "ENCUMBRANCE"):
        relevance = "DIRECTLY_RELEVANT"
    else:
        relevance = "DIRECTLY_RELEVANT"

    # --------------------------------------------------------------------------
    # 4. 정보 완전성 (Completeness)
    # --------------------------------------------------------------------------
    completeness: Literal["COMPLETE", "PARTIAL_DEFICIENT", "SUMMARY_ONLY"] = "COMPLETE"
    if doc_meta.get("is_summary"):
        completeness = "SUMMARY_ONLY"
    elif doc_meta.get("has_missing_pages"):
        completeness = "PARTIAL_DEFICIENT"

    # --------------------------------------------------------------------------
    # 5. 시간적 적합성 (Temporal Applicability)
    # --------------------------------------------------------------------------
    temporal_applicability: Literal[
        "CONTEMPORANEOUS", "SUBSEQUENT_RECORD", "RETROSPECTIVE_CLAIM", "EXPIRED_OBSOLETE"
    ] = "CONTEMPORANEOUS"
    if authenticity == "BILATERAL_SIGNED":
        temporal_applicability = "CONTEMPORANEOUS"
    elif authenticity == "OFFICIAL_PUBLIC":
        temporal_applicability = "CONTEMPORANEOUS"
    elif authenticity in ("PRIVATE_UNILATERAL", "INFORMAL_COMMUNICATION"):
        if "기준" in proposition.statement or proposition.epistemic_status == "REPORTED":
            temporal_applicability = "SUBSEQUENT_RECORD"
        else:
            temporal_applicability = "CONTEMPORANEOUS"

    # --------------------------------------------------------------------------
    # 6. 상호 보강성 (Corroboration) 판별
    # --------------------------------------------------------------------------
    corroboration: Literal[
        "FULLY_CORROBORATED", "PARTIALLY_CORROBORATED", "UNCORROBORATED", "DIRECTLY_CONTRADICTED"
    ] = "UNCORROBORATED"

    corroborating_count = 0
    contradicting_count = 0

    from ai_legal_helper.case_intelligence.fact_semantics import check_proposition_comparability

    for op in other_props:
        comp = check_proposition_comparability(proposition, op)
        val_a = (proposition.value or {}).get("amount") if isinstance(proposition.value, dict) else proposition.value
        val_b = (op.value or {}).get("amount") if isinstance(op.value, dict) else op.value

        # (1) 내용 일치 또는 상호 지지 (Corroborating)
        if comp.status == "CONSISTENT" or comp.reason_code in ("PAYMENT_AMOUNT_MATCH", "TEMPORALLY_COMPATIBLE"):
            corroborating_count += 1
        elif (
            op.event_type == proposition.event_type
            and val_a is not None
            and val_b is not None
            and val_a == val_b
        ):
            corroborating_count += 1
        # (2) 직접적 대립/모순 (Contradicting)
        elif comp.is_comparable:
            if {proposition.polarity, op.polarity} == {"AFFIRMATIVE", "NEGATIVE"}:
                contradicting_count += 1
            elif val_a is not None and val_b is not None and val_a != val_b:
                contradicting_count += 1
            elif (
                proposition.temporal_value
                and op.temporal_value
                and proposition.temporal_value != op.temporal_value
            ):
                contradicting_count += 1

    if contradicting_count > 0:
        corroboration = "DIRECTLY_CONTRADICTED"
    elif corroborating_count >= 2:
        corroboration = "FULLY_CORROBORATED"
    elif corroborating_count == 1:
        corroboration = "PARTIALLY_CORROBORATED"
    else:
        corroboration = "UNCORROBORATED"

    # --------------------------------------------------------------------------
    # 7. 데이터 원본성 품질 (Provenance Quality)
    # --------------------------------------------------------------------------
    provenance_quality: Literal["HIGH", "MEDIUM", "LOW"] = "HIGH" if proposition.source_span_ids else "MEDIUM"

    # --------------------------------------------------------------------------
    # 8. 종합 점수 및 상태 산출
    # --------------------------------------------------------------------------
    w_auth = 0.30
    w_dir = 0.25
    w_rel = 0.15
    w_comp = 0.10
    w_temp = 0.10
    w_cor = 0.10

    score = (
        w_auth * _AUTHENTICITY_SCORES[authenticity]
        + w_dir * _DIRECTNESS_SCORES[directness]
        + w_rel * _RELEVANCE_SCORES[relevance]
        + w_comp * _COMPLETENESS_SCORES[completeness]
        + w_temp * _TEMPORAL_SCORES[temporal_applicability]
        + w_cor * _CORROBORATION_SCORES[corroboration]
    )
    score = round(max(0.0, min(1.0, score)), 4)

    # 종합 상태 결정
    assessment_status: Literal["CONCLUSIVE", "RELIABLE", "PROVISIONAL", "DEFICIENT", "REJECTED"] = "PROVISIONAL"
    if corroboration == "DIRECTLY_CONTRADICTED" and authenticity in ("PRIVATE_UNILATERAL", "INFORMAL_COMMUNICATION"):
        assessment_status = "DEFICIENT"
    elif directness == "DIRECT_DISPOSITIVE" and authenticity in ("OFFICIAL_PUBLIC", "BILATERAL_SIGNED") and score >= 0.85:
        assessment_status = "CONCLUSIVE"
    elif score >= 0.70:
        assessment_status = "RELIABLE"
    elif score >= 0.50:
        assessment_status = "PROVISIONAL"
    else:
        assessment_status = "DEFICIENT"

    # --------------------------------------------------------------------------
    # 9. 입증 범위(Proof Scope) 및 한계 명시
    # --------------------------------------------------------------------------
    proven_list: List[str] = []
    unproven_list: List[str] = []
    limits: List[str] = []

    if authenticity == "BILATERAL_SIGNED":
        proven_list.extend(["계약 당사자 신원", "약정 보증금 및 차임", "약정 임대차 기간", "약정 지급기일"])
        unproven_list.extend(["실제 인도/입주 여부", "주민등록 전입신고 일자", "확정일자 부여 여부", "보증보험 가입 여부"])
        limits.append("처분문서로서 계약 체결 및 약정 사실을 완전하게 입증하나, 사후적인 실제 이행·전입·공시 사실은 별도 증빙이 필요합니다.")
    elif authenticity == "OFFICIAL_PUBLIC":
        if "등기" in doc_name_lower:
            proven_list.extend(["부동산 소유자 신원", "선순위 제한물권(근저당·가압류) 내역", "등기 접수일자"])
            unproven_list.extend(["실제 채무 잔액 변제 여부", "임차인 대항력 취득 여부"])
            limits.append("등기부 기재 사실에 대한 공적 증명력을 가지나, 등기 외 채권관계나 실제 변제 여부는 입증하지 않습니다.")
        elif "전입" in doc_name_lower or "주민" in doc_name_lower:
            proven_list.extend(["전입신고 일자", "세대주 및 세대원 거주 신고 내역"])
            unproven_list.extend(["임대차계약의 유효성", "보증금 지급 사실"])
            limits.append("공적 전입신고 사실을 입증하나, 실제 점유 계속성 및 임대차 관계 자체를 입증하지는 않습니다.")
    elif authenticity == "INFORMAL_COMMUNICATION":
        proven_list.append("해당 일시에 당사자 간 대화·의사표시가 전달된 정황")
        unproven_list.extend(["법률상 처분문서의 직접 효력", "상대방의 명시적 동의 여부(묵비 시)"])
        limits.append("발신 및 수신 사실의 정황을 입증할 수 있으나, 단독으로 법률적 권리관계를 확정하기는 부족합니다.")

    proof_scope = {
        "proven_propositions": proven_list,
        "unproven_propositions": unproven_list,
        "limits": limits,
    }

    summary = (
        f"[{assessment_status}] {document_name}은(는) {authenticity} 등급의 증거로서 "
        f"해당 명제에 대해 {directness}의 직접성을 가지며 종합 신뢰도 {score:.2f}로 평가되었습니다."
    )

    return EvidenceAssessmentResult(
        source_authenticity=authenticity,
        directness=directness,
        relevance=relevance,
        completeness=completeness,
        temporal_applicability=temporal_applicability,
        corroboration=corroboration,
        provenance_quality=provenance_quality,
        reliability_score=score,
        assessment_status=assessment_status,
        proof_scope=proof_scope,
        summary=summary,
    )
