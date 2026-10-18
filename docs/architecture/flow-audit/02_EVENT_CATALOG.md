# 02. 전체 이벤트 카탈로그 (Event Catalog)

이 문서는 감사 기준 필수 이벤트 30개(`EVT-001` ~ `EVT-030`)와 실제 프런트엔드·백엔드 코드 전수 조사로 추가 발견된 이벤트 5개(`EVT-031` ~ `EVT-035`)를 포함한 **총 35개 이벤트의 종합 카탈로그**이다.

---

## 1. 구현 상태 분류 기준

- **`IMPLEMENTED` (구현 완료)**: UI/트리거부터 API, Service, DB 반영, 응답 및 화면 갱신까지 E2E 코드 경로가 완결되어 있고 치명적 런타임 차단 결함이 없는 상태.
- **`PARTIAL` (부분 구현 / 결함 내포)**: 코드는 존재하나 (a) 프롬프트/데이터 전달 누락, (b) 특정 조건에서 런타임 예외(`NameError`, `AttributeError`, `ImportError`, HTTP 422), (c) 핵심 하위 로직(모순 링크 생성 등) 미작동으로 인해 설계 의도대로 완결되지 않는 상태.
- **`MISSING` (미구현)**: 해당 이벤트를 처리하는 UI 핸들러, API 엔드포인트 또는 LangGraph 노드/엣지가 실제 코드에 존재하지 않는 상태.

---

## 2. 전체 이벤트 목록 (`EVT-001` ~ `EVT-035`)

### A. 필수 기준 이벤트 (`EVT-001` ~ `EVT-030`)

