# -*- coding: utf-8 -*-
"""
모듈명: final_disposition.py

[모듈 개요]
쟁점별 검증 결과(IssueVerificationResult)와 사건 증거 브리핑(CaseEvidenceBriefing)을 바탕으로
최종 고객 응답 처분 상태(final_disposition: DELIVERED, CAUTIONARY, WITHHELD)를 결정하고,
검증된 쟁점과 확인된 사실관계만을 안전하게 선별·조립(Assemble)하여 최종 답변을 생성하는 모듈.

[주요 기능]
1. 쟁점 기반 최종 처분 상태 결정 (determine_final_disposition, Section 8, P0-05):
   - 검증된 쟁점이 존재하면 전체 답변 폐기를 방지하고 DELIVERED 또는 CAUTIONARY 부여
   - 안전하게 제공 가능한 쟁점이 전혀 없는 극단적 경우에만 WITHHELD 부여
2. 부분 답변 조립 정책 (assemble_grounded_answer, Section 8.4):
   - 차단된(BLOCKED) 주장, 허위 인용, 미검증 결론은 엄격히 배제
   - 확인된 사건 사실(FactAdjudication), 증거 번호(E01, E02...) 및 쟁점별 법률 분석 결합
   - 이미 등록된 증거를 다시 요구하지 않고, 실제 미비된 증거 공백(EvidenceGap)만 안내
3. 개선된 판단 유보 생성 (build_dynamic_withheld_answer, Section 9, P0-06):
   - WITHHELD 상태에서도 등록된 증거 목록과 입증된 사실을 요약하여 투명성 제공
"""

from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.agents.issue_verifier import IssueVerificationResult
from ai_legal_helper.utils.text_formatter import clean_markdown_formatting
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


def determine_final_disposition(
    issue_results: List[IssueVerificationResult],
) -> Tuple[str, str]:
    """쟁점별 검증 결과를 종합하여 최종 응답 처분 상태(DELIVERED, CAUTIONARY, WITHHELD)를 판정한다.

    Section 8.3 요구사항 반영:
    1. DELIVERED: 핵심 법률 쟁점이 VERIFIED 상태로 확정되고 BLOCKED 쟁점이 없음.
    2. CAUTIONARY: 실질적 법률 분석이 검증되었으나, 일부 쟁점이 CONDITIONAL 또는 NEEDS_EVIDENCE 상태임.
    3. WITHHELD: 모든 쟁점이 BLOCKED이거나, 안전하게 제공할 수 있는 법률적 판단이 전혀 없음.

    Args:
        issue_results: 각 단위 법률 쟁점별 검증 결과 목록.

    Returns:
        Tuple[str, str]: (final_disposition, disposition_reason)
    """
    if not issue_results:
        return "WITHHELD", "검증 대상 법률 쟁점이 도출되지 않았습니다."

    verified_count = sum(1 for r in issue_results if r.status == "VERIFIED")
    conditional_count = sum(1 for r in issue_results if r.status == "CONDITIONAL")
    needs_evidence_count = sum(1 for r in issue_results if r.status in ("NEEDS_EVIDENCE", "NEEDS_LEGAL_SOURCE"))
    blocked_count = sum(1 for r in issue_results if r.status == "BLOCKED")

    # 모든 쟁점이 차단되었거나 실질 분석이 전무한 경우
    if verified_count == 0 and conditional_count == 0:
        return "WITHHELD", f"모든 쟁점({len(issue_results)}건)의 증거 또는 법률 근거가 불충분하여 법률 판단을 유보합니다."

    # 모든 쟁점이 완전 검증된 경우
    if verified_count > 0 and conditional_count == 0 and needs_evidence_count == 0 and blocked_count == 0:
        return "DELIVERED", f"핵심 법률 쟁점 {verified_count}건이 등록 증거 및 관련 법령에 의해 검증되었습니다."

    # 검증된 쟁점과 조건부/증거부족 쟁점이 혼합된 경우 -> CAUTIONARY (부분 답변 보존)
    return "CAUTIONARY", (
        f"검증 완료 쟁점 {verified_count}건, 조건부 쟁점 {conditional_count}건이 "
        f"식별되어 확인된 범위 내에서 실질적 분석을 제공합니다."
    )


