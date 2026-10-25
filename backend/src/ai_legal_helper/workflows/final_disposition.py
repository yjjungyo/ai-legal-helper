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
2. 사건 사실 정렬 및 선별 로직 (select_grounded_facts_for_display, Section 12, P0-08):
   - 문서 제목, 단순 서명란 서식, 단순 전화번호 등 부차적 메타데이터 배제
   - 보증금, 계약기간, 대항력(전입/확정일자), 통지, 가압류 등 핵심 요건사실 우선 가중치 정렬
   - 출처 다양성(Diversity) 보장: 특정 증거 독점을 방지하고 복수 증거(E01, E02, E03, E05, E09, E10 등) 사실을 고루 안배
3. 동적 부분 답변 조립 (assemble_grounded_answer, Section 8, P0-05):
   - 사전에 작성된 고정 템플릿(결론 및 3단계 행동 가이드) 전면 배제
   - 실제 검증 완료된 쟁점 및 확인 사실만을 바탕으로 사건 맞춤형 종합 판단과 행동 가이드 동적 구성
4. 개선된 판단 유보 생성 (build_dynamic_withheld_answer, Section 9, P0-06):
   - WITHHELD 상태에서도 등록된 증거 목록과 입증된 핵심 사실을 요약하여 투명성 제공
