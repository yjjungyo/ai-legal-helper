# AI Legal Helper — P3.2 Issue Resolution

## 1. 테스트 환경의 비동기/동기 세션 불일치 문제
- **이슈 사항**: LangGraph 통합 테스트 작성 중 `AsyncClient` 및 `AsyncSession`을 사용하여 테스트를 진행하려 하였으나, FastAPI `TestClient`와 기존 테스트 환경(`test_graph_rag.py`)이 동기식 세션과 클라이언트를 사용하고 있었음. 이로 인해 Fixture Missing 및 `greenlet` 모듈 의존성 에러가 발생함.
- **해결 방안**: 테스트 환경의 통일성을 기하기 위해 비동기 클라이언트 대신 `TestClient` 및 동기식 `Session`과 `Mock` 객체를 사용하도록 `test_document_generation.py` 코드를 전면 수정. `@patch` 데코레이터를 사용하여 `build_document_graph`의 리턴값을 모킹함.

## 2. Pydantic `.dict()` Deprecation Warning
- **이슈 사항**: Pydantic V2로 마이그레이션된 환경에서 `.dict()` 호출 시 Warning이 발생함.
- **해결 방안**: 향후 V3 호환성을 고려하여 LangGraph의 state를 전달할 때 `.dict()` 대신 `.model_dump()`로 리팩토링하는 작업이 추후 필요함을 확인. 현재는 Warning 레벨이므로 코드 안정성을 위해 기능 구현 완료 후 추가 기술 부채(Tech Debt)로 관리.

## 3. Mock Path 참조 오류
- **이슈 사항**: FastAPI 라우트(`routes/documents.py`)에서 `build_document_graph` 모듈 함수를 직접 Import 한 것을, 테스트에서 원본 모듈 경로를 지정해 Patch 하려다 Mock 적용 실패 (AttributeError 발생).
- **해결 방안**: 모킹 대상을 `ai_legal_helper.api.routes.documents.build_document_graph`로 재지정하여 제대로 반환 객체가 Mock 객체로 오버라이드 되도록 수정. 

## 4. 모킹 중인 `final_state` 필수 필드 누락
- **이슈 사항**: Mock 반환 값에 `revision_id`를 누락하여 HTTP 응답 코드가 404가 나오는 이슈 발생.
- **해결 방안**: API 테스트 이전에 Mock 객체 내에서 테스트 DB 세션에 수동으로 `LegalDocument`, `DocumentRevision` 레코드를 생성하고, 생성된 Primary Key를 `final_state`의 `document_id`와 `revision_id`로 매핑하여 통과시킴.

