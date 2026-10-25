# -*- coding: utf-8 -*-
"""
모듈명: case_briefing.py

[모듈 개요]
법률 상담(Legal Consultation) 실행 시 등록된 사건(Case)의 증거, 사실관계(Facts),
당사자(Parties), 타임라인(Timeline/Events), 증거 신뢰성 평가(EvidenceAssessment),
사실 확정 상태(FactAdjudication), 증거 공백(EvidenceGap) 및 실제 대립 상충(GENUINELY_DISPUTED)을
단일 구조화 브리핑 모델(CaseEvidenceBriefing)로 통합 구성하는 모듈.

[주요 기능]
1. 증거 문서 식별 라벨(E01, E02...)의 안정적 부여 및 EvidenceDocument ID와의 1:1 매핑
2. FactAdjudication 기반 사실 신뢰 수준(EVIDENCE_SUPPORTED, CORROBORATED 등) 구조화
3. 증거 공백(EvidenceGap) 및 실제 분쟁 항목 선별 브리핑
4. Synthesizer, Verifier, Agent 및 UI에 공급 가능한 표준 Source Registry 구성
"""

from typing import List, Dict, Any, Optional
import re
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai_legal_helper.database.models import (
    Case,
    Party,
    Fact,
    Event,
    EvidenceDocument,
    EvidenceClaim,
    EvidenceAssessment,
    FactAdjudication,
    EvidenceGap,
)
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

# 파일명에서 E01, E02 등 기존 증거 번호 접두사를 파싱하는 정규식
_EVIDENCE_LABEL_REGEX = re.compile(r"^(E\d{1,3})(?:_|\s|-|\.)", re.IGNORECASE)


class EvidenceItemBrief(BaseModel):
    """개별 증거 문서 요약 정보 모델."""
    evidence_id: str = Field(..., description="증거 문서 UUID")
    evidence_label: str = Field(..., description="안정적인 표시용 증거 번호 (예: E01, E02)")
    document_name: str = Field(..., description="원본 파일명")
    document_type: str = Field("GENERAL", description="문서 유형 (계약서, 영수증, 등기부 등)")
    status: str = Field("UPLOADED", description="추출 및 검토 상태")
    claim_count: int = Field(0, description="해당 문서에서 추출된 주장/사실 건수")
    uploaded_at: Optional[str] = Field(None, description="업로드 일시 (KST)")


class PartyItemBrief(BaseModel):
    """사건 당사자 요약 정보 모델."""
    party_id: str = Field(..., description="당사자 UUID")
    name: str = Field(..., description="당사자 성명 또는 기관명")
    role: str = Field("당사자", description="법적 역할 (임대인, 임차인, 채권자 등)")
    verification_status: str = Field("UNVERIFIED", description="신원 검증 상태")
    related_fact_ids: List[str] = Field(default_factory=list, description="연관 Fact ID 목록")
    related_claim_ids: List[str] = Field(default_factory=list, description="연관 Claim ID 목록")


class FactItemBrief(BaseModel):
    """확정 및 심리 사실관계 요약 모델."""
    fact_id: str = Field(..., description="사실 UUID")
    statement: str = Field(..., description="정규화된 사실 진술문")
    fact_type: str = Field("GENERAL", description="사실 유형 (AMOUNT, DATE, ACTION 등)")
    adjudication_status: str = Field(
        "UNASSESSED",
        description="사실 확정 상태 (UNASSESSED, EVIDENCE_SUPPORTED, CORROBORATED, PARTY_ALLEGED, EVIDENCE_INCOMPLETE, GENUINELY_DISPUTED)"
    )
    source_evidence_id: Optional[str] = Field(None, description="근거 증거 문서 ID")
    evidence_label: Optional[str] = Field(None, description="근거 증거 번호 (예: E01)")
    document_name: Optional[str] = Field(None, description="근거 증거 문서명")
    confidence: float = Field(1.0, description="신뢰도 점수 (0.0~1.0)")
    supporting_evidence_labels: List[str] = Field(default_factory=list, description="지지하는 모든 증거 번호 목록")
    trust_level: str = Field(
        "USER_ALLEGED",
        description="P0-3 논리적 사실 상태 (USER_ALLEGED, EVIDENCE_PENDING, EVIDENCE_SUPPORTED, DISPUTED, SUPERSEDED)"
    )


