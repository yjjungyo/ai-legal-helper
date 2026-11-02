# Temporal Legal RAG — P2 공식 법령 카탈로그 및 Law Resolver 개발 결과

**작성:** 2026-11-02  
**소스 기준:** P1 병합 `b7425a58f10fc0967d9f717d8144442ff454459d`  
**개발 브랜치:** `feature/temporal-legal-rag-p2-law-catalog`

## 1. 문제 및 해결 전략

기존 AI Legal Helper는 8개 전문 Agent와 분야별 Vector 컬렉션이 결합되어 있어,
법률 분야 분류가 맞더라도 해당 법령이 Vector에 없으면 식별·조회가 어려울 수 있다.

**P2 목표:** Agent와 Vector 적재 여부에 종속되지 않는 공식 법령 ID·정식 법령명·법령약칭
색인을 PostgreSQL에 구축하고, 질문에서 공식 법령 후보를 정확히 식별한다.

- **Agent:** 기존 8개 그대로 유지. 동적 Agent 생성 금지
- **법령 식별:** Law Catalog + Law Resolver (신규)
- **Vector/OpenLaw 본문 검색:** 기존 기능 유지, 공통 검색 전환은 P3/P4
- **법률 적용시점:** P1 3상 API 유지, P5 Temporal Resolver에서 통합
- **백그라운드 임베딩:** P9 독립 Worker로 분리

이 단계에서는 새로운 LLM 프롬프트나 불필요한 LLM 호출이 추가되지 않는다.

## 2. 구현 산출물

| 파일 | 변경 목적 |
| --- | --- |
| `database/models.py` | 공식 법령명·별칭·동기화 이력 ORM 모델 3종 |
| `alembic/versions/90d4e30c2a71_add_official_law_catalog.py` | 기존 데이터 무수정 신규 테이블 마이그레이션 |
| `legal_knowledge/law_catalog.py` | 공식 목록 XML 파싱·정규화 및 페이지별 API |
| `legal_knowledge/catalog_store.py` | 중복 없는 PostgreSQL Upsert·관리자 전체 동기화 |
| `legal_knowledge/law_resolver.py` | 공식 법령명·약칭·복수/모호성 식별 |
| `scripts/sync_law_catalog.py` | 명시적 관리자 동기화 명령 |
| `tests/unit/test_law_catalog_p2.py` | 공식 API Mock/SQLite 기반 테스트 |
| `tests/unit/test_law_catalog_migration_p2.py` | Alembic 업그레이드·다운그레이드 테스트 |
| `.github/workflows/temporal-legal-rag-p2.yml` | P2 GitHub Actions 테스트 자동화 |

## 3. 저장 구조

### law_catalog

공식 지속 법령 ID(`law_id`)를 PK로 하여 법령명, 법령종류, 최신 목록 MST,
공식 약칭 및 목록 공포일·시행일을 저장한다.

**중요:** 목록의 `list_effective_date`는 조문별 시행일 및 실제 사건 적용 가능 시점이 아니다.
해당 날짜만으로 법률 효과를 확정해서는 안 된다.

### law_catalog_aliases

공식 `법령약칭명`과 별도 검토 승인 별칭을 각각 보관한다.
동일 약칭이 여러 법령ID에 매핑되는 경우 전역 unique 제약을 강제하지 않는다.
Law Resolver가 `AMBIGUOUS`로 반환하며 임의의 한 법령을 선택하지 않는다.

### law_catalog_sync_runs

관리자의 수집 시작/종료, 대상, 예상 총건수, 처리 페이지, 실패 코드,
`COMPLETE/PARTIAL/FAILED` 상태를 저장한다. 이력이 있다고 전체 법령을 수집한 것은 아니다.

## 4. 법령 식별 규칙

`LawResolver.resolve(question, suggested_laws=...)`는 **오직 로컬 카탈로그**를 읽는다.

| 상태 | 의미 |
| --- | --- |
| FOUND | 공식 법령명 또는 약칭을 질문에서 직접 식별 |
| MULTIPLE | 서로 다른 법령을 질문에서 명시 |
| AMBIGUOUS | 하나의 명칭·약칭에 복수 법령ID가 매핑 |
| SUGGESTED | LLM 제안이 공식 카탈로그의 법령명/별칭과 정확히 일치 |
| NO_MATCH | 로컬에서 관련 법령명을 확인하지 못함 |
| CATALOG_EMPTY | 아직 공식 법령 목록이 적재되지 않음 |

위 결과는 **법령 검색 후보**다. 조문 내용·개정 이력·시행일·적용례 검증 완료가 아니다.

예: `주택임대차보호법` → 해당 법령 ID 후보 발견 → 같은 이름 기초를 가진
`주택임대차보호법 시행령`, `주택임대차보호법 시행규칙`을 관계 *후보*로 제시.
이 이름 기반 후보는 법률상 위임·적용 관계를 확정하지 않는다.

`민법`과 `난민법`의 부분 문자열 혼동을 차단한다.
질문에 없는 법령을 LLM의 상상만으로 새 공식 법령으로 등록하지 않는다.

