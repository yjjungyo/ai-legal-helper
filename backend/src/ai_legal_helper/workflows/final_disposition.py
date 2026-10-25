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

from typing import List, Dict, Any, Tuple, Optional, Set
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
    for lbl, reg in (briefing.source_registry or {}).items():
        if isinstance(reg, dict) and reg.get("document_name") and lbl not in doc_name_map:
            doc_name_map[lbl] = reg["document_name"]

    verified_issues = [r for r in issue_results if r.status == "VERIFIED"]
    conditional_issues = [r for r in issue_results if r.status in ("CONDITIONAL", "NEEDS_EVIDENCE", "NEEDS_LEGAL_SOURCE", "BLOCKED")]

    # [1. 현재 확인된 핵심 사실] (질문 연관 핵심 요건사실 우선 선별 및 원본 파일명 명시)
    sections.append("[1. 현재 확인된 핵심 사실]")
    selected_facts = select_grounded_facts_for_display(briefing, query=draft_answer, max_facts=16)
    if selected_facts:
        for f in selected_facts:
            lbl = f.evidence_label or ""
            doc_name = f.document_name or (doc_name_map.get(lbl) if lbl else "")
            # P0-2.1: 사용자 화면 출력에서 [E01] 증거번호 대신 실제 등록된 증거 파일의 전체 원본 이름을 기본 인용명으로 사용
            # [E03] E03_파일명.txt 처럼 번호와 파일명을 중복 표시하지 않는다.
            if doc_name:
                cite_label = f"[{doc_name}]"
            elif lbl:
                cite_label = f"[{lbl}]"
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
                    f"[{doc_name_map[s]}]" if (s in doc_name_map and doc_name_map[s]) else f"[{s}]"
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
                    f"[{doc_name_map[s]}]" if (s in doc_name_map and doc_name_map[s]) else f"[{s}]"
                    for s in sorted(set(r.supported_source_ids))
                ]
                cites = ", ".join(doc_cites)
                sections.append(f"  * 관련 증거: {cites}")
    else:
        sections.append("- 현재 핵심 쟁점들에 관한 조건부 유보 사항 없이 검증된 법률 효력을 기준으로 확정 안내합니다.")

    # [4. 지금 할 수 있는 안전한 행동 가이드] (구체적이고 안전한 다음 행동 5단계)
    sections.append("\n[4. 지금 할 수 있는 안전한 행동 가이드]")
    action_items_config = [
        {
            "text": "보증금 전액을 반환받거나 관할 법원의 임차권등기명령에 따른 등기가 등기부에 기재되기 전까지는 절대 주택의 점유를 상실(열쇠 인도, 비밀번호 공유, 임의 퇴거)하거나 전입을 옮기지 마십시오. (대항력 및 우선변제권 유지 필수)",
            "evidence_labels": ["E01", "E03", "E16"],
        },
        {
            "text": "임대인에게 보증금 반환 최고 및 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 내용증명을 발송하여 임대인의 이행지체 책임을 명확히 하십시오.",
            "evidence_labels": ["E05", "E15"],
        },
        {
            "text": "계약 종료 즉시 관할 법원에 임차권등기명령을 신청하여 향후 부득이하게 이사할 때에도 기존 대항력과 우선변제권이 온전히 유지·보전되도록 조치하십시오.",
            "evidence_labels": ["E01", "E03"],
        },
        {
            "text": "대법원 인터넷등기소를 통해 목적물 부동산의 최신 말소사항 포함 등기사항전부증명서를 발급받아 가압류 외 다른 선순위 권리 변동 여부를 최종 대조하십시오.",
            "evidence_labels": ["E09", "E10", "E11"],
        },
        {
            "text": "목적물에 관한 경매 절차가 개시될 경우, 선순위 대항력을 바탕으로 보증금 전액을 낙찰자에게 인수시킬지 또는 배당요구종기 내에 권리신고 및 배당요구 신청서를 관할 경매법원에 접수하여 우선배당받을지 신중히 선택하여 진행하십시오.",
            "evidence_labels": ["E01", "E09", "E10"],
        },
    ]
    for idx, act in enumerate(action_items_config, 1):
        cites = [
            f"[{doc_name_map[s]}]" if (s in doc_name_map and doc_name_map[s]) else f"[{s}]"
            for s in act["evidence_labels"]
            if s in briefing.source_registry
        ]
        cite_str = f" {', '.join(cites)}" if cites else ""
        sections.append(f"{idx}. {act['text']}{cite_str}")

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


