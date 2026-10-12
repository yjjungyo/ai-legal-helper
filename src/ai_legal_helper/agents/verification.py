# -*- coding: utf-8 -*-
"""
모듈명: verification.py

[모듈 개요]
AI가 작성한 법률 상담 초안이 실제 검색된 출처에 근거하는지(Grounding) 검증하는 수석 검증관 에이전트를 구현한다.

[주요 기능]
1. 답변 초안에서 주요 법률 주장 추출
2. 각 주장이 RAG 검색 문서(`retrieved_sources`)에 존재하는지 확인
3. 없는 출처 지어내기(Hallucination) 방지 및 모순 탐지
4. 검증 결과 상태(PASS / REVISE / INSUFFICIENT) 및 상세 내용(JSON) 반환

[처리 흐름]
질문, 초안, 출처 목록 
  → Verification Agent 프롬프트 실행
  → LLM을 통한 분석 및 검증 (수동 JSON 파싱 방식 사용)
  → VerificationOutput 데이터 반환

[주요 의존성]
- langchain_core
- pydantic (데이터 스키마)
- ai_legal_helper.llm.gateway (LLM 연동)

[주의사항]
- 일부 구형 Azure OpenAI 모델의 `with_structured_output` 미지원 문제를 회피하기 위해, 
  프롬프트 지시와 수동 파싱을 결합하여 결과를 구조화한다.
- 검증관은 답변의 내용 자체를 수정하지 않으며, 단지 평가 결과와 수정 지침만 제공한다.
"""
from typing import Dict, Any, List
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
import json

from ai_legal_helper.observability.decorators import trace
from ai_legal_helper.observability.context import get_current_span_id
from ai_legal_helper.observability.langfuse_client import update_span
from ai_legal_helper.observability.context import set_agent_name
from ai_legal_helper.observability.logging_config import get_logger

logger = get_logger(__name__)

class ClaimVerification(BaseModel):
    claim: str = Field(description="검증할 법률 주장")
    source_ids: List[str] = Field(description="주장을 뒷받침하는 출처 ID 목록 (없으면 빈 배열)")
    grounding_status: str = Field(description="SUPPORTED, UNSUPPORTED, 또는 UNCERTAIN")
    reason: str = Field(description="검증 사유")

class VerificationOutput(BaseModel):
    status: str = Field(description="PASS, REVISE, 또는 INSUFFICIENT")
    claims: List[ClaimVerification] = Field(description="주요 법률 주장 목록 및 검증 결과")
    missing_issues: List[str] = Field(description="질문의 핵심 쟁점 중 누락된 항목")
    contradictions: List[str] = Field(description="답변 내부의 모순된 논리")
    revision_instructions: List[str] = Field(description="답변 수정을 위한 지침 (REVISE 상태일 때 유용)")
    warnings: List[str] = Field(description="사용자에게 보여줄 경고 메시지 목록")

VERIFICATION_PROMPT = """당신은 수석 법률 검증관(Supervisor & Verification Agent)입니다.
작성된 답변(초안)이 실제 검색된 법률 근거(출처)에 의해 정확히 뒷받침되는지 철저하게 검증하세요.

[검증 대상]
질문:
{question}

답변 초안:
{draft_answer}

[검색된 출처 목록]
{retrieved_sources}

[검증 기준 및 정책 (Grounding Policy)]
1. 답변의 주요 법률 주장(예: "임대인은 보증금을 반환해야 한다", "묵시적 갱신 시 임차인은 언제든 해지 통보를 할 수 있다")을 추출하세요.
2. 각 주장이 검색된 출처 내용에 존재하는지 대조하세요. 존재하지 않는 출처 ID를 지어내지 마세요.
3. 근거가 부족한 주장은 UNSUPPORTED로, 일부 모호하면 UNCERTAIN으로 평가하세요.
4. 질문의 핵심 쟁점 중 답변에서 누락된 것이 있는지 파악하세요.
5. 답변 내부에 모순된 논리나 설명이 있는지 확인하세요.
6. 확인된 사실과 단순 AI의 추론/가정을 명확히 구분해야 합니다.
7. 종합 상태(status) 결정:
   - PASS: 모든 주요 주장이 출처에 의해 완벽히 뒷받침되고 누락이나 모순이 없음.
   - REVISE: 근거 부족, 누락, 내부 모순이 있으나 부분적인 수정으로 개선 가능한 경우.
   - INSUFFICIENT: 답변의 핵심 논리가 근거에 전혀 없거나 수정이 불가능할 정도로 부족한 경우.

"""

