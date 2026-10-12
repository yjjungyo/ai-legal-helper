# ADR-007: 데이터베이스 PostgreSQL 17 마이그레이션

## 1. 배경 (Context)
P2.2 단계에서 처음 채택된 데이터베이스는 SQLite(ADR-006)였다. 그러나 사건 관리(Case Intelligence) 시스템이 고도화되고 다중 사용자 접근 및 복잡한 트랜잭션, 그리고 동시성 충돌 처리의 필요성이 대두되었다.
SQLite는 단순한 단일 파일 구조로 로컬 개발에는 유리하나, 운영 환경 수준의 제약 조건과 Table-level Write Lock으로 인해 병목이 우려되었다. 따라서 안정적인 RDBMS로의 전환이 요구되었다.

## 2. 대안 (Alternatives)
- **A. SQLite 유지**: WAL 모드를 유지하며 애플리케이션 레벨에서 락을 제어. 장기적 안정성에 부적합.
- **B. PostgreSQL 17 (Docker)**: 가장 안정적이고 널리 사용되는 오픈소스 RDBMS. Docker Compose를 통해 개발/테스트 환경을 격리 및 일원화.
- **C. MySQL / MariaDB**: PostgreSQL과 유사한 수준이나, JSON 데이터 처리나 SQLAlchemy와의 호환성 측면에서 PostgreSQL이 약간 더 유리.

## 3. 결정 (Decision)
**대안 B (PostgreSQL 17)**을 채택한다.

- `docker-compose`를 사용하여 로컬 포트(`127.0.0.1:5432`)와 `pgdata` Named Volume에 영속화한다.
- ORM은 SQLAlchemy 2.x 구조를 유지하되, 드라이버를 `psycopg` (v3)로 교체한다.
- 데이터베이스 마이그레이션 관리를 위해 `Alembic`을 도입한다.
- 동시성 충돌 방지를 위해 `Case` 모델에 `version` 컬럼을 추가하고 SQLAlchemy의 Optimistic Locking 기능(`__mapper_args__`)을 활성화한다.

## 4. 결과 (Consequences)
- **장점**: 데이터베이스 무결성과 다중 트랜잭션 안전성 확보, 운영 환경과 유사한 개발 환경 유지, 충돌 발생 시 명확한 에러(`StaleDataError`) 핸들링 가능.
- **단점**: Docker 환경 구동이 필수가 되어 개발 셋업 비용이 증가함. `psycopg[binary]` 등 추가적인 패키지 의존성이 발생함.

