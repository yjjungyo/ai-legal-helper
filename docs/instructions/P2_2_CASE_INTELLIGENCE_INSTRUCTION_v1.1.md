# AI Legal Helper — P2.2 개발 착수 지시서 (v1.1 수정본)

**단계:** P2.2 — Case Intelligence & Timeline Engine  
**프로젝트:** `C:\myprjs\ai-legal-helper`  
**개발 환경:** Windows + Docker Desktop(WSL2 Backend)  
**우선 적용 분야:** 주택임대차 분쟁  
**목표:** 사건의 사실관계, 당사자, 시간순 사건, 법률 쟁점 및 변경 이력을 구조화하고 지속적으로 관리하는 AI 시스템 구축

---

## 1. 개발 목표 (변경 없음)
기존 AI Legal Helper는 사용자의 질문을 분석하고 법률 근거를 검색하여 답변을 생성한다.
P2.2에서는 다음 기능을 추가한다.
1. 사건 생성 및 영구 저장
2. 사건 당사자 관리
3. 사용자 진술에서 사실관계 추출
4. 사건 타임라인 자동 생성
5. 법률 쟁점 추출 및 연결
6. 부족한 정보 탐지
7. 새로운 사실을 기존 사건에 추가
8. 변경된 사실에 따른 재분석
9. 사건 변경 이력 관리
10. React 기반 사건 관리 UI

**핵심 목표:** AI가 매번 처음부터 질문을 받는 것이 아니라, 이미 저장된 사건의 맥락을 활용하여 상담을 이어갈 수 있어야 한다.

## 2. 개발 원칙 (v1.1 업데이트)
- **데이터베이스 변경:** SQLite 대신 PostgreSQL 17을 사용한다.
- 데이터베이스는 Docker Compose를 통해 실행하며 포트는 `127.0.0.1:5432`에만 바인딩한다.
- PostgreSQL 데이터는 Docker Named Volume(`pgdata`)에 영구 저장한다.
- ORM은 SQLAlchemy 2.x와 Alembic, 드라이버는 psycopg 3을 사용한다.
- DB 접속 정보는 환경변수(`.env`)로 관리하고 Git에 포함하지 않는다.
- 개발 DB와 테스트 DB를 분리한다.
- 기존 P0~P2.1 기능을 유지한다. DB 구성을 변경했다는 이유로 기존 법률 엔진을 재작성하지 않는다.
- React + FastAPI + LangGraph 구조를 유지한다.
- Docker Redis 및 신규 유료 외부 서비스를 도입하지 않는다.
- 국제법 데이터 확충은 이번 단계에서 제외한다.
- 모든 신규·수정 코드에 상세한 한글 주석을 `CODING_COMMENT_STANDARD.md`를 준수하여 작성한다.
- DB 시작·종료·백업·복구·초기화 절차를 문서화(`DB_OPERATIONS.md`)한다.
- PostgreSQL 연결, 마이그레이션, 트랜잭션, 동시 수정 충돌 테스트를 수행한다.

