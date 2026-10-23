# -*- coding: utf-8 -*-
"""
증거 인공지능 추출 서비스 (Evidence AI Extractor)

추출된 텍스트 Span들을 기반으로 LLM을 활용하여 사실관계, 당사자, 날짜 등의
EvidenceClaim 후보를 추출한다.
추출된 후보는 사용자의 승인을 거치기 위해 REVIEW_STATUS="PENDING"으로 생성된다.
문서가 긴 경우 Span을 배치 단위(EXTRACTION_BATCH_SIZE=20)로 분할 처리하여 컨텍스트 초과 및 누락을 방지하며,
추출 후 독립 상충 검증 엔진(conflict_detector.py)을 통해 실제 논리적 모순(CONTRADICTION)으로 검증된 경우에만
상충 상태 및 CONTRADICTS 링크를 기록한다.
"""

import logging
import json
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from ai_legal_helper.database.models import (
    EvidenceDocument,
    EvidenceSpan,
    EvidenceClaim,
    EvidenceSpanClaimLink,
    EvidenceLink,
    Fact,
)
from ai_legal_helper.case_intelligence.conflict_detector import (
    build_structured_slots,
    evaluate_claim_conflicts,
)
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span

logger = logging.getLogger(__name__)

EXTRACTION_BATCH_SIZE = 20

# 9가지 법률 도메인 세분화 카테고리 매핑
# DB 영속화: 표준 영문 코드 (PROPERTY, RIGHT_DUTY, DOC_INFO, DATE, AMOUNT, PARTY_INFO, ACTION, CONDITION, GENERAL)
# UI 표시: 공백 없는 한글 표기 (목적물정보, 권리의무, 문서정보, 일자기한, 금액비용, 당사자정보, 법률행위, 계약조건, 일반서술)

CLAIM_TYPE_TO_CODE_MAP: Dict[str, str] = {
    # 목적물정보 -> PROPERTY
    "PROPERTY": "PROPERTY",
    "PROPERTY_INFO": "PROPERTY",
    "부동산": "PROPERTY",
    "목적물": "PROPERTY",
    "목적물정보": "PROPERTY",
    "목적물 정보": "PROPERTY",

    # 권리의무 -> RIGHT_DUTY
    "RIGHT_DUTY": "RIGHT_DUTY",
    "RIGHTS_DUTIES": "RIGHT_DUTY",
    "OBLIGATION": "RIGHT_DUTY",
    "RIGHT": "RIGHT_DUTY",
    "권리의무": "RIGHT_DUTY",
    "권리 의무": "RIGHT_DUTY",

    # 문서정보 -> DOC_INFO
    "DOC_INFO": "DOC_INFO",
    "DOCUMENT_INFO": "DOC_INFO",
    "DOCUMENT": "DOC_INFO",
    "문서": "DOC_INFO",
    "문서정보": "DOC_INFO",
    "문서 정보": "DOC_INFO",

    # 일자기한 -> DATE
    "DATE": "DATE",
    "DATE_INFO": "DATE",
    "일자": "DATE",
    "기한": "DATE",
    "일자기한": "DATE",
    "일자 기한": "DATE",

    # 금액비용 -> AMOUNT
    "AMOUNT": "AMOUNT",
    "PRICE": "AMOUNT",
    "COST": "AMOUNT",
    "금액": "AMOUNT",
    "비용": "AMOUNT",
    "금액비용": "AMOUNT",
    "금액 비용": "AMOUNT",

    # 당사자정보 -> PARTY_INFO
    "PARTY_INFO": "PARTY_INFO",
    "PARTY": "PARTY_INFO",
    "PARTIES": "PARTY_INFO",
    "당사자": "PARTY_INFO",
    "당사자정보": "PARTY_INFO",
    "당사자 정보": "PARTY_INFO",

    # 법률행위 -> ACTION
    "ACTION": "ACTION",
    "LEGAL_ACTION": "ACTION",
    "행위": "ACTION",
    "법률행위": "ACTION",
    "법률 행위": "ACTION",

    # 계약조건 -> CONDITION
    "CONDITION": "CONDITION",
    "TERMS": "CONDITION",
    "조건": "CONDITION",
    "특약": "CONDITION",
    "계약조건": "CONDITION",
    "계약 조건": "CONDITION",

    # 일반서술 -> GENERAL
    "OTHER": "GENERAL",
    "GENERAL": "GENERAL",
    "STATEMENT": "GENERAL",
    "일반": "GENERAL",
    "서술": "GENERAL",
    "일반서술": "GENERAL",
    "일반 서술": "GENERAL",
}