| 이벤트 ID | 이벤트 명칭 | 발생 영역 / 트리거 | 호출 API / 내부 진입점 | 핵심 처리 요약 | 구현 상태 | 상세 문서 |
|---|---|---|---|---|---|---|
| **EVT-001** | 서비스 시작 및 초기화 | 백엔드 프로세스 기동 | `api/main.py:lifespan` | 로깅/OTel 초기화 → 개발환경 `init_db()` → `graph_sync_worker_loop()` 태스크 기동 → Neo4j 연결 확인 | **IMPLEMENTED** | [EVT-001](events/EVT-001.md) |
| **EVT-002** | 사용자 세션 시작 | 앱 초기 마운트 (`AuthProvider`) | `GET /api/v1/auth/me` | `session_token` 쿠키 검증 또는 미인증 시 로컬 테스터(`tester@local`) 자동 생성·귀속. 단 `ProtectedRoute`는 미적용 | **PARTIAL** | [EVT-002](events/EVT-002.md) |
| **EVT-003** | 사건 등록 | `CaseList` `+ 새 사건 등록` 모달 제출 | `POST /api/v1/cases` | `CaseMemoryManager.create_case()`로 `Case(status="OPEN")` 생성 후 워크스페이스로 이동 | **IMPLEMENTED** | [EVT-003](events/EVT-003.md) |
| **EVT-004** | 사건 목록 조회 | `CaseList` 마운트 | `GET /api/v1/cases` | 현재 사용자의 `Case` 목록 최신순 조회 및 카드 렌더링 | **IMPLEMENTED** | [EVT-004](events/EVT-004.md) |
| **EVT-005** | 사건 상세 조회 | `CaseWorkspace` 진입 (`/:caseId/workspace/*`) | `GET /api/v1/cases/{case_id}` | 사건 기본 정보 + `parties`, `facts`, `events`, `legal_issues` Eager/Lazy 로드 및 사이드바·탭 상태 설정 | **IMPLEMENTED** | [EVT-005](events/EVT-005.md) |
| **EVT-006** | 사건 정보 수정 | 해당 없음 (미구현) | 미구현 (`PUT/PATCH /cases/{id}` 없음) | 사건 제목·유형·상태를 수정하는 UI 모달 및 REST API 엔드포인트가 존재하지 않음 (진술 추가만 존재) | **MISSING** | [EVT-006](events/EVT-006.md) |
| **EVT-007** | 사건 삭제 | `CaseList` 사건 카드 `삭제` 버튼 → 확인 모달 | `DELETE /api/v1/cases/{case_id}` | 증거 물리 파일 삭제 → `Case` ORM Cascade 삭제 → `GraphSyncTask` 큐잉 | **IMPLEMENTED** | [EVT-007](events/EVT-007.md) |
| **EVT-008** | 증거 파일 업로드 | `EvidenceSection` `+ 증거 파일 업로드` | `POST /api/v1/cases/{case_id}/evidence` | 확장자/MIME/SHA-256 중복 검사 → `./storage/evidence/` 저장 → `EvidenceDocument(UPLOADED)` 생성 → 백그라운드 추출 예약 | **IMPLEMENTED** | [EVT-008](events/EVT-008.md) |
| **EVT-009** | 파일 파싱 및 사실 추출 | 업로드 직후 BackgroundTask 또는 `사실 추출` 버튼 | `POST /api/v1/cases/{case_id}/evidence/{doc_id}/extract` | PDF/DOCX/TXT 파싱 → `EvidenceSpan` 저장 → LLM `EvidenceClaim` 추출 → `status="EXTRACTED"` | **IMPLEMENTED** | [EVT-009](events/EVT-009.md) |
| **EVT-010** | 증거 임베딩 및 인덱싱 | `GraphSyncWorker` 5초 주기 폴링 | `sync_evidence_to_vector_store()` | `Fact` 및 `EvidenceClaim`을 임베딩하여 ChromaDB `case_evidence`에 Upsert. 단 Chroma 경로 이원화 및 로컬 Rust 패닉 이슈 존재 | **PARTIAL** | [EVT-010](events/EVT-010.md) |
| **EVT-011** | 사건 Timeline 생성 | 진술 추가 시 자동 실행 | `TimelineEngine.reconstruct_timeline()` | 추출된 `Event`들의 날짜를 `YYYY-MM-DD` 정규화 및 시간순 정렬하여 저장 후 `FactsTab`에 표시 | **PARTIAL** | [EVT-011](events/EVT-011.md) |
| **EVT-012** | 법률 질문 입력 | `ChatSection` `🚀 상담 요청하기` 버튼 | `POST /api/v1/consultations` + `GET /api/v1/consultations/{id}` | 질문 접수 후 `IN_PROGRESS` 레코드 생성, 백그라운드 `process_consultation` 기동 및 프런트 2초 주기 폴링 | **PARTIAL** | [EVT-012](events/EVT-012.md) |
| **EVT-013** | Supervisor Agent 실행 | `process_consultation` 내부 `graph.invoke()` | `legal_workflow.py` (`supervisor_initialize` ~ `synthesize`) | 사건 브리핑 + GraphRAG 컨텍스트 조합 → `RouterAgent` 분야 분류 → `plan` → 하위 에이전트 실행 → `SynthesizerAgent` 통합 | **PARTIAL** | [EVT-013](events/EVT-013.md) |
| **EVT-014** | 법률 RAG 검색 | 하위 에이전트 실행 중 `search_law` Tool 호출 | `RetrievalService.retrieve()` | `rewrite_query` 후 ChromaDB `law_docs_*` 검색 및 `_retrieved_sources_var` 저장. **단, `BaseAgent`가 검색 결과 텍스트를 폐기하여 LLM에 미전달!** | **PARTIAL** | [EVT-014](events/EVT-014.md) |
| **EVT-015** | 증거 RAG 검색 | `GraphRAGRetriever.search_hybrid()` 폴백 경로 | `EvidenceVectorStore.search_similar_evidence()` | ChromaDB `case_evidence` 유사도 검색 코드가 존재하나, 호출부에서 `if driver is None: return`으로 사전 차단되어 실행되지 않음 | **PARTIAL** | [EVT-015](events/EVT-015.md) |
| **EVT-016** | GraphRAG 검색 | 상담 초기화(`_collect_graph_evidence`) 및 문서 작성(`gather_context`) | `GraphRAGRetriever.search_hybrid()` | Neo4j Cypher로 사건 서브그래프 조회 후 `[그래프 기반 사건 증거 컨텍스트]` 생성. `Synthesizer`와 `DocumentWorkflow`만 활용 (`BaseAgent`는 누락) | **PARTIAL** | [EVT-016](events/EVT-016.md) |
| **EVT-017** | 검색 결과 충분성 평가 | `legal_workflow.py` `verification_node` | `VerificationAgent.verify_answer()` | 답변의 근거·할루시네이션·충분성을 평가하여 `PASS`/`REVISE`/`INSUFFICIENT` 반환. 단 JSON 스키마 누락으로 파싱 실패 시 `PASS` 폴백 | **PARTIAL** | [EVT-017](events/EVT-017.md) |
| **EVT-018** | 검색 전략 변경 및 재검색 | `verification_condition` == `"REVISE"` 분기 | `legal_workflow.py:revise_node` | **미구현**: `revise_node`는 기존 초안 텍스트만 LLM으로 수정하며, 검색 쿼리를 변경하거나 ChromaDB/Neo4j를 재검색하는 루프가 없음 | **MISSING** | [EVT-018](events/EVT-018.md) |
| **EVT-019** | LLM 답변 생성 | 하위 에이전트 → `SynthesizerAgent` → `finalize`/`revise` | `BaseAgent.run()`, `SynthesizerAgent.synthesize()` | 분야별 초안 생성 후 종합 답변 작성. `BaseAgent`에 RAG/사건 컨텍스트가 누락되어 LLM 사전학습 지식 의존도가 높음 | **PARTIAL** | [EVT-019](events/EVT-019.md) |
| **EVT-020** | 법률 근거 및 인용 검증 | 답변 생성 및 검증 단계 | `base_agent.py`, `verification.py`, `consultation.py:147` | 본문 인용과 실제 검색 출처(`_retrieved_sources_var`) 대조 검증기 부재. 검색 출처가 있으면 `consultation.py:147`에서 `os` 미임포트로 `NameError` 발생 | **PARTIAL** | [EVT-020](events/EVT-020.md) |
| **EVT-021** | 분석 결과 저장 | `process_consultation` 완료 단계 | `consultation.py:153-233` | `_consultations` 메모리 및 PostgreSQL `consultations` 테이블 갱신. 단 `sources` 존재 시 `NameError`로 인해 `status="ERROR"`로 저장됨 | **PARTIAL** | [EVT-021](events/EVT-021.md) |
| **EVT-022** | 분석 결과 화면 표시 | `useConsultation` 폴링 완료 또는 상담 이력 로드 | `ChatSection.tsx` 렌더링 | 질문·답변·출처 배지(`sources`) 화면 표시. 단 `verification_result`와 `warnings` 필드는 UI에서 렌더링하지 않음 | **PARTIAL** | [EVT-022](events/EVT-022.md) |
| **EVT-023** | 새로운 증거 추가 후 재분석 | 증거 업로드 → Claim 승인 → 상담/액션플랜 재실행 | `POST .../review` → `POST /consultations` 또는 `POST .../actions/plan` | Claim 승인 시 `Fact` 승격 및 `GraphSyncTask` 큐잉 후 사용자가 수동으로 상담·액션플랜·문서 생성을 재호출. 자동 재분석 트리거는 없음 | **PARTIAL** | [EVT-023](events/EVT-023.md) |
| **EVT-024** | 증거 불일치 탐지 | `EvidenceSection` 마운트 시 자동 호출 | `GET /api/v1/cases/{case_id}/evidence/conflicts` | RDB `CONTRADICTS` 링크 및 `CONTRADICTION_CANDIDATE` 조회 + GraphRAG 조회를 시도하나, 해당 데이터를 생성하는 코드가 없고 `GraphRAG` `ImportError`로 항상 빈 목록 반환 | **PARTIAL** | [EVT-024](events/EVT-024.md) |
| **EVT-025** | Next Action 생성·갱신 | `ActionPlanSection` 생성 버튼 및 `OverviewTab` 진입 | `POST /api/v1/cases/{case_id}/actions/plan`, `GET .../workflow/summary` | LLM 기반 `LegalAction`/`ActionRequirement` 생성(단 `queue_sync_task` 후 `commit` 누락) 및 워크플로우 단계 기반 `next_action` 배너 산출 | **PARTIAL** | [EVT-025](events/EVT-025.md) |
| **EVT-026** | 법률 문서 초안 생성 | `DocumentSection` 내용증명/통지서 생성 버튼 | `POST /api/v1/cases/{case_id}/documents` | `document_workflow.py` 5단계 그래프 실행 후 `LegalDocument` 저장. 단 생성 후 `OverviewTab` 호출 시 `d.doc_type` `AttributeError` 유발 | **PARTIAL** | [EVT-026](events/EVT-026.md) |
| **EVT-027** | DOCX/PDF 다운로드 | `DocumentSection` `📥 DOCX 다운로드` / `📥 PDF 다운로드` | `POST /api/v1/cases/{case_id}/documents/{doc_id}/export?format=docx\|pdf` | `python-docx` / `reportlab`(Malgun Gothic 폰트)으로 파일 생성 후 `FileResponse` Blob 다운로드 | **IMPLEMENTED** | [EVT-027](events/EVT-027.md) |
| **EVT-028** | Langfuse Trace 기록 | 모든 API 요청, `@trace` 함수, LLM 호출 | `observability/*`, `llm/gateway.py` | 미들웨어 root trace, `@trace` span, `TokenTrackingCallbackHandler` generation 기록. 단 부모 Span ID 매칭 버그로 계층 평탄화 및 기본 핸들러 마스킹 우회 존재 | **PARTIAL** | [EVT-028](events/EVT-028.md) |
| **EVT-029** | 오류·타임아웃·재시도 처리 | LLM 호출 실패, GraphSync 실패, API 예외, 401 응답 | `gateway.py`, `graph_sync_worker.py`, `main.py`, `apiFetch.ts` | LLM 지수 백오프 재시도, GraphSync 3회 재시도(`FAILED`), 전역 예외 핸들러, 401 이벤트 처리 구현. 단 다수의 `except: pass` 존재 | **PARTIAL** | [EVT-029](events/EVT-029.md) |
| **EVT-030** | 서비스 종료 및 리소스 정리 | FastAPI 서버 종료 시그널 | `api/main.py:lifespan` 종료 블록 | `graph_sync_worker` 태스크 취소 및 `close_neo4j_driver()` 수행. 단 `flush_langfuse()` 및 PostgreSQL `engine.dispose()` 누락 | **PARTIAL** | [EVT-030](events/EVT-030.md) |

