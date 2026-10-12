import pytest
import os
os.environ["TESTING"] = "1"

from ai_legal_helper.api.main import app
from ai_legal_helper.api.dependencies import get_current_user
from ai_legal_helper.database.models import User
from ai_legal_helper.database.session import SessionLocal

def override_get_current_user():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == "test-user-id").first()
        if not user:
            user = User(
                id="test-user-id",
                email="test@example.com",
                display_name="Test User",
                password_hash="fakehash"
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    finally:
        db.close()

@pytest.fixture(autouse=True)
def override_dependencies():
    app.dependency_overrides[get_current_user] = override_get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)
