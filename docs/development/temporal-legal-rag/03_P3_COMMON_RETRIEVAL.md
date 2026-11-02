# Temporal Legal RAG — P3 공통 Law Retrieval Service 개발 결과

**작성:** 2026-11-02  
**기준 소스:** P2 main `4f47a33de95ca3db9cec2931265b8f12fc2842d3`  
**개발 브랜치:** `feature/temporal-legal-rag-p3-common-retrieval`  
**핵심 제약:** 기존 8개 Agent 유지, 동적 Agent 생성 금지, 공식 법령 검색의 기존 HILT 유지.

## 1. 문제 정의

기존 `make_fixed_retrieval_tool()`은 Agent별 `law_docs_civil`,
`law_docs_administrative` 등 한 개의 Vector 컬렉션만 조회한다.
새 공식 법령을 `law_docs_global`에 임베딩해도 기존 민법 Agent가 해당
자료를 검색할 수 없다는 결합 문제가 있다.

**P3 목표:** 현재 8개 Agent/Tool 호출 계약을 유지하면서
공통 법령 Vector 검색과 기존 분야별 검색을 하나의 서비스에서 수행한다.
검색 결과는 공식 법령ID/버전/조문/시점 메타데이터를 보존하고,
근거 확보 상태 및 인프라 장애를 구조화한다.

## 2. 아키텍처 및 호출 흐름

```text
기존 Router → 기존 8개 Agent 중 적합한 Agent 선택
              ↓
기존 검색 Tool (tool_name/입출력 유지)
              ↓
       LawRetrievalService.search()
           ├── Law Resolver (P2, 로컬 법령명 카탈로그)
           ├── law_docs_global (신규 공통 Chroma 컬렉션, 존재 시)
           └── law_docs_{category} (기존 분야별 컬렉션)
              ↓
     법령 ID/버전/조문 필터 및 중복 제거
              ↓
       LawRetrievalResponse
           ├── sources (표준 Source 전체 원문)
           ├── status (검색 근거 상태)
           ├── missing_laws/missing_articles
           ├── collection_statuses
           ├── resolved_laws/catalog_status
           └── official_search_recommended (제안만, 실제 호출 없음)
              ↓
   기존 Agent Observation + Source Registry
              ↓
      기존 Synthesizer/Verification
```

**주의:** 현재 `DOCUMENT_MODE`의 `run_agents_node`에는 별도 검색 경로가 존재한다.
문서 사건 상담/후속 재검증 경로의 기존 계약을 깨지 않기 위해 P3에서는 변경하지 않는다.
문서 상담도 동일 공통 법령 조회 결과를 사용할 수 있도록 하는 작업은 별도 통합 검증 후 수행한다.

## 3. 변경 파일

| 파일 | 핵심 변경 |
| --- | --- |
| `legal_knowledge/retrieval_service.py` | 새 공통 Vector 검색 및 SourceCoverage 상태, ID/버전/조문 엄격 필터 |
| `rag/retrieval_factory.py` | 기존 8개 Tool을 공통 검색 어댑터로 전환, Feature Flag 롤백 |
| `agents/legal/base_agent.py` | 실제 공식 법령명·조문·URL 근거 인용 허용, 가짜 PDF 페이지 금지 |
| `tests/unit/test_law_retrieval_service_p3.py` | 공통 검색/카탈로그/버전/시행일/장애 Mock 테스트 |
| `tests/unit/test_law_retrieval_tool_p3.py` | 기존 8개 Tool/AgentExecutor 통합 Mock 테스트 |
| `.github/workflows/temporal-legal-rag-p3.yml` | 두 격리 테스트 Job 자동화 |

기존 PostgreSQL, Neo4j, ChromaDB 데이터 및 HILT Graph 구성은 변경하지 않는다.

## 4. 근거 확보 상태

`LawSourceStatus`는 다음 상태를 구별한다.

| 상태 | 의미 |
| --- | --- |
| `SOURCE_COMPLETE` | 명시 법령·조문 검색 범위가 확인됨. **법률 적용 확정 아님** |
| `SOURCE_PARTIAL` | 검색 근거는 있으나 법령/조문 범위 미확인 또는 일부 누락 |
| `SOURCE_MISSING` | 검색 실행은 되었으나 관련 근거 미확보 |
| `SOURCE_VERSION_UNCONFIRMED` | 공식 법령 버전 또는 현재 목록 MST와 정합성 미확인 |
| `SOURCE_TEMPORAL_UNCONFIRMED` | 적용 기준일·시행일·부칙 적용례 검증 미완료 |
| `RETRIEVAL_ERROR` | 벡터 서비스/설정 장애 등 검색을 정상 완료하지 못함 |

검색 성공과 법률 적용 가능 판정은 별개다. P1의 Temporal Applicability
API를 옵션 `as_of_date`로 적용하되, 이를 실제 사건 날짜에서 추출하고
정식 시행/적용례 검증으로 연결하는 작업은 P5~P8에서 진행한다.

`official_search_recommended`는 **LangGraph가 추후 HILT를 처리할 수 있도록
제공하는 판단용 신호**이며 P3가 OpenLaw를 자동 호출한다는 뜻이 아니다.
벡터 서비스 장애로 법령이 조회되지 않은 경우 자동 공식 검색을 권하지 않는다.

## 5. 필수 안전 정책

