# -*- coding: utf-8 -*-
"""
사실 확정 및 상충 판정 모듈 (Fact Adjudication & Semantic Integration Engine)

이 모듈은 AI Legal Helper의 정규화된 사실 명제(SemanticProposition), 증거 신뢰성 평가 결과(EvidenceAssessmentResult),
기존 확정 사실(Fact) 목록을 종합 심리하여 개별 명제의 최종 법적 확정 상태(Adjudication Status)와
의미적 관계(Primary Relation)를 결정한다.

[핵심 판정 원칙]
1. 증거 부족(미확인, 자료 미제출)은 모순이 아니며 EVIDENCE_INCOMPLETE 및 EVIDENCE_GAP으로 분류한다.
2. 처분문서(임대차계약서, 등기사항증명서)로 입증된 사실은 무관한 보증보험 메모 미확인 등으로 격하되지 않고
   EVIDENCE_SUPPORTED 또는 CORROBORATED 상태를 확고히 유지한다.
3. 동일 대상·동일 시점의 실질적 양립 불가능성(진짜 모순)이 확인된 경우에만 CONTRADICTS 및 GENUINELY_DISPUTED를 부여한다.
4. 구성항목(PART_OF), 의사표시 대응(RESPONDS_TO), 상태 지속(CONTINUES), 시계열 선후(BEFORE/AFTER) 등
   다차원 의미 관계를 정확히 부여하여 오탐을 원천 방지한다.
5. 한국어 코딩 주석 표준(CODING_COMMENT_STANDARD.md)을 준수한다.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.fact_semantics import (
    SemanticProposition,
    check_proposition_comparability,
)
from ai_legal_helper.case_intelligence.evidence_reliability import EvidenceAssessmentResult
from ai_legal_helper.case_intelligence.evidence_gap import EvidenceGapItem, detect_evidence_gap


# ==============================================================================
# 1. 사실 확정 결과 Pydantic 모델
# ==============================================================================

class FactAdjudicationResult(BaseModel):
    """
    단일 명제에 대한 최종 법적 심리 및 사실 확정 결과 모델.
    """

    # 사실 확정 상태
    adjudication_status: Literal[
        "EVIDENCE_SUPPORTED",          # 직접 처분문서 또는 공문서에 의해 확실히 입증됨
        "CORROBORATED",                # 복수의 독립적 증거에 의해 상호 뒷받침됨
        "PARTY_ALLEGED",               # 일방 당사자의 일방적 주장 (객관적 증빙 부족)
        "EVIDENCE_INCOMPLETE",         # 증거 불충분 / 추가 확인 및 보완 필요
        "GENUINELY_DISPUTED",          # 직접 증거 간 실질적 대립 및 양립 불가능한 모순
    ] = Field(..., description="사실 확정 및 신뢰 수준")

    # 의미적 관계 유형
    primary_relation: Literal[
        "SUPPORTS",                    # 증거와 기존 사실이 일치·뒷받침함
        "CONTRADICTS",                 # 동일 대상·시점 양립 불가능한 실질적 모순
        "PART_OF",                     # 구성 항목 관계 (예: 계약금은 보증금의 일부)
        "RESPONDS_TO",                 # 의사표시 대응 (예: 제안에 대한 거절)
        "BEFORE",                      # 시계열적 선행 사건
        "AFTER",                       # 시계열적 후행 사건
        "CONTINUES",                   # 과거 행위 이후 상태 지속
        "DIFFERENT_CONTEXT",           # 별개 맥락 (채권자 다름, 절차 단계 다름 등)
        "EVIDENCE_GAP",                # 증거 공백 (미확인 정보)
    ] = Field(..., description="기존 사건 데이터와의 핵심 법적 의미 관계")

    confidence: float = Field(1.0, description="판정 신뢰도 (0.0 ~ 1.0)")
    adjudication_basis: str = Field(..., description="한국어 법적 판정 이유")
    supporting_evidence_ids: List[str] = Field(
        default_factory=list,
        description="이 사실을 지지하는 증거 문서 ID 목록",
    )
    contradicting_evidence_ids: List[str] = Field(
        default_factory=list,
        description="이 사실과 대립하는 증거 문서 ID 목록",
    )
    gap_item: Optional[EvidenceGapItem] = Field(
        None,
        description="증거 공백이 탐지된 경우의 보완 권장 정보",
    )


# ==============================================================================
# 2. 사실 심리 및 판정 함수 (adjudicate_fact)
# ==============================================================================

def adjudicate_fact(
    proposition: SemanticProposition,
    candidate_facts: Optional[List[Any]] = None,
    assessment: Optional[EvidenceAssessmentResult] = None,
    claim_id: Optional[str] = None,
    fact_id: Optional[str] = None,
    fact_doc_names: Optional[Dict[str, str]] = None,
) -> FactAdjudicationResult:
    """단일 사실 명제와 사건의 기존 사실군, 증거 신뢰성 평가를 종합하여 FactAdjudicationResult를 도출한다.

    Args:
        proposition: 심리 대상 사실 명제.
        candidate_facts: 비교 대상 기존 Fact ORM 객체 또는 SemanticProposition 목록.
        assessment: 해당 증거 문서에 대한 7대 차원 신뢰성 평가 결과.
        claim_id: 출처 EvidenceClaim ID.
        fact_id: 연관 Fact ID.

    Returns:
        FactAdjudicationResult: 사실 확정 상태 및 의미 관계가 명시된 결과 객체.
    """
    c_facts = candidate_facts or []
    stmt = (proposition.statement or "").strip()

    # --------------------------------------------------------------------------
    # 1. 증거 부족 및 인식 상태(Epistemic Gap) 우선 분기 (원칙 2.1, CASE-01, CASE-05, CASE-06)
    # --------------------------------------------------------------------------
    if (
        proposition.epistemic_status == "NOT_VERIFIED"
        or proposition.semantic_category in ("EPISTEMIC_STATUS", "SOURCE_AVAILABILITY")
    ):
        gap = detect_evidence_gap(proposition, claim_id=claim_id, fact_id=fact_id)
        return FactAdjudicationResult(
            adjudication_status="EVIDENCE_INCOMPLETE",
            primary_relation="EVIDENCE_GAP",
            confidence=0.9,
            adjudication_basis="진술이 실체적 사실의 부정이 아니라 증거 미제출 또는 미확인 상태를 나타내므로 증거 보완이 필요한 공백으로 판정합니다.",
            supporting_evidence_ids=[proposition.source_evidence_id] if proposition.source_evidence_id else [],
            contradicting_evidence_ids=[],
            gap_item=gap,
        )

    # --------------------------------------------------------------------------
    # 2. 기존 확정 사실군과의 의미적 비교 및 상충 검증
    # --------------------------------------------------------------------------
    found_contradiction = False
    contradicting_doc_ids: List[str] = []
    found_relation: Literal[
        "SUPPORTS", "CONTRADICTS", "PART_OF", "RESPONDS_TO", "BEFORE", "AFTER", "CONTINUES", "DIFFERENT_CONTEXT", "EVIDENCE_GAP"
    ] = "SUPPORTS"
    relation_basis = ""

    for target in c_facts:
        target_stmt = target.statement if hasattr(target, "statement") else str(target)
        target_doc = None
        if hasattr(target, "id") and fact_doc_names:
            target_doc = fact_doc_names.get(target.id)
        target_evidence_id = getattr(target, "source_ref", None)

        from ai_legal_helper.case_intelligence.fact_semantics import extract_semantic_proposition
        target_prop = extract_semantic_proposition(
            target_stmt,
            context={"evidence_id": target_evidence_id, "document_name": target_doc},
        )

        comp_res = check_proposition_comparability(proposition, target_prop)

        # (A) 비교 가능 대상(동일 명제 후보)으로 진입한 경우 실질적 상충 여부 검사
        if comp_res.is_comparable:
            # 1) 서술 극성 대립 (긍정 vs 부정)
            # 동일한 구체적 사건 및 행위/서술어를 대상으로 직접 대립하는 경우에만 실질적 모순으로 판정
            if {proposition.polarity, target_prop.polarity} == {"AFFIRMATIVE", "NEGATIVE"}:
                same_action = (
                    proposition.event_type == target_prop.event_type
                    and proposition.event_subtype == target_prop.event_subtype
                    and proposition.speech_act == target_prop.speech_act
                )
                if same_action and (
                    proposition.event_type != "GENERAL_FACT"
                    or (proposition.predicate_key and target_prop.predicate_key and proposition.predicate_key == target_prop.predicate_key)
                    or any(act in stmt and act in target_stmt for act in ("반환", "지급", "가입", "인도", "명도", "퇴거", "해지", "동의", "체결"))
                ):
                    found_contradiction = True
                    found_relation = "CONTRADICTS"
                    relation_basis = f"동일 사실에 대해 한쪽은 긍정하고 다른 쪽은 부정하여 실질적 모순입니다 ('{stmt}' vs '{target_stmt}')."
                    if hasattr(target, "source_ref") and target.source_ref:
                        contradicting_doc_ids.append(str(target.source_ref))
                    break

            # 2) 동일 단계 금액 직접 불일치
            val_a = (proposition.value or {}).get("amount") if isinstance(proposition.value, dict) else proposition.value
            val_b = (target_prop.value or {}).get("amount") if isinstance(target_prop.value, dict) else target_prop.value
            if val_a is not None and val_b is not None and val_a != val_b:
                found_contradiction = True
                found_relation = "CONTRADICTS"
                relation_basis = f"동일 지급 단계에서 서로 다른 금액이 기재되어 직접적 수치 모순입니다 ({val_a:,}원 vs {val_b:,}원)."
                if hasattr(target, "source_ref") and target.source_ref:
                    contradicting_doc_ids.append(str(target.source_ref))
                break

            # 3) 동일 사건 일자 직접 불일치
            if (
                proposition.temporal_value
                and target_prop.temporal_value
                and proposition.temporal_value != target_prop.temporal_value
            ):
                found_contradiction = True
                found_relation = "CONTRADICTS"
                relation_basis = f"동일 사건에 대해 서로 다른 일자가 기재되어 시점 모순입니다 ({proposition.temporal_value} vs {target_prop.temporal_value})."
                if hasattr(target, "source_ref") and target.source_ref:
                    contradicting_doc_ids.append(str(target.source_ref))
                break

        # (B) 비교 불가(비상충) 판정인 경우 구체적 의미 관계 매핑
        else:
            if comp_res.reason_code == "COMPONENT_OF_SUM":
                found_relation = "PART_OF"
                relation_basis = "보증금 총액과 그 구성 항목(계약금/잔금) 간의 양립 가능한 부분-전체(PART_OF) 관계입니다."
            elif comp_res.reason_code == "DIFFERENT_PAYMENT_COMPONENT":
                found_relation = "PART_OF"
                relation_basis = "서로 다른 지급 단계(계약금 vs 잔금 vs 보증금원금)의 개별 지급 구성항목입니다."
            elif comp_res.reason_code == "PROPOSAL_VS_REJECTION":
                found_relation = "RESPONDS_TO"
                relation_basis = "임대인의 분할 상환 제안에 대해 임차인이 거절 의사를 표시한 대응(RESPONDS_TO) 관계입니다."
            elif comp_res.reason_code in ("INITIAL_EVENT_VS_MAINTAINED_STATUS", "EVENT_VS_STATE"):
                found_relation = "CONTINUES"
                relation_basis = "최초 행위 발생 이후 현재 시점까지 상태가 계속 유지되는 지속(CONTINUES) 관계입니다."
            elif comp_res.reason_code in ("TEMPORALLY_COMPATIBLE", "PAYMENT_AMOUNT_MATCH", "NOTICE_DATE_VS_TARGET_DATE"):
                found_relation = "SUPPORTS"
                relation_basis = comp_res.explanation or "서로 다른 진술이 동일한 사실 또는 정상 이행을 상호 입증·지지하는 관계입니다."
            elif comp_res.status == "DIFFERENT_CONTEXT":
                found_relation = "DIFFERENT_CONTEXT"
                relation_basis = f"비교 차원이 다른 별개 맥락입니다 ({comp_res.reason_code})."

    # --------------------------------------------------------------------------
    # 3. 최종 사실 확정 상태(Adjudication Status) 결정
    # --------------------------------------------------------------------------
    sup_ids = [proposition.source_evidence_id] if proposition.source_evidence_id else []

    if found_contradiction:
        return FactAdjudicationResult(
            adjudication_status="GENUINELY_DISPUTED",
            primary_relation="CONTRADICTS",
            confidence=0.95,
            adjudication_basis=relation_basis,
            supporting_evidence_ids=sup_ids,
            contradicting_evidence_ids=contradicting_doc_ids,
            gap_item=None,
        )

    # 증거 신뢰성 평가에 따른 상태 확정
    auth = assessment.source_authenticity if assessment else "BILATERAL_SIGNED"
    direct = assessment.directness if assessment else "DIRECT_DISPOSITIVE"
    corrob = assessment.corroboration if assessment else "UNCORROBORATED"

    if corrob in ("FULLY_CORROBORATED", "PARTIALLY_CORROBORATED"):
        status: Literal["EVIDENCE_SUPPORTED", "CORROBORATED", "PARTY_ALLEGED", "EVIDENCE_INCOMPLETE", "GENUINELY_DISPUTED"] = "CORROBORATED"
        basis = relation_basis or "복수의 독립된 증거에 의해 사실관계가 상호 보강·입증되었습니다."
    elif direct == "DIRECT_DISPOSITIVE" or auth in ("OFFICIAL_PUBLIC", "BILATERAL_SIGNED"):
        status = "EVIDENCE_SUPPORTED"
        basis = relation_basis or "직접적인 처분문서 또는 공적 기록에 의해 사실관계가 명백히 뒷받침됩니다."
    elif auth in ("INFORMAL_COMMUNICATION", "PRIVATE_UNILATERAL"):
        status = "PARTY_ALLEGED"
        basis = relation_basis or "일방 당사자의 진술 또는 비공식 대화에 기반한 사실로서 추가 공적 증빙이 필요합니다."
    else:
        status = "EVIDENCE_SUPPORTED"
        basis = relation_basis or "제출된 증거에 의해 뒷받침되는 사실입니다."

    return FactAdjudicationResult(
        adjudication_status=status,
        primary_relation=found_relation,
        confidence=assessment.reliability_score if assessment else 0.95,
        adjudication_basis=basis,
        supporting_evidence_ids=sup_ids,
        contradicting_evidence_ids=[],
        gap_item=None,
    )
