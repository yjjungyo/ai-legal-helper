# Temporal Legal RAG — P0 기준선·안전성 감사 (2026-11-02)

> **상태:** P0 소스 감사 및 테스트 기준선 코드 등록. **실제 pytest / DB / OpenLaw / Langfuse E2E 실행은 미수행.**
>
> **대상 기준:** `main` `cbea002e6c0eeebfcb1c953d8767b558d432a7c5`
>
> **개발 브랜치:** `feature/temporal-legal-rag-p0-baseline`
>
> **원칙:** 운영 `main`, PostgreSQL, Neo4j, ChromaDB 및 기존 법령 원문을 변경하지 않는다.

## 1. 이번 P0의 목적과 범위

확정된 아키텍처는 **기존 8개 전문 Agent 유지 + 검색 Tool과 Agent의 느슨한 결합 + 전체 법령 카탈로그 + 공식 법령 선행 검색 + 시점 검증 + 백그라운드 버전별 임베딩**이다.

이번 P0에서는 기능 구현 이전의 퇴행 위험과 기준선 수치를 분리한다. 기능 코드를 수정하지 않고 테스트 계약을 추가한다. 후속 Phase의 완료 판단은 실제 실행 로그 및 회귀 테스트 통과가 있어야 가능하다.

## 2. 코드에서 확인한 현재 계약

| 항목 | 실제 확인 사항 | 이후 보호/변경 정책 |
| --- | --- | --- |
| Router | `agents/router.py`는 `CATEGORIES` 8개를 허용하고 최대 3개 분야를 반환 | 8개 Agent 유지, 전체 법령 식별은 독립 서비스로 분리 |
| Agent | `agents/specialist.py`가 분야별 Agent 객체를 캐싱 | Agent 이름 및 기존 인터페이스 보존 |
| Tool | `rag/retrieval_factory.py`에서 분야별 단일 Chroma 컬렉션 검색 | 공통 LawRetrievalService 어댑터로 전환 |
| 실제 Tool 실행 | `agents/legal/base_agent.py` `AgentExecutor.invoke()`는 `tools[0]`만 실행 | 추가 Tool 연결만으로 검색이 확장된다고 가정하지 않음 |
| LangGraph | `plan → run_agents → synthesize → verification` | 필요한 법령을 최초 synthesize 전에 선행 검색 |
| HILT | 승인 및 공식 검색이 `verification_result` 후보 법령에 의존 | `legal_search_plan` 별도 계약 필요 |
| 공식 검색 | `search_official_statutes()`는 후보 법령명 필요, 날짜 인자를 전달받음 | 전체 카탈로그 식별 및 과거/시행예정 버전 조회 보완 |
| 현재 시간 메타 | `source_schema.py`에는 `law_id/version_id/promulgation_date/effective_date` 일부 존재 | 조문별 시행일·부칙·적용례·신뢰상태 별도 저장 |
| 위험한 기본값 | `is_statute_applicable_to_date()`가 날짜 누락 시 `True` 반환 | 적용 여부 3상 이상 판정 API로 교체 |
| 레거시 PDF | `chunker.py`는 법령 공통 `meta.effective_date`를 조문 청크에 기록 | 공식 조문별 날짜를 우선하고 불명은 미확인 처리 |
| 공식 출처 | `official_statute_search.py`는 공포번호·부칙 및 일부 조문 시행일을 추출 | 검증된 원문/부칙과 메타데이터를 보존하고 버전별 색인 |
| 기존 색인 | `rag/indexer.py`는 `reindex=True`일 때 컬렉션 삭제 가능 | 증분 Worker는 독립 구현, 기존 인덱스 삭제 금지 |
| 문서 상담 | `document_consultation.py`에 별도의 검증·재작성·Snapshot 계약 | 일반 상담 로직을 기계적으로 통합하지 않음 |

## 3. 성능 기준선: 재실측하지 않은 보고서 기록

근거 파일: `docs/evaluation/kpi/TRACE_COMPARISON_A99777E7_VS_9AA92B46.md`.

| 지표 | 이전 Trace `a99777e7` | 현행 비교 Trace `9aa92b46` |
| --- | ---: | ---: |
| 전체 실행시간 | 141.3초 | 220.2초 |
| LLM 추론시간 | 125.4초 | 201.6초 |
| 총 토큰 | 96,420 | 169,294 |
| 입력/출력 토큰 | 85,585 / 10,835 | 151,205 / 18,089 |
| 보고된 Generations | 5회 | 7회 |
| Verification 누적 | 68.9초 | 106.5초 |
| re_analyze 누적 | 41.7초 | 75.2초 |
| 공식 검색 노드 실행 | 1회 | 2회 |

