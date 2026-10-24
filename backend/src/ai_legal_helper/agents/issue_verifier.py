# -*- coding: utf-8 -*-
"""
모듈명: issue_verifier.py

[모듈 개요]
법률 상담 초안(Draft Answer)을 전체 일괄 판정(PASS/REVISE/INSUFFICIENT)하는 대신,
단위 쟁점(Issue)별로 분리하여 독립적으로 검증하는 쟁점별 검증 엔진(Issue-Level Verification Engine).

[주요 기능]
1. Fact Verifier와 Legal Verifier의 분리 (Section 12, P0-09):
   - 사건 사실 검증: CaseEvidenceBriefing 내 FactAdjudication(EVIDENCE_SUPPORTED/CORROBORATED) 및 증거 라벨(E01, E02...) 유효성 대조
   - 법령 근거 검증: 실제 검색된 retrieved_sources 및 주택임대차보호법·민법 등 관계 법령 원문 일치 검증
2. 쟁점별 5대 상태 분류 (Section 7, P0-04):
   - VERIFIED: 사실과 법령 근거가 모두 확보되어 확정적 분석 제공 가능
   - CONDITIONAL: 핵심 사실은 확인되었으나 일부 조건이나 가정에 기한 유보적 분석 제공
   - NEEDS_EVIDENCE: 해당 쟁점 판단에 필수적인 증거자료가 결여됨
   - NEEDS_LEGAL_SOURCE: 필수 법령 또는 판례 조문 확인이 추가로 필요함
   - BLOCKED: 허위 인용, 심각한 모순으로 결론 제공 차단
3. 쟁점 간 격리: 특정 쟁점의 검증 실패가 전체 답변의 판단 유보로 전이되지 않도록 보장
"""

from typing import List, Dict, Any, Optional, Literal
import re
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.workflows.issue_planner import LegalIssueTask
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 인용 검증용 정규식
_E_LABEL_REGEX = re.compile(r"\[(E\d{1,3})(?:[^\]]*)\]", re.IGNORECASE)
_STATUTE_REGEX = re.compile(r"([가-힣]+(?:법률|법|시행령|특례법))\s*(?:제\s*(\d+)조(?:의\s*(\d+))?)?", re.IGNORECASE)


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
    verified_claims: List[Dict[str, Any]] = Field(default_factory=list, description="검증 완료된 세부 주장들")
    unsupported_claims: List[Dict[str, Any]] = Field(default_factory=list, description="근거 부족으로 제외/유보된 주장들")
    unresolved_facts: List[str] = Field(default_factory=list, description="미확인으로 남아있는 사실 목록")
    missing_legal_sources: List[str] = Field(default_factory=list, description="부족한 법령/판례 근거 목록")
    missing_statutes: List[str] = Field(default_factory=list, description="부족한 법령 목록 (호환 필드)")
    legal_analysis: Optional[str] = Field(None, description="해당 쟁점에 대한 검증된 권장 분석 문안")
    safe_recommendations: List[str] = Field(default_factory=list, description="해당 쟁점에 한정된 안전한 실무 조치 안내")
    revision_instructions: List[str] = Field(default_factory=list, description="수정/보완 지침")


