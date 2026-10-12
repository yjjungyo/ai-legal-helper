from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class DocumentSourceLinkSchema(BaseModel):
    id: str
    section_id: Optional[str] = None
    source_type: str
    source_id: str
    evidence_span_id: Optional[str] = None
    verification_status: str

    class Config:
        from_attributes = True

class DocumentReviewSchema(BaseModel):
    id: str
    review_status: str
    review_comment: Optional[str] = None
    reviewed_at: datetime

    class Config:
        from_attributes = True

class DocumentExportSchema(BaseModel):
    id: str
    file_format: str
    file_path: str
    checksum: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class DocumentRevisionSchema(BaseModel):
    id: str
    document_id: str
    revision_number: int
    content: Optional[str] = None
    structured_content: Optional[Dict[str, Any]] = None
    generation_context_version: Optional[int] = None
    verification_status: str
    created_at: datetime
    source_links: List[DocumentSourceLinkSchema] = []
    reviews: List[DocumentReviewSchema] = []
    exports: List[DocumentExportSchema] = []

    class Config:
        from_attributes = True

class LegalDocumentSchema(BaseModel):
    id: str
    case_id: str
    action_id: Optional[str] = None
    document_type: str
    title: str
    status: str
    current_revision_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    revisions: List[DocumentRevisionSchema] = []

    class Config:
        from_attributes = True

class DocumentCreateRequest(BaseModel):
    document_type: str
    title: str
    action_id: Optional[str] = None

class DocumentUpdateRequest(BaseModel):
    content: Optional[str] = None
    structured_content: Optional[Dict[str, Any]] = None
    review_status: Optional[str] = None
    review_comment: Optional[str] = None

