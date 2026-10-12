# AI Legal Helper — P3.4 Security Architecture

## 1. 개요
이 문서는 P3.4 단계에서 구축하는 인증(Authentication), 인가(Authorization), 파일 관리(File Storage), 상태 점검(Readiness/Liveness), 감사 로그(Audit Logging)의 전체 보안 아키텍처를 정의한다.

## 2. 사용자 인증 아키텍처 (Authentication)

### 2.1 인증 흐름 (Cookie-based JWT / Session Token)
- **로그인 방식**: 사용자가 이메일/비밀번호를 입력하여 서버의 `POST /api/v1/auth/login`을 호출.
- **비밀번호 저장**: Argon2id 해시 알고리즘을 사용해 안전하게 암호화하여 DB(`User` 테이블)에 저장.
- **세션 관리**: 로그인 성공 시 임의의 난수 토큰을 생성하고 그 해시값을 `UserSession` 테이블에 저장. 토큰 원문은 `HttpOnly`, `Secure`, `SameSite=Lax` 속성의 쿠키로 클라이언트에 전달.
- **로그아웃**: `POST /api/v1/auth/logout` 호출 시 DB의 세션 만료 및 클라이언트의 쿠키 삭제 처리.

### 2.2 프론트엔드 인증 상태
- `AuthContext`를 통해 현재 사용자의 세션 여부를 전역 상태로 관리.
- 인증이 필요한 페이지는 `ProtectedRoute` 컴포넌트로 감싸 미인증 시 `/login`으로 리다이렉트 처리.

## 3. 접근 권한 아키텍처 (Authorization)

### 3.1 사건(Case) 단위의 다중 테넌트 격리
- PostgreSQL의 `Case` 모델에 `user_id` 외래키를 추가.
- 모든 API 엔드포인트(예: `GET /api/v1/cases/{case_id}`)는 FastAPI의 `Dependency Injection`을 활용해 요청된 `case_id`의 소유자가 현재 인증된 사용자(User)와 일치하는지(`case.user_id == current_user.id`) 서버 측에서 검증.
- 하위 도메인(`Fact`, `EvidenceDocument`, `LegalAction`, `LegalDocument`) 역시 부모 `Case`의 소유권 검증을 거친 후 접근 허용.

### 3.2 벡터 스토어 및 그래프 데이터 격리
- **ChromaDB**: 기존 메타데이터 필터링에 `user_id` 조건을 추가하여 검색 격리 확보.
- **Neo4j**: 쿼리 시점에서 `MATCH (c:Case {id: $case_id})`에 부합하는 서브그래프만 탐색하도록 기존 쿼리를 고도화하거나 검증 절차 병행.

## 4. 파일 저장소 아키텍처 (File Storage Isolation)

- **저장 위치**: 외부 공개 불가능한 비공개 디렉터리(`data/evidence`, `data/exports`).
- **권한 검증**: 파일 다운로드 라우트(`GET /api/v1/evidence/{evidence_id}/download` 등) 호출 시 DB에서 파일의 메타데이터 조회 후 부모 `Case`의 소유권 검증을 통과한 경우에만 `FileResponse` 반환.
- **경로 탐색 방어**: 파일명은 임의의 고유 식별자(UUID)로 변환해 저장(`safe_storage_key`)하고, 사용자가 입력한 파일명을 파일 경로 구성에 절대 사용하지 않음.

## 5. 감사 로그 (Audit Logging)

- `AuditLog` 테이블을 통해 사용자의 중요 행위(로그인, 사건 생성, 증거 업로드, 분석 실행 등)를 타임스탬프와 함께 기록.
- 로깅 시 민감 정보(비밀번호, 개인정보)는 마스킹 처리하거나 저장하지 않음.

## 6. 서비스 상태 점검 (Health Probes)

- **Liveness (`/health/live`)**: 서버 자체의 실행 가능 상태 반환 (200 OK). 쿠버네티스/도커의 재시작 지표.
- **Readiness (`/health/ready`)**: DB, Neo4j, ChromaDB 등 필수 의존성 서비스의 연결 상태를 확인 후 반환. 연결 실패 시 503 상태를 반환하여 트래픽 인입 차단.