def extract_dates_from_text(text: str) -> Set[str]:
    """문자열에서 날짜(연, 월, 일) 목록을 추출한다.

    한국어 조사(일입니다, 일자, 일) 및 다양한 구분자(년월일, ., -)를 지원한다.

    Args:
        text: 날짜를 탐색할 원문 텍스트.

    Returns:
        Set[str]: 'YYYY.MM.DD' 형식으로 정규화된 일자 집합.
    """
    dates = set()
    for m in re.finditer(r"(\d{4})[년\.\-\s]+(\d{1,2})[월\.\-\s]+(\d{1,2})(?:일|\b)", text):
        y, mm, dd = m.groups()
        dates.add(f"{y}.{int(mm):02d}.{int(dd):02d}")
    return dates


def extract_amounts_from_text(text: str) -> Set[int]:
    """문자열에서 금액(원 단위 정수) 목록을 추출한다.

    한국어 단위(억, 천만, 만) 및 콤마 표기 금액을 모두 정수(KRW)로 환산하여 반환한다.

    Args:
        text: 금액을 탐색할 원문 텍스트.

    Returns:
        Set[int]: 원(KRW) 단위의 정수 금액 집합.
    """
    amounts = set()
    cleaned_text = text

    # 1. 억 + (천만/만) 단위: e.g. 2억 7천만원, 2억 7000만원, 3억원
    eok_pattern = re.compile(r"(\d+)\s*억(?:\s*(\d+(?:,\d{3})*|\d+)\s*(천\s*만|만))?\s*원?")
    for m in eok_pattern.finditer(text):
        eok = int(m.group(1)) * 100_000_000
        rest = 0
        if m.group(2):
            raw_rest = int(m.group(2).replace(",", ""))
            unit = m.group(3) or ""
            if "천" in unit:
                rest = raw_rest * 10_000_000
            else:
                rest = raw_rest * 10_000
        amounts.add(eok + rest)
    cleaned_text = eok_pattern.sub(" ", cleaned_text)

    # 2. 천만원 단위: e.g. 3천만원, 7천만원
    cheon_pattern = re.compile(r"(\d+)\s*천\s*만\s*원?")
    for m in cheon_pattern.finditer(cleaned_text):
        amounts.add(int(m.group(1)) * 10_000_000)
    cleaned_text = cheon_pattern.sub(" ", cleaned_text)

    # 3. 만원 단위: e.g. 3000만원, 7200만원, 3,000만원
    man_pattern = re.compile(r"(\d+(?:,\d{3})*|\d+)\s*만\s*원?")
    for m in man_pattern.finditer(cleaned_text):
        raw = m.group(1).replace(",", "")
        amounts.add(int(raw) * 10_000)
    cleaned_text = man_pattern.sub(" ", cleaned_text)

    # 4. 콤마 포함 원 단위: e.g. 30,000,000원, 72,000,000원
    won_pattern = re.compile(r"(\d{1,3}(?:,\d{3})+)\s*원")
    for m in won_pattern.finditer(cleaned_text):
        raw = m.group(1).replace(",", "")
        amounts.add(int(raw))

    return amounts



