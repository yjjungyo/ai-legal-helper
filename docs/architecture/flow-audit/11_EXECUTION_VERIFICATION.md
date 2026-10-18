# 11. 실제 실행 검증 결과 (Execution Verification Report)

이 문서는 감사 지침 제7장(실제 실행 검증)에 따라 **정적 코드 분석만 수행한 항목**과 **실제 로컬 인프라(PostgreSQL, Neo4j, ChromaDB SQLite) 및 FastAPI `TestClient`/격리 실행으로 직접 확인한 항목**을 엄격히 구분하여 기록한다.
(감사 원칙에 따라 사용자 DB 데이터나 소스코드를 변경하지 않는 **비파괴 Read-Only 검증**으로 수행하였다.)

---

## 1. 로컬 런타임 인프라 및 저장소 실측 결과

### 1.1 실행 중인 컨테이너 및 포트 상태
- **PostgreSQL**: `127.0.0.1:5432` — **정상 연결 (`CONNECTED`)**
- **Neo4j**: `127.0.0.1:7474` (HTTP), `127.0.0.1:7687` (Bolt) — **정상 연결 (`CONNECTED`, `get_neo4j_driver()` 가용)**
- **ChromaDB Server**: `127.0.0.1:8001` — 포트 리스닝 중이나 `HttpClient(host="localhost", port=8001)` 접속 시 `chromadb.errors.InternalError: (code: 14) unable to open database file` 발생 (단, 백엔드 코드는 `:8001` 서버를 사용하지 않고 로컬 `PersistentClient`를 사용함)
- **Langfuse Server**: `127.0.0.1:3001` — 포트 리스닝 중

### 1.2 PostgreSQL 15개 테이블 실제 적재 현황 (PII 제외 카운트)
`ai_legal_helper.database.session.engine`을 통해 실제 DB의 전체 테이블과 행 수를 조회한 결과는 다음과 같다.

| 테이블명 | 행 수 | 검증 결과 | 비고 |
|---|---:|---|---|
| `users` | 32 | 정상 조회 | `tester@local` 포함 |
| `user_sessions` | 12 | 정상 조회 | 세션 토큰 해시 저장 확인 |
| `cases` | 3 | 정상 조회 | `status`: `OPEN` 2건, `IN_PROGRESS` 1건(`synth-case-lease-001`) |
| `parties` | 7 | 정상 조회 | 사건별 임대인/임차인 등 |
| `facts` | 49 | 정상 조회 | 진술 추출 및 증거 승격 사실 |
| `events` | 6 | 정상 조회 | 타임라인 이벤트 |
| `legal_issues` | 12 | 정상 조회 | 법률 쟁점 |
| `legal_actions` | 10 | 정상 조회 | `ActionItem` 모델의 실제 테이블명(`__tablename__ = "legal_actions"`) |
| `action_requirements` | 27 | 정상 조회 | 대응 계획 체크리스트 |
| `evidence_documents` | 2 | 정상 조회 | 업로드된 증거 문서 |
| `evidence_spans` | 32 | 정상 조회 | 파싱된 텍스트 구간 |
| `evidence_claims` | 68 | 정상 조회 | 추출된 주장 |
| `evidence_links` | 36 | 정상 조회 | 모두 `SUPPORTS` 링크 (`CONTRADICTS` 0건) |
| `graph_sync_tasks` | 28 | 정상 조회 | Outbox 동기화 이력 |
| `consultations` | 11 | 정상 조회 | 법률 상담 이력 |
| `legal_documents` | 0 | **0건** | **현재 0건이기 때문에 `workflow.py:305`의 `d.doc_type` 버그가 잠복 상태임이 입증됨** |

---

### 1.3 ChromaDB 로컬 SQLite 및 Rust 클라이언트 검증 결과
1. **SQLite 직접 조회 (`sqlite3` Read-Only 모드)**:
   - `backend/data/chroma/chroma.sqlite3` (법률 RAG 저장소):
     - `law_docs_civil`: **1,210** embeddings
     - `law_docs_commercial`: **1,219** embeddings
     - `law_docs_tax`: **1,130** embeddings
     - `law_docs_administrative`: **767** embeddings
     - `law_docs_labor`: **449** embeddings
     - `law_docs_criminal`: **403** embeddings
     - `law_docs_constitution`: **136** embeddings
     - `case_evidence`: **143** embeddings
   - `backend/vectorstore/chroma/chroma.sqlite3` (증거 벡터 저장소):
     - `case_evidence`: **26** embeddings
