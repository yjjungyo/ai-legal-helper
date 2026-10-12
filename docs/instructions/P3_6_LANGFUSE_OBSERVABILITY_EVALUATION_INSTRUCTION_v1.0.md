# AI Legal Helper — P3.6 Langfuse Observability & Evaluation Integration 개발지시서 v1.0

**프로젝트:** `C:\myprjs\ai-legal-helper`  
**단계:** P3.6 — Langfuse Observability & Evaluation Integration  
**목표:** Langfuse를 기존 AI Legal Helper에 통합하여 Multi-Agent, RAG, GraphRAG, 법률 검증 및 문서 생성 과정을 관측하고 평가할 수 있는 기반을 구축한다.

## 1. 핵심 개발 원칙

1. P0~P3.5의 기존 기능과 아키텍처를 유지한다.
2. `C:\myprjs\ai-legal-agent` 프로젝트는 절대 수정하지 않는다.
3. 기존 AOP Tracing, OpenTelemetry, Gateway, TokenTracker를 우선 재사용한다.
4. Langfuse 도입으로 동일 LLM 호출이 중복 집계되지 않도록 한다.
5. Langfuse 장애가 핵심 법률 분석 기능을 중단시키지 않도록 한다.
6. 개인정보 및 법률 사건 원문을 기본적으로 Langfuse에 저장하지 않는다.
7. Self-hosted 구성을 우선 검토한다.
8. 기존 Docker Compose와 충돌하지 않도록 구성한다.
9. P4 사용자 직접 테스트에서 추적 데이터를 활용할 수 있어야 한다.
10. 한국어 코드 주석 표준과 개발지시서 버전 관리 규칙을 준수한다.

## 2. 사전 조사 및 설계

구현 전 다음을 실제 코드 기준으로 조사한다.

- AOP Tracing 구현 구조
- OpenTelemetry SDK 및 Exporter
- Azure OpenAI Gateway 호출 경로
- TokenTracker 집계 방식
- LangGraph 실행 구조
- Supervisor / Verification Agent 호출 방식
- ChromaDB 검색 코드
- Neo4j GraphRAG 검색 코드
- Action Planner 실행 코드
- Document Generation 실행 코드
- Docker Compose 구성
- 기존 개인정보 로깅 정책

Langfuse의 현재 공식 SDK, LangGraph 연동 방식, Self-hosted 배포 요구사항을 확인한다.

설치 버전과 선택 근거를 ADR에 기록한다.

기존 추적 구조와 Langfuse의 연동 방법을 비교한다.

### 연동 후보

A. OpenTelemetry 기반 연동  
B. LangGraph Callback Handler 기반 연동  
C. Gateway 중심 수동 계측

중복 기록, 구현 복잡도, 비용 정확도, 유지보수성, 개인정보 통제를 비교한 뒤 적합한 방식을 선택한다.

**한 실행 경로에 복수의 중복 LLM 계측 방식을 무분별하게 적용하지 않는다.**

## 3. Langfuse Self-hosted 환경

기존 `docker-compose.yml`과 충돌하지 않도록 별도 Compose Profile 또는 별도 Compose 파일로 구성한다.

예:

- `docker-compose.langfuse.yml`

현재 공식 Langfuse 버전의 필수 인프라를 확인한다.

버전에 따라 필요한 구성요소:

- Langfuse Web
- Langfuse Worker
- PostgreSQL
- ClickHouse
- Redis
- S3 호환 오브젝트 스토리지

기존 AI Legal Helper의 PostgreSQL 데이터베이스와 Langfuse의 내부 저장소는 논리적으로 분리한다.

### 필수 요구사항

- 버전 고정
- 환경변수 관리
- Health Check
- 영속 볼륨
- 서비스 시작·종료
- 내부 네트워크 설정
- 데이터 백업 및 삭제 정책
- 포트 충돌 방지
- 개발 환경용 접근 제한

