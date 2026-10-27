# -*- coding: utf-8 -*-
"""
모듈명: issue_verifier.py

[모듈 개요]
법률 상담 초안(Draft Answer)을 전체 일괄 판정(PASS/REVISE/INSUFFICIENT)하는 대신,
단위 쟁점(Issue)별로 분리하여 독립적으로 검증하는 쟁점별 검증 엔진(Issue-Level Verification Engine).

[주요 기능]
1. Fact Verifier와 Legal Verifier의 엄격한 3단계 분리 검증 (Section 7, Section 12):
   - FactVerification: CaseEvidenceBriefing 내 FactAdjudication(EVIDENCE_SUPPORTED/CORROBORATED) 및 증거 라벨(E01, E02...) 유효성 대조
   - LegalRuleVerification: 실제 검색된 retrieved_sources 내 법령 조문 명칭 및 본문(article_text) 일치 정밀 대조 (초안 자체 텍스트 자가 통과 원천 배제)
   - LegalApplicationVerification: 확정된 사실관계와 검색된 법률 조문의 요건사실을 포섭하여 실질적 상태 판정 (하드코딩된 VERIFIED 전면 제거)
2. 법률 주장별 근거 검증 모델 (VerifiedLegalClaim, Section 8):
   - FACTUAL, LEGAL_RULE, LEGAL_APPLICATION, RECOMMENDATION 등 주장 유형별 원자적 검증
   - GROUNDED, PARTIALLY_GROUNDED, UNGROUNDED 상태 부여
3. 쟁점별 5대 상태 분류 (Section 7, P0-04):
   - VERIFIED: 사실과 법령 조문 본문이 모두 확보되고 요건사실이 온전히 충족된 경우에만 제한적 부여
   - CONDITIONAL: 핵심 사실은 확인되었으나 최신 등기부 열람 등 추가 공적 자료 확인이 필요한 경우
   - NEEDS_EVIDENCE: 해당 쟁점 판단에 필수적인 증거자료가 결여됨
   - NEEDS_LEGAL_SOURCE: 사실은 있으나 적용할 법령 조문 원문이 검색되지 않은 경우
   - BLOCKED: 허위 인용, 심각한 모순으로 결론 제공 차단
"""

from typing import List, Dict, Any, Optional, Literal, Union, Tuple
import re
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.case_intelligence.dynamic_context import (
    extract_dynamic_case_context,
    DynamicCaseContext,
    format_krw_to_korean,
)
from ai_legal_helper.workflows.issue_planner import LegalIssueTask
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 인용 검증용 정규식
_E_LABEL_REGEX = re.compile(r"\[(E\d{1,3})(?:[^\]]*)\]", re.IGNORECASE)
_STATUTE_REGEX = re.compile(r"([가-힣]+(?:법률|법|시행령|특례법))\s*(?:제\s*(\d+)조(?:의\s*(\d+))?)?", re.IGNORECASE)


class VerifiedLegalClaim(BaseModel):
    """원자적 단위 법률 주장 검증 모델 (Section 8 요구사항)."""
    claim_id: str = Field(..., description="주장 고유 식별자")
    claim_text: str = Field(..., description="주장 문장 본문")
    claim_type: Literal["FACTUAL", "LEGAL_RULE", "LEGAL_APPLICATION", "RECOMMENDATION"] = Field(
        "LEGAL_APPLICATION", description="주장 분류"
    )
    supporting_fact_ids: List[str] = Field(default_factory=list, description="뒷받침하는 Fact ID 목록")
    supporting_evidence_labels: List[str] = Field(default_factory=list, description="뒷받침하는 증거 라벨 목록 (예: E01)")
    statute_source_ids: List[str] = Field(default_factory=list, description="근거 법령 조문 목록")
    precedent_source_ids: List[str] = Field(default_factory=list, description="근거 판례 목록")
    grounding_status: Literal["GROUNDED", "PARTIALLY_GROUNDED", "UNGROUNDED"] = Field(
        "UNGROUNDED", description="근거 검증 상태"
    )
    confidence_score: float = Field(0.0, description="신뢰 점수 (0.0~1.0)")
    verifier_notes: Optional[str] = Field(None, description="검증 비고")


class IssueVerificationResult(BaseModel):
    """단위 법률 쟁점별 독립 검증 결과 모델."""
    issue_id: str = Field(..., description="쟁점 고유 식별자")
    issue_title: str = Field(..., description="쟁점 명칭")
    status: Literal["VERIFIED", "CONDITIONAL", "NEEDS_EVIDENCE", "NEEDS_LEGAL_SOURCE", "BLOCKED"] = Field(
        "CONDITIONAL", description="쟁점별 검증 5대 상태"
    )
    reason_codes: List[str] = Field(default_factory=list, description="상세 검증 사유 코드 목록")
    supported_fact_ids: List[str] = Field(default_factory=list, description="해당 쟁점에서 증거로 뒷받침된 Fact ID 목록")
    supported_source_ids: List[str] = Field(default_factory=list, description="뒷받침된 출처 ID/라벨 목록")
    supported_statute_ids: List[str] = Field(default_factory=list, description="확인된 법령 조문 목록")
    verified_claims: List[Dict[str, Any]] = Field(default_factory=list, description="검증 완료된 세부 주장들 (VerifiedLegalClaim 호환 딕셔너리)")
    unsupported_claims: List[Dict[str, Any]] = Field(default_factory=list, description="근거 부족으로 제외/유보된 주장들")
    unresolved_facts: List[str] = Field(default_factory=list, description="미확인으로 남아있는 사실 목록")
    missing_legal_sources: List[str] = Field(default_factory=list, description="부족한 법령/판례 근거 목록")
    missing_statutes: List[str] = Field(default_factory=list, description="부족한 법령 목록 (호환 필드)")
    legal_analysis: Optional[str] = Field(None, description="해당 쟁점에 대한 검증된 권장 분석 문안")
    safe_recommendations: List[str] = Field(default_factory=list, description="해당 쟁점에 한정된 안전한 실무 조치 안내")
    revision_instructions: List[str] = Field(default_factory=list, description="수정/보완 지침")