2. **Python `chromadb.PersistentClient` 실행 시 패닉 확인**:
   - 현재 시스템 Python(`C:\Python311`, `chromadb==1.0.20`)에서 `chromadb.PersistentClient(path="backend/data/chroma")` 또는 `PersistentClient(path="backend/vectorstore/chroma")` 호출 시:
     ```text
     thread '<unnamed>' panicked at rust\sqlite\src\db.rs:157:42:
     range start index 10 out of range for slice of length 9
     pyo3_runtime.PanicException: range start index 10 out of range for slice of length 9
     ```
   - 이는 기존 `chroma.sqlite3`가 구버전 ChromaDB에서 생성된 상태에서 `chromadb 1.0.20` Rust 바인딩이 마이그레이션/경로 슬라이싱을 수행할 때 발생하는 패닉으로, 로컬에서 RAG 검색이나 증거 벡터 동기화를 실행할 때 즉시 패닉을 일으킨다.

---

### 1.4 Neo4j 그래프 DB 실측 결과
`get_neo4j_driver()`를 통해 실제 Neo4j(`bolt://localhost:7687`)에 저장된 노드와 엣지 수를 조회한 결과:
- **노드(Nodes)**: `Case` (11), `EvidenceDocument` (5), `Fact` (49), `Party` (7), `Event` (6), `LegalIssue` (12), `LegalAction` (10), `EvidenceSpan` (32), `EvidenceClaim` (68), `ActionRequirement` (27) — **총 227개 노드**
- **관계(Relationships)**: `SUPPORTS` (106), `HAS_CLAIM` (68), `HAS_FACT` (49), `CONTAINS_SPAN` (32), `HAS_REQUIREMENT` (27), `HAS_ISSUE` (12), `RECOMMENDS_ACTION` (10), `DEPENDS_ON_ACTION` (10), `INVOLVES_PARTY` (7), `RELATED_TO` (7), `HAS_EVENT` (6), `HAS_EVIDENCE` (5), `OCCURRED_BEFORE` (5) — **총 344개 엣지** (`CONTRADICTS` 엣지는 **0개**)

---

## 2. FastAPI `TestClient` 기반 실제 API 실행 검증 결과

FastAPI 앱(`ai_legal_helper.api.main:app`)을 `TestClient`로 구동하여 DB에 존재하는 3개 사건(`d54ebb0d-...`, `synth-case-lease-001`, `85d797a7-...`)에 대해 Read-Only 엔드포인트들을 실제 호출한 결과는 다음과 같다.

| 호출 엔드포인트 | HTTP 상태 코드 | 실행 시간 | 실제 응답 및 검증 결과 |
|---|---:|---:|---|
| `GET /api/v1/auth/me` | **200 OK** | ~15ms | 쿠키 없이 요청 시 로컬 테스터 폴백 동작 확인:<br>`{"id": "f83a07d3-...", "email": "tester@local", "display_name": "로컬 테스터", "status": "ACTIVE"}` |
| `GET /api/v1/cases` | **200 OK** | ~12ms | 3개 사건 배열 정상 반환 (`CaseSchema`) |
| `GET /api/v1/cases/{case_id}` | **200 OK** | ~10ms | 3개 사건 모두 `parties`, `facts`, `events`, `legal_issues` 포함 반환.<br>*(참고: FastAPI `response_model=CaseDetailSchema`는 루트의 `from_attributes=True`를 하위 스키마에 전파하여 200 OK를 반환하나, Python에서 `CaseDetailSchema.model_validate(orm_obj)`를 직접 호출하면 하위 스키마에 `from_attributes=True`가 없어 `ValidationError` 발생)* |
| `GET /api/v1/cases/{case_id}/workflow/summary` | **200 OK** *(조건부)* | ~20ms | 현재 3개 사건 모두 `legal_documents`가 0건이고 `last_c.answer`가 비어있지 않아 200 OK 반환.<br>**단, 격리 검증(4c)에서 `LegalDocument` 인스턴스에 `.doc_type` 접근 시 `AttributeError` 발생 확인 완료.** |
| `GET /api/v1/cases/{case_id}/evidence` | **200 OK** | ~7ms | 사건별 증거 문서 목록 정상 반환 |
| `GET /api/v1/cases/{case_id}/evidence/conflicts` | **200 OK** | ~8ms | 3개 사건 모두 `[]` (빈 배열) 반환. 내부적으로 `from ai_legal_helper.rag.graph_rag import GraphRAG`가 `ImportError`를 일으키고 `except: pass`로 무시됨을 확인 |
| `GET /api/v1/cases/{case_id}/graph` | **200 OK** | ~15ms | Neo4j로부터 사건 서브그래프 `nodes`, `edges` 정상 반환 |
| `GET /api/v1/cases/{case_id}/graph/analysis` | **200 OK** | ~10ms | Neo4j 기반 미입증 사실(`unsupported_facts`), 미해결 쟁점(`unaddressed_issues`) 등 정상 반환 |
| `GET /api/v1/cases/{case_id}/actions` | **200 OK** | ~10ms | 사건별 대응 계획 목록 정상 반환 |
| `GET /api/v1/cases/{case_id}/documents` | **200 OK** | ~7ms | `[]` 반환 (`legal_documents` 0건) |
| `GET /api/v1/cases/{case_id}/consultations` | **200 OK** | ~8ms | 과거 저장된 상담 이력 정상 반환 |
| `GET /api/v1/graph/health` | **200 OK** | ~1ms | `{"available": true}` 반환 |

