import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from passlib.hash import argon2

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import User, UserSession, AuditLog
from ai_legal_helper.api.dependencies import get_current_user
from ai_legal_helper.utils.datetime_utils import get_kst_now

router = APIRouter(prefix="/auth", tags=["auth"])

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    display_name: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    display_name: Optional[str]
    status: str

def create_audit_log(db: Session, actor_id: str, event_type: str, resource_type: str, result: str):
    log = AuditLog(
        actor_user_id=actor_id,
        event_type=event_type,
        resource_type=resource_type,
        result=result
    )
    db.add(log)
    db.commit()

@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
        
    pwd_hash = argon2.hash(user.password)
    new_user = User(
        email=user.email,
        password_hash=pwd_hash,
        display_name=user.display_name
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    create_audit_log(db, new_user.id, "USER_REGISTER", "User", "SUCCESS")
    
    return new_user

@router.post("/login")
def login(creds: UserLogin, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == creds.email).first()
    if not user or not argon2.verify(creds.password, user.password_hash):
        if user:
            create_audit_log(db, user.id, "USER_LOGIN", "User", "FAIL_INVALID_CREDS")
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
        
    if user.status != "ACTIVE":
        create_audit_log(db, user.id, "USER_LOGIN", "User", "FAIL_INACTIVE")
        raise HTTPException(status_code=403, detail="활성화되지 않은 계정입니다.")

    session_token = str(uuid.uuid4())
    token_hash = hashlib.sha256(session_token.encode()).hexdigest()
    expires = get_kst_now() + timedelta(days=7)
    
    user_session = UserSession(
        user_id=user.id,
        session_token_hash=token_hash,
        expires_at=expires
    )
    db.add(user_session)
    db.commit()
    
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=False, # 개발용이므로 False. 운영 시 True 권장
        max_age=7*24*60*60
    )
    
    create_audit_log(db, user.id, "USER_LOGIN", "User", "SUCCESS")
    
    return {"message": "로그인 성공"}

@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session_token = request.cookies.get("session_token")
    if session_token:
        token_hash = hashlib.sha256(session_token.encode()).hexdigest()
        user_session = db.query(UserSession).filter(UserSession.session_token_hash == token_hash).first()
        if user_session:
            user_session.revoked_at = get_kst_now()
            create_audit_log(db, user_session.user_id, "USER_LOGOUT", "User", "SUCCESS")
            db.commit()
            
    response.delete_cookie("session_token")
    return {"message": "로그아웃 성공"}

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

