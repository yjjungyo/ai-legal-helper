# -*- coding: utf-8 -*-
"""
증거 보완 추천 및 공백 탐지 모듈 (Evidence Gap & Recommendation Engine)

이 모듈은 AI Legal Helper의 사실관계 분석 중 발견되는 증거 공백(Evidence Gap)을 정밀 탐지하고,
소송 및 법률 분쟁에서 필수적인 요건사실 입증을 완성하기 위해 사용자에게 필요한
구체적인 보완 문서 유형과 권장 조치(Actionable Recommendation)를 제시한다.

[설계 원칙]
1. 증거 부족(미확인, 자료 미제출)은 모순(CONTRADICTION)이 아니라 증거 공백(EVIDENCE_GAP)으로 관리한다.
2. 각 결함 유형별로 실무상 소송/상담에 필요한 표준 증빙 서류 목록을 구체적으로 매핑한다.
3. 한국어 코딩 주석 표준(CODING_COMMENT_STANDARD.md)을 엄격히 준수한다.
"""

import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.fact_semantics import SemanticProposition


# ==============================================================================
# 1. 증거 공백 Pydantic 모델
# ==============================================================================

class EvidenceGapItem(BaseModel):
    """
    단일 사실 또는 쟁점에 대한 증거 공백 및 보완 추천 모델.
    """

    gap_type: Literal[
        "HUG_INSURANCE_CONFIRMATION_GAP",   # 보증보험 가입 여부 및 보증 범위 미확인
        "REGISTRY_CONFIRMATION_GAP",       # 최신 등기사항전부증명서 미제출/미확인
        "PAYMENT_RECEIPT_GAP",             # 실제 대금 지급(계좌이체증/영수증) 미증명
        "NOTICE_DELIVERY_GAP",             # 통지 의사표시의 상대방 수령/도달 미확인
        "RESIDENCE_CONFIRMATION_GAP",      # 전입세대확인서/확정일자부 미확인
        "LOAN_BALANCE_GAP",                # 대출 잔액 및 상환 내역 미확인
        "GENERAL_EVIDENCE_GAP",            # 기타 사실관계 증빙 부족
    ] = Field(..., description="증거 공백 유형 코드")

    target_proposition: str = Field(..., description="보완 대상 사실 명제 또는 진술문")
    description: str = Field(..., description="증거 공백에 대한 상세 법률적 설명")
    recommended_document_types: List[str] = Field(
        default_factory=list,
        description="추천 보완 문서 명칭 목록",
    )
    recommended_action: str = Field(..., description="사용자 권장 조치 가이드")
    priority: Literal["HIGH", "MEDIUM", "LOW"] = Field("MEDIUM", description="보완 우선순위")
    source_claim_id: Optional[str] = Field(None, description="연계된 EvidenceClaim ID")
    source_fact_id: Optional[str] = Field(None, description="연계된 Fact ID")
    is_resolved: bool = Field(False, description="보완 완료 여부")


# ==============================================================================
# 2. 증거 공백 탐지 및 추천 생성 함수
# ==============================================================================