---

## 3. 핵심 결함의 격리 실행(Isolated Runtime Reproduction) 검증 결과

데이터를 오염시키지 않고 각 버그의 정확한 발생 메커니즘을 Python 런타임에서 직접 실행하여 확인한 결과이다.

| 검증 번호 | 검증 대상 | 실행 코드 요약 | 실제 런타임 출력 | 판정 |
|---:|---|---|---|---|
| **검증 1** | 회원가입 스키마 불일치 (`EVT-031`) | `UserCreate.model_validate({"email": "a@b.com", "password": "pw", "name": "Tester"})` | `ValidationError: 1 validation error for UserCreate - display_name: Field required` | **실행 확인 완료 (`CONFIRMED BUG`)** |
| **검증 2** | `LegalDocument` 컬럼명 및 속성 오류 (`EVT-026`, `EVT-035`) | `models.LegalDocument` 필드 및 `.doc_type` 접근 확인 | `LegalDocument` 컬럼은 `document_type`이며 `.doc_type` 속성이 존재하지 않아 `workflow.py:305` 실행 시 `AttributeError` 발생 확정 | **실행 확인 완료 (`CONFIRMED BUG`)** |
| **검증 3** | `BaseAgent` 프롬프트 변수 누락 (`EVT-013`, `EVT-014`, `EVT-019`) | `PromptTemplate.from_template(REACT_TEMPLATE).input_variables` 확인 | `['agent_scratchpad', 'input', 'system', 'tool_names', 'tools']` — `chat_brief`가 프롬프트 변수에 없으며 `base_agent.py:75`가 도구 반환값을 버림을 확인 | **실행 확인 완료 (`CONFIRMED BUG`)** |
| **검증 4** | 상담 완료 시 `os.path.basename` `NameError` (`EVT-020`, `EVT-021`) | `import ai_legal_helper.api.routes.consultation as m; hasattr(m, 'os')` | `False` (`consultation.py`에 `import os` 누락, 147·217·221행 호출 시 `NameError` 발생 확정) | **실행 확인 완료 (`CONFIRMED BUG`)** |
| **검증 5** | 증거 모순 탐지 `GraphRAG` 임포트 오류 (`EVT-024`) | `from ai_legal_helper.rag.graph_rag import GraphRAG` | `ImportError: cannot import name 'GraphRAG' from 'ai_legal_helper.rag.graph_rag'` | **실행 확인 완료 (`CONFIRMED BUG`)** |
| **검증 6** | Python Editable 패키지 경로 불일치 (`EVT-001`) | 루트에서 `PYTHONPATH` 없이 `import ai_legal_helper.database.session` 실행 | 과거 `src/`가 `backend/src/`로 이동된 후 editable hook이 갱신되지 않아 `PYTHONPATH=backend/src` 없이는 `ModuleNotFoundError` 발생 | **실행 확인 완료 (`CONFIRMED ENV ISSUE`)** |

