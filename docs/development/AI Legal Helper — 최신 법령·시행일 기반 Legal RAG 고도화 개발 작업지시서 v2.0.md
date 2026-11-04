# AI Legal Helper — 최신 법령·시행일 기반 Legal RAG 고도화 개발 작업지시서 v2.0

**프로젝트:** AI Legal Helper  
**개발 대상:** `yjjungyo/ai-legal-helper`  
**소스 기준:** `main` / `cbea002e6c0eeebfcb1c953d8767b558d432a7c5`  
**작성일:** 2026-11-02  
**개발 방식:** 단계별 구현 → 단위 테스트 → 통합 테스트 → 기존 기능 회귀검증 → 성능 비교  
**문서 상태:** 개발 지시용 확정 설계안. 실제 구현·테스트는 아직 수행하지 않음.

---

# 3. 목표 시스템 아키텍처

## 3.1 핵심 설계 원칙

AI Legal Helper의 핵심 기능을 다음과 같이 정의한다.

**Version-aware + Temporal-aware + Evidence-grounded Legal RAG**

1. 전체 법령을 검색 가능한 대상으로 취급한다.
2. 법령 검색 범위는 기존 8개 Agent의 분야에 제한되지 않는다.
3. Agent의 역할은 법률 분석이며, 법령 검색은 공통 서비스가 담당한다.
4. 이미 저장된 법령은 재사용하되 법령 버전의 유효성을 검사한다.
5. 법령·조문·부칙이 없거나 불완전하면 공식 국가법령정보를 검색한다.
6. 법령의 공포일, 시행일, 적용례, 경과규정과 사건 기준일을 대조한다.
7. 법령 적용 가능 여부가 확정된 후 해당 근거를 Agent 분석에 전달한다.
8. 공식 검색으로 확보한 법령은 임베딩을 기다리지 않고 즉시 답변에 사용한다.
9. 확보한 법령 원문은 별도 Worker로 버전별 임베딩하여 재사용한다.
10. 최종 Verification은 법률 결론과 출처, 시행일의 정확성을 다시 확인한다.

## 3.2 목표 워크플로

```text
START
  ↓
supervisor_initialize
  ↓
intent_analysis
  ↓
route
  │
  ├── 기존 8개 전문분야 선택
  └── 관련 법령 후보·사건 기준일 추출
  ↓
plan
  ↓
resolve_legal_sources          [신규]
  │
  ├── Law Catalog에서 법령 식별
  ├── ChromaDB 검색
  ├── PostgreSQL 법령 버전 확인
  ├── 조문·부칙·적용례 완전성 판단
  │
  ├── 근거 충분
  │      ↓
  │   resolve_temporal_law     [신규]
  │
  └── 근거 부족 / 최신성 불확실
         ↓
      statute_search_approval  [기존 HILT 재사용]
         ↓
      execute_statute_search   [기존 노드 확장]
         ↓
      resolve_temporal_law     [신규]
         │
         └── 임베딩 작업 등록
                  │
                  └── 별도 Worker 프로세스
                         ↓
                    ChromaDB Upsert

  ↓
run_agents                     [기존 8개 Agent]
  ↓
synthesize
  ↓
verification                   [Temporal 검증 강화]
  │
  ├── PASS → finalize
  ├── 수정 필요 → revise → verification
  ├── 추가 근거 필요 → 기존 HILT 및 재분석 경로
  └── 해결 불가 → insufficient
  ↓
END
```

이 다이어그램은 목표 구조이며, 현재 코드의 실행 그래프와 동일하지 않다.

기존 LangGraph Checkpointer, 일반 상담·문서 상담 분기, 승인·거절 정책은 유지한다.

**중요:** `resolve_temporal_law`가 모든 법률 문제를 자체적으로 해석한다는 의미가 아니다. 이 노드는 공식 원문과 명확한 시행 규칙을 정규화하고, 적용 가능 여부와 미확인 사항을 구조화한다. 법률적 해석이 필요한 적용례·경과규정은 Specialist와 Verification의 검토 대상이다.

---

# 4. 공통 데이터 모델 및 계약

## 4.1 Legal Search Plan

현재 검색 계획이 Verification 결과에 의존하는 문제를 해결하기 위해 독립적인 `LegalSearchPlan`을 정의한다.

```json
{
  "question": "임차권등기명령을 신청할 수 있나요?",
  "domains": ["민법"],
  "legal_issues": [
    "임대차 종료",
    "보증금 미반환",
    "임차권등기명령"
  ],
  "candidate_laws": [
    {
      "law_name": "주택임대차보호법",
      "law_id": null,
      "required_articles": [],
      "required_addenda": true
    }
  ],
  "event_dates": [
    {
      "event_type": "LEASE_TERMINATION",
      "date": null,
      "evidence_status": "UNCONFIRMED"
    }
  ],
  "requires_current_law": true,
  "source_status": "UNRESOLVED"
}
```

위 데이터는 인터페이스 예시다. 실제 공식 법령 ID와 시행일은 조회 결과로 설정해야 한다.

**구현 요구사항**

- 기존 `categories`는 그대로 유지한다.
- `legal_search_plan`은 별도 상태로 관리한다.
- 특정 8개 분야에 없다는 이유로 후보 법령을 삭제하지 않는다.
- 후보 법령은 검색 제안이며 확인된 법적 근거가 아니다.
- 법령명·조문을 명시한 질문은 결정론적 추출을 우선한다.
- 법령명이 없는 질문은 전체 Law Catalog를 기반으로 관련 법령을 탐색한다.
- 추가적인 Router LLM 호출은 성능 검증 없이 도입하지 않는다.
- 검색 계획이 불완전하더라도 임의의 법령 ID를 생성하지 않는다.

## 4.2 공통 Source Contract

검색된 법령은 Vector와 OpenLaw 출처에 관계없이 동일한 형식으로 전달한다.

필수 항목:

```text
source_id
source_type
law_id
law_name
law_type
version_id
article
article_title
paragraph
item
content
content_hash
source_url
retrieval_method
retrieved_at

promulgation_date
promulgation_number
law_effective_date
article_effective_date
effective_date_basis

addendum_id
applicability_rule_id
transitional_rule_id

temporal_status
metadata_confidence
```

**설계 원칙**

