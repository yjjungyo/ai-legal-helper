# P3.6 Langfuse Observability & Evaluation Integration - 구현 로그

## 1. 개요
* **단계:** P3.6
* **목표:** AI Legal Helper 서비스의 통합 가시성 및 평가(Observability & Evaluation)를 위한 Langfuse 통합 구현 내역을 기록한다.

## 2. 구현 내역

### 2.1 인프라 및 운영 환경 (Self-Hosted Langfuse)
* `init-multiple-databases.sh` 스크립트 수정: `langfuse` 데이터베이스 자동 생성 스크립트 추가
* `docker-compose.langfuse.yml` 추가: Langfuse v2 기반 독립적인 Docker Compose 파일 생성 (PostgreSQL 연결 포함)
* `windows-langfuse-start.ps1`, `windows-langfuse-stop.ps1`, `windows-langfuse-status.ps1` 작성: Windows 로컬 환경에서 백그라운드로 Langfuse를 띄우고 상태를 확인/제어할 수 있는 편리한 스크립트 제공
* `env.example` 및 `.env` 파일에 Langfuse 연동 환경 변수 템플릿(Public Key, Secret Key, Host 등) 추가

### 2.2 애플리케이션 코어 통합 (`langfuse_client.py`)
* `src/ai_legal_helper/observability/langfuse_client.py` 생성: Langfuse Python SDK 래퍼 구현
* 전역 싱글톤 `LangfuseClient` 구성, 환경 변수에 따라 Langfuse 활성화 여부를 동적으로 판별
* Trace 생성, Span 추가, Event(Metrics) 기록 등 핵심 기능 캡슐화
* Langfuse 서버에 접근 불가능하거나 네트워크 오류 발생 시 애플리케이션 흐름이 중단되지 않도록 모든 호출을 `try-except` 블록으로 보호

### 2.3 AOP 데코레이터 통합 (`decorators.py`)
* 기존 `@trace` 데코레이터가 Langfuse Trace와 Span을 동시에 기록하도록 확장
* RAG 파이프라인 및 Agent 함수 호출 시 자동으로 Langfuse에 Span이 기록됨
* **개인정보 보호(PII):** 입출력 데이터를 `[MASKED FOR PRIVACY]`로 마스킹하여 저장 (사용자 입력, LLM 응답, 검색된 법률/증거 원문 등 모두 제외)
* 컨텍스트 변수(`current_span_id`)를 활용하여 비동기 환경에서도 부모-자식 Span 계층 구조를 안전하게 유지하도록 설계

### 2.4 TokenTracking 래퍼 통합 (`callbacks.py`)
* LangChain용 LangfuseCallbackHandler를 그대로 사용하면 프롬프트 내용이 그대로 전송되는 문제가 발생하여, 기존에 구축한 `TokenTrackingCallbackHandler` 내부에 직접 Langfuse Generation Span 생성 로직 통합
* LLM 사용량(토큰 수, 모델명, 소요 시간)을 Langfuse에 보고하되, 프롬프트(`prompts`) 및 결과물(`generations`) 내용은 완전히 배제

### 2.5 비즈니스 로직 연동 (Metrics)
* `graph_rag.py`, `retrieval.py`, `action_planner.py`, `verification.py`, `document_workflow.py` 등의 주요 컴포넌트에 `langfuse_client.update_span` 호출 적용
* 검색된 노드/엣지 수(GraphRAG), 유사도 검색 타겟 청크 수(ChromaDB), 추출된 사실 개수, 문서 길이 등의 수치적 지표(Metrics)를 Span의 `metadata`로 전달하여 RAG 성능과 에이전트 동작 패턴을 관측 가능하게 함

## 3. 관련 문서
* `docs/architecture/P3_6_OBSERVABILITY_ARCHITECTURE.md`: 관측성 아키텍처 상세
* `docs/development/P3_6_LANGFUSE_INTEGRATION_DECISIONS.md`: Langfuse 통합 아키텍처 결정(ADR)
* `docs/guides/LANGFUSE_SETUP_GUIDE.md`: Langfuse 로컬 설치 및 설정 가이드

