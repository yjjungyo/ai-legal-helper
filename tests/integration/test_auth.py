import pytest
from fastapi.testclient import TestClient
from ai_legal_helper.api.main import app
import time

client = TestClient(app)

def test_register_and_login():
    from ai_legal_helper.api.dependencies import get_current_user
    app.dependency_overrides.pop(get_current_user, None)
    
    # 1. Register a new user
    unique_email = f"test_{int(time.time())}@example.com"
    reg_res = client.post("/api/v1/auth/register", json={
        "email": unique_email,
        "password": "Password123!",
        "display_name": "Integration Test User"
    })
    
    assert reg_res.status_code == 200
    reg_data = reg_res.json()
    assert reg_data["email"] == unique_email
    assert reg_data["display_name"] == "Integration Test User"
    
    # Check that a session cookie was NOT set in register
    assert "session_token" not in reg_res.cookies
    
    # 2. Login
    login_res = client.post("/api/v1/auth/login", json={
        "email": unique_email,
        "password": "Password123!"
    })
    assert login_res.status_code == 200
    assert login_res.json()["message"] == "로그인 성공"
    
    # Check session cookie
    new_cookies = login_res.cookies
    assert "session_token" in new_cookies
    
    # 3. Get ME
    me_res = client.get("/api/v1/auth/me", cookies=new_cookies)
    assert me_res.status_code == 200
    assert me_res.json()["email"] == unique_email
    
    # 4. Logout
    logout_res = client.post("/api/v1/auth/logout", cookies=new_cookies)
    assert logout_res.status_code == 200
    

    invalid_res = client.post("/api/v1/auth/login", json={
        "email": unique_email,
        "password": "WrongPassword!"
    })
    assert invalid_res.status_code == 401