- `law_effective_date`와 `article_effective_date`를 구별한다.
- `version_id`는 공식 법령 버전 식별자를 사용한다.
- 검색 시점과 법령 시행일을 혼동하지 않는다.
- 조회 시점이 최신이라고 해서 해당 법령이 사건에 적용된다고 단정하지 않는다.
- 파일명에서 추정한 날짜는 공식 확인된 시행일로 승격하지 않는다.
- 출처 원문은 훼손 없이 보존한다.
- Agent 입력용 요약과 검증용 원문을 분리한다.

---

# 5. 데이터베이스 설계

## 5.1 PostgreSQL

기존 사건 관련 테이블은 변경하지 않고 법령 관리 테이블을 추가한다.

| 테이블 | 목적 | 주요 필드 |
|---|---|---|
| `law_catalog` | 전체 법령 식별 및 검색 | law_id, name, type, aliases, status |
| `law_versions` | 법령별 공포·시행 버전 | law_id, version_id, promulgation_date, promulgation_number, effective_date |
| `law_article_versions` | 조문 버전 및 원문 | version_id, article_key, content, content_hash, effective_date |
| `law_addenda` | 공포번호별 부칙 원문 | addendum_id, version_id, promulgation_number, content |
| `law_temporal_rules` | 시행 예외·적용례·경과규정 | rule_id, rule_type, source_span, date_basis, status |
| `law_index_jobs` | 비동기 임베딩 작업 관리 | job_id, version_id, status, attempts, error_code |
| `law_index_manifest` | Chroma 인덱스 무결성 및 완료 상태 | version_id, embedding_model, chunk_strategy, chunk_count, status |
| `law_source_checks` | 공식 최신성 및 조회 이력 | law_id, checked_at, official_version_id, result |

각 테이블의 정확한 컬럼과 제약조건은 기존 SQLAlchemy/Alembic 관례에 맞춰 정의한다.

### 필수 DB 제약조건

- 공식 법령 ID와 버전 ID의 유효성 검사
- `(law_id, version_id)` 복합 유일성
- 조문 키와 버전의 유일성
- 동일 버전·원문 해시·임베딩 모델·청킹 전략 중복 작업 방지
- 실패 작업의 안전한 재실행
- 임베딩 중인 법령의 원문 변경 방지 또는 변경 감지
- 검색 시 공식 원문 버전의 추적 가능성

법령 원문과 구조화된 법령 정보는 PostgreSQL에서 관리한다. 전체 원본 XML은 기존 로컬 운영 정책에 따라 지속성 있는 로컬 저장소에 보존하고 PostgreSQL에 경로와 해시를 관리하거나, 용량 검토 후 DB에 저장한다. 어느 방식을 택하더라도 Worker 재시작 후 원문 복구가 가능해야 한다.

## 5.2 ChromaDB

새 공통 컬렉션을 다음 이름으로 도입한다.

```text
law_docs_global
```

기존 컬렉션은 유지한다.

```text
law_docs_civil
law_docs_criminal
law_docs_administrative
law_docs_labor
law_docs_commercial
law_docs_constitution
law_docs_tax
law_docs_international
```

`law_docs_global`에는 공식 법령 ID와 버전별 청크를 저장한다.

**신규 공식 법령은 기본적으로 공통 컬렉션에만 임베딩한다.** 동일 법령을 분야별 컬렉션마다 중복 저장하지 않는다.

### Chroma 메타데이터 필수 항목

```json
{
  "source_type": "STATUTE",
  "law_id": "OFFICIAL_ID",
  "law_name": "주택임대차보호법",
  "version_id": "OFFICIAL_VERSION",
  "article": "제6조의2",
  "article_effective_date": "YYYY-MM-DD",
  "promulgation_date": "YYYY-MM-DD",
  "promulgation_number": "OFFICIAL_NUMBER",
  "temporal_status": "VERIFIED",
  "content_hash": "SHA256_HASH",
  "chunk_strategy_version": "v1"
}
```

실제 날짜가 확인되지 않은 필드는 `UNCONFIRMED` 상태를 별도로 관리하고, 유효하지 않은 날짜 문자열을 넣지 않는다. Chroma의 메타데이터 타입 제약에 맞춰 평면화하고, 복잡한 적용례 원문과 관계 정보는 PostgreSQL의 참조 ID로 연결한다.

## 5.3 법령 버전 관리

동일한 조문이 개정되더라도 과거 조문을 삭제하지 않는다.

```text
Law: 주택임대차보호법
  ├── Version A
  │      └── 제6조의2
  ├── Version B
  │      └── 제6조의2
  └── Version C
         └── 제6조의2
```

각 버전은 독립적인 원문 해시와 시행일, 관련 부칙을 가져야 한다.

**주의:** 법령 버전의 시행기간과 사건에 대한 법률적 적용기간은 같지 않을 수 있다. 경과규정에 따라 종전 규정이 적용되는 사건이 있으므로, 단순히 `시행일 <= 사건일`만으로 버전을 확정하지 않는다.

---

# 6. 핵심 모듈별 개발 작업

## TASK-01. Law Catalog 구축

**목적:** 현재 Vector에 존재하지 않는 법령도 발견할 수 있도록 한다.

**신규 모듈 제안**

```text
legal_knowledge/
  law_catalog.py
  law_resolver.py
  law_metadata.py
```

### 구현 기능

1. 공식 국가법령정보 API에서 법령 목록과 식별자를 수집한다.
2. 법령명, 약칭, 별칭, 법령 유형, 공식 ID를 저장한다.
3. 검색 후보와 공식 법령의 동일성을 확인한다.
4. 법령명·약칭·관련 쟁점으로 후보를 찾는다.
5. 법률·시행령·시행규칙 간 관계를 유지한다.
6. 법령 카탈로그의 변경 사항을 증분 동기화한다.
7. 검색 결과가 여러 법령과 일치하면 모호성을 표시한다.

전체 법령 카탈로그 구축과 전체 법령 본문 임베딩은 별개 작업이다.

카탈로그 메타데이터는 우선 수집하되, 법령 원문과 임베딩은 필요할 때 확보한다.

### 완료 기준

- 주택임대차보호법, 근로기준법 등 다양한 법령을 식별한다.
- Vector에 존재하지 않는 법령도 검색 후보가 된다.
- `민법` 검색 시 `난민법`을 임의로 선택하지 않는다.
- 법령 분류가 8개 Agent 분야에 종속되지 않는다.
- 신규 법령 발견을 위해 소스에 법령명을 추가할 필요가 없다.

