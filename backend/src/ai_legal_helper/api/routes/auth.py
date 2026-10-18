# -*- coding: utf-8 -*-
"""
모듈명: auth.py

[모듈 개요]
사용자 회원가입, 로그인(세션 쿠키 발급), 로그아웃, 현재 로그인 사용자 조회 API를 제공하는 라우터 모듈이다.
비밀번호는 Argon2 해시로 저장하며, 세션 토큰은 SHA-256 해시로 UserSession 테이블에 보관하고 감사 로그(AuditLog)를 기록한다.
"""
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, model_validator
from sqlalchemy.orm import Session
from passlib.hash import argon2

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import User, UserSession, AuditLog
from ai_legal_helper.api.dependencies import get_current_user
from ai_legal_helper.utils.datetime_utils import get_kst_now

router = APIRouter(prefix="/auth", tags=["auth"])


class UserCreate(BaseModel):
    """회원가입 요청 페이로드 스키마.

    프런트엔드 호환성을 위해 `display_name`과 `name` 중 어느 하나로 전달되어도
    `display_name`으로 정규화한다.
    """
    email: EmailStr
    password: str
    display_name: Optional[str] = None
    name: Optional[str] = None

    @model_validator(mode="after")
    def ensure_display_name(self) -> "UserCreate":
        """display_name 또는 name 중 하나를 필수 표시 이름으로 정규화한다."""
        resolved = (self.display_name or self.name or "").strip()
        if not resolved:
            raise ValueError("display_name 또는 name 필드가 필요합니다.")
        self.display_name = resolved
        self.name = resolved
        return self


class UserLogin(BaseModel):
    """로그인 요청 페이로드 스키마."""
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """사용자 프로필 응답 스키마."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: Optional[str] = None
    name: Optional[str] = None
    status: str

    @model_validator(mode="after")
    def populate_name_alias(self) -> "UserResponse":
        """프런트엔드 User.name 필드와 백엔드 display_name 필드를 동기화한다."""
        if not self.name and self.display_name:
            self.name = self.display_name
        return self


def create_audit_log(db: Session, actor_id: str, event_type: str, resource_type: str, result: str):
    """보안 및 인증 이벤트에 대한 감사 로그(AuditLog)를 데이터베이스에 기록한다.

    Args:
        db: 데이터베이스 세션.
        actor_id: 행위 주체 사용자 ID.
        event_type: 이벤트 유형 코드 (예: USER_REGISTER, USER_LOGIN, USER_LOGOUT).
        resource_type: 대상 리소스 유형.
        result: 처리 결과 상태 문자열.
    """
    log = AuditLog(
        actor_user_id=actor_id,
        event_type=event_type,
        resource_type=resource_type,
        result=result,
    )
    db.add(log)
    db.commit()


@router.post("/register", response_model=UserResponse)
def register(user: UserCreate, db: Session = Depends(get_db)):
    """신규 사용자를 등록하고 감사 로그를 남긴다.

    Args:
        user: 회원가입 요청 데이터 (이메일, 비밀번호, 표시 이름).
        db: 데이터베이스 세션.

    Returns:
        UserResponse: 생성된 사용자 정보.
    """
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    pwd_hash = argon2.hash(user.password)
    new_user = User(
        email=user.email,
        password_hash=pwd_hash,
        display_name=user.display_name,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    create_audit_log(db, new_user.id, "USER_REGISTER", "User", "SUCCESS")

    return UserResponse.model_validate(new_user)


@router.post("/login")
def login(creds: UserLogin, response: Response, db: Session = Depends(get_db)):
    """사용자 자격증명을 검증하고 HttpOnly 세션 쿠키 및 사용자 프로필 정보를 반환한다.

    Args:
        creds: 로그인 요청 데이터 (이메일, 비밀번호).
        response: 쿠키 설정을 위한 FastAPI Response 객체.
        db: 데이터베이스 세션.

    Returns:
        dict: 로그인 성공 메시지 및 사용자 프로필 정보(id, email, display_name, name, status).
    """
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
        expires_at=expires,
    )
    db.add(user_session)
    db.commit()

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=False,  # 개발 환경에서는 False, 운영 HTTPS 환경에서는 True 권장
        max_age=7 * 24 * 60 * 60,
    )

    create_audit_log(db, user.id, "USER_LOGIN", "User", "SUCCESS")

    return {
        "message": "로그인 성공",
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "name": user.display_name,
        "status": user.status,
    }


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """현재 활성 세션을 폐기(revoked_at 기록)하고 세션 쿠키를 삭제한다.

    Args:
        request: 쿠키 조회를 위한 FastAPI Request 객체.
        response: 쿠키 삭제를 위한 FastAPI Response 객체.
        db: 데이터베이스 세션.

    Returns:
        dict: 로그아웃 완료 메시지.
    """
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
    """현재 인증된 사용자의 프로필 정보를 반환한다.

    Args:
        current_user: 세션 쿠키 또는 인증 의존성을 통해 조회된 User 객체.

    Returns:
        UserResponse: 현재 로그인한 사용자 정보.
    """
    return UserResponse.model_validate(current_user)