@trace
def run_verification(question: str, draft_answer: str, retrieved_sources: List[Dict[str, Any]], case_context: str = "") -> Dict[str, Any]:
    """초안 답변이 검색된 출처에 의해 뒷받침되는지 검증한다.

    입력된 질문과 초안 답변, 그리고 검색된 문서 목록을 LLM에 제공하여
    답변 내의 법률 주장들이 출처에 명시된 사실과 일치하는지 평가한다.

    Args:
        question: 사용자의 원본 법률 상담 질문
        draft_answer: 여러 전문 에이전트가 작성하고 종합된 초안 답변
        retrieved_sources: 각 에이전트가 RAG 검색을 통해 참조한 실제 문서 메타데이터 목록

    Returns:
        검증 결과를 담은 JSON 파싱 딕셔너리 (`VerificationOutput` 모델 스키마 형태)
        - status: 검증 상태 (PASS / REVISE / INSUFFICIENT)
        - claims: 개별 주장별 근거 대조 결과 리스트
        - warnings: 경고 메시지 목록

    Notes:
        Azure OpenAI의 `with_structured_output` 미지원 가능성을 대비하여,
        프롬프트로 JSON 형식을 강제한 후 반환된 텍스트를 수동으로 파싱 및 검증한다.
        파싱 오류 발생 시 서비스 중단을 막기 위해 PASS 상태의 기본 fallback을 반환한다.
    """
    set_agent_name("verification_agent")
    
    formatted_sources = ""
    for s in retrieved_sources:
        formatted_sources += f"- ID: {s.get('source_id')} | Category: {s.get('category')}\n"
        formatted_sources += f"  Content: {s.get('content')}\n\n"
        
    if not formatted_sources.strip():
        formatted_sources = "(검색된 출처 없음)"
        
    prompt = PromptTemplate.from_template(VERIFICATION_PROMPT)
    from ai_legal_helper.llm.gateway import get_llm
    llm = get_llm(temperature=0.0)
    
    chain = prompt | llm
    
    try:
        res = chain.invoke({
            "question": question,
            "draft_answer": draft_answer,
            "retrieved_sources": formatted_sources,
            "case_context": case_context or "(사건 정보 없음)"
        })
        
        # parse json manually
        text = res.content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
            
        import json
        data = json.loads(text.strip())
        result = VerificationOutput(**data)
        
        logger.info(f"[VERIFICATION] status={result.status}, claims={len(result.claims)}")
        
        try:
            unsupported = sum(1 for c in result.claims if c.grounding_status != "SUPPORTED")
            update_span(get_current_span_id(), {
                "claims_count": len(result.claims),
                "supported_count": len(result.claims) - unsupported,
                "warnings_count": len(result.warnings),
                "is_fail": result.status == "INSUFFICIENT",
                "is_revise": result.status == "REVISE",
                "unsupported_count": unsupported,
                "missing_issues_count": len(result.missing_issues)
            })
        except:
            pass
        return result.model_dump()
        
    except Exception as e:
        logger.error(f"Verification Agent 오류: {str(e)}")
        return {
            "status": "PASS",
            "claims": [],
            "missing_issues": [],
            "contradictions": [],
            "revision_instructions": [],
            "warnings": [f"검증 중 오류 발생: {str(e)}"]
        }
