# -*- coding: utf-8 -*-
"""
모듈명: document_workflow.py

[모듈 개요]
법률 문서 초안을 생성, 검증, 관리하기 위한 LangGraph 기반 워크플로우를 정의한다.

[노드 구성]
1. context: 사건 정보, 사실, 증거 로드
2. requirements: 문서 유형별 필수 요건 검사
3. generation: 구조화된 초안(Pydantic) 생성
4. verification: 검증 (근거 확인, 환각 방지)
5. review_gate: 승인 및 DB 이관 판정
"""

from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

import re
from ai_legal_helper.database.session import SessionLocal
from ai_legal_helper.database.models import (
    Case, LegalDocument, DocumentRevision, Fact, Event, EvidenceClaim, Party
)
from ai_legal_helper.llm.gateway import get_llm
from langchain_core.prompts import PromptTemplate
from ai_legal_helper.observability.logging_config import get_logger
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span

logger = get_logger(__name__)

class DocumentState(BaseModel):
    case_id: str
    document_type: str
    action_id: Optional[str] = None
    context_text: str = ""
    requirements_met: bool = False
    missing_info: List[str] = []
    draft_content: str = ""
    structured_content: Dict[str, Any] = {}
    verification_status: str = "UNVERIFIED"
    verification_warnings: List[str] = []
    revision_id: Optional[str] = None

class DocumentDraftSchema(BaseModel):
    title: str = Field(description="문서 제목")
    sender: str = Field(description="발신인 정보")
    receiver: str = Field(description="수신인 정보")
    body_sections: List[Dict[str, str]] = Field(description="본문의 각 섹션 (제목과 내용)")
    conclusion: str = Field(description="결론 및 요구사항")
    full_content: str = Field(description="전체 렌더링된 텍스트 초안")

@trace
def context_node(state: DocumentState) -> DocumentState:
    """사건 기본 정보, 당사자, 확정 사실(Fact), 타임라인(Event), 승인된 증거(EvidenceClaim)를 조회하여 문서 생성 컨텍스트를 구성한다."""
    db = SessionLocal()
    try:
        case = db.query(Case).filter(Case.id == state.case_id).first()
        parties = db.query(Party).filter(Party.case_id == state.case_id).all()
        facts = db.query(Fact).filter(Fact.case_id == state.case_id).all()
        events = db.query(Event).filter(Event.case_id == state.case_id).order_by(Event.event_date).all()
        approved_claims = db.query(EvidenceClaim).filter(
            EvidenceClaim.case_id == state.case_id,
            EvidenceClaim.review_status.in_(["APPROVED", "EDITED"]),
        ).all()

        title = case.title if case else "미상 사건"
        parts = [f"[사건: {title}]"]
        if case and case.description:
            parts.append(f"[사건 개요]\n{case.description}")
        if parties:
            parts.append("[당사자]")
            parts.extend([f"- {p.role or '당사자'}: {p.name}" for p in parties])
        if facts:
            parts.append("[사실관계]")
            parts.extend([f"- {f.statement}" for f in facts])
        if events:
            parts.append("[타임라인]")
            parts.extend([f"- {e.event_date or '미상'}: {e.title}" for e in events])
        if approved_claims:
            parts.append("[증거]")
            parts.extend([f"- {c.statement}" for c in approved_claims])

        state.context_text = "\n".join(parts)
    finally:
        db.close()
    return state

@trace
def requirements_node(state: DocumentState) -> DocumentState:
    """문서 초안 작성을 위한 최소 사건 맥락(사실관계, 증거, 당사자, 사건 개요 중 하나 이상) 존재 여부를 검증한다."""
    state.requirements_met = True
    has_substance = any(
        marker in state.context_text
        for marker in ("[사실관계]", "[증거]", "[당사자]", "[사건 개요]", "수신인", "발신인", "의뢰인", "상대방", "임대인", "채무자")
    )
    if not has_substance:
        state.requirements_met = False
        state.missing_info.append("사건 사실관계, 증거 또는 당사자 정보 부족")
    return state

