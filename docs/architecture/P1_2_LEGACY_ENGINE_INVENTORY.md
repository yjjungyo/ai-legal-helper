# P1.2 Legacy Engine Inventory

이 문서는 기존 `ai-legal-agent` 시스템의 구조와 기능을 분석하고 신규 아키텍처로의 이식 여부 및 방식을 분류한 보고서입니다. 모든 조사는 원본 소스코드(`C:\myprjs\ai-legal-agent\src`)를 기반으로 이루어졌습니다.

## 1. 주요 기능 조사 결과

### 1.1 LangGraph Workflow (`src/agents/workflow.py`)
- **State**: `LegalState(MessagesState)` - `question`, `categories`, `plan`, `results` 상태 보유
- **Node**: `route_node`, `plan_node`, `run_agents_node`, `synthesize_node`
- **구조**: `START -> route -> plan -> run_agents -> synthesize -> END` 형태의 순차적/병렬 하이브리드 워크플로우. `run_agents_node`에서 `ThreadPoolExecutor`를 사용해 병렬로 전문 Agent들을 호출.

### 1.2 Router (`src/agents/router.py`)
- **동작**: 사용자 질문을 기반으로 LLM 프롬프트(`ROUTER_PROMPT`)를 사용하여 8개 법률 카테고리 중 1~3개를 분류하여 JSON으로 응답.
- **예외 처리**: JSON 파싱 실패 시 보수적으로 `["민법"]` 반환.

### 1.3 Planner (`src/agents/planner.py`)
- **동작**: 분류된 카테고리 목록을 기반으로 실행할 전문 Agent 이름(`agent__<slug>`)을 반환. LLM 호출 없이 단순 매핑 로직(`get_agent_name`)으로 동작.

### 1.4 전문 Agent (Specialist Agents)
- **목록**: 헌법(constitution), 민법(civil), 형법(criminal), 상법(commercial), 노동(labor), 행정(administrative), 조세(tax), 국제(international) 총 8개.
- **생성 방식**: `base_agent.build_react_agent`를 통해 LangChain `AgentExecutor` (ReAct 기반, `max_iterations=3`)로 공통 빌드.
- **프롬프트**: 분야별 역할이 지정된 `BASE_SYSTEM` 프롬프트 사용.

### 1.5 Agent Tools (`src/agents/tools/`)
- **동작**: 각 전문 Agent는 하나의 `retrieval_tool` (예: `civil_retrieval_tool`)을 소유.
- **팩토리**: `retrieval_factory.make_fixed_retrieval_tool`로 생성. 질의가 들어오면 `rewrite_query`로 벡터 검색용 키워드를 2개 추출 후 Chroma에서 `retrieve` 수행.
- **반환**: 검색 결과를 최대 2건(`MAX_DOCS=2`) 반환하고 텍스트 일부 스니펫(240자)을 잘라서 제공.

### 1.6 Synthesizer (`src/agents/synthesizer.py`)
- **동작**: 각 전문 Agent의 결과(`results`)를 취합(`_format_findings`)하여 LLM으로 최종 종합 답변 요약 작성.
- **포맷**: Markdown 형식으로 출력하며, 하단에 `_render_originals`를 통해 각 카테고리별 전문 답변 원문을 그대로 첨부.

### 1.7 RAG 검색 & Chroma (`src/rag/retrieval.py`, `src/config.py`)
- **DB 위치**: `CHROMA_PERSIST` (`./vectorstore/chroma`)
- **컬렉션**: `law_docs_<category_eng>` 구조 (분야별 컬렉션 분리). 카테고리가 미지정 시 전체 `law_docs_*`에서 병합 검색.
- **Embedding**: `AzureOpenAIEmbeddings` (`text-embedding-3-large`) 사용.

### 1.8 LLM 설정 (`src/config.py`)
- **초기화**: `get_llm`, `get_temp_llm` 내부에서 직접 `AzureChatOpenAI` 객체 생성. P0의 Gateway를 사용하지 않아 AOP / Trace 적용이 누락될 수 있는 원인.

### 1.9 오류 처리 및 UI 종속성
- **오류 처리**: ReAct Agent에서 `handle_parsing_errors=True` 적용 및 파싱 실패 시 기본값 fallback(예: Router의 민법 fallback) 위주.
- **UI 종속성**: `src` 내부에는 Streamlit UI 종속 코드가 거의 없으나 최상단 `app.py`에 UI 종속성이 존재. 백엔드 워크플로우 모듈화는 잘 되어 있는 편.

---

## 2. 이식 분류 (Migration Strategy)

| 모듈/기능 | 이식 방식 | 상세 사유 |
|---|---|---|
| **LangGraph Workflow** | **리팩터링 후 이식** | 기존 워크플로우 구조는 유지하되, `ThreadPoolExecutor`를 제거하고 LangGraph의 네이티브 병렬 Node(Send/Map) 기능으로 개선하여 async 환경 및 P0 AOP 컨텍스트 전파 호환성 확보. |
| **Router** | **직접 이식** | 기존 프롬프트와 JSON 출력 포맷이 견고하므로, LLM 초기화만 P0 Gateway로 교체 후 재사용. |
| **Planner** | **직접 이식** | 현재는 카테고리 매핑 역할만 하므로 그대로 이식하고, 향후 P2 단계에서 복잡한 사건 단위 분석 계획용으로 확장. |
| **Specialist Agents** | **리팩터링 후 이식** | `build_react_agent`를 LangGraph 기반으로 변경하거나, 기존 ReAct 방식을 사용하되 LLM을 P0 Gateway로 연결하고 `Trace` ID와 `node_name`이 정확히 매핑되도록 Callback 추가 적용. |
| **Agent Tools & RAG** | **리팩터링 후 이식** | `retrieval_factory`와 `retrieve` 함수는 유지하되, Chroma 절대 경로 참조 및 P0 Observability 연동을 위해 환경 및 로깅 리팩터링. |
| **Synthesizer** | **직접 이식** | 프롬프트와 문자열 가공(`chat_brief`, `findings`) 방식이 유효하므로 LLM 인스턴스만 교체 후 이식. |
| **LLM 설정 (`config.py`)** | **이식 제외** | `src/config.py`의 AzureChatOpenAI 직접 호출은 P0 `llm/gateway.py`로 전면 대체. |
| **Streamlit (`app.py`)** | **이식 제외** | 신규 아키텍처는 React/FastAPI 기반이므로 기존 UI 코드는 이식 대상에서 제외. |

