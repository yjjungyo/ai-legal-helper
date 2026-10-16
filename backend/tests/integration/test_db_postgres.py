import os
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from ai_legal_helper.database.session import engine, SessionLocal
from ai_legal_helper.database.models import Case
from sqlalchemy.orm.exc import StaleDataError
from dotenv import load_dotenv

# 로드 시 test DB URL 사용하도록 세션 오버라이드
load_dotenv()
test_db_url = os.environ.get("TEST_DATABASE_URL")
if test_db_url:
    from sqlalchemy import create_engine
    test_engine = create_engine(test_db_url)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
else:
    TestSessionLocal = SessionLocal

@pytest.fixture(scope="module")
def db_session():
    """테스트용 데이터베이스 세션을 제공한다."""
    if test_db_url:
        # 테스트 DB에 테이블 생성
        from ai_legal_helper.database.models import Base
        Base.metadata.create_all(bind=test_engine)
    
    session = TestSessionLocal()
    yield session
    
    # 롤백 및 세션 종료
    session.rollback()
    session.close()

def test_postgresql_connection(db_session):
    """
    PostgreSQL 연결을 확인한다.
    
    간단한 SELECT 1 쿼리를 통해 연결이 정상적으로 이루어졌는지 검증한다.
    """
    result = db_session.execute(text("SELECT 1")).scalar()
    assert result == 1

def test_transaction_insert_and_commit(db_session):
    """
    데이터베이스 트랜잭션 정상 처리를 확인한다.
    
    새로운 Case 객체를 생성하고, 커밋한 후 조회가 되는지 검증한다.
    """
    # given
    new_case = Case(title="트랜잭션 테스트 사건", description="테스트용 내용입니다.")
    
    # when
    db_session.add(new_case)
    db_session.commit()
    
    # then
    fetched_case = db_session.query(Case).filter_by(id=new_case.id).first()
    assert fetched_case is not None
    assert fetched_case.title == "트랜잭션 테스트 사건"

def test_optimistic_locking_conflict(db_session):
    """
    동시 수정 충돌(Optimistic Locking)을 확인한다.
    
    두 개의 서로 다른 세션에서 동일한 엔터티를 수정할 때,
    버전 정보 충돌로 인해 StaleDataError가 발생하는지 검증한다.
    """
    # given: 데이터 생성
    base_case = Case(title="동시성 테스트 사건 원본")
    db_session.add(base_case)
    db_session.commit()
    
    case_id = base_case.id
    
    # when: 서로 다른 세션에서 동일한 데이터를 조회
    session1 = TestSessionLocal()
    session2 = TestSessionLocal()
    
    case_in_session1 = session1.query(Case).get(case_id)
    case_in_session2 = session2.query(Case).get(case_id)
    
    # 첫 번째 세션에서 수정 및 반영
    case_in_session1.title = "세션1에서 수정됨"
    session1.commit()
    
    # 두 번째 세션에서 동일한 데이터를 수정하고 반영 시도
    case_in_session2.title = "세션2에서 수정됨"
    
    # then: 버전 불일치로 인한 예외 발생 확인
    with pytest.raises(StaleDataError):
        session2.commit()
        
    session1.close()
    session2.close()