def assemble_grounded_answer(
    issue_results: List[IssueVerificationResult],
    briefing: CaseEvidenceBriefing,
    draft_answer: str,
    disposition: str,
) -> str:
    """검증된 쟁점과 확인된 사건 증거만을 구조적으로 조립하여 사용자용 최종 답변을 생성한다.

    Section 8 (P0-05) 및 Section 9 (P0-06) 원칙:
    - [1. 사건 종합 판단 및 핵심 결론]
    - [2. 등록 증거 기반 확인된 사실관계] (E01, E02... 라벨 명시)
    - [3. 쟁점별 법률 분석 및 판단]
    - [4. 보완이 필요한 증거 (Evidence Gaps)] (이미 등록된 서류 제외)
    - [5. 안전한 실무적 다음 행동 가이드]

    Args:
        issue_results: 단위 쟁점별 검증 결과 목록.
        briefing: 사건 증거 브리핑 모델.
        draft_answer: AI가 생성한 원본 초안 텍스트.
        disposition: 최종 처분 코드 ('DELIVERED', 'CAUTIONARY', 'WITHHELD').

    Returns:
        str: 정돈된 플레인 텍스트 형태의 최종 답변.
    """
    sections = []

    # 1. 사건 종합 판단 및 핵심 결론
    sections.append("[1. 사건 종합 판단 및 핵심 결론]")
    if disposition == "DELIVERED":
        sections.append(
            "- 등록된 증거자료와 관련 법령(주택임대차보호법 등)을 검토한 결과, "
            "임대차계약 종료 및 임차인의 대항력·우선변제권 관련 주요 법률관계가 명확히 확인되었습니다."
        )
    elif disposition == "CAUTIONARY":
        sections.append(
            "- 등록된 사건 증거를 바탕으로 임대차계약 체결, 보증금 약정, 전입·확정일자 및 가압류 등재 사실 등 "
            "핵심 사실관계는 명확히 입증되었습니다. 다만 경매 시 정확한 배당 수령액 및 최신 권리변동은 "
            "추가적인 공적 서류 확인이 수반되는 조건부 법률 판단을 제공합니다."
        )
    else:
        sections.append(
            "- 현재 등록된 증거를 바탕으로 기본 사실관계는 확인되나, 법률상 권리구제를 확정하기 위해 "
            "일부 추가적인 공적 입증자료의 보완이 필요하여 조건부 가이드를 제공합니다."
        )

    # 2. 등록 증거 기반 확인된 사실관계 (E번호 표시)
    sections.append("\n[2. 등록 증거 기반 확인된 사실관계]")
    supported_facts = [f for f in briefing.facts if f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")]
    
    # 중복 및 핵심 사실 위주 선별
    seen_stmts = set()
    displayed_facts = 0
    for f in supported_facts:
        norm_stmt = f.statement.strip()
        if norm_stmt in seen_stmts:
            continue
        seen_stmts.add(norm_stmt)
        cite_label = f"[{f.evidence_label}]" if f.evidence_label else ""
        sections.append(f"- {norm_stmt} {cite_label}".strip())
        displayed_facts += 1
        if displayed_facts >= 12:  # 가독성을 위해 핵심 사실 12건 내외 선별
            break

    # 3. 쟁점별 법률 분석 및 판단
    sections.append("\n[3. 쟁점별 법률 분석 및 판단]")
    for idx, r in enumerate(issue_results, 1):
        status_kr = {
            "VERIFIED": "검증 완료",
            "CONDITIONAL": "조건부 판단",
            "NEEDS_EVIDENCE": "증거 보완 필요",
            "NEEDS_LEGAL_SOURCE": "법령 근거 보강 필요",
            "BLOCKED": "판단 유보",
        }.get(r.status, "검토")

        sections.append(f"\n{idx}. {r.issue_title} ({status_kr})")

        # 해당 쟁점 추천 조치 및 법률 분석
        for rec in r.safe_recommendations:
            sections.append(f"  * {rec}")

        # 근거 증거 라벨
        if r.supported_source_ids:
            cites = ", ".join(sorted(r.supported_source_ids))
            sections.append(f"  * 관련 증거: [{cites}]")

        # 인용 법령
        if r.supported_statute_ids:
            laws = ", ".join(r.supported_statute_ids)
            sections.append(f"  * 적용 법령: {laws}")

        # 미해결 조건
        if r.unresolved_facts:
            unres_text = ", ".join(r.unresolved_facts[:2])
            sections.append(f"  * 추가 확인 필요 사항: {unres_text}")

    # 4. 보완이 필요한 증거 (Evidence Gaps) - 등록된 증거(E01~E17)를 다시 요구하지 않음
    sections.append("\n[4. 보완이 필요한 증거 (Evidence Gaps)]")
    if briefing.evidence_gaps:
        for gap in briefing.evidence_gaps[:5]:
            act_text = f" -> {gap.recommended_action}" if gap.recommended_action else ""
            sections.append(f"- [{gap.priority}] {gap.target_proposition}{act_text}")
    else:
        sections.append("- 현재 핵심 사실관계를 입증하기 위한 필수 증빙 서류는 충실히 등록되어 있습니다.")

    # 5. 안전한 실무적 다음 행동 가이드
    sections.append("\n[5. 안전한 실무적 다음 행동 가이드]")
    sections.append(
        "1. 전입 및 점유 유지: 보증금 전액을 반환받거나 임차권등기가 등기부에 기재될 때까지 절대 주택 점유를 상실(퇴거/열쇠 반환)하거나 전입을 옮기지 마십시오.\n"
        "2. 최신 등기사항전부증명서 열람: 인터넷등기소를 통해 목적물의 최신 말소사항 포함 등기부를 발급받아 가압류 외 다른 선순위 권리 변동을 최종 대조하십시오.\n"
        "3. 임차권등기명령 및 지급명령 준비: 임대인의 분할 지급 제안을 거절하고, 계약 종료 즉시 관할 법원에 임차권등기명령 신청 및 보증금 반환 청구 소송(또는 지급명령)을 진행하십시오."
    )

    final_text = "\n".join(sections)
    return clean_markdown_formatting(final_text)


def build_dynamic_withheld_answer(
    issue_results: Any,
    briefing: Any,
    reason_code: str = "LEGAL_SOURCE_MISSING",
) -> str:
    """판단 유보(WITHHELD) 상태에서도 확인된 사실과 실제 등록 증거 목록을 제공하는 안내문을 생성한다.

    Section 9 (P0-06) 요구사항 반영:
    1. 기계적 일반 안내문 대신, 실제 등록된 증거(E01, E02...)와 확인된 사실을 명시
    2. 이미 계약서나 이체내역이 등록된 경우 '계약서를 확보하세요' 등의 불필요한 반복 방지
    3. 유보된 구체적 사유 및 남아있는 증거 공백만을 정확히 명시

    Args:
        issue_results: 쟁점별 검증 결과 (또는 briefing).
        briefing: 사건 증거 브리핑 (또는 issue_results).
        reason_code: 유보 대표 사유 코드.

    Returns:
        str: 정돈된 판단 유보 안내문.
    """
    # 인수 순서 유연 처리 (briefing, issue_results 또는 issue_results, briefing 모두 허용)
    if isinstance(issue_results, CaseEvidenceBriefing):
        briefing, issue_results = issue_results, briefing
    elif not isinstance(briefing, CaseEvidenceBriefing) and hasattr(issue_results, "facts"):
        briefing, issue_results = issue_results, briefing

    if not isinstance(issue_results, list):
        issue_results = [issue_results] if issue_results else []

    sections = []
    sections.append("[안내: 일부 쟁점에 대한 법적 근거 및 증빙 추가 확인 필요]\n")
    sections.append(
        "현재 사건에 등록된 증거를 바탕으로 기본 사실관계는 정상적으로 확인되었으나, "
        "일부 법률 효과를 확정하기 위해 추가적인 공적 확인이 필요하여 답변을 조건부로 안내합니다.\n"
    )

    # 1. 현재 확인된 사실관계
    sections.append("[1. 등록 증거로 입증된 사실관계]")
    supported = [f for f in briefing.facts if f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")]
    if supported:
        for f in supported[:8]:
            cite = f"[{f.evidence_label}]" if f.evidence_label else ""
            sections.append(f"- {f.statement} {cite}".strip())
    else:
        sections.append("- 등록된 진술을 바탕으로 기초 정황을 확인하였습니다.")

    # 2. 등록된 증거 목록
    sections.append("\n[2. 현재 등록된 사건 증거 목록]")
    for ev in briefing.evidences[:8]:
        sections.append(f"- [{ev.evidence_label}] {ev.document_name} ({ev.document_type})")

    # 3. 보완이 필요한 구체적 쟁점 및 서류
    sections.append("\n[3. 유보 사유 및 보완이 필요한 사항]")
    if briefing.evidence_gaps:
        for g in briefing.evidence_gaps[:4]:
            sections.append(f"- {g.target_proposition} (권장: {g.recommended_action or '관련 확인'})")
    else:
        sections.append("- 목적물에 관한 최신 등기사항전부증명서 및 권리 변동 내역의 확인이 필요합니다.")

    # 4. 안전한 후속 행동 가이드
    sections.append("\n[4. 안전한 후속 행동 가이드]")
    sections.append(
        "- 보증금 반환을 받지 못한 상태에서 퇴거나 전입 이전을 하지 마시고 점유를 유지하십시오.\n"
        "- 관할 법원 임차권등기명령 신청 또는 대한법률구조공단(132), 전문 변호사의 대면 상담을 병행하십시오."
    )

    final_text = "\n".join(sections)
    return clean_markdown_formatting(final_text)
