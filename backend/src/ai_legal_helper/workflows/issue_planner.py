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
from pydantic import BaseModel, Field, model_validator

from ai_legal_helper.case_intelligence.case_briefing import CaseEvidenceBriefing
from ai_legal_helper.case_intelligence.settlement_calculator import find_case_property_info
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
    candidate_statutes: List[str] = Field(default_factory=list, description="후보 법령 목록 (P0-09)")
    retrieved_statutes: List[str] = Field(default_factory=list, description="검색 확보된 법령 목록 (P0-09)")
    verified_statutes: List[str] = Field(default_factory=list, description="조문 본문 검증 완료된 법령 목록 (P0-09)")
    applicable_statutes: List[str] = Field(default_factory=list, description="요건사실 포섭 적용 법령 목록 (P0-09)")
    cited_statutes: List[str] = Field(default_factory=list, description="최종 인용 법령 목록 (P0-09)")
    missing_evidence: List[str] = Field(default_factory=list, description="해당 쟁점에 결여된 증빙 자료 요건")
    priority: str = Field("HIGH", description="상담 우선순위 (HIGH, MEDIUM, LOW)")

    @model_validator(mode="after")
    def sync_candidate_statutes(self) -> "LegalIssueTask":
        """후보 법령과 필수 법령 목록을 동기화하여 라이프사이클을 초기화한다 (P0-09)."""
        if not self.candidate_statutes and self.required_statutes:
            self.candidate_statutes = list(self.required_statutes)
        return self


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