법령명이 없는 추상적 법률 질문은 카탈로그만으로 항상 정확한 법령을 식별할 수 없다.
이 경우 `NO_MATCH`를 반환하며 후속 승인된 공식 검색·의미검색으로 보강해야 한다.

## 5. 운영 적용 명령 (로컬 환경)

### 5.1 DB 마이그레이션

기존 PostgreSQL이 실행 중이고 `DATABASE_URL`이 설정된 상태에서:

```powershell
cd backend
python -m alembic upgrade head
python -m alembic current
```

운영 DB에 실제로 실행하기 전에 별도 백업 및 직전 Alembic 버전 확인을 권장한다.
P2 마이그레이션은 신규 테이블만 생성하며 기존 사건 테이블과 Chroma 컬렉션을 수정하지 않는다.

### 5.2 법령 목록 1페이지 시험 수집

```powershell
cd backend
python scripts/sync_law_catalog.py --max-pages 1
python scripts/sync_law_catalog.py --execute --max-pages 1
```

첫 번째 명령은 DRY RUN이다. 두 번째는 실제 API 호출·DB Upsert를 실행한다.
단, 전체 수집은 아니므로 `PARTIAL`로 기록되며 종료 코드는 1일 수 있다.

### 5.3 전체 현행법령 목록 수집

```powershell
cd backend
python scripts/sync_law_catalog.py --execute --max-pages 0
```

사전에 `LAW_OPENAPI_KEY`를 설정한다. 공식 API는 페이지별 `display=100`, `page`를
제공한다. `totalCnt`에 도달할 때까지 조회하며 최대 1,000페이지 안전 상한을 둔다.

**완료 확인:** CLI의 `COMPLETE`, `items_seen=total_expected` 및
`law_catalog_sync_runs`의 마지막 전체 동기화 완료 상태를 확인한다.
정상 호출 후에도 조문 본문과 시행일/부칙은 아직 적재하지 않았으므로
Temporal Law RAG 품질 검증이 완료된 것으로 표시하지 않는다.

### 5.4 재동기화

동일 법령 ID는 Upsert하고 공식 약칭을 갱신한다. 여러 페이지에서 동일 법령 ID가 반복 발견되면 전수 누락 가능성이 있으므로 전체 수집 COMPLETE 판정을 금지한다. 기존 검토 승인 별칭은 유지한다.
과거의 공식 별칭이 변경되면 현재 공식 목록에 없는 별칭은 자동으로 검색하지 않는다.

## 6. 테스트·검증 증빙

- CI 워크플로: `Temporal Legal RAG P2 regression`
- GitHub Actions 최초 실행: 18 PASS
- P2 신규 Alembic 업그레이드·롤백 및 중복 법령ID 검사 추가 후: **20 PASS**
- 네트워크/유료 LLM/운영 DB 접근 없이 Mock XML·SQLite로 통과
- 간헐적으로 pytest-asyncio 설정 및 GitHub Node.js 런타임 관련 경고 발생하나 테스트 실패는 없음

**미실행:** 실제 OpenLaw API 전체 수집, 운영 PostgreSQL Alembic upgrade, UI/E2E 통합,
실제 8개 Agent 실행 및 P2 신설 기능이 상담 지연에 미치는 영향 측정.

이런 미실행 항목을 완료했다고 보고하지 않는다.

## 7. 다음 단계 P3로 인계할 인터페이스

- `LawCatalogStore(session).all_entries()`
- `LawResolver(LawCatalogStore(session)).resolve(question, suggested_laws=...)`
- `LawResolution.status`, `laws`, `family_suggestions`,
  `official_search_required`
- `ResolvedLaw.law_id`, `law_name`, `current_mst`

P3는 이 검색 후보와 기존 8개 Agent의 검색 경로를 분리해 공통
`LawRetrievalService`로 연결한다. 본문 부족/버전 미확인 시
승인을 요청하는 판단은 P4/P6에서 담당한다. **HILT 승인 없이 새 외부
검색 호출을 Agent Tool에 숨겨 넣지 않는다.**

## 8. 품질·회귀 위험과 제한

1. 공식 API 키 없는 환경에서 전체 동기화는 수행할 수 없다.
2. 법령 목록이 `PARTIAL`이면 없는 법령을 없다고 단정할 수 없다.
3. 공식 목록은 기본적으로 현행법령(`target=law`)이며 과거·시행예정의
   실제 적용 버전은 별도 P4 시행일 법령 조회로 보강해야 한다.
4. 질문이 구어체 쟁점만 포함하고 법령명/공식 별칭이 없으면 로컬
   명칭 검색만으로 정답을 보장하지 않는다. 후속 Vector/공식 검색 필요.
5. 초기 동기화와 마이그레이션은 사용자의 로컬 개발환경에서
   실제 실행·검증을 추가해야 한다.
6. 신규 기능은 현행 LangGraph 워크플로에 연결하지 않았으므로
   P2 구현만으로 상담 출력 품질·속도가 변경되었다고 주장하지 않는다.

**P2 완료 범위:** 공식 목록 수집·정규화·영속화·법령명 Resolver·오프라인
자동 테스트. P3 공통 검색 및 P4~P5 공식 법령 시행일 적용 검증은 후속 개발.
