import pytest
import uuid
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
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
    user = db.query(m.User).filter_by(id='test-user-id').first()
    if not user:
        user = m.User(id='test-user-id', email='test@example.com', display_name='Test User', password_hash='fakehash')
        db.add(user); db.commit()
    case = m.Case(title="Test Case", case_type="주택임대차", user_id="test-user-id")
    db.add(case)
    db.commit()
    db.refresh(case)

    action = m.LegalAction(
        case_id=case.id,
        action_type="내용증명 발송",
        title="임대차보증금 반환 요구",
        description="요구",
        status="PROPOSED",
        risk_level="LOW",
        confidence=0.9
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    yield case, action

def test_get_workflow_status_case_created(client: TestClient, db, setup_case_and_action):
    # setup_case_and_action 픽스처는 case와 action을 만듦
    case, action = setup_case_and_action
    
    # Action이 있으므로 ACTION_PLAN_READY 상태여야 함
    response = client.get(f"/api/v1/cases/{case.id}/workflow/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ACTION_PLAN_READY"

def test_get_workflow_status_not_found(client: TestClient):
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/v1/cases/{fake_id}/workflow/status")
    assert response.status_code == 404
