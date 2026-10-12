# P1.2 Issue Resolution

## 1. @trace 데코레이터 호환성 문제
- **문제**: 레거시 코드를 이식하며 P0에서 구현된 `@trace` 데코레이터를 적용할 때, `@trace(name="Router", component="Agent")`와 같이 매개변수를 전달했으나 `TypeError`가 발생.
- **원인**: P0 데코레이터는 파라미터를 받지 않는 순수 래퍼(`def trace(func: Callable)`)로 구현되어 있었음.
- **해결**: 모든 파일의 데코레이터를 순수 `@trace`로 롤백하고, 컨텍스트 주입은 내부에서 `set_node_name` / `set_agent_name`을 명시적으로 호출하는 방식으로 해결.

## 2. Windows PowerShell Here-Doc 이슈
- **문제**: 콘솔에서 긴 Python 코드를 생성하기 위해 `cat << 'EOF'` 방식 사용 시 에러 발생.
- **해결**: `write_to_file` 도구를 직접 사용하여 파일 생성.

## 3. 백그라운드 LLM 호출 중 Azure 인증 오류
- **문제**: `test_consultation.py` 실행 시 `DeploymentNotFound` 및 Azure Credential 누락 오류 발생.
- **원인**: 통합 테스트 환경에 `.env` 파일이 없고 레거시와 배포명(`aicore-gpt4o` vs `gpt-4o`)이 달랐음.
- **해결**: `get_llm` 인스턴스화 부분에서 `dotenv`를 로드하도록 추가하고 기본 모델 배포명을 환경변수 참조로 수정함. 기존 `ai-legal-agent`의 `.env`를 새 프로젝트 루트로 복사하여 인증 타파.

## 4. 비동기 LangGraph 병렬 처리
- **문제**: 기존 레거시 시스템은 `ThreadPoolExecutor` 안에서 블로킹 호출을 사용함.
- **해결**: `contextvars.copy_context()`와 `asyncio.to_thread`를 결합하여 비동기 루프를 차단하지 않고 병렬 에이전트를 실행하며 P0 로깅 컨텍스트를 성공적으로 전파함.

