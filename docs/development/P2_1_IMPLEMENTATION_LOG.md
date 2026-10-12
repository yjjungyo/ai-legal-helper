# P2.1 Implementation Log

## 1. 개요
P2.1 단계에서는 기존 P1.2 통합 엔진에 Supervisor 및 Verification 노드를 추가하여, AI가 생성한 법률 답변의 근거를 확인하고 모순이나 누락을 방지하는 체계를 구축했습니다.

## 2. 변경 사항
- **State 확장:** `LegalState`에 `draft_answer`, `verification_result`, `revision_count`, `warnings`, `retrieved_sources` 등의 필드를 추가하여 Supervisor와 Verification Agent 간 상태를 공유할 수 있도록 하였습니다.
- **Workflow 재편:** LangGraph를 수정하여 `START -> supervisor_initialize -> route -> plan -> run_agents -> synthesize -> verification -> [PASS/REVISE/INSUFFICIENT] -> END` 구조로 변경했습니다.
- **Verification Agent 추가:** `verification_agent.py`를 신설하여, 합성된 `draft_answer`에서 핵심 법률 주장을 추출하고, RAG 도구가 저장한 실제 출처 문서(`retrieved_sources`)와 대조하는 로직을 구현했습니다.
- **제한적 재검토 로직:** 검증 결과가 `REVISE`일 경우 1회에 한해 수정 지침을 바탕으로 `revise_node`를 거치도록 하였습니다. 재검토 후에도 `REVISE`가 나오거나 최초부터 `INSUFFICIENT`일 경우, 근거가 부족함을 사용자에게 명시하고 종료합니다.
- **AOP 및 토큰 계측 연동:** 기존 ContextVar(`_retrieved_sources_var`)를 확장하여 병렬 `asyncio.to_thread` 환경에서 각 Agent가 조회한 출처를 안전하게 수집하였으며, TokenTracker에 `verification_agent` 및 `revise` 노드의 사용량이 정상 합산되도록 유지했습니다.
- **React 스키마 및 UI 변경:** 프론트엔드에서 검증 상태, 각 법률 주장의 Grounding Status, Agent별 토큰 사용량, Trace 경로를 표시할 수 있도록 `ConsultationResponse` 스키마와 `App.tsx`를 업데이트했습니다.

## 3. 해결된 기술적 과제
- `run_specialist_agent` 비동기 병렬 실행 시 `contextvars`가 각 스레드에서만 독립적으로 동작하여 RAG 검색 출처를 메인 스레드로 수집하지 못하는 문제가 있었습니다.
- **해결:** `run_specialist_agent`의 반환값을 튜플로 변경하여 명시적으로 검색 출처 목록을 `run_agents_node`로 반환 및 병합하도록 수정했습니다.