def normalize_to_claim_code(raw_type: Optional[str]) -> str:
    """추출된 주장(Claim)의 유형을 DB 저장용 표준 영문 코드로 정규화한다.

    Args:
        raw_type (Optional[str]): 원본 분류 문자열 (한글 또는 영문).

    Returns:
        str: 표준 영문 대문자 코드. 기본값은 'GENERAL'.
    """
    if not raw_type:
        return "GENERAL"
    cleaned = raw_type.strip().upper()
    if cleaned in CLAIM_TYPE_TO_CODE_MAP:
        return CLAIM_TYPE_TO_CODE_MAP[cleaned]
    no_space = raw_type.replace(" ", "")
    if no_space in CLAIM_TYPE_TO_CODE_MAP:
        return CLAIM_TYPE_TO_CODE_MAP[no_space]
    return "GENERAL"


def normalize_claim_type(raw_type: Optional[str]) -> str:
    """추출된 주장(Claim)의 유형을 UI 표기용 공백 없는 한글 카테고리로 정규화한다."""
    code = normalize_to_claim_code(raw_type)
    code_to_label = {
        "PROPERTY": "목적물정보",
        "RIGHT_DUTY": "권리의무",
        "DOC_INFO": "문서정보",
        "DATE": "일자기한",
        "AMOUNT": "금액비용",
        "PARTY_INFO": "당사자정보",
        "ACTION": "법률행위",
        "CONDITION": "계약조건",
        "GENERAL": "일반서술",
    }
    return code_to_label.get(code, "일반서술")


def detect_conflicting_fact(
    statement: str,
    existing_facts: List[Fact],
    claim_type: Optional[str] = None,
    evidence_id: Optional[str] = None,
) -> Optional[Fact]:
    """신규 추출된 증거 주장(statement)이 사건의 기존 사실관계(Fact)와 논리적으로 모순(CONTRADICTION)되는지 판별한다.

    내부적으로 3단계 구조화 상충 탐지 엔진(`conflict_detector.evaluate_claim_conflicts`)을 호출하여,
    문서 고유 정보(DOC_INFO), 서로 다른 값 차원(날짜 vs 금액), 정규화 금액 일치(예: 한글 수사 vs 아라비아 숫자)를
    모순에서 배제하고 실제 양립 불가능한 상충 Fact만 반환한다.

    Args:
        statement: 증거 문서에서 추출된 주장 문자열.
        existing_facts: 사건에 이미 등록된 Fact 엔티티 목록.
        claim_type: 추출된 Claim의 표준 유형 코드 (선택).
        evidence_id: 출처 증거 문서 ID (선택).

    Returns:
        Optional[Fact]: 검증된 상충 Fact 엔티티 (상충 없을 시 None).
    """
    if not statement or not existing_facts:
        return None

    eval_res = evaluate_claim_conflicts(
        statement=statement,
        existing_facts=existing_facts,
        claim_type=claim_type,
        evidence_id=evidence_id,
        enable_llm_verification=False,
    )
    contradictions = eval_res.get("contradictions", [])
    if not contradictions:
        return None

    facts_by_id = {f.id: f for f in existing_facts}
    top_decision = contradictions[0]
    return facts_by_id.get(top_decision.target_fact_id)


