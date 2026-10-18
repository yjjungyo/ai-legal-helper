# AI Legal Helper — AI 개발 에이전트 공통 지침

이 문서는 `ai-legal-helper` 저장소에서 작업하는 모든 AI 코딩 에이전트에 적용한다.

## 1. 필수 주석 작성 규칙

**모든 신규·수정 소스코드는 [`docs/development/CODING_COMMENT_STANDARD.md`](docs/development/CODING_COMMENT_STANDARD.md)를 따라야 한다.**

- Python: 한국어 모듈 Docstring + Google 스타일 클래스·함수 Docstring.
- TypeScript/React: 한국어 TSDoc/JSDoc.
- 주요 함수, 알고리즘, 조건 분기, 예외, 상태 전이, Agent·LangGraph Node/Edge, RAG 데이터 흐름에 **무엇을/왜** 설명한다.
- 코드 변경 시 관련 주석을 반드시 갱신한다.
- 자명한 코드의 기계적 주석, 실제 동작과 다른 설명, 민감정보 기록은 금지한다.
- 완료보고서에 주석 표준 준수 여부를 점검한다.

## 2. 프로젝트 개발 원칙

- 통합 제품 아키텍처: React + TypeScript / FastAPI / Python LangGraph.
- `ai-legal-agent` 원본은 보존하며, 신규 제품은 외부 레거시 프로젝트 실행에 의존하지 않는다.
- 기존 테스트를 유지하고 신규 기능의 단위·통합 테스트를 추가한다.
- 법률 주장과 검색 근거를 구분하며, 출처 없는 주장을 검증된 사실로 표현하지 않는다.
- API Key, 개인정보, 상담 원문을 로그·주석에 노출하지 않는다.
- 구현하지 않았거나 검증하지 않은 항목을 완료 또는 PASS로 보고하지 않는다.
- 별도 지시 없이 다음 세부 단계로 자동 진행하지 않는다.

## 3. 백엔드 라이브러리 및 의존성 관리 규칙

- **백엔드 개발 시 신규 외부 라이브러리·모듈이 추가되면 반드시 `backend/requirements.txt`와 `backend/pyproject.toml`에 해당 패키지와 최소 호환 버전을 즉시 추가하여 동기화해야 한다.**
- 개발 환경이나 가상환경(`.venv`)에서만 임의로 패키지를 설치하고 의존성 파일에 반영하지 않아 발생하는 `ModuleNotFoundError`를 원천 방지한다.
- 신규 의존성 도입 시 버전 호환성 및 기존 패키지와의 충돌 여부를 사전에 검토한다.
