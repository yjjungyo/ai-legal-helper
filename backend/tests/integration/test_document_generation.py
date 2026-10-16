import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, MagicMock

from ai_legal_helper.api.main import app
from ai_legal_helper.database.session import Base, get_db
from ai_legal_helper.database import models as m

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://ai_user:ai_password@127.0.0.1:5432/ai_legal_helper_test",
)
engine = create_engine(TEST_DB_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(scope="module")
def db():
    Base.metadata.create_all(bind=engine)
    s = TestingSessionLocal()
    yield s
    s.close()

@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)

@pytest.fixture
def setup_case_and_action(db):
    """테스트용 사건 및 Action 데이터를 생성합니다."""
    # 사용자 생성 (외래키 제약조건 방지)
    user = db.query(m.User).filter_by(id="test-user-id").first()
    if not user:
        user = m.User(id="test-user-id", email="test@example.com", display_name="Test User", password_hash="fakehash")
        db.add(user)
        db.commit()
    
    # 사건 생성
    case = m.Case(title="Test Case for Document", case_type="주택임대차", user_id="test-user-id")
    db.add(case)
    db.commit()
    db.refresh(case)

    # Action 생성
    action = m.LegalAction(
        case_id=case.id,
        action_type="내용증명 발송",
        title="임대차보증금 반환 요구 내용증명",
        description="임대차계약 만료에 따른 보증금 반환 요구",
        status="PROPOSED",
        risk_level="LOW",
        confidence=0.9
    )
    db.add(action)
    db.commit()
    db.refresh(action)

    yield case, action

@patch("ai_legal_helper.api.routes.documents.build_document_graph")
def test_generate_document_endpoint(
    mock_compile,
    client: TestClient,
    setup_case_and_action,
    db
):
    """
    POST /cases/{case_id}/documents 엔드포인트를 통해 문서 생성을 요청하는 테스트입니다.
    LangGraph 워크플로우를 모킹하여 실제 AI 호출 없이 상태 변경만 검증합니다.
    """
    case, action = setup_case_and_action

    # 모의 문서 및 리비전 생성
    doc = m.LegalDocument(
        case_id=case.id,
        action_id=action.id,
        document_type="내용증명",
        title="임대차보증금 반환 요구 내용증명",
        status="DRAFT"
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    rev = m.DocumentRevision(
        document_id=doc.id,
        revision_number=1,
        content="임시 내용",
        structured_content={"body": "보증금 반환해 주세요."},
        verification_status="PENDING"
    )
    db.add(rev)
    db.commit()
    db.refresh(rev)

    doc.current_revision_id = rev.id
    db.commit()

    # 모킹: LangGraph 실행 결과를 반환하도록 설정
    mock_app = MagicMock()
    mock_app.invoke.return_value = {
        "messages": [],
        "case_id": str(case.id),
        "action_id": str(action.id),
        "document_type": "내용증명",
        "requirements": ["임대인 정보", "임차인 정보", "계약일", "보증금액"],
        "draft_content": {
            "title": "임대차보증금 반환 요구",
            "sender": "임차인 Test",
            "receiver": "임대인 Test",
            "body": "보증금 반환해 주세요.",
            "date": "2024-01-01"
        },
        "document_id": str(doc.id),
        "revision_id": str(rev.id),
        "verification_result": True,
        "errors": []
    }
    mock_compile.return_value = mock_app

    # 요청 페이로드
    payload = {
        "action_id": str(action.id),
        "document_type": "내용증명",
        "title": "임대차보증금 반환 요구 내용증명"
    }

    # API 호출
    response = client.post(f"/api/v1/cases/{case.id}/documents", json=payload)
    
    # 응답 검증
    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == str(case.id)
    assert data["action_id"] == str(action.id)
    assert data["document_type"] == "내용증명"
    assert data["status"] == "DRAFT"
    
    # DB 검증
    doc = db.query(m.LegalDocument).filter_by(id=data["id"]).first()
    assert doc is not None
    assert doc.status == "DRAFT"
    assert doc.current_revision_id is not None

    rev = db.query(m.DocumentRevision).filter_by(id=doc.current_revision_id).first()
    assert rev is not None
    assert rev.document_id == doc.id
    assert "body" in rev.structured_content
    assert rev.structured_content["body"] == "보증금 반환해 주세요."

def test_get_documents_endpoint(
    client: TestClient,
    setup_case_and_action,
    db
):
    """
    GET /cases/{case_id}/documents 엔드포인트가 문서를 반환하는지 테스트합니다.
    """
    case, action = setup_case_and_action

    # 수동으로 문서 데이터 삽입
    doc = m.LegalDocument(
        case_id=case.id,
        action_id=action.id,
        document_type="내용증명",
        title="수동 생성 문서",
        status="DRAFT"
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    rev = m.DocumentRevision(
        document_id=doc.id,
        revision_number=1,
        content="임시 내용",
        structured_content={"body": "임시 내용"},
        verification_status="PENDING"
    )
    db.add(rev)
    db.commit()
    db.refresh(rev)

    doc.current_revision_id = rev.id
    db.commit()

    # API 호출
    response = client.get(f"/api/v1/cases/{case.id}/documents")
    print(response.json())
    assert response.status_code == 200
    data = response.json()
    
    assert len(data) >= 1
    assert any(d["id"] == str(doc.id) for d in data)
