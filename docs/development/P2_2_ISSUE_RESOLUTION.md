# P2.2 이슈 및 해결 과정 (Issue Resolution)

## 1. SQLAlchemy 관계 모델 필드명 충돌 (Shadowing)
**문제**: `models.py`에서 `Party` 클래스를 정의할 때, 상대방과의 관계를 저장할 의도로 `relationship = Column(String)`을 선언함. 그러나 파일 상단에서 `from sqlalchemy.orm import relationship`으로 임포트한 `relationship()` 함수와 식별자가 충돌(Shadowing)하면서, 뒤따르는 `case = relationship("Case", back_populates="parties")` 구문 평가 시 `TypeError: 'Column' object is not callable` 오류가 발생.
**해결**: `Party` 클래스의 `relationship` 필드명을 `party_relationship`으로 변경하여 충돌을 방지함.

## 2. SQLite 동시성 병목
**문제**: LangGraph의 병렬 Agent 실행(Parallel Tasks) 환경에서 SQLite가 쓰기 락(Write Lock)에 걸려 `OperationalError: database is locked`가 발생할 위험성이 존재함.
**해결**: `session.py`에서 DB 엔진 초기화 시 `PRAGMA journal_mode=WAL` (Write-Ahead Logging)을 강제로 활성화하는 이벤트 리스너를 추가하여, 읽기와 쓰기가 동시에 진행될 수 있도록 개선함.

## 3. Azure OpenAI Structured Output 미지원 (P2.1부터 지속)
**문제**: Fact Extractor 구현 시 LangChain의 `.with_structured_output(Schema)`를 호출하면 Azure API 측에서 Error 400 (지원하지 않는 기능)을 반환함.
**해결**: P2.1의 해결책과 동일하게, 일반적인 Chat LLM을 사용하되 프롬프트 상에서 명시적으로 JSON 스키마를 제시하고 반환값을 Pydantic `model_validate_json()` 또는 파이썬 내장 `json.loads`로 파싱하여 객체화함. 마크다운(` ```json `) 블록이 섞여 나올 것에 대비한 텍스트 전처리(Strip) 로직 추가.

## 4. Frontend TypeScript 에러
**문제**: 프론트엔드 `App.tsx`에서 백엔드의 `ConsultationResponse` 안의 `usage_summary.agent_usage`를 참조하려 했으나, 해당 속성이 `types/consultation.ts` 인터페이스에 정의되어 있지 않아 TS1234 에러가 발생.
**해결**: P2.1 수정 사항에 맞춰 `UsageSummary`에 `agent_usage?: Record<string, number>;`를 추가하여 빌드 에러를 해소함.

## 5. Mypy `Column` 연산 에러
**문제**: `case.version += 1` 연산에서 Mypy가 SQLAlchemy 2.0 매핑 없이 `ColumnElement[int]`와 `int`가 호환되지 않는다고 경고함.
**해결**: `case.version = int(case.version or 0) + 1  # type: ignore`를 사용하여 우회.

