# -*- coding: utf-8 -*-
"""
증거 인공지능 추출 서비스 (Evidence AI Extractor)

추출된 텍스트 Span들을 기반으로 LLM을 활용하여 사실관계, 당사자, 날짜 등의 
EvidenceClaim 후보를 추출한다.
추출된 후보는 사용자의 승인을 거치기 위해 REVIEW_STATUS="PENDING"으로 생성된다.
"""

import logging
import json
import re
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
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span

logger = logging.getLogger(__name__)

# LLM 출력을 위한 Pydantic 스키마 정의
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

    입력이 한글이든 레거시 영문이든 표준 9가지 영문 대문자 코드
    (PROPERTY, RIGHT_DUTY, DOC_INFO, DATE, AMOUNT, PARTY_INFO, ACTION, CONDITION, GENERAL)로 변환한다.

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
    """추출된 주장(Claim)의 유형을 UI 표기용 공백 없는 한글 카테고리로 정규화한다.

    Args:
        raw_type (Optional[str]): 원본 분류 문자열.

    Returns:
        str: 표준 한글 카테고리 명칭 (공백 없음). 기본값은 '일반서술'.
    """
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


def detect_conflicting_fact(statement: str, existing_facts: List[Fact]) -> Optional[Fact]:
    """신규 추출된 증거 주장(statement)이 사건의 기존 사실관계(Fact)와 상충하는지 탐지한다.

    1. 동일 핵심 키워드(보증금, 월세, 차임, 계약일, 만기일, 반환 등)를 공유하면서
       수치(금액·일자)가 서로 다르거나 긍정/부정 진술이 반대인 경우 상충하는 Fact를 반환한다.

    Args:
        statement: 증거 문서에서 추출된 주장 문자열.
        existing_facts: 사건에 이미 등록된 Fact 엔티티 목록.

    Returns:
        Optional[Fact]: 상충이 감지된 기존 Fact 엔티티 (상충 없을 시 None).
    """
    if not statement or not existing_facts:
        return None

    key_subjects = ["보증금", "전세금", "월세", "차임", "관리비", "계약일", "만기일", "인도일", "반환", "해지"]
    negation_pairs = [
        ("지급하", "지급하지 않"),
        ("지급함", "미지급"),
        ("반환하", "반환하지 않"),
        ("반환함", "미반환"),
        ("동의하", "동의하지 않"),
        ("통지하", "통지하지 않"),
        ("있", "없"),
    ]
    stmt_nums = set(re.findall(r"\d+(?:,\d+)*(?:\s*(?:억|천만|백만|만|원|년|월|일))", statement))

    for fact in existing_facts:
        f_stmt = fact.statement or ""
        if not f_stmt or f_stmt.strip() == statement.strip():
            continue

        shared_subjects = [kw for kw in key_subjects if kw in statement and kw in f_stmt]
        if not shared_subjects:
            continue

        # 1. 동일 주제에 대해 금액/일자가 서로 다른 경우
        fact_nums = set(re.findall(r"\d+(?:,\d+)*(?:\s*(?:억|천만|백만|만|원|년|월|일))", f_stmt))
        if stmt_nums and fact_nums and stmt_nums != fact_nums:
            return fact

        # 2. 동일 주제에 대해 긍정/부정 서술이 반대인 경우
        for pos, neg in negation_pairs:
            if (pos in statement and neg in f_stmt) or (neg in statement and pos in f_stmt):
                return fact

    return None


class ExtractedClaimSchema(BaseModel):
    """LLM으로부터 추출되는 단일 증거 주장 스키마."""
    statement: str = Field(description="추출된 사실관계 진술. (예: '임대인 홍길동이 임차인 김철수와 2022년 3월 1일에 전세계약을 체결함')")
    claim_type: str = Field(description="사실관계의 유형 영문 코드: PROPERTY(목적물정보), RIGHT_DUTY(권리의무), DOC_INFO(문서정보), DATE(일자기한), AMOUNT(금액비용), PARTY_INFO(당사자정보), ACTION(법률행위), CONDITION(계약조건), GENERAL(일반서술)")
    assertion_status: str = Field(description="단언 상태. 문서에 확정적으로 쓰여진 사실이면 DOCUMENT_STATES, 일방의 주장이면 PARTY_ALLEGES, 기존 사실과 상충하면 CONTRADICTION_CANDIDATE, AI가 추론한 것이면 AI_INFERENCE, 불확실하면 UNCERTAIN.")
    confidence: float = Field(description="추출 결과의 신뢰도 (0.0 ~ 1.0)")
    source_span_ids: List[str] = Field(description="이 주장을 뒷받침하는 제공된 문단(span)의 ID 목록. 반드시 제공된 ID 중에 있어야 함.")
    contradicts_fact_id: Optional[str] = Field(default=None, description="기존 사실관계(Fact ID)와 모순·상충되는 경우 해당 Fact ID (없으면 null)")


