# AI Legal Helper — 데이터베이스 운영 가이드 (DB Operations)

본 문서는 P2.2 Case Intelligence 개발 과정에서 도입된 PostgreSQL 데이터베이스의 운영 방법을 설명한다.
개발자는 이 가이드에 따라 데이터베이스를 시작, 종료, 백업, 복구, 초기화해야 한다.

## 1. 개요
*   **RDBMS**: PostgreSQL 17
*   **실행 환경**: Docker Compose (Windows Docker Desktop 기반)
*   **접속 포트**: `127.0.0.1:5432` (외부 노출 차단)
*   **영구 저장소**: Docker Named Volume (`pgdata`)
*   **마이그레이션 도구**: Alembic
*   **ORM**: SQLAlchemy 2.x + psycopg 3

## 2. Docker Compose 운영

### 데이터베이스 시작
```bash
# 백그라운드에서 PostgreSQL 컨테이너 실행
docker compose up -d
```
*최초 실행 시 `scripts/init-multiple-databases.sh`를 통해 `POSTGRES_DB`와 `POSTGRES_TEST_DB`가 자동 생성된다.*

### 데이터베이스 종료
```bash
# 컨테이너 중지 (데이터는 pgdata 볼륨에 유지됨)
docker compose down
```

### 데이터베이스 완전 초기화 (데이터 삭제)
**주의: 이 작업은 영구 저장된 데이터를 모두 삭제한다.**
```bash
# 볼륨까지 포함하여 삭제
docker compose down -v
# 이후 다시 시작하여 새 볼륨 생성
docker compose up -d
# 마이그레이션 재실행 필요
.venv\Scripts\alembic upgrade head
```

## 3. 데이터베이스 백업 및 복구

### 백업 (Backup)
개발 환경에서 데이터를 로컬 SQL 파일로 백업할 수 있다.
```bash
# ai_legal_helper 데이터베이스 덤프
docker exec -t ai-legal-helper-postgres-1 pg_dump -U ai_user ai_legal_helper > backup.sql
```

### 복구 (Restore)
백업된 SQL 파일을 이용해 데이터를 복원한다.
```bash
# 복원 전 데이터베이스 초기화 권장 (위의 완전 초기화 과정 참고)
cat backup.sql | docker exec -i ai-legal-helper-postgres-1 psql -U ai_user -d ai_legal_helper
```

## 4. Alembic 마이그레이션

SQLAlchemy 모델(`models.py`)을 수정한 후, 변경사항을 데이터베이스 스키마에 반영해야 한다.

### 새 마이그레이션 파일 생성
```bash
# -m "설명"에 변경 내용을 요약하여 작성
.venv\Scripts\alembic revision --autogenerate -m "Add new column to cases"
```

### 마이그레이션 적용 (DB 업데이트)
```bash
# 생성된 마이그레이션을 데이터베이스에 반영
.venv\Scripts\alembic upgrade head
```

### 마이그레이션 롤백 (이전 상태로 되돌리기)
```bash
# 바로 이전 버전으로 롤백
.venv\Scripts\alembic downgrade -1
```

## 5. 접속 정보 관리
데이터베이스 접속 계정, 암호, 연결 URL은 모두 `.env` 파일에서 관리되며, Git 저장소에 커밋되지 않는다. 새로운 환경 구성 시 `.env.example`을 참고하여 `.env` 파일을 생성해야 한다.

