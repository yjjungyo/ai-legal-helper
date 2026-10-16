# -*- coding: utf-8 -*-
"""
사건 관리를 위한 데이터베이스 세션 설정 (Database Session)

이 모듈은 PostgreSQL 데이터베이스 연결을 위한 SQLAlchemy Engine과 SessionMaker를 제공한다.
FastAPI Dependency Injection에서 사용하거나 백그라운드 태스크에서 직접 세션을 열 때 사용한다.
기존 SQLite에서 PostgreSQL(psycopg)로 변경되었다.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# .env 파일에서 환경변수 로드
load_dotenv()

# 데이터베이스 URL 설정. 환경변수가 없으면 로컬 기본값 사용
SQLALCHEMY_DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql+psycopg://ai_user:ai_password@127.0.0.1:5432/ai_legal_helper"
)

# PostgreSQL 연결을 위한 Engine 생성 (SQLite 옵션 제거)
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # 끊어진 연결을 자동으로 다시 시도
)

# 세션 팩토리 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 모델의 베이스 클래스
Base = declarative_base()

def get_db():
    """
    FastAPI 의존성 주입(Dependency Injection)을 위한 데이터베이스 세션 제너레이터.
    
    요청 단위로 데이터베이스 세션을 열고, 완료 시 안전하게 세션을 닫는다.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
