# AI Legal Helper — 문서·소스코드 2차 검토 보고서

- 검토일: 2026-10-13, Asia/Seoul
- 검토 대상: C:/myprjs/ai-legal-helper의 현재 작업 트리
- 기준 커밋: 7cbe9363c1b68131d8ae421a89d5e0a9425315f3
- 목적: 개발 인수인계, 산출물과 구현의 일치 여부 재검토, ChatGPT 검토 자료 제공
- 작업 범위: 읽기·정적 분석·격리 재현·기존 단위 테스트·이 보고서 작성
- 변경 범위: 이 Markdown 보고서만 신규 작성. 제품 소스코드, 설정, 기존 문서, 기존 테스트는 수정하지 않음.
- 전달 상태: ChatGPT에 첨부할 문서 준비. 연결된 Codex 문서 세션이 없어 자동 전송은 수행하지 않음.

## 1. 검토 결론

React/TypeScript, FastAPI, Python/LangGraph 중심의 통합 제품 골격과 P3.6까지의 단계별 구현 파일은 존재한다. 그러나 코드의 존재를 기능 완성과 동일하게 볼 수 없다. 핵심 데이터 흐름, 인증 경계, 검증 상태, 상담 영속성, 재생성 시 데이터 보존, 배포 설정에서 산출물과 다른 동작이 확인되었다.

현재 상태에 대한 판정은 **개발 재개를 위한 구조 파악 완료 / 제품 전체 완료·출시 준비 판정 보류**다. 이 판정은 코드 검토자의 의견이며, 기존 완료보고서나 승인 상태를 변경한 것은 아니다.

특히 다음 문제가 우선이다.

1. 기본 인증 우회와 증거 Claim의 객체별 권한 검사 누락.
2. Langfuse 공식 콜백·Trace 메타데이터·OpenTelemetry 예외에 대한 원문 수집 통제 누락.
3. 전문 Agent 프롬프트에서 검색 결과와 사건 맥락이 빠지는 문제.
4. 법률 검증 오류 및 문서 생성 오류를 PASS로 처리하는 문제.
5. 실제 사용 경로의 회원가입 필드 불일치, 사건 상세 ORM 변환 실패, 상담 출처 처리 오류.
6. 상담 테이블 마이그레이션 누락, 증거 승인·반려와 Fact 상태 불일치, 기존 Action 삭제.
7. 벤치마크의 일반 DB 테이블 삭제 경로 및 배포 재현성 문제.

기존 단위 테스트와 TypeScript 검사는 통과했지만, 위 문제 상당수는 그 테스트의 검증 범위 밖이다. 이번 검토에서 법률 답변 정확도, 실제 사용자 E2E, Docker 기동, Langfuse 대시보드 조회를 완료했다고 주장하지 않는다.

## 2. 조사 범위와 판정 용어

### 2.1 조사 범위

보고서 생성 전 파일 목록 기준:

| 대상 | 수량 또는 범위 | 검토 방법 |
|---|---|---|
| Markdown | 161개 | 재귀 목록, 기준·지시·설계·완료 문서 대조, 상대 링크·지정 산출물 검사 |
| Python | 85개 | 제품·테스트·마이그레이션·스크립트·scratch 포함 구문 검사 및 핵심 실행 경로 재검토 |
| TypeScript/TSX | 26개 | API 계약·컴포넌트·Hook·라우팅·타입 설정 대조, TypeScript 검사 |
| 운영 설정 | Dockerfiles, Compose, 환경변수 예제, 패키지 선언, Windows 스크립트 | 현재 파일의 설정·호출 순서 정적 검사 |
| 로컬 저장소 | data, storage, vectorstore | 이전 조사에서 SQLite 읽기 전용 구조 확인 및 파일 인벤토리 조사. 실제 상담 원문은 보고서에 복제하지 않음 |
| 설치 SDK | 필요한 Langfuse/OTel 코드와 설치 버전 | 원문 수집·예외 이벤트 동작 확인을 위한 제한적 검사 |

.git 내부, 가상환경 전체, node_modules 전체, 캐시, 빌드 출력 전체를 제품 소스로 간주해 전수 검증한 것은 아니다. 모든 업무 기능의 실제 E2E를 실행한 것도 아니다. 이 보고서는 1차 전체 구조 조사 이후 핵심 지적을 다시 읽고 재현한 **2차 정적·격리 검토**다.

검토 시작 시 이미 수정·삭제·미추적 파일이 있었다. 보고서는 커밋된 원본만이 아니라 그 변경을 포함한 현재 파일을 대상으로 한다. 기존 변경은 되돌리거나 정리하지 않았다.

### 2.2 판정 용어

| 표기 | 의미 |
|---|---|
| 재현 확인 | 가짜 LLM/DB/SDK 또는 메모리 SQLite로 해당 동작을 직접 확인 |
| 정적 확인 | 현재 코드·문서·설정에서 동작 또는 누락을 확인. 실제 인프라 전체 실행은 하지 않음 |
| 추가 검증 필요 | 실제 PostgreSQL, Docker, 브라우저, SDK 서버 또는 법률 평가 데이터가 필요 |

심각도는 검토 의견이다. CRITICAL은 데이터 접근·원문 노출·기존 DB 삭제와 관련된 경로, HIGH는 핵심 기능·검증·데이터 보존 문제, MEDIUM은 통합·운영·상태·추적·문서 정합성 문제, LOW는 주로 링크·경로 정리 문제를 뜻한다. 실제 악용이나 실제 개인정보 유출이 있었다는 뜻은 아니다.

격리 재현에서는 일부 함수의 AOP decorator와 HTTP 의존성 주입을 제외하고 실제 함수 본문을 실행했다. 따라서 그 결과를 HTTP 공격 성공, 운영 DB 손상 또는 실제 외부 전송 성공으로 확대 해석하지 않는다.

## 3. 개발자가 알아야 할 현재 구조