기존 AI Legal Helper는 Langfuse를 실행하지 않아도 정상 동작해야 한다.

Langfuse Self-hosted 운영이 로컬 PC 자원에 과도한 부담을 주는 경우, 경량 개발 모드 또는 별도 승인된 환경을 대안으로 문서화한다.

## 4. 환경변수

`.env.example`에 다음 설정을 추가한다.

- `LANGFUSE_ENABLED`
- `LANGFUSE_HOST`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_CAPTURE_CONTENT`
- `LANGFUSE_SAMPLE_RATE`
- `LANGFUSE_ENVIRONMENT`

기본값:

- Langfuse 비활성화 가능
- 원문 수집 비활성화
- 비밀키 로그 출력 금지

환경변수 이름은 선택한 공식 SDK 버전에 맞게 검증한다.

개발·테스트·운영 환경별 설정을 분리한다.

## 5. Trace Context 설계

사건별 AI 실행을 하나의 Trace로 연결한다.

### Trace Metadata

- `trace_id`
- `request_id`
- `case_ref`
- `workflow_type`
- `workflow_revision`
- `agent_name`
- `operation`
- `status`
- `duration_ms`
- `error_code`
- `token_usage`
- `estimated_cost`

`case_ref`는 원본 사건 ID를 그대로 노출하지 않는 가명화 식별자를 사용한다.

사용자 이름, 주소, 연락처, 계약서 내용 등 개인정보는 Metadata에 포함하지 않는다.

FastAPI 요청 → LangGraph → Agent → Gateway → RAG → Verification까지 추적 관계를 유지한다.

비동기 작업과 GraphSync Worker에서도 추적 연결을 고려한다.

## 6. LangGraph Multi-Agent 추적

다음 실행 단계를 추적한다.

- Router
- Planner
- Supervisor
- Specialist Agents
- Synthesizer
- Verification Agent
- FactExtractor
- Evidence Analysis
- GraphRAG
- LegalActionPlanner
- Document Generation
- Document Verification

각 단계에 다음 정보를 기록한다.

- 시작 및 종료
- 소요 시간
- 성공·실패 상태
- 재시도 횟수
- 주요 분기 결과
- 오류 유형
- 입력 및 출력의 구조적 크기
- 필요 시 비식별화된 진단 정보

프롬프트 및 응답 원문은 기본적으로 저장하지 않는다.

## 7. Azure OpenAI Gateway 추적

기존 Gateway를 통해 발생하는 LLM 호출을 추적한다.

필수 항목:

- 모델 및 Deployment
- 호출 목적
- 입력 토큰
- 출력 토큰
- 총 토큰
- 호출 지연시간
- 재시도 횟수
- 성공 및 오류
- 추정 비용

실제 API 응답에서 제공되는 토큰 사용량을 우선 사용한다.

추정값과 실제 사용량을 구분한다.

Azure OpenAI의 실제 계약 가격을 알 수 없으면 비용을 확정 금액으로 표시하지 않는다.

기존 TokenTracker와 Langfuse의 토큰 합계가 일치하는지 비교한다.

중복 집계가 발생하면 원인을 분석하여 수정한다.

## 8. RAG / GraphRAG 추적

### ChromaDB

- 검색 유형
- 컬렉션 식별자
- 검색 소요 시간
- Top-K
- 검색 결과 개수
- 결과 점수의 요약 통계
- 검색 실패 여부

### Neo4j

- 그래프 탐색 유형
- 탐색 소요 시간
- 관련 노드 수
- 관련 관계 수
- 경로 수
- Fallback 여부
- 오류 유형

검색 원문, 계약서 본문, 증거 텍스트를 기본적으로 기록하지 않는다.

검색 결과 ID는 사건 간 추적이 불가능한 안전한 형태로 처리한다.

## 9. Verification Agent 추적

다음 정보를 기록한다.

- 검증 대상 Claim 개수
- 검증 통과 개수
- WARNING 개수
- FAIL 개수
- 근거 부족 개수
- 재분석 요청 개수
- 재시도 후 결과

법률적 판단의 정답 여부와 시스템 내부 Verification 통과 여부를 구분한다.

Verification 통과율을 실제 법률 정확도로 표현하지 않는다.

## 10. Action / Document 추적

### Action Planner

- 생성한 Action 개수
- 우선순위 분포
- 선행조건 부족 개수
- 기한 검증 실패 개수
- 사용자 확인 필요 개수

### Document Generator

- 문서 유형
- 초안 생성 시간
- 문서 검증 결과
- Revision 개수
- 사용자 수정 발생 여부
- DOCX/PDF 출력 성공 여부

문서 본문과 개인정보는 Langfuse에 저장하지 않는다.

## 11. Evaluation Framework

P4 사용자 직접 테스트를 위한 평가 구조를 구현한다.

### 평가 대상

- 법률 쟁점 추출
- 근거 검색
- 사실 추출
- 증거 연결
- Action 추천
- 문서 검증

### 평가 지표

- Precision@K
- Recall@K
- 근거 추적률
- 필수 절차 누락률
- 문서 사실 불일치율
- 응답 지연시간
- 토큰 사용량
- 추정 비용

평가 데이터셋과 정답 데이터가 없는 지표는 `NOT_EVALUATED`로 표시한다.

Langfuse에 평가 결과를 기록할 수 있는 인터페이스를 구현하되, 실제 정답 데이터 기반 평가는 P4에서 수행한다.

합성 데이터 기반 기술 테스트와 실제 법률 정확도 평가를 구분한다.

## 12. React 개발자 진단 UI

기존 개발자 콘솔과 연계한다.

다음 정보를 확인할 수 있도록 한다.

- Trace ID
- 실행 상태
- Agent 실행 순서
- 총 지연시간
- 토큰 사용량
- 추정 비용
- 오류 및 재시도
- Langfuse 대시보드 이동

일반 사용자에게 내부 추적 정보가 불필요하게 노출되지 않도록 한다.

Langfuse 대시보드 링크는 인증된 관리자 또는 개발자에게만 제공한다.

기존 개발자 콘솔이 있다면 중복 UI를 만들지 않는다.

## 13. 개인정보 및 보안

### 기본 정책

- Prompt/Response 원문 수집 OFF
- Evidence 원문 수집 OFF
- Document 본문 수집 OFF
- 개인정보 Metadata 저장 금지
- API Key 및 인증 토큰 수집 금지
- 예외 메시지의 민감정보 마스킹
- Trace 접근 권한 제한
- 보존 기간 및 삭제 정책 정의

공식 SDK가 자동으로 입력·출력을 수집하는 경우 이를 비활성화하거나 계측 계층에서 제거한다.

마스킹 이전의 원문이 Span Attribute, Event, Exception에 포함되지 않는지 테스트한다.

## 14. 장애 격리

다음 상황을 검증한다.

- Langfuse 서버 미실행
- Langfuse 응답 지연
- Langfuse 인증 오류
- Langfuse 네트워크 단절
- Langfuse 저장소 장애
- 추적 데이터 전송 실패

이러한 장애가 발생해도 AI Legal Helper의 핵심 요청은 정상적으로 처리되어야 한다.

추적 실패로 인한 무한 재시도, 메모리 증가 또는 요청 지연을 방지한다.

필요하다면 비동기 큐, 타임아웃, 샘플링, Circuit Breaker를 적용한다.

## 15. Windows 실행 지원

다음 스크립트를 추가하거나 기존 스크립트를 확장한다.

- `scripts/windows-langfuse-start.ps1`
- `scripts/windows-langfuse-stop.ps1`
- `scripts/windows-langfuse-status.ps1`

기존 `windows-start.ps1`은 Langfuse 없이도 정상 동작해야 한다.

사용자가 Langfuse를 선택적으로 실행할 수 있도록 한다.

설치 및 최초 설정 방법을 사용자 가이드에 기록한다.

## 16. 테스트

최소 다음을 검증한다.

1. Langfuse 비활성화 상태에서 기존 서비스 정상 동작
2. Langfuse 활성화 후 Trace 생성
3. FastAPI → LangGraph → Agent 추적 연결
4. Gateway LLM 호출 추적
5. 토큰 사용량 중복 집계 방지
6. ChromaDB 검색 추적
7. Neo4j GraphRAG 추적
8. Verification Agent 추적
9. Action Planner 추적
10. Document Generator 추적
11. 개인정보 원문 미수집
12. API Key 및 인증 토큰 미노출
13. Langfuse 서버 장애 시 핵심 기능 유지
14. 추적 전송 지연 시 응답 지연 제한
15. Trace 접근 권한 제한
16. Windows 시작·종료 스크립트
17. Docker Compose 충돌 여부
18. 기존 P0~P3.5 회귀 테스트

실제 Langfuse UI에서 Trace가 조회되는지 확인한다.

Mock 테스트 통과와 실제 Self-hosted 환경 검증을 구분한다.

## 17. AI Master 평가 자료

이번 단계는 특히 다음 평가 요소를 강화한다.

### Technical Depth & System Excellence

- 분산 추적 구조
- Multi-Agent 실행 관측
- RAG 및 GraphRAG 성능 분석
- 토큰·비용 추적
- 장애 격리
- 개인정보 보호 설계

### Problem Solving & Strategy

- 기존 시스템에서 관측하기 어려웠던 문제 정의
- Langfuse 도입 목적
- 기존 AOP/OTel과의 통합 이유
- 도입 전후 비교 가능한 측정 항목

### Growth Potential & Communication

- 실제 Agent 실행 Trace를 활용한 시연
- 오류 발견 및 개선 사례
- 측정 기반 시스템 고도화 계획
- 기술 선택과 트레이드오프 설명

실제 측정하지 않은 개선 효과는 주장하지 않는다.

## 18. 필수 산출물

- `docs/instructions/P3_6_LANGFUSE_OBSERVABILITY_EVALUATION_INSTRUCTION_v1.0.md`
- `docs/architecture/P3_6_OBSERVABILITY_ARCHITECTURE.md`
- `docs/adr/P3_6_LANGFUSE_INTEGRATION_DECISIONS.md`
- `docs/development/P3_6_IMPLEMENTATION_LOG.md`
- `docs/development/P3_6_ISSUE_RESOLUTION.md`
- `docs/evaluation/P3_6_TEST_REPORT.md`
- `docs/evaluation/P3_6_MASTER_QA.md`
- `docs/evaluation/P3_6_COMPLETION_REPORT.md`
- `docs/user/LANGFUSE_SETUP_GUIDE.md`

README 개발지시서 인덱스를 갱신한다.

## 19. 완료 기준

1. Langfuse 선택적 실행 가능
2. 기존 서비스 단독 실행 가능
3. LangGraph Agent 추적
4. Azure OpenAI 토큰·비용 추적
5. RAG/GraphRAG 추적
6. Verification 추적
7. Action/Document 추적
8. 개인정보 수집 통제
9. Langfuse 장애 격리
10. 평가 데이터 기록 기반
11. 실제 Langfuse 대시보드 확인
12. 테스트 로그 및 개발 문서 확보

완료하지 못한 항목은 `PARTIAL` 또는 `NOT_TESTED`로 명시한다.

## 20. 개발 종료

개발 완료 후 실제 구현 파일, 실행 명령, 테스트 결과, Langfuse Trace 화면 확인 결과, 미완료 항목을 보고한다.

**P3.6 완료보고서를 제출하고 사용자 승인 없이 P4로 진행하지 않는다.**

