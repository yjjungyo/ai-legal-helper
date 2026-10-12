import os
import hashlib
from datetime import datetime
from fastapi import Depends, HTTPException, Request, Response, Cookie
from sqlalchemy.orm import Session

from ai_legal_helper.database.session import get_db
from ai_legal_helper.database.models import User, UserSession, Case
from ai_legal_helper.utils.datetime_utils import get_kst_now

# 로컬 1인 테스트 모드 활성화 여부
# 기본값은 로컬 실행 편의를 위해 True이나, 자동화 테스트(TESTING=1)에서는 False로 엄격 검증
AUTH_BYPASS_DEFAULT = "true" if os.getenv("TESTING") != "1" else "false"
AUTH_BYPASS = os.getenv("AUTH_BYPASS", AUTH_BYPASS_DEFAULT).lower() in ("true", "1", "yes")

def get_current_user(request: Request, db: Session = Depends(get_db)):
    """현재 로그인된 사용자를 조회한다. 세션이 없을 경우 1인 테스트 모드에 따라 로컬 테스터로 자동 연결한다."""
    session_token = request.cookies.get("session_token")
    if session_token:
        token_hash = hashlib.sha256(session_token.encode()).hexdigest()
        user_session = db.query(UserSession).filter(
            UserSession.session_token_hash == token_hash,
            UserSession.revoked_at.is_(None)
        ).first()
        
        if user_session and user_session.expires_at >= get_kst_now():
            user = user_session.user
            if user and user.status == "ACTIVE":
                return user

    # 1인 로컬 개발/테스트 모드: 로그인 없이 바로 사용 가능하도록 기본 테스터 계정 반환
    if AUTH_BYPASS:
        local_user = db.query(User).filter(User.email == "tester@local").first()
        if not local_user:
            local_user = User(
                email="tester@local",
                password_hash="dev_bypass_local",
                display_name="로컬 테스터",
                status="ACTIVE"
            )
            db.add(local_user)
            db.commit()
            db.refresh(local_user)
        return local_user

    raise HTTPException(status_code=401, detail="인증이 필요합니다.")

def get_case_for_user(case_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Case:
    """주어진 사건이 현재 사용자의 소유인지 확인하고 반환한다."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="사건을 찾을 수 없거나 접근 권한이 없습니다.")

    # 1인 로컬 테스트 모드이거나 소유자가 지정되지 않은 기존 사건인 경우 접근 허용
    if AUTH_BYPASS:
        if not case.user_id:
            case.user_id = current_user.id
            db.commit()
        return case

    if case.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="해당 사건에 접근할 권한이 없습니다.")

    return case

