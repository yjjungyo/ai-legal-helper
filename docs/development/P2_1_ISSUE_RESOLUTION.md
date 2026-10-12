# P2.1 Issue Resolution

## 1. asyncio.gather 와 contextvars.Context.run() 충돌
- **문제**: `run_agents_node`에서 다중 Agent를 병렬로 실행(`asyncio.gather`)할 때, 하나의 `contextvars.Context` 객체를 여러 `asyncio.to_thread(ctx.run, ...)`가 동시에 진입하려 시도하여 `RuntimeError: cannot enter context: ... is already entered` 발생.
- **해결**: Python 3.9 이상부터 `asyncio.to_thread`는 기본적으로 현재 `contextvars`를 복제하여 사용하므로, 명시적인 `ctx.run` 호출을 제거하고 기본 동작에 맡기도록 수정하여 해결.

## 2. RAG 검색 결과 유실 문제
- **문제**: 전문 에이전트 내부에서 `make_fixed_retrieval_tool`이 RAG 검색을 수행하지만, LangChain의 AgentExecutor는 최종 생성된 텍스트(`output`)만 반환하므로, 검증 노드가 실제 검색된 원문을 확인할 수 없음.
- **해결**: `retrieval_factory.py`에서 검색된 문서가 있을 때마다 `add_retrieved_source` ContextVar 함수를 호출하도록 하고, `run_specialist_agent`가 종료될 때 해당 리스트를 반환하여 State의 `retrieved_sources`에 모아 Verification 노드로 전달.

## 3. 무한 루프 위험 방지
- **문제**: `verification_node`가 계속 `REVISE`를 반환할 경우, 수정 노드(`revise_node`)와 무한 루프에 빠질 위험 존재.
- **해결**: LangGraph State에 `revision_count`를 도입하고, `verification_condition`에서 해당 카운트가 1 이상일 경우 강제로 `insufficient_node`로 라우팅하여 루프를 차단.

## 4. ChatOpenAI 대신 AzureChatOpenAI 사용
- **문제**: P1.2 지침에 따라 `ai_legal_helper.llm.gateway.get_llm()`을 사용해야 했으나, Verification 개발 중 실수로 LangChain의 `ChatOpenAI`를 직접 호출하여 API Key 오류 발생.
- **해결**: 모든 노드와 Agent가 공통 Gateway인 `get_llm()`을 사용하도록 리팩토링.

