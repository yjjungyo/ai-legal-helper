# P1.2 Unified Legal Engine Architecture

## 1. 개요
P1.2 마이그레이션 단계에서는 기존 `ai-legal-agent`에 대한 HTTP/어댑터 런타임 의존성을 완전히 제거하고, 모든 백엔드 컴포넌트를 `ai-legal-helper` 패키지 내부로 이식하는 통합 아키텍처를 구축했습니다.

## 2. 아키텍처 목표 구조
```text
React + TypeScript
        ↓
FastAPI (app.py, consultation.py)
        ↓
AI Legal Helper Workflow (legal_workflow.py)
        ↓
Router & Planner
        ↓
Specialist Legal Agents (specialist.py / base_agent.py)
        ↓
Synthesizer
        ↓
사용자 응답
```
모든 LLM 생성 요청은 P0에서 구축한 `ai_legal_helper.llm.gateway`를 통과하며, LangGraph 컨텍스트를 유지하기 위해 AOP 기반 `TokenTracker` 및 `OpenTelemetry` 트레이스가 모든 전문 Agent에 자동 상속됩니다.

## 3. 핵심 이식 내용
- **Router (`router.py`)**: 사용자 질의에 기반하여 1~3개의 법률 카테고리 도출
- **Planner (`planner.py`)**: 카테고리에 해당하는 에이전트 목록 매핑
- **Specialist Agent (`specialist.py`)**: `ThreadPoolExecutor` 대신 `asyncio.gather` 및 `contextvars`를 통해 LangGraph의 비동기 실행 흐름 안에서 컨텍스트가 안전하게 전파되도록 개선했습니다.
- **RAG & VectorStore**: 원본 `ai-legal-agent`의 Chroma 데이터베이스를 `data/chroma` 디렉토리로 안전하게 복제(Copy) 후 연동하여 원본을 보호했습니다.
- **Synthesizer (`synthesizer.py`)**: 에이전트 답변을 종합하고 P0 Gateway LLM 인스턴스를 통해 요약 답변을 제공합니다.

## 4. 향후 계획 (P2 단계 고려)
현재는 기존 레거시 워크플로우를 그대로 재현하는 형태(일방향)로 구성되어 있습니다. 향후 P2 단계에서는 복잡한 사건 정보를 분석하고 분기하는 정교한 Supervisor, Verification(Response Reviewer) 노드 도입을 통해 Agentic 구조를 한 단계 더 고도화할 계획입니다.