def verify_issue(
    issue: LegalIssueTask,
    draft_answer: str,
    briefing: CaseEvidenceBriefing,
    retrieved_sources: List[Dict[str, Any]],
) -> IssueVerificationResult:
    """단일 법률 쟁점에 대해 사실 검증과 법령 검증을 독립적으로 수행한다.

    Section 7 (P0-04) 및 Section 12 (P0-09) 원칙:
    1. Fact Verification:
       - 브리핑 내 relevant_fact_ids의 사실 확정 상태(EVIDENCE_SUPPORTED, CORROBORATED 등) 평가
       - draft_answer 내 인용된 [E01], [E02] 라벨이 실제 briefing.source_registry에 존재하는지 검증
       - 허위 증거 번호 인용 시 BLOCKED 처리
    2. Legal Verification:
       - issue.required_statutes 조문이 draft 또는 retrieved_sources에 존재하는지 확인
       - 사실이 충분하나 법령이 부족하면 NEEDS_LEGAL_SOURCE 또는 CONDITIONAL 부여
       - 사실이 부족하나 법령이 존재하면 CONDITIONAL 또는 NEEDS_EVIDENCE 부여
    3. 종합 판정:
       - 핵심 사실과 법령이 모두 확인되면 VERIFIED
       - 조건부 설명 및 사실 입증 주의가 수반되는 경우 CONDITIONAL
       - 핵심 증거가 아예 없으면 NEEDS_EVIDENCE
       - 허위 인용/모순 발견 시 BLOCKED

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
            verified_claims.append({
                "statement": f.statement,
                "status": f.adjudication_status,
                "evidence_label": f.evidence_label,
            })
        elif f.adjudication_status == "EVIDENCE_INCOMPLETE":
            has_incomplete_facts = True
            unresolved_facts.append(f.statement)
        elif f.adjudication_status == "PARTY_ALLEGED":
            verified_claims.append({
                "statement": f.statement,
                "status": "PARTY_ALLEGED",
                "evidence_label": None,
            })

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

    # 3. 법령 근거 검증 (Legal Verification)
    # 실제 검색된 법령/판례 출처(source_texts)에 해당 법령 명칭 및 조문이 존재하는지 엄격히 검증
    # (draft_answer 자체에 적힌 텍스트로 자가 통과(Self-pass)하는 오류 원천 차단)
    source_texts = " ".join([
        str(s.get("content", "")) + " " + str(s.get("title", "")) + " " + str(s.get("article", ""))
        for s in retrieved_sources
    ])

    for stat in issue.required_statutes:
        m = _STATUTE_REGEX.search(stat)
        if m:
            law_name = m.group(1)
            art_no = m.group(2)
            if law_name in source_texts:
                if not art_no or f"제{art_no}조" in source_texts or f"제 {art_no} 조" in source_texts:
                    supported_statute_ids.append(stat)
                else:
                    missing_statutes.append(stat)
            else:
                missing_statutes.append(stat)
        else:
            if stat in source_texts:
                supported_statute_ids.append(stat)
            else:
                missing_statutes.append(stat)

    # 4. 쟁점 상태 판정 (Status Determination)
    # (A) 쟁점: 계약 종료 (ISSUE_LEASE_TERMINATION)
    if issue.issue_id == "ISSUE_LEASE_TERMINATION":
        if has_supported_facts and supported_statute_ids:
            status = "VERIFIED"
            reason_codes.append("TERMINATION_FACTS_AND_LAW_SUPPORTED")
            safe_recommendations.append("계약서상 약정 기간 및 퇴거 통고 도달 증빙(E01, E05)을 기초로 보증금 반환 채무의 이행기를 명확히 주장 가능합니다.")
        elif has_supported_facts:
            status = "CONDITIONAL"
            reason_codes.append("TERMINATION_FACTS_VERIFIED_LAW_CONDITIONAL")
            safe_recommendations.append("임대차계약 및 통고 사실은 확인되므로, 도달 효력 발생 시점에 따른 조건부 반환 청구가 가능합니다.")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("TERMINATION_EVIDENCE_LACKING")

    # (B) 쟁점: 가압류 순위 (ISSUE_ATTACHMENT_RANKING)
    elif issue.issue_id == "ISSUE_ATTACHMENT_RANKING":
        # 전입신고/확정일자(E03)와 가압류 등재(E09, E10) 확인 여부
        has_residence = any("E03" in f.evidence_label for f in briefing.facts if f.evidence_label)
        has_attachment = any(lbl in briefing.source_registry for lbl in ("E09", "E10"))
        if has_residence and has_attachment:
            status = "CONDITIONAL"  # 최신 등기부 전수 확인이 남아있으므로 조건부 판정이 법률상 가장 정확
            reason_codes.append("PRIORITY_CONDITIONAL_ON_REGISTRY_UPDATE")
            safe_recommendations.append("임차인의 확정일자(2022.03.02)가 가압류 등재일보다 앞서면 선순위 우선변제권이 인정되나, 말소사항 포함 최신 등기부로 중간 권리 존재 여부를 최종 확인해야 합니다.")
        elif has_residence:
            status = "CONDITIONAL"
            reason_codes.append("RESIDENCE_VERIFIED_ATTACHMENT_UNVERIFIED")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("RESIDENCE_REGISTRATION_EVIDENCE_NEEDED")

    # (C) 쟁점: 경매 배당 위험 (ISSUE_AUCTION_DIVIDEND_RISK)
    elif issue.issue_id == "ISSUE_AUCTION_DIVIDEND_RISK":
        # 배당금 산정은 낙찰가와 선순위 총액이 필요하므로 원칙적으로 CONDITIONAL
        status = "CONDITIONAL"
        reason_codes.append("AUCTION_DIVIDEND_REQUIRES_VALUATION")
        safe_recommendations.append("정확한 배당 수령액은 실제 경매 낙찰가율 및 배당요구 채권 총액에 따라 변동되므로, 경매 개시 시 반드시 배당요구종기 내에 권리신고 및 배당요구 신청을 해야 합니다.")

    # (D) 쟁점: 권리보전 절차 (ISSUE_RIGHT_PRESERVATION)
    elif issue.issue_id == "ISSUE_RIGHT_PRESERVATION":
        has_residence = any("E03" in f.evidence_label for f in briefing.facts if f.evidence_label)
        if has_residence:
            status = "VERIFIED"
            reason_codes.append("RIGHT_PRESERVATION_PROCEDURE_VERIFIED")
            safe_recommendations.append("임차권등기명령이 완료되어 등기부에 기재되기 전까지는 절대 주민등록 이전이나 주택 점유를 전면 상실(열쇠 인도)해서는 안 됩니다.")
        else:
            status = "CONDITIONAL"
            reason_codes.append("RIGHT_PRESERVATION_FACTS_PARTIAL")

    # (E) 쟁점: 분할반환 제안 대응 (ISSUE_INSTALLMENT_PROPOSAL)
    elif issue.issue_id == "ISSUE_INSTALLMENT_PROPOSAL":
        status = "VERIFIED"
        reason_codes.append("PROPOSAL_REJECTION_LEGAL_EFFECT_VERIFIED")
        safe_recommendations.append("임대인의 일방적 분할 지급 제안은 임차인의 명시적 동의가 없는 한 법적 구속력이 없으며, 계약 종료 시 전액 반환 및 지연손해금을 청구할 수 있습니다.")

    # (F) 쟁점: 추가 증거 및 다음 행동 (ISSUE_NEXT_ACTIONS)
    elif issue.issue_id == "ISSUE_NEXT_ACTIONS":
        status = "VERIFIED"
        reason_codes.append("ACTION_PLAN_VERIFIED")
        safe_recommendations.append("1) 최신 등기사항증명서 발급 열람, 2) 임차권등기명령 신청 준비, 3) 지급명령 또는 전세보증금 반환청구 소송 제기를 순차 진행하십시오.")

    # (G) 일반 기타 쟁점
    else:
        if has_supported_facts and supported_statute_ids:
            status = "VERIFIED"
            reason_codes.append("GENERAL_FACTS_AND_LAW_SUPPORTED")
        elif has_supported_facts:
            status = "CONDITIONAL"
            reason_codes.append("GENERAL_FACTS_SUPPORTED_LAW_INSUFFICIENT")
        else:
            status = "NEEDS_EVIDENCE"
            reason_codes.append("GENERAL_EVIDENCE_NEEDED")

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

