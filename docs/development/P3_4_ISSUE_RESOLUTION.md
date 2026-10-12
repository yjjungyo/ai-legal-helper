# P3.4 Service Foundation & Security - 이슈 해결 기록

## 1. 테스트 DB 의존성 및 인증 컨텍스트 충돌
- **현상:** 기존 통합 테스트에 글로벌 인증 `get_current_user`를 추가하면서 여러 테스트가 `401 Unauthorized` 또는 `404 Not Found` 오류를 발생함.
- **원인:** 
  1. `conftest.py`의 `override_get_current_user`가 테스트 전용 DB(`TestingSessionLocal`) 대신 `SessionLocal`을 참조하여 의도치 않은 분리 현상 발생.
  2. `app.dependency_overrides.clear()` 호출로 인해 특정 테스트에 필요한 `get_db` 모킹까지 초기화됨.
- **해결:** `conftest.py`에서 `TESTING=1` 환경변수 세팅 및 `.clear()` 대신 `.pop()`을 사용하여 모킹 상태를 복원하도록 수정.

## 2. AuditLog 인스턴스화 키워드 오류
- **현상:** `create_case`, `create_document` 시도 중 `TypeError: 'user_id' is an invalid keyword argument for AuditLog` 발생.
- **원인:** 모델에 정의된 외래 키 컬럼명이 `actor_user_id`이나 코드상 `user_id`로 혼용하여 작성됨.
- **해결:** 일괄 치환 스크립트를 적용해 전역 라우터의 `AuditLog` 객체 생성 인자를 `actor_user_id`, `event_type`, `result="SUCCESS"` 체계로 통일.

## 3. ChromaDB 병렬/순차 실행 시 패닉(Panic) 오류
- **현상:** GraphRAG 관련 `test_sync_is_idempotent` 실행 시 `pyo3_runtime.PanicException` 발생.
- **원인:** Rust 기반 ChromaDB 백엔드가 동일 디스크 저장소를 반복 점유하려 시도하면서 파일 락(Lock) 충돌 발생.
- **해결:** 테스트 실행 환경(TESTING=1) 감지 시 `PersistentClient` 대신 `EphemeralClient`를 인스턴스화하도록 분기문 추가.

## 4. TestClient 쿠키 잔존 버그
- **현상:** `test_security.py`에서 권한 없는 접속 시나리오(`Unauthenticated access`) 검증 시 `401`이 아닌 `403`이 반환됨.
- **원인:** `fastapi.testclient.TestClient`는 내부적으로 쿠키를 유지하므로 직전에 로그인한 사용자의 세션 토큰이 전달됨.
- **해결:** 해당 테스트 직전 명시적으로 `client.cookies.clear()`를 호출하여 쿠키 초기화.

