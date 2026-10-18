# -*- coding: utf-8 -*-
"""
모듈명: case.py

[모듈 개요]
FastAPI 엔드포인트에서 사건(Case) 및 하위 엔티티(Party, Fact, Event, LegalIssue) 데이터를
직렬화·역직렬화하기 위한 Pydantic 스키마를 정의한다.
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import datetime


class PartySchema(BaseModel):
    """사건 당사자(Party) 응답 스키마."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    name: str = Field(..., description="당사자 이름 또는 지칭")
    role: Optional[str] = Field(None, description="임차인, 임대인 등 역할")
    party_relationship: Optional[str] = Field(None, description="상대방과의 관계")
    notes: Optional[str] = None


class FactSchema(BaseModel):
    """사건 사실관계(Fact) 응답 스키마."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    statement: str = Field(..., description="구조화된 단일 사실 내용")
    fact_type: Optional[str] = Field(None, description="날짜, 금액, 행위 등")
    confidence: Optional[float] = Field(None, description="추출 신뢰도")
    source_type: str = Field("USER_CLAIM")
    occurred_at: Optional[str] = Field(None, description="발생 시점 문자열")
    verification_status: str = Field("UNVERIFIED")


class EventSchema(BaseModel):
    """사건 타임라인 이벤트(Event) 응답 스키마."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    title: str = Field(..., description="사건 요약")
    description: Optional[str] = None
    event_date: Optional[str] = Field(None, description="YYYY-MM-DD 또는 대략적 시기")
    date_precision: str = Field("EXACT")
    event_type: Optional[str] = None
    related_fact_ids: Optional[List[str]] = Field(default_factory=list)


class LegalIssueSchema(BaseModel):
    """법률 쟁점(LegalIssue) 응답 스키마."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    title: str = Field(..., description="법률 쟁점 명")
    description: Optional[str] = None
    related_fact_ids: Optional[List[str]] = Field(default_factory=list)
    status: str = Field("OPEN")


class CaseSchema(BaseModel):
    """사건 기본 정보 응답 스키마."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    case_type: Optional[str] = None
    description: Optional[str] = None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class CaseDetailSchema(CaseSchema):
    """하위 당사자·사실·이벤트·쟁점을 포함한 사건 상세 응답 스키마."""
    parties: List[PartySchema] = Field(default_factory=list)
    facts: List[FactSchema] = Field(default_factory=list)
    events: List[EventSchema] = Field(default_factory=list)
    legal_issues: List[LegalIssueSchema] = Field(default_factory=list)


class CaseCreateRequest(BaseModel):
    """사건 신규 생성 요청 스키마."""
    title: Optional[str] = "새 사건"
    case_type: Optional[str] = None
    description: Optional[str] = None


class CaseUpdateRequest(BaseModel):
    """사건 기본 정보 수정 요청 스키마 (EVT-006)."""
    title: Optional[str] = Field(None, description="수정할 사건 제목")
    case_type: Optional[str] = Field(None, description="수정할 사건 유형")
    description: Optional[str] = Field(None, description="수정할 사건 설명")
    status: Optional[str] = Field(None, description="수정할 사건 진행 상태 (예: IN_PROGRESS, CLOSED)")


class StatementAddRequest(BaseModel):
    """사건 사실관계 진술 추가 요청 스키마."""
    statement: str = Field(..., description="사용자의 진술 내용")