---

## TASK-02. 공통 Law Retrieval Service 개발

**목적:** 전문 Agent와 법령 저장소 간의 고정 결합을 제거한다.

**신규 모듈 제안**

```text
legal_knowledge/
  retrieval_service.py
  source_coverage.py
  source_registry.py
```

### 인터페이스 예시

```python
class LawRetrievalService:
    def resolve(
        self,
        search_plan,
        event_context,
    ):
        """검색 출처, 버전 및 부족한 근거를 반환한다."""
```

### 실행 순서

1. Law Catalog에서 법령 식별
2. ChromaDB 공통 법령 컬렉션 검색
3. 필요한 경우 기존 분야별 컬렉션 검색
4. 관련 법령·조문·버전 필터링
5. PostgreSQL의 시행일·부칙 메타데이터 확인
6. 근거 완전성 판단
7. 충분하면 `EvidenceBundle` 반환
8. 부족하면 `OfficialSearchRequest` 반환

### 검색 완전성 상태

```text
SOURCE_COMPLETE
SOURCE_PARTIAL
SOURCE_MISSING
SOURCE_VERSION_UNCONFIRMED
SOURCE_TEMPORAL_UNCONFIRMED
RETRIEVAL_ERROR
```

검색 실패와 결과 없음은 반드시 구별한다.

예를 들어 Chroma 연결 장애를 법령 미적재로 오인하여 불필요한 외부 검색을 반복하지 않는다.

### 기존 Agent 연결 변경

현재 `make_fixed_retrieval_tool()`의 공개 인터페이스는 보존한다.

내부 검색 호출을 공통 서비스로 위임하는 어댑터를 만든다.

```text
기존:
civil_agent
  → civil_retrieval_tool
  → law_docs_civil

개선:
civil_agent
  → civil_retrieval_tool
  → LawRetrievalService
       ├── law_docs_global
       ├── 기존 분야별 Vector
       └── Source Registry
```

OpenLaw 호출 승인은 LangGraph가 담당한다. 개별 Agent Tool이 사용자 승인 없이 공식 API를 직접 호출하지 않도록 한다.

### 완료 기준

- 기존 8개 Agent의 Tool 호출 방식이 유지된다.
- 모든 Agent가 공통 법령을 검색할 수 있다.
- 주택임대차보호법을 한 번 임베딩하면 민법·행정 Agent가 공통 재사용할 수 있다.
- 동일 상담 내 불필요한 검색이 중복되지 않는다.
- `AgentExecutor`가 첫 번째 Tool만 실행하는 기존 특성을 고려하여 사전 검색 결과를 Agent에 명시적으로 전달한다.
- 공통 검색 실패 시 정상적인 기존 검색 경로를 유지할 수 있다.

---

## TASK-03. 공식 법령 검색 고도화

**대상:** `tools/official_statute_search.py`

### 필수 개선

현재 공포일 중심의 법령명 검색 및 상세 조회에 다음 기능을 보강한다.

1. 시행일 기준 법령 목록·본문 검색
2. 법령 연혁 및 시행예정 버전 식별
3. 동일 법령의 복수 버전 조회
4. 조문·항·호 원문 검색
5. 조문별 시행일 추출
6. 공포번호에 대응하는 부칙 원문 추출
7. 시행일 예외 및 적용례 검토용 원문 확보
8. 법령 원문과 메타데이터 해시 검증
9. 동일 법령 버전의 중복 네트워크 호출 방지
10. 검색 결과와 배경 임베딩용 원본 분리

API 요청 파라미터는 공식 문서에 정의된 `target=law`, `target=eflaw`, 법령 ID 및 MST 등 실제 지원 기능에 맞춰 구현한다.

### 출력 형태

```text
OfficialLawResponse
  ├── law_identity
  ├── law_version
  ├── selected_articles
  ├── addenda
  ├── temporal_metadata
  ├── original_xml_reference
  ├── source_manifest
  └── retrieval_status
```

### 중요 규칙

- 질문에 필요한 조문만 반환하는 상담용 API와 전체 법령을 색인하는 작업을 구분한다.
- 상담 경로에서 임베딩 생성을 수행하지 않는다.
- 이미 확보한 공식 XML이 있으면 Background Worker에 재사용한다.
- 법령 원문을 실제로 PDF로 내려받지 않았다면 PDF 파일명으로 출처를 가장하지 않는다.
- URL, 공포번호, MST 등은 공식 응답값만 사용한다.
- 해당 조문이 조회되지 않았는데 무관한 조문으로 대체하지 않는다.
- 부칙을 찾지 못한 경우 성공으로 처리하지 않고 미확인 상태를 유지한다.

### 완료 기준

공식 법령을 검색하여 법령명·조문·공포번호·시행일·부칙을 하나의 검증 가능한 자료 묶음으로 확보할 수 있다.

---

## TASK-04. Temporal Law Resolver 개발

**이번 프로젝트의 핵심 차별화 기능이다.**

**신규 모듈 제안**

```text
legal_knowledge/
  temporal_resolver.py
  temporal_rules.py
  legal_event_dates.py
```

### 주요 기능

1. 질문 또는 사건 자료에서 법률적 기준일을 추출한다.
2. 계약 체결일, 갱신일, 해지통지 도달일, 행위일, 청구일 등 날짜의 역할을 구분한다.
3. 법령 공포일과 실제 시행일을 구분한다.
4. 법령 전체 시행일과 개별 조문의 시행일을 구분한다.
5. 부칙의 시행일 예외를 확인한다.
6. 적용례·경과규정을 확인한다.
7. 현재·과거·시행예정 법령 버전을 비교한다.
8. 적용 법령을 선정하거나 판단 불가 사유를 반환한다.

### 적용 여부 결과

```text
APPLICABLE
NOT_APPLICABLE
NOT_YET_EFFECTIVE
SUPERSEDED
TRANSITIONAL_RULE_REVIEW_REQUIRED
UNCONFIRMED
```

단순히 `True/False`만 반환하지 않는다.

### 판단 결과 구조

