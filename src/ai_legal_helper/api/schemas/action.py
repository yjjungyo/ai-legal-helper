from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class ActionRequirementSchema(BaseModel):
    id: str
    requirement_type: str
    description: Optional[str] = None
    satisfaction_status: str
    supporting_evidence_ids: Optional[List[str]] = None

    class Config:
        from_attributes = True

class ActionDeadlineSchema(BaseModel):
    id: str
    deadline_type: str
    deadline_date: Optional[datetime] = None
    calculation_basis: Optional[str] = None
    verification_status: str

    class Config:
        from_attributes = True

class ActionDependencySchema(BaseModel):
    id: str
    depends_on_action_id: str
    dependency_type: str

    class Config:
        from_attributes = True

class LegalActionSchema(BaseModel):
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

    class Config:
        from_attributes = True