def detect_unregistered_evidence_references(
    question: str,
    briefing: CaseEvidenceBriefing,
) -> List[str]:
    """의뢰인 질문 내 증거 참조 표현 중 현재 사건에 등록되지 않은 가공/미등록 증거를 식별한다 (P0-4.2 작업 B).

    특정 문자열(예: '99호증')을 하드코딩하지 않고, 증거 라벨, 문서명, 호증 표현, 파일 확장자 패턴을
    동적으로 추출하여 현재 사건 브리핑의 등록 증거 목록(UUID, 등록 라벨, 원본 파일명)과 대조한다.

    Args:
        question: 사용자 질의 텍스트.
        briefing: 현재 사건 증거 브리핑 모델.

    Returns:
        List[str]: 식별된 미등록 증거 참조 표현 목록.
    """
    if not question:
        return []

    # 현재 사건에 공적으로 등록된 식별자 집합 구축
    registered_labels: set[str] = {
        ev.evidence_label.upper() for ev in (briefing.evidences or []) if ev.evidence_label
    }
    registered_names: set[str] = {
        ev.document_name.lower() for ev in (briefing.evidences or []) if ev.document_name
    }
    registered_ids: set[str] = {
        ev.evidence_id.lower() for ev in (briefing.evidences or []) if ev.evidence_id
    }
    for lbl, reg in (briefing.source_registry or {}).items():
        if lbl:
            registered_labels.add(lbl.upper())
        if isinstance(reg, dict):
            if reg.get("document_name"):
                registered_names.add(reg["document_name"].lower())
            if reg.get("evidence_id"):
                registered_ids.add(reg["evidence_id"].lower())

    unregistered: List[str] = []

    # 1. '증거 N호증', '증거 A', '증거 99', '증거 제1호' 등 패턴 탐색
    ev_expr_matches = re.findall(
        r"(증거\s*(?:제\s*)?([0-9A-Za-z가-힣]+(?:호증|호|번)?|[A-Za-z]))",
        question,
    )
    for full_expr, sub_part in ev_expr_matches:
        clean_sub = sub_part.strip().upper()
        # E01, E02 등으로 정규화 시도
        m_num = re.search(r"(\d+)", clean_sub)
        cand_e_label = f"E{int(m_num.group(1)):02d}" if m_num else clean_sub

        is_registered = (
            cand_e_label in registered_labels
            or clean_sub in registered_labels
            or any(clean_sub.lower() in name for name in registered_names)
        )
        if not is_registered and full_expr not in unregistered:
            unregistered.append(full_expr)

    # 2. 'E99', 'e100' 등 단독 라벨 패턴 탐색
    e_label_matches = re.findall(r"\b([E|e]\d{1,3})\b", question)
    for lbl in e_label_matches:
        u_lbl = lbl.upper()
        if u_lbl not in registered_labels and u_lbl not in unregistered:
            unregistered.append(u_lbl)

    # 3. 문서 파일명 형식 (예: fake_doc.pdf) 탐색
    file_matches = re.findall(r"([가-힣A-Za-z0-9_\-]+\.(?:pdf|png|jpg|jpeg|docx|hwp|txt))", question, re.IGNORECASE)
    for f in file_matches:
        if f.lower() not in registered_names and f not in unregistered:
            unregistered.append(f)

    return unregistered


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

    # 0. 쟁점: 가공의 증거 라벨 식별 및 존재 부인 (P0-4.2 작업 B / SC01-V05 대응)
    unregistered_evs = detect_unregistered_evidence_references(q, briefing)
    if unregistered_evs:
        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_FAKE_CITATION",
                issue_title="가공의 증거 라벨 식별 및 존재 부인",
                legal_questions=[
                    f"의뢰인이 언급한 증거('{', '.join(unregistered_evs)}')가 현재 사건에 공적으로 등록되어 있는지 여부",
                    "존재하지 않는 가공 증거에 기재됐다고 주장된 사실의 효력 배제 및 등록 증거 대조",
                ],
                required_fact_keys=["등록증거목록", "가공증거부인"],
                relevant_fact_ids=[],
                relevant_evidence_ids=[],
                relevant_evidence_labels=[ev.evidence_label for ev in (briefing.evidences or [])][:5],
                required_statutes=[],
                missing_evidence=[f"현재 사건에 공식 등록된 정식 증거 목록 확인 ({', '.join(unregistered_evs)} 부존재)"],
                priority="HIGH",
            )
        )

    # [P0-1 핵심 개선] 의뢰인이 전문 법률 용어를 몰라도 상황을 진술했을 때(종합 분석 및 대처 요청)
    # 사건에 등록된 증거(계약서, 가압류 등)를 바탕으로 핵심 법률 쟁점을 포섭한다.
    is_comprehensive = (
        any(k in q_compact for k in ("상황", "대처", "어떻게", "분석", "종합", "전체", "법적으로", "알려"))
        and any(k in q_compact for k in ("보증금", "전세", "임대차", "임차"))
    )
    has_attachment_evidence = (
        any("가압류" in f.statement or "근저당" in f.statement or "압류" in f.statement for f in briefing.facts)
        or any(any(k in getattr(ev, "document_name", "").lower() for k in ("등기", "을구", "가압류")) for ev in (briefing.evidences or []))
    )

    # 1-1. 쟁점: 문자메시지에 의한 해지의사표시 도달 및 효력 (SC01-T03 대응)
    has_text_notice_mention = any(k in q_compact for k in ("문자", "카톡", "메시지", "메세지")) and any(k in q_compact for k in ("해지", "도달", "효력", "퇴거", "요청", "문자가"))
    if has_text_notice_mention:
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["계약기간", "해지", "문자", "퇴거", "도달", "답장", "분할", "제안"], briefing
        )
        for ev in briefing.evidences:
            if any(k in (ev.document_name or "") for k in ("문자", "통지", "통보", "퇴거", "해지", "답장", "분할", "제안")):
                if ev.evidence_label not in e_lbls:
                    e_lbls.append(ev.evidence_label)
                if ev.evidence_id not in e_ids:
                    e_ids.append(ev.evidence_id)

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_NOTICE_REACH",
                issue_title="문자메시지에 의한 해지의사표시 도달 및 효력",
                legal_questions=[
                    "문자메시지를 통한 계약 해지 및 보증금 반환 요청 의사표시가 법적으로 유효한가?",
                    "임대인의 후속 답장이나 통화로 해지 의사표시의 상대방 도달 사실이 객관적으로 입증되는가?",
                    "주택임대차보호법 제6조의2에 따라 임대인이 통지를 받은 날부터 3개월이 지나면 해지 효력이 확정되는가?",
                ],
                required_fact_keys=["문자발신일", "임대인답장", "도달사실", "3개월경과"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제6조의2", "민법 제111조"],
                missing_evidence=[],
                priority="HIGH",
            )
        )

    # 1. 쟁점: 임대차계약 종료 시점 및 효력 발생
    if is_comprehensive or (not has_text_notice_mention and any(k in q_compact for k in ("종료", "해지", "만료", "끝", "퇴거", "갱신", "반환", "돌려"))):
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
    if any(k in q_compact for k in ("가압류", "근저당", "저당", "담보", "순위", "권리관계", "등기")) or (is_comprehensive and has_attachment_evidence):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["가압류", "전입신고", "확정일자", "등기", "근저당", "주민등록"], briefing
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
                    "등재된 가압류·담보권의 접수일자와 임차인의 우선변제권 발생일자의 선후 순위는 어떠한가?",
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

    # 3. 쟁점: 경매 실행 시 보증금 회수 위험 및 배당 관계 (선순위 대항력 임차인의 배당요구권과 대항력 선택권)
    if any(k in q_compact for k in ("경매", "위험", "배당", "회수", "우선변제", "낙찰자", "인수", "인수시켜야")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["보증금", "확정일자", "가압류", "배당", "시세", "대항력", "전입", "점유"], briefing
        )
        for ev in briefing.evidences:
            if any(k in (ev.document_name or "") for k in ("계약서", "가압류", "확정일자", "전입", "점유", "카드", "열쇠")):
                if ev.evidence_label not in e_lbls:
                    e_lbls.append(ev.evidence_label)
                if ev.evidence_id not in e_ids:
                    e_ids.append(ev.evidence_id)

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_AUCTION_STRATEGY",
                issue_title="선순위 대항력 임차인의 배당요구권과 대항력 선택권",
                legal_questions=[
                    "선순위 대항요건(주택 인도 및 전입신고)과 확정일자를 갖춘 임차인에게 배당요구권과 대항력 선택권이 모두 인정되는가?",
                    "경매 개시 결정 시 배당요구 종기 내 배당요구로 매각대금에서 우선배당받는 방안과, 배당요구 없이 대항력을 유지하여 낙찰자에게 전액 인수시키는 방안의 법률적 차이는 무엇인가?",
                    f"{find_case_property_info(briefing)[1]}의 최근 실거래 시세 및 예상 낙찰가율에 비추어 전액 배당 회수가 불확실한 경우 대항력 인수 전략이 안전한가?",
                ],
                required_fact_keys=["대항요건구비일", "확정일자일", "배당요구종기", "선순위채권총액", "시세/낙찰가"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=[
                    "주택임대차보호법 제3조 제1항",
                    "주택임대차보호법 제3조의2 제2항",
                    "주택임대차보호법 제3조의5",
                    "민사집행법 제88조",
                    "민사집행법 제148조",
                ],
                missing_evidence=["정확한 시세 감정평가서", "선순위 채권 전수 확인 내역"],
                priority="HIGH",
            )
        )
        # 경매 배당 위험 분석 쟁점 병행 지원 (하위 호환성 및 세부 배당 순위 검토)
        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_AUCTION_DIVIDEND_RISK",
                issue_title="경매 실행 시 배당 순위 및 보증금 회수 위험",
                legal_questions=[
                    "경매 매각 시 선순위 대항력 임차인의 배당 순위는 어떠한가?",
                    "전액 배당받지 못한 미배당 보증금에 대해 매수인(낙찰자)에게 대항하여 반환받을 수 있는가?",
                ],
                required_fact_keys=["대항요건구비일", "확정일자일", "배당요구종기", "선순위채권총액"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=[
                    "주택임대차보호법 제3조의2",
                    "주택임대차보호법 제3조의5",
                    "민사집행법 제148조",
                ],
                missing_evidence=[],
                priority="HIGH",
            )
        )

    # 4. 쟁점: 이사 전 권리보전 절차 (임차권등기명령, 대항력 유지)
    if is_comprehensive or any(k in q_compact for k in ("이사", "보전", "임차권등기", "대항력", "점유", "전입유지", "짐", "열쇠", "비밀번호", "퇴거", "비우", "나가")):
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

    # 5. 쟁점: 임대인의 분할반환 제안의 법적 의미 및 대응 (임대인의 일방적 분할변제 제안의 구속력 및 위험성)
    # [P0-VER-01] "처분할", "구분할", "배분할" 등 동사 활용형에 의한 "분할" 오탐 방지 및 분할변제 문맥 확인
    has_installment_mention = (
        any(k in q_compact for k in ("분할반환", "분할변제", "분할지급", "분할상환", "일부반환", "1년뒤", "일부만먼저", "나누어서"))
        or (bool(re.search(r"(?<!처)(?<!구)(?<!배)분할", q_compact)) and any(k in q_compact for k in ("반환", "변제", "지급", "보증금", "돈", "제안", "합의", "동의")))
        or (any(k in q_compact for k in ("제안", "합의", "동의")) and any(k in q_compact for k in ("보증금", "반환", "1년", "나중", "임대인", "집주인")))
    )
    if has_installment_mention:
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
                issue_title="임대인의 일방적 분할변제 제안의 구속력 및 위험성",
                legal_questions=[
                    "임대인의 일방적 분할반환 및 잔액 1년 유예 제안을 임차인이 수용할 법적 의무가 있는가?",
                    "민법 제536조에 따라 임대인의 보증금 반환의무와 임차인의 목적물 인도의무는 동시이행 관계에 있는가?",
                    "가압류가 설정된 상태에서 담보 없는 분할 변제 약속을 거부하고 전액 일시반환 및 지연손해금을 청구할 수 있는가?",
                ],
                required_fact_keys=["분할제안내용", "임차인거절의사표시", "동시이행항변권", "전액반환채무"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["민법 제536조", "민법 제460조", "민법 제468조", "민법 제397조", "소송촉진 등에 관한 특례법 제3조"],
                missing_evidence=[],
                priority="MEDIUM",
            )
        )

    # 5-2. 쟁점: 내용증명 우편의 법적 효과 및 필수적 기재사항 (SC01-T10 대응)
    if any(k in q_compact for k in ("내용증명", "배달증명", "최고장", "우체국")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["보증금", "종료", "해지", "내용증명", "최고"], briefing
        )
        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_PROOF_OF_CONTENTS",
                issue_title="내용증명 우편의 법적 효과 및 필수적 기재사항",
                legal_questions=[
                    "내용증명 우편이 갖는 법적 증명력과 이행최고 효력은 무엇인가?",
                    "내용증명에 반드시 포함되어야 할 필수적 기재사항(계약내역, 해지통고, 반환기한, 동시이행 인도준비, 지연손해금)은 무엇인가?",
                    "우체국 배달증명 서비스를 통해 도달 일자를 객관적으로 입증하는 절차는 어떠한가?",
                ],
                required_fact_keys=["계약종료경위", "보증금전액", "동시이행제공", "도달입증"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제6조의2", "민법 제536조", "민법 제111조"],
                missing_evidence=[],
                priority="HIGH",
            )
        )

    # 5-3. 쟁점: 임대인의 자력 상실 및 연락 두절 시 사법절차 전환 (SC01-T11 대응)
    if any(k in q_compact for k in ("연락두절", "연락이두절", "연락안됨", "연락도잘안", "연락이잘안", "잠적", "파산", "회생", "자력악화", "자력상실", "대출거절", "추가대출도거절")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["보증금", "가압류", "대출", "연락"], briefing
        )
        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_COMMUNICATION_BREAKDOWN",
                issue_title="임대인의 자력 상실 및 연락 두절 시 사법절차 전환",
                legal_questions=[
                    "임대인의 자력 상실 및 연락 두절 상황에서 임의 변제를 기다리지 않고 즉시 사법 절차로 전환해야 하는 법적 필요성은 무엇인가?",
                    "임차권등기명령 신청과 보증금반환청구 지급명령 또는 정식 소송을 병행하여 조속히 집행권원을 확보하는 절차는 어떠한가?",
                    "임대인의 다른 일반재산(다른 부동산, 예금 등)에 대한 가압류 보전처분 필요성은 어떠한가?",
                ],
                required_fact_keys=["연락두절사실", "자력상실정황", "집행권원필요성"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제3조의3", "민사소송법 제462조", "민사집행법 제88조"],
                missing_evidence=[],
                priority="HIGH",
            )
        )

    # 5-4. 쟁점: 가압류 상태에서의 무담보 단순 확약서 수용 위험성 (SC01-V03 대응)
    if any(k in q_compact for k in ("확약서", "공증없이", "공증이없이", "합의하고기다려", "기다려주는게")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["보증금", "가압류", "확약서", "1년", "공증"], briefing
        )
        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_UNSECURED_AGREEMENT",
                issue_title="가압류 상태에서의 무담보 단순 확약서 수용 위험성",
                legal_questions=[
                    "가압류가 걸려 있는 상태에서 공증이나 물적 담보 없는 단순 확약서만 받고 기다려주는 합의의 법률상 위험성은 무엇인가?",
                    "임대인의 보증금 반환의무와 임차인의 인도 의무가 동시이행 관계(민법 제536조)에 있음에도 단순 확약서를 수용할 법적 의무가 있는가?",
                    "단순 확약 제안을 단호히 거절하고 집행권원 확보를 위한 법적 절차에 즉시 착수해야 하는 이유는 무엇인가?",
                ],
                required_fact_keys=["가압류등재사실", "무담보확약서", "동시이행관계"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["민법 제536조", "주택임대차보호법 제3조"],
                missing_evidence=[],
                priority="HIGH",
            )
        )

    # 5-5. 쟁점: 새 임차인 유치 조건부 반환의 부당성 (SC01-V08 대응)
    if any(k in q_compact for k in ("새세입자", "다음세입자", "신규세입자", "새로운세입자")) and any(k in q_compact for k in ("기다려", "의무", "기다려야", "들어올때까지")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["보증금", "종료", "새세입자", "신규임차인"], briefing
        )
        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_NO_WAIT_DUTY",
                issue_title="새 임차인 유치 조건부 반환의 부당성",
                legal_questions=[
                    "임대차계약 종료 시 '새 세입자가 들어올 때까지 기다려야 한다'는 임대인의 주장에 법적 근거가 있는가?",
                    "임대인의 보증금 반환의무와 임차인의 목적물 인도의무가 동시이행 관계(민법 제536조)에 비추어 대기 의무가 부존재하는 이유는 무엇인가?",
                    "임대인의 부당한 주장을 일축하고 보증금 전액 반환 및 지연손해금을 청구할 수 있는가?",
                ],
                required_fact_keys=["계약종료사실", "새세입자유치조건의부당성", "동시이행관계"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["민법 제536조", "주택임대차보호법 제3조"],
                missing_evidence=[],
                priority="HIGH",
            )
        )

    # 6-1. 쟁점: 소송 및 보전처분을 위한 필수 증빙 서류 보완 (SC01-T08 대응)
    if any(k in q_compact for k in ("서류", "준비서류", "신청서류", "필요서류", "구비서류", "추가로확인", "발급받아야")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["계약서", "전입", "확정일자", "등기", "서류"], briefing
        )
        for ev in briefing.evidences:
            if any(k in (ev.document_name or "") for k in ("계약서", "전입", "확정일자", "등기")):
                if ev.evidence_label not in e_lbls:
                    e_lbls.append(ev.evidence_label)
                if ev.evidence_id not in e_ids:
                    e_ids.append(ev.evidence_id)

        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_EVIDENCE_GAPS",
                issue_title="소송 및 보전처분을 위한 필수 증빙 서류 보완",
                legal_questions=[
                    "임차권등기명령 신청 및 보증금반환청구 소송에 필요한 법정 필수 서류는 무엇인가?",
                    "대법원 인터넷등기소를 통해 목적물 등기사항전부증명서(말소사항 포함)를 발급받아야 하는 이유는 무엇인가?",
                    "거래은행 전세대출 담당자에게 반환보증 가입 여부를 최종 확인해야 하는 이유는 무엇인가?",
                ],
                required_fact_keys=["임대차계약서", "주민등록초본", "확정일자부여현황", "등기사항전부증명서"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제3조의3", "주택임대차보호법 제3조"],
                missing_evidence=["최신 등기사항전부증명서", "전세대출 반환보증 가입 확인 문서"],
                priority="HIGH",
            )
        )

    # 6. 쟁점: 필요한 추가 증거 및 실무적 다음 행동
    is_lease_context = (
        any(k in q_compact for k in ("보증금", "전세", "임대차", "임차", "집주인", "세입자", "퇴거", "이사"))
        or "임대차" in (briefing.case_type or "")
        or "임대차" in (briefing.title or "")
        or "보증금" in (briefing.title or "")
        or any(lbl.startswith("E") for lbl in briefing.source_registry)
    )
    if is_lease_context and (is_comprehensive or any(k in q_compact for k in ("추가증거", "다음행동", "미확인", "보완", "행동", "조치", "대처", "단계별"))):
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
                required_statutes=["주택임대차보호법 제3조", "주택임대차보호법 제3조의3"],
                missing_evidence=missing_props,
                priority="HIGH",
            )
        )

    # 7. 쟁점: 허위 법령 배제 및 형사처벌/민사 권리구제 (SC01-V04 대응)
    if any(k in q_compact for k in ("99조", "처벌", "형사", "징역", "고소", "사기", "벌금")):
        f_ids, e_ids, e_lbls = _match_facts_and_evidences(
            ["보증금", "계약기간", "미반환"], briefing
        )
        issues.append(
            LegalIssueTask(
                issue_id="ISSUE_FAKE_STATUTE",
                issue_title="존재하지 않는 가공 조문 및 민형사 구분 권리구제 절차",
                legal_questions=[
                    "주택임대차보호법에 임대인을 형사처벌하는 조항(제99조 등)이 존재하는가?",
                    "단순 보증금 미반환 행위가 형사상 사기죄 등 범죄에 해당하는가?",
                    "보증금을 실질적으로 회수하기 위해 취해야 할 올바른 법적 절차는 무엇인가?",
                ],
                required_fact_keys=["보증금미반환", "계약체결경위", "변제자력"],
                relevant_fact_ids=f_ids,
                relevant_evidence_ids=e_ids,
                relevant_evidence_labels=sorted(e_lbls),
                required_statutes=["주택임대차보호법 제3조의2", "민사집행법 제41조", "형법 제347조"],
                missing_evidence=["기망행위 입증 자료", "계약 당시 편취 고의 증빙"],
                priority="HIGH",
            )
        )

    # 8. 일반 질문 또는 기타 도메인 (노동, 대여금 등) 기본 폴백 쟁점
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
