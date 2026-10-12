# -*- coding: utf-8 -*-
"""
증거 인공지능 추출 서비스 (Evidence AI Extractor)

추출된 텍스트 Span들을 기반으로 LLM을 활용하여 사실관계, 당사자, 날짜 등의 
EvidenceClaim 후보를 추출한다.
추출된 후보는 사용자의 승인을 거치기 위해 REVIEW_STATUS="PENDING"으로 생성된다.
"""

import logging
import json
from typing import List, Dict, Any

from sqlalchemy.orm import Session
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from ai_legal_helper.database.models import EvidenceDocument, EvidenceSpan, EvidenceClaim, EvidenceSpanClaimLink
from ai_legal_helper.llm.gateway import get_llm

logger = logging.getLogger(__name__)

# LLM 출력을 위한 Pydantic 스키마 정의
class ExtractedClaimSchema(BaseModel):
    statement: str = Field(description="추출된 사실관계 진술. (예: '임대인 홍길동이 임차인 김철수와 2022년 3월 1일에 전세계약을 체결함')")
    claim_type: str = Field(description="사실관계의 유형. (DATE, AMOUNT, PARTY_INFO, ACTION, CONDITION, OTHER 중 하나)")
    assertion_status: str = Field(description="단언 상태. 문서에 확정적으로 쓰여진 사실이면 DOCUMENT_STATES, 일방의 주장이면 PARTY_ALLEGES, AI가 추론한 것이면 AI_INFERENCE, 불확실하면 UNCERTAIN.")
    confidence: float = Field(description="추출 결과의 신뢰도 (0.0 ~ 1.0)")
    source_span_ids: List[str] = Field(description="이 주장을 뒷받침하는 제공된 문단(span)의 ID 목록. 반드시 제공된 ID 중에 있어야 함.")

class EvidenceExtractionResultSchema(BaseModel):
    claims: List[ExtractedClaimSchema] = Field(description="추출된 주장 목록")

def extract_claims_from_evidence(db: Session, doc_id: str) -> bool:
    """
    특정 EvidenceDocument의 텍스트를 LLM에 전달하여 EvidenceClaim 후보들을 도출한다.
    결과물은 DB에 저장되며, 사용자가 검토할 수 있도록 준비된다.
    """
    doc = db.query(EvidenceDocument).filter_by(id=doc_id).first()
    if not doc:
        return False
        
    spans = db.query(EvidenceSpan).filter_by(evidence_id=doc_id).order_by(EvidenceSpan.created_at).all()
    if not spans:
        logger.warning(f"No spans found for document {doc_id}")
        return False
        
    # 최대 처리 한계 등을 고려하여 적절히 묶는 로직이 필요할 수 있으나 MVP에서는 전체 전송
    span_texts = []
    for s in spans:
        loc = f"Page {s.page_number}" if s.page_number else f"Para {s.paragraph_index}"
        span_texts.append(f"[Span ID: {s.id}] ({loc}): {s.text_excerpt}")
        
    context_str = "\n\n".join(span_texts)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", "당신은 법률 증거 분석 보조 AI입니다. 주어진 문서 내용을 바탕으로 중요한 사실관계, 당사자 정보, 금액, 날짜, 행위를 추출하세요.\n"
                   "반드시 제공된 'Span ID'를 source_span_ids에 포함하여 출처를 명확히 해야 합니다.\n"
                   "결과물은 JSON 형식으로 반환해야 합니다. 거짓 정보를 생성하지 마세요."),
        ("human", "다음 문서 텍스트에서 중요한 사실들을 추출해주세요.\n\n{context}")
    ])
    
    llm = get_llm(temperature=0.0)
    
    # with_structured_output이 지원되는 모델의 경우 직접 사용, 아니면 JSON parser 사용
    try:
        structured_llm = llm.with_structured_output(EvidenceExtractionResultSchema)
        chain = prompt | structured_llm
        result = chain.invoke({"context": context_str})
    except Exception as e:
        logger.warning(f"with_structured_output failed, falling back to JSON parsing: {str(e)}")
        # Fallback (프롬프트에 JSON 포맷 명시 후 파싱)
        fallback_prompt = ChatPromptTemplate.from_messages([
            ("system", "당신은 법률 증거 분석 보조 AI입니다. 주어진 문서 내용을 바탕으로 중요한 사실들을 추출하세요.\n"
                       "반드시 다음과 같은 JSON 형식으로만 응답해야 합니다:\n"
                       "{{\"claims\": [{{\"statement\": \"...\", \"claim_type\": \"...\", \"assertion_status\": \"...\", \"confidence\": 0.9, \"source_span_ids\": [\"...\"]}}]}}\n"
                       "결과물은 반드시 유효한 JSON 포맷이어야 합니다."),
            ("human", "{context}")
        ])
        fallback_chain = fallback_prompt | llm
        response = fallback_chain.invoke({"context": context_str})
        
        try:
            # Markdown JSON 블록 제거 처리
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
    
    for c_idx, claim_data in enumerate(result.claims):
        # 유효한 span id만 필터링
        filtered_span_ids = [sid for sid in claim_data.source_span_ids if sid in valid_span_ids]
        
        # 연결 가능한 span이 하나라도 있는 경우만 저장
        if filtered_span_ids:
            new_claim = EvidenceClaim(
                case_id=doc.case_id,
                evidence_id=doc.id,
                statement=claim_data.statement,
                claim_type=claim_data.claim_type,
                assertion_status=claim_data.assertion_status,
                confidence=claim_data.confidence,
                review_status="PENDING",
                extractor_model="azure-openai"
            )
            db.add(new_claim)
            db.flush() # id 할당을 위해 flush
            
            for sid in filtered_span_ids:
                links_to_create.append(EvidenceSpanClaimLink(
                    claim_id=new_claim.id,
                    span_id=sid
                ))
            
            new_claims.append(new_claim)
            
    if links_to_create:
        db.add_all(links_to_create)
        
    doc.status = "REVIEW_REQUIRED" # 사용자 검토 대기 상태
    doc.extraction_version = "llm-v1"
    db.commit()
    
    return True