```json
{
  "law_id": "OFFICIAL_ID",
  "version_id": "OFFICIAL_VERSION",
  "article": "제X조",
  "event_type": "CONTRACT_EXECUTED",
  "event_date": "YYYY-MM-DD",
  "article_effective_date": "YYYY-MM-DD",
  "temporal_status": "UNCONFIRMED",
  "reason_code": "TRANSITIONAL_RULE_REVIEW_REQUIRED",
  "supporting_source_ids": [],
  "unresolved_conditions": []
}
```

### 절대 금지사항

- 공포일만으로 신법 적용 확정
- 시행일이 없으면 공포일을 시행일로 대체
- 계약일만으로 모든 법률 쟁점 판단
- 부칙 예외를 무시한 일괄 적용
- 과거 법령을 삭제하고 최신 버전만 보관
- 미확인 결과를 `APPLICABLE`로 반환
- 부칙 원문이 있는데도 임의 해석 결과만 보관

명확한 계산 규칙으로 해결할 수 없는 부칙은 `UNCONFIRMED` 또는 `TRANSITIONAL_RULE_REVIEW_REQUIRED`로 반환한다.

### 완료 기준

- 서로 다른 시행일을 가진 조문들을 구별한다.
- 시행일 이전과 이후 사건의 판단 결과를 구별한다.
- 소급 적용 및 경과규정이 관련된 문제를 누락하지 않는다.
- 계약일이 없거나 여러 사건 날짜가 존재하는 경우 안전하게 처리한다.
- 근거가 없으면 적용 가능 여부를 확정하지 않는다.

---

# 7. LangGraph 워크플로 변경

## TASK-05. 선행 법령 검색 분기 구현

기존 노드들은 가능한 한 유지한다.

### 주요 변경

```text
plan
  ↓
resolve_legal_sources
  │
  ├── SOURCE_COMPLETE
  │      ↓
  │   resolve_temporal_law
  │      ↓
  │   run_agents
  │
  └── OFFICIAL_SEARCH_REQUIRED
         ↓
      statute_search_approval
         ↓
      execute_statute_search
         ↓
      resolve_temporal_law
         ↓
      run_agents
```

### HILT 계약 변경

현재 HILT는 `verification_result`를 참조한다.

하지만 선행 법령 검색은 Verification보다 먼저 실행되므로 다음을 추가한다.

```text
state.legal_search_plan
state.official_search_request
state.source_coverage_result
state.temporal_resolution
state.official_search_stage
```

**HILT 노드와 공식 검색 노드는 새 검색 계획을 직접 입력받을 수 있도록 확장한다.**

기존 Verification 이후의 HILT 경로는 삭제하지 않는다.

### 검색 후 분기 정책

- `draft_answer`가 없는 사전 검색 → `run_agents`로 진입
- 기존 초안 검증 이후 추가 검색 → `re_analyze` 사용
- 검색 승인 거절 → 기존 안전 종료 정책 유지
- 공식 검색 실패 → 허위 근거를 만들지 않고 안전 처리
- 추가 검색이 필요한 경우 → 기존 횟수 제한 및 승인 정책 준수

### LangGraph 안전 요구사항

- 동일 HILT 승인 요청의 중복 처리 금지
- Checkpoint 복구 후 검색 중복 실행 금지
- 승인된 법령 범위를 넘어선 검색 금지
- `revision_count`와 `statute_search_count`의 의미 유지
- 문서 상담의 별도 수정·검증 횟수 정책 유지
- 기존 상담 DB 상태 및 UI 응답 필드 호환
- 재개 시 사용자 승인 대상이 무엇이었는지 재확인

HILT 승인 요청에는 법령명, 필요한 조문, 검색 사유, 검색 범위, 요청 식별자를 명시한다. 승인 후 재개할 때 동일한 계획이 실행되는지 검사한다.

---

# 8. Agent 분석 및 답변 생성

## TASK-06. 기존 8개 Agent 입력 구조 개선

**대상:** `agents/specialist.py`, `agents/legal/base_agent.py`, `workflows/legal_workflow.py`

현재 8개 Agent의 이름과 전문분야를 그대로 유지한다.

### 변경 전

```text
전문 Agent
  → 고정 분야 Vector Tool
  → 검색 결과
  → LLM 분석
```

### 변경 후

```text
공통 법령 검색
  ↓
Evidence Bundle
  ↓
전문 Agent
  ├── 관련 공식 법령
  ├── 적용 가능한 조문 버전
  ├── 부칙·적용례
  ├── 사건 증거
  └── 미확인 조건
  ↓
LLM 분석
```

### 구현 원칙

- Agent에 필요한 법령을 사전에 제공한다.
- 공식 법령과 Vector 검색 결과를 중복해서 전달하지 않는다.
- 원문을 임의로 잘라 법적 조건을 누락하지 않는다.
- 긴 문서는 검증 가능한 관련 조문과 부칙 중심으로 제공한다.
- 기존 사건 증거·GraphRAG 분석 능력을 유지한다.
- 여러 법률이 적용되는 질문도 최소한의 Agent만 실행한다.
- 새로운 전문 Agent를 생성하지 않는다.

### 답변 생성 필수 요건

최종 답변은 가능한 경우 다음 정보를 담는다.

1. 질문에 대한 직접적인 결론
2. 적용되는 법령 및 조문
3. 판단의 기준이 된 사건 날짜
4. 해당 법령의 시행일
5. 부칙·적용례에 따른 판단 이유
6. 미확인 조건이 존재할 경우 그 한계
7. 사건 해결을 위한 다음 행동

단순 법령 질문은 간결하게 작성하고, 복합 사건 상담은 쟁점별 분석을 유지한다.

---

# 9. 백그라운드 자동 임베딩

## TASK-07. Independent Embedding Worker

백그라운드 임베딩은 상담 요청과 별도 프로세스에서 실행한다.

### 권장 구성

```text
OpenLaw 검색 성공
  ↓
공식 원문 저장
  ↓
law_index_jobs 생성
  ↓
상담은 즉시 계속 진행
  ↓
Embedding Worker
  ↓
원문 구조 검증
  ↓
조문·부칙 청킹
  ↓
Embedding 생성
  ↓
law_docs_global Upsert
  ↓
건수·해시·메타데이터 검증
  ↓
INDEXED
```

### Worker 상태

```text
QUEUED
RUNNING
INDEXED
FAILED_RETRYABLE
FAILED_PERMANENT
SKIPPED_EXISTING
```

