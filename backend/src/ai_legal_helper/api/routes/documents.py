# -*- coding: utf-8 -*-
"""
모듈명: documents.py

[모듈 개요]
사건별 법률 문서(내용증명, 통지서, 고소장 등) 초안 AI 생성, 목록/상세 조회,
사용자 직접 편집(새 리비전 생성), DOCX/PDF 파일 내보내기(Export)를 처리하는 FastAPI 라우터 모듈이다.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List
import os

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import (
    LegalDocument, DocumentRevision, DocumentReview, DocumentExport, Case, User, AuditLog
)
from ai_legal_helper.api.schemas.document import (
    LegalDocumentSchema, DocumentCreateRequest, DocumentUpdateRequest, DocumentRevisionSchema
)
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
        if doc and req.title and req.title.strip():
            doc.title = req.title.strip()
        
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
        db.refresh(doc)
        
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
    """특정 법률 문서의 상세 정보 및 리비전 이력을 조회한다."""
    doc = db.query(LegalDocument).filter(LegalDocument.id == document_id, LegalDocument.case_id == case.id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return doc

@router.put("/{document_id}", response_model=LegalDocumentSchema)
@router.patch("/{document_id}", response_model=LegalDocumentSchema)
def update_document(
    document_id: str,
    req: DocumentUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    case: Case = Depends(get_case_for_user),
    db: Session = Depends(get_db),
):
    """법률 문서 초안 본문을 편집하여 신규 리비전(DocumentRevision)을 생성하고 문서 상태를 갱신한다."""
    doc = db.query(LegalDocument).filter(
        LegalDocument.id == document_id,
        LegalDocument.case_id == case.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

    latest_rev = (
        db.query(DocumentRevision)
        .filter(DocumentRevision.document_id == doc.id)
        .order_by(DocumentRevision.revision_number.desc())
        .first()
    )
    next_rev_num = (latest_rev.revision_number + 1) if latest_rev else 1

    if req.content is not None or req.structured_content is not None:
        new_content = req.content if req.content is not None else (latest_rev.content if latest_rev else "")
        new_struct = (
            req.structured_content
            if req.structured_content is not None
            else (latest_rev.structured_content if latest_rev else {})
        )
        new_rev = DocumentRevision(
            document_id=doc.id,
            revision_number=next_rev_num,
            content=new_content,
            structured_content=new_struct,
            generation_context_version=case.version,
            verification_status="USER_EDITED",
        )
        db.add(new_rev)
        db.flush()
        doc.current_revision_id = new_rev.id
        target_rev_id = new_rev.id
    else:
        target_rev_id = doc.current_revision_id

    if req.review_status and target_rev_id:
        review = DocumentReview(
            document_revision_id=target_rev_id,
            review_status=req.review_status,
            review_comment=req.review_comment,
        )
        db.add(review)
        if req.review_status == "APPROVED":
            doc.status = "FINALIZED"

    audit = AuditLog(
        actor_user_id=current_user.id,
        case_id=case.id,
        event_type="UPDATE_DOCUMENT",
        resource_type="LegalDocument",
        resource_id=doc.id,
        result="SUCCESS",
    )
    db.add(audit)
    db.commit()
    db.refresh(doc)
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