class ExtractedClaimSchema(BaseModel):
    """LLM으로부터 추출되는 단일 구조화 증거 주장 스키마."""
    statement: str = Field(description="추출된 사실관계 진술. 문서 고유 제목·형식인 경우 문서 종류를 함께 명시하세요.")
    claim_type: str = Field(description="사실관계의 유형 영문 코드: PROPERTY(목적물정보), RIGHT_DUTY(권리의무), DOC_INFO(문서정보), DATE(일자기한), AMOUNT(금액비용), PARTY_INFO(당사자정보), ACTION(법률행위), CONDITION(계약조건), GENERAL(일반서술)")
    subject: Optional[str] = Field(default=None, description="서술의 핵심 대상 또는 주체 (예: '임대차계약', '임차인', '임대인', '근로계약', '문서자체')")
    predicate: Optional[str] = Field(default=None, description="서술하는 구체적 속성이나 행위 종류 (예: '약정보증금', '반환요청금액', '반환요청일자', '계약기간', '문서제목', '해지통지')")
    scope: Optional[str] = Field(default="CASE_GLOBAL", description="적용 범위: 해당 문서 자체의 제목·형식·작성정보이면 DOCUMENT_LOCAL, 사건의 실체적 사실이면 CASE_GLOBAL")
    temporal_context: Optional[str] = Field(default=None, description="시간적 문맥 또는 단계 (예: 'INITIAL_CONTRACT', 'MODIFICATION_OR_RENEWAL', 'RETURN_REQUEST', 'ACTUAL_PERFORMANCE')")
    assertion_status: str = Field(description="단언 상태. 문서에 확정적으로 쓰여진 사실이면 DOCUMENT_STATES, 일방의 주장이면 PARTY_ALLEGES, 기존 사실과 명백히 양립 불가능한 모순이면 CONTRADICTION_CANDIDATE, AI가 추론한 것이면 AI_INFERENCE, 불확실하면 UNCERTAIN.")
    confidence: float = Field(description="추출 결과의 신뢰도 (0.0 ~ 1.0)")
    source_span_ids: List[str] = Field(description="이 주장을 뒷받침하는 제공된 문단(span)의 ID 목록. 반드시 제공된 ID 중에 있어야 함.")
    contradicts_fact_id: Optional[str] = Field(default=None, description="기존 사실관계(Fact ID)와 동일한 대상·동일한 속성에 대해 양립 불가능하게 모순되는 경우에만 해당 Fact ID 기재 (없으면 null)")


class EvidenceExtractionResultSchema(BaseModel):
    """증거 문서 사실 추출 전체 결과 스키마."""
    claims: List[ExtractedClaimSchema] = Field(description="추출된 주장 목록")


def _extract_batch_claims_via_llm(
    llm: Any,
    prompt: ChatPromptTemplate,
    context_str: str,
) -> Optional[EvidenceExtractionResultSchema]:
    """단일 배치의 증거 원문 Span 컨텍스트에 대해 LLM 구조화 추출을 수행한다."""
    try:
        structured_llm = llm.with_structured_output(EvidenceExtractionResultSchema, method="function_calling")
        chain = prompt | structured_llm
        return chain.invoke({"context": context_str})
    except Exception as e:
        logger.warning(f"with_structured_output failed, falling back to JSON parsing: {str(e)}")
        fallback_prompt = ChatPromptTemplate.from_messages([
            ("system", "당신은 법률 증거 분석 보조 AI입니다. 주어진 문서 내용을 바탕으로 중요한 사실들을 추출하세요.\n"
                       "각 사실의 claim_type은 다음 영문 코드 중 하나로 지정하세요: PROPERTY, RIGHT_DUTY, DOC_INFO, DATE, AMOUNT, PARTY_INFO, ACTION, CONDITION, GENERAL.\n"
                       "서로 다른 문서의 고유 제목(DOC_INFO)이나 서로 다른 속성(금액 vs 날짜), 동일한 금액의 다른 표기 방식은 절대 상충(CONTRADICTION_CANDIDATE)으로 분류하지 마세요.\n"
                       "반드시 다음과 같은 JSON 형식으로만 응답해야 합니다:\n"
                       "{{\"claims\": [{{\"statement\": \"...\", \"claim_type\": \"DATE\", \"subject\": \"...\", \"predicate\": \"...\", \"scope\": \"CASE_GLOBAL\", \"assertion_status\": \"DOCUMENT_STATES\", \"confidence\": 0.9, \"source_span_ids\": [\"...\"], \"contradicts_fact_id\": null}}]}}\n"
                       "결과물은 반드시 유효한 JSON 포맷이어야 합니다."),
            ("human", "{context}"),
        ])
        fallback_chain = fallback_prompt | llm
        response = fallback_chain.invoke({"context": context_str})
        text_content = response.content if hasattr(response, "content") else str(response)
        if text_content.startswith("```json"):
            text_content = text_content[7:-3]
        elif text_content.startswith("```"):
            text_content = text_content[3:-3]
        data = json.loads(text_content)
        return EvidenceExtractionResultSchema(**data)