### 주요 요구사항

- PostgreSQL 기반 작업 큐를 우선 사용한다.
- Worker는 Python 독립 프로세스로 운영한다.
- 기존 Docker 기반 PostgreSQL·ChromaDB에 연결한다.
- 회사가 허용한 Embedding 모델만 사용한다.
- 별도 유료 SaaS나 신규 클라우드 인프라에 의존하지 않는다.
- 동일 작업 동시 실행을 원자적으로 방지한다.
- 중단된 작업은 재시작 후 복구한다.
- 실패 작업은 제한된 횟수와 지수 백오프로 재시도한다.
- 임베딩 실패는 사용자 상담 실패로 전파하지 않는다.
- 기존 법령 및 사건 증거 컬렉션을 삭제하지 않는다.
- 과거 법령 버전을 최신 버전으로 덮어쓰지 않는다.

### 인덱싱 중복 방지 키

```text
law_id
+ version_id
+ source_content_hash
+ embedding_model_id
+ chunk_strategy_version
```

### 청킹 정책

우선 `Article-aware` 방식을 사용한다.

- 조문이 짧으면 조문 단위
- 조문이 길면 항·호 단위
- 부칙은 독립된 원문 단위
- 부칙과 개정 본문의 관계는 ID로 연결
- 법률요건을 중간에서 잘라 의미를 훼손하지 않음
- 모든 청크에 공식 법령 ID와 버전 정보 포함

### 인덱스 완료 판정

Chroma Upsert 호출이 성공했다는 이유만으로 `INDEXED`로 기록하지 않는다.

다음 사항을 확인한 후 완료 처리한다.

- 저장 청크 수
- 필수 메타데이터 존재
- 검색 가능 상태
- 원문 해시 정합성
- 임베딩 모델 버전 일치
- 부칙 및 관련 원문 보존

임베딩 작업의 상태는 관리자 로그 및 개발자 진단에서 확인할 수 있어야 한다.

---

# 10. Temporal Verification 강화

## TASK-08. 법령 적용시점 검증

기존 Verification Agent와 결정론적 QA를 유지한다.

다음 검사 항목을 필수로 추가한다.

### A. 법령 출처 확인

- 실제 공식 법령인가?
- 법령 ID가 일치하는가?
- 원문에 존재하는 조문인가?
- 인용한 조문 내용이 실제 출처에 있는가?

### B. 법령 버전 확인

- 사건의 법률 기준일에 어떤 법령 버전이 관련되는가?
- 최신 버전을 과거 사건에 잘못 적용하지 않았는가?
- 과거 버전을 현재 시행 규정으로 잘못 설명하지 않았는가?

### C. 시행일 확인

- 공포일과 시행일을 구분했는가?
- 개별 조문의 시행일을 확인했는가?
- 일부 조문 시행일 예외를 반영했는가?

### D. 부칙·적용례 검증

- 관련 부칙 원문을 확보했는가?
- 적용례가 사건의 계약일 또는 행위일과 연결되는가?
- 경과규정 검토가 필요한가?
- 명확하지 않은 상태에서 법적 효과를 단정했는가?

### E. 사건 사실 검증

- 사용자가 제공한 계약일 및 기타 사건 날짜를 정확히 사용했는가?
- 서로 다른 날짜 역할을 혼동하지 않았는가?
- 확인되지 않은 사실을 확정 사실로 취급하지 않았는가?

### 판정 정책

```text
법률 근거 충분 + 시점 검증 통과 + 질문 충족
  → PASS

법률 근거 있으나 시점 조건 미확인
  → UNCERTAIN / 조건부 판단

시행일 또는 적용례 오류
  → REVISE

공식 법령 원문 부족
  → SOURCE_MISSING / 공식 검색

검증 기술 오류
  → VERIFICATION_ERROR / 안전 종료
```

현재 `is_statute_applicable_to_date()`의 미확인 날짜를 `True`로 반환하는 정책은 제거하거나, 명시적 판정 객체를 반환하는 새 API로 대체한다.

또한 현재 `temporal_answer_errors()`는 특정 문구 패턴을 중심으로 검사하므로, **“적용됩니다”와 “적용되지 않습니다”라는 긍정·부정 결론을 모두 독립적으로 검증**하도록 개선한다.

### 질문 충족 검사 보완

기존 QA에는 두 개의 요구사항 중 하나만 충족되어도 질문 충족으로 판단될 수 있는 경로가 있다.

새로운 경량 PASS 범위를 확대하기 전에 이 문제를 수정한다.

단순한 키워드 출현을 실제 질문 해결로 간주하지 않는다.

---

# 11. 성능 최적화

## TASK-09. 중복 실행 제거

법령 검색 아키텍처 변경 이후의 Trace를 먼저 측정한 후 다음 최적화를 단계적으로 적용한다.

### 우선순위

| 순서 | 개선 작업 | 목표 |
|---|---|---|
| 1 | 공식 법령 선행 검색 | 불필요한 초안 재작성 감소 |
| 2 | 동일 법령·버전 검색 재사용 | OpenLaw 중복 호출 감소 |
| 3 | 동일 Source Registry 공유 | Agent 간 중복 검색 감소 |
| 4 | Verification 중복 감사 제거 | 불필요한 반복 검증 감소 |
| 5 | 필요한 주장 중심 Verification | LLM 입력 토큰 감소 |
| 6 | 부분 재분석 | 전체 답변 재작성 감소 |
| 7 | 프롬프트 길이 조정 | 입력·출력 토큰 감소 |
| 8 | 문서 상담 Vector 병렬화 | 검색 지연 감소 |

### 성능 개선 원칙

- 법률 정확성에 필요한 검증은 생략하지 않는다.
- 검증 완료된 정상 문장은 다시 작성하지 않는다.
- 법령별 공식 원문은 상담 중 재사용한다.
- 같은 법령 버전으로 여러 요청이 들어오면 검색을 병합한다.
- 임베딩 작업은 상담의 Critical Path에 포함하지 않는다.
- 사용자 HILT 승인 대기시간과 시스템 실행시간을 별도로 집계한다.

기존 `9aa92b46` Trace 기준선은 다음과 같다.

