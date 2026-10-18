# -*- coding: utf-8 -*-
"""
모듈명: action.py

[모듈 개요]
법률 대응 행동 계획(LegalAction), 사전 요건(ActionRequirement), 기한(ActionDeadline),
의존성(ActionDependency) 및 상태 변경 요청을 위한 Pydantic 스키마를 정의한다.
"""
from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime

class ActionRequirementSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    requirement_type: str
    description: Optional[str] = None
    satisfaction_status: str
    supporting_evidence_ids: Optional[List[str]] = None

class ActionDeadlineSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    deadline_type: str
    deadline_date: Optional[datetime] = None
    calculation_basis: Optional[str] = None
    verification_status: str

class ActionDependencySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    depends_on_action_id: str
    dependency_type: str

class LegalActionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_type: str
    title: str
    description: Optional[str] = None
    priority: str
    status: str
    rationale: Optional[str] = None
    risk_level: str
    requirements: List[ActionRequirementSchema] = []
    deadlines: List[ActionDeadlineSchema] = []
    dependencies_out: List[ActionDependencySchema] = []

class ActionStatusUpdateRequest(BaseModel):
    """대응 조치(LegalAction) 진행 상태 변경 요청 스키마."""
    status: str

class RequirementStatusUpdateRequest(BaseModel):
    """대응 조치 사전 요건(ActionRequirement) 충족 상태 변경 요청 스키마."""
    satisfaction_status: str