class EvidenceExtractionResultSchema(BaseModel):
    """증거 문서 사실 추출 전체 결과 스키마."""
    claims: List[ExtractedClaimSchema] = Field(description="추출된 주장 목록")


@trace
def extract_claims_from_evidence(db: Session, doc_id: str) -> bool:
    """특정 EvidenceDocument의 텍스트를 LLM에 전달하여 EvidenceClaim 후보들을 도출하고 상충 여부를 검사한다.

    도출된 후보는 9종의 세분화 카테고리로 분류되며, 기존 사건 사실관계(Fact)와 상충하는 경우
    `assertion_status='CONTRADICTION_CANDIDATE'` 및 `EvidenceLink(link_type='CONTRADICTS')`를 생성한다.

    Args:
        db (Session): 데이터베이스 세션.
        doc_id (str): 대상 증거 문서의 고유 식별자(UUID).

    Returns:
        bool: 추출 파이프라인 수행 성공 여부.
    """
    doc = db.query(EvidenceDocument).filter_by(id=doc_id).first()
    if not doc:
        return False

    spans = db.query(EvidenceSpan).filter_by(evidence_id=doc_id).order_by(EvidenceSpan.created_at).all()
    if not spans:
        logger.warning(f"No spans found for document {doc_id}")
        return False

    existing_facts = db.query(Fact).filter_by(case_id=doc.case_id).all()
    facts_by_id = {f.id: f for f in existing_facts}
    existing_facts_str = "\n".join([f"- [Fact ID: {f.id}] {f.statement}" for f in existing_facts]) or "(등록된 기존 사실관계 없음)"

    span_texts = []
    for s in spans:
        loc = f"Page {s.page_number}" if s.page_number else f"Para {s.paragraph_index}"
        span_texts.append(f"[Span ID: {s.id}] ({loc}): {s.text_excerpt}")

    context_str = f"[기존 사건 사실관계]\n{existing_facts_str}\n\n[증거 문서 원문 Span]\n" + "\n\n".join(span_texts)

    prompt = ChatPromptTemplate.from_messages([
        ("system", "당신은 법률 증거 분석 보조 AI입니다. 주어진 문서 내용을 바탕으로 중요한 사실관계 후보를 추출하세요.\n"
                   "각 사실의 분류(claim_type)는 다음 9가지 세분화 카테고리의 표준 영문 코드로 지정해야 합니다:\n"
                   "- PROPERTY: 부동산 소재지, 임대차 목적물, 구조/면적, 차량 등 목적물에 관한 사항 (목적물정보)\n"
                   "- RIGHT_DUTY: 원상복구의무, 명도의무, 대항력, 비용상환청구권 등 당사자의 법적 권리와 의무 (권리의무)\n"
                   "- DOC_INFO: 계약서 명칭, 작성자 날인/서명 여부, 작성일자, 특약사항 기재 여부 등 문서 자체의 형식적 사항 (문서정보)\n"
                   "- DATE: 계약일, 인도일, 잔금일, 만기일, 해지통지일 등 중요 날짜 및 기한 (일자기한)\n"
                   "- AMOUNT: 보증금, 월 차임, 관리비, 중개보수, 손해배상액, 위약금 등 금액 (금액비용)\n"
                   "- PARTY_INFO: 임대인, 임차인, 대리인, 공인중개사 등 인적사항 및 당사자 관계 (당사자정보)\n"
                   "- ACTION: 계약체결, 해지통지, 명도완료, 대금지급 등 실제 행하여진 법률행위 (법률행위)\n"
                   "- CONDITION: 해제조건, 실효조건, 갱신거절조건, 특약조항 등 (계약조건)\n"
                   "- GENERAL: 위 범주에 속하지 않는 배경 정황 및 기타 일반 진술 (일반서술)\n"
                   "만약 추출된 사실이 [기존 사건 사실관계]와 모순·상충된다면 assertion_status를 'CONTRADICTION_CANDIDATE'로 지정하고 contradicts_fact_id에 해당 Fact ID를 기재하세요.\n"
                   "반드시 제공된 'Span ID'를 source_span_ids에 포함하여 출처를 명확히 해야 합니다.\n"
                   "결과물은 JSON 형식으로 반환해야 합니다. 거짓 정보를 생성하지 마세요."),
        ("human", "다음 문서 텍스트에서 중요한 사실들을 추출해주세요.\n\n{context}")
    ])

    llm = get_llm(temperature=0.0)

    # Azure OpenAI의 json_schema 400 에러를 방지하기 위해 function_calling 방식으로 구조화 출력 호출
    try:
        structured_llm = llm.with_structured_output(EvidenceExtractionResultSchema, method="function_calling")
        chain = prompt | structured_llm
        result = chain.invoke({"context": context_str})
    except Exception as e:
        logger.warning(f"with_structured_output failed, falling back to JSON parsing: {str(e)}")
        fallback_prompt = ChatPromptTemplate.from_messages([
            ("system", "당신은 법률 증거 분석 보조 AI입니다. 주어진 문서 내용을 바탕으로 중요한 사실들을 추출하세요.\n"
                       "각 사실의 claim_type은 다음 영문 코드 중 하나로 지정하세요: PROPERTY, RIGHT_DUTY, DOC_INFO, DATE, AMOUNT, PARTY_INFO, ACTION, CONDITION, GENERAL.\n"
                       "기존 사실과 상충하면 assertion_status를 CONTRADICTION_CANDIDATE로 설정하세요.\n"
                       "반드시 다음과 같은 JSON 형식으로만 응답해야 합니다:\n"
                       "{{\"claims\": [{{\"statement\": \"...\", \"claim_type\": \"DATE\", \"assertion_status\": \"DOCUMENT_STATES\", \"confidence\": 0.9, \"source_span_ids\": [\"...\"], \"contradicts_fact_id\": null}}]}}\n"
                       "결과물은 반드시 유효한 JSON 포맷이어야 합니다."),
            ("human", "{context}")
        ])
        fallback_chain = fallback_prompt | llm
        response = fallback_chain.invoke({"context": context_str})

        try:
            text_content = response.content
            if text_content.startswith("```json"):
                text_content = text_content[7:-3]
            elif text_content.startswith("```"):
                text_content = text_content[3:-3]

            data = json.loads(text_content)
            result = EvidenceExtractionResultSchema(**data)
        except Exception as parse_error:
            logger.error(f"Failed to parse LLM JSON response: {str(parse_error)}")
            doc.status = "FAILED"
            doc.error_code = "AI_EXTRACTION_FAILED"
            db.commit()
            return False

    if not result or not result.claims:
        doc.status = "REVIEW_REQUIRED"
        db.commit()
        return True

    valid_span_ids = {s.id for s in spans}

    new_claims = []
    links_to_create = []
    contradiction_links_to_create = []

    for c_idx, claim_data in enumerate(result.claims):
        filtered_span_ids = [sid for sid in claim_data.source_span_ids if sid in valid_span_ids]

        if filtered_span_ids:
            normalized_code = normalize_to_claim_code(claim_data.claim_type)
            # LLM이 표시했거나 규칙 기반 상충 탐지기가 감지한 기존 Fact 확인
            conflicting_fact = None
            if getattr(claim_data, "contradicts_fact_id", None) and claim_data.contradicts_fact_id in facts_by_id:
                conflicting_fact = facts_by_id[claim_data.contradicts_fact_id]
            else:
                conflicting_fact = detect_conflicting_fact(claim_data.statement, existing_facts)

            assertion_status = claim_data.assertion_status
            if conflicting_fact:
                assertion_status = "CONTRADICTION_CANDIDATE"

            new_claim = EvidenceClaim(
                case_id=doc.case_id,
                evidence_id=doc.id,
                statement=claim_data.statement,
                claim_type=normalized_code,
                assertion_status=assertion_status,
                confidence=claim_data.confidence,
                review_status="PENDING",
                extractor_model="azure-openai",
            )
            db.add(new_claim)
            db.flush()  # id 할당을 위해 flush

            for sid in filtered_span_ids:
                links_to_create.append(EvidenceSpanClaimLink(
                    claim_id=new_claim.id,
                    span_id=sid,
                ))

            # 상충하는 기존 Fact가 확인되면 CONTRADICTS 링크를 생성하여 불일치 탐지 API(EVT-024) 및 그래프에 반영
            if conflicting_fact:
                contradiction_links_to_create.append(EvidenceLink(
                    evidence_id=doc.id,
                    claim_id=new_claim.id,
                    target_type="FACT",
                    target_id=conflicting_fact.id,
                    link_type="CONTRADICTS",
                ))

            new_claims.append(new_claim)

    if links_to_create:
        db.add_all(links_to_create)
    if contradiction_links_to_create:
        db.add_all(contradiction_links_to_create)

    doc.status = "REVIEW_REQUIRED"  # 사용자 검토 대기 상태
    doc.extraction_version = "llm-v1"
    db.commit()

    cur_span = get_current_span_id()
    if cur_span:
        try:
            update_span(cur_span, {
                "document_id": doc_id,
                "claims_count": len(new_claims),
                "contradictions_count": len(contradiction_links_to_create),
            })
        except Exception:
            pass

    return True