| 지표 | 기준선 | 1차 목표 |
|---|---:|---:|
| 전체 실행시간 | 220.2초 | 120초 이하 |
| LLM Generation | 7회 | 4~5회 |
| 총 토큰 | 169,294 | 80,000 이하 |
| Verification 시간 | 106.5초 | 감소 |
| 재분석 시간 | 75.2초 | 감소 또는 실행 회피 |

목표치는 실험 전 가설이며 실제 달성치를 의미하지 않는다.

---

# 12. 기존 데이터 마이그레이션

## TASK-10. 기존 Vector 및 법령 데이터 보호

현재 적재된 법령 데이터를 삭제하지 않는다.

### 마이그레이션 단계

1. 기존 Chroma 컬렉션 목록 및 청크 수 백업
2. PostgreSQL 데이터와 기존 법령 원문 현황 조사
3. 기존 PDF 메타데이터의 시행일 신뢰도 평가
4. `law_docs_global` 신규 생성
5. 기존 법령의 공식 ID·버전 식별 가능 여부 확인
6. 신뢰 가능한 데이터만 공식 버전과 연결
7. 미확인 데이터는 `LEGACY_UNVERIFIED`로 표시
8. 신규 검색 기능을 Feature Flag로 활성화
9. 조회 결과와 기존 시스템의 정합성 비교
10. 안정화 후 신규 공통 검색 경로를 기본값으로 전환

### 중요

과거 인덱스에 법령 전체 시행일을 복사했다면 그 날짜를 조문별 공식 시행일로 인정하지 않는다.

기존 PDF 파일명에서 추출된 날짜도 공식 검증 전에는 신뢰 수준을 구분해야 한다.

과거 버전이 필요한 상담이 가능하도록 정식 버전 식별을 완료하기 전에는 법령 데이터를 삭제하지 않는다.

---

# 13. 테스트 및 평가 작업

## TASK-11. 필수 기능 테스트

| ID | 시나리오 | 기대 결과 |
|---|---|---|
| T01 | 기존 민법 제6조 질문 | 기존 RAG로 정확한 단문 답변 |
| T02 | Vector에 없는 법령 질문 | 전체 카탈로그 식별 후 HILT → 공식 검색 |
| T03 | 임베딩되지 않은 특별법 질문 | 기존 8개 Agent 범위를 넘어 법령 확보 |
| T04 | 신규 공식 검색 결과 확보 | 임베딩을 기다리지 않고 답변 |
| T05 | 동일 법령 두 번째 질문 | 기존 임베딩 재사용 |
| T06 | 조문은 있지만 부칙 미적재 | 공식 부칙 추가 확인 |
| T07 | 조문별 시행일이 서로 다름 | 각 조문의 시행일을 개별 적용 |
| T08 | 법령 공포일과 시행일이 다름 | 공포만으로 신법 적용 단정 금지 |
| T09 | 사건 기준일이 개정 시행 전 | 관련 적용례 확인 후 구법·신법 판단 |
| T10 | 사건 기준일이 개정 시행 후 | 관련 적용례 확인 후 적용 판단 |
| T11 | 경과규정이 존재 | 단순 시행일 비교 대신 경과규정 반영 |
| T12 | 사건 기준일 미확정 | 조건부 판단 또는 추가 확인 |
| T13 | 동일 법령 동시 검색 | 중복 임베딩 작업 방지 |
| T14 | Embedding Worker 장애 | 상담 정상 처리, 재시도 가능 |
| T15 | Chroma 장애 | 검색 장애를 미적재와 구분 |
| T16 | OpenLaw 장애 | 허위 법령 생성 없이 안전 처리 |
| T17 | HILT 승인 | 승인 범위에 한해 공식 검색 |
| T18 | HILT 거절 | 미승인 외부 검색 차단 |
| T19 | Checkpoint Resume | 중복 승인·검색·답변 방지 |
| T20 | SC-001 사건 상담 | 증거·사실·시점·행동계획 유지 |
| T21 | 문서 상담 | 승인 원문·해시·출처 검증 보존 |
| T22 | 복합 법률 상담 | 여러 법령 적용관계 및 출처 검증 |
| T23 | 과거 버전 질의 | 최신 법령을 무조건 적용하지 않음 |
| T24 | 긍정·부정 적용 판단 | 양쪽 모두 시행일 및 부칙 검증 |

법령 최신성 테스트는 공식 원문과 적용례를 확인한 뒤 정답지를 작성한다. 미확인 법률 효과를 Gold 정답으로 고정하지 않는다.

## TASK-12. LLM Chat / LLM RAG / Legal Agent 비교

동일한 질문으로 세 시스템을 평가한다.

**비교군**

- A: 회사 LLM 단독 Chat
- B: 기존 Vector 기반 LLM RAG
- C: 개선된 AI Legal Helper

**평가 항목**

| 항목 | 측정 방식 |
|---|---|
| 최신 개정법 발견 | 공식 원문 대비 발견 여부 |
| 관련 법령 선정 | 정답지 필수 법령·조문 재현율 |
| 조문 정확도 | 공식 원문과 인용 일치 |
| 시행일 정확도 | 조문별 시행일 정답 여부 |
| 부칙 확인 | 관련 부칙 확보 여부 |
| 적용례 정확도 | 사건 기준일별 적용 판단 |
| 근거 접지율 | 법률 주장과 출처 연결 |
| 질문 충족률 | 핵심 요청 항목 충족 |
| 허위 인용률 | 존재하지 않는 법령·조문 인용 |
| 응답시간 | P50, P95 |
| LLM 호출 및 토큰 | Langfuse 실제 집계 |
| OpenLaw 조회 횟수 | 최초 및 재사용 상담 비교 |

### 정량 평가 방식

최소 다음 세 가지 테스트 집합을 구분한다.

1. **고정 Gold 평가:** 공식 법령 버전과 평가일을 고정하여 재현성 확보
2. **최신성 평가:** 실행 당일 공식 법령을 확인해 변경 탐지 능력 측정
3. **사건 E2E 평가:** SC-001 등 사건 자료를 기반으로 실제 적용 여부 검증

LLM Chat이나 일반 RAG가 반드시 틀린다는 가정을 두지 않는다. 동일 질문과 동일 Gold 정답으로 실제 차이를 입증한다.

## TASK-13. 필수 회귀 검증

새 법령 검색 기능이 기존 사건 분석을 손상시켜서는 안 된다.

