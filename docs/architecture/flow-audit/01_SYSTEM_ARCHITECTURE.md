# 01. 전체 시스템 아키텍처 (System Architecture)

이 문서는 실제 구현 코드(`frontend/src`, `backend/src/ai_legal_helper`)에 근거하여 AI Legal Helper의 전체 컴포넌트 구조, 호출 방향, 데이터 흐름, 외부 시스템 연동을 시각화한다.

---

## 1. End-to-End 전체 시스템 아키텍처 다이어그램

```mermaid
flowchart TB
    subgraph Client["Browser Client (React 19 + TypeScript + Vite)"]
        direction TB
        App["App.tsx / Navbar\n(Router + AuthProvider)"]
        Pages["Pages\n- Login.tsx / Register.tsx\n- CaseList.tsx\n- CaseWorkspace.tsx (OverviewTab, FactsTab)"]
        Components["Workspace Tab Components\n- ChatSection.tsx (useConsultation)\n- EvidenceSection.tsx\n- EvidenceGraph.tsx (ForceGraph2D)\n- ActionPlanSection.tsx\n- DocumentSection.tsx"]
        APIClients["API Client Layer (frontend/src/api)\n- apiFetch.ts (credentials: include, 401 event)\n- authClient.ts / caseClient.ts\n- consultationClient.ts / evidenceClient.ts\n- graphClient.ts / actionClient.ts\n- documentClient.ts / workflowClient.ts"]

        App --> Pages --> Components --> APIClients
    end

    subgraph FastAPI["FastAPI Backend (backend/src/ai_legal_helper/api)"]
        direction TB
        Main["main.py\n- CORS Middleware\n- trace_context_middleware\n- Lifespan (init_db, GraphSyncWorker, Neo4j)\n- Global Exception Handlers"]
        Deps["dependencies.py\n- get_current_user (session_token Cookie / 로컬 테스터 폴백)\n- verify_case_ownership (IDOR 방어)"]
        Routers["REST Routers (/api/v1)\n- auth.py (/auth/*)\n- cases.py (/cases/*)\n- consultation.py (/consultations/*)\n- evidence.py (/cases/{id}/evidence/*)\n- graph.py (/cases/{id}/graph/*)\n- documents.py (/cases/{id}/documents/*)\n- workflow.py (/cases/{id}/workflow/summary)"]

        Main --> Routers
        Routers --> Deps
    end

    subgraph Services["Domain Services & Case Intelligence (case_intelligence / database)"]
        direction TB
        CaseMgr["CaseMemoryManager (manager.py)\n+ CaseExtractor (extractor.py)\n+ TimelineEngine (timeline.py)"]
        EvidIngest["Evidence Ingestion & Extraction\n- evidence_ingestion.py (PDF/DOCX/TXT 파싱)\n- evidence_extractor.py (Span/Claim LLM 추출)\n- evidence_manager.py (Claim 승인 -> Fact 승격)"]
        ActionSvc["ActionPlanService\n(action_service.py)"]
        DocExport["DocumentExporter\n(document_exporter.py: DOCX/PDF)"]
        GraphSync["Outbox Graph Sync\n- graph_sync.py (queue_sync_task, sync_case_to_graph)\n- graph_sync_worker.py (5초 주기 폴링 태스크)"]
    end

    subgraph Workflows["LangGraph Workflows & Agents (workflows / agents / rag)"]
        direction TB
        LegalWF["Legal Consultation Graph (legal_workflow.py)\nsupervisor_initialize -> route -> plan\n-> run_agents -> synthesize -> verification\n-> finalize / revise / insufficient"]
        DocWF["Document Drafting Graph (document_workflow.py)\ngather_context -> analyze_requirements\n-> generate_draft -> verify_document -> finalize_document"]
        Agents["Agent Layer (agents/)\n- RouterAgent (router.py)\n-7 Specialist Agents (base_agent.py: 민법/행정/상사/헌법/형사/노동/세법)\n- SynthesizerAgent (synthesizer.py)\n- VerificationAgent (verification.py)"]
        RAGLayer["RAG Layer (rag/)\n- query_rewrite.py (rewrite_query)\n- retrieval_factory.py / retrieval.py (Law RAG)\n- evidence_vector.py (EvidenceVectorStore)\n- graph_rag.py (GraphRAGRetriever)"]

        LegalWF --> Agents
        LegalWF --> RAGLayer
        Agents --> RAGLayer
        DocWF --> RAGLayer
    end

    subgraph GatewayObs["LLM Gateway & Observability (llm / observability)"]
        direction TB
        LLMGateway["LLM Gateway (llm/gateway.py)\n- get_llm() (AzureChatOpenAI / ChatOpenAI)\n- invoke_with_retry() (지수 백오프 재시도)\n- Usage / Cost Tracker (llm/usage.py)"]
        Obs["Observability (observability/)\n- context.py (ContextVars)\n- decorators.py (@trace)\n- callbacks.py (TokenTrackingCallbackHandler)\n- langfuse_client.py (Langfuse SDK v2)\n- telemetry.py (OpenTelemetry FastAPI/SQLAlchemy)"]
    end

    subgraph Storage["Data Stores & External Systems"]
        direction TB
        PG[("PostgreSQL (:5432)\n15 ORM Models (models.py)\nUsers, Cases, Parties, Facts, Events,\nLegalIssues, LegalActions, Evidence*,\nConsultations, LegalDocuments, GraphSyncTasks")]
        ChromaLaw[("ChromaDB Law Store\n(backend/data/chroma)\n7개 컬렉션: law_docs_* (5,314 chunks)\n+ case_evidence (143 chunks)")]
        ChromaEvid[("ChromaDB Evidence Store\n(backend/vectorstore/chroma)\ncase_evidence (26 chunks)")]
        Neo4j[("Neo4j GraphDB (:7687)\nNodes: Case, Party, Fact, Event,\nLegalIssue, LegalAction, Evidence*\nEdges: SUPPORTS, OCCURRED_BEFORE 등")]
        FS[("Local File System\n- ./storage/evidence/ (업로드 원본)\n- ./data/exports/ (DOCX/PDF 출력)")]
        AzureLLM[["Azure OpenAI / OpenAI API\n- Chat Completions (gpt-4o-mini)\n- Embeddings (text-embedding-3-large)"]]
        LangfuseSrv[["Langfuse Server (:3001)\nTrace / Span / Generation 수집"]]
    end

    APIClients ==>|"HTTP REST / JSON / FormData / Blob\n(Vite Proxy /api -> :8000)"| Main
    Routers --> Services
    Routers --> Workflows
    Services --> PG
    Services --> FS
    GraphSync --> PG
    GraphSync --> Neo4j
    GraphSync --> ChromaEvid
    RAGLayer --> ChromaLaw
    RAGLayer --> ChromaEvid
    RAGLayer --> Neo4j
    Services --> LLMGateway
    Workflows --> LLMGateway
    Agents --> LLMGateway
    RAGLayer --> LLMGateway
    LLMGateway ==> AzureLLM
    LLMGateway --> Obs
    Workflows --> Obs
    Main --> Obs
    Obs ==> LangfuseSrv
```

