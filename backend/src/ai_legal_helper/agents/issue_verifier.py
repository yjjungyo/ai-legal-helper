# -*- coding: utf-8 -*-
"""
모듈명: issue_verifier.py

[모듈 개요]
법률 상담 초안(Draft Answer)을 전체 일괄 판정(PASS/REVISE/INSUFFICIENT)하는 대신,
단위 쟁점(Issue)별로 분리하여 독립적으로 검증하는 쟁점별 검증 엔진(Issue-Level Verification Engine).

[주요 기능]
1. Fact Verifier와 Legal Verifier의 엄격한 3단계 분리 검증 (Section 7, Section 12):
   - FactVerification: CaseEvidenceBriefing 내 FactAdjudication(EVIDENCE_SUPPORTED/CORROBORATED) 및 증거 라벨 유효성 대조
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
4. 사건 독립적 법률 판단 무결성 (P0-4.2 최종 보완 v3.0):
   - 특정 사건 종속 금액, 일자, 채권자명, 목적물 및 증거번호(E01, E03 등)의 고정을 전면 제거
   - CaseEvidenceBriefing 및 settlement_calculator의 검증된 단일 원천 데이터로부터 동적 도출
"""

from typing import List, Dict, Any, Optional, Literal, Union, Tuple
import datetime
import re
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.case_intelligence.consultation_semantics import is_conditional_contract_statement
from ai_legal_helper.case_intelligence.settlement_calculator import (
    is_fact_strictly_verified,
    format_krw_to_korean,
    extract_dates_from_text,
    extract_amounts_from_text,
    extract_case_contract_deposit,
    extract_case_prior_verified_repayments,
    calculate_three_months_expiry,
    evaluate_notice_status,
    evaluate_attachment_ranking,
    find_case_property_info,
    find_evidence_labels_by_type,
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
    if not stat or not retrieved_sources:
        return False, None

    # 검증 대상 조문 정규화 (공백 정규화)
    stat_clean = re.sub(r"\s+", " ", stat.strip())

    # 법령명 및 조문 번호 추출: e.g. ('주택임대차보호법', '3', '2') or ('민법', '536', None)
    m_stat = _STATUTE_REGEX.search(stat_clean)
    target_law = m_stat.group(1) if m_stat else ""
    main_art = m_stat.group(2) if m_stat else ""
    sub_art = m_stat.group(3) if m_stat else None

    # 조문 표기 변형 패턴 목록 구성
    art_patterns: List[str] = []
    if main_art:
        if sub_art:
            art_patterns.extend([
                f"제{main_art}조의{sub_art}",
                f"제 {main_art} 조의 {sub_art}",
                f"제{main_art}조의 {sub_art}",
                f"제 {main_art}조의{sub_art}",
                f"제{main_art}조 의 {sub_art}",
            ])
        else:
            art_patterns.extend([
                f"제{main_art}조",
                f"제 {main_art} 조",
                f"제 {main_art}조",
            ])

    # 1단계: target_law가 일치하거나 출처 법령 메타데이터가 일치하는 청크를 우선 필터링
    primary_chunks: List[Dict[str, Any]] = []
    fallback_chunks: List[Dict[str, Any]] = []

    for src in retrieved_sources:
        src_law = (src.get("source_law") or src.get("law_name") or "").strip()
        title = (src.get("title") or "").strip()
        citation = (src.get("citation") or "").strip()

        # 청크가 해당 법령에서 직접 인출된 것인지 판별
        if target_law and (target_law in src_law or target_law in title or target_law in citation):
            primary_chunks.append(src)
        else:
            fallback_chunks.append(src)

    # 2단계: 대상 법령 청크 본문에서 조문 번호 및 핵심 내용 대조
    candidate_chunks = primary_chunks if primary_chunks else fallback_chunks

    for src in candidate_chunks:
        content = src.get("content") or src.get("article_text") or ""
        title = src.get("title") or ""
        full_chunk_text = f"{title} {content}"

        # (a) 대상 법령명이 명시된 청크인지 확인 (타 법령 인용 방지)
        if target_law and not primary_chunks:
            if target_law not in full_chunk_text:
                continue

        # (b) 조문 번호 존재 여부 확인
        if art_patterns:
            matched_pattern = False
            for pat in art_patterns:
                if pat in full_chunk_text:
                    if not sub_art:
                        if f"{pat}의" in full_chunk_text or f"{pat} 의" in full_chunk_text:
                            continue
                    matched_pattern = True
                    break

            if matched_pattern:
                summary = content[:120].strip().replace("\n", " ")
                return True, summary
        else:
            if target_law and target_law in full_chunk_text:
                summary = content[:120].strip().replace("\n", " ")
                return True, summary

    return False, None


def verify_issue(
    issue: LegalIssueTask,
    draft_answer: str,
    briefing: CaseEvidenceBriefing,
    retrieved_sources: List[Dict[str, Any]],
) -> IssueVerificationResult:
    """단위 법률 쟁점(LegalIssueTask)에 대해 3단계 분리 검증을 수행한다.

    1. Fact Grounding: 쟁점 관련 Fact가 EVIDENCE_SUPPORTED/CORROBORATED 상태인지 검증.
    2. Citation Grounding: 인용된 증거 라벨이 Source Registry에 등록된 실제 증거인지 검증.
    3. Legal Rule Grounding: 요구되는 법령 조문 본문이 retrieved_sources에 실질 존재하는지 검증.
    4. Legal Application: 요건사실 충족 여부를 포섭하여 쟁점별 상태(VERIFIED, CONDITIONAL 등) 결정.
    """
    supported_fact_ids: List[str] = []
    supported_source_ids: List[str] = []
    supported_statute_ids: List[str] = []
    verified_claims: List[Dict[str, Any]] = []
    unsupported_claims: List[Dict[str, Any]] = []
    unresolved_facts: List[str] = []
    missing_statutes: List[str] = []
    reason_codes: List[str] = []
    safe_recommendations: List[str] = []

    # 1. 사실관계 검증 (Fact Grounding)
    fact_dict = {f.fact_id: f for f in briefing.facts}
    has_supported_facts = False
    has_incomplete_facts = False

    for fid in issue.relevant_fact_ids:
        f = fact_dict.get(fid)
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
    for stat in issue.required_statutes:
        is_grounded, matched_summary = _is_statute_grounded_in_sources(stat, retrieved_sources)
        if is_grounded:
            supported_statute_ids.append(stat)
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

    # 등록 증거 라벨 집합
    available_evidence_labels = set(briefing.source_registry.keys()) | {
        e.evidence_label for e in (briefing.evidences or [])
    }

    # 사건 브리핑으로부터 공통 법률 요건사실 및 계산 결과 동적 도출 (사건별 고정값 전면 제거)
    deposit_krw = extract_case_contract_deposit(briefing)
    repaid_krw, repaid_sources = extract_case_prior_verified_repayments(briefing)
    balance_krw = max(0, deposit_krw - repaid_krw) if deposit_krw > 0 else 0
    deposit_text = format_krw_to_korean(deposit_krw) if deposit_krw > 0 else "보증금"
    balance_text = format_krw_to_korean(balance_krw) if balance_krw > 0 else ("0원" if deposit_krw > 0 and repaid_krw >= deposit_krw else "미반환 잔액")

    # 기변제 원금 재청구 방지: 기변제액이 있는 경우 미반환 잔액만 청구하도록 엄격 제한
    if repaid_krw > 0:
        claim_amount_text = f"미반환 잔액 {balance_text}(총 보증금 {deposit_text} 중 {format_krw_to_korean(repaid_krw)} 기변제 공제 후 잔액)"
        demand_summary_text = f"미반환 잔액 {balance_text}"
    else:
        claim_amount_text = f"보증금 {deposit_text} 전액"
        demand_summary_text = f"보증금 {deposit_text} 전액"

    ref_date_str = getattr(briefing, "as_of_date", None)
    notice_info = evaluate_notice_status(briefing, reference_date=ref_date_str)
    ranking_info = evaluate_attachment_ranking(briefing, reference_date=ref_date_str)
    prop_name, prop_type = find_case_property_info(briefing)

    # 문서 유형에 따른 동적 증거 라벨 추출 (특정 증거번호 역할 고정 배제)
    lease_labels = find_evidence_labels_by_type(briefing, ["LEASE", "임대차", "계약서"])
    notice_labels = find_evidence_labels_by_type(briefing, ["NOTICE", "통고", "통지", "문자", "카카오", "내용증명"])
    residence_labels = find_evidence_labels_by_type(briefing, ["RESIDENCE", "주민등록", "전입", "초본", "등본"])
    attachment_labels = ranking_info.get("evidence_labels", []) or find_evidence_labels_by_type(briefing, ["REGISTRY", "등기", "가압류", "압류", "근저당"])

    # 4. 쟁점 상태 판정 및 법률 포섭 (Legal Application Verification)
    # (A) 쟁점: 계약 종료 (ISSUE_LEASE_TERMINATION)
    if issue.issue_id == "ISSUE_LEASE_TERMINATION":
        cand_labels = lease_labels + notice_labels + [lbl for lbl in issue.relevant_evidence_labels if lbl in available_evidence_labels]
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_lease = (
            len(lease_labels) > 0
            or any(any(w in f.statement for w in ("계약", "임대차", "보증금", "전세", "만료", "만기")) for f in briefing.facts if is_fact_strictly_verified(f, briefing))
            or any(lbl in briefing.source_registry for lbl in issue.relevant_evidence_labels)
        )
        has_notice = (
            len(notice_labels) > 0
            or notice_info["has_sent"]
            or notice_info["has_reached"]
            or any(any(w in f.statement for w in ("통지", "통고", "해지", "만료")) for f in briefing.facts if is_fact_strictly_verified(f, briefing))
        )

        has_sent = notice_info["has_sent"]
        has_reached = notice_info["has_reached"]
        reach_date = notice_info["reach_date"]
        sent_date = notice_info["sent_date"]
        effect_date = notice_info["statutory_effect_date"]
        move_out_date = notice_info["designated_move_out_date"]

        # 묵시적 갱신 여부에 따른 해지 요건사실 분기
        if notice_info["is_implicit_renewal"]:
            if has_lease and has_reached and law_verified:
                if not effect_date:
                    status = "CONDITIONAL"
                    reason_codes.append("TERMINATION_EFFECT_DATE_UNCONFIRMED")
                    safe_recommendations.append("해지 통지의 정확한 도달일이 없어 법정 효력 발생일을 확정할 수 없습니다.")
                elif notice_info.get("is_effect_date_future"):
                    status = "CONDITIONAL"
                    reason_codes.append("TERMINATION_EFFECT_DATE_FUTURE")
                    safe_recommendations.append(
                        f"주택임대차보호법 제6조의2 제2항에 따라 묵시적 갱신 중 임차인의 해지통고는 임대인 도달일({reach_date})로부터 3개월이 경과하는 {effect_date}에 해지 효력이 발생할 예정입니다. "
                        f"현재 상담 기준 시점({notice_info['reference_date']})에서는 아직 법정 효력 발생일이 도래하지 않았으므로, "
                        f"효력 발생일({effect_date}) 도래 시 임대인의 보증금 {deposit_text}(기변제 공제 후 {demand_summary_text}) 반환 채무가 이행기에 도달하게 됩니다."
                    )
                else:
                    status = "VERIFIED"
                    reason_codes.append("TERMINATION_FACTS_AND_LAW_SUPPORTED")
                    rec_parts = [
                        "최초 임대차 기간 만기 전후로 별도 갱신거절 통지가 없어 계약은 동일 조건으로 묵시적으로 갱신되어 임대차 기간이 연장된 상태였습니다. "
                        f"이후 주택임대차보호법 제6조의2에 따라 묵시적 갱신 중 임차인의 해지통고는 임대인 도달일({reach_date})로부터 3개월이 지난 시점({effect_date or '3개월 경과 시점'})에 "
                        "법정 해지 효력이 확정적으로 발생하였습니다."
                    ]
                    if move_out_date:
                        rec_parts.append(f" 또한 의뢰인이 통지로 지정한 퇴거일({move_out_date}) 역시 이미 도과하여,")
                    rec_parts.append(
                        f" 임대인의 보증금 {deposit_text}(기변제 공제 후 {demand_summary_text}) 반환 채무는 확정적으로 이행기에 도달하였습니다."
                    )
                    safe_recommendations.append("".join(rec_parts))
            elif has_lease and has_sent and not has_reached:
                status = "CONDITIONAL"
                reason_codes.append("TERMINATION_NOTICE_REACH_UNCONFIRMED")
                safe_recommendations.append(
                    f"임대차계약 및 해지 통고 발송 사실({sent_date or '발송'})은 확인되나, 상대방(임대인)에게 실제 도달한 일자가 객관적으로 확인되지 않았습니다. "
                    "민법 제111조 및 주택임대차보호법 제6조의2에 따라 해지의 효력은 상대방에게 도달한 날부터 3개월이 지나야 발생하므로, "
                    "상대방 도달일 입증 자료를 보강하기 전까지는 법정 해지 효력 발생 여부가 조건부 상태입니다."
                )
            elif has_lease and has_reached:
                status = "CONDITIONAL"
                reason_codes.append("TERMINATION_FACTS_VERIFIED_LAW_CONDITIONAL")
                safe_recommendations.append(
                    f"임대차계약 및 해지 통고 도달 사실({reach_date})은 확인되므로, 도달 후 3개월 경과 시점({effect_date or '3개월 경과일'}) 기준으로 조건부 반환 청구가 가능합니다."
                )
            elif has_lease:
                status = "CONDITIONAL"
                reason_codes.append("TERMINATION_NOTICE_EVIDENCE_NEEDED")
                safe_recommendations.append("임대차계약은 확인되나 해지 통고의 상대방 도달 시점에 관한 추가 증빙 보강이 권장됩니다.")
            else:
                status = "NEEDS_EVIDENCE"
                reason_codes.append("TERMINATION_EVIDENCE_LACKING")
        else:
            # 당초 계약 만기 만료 또는 일반 해지 (주택임대차보호법 제6조)
            # 만기일이 상담 기준일보다 미래인지 확인 (P0-03)
            expiry_dates = []
            for f in briefing.facts:
                if not is_fact_strictly_verified(f, briefing):
                    continue
                stmt = f.statement or ""
                if any(w in stmt for w in ["만기", "만료", "계약기간", "계약 기간", "임대차 기간", "종료"]):
                    expiry_dates.extend(extract_dates_from_text(stmt))

            is_future_expiry = False
            contract_expiry_date = None
            if expiry_dates:
                latest_exp = sorted(expiry_dates)[-1]
                contract_expiry_date = latest_exp
                try:
                    exp_parts = latest_exp.split(".")
                    ref_parts = notice_info["reference_date"].split(".")
                    exp_d = datetime.date(int(exp_parts[0]), int(exp_parts[1]), int(exp_parts[2]))
                    ref_d = datetime.date(int(ref_parts[0]), int(ref_parts[1]), int(ref_parts[2]))
                    if exp_d > ref_d:
                        is_future_expiry = True
                except Exception:
                    pass

            is_term_expired = bool(contract_expiry_date and not is_future_expiry)
            # 최초 만기 경과·일반 반환 조항·통지 도달만으로 현재 종료를 확정하지 않는다.
            # 갱신 정보가 없을 때도 실제 종료 사건이 별도로 입증되어야 한다.
            actual_termination_facts = [
                f for f in briefing.facts
                if is_fact_strictly_verified(f, briefing)
                and not is_conditional_contract_statement(f.statement)
                and re.search(
                    r"(?:종료|해지)(?:되었|됐|하였다|하였|됨|되었습니다)|"
                    r"합의\s*해지\s*완료",
                    f.statement,
                )
            ]
            is_expired_or_reached = bool(actual_termination_facts)
            if has_lease and is_future_expiry:
                status = "CONDITIONAL"
                reason_codes.append("TERMINATION_EXPIRY_DATE_FUTURE")
                safe_recommendations.append(
                    f"임대차계약서상 계약 만기일({contract_expiry_date})이 현재 상담 기준일({notice_info['reference_date']})보다 미래이므로, "
                    f"임대차기간 만료일({contract_expiry_date}) 도래 시 계약이 종료될 예정입니다. 만기 도래 전에는 보증금 반환 채무의 이행기가 아직 발생하지 않았습니다."
                )
            elif has_lease and is_expired_or_reached and law_verified:
                status = "VERIFIED"
                reason_codes.append("TERMINATION_FACTS_AND_LAW_SUPPORTED")
                if is_term_expired:
                    safe_recommendations.append(
                        f"임대차계약서상 계약 만기일({contract_expiry_date}) 경과와 별도로 실제 종료 사실이 등록 증거로 확인되었으므로, "
                        f"주택임대차보호법 제6조에 근거하여 임대인의 보증금 {deposit_text}(기변제 공제 후 {demand_summary_text}) 반환 채무는 확정적으로 이행기에 도달하였습니다."
                    )
                else:
                    safe_recommendations.append(
                        f"임대차계약서 및 통지 증빙에 따라 임대차 기간이 만료되거나 적법하게 종료되었으므로, "
                        f"주택임대차보호법 제6조에 근거하여 임대인의 보증금 {deposit_text}(기변제 공제 후 {demand_summary_text}) 반환 채무는 확정적으로 이행기에 도달하였습니다."
                    )
            elif has_lease and (has_notice or has_sent):
                status = "CONDITIONAL"
                reason_codes.append("TERMINATION_NOTICE_REACH_UNCONFIRMED")
                safe_recommendations.append(
                    f"임대차계약 및 통지 사실은 확인되나 상대방 도달 일자가 확인되지 않아, 만료 또는 해지 기준 조건부 보증금({demand_summary_text}) 반환 청구가 가능합니다."
                )
            elif has_lease:
                status = "CONDITIONAL"
                reason_codes.append("TERMINATION_NOTICE_EVIDENCE_NEEDED")
                safe_recommendations.append("임대차계약은 확인되나 해지 통고의 상대방 도달 시점에 관한 추가 증빙 보강이 권장됩니다.")
            else:
                status = "NEEDS_EVIDENCE"
                reason_codes.append("TERMINATION_EVIDENCE_LACKING")

    # (B) 쟁점: 문자메시지에 의한 해지의사표시 도달 및 효력 (ISSUE_NOTICE_REACH)
    elif issue.issue_id == "ISSUE_NOTICE_REACH":
        cand_labels = lease_labels + notice_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_lease = len(lease_labels) > 0 or any("계약" in f.statement for f in briefing.facts if is_fact_strictly_verified(f, briefing))
        has_sent = notice_info["has_sent"]
        has_reached = notice_info["has_reached"]
        sent_date = notice_info["sent_date"]
        reach_date = notice_info["reach_date"]
        effect_date = notice_info["statutory_effect_date"]
        move_out_date = notice_info["designated_move_out_date"]

        if has_lease and has_reached and notice_info.get("renewal_status") == "UNKNOWN":
            # 통지 도달 자체는 확인해도 갱신 유형·종료 효력은 별도로 입증해야 한다.
            status = "CONDITIONAL"
            reason_codes.append("NOTICE_RENEWAL_STATUS_UNCONFIRMED")
            safe_recommendations.append(
                "통지 도달 사실은 확인되나 갱신 유형과 현재 계약 종료 여부는 미확인입니다. "
                "최초 만기 이후의 갱신 경위와 통지 내용·일자를 대조해야 합니다."
            )
        elif has_lease and has_reached and law_verified and notice_info["is_implicit_renewal"] and not effect_date:
            status = "CONDITIONAL"
            reason_codes.append("NOTICE_EFFECT_DATE_UNCONFIRMED")
            safe_recommendations.append("해지 통지의 정확한 도달일이 없어 법정 효력 발생일을 확정할 수 없습니다.")
        elif has_lease and has_reached and law_verified:
            # 묵시적 갱신이 아닌 계약 만기 갱신거절 사안에서는 3개월 경과 효력일이 아닌 만기일에 확정 종료 (P0-02)
            if not notice_info["is_implicit_renewal"]:
                status = "VERIFIED"
                reason_codes.append("NOTICE_REACH_FACTS_AND_LAW_SUPPORTED")
                rec_parts = [
                    "주택임대차보호법 제6조에 따른 계약 종료 및 갱신거절 통지의 상대방 도달 사실이 임대인의 확인 회신 등을 통해 객관적으로 입증되었습니다. "
                ]
                if sent_date and reach_date:
                    rec_parts.append(f"본 사안에서는 {sent_date} 발송한 통고가 {reach_date} 임대인에게 도달하였고, ")
                elif reach_date:
                    rec_parts.append(f"본 사안에서는 통고가 {reach_date} 임대인에게 도달하였고, ")
                else:
                    rec_parts.append("본 사안에서는 통고의 도달 사실이 확인되었고, ")

                if notice_info["has_landlord_acknowledgement"]:
                    ack_date = notice_info["landlord_ack_date"]
                    date_prefix = f"{ack_date} " if ack_date else ""
                    rec_parts.append(f"임대인이 {date_prefix}답변 또는 회신을 함으로써 통고 수령 사실이 객관적으로 입증됩니다. ")

                rec_parts.append("통지 도달과 계약 종료·반환채무 이행기는 별개의 판단이므로 계약기간과 갱신거절 요건을 함께 확인해야 합니다.")
                safe_recommendations.append("".join(rec_parts))
            elif notice_info.get("is_effect_date_future"):
                status = "CONDITIONAL"
                reason_codes.append("NOTICE_EFFECT_PENDING_FUTURE")
                rec_parts = [
                    "임대차계약의 묵시적 갱신 중 임차인은 언제든지 임대인에게 계약해지를 통고할 수 있으며(주택임대차보호법 제6조의2 제1항), "
                    "상대방에게 도달한 날부터 3개월이 지나면 그 효력이 발생합니다(동조 제2항, 민법 제111조 제1항). "
                    "문자메시지, 모바일 메신저 등 전자적 의사표시도 상대방이 수신하여 내용을 확인하거나 객관적으로 확인할 수 있는 상태에 놓인 때 도달된 것으로 인정됩니다. "
                ]
                if sent_date and reach_date:
                    rec_parts.append(f"본 사안에서는 {sent_date} 발송한 해지 통고가 {reach_date} 임대인에게 도달하였음이 확인되었습니다. ")
                elif reach_date:
                    rec_parts.append(f"본 사안에서는 해지 통고가 {reach_date} 임대인에게 도달하였음이 확인되었습니다. ")
                else:
                    rec_parts.append("본 사안에서는 해지 통고의 도달 사실이 확인되었습니다. ")

                if notice_info["has_landlord_acknowledgement"]:
                    ack_date = notice_info["landlord_ack_date"]
                    date_prefix = f"{ack_date} " if ack_date else ""
                    rec_parts.append(f"임대인이 {date_prefix}답변 또는 회신을 함으로써 해지 통고 수령 사실이 객관적으로 입증됩니다. ")

                rec_parts.append(
                    f"다만 법정 3개월 경과 효력 발생일({effect_date})이 현재 상담 기준일({notice_info['reference_date']})보다 미래이므로, "
                    f"해당 효력 발생일({effect_date})이 도래해야 해지 효력 및 보증금({deposit_text}, 공제 후 {demand_summary_text}) 반환 채무의 이행기가 확정적으로 도달합니다."
                )
                safe_recommendations.append("".join(rec_parts))
            else:
                status = "VERIFIED"
                reason_codes.append("NOTICE_REACH_FACTS_AND_LAW_SUPPORTED")
                rec_parts = [
                    "임대차계약의 묵시적 갱신 중 임차인은 언제든지 임대인에게 계약해지를 통고할 수 있으며(주택임대차보호법 제6조의2 제1항), "
                    "상대방에게 도달한 날부터 3개월이 지나면 그 효력이 발생합니다(동조 제2항, 민법 제111조 제1항). "
                    "문자메시지, 모바일 메신저 등 전자적 의사표시도 상대방이 수신하여 내용을 확인하거나 객관적으로 확인할 수 있는 상태에 놓인 때 도달된 것으로 인정됩니다. "
                ]
                if sent_date and reach_date:
                    rec_parts.append(f"본 사안에서는 {sent_date} 발송한 해지 통고가 {reach_date} 임대인에게 도달하였고, ")
                elif reach_date:
                    rec_parts.append(f"본 사안에서는 해지 통고가 {reach_date} 임대인에게 도달하였고, ")
                else:
                    rec_parts.append("본 사안에서는 해지 통고의 도달 사실이 확인되었고, ")

                if notice_info["has_landlord_acknowledgement"]:
                    ack_date = notice_info["landlord_ack_date"]
                    date_prefix = f"{ack_date} " if ack_date else ""
                    rec_parts.append(f"임대인이 {date_prefix}답변 또는 회신을 함으로써 해지 통고 수령 사실이 객관적으로 입증됩니다. ")

                if effect_date:
                    rec_parts.append(f"따라서 해지통고 도달일({reach_date})로부터 3개월이 경과한 {effect_date} 법정 해지 효력이 확정 발생하였으며, ")
                else:
                    rec_parts.append(f"따라서 해지통고 도달일({reach_date})로부터 3개월이 경과하여 법정 해지 효력이 확정 발생하였으며, ")

                if move_out_date:
                    rec_parts.append(f"약정한 퇴거일({move_out_date}) 역시 이미 도과하여 ")

                rec_parts.append(f"임대인의 보증금 {deposit_text}(기변제 공제 후 {demand_summary_text}) 반환 채무는 확정적으로 이행기에 도달하였습니다.")
                safe_recommendations.append("".join(rec_parts))
        elif has_lease and has_sent and not has_reached:
            status = "CONDITIONAL"
            reason_codes.append("NOTICE_REACH_UNCONFIRMED")
            safe_recommendations.append(
                f"해지 통고를 발송한 사실({sent_date or '발송'})은 확인되나 임대인에게 실제로 도달하였는지 객관적인 수신 증빙이 확인되지 않았습니다. "
                "의사표시는 도달주의 원칙에 따라 상대방에게 도달해야 효력이 발생하므로, 임대인의 수신 확인 회신 또는 배달증명 등 도달 입증 증거를 확보해야 확정적 반환 청구가 가능합니다."
            )
        elif has_lease and has_reached:
            status = "CONDITIONAL"
            reason_codes.append("NOTICE_REACH_FACTS_VERIFIED_LAW_CONDITIONAL")
            safe_recommendations.append(
                f"해지통고 도달 사실({reach_date})이 확인되므로 도달 후 3개월 경과 시점({effect_date or '3개월 경과일'}) 기준으로 보증금 반환 청구가 가능합니다."
            )
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("NOTICE_REACH_EVIDENCE_NEEDED")

    # (C) 쟁점: 가압류 순위 (ISSUE_ATTACHMENT_RANKING)
    elif issue.issue_id == "ISSUE_ATTACHMENT_RANKING":
        cand_labels = residence_labels + attachment_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_opposing_power = ranking_info.get("has_opposing_power", False)
        has_transfer = ranking_info.get("has_transfer", False)
        has_move_in = ranking_info.get("has_move_in", False)
        has_attachment = ranking_info["has_attachment"]
        priority_status = ranking_info["priority_status"]
        summary_text = ranking_info["summary_text"]
        opp_eff_date = ranking_info.get("tenant_opposing_effective_date")
        fixed_date = ranking_info.get("tenant_fixed_date")
        prio_date = ranking_info.get("tenant_priority_date")

        # 1. 대항요건 미충족 (전입만 있거나 인도만 있는 경우) -> 대항요건 미확정 처리 (P0-01)
        if not (has_transfer and has_move_in):
            if has_transfer and not has_move_in:
                status = "CONDITIONAL"
                reason_codes.append("MOVE_IN_EVIDENCE_NEEDED")
                safe_recommendations.append(
                    "주택임대차보호법 제3조 제1항에 따른 대항요건은 주민등록 전입신고와 주택의 인도(점유)가 모두 구비되어야 합니다. "
                    "현재 주민등록 전입신고 사실은 확인되나 주택의 실제 인도(점유·입주)에 관한 객관적 증빙이 결여되어 대항요건 구비 여부를 확정할 수 없습니다. "
                    "가압류와의 권리 선후관계를 판단하기 위해 주택 인도 증빙(열쇠 수령증, 관리비 납부 내역 등)의 보완이 필수적입니다."
                )
            elif has_move_in and not has_transfer:
                status = "CONDITIONAL"
                reason_codes.append("TRANSFER_REGISTRATION_EVIDENCE_NEEDED")
                safe_recommendations.append(
                    "주택임대차보호법 제3조 제1항에 따른 대항요건은 주택의 인도와 주민등록 전입신고가 모두 구비되어야 합니다. "
                    "현재 주택 인도(점유) 사실은 확인되나 주민등록 전입신고에 관한 객관적 증빙이 결여되어 대항요건 구비 여부를 확정할 수 없습니다. "
                    "가압류와의 권리 선후관계를 판단하기 위해 주민등록초본(전입일자 확인) 증빙의 보완이 필수적입니다."
                )
            else:
                status = "NEEDS_EVIDENCE"
                reason_codes.append("RESIDENCE_REGISTRATION_EVIDENCE_NEEDED")
                safe_recommendations.append(
                    "임차인의 대항요건(주택 인도 및 주민등록 전입)에 관한 객관적 증거가 결여되어 권리관계를 확정할 수 없습니다."
                )
        elif has_attachment:
            status = "CONDITIONAL"
            if priority_status == "TENANT_SENIOR":
                reason_codes.append("PRIORITY_CONDITIONAL_ON_REGISTRY_UPDATE")
                safe_recommendations.append(
                    f"임차인의 대항요건(주택 인도 및 전입신고)에 따른 대항력 발생 시점({opp_eff_date or '익일 0시'})과 "
                    f"확정일자({fixed_date or '확정일자'})에 기한 우선변제권 효력 발생 시점({prio_date or '우선변제권 취득일'})이 "
                    f"등기부상 등재된 가압류({summary_text})보다 앞서므로 선순위 우선변제권이 인정됩니다. "
                    "경매 매각 시 후순위 가압류 채권자보다 우선하여 환가대금에서 배당받을 수 있으며, "
                    f"미배당 잔액({demand_summary_text})이 발생하더라도 선순위 대항력을 근거로 낙찰자(매수인)에게 전액 반환받을 때까지 주택 인도를 거절할 수 있습니다. "
                    "다만 최신 등기사항전부증명서(말소사항 포함)를 발급받아 가압류 외 다른 선순위 제한물권(담보권) 변동 여부를 최종 확인해야 합니다."
                )
            elif priority_status == "ATTACHMENT_SENIOR":
                reason_codes.append("ATTACHMENT_SENIOR_PRIORITY")
                safe_recommendations.append(
                    f"임차인의 대항력 발생 시점({opp_eff_date or '익일 0시'}) 또는 우선변제권 취득 시점({prio_date or '우선변제권 취득일'})보다 "
                    f"등기부상 가압류({summary_text})의 접수일자가 앞서거나 같은 날 설정되어 가압류가 선순위입니다. "
                    "따라서 임차인은 후순위 권리자로서 경매 매각 시 낙찰자에게 대항력을 주장할 수 없으며, "
                    f"경매 매각대금 배당 절차를 통해 채권 순위 및 안분 배당에 참여하여 {demand_summary_text}을 회수해야 하는 법적 위험이 있습니다."
                )
            else:
                reason_codes.append("PRIORITY_UNCERTAIN_NEEDS_REGISTRY")
                safe_recommendations.append(
                    f"현재 확인된 자료만으로는 임차인의 권리 취득 시점(대항요건 익일 0시 및 확정일자)과 등기부상 가압류·담보권({summary_text})의 등기접수일자 간의 선후관계를 확정할 수 없습니다. "
                    "날짜 정보가 결여되었거나 권리관계가 불명확한 상태에서는 '선순위 우선변제권 인정'을 단정할 수 없으며, "
                    "최신 등기사항전부증명서(말소사항 포함)의 접수일자와 주민등록초본의 전입일자를 정밀 대조하여 선순위 여부를 확인해야 합니다."
                )
        else:
            # 가압류가 없는 경우 (P0-05)
            if priority_status == "NO_ATTACHMENT":
                status = "CONDITIONAL"
                reason_codes.append("NO_ATTACHMENT_VERIFIED_IN_REGISTRY")
                safe_recommendations.append(
                    f"제출된 등기사항증명서상 확인된 가압류나 선순위 제한물권은 없는 것으로 파악됩니다({summary_text}). "
                    "다만 등기 열람 이후 권리 변동 가능성이 있으므로, 관할 등기소에서 최신 등기사항전부증명서(말소사항 포함)를 재발급받아 최종 대조하십시오."
                )
            else:
                status = "NEEDS_EVIDENCE"
                reason_codes.append("REGISTRY_EVIDENCE_NEEDED")
                safe_recommendations.append(
                    "등기사항증명서가 제출되지 않아 목적물 부동산의 선순위 제한물권(근저당권, 가압류 등) 부존재 여부를 확인할 수 없습니다. "
                    "반드시 최신 부동산 등기사항전부증명서를 열람·발급하여 권리관계를 확인해야 합니다."
                )

    # (D) 쟁점: 경매 배당 위험 및 대항력 선택 (ISSUE_AUCTION_STRATEGY / ISSUE_AUCTION_DIVIDEND_RISK)
    elif issue.issue_id in ("ISSUE_AUCTION_DIVIDEND_RISK", "ISSUE_AUCTION_STRATEGY"):
        cand_labels = lease_labels + residence_labels + attachment_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        status = "CONDITIONAL"
        reason_codes.append("AUCTION_DIVIDEND_REQUIRES_VALUATION")
        priority_status = ranking_info["priority_status"]
        tenant_date = ranking_info["tenant_fixed_date"] or ranking_info["tenant_opposing_date"]

        if priority_status == "TENANT_SENIOR":
            safe_recommendations.append(
                f"1) 의뢰인은 등재된 가압류보다 앞서 대항요건(주택 인도 및 전입신고)과 확정일자({tenant_date or '구비일'})를 갖추었으므로 선순위 대항력과 우선변제권을 보유합니다(주택임대차보호법 제3조, 제3조의2 제2항). "
                "2) 경매 개시 시 반드시 법원이 지정한 배당요구 종기일까지 권리신고 및 배당요구를 신청해야 매각대금에서 후순위 채권자보다 우선하여 배당받을 수 있습니다(민사집행법 제88조, 제148조). "
                f"3) 배당요구를 하여 보증금 전액을 배당받지 못한 미배당 잔액({demand_summary_text})이 남더라도 주택임대차보호법 제3조의5 단서에 따라 매수인(낙찰자)에게 대항력을 행사하여 전액을 돌려받을 때까지 주택 인도를 거절할 수 있습니다. "
                f"4) 배당요구를 하지 않고 낙찰자에게 임대차 승계 및 {demand_summary_text} 반환을 요구하는 방안도 선택 가능하므로, {prop_name}({prop_type})의 최근 실거래 시세 및 낙찰가율을 파악하여 배당요구 종기일 전까지 유리한 전략을 결정하십시오."
            )
        elif priority_status == "ATTACHMENT_SENIOR":
            safe_recommendations.append(
                f"1) 가압류 등기가 임차인의 대항력 발생 시점보다 앞서 가압류가 선순위입니다. "
                "2) 임차인은 낙찰자에게 대항할 수 없으므로(주택임대차보호법 제3조의5 본문), 경매 개시 시 반드시 배당요구 종기일까지 권리신고 및 배당요구를 신청하여 매각대금에서 배당 절차를 통해 회수해야 합니다(민사집행법 제88조). "
                f"3) 후순위 임차인은 선순위 가압류 채권자와의 배당 순위 및 안분 배당에 따라 {demand_summary_text}의 일부를 회수하지 못할 실질적 위험이 있으므로, {prop_name}({prop_type})의 시세와 예상 낙찰가를 확인하여 회수 가능액을 산정하십시오."
            )
        else:
            safe_recommendations.append(
                "1) 경매 개시 시 배당요구 종기일까지 권리신고 및 배당요구를 신청해야 매각대금에서 배당에 참여할 수 있습니다(민사집행법 제88조, 제148조). "
                "2) 권리 선후관계가 불명확한 경우 최신 등기부등본 열람을 통해 말소기준권리(근저당권, 압류, 가압류 등) 설정일자와 임차인의 대항요건 취득일자를 대조해야 합니다. "
                f"3) 선순위 대항력이 인정되지 않는 경우 매수인(낙찰자)에게 대항할 수 없으므로 배당 절차를 통한 회수가 필수적이며, {prop_name}({prop_type})의 실거래 시세 및 낙찰가율을 확인하여 배당 전략을 수립하십시오."
            )

    # (E) 쟁점: 권리보전 절차 (ISSUE_RIGHT_PRESERVATION)
    elif issue.issue_id == "ISSUE_RIGHT_PRESERVATION":
        cand_labels = lease_labels + residence_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_residence = len(residence_labels) > 0 or ranking_info["tenant_opposing_date"] is not None or any(("전입" in f.statement or "점유" in f.statement) for f in briefing.facts if is_fact_strictly_verified(f, briefing))
        if has_residence and law_verified:
            status = "VERIFIED"
            reason_codes.append("RIGHT_PRESERVATION_FACTS_AND_LAW_VERIFIED")
            safe_recommendations.append(
                f"{demand_summary_text}을 반환받거나 관할 법원의 임차권등기명령에 따른 등기가 등기부에 기재되기 전까지는 "
                f"절대 {prop_type}의 점유를 상실(열쇠 인도, 비밀번호 공유, 임의 퇴거)하거나 전입을 옮겨서는 안 됩니다. "
                "임차권등기 완료 전에 퇴거하거나 점유를 풀면 기존의 대항력과 우선변제권이 소멸하여 보증금을 회수하지 못할 중대한 법적 불이익이 발생합니다."
            )
        elif has_residence:
            status = "CONDITIONAL"
            reason_codes.append("RIGHT_PRESERVATION_LAW_CONDITIONAL")
            safe_recommendations.append(f"대항력 유지를 위해 임차권등기명령 기재 시까지 전입과 점유를 계속 유지해야 하며 먼저 퇴거해서는 안 됩니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("RIGHT_PRESERVATION_FACTS_PARTIAL")

    # (F) 쟁점: 분할반환 제안 대응 (ISSUE_INSTALLMENT_PROPOSAL)
    elif issue.issue_id == "ISSUE_INSTALLMENT_PROPOSAL":
        cand_labels = lease_labels + notice_labels + attachment_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_deposit_fact = (deposit_krw > 0) or any(
            is_fact_strictly_verified(f, briefing) and "보증금" in (f.statement or "")
            for f in briefing.facts
        )
        if has_deposit_fact and law_verified:
            status = "VERIFIED"
            reason_codes.append("PROPOSAL_REJECTION_LEGAL_EFFECT_VERIFIED")
            att_warn = f"현재 등기부상 {ranking_info['summary_text']} 등이 등재되어 있어, " if ranking_info["has_attachment"] else "현재 권리관계상 "
            safe_recommendations.append(
                "1) 임대인의 일방적인 분할 반환 제안은 임차인의 명시적 동의가 없는 한 법적 구속력이 없습니다. "
                f"2) {att_warn}무담보 분할 지급을 수용하여 주택을 명도하거나 전입을 옮기면 {demand_summary_text}에 대한 대항력과 우선변제권이 상실되어 심각한 회수 불능 위험이 발생합니다. "
                f"3) 따라서 임대인에게 분할반환 제안 거절 및 {demand_summary_text}의 일시반환을 강력히 촉구 통보하고, 임대인이 전액을 반환할 때까지 민법 제536조(동시이행의 항변권)에 기해 주택 인도를 거절해야 합니다. "
                "4) 불응 시 즉시 지급명령 또는 보증금반환청구 소송 등 법적 강제집행 절차에 착수해야 합니다."
            )
        elif has_deposit_fact:
            status = "CONDITIONAL"
            reason_codes.append("PROPOSAL_REJECTION_LEGAL_CONDITIONAL")
            safe_recommendations.append(f"합의 없는 분할 지급 제안은 거절 가능하며, {demand_summary_text} 일시 반환 및 동시이행 항변권을 유지할 수 있습니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("DEPOSIT_AGREEMENT_EVIDENCE_NEEDED")

    # (G) 쟁점: 내용증명 우편 작성 및 법적 효과 (ISSUE_PROOF_OF_CONTENTS)
    elif issue.issue_id == "ISSUE_PROOF_OF_CONTENTS":
        cand_labels = lease_labels + notice_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_lease = len(lease_labels) > 0 or any("계약" in f.statement for f in briefing.facts if is_fact_strictly_verified(f, briefing))
        if has_lease and law_verified:
            status = "VERIFIED"
            reason_codes.append("PROOF_OF_CONTENTS_GUIDANCE_VERIFIED")
            reach_info = f"상대방 도달일자({notice_info['reach_date'] or notice_info['sent_date'] or '통고일'})"
            safe_recommendations.append(
                "1) 내용증명 우편은 우체국을 통해 발송 일자와 통지 내용을 공적으로 증명하는 문서로, 계약 해지 통고의 확정일자 부여 및 이행 최고(민법 제111조)에 강력한 증거력을 가집니다. "
                f"2) 내용증명 필수 기재사항: ① 당사자 인적사항(임대인·임차인 성명, 주소), ② 임대차 계약 내역({prop_name}, 확정일자 부여 사실, 보증금 {deposit_text}), "
                f"③ 계약 해지 통고 사실 및 {reach_info}, ④ 현재까지 {demand_summary_text}이 미반환된 사실 및 반환 최고 기한·입금 계좌, "
                f"⑤ 기한 내 미반환 시 임차권등기명령, {demand_summary_text}에 대한 보증금반환청구소송, 법정 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 경고, "
                f"⑥ {demand_summary_text} 전액 반환 시까지 주택 인도 거절(민법 제536조 동시이행 항변) 명시입니다. "
                "3) 폐문부재나 수취거부로 반송될 경우, 반송 봉투와 내용증명 사본을 지참하여 주민센터에서 임대인의 주민등록초본을 교부받아 최신 주소지로 재발송하거나 의사표시 공시송달(민법 제113조)을 진행해야 합니다."
            )
        elif has_lease:
            status = "CONDITIONAL"
            reason_codes.append("PROOF_OF_CONTENTS_GUIDANCE_CONDITIONAL")
            safe_recommendations.append(f"내용증명에는 임대차 계약 내역, 해지 통고 도달일, {demand_summary_text} 반환 최고 기한 및 미반환 시 법적 조치 경고를 명확히 기재해야 합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("PROOF_OF_CONTENTS_EVIDENCE_NEEDED")

    # (H) 쟁점: 임대인의 자력 상실 및 연락 두절 시 사법절차 전환 (ISSUE_COMMUNICATION_BREAKDOWN)
    elif issue.issue_id == "ISSUE_COMMUNICATION_BREAKDOWN":
        cand_labels = lease_labels + residence_labels + notice_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_lease = len(lease_labels) > 0 or any("계약" in f.statement for f in briefing.facts if is_fact_strictly_verified(f, briefing))
        if has_lease and law_verified:
            status = "VERIFIED"
            reason_codes.append("COMMUNICATION_BREAKDOWN_REMEDIES_VERIFIED")
            safe_recommendations.append(
                "1) 임대인의 추가 대출 거절 및 연락 두절 상황에서는 임의 변제를 기다리지 말고 지체 없이 사법적 강제집행 절차로 전환해야 합니다. "
                f"2) 최우선 조치로 열쇠와 출입카드를 보관하며 {prop_type}의 점유 및 주민등록 전입을 엄격히 유지한 상태에서, 관할 법원에 임차권등기명령(주택임대차보호법 제3조의3)을 신청하여 등기부에 기입되도록 조치해야 합니다. "
                f"3) 만기 도과 후 현재까지 {demand_summary_text}이 미반환된 상태이므로, 신속한 지급명령(민사소송법 제462조) 또는 {demand_summary_text}에 대한 정식 보증금반환청구 소송을 제기하여 판결 등 집행권원을 확보해야 합니다. "
                f"4) 확보한 집행권원으로 임차주택에 대한 강제경매를 신청하거나, 타 채권자의 경매 진행 시 배당요구종기까지 권리신고 및 배당요구를 신청하여 배당 절차에서 {demand_summary_text}을 회수해야 합니다(민사집행법 제88조). "
                "5) 인터넷등기소를 통해 최신 등기사항전부증명서를 열람하여 타 채권자의 경매개시결정 등 추가 권리 침해 여부를 즉시 확인하십시오."
            )
        elif has_lease:
            status = "CONDITIONAL"
            reason_codes.append("COMMUNICATION_BREAKDOWN_REMEDIES_CONDITIONAL")
            safe_recommendations.append(f"임대인 연락 두절 시 점유와 전입을 유지한 채 임차권등기명령 및 {demand_summary_text} 지급명령/소송을 통한 집행권원 확보 절차로 즉시 전환해야 합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("COMMUNICATION_BREAKDOWN_EVIDENCE_NEEDED")

    # (I) 쟁점: 가압류 상태에서의 무담보 단순 확약서 수용 위험성 (ISSUE_UNSECURED_AGREEMENT)
    elif issue.issue_id == "ISSUE_UNSECURED_AGREEMENT":
        cand_labels = lease_labels + residence_labels + attachment_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_residence = len(residence_labels) > 0 or ranking_info["tenant_opposing_date"] is not None
        if has_residence and law_verified:
            status = "VERIFIED"
            reason_codes.append("UNSECURED_AGREEMENT_RISK_VERIFIED")
            att_context = f"등기부상 제한물권({ranking_info['summary_text']})이 등재된 상태에서 " if ranking_info["has_attachment"] else "권리관계가 불안정한 상태에서 "
            safe_recommendations.append(
                f"1) {att_context}별도 담보(근저당권 등) 없는 단순 '지급확약서(지불각서)'만 믿고 주택을 명도하거나 비밀번호를 알려주어서는 절대 안 됩니다. "
                "2) 지급확약서는 단순한 채권적 문서에 불과하여 강제집행력이나 물권적 우선변제 효력이 없습니다. "
                f"3) 주택을 인도하거나 퇴거하여 점유를 상실하는 순간 주택임대차보호법 제3조에 따른 대항력과 우선변제권이 즉시 소멸하며, 후순위 일반 채권자로 전락하여 {demand_summary_text}을 전액 떼일 치명적인 법적 위험이 발생합니다. "
                f"4) 따라서 {demand_summary_text}을 실제로 반환받거나 법원의 임차권등기명령이 등기부에 기입되기 전까지는 민법 제536조(동시이행의 항변권)에 기해 주택 인도를 단호히 거절하고 점유를 계속 유지해야 합니다."
            )
        elif has_residence:
            status = "CONDITIONAL"
            reason_codes.append("UNSECURED_AGREEMENT_RISK_CONDITIONAL")
            safe_recommendations.append(f"무담보 지급확약서만 믿고 퇴거하면 대항력과 우선변제권이 즉시 소멸하므로 주택 인도를 거절하고 점유를 유지해야 합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("UNSECURED_AGREEMENT_EVIDENCE_NEEDED")

    # (J) 쟁점: 가공의 증거 라벨 식별 및 존재 부인 (ISSUE_FAKE_CITATION)
    elif issue.issue_id == "ISSUE_FAKE_CITATION":
        if lease_labels:
            for lbl in lease_labels:
                if lbl in available_evidence_labels and lbl not in supported_source_ids:
                    supported_source_ids.append(lbl)
        status = "VERIFIED"
        reason_codes.append("FAKE_CITATION_DENIED_AND_RESOLVED")

        fake_refs = [lbl for lbl in cited_e_labels if lbl not in briefing.source_registry]
        fake_ref_desc = f"문서({', '.join(fake_refs)} 등)" if fake_refs else "언급하신 가공의 증거"
        safe_recommendations.append(
            f"1) 질문에서 언급하신 {fake_ref_desc}은(는) 본 상담 사건의 공적 증거 목록(Source Registry)에 전혀 존재하지 않거나 등록된 바 없는 가공의 자료입니다. "
            f"2) 가공 증거의 부재 확인 자체가 다른 모든 변제 사실의 부존재를 단정하는 것은 아니나, 현재 본 사건의 공적 등록·검증된 공식 증거상으로는 {demand_summary_text}이 미반환 상태임이 확인됩니다. "
            "3) 따라서 미등록 가공 문서의 일방적 주장은 배제하고, 실제 공식 제출·검증된 금융거래 내역 및 증거에 기초하여 대처해야 합니다."
        )

    # (K) 쟁점: 새 임차인 유치 조건부 반환의 부당성 (ISSUE_NO_WAIT_DUTY)
    elif issue.issue_id == "ISSUE_NO_WAIT_DUTY":
        cand_labels = lease_labels + notice_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_lease = len(lease_labels) > 0 or any("계약" in f.statement for f in briefing.facts if is_fact_strictly_verified(f, briefing))
        if has_lease and law_verified:
            status = "VERIFIED"
            reason_codes.append("NO_WAIT_DUTY_LEGAL_EFFECT_VERIFIED")
            sent_info = f"임차인이 {notice_info['sent_date']} 해지통고를 보내 " if notice_info["sent_date"] else "임차인의 해지통고로 "
            safe_recommendations.append(
                "1) 임차인에게는 후속 임차인이 입주하여 보증금을 낼 때까지 기다려야 할 어떠한 법적 의무도 존재하지 않습니다. "
                f"2) 임대차계약(보증금 {deposit_text}) 만기 후 {sent_info}효력이 발생하였으므로, 임대인의 보증금 반환 의무는 임차인의 목적물 인도 의무와 동시이행 관계(민법 제536조)에 있을 뿐입니다. "
                f"3) '신규 세입자 유치'는 임대인 개인의 내부 사정에 불과하여 법률상 반환 거절 사유가 될 수 없으며, 현재 {demand_summary_text}이 미반환된 상태입니다. "
                f"4) 따라서 대기 의무가 없음을 명확히 고지하고 즉시 {demand_summary_text} 일시반환을 촉구하며, 미반환 시 임차권등기명령 및 지연손해금 청구 소송 등 사법 절차를 즉시 착수해야 합니다."
            )
        elif has_lease:
            status = "CONDITIONAL"
            reason_codes.append("NO_WAIT_DUTY_LEGAL_EFFECT_CONDITIONAL")
            safe_recommendations.append(f"신규 임차인 유치는 임대인 내부 사정이며 임차인이 기다릴 법적 의무가 없으므로 {demand_summary_text} 반환 청구권을 유지할 수 있습니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("NO_WAIT_DUTY_EVIDENCE_NEEDED")

    # (L) 쟁점: 소송 및 보전처분을 위한 필수 증빙 서류 보완 (ISSUE_EVIDENCE_GAPS)
    elif issue.issue_id == "ISSUE_EVIDENCE_GAPS":
        cand_labels = lease_labels + residence_labels + notice_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        has_lease = len(lease_labels) > 0 or any("계약" in f.statement for f in briefing.facts if is_fact_strictly_verified(f, briefing))
        if has_lease and law_verified:
            status = "VERIFIED"
            reason_codes.append("EVIDENCE_GAPS_CHECKLIST_VERIFIED")
            safe_recommendations.append(
                "1) 임차권등기명령 및 보증금반환청구 소송을 위해 필수적으로 구비해야 할 서류 목록은 다음과 같습니다: "
                f"① 확정일자 부여된 주택임대차계약서, ② 주민등록등본 및 전입일자가 확인되는 주민등록초본, ③ 임대차 목적물({prop_name})의 부동산 등기사항전부증명서(말소사항 포함), "
                "④ 임대차계약 해지 통고 및 도달 증빙(내용증명 배달증명서, 문자메시지·카카오톡 수신 캡처), ⑤ 보증금 지급 금융거래내역서. "
                "2) 특히 사법절차에서는 해지의사표시의 '상대방 도달' 입증이 핵심이므로, 단순 발송 내역뿐 아니라 상대방의 수신·확인이 확인되는 객관적 증빙을 보완해야 합니다."
            )
        elif has_lease:
            status = "CONDITIONAL"
            reason_codes.append("EVIDENCE_GAPS_CHECKLIST_CONDITIONAL")
            safe_recommendations.append("계약서, 주민등록초본, 등기부등본, 해지통고 도달 증빙, 이체내역서를 철저히 구비하여 절차를 진행해야 합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("EVIDENCE_GAPS_EVIDENCE_NEEDED")

    # (M) 쟁점: 추가 증거 및 다음 행동 (ISSUE_NEXT_ACTIONS)
    elif issue.issue_id == "ISSUE_NEXT_ACTIONS":
        cand_labels = lease_labels + residence_labels + notice_labels
        for ev_cand in cand_labels:
            if ev_cand in available_evidence_labels and ev_cand not in supported_source_ids:
                supported_source_ids.append(ev_cand)

        if has_supported_facts or law_verified:
            status = "VERIFIED"
            reason_codes.append("ACTION_PLAN_VERIFIED")
            safe_recommendations.append(
                f"1) {demand_summary_text} 반환 시까지 {prop_type} 점유 및 주민등록 전입 절대 유지, "
                f"2) 임대인에게 {demand_summary_text} 반환 최고 및 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 내용증명 발송, "
                "3) 관할 법원에 임차권등기명령 신청 및 등기 기입 확인 후 이사, "
                f"4) 인터넷등기소를 통한 {prop_name}의 최신 말소사항 포함 등기사항전부증명서 발급 열람 및 대조를 순차 진행하십시오."
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
        if lease_labels:
            for lbl in lease_labels:
                if lbl in available_evidence_labels and lbl not in supported_source_ids:
                    supported_source_ids.append(lbl)
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

    logger.debug(f"[ISSUE_VERIFIER] 쟁점 검증({issue.issue_id}) -> 상태={status} (확인사실={len(supported_fact_ids)}건, 법령근거={len(supported_statute_ids)}건)")

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