class TimelineItemBrief(BaseModel):
    """시계열 타임라인 사건 요약 모델."""
    event_id: str = Field(..., description="이벤트 UUID")
    title: str = Field(..., description="사건 명칭")
    event_date: Optional[str] = Field(None, description="발생 또는 예정 일자 (YYYY-MM-DD)")
    event_type: str = Field("GENERAL", description="사건 분류 (계약, 지급, 통지 등)")
    occurrence_status: str = Field("ACTUAL", description="ACTUAL(실제발생), SCHEDULED(예정), REQUESTED(요청)")
    related_fact_ids: List[str] = Field(default_factory=list, description="근거 Fact ID 목록")
    evidence_labels: List[str] = Field(default_factory=list, description="관련 증거 번호 목록")


class EvidenceGapBrief(BaseModel):
    """증거 공백 및 보완 권고 모델."""
    gap_id: str = Field(..., description="증거 공백 UUID")
    gap_type: str = Field(..., description="공백 유형 (HUG_INSURANCE_CONFIRMATION_GAP 등)")
    target_proposition: str = Field(..., description="입증이 결여된 대상 사실 명제")
    description: Optional[str] = Field(None, description="상세 보완 필요 사유")
    recommended_action: Optional[str] = Field(None, description="권장되는 보완 행동 지침")
    priority: str = Field("MEDIUM", description="보완 우선순위 (HIGH, MEDIUM, LOW)")


class DisputedConflictBrief(BaseModel):
    """실제 대립 상충(GENUINELY_DISPUTED) 요약 모델."""
    fact_id: str = Field(..., description="상충 대상 Fact ID")
    statement: str = Field(..., description="확정 사실 진술")
    opposing_statement: Optional[str] = Field(None, description="대립하는 타 증거 주장 진술")
    evidence_label_a: Optional[str] = Field(None, description="첫 번째 증거 번호")
    evidence_label_b: Optional[str] = Field(None, description="상반된 두 번째 증거 번호")
    reason: str = Field(..., description="실제 모순 사유")


class CaseEvidenceBriefing(BaseModel):
    """
    상담 워크플로우에 직접 주입되는 종합 사건 증거 브리핑 모델.
    
    사건의 기본 정보, 당사자, 확정 사실, 타임라인, 증거 목록, 증거 공백,
    대립 상충 및 LLM 프롬프트 주입용 텍스트 서머리를 통합 관리한다.
    """
    case_id: str = Field(..., description="사건 UUID")
    title: str = Field(..., description="사건 제목")
    case_type: Optional[str] = Field(None, description="사건 유형 (주택임대차 등)")
    status: str = Field("OPEN", description="사건 상태")
    version: int = Field(1, description="사건 버전")
    parties: List[PartyItemBrief] = Field(default_factory=list, description="사건 당사자 목록")
    facts: List[FactItemBrief] = Field(default_factory=list, description="심리 및 확정 사실관계 목록")
    timeline: List[TimelineItemBrief] = Field(default_factory=list, description="시간순 이벤트 목록")
    evidences: List[EvidenceItemBrief] = Field(default_factory=list, description="등록 증거 문서 목록")
    evidence_gaps: List[EvidenceGapBrief] = Field(default_factory=list, description="증거 공백 목록")
    genuinely_disputed: List[DisputedConflictBrief] = Field(default_factory=list, description="실제 상충 분쟁 목록")
    source_registry: Dict[str, Dict[str, Any]] = Field(default_factory=dict, description="증거 인용 레지스트리")
    formatted_summary: str = Field("", description="LLM Synthesizer/Agent 주입용 정돈된 브리핑 텍스트")

    def to_prompt_context(self) -> str:
        """프롬프트 주입용 브리핑 텍스트를 반환한다."""
        return self.formatted_summary