다음 기능은 반드시 회귀 테스트한다.

- 사건 등록 및 상태 갱신
- 증거 등록
- 사실 추출 및 사용자 승인
- GraphRAG 증거 관계
- 사실 충돌 감지
- 사건 타임라인
- 일반 법률 상담
- 문서 기반 상담
- Verification 및 부분 답변
- HILT 승인·거절·재개
- 사용자 답변 UI
- Langfuse 추적 및 토큰 집계
- 전체 AOP 오류 로그
- PostgreSQL 및 Neo4j 데이터 정합성

---

# 14. 실제 개발 수행 순서

한 번에 모든 기능을 구현하지 않는다. 아래 순서대로 각각 별도 개발·검증 단위로 진행한다.

| Phase | 핵심 개발 | 완료 기준 | 우선순위 |
|---|---|---|---|
| **P0** | 현행 소스·Trace·DB·테스트 기준선 고정 | 기존 기능 재현 | 최우선 |
| **P1** | 법령 표준 메타데이터·DB 스키마·적용시점 미확인 처리 | 무결성 단위 테스트 | 최우선 |
| **P2** | Law Catalog 및 Law Resolver | 미적재 법령 식별 | 최우선 |
| **P3** | 공통 Law Retrieval Service | 8개 Agent 호환 | 최우선 |
| **P4** | OpenLaw 시행일·연혁·부칙 검색 | 공식 버전 확보 | 최우선 |
| **P5** | Temporal Law Resolver | 사건 기준일별 판단 | 최우선 |
| **P6** | LangGraph 선행 검색 및 HILT 연결 | 승인·재개·분기 검증 | 최우선 |
| **P7** | Agent Evidence Bundle 주입·답변 생성 | 최초 답변 정확성 | 최우선 |
| **P8** | Temporal Verification 고도화 | 오판정 차단 | 최우선 |
| **P9** | PostgreSQL 작업 큐·Embedding Worker | 비동기 안전 적재 | 높음 |
| **P10** | 기존 데이터 마이그레이션·전환 | 데이터 보존 | 높음 |
| **P11** | 중복 검색·검증·재분석 최적화 | 성능 개선 | 높음 |
| **P12** | A/B/C 및 E2E 최종 평가 | KPI·평가 증빙 완성 | 필수 |

### 단계별 작업 원칙

매 Phase는 다음 순서로 진행한다.

```text
1. 대상 실제 소스 검토
2. 변경 범위 확정
3. 단위 기능 구현
4. 단위 테스트
5. 관련 통합 테스트
6. 기존 기능 회귀 테스트
7. 성능 및 품질 전후 비교
8. 변경 내역과 테스트 증빙 정리
9. 승인된 변경만 main 병합
10. 다음 Phase 시작
```

하나의 Phase를 구현하면서 다음 Phase까지 임의로 선행 구현하지 않는다.

---

# 15. 개발 환경·운영 요구사항

## 15.1 기존 환경 유지

- Python 기반 백엔드
- Streamlit UI
- LangGraph
- 회사 제공 LLM
- PostgreSQL
- Neo4j
- ChromaDB
- Langfuse OSS
- Docker 기반 DB 서비스
- 로컬 실행

신규 Embedding Worker는 가능하면 기존 Python 패키지와 실행 환경을 재사용한다.

외부 클라우드 관리형 DB 또는 유료 서비스 추가를 금지한다.

## 15.2 환경설정

필요한 설정을 별도로 정의한다.

```text
LEGAL_GLOBAL_RETRIEVAL_ENABLED
LEGAL_TEMPORAL_RESOLVER_ENABLED
LEGAL_OFFICIAL_PRESEARCH_ENABLED
LEGAL_ASYNC_EMBEDDING_ENABLED

LAW_OPENAPI_KEY
LAW_INDEX_WORKER_ENABLED
LAW_INDEX_BATCH_SIZE
LAW_INDEX_RETRY_LIMIT
LAW_INDEX_POLL_INTERVAL

AZURE_OPENAI_DEPLOYMENT_EMBED
CHROMA_HOST
CHROMA_PORT
```

설정명은 설계 제안이며 실제 프로젝트 네이밍과 충돌하지 않도록 최종 확정한다.

기본값은 안전한 기존 워크플로가 계속 실행되도록 설계한다.

회사 Embedding 모델 배포가 제공되지 않으면 Worker 기능을 비활성화하되 공식 법령 검색 및 직접 답변 기능은 정상 동작해야 한다.

## 15.3 관측성 및 로그

모든 신규 모듈은 기존 AOP·Langfuse 추적 정책을 따른다.

필수 로그 항목:

```text
request_id
trace_id
case_id
node_name
agent_name

law_id
version_id
article_key
event_date
source_status
temporal_status

search_provider
retrieval_method
cache_hit
official_search_count

embedding_job_id
embedding_job_status
embedding_model
chunk_count

execution_ms
llm_calls
input_tokens
output_tokens
error_code
```

법령 원문 및 검색 결과와 관련된 로그는 검색 계획, 원문 식별자, 처리 상태를 추적할 수 있어야 한다.

사용자의 사건 원문이나 개인정보는 백그라운드 임베딩 작업과 운영 로그에 불필요하게 복제하지 않는다.

API 키 및 인증정보는 로그에 노출하지 않는다.

---

# 16. 안전한 배포 및 롤백

신규 워크플로는 Feature Flag로 활성화한다.

### 배포 절차

1. 신규 DB 테이블 및 컬렉션 생성
2. 기존 법령 데이터 보존 확인
3. 신규 Law Resolver 단독 테스트
4. 신규 검색 결과와 기존 검색 결과 비교
5. 공식 검색 및 시행일 검증 테스트
6. Shadow Mode에서 결과 기록
7. 제한된 테스트 상담에 신규 워크플로 적용
8. E2E 회귀검증
9. 기본 검색 경로 전환

### 롤백 정책

신규 워크플로가 오류를 발생시키면 Feature Flag를 비활성화하여 기존 경로로 복귀한다.

롤백 시 신규 적재 법령을 삭제할 필요는 없다.

단, 이미 시작된 HILT 상담은 해당 Checkpoint의 그래프 버전과 호환되는 실행 환경에서 완료하거나 명시적으로 안전 종료해야 한다. 실행 중인 Checkpoint를 구조가 다른 그래프에서 무조건 재개하지 않는다.