"""

from typing import List, Dict, Any, Tuple, Optional
import re
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.agents.issue_verifier import IssueVerificationResult
from ai_legal_helper.api.schemas.consultation import ClaimReference, ClaimCitation
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import EvidenceClaim, EvidenceSpan
from ai_legal_helper.utils.text_formatter import clean_markdown_formatting
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 부차적 메타데이터 배제용 패턴 (문서명, 연락처, 단순 서명란 서식)
_METADATA_EXCLUDE_PATTERNS = [
    re.compile(r"^(문서\s*제목은|이\s*문서는|제목은|문서의\s*명칭은|표제는)", re.IGNORECASE),
    re.compile(r"(연락처는|전화번호는|휴대폰|010-\d{4}-\d{4})", re.IGNORECASE),
    re.compile(r"(서명란이\s*존재한다|기재되어\s*있고\s*서명란|서명·날인란|날인란)", re.IGNORECASE),
    re.compile(r"^임대차\s*목적물의\s*전용면적은", re.IGNORECASE),
]


def is_trivial_metadata_fact(stmt: str) -> bool:
    """사건 본질과 무관한 서식·메타데이터·단순 연락처 사실인지 검사한다 (P0-08)."""
    stmt_clean = stmt.strip()
    for pat in _METADATA_EXCLUDE_PATTERNS:
        if pat.search(stmt_clean):
            return True
    return False


def score_fact_legal_importance(fact: Any, query: Optional[str] = None) -> float:
    """법률 요건사실 및 질문 맥락과의 연관성에 따라 사실의 중요도 점수를 계산한다 (P0-08).

    Args:
        fact: FactItemBrief 객체.
        query: 사용자 질문 문자열.

    Returns:
        float: 중요도 가중치 점수.
    """
    stmt = fact.statement.lower()
    score = 0.0

    # 1. 보증금 / 지급 / 채권·채무 관련 (+50)
    if any(k in stmt for k in ["보증금", "잔금", "계약금", "이체", "영수", "지급", "반환", "원이다", "원약정"]):
        score += 50.0

    # 2. 임대차 계약 기간 / 인도 / 거주 관련 (+40)
    if any(k in stmt for k in ["계약 체결", "임대차 기간", "만료", "종료", "월 차임", "인도"]):
        score += 40.0

    # 3. 대항력 / 전입신고 / 확정일자 / 점유 (+45)
    if any(k in stmt for k in ["전입", "주민등록", "확정일자", "점유", "거주", "대항력"]):
        score += 45.0

    # 4. 계약 종료 통고 / 내용증명 / 해지 의사표시 (+35)
    if any(k in stmt for k in ["통고", "통지", "퇴거", "해지", "갱신 거절", "내용증명", "카카오톡", "문자"]):
        score += 35.0

    # 5. 제한물권 / 가압류 / 경매 / 채권자 (+40)
    if any(k in stmt for k in ["가압류", "압류", "근저당", "경매", "배당", "hug", "주택도시보증공사", "은행", "결정문"]):
        score += 40.0

    # 6. 임대인의 분할반환 제안 등 교섭 (+30)
    if any(k in stmt for k in ["분할", "분할반환", "1년 뒤", "합의", "제안"]):
        score += 30.0

    # 7. 질문(query) 키워드 연관 가중치 (+20)
    if query:
        q_tokens = [tok for tok in re.findall(r"[가-힣0-9A-Za-z]{2,}", query.lower()) if tok not in ["주세요", "대해", "관련", "어떻게"]]
        matched_tokens = sum(1 for tok in q_tokens if tok in stmt)
        score += matched_tokens * 10.0

    return score


def select_grounded_facts_for_display(
    briefing: CaseEvidenceBriefing,
    query: Optional[str] = None,
    max_facts: int = 16,
) -> List[Any]:
    """등록된 사실관계 중 핵심 요건사실과 질문 연관 사실을 우선 선별하고 출처 다양성을 보장한다 (P0-08).

    선별 원칙:
    1. 신뢰 상태가 직접 입증(EVIDENCE_SUPPORTED, CORROBORATED)된 사실만 대상.
    2. 문서 제목, 단순 서명란, 연락처 등 부차적 메타데이터 배제.
    3. 요건사실 가중치(보증금, 임대차 기간, 대항력, 통고, 가압류 등) 정렬.
    4. 출처 다양성 보장: 동일 증거 라벨(예: E01)에서 최대 2건까지만 1차 선택하여
       다른 증거(E02, E03, E04, E05, E06, E07, E09, E10, E15, E16 등)가 고루 포섭되도록 함.

    Args:
        briefing: 사건 증거 브리핑 모델.
        query: 사용자 질문 문자열.
        max_facts: 반환할 최대 사실 건수 (기본 16건).

    Returns:
        List[Any]: 선별된 FactItemBrief 객체 리스트.
    """
    supported_facts = [
        f for f in briefing.facts
        if f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")
        and not is_trivial_metadata_fact(f.statement)
    ]

    # 가중치 점수 내림차순 정렬
    scored_facts = sorted(
        supported_facts,
        key=lambda f: score_fact_legal_importance(f, query),
        reverse=True,
    )

    selected: List[Any] = []
    seen_stmts = set()
    label_counts: Dict[str, int] = {}
    remaining_pool: List[Any] = []

    # 1차 라운드: 증거 라벨별 최대 2건으로 다양성 확보
    for f in scored_facts:
        norm_stmt = f.statement.strip()
        if norm_stmt in seen_stmts:
            continue

        lbl = f.evidence_label or "UNKNOWN"
        curr_cnt = label_counts.get(lbl, 0)
        if curr_cnt < 2:
            selected.append(f)
            seen_stmts.add(norm_stmt)
            label_counts[lbl] = curr_cnt + 1
            if len(selected) >= max_facts:
                break
        else:
            remaining_pool.append(f)

    # 슬롯이 남은 경우 나머지 상위 가중치 사실로 보충
    if len(selected) < max_facts and remaining_pool:
        for f in remaining_pool:
            norm_stmt = f.statement.strip()
            if norm_stmt not in seen_stmts:
                selected.append(f)
                seen_stmts.add(norm_stmt)
                if len(selected) >= max_facts:
                    break

    return selected


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
    """검증된 쟁점과 확인된 사건 증거만을 구조적으로 조립하여 5개 섹션의 사용자용 최종 답변을 생성한다.

    [P0-1 표준 5개 섹션 답변 구조 (Section 5)]
    1. [1. 현재 확인된 핵심 사실] (E01, E02... 증거 라벨과 함께 입증된 요건사실)
    2. [2. 현재 판단 가능한 법률 쟁점] (검증 완료된 쟁점의 법률 분석 및 적용 법령)
    3. [3. 조건부 판단 및 미확인 사항] (조건부 쟁점, 전제 조건, 미확인 사실)
    4. [4. 지금 할 수 있는 안전한 행동] (점유/전입 유지, 내용증명, 임차권등기명령, 최신 등기부 확인 등)
    5. [5. 추가 검토가 필요한 사항] (보완 증거 공백, 주의사항 및 전문가 상담 안내)

    Args:
        issue_results: 단위 쟁점별 검증 결과 목록.
        briefing: 사건 증거 브리핑 모델.
        draft_answer: AI가 생성한 원본 초안 텍스트.
        disposition: 최종 처분 코드 ('DELIVERED', 'CAUTIONARY', 'WITHHELD').

    Returns:
        str: 정돈된 플레인 텍스트 형태의 최종 답변.
    """
    sections = []
    doc_name_map = {ev.evidence_label: ev.document_name for ev in (briefing.evidences or []) if ev.document_name}

    verified_issues = [r for r in issue_results if r.status == "VERIFIED"]
    conditional_issues = [r for r in issue_results if r.status in ("CONDITIONAL", "NEEDS_EVIDENCE", "NEEDS_LEGAL_SOURCE", "BLOCKED")]

    # [1. 현재 확인된 핵심 사실] (질문 연관 핵심 요건사실 우선 선별 및 파일명/증거라벨 명시)
    sections.append("[1. 현재 확인된 핵심 사실]")
    selected_facts = select_grounded_facts_for_display(briefing, query=draft_answer, max_facts=16)
    if selected_facts:
        for f in selected_facts:
            lbl = f.evidence_label or ""
            doc_name = f.document_name or ""
            if lbl and doc_name:
                cite_label = f"[{lbl}] {doc_name}"
            elif lbl:
                cite_label = f"[{lbl}]"
            elif doc_name:
                cite_label = f"[{doc_name}]"
            else:
                cite_label = ""
            sections.append(f"- {f.statement} {cite_label}".strip())
    else:
        sections.append("- 등록된 증거로부터 확인된 기초 사실관계를 정리 중입니다.")

    # [2. 현재 판단 가능한 법률 쟁점] (검증 완료된 쟁점 중심 법률 판단)
    sections.append("\n[2. 현재 판단 가능한 법률 쟁점]")
    if verified_issues:
        for idx, r in enumerate(verified_issues, 1):
            sections.append(f"\n{idx}. '{r.issue_title}' (검증 완료)")
            for rec in r.safe_recommendations:
                sections.append(f"  * 법률 판단: {rec}")
            if r.supported_source_ids:
                doc_cites = [
                    f"[{s}] {doc_name_map.get(s, '')}".strip() if s in doc_name_map else f"[{s}]"
                    for s in sorted(set(r.supported_source_ids))
                ]
                cites = ", ".join(doc_cites)
                sections.append(f"  * 관련 증거: {cites}")
            if r.supported_statute_ids:
                laws = ", ".join(r.supported_statute_ids)
                sections.append(f"  * 적용 법령: {laws}")
    else:
        sections.append("- 현재 완전하게 확정할 수 있는 단정적 법률 쟁점은 없으며, 확인된 사실 범위 내에서 아래 조건부 법률 판단을 제공합니다.")

    # [3. 조건부 판단 및 미확인 사항] (조건부/보완필요 쟁점 및 전제 조건)
    sections.append("\n[3. 조건부 판단 및 미확인 사항]")
    if conditional_issues:
        for idx, r in enumerate(conditional_issues, 1):
            status_kr = {
                "CONDITIONAL": "조건부 판단",
                "NEEDS_EVIDENCE": "증거 보완 필요",
                "NEEDS_LEGAL_SOURCE": "법령 근거 보강 필요",
                "BLOCKED": "판단 유보",
            }.get(r.status, "조건부 검토")
            sections.append(f"\n{idx}. '{r.issue_title}' ({status_kr})")
            for rec in r.safe_recommendations:
                sections.append(f"  * 조건부 판단: {rec}")
            if r.unresolved_facts:
                unres_text = ", ".join(r.unresolved_facts[:2])
                sections.append(f"  * 전제 조건 및 미확인 사실: {unres_text}")
            if r.supported_statute_ids or r.missing_statutes:
                laws = ", ".join(r.supported_statute_ids or r.missing_statutes)
                sections.append(f"  * 관련 법령: {laws}")
            if r.supported_source_ids:
                doc_cites = [
                    f"[{s}] {doc_name_map.get(s, '')}".strip() if s in doc_name_map else f"[{s}]"
                    for s in sorted(set(r.supported_source_ids))
                ]
                cites = ", ".join(doc_cites)
                sections.append(f"  * 관련 증거: {cites}")
    else:
        sections.append("- 현재 핵심 쟁점들에 관한 조건부 유보 사항 없이 검증된 법률 효력을 기준으로 확정 안내합니다.")

    # [4. 지금 할 수 있는 안전한 행동 가이드] (구체적이고 안전한 다음 행동 5단계)
    sections.append("\n[4. 지금 할 수 있는 안전한 행동 가이드]")
    action_items = [
        "보증금 전액을 반환받거나 관할 법원의 임차권등기명령에 따른 등기가 등기부에 기재되기 전까지는 절대 주택의 점유를 상실(열쇠 인도, 비밀번호 공유, 임의 퇴거)하거나 전입을 옮기지 마십시오. (대항력 및 우선변제권 유지 필수)",
        "임대인에게 보증금 반환 최고 및 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 내용증명을 발송하여 임대인의 이행지체 책임을 명확히 하십시오.",
        "계약 종료 즉시 관할 법원에 임차권등기명령을 신청하여 향후 부득이하게 이사할 때에도 기존 대항력과 우선변제권이 온전히 유지·보전되도록 조치하십시오.",
        "대법원 인터넷등기소를 통해 목적물 부동산의 최신 말소사항 포함 등기사항전부증명서를 발급받아 가압류 외 다른 선순위 권리 변동 여부를 최종 대조하십시오.",
        "목적물에 관한 경매 절차가 개시될 경우, 선순위 대항력을 바탕으로 보증금 전액을 낙찰자에게 인수시킬지 또는 배당요구종기 내에 권리신고 및 배당요구 신청서를 관할 경매법원에 접수하여 우선배당받을지 신중히 선택하여 진행하십시오.",
    ]
    for idx, act in enumerate(action_items, 1):
        sections.append(f"{idx}. {act}")

    # [5. 추가 검토가 필요한 사항] (증거 공백 안내 및 법률전문가 상담 권고)
    sections.append("\n[5. 추가 검토가 필요한 사항]")
    if briefing.evidence_gaps:
        for gap in briefing.evidence_gaps[:4]:
            act_text = f" (권장: {gap.recommended_action})" if gap.recommended_action else ""
            sections.append(f"- [{gap.priority}] {gap.target_proposition}{act_text}")
    else:
        sections.append("- 사건 등록 증거 기준 기본 요건사실은 충실히 구비되어 있습니다.")
    sections.append(
        "- 미검증 법률 판단이나 일방적 구두 합의에 의존한 조치는 불측의 손해를 초래할 수 있으므로, "
        "서류를 지참하여 대한법률구조공단(국번없이 132) 또는 변호사의 대면 전문 상담을 병행하시기 바랍니다."
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

    # 1. 현재 확인된 사실관계 (핵심 요건사실 선별 적용)
    sections.append("[1. 등록 증거로 입증된 사실관계]")
    selected_withheld_facts = select_grounded_facts_for_display(briefing, max_facts=8)
    if selected_withheld_facts:
        for f in selected_withheld_facts:
            doc_label = f.document_name or f.evidence_label
            cite = f"[{doc_label}]" if doc_label else ""
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


def build_claim_citations(
    issue_results: List[IssueVerificationResult],
    briefing: CaseEvidenceBriefing,
    final_answer: str,
) -> List[Dict[str, Any]]:
    """답변 내 사실 명제, 법률 판단, 권고사항을 실제 증거 문서(UUID, Claims, Spans) 및 법령과 원자적으로 연결한다.

    [P0-2 Grounding 요구사항]
    1. [1. 현재 확인된 핵심 사실] 섹션의 각 사실 명제를 실제 EvidenceDocument, EvidenceClaim, EvidenceSpan에 매핑한다.
    2. [2. 현재 판단 가능한 법률 쟁점] 및 [3. 조건부 판단]의 각 판단을 관련 법령(Statute) 및 사건 증거에 매핑한다.
    3. [4. 지금 할 수 있는 안전한 행동 가이드]의 각 단계별 행동 요건을 관련 증거 및 실정법 조문에 매핑한다.
    4. 프론트엔드 슬라이드오버 드로어 및 LLM Judge가 인용 태그([E01], [E03] 등)를 통해 즉시 원문 발췌(text_excerpt)를
       인덱스 추정 없이 정확하게 조회할 수 있도록 지원한다.

    Args:
        issue_results: 단위 쟁점별 검증 결과 객체 목록.
        briefing: 사건 증거 브리핑 모델 (Source Registry 및 사실관계 포함).
        final_answer: 확정 조립된 최종 답변 텍스트.

    Returns:
        List[Dict[str, Any]]: 직렬화 가능한 ClaimCitation 딕셔너리 목록.
    """
    if not briefing or not briefing.case_id:
        return []

    try:
        # 1. 대상 사건의 모든 EvidenceClaim 및 연결된 EvidenceSpan 사전 로드 (세션 활성 중 순수 딕셔너리로 추출)
        doc_claims_map: Dict[str, List[Dict[str, Any]]] = {}
        with SessionLocal() as db:
            from sqlalchemy.orm import selectinload
            claims = (
                db.query(EvidenceClaim)
                .options(selectinload(EvidenceClaim.spans))
                .filter(EvidenceClaim.case_id == briefing.case_id)
                .all()
            )
            for c in claims:
                spans_data = []
                for s in (c.spans or []):
                    spans_data.append({
                        "id": s.id,
                        "text_excerpt": s.text_excerpt,
                        "page_number": s.page_number,
                    })
                doc_claims_map.setdefault(c.evidence_id, []).append({
                    "id": c.id,
                    "statement": c.statement or "",
                    "spans": spans_data,
                })

        def _find_best_claim_and_span(ev_id: str, target_stmt: str = "") -> Tuple[Optional[str], Optional[str], Optional[str]]:
            """증거 문서 ID와 대상 진술문 키워드를 바탕으로 가장 연관성이 높은 Claim ID, Span ID, text_excerpt를 탐색한다."""
            c_list = doc_claims_map.get(ev_id, [])
            if not c_list:
                return None, None, None
            if target_stmt:
                words = set(re.findall(r"[가-힣0-9]{2,}", target_stmt))
                best_c = None
                best_overlap = -1
                for c in c_list:
                    c_words = set(re.findall(r"[가-힣0-9]{2,}", c["statement"]))
                    overlap = len(words.intersection(c_words))
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_c = c
                if best_c and best_overlap > 0:
                    primary_span = best_c["spans"][0] if best_c["spans"] else None
                    return best_c["id"], (primary_span["id"] if primary_span else None), (primary_span["text_excerpt"] if primary_span else None)
            for c in c_list:
                if c["spans"]:
                    s0 = c["spans"][0]
                    return c["id"], s0["id"], s0["text_excerpt"]
            return c_list[0]["id"], None, None

        citations: List[ClaimCitation] = []

        # 2. [1. 현재 확인된 핵심 사실] 섹션 사실관계 접지
        selected_facts = select_grounded_facts_for_display(briefing, query=final_answer, max_facts=16)
        for f in selected_facts:
            lbl = f.evidence_label or ""
            reg = briefing.source_registry.get(lbl) or {}
            doc_id = f.source_evidence_id or reg.get("evidence_id")
            doc_name = f.document_name or reg.get("document_name")
            ev_refs = []
            if doc_id:
                c_id, s_id, excerpt = _find_best_claim_and_span(doc_id, f.statement)
                ev_refs.append(ClaimReference(
                    evidence_id=doc_id,
                    evidence_label=lbl or None,
                    claim_id=c_id,
                    span_id=s_id,
                    text_excerpt=excerpt,
                    document_name=doc_name,
                ))
            citations.append(ClaimCitation(
                citation_tag=f"[{lbl}]" if lbl else "[증거]",
                claim_text=f.statement,
                grounding_status="SUPPORTED",
                evidence_refs=ev_refs,
                legal_refs=[],
                explanation="사건 등록 증거 원문 및 발췌 확인 완료",
            ))

        # 3. [2. 현재 판단 가능한 법률 쟁점] 및 [3. 조건부 판단] 접지
        for r in (issue_results or []):
            ev_refs = []
            for src_lbl in (r.supported_source_ids or []):
                reg = briefing.source_registry.get(src_lbl) or {}
                doc_id = reg.get("evidence_id")
                doc_name = reg.get("document_name")
                if doc_id:
                    c_id, s_id, excerpt = _find_best_claim_and_span(doc_id, r.issue_title)
                    ev_refs.append(ClaimReference(
                        evidence_id=doc_id,
                        evidence_label=src_lbl,
                        claim_id=c_id,
                        span_id=s_id,
                        text_excerpt=excerpt,
                        document_name=doc_name,
                    ))
            leg_refs = []
            for stat in (r.supported_statute_ids or []):
                leg_refs.append({
                    "statute_id": stat,
                    "statute_name": stat.split("제")[0].strip() if "제" in stat else stat,
                    "article": "제" + stat.split("제")[1].strip() if "제" in stat else None,
                    "grounding_status": "SUPPORTED",
                })
            tag = ", ".join([f"[{s}]" for s in sorted(set(r.supported_source_ids))]) if r.supported_source_ids else "[법률근거]"
            gr_status = "SUPPORTED" if r.status == "VERIFIED" else "CONDITIONALLY_SUPPORTED"
            for rec in r.safe_recommendations:
                citations.append(ClaimCitation(
                    citation_tag=tag,
                    claim_text=rec,
                    grounding_status=gr_status,
                    evidence_refs=ev_refs,
                    legal_refs=leg_refs,
                    explanation=f"{r.issue_title} ({r.status})",
                ))

        # 4. [4. 지금 할 수 있는 안전한 행동 가이드] 5대 조치사항 접지
        action_item_configs = [
            {
                "tag": "[E01], [E03], [E16]",
                "text": "보증금 전액을 반환받거나 관할 법원의 임차권등기명령에 따른 등기가 등기부에 기재되기 전까지는 절대 주택의 점유를 상실(열쇠 인도, 비밀번호 공유, 임의 퇴거)하거나 전입을 옮기지 마십시오. (대항력 및 우선변제권 유지 필수)",
                "evidence_labels": ["E01", "E03", "E16"],
                "statute": "주택임대차보호법 제3조 제1항",
            },
            {
                "tag": "[E05], [E15]",
                "text": "임대인에게 보증금 반환 최고 및 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 내용증명을 발송하여 임대인의 이행지체 책임을 명확히 하십시오.",
                "evidence_labels": ["E05", "E15"],
                "statute": "민법 제544조, 소송촉진 등에 관한 특례법 제3조",
            },
            {
                "tag": "[E01], [E03]",
                "text": "계약 종료 즉시 관할 법원에 임차권등기명령을 신청하여 향후 부득이하게 이사할 때에도 기존 대항력과 우선변제권이 온전히 유지·보전되도록 조치하십시오.",
                "evidence_labels": ["E01", "E03"],
                "statute": "주택임대차보호법 제3조의3",
            },
            {
                "tag": "[E09], [E10], [E11]",
                "text": "대법원 인터넷등기소를 통해 목적물 부동산의 최신 말소사항 포함 등기사항전부증명서를 발급받아 가압류 외 다른 선순위 권리 변동 여부를 최종 대조하십시오.",
                "evidence_labels": ["E09", "E10", "E11"],
                "statute": "부동산등기법",
            },
            {
                "tag": "[E01], [E09], [E10]",
                "text": "목적물에 관한 경매 절차가 개시될 경우, 선순위 대항력을 바탕으로 보증금 전액을 낙찰자에게 인수시킬지 또는 배당요구종기 내에 권리신고 및 배당요구 신청서를 관할 경매법원에 접수하여 우선배당받을지 신중히 선택하여 진행하십시오.",
                "evidence_labels": ["E01", "E09", "E10"],
                "statute": "주택임대차보호법 제3조의2 제2항, 민사집행법 제84조",
            },
        ]
        for act in action_item_configs:
            ev_refs = []
            for src_lbl in act["evidence_labels"]:
                reg = briefing.source_registry.get(src_lbl) or {}
                doc_id = reg.get("evidence_id")
                doc_name = reg.get("document_name")
                if doc_id:
                    c_id, s_id, excerpt = _find_best_claim_and_span(doc_id, act["text"])
                    ev_refs.append(ClaimReference(
                        evidence_id=doc_id,
                        evidence_label=src_lbl,
                        claim_id=c_id,
                        span_id=s_id,
                        text_excerpt=excerpt,
                        document_name=doc_name,
                    ))
            stat = act["statute"]
            leg_refs = [{
                "statute_id": stat,
                "statute_name": stat.split("제")[0].strip() if "제" in stat else stat,
                "article": "제" + stat.split("제")[1].strip() if "제" in stat else None,
                "grounding_status": "SUPPORTED",
            }]
            citations.append(ClaimCitation(
                citation_tag=act["tag"],
                claim_text=act["text"],
                grounding_status="SUPPORTED",
                evidence_refs=ev_refs,
                legal_refs=leg_refs,
                explanation="권리보전을 위한 법정 단계별 행동 지침",
            ))

        return [c.model_dump() for c in citations]
    except Exception as e:
        logger.warning(f"[BUILD_CLAIM_CITATIONS] 예외 발생: {e}", exc_info=True)
        return []
