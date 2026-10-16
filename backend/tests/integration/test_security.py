import pytest
from fastapi.testclient import TestClient
from ai_legal_helper.api.main import app
import time

client = TestClient(app)

def create_user_and_get_cookies(email):
    client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "Password123!",
        "display_name": "Sec Test User"
    })
    res = client.post("/api/v1/auth/login", json={
        "email": email,
        "password": "Password123!"
    })
    return res.cookies

def test_case_ownership_security():
    # We must explicitly disable the dependency override for this test because we want to test actual auth
    from ai_legal_helper.api.dependencies import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    
    user1_email = f"u1_{int(time.time())}@example.com"
    user2_email = f"u2_{int(time.time())}@example.com"
    
    cookies1 = create_user_and_get_cookies(user1_email)
    cookies2 = create_user_and_get_cookies(user2_email)
    
    # 1. Create a case for user 1
    case_res = client.post("/api/v1/cases", json={
        "title": "User 1 Case",
        "case_type": "Civil"
    }, cookies=cookies1)
    
    assert case_res.status_code == 200
    case_id = case_res.json()["id"]
    
    # 2. User 1 accesses their case
    access_res1 = client.get(f"/api/v1/cases/{case_id}", cookies=cookies1)
    assert access_res1.status_code == 200
    
    # 3. User 2 tries to access User 1's case (Should be Forbidden)
    access_res2 = client.get(f"/api/v1/cases/{case_id}", cookies=cookies2)
    assert access_res2.status_code == 403
    
    # 4. User 2 tries to list cases (Should not see User 1's case)
    list_res2 = client.get("/api/v1/cases", cookies=cookies2)
    assert list_res2.status_code == 200
    cases2 = list_res2.json()
    assert all(c["id"] != case_id for c in cases2)
    
    # 5. Unauthenticated access (Should be Unauthorized)
    client.cookies.clear()
    unauth_res = client.get(f"/api/v1/cases/{case_id}")
    assert unauth_res.status_code == 401