---

### B. 코드 전수 조사로 추가 발견된 이벤트 (`EVT-031` ~ `EVT-035`)

| 이벤트 ID | 이벤트 명칭 | 발생 영역 / 트리거 | 호출 API / 내부 진입점 | 핵심 처리 요약 | 구현 상태 | 상세 문서 |
|---|---|---|---|---|---|---|
| **EVT-031** | 사용자 회원가입·로그인·로그아웃 | `Register.tsx`, `Login.tsx`, `Navbar` 로그아웃 버튼 | `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout` | 회원가입 시 프런트 `{name}` vs 백엔드 `{display_name}` 불일치(HTTP 422), 로그인 시 `{message}` 객체를 `user` 상태에 저장하는 버그 존재 | **PARTIAL** | [EVT-031](events/EVT-031.md) |
| **EVT-032** | 사건 진술(Statement) 추가 및 사실·쟁점 추출 | 사이드바 `+ 새 사실(Fact) 추가` 모달 또는 상담 내역 `📌 사건 사실관계(Fact)로 등록` | `POST /api/v1/cases/{case_id}/statements` | `CaseMemoryManager.process_new_statement()` → LLM으로 당사자·사실·이벤트·쟁점 추출 및 병합 → 타임라인 재구성 → `GraphSyncTask` 큐잉 | **IMPLEMENTED** | [EVT-032](events/EVT-032.md) |
| **EVT-033** | 증거 추출 주장(Claim) 검토 (승인·수정승인·반려) | `EvidenceSection` Claim 카드 `✓ 승인`, `✎ 수정 승인`, `✕ 반려` 버튼 | `POST /api/v1/cases/{case_id}/evidence/{doc_id}/claims/{claim_id}/review` | 승인/수정승인 시 `EvidenceClaim`을 `Fact(source="evidence_promoted")`로 승격하고 `EvidenceLink(SUPPORTS)` 생성 후 `GraphSyncTask` 큐잉 | **IMPLEMENTED** | [EVT-033](events/EVT-033.md) |
| **EVT-034** | 증거 파일 삭제 | `EvidenceSection` 문서 목록 `삭제` 버튼 | `DELETE /api/v1/cases/{case_id}/evidence/{doc_id}` | 물리 파일 삭제, 해당 문서에서 승격된 `Fact` 삭제(타 증거 연결 없는 경우), `EvidenceDocument` Cascade 삭제, `GraphSyncTask` 큐잉 | **IMPLEMENTED** | [EVT-034](events/EVT-034.md) |
| **EVT-035** | 통합 워크플로우 요약 및 증거 그래프 시각화·분석 조회 | `OverviewTab` 및 `EvidenceGraph` 마운트 / `🔄 새로고침` | `GET /api/v1/cases/{case_id}/workflow/summary`, `GET .../graph`, `GET .../graph/analysis` | 5단계 진행률·요약 카드·최근 활동 조회 및 Neo4j 그래프 노드/엣지·구조적 결함 조회. 단 `LegalDocument` 존재 시 `workflow/summary`가 `d.doc_type` `AttributeError`로 실패 | **PARTIAL** | [EVT-035](events/EVT-035.md) |