@trace
def extract_claims_from_evidence(db: Session, doc_id: str) -> bool:
    """특정 EvidenceDocument의 텍스트를 LLM에 전달하여 구조화된 EvidenceClaim 후보들을 도출하고
    3단계 상충 검증 엔진(`evaluate_claim_conflicts`)을 통해 검증된 상충만 기록한다.

    Args:
        db (Session): 데이터베이스 세션.
        doc_id (str): 대상 증거 문서의 고유 식별자(UUID).

    Returns:
        bool: 추출 파이프라인 수행 성공 여부.
    """
    doc = db.query(EvidenceDocument).filter_by(id=doc_id).first()
    if not doc:
        return False

    spans = (
        db.query(EvidenceSpan)
        .filter_by(evidence_id=doc_id)
        .order_by(
            EvidenceSpan.page_number.asc().nullsfirst(),
            EvidenceSpan.paragraph_index.asc().nullsfirst(),
            EvidenceSpan.created_at.asc(),
        )
        .all()
    )
    if not spans:
        logger.warning(f"No spans found for document {doc_id}")
        return False

    case_docs = db.query(EvidenceDocument).filter_by(case_id=doc.case_id).all()
    docs_by_id = {d.id: d.original_filename for d in case_docs}

    existing_facts = db.query(Fact).filter_by(case_id=doc.case_id).all()
    facts_by_id = {f.id: f for f in existing_facts}
    fact_doc_names = {
        f.id: docs_by_id.get(f.source_ref, "사건 기본 사실")
        for f in existing_facts
    }

    existing_facts_lines = []
    for f in existing_facts:
        src_doc_label = fact_doc_names.get(f.id, "사건 기본 사실")
        existing_facts_lines.append(
            f"- [Fact ID: {f.id} | 유형: {f.fact_type or 'GENERAL'} | 출처문서: {src_doc_label}] {f.statement}"
        )
    existing_facts_str = "\n".join(existing_facts_lines) or "(등록된 기존 사실관계 없음)"

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "당신은 법률 증거 분석 보조 AI입니다. 현재 분석 중인 증거 문서('{doc_name}')의 내용을 바탕으로 중요한 사실관계 후보를 추출하세요.\n"
            "각 사실의 분류(claim_type)는 다음 9가지 세분화 카테고리의 표준 영문 코드로 지정해야 합니다:\n"
            "- PROPERTY: 부동산, 동산, 유가증권, 지식재산권, 차량 등 분쟁 목적물에 관한 사항 (목적물정보)\n"
            "- RIGHT_DUTY: 이행의무, 지급청구권, 손해배상의무, 인도/명도의무, 대항력 등 당사자의 법적 권리와 의무 (권리의무)\n"
            "- DOC_INFO: 계약서/통지서/영수증 명칭, 작성자 날인/서명 여부, 작성일자, 특약/조건 기재 여부 등 문서 자체의 형식적 사항 (문서정보, scope='DOCUMENT_LOCAL')\n"
            "- DATE: 계약일, 발생일, 지급일/만기일, 통지일/도달일 등 중요 날짜 및 기한 (일자기한)\n"
            "- AMOUNT: 대여금, 매매대금, 보증금/차임, 임금/퇴직금, 손해배상액, 위약금 등 금액 (금액비용)\n"
            "- PARTY_INFO: 원고/피고, 채권자/채무자, 근로자/사용자, 임대인/임차인 등 당사자 및 대리인 인적사항 (당사자정보)\n"
            "- ACTION: 계약체결, 통지/최고, 대금지급, 계약해제/해지, 이행/인도 등 실제 행하여진 법률행위 (법률행위)\n"
            "- CONDITION: 해제조건, 실효조건, 기한이익상실, 갱신거절조건, 특약조항 등 (계약조건)\n"
            "- GENERAL: 위 범주에 속하지 않는 배경 정황 및 기타 일반 진술 (일반서술)\n\n"
            "[다중 증거 문서 상충(CONTRADICTION) 판정 엄격 규칙]\n"
            "1. 한 사건에는 여러 개의 증거 문서가 등록됩니다. 다른 문서와 문서 제목·종류(DOC_INFO)가 다른 것은 당연하므로 절대 상충(CONTRADICTION_CANDIDATE)으로 분류하지 마세요.\n"
            "2. 동일한 금액의 표기 방식 차이(아라비아 숫자 vs 한글 수사·만/억 단위 표기)는 일치하는 사실이므로 상충이 아닙니다.\n"
            "3. 서로 다른 속성(예: 약정 금액 vs 반환 요청 일자)이나 시간 순서에 따른 후속 행위(계약 체결 후 통지·요청·재확인)는 별개 사실이지 상충이 아닙니다.\n"
            "4. 오직 동일한 대상(subject)과 동일한 속성(predicate)에 대해 두 진술이 논리적으로 동시에 참일 수 없을 때만 assertion_status를 'CONTRADICTION_CANDIDATE'로 지정하고 contradicts_fact_id를 기재하세요.\n"
            "5. 반드시 제공된 'Span ID'를 source_span_ids에 포함하여 출처를 명확히 해야 합니다. 거짓 정보를 생성하지 마세요.",
        ),
        ("human", "다음 문서 텍스트에서 중요한 사실들을 추출해주세요.\n\n{context}"),
    ]).partial(doc_name=doc.original_filename or doc.id)

    llm = get_llm(temperature=0.0)
    all_extracted_claims: List[ExtractedClaimSchema] = []

    # 긴 문서를 위한 Span 배치 분할 처리
    batches = [
        spans[i:i + EXTRACTION_BATCH_SIZE]
        for i in range(0, len(spans), EXTRACTION_BATCH_SIZE)
    ]

    for batch_spans in batches:
        span_texts = []
        for s in batch_spans:
            loc = f"Page {s.page_number}" if s.page_number else f"Para {s.paragraph_index}"
            span_texts.append(f"[Span ID: {s.id}] ({loc}): {s.text_excerpt}")
        context_str = (
            f"[현재 분석 문서명]\n{doc.original_filename}\n\n"
            f"[기존 사건 사실관계]\n{existing_facts_str}\n\n"
            f"[증거 문서 원문 Span]\n" + "\n\n".join(span_texts)
        )

        try:
            batch_res = _extract_batch_claims_via_llm(llm, prompt, context_str)
            if batch_res and batch_res.claims:
                all_extracted_claims.extend(batch_res.claims)
        except Exception as parse_error:
            logger.error(f"Failed to parse LLM JSON response: {str(parse_error)}")
            if not all_extracted_claims:
                doc.status = "FAILED"
                doc.error_code = "AI_EXTRACTION_FAILED"
                db.commit()
                return False

    if not all_extracted_claims:
        doc.status = "REVIEW_REQUIRED"
        db.commit()
        return True

    valid_span_ids = {s.id for s in spans}

    new_claims = []
    links_to_create = []
    contradiction_links_to_create = []
    seen_norm_statements = set()

    for claim_data in all_extracted_claims:
        filtered_span_ids = [sid for sid in claim_data.source_span_ids if sid in valid_span_ids]

        if filtered_span_ids:
            norm_stmt = "".join((claim_data.statement or "").split())
            if not norm_stmt or norm_stmt in seen_norm_statements:
                continue
            seen_norm_statements.add(norm_stmt)

            normalized_code = normalize_to_claim_code(claim_data.claim_type)
            claim_slots = build_structured_slots(
                statement=claim_data.statement,
                claim_type=normalized_code,
                subject=getattr(claim_data, "subject", None),
                predicate=getattr(claim_data, "predicate", None),
                scope=getattr(claim_data, "scope", None),
                temporal_context=getattr(claim_data, "temporal_context", None),
                evidence_id=doc.id,
                document_name=doc.original_filename,
                source_span_ids=filtered_span_ids,
            )

            # 3단계 상충 검증 엔진을 통해 기존 Fact들과의 관계 검증
            # 중요: LLM이 1차 추출에서 CONTRADICTION_CANDIDATE로 표시했더라도
            # 검증 엔진에서 CONTRADICTION으로 확인되지 않으면 오탐을 차단하고 DOCUMENT_STATES로 복원한다.
            eval_res = evaluate_claim_conflicts(
                statement=claim_data.statement,
                existing_facts=existing_facts,
                claim_type=normalized_code,
                subject=claim_slots.subject_key,
                predicate=claim_slots.predicate_key,
                scope=claim_slots.scope,
                temporal_context=claim_slots.temporal_context,
                evidence_id=doc.id,
                document_name=doc.original_filename,
                source_span_ids=filtered_span_ids,
                llm_suggested_fact_id=getattr(claim_data, "contradicts_fact_id", None),
                fact_doc_names=fact_doc_names,
                enable_llm_verification=None,
            )
            verified_contradictions = eval_res["contradictions"]
            potential_conflicts = eval_res.get("potential_conflicts", [])

            assertion_status = claim_data.assertion_status
            if verified_contradictions:
                assertion_status = "CONTRADICTION_CANDIDATE"
            elif assertion_status == "CONTRADICTION_CANDIDATE":
                # 검증 엔진이 오탐(CONSISTENT, DIFFERENT_CONTEXT, POTENTIAL_CONFLICT 등)으로 기각한 경우 정상 상태로 복원
                assertion_status = "DOCUMENT_STATES"

            new_claim = EvidenceClaim(
                case_id=doc.case_id,
                evidence_id=doc.id,
                statement=claim_data.statement,
                claim_type=normalized_code,
                subject_key=claim_slots.subject_key,
                predicate_key=claim_slots.predicate_key,
                scope=claim_slots.scope,
                temporal_context=claim_slots.temporal_context,
                structured_slots=claim_slots.model_dump(),
                assertion_status=assertion_status,
                confidence=claim_data.confidence,
                review_status="PENDING",
                extractor_model="azure-openai",
            )
            db.add(new_claim)
            db.flush()  # id 할당을 위해 flush

            for sid in dict.fromkeys(filtered_span_ids):
                links_to_create.append(
                    EvidenceSpanClaimLink(
                        claim_id=new_claim.id,
                        span_id=sid,
                    )
                )

            # 검증 엔진에서 최종 확인된 CONTRADICTION에 한해서만 CONTRADICTS 링크 생성
            seen_contra_targets = set()
            for c_dec in verified_contradictions:
                if c_dec.target_fact_id in facts_by_id and c_dec.target_fact_id not in seen_contra_targets:
                    seen_contra_targets.add(c_dec.target_fact_id)
                    contradiction_links_to_create.append(
                        EvidenceLink(
                            evidence_id=doc.id,
                            claim_id=new_claim.id,
                            target_type="FACT",
                            target_id=c_dec.target_fact_id,
                            link_type="CONTRADICTS",
                        )
                    )

            # POTENTIAL_CONFLICT는 CONTRADICTS와 분리하여 별도 POTENTIAL_CONFLICT 링크로 기록
            if not verified_contradictions:
                for p_dec in potential_conflicts:
                    if p_dec.target_fact_id in facts_by_id and p_dec.target_fact_id not in seen_contra_targets:
                        seen_contra_targets.add(p_dec.target_fact_id)
                        contradiction_links_to_create.append(
                            EvidenceLink(
                                evidence_id=doc.id,
                                claim_id=new_claim.id,
                                target_type="FACT",
                                target_id=p_dec.target_fact_id,
                                link_type="POTENTIAL_CONFLICT",
                            )
                        )

            new_claims.append(new_claim)

    if links_to_create:
        db.add_all(links_to_create)
    if contradiction_links_to_create:
        db.add_all(contradiction_links_to_create)

    doc.status = "REVIEW_REQUIRED"  # 사용자 검토 대기 상태
    doc.extraction_version = "llm-v3-structured-conflict"
    db.commit()

    cur_span = get_current_span_id()
    if cur_span:
        try:
            update_span(
                cur_span,
                {
                    "document_id": doc_id,
                    "claims_count": len(new_claims),
                    "contradictions_count": len(contradiction_links_to_create),
                    "batches_count": len(batches),
                },
            )
        except Exception:
            pass

    return True
