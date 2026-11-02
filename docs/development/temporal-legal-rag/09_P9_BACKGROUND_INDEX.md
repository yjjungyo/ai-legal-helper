# P9 — 공식 법령 버전별 비동기 증분 임베딩

2026-11-02 / 기준 P8 main b6f39eeeb09c44b7cd0297e462314b722c913714

## 구현 내용

- PostgreSQL official_law_index_jobs: 공식 법령 ID + MST에 Unique Constraint
- 기존 HILT 승인을 받은 공식 검색 중 P4 HISTORY_COMPLETE/MST 정합 자료만 작업 등록
- LEGAL_BACKGROUND_INDEX_ENABLED=1로 승인된 검색 후 Job 등록
- 전체 XML의 조문과 해당 공포번호 부칙을 별도 Worker에서 ChromaDB law_docs_global에 Upsert
- 청크 ID는 법령ID/MST/조문/본문 해시 조합; 다른 역사 버전과 기존 컬렉션은 삭제하지 않음
- PostgreSQL SKIP LOCKED 기반 작업 선점, PENDING/INDEXING/RETRY/READY/FAILED 구분
- API Key 민감정보 로그 유출 방지, 공식 법령ID/MST 충돌 시 작업 중단

## 운영 명령

실행 전 운영 DB 백업 후 마이그레이션:

    cd backend
    python -m alembic upgrade head

신규 승인 검색의 Job 등록을 활성화하려면 앱 환경에
LEGAL_BACKGROUND_INDEX_ENABLED=1 설정 후 재시작한다.

Worker는 독립 프로세스로 관리자 스케줄러/PowerShell에서 기동:

    python scripts/run_official_law_index_worker.py
    python scripts/run_official_law_index_worker.py --execute

첫 명령은 Dry Run이다. 두 번째는 대기 작업 한 건을 처리한다.

## 검증 한계

- Mock Chroma/SQLite/공식 XML에서 멱등 작업·MST 분리·재시도 검증
- 실제 운영 PostgreSQL 및 OpenLaw/임베딩 연결 E2E는 미실행
- Worker 비정상 종료 시 INDEXING Lease 복구, 다중 배치 일부 완료의 검색 노출
  제어 및 실제 Job READY 상태 조회 등은 운영 강화 과제로 남는다.
- 기본 Feature Flag는 OFF다. 안전한 전체 회귀 검증 전 자동 활성화하지 않는다.

## 다음

P10 기존 Vector 무삭제 이관과 메타데이터 감사; P11 Gold Set 품질 및 지연 비교.