1. 복수 법령 질문은 요구 법령별 최소 한 건을 우선하여 상위 K개 결과를 구성한다.
2. 법령 ID가 서로 다르면 법령명이 같아도 임의로 동일 출처로 취급하지 않는다.
3. 동일 법령/동일 조문의 다른 MST 버전은 별도로 보존한다.
4. 동일 법령/버전/조문/내용이 공통 및 레거시 컬렉션에 중복되면 한 번만 반환한다.
5. 약칭 충돌(`AMBIGUOUS`) 시 Vector 유사도로 법령ID를 임의 선정하지 않는다.
6. 검색 결과가 없다는 이유만으로 '해당 법령이 존재하지 않는다'고 주장하지 않는다.
7. 공식 출처에 PDF 파일/페이지가 없다면 법령명·조문·URL로 인용한다.
8. 원문 전체를 Source Registry에 등록하고, Tool Observation만 240자 미리보기로 줄인다.
9. OpenLaw 추가 검색·외부 요청 및 임베딩은 P3에서 호출하지 않는다.
10. 기존 `AgentExecutor.tools[0]` 사용 방식 및 각 Agent Tool 이름은 그대로 유지한다.
11. 로컬 Law Catalog DB에 접근 불가해도 기존 Vector 검색이 실행될 수 있도록 한다.
12. 검색 결과의 `SOURCE_COMPLETE`는 최종 Verification PASS 또는 시행일 적용 확정을 의미하지 않는다.

## 6. 환경설정 및 롤백

| 환경변수 | 기본값 | 역할 |
| --- | --- | --- |
| `LEGAL_GLOBAL_RETRIEVAL_ENABLED` | `1` | 공통 컬렉션 + 분야 컬렉션 동시 조회 |
| `LEGAL_CATALOG_RESOLUTION_ENABLED` | `1` | 명시된 법령명을 로컬 P2 Catalog에서 식별 |
| `CHROMA_HOST`, `CHROMA_PORT` | 기존 설정 | ChromaDB 위치 |
| `DATABASE_URL` | 기존 설정 | P2 Law Catalog PostgreSQL |

**즉시 이전 검색으로 롤백:**

```powershell
$env:LEGAL_GLOBAL_RETRIEVAL_ENABLED = "0"
```

이를 설정하고 애플리케이션을 재시작하면 기존 분야별 단일 컬렉션 검색 경로를
사용한다. 공식 API 인증을 새로 요구하지 않는다.

P2 Catalog가 초기화되지 않은 환경에서는 카탈로그 조회 실패를 로그에 남기고
Vector 검색을 계속하지만, 카탈로그 없는 상태에서 필요한 법령을
모두 확인했다고 주장하지 않는다.

**주의:** 최초 임베딩 Worker는 P9 개발 범위다. `law_docs_global` 컬렉션이
아직 없더라도 P3 자체는 정상 동작할 수 있다. 과거 법령 인덱스는 삭제하지 않는다.

## 7. 테스트 / KPI 확인

### P3 서비스 격리 테스트

```powershell
cd backend
python -m pytest -q tests/unit/test_law_retrieval_service_p3.py tests/unit/test_law_catalog_p2.py
```

### 기존 Tool/AgentExecutor 통합 테스트

```powershell
cd backend
python -m pytest -q tests/unit/test_law_retrieval_tool_p3.py tests/unit/test_temporal_legal_rag_p0_contract.py
```

CI `Temporal Legal RAG P3 regression`의 2개 Job을 모두 통과해야 한다.

후속 실제 환경의 A/B 성능 기준은 동일 질문 및 동일 Vector 인덱스를 기준으로
`LEGAL_GLOBAL_RETRIEVAL_ENABLED=0/1`을 비교한다.

필수 지표:

- 법령 검색 적중 여부
- 공통 컬렉션 적중/부재
- 공식 법령명과 반환 source의 법령ID 일치율
- 중복 제거 전후 Source 수
- 반환 Source의 버전/시행일 미확인율
- 장애/근거 없음 구분 정확도
- Tool 검색 소요시간 P50/P95
- LLM 호출 횟수/토큰량
- HILT 승인·거절 및 Checkpoint 회귀

두 컬렉션을 검색하므로 P3 자체가 항상 더 빠르다고 주장하지 않는다.
P11에서 실측값을 기준으로 캐시 및 중복 검색 최적화를 추가한다.

## 8. 후속 범위와 알려진 제한

- **P4:** 공식 시행일 기준 법령·연혁 API 조회 및 부칙 원문 확보
- **P5:** 법률 사건 기준일·부칙 적용례를 검증한 Temporal Resolver
- **P6:** LangGraph 선행 검색 계획과 기존 HILT 승인 경로 연결
- **P7~P8:** 공통 Evidence Bundle의 Synthesizer/Verification 연동
- **P9:** 독립 백그라운드 법령 임베딩 Worker 및 중복 작업 방지
- **P10:** 기존 레거시 Vector 메타데이터 검증·마이그레이션

현재 Router가 '임차권등기명령' 같은 법률 용어만으로 법령명을
발견하는 기능은 P2 이름/약칭 Resolver만으로 보장되지 않는다.
P3는 실제 Vector 검색 결과를 추가하되, 법령명이 생략된 문제의
정밀 법령 선정/근거 검증은 후속 단계에서 완성해야 한다.

**P3의 목표 산출물은 공통 검색 인프라와 기존 8개 Agent의 느슨한 결합이다.**