**중요한 데이터 정합성 유의사항:** 기존 Trace 보고서에서 7회 Generation이라고 기록하면서, 같은 표의 설명은 `Router 1 + Plan 1 + Synth 1 + Verify 3 + Re-analyze 2 = 8`회로 합산된다. 실제 `plan_node`는 LLM 호출이 없는 결정론적 계획이다. 따라서 **Generation 총계는 원시 Langfuse Trace/TokenTracking 기록으로 다시 확인하기 전까지 검증된 성능 기준값으로 확정하지 않는다.**

위 수치는 기존 보고서의 **기록값**이며 P0 과정에서 실측하거나 개선 결과로 주장한 것이 아니다.

## 4. 테스트 기준선

추가 파일: `backend/tests/unit/test_temporal_legal_rag_p0_contract.py`.

### 기존 동작 보호 테스트

1. 8개 Agent 이름 및 분야별 Tool/컬렉션 매핑
2. 공식 법령 Source의 ID·버전·공포·시행 메타데이터 보존
3. 동일 공포번호에 해당하는 부칙만 연결
4. 명시적 조문 시행일의 우선순위
5. 시행일 전후에 대한 기존 날짜 비교 동작

### Known-gap 테스트 (xfail, 정상 PASS 아님)

1. 날짜 정보가 없는데도 시행 중으로 자동 승인하는 동작
2. PDF 파일명 날짜를 공식 조문 시행일과 동등하게 취급하는 동작

각 xfail은 **P1에서 해결하고 PASS로 전환해야 할 결함**을 나타낸다. xfail 상태를 완료로 보고하지 않는다.

기존 테스트에서 반드시 보존할 사항:

- `backend/tests/unit/test_statute_temporal_p0_law_02.py`
- `backend/tests/unit/test_official_statute_search.py`
- `backend/tests/integration/test_router_workflow.py`
- 문서 Snapshot/승인 및 HILT Resume 관련 테스트

## 5. 실행 방법

기존 프로젝트 의존성이 설치된 로컬 개발 환경에서 실행한다.

```powershell
cd backend
python -m pytest -q tests/unit/test_temporal_legal_rag_p0_contract.py tests/unit/test_statute_temporal_p0_law_02.py
python -m pytest -q tests/integration/test_router_workflow.py
```

실제 OpenLaw 호출 테스트는 개발용 API 키와 네트워크 환경을 별도로 준비하여 실행한다. 외부 API 없이도 테스트 가능한 고정 XML 픽스처를 우선 활용한다.

P0 작성 환경에서는 GitHub 소스 열람·변경이 가능하지만 **프로젝트 전체 저장소 및 의존성/DB를 실행할 수 있는 환경이 확보되지 않아 실제 테스트 통과 여부를 검증하지 못했다.**

## 6. 후속 단계 진입 게이트

P1에 진입하기 전에 최소 다음 사항을 확인해야 한다.

- 기존 8개 Agent 계약 테스트 PASS
- 공식 Source 메타데이터 보존 테스트 PASS
- 조문 시행일·부칙 테스트 PASS
- 기존 일반 상담 Router 회귀 테스트 PASS
- 두 건의 known-gap xfail 상태 확인 및 해결 계획 유지
- 테스트 실행의 실제 결과와 Git SHA 기록
- HILT 승인/거절을 포함한 후속 통합 테스트 대상 식별
- 현행 Trace에 대한 실제 Generation 분해 및 Critical Path 검증 계획

**다음 개발 단계(P1):** 법령 시간 메타데이터 계약과 명시적인 `APPLICABLE / NOT_APPLICABLE / UNCONFIRMED` 판단 API를 추가하고, 레거시 함수의 조용한 fail-open 위험을 제거한다. 적용시점이 복잡한 부칙은 자동으로 확정하지 않고 원문·판단 근거·불확실성을 보존한다.

## 7. 변경 이력

- P0 개발 브랜치 생성
- P0 계약 테스트 및 알려진 위험 xfail 추가
- 재실측 전 성능 보고 수치를 사실/추정으로 명확히 구분
- 실제 운영 소스, 기존 법령 컬렉션, DB 및 `main` 미수정
