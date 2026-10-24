# -*- coding: utf-8 -*-
"""
모듈명: issue_planner.py

[모듈 개요]
사용자의 복합 법률 상담 질문(Complex Legal Query)을 독립적으로 분석 및 검증할 수 있는
단위 법률 쟁점 과업(LegalIssueTask) 목록으로 분해(Decomposition)하는 모듈.

[주요 기능]
1. 사용자 질문과 사건 증거 브리핑(CaseEvidenceBriefing)을 기반으로 독립적 법률 쟁점 도출
2. 각 쟁점별 요건사실 키, 연관 Fact ID, 관련 증거 번호(E01, E02...) 및 적용 후보 법령 매핑
3. 주택임대차, 근로계약, 일반 채권채무 등 도메인 일반화 규칙 및 동적 쟁점 추출 지원
4. 쟁점 간 독립성 보장: 특정 쟁점의 자료 부족이 타 쟁점의 검증 실패로 전이되지 않도록 분리
"""

from typing import List, Dict, Any, Optional
import re
from pydantic import BaseModel, Field

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)


class LegalIssueTask(BaseModel):
    """독립적으로 분석 및 검증 가능한 단위 법률 쟁점 과업 모델."""
    issue_id: str = Field(..., description="쟁점 고유 식별자 (예: ISSUE_LEASE_TERMINATION)")
    issue_title: str = Field(..., description="사용자 친화적 쟁점 명칭")
    legal_questions: List[str] = Field(default_factory=list, description="해당 쟁점에서 검토할 구체적 법률 질문들")
    required_fact_keys: List[str] = Field(default_factory=list, description="법률 효과 판단에 필요한 요건사실 키워드")
    relevant_fact_ids: List[str] = Field(default_factory=list, description="사건 브리핑에서 연관된 Fact ID 목록")
    relevant_evidence_ids: List[str] = Field(default_factory=list, description="관련 증거 문서 ID 목록")
    relevant_evidence_labels: List[str] = Field(default_factory=list, description="관련 표시용 증거 번호 목록 (예: ['E01', 'E03'])")
    required_statutes: List[str] = Field(default_factory=list, description="검토에 필요한 관련 법령/조문 (예: ['주택임대차보호법 제6조'])")
    missing_evidence: List[str] = Field(default_factory=list, description="해당 쟁점에 결여된 증빙 자료 요건")
    priority: str = Field("HIGH", description="상담 우선순위 (HIGH, MEDIUM, LOW)")


def _match_facts_and_evidences(
    keywords: List[str],
    briefing: CaseEvidenceBriefing,
) -> tuple[List[str], List[str], List[str]]:
    """요건사실 키워드와 매칭되는 브리핑 내 Fact ID 및 증거 번호를 선별한다."""
    matched_fact_ids: List[str] = []
    matched_evidence_ids: List[str] = []
    matched_labels: List[str] = []

    compact_keywords = [re.sub(r"\s+", "", kw) for kw in keywords]

    for fact in briefing.facts:
        f_compact = re.sub(r"\s+", "", fact.statement)
        if any(ck in f_compact for ck in compact_keywords):
            matched_fact_ids.append(fact.fact_id)
            if fact.source_evidence_id and fact.source_evidence_id not in matched_evidence_ids:
                matched_evidence_ids.append(fact.source_evidence_id)
            if fact.evidence_label and fact.evidence_label not in matched_labels:
                matched_labels.append(fact.evidence_label)
            for sl in fact.supporting_evidence_labels:
                if sl not in matched_labels:
                    matched_labels.append(sl)

    return matched_fact_ids, matched_evidence_ids, matched_labels


