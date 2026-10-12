import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
import os

from ai_legal_helper.database.session import Base, get_db
from ai_legal_helper.database import models  # Import all models to register them
from ai_legal_helper.api.main import app

# Use the test DB URL
TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://ai_user:ai_password@127.0.0.1:5432/ai_legal_helper_test")
engine = create_engine(TEST_DB_URL)
Base.metadata.create_all(bind=engine)

def override_get_db():
    from sqlalchemy.orm import sessionmaker
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
import ai_legal_helper.api.routes.evidence
ai_legal_helper.api.routes.evidence.get_db = override_get_db

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from sqlalchemy.orm import sessionmaker
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    user = models.User(id="test-user-id", email="test@example.com", display_name="Test User", password_hash="fakehash")
    db.add(user)
    db.commit()
    db.close()
    
    yield
    Base.metadata.drop_all(bind=engine)

def test_evidence_workflow():
    # 1. Create a case
    res = client.post("/api/v1/cases", json={"title": "Test Case", "case_type": "TEST"})
    assert res.status_code == 200
    case_id = res.json()["id"]

    # 2. Upload an evidence file
    # We will upload a simple text file
    test_content = b"This is a test evidence file content about returning 1,000,000 KRW deposit."
    
    # We use a tuple for files: (filename, fileobj, content_type)
    res = client.post(
        f"/api/v1/cases/{case_id}/evidence",
        files={"file": ("test_evidence.txt", test_content, "text/plain")}
    )
    assert res.status_code == 200
    doc = res.json()
    assert doc["status"] == "UPLOADED"
    evidence_id = doc["evidence_id"]

    # Background extraction is triggered automatically on upload.
    # Instead, we will simulate the extraction output manually in DB or just assume it works.
    # Let's check status right after. It might be EXTRACTING or REVIEW_REQUIRED.
    res = client.get(f"/api/v1/cases/{case_id}/evidence")
    docs = res.json()
    assert len(docs) == 1
    
    # Since the background extraction might be running or finished, we won't assert the exact final status here
    # but we can check the endpoint exists.
    res = client.get(f"/api/v1/cases/{case_id}/evidence/{evidence_id}/claims")
    assert res.status_code == 200