def detect_evidence_gap(
    proposition: SemanticProposition,
    claim_id: Optional[str] = None,
    fact_id: Optional[str] = None,
) -> Optional[EvidenceGapItem]:
    """단일 사실 명제(SemanticProposition)를 분석하여 증거 공백을 탐지하고 보완 추천을 생성한다.

    Args:
        proposition: 분석 대상 사실 명제.
        claim_id: 선택적 출처 Claim ID.
        fact_id: 선택적 연관 Fact ID.

    Returns:
        Optional[EvidenceGapItem]: 증거 공백이 발견되면 Gap 객체, 없으면 None.
    """
    stmt = (proposition.statement or "").strip()
    compact = re.sub(r"\s+", "", stmt)

    # 1. HUG 전세보증금 반환보증보험 가입 여부 미확인 공백 (CASE-01, CASE-06)
    if any(kw in compact for kw in ("보증보험", "반환보증", "HUG", "전세보증", "주택도시보증공사")):
        if proposition.epistemic_status == "NOT_VERIFIED" or any(kw in compact for kw in (
            "확인되지않았", "미확인", "알수없", "확인할수없", "자료가없"
        )):
            return EvidenceGapItem(
                gap_type="HUG_INSURANCE_CONFIRMATION_GAP",
                target_proposition=stmt,
                description="전세보증금 반환보증보험의 가입 여부 및 보증 한도가 객관적 서류로 확인되지 않았습니다.",
                recommended_document_types=[
                    "HUG 전세보증금 반환보증 증권",
                    "보증보험 가입증명서",
                    "주택도시보증공사 보증확인원",
                    "SGI서울보증 전세보증보험 가입증명서",
                ],
                recommended_action="HUG(주택도시보증공사) 또는 SGI서울보증에서 발급받은 보증증권 또는 가입확인서를 추가 등록하여 보증 대상 및 금액을 확정하세요.",
                priority="HIGH",
                source_claim_id=claim_id,
                source_fact_id=fact_id,
                is_resolved=False,
            )

    # 2. 등기부등본(등기사항전부증명서) 미제출 공백 (CASE-05)
    if any(kw in compact for kw in ("등기사항", "등기부", "등기부등본")):
        if (
            proposition.semantic_category == "SOURCE_AVAILABILITY"
            or proposition.epistemic_status == "NOT_VERIFIED"
            or any(kw in compact for kw in ("미제출", "제출되지않았", "자료가없", "확인되지않았"))
        ):
            return EvidenceGapItem(
                gap_type="REGISTRY_CONFIRMATION_GAP",
                target_proposition=stmt,
                description="목적물 부동산의 소유권 변동, 선순위 근저당, 가압류 등의 권리관계를 확인할 수 있는 최신 등기부가 미제출되었습니다.",
                recommended_document_types=[
                    "부동산 등기사항전부증명서 (말소사항 포함)",
                    "집합건물 등기사항전부증명서 (토지·건물 일체)",
                ],
                recommended_action="대법원 인터넷등기소에서 발급한 최신 '부동산 등기사항전부증명서(말소사항 포함)'를 제출하여 제한물권 설정을 확인하세요.",
                priority="HIGH",
                source_claim_id=claim_id,
                source_fact_id=fact_id,
                is_resolved=False,
            )

    # 3. 계약해지 통지서 등 의사표시 도달(수령) 미확인 공백
    if proposition.event_type == "COMMUNICATION" or any(kw in compact for kw in ("해지통지", "내용증명", "계약해지")):
        if proposition.event_subtype == "NOTICE_SENT" and proposition.epistemic_status != "DOCUMENT_STATES":
            return EvidenceGapItem(
                gap_type="NOTICE_DELIVERY_GAP",
                target_proposition=stmt,
                description="계약 해지 또는 이행 최고 통지서를 발송하였으나, 상대방에게 적법하게 도달·수령되었는지 여부가 확인되지 않았습니다.",
                recommended_document_types=[
                    "우체국 배달증명서",
                    "내용증명 배달결과 조회서",
                    "문자/메시지 수신 확인 및 상대방 답변 캡처",
                ],
                recommended_action="인터넷우체국 배달증명서 또는 상대방이 통지를 확인한 답변 메시지를 등록하여 도달 일자를 확정하세요.",
                priority="HIGH",
                source_claim_id=claim_id,
                source_fact_id=fact_id,
                is_resolved=False,
            )

    # 4. 전입신고 및 대항력/확정일자 공백
    if any(kw in compact for kw in ("전입신고", "확정일자", "대항력", "주민등록")):
        if proposition.epistemic_status == "NOT_VERIFIED" or any(kw in compact for kw in ("확인되지않았", "미확인")):
            return EvidenceGapItem(
                gap_type="RESIDENCE_CONFIRMATION_GAP",
                target_proposition=stmt,
                description="주택임대차보호법상 대항력 및 우선변제권 취득을 증명하는 전입일자 및 확정일자 부여 사실이 확인되지 않았습니다.",
                recommended_document_types=[
                    "주민등록표 등본/초본 (전입일자 포함)",
                    "전입세대확인서",
                    "임대차계약서 확정일자 날인본",
                ],
                recommended_action="주민센터 또는 정부24에서 발급받은 '전입세대확인서'와 확정일자가 날인된 계약서를 등록하세요.",
                priority="HIGH",
                source_claim_id=claim_id,
                source_fact_id=fact_id,
                is_resolved=False,
            )

    # 5. 기타 명시적 미확인 상태(EPISTEMIC_STATUS / SOURCE_AVAILABILITY)
    if proposition.epistemic_status == "NOT_VERIFIED" or proposition.semantic_category in ("EPISTEMIC_STATUS", "SOURCE_AVAILABILITY"):
        return EvidenceGapItem(
            gap_type="GENERAL_EVIDENCE_GAP",
            target_proposition=stmt,
            description="해당 사실에 대한 직접적인 객관적 증빙 자료가 아직 제출되지 않아 사실 확정을 위해 추가 확인이 필요합니다.",
            recommended_document_types=["관련 사실을 입증하는 객관적 공문서, 계약서, 이체증"],
            recommended_action="주장 내용을 뒷받침할 수 있는 직접 증거 문서를 보완해 주시기 바랍니다.",
            priority="MEDIUM",
            source_claim_id=claim_id,
            source_fact_id=fact_id,
            is_resolved=False,
        )

    return None
