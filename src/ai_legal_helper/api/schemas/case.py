# -*- coding: utf-8 -*-
"""
Case 관련 API 스키마 (Case Schemas)

이 모듈은 FastAPI 엔드포인트에서 사건 관련 데이터를 송수신하기 위한
Pydantic 모델(스키마)들을 정의한다.
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class PartySchema(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., description="당사자 이름 또는 지칭")
    role: Optional[str] = Field(None, description="임차인, 임대인 등 역할")
    party_relationship: Optional[str] = Field(None, description="상대방과의 관계")
    notes: Optional[str] = None

class FactSchema(BaseModel):
    id: Optional[str] = None
    statement: str = Field(..., description="구조화된 단일 사실 내용")
    fact_type: Optional[str] = Field(None, description="날짜, 금액, 행위 등")
    confidence: Optional[float] = Field(None, description="추출 신뢰도")
    source_type: str = Field("USER_CLAIM")
    occurred_at: Optional[str] = Field(None, description="발생 시점 문자열")
    verification_status: str = Field("UNVERIFIED")

class EventSchema(BaseModel):
    id: Optional[str] = None
    title: str = Field(..., description="사건 요약")
    description: Optional[str] = None
    event_date: Optional[str] = Field(None, description="YYYY-MM-DD 또는 대략적 시기")
    date_precision: str = Field("EXACT")
    event_type: Optional[str] = None
    related_fact_ids: Optional[List[str]] = Field(default_factory=list)

class LegalIssueSchema(BaseModel):
    id: Optional[str] = None
    title: str = Field(..., description="법률 쟁점 명")
    description: Optional[str] = None
    related_fact_ids: Optional[List[str]] = Field(default_factory=list)
    status: str = Field("OPEN")

class CaseSchema(BaseModel):
    id: str
    title: str
    case_type: Optional[str] = None
    description: Optional[str] = None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class CaseDetailSchema(CaseSchema):
    parties: List[PartySchema] = Field(default_factory=list)
    facts: List[FactSchema] = Field(default_factory=list)
    events: List[EventSchema] = Field(default_factory=list)
    legal_issues: List[LegalIssueSchema] = Field(default_factory=list)

class CaseCreateRequest(BaseModel):
    title: Optional[str] = "새 사건"
    case_type: Optional[str] = None
    description: Optional[str] = None

class StatementAddRequest(BaseModel):
    statement: str = Field(..., description="사용자의 진술 내용")

