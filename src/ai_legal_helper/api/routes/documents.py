# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
import os

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import LegalDocument, DocumentRevision, DocumentExport, Case, User, AuditLog
from ai_legal_helper.api.schemas.document import LegalDocumentSchema, DocumentCreateRequest, DocumentRevisionSchema
from ai_legal_helper.workflows.document_workflow import build_document_graph, DocumentState
from ai_legal_helper.api.dependencies import get_current_user, get_case_for_user

router = APIRouter(prefix="/cases/{case_id}/documents", tags=["documents"])

@router.post("", response_model=LegalDocumentSchema)
def create_document(
    req: DocumentCreateRequest, 
    request: Request,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user), 
    db: Session = Depends(get_db)
):
    """새로운 법률 문서 초안을 생성한다."""
    app = build_document_graph()
    
    state = DocumentState(
        case_id=case.id,
        action_id=req.action_id,
        document_type=req.document_type
    )
    
    final_state = app.invoke(state.dict())
    
    if final_state["revision_id"]:
        doc = db.query(LegalDocument).filter(LegalDocument.current_revision_id == final_state["revision_id"]).first()
        
        audit = AuditLog(
            actor_user_id=current_user.id,
            case_id=case.id,
            event_type="CREATE_DOCUMENT",
            resource_type="LegalDocument",
            resource_id=doc.id,
            result="SUCCESS"
        )
        db.add(audit)
        db.commit()
        
        return doc
    else:
        raise HTTPException(status_code=400, detail="문서 생성 실패: " + final_state["draft_content"])

@router.get("", response_model=List[LegalDocumentSchema])
def list_documents(case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    """사건의 문서 목록을 조회한다."""
    docs = db.query(LegalDocument).filter(LegalDocument.case_id == case.id).all()
    return docs

@router.get("/{document_id}", response_model=LegalDocumentSchema)
def get_document(document_id: str, case: Case = Depends(get_case_for_user), db: Session = Depends(get_db)):
    doc = db.query(LegalDocument).filter(LegalDocument.id == document_id, LegalDocument.case_id == case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return doc

@router.post("/{document_id}/export")
def export_document(
    document_id: str, 
    request: Request,
    format: str = "docx",
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user), 
    db: Session = Depends(get_db)
):
    doc = db.query(LegalDocument).filter(LegalDocument.id == document_id, LegalDocument.case_id == case.id).first()
    if not doc or not doc.current_revision_id:
        raise HTTPException(status_code=404, detail="문서 또는 리비전을 찾을 수 없습니다.")
        
    revision = db.query(DocumentRevision).filter(DocumentRevision.id == doc.current_revision_id).first()
    
    output_dir = os.path.join(os.getcwd(), "data", "exports")
    format_lower = format.lower()
    
    if format_lower == "pdf":
        from ai_legal_helper.case_intelligence.document_exporter import export_pdf
        filepath = export_pdf(revision, output_dir)
        media_type = 'application/pdf'
        file_format_enum = "PDF"
    else:
        from ai_legal_helper.case_intelligence.document_exporter import export_docx
        filepath = export_docx(revision, output_dir)
        media_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        file_format_enum = "DOCX"
    
    export_record = DocumentExport(
        document_revision_id=revision.id,
        file_format=file_format_enum,
        file_path=filepath
    )
    
    audit = AuditLog(
        actor_user_id=current_user.id,
        event_type="EXPORT_DOCUMENT",
        resource_type="LegalDocument",
        resource_id=doc.id,
        result="SUCCESS"
    )
    db.add(export_record)
    db.add(audit)
    db.commit()
    
    # Return file securely instead of file path
    filename = os.path.basename(filepath)
    return FileResponse(path=filepath, filename=filename, media_type=media_type)