---

## 2. 계층별 구성요소 및 실제 코드 위치

### 2.1 프런트엔드 계층 (`frontend/src/`)
| 구분 | 파일 경로 | 역할 및 특징 |
|---|---|---|
| 엔트리 및 라우팅 | [`frontend/src/main.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/main.tsx), [`frontend/src/App.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/App.tsx) | React 19 마운트, `AuthProvider` 래핑, 상단 `Navbar`, 라우트 정의 (`/login`, `/register`, `/`, `/:caseId/workspace/*`). [`ProtectedRoute.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/components/ProtectedRoute.tsx)는 존재하나 `App.tsx`에서 미사용. |
| 인증 컨텍스트 | [`frontend/src/context/AuthContext.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/context/AuthContext.tsx) | 앱 마운트 시 `GET /api/v1/auth/me` 호출, `auth:unauthorized` 윈도우 이벤트 수신 시 `user = null` 초기화. |
| 페이지 컴포넌트 | [`frontend/src/pages/CaseList.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/pages/CaseList.tsx), [`frontend/src/pages/CaseWorkspace.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/pages/CaseWorkspace.tsx), [`frontend/src/pages/Login.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/pages/Login.tsx), [`frontend/src/pages/Register.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/pages/Register.tsx) | 사건 목록/생성/삭제 모달(`CaseList`), 7개 탭(`overview`, `chat`, `facts`, `evidence`, `graph`, `action`, `docs`) 및 진술 추가 모달을 가진 사건 워크스페이스(`CaseWorkspace`). |
| 탭별 기능 컴포넌트 | [`ChatSection.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/components/ChatSection.tsx), [`EvidenceSection.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/components/EvidenceSection.tsx), [`EvidenceGraph.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/components/EvidenceGraph.tsx), [`ActionPlanSection.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/components/ActionPlanSection.tsx), [`DocumentSection.tsx`](file:///c:/myprjs/ai-legal-helper/frontend/src/components/DocumentSection.tsx) | 법률 질문 및 폴링(`useConsultation.ts`), 증거 파일 업로드/파싱/Claim 검토/모순 조회, `react-force-graph-2d` 기반 그래프 시각화, AI 대응 계획 생성, 내용증명/통지서 생성 및 DOCX/PDF 다운로드. |
| API 통신 래퍼 | [`frontend/src/api/apiFetch.ts`](file:///c:/myprjs/ai-legal-helper/frontend/src/api/apiFetch.ts) 외 8개 `*Client.ts` | 모든 요청에 `credentials: 'include'` 설정, 응답 코드가 401이면 `window.dispatchEvent(new Event('auth:unauthorized'))` 발생. |

### 2.2 백엔드 API 및 미들웨어 계층 (`backend/src/ai_legal_helper/api/`)
| 구분 | 파일 경로 | 역할 및 특징 |
|---|---|---|
| 앱 초기화 및 미들웨어 | [`backend/src/ai_legal_helper/api/main.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/main.py) | `lifespan`에서 `init_db()`(개발 환경), `graph_sync_worker_loop()` 백그라운드 태스크 시작, Neo4j 연결 검증 수행. `trace_context_middleware`가 요청별 `request_id`, `case_id`, Langfuse root trace(`api_request`) 생성. |
| 인증 및 인가 의존성 | [`backend/src/ai_legal_helper/api/dependencies.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/dependencies.py) | `session_token` 쿠키를 SHA-256 해싱하여 `UserSession` 조회. 미인증 시 `ALLOW_UNAUTHENTICATED_FALLBACK`(기본 `true`)에 따라 `tester@local` 계정을 자동 생성/반환하고 기존 orphan 사건(`user_id IS NULL`)을 귀속시킴. `verify_case_ownership`으로 사건 소유권 검증. |
| 라우터 모듈 | `api/routes/` 하위 7개 파일 (`auth.py`, `cases.py`, `consultation.py`, `evidence.py`, `graph.py`, `documents.py`, `workflow.py`) | `/api/v1` 프리픽스 하위에 총 27개 엔드포인트 노출. |

### 2.3 도메인 서비스 및 AI 워크플로우 계층
| 구분 | 파일 경로 | 역할 및 특징 |
|---|---|---|
| 사건 인텔리전스 | [`manager.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/case_intelligence/manager.py), [`extractor.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/case_intelligence/extractor.py), [`timeline.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/case_intelligence/timeline.py), [`action_service.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/case_intelligence/action_service.py) | 자유 진술문에서 `Party`, `Fact`, `Event`, `LegalIssue` 구조화 추출 및 기존 데이터와 병합, 타임라인 정규화·정렬, 대응 계획(`LegalAction`, `ActionRequirement`) 생성. |
| 증거 파이프라인 | [`evidence_ingestion.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/case_intelligence/evidence_ingestion.py), [`evidence_extractor.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/case_intelligence/evidence_extractor.py), [`evidence_manager.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/case_intelligence/evidence_manager.py) | 파일 확장자/MIME/SHA-256 검증, PDF(`pypdf`)/DOCX(`python-docx`)/TXT 텍스트 추출, LLM 기반 `EvidenceSpan`·`EvidenceClaim` 추출, 사용자 승인 시 `Fact` 승격 및 `EvidenceLink` 생성. |
| LangGraph 워크플로우 | [`legal_workflow.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/workflows/legal_workflow.py), [`document_workflow.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/workflows/document_workflow.py) | 법률 상담 멀티에이전트 상태 그래프(9개 노드) 및 법률 문서 초안 작성 상태 그래프(5개 노드). |
| RAG 및 그래프 동기화 | [`retrieval.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/rag/retrieval.py), [`evidence_vector.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/rag/evidence_vector.py), [`graph_rag.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/rag/graph_rag.py), [`graph_sync.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/database/graph_sync.py), [`graph_sync_worker.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/database/graph_sync_worker.py) | 법령/판례 ChromaDB 검색, 증거/사실 벡터 인덱싱, RDB→Neo4j Outbox 비동기 동기화, Neo4j 서브그래프 탐색 및 구조적 결함 분석(`analyze_case_structure`). |

---

## 3. 저장소 아키텍처 및 경로 이원화 주의사항

실제 코드와 런타임 환경을 대조한 결과, 저장소 경로 설정에 다음과 같은 구조적 특징과 불일치가 존재한다.

1. **PostgreSQL (`DATABASE_URL`, 기본 `postgresql+psycopg://postgres:postgres@localhost:5432/ai_legal_helper`)**
   - 모든 사건·증거·상담·문서·아웃박스 태스크의 **Single Source of Truth (SSOT)** 역할을 수행한다.
2. **ChromaDB 경로 이원화 (`data/chroma` vs `./vectorstore/chroma`)**
   - **법률 RAG** ([`retrieval_factory.py:32`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/rag/retrieval_factory.py#L32)): `CHROMA_DIR = os.getenv("CHROMA_DIR", "data/chroma")`를 사용하여 `backend/data/chroma` 내 7개 법령 컬렉션(`law_docs_civil` 등 총 5,314개 임베딩)을 조회한다.
   - **증거 RAG** ([`evidence_vector.py:36`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/rag/evidence_vector.py#L36)): `persist_dir = os.getenv("CHROMA_PERSIST_DIR", "./vectorstore/chroma")`를 사용하여 `backend/vectorstore/chroma` 내 `case_evidence` 컬렉션(26개 임베딩)에 저장한다. (반면 `backend/data/chroma`에도 과거 적재된 `case_evidence` 143개 임베딩이 별도로 존재한다.)
   - 또한 Docker 컨테이너로 떠 있는 `:8001` Chroma 서버는 코드 어디에서도 `HttpClient`로 호출하지 않으며, 로컬 `PersistentClient`만 사용한다.
3. **인메모리 상담 상태와 PostgreSQL 이중 관리 (`consultation.py:38`)**
   - [`consultation.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/routes/consultation.py#L38)는 프로세스 메모리 딕셔너리 `_consultations: Dict[str, ConsultationResponse] = {}`와 PostgreSQL `consultations` 테이블에 상태를 중복 기록한다.
   - 단건 폴링 엔드포인트(`GET /api/v1/consultations/{request_id}`)는 `_consultations` 메모리를 우선 조회하고 없을 때만 DB를 조회하므로, 멀티 워커 환경이나 서버 재시작 직후 상태 불일치가 발생할 수 있다.
4. **레거시 Streamlit UI 공존 (`backend/src/ai_legal_helper/ui/app.py`)**
   - 통합 아키텍처(React + FastAPI) 외에 레거시 프로토타입인 [`ui/app.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/ui/app.py)가 남아 있으나, 신규 서비스 실행 플로우에서는 사용되지 않는다.