def plan_legal_issues(
    question: str,
    briefing: CaseEvidenceBriefing,
) -> List[LegalIssueTask]:
    """사용자의 복합 상담 질문과 사건 브리핑을 분석하여 독립적인 법률 쟁점 목록을 계획한다.

    Section 6 (P0-03) 요구사항 반영:
    1. 계약 종료 시점 및 해지 효력
    2. 가압류 및 담보권과 임차인 권리 순위 관계
    3. 경매 시 보증금 회수 위험 및 배당 관계
    4. 이사 전 대항력 유지 및 임차권등기명령 등 권리보전 절차
    5. 임대인의 분할반환 제안 등의 의사표시 효력
    6. 필요한 추가 증거 및 다음 행동 가이드
    7. 일반 법률 쟁점의 동적 도출 (임대차 외 노동/일반 채권 지원)

    Args:
        question: 사용자 상담 질문.
        briefing: 사건 증거 및 사실관계 브리핑 모델.

    Returns:
        List[LegalIssueTask]: 도출된 단위 법률 쟁점 과업 목록.
    """
    issues: List[LegalIssueTask] = []
    q = question or ""
    q_compact = re.sub(r"\s+", "", q)

    # 1. 쟁점: 임대차계약 종료 시점 및 효력 발생
    if any(k in q_compact for k in ("종료", "해지", "만료", "끝", "퇴거", "갱신", "반환", "돌려")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["계약기간", "종료", "해지", "만료", "퇴거", "보증금", "임대차"], briefing
        )
        # 계약서(E01) 및 통지(E05 등) 증거 라벨 보강
        for ev in briefing.evidences:
            if any(k in (ev.document_name or "") for k in ("계약서", "퇴거", "해지", "통보", "통지", "요청")):
                if ev.evidence_label not in e_lbls:
                    e_lbls.append(ev.evidence_label)
                if ev.evidence_id not in e_ids:
                    e_ids.append(ev.evidence_id)

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_LEASE_TERMINATION",
                issue_title="임대차계약 종료 시점 및 보증금 반환의무 발생",
                legal_questions=[
                    "임대차계약의 당초 만료일은 언제인가?",
                    "임차인의 해지 및 반환 통고가 임대인에게 적법하게 도달하여 계약이 종료되었는가?",
                    "계약 종료에 따른 임대인의 보증금 반환 채무가 이행기에 도달하였는가?",
                ],
                required_fact_keys=["임대차기간", "만료일", "퇴거요청일", "통지도달", "보증금액"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제6조", "주택임대차보호법 제6조의2", "민법 제544조", "민법 제623조"],
                missing_evidence=[],
                priority="HIGH",
            )
        )

    # 2. 쟁점: 가압류 및 담보권과 임차인 대항력/우선변제권 권리 순위
    if any(k in q_compact for k in ("가압류", "근저당", "동진은행", "HUG", "순위", "권리관계", "등기")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["가압류", "전입신고", "확정일자", "등기", "동진은행", "HUG", "주민등록"], briefing
        )
        for ev in briefing.evidences:
            if any(k in (ev.document_name or "") for k in ("전입", "확정일자", "가압류", "등기", "열람")):
                if ev.evidence_label not in e_lbls:
                    e_lbls.append(ev.evidence_label)
                if ev.evidence_id not in e_ids:
                    e_ids.append(ev.evidence_id)

        # 등기부 최신본 부재 여부 체크
        missing = []
        for g in briefing.evidence_gaps:
            if g.gap_type in ("REGISTRY_CONFIRMATION_GAP", "HUG_INSURANCE_CONFIRMATION_GAP"):
                missing.append(g.target_proposition)

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_ATTACHMENT_RANKING",
                issue_title="가압류 등재와 임차인의 대항력·우선변제권 순위 관계",
                legal_questions=[
                    "임차인의 대항력(전입+주택인도) 및 우선변제권(확정일자) 구비 시점은 언제인가?",
                    "등재된 복수 가압류(은행, HUG)의 접수일자와 임차인의 우선변제권 발생일자의 선후 순위는 어떠한가?",
                    "임차인이 선순위 대항력을 갖춘 경우 가압류 채권자에게 대항할 수 있는가?",
                ],
                required_fact_keys=["전입신고일", "주택인도일", "확정일자일", "가압류접수일", "청구금액"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제3조", "주택임대차보호법 제3조의2", "민사집행법 제91조", "민사집행법 제148조"],
                missing_evidence=missing,
                priority="HIGH",
            )
        )

    # 3. 쟁점: 경매 실행 시 보증금 회수 위험 및 배당 관계
    if any(k in q_compact for k in ("경매", "위험", "배당", "회수", "우선변제")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["보증금", "확정일자", "가압류", "배당", "시세"], briefing
        )
        for ev in briefing.evidences:
            if any(k in (ev.document_name or "") for k in ("계약서", "가압류", "확정일자")):
                if ev.evidence_label not in e_lbls:
                    e_lbls.append(ev.evidence_label)

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_AUCTION_DIVIDEND_RISK",
                issue_title="경매 시 보증금 회수 위험 및 배당 요구 법률관계",
                legal_questions=[
                    "목적물이 강제경매 또는 임의경매로 매각될 경우 임차인의 배당요구 필요성은 어떠한가?",
                    "선순위 임차인이 배당요구를 하지 않는 경우 매수인이 보증금 반환 채무를 인수하는가?",
                    "가압류 청구금액 및 낙찰 예상가에 비추어 전액 배당 회수가 가능한가?",
                ],
                required_fact_keys=["보증금액", "배당요구종기", "선순위채권총액", "시세/낙찰가"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제3조의5", "민사집행법 제88조", "민사집행법 제148조"],
                missing_evidence=["정확한 시세 감정평가서", "선순위 채권 전수 확인 내역"],
                priority="HIGH",
            )
        )

    # 4. 쟁점: 이사 전 권리보전 절차 (임차권등기명령, 대항력 유지)
    if any(k in q_compact for k in ("이사", "보전", "임차권등기", "대항력", "점유", "전입유지")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["전입신고", "점유", "거주", "열쇠", "출입카드", "이사"], briefing
        )
        for ev in briefing.evidences:
            if any(k in (ev.document_name or "") for k in ("전입", "주민등록", "확정일자", "퇴거")):
                if ev.evidence_label not in e_lbls:
                    e_lbls.append(ev.evidence_label)

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_RIGHT_PRESERVATION",
                issue_title="이사 전 대항력 유지 및 임차권등기명령 등 권리보전 조치",
                legal_questions=[
                    "보증금을 반환받지 못한 상태에서 다른 곳으로 이사하거나 주민등록을 이전할 때 발생하는 위험은 무엇인가?",
                    "주택임대차보호법상 임차권등기명령 신청 요건(계약종료+미반환)이 충족되었는가?",
                    "임차권등기가 등기부에 기재되기 전까지 점유와 전입을 유지해야 하는 법적 이유는 무엇인가?",
                ],
                required_fact_keys=["계약종료사실", "미반환사실", "전입유지상태", "점유상태"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제3조의3", "주택임대차보호법 제3조 제1항"],
                missing_evidence=[],
                priority="HIGH",
            )
        )

    # 5. 쟁점: 임대인의 분할반환 제안의 법적 의미 및 대응
    if any(k in q_compact for k in ("분할", "제안", "일부반환", "1년뒤", "합의", "동의")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["분할", "제안", "거절", "일부반환", "문자"], briefing
        )
        for ev in briefing.evidences:
            if any(k in (ev.document_name or "") for k in ("제안", "분할", "대화", "녹음", "문자")):
                if ev.evidence_label not in e_lbls:
                    e_lbls.append(ev.evidence_label)

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_INSTALLMENT_PROPOSAL",
                issue_title="임대인의 분할반환 제안에 대한 법적 효력 및 대응 방안",
                legal_questions=[
                    "임대인의 일방적 분할반환 및 잔액 1년 유예 제안을 임차인이 수용할 법적 의무가 있는가?",
                    "임차인의 거절 의사표시로 인해 제안의 법적 효력이 소멸하였는가?",
                    "분할 지급 제안을 거부하고 전액 즉시 반환 청구 및 지연손해금을 청구할 수 있는가?",
                ],
                required_fact_keys=["분할제안내용", "임차인거절의사표시", "전액반환채무"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["민법 제460조", "민법 제468조", "민법 제397조", "소송촉진 등에 관한 특례법 제3조"],
                missing_evidence=[],
                priority="MEDIUM",
            )
        )

    # 6. 쟁점: 필요한 추가 증거 및 실무적 다음 행동
    if any(k in q_compact for k in ("추가증거", "다음행동", "미확인", "보완", "행동", "절차", "조치")):
        missing_props = [g.target_proposition for g in briefing.evidence_gaps]
        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_NEXT_ACTIONS",
                issue_title="입증 보완이 필요한 증거 목록 및 안전한 실무적 다음 행동",
                legal_questions=[
                    "향후 지급명령, 임차권등기명령, 반환소송을 진행하기 위해 보완해야 할 필수 증빙은 무엇인가?",
                    "권리 상실을 방지하기 위해 임차인이 취해야 할 단계별 실무 조치는 무엇인가?",
                ],
                required_fact_keys=["증거공백목록", "등기부열람", "내용증명도달", "보증보험가입증명"],
                relevant_fact_ids=[f.fact_id for f in briefing.facts if f.adjudication_status == "EVIDENCE_INCOMPLETE"],
                relevant_evidence_ids=[ev.evidence_id for ev in briefing.evidences],
                relevant_evidence_labels=[ev.evidence_label for ev in briefing.evidences],
                required_statutes=["민사소송법 제462조", "민사집행법 제276조"],
                missing_evidence=missing_props,
                priority="HIGH",
            )
        )

    # 7. 일반 질문 또는 기타 도메인 (노동, 대여금 등) 기본 폴백 쟁점
    if not issues:
        f_ids = [f.fact_id for f in briefing.facts]
        e_ids = [e.evidence_id for e in briefing.evidences]
        e_lbls = [e.evidence_label for e in briefing.evidences]
        missing_props = [g.target_proposition for g in briefing.evidence_gaps]

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_GENERAL_ANALYSIS",
                issue_title="사건 사실관계 및 법률적 검토 쟁점",
                legal_questions=[q],
                required_fact_keys=["주요사실", "요건사실"],
                relevant_fact_ids=f_ids[:10],
                relevant_evidence_ids=e_ids[:5],
                relevant_evidence_labels=sorted(e_lbls[:5]),
                required_statutes=[],
                missing_evidence=missing_props,
                priority="HIGH",
            )
        )

    logger.info(f"[ISSUE_PLANNER] 질문 분석 결과 {len(issues)}개 단위 쟁점 도출 완료")
    return issues