법령 적용시점 오류가 확인되면 성능 지표와 무관하게 신규 경로 사용을 중단한다.

---

# 17. 개발 결과물 및 평가 증빙

각 Phase 완료 시 다음 자료를 제출한다.

**개발 결과물**

- 변경 소스 파일 목록
- 신규 데이터 모델 및 Alembic 마이그레이션
- 신규 인터페이스·상태 계약
- 단위 테스트 코드
- 통합 테스트 코드
- 회귀 테스트 결과
- 필요 환경변수 및 실행 명령
- Docker 및 Worker 운영 방법
- Feature Flag와 롤백 방법

**평가 증빙**

- 문제 정의
- 기존 구조의 한계
- 대안 비교 및 기술 선택 이유
- 변경 전후 아키텍처
- 구현 내용과 핵심 소스
- 테스트 시나리오
- 실제 Langfuse Trace
- LLM 호출·토큰·응답시간 비교
- 법령 적용시점 정답률 비교
- 확인된 한계 및 향후 개선 방향

### AI Master 평가용 핵심 기술 설명

**Agentic RAG:** 전문 Agent가 사건 쟁점을 분석하고 필요한 법률 근거를 활용한다.

**Adaptive RAG:** 현재 Vector 근거가 불충분하면 공식 법령 검색으로 전환한다.

**GraphRAG:** 사건 증거·사실·주장 관계를 분석에 반영한다.

**Temporal Legal RAG:** 공식 법령 버전과 조문별 시행일·부칙·적용례를 사건의 법률적 기준일에 대조한다.

**Verification:** 최종 답변의 출처, 사건 사실, 법령 적용시점을 독립적으로 재검증한다.

**Asynchronous Knowledge Ingestion:** 새로 조회한 법령을 별도 Worker로 적재하여 향후 상담에 재사용한다.

---

# 18. 최종 완료 조건 — Definition of Done

전체 개발은 다음 조건을 모두 만족할 때 완료한 것으로 판단한다.

- [ ] 기존 8개 Agent가 정상 동작한다.
- [ ] 동적 Agent를 생성하지 않는다.
- [ ] Agent가 특정 분야 Vector 컬렉션에 직접 종속되지 않는다.
- [ ] 전체 법령 카탈로그를 통해 미적재 법령을 식별한다.
- [ ] Vector에 없는 법령을 HILT 승인 후 공식 검색한다.
- [ ] 법령의 공포일·시행일·조문별 시행일을 구분한다.
- [ ] 부칙·적용례·경과규정이 검색 및 검증에 반영된다.
- [ ] 법령 버전별 원문을 보존한다.
- [ ] 사건 기준일과 법령 적용시점을 비교한다.
- [ ] 적용시점 미확인 시 확정적 법률 결론을 차단한다.
- [ ] 공식 검색 결과를 임베딩 전에도 답변에 사용한다.
- [ ] 독립 Embedding Worker가 동작한다.
- [ ] 동일 법령 버전의 임베딩이 중복 생성되지 않는다.
- [ ] 이후 상담에서 임베딩된 법령을 재사용한다.
- [ ] 기존 HILT·Checkpoint가 정상 동작한다.
- [ ] 기존 사건 분석·증거 승인·GraphRAG 기능에 회귀가 없다.
- [ ] 최신 법령 및 시행일 평가용 Gold 테스트를 통과한다.
- [ ] 기존 시스템과 개선 시스템의 품질·성능을 정량 비교한다.
- [ ] 변경 사항, 근거, 테스트 결과를 평가 문서에 반영한다.

**품질 게이트:** 시행일 또는 적용례에 관한 필수 회귀 테스트에서 오답이 하나라도 발생하면 해당 변경을 완료로 승인하지 않는다.

---

# 19. Codex / Antigravity 개발 지시사항

이 개발 작업지시서는 전체 구현의 상위 기준 문서로 사용한다.

개발자는 다음 사항을 반드시 준수한다.

1. 작업 전에 GitHub `main` 최신 상태를 다시 확인한다.
2. 개발용 브랜치에서 작업한다.
3. 기존 코드를 삭제하거나 워크플로를 전면 재작성하지 않는다.
4. 새로운 9번째 전문 Agent 또는 동적 Agent를 생성하지 않는다.
5. 기존 8개 Agent의 공개 계약과 기존 기능을 보존한다.
6. 법령명, 특정 시행일, 평가 질문을 대상으로 한 정답 하드코딩을 금지한다.
7. 법령 버전과 시행일을 공식 근거 없이 추정하지 않는다.
8. 최신 법령의 검색 성공과 실제 법령의 적용 가능성을 별도로 검사한다.
9. HILT 승인 없이 새로운 외부 검색 경로를 실행하지 않는다.
10. 기존 사건 데이터 및 Chroma 컬렉션을 삭제하거나 초기화하지 않는다.
11. 모든 신규 모듈·분기·예외 처리에 상세한 한국어 주석을 작성한다.
12. 기존 AOP 로깅과 Langfuse Trace를 유지한다.
13. 모든 Phase에서 테스트 및 전후 비교 결과를 기록한다.
14. 신규 기능으로 법률 정확성이 떨어질 경우 변경을 승인하지 않는다.
15. 성능 개선은 실제 Trace로 증명하며 추정 결과를 측정값으로 보고하지 않는다.
16. 각 Phase의 결과를 검토한 뒤 다음 Phase로 진행한다.
17. 승인된 단계만 `main`에 병합한다.

## 최종 개발 방향

**기존 8개 Agent는 유지한다.**

그러나 법률 지식 검색은 8개 분야의 고정 Vector 컬렉션을 넘어 대한민국 전체 법령을 대상으로 확장한다.

검색된 공식 법령은 **법령 버전, 조문별 시행일, 부칙, 적용례, 경과규정**을 구조화하여 사건의 기준일에 맞는 법률 판단에 활용한다.

새 법령은 독립 Worker가 버전별로 임베딩하고, 다음 상담에서 검색 근거로 재사용한다.

**이를 통해 AI Legal Helper는 단순 법령 검색 시스템이 아니라, 사건 발생 시점에 실제 적용되는 법령을 확인하고 그 근거로 해결 방향을 제시하는 AI 법률 도우미로 발전한다.**