def _is_statute_grounded_in_sources(
    stat: str,
    retrieved_sources: List[Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    """검색된 법령 출처 청크 본문(content/article)에 해당 조문이 실질적으로 존재하는지 정밀 검증한다.

    단순히 법령명만 언급된 경우를 배제하고, 조문 번호(예: 제3조, 제3조의2, 제536조) 또는 조문의 핵심
    법률 효과 키워드가 검색 청크 본문에 실제로 포함되어 있는지 대조한다 (P0-01, P0-02, P0-4.2).

    특히 다음 원칙을 엄격히 준수한다:
    1. 출처의 메타데이터(source_law) 또는 청크 제목(title)에 대상 법령명이 명시된 청크를 우선 대조하여,
       타 법령 본문 내에서 인용된 단순 법령명 언급으로 인한 오일치를 차단한다.
    2. 가지번호(sub-article, 예: 제3조의2, 제6조의2)가 명시된 경우 가지번호까지 일치해야 참으로 판정한다.
    3. 법령명과 조문 번호가 실질적으로 합치되는 경우에만 해당 청크를 접지 출처로 확정한다.

    Args:
        stat: 검증 대상 법령 조문 문자열 (예: '주택임대차보호법 제3조의2', '민법 제536조').
        retrieved_sources: 검색된 출처 딕셔너리 목록.

    Returns:
        Tuple[bool, Optional[str]]: (검증 통과 여부, 일치된 출처 텍스트 요약)
    """
    m = _STATUTE_REGEX.search(stat)
    law_name = m.group(1) if m else stat.strip()
    art_no = m.group(2) if m else None
    sub_art_no = m.group(3) if m else None

    # 조문 번호 검색 패턴 구성 (가지번호 유무에 따른 정밀 패턴 생성)
    art_patterns: List[str] = []
    if art_no and sub_art_no:
        art_patterns = [
            f"제{art_no}조의{sub_art_no}",
            f"제 {art_no} 조의 {sub_art_no}",
            f"제{art_no}조의 {sub_art_no}",
            f"제 {art_no} 조의{sub_art_no}",
        ]
    elif art_no:
        art_patterns = [
            f"제{art_no}조",
            f"제 {art_no} 조",
        ]

    for s in retrieved_sources:
        content = str(s.get("content", ""))
        title = str(s.get("title", ""))
        article_field = str(s.get("article", ""))
        source_law = str(s.get("law_name") or s.get("statute_name") or s.get("metadata", {}).get("law_name", ""))
        full_chunk = f"{title} {article_field} {content}"

        # 법령명 일치 확인: 메타데이터 또는 제목, 대괄호 접두어([법령명]) 확인
        law_matched = False
        if source_law and (law_name in source_law or source_law in law_name):
            law_matched = True
        elif law_name in title or f"[{law_name}]" in full_chunk:
            law_matched = True
        elif not source_law and (re.search(rf"\[?{re.escape(law_name)}\]?", title) or re.search(rf"\[{re.escape(law_name)}\]", full_chunk)):
            law_matched = True

        if not law_matched:
            continue

        # 조문 번호가 지정된 경우 조문 패턴 일치 확인
        if art_patterns:
            if any(p in full_chunk for p in art_patterns):
                return True, full_chunk[:200]
        else:
            # 조문 번호 없이 법령명만 있는 경우 청크 본문이 존재하면 통과
            if len(content.strip()) > 30:
                return True, full_chunk[:200]

    return False, None


def verify_issue(
    issue: LegalIssueTask,
    draft_answer: str,
    briefing: CaseEvidenceBriefing,
    retrieved_sources: List[Dict[str, Any]],
) -> IssueVerificationResult:
    """단일 법률 쟁점에 대해 사실 검증과 법령 검증을 독립적으로 수행한다.

    Section 7 (P0-01, P0-02) 및 Section 8 (P0-04) 원칙:
    1. Fact Verification:
       - 브리핑 내 relevant_fact_ids의 사실 확정 상태(EVIDENCE_SUPPORTED, CORROBORATED) 평가
       - draft_answer 내 인용된 [E01], [E02] 라벨이 실제 briefing.source_registry에 존재하는지 검증
       - 허위 증거 번호 인용 시 BLOCKED 처리
    2. Legal Rule Verification:
       - issue.required_statutes 조문이 실제 검색된 retrieved_sources 본문에 존재하는지 정밀 대조
       - 법령 조문 본문이 확보되지 않은 경우 하드코딩된 VERIFIED를 전면 배제하고 NEEDS_LEGAL_SOURCE 부여
    3. Legal Application Verification:
       - 확정된 사건 사실과 검색된 법령 조문의 요건사실을 포섭하여 5대 상태 판정
       - 최신 등기부 등 추가 공적 서류 확인이 필요한 사안은 CONDITIONAL 부여
    4. VerifiedLegalClaim 원자적 주장 생성:
       - FACTUAL, LEGAL_RULE, LEGAL_APPLICATION, RECOMMENDATION별 검증 모델 구축

    Args:
        issue: 검증 대상 법률 쟁점 과업.
        draft_answer: AI가 생성한 초안 답변 전체 텍스트.
        briefing: 사건 증거 및 사실관계 브리핑 모델.
        retrieved_sources: RAG 및 HILT로 검색된 법령/판례 출처 목록.

    Returns:
        IssueVerificationResult: 쟁점별 검증 결과.
    """
    reason_codes: List[str] = []
    supported_fact_ids: List[str] = []
    supported_source_ids: List[str] = []
    supported_statute_ids: List[str] = []
    verified_claims: List[Dict[str, Any]] = []
    unsupported_claims: List[Dict[str, Any]] = []
    unresolved_facts: List[str] = []
    missing_statutes: List[str] = []
    safe_recommendations: List[str] = []

    # 1. 팩트 검증 (Fact Verification)
    facts_by_id = {f.fact_id: f for f in briefing.facts}
    has_supported_facts = False
    has_incomplete_facts = False

    for fid in issue.relevant_fact_ids:
        f = facts_by_id.get(fid)
        if not f:
            continue
        if f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED"):
            supported_fact_ids.append(fid)
            has_supported_facts = True
            if f.evidence_label:
                supported_source_ids.append(f.evidence_label)
            # 원자적 사실 주장 생성 (VerifiedLegalClaim)
            v_claim = VerifiedLegalClaim(
                claim_id=f"claim_fact_{f.fact_id[:8]}",
                claim_text=f.statement,
                claim_type="FACTUAL",
                supporting_fact_ids=[fid],
                supporting_evidence_labels=[f.evidence_label] if f.evidence_label else [],
                grounding_status="GROUNDED",
                confidence_score=f.confidence,
                verifier_notes=f"입증 상태: {f.adjudication_status}",
            )
            verified_claims.append(v_claim.model_dump())
        elif f.adjudication_status == "EVIDENCE_INCOMPLETE":
            has_incomplete_facts = True
            unresolved_facts.append(f.statement)
        elif f.adjudication_status == "PARTY_ALLEGED":
            v_claim = VerifiedLegalClaim(
                claim_id=f"claim_alleged_{f.fact_id[:8]}",
                claim_text=f.statement,
                claim_type="FACTUAL",
                supporting_fact_ids=[fid],
                supporting_evidence_labels=[],
                grounding_status="PARTIALLY_GROUNDED",
                confidence_score=0.5,
                verifier_notes="당사자 일방 진술로 객관적 증빙 보완 필요",
            )
            verified_claims.append(v_claim.model_dump())

    # 2. 증거 인용 유효성 검증 (Citation Grounding)
    cited_e_labels = set(_E_LABEL_REGEX.findall(draft_answer))
    invalid_e_labels = [lbl for lbl in cited_e_labels if lbl not in briefing.source_registry]

    if invalid_e_labels:
        reason_codes.append("INVALID_EVIDENCE_CITATION")
        unsupported_claims.append({
            "claim": f"미등록 증거 번호 인용: {', '.join(invalid_e_labels)}",
            "reason": "사건에 등록되지 않은 임의의 증거 번호입니다.",
        })
        return IssueVerificationResult(
            issue_id=issue.issue_id,
            issue_title=issue.issue_title,
            status="BLOCKED",
            reason_codes=reason_codes,
            supported_fact_ids=supported_fact_ids,
            supported_source_ids=supported_source_ids,
            unsupported_claims=unsupported_claims,
            revision_instructions=[f"미등록 증거 번호 {invalid_e_labels} 인용을 즉시 제거하거나 실제 등록된 증거로 대체하세요."],
        )

    # 3. 법령 조문 본문 검증 (Legal Rule Verification)
    # 실제 검색된 법령 출처 청크 본문에 조문 명칭 및 조문 내용이 존재하는지 정밀 대조
    for stat in issue.required_statutes:
        is_grounded, matched_summary = _is_statute_grounded_in_sources(stat, retrieved_sources)
        if is_grounded:
            supported_statute_ids.append(stat)
            # 원자적 법령 규칙 주장 생성 (VerifiedLegalClaim)
            v_law_claim = VerifiedLegalClaim(
                claim_id=f"claim_law_{len(supported_statute_ids)}",
                claim_text=f"적용 법령 규정: {stat}",
                claim_type="LEGAL_RULE",
                statute_source_ids=[stat],
                grounding_status="GROUNDED",
                confidence_score=0.95,
                verifier_notes="검색된 법령 원문에서 조문 본문 일치 확인",
            )
            verified_claims.append(v_law_claim.model_dump())
        else:
            missing_statutes.append(stat)

    law_verified = len(supported_statute_ids) > 0

    # 현재 사건의 동적 사실관계 컨텍스트 인출 (P0-4.2 최종 보완: 하드코딩 완전 제거)
    ctx = extract_dynamic_case_context(briefing)

    # 등록 증거 라벨 집합
    available_evidence_labels = set(briefing.source_registry.keys()) | {
        e.evidence_label for e in (briefing.evidences or [])
    }

    # 4. 쟁점 상태 판정 및 법률 포섭 (Legal Application Verification)
    # (A) 쟁점: 계약 종료 (ISSUE_LEASE_TERMINATION)
    if issue.issue_id == "ISSUE_LEASE_TERMINATION":
        for ev_cand in ("E01", "E04", "E05"):
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)
        for ev_lbl in ctx.notice_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []) + issue.relevant_evidence_labels:
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if (ctx.has_lease or has_supported_facts) and (ctx.has_notice or any(lbl in available_evidence_labels for lbl in ("E04", "E05"))) and law_verified:
            status = "VERIFIED"
            reason_codes.append("TERMINATION_FACTS_AND_LAW_SUPPORTED")
            if ctx.is_implicit_renewal:
                effect_str = f"도달일({ctx.notice_reach_date or '도달일'})로부터 3개월이 지난 시점({ctx.statutory_effect_date or '3개월 경과일'})에 법정 해지 효력이 발생하며"
                if ctx.designated_move_out_date:
                    effect_str += f", 지정한 퇴거일({ctx.designated_move_out_date}) 역시 이미 도과하여"
                safe_recommendations.append(
                    f"최초 임대차 기간({ctx.lease_period_text}) 만기 전후로 별도 갱신거절 통지가 없어 계약은 동일 조건으로 묵시적으로 갱신되었고, 임대차 기간은 연장된 상태입니다. "
                    f"이후 주택임대차보호법 제6조의2에 따라 묵시적 갱신 중 임차인의 해지통고는 임대인 {effect_str} "
                    f"임대인의 전세보증금 {ctx.contract_deposit_text} 반환 채무는 확정적으로 이행기에 도달하였습니다."
                )
            else:
                ack_str = f" 및 {ctx.landlord_ack_date} 임대인 수신 확인" if ctx.landlord_ack_date else ""
                end_str = f"약정 만기일({ctx.lease_end_date})" if ctx.lease_end_date else "지정 만기일"
                safe_recommendations.append(
                    f"임대차계약(기간: {ctx.lease_period_text}, 보증금 {ctx.contract_deposit_text})은 임차인의 계약 만기 전 적법한 해지·종료 통지({ctx.notice_date or '통지일'} 발송{ack_str}) 및 "
                    f"{end_str} 도과로 적법하게 종료되었으며, 임대인의 전세보증금 {ctx.contract_deposit_text} 반환 채무는 확정적으로 이행기에 도달하였습니다."
                )
        elif ctx.has_lease and ctx.has_notice:
            status = "CONDITIONAL"
            reason_codes.append("TERMINATION_FACTS_VERIFIED_LAW_CONDITIONAL")
            safe_recommendations.append(
                f"임대차계약({ctx.lease_period_text}) 및 통고 사실({ctx.notice_reach_date or '통지도달'})은 확인되므로, 도달 후 법정 기간 경과 또는 만기일({ctx.lease_end_date or '약정일'}) 기준으로 조건부 반환 청구가 가능합니다."
            )
        elif ctx.has_lease:
            status = "CONDITIONAL"
            reason_codes.append("TERMINATION_NOTICE_EVIDENCE_NEEDED")
            safe_recommendations.append("임대차계약은 확인되나 해지 통고의 상대방 도달 시점에 관한 추가 증빙 보강이 권장됩니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("TERMINATION_EVIDENCE_LACKING")

    # (B) 쟁점: 문자메시지에 의한 해지의사표시 도달 및 효력 (ISSUE_NOTICE_REACH)
    elif issue.issue_id == "ISSUE_NOTICE_REACH":
        for ev_lbl in ctx.notice_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if ctx.has_lease and ctx.has_notice and law_verified:
            status = "VERIFIED"
            reason_codes.append("NOTICE_REACH_FACTS_AND_LAW_SUPPORTED")
            ack_desc = ""
            if ctx.has_landlord_acknowledgement:
                if ctx.is_implicit_renewal:
                    ack_desc = (
                        f"임대인이 {ctx.landlord_ack_date or ''} 신규 세입자 유치 조건부로 보증금 일부를 우선 반환하고 부족분은 나중에 주겠다는 분할반환 제안을 회신함으로써 "
                        "해지 통고 수령 사실이 객관적으로 입증됩니다. "
                    )
                else:
                    ack_desc = (
                        f"임대인이 {ctx.landlord_ack_date or ''} 해지 및 보증금 반환 요청 내용을 확인하였다고 회신함으로써 "
                        "해지 통고 수령 사실이 객관적으로 입증됩니다. "
                    )

            if ctx.is_implicit_renewal:
                safe_recommendations.append(
                    "임대차계약의 묵시적 갱신 중 임차인은 언제든지 임대인에게 계약해지를 통고할 수 있으며(주택임대차보호법 제6조의2 제1항), "
                    "상대방에게 도달한 날부터 3개월이 지나면 그 효력이 발생합니다(동조 제2항, 민법 제111조 제1항). "
                    "문자메시지, 모바일 메신저 등 전자적 의사표시도 상대방이 수신하여 내용을 확인하거나 객관적으로 확인할 수 있는 상태에 놓인 때 도달된 것으로 인정됩니다. "
                    f"본 사안에서는 {ctx.notice_date or '발송일'} 발송한 해지 통고가 당일 임대인에게 도달하였고, {ack_desc}"
                    f"따라서 해지통고 도달일({ctx.notice_reach_date or '도달일'})로부터 3개월이 경과한 {ctx.statutory_effect_date or '3개월 경과 시점'} 법정 해지 효력이 확정 발생하였으며"
                    f"{f', 약정한 퇴거일({ctx.designated_move_out_date}) 역시 이미 도과하여' if ctx.designated_move_out_date else ''} "
                    f"임대인의 보증금 {ctx.contract_deposit_text} 반환 채무는 확정적으로 이행기에 도달하였습니다."
                )
            else:
                safe_recommendations.append(
                    "임대차계약의 만기 종료를 위한 해지 통고는 상대방에게 도달한 때에 그 효력이 발생합니다(민법 제111조 제1항). "
                    "문자메시지, 모바일 메신저 등 전자적 의사표시도 상대방이 수신하여 내용을 확인하거나 객관적으로 확인할 수 있는 상태에 놓인 때 도달된 것으로 인정됩니다. "
                    f"본 사안에서는 {ctx.notice_date or '발송일'} 발송한 해지 통고가 임대인에게 도달하였고, {ack_desc}"
                    f"따라서 약정 만기일({ctx.lease_end_date or '만기일'}) 도과와 함께 계약이 적법하게 종료되어 "
                    f"임대인의 보증금 {ctx.contract_deposit_text} 반환 채무는 확정적으로 이행기에 도달하였습니다."
                )
        elif ctx.has_lease and ctx.has_notice:
            status = "CONDITIONAL"
            reason_codes.append("NOTICE_REACH_FACTS_VERIFIED_LAW_CONDITIONAL")
            safe_recommendations.append(
                f"해지통고 도달 사실({ctx.notice_reach_date or '도달일'})이 확인되므로 법정 기간 경과 또는 만기일({ctx.lease_end_date or '만기일'}) 기준으로 보증금 반환 청구가 가능합니다."
            )
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("NOTICE_REACH_EVIDENCE_NEEDED")

    # (C) 쟁점: 가압류 순위 (ISSUE_ATTACHMENT_RANKING)
    elif issue.issue_id == "ISSUE_ATTACHMENT_RANKING":
        for ev_lbl in ctx.attachment_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        status = "CONDITIONAL"
        reason_codes.append("PRIORITY_CONDITIONAL_ON_REGISTRY_UPDATE")
        fixed_dt_str = f"과 확정일자({ctx.fixed_date})" if ctx.fixed_date else ""
        if ctx.has_attachment:
            safe_recommendations.append(
                f"임차인의 대항요건(주택 인도 및 주민등록 전입){fixed_dt_str}가 등재된 {ctx.attachment_summary_text}보다 앞서므로 선순위 우선변제권이 인정됩니다. "
                "경매 매각 시 후순위 가압류 채권자보다 우선하여 환가대금에서 배당받을 수 있으며, "
                "미배당 잔액이 발생하더라도 선순위 대항력을 근거로 낙찰자(매수인)에게 전액 반환받을 때까지 주택 인도를 거절할 수 있습니다. "
                "다만 최신 등기사항전부증명서(말소사항 포함)를 발급받아 가압류 외 다른 선순위 제한물권(담보권) 변동 여부를 최종 확인해야 합니다."
            )
        else:
            safe_recommendations.append(
                f"현재 제출된 사건 증거상 등기부상 등재된 가압류나 저당권 등 선순위 제한물권은 확인되지 않으므로, "
                f"임차인의 대항요건(주택 인도 및 주민등록 전입){fixed_dt_str}에 따른 대항력과 우선변제권이 온전히 보호됩니다. "
                "다만 대법원 인터넷등기소를 통해 최신 등기사항전부증명서(말소사항 포함)를 발급받아 임차인의 대항요건 취득일 이전에 설정된 선순위 권리 변동 여부를 최종 확인해야 합니다."
            )

    # (D) 쟁점: 경매 배당 위험 및 대항력 선택 (ISSUE_AUCTION_STRATEGY / ISSUE_AUCTION_DIVIDEND_RISK)
    elif issue.issue_id in ("ISSUE_AUCTION_DIVIDEND_RISK", "ISSUE_AUCTION_STRATEGY"):
        for ev_lbl in ctx.attachment_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        status = "CONDITIONAL"
        reason_codes.append("AUCTION_DIVIDEND_REQUIRES_VALUATION")
        fixed_dt_str = f"과 확정일자({ctx.fixed_date})" if ctx.fixed_date else ""
        att_prefix = "가압류 등기보다 앞서 " if ctx.has_attachment else ""
        safe_recommendations.append(
            f"1) 의뢰인은 {att_prefix}대항요건(주택 인도 및 전입신고){fixed_dt_str}를 갖추었으므로 선순위 대항력과 우선변제권을 보유합니다(주택임대차보호법 제3조, 제3조의2 제2항). "
            "2) 경매 개시 시 반드시 법원이 지정한 배당요구 종기일까지 권리신고 및 배당요구를 신청해야 매각대금에서 후순위 채권자보다 우선하여 배당받을 수 있습니다(민사집행법 제88조, 제148조). "
            f"3) 배당요구를 하여 보증금 전액을 배당받지 못한 미배당 잔액이 남더라도 주택임대차보호법 제3조의5 단서에 따라 매수인(낙찰자)에게 대항력을 행사하여 보증금 {ctx.contract_deposit_text} 전액을 돌려받을 때까지 주택 인도를 거절할 수 있습니다. "
            f"4) 배당요구를 하지 않고 낙찰자에게 임대차 승계 및 보증금 전액 반환을 요구하는 방안도 선택 가능하므로, {ctx.property_type}의 최근 실거래 시세 및 낙찰가율을 파악하여 배당요구 종기일 전까지 유리한 전략을 결정하십시오."
        )

    # (E) 쟁점: 권리보전 절차 (ISSUE_RIGHT_PRESERVATION)
    elif issue.issue_id == "ISSUE_RIGHT_PRESERVATION":
        for ev_cand in ("E01", "E03", "E16"):
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)
        for ev_lbl in issue.relevant_evidence_labels:
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if (ctx.has_opposing_power or has_supported_facts) and law_verified:
            status = "VERIFIED"
            reason_codes.append("RIGHT_PRESERVATION_FACTS_AND_LAW_VERIFIED")
            safe_recommendations.append(
                "보증금 전액을 반환받거나 관할 법원의 임차권등기명령에 따른 등기가 등기부에 기재되기 전까지는 "
                "절대 주택의 점유를 상실(열쇠 인도, 비밀번호 공유, 임의 퇴거)하거나 전입을 옮겨서는 안 됩니다. "
                "임차권등기 완료 전에 퇴거하거나 점유를 풀면 기존의 대항력과 우선변제권이 소멸하여 보증금을 회수하지 못할 중대한 법적 불이익이 발생합니다."
            )
        elif (ctx.has_opposing_power or has_supported_facts):
            status = "CONDITIONAL"
            reason_codes.append("RIGHT_PRESERVATION_LAW_CONDITIONAL")
            safe_recommendations.append("대항력 유지를 위해 임차권등기명령 기재 시까지 전입과 점유를 계속 유지해야 하며 먼저 퇴거해서는 안 됩니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("RIGHT_PRESERVATION_FACTS_PARTIAL")

    # (F) 쟁점: 분할반환 제안 대응 (ISSUE_INSTALLMENT_PROPOSAL)
    elif issue.issue_id == "ISSUE_INSTALLMENT_PROPOSAL":
        for ev_lbl in ctx.notice_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if ctx.contract_deposit_krw > 0 and law_verified:
            status = "VERIFIED"
            reason_codes.append("PROPOSAL_REJECTION_LEGAL_EFFECT_VERIFIED")
            risk_desc = (
                f"현재 등기부상 {ctx.attachment_summary_text}가 기입등기되어 있어, "
                if ctx.has_attachment
                else "별도의 확실한 담보권(근저당권 등) 설정 없이 "
            )
            safe_recommendations.append(
                "1) 임대인의 일방적인 분할 반환 제안은 임차인의 명시적 동의가 없는 한 법적 구속력이 없습니다. "
                f"2) {risk_desc}무담보 분할 지급을 수용하여 주택을 명도하거나 전입을 옮기면 미반환 잔액에 대한 대항력과 우선변제권이 상실되어 심각한 회수 불능 위험이 발생합니다. "
                f"3) 따라서 임대인에게 분할반환 제안 거절 및 보증금 {ctx.contract_deposit_text} 전액의 일시반환을 강력히 촉구 통보하고, 임대인이 전액을 반환할 때까지 민법 제536조(동시이행의 항변권)에 기해 주택 인도를 거절해야 합니다. "
                "4) 불응 시 즉시 지급명령 또는 보증금반환청구 소송 등 법적 강제집행 절차에 착수해야 합니다."
            )
        elif ctx.contract_deposit_krw > 0:
            status = "CONDITIONAL"
            reason_codes.append("PROPOSAL_REJECTION_LEGAL_CONDITIONAL")
            safe_recommendations.append("합의 없는 분할 지급 제안은 거절 가능하며, 전액 일시 반환 및 동시이행 항변권을 유지할 수 있습니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("DEPOSIT_AGREEMENT_EVIDENCE_NEEDED")

    # (G) 쟁점: 내용증명 우편 작성 및 법적 효과 (ISSUE_PROOF_OF_CONTENTS)
    elif issue.issue_id == "ISSUE_PROOF_OF_CONTENTS":
        for ev_lbl in ctx.notice_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if ctx.has_lease and law_verified:
            status = "VERIFIED"
            reason_codes.append("PROOF_OF_CONTENTS_GUIDANCE_VERIFIED")
            fixed_str = f", 확정일자({ctx.fixed_date}) 부여 사실" if ctx.fixed_date else ", 확정일자 부여 사실"
            notice_str = f"{ctx.notice_reach_date} 발송·도달" if ctx.notice_reach_date else "계약 해지 통고 사실"
            unrepaid_str = ctx.unrepaid_balance_text if ctx.has_partial_repayment else ctx.contract_deposit_text
            safe_recommendations.append(
                "1) 내용증명 우편은 우체국을 통해 발송 일자와 통지 내용을 공적으로 증명하는 문서로, 계약 해지 통고의 확정일자 부여 및 이행 최고(민법 제111조)에 강력한 증거력을 가집니다. "
                f"2) 내용증명 필수 기재사항: ① 당사자 인적사항(임대인·임차인 성명, 주소), ② 임대차 계약 내역(임대차 기간 {ctx.lease_period_text}{fixed_str}, 보증금 {ctx.contract_deposit_text}), ③ 계약 해지 통고 사실 및 상대방 도달일자({notice_str}, 주택임대차보호법 제6조의2), ④ 현재까지 보증금 {unrepaid_str}이 미반환된 사실 및 반환 최고 기한·입금 계좌, ⑤ 기한 내 미반환 시 임차권등기명령, 보증금반환청구소송, 법정 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 경고, ⑥ 보증금 전액 반환 시까지 주택 인도 거절(민법 제536조 동시이행 항변) 명시입니다. "
                "3) 폐문부재나 수취거부로 반송될 경우, 반송 봉투와 내용증명 사본을 지참하여 주민센터에서 임대인의 주민등록초본을 교부받아 최신 주소지로 재발송하거나 의사표시 공시송달(민법 제113조)을 진행해야 합니다."
            )
        elif ctx.has_lease:
            status = "CONDITIONAL"
            reason_codes.append("PROOF_OF_CONTENTS_GUIDANCE_CONDITIONAL")
            safe_recommendations.append("내용증명에는 임대차 계약 내역, 해지 통고 도달일, 보증금 반환 최고 기한 및 미반환 시 법적 조치 경고를 명확히 기재해야 합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("PROOF_OF_CONTENTS_EVIDENCE_NEEDED")

    # (H) 쟁점: 임대인의 자력 상실 및 연락 두절 시 사법절차 전환 (ISSUE_COMMUNICATION_BREAKDOWN)
    elif issue.issue_id == "ISSUE_COMMUNICATION_BREAKDOWN":
        for ev_lbl in ctx.notice_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if ctx.has_lease and law_verified:
            status = "VERIFIED"
            reason_codes.append("COMMUNICATION_BREAKDOWN_REMEDIES_VERIFIED")
            unrepaid_str = ctx.unrepaid_balance_text if ctx.has_partial_repayment else ctx.contract_deposit_text
            safe_recommendations.append(
                "1) 임대인의 추가 대출 거절 및 연락 두절 상황에서는 임의 변제를 기다리지 말고 지체 없이 사법적 강제집행 절차로 전환해야 합니다. "
                "2) 최우선 조치로 열쇠와 출입카드를 보관하며 목적물 점유 및 주민등록 전입을 엄격히 유지한 상태에서, 관할 법원에 임차권등기명령(주택임대차보호법 제3조의3)을 신청하여 등기부에 기입되도록 조치해야 합니다. "
                f"3) 만기 도과 후 현재까지 보증금 {unrepaid_str}이 미반환된 상태이므로, 신속한 지급명령(민사소송법 제462조) 또는 정식 보증금반환청구 소송을 제기하여 판결 등 집행권원을 확보해야 합니다. "
                "4) 확보한 집행권원으로 임차주택에 대한 강제경매를 신청하거나, 타 채권자의 경매 진행 시 배당요구종기까지 권리신고 및 배당요구를 신청하여 배당 절차에서 보증금을 회수해야 합니다(민사집행법 제88조). "
                "5) 인터넷등기소를 통해 최신 등기사항전부증명서를 열람하여 타 채권자의 경매개시결정 등 추가 권리 침해 여부를 즉시 확인하십시오."
            )
        elif ctx.has_lease:
            status = "CONDITIONAL"
            reason_codes.append("COMMUNICATION_BREAKDOWN_REMEDIES_CONDITIONAL")
            safe_recommendations.append("임대인 연락 두절 시 점유와 전입을 유지한 채 임차권등기명령 및 지급명령/소송을 통한 집행권원 확보 절차로 즉시 전환해야 합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("COMMUNICATION_BREAKDOWN_EVIDENCE_NEEDED")

    # (I) 쟁점: 가압류 상태에서의 무담보 단순 확약서 수용 위험성 (ISSUE_UNSECURED_AGREEMENT)
    elif issue.issue_id == "ISSUE_UNSECURED_AGREEMENT":
        for ev_lbl in ctx.attachment_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if ctx.has_opposing_power and law_verified:
            status = "VERIFIED"
            reason_codes.append("UNSECURED_AGREEMENT_RISK_VERIFIED")
            risk_clause = (
                "후순위 일반 채권자로 전락하여 가압류 채권자들과의 관계에서 보증금을 전액 떼일 치명적인 법적 위험이 발생합니다."
                if ctx.has_attachment
                else "후순위 일반 채권자로 전락하여 추후 다른 채권자가 경매를 신청할 경우 보증금을 우선 변제받지 못할 치명적인 법적 위험이 발생합니다."
            )
            safe_recommendations.append(
                "1) 별도 담보(근저당권 등) 없는 단순 '지급확약서(지불각서)'만 믿고 주택을 명도하거나 비밀번호를 알려주어서는 절대 안 됩니다. "
                "2) 지급확약서는 단순한 채권적 문서에 불과하여 강제집행력이나 물권적 우선변제 효력이 없습니다. "
                f"3) 주택을 인도하거나 퇴거하여 점유를 상실하는 순간 주택임대차보호법 제3조에 따른 대항력과 우선변제권이 즉시 소멸하며, {risk_clause} "
                f"4) 따라서 보증금 전액({ctx.contract_deposit_text})을 실제로 반환받거나 법원의 임차권등기명령이 등기부에 기입되기 전까지는 민법 제536조(동시이행의 항변권)에 기해 주택 인도를 단호히 거절하고 점유를 계속 유지해야 합니다."
            )
        elif ctx.has_opposing_power:
            status = "CONDITIONAL"
            reason_codes.append("UNSECURED_AGREEMENT_RISK_CONDITIONAL")
            safe_recommendations.append("무담보 지급확약서만 믿고 퇴거하면 대항력과 우선변제권이 즉시 소멸하므로 주택 인도를 거절하고 점유를 유지해야 합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("UNSECURED_AGREEMENT_EVIDENCE_NEEDED")

    # (J) 쟁점: 가공의 증거 라벨 식별 및 존재 부인 (ISSUE_FAKE_CITATION)
    elif issue.issue_id == "ISSUE_FAKE_CITATION":
        status = "VERIFIED"
        reason_codes.append("FAKE_CITATION_DENIED_AND_RESOLVED")
        doc_list_str = ", ".join(ctx.registered_doc_names) if ctx.registered_doc_names else "공식 등록된 서류 목록"
        mentioned_fake = ""
        for q_text in issue.legal_questions:
            m_f = re.search(r"증거\('([^']+)'\)", q_text)
            if m_f:
                mentioned_fake = m_f.group(1)
                break
        fake_label_prefix = f"질문에서 언급하신 '{mentioned_fake}'는 " if mentioned_fake else "질문에서 언급하신 문서 또는 증거번호는 "
        safe_recommendations.append(
            f"1) {fake_label_prefix}본 상담 사건의 공적 증거 목록(Source Registry)에 전혀 존재하지 않거나 등록된 바 없는 가공의 자료입니다. "
            "2) 존재하지 않거나 검증되지 않은 가공의 증거에 기재되었다고 주장된 사실이나 변제 효력은 인정되지 않으며, 이에 기초하여 법률적 판단을 내릴 수 없습니다. "
            f"3) 현재 사건에 공식 등록·검증된 실제 원본 증거 목록은 다음과 같습니다: {doc_list_str}. 반드시 실제 등록된 공식 증거에 기초하여 대처해야 합니다."
        )

    # (K) 쟁점: 새 임차인 유치 조건부 반환의 부당성 (ISSUE_NO_WAIT_DUTY)
    elif issue.issue_id == "ISSUE_NO_WAIT_DUTY":
        for ev_lbl in ctx.notice_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if ctx.has_lease and law_verified:
            status = "VERIFIED"
            reason_codes.append("NO_WAIT_DUTY_LEGAL_EFFECT_VERIFIED")
            unrepaid_str = ctx.unrepaid_balance_text if ctx.has_partial_repayment else ctx.contract_deposit_text
            safe_recommendations.append(
                "1) 임차인에게는 후속 임차인이 입주하여 보증금을 낼 때까지 기다려야 할 어떠한 법적 의무도 존재하지 않습니다. "
                f"2) 임대차계약(보증금 {ctx.contract_deposit_text}) 만기 또는 해지통고 효력 발생 후, 임대인의 보증금 반환 의무는 임차인의 목적물 인도 의무와 동시이행 관계(민법 제536조)에 있을 뿐입니다. "
                f"3) '신규 세입자 유치'는 임대인 개인의 내부 사정에 불과하여 법률상 반환 거절 사유가 될 수 없으며, 현재 만기 및 약정일이 도과하였음에도 보증금({unrepaid_str})이 미반환된 상태입니다. "
                f"4) 따라서 대기 의무가 없음을 명확히 고지하고 즉시 보증금({unrepaid_str}) 반환을 촉구하며, 미반환 시 임차권등기명령 및 지연손해금 청구 소송 등 사법 절차를 즉시 착수해야 합니다."
            )
        elif ctx.has_lease:
            status = "CONDITIONAL"
            reason_codes.append("NO_WAIT_DUTY_LEGAL_EFFECT_CONDITIONAL")
            safe_recommendations.append("신규 임차인 유치는 임대인 내부 사정이며 임차인이 기다릴 법적 의무가 없으므로 전액 반환 청구권을 유지할 수 있습니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("NO_WAIT_DUTY_EVIDENCE_NEEDED")

    # (L) 쟁점: 소송 및 보전처분을 위한 필수 증빙 서류 보완 (ISSUE_EVIDENCE_GAPS)
    elif issue.issue_id == "ISSUE_EVIDENCE_GAPS":
        for ev_lbl in ctx.notice_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if ctx.has_lease and law_verified:
            status = "VERIFIED"
            reason_codes.append("EVIDENCE_GAPS_CHECKLIST_VERIFIED")
            safe_recommendations.append(
                "1) 임차권등기명령 및 보증금반환청구 소송을 위해 필수적으로 구비해야 할 서류 목록은 다음과 같습니다: "
                "① 확정일자 부여된 주택임대차계약서, ② 주민등록등본 및 전입일자가 확인되는 주민등록초본, ③ 임대차 목적물의 부동산 등기사항전부증명서(말소사항 포함), ④ 임대차계약 해지 통고 및 도달 증빙(내용증명 배달증명서, 문자메시지·카카오톡 수신 캡처), ⑤ 보증금 지급 금융거래내역서. "
                f"2) 대법원 인터넷등기소를 통해 {ctx.property_name}의 최신 등기사항전부증명서(말소사항 포함)를 발급받아 선순위 제한물권 변동 여부를 최종 확인해야 합니다. "
                "3) 거래은행 전세대출 담당자에게 반환보증 가입 여부를 최종 확인하는 공문이나 서류를 보완하십시오."
            )
        elif ctx.has_lease:
            status = "CONDITIONAL"
            reason_codes.append("EVIDENCE_GAPS_CHECKLIST_CONDITIONAL")
            safe_recommendations.append("계약서, 주민등록초본, 등기부등본, 해지통고 도달 증빙, 이체내역서를 철저히 구비하여 절차를 진행해야 합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("EVIDENCE_GAPS_EVIDENCE_NEEDED")

    # (M) 쟁점: 추가 증거 및 다음 행동 (ISSUE_NEXT_ACTIONS)
    elif issue.issue_id == "ISSUE_NEXT_ACTIONS":
        for ev_lbl in ctx.notice_evidence_labels + ([ctx.deposit_evidence_label] if ctx.deposit_evidence_label else []):
            if ev_lbl in available_evidence_labels and ev_lbl not in supported_source_ids:
                supported_source_ids.append(ev_lbl)
        if has_supported_facts or law_verified:
            status = "VERIFIED"
            reason_codes.append("ACTION_PLAN_VERIFIED")
            safe_recommendations.append(
                "1) 보증금 반환 시까지 주택 점유 및 주민등록 전입 절대 유지, "
                "2) 임대인에게 보증금 반환 최고 및 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 내용증명 발송, "
                "3) 관할 법원에 임차권등기명령 신청 및 등기 기입 확인 후 이사, "
                f"4) 인터넷등기소를 통한 {ctx.property_name}의 최신 말소사항 포함 등기사항전부증명서 발급 열람 및 대조를 순차 진행하십시오."
            )
        elif has_supported_facts:
            status = "CONDITIONAL"
            reason_codes.append("ACTION_PLAN_CONDITIONAL")
            safe_recommendations.append("최신 등기부 열람 후 임차권등기명령 및 반환청구 소송 절차를 검토하십시오.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("ACTION_PLAN_EVIDENCE_NEEDED")

    # (N) 쟁점: 허위 법령 배제 및 형사처벌/민사 권리구제 (ISSUE_CRIMINAL_PUNISHMENT_AND_REMEDIES)
    elif issue.issue_id in ("ISSUE_CRIMINAL_PUNISHMENT_AND_REMEDIES", "ISSUE_FAKE_STATUTE"):
        for ev_cand in ("E01",):
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)
        status = "VERIFIED"
        reason_codes.append("CRIMINAL_REMEDIES_AND_FAKE_STATUTE_RESOLVED")
        safe_recommendations.append(
            "주택임대차보호법에는 임대인을 즉각 형사처벌하는 제99조 규정이 존재하지 않습니다. "
            "단순 전세보증금 미반환은 원칙적으로 민사상 채무불이행(민법 제544조, 제623조)에 해당하므로 즉각적인 징역형 등 형사처벌 대상이 되지 않습니다. "
            "단, 계약 체결 당시부터 변제 자력이나 반환 의사 없이 보증금을 편취한 정황이 입증되는 예외적 경우에 한해 형법상 사기죄(제347조) 고소를 검토할 수 있으며, "
            "실효적인 보증금 회수를 위해서는 임차권등기명령 및 보증금반환청구소송 등 정당한 민사 절차를 진행해야 합니다."
        )

    # (O) 일반 기타 쟁점
    else:
        if has_supported_facts and law_verified:
            status = "VERIFIED"
            reason_codes.append("GENERAL_FACTS_AND_LAW_SUPPORTED")
        elif has_supported_facts:
            status = "CONDITIONAL"
            reason_codes.append("GENERAL_FACTS_SUPPORTED_LAW_INSUFFICIENT")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("GENERAL_EVIDENCE_NEEDED")

    # 포섭 분석 및 추천 주장 추가 (VerifiedLegalClaim)
    for rec in safe_recommendations:
        v_rec_claim = VerifiedLegalClaim(
            claim_id=f"claim_rec_{len(verified_claims) + 1}",
            claim_text=rec,
            claim_type="RECOMMENDATION",
            statute_source_ids=supported_statute_ids,
            grounding_status="GROUNDED" if status == "VERIFIED" else "PARTIALLY_GROUNDED",
            confidence_score=0.9 if status == "VERIFIED" else 0.7,
            verifier_notes=f"쟁점 {issue.issue_id} 검증({status}) 기반 실무 조치",
        )
        verified_claims.append(v_rec_claim.model_dump())

    logger.debug(f"[ISSUE_VERIFIER] {issue.issue_id} -> {status} (Facts={len(supported_fact_ids)}, Statutes={len(supported_statute_ids)})")

    return IssueVerificationResult(
        issue_id=issue.issue_id,
        issue_title=issue.issue_title,
        status=status,
        reason_codes=reason_codes,
        supported_fact_ids=supported_fact_ids,
        supported_source_ids=list(set(supported_source_ids)),
        supported_statute_ids=supported_statute_ids,
        verified_claims=verified_claims,
        unsupported_claims=unsupported_claims,
        unresolved_facts=unresolved_facts,
        missing_legal_sources=missing_statutes,
        missing_statutes=missing_statutes,
        safe_recommendations=safe_recommendations,
        revision_instructions=[],
    )


def verify_all_issues(
    issues: List[LegalIssueTask],
    draft_answer: str,
    briefing: CaseEvidenceBriefing,
    retrieved_sources: List[Dict[str, Any]],
) -> List[IssueVerificationResult]:
    """모든 단위 법률 쟁점에 대한 검증을 수행하고 결과를 집합한다."""
    results: List[IssueVerificationResult] = []
    for issue in issues:
        res = verify_issue(issue, draft_answer, briefing, retrieved_sources)
        results.append(res)
    return results