def assign_evidence_labels(documents: List[EvidenceDocument]) -> Dict[str, str]:
    """증거 문서 목록에 대해 결정론적이고 안정적인 표시용 증거 번호(E01, E02...)를 부여한다.

    1. 파일명에 이미 E01, E02 등의 번호가 포함되어 있다면 해당 라벨을 최우선 보존한다.
    2. 번호가 없는 파일은 업로드 일시 및 ID 오름차순으로 순차 번호를 부여하여 충돌을 방지한다.

    Args:
        documents: 증거 문서 ORM 엔티티 목록.

    Returns:
        Dict[str, str]: evidence_id -> evidence_label (예: "ff554328" -> "E01")
    """
    label_map: Dict[str, str] = {}
    used_indices = set()

    # 1차 패스: 파일명 접두사에서 기존 E번호 추출
    unlabeled_docs = []
    for doc in documents:
        fname = doc.original_filename or ""
        m = _EVIDENCE_LABEL_REGEX.match(fname.strip())
        if m:
            lbl = m.group(1).upper()
            label_map[doc.id] = lbl
            try:
                num = int(lbl[1:])
                used_indices.add(num)
            except ValueError:
                pass
        else:
            unlabeled_docs.append(doc)

    # 2차 패스: 접두사가 없는 문서는 빈 번호 순차 할당
    unlabeled_docs.sort(key=lambda d: (str(d.uploaded_at or ""), d.id))
    next_idx = 1
    for doc in unlabeled_docs:
        while next_idx in used_indices:
            next_idx += 1
        lbl = f"E{next_idx:02d}"
        label_map[doc.id] = lbl
        used_indices.add(next_idx)
        next_idx += 1

    return label_map


