# -*- coding: utf-8 -*-
"""
사건 정보 추출기 (Fact & Party Extractor)

사용자의 진술로부터 사건의 당사자, 개별 사실관계, 법률 쟁점 후보 등을 구조화하여 추출한다.
P2.1에서 확인된 Azure OpenAI의 Structured Output 미지원 문제를 우회하기 위해
명시적으로 JSON 형식을 요구하고 결과를 파싱하는 방식을 사용한다.
"""

import json
from typing import List, Dict, Any
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from ai_legal_helper.llm.gateway import get_llm
from ai_legal_helper.observability.decorators import trace

class ExtractedParty(BaseModel):
    name: str = Field(description="이름 또는 지칭 (예: 임대인, 철수)")
    role: str = Field(description="역할 (예: 임차인, 임대인, 대리인 등)")
    relationship: str = Field(description="다른 당사자와의 관계 (예: 임대인의 대리인)")

class ExtractedFact(BaseModel):
    statement: str = Field(description="분리된 단일 사실 내용 (예: 2024년 4월에 전세계약을 체결함)")
    fact_type: str = Field(description="사실 유형 (날짜, 금액, 계약조건, 통지, 행위 등)")
    occurred_at: str = Field(description="발생 시점 문자열 (명시되지 않았으면 빈 문자열)")
    source_type: str = Field(description="USER_CLAIM, DOCUMENT_SUPPORTED, AI_INFERENCE 중 하나")

class ExtractionResult(BaseModel):
    parties: List[ExtractedParty]
    facts: List[ExtractedFact]
    missing_info_questions: List[str] = Field(description="이 사실들만으로 판단하기 부족하여 추가로 물어봐야 할 질문 리스트 (없으면 빈 리스트)")

EXTRACTION_PROMPT = """
당신은 법률 사실관계 추출 AI입니다.
사용자의 진술을 분석하여 관련된 당사자(parties)와 개별 사실관계(facts)를 최대한 잘게 쪼개어 추출하세요.
또한 현재까지의 정보만으로 파악하기 어려운 핵심 사실이 있다면 추가 질문(missing_info_questions)을 1~2개 생성하세요.

원칙:
1. 원문에 없는 사실을 상상해서 지어내지 마세요.
2. 사실과 단순 감정 표현을 구분하세요.
3. 동일한 사실은 중복되지 않게 추출하세요.

출력 형식은 반드시 아래 JSON 스키마를 따르는 순수 JSON 문자열이어야 합니다. (Markdown 코드 블록 없이 출력하세요)
{{
    "parties": [
        {{"name": "...", "role": "...", "relationship": "..."}}
    ],
    "facts": [
        {{"statement": "...", "fact_type": "...", "occurred_at": "...", "source_type": "..."}}
    ],
    "missing_info_questions": [
        "..."
    ]
}}

사용자 진술:
{statement}
"""

@trace
def extract_case_info(statement: str) -> ExtractionResult:
    """
    사용자의 진술 텍스트를 받아 당사자, 사실관계, 추가 질문을 JSON 형태로 추출한다.
    
    Args:
        statement (str): 사용자의 자유 형식 진술
        
    Returns:
        ExtractionResult: 추출된 구조화 데이터
    """
    llm = get_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_template(EXTRACTION_PROMPT)
    
    chain = prompt | llm
    res = chain.invoke({"statement": statement})
    
    content = (res.content or "").strip()
    
    # 마크다운 코드 블록 제거 (혹시 포함되었을 경우)
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    
    try:
        data = json.loads(content)
        return ExtractionResult(**data)
    except Exception as e:
        # 추출 실패 시 최소한의 원문 사실을 남김
        return ExtractionResult(
            parties=[],
            facts=[ExtractedFact(
                statement=statement, 
                fact_type="원문", 
                occurred_at="", 
                source_type="USER_CLAIM"
            )],
            missing_info_questions=[]
        )