| 영역 | 주요 구현 경로 | 현재 역할 |
|---|---|---|
| React UI | frontend/src/App.tsx, pages/CaseWorkspace.tsx | 사건별 개요·상담·사실·증거·그래프·대응·문서 탭 |
| API 진입점 | src/ai_legal_helper/api/main.py | 라우터 등록, 예외 처리, 상태 점검, 그래프 Worker 시작 |
| 인증 | api/dependencies.py, api/routes/auth.py | 쿠키 세션, 사용자 조회, 사건 소유권 검사, 로컬 우회 |
| 사건 정보 | case_intelligence/manager.py, extractor.py, timeline.py | 진술 추출·사실 저장·타임라인 재구축·변경 이력 |
| 증거 정보 | evidence_ingestion.py, evidence_extractor.py, evidence_manager.py | 파일 저장·원문 위치 추출·Claim 후보·검토·Fact 반영 |
| 상담 | workflows/legal_workflow.py, agents/* | 분야 선택·병렬 전문 분석·종합·검증·최대 1회 재검토 |
| 법률 검색 | rag/retrieval.py, retrieval_factory.py, query_rewrite.py | 분야별 law_docs_* 컬렉션 검색과 출처 수집 |
| 사건 검색 | rag/evidence_vector.py, graph_rag.py | case_evidence 벡터 검색, Neo4j 관계 탐색, 경로 실존 확인 |
| 그래프 동기화 | database/graph_sync.py, graph_sync_worker.py | PostgreSQL 스냅샷을 Neo4j/Chroma 파생 저장소로 반영 |
| 대응 계획 | agents/action_planner.py, deadline_engine.py, case_intelligence/action_service.py | 행동·요건·의존성·기한 생성 및 저장 |
| 법률 문서 | workflows/document_workflow.py, api/routes/documents.py, document_exporter.py | 구조화 초안, Revision 1 저장, DOCX/PDF 출력 |
| 영속 저장 | database/models.py, session.py, alembic/versions | 27개 ORM 클래스, 7개 마이그레이션 |
| 관측성 | observability/*, llm/gateway.py, llm/usage.py | AOP·ContextVar·OTel·토큰 추적·선택적 Langfuse |

제품 실행 경로는 외부 ai-legal-agent 어댑터에 의존하지 않는다. ui/app.py는 P0 Streamlit 로그 확인용 골격이며 현재 React 제품의 주 화면이 아니다. 기존 SQLite와 vectorstore 폴더의 존재 자체는 현재 PostgreSQL 전환의 실패를 뜻하지 않는다.

## 4. 재현된 문제와 중요한 정책 불일치

### R01. 기본 인증 우회 — CRITICAL / 재현·정적 확인

- 코드: src/ai_legal_helper/api/dependencies.py:13-14, 32-44, 55-59; api/routes/cases.py:53-60.
- 사실: AUTH_BYPASS가 명시되지 않고 TESTING=1이 아니면 우회가 활성화된다. 우회 중에는 전체 사건 목록을 조회하고 사건 소유자가 달라도 접근을 허용한다. 인증된 사용자도 이 우회 분기의 영향을 받는다.
- 산출물: docs/evaluation/P3_4_COMPLETION_REPORT.md:9의 비로그인·타인 접근 차단 완료 주장과 기본 실행 정책이 일치하지 않는다.
- 재확인: 설정식만 격리 평가했을 때 기본값은 true였다. 로컬 1인 테스트를 위한 의도된 기능이라는 주석은 존재한다. 따라서 우회 기능의 존재 자체보다 **안전한 기본값·활성 조건과 보안 완료 주장**이 문제다. 실제 실행 모드의 배포 보안 검증은 별도다.
- 후속 검증 기준: 우회를 명시적으로 켠 로컬 모드와 일반 모드를 구분하고, 일반 모드에서 401/403 및 사건 목록 격리를 검사할 것.

### R02. 증거 Claim과 URL의 문서·사건 연결 검사 누락 — CRITICAL / 격리 재현·정적 확인

- 코드: api/routes/evidence.py:295-301; case_intelligence/evidence_manager.py:35-39.
- 사실: 라우트는 evidence_id의 사건 소유권만 확인하고 claim_id의 소속을 대조하지 않는다. 서비스는 claim_id만으로 Claim과 그 사건을 조회한다.
- 재현: 소유한 사건·문서 객체와 다른 사건을 의미하는 합성 Claim ID를 전달하자 서비스 호출까지 그대로 전달되었다. 실제 HTTP 세션 공격이나 다른 사용자의 DB 변경을 실행한 것은 아니다.
- 영향: AUTH_BYPASS=false여도 객체 ID 교차 참조를 차단하는 코드가 없다. P3.4의 모든 비즈니스 엔드포인트 접근 통제 완료 주장을 재검토해야 한다.
- 후속 검증 기준: claim.case_id, claim.evidence_id, URL case_id/evidence_id를 함께 확인하고 교차 문서·교차 사건 요청을 거부할 것.

### R03. 원문 미수집 정책과 실제 관측성 경로 충돌 — CRITICAL / 격리 재현·정적 확인

- 코드: llm/gateway.py:48-51; observability/langfuse_client.py:137-156; api/routes/consultation.py:99-104; observability/decorators.py:171, 218; observability/callbacks.py:109, 122.
- 산출물: docs/development/P3_6_ISSUE_RESOLUTION.md:9-11, docs/architecture/P3_6_OBSERVABILITY_ARCHITECTURE.md:18-21은 공식 콜백 배제 및 원문 미수집을 설명한다.
- 사실: Gateway는 공식 Langfuse CallbackHandler를 등록한다. 프로젝트의 LANGFUSE_CAPTURE_CONTENT=false는 공식 콜백 생성 인자에 마스킹 함수로 연결되지 않는다. 설치 SDK에서 입력·출력 원문 기록 경로도 확인했다. 수동 Trace에는 질문 앞 120자와 원래 사건 ID가 전달된다.
- 재현: 가짜 콜백 생성자로 전달 인자를 검사했을 때 mask 인자가 없었다. OTel InMemorySpanExporter에서 기존 합성 오류 테스트를 실행했을 때 원래 예외 문자열의 합성 비밀값이 이벤트에 남았고, 예외 이벤트는 2개였다.
- 한계: 실제 사용자 데이터나 실제 Langfuse 서버로 전송하지 않았다. **외부 유출 이력이 확인된 것은 아니며, 미수집을 보장하지 못하는 코드와 OTel의 비마스킹 동작이 확인된 것**이다.
- 후속 검증 기준: Langfuse 콜백·수동 Trace·일반 로그·OTel 이벤트 전체에 합성 원문을 넣어 수집 대상에서 배제되는지 검사할 것.

### R04. 벤치마크가 일반 DATABASE_URL의 테이블을 삭제할 수 있음 — CRITICAL / 정적 확인

- 코드: scripts/run_p2_5_benchmark.py:8, 10, 22-23; database/session.py:19-22.
- 사실: ENV=test만 설정한 뒤 일반 SessionLocal/engine을 사용한다. 세션 모듈에는 ENV에 따라 TEST_DATABASE_URL로 전환하는 코드가 없다. setup_benchmark_data는 그 엔진에 drop_all()을 호출한다.
- 산출물: docs/evaluation/P2_5_TEST_REPORT.md:10의 ENV=test에 의한 DB 격리 설명과 다르다.
- 한계: 스크립트는 실행하지 않았고 DB를 삭제하지 않았다. DATABASE_URL이 별도로 테스트 DB를 가리키면 그 DB가 대상이지만, 스크립트 자체가 이를 보장하지 않는다.
- 후속 검증 기준: 테스트 DB 선택·대상 검증·기존 데이터 보호를 먼저 확인한 뒤 벤치마크를 실행할 것.

### R05. 전문 Agent 프롬프트의 검색 결과·사건 맥락 누락 — HIGH / 재현 확인

- 코드: agents/legal/base_agent.py:19-39, 47-92; agents/specialist.py:83; workflows/legal_workflow.py:209-211.
- 사실: 자체 Mock AgentExecutor가 제품 경로에 사용된다. 도구를 호출하지만 반환 텍스트를 프롬프트에 넣지 않는다. 실제 REACT_TEMPLATE에 chat_brief도 없다. create_react_agent는 LLM Agent를 생성하지 않고 프롬프트만 반환한다.
- 재현: 현재 PromptTemplate과 Executor 본문으로 모델 입력을 수집했을 때 합성 검색 표식과 합성 사건 맥락 표식 모두 없었다.
- 산출물: docs/evaluation/P2_2_COMPLETION_REPORT.md:31-33의 전문 Agent 사건 맥락 주입, 통합 엔진의 RAG 근거 기반 분석 설명과 충돌한다.
- 영향: ContextVar에 출처가 수집됐다는 사실과 실제 답변 생성에 그 근거가 사용됐다는 사실을 구분해야 한다. max_iterations/max_execution_time 인자도 현재 자체 Executor가 실행 제한에 사용하지 않는다.

### R06. 법률 검증 오류를 PASS로 반환 — HIGH / 재현 확인

- 코드: agents/verification.py:57-82, 123-168; workflows/legal_workflow.py:332-346.
- 사실: JSON 파싱·응답 모델 검증 실패가 PASS fallback으로 이어진다. 프롬프트에는 JSON 출력 스키마가 없고 case_context 변수도 템플릿에 들어 있지 않다. 상태와 grounding_status는 enum이 아닌 자유 문자열이다.
- 재현: 가짜 모델이 JSON이 아닌 합성 문자열을 반환했을 때 status=PASS였다.
- 문서 관계: docs/architecture/P2_1_VERIFICATION_DESIGN.md:42에도 PASS fallback이 명시되어 있다. 코드만의 문서 미준수가 아니라 해당 설계가 AGENTS.md 및 주석 표준의 미검증 PASS 금지 원칙과 충돌한다.
- 후속 검증 기준: 파싱 실패·모델 실패·출처 없음·존재하지 않는 출처 ID를 성공과 구분하고 UI에 검증 한계를 표시할 것.

### R07. 생성 실패한 문서도 검증 PASS — HIGH / 재현 확인

- 코드: workflows/document_workflow.py:80-85, 103-121, 127-151.
- 사실: 필수 정보는 수신인/임대인 단어 포함 여부로 판단한다. requirements_met=true이면 실제 사실·이름·날짜·법률 근거 대조 없이 PASS를 부여한다.
- 재현: draft_content가 '생성 오류 발생'인 상태도 verification_status=PASS였다. 그 상태는 review_gate의 저장 조건을 통과할 수 있다.
- 산출물: docs/evaluation/P3_5_FEATURE_INVENTORY.md:19의 Document Verification 구현 완료 및 P3.2 검증 설계와 실제 범위를 구분해야 한다.

### R08. 승인·검증 상태 없이 문서 Export 가능 — HIGH / 정적 확인

- 코드: api/routes/documents.py:66-114; frontend/src/components/DocumentSection.tsx:87-88.
- 사실: Export는 문서와 현재 Revision 존재 여부만 확인한다. DocumentReview 승인, 문서 status, Revision verification_status 확인이 없다.
- 산출물: docs/adr/P3_2_DOCUMENT_DESIGN_DECISIONS.md:21-23은 명시적 사용자 승인 후 Export만 허용한다고 설명한다.
- 구분: 현재 소유권 dependency와 FileResponse 자체는 존재한다. 승인 게이트를 구현하지 않은 문제를 '모든 다운로드 권한 검사가 없다'로 확대하지 않는다.

### R09. 문서 수정·버전·근거 관리가 테이블 선언에 머묾 — HIGH / 정적 확인

- 코드: workflows/document_workflow.py:130-151; api/routes/documents.py 전체; api/schemas/document.py:71-75.
- 사실: 새 생성마다 새 LegalDocument와 revision_number=1을 만든다. 기존 문서를 수정·승인·재생성하는 라우트가 없고 DocumentSourceLink/DocumentReview 생성 경로도 없다. 요청 title은 실제 생성 상태에 반영되지 않는다.
- 산출물: P3.2 ADR의 매 수정마다 새 Revision 보존 및 P3.5 기능 인벤토리의 문서 버전 관리 완료와 차이가 있다.
- 구분: Revision 테이블과 초안 저장은 구현되어 있다. 이를 전체 수정 이력 기능 완료로 볼 수 없다는 의미다.

### R10. 중첩 ORM 객체의 사건 상세 응답 변환 실패 — HIGH / 재현 확인

- 코드: api/schemas/case.py:12-42, 44-61.
- 사실: CaseSchema에는 from_attributes가 있지만 Party/Fact/Event/LegalIssue에는 없다.
- 재현: DB 연결 없이 실제 Case ORM 객체에 Fact ORM 객체를 넣고 CaseDetailSchema.model_validate를 호출하자 facts[0]에서 model_type 오류가 발생했다.
- 한계: 전체 HTTP 서버를 띄운 재현은 아니다. 실제 엔드포인트가 반환하는 ORM 객체를 현재 응답 스키마에 대입한 재현이다. 빈 사건 조회만으로 이 문제를 검증할 수 없다.

### R11. 회원가입·로그인 API 계약 불일치 — HIGH / 재현·정적 확인

- 코드: frontend/src/api/authClient.ts:3-7, 10-31; frontend/src/context/AuthContext.tsx:39-48; api/routes/auth.py:18-31, 98.
- 사실: 프론트엔드는 name을 보내고 백엔드는 display_name을 필수로 요구한다. 프론트엔드는 로그인 결과를 User로 취급하지만 API는 message 객체를 반환한다. User의 name/role과 백엔드의 display_name/status도 다르다.
- 재현: 프론트엔드 형태의 합성 회원가입 payload를 현재 UserCreate에 입력하면 display_name missing 오류가 발생했다. HTTP 422는 해당 스키마 사용에서 예상되는 결과이며 실제 브라우저 요청은 실행하지 않았다.
- 산출물: P3.4/P3.5의 React 인증 연동 완료 주장은 API 단독 테스트와 구분해야 한다.

### R12. 상담의 출처 처리에서 os import 누락 — HIGH / 재현 확인

- 코드: api/routes/consultation.py:19-37, 142-147, 213-218.
- 사실: os.path.basename을 호출하지만 모듈에 os import가 없다.
- 재현: 가짜 상담 워크플로우가 출처 1건을 반환했을 때 process_consultation 본문은 ERROR 상태로 바뀌었고 os 이름 미정의 오류가 경고에 남았다.
- 구분: 출처가 빈 배열인 경로는 해당 list comprehension 본문을 실행하지 않아 문제를 숨길 수 있다. 사건별 상담 목록의 Source(**s) 경로까지 모두 같은 NameError라고 주장하지 않는다.

### R13. 상담 테이블의 마이그레이션 누락·저장 오류 은폐 — HIGH / 정적 확인

- 코드: database/models.py:515-542; alembic/versions의 7개 파일; api/routes/consultation.py:72-85, 166-182.
- 사실: ORM에 consultations가 있으나 마이그레이션의 create_table에는 없다. 저장 실패 시 rollback 또는 pass만 수행한다. usage_summary/revision_count 저장 필드도 없어 DB 복원 응답에서 전체 실행 메타데이터가 복원되지 않는다.
- 구분: Base.metadata.create_all이나 기존 수동 초기화로 테이블이 이미 있을 가능성은 있다. 실제 운영 DB의 테이블 부재를 확인한 것이 아니라 **Alembic에 의한 새 환경 재현 경로의 누락**을 확인했다.
- 후속 검증 기준: 비어 있는 별도 DB에 Alembic만 적용한 뒤 상담 저장·재시작 조회·메타데이터 복원을 검증할 것.

### R14. 반복 승인·반려 후 Fact 상태 불일치 — HIGH / 재현 확인

- 코드: case_intelligence/evidence_manager.py:44-58, 85-107.
- 사실: 승인/수정마다 새 VERIFIED Fact를 만든다. 기존 승인 여부 확인·Fact 재사용·반려 후 기존 Fact 무효화가 없다. assertion_status의 AI_INFERENCE/PARTY_ALLEGES와 Fact의 VERIFIED 관계도 별도 검증 없이 승격된다.
- 재현: 메모리 SQLite에서 APPROVE → APPROVE → REJECT를 실행한 뒤 Claim은 REJECTED지만 Fact는 2개이며 둘 다 VERIFIED였다.
- 한계: PostgreSQL 동시성/잠금 검증은 아니다. 순차 검토의 멱등성·논리 상태 재현이다.

### R15. 빈 행동 계획이 기존 Action을 삭제 — HIGH / 재현 확인

- 코드: case_intelligence/action_service.py:73-80, 138-150; agents/action_planner.py:111-114.
- 사실: 계획 응답 확인 뒤 기존 Action을 일괄 삭제하며, Planner는 호출 오류 시 빈 actions를 반환한다. 계획과 Revision 저장도 두 번의 commit으로 나뉜다.
- 재현: 메모리 DB에 COMPLETED Action을 만든 뒤 가짜 Planner가 빈 배열을 반환하도록 하자 기존 Action 수가 0이 되었다.
- 산출물: docs/adr/P3_1_ACTION_PLANNER_DECISIONS.md:34-35의 재평가 때 행동 이력·상태 보존 설명과 다르다.
- 구분: 빈 배열이 유효한 새 계획인지 생성 실패인지를 현재 계약이 구분하지 않는다. PostgreSQL의 연관 문서/외래 키 영향은 추가 검증이 필요하다.

### R16. Neo4j 장애의 벡터 fallback이 호출부에서 차단 — HIGH / 재현·정적 확인

- 코드: workflows/legal_workflow.py:165-168; api/routes/graph.py:92-95; rag/graph_rag.py:244-260.
- 사실: GraphRAGRetriever.search_hybrid에는 driver=None 벡터 fallback이 있지만 상담과 검색 API는 driver가 없으면 그 함수 호출 전에 반환한다.
- 재현: Neo4j driver=None으로 상담의 _collect_graph_evidence를 호출했을 때 search_hybrid 호출은 없었고 vector_matches 키도 없는 기본 결과였다.
- 산출물: docs/evaluation/P2_5_BASELINE_VS_GRAPHRAG.md:45-48의 Supervisor로 벡터 결과 전달 완료와 다르다.
- 구분: 그래프 장애 때 법령 RAG나 나머지 화면을 계속 처리하는 fallback과 사건 증거 벡터 fallback은 서로 다른 기능이다.

### R17. Action 생성 후 그래프 동기화 작업이 커밋되지 않음 — HIGH / 2차 추가 재현

- 코드: api/routes/cases.py:122-126; database/graph_sync_worker.py:79-85; database/session.py:31, 42-46.
- 사실: audit commit 후 queue_sync_task를 호출하고 바로 반환한다. queue_sync_task는 db.add만 수행한다. 요청 세션은 autoflush=false이며 종료 시 닫힌다.
- 재현: 같은 세션 설정의 메모리 DB에서 해당 라우트 본문을 실행하자 세션에는 새 작업 1개가 있었지만 세션을 닫고 새 세션에서 조회한 저장 작업 수는 0이었다.
- 산출물: P3.1의 Action 그래프 반영 및 P2.5의 트랜잭션 내 Outbox 보장 설명과 차이가 있다.

## 5. 배포·통합·운영의 정적 확인 사항

| ID | 심각도 | 문제·근거 | 검증 수준과 범위 |
|---|---|---|---|
| R18 | HIGH | Dockerfile.api:18-23은 pyproject만 복사한 상태에서 editable install을 한다. pyproject.toml:9, 46-47은 README와 src 패키지를 요구하지만 설치 시점에 없고 README COPY도 없다. | 정적 확인. Docker 빌드 실패 로그를 획득한 것은 아니며 깨끗한 환경 빌드가 추가로 필요하다. |
| R19 | LOW / 1차 판정 정정 | Compose:72 및 .env.example:16-17은 postgresql://를 사용한다. 코드의 fallback은 postgresql+psycopg://이며 SQLAlchemy 버전은 >=2.0으로 넓게 선언되어 있다. | 현재 설치된 SQLAlchemy 2.1.4의 make_url(...).get_dialect().driver를 실제 검사한 결과 두 URL 모두 psycopg였다. 따라서 로컬 psycopg2 미설치만으로 현재 DB 연결 실패를 주장한 1차 판단은 철회한다. 다른 설치 버전·깨끗한 Docker 환경의 드라이버 선택은 별도 확인 대상이다. |
| R20 | HIGH | pyproject에는 직접 import하는 langchain-chroma가 없고, filetype와 EmailStr용 email-validator는 두 의존성 파일 모두 명시하지 않는다. dateutil도 직접 선언이 없다. requirements의 Langfuse는 상한이 없지만 pyproject는 <3이다. | 선언 불일치 정적 확인. 현재 로컬에 설치된 일부 패키지/전이 의존성이 이를 가릴 수 있어 모든 항목을 현재 import 실패로 주장하지 않는다. |
| R21 | MEDIUM | Compose:81은 AZURE_OPENAI_DEPLOYMENT를 전달하지만 Gateway:44는 AZURE_OPENAI_DEPLOYMENT_CHAT를 읽는다. LANGFUSE_ENABLED/키는 빈 값으로 지정되고 LANGFUSE_ENVIRONMENT는 JWT_SECRET_KEY를 참조한다. | 정적 확인. .env를 Docker 실행 변수로 모두 전달한다고 가정할 수 없다. 프로젝트의 .env를 변경하지 않았다. |
| R22 | MEDIUM | Dockerfile은 fonts-nanum을 설치하지만 document_exporter.py:51-56은 Windows malgun.ttf만 찾아 없으면 Helvetica를 사용한다. 본문 줄바꿈도 문자 폭 기준이 아니다. | Linux 한글 폰트 경로·렌더링 연결 누락 정적 확인. 실제 Linux PDF 생성·글리프 및 긴 문장 시각 검사는 미실행. |
| R23 | MEDIUM | frontend/src/App.tsx:40-45는 ProtectedRoute를 사용하지 않는다. 구현 파일은 있지만 현재 인증 보호 라우팅에 연결되지 않았다. | 정적 확인. 서버의 소유권 dependency가 없다는 뜻은 아니며 로컬 인증 생략 UI와 보안 산출물의 정책 차이다. |
| R24 | MEDIUM | api/routes/workflow.py:16-45는 행 개수만으로 상태를 정하며 pending_tasks=0을 고정한다. CaseWorkspace.tsx:103은 준비중이며 상태 API를 사용하지 않는다. summary/trigger API도 없다. | 정적 확인. P3.3 상태 API 기반 일부 구현은 인정하되 승인 상태·실행 상태·재분석 조건을 아우르는 Orchestrator 완료는 아니다. |
| R25 | MEDIUM | api/routes/evidence.py:180은 존재하지 않는 GraphRAG를 import한다. 실제 클래스는 GraphRAGRetriever다. 예외는 pass로 처리한다. | 정적 확인. RDB의 충돌 목록까지 모두 실패한다고 해석하면 안 된다. Neo4j 보강 부분이 실행되지 않는다. |
| R26 | MEDIUM | rag/graph_rag.py:249, 265는 import되지 않은 update_span/get_current_span_id를 호출하고 예외를 무시한다. | 정적 확인. P3.6 GraphRAG 메타데이터 UI 조회 완료 주장과 다르다. GraphRAG 검색 본체는 계속 진행될 수 있다. |
| R27 | MEDIUM | observability/decorators.py:45와 callbacks.py:80,116은 parent ID로 노드/Agent 이름을 사용한다. langfuse_client.py:228,293은 UUID 키의 active_spans에서 찾는다. 공식 콜백과 수동 Generation도 함께 있다. | 가짜 Trace에서 이름 parent를 전달하면 Span 생성이 없음을 재현. 중복 계측 경로는 확인했지만 실제 UI 중복 개수·비용 오차는 측정하지 않았다. |
| R28 | MEDIUM | graph_sync_worker.py:35-49는 PROCESSING으로 commit하고 해당 상태를 다시 조회/회수하지 않는다. | 정적 확인. P2_5_GRAPH_SYNC_RELIABILITY.md:19-21의 재시작 복구·관리자 재시도 기능이 현재 구현되지 않았다. 단순 재시도 자체는 존재한다. |
| R29 | MEDIUM | frontend/src/hooks/useConsultation.ts:49-65에서 interval을 지역 변수로 만들고 컴포넌트 해제 cleanup에 연결하지 않는다. 기존 IN_PROGRESS 이력 재개도 없다. | 정적 확인. 주석의 해제 시 폴링 정리와 다르다. 브라우저 타이머·중복 요청 재현은 미실행. |
| R30 | MEDIUM | ChatSection.tsx는 답변/출처를 표시하지만 verification_result/warnings를 표시하지 않는다. legal_workflow의 경고는 검증 결과 안에만 남을 수 있다. | 정적 확인. 근거 부족 문구가 붙는 일부 종료 경로는 있으나 모든 검증 오류가 사용자에게 보이는 것은 아니다. |
| R31 | MEDIUM | _consultations, global_token_tracker.records, _active_traces/_active_spans에 정리 정책이 없고 end_trace는 pass다. 여러 경로에서 동기 flush도 호출한다. | 메모리 보존·동기 호출 정적 확인. 실제 장시간 메모리 증가량이나 서버 장애 지연 시간은 측정하지 않았다. |
| R32 | MEDIUM | USER_TEST_GUIDE.md:42-44는 PNG 업로드·자동 타임라인 구성을 안내하지만 업로드 허용은 PDF/DOCX/TXT이며 승인 서비스는 Fact만 생성한다. | 정적 확인. 영상·사진 OCR/STT 기능의 구현 완료를 인정할 수 없다. 기존 TXT/PDF/DOCX 파서는 존재한다. |
| R33 | MEDIUM | frontend/src/api/apiFetch.ts:1은 localhost:8000을 고정하여 nginx의 /api 프록시를 사용하지 않는다. local-start는 API를 0.0.0.0에 바인딩한다. | 정적 확인. 현재 PC에서의 localhost 사용이 실패한다고 단정하지 않는다. 다른 호스트 접속·일반 배포·기본 인증 우회와의 조합은 추가 검증 대상이다. |
| R34 | MEDIUM | P3.6 지시서의 평가 결과 기록·비용/샘플링·관리자 진단 UI/접근제한에 대응하는 구현을 해당 관측성·UI 경로에서 확인하지 못했다. | 미구현 또는 별도 증빙 필요로 분류. 실제 법률 정확도와 합성 기술 테스트, 내부 Verification 통과율을 구분해야 한다. |

## 6. 추가 관찰: 오류·파일·객체 정합성

아래는 1차 보고의 핵심 결론에 추가되는 정적 관찰이며 실제 공격·업로드·운영 파일 변경을 실행하지 않았다.

- **문서의 action_id 교차 사건 참조**: documents.py:27-30은 action_id의 case_id를 조회해 대조하지 않는다. FK 실존 확인과 같은 사건 소속 확인은 다르다. 실제 PostgreSQL/API 검증을 추가해야 한다.
- **반출 파일 경로 응답**: FileResponse 자체는 존재하지만 api/schemas/document.py:25-29, 46은 file_path를 nested exports에 포함한다. 생성된 Export 기록이 문서 조회 응답으로 직렬화되면 내부 경로가 노출될 수 있다. 실제 HTTP 응답 확인은 미실행이다.
- **업로드 크기 오류 상태**: evidence_ingestion.py:79-85에서 10MB 초과 HTTPException(400)을 넓은 except가 다시 HTTPException(500)으로 바꾼다.
- **시그니처 검증 한계**: evidence_ingestion.py:88-93은 인식 불가 파일을 text/plain으로 보고, text/plain은 허용 목록에 있다. 확장자와 파일 시그니처의 일치를 충분히 보장하지 않는다. 잘못된 PDF/DOCX나 위장 파일 업로드 검증이 필요하다.
- **KST 일괄 보정의 재실행**: scripts/migrate_to_kst.py:23-27은 모든 대상 타임스탬프에 매번 9시간을 더한다. 재실행 이력이나 UTC/KST 판별 조건이 없다. 이를 자동 실행하거나 실제 DB에 재적용하지 않았다.
- **권한 오류의 500 변환**: evidence.py:295-316의 넓은 except는 함수 내부 404 HTTPException도 500으로 변환할 수 있다. 명세의 400/404/409/500 구분과 함께 재검증해야 한다.

## 7. 문서·산출물 정합성

### 7.1 현재 완료 주장을 그대로 유지하기 어려운 문서

| 문서 | 재검토할 주장 | 관련 문제 |
|---|---|---|
| docs/evaluation/P2_2_COMPLETION_REPORT.md | 전문 Agent에 사건 맥락 전달, 전체 기능 달성 | R05, R10 |
| docs/evaluation/P2_3_COMPLETION_REPORT.md | 증거 검토·검증 근거 편입 및 E2E 안정성 | R02, R05, R06, R14 |
| docs/evaluation/P2_5_COMPLETION_REPORT.md | 장애 fallback·동기화·벤치마크 완료 | R04, R16, R17, R28 |
| docs/evaluation/P2_5_BASELINE_VS_GRAPHRAG.md | Supervisor 벡터 fallback, 정량 우위·환각 감소 | R16, 정량 증빙 범위 |
| docs/evaluation/P3_1_COMPLETION_REPORT.md | 요구사항 전체 충족, Action 상태·그래프 저장 | R15, R17 |
| docs/evaluation/P3_2_COMPLETION_REPORT.md | 문서 생성·검토·버전 관리 구현·검증 | R07-R09 |
| docs/evaluation/P3_4_COMPLETION_REPORT.md | 모든 보안 요구 충족·주석 100% 준수 | R01-R03, R11, R23, 주석 적용 범위 |
| docs/evaluation/P3_5_RELEASE_READINESS_REPORT.md | 원클릭 실행·React 연동·회귀 SUCCESS | R10-R13, R18-R22 |
| docs/evaluation/P3_6_COMPLETION_REPORT.md, P3_6_TEST_REPORT.md | 원문 미수집·계층 추적·GraphRAG 계측·100% 충족 | R03, R26-R27, R31, R34 |

과거에 해당 문서 작성 시점의 코드나 환경에서 테스트가 통과했을 가능성을 부정하는 보고서가 아니다. **현재 작업 트리에서 그 결론을 재사용할 충분한 증빙이 없고, 직접 충돌하는 코드가 있다**는 판정이다.

### 7.2 실제 깨진 Markdown 상대 링크

README.md에서 두 링크의 대상 파일이 없다.

1. docs/instructions/P3_2_DOCUMENT_INTELLIGENCE_INSTRUCTION_v1.0.md
2. docs/instructions/P3_5_E2E_SERVICE_COMPLETION_INSTRUCTION_v1.0.md

P3.2의 실제 지시서 이름은 P3_2_LEGAL_DOCUMENT_INTELLIGENCE_INSTRUCTION_v1.0.md다. P3.5는 다른 이름의 지시서를 확인하지 못했다.

### 7.3 지시서가 지정한 경로에 없는 산출물

| 지시서 | 지정 경로 | 확인 결과 |
|---|---|---|
| P2.3 | docs/architecture/P2_3_EVIDENCE_ARCHITECTURE.md | 없음 |
| P2.3 | docs/architecture/P2_3_EVIDENCE_DATA_MODEL.md | 없음 |
| P2.3 | docs/architecture/P2_3_PROVENANCE_AND_SECURITY.md | 없음 |
| P2.3 | docs/adr/ADR-007-EVIDENCE-STORAGE-AND-PROVENANCE.md | 없음 |
| P2.3 | docs/development/P2_3_IMPLEMENTATION_LOG.md | 없음 |
| P2.3 | docs/development/P2_3_ISSUE_RESOLUTION.md | 없음 |
| P2.3 | docs/evaluation/P2_3_TEST_REPORT.md | 없음 |
| P3.2 | docs/development/P3_2_IMPLEMENTATION_LOG.md | 같은 이름이 docs/logs에 있음 |
| P3.2 | docs/development/P3_2_ISSUE_RESOLUTION.md | 같은 이름이 docs/logs에 있음 |
| P3.4 | docs/evaluation/P3_4_TEST_REPORT.md | 같은 이름이 docs/development에 있음 |
| P3.4 | docs/evaluation/P3_4_MASTER_QA.md | 같은 이름이 docs/development에 있음 |

P3.6 완료보고서가 기재한 utils/context.py, utils/decorators.py는 실제 observability/context.py, observability/decorators.py와 다르다. ADR은 docs/adr, 설치 가이드는 docs/user에 있지만 보고서는 다른 폴더를 기재한다. docs/adr에는 ADR-007 이름을 공유하는 서로 다른 결정 문서도 있다.

### 7.4 기준 문서의 현재성·Phase 의미

- docs/.gpt/AI_Legal_Helper_Development_Baseline_v1.1.md:55와 MASTER_INDEX:282는 IMPLEMENTATION: NOT STARTED다. 현재 코드·완료 문서가 존재하므로 현재 상태 인덱스로는 오래된 내용이다.
- .gpt의 P0-P10과 현재 지시서의 P0-P3.6은 Phase 이름과 의미가 다르다. 예를 들어 초기 P4 Playbook과 현재 문서의 P4 사용자 테스트를 같은 승인 단계로 볼 수 없다.
- pgvector 중심 초기안과 이후 Chroma/Neo4j의 차이는 후속 ADR·지시서에 따른 설계 변경일 수 있다. 단지 기술이 바뀌었다는 이유만으로 위반으로 판정하지 않는다.
- 개발 재개 전에 현재 적용되는 기준 문서·승인 이력·완료 범위를 한 인덱스에서 확정할 필요가 있다. 이 검토에서는 기존 기준 문서를 수정하거나 새 Phase를 승인하지 않았다.

### 7.5 주석 표준 준수 점검

src Python 파일 중 모듈 Docstring이 없는 파일은 22개다. 이 수치는 전체 주석 품질 점수가 아니며, 구형 P0 코드의 단계적 보강 원칙을 무시하고 모든 파일을 동일한 신규 위반으로 판정한 것도 아니다.

다만 P3에 추가된 auth.py, dependencies.py, documents.py, workflow.py, action/document 스키마 등 주요 모듈에 한국어 모듈 Docstring이 없다. 다수 핵심 함수에 Google 스타일 설명이 없고, 주요 React API·컴포넌트에 한국어 JSDoc도 없다. 따라서 P3.4의 모든 신규·수정 코드 100% 준수 주장은 현재 코드로 입증되지 않는다.

실제 동작과 다른 주석의 예:

- case_intelligence/manager.py:6은 SQLite 저장을 설명하지만 실제 세션은 PostgreSQL이다.
- useConsultation.ts는 컴포넌트 해제 시 interval 정리를 설명하지만 cleanup이 없다.
- 문서 verification_node의 이름·날짜 검증 설명에 실제 대조 로직이 없다.
- Langfuse 문서는 공식 콜백 배제와 current_span_id 기반 부모 연결을 설명하지만 실제 경로는 다르다.

이번 작업은 제품 소스코드를 새로 작성·수정하지 않았으므로 소스 주석 보강을 수행하지 않았다. 보고서에는 실제 검증 범위와 미검증 범위를 구분했고 비밀정보·개인정보·상담 원문을 기록하지 않았다.

## 8. 실제 실행한 검사

### 8.1 기존 테스트와 타입 검사

검사 환경은 Windows / Python 3.11.6이다. 로컬 설치 버전은 Pydantic 2.14.0, SQLAlchemy 2.1.4, LangChain 1.4.4, Langfuse 2.60.10, ChromaDB 1.5.9다. 이것은 이번 검사 환경의 기록이며 새 Docker 이미지의 설치 버전을 의미하지 않는다.

| 검사 | 실제 결과 | 해석 범위 |
|---|---|---|
| Python 85개 AST 검사 | 구문 오류 0개 | 문법 검사. import·API·DB·법률 정확도 검증 아님 |
| 기존 단위 테스트 3개 파일 | 15 passed, 1 warning, 0.72s | AOP·DeadlineEngine·TokenTracker 범위 |
| tsconfig.app.json 타입 검사 | exit code 0 | 앱 소스 정적 타입 검사 |
| tsconfig.node.json 타입 검사 | exit code 0 | Vite 설정 정적 타입 검사 |
| Markdown 상대 링크 검사 | 깨진 링크 2개 | 명시된 상대 링크 검사. 모든 plain-text 경로를 링크로 간주하지 않음 |
| ORM와 migration create_table 대조 | consultations 누락 | 실제 DB의 현재 스키마와는 별도 |
| PostgreSQL URL dialect 선택 | postgresql:// 및 postgresql+psycopg:// 모두 psycopg | 로컬 SQLAlchemy 2.1.4 기준. 실제 서버 연결을 수행한 검사가 아님 |

실행 명령은 다음과 같다. pytest는 bytecode와 pytest cache 생성을 막고 Langfuse를 비활성화했다.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:LANGFUSE_ENABLED='false'
.venv/Scripts/python.exe -B -m pytest tests/unit/test_aop.py tests/unit/test_deadline_engine.py tests/unit/test_llm_tracking.py -q -p no:cacheprovider
```

frontend 폴더에서:

```powershell
.\node_modules\.bin\tsc.cmd -p tsconfig.app.json --noEmit
.\node_modules\.bin\tsc.cmd -p tsconfig.node.json --noEmit
```

warning은 pythonjsonlogger.jsonlogger 경로의 DeprecationWarning 1개다. npm run build, Vite 번들 생성, 전체 pytest를 실행한 결과로 보고하지 않는다.

### 8.2 격리 재현의 결과

아래는 제품 기능의 PASS 목록이 아니라 **문제 동작을 재현한 진단 결과**다. 재현 스크립트는 셸 표준입력으로 실행했으며 제품 테스트 파일로 추가하지 않았다.

| 시나리오 | 결과 | 사용한 격리 방식 |
|---|---|---|
| 중첩 ORM 응답 | facts[0]: model_type | 실제 ORM·현재 Pydantic 스키마, DB 연결 없음 |
| 프론트 회원가입 payload | display_name: missing | 현재 UserCreate, 합성 데이터 |
| 전문 Agent 프롬프트 | 검색 표식 없음 / 사건 맥락 표식 없음 | 현재 템플릿·Executor, 가짜 LLM·Tool |
| 법률 검증의 비 JSON 응답 | PASS | 실제 프롬프트/파싱, 가짜 모델 |
| 생성 오류 문서 검증 | PASS | 현재 노드 본문, 합성 상태 |
| 출처가 있는 상담 | ERROR / os 이름 미정의 | 현재 함수 본문, 가짜 워크플로우·DB |
| 교차 문서 Claim 전달 | 서비스까지 전달됨 | 라우트 본문, 가짜 소유 문서·서비스 |
| 인증 우회 기본값 | true | 설정식만 격리 평가 |
| APPROVE → APPROVE → REJECT | Fact 2개, VERIFIED 2개, Claim REJECTED | 실제 서비스, 메모리 SQLite |
| 빈 계획 재생성 | 기존 Action 0개 | 실제 서비스, 가짜 Planner, 메모리 SQLite |
| 공식 Langfuse 콜백 | mask 인자 없음 | 가짜 콜백 생성자, 합성 설정 |
| 이름을 부모 ID로 Span 생성 | 생성 호출 없음 | 실제 wrapper, 가짜 Trace |
| OTel 예외 마스킹 | 합성 원문 비밀값 존재 / 이벤트 2개 | 기존 합성 오류 함수, InMemorySpanExporter |
| Action Outbox commit | 세션 내 pending 1개 / 종료 후 저장 0개 | 라우트 본문·실제 queue 함수, 메모리 SQLite |
| Neo4j 없음 상담 fallback | hybrid 호출 없음 / vector_matches 없음 | 현재 함수 본문, driver=None |

이 결과는 PostgreSQL 잠금·동시성·트랜잭션 격리 수준이나 실제 Azure/Langfuse 장애를 검증한 것이 아니다.

### 8.3 실행하지 않은 검사

- 전체 통합 테스트: 일부 import/fixture가 DB create_all/drop_all 및 전역 dependency override를 수행한다. conftest.py의 사용자 조회는 일반 SessionLocal을 사용하며 일부 테스트만 별도 테스트 엔진을 사용한다.
- 실제 LLM 호출: 일부 mock 이름의 테스트도 실제 Gateway를 호출한다. test_api.py는 상담 최종 상태에 ERROR도 허용하고 test_rag.py는 검색 결과가 비어 있지 않은지 검사하지 않는다.
- 실제 Docker 이미지 빌드·Compose up/down, 실제 PostgreSQL/Alembic 적용, Neo4j/Chroma 동기화.
- 실제 브라우저 회원가입부터 파일 다운로드까지의 E2E.
- 실제 Langfuse UI 조회·외부 서버의 원문 유무·수동/공식 Generation 중복 개수.
- 법률 주장 정확도, Precision/Recall, 환각 감소, 비용/지연 개선, 실제 사용자 만족도.

벤치마크는 질의별 결과를 출력하지만 현재 코드에서 정답셋 기반 Precision/Recall·지연시간·토큰 비용 비교 측정을 확인하지 못했다. 따라서 '압도적 우위', '환각 크게 감소', '가용성 항상 보장'은 이번 검토의 측정 결과가 아니다.

## 9. 1차 보고에서 정정·한정한 표현

1. 인증 우회는 의도된 로컬 기능임을 인정한다. 다만 기본 활성화와 보안 완료 주장 사이의 차이는 유지한다.
2. Docker는 정적 재현성 문제로 유지하고 실제 빌드 실패를 이번에 확인했다고 표현하지 않는다.
3. consultations migration 누락과 현재 DB에 실제 테이블이 없는 상태를 구분한다.
4. GraphRAG 검색기의 내부 fallback 존재와 상담/API 호출부의 fallback 미도달을 구분한다.
5. 원문 수집 경로와 실제 외부 개인정보 유출 이력을 구분한다. OTel 합성 원문 이벤트는 직접 확인했다.
6. 공식·수동 Langfuse 이중 계측 경로와 실제 토큰/비용 중복 합산 결과를 구분한다.
7. 모듈 Docstring 22개 누락을 모든 시점·모든 소스의 동일한 신규 위반으로 확대하지 않는다. 현재 P3의 100% 준수 주장과 직접 대조한다.
8. SQLite→PostgreSQL, pgvector 초기안→Chroma/Neo4j, 초기 Phase→현재 세부 단계 변화는 승인된 후속 변경일 수 있다. 이전 문서의 모든 차이를 버그로 분류하지 않는다.
9. **DB 드라이버에 관한 1차 판단을 정정한다.** 현재 SQLAlchemy 2.1.4는 postgresql://도 psycopg로 해석한다. psycopg2 미설치를 근거로 현재 연결 실패를 추론한 것은 해당 버전에서 맞지 않는다. R19는 현재 재현된 장애에서 제외하고 설치 버전·URL 재현성 확인 사항으로 낮춘다.
10. 이번에 새로 재현한 Action Outbox commit 누락은 R17에 별도 기록한다.

## 10. 개발 재개를 위한 권고 순서 — 구현 지시가 아님

1. 데이터 보호: R01-R04의 인증 정책·객체 권한·원문 수집·벤치마크 DB 대상을 먼저 확정한다.
2. 핵심 사용 경로: R10-R13의 사건 상세·회원가입·상담 출처·상담 migration을 정리한다.
3. 근거·검증: R05-R09의 검색/사건 맥락 전달, 검증 오류 상태, 문서 승인·수정·근거 링크를 검토한다.
4. 데이터 보존: R14-R17의 검토 멱등성·반려 무효화·Action 보존·Outbox/fallback을 검토한다.
5. 실행 재현: R18-R22를 깨끗한 환경에서 확인하고 별도 테스트 DB로 회귀를 수행한다.
6. 운영·문서 정합성: 나머지 상태·추적·폴링·가이드·산출물 경로·주석·현재 기준 문서를 정리한다.

각 단계에서 먼저 구체적인 수정 범위와 완료 기준을 합의하고, 구현·테스트·문서 갱신 결과를 분리해 제출하는 것이 적절하다. 이 보고서는 해당 수정의 수행, 새로운 개발 단계 진행, P4 승인 또는 배포 승인이 아니다.

## 11. ChatGPT에 전달할 요청문

다음 요청과 이 파일을 함께 전달하면 된다.

> 첨부한 AI Legal Helper 2차 검토 보고서를 검토해 주세요. 현재 작업 트리의 코드 근거, 기존 산출물 주장, 격리 재현 결과, 실제 인프라에서 아직 검증하지 않은 항목을 구분해 판단해 주세요. R01-R17을 먼저 검토하고, 각 문제의 우선순위·수정 범위·필수 회귀 테스트·완료 기준을 제안해 주세요. 정적 위험을 실제 장애나 유출 이력으로 확대하지 말고, 기존 PASS 문구만으로 완료를 인정하지 마세요. 초기 설계의 Phase와 현재 P3.6 이후 사용자 테스트 단계의 의미를 구분하고, 사용자 승인 없이 다음 단계나 코드 수정으로 진행하지 마세요.

이 파일에는 실제 인증키·인증토큰·사용자 개인정보·상담 원문을 포함하지 않았다. 연결된 ChatGPT 문서 세션이 없어 자동 전달 완료라고 보고하지 않는다.

## 12. 변경·검증 보존 기록

- 제품 소스코드 및 기존 문서·설정·테스트를 수정하지 않았다.
- 실제 운영/테스트 PostgreSQL·Neo4j·Chroma 데이터, 업로드 파일을 변경하지 않았다.
- 메모리 SQLite 데이터는 검증 프로세스 내에서만 생성하고 종료했다.
- 테스트는 bytecode·pytest cache 생성 없이 실행했고, 타입 검사는 noEmit으로 수행했다.
- 작업 시작 시점에 기록한 기존 검토 대상 파일 295개의 SHA-256을 마지막에 비교했다. 기존 파일 변경·삭제는 0개이며 추가된 파일은 이 보고서 1개뿐이다. 비교 대상은 제품 소스·테스트·문서·주요 설정/스크립트이며 Git 내부·설치 패키지·캐시 전체의 해시 비교는 아니다.
- 실제 검사하지 않은 항목을 완료 또는 PASS로 표현하지 않았다.