---

## 3. 백엔드에 존재하나 프런트엔드 UI에서 호출하지 않는 미연결 API 목록

코드 대조 결과, 백엔드 라우터에는 정의되어 있으나 프런트엔드(`frontend/src/`) 어디에서도 호출하지 않는 엔드포인트는 총 4개이다.

1. `GET /api/v1/consultations/{request_id}/status` ([`consultation.py:237`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/routes/consultation.py#L237)): 프런트엔드 `useConsultation.ts`는 경량 상태 엔드포인트 대신 전체 결과 엔드포인트인 `GET /api/v1/consultations/{request_id}`를 2초마다 폴링한다.
2. `GET /api/v1/graph/health` ([`graph.py:36`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/routes/graph.py#L36)): Neo4j 가용성 확인용 엔드포인트이나 UI에서 호출하지 않는다.
3. `POST /api/v1/cases/{case_id}/graph/sync` ([`graph.py:42`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/routes/graph.py#L42)): 수동 즉시 그래프 동기화 엔드포인트이나 UI에 버튼이 없다(백그라운드 워커가 자동 동기화 수행).
4. `GET /api/v1/cases/{case_id}/graph/search` ([`graph.py:84`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/routes/graph.py#L84)): 하이브리드 그래프 검색 독립 API이나 UI 검색창이 연결되어 있지 않다.