def build_case_evidence_briefing(
    db: Session,
    case_id: str,
    question: str = "",
    resolved_query: Optional[str] = None,
) -> CaseEvidenceBriefing:
    """PostgreSQL 데이터베이스로부터 사건의 전체 증거 및 사실 확정 데이터를 구조화하여 브리핑 모델을 생성한다.

    Section 4 (P0-01) 및 Section 5 (P0-02) 요구사항 반영:
    1. Case, Party, Fact, Event, EvidenceDocument, EvidenceClaim, EvidenceAssessment, FactAdjudication, EvidenceGap 조회
    2. 안정적인 증거 번호(E01, E02...) 부여 및 1:1 매핑
    3. FactAdjudication 상태에 따른 증명력 구분(EVIDENCE_SUPPORTED vs EVIDENCE_INCOMPLETE vs PARTY_ALLEGED)
    4. 실제 상충(GENUINELY_DISPUTED)과 증거 공백(EvidenceGap) 분리
    5. Synthesizer와 Verifier가 참조할 수 있는 표준 source_registry 구성
    6. LLM이 바로 읽을 수 있는 formatted_summary 문자열 조립

    Args:
        db: SQLAlchemy DB 세션.
        case_id: 대상 사건 UUID.
        question: 사용자 법률 상담 질문 원문.
        resolved_query: 의도 분석 및 대화 맥락이 반영된 보강 질문 (선택).

    Returns:
        CaseEvidenceBriefing: 구조화된 사건 증거 브리핑 모델.
    """
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        logger.warning(f"[CASE_BRIEFING] 사건을 찾을 수 없음: case_id={case_id}")
        return CaseEvidenceBriefing(
            case_id=case_id,
            title="미등록 사건",
            formatted_summary="사건 정보가 존재하지 않습니다."
        )

    # 1. 증거 문서 목록 및 라벨 매핑
    doc_records = (
        db.query(EvidenceDocument)
        .filter(EvidenceDocument.case_id == case_id)
        .all()
    )
    label_map = assign_evidence_labels(doc_records)
    doc_dict = {d.id: d for d in doc_records}

    # 증거별 Claim 건수 집계
    claim_counts: Dict[str, int] = {}
    claims = db.query(EvidenceClaim).filter(EvidenceClaim.case_id == case_id).all()
    for c in claims:
        claim_counts[c.evidence_id] = claim_counts.get(c.evidence_id, 0) + 1

    evidence_items: List[EvidenceItemBrief] = []
    for d in doc_records:
        evidence_items.append(
            EvidenceItemBrief(
                evidence_id=d.id,
                evidence_label=label_map.get(d.id, "E??"),
                document_name=d.original_filename,
                document_type=d.source_kind or "GENERAL",
                status=d.status or "UPLOADED",
                claim_count=claim_counts.get(d.id, 0),
                uploaded_at=str(d.uploaded_at) if d.uploaded_at else None,
            )
        )
    evidence_items.sort(key=lambda x: x.evidence_label)

    # 2. 당사자 정보
    parties_records = db.query(Party).filter(Party.case_id == case_id).all()
    party_items: List[PartyItemBrief] = []
    for p in parties_records:
        party_items.append(
            PartyItemBrief(
                party_id=p.id,
                name=p.name,
                role=p.role or "당사자",
                verification_status=p.verification_status or "UNVERIFIED",
                related_fact_ids=p.related_fact_ids or [],
                related_claim_ids=p.related_claim_ids or [],
            )
        )

    # 3. 사실 확정(FactAdjudication) 및 사실관계(Fact) 정보
    facts_records = db.query(Fact).filter(Fact.case_id == case_id).all()
    adjudication_records = (
        db.query(FactAdjudication)
        .filter(FactAdjudication.case_id == case_id)
        .all()
    )
    adj_by_fact_id = {a.fact_id: a for a in adjudication_records if a.fact_id}

    fact_items: List[FactItemBrief] = []
    disputed_items: List[DisputedConflictBrief] = []

    for f in facts_records:
        adj = adj_by_fact_id.get(f.id)
        # FactAdjudication이 없는 경우 검증되지 않은 사실(UNASSESSED)로 명시하여 허위 입증 승격 방지 (P0-07)
        adj_status = adj.adjudication_status if adj else "UNASSESSED"
        source_doc_id = f.source_ref if f.source_ref in doc_dict else None
        source_doc = doc_dict.get(source_doc_id) if source_doc_id else None
        lbl = label_map.get(source_doc_id) if source_doc_id else None

        sup_labels = []
        if adj and adj.supporting_evidence_ids:
            for seid in adj.supporting_evidence_ids:
                if seid in label_map:
                    sup_labels.append(label_map[seid])
        if lbl and lbl not in sup_labels:
            sup_labels.append(lbl)

        from ai_legal_helper.case_intelligence.fact_adjudicator import map_to_fact_trust_level
        trust_lvl = map_to_fact_trust_level(
            verification_status=f.verification_status,
            adjudication_status=adj_status,
            source_type=f.source_type,
        )

        fact_brief = FactItemBrief(
            fact_id=f.id,
            statement=f.statement,
            fact_type=f.fact_type or "GENERAL",
            adjudication_status=adj_status,
            source_evidence_id=source_doc_id,
            evidence_label=lbl,
            document_name=source_doc.original_filename if source_doc else None,
            confidence=f.confidence or 1.0,
            supporting_evidence_labels=sup_labels,
            trust_level=trust_lvl,
        )
        fact_items.append(fact_brief)

        # 실제 대립 상충 항목 별도 수집
        if adj_status == "GENUINELY_DISPUTED" or trust_lvl == "DISPUTED":
            disputed_items.append(
                DisputedConflictBrief(
                    fact_id=f.id,
                    statement=f.statement,
                    opposing_statement=adj.adjudication_basis if adj else None,
                    evidence_label_a=lbl,
                    reason=adj.adjudication_basis or "실제 상충 대립 사실" if adj else "상충",
                )
            )

    # 4. 타임라인(Events)
    event_records = (
        db.query(Event)
        .filter(Event.case_id == case_id)
        .order_by(Event.event_date.asc().nulls_last())
        .all()
    )
    timeline_items: List[TimelineItemBrief] = []
    for ev in event_records:
        rel_labels = []
        for fid in (ev.related_fact_ids or []):
            matching_fact = next((item for item in fact_items if item.fact_id == fid), None)
            if matching_fact and matching_fact.evidence_label:
                if matching_fact.evidence_label not in rel_labels:
                    rel_labels.append(matching_fact.evidence_label)

        timeline_items.append(
            TimelineItemBrief(
                event_id=ev.id,
                title=ev.title,
                event_date=ev.event_date,
                event_type=ev.event_type or "GENERAL",
                occurrence_status=ev.occurrence_status or "ACTUAL",
                related_fact_ids=ev.related_fact_ids or [],
                evidence_labels=rel_labels,
            )
        )

    # 5. 증거 공백(EvidenceGap)
    gap_records = (
        db.query(EvidenceGap)
        .filter(EvidenceGap.case_id == case_id, EvidenceGap.is_resolved.is_(False))
        .all()
    )
    gap_items: List[EvidenceGapBrief] = []
    for g in gap_records:
        gap_items.append(
            EvidenceGapBrief(
                gap_id=g.id,
                gap_type=g.gap_type,
                target_proposition=g.target_proposition,
                description=g.description,
                recommended_action=g.recommended_action,
                priority=g.priority or "MEDIUM",
            )
        )

    # 6. Source Registry 구성 (인용 검증 및 Verifier/Synthesizer 공통 참조, P0-2)
    source_registry: Dict[str, Dict[str, Any]] = {}
    for ev_item in evidence_items:
        entry = {
            "source_id": f"EVIDENCE:{ev_item.evidence_label}",
            "evidence_id": ev_item.evidence_id,
            "evidence_label": ev_item.evidence_label,
            "label": ev_item.evidence_label,
            "document_name": ev_item.document_name,
            "filename": ev_item.document_name,
            "file": ev_item.document_name or ev_item.evidence_label,
            "title": ev_item.document_name or ev_item.evidence_label,
            "source_type": "CASE_EVIDENCE",
            "citation_tag": f"[{ev_item.evidence_label}]",
        }
        source_registry[ev_item.evidence_label] = entry
        source_registry[ev_item.evidence_id] = entry
        if ev_item.document_name:
            source_registry[ev_item.document_name] = entry

    # 7. LLM 주입용 정돈된 브리핑 텍스트(formatted_summary) 생성
    summary_lines = []
    summary_lines.append(f"### [사건 기본 브리핑: {case.title} (ID: {case.id[:8]})]")
    summary_lines.append(f"- 사건 유형: {case.case_type or '일반 법률상담'} (상태: {case.status})")

    # 등록 증거 목록
    if evidence_items:
        summary_lines.append("\n#### 1. 등록된 사건 증거 목록 (Source Registry)")
        for ev in evidence_items:
            summary_lines.append(f"- [{ev.document_name}] ({ev.document_type}, 추출사실: {ev.claim_count}건)")

    # 당사자 정보
    if party_items:
        summary_lines.append("\n#### 2. 확정 당사자 (Parties)")
        for p in party_items:
            summary_lines.append(f"- {p.role}: {p.name} (검증상태: {p.verification_status})")

    # 확정 사실관계 (증거 신뢰 수준별 구분)
    if fact_items:
        summary_lines.append("\n#### 3. 심리 확정 사실관계 (Facts & Evidence Grounding)")
        supported_facts = [f for f in fact_items if f.adjudication_status in ("EVIDENCE_SUPPORTED", "CORROBORATED")]
        alleged_facts = [f for f in fact_items if f.adjudication_status == "PARTY_ALLEGED"]
        incomplete_facts = [f for f in fact_items if f.adjudication_status == "EVIDENCE_INCOMPLETE"]

        if supported_facts:
            summary_lines.append("  [증거로 입증된 사실 (EVIDENCE_SUPPORTED / CORROBORATED)]")
            for sf in supported_facts:
                doc_lbl = sf.document_name or sf.evidence_label
                cite = f"[{doc_lbl}]" if doc_lbl else ""
                summary_lines.append(f"  * {sf.statement} {cite} (상태: {sf.adjudication_status})")

        if alleged_facts:
            summary_lines.append("  [당사자 주장 사실 (PARTY_ALLEGED, 객관적 증빙 대기)]")
            for af in alleged_facts:
                summary_lines.append(f"  * {af.statement}")

        if incomplete_facts:
            summary_lines.append("  [자료 미비 사실 (EVIDENCE_INCOMPLETE, 추가 확인 필요)]")
            for inc in incomplete_facts:
                summary_lines.append(f"  * {inc.statement}")

    # 타임라인
    if timeline_items:
        summary_lines.append("\n#### 4. 사건 타임라인 (Timeline)")
        for t in timeline_items:
            dt_str = t.event_date or "일자미상"
            cites = " ".join([f"[{lbl}]" for lbl in t.evidence_labels])
            summary_lines.append(f"- {dt_str}: {t.title} ({t.occurrence_status}) {cites}")

    # 증거 공백 및 보완 권고
    if gap_items:
        summary_lines.append("\n#### 5. 보완이 필요한 증거 공백 (Evidence Gaps)")
        for g in gap_items:
            summary_lines.append(f"- [{g.priority}] {g.target_proposition} -> 권장조치: {g.recommended_action or '관련 서류 확인'}")

    # 실제 대립 상충
    if disputed_items:
        summary_lines.append("\n#### 6. 실제 대립 상충 쟁점 (GENUINELY_DISPUTED)")
        for dis in disputed_items:
            summary_lines.append(f"- {dis.statement} (사유: {dis.reason})")

    formatted_summary_text = "\n".join(summary_lines)

    return CaseEvidenceBriefing(
        case_id=case_id,
        title=case.title,
        case_type=case.case_type,
        status=case.status,
        version=case.version or 1,
        parties=party_items,
        facts=fact_items,
        timeline=timeline_items,
        evidences=evidence_items,
        evidence_gaps=gap_items,
        genuinely_disputed=disputed_items,
        source_registry=source_registry,
        formatted_summary=formatted_summary_text,
    )
