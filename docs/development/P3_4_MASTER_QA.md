# P3.4 Service Foundation & Security - 마스터 QA 체크리스트

## 1. 요구사항 검증
- [x] 기존 사용자 및 인증 모델 구현 또는 통합 (argon2 기반 해싱)
- [x] Case 소유자(User) 매핑 및 타인 Case 접근 차단
- [x] 모든 수정(생성, 삭제, 내보내기 등) 작업 시 Audit Log 기록
- [x] 상태 점검 API (`/api/v1/health/live`, `/api/v1/health/ready`) 구현 및 의존성 헬스체크 통과
- [x] 개인정보 및 API 키 로그 노출 차단 (코드 및 주석에 평문 저장 없음)
- [x] React UI에서의 AuthContext를 통한 보호된 라우팅 구현 및 버튼 노출 제어에 그치지 않는 API 레벨의 방어 로직 구현

## 2. 코드 품질 및 아키텍처 원칙 준수
- [x] 원본 `ai-legal-agent` 코드는 절대 수정하지 않음.
- [x] 모든 신규 파일, 모듈, 클래스, 함수에 대한 한국어 Docstring 및 주석 표준 적용.
- [x] PostgreSQL이 사용자, 권한, 사건 이력의 Source of Truth로 유지됨.
- [x] API의 HTTP 응답 코드가 RESTful 원칙(401, 403, 404 분리)을 철저히 따름.

## 3. 안정성 및 테스트
- [x] 전체 Integration Test (`pytest tests/integration/`) 통과 확인.
- [x] FastAPI `Depends`를 활용한 의존성 주입이 테스트 및 운영 모드에서 오작동하지 않도록 픽스처 안전장치 마련.
- [x] ChromaDB의 `pyo3_runtime.PanicException` 방지를 위한 테스트 전용 EphemeralClient 적용.

