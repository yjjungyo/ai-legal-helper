# ADR-004: Unified Legal Engine Migration

## 1. Context & Background
기존 P1 단계에서는 `ai-legal-helper` 내부에 Legacy Adapter(`integrations/legacy_legal`)를 두고 별도의 저장소/프로젝트인 `ai-legal-agent`를 `sys.path`와 Monkey-patching으로 연동했습니다. 이 방식은 상대경로 파손, 모듈 충돌, 전역 변수 경합 등의 부작용을 일으켰습니다. 따라서 안정적이고 확장 가능한 AI 법률 서비스를 위해 단일 통합 아키텍처(Unified Legal Engine)로의 마이그레이션이 요구되었습니다.

## 2. Decision
기존 Adapter 방식을 폐기하고 `ai-legal-agent`의 핵심 워크플로우(Router, Planner, Specialist Agents, Synthesizer)를 `ai-legal-helper/agents` 및 `ai-legal-helper/workflows` 내로 직접 이식(Porting)합니다.

- **LangGraph Workflow**: 기존 `ThreadPoolExecutor`를 비동기 LangGraph 워크플로우와 `asyncio`로 리팩터링하여 병렬 실행 및 컨텍스트 전파(Context Propagation)를 보장합니다.
- **RAG & VectorStore**: 원본 Chroma 데이터베이스는 훼손하지 않기 위해 `ai-legal-helper/data/chroma` 하위로 복사본을 만들어 로컬 참조하도록 구성합니다.
- **Observability 연동**: Legacy Monkey-patching을 제거하고, 모든 통합 에이전트에 P0에서 구축한 `@trace` AOP와 `get_llm` 기반의 `TokenTracker`를 명시적으로 적용합니다.

## 3. Options Considered
1. **유지 및 패키징 (Rejected)**: `ai-legal-agent`를 `pip install -e` 형태의 독립 패키지로 만들어 분리. 하지만, AOP와 TokenTracker를 외부 코드에 주입하기 위해 복잡한 패치 작업이 지속되어야 함.
2. **Microservice 전환 (Rejected)**: FastAPI 서버 두 대를 띄우고 REST API로 통신. 오버헤드가 크고 디버깅(TraceID 전파 등)이 복잡해짐.
3. **직접 통합 (Accepted)**: 코드를 복제하여 새로운 아키텍처에 맞게 리팩터링. 기존 코드의 로직은 유지하되 실행 구조(AOP, Async)를 개선할 수 있음.

## 4. Consequences
- **장점**: 단일 코드베이스에서 개발 및 관측(Tracing)이 완벽하게 일치합니다. 기존 프로젝트를 클론하거나 실행할 필요가 없어 배포가 단순해집니다.
- **단점**: 기존 프롬프트와 체인이 그대로 넘어왔으므로, 복잡한 법률 사건에 대한 깊이 있는 분석(Multi-step Reasoning) 기능은 아직 부족합니다. 이는 P2 단계에서 Supervisor와 Verification 노드를 추가하여 확장할 예정입니다.

