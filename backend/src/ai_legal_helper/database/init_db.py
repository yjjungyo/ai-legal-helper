# -*- coding: utf-8 -*-
"""
데이터베이스 초기화 스크립트

이 모듈은 데이터베이스 엔진을 사용하여 모든 테이블을 생성한다.
"""

from ai_legal_helper.database.session import engine, Base
from ai_legal_helper.database import models  # noqa: F401 모델이 등록되도록 임포트

def init_db():
    """모든 선언된 SQLAlchemy 모델을 바탕으로 테이블을 생성한다."""
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Database initialized successfully.")

