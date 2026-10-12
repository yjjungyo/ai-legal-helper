# P3.4 Service Foundation & Security - 구현 일지

## 1. 구현 개요
- **목표:** AI Legal Helper 서비스의 운영 가능 수준 보안 체계 및 기반 시스템 구축
- **주요 내용:** 사용자 인증, Case 소유권 분리, 감사 로그(Audit Log), 상태 점검(Health Check), React UI 권한 연동

## 2. 세부 구현 사항

### 2.1 사용자 인증 및 세션 관리
- `ai_legal_helper.api.routes.auth` 추가
- `User`, `UserSession` 모델 구현 (argon2를 이용한 비밀번호 해싱)
- `/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/me`, `/api/v1/auth/logout` 엔드포인트 구현
- HTTPOnly 쿠키를 이용한 세션 토큰 관리 및 검증

### 2.2 Case 소유권 및 권한 제어
- `get_current_user` 의존성을 통한 글로벌 인증 검증 적용
- `get_case_for_user` 의존성을 추가하여 `case_id` 접근 시 소유권(user_id) 검증
- 모든 엔드포인트(`cases`, `documents`, `evidence`, `graph`, `workflow` 등)에 `get_case_for_user` 적용

### 2.3 감사 로그 (Audit Logging)
- `AuditLog` 데이터베이스 모델 추가
- 주요 보안 이벤트(로그인, 생성, 문서 파일 다운로드 등) 발생 시 기록하는 로직 삽입
- `CREATE_CASE`, `CREATE_DOCUMENT`, `EXPORT_DOCUMENT`, `USER_LOGIN` 등의 이벤트 추적

### 2.4 Health Check API
- `/api/v1/health/live` (Liveness) 및 `/api/v1/health/ready` (Readiness) 라우트 추가
- Postgres 및 Neo4j 연결 상태 점검 통합

### 2.5 React UI Auth 통합
- `AuthContext`를 통해 프론트엔드 라우팅에 Protected Route 구성
- `AuthProvider`에서 `/api/v1/auth/me`를 호출하여 로그인 상태 확인 및 세션 복구
- 로그인 및 회원가입 페이지 구현

## 3. 테스트 및 최적화
- `test_security.py`, `test_auth.py` 신규 작성
- 기존의 통합 테스트들에 인증 컨텍스트 주입 (`conftest.py` 활용)
- ChromaDB 및 Neo4j 의존성 환경 분리를 위한 픽스처 강화

