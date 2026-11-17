# AI Legal Helper 기술 아키텍처 발표자료 - 상세 개정판

- 소스 기준: `main` 브랜치 (2026-11-17, 검토 시점 SHA: `76ac3753aa57735661c2b406037ae2891228416f`)
- 제작 형식: 16:9 와이드 · 2400×1350 · 한국어 · 편집 가능한 SVG + 생성 시 PNG/PDF
- 목적: 동일한 박스 나열을 피하고 **사용자 경험 / 실행 아키텍처 / 실제 LangGraph 토폴로지**를 각각 별도 도식으로 설명

## 그림 구성

| 파일 | 다이어그램 성격 | 핵심 내용 |
|---|---|---|
| `01_사용자경험_서비스개념도.svg` | 사용자 여정 + 사용자/시스템 2계층 스윔레인 | 사건 생성 → 증거 업로드 → 사실 승인 → AI 상담 → 대응계획 → 법률문서; 하단에 DB 객체와 사건 맥락 유지 |
| `02_전체시스템_아키텍처.svg` | 기술 시스템 아키텍처 및 컨테이너 경계 | React 프런트엔드, FastAPI / BackgroundTasks / LangGraph / Graph Sync Worker, Azure OpenAI, 법령 API, Langfuse, PostgreSQL, Neo4j, ChromaDB, 증거 파일 저장소 |
| `03_LangGraph_상담처리흐름도.svg` | **실제 Node / Edge 기반 실행 흐름** | 활성 노드 14개, 조건부 분기 6개, 총 30개 연결, 조기 종료·추가 법령검색·재분석·재검증 루프 |

> 모든 그림은 논리 및 실행 관계를 설명합니다. Docker Compose에 없는 외부 서비스를 같은 컨테이너로 표현하거나, 코드를 확인하지 않은 독립 Agent/Node를 생성하지 않았습니다.

## 코드 근거

| 구분 | 소스코드 | 검토 결과 |
|---|---|---|
| 웹 UI | `frontend/src/pages/CaseWorkspace.tsx`, `frontend/src/App.tsx` | 사건 워크스페이스(상담, 증거, 사실·타임라인, 그래프, 계획, 문서) |
| API 경계 | `backend/src/ai_legal_helper/api/main.py` | FastAPI 엔트리, 라우터, 추적 미들웨어, Graph Sync Worker 실행 |
| 상담 API | `backend/src/ai_legal_helper/api/routes/consultation.py` | `BackgroundTasks`, 상태 폴링, `ConsultationRecord` 저장, 상담 실행 함수 |
| 증거 처리 | `backend/src/ai_legal_helper/api/routes/evidence.py` | 파일 저장·텍스트 추출·LLM 사실 후보·사용자 리뷰·동기화 태스크 |
| 법률 상담 | `backend/src/ai_legal_helper/workflows/legal_workflow.py` | `build_legal_graph()` 실제 Node, Edge, 분기 함수, 체크포인터 |
| 법률문서 | `backend/src/ai_legal_helper/workflows/document_workflow.py` | **별도의** `context → requirements → generate → verification → review_gate` 그래프 |
| 문서 API | `backend/src/ai_legal_helper/api/routes/documents.py` | 문서 생성·개정·DOCX/PDF 내보내기 |
| LLM / Embedding | `backend/src/ai_legal_helper/llm/gateway.py` | AzureChatOpenAI, AzureOpenAIEmbeddings, 토큰 추적 연결 |
| DB 동기화 | `backend/src/ai_legal_helper/database/graph_sync_worker.py` | PostgreSQL의 `GraphSyncTask`를 폴링하여 Neo4j 동기화, 재시도 |
| 런타임 서비스 | `docker-compose.yml` | frontend, api, postgres, neo4j, chromadb; 외부 LLM/법령/Langfuse 분리 |

## LangGraph : 등록된 활성 노드 (총 14)

`supervisor_initialize`, `general_conversation`, `evidence_unavailable`, `route`, `run_agents`, `synthesize`, `verification`, `revise`, `insufficient`, `finalize`, `statute_search_approval`, `execute_statute_search`, `re_analyze`, `routing_exit`.

실제 함수 정의가 있어도 등록하지 않은 `followup_action`, `statute_search_plan`, `legal_evidence_bundle`은 **활성 노드가 아닙니다**.

### 실제 Edge 30개

| 출발 노드 | 실제 도착 노드 | 개수 | 구분 |
|---|---|---:|---|
| START | supervisor_initialize | 1 | 고정 |
| supervisor_initialize | general_conversation, evidence_unavailable, routing_exit, route | 4 | 조건부 |
| general_conversation | END | 1 | 고정 |
| evidence_unavailable | END | 1 | 고정 |
| route | run_agents, routing_exit | 2 | 조건부 |
| routing_exit | END | 1 | 고정 |
| run_agents | synthesize | 1 | 고정 |
| synthesize | verification, statute_search_approval, insufficient | 3 | 조건부 |
| verification | finalize, statute_search_approval, execute_statute_search, revise, insufficient | 5 | 조건부 |
| statute_search_approval | execute_statute_search, insufficient | 2 | 조건부 |
| execute_statute_search | run_agents, re_analyze, revise, finalize, insufficient | 5 | 조건부 |
| re_analyze | verification | 1 | 고정 |
| revise | verification | 1 | 고정 |
| insufficient | END | 1 | 고정 |
| finalize | END | 1 | 고정 |
| **합계** | | **30** | 조건부 21 / 고정 9 |

### 특히 주의할 조건: `execute_statute_search → finalize`

단순 검색 성공 후 무조건 검증을 건너뛰는 경로가 아닙니다. `statute_search_result_condition()`에서 **`DOCUMENT_MODE` + `search_delta_count == 0` + 기존 `draft_answer`**일 때, 최초 수정 기회가 필요한 상태라면 `revise`로 보내고, 그 외에 기존 `verification_result.claims`가 있으면 `finalize`를 반환합니다. `finalize_node()`는 문서 모드에서 `finish_answer()`를 호출하며, 초안·출처 스냅샷 무결성, 법령 적용 시점 차단, 미입증 주장, 출처 검증 등 안전 검사를 수행하여 허용하거나 판단을 보류합니다.

### 실제 실행 경로와 가능한 경로의 구별

여기 표시한 내용은 `main`의 **가능한 그래프 토폴로지**입니다. 특정 사건이 어느 Edge를 실제로 통과했는지는 별도 Langfuse E2E V8 Trace를 분석해야 합니다. 본 그림을 "SC-001 실제 실행 경로"로 오해해 사용해서는 안 됩니다.

## 생성 / 편집

```bash
python build_graph_slide.py
```

위 스크립트는 `build_deep_slides.py`를 import하여 1·2장 및 기본 도형을 생성한 뒤, 3장 실제 Edge 전체를 그려 세 페이지를 PDF로 병합합니다. 추가 Python 패키지: `svgwrite`, `cairosvg`, `PyMuPDF`.

- 원본: SVG 3장, 각 도형/텍스트 편집 가능
- 출력: PNG 3장, PDF 3장, `AI_Legal_Helper_기술아키텍처_상세3장.pdf`
- 다이어그램은 **왼쪽 → 오른쪽 / 위 → 아래**를 우선하며, 재검증과 검색 재시도 Edge만 반대 방향으로 복귀하도록 연결합니다.