# AI Legal Helper — P3.4 Auth & Authorization Decisions

## 1. 개요
이 문서는 P3.4 단계에서 인증(Authentication) 및 인가(Authorization) 방식을 결정한 배경과 대안을 기록한다.

## 2. 인증 방식 결정: HttpOnly Cookie 기반 세션

### 대안 1: JWT (JSON Web Token) in LocalStorage
- **장점**: 구현이 간단하고, 백엔드 상태(Stateless) 유지가 쉽다.
- **단점**: 클라이언트 측 스크립트(XSS) 탈취 위험이 크며, 강제 로그아웃/만료 처리가 복잡하다.

### 대안 2: Session Token in HttpOnly Cookie (채택)
- **장점**: 토큰이 자바스크립트에서 접근 불가능하므로 XSS 공격에 안전하며, 서버에서 즉시 무효화가 가능하다.
- **단점**: CSRF(Cross-Site Request Forgery) 공격 방어를 위한 설정이 추가로 필요하며, 도메인 제약이 있다.

### 결정 사유
AI Legal Helper는 사용자의 매우 민감한 개인정보(계약서, 개인 분쟁 내용 등)를 다룬다. 따라서 보안 수준이 가장 높은 XSS 방어(HttpOnly)와 탈취된 토큰의 즉시 폐기(DB 기반 세션 관리)가 가능한 **HttpOnly Cookie 기반의 Opaque Session Token** 방식을 채택한다. CSRF는 최신 브라우저의 `SameSite=Lax` 정책으로 기본 방어된다.

## 3. 비밀번호 암호화 알고리즘: Argon2id

### 결정 사유
- `bcrypt`, `PBKDF2` 대비 GPU를 이용한 병렬 해싱 연산 공격에 대한 저항성(메모리 소모 강제)이 월등히 뛰어나 최신 암호학계와 OWASP가 권장하는 `Argon2id`를 선택한다. 
- Python의 `passlib` 라이브러리를 통해 적용한다.

## 4. 인가(Authorization)의 처리 위치

### 대안 1: 뷰/UI 계층에서의 단순 필터링
사용자에게 보여지는 목록(리스트) 쿼리에서만 자신의 것을 보여주고 API 엔드포인트 자체에서는 검증하지 않는 방식. (IDOR 취약점 발생)

### 대안 2: 백엔드 API Gateway 또는 미들웨어에서의 공통 검증
`user_id`를 모든 라우트에 대해 일괄 적용.

### 대안 3: FastAPI Dependency Injection 기반 리소스 소유권 검증 (채택)
- **장점**: 엔드포인트마다 요구하는 리소스(사건, 증거, 액션 등)의 형태가 다르므로 가장 적합한 위치에서 유연하면서도 확실하게 검증할 수 있다.
- **결정 사유**: `Depends(get_current_user)`와 내부 검증 함수 `get_case_for_user(case_id, user_id)`를 결합해 모든 엔드포인트에서 예외 없이 소유권을 검증하도록 구조를 설계한다.

## 5. 기존 개발 데이터 소유권 마이그레이션

### 결정 사유
기존에 `user_id` 컬럼 없이 생성된 `Case` 데이터는, 보안 원칙 상 알 수 없는 익명의 사용자에게 할당되어 개인정보를 노출시킬 위험이 있다.
- **운영 데이터가 아닌 개발/테스트 DB임**을 감안하여, 테이블 업데이트(마이그레이션) 시점에 기본 테스트 사용자(System User 등)를 하나 생성하고, 기존 고아(Orphan) `Case`들을 모두 해당 기본 사용자에게 귀속시키는 방식을 채택한다.
- 이후 신규 생성되는 모든 사건은 가입 및 로그인된 사용자의 ID를 필수로 받도록 `NOT NULL` 제약조건을 건다.

