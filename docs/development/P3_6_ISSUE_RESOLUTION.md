# P3.6 Langfuse Observability & Evaluation Integration - 이슈 해결 로그

## 1. 개요
이 문서는 P3.6 단계에서 Langfuse 연동을 구현하며 발생한 주요 이슈와 해결 방법을 기록한다.

## 2. 주요 이슈 및 해결 방안

### 2.1 기존 LangfuseCallbackHandler 사용 시 PII 노출 문제
* **이슈:** `langchain`에서 제공하는 공식 `LangfuseCallbackHandler`를 RAG 및 Agent 실행 과정에 주입했으나, 해당 핸들러가 프롬프트 내용과 생성 결과를 강제로 서버로 전송하는 동작이 기본 탑재되어 있음. 이로 인해 임대차 계약 내용이나 개인정보(이름, 주소 등)가 중앙 서버에 로깅되는 보안 리스크 발견.
* **원인:** 공식 핸들러에서 프롬프트/응답 마스킹 기능을 완전하게 커스터마이징하기 어려움.
* **해결:** 대안 접근법(Custom Instrumentation) 채택. 공식 핸들러를 배제하고 기존에 개발해 둔 `TokenTrackingCallbackHandler`와 AOP 기반 `@trace` 데코레이터를 확장. TokenTracker의 `on_llm_end`에서 LLM의 토큰 사용량과 메타데이터만 Langfuse로 전송하고, 요청 내용 자체는 철저히 배제(`[MASKED FOR PRIVACY]`)하도록 래퍼를 새로 구현함. (ADR 참고)

### 2.2 비동기 실행 및 Multi-Agent 환경에서의 Span Context 소실
* **이슈:** `FastAPI` + `LangGraph` 기반으로 동작하는 환경에서는 수많은 비동기 태스크(Agent Node 실행, 병렬 검색 등)가 발생. 단순히 전역 변수나 싱글톤으로 부모 Span ID를 관리할 경우, 동시성 이슈로 인하여 Trace 계층이 꼬이거나 Context를 유실하는 문제 발생 가능.
* **해결:** Python 내장 모듈인 `contextvars`를 활용하여 비동기 환경에서도 안전하게 Context를 유지하도록 수정. `src/ai_legal_helper/utils/context.py` 모듈에 `current_span_id` ContextVar를 선언하고, `@trace` 데코레이터에서 자식 Span 진입 시 이를 복사 및 복원하도록 설계.

### 2.3 PowerShell UTF-16 인코딩으로 인한 Python SyntaxError
* **이슈:** 스크립트 작성 시 Windows PowerShell에서 `echo "..." > script.py` 방식으로 Python 코드를 생성했더니, PowerShell 기본 인코딩이 UTF-16(BOM)으로 적용되면서 Python 인터프리터가 `SyntaxError: Non-UTF-8 code starting with '\xff'` 예외를 던지는 현상.
* **해결:** PowerShell의 `>` 연산자를 피하고 `Set-Content -Encoding UTF8`을 사용하거나, 에이전트 내장 파일 작성 도구(`write_to_file`)를 강제 사용하도록 절차 개선.

### 2.4 Docker 환경의 데이터베이스 의존성 구성 순서
* **이슈:** 기존 `init-multiple-databases.sh` 쉘 스크립트가 실행될 때 PostgreSQL 서버가 완전히 구동되기 전 초기화 스크립트가 실행되어 `langfuse` DB가 정상적으로 생성되지 않을 수 있음.
* **해결:** `docker-compose.yml` 및 `docker-compose.langfuse.yml` 구조상 `depends_on` 옵션과 `healthcheck`를 재확인하고, `langfuse` 컨테이너가 데이터베이스 마이그레이션을 정상적으로 시도할 수 있도록 `db` 서비스의 헬스체크 대기 시간을 고려함.

## 3. 교훈 및 향후 과제
* 서드파티 로깅(Observability) 도구를 프로젝트에 엮을 때, 프레임워크 제공 도구(예: Langchain 콜백)가 개인정보나 기밀 유지 요구사항에 맞지 않을 수 있다는 점을 항상 인지해야 함. 직접 AOP 레벨에서 제어권을 가지는 설계가 운영상 훨씬 유연함을 입증함.