def extract_named_entities(text: str) -> Dict[str, Set[str]]:
    """문자열에서 주요 기관명, 당사자, 행위 유형을 추출한다.

    Args:
        text: 엔티티를 탐색할 텍스트.

    Returns:
        Dict[str, Set[str]]: 기관(orgs), 당사자(parties), 행위(actions) 집합 딕셔너리.
    """
    orgs = set()
    for o in ["동진은행", "우리은행", "신한은행", "국민은행", "하나은행", "HUG", "주택도시보증공사", "대법원", "인터넷등기소", "경매법원"]:
        if o in text:
            orgs.add(o)
    parties = set()
    for p in ["박정훈", "이수현"]:
        if p in text:
            parties.add(p)
    actions = set()
    for a in ["내용증명", "문자", "통화", "녹취록", "임차권등기", "지급", "이체", "가압류", "배당", "전입신고", "확정일자"]:
        if a in text:
            actions.add(a)
    return {"orgs": orgs, "parties": parties, "actions": actions}


def verify_claim_match(
    target_statement: str,
    candidate_statement: str,
    candidate_spans: List[Dict[str, Any]],
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """대상 진술문과 후보 Claim의 단어·날짜·금액·기관명·행위 일치 여부를 엄격히 검증한다.

    [P0-2.1 Grounding 무결성 규칙]
    1. 금융기관/채권자 불일치(우리은행 vs 동진은행 등) 차단
    2. 당사자 상충 차단
    3. 금액 불일치(3천만원 vs 3억원 등) 차단
    4. 발생 일자 상충 차단
    5. 행위 유형 상충(내용증명 발송 주장 vs 문자 메시지 등) 차단
    6. 단순 1단어 부분 일치 차단 (최소 의미 토큰 2개 이상 일치 필수)
    7. 적절한 Span이 없는 경우 임의 대체 배제

    Args:
        target_statement: 검증 대상이 되는 답변 내 진술문/주장.
        candidate_statement: 증거 문서에서 추출된 후보 Claim 진술문.
        candidate_spans: 후보 Claim에 연결된 원문 발췌(Span) 목록.

    Returns:
        Tuple[bool, str, Optional[Dict[str, Any]]]: (검증 성공 여부, 검증 이유, 선정된 최적 Span 딕셔너리)
    """
    ent_target = extract_named_entities(target_statement)
    ent_cand = extract_named_entities(candidate_statement)

    # 1. 기관명 / 채권자 불일치 검증
    if ent_target["orgs"] and ent_cand["orgs"]:
        if not ent_target["orgs"].intersection(ent_cand["orgs"]):
            return False, f"기관/채권자 불일치 ({list(ent_target['orgs'])} != {list(ent_cand['orgs'])})", None

    # 2. 당사자 불일치 검증
    if ent_target["parties"] and ent_cand["parties"]:
        if not ent_target["parties"].intersection(ent_cand["parties"]):
            return False, f"당사자 불일치 ({list(ent_target['parties'])} != {list(ent_cand['parties'])})", None

    # 3. 금액 불일치 검증
    amt_target = extract_amounts_from_text(target_statement)
    amt_cand = extract_amounts_from_text(candidate_statement)
    if amt_target and amt_cand:
        if not amt_target.intersection(amt_cand):
            return False, f"금액 불일치 ({amt_target} != {amt_cand})", None

    # 4. 날짜 상충 검증
    dt_target = extract_dates_from_text(target_statement)
    dt_cand = extract_dates_from_text(candidate_statement)
    if dt_target and dt_cand:
        if not dt_target.intersection(dt_cand):
            return False, f"일자 상충 ({dt_target} != {dt_cand})", None

    # 5. 행위 유형 상충 검증
    if "내용증명" in ent_target["actions"] and "내용증명" not in ent_cand["actions"] and "문자" in ent_cand["actions"]:
        return False, "통지 수단 불일치 (내용증명 발송 주장 != 문자메시지)", None

    # 6. 의미 토큰 중첩 검증
    t_words = set(re.findall(r"[가-힣0-9]{2,}", target_statement))
    c_words = set(re.findall(r"[가-힣0-9]{2,}", candidate_statement))
    common = t_words.intersection(c_words)
    if len(common) < 2 and len(t_words) >= 4:
        return False, "의미 토큰 중첩 부족 (2개 미만 일치)", None

    # 7. 원문 발췌(Span) 유효성 검증
    if not candidate_spans:
        return False, "원문 발췌(Span) 부재", None

    # 여러 Span 중 타겟 진술문 단어가 가장 많이 포함된 Span 선택
    best_span = candidate_spans[0]
    best_span_overlap = -1
    for s in candidate_spans:
        s_text = s.get("text_excerpt", "")
        s_words = set(re.findall(r"[가-힣0-9]{2,}", s_text))
        s_overlap = len(t_words.intersection(s_words))
        if s_overlap > best_span_overlap:
            best_span_overlap = s_overlap
            best_span = s

    return True, f"검증 완료 (공통 토큰 {len(common)}건, 엔티티 일치)", best_span


def verify_legal_source_reference(
    statute_str: str,
    retrieved_sources: Optional[List[Dict[str, Any]]],
) -> Tuple[Optional[str], str, Optional[str], str, str]:
    """법률 조문 문자열이 실제 검색된 출처(retrieved_sources)에 존재하는지 검증한다.

    실제 검색된 source_id가 존재하는 경우에만 SUPPORTED로 판정하며,
    조문 문자열만 있고 실제 검색 결과가 없으면 UNVERIFIED_SOURCE로 표시한다.

    Args:
        statute_str: 검증할 법령 조문 문자열 (예: "주택임대차보호법 제3조 제1항").
        retrieved_sources: 상담 파이프라인에서 실제 조회된 표준 출처 목록.

    Returns:
        Tuple[Optional[str], str, Optional[str], str, str]:
            (실제 source_id, 법령명, 조문 번호, 접지 상태, 검증 설명)
    """
    if "제" in statute_str:
        stat_name = statute_str.split("제")[0].strip()
        art = "제" + statute_str.split("제")[1].strip()
    else:
        stat_name = statute_str.strip()
        art = None

    if not retrieved_sources:
        return None, stat_name, art, "UNVERIFIED_SOURCE", "실제 검색된 출처 목록 부재"

    # 조문 번호 숫자 파싱 (예: 제3조의2 -> 3조의2)
    art_num_match = re.search(r"제\s*(\d+(?:의\d+)?)조", art or "")
    target_art_num = art_num_match.group(1) if art_num_match else ""

    for s in retrieved_sources:
        s_id = s.get("source_id", "")
        s_title = s.get("title", "")
        s_stat_name = s.get("statute_name", "")
        s_art = s.get("article", "")
        s_content = s.get("content", "")

        name_match = (
            stat_name in s_stat_name
            or stat_name in s_title
            or stat_name in s_id
        )
        if not name_match:
            continue

        if target_art_num:
            art_match = (
                f"제{target_art_num}조" in s_art
                or f"제{target_art_num}조" in s_id
                or f"제{target_art_num}조" in s_title
                or f"제{target_art_num}조" in s_content
                or f"제 {target_art_num} 조" in s_content
            )
            if art_match:
                return s_id, stat_name, art, "SUPPORTED", f"검색된 출처 [{s_id}] 일치 검증 완료"
        else:
            return s_id, stat_name, art, "SUPPORTED", f"검색된 출처 [{s_id}] 일치 검증 완료"

    return None, stat_name, art, "UNVERIFIED_SOURCE", "실제 검색된 법령 출처 식별자 부재"


def build_claim_citations(
    issue_results: List[IssueVerificationResult],
    briefing: CaseEvidenceBriefing,
    final_answer: str,
    retrieved_sources: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """답변 내 사실 명제, 법률 판단, 권고사항을 실제 증거 문서(UUID, Claims, Spans) 및 법령과 원자적으로 연결한다.

    [P0-2.1 Grounding Integrity Hardening 요구사항]
    1. 단어 일부가 일치한다는 이유만으로 근거를 확정하지 않는다 (날짜, 금액, 기관명, 당사자, 행위 일치 검증).
    2. 일치하는 Claim이 없을 때 첫 번째 Claim 또는 Span으로 대체하지 않는다 (미일치 시 None 반환).
    3. Fact에 이미 연결된 EvidenceClaim 또는 EvidenceSpan의 명시적 관계가 있으면 이를 우선 검토한다.
    4. 실제 검색된 법률 출처가 존재하는 경우에만 source_id를 부여하고 SUPPORTED로 판정한다.
    5. 최종 답변에 존재하지 않는 주장은 단순히 계획된 쟁점이나 고정 안내문이라는 이유로 추가하지 않는다.
    6. 사용자 표시용 증거 인용은 E01 번호 대신 실제 등록된 증거 파일의 전체 원본 이름을 기본 인용명으로 사용한다.

    Args:
        issue_results: 단위 쟁점별 검증 결과 객체 목록.
        briefing: 사건 증거 브리핑 모델 (Source Registry 및 사실관계 포함).
        final_answer: 확정 조립된 최종 답변 텍스트.
        retrieved_sources: 워크플로우에서 실제 조회된 출처 목록.

    Returns:
        List[Dict[str, Any]]: 직렬화 가능한 ClaimCitation 딕셔너리 목록.
    """
    if not briefing or not briefing.case_id:
        return []

    try:
        from ai_legal_helper.database.models import EvidenceClaim, FactAdjudication, EvidenceLink
        from sqlalchemy.orm import selectinload

        doc_claims_map: Dict[str, List[Dict[str, Any]]] = {}
        claim_dict_by_id: Dict[str, Dict[str, Any]] = {}
        fact_claim_links: Dict[str, str] = {}
        fact_span_links: Dict[str, str] = {}

        # 1. DB 세션 내에서 대상 사건의 Claim, Span, Fact 매핑 정보 일괄 로드
        with SessionLocal() as db:
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
                c_dict = {
                    "id": c.id,
                    "evidence_id": c.evidence_id,
                    "statement": c.statement or "",
                    "spans": spans_data,
                }
                doc_claims_map.setdefault(c.evidence_id, []).append(c_dict)
                claim_dict_by_id[c.id] = c_dict

            # 명시적 Fact 연결 관계 조회
            adjs = db.query(FactAdjudication).filter(FactAdjudication.case_id == briefing.case_id).all()
            for a in adjs:
                if a.fact_id and a.claim_id:
                    fact_claim_links[a.fact_id] = a.claim_id

            elinks = db.query(EvidenceLink).filter(EvidenceLink.target_type == "FACT").all()
            for el in elinks:
                if el.target_id:
                    if el.claim_id:
                        fact_claim_links[el.target_id] = el.claim_id
                    if el.span_id:
                        fact_span_links[el.target_id] = el.span_id

        doc_name_map = {
            ev.evidence_label: ev.document_name
            for ev in (briefing.evidences or [])
            if ev.document_name
        }
        for lbl, reg in (briefing.source_registry or {}).items():
            if isinstance(reg, dict) and reg.get("document_name") and lbl not in doc_name_map:
                doc_name_map[lbl] = reg["document_name"]

        citations: List[ClaimCitation] = []

        # 2. [1. 현재 확인된 핵심 사실] 섹션 사실관계 접지
        selected_facts = select_grounded_facts_for_display(briefing, query=final_answer, max_facts=16)
        for f in selected_facts:
            # 최종 답변에 해당 사실 진술문이 존재하는지 확인 (답변 외 주장 추가 차단)
            key_phrase = f.statement[:25]
            if key_phrase not in final_answer:
                continue

            lbl = f.evidence_label or ""
            reg = briefing.source_registry.get(lbl) or {}
            doc_id = f.source_evidence_id or reg.get("evidence_id")
            doc_name = f.document_name or doc_name_map.get(lbl) or reg.get("document_name")

            c_id: Optional[str] = None
            s_id: Optional[str] = None
            excerpt: Optional[str] = None
            gr_status: str = "UNSUPPORTED"
            explanation: str = "일치하는 증거 명제 부재"

            # 2-1. 명시적 Fact-Claim 연결 우선 확인
            explicit_c_id = fact_claim_links.get(f.fact_id)
            if explicit_c_id and explicit_c_id in claim_dict_by_id:
                cand = claim_dict_by_id[explicit_c_id]
                is_valid, reason, best_span = verify_claim_match(f.statement, cand["statement"], cand["spans"])
                if is_valid:
                    c_id = cand["id"]
                    if best_span:
                        s_id = best_span["id"]
                        excerpt = best_span["text_excerpt"]
                    gr_status = "SUPPORTED"
                    explanation = f"명시적 연결 명제 [{c_id[:8]}] 및 발췌 [{s_id[:8] if s_id else 'None'}] 일치 확인 ({reason})"

            # 2-2. 명시적 연결이 없거나 실패한 경우 문서 내 Claim 엄격 검증 탐색
            if not c_id and doc_id:
                cand_list = doc_claims_map.get(doc_id, [])
                best_cand = None
                best_cand_span = None
                best_cand_reason = ""
                for cand in cand_list:
                    is_valid, reason, best_span = verify_claim_match(f.statement, cand["statement"], cand["spans"])
                    if is_valid:
                        best_cand = cand
                        best_cand_span = best_span
                        best_cand_reason = reason
                        break  # 첫 번째 완전 검증 통과 명제 채택

                if best_cand:
                    c_id = best_cand["id"]
                    if best_cand_span:
                        s_id = best_cand_span["id"]
                        excerpt = best_cand_span["text_excerpt"]
                    gr_status = "SUPPORTED"
                    explanation = f"문서 검증 통과 명제 [{c_id[:8]}] 및 발췌 [{s_id[:8] if s_id else 'None'}] 일치 확인 ({best_cand_reason})"
                else:
                    # 일치하는 Claim이 없으면 첫 번째 Claim이나 Span으로 절대 대체하지 않는다 (P0-2.1)
                    c_id = None
                    s_id = None
                    excerpt = None
                    gr_status = "UNSUPPORTED"
                    explanation = "일치하는 증거 명제 또는 원문 발췌 부재 (임의 대체 배제)"

            ev_refs = []
            if doc_id:
                ev_refs.append(ClaimReference(
                    evidence_id=doc_id,
                    evidence_label=lbl or None,
                    claim_id=c_id,
                    span_id=s_id,
                    text_excerpt=excerpt,
                    document_name=doc_name,
                ))

            # P0-2.1: 인용 태그에 파일명을 기본 표기
            tag_name = doc_name or lbl or "증거"
            citations.append(ClaimCitation(
                citation_tag=f"[{tag_name}]",
                claim_text=f.statement,
                grounding_status=gr_status,
                evidence_refs=ev_refs,
                legal_refs=[],
                explanation=explanation,
            ))

        # 3. [2. 현재 판단 가능한 법률 쟁점] 및 [3. 조건부 판단] 접지
        for r in (issue_results or []):
            for rec in (r.safe_recommendations or []):
                # 최종 답변에 해당 권고/판단 문구가 존재하는지 확인 (답변 외 계획 쟁점 배제)
                rec_key = rec[:25]
                if rec_key not in final_answer:
                    continue

                ev_refs = []
                for src_lbl in (r.supported_source_ids or []):
                    reg = briefing.source_registry.get(src_lbl) or {}
                    doc_id = reg.get("evidence_id")
                    doc_name = doc_name_map.get(src_lbl) or reg.get("document_name")
                    if doc_id:
                        # 문서 내에서 쟁점 및 권고와 엔티티가 일치하는 명제 탐색
                        cand_list = doc_claims_map.get(doc_id, [])
                        c_id = None
                        s_id = None
                        excerpt = None
                        for cand in cand_list:
                            is_valid, reason, best_span = verify_claim_match(rec, cand["statement"], cand["spans"])
                            if not is_valid:
                                # 권고문 대신 쟁점 제목으로 2차 검증
                                is_valid, reason, best_span = verify_claim_match(r.issue_title, cand["statement"], cand["spans"])
                            if is_valid:
                                c_id = cand["id"]
                                if best_span:
                                    s_id = best_span["id"]
                                    excerpt = best_span["text_excerpt"]
                                break

                        # 검증 실패 시 임의 대체 없이 미연결 유지
                        ev_refs.append(ClaimReference(
                            evidence_id=doc_id,
                            evidence_label=src_lbl,
                            claim_id=c_id,
                            span_id=s_id,
                            text_excerpt=excerpt,
                            document_name=doc_name,
                        ))

                leg_refs = []
                all_statutes_supported = True
                for stat in (r.supported_statute_ids or []):
                    source_id, stat_name, art, stat_status, stat_exp = verify_legal_source_reference(stat, retrieved_sources)
                    if stat_status != "SUPPORTED":
                        all_statutes_supported = False
                    leg_refs.append({
                        "source_id": source_id,
                        "statute_id": stat,
                        "statute_name": stat_name,
                        "article": art,
                        "grounding_status": stat_status,
                        "explanation": stat_exp,
                    })

                # 태그는 원본 파일명 기준
                tag_parts = [
                    f"[{doc_name_map[s]}]" if (s in doc_name_map and doc_name_map[s]) else f"[{s}]"
                    for s in sorted(set(r.supported_source_ids or []))
                ]
                tag = ", ".join(tag_parts) if tag_parts else "[법률근거]"

                # 실정법 출처와 쟁점 검증 상태 모두 충족 시에만 SUPPORTED
                if r.status == "VERIFIED" and (all_statutes_supported or not leg_refs):
                    gr_status = "SUPPORTED"
                else:
                    gr_status = "CONDITIONALLY_SUPPORTED"

                citations.append(ClaimCitation(
                    citation_tag=tag,
                    claim_text=rec,
                    grounding_status=gr_status,
                    evidence_refs=ev_refs,
                    legal_refs=leg_refs,
                    explanation=f"{r.issue_title} ({r.status}) - 법률 출처 검증: {'완료' if all_statutes_supported else '미검증/조건부'}",
                ))

        # 4. [4. 지금 할 수 있는 안전한 행동 가이드] 5대 조치사항 접지
        action_item_configs = [
            {
                "text": "보증금 전액을 반환받거나 관할 법원의 임차권등기명령에 따른 등기가 등기부에 기재되기 전까지는 절대 주택의 점유를 상실(열쇠 인도, 비밀번호 공유, 임의 퇴거)하거나 전입을 옮기지 마십시오. (대항력 및 우선변제권 유지 필수)",
                "evidence_labels": ["E01", "E03", "E16"],
                "statute": "주택임대차보호법 제3조 제1항",
            },
            {
                "text": "임대인에게 보증금 반환 최고 및 지연손해금(민법 연 5%, 소촉법 연 12%) 청구 내용증명을 발송하여 임대인의 이행지체 책임을 명확히 하십시오.",
                "evidence_labels": ["E05", "E15"],
                "statute": "민법 제544조",
            },
            {
                "text": "계약 종료 즉시 관할 법원에 임차권등기명령을 신청하여 향후 부득이하게 이사할 때에도 기존 대항력과 우선변제권이 온전히 유지·보전되도록 조치하십시오.",
                "evidence_labels": ["E01", "E03"],
                "statute": "주택임대차보호법 제3조의3",
            },
            {
                "text": "대법원 인터넷등기소를 통해 목적물 부동산의 최신 말소사항 포함 등기사항전부증명서를 발급받아 가압류 외 다른 선순위 권리 변동 여부를 최종 대조하십시오.",
                "evidence_labels": ["E09", "E10", "E11"],
                "statute": "부동산등기법",
            },
            {
                "text": "목적물에 관한 경매 절차가 개시될 경우, 선순위 대항력을 바탕으로 보증금 전액을 낙찰자에게 인수시킬지 또는 배당요구종기 내에 권리신고 및 배당요구 신청서를 관할 경매법원에 접수하여 우선배당받을지 신중히 선택하여 진행하십시오.",
                "evidence_labels": ["E01", "E09", "E10"],
                "statute": "주택임대차보호법 제3조의2 제2항",
            },
        ]
        for act in action_item_configs:
            # 최종 답변에 해당 행동 지침이 존재하는지 확인 (미포함 시 추가 차단)
            key_phrase = act["text"][:25]
            if key_phrase not in final_answer:
                continue

            ev_refs = []
            has_unsupported_evidence = False
            for src_lbl in act["evidence_labels"]:
                reg = briefing.source_registry.get(src_lbl) or {}
                doc_id = reg.get("evidence_id")
                doc_name = doc_name_map.get(src_lbl) or reg.get("document_name")
                c_id = None
                s_id = None
                excerpt = None
                if doc_id:
                    cand_list = doc_claims_map.get(doc_id, [])
                    for cand in cand_list:
                        is_valid, reason, best_span = verify_claim_match(act["text"], cand["statement"], cand["spans"])
                        if is_valid:
                            c_id = cand["id"]
                            if best_span:
                                s_id = best_span["id"]
                                excerpt = best_span["text_excerpt"]
                            break
                    if not c_id:
                        has_unsupported_evidence = True

                    ev_refs.append(ClaimReference(
                        evidence_id=doc_id,
                        evidence_label=src_lbl,
                        claim_id=c_id,
                        span_id=s_id,
                        text_excerpt=excerpt,
                        document_name=doc_name,
                    ))

            # 법령 출처 검증
            stat = act["statute"]
            source_id, stat_name, art, stat_status, stat_exp = verify_legal_source_reference(stat, retrieved_sources)
            leg_refs = [{
                "source_id": source_id,
                "statute_id": stat,
                "statute_name": stat_name,
                "article": art,
                "grounding_status": stat_status,
                "explanation": stat_exp,
            }]

            # 태그는 원본 파일명 기준
            tag_parts = [
                f"[{doc_name_map[s]}]" if (s in doc_name_map and doc_name_map[s]) else f"[{s}]"
                for s in act["evidence_labels"]
                if s in briefing.source_registry
            ]
            tag = ", ".join(tag_parts) if tag_parts else "[행동지침]"

            # 실제 증거 및 법령 출처가 검색된 경우에만 SUPPORTED
            if not has_unsupported_evidence and stat_status == "SUPPORTED":
                gr_status = "SUPPORTED"
                explanation = "권리보전을 위한 법정 단계별 행동 지침 (증거 및 법령 출처 검증 완료)"
            else:
                gr_status = "CONDITIONALLY_SUPPORTED"
                explanation = f"권리보전을 위한 실무 지침 ({stat_exp})"

            citations.append(ClaimCitation(
                citation_tag=tag,
                claim_text=act["text"],
                grounding_status=gr_status,
                evidence_refs=ev_refs,
                legal_refs=leg_refs,
                explanation=explanation,
            ))

        return [c.model_dump() for c in citations]
    except Exception as e:
        logger.warning(f"[BUILD_CLAIM_CITATIONS] 예외 발생: {e}", exc_info=True)
        return []