@trace
def generate_node(state: DocumentState) -> DocumentState:
    if not state.requirements_met:
        state.draft_content = "필수 정보가 부족하여 문서를 생성할 수 없습니다."
        return state

    prompt = PromptTemplate.from_template(
        "당신은 법률 문서 작성 보조 AI입니다.\n"
        "다음 정보를 바탕으로 '{doc_type}' 초안을 작성하세요.\n\n"
        "[사건 정보]\n{context}\n\n"
        "객관적이고 정중한 어조를 사용하며, 증거가 없는 사실은 단정적으로 기재하지 마세요."
    )
    # Azure OpenAI 호환성을 위해 function_calling 방식으로 구조화 출력 호출
    llm = get_llm(temperature=0.0).with_structured_output(DocumentDraftSchema, method="function_calling")
    
    try:
        res = llm.invoke(prompt.format(doc_type=state.document_type, context=state.context_text))
        state.structured_content = res.dict()
        state.draft_content = res.full_content
    except Exception as e:
        logger.error(f"Doc Generation error: {e}")
        state.draft_content = "생성 오류 발생"
        
    return state

@trace
def verification_node(state: DocumentState) -> DocumentState:
    """생성된 문서 초안의 유효성 및 사건 컨텍스트 대비 미검증 날짜·금액 포함 여부를 검사한다."""
    if not state.requirements_met:
        state.verification_status = "FAIL"
        return state

    draft = (state.draft_content or "").strip()
    if not draft or draft == "생성 오류 발생":
        state.verification_status = "FAIL"
        state.verification_warnings.append("문서 초안 생성에 실패했거나 본문이 비어 있습니다.")
        return state

    # 초안 내 연도/날짜(YYYY-MM-DD 또는 YYYY년) 및 금액 표현이 원본 컨텍스트에 존재하는지 대조
    # 한국어 조사('까지', '을' 등)가 바로 붙는 경우에도 매칭되도록 단어 경계(\b) 대신 숫자 경계((?<!\d))를 사용한다.
    context_normalized = state.context_text.replace(",", "")
    draft_normalized = draft.replace(",", "")

    date_tokens = set(re.findall(r"(?<!\d)20\d{2}[-.]\d{1,2}[-.]\d{1,2}(?!\d)|(?<!\d)20\d{2}년", draft_normalized))
    unverified_dates = [d for d in date_tokens if d not in context_normalized]
    if unverified_dates:
        state.verification_warnings.append(
            f"사건 기록에서 확인되지 않은 날짜 표현이 포함되었습니다: {', '.join(sorted(unverified_dates))}"
        )

    amount_tokens = set(re.findall(r"(?<!\d)\d+(?:억|천만|백만|십만|만)?\s*원", draft_normalized))
    unverified_amounts = [a for a in amount_tokens if a.replace(" ", "") not in context_normalized.replace(" ", "")]
    if unverified_amounts:
        state.verification_warnings.append(
            f"사건 기록에서 확인되지 않은 금액 표현이 포함되었습니다: {', '.join(sorted(unverified_amounts))}"
        )

    state.verification_status = "WARN" if state.verification_warnings else "PASS"
    return state

@trace
def review_gate_node(state: DocumentState) -> DocumentState:
    # DB에 저장
    if state.requirements_met and state.verification_status != "FAIL":
        db = SessionLocal()
        try:
            doc = LegalDocument(
                case_id=state.case_id,
                action_id=state.action_id,
                document_type=state.document_type,
                title=state.structured_content.get("title", f"{state.document_type} 초안"),
                status="DRAFT"
            )
            db.add(doc)
            db.flush()

            rev = DocumentRevision(
                document_id=doc.id,
                revision_number=1,
                content=state.draft_content,
                structured_content=state.structured_content,
                verification_status=state.verification_status
            )
            db.add(rev)
            db.flush()
            
            doc.current_revision_id = rev.id
            db.commit()
            state.revision_id = rev.id
            try:
                update_span(get_current_span_id(), {"document_type": state.document_type, "verification_status": state.verification_status, "revision_number": 1})
                from ai_legal_helper.observability.langfuse_client import log_score
                from ai_legal_helper.observability.context import get_trace_id
                doc_score = 1.0 if state.verification_status == "PASS" else 0.0
                log_score(get_trace_id(), "document_verification_score", doc_score, comment=state.verification_status)
            except Exception:
                pass
        finally:
            db.close()
    return state

def build_document_graph():
    graph = StateGraph(DocumentState)
    graph.add_node("context", context_node)
    graph.add_node("requirements", requirements_node)
    graph.add_node("generate", generate_node)
    graph.add_node("verification", verification_node)
    graph.add_node("review_gate", review_gate_node)

    graph.add_edge(START, "context")
    graph.add_edge("context", "requirements")
    graph.add_edge("requirements", "generate")
    graph.add_edge("generate", "verification")
    graph.add_edge("verification", "review_gate")
    graph.add_edge("review_gate", END)

    return graph.compile()

