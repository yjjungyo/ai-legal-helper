# Temporal Legal RAG — P1 법령 메타데이터·시행일 판정 API 구현 보고

작성일: 2026-11-02  
기준선: P0가 병합된 `main` 커밋 `c5020c18566261a57933095e9a7bae36bb28a0ef`  
작업 브랜치: `feature/temporal-legal-rag-p1-metadata`

## 1. 문제 정의

AI Legal Helper는 최신 법령만 검색해서는 법률적 정확성을 보장할 수 없다. 법령이 공포되었더라도 시행일까지 유예될 수 있고, 개별 조문의 시행일 및 부칙 적용례가 법령 전체의 시행일과 다를 수 있다.

기존 코드에서는 PDF 파일명에서 추출한 날짜를 `effective_date`에 복사하고, `is_statute_applicable_to_date()`는 시행일을 알 수 없을 때도 `True`를 반환할 수 있었다.

따라서 날짜 **비교**와 법률 **적용 가능 판정**을 분리한다.

## 2. 구현 항목

### 2.1 3상 법령 적용 판정

신규 모듈: `backend/src/ai_legal_helper/rag/temporal_applicability.py`

- `ApplicabilityStatus.APPLICABLE`
- `ApplicabilityStatus.NOT_APPLICABLE`
- `ApplicabilityStatus.UNCONFIRMED`
- `evaluate_statute_applicability(source, event_date, event_type=None)`
- `parse_legal_date()`
- `ApplicabilityDecision.as_dict()`

임의의 법률 효과를 계산하지 않으며, **공식 조문 시행일의 출처와 적용례 검토 상태가 확인되지 않으면 긍정 적용 판정을 금지**한다.

`APPLICABLE`은 `effective_date_basis`가 `ARTICLE_EFFECTIVE_DATE` 또는 `ADDENDUM_EFFECTIVE_DATE`이고, `temporal_status=VERIFIED`이며, 사건 기준일 및 지정된 사건 유형이 검토를 통과한 경우에만 허용한다.

적용례 또는 경과규정이 미확인이라면 `UNCONFIRMED`를 반환한다. 조문 시행일 전에 대한 `NOT_APPLICABLE`은 검증된 조문 시행일과 비교한 결과이며, 소급효 검토가 필요하다고 표시된 경우는 `UNCONFIRMED`로 보류한다.

### 2.2 Source 메타데이터 확장

수정: `rag/source_schema.py`

추가 항목:

- `law_type`
- `law_effective_date`
- `article_effective_date`
- `effective_date_basis`
- `effective_to` (종료일은 독점 상한, 확인된 값만 사용)
- `filename_date_hint`
- `addendum_id`
- `applicability_rule_id`
- `transitional_rule_id`
- `applicability_event_type`
- `retroactivity_review_required`
- `temporal_status`
- `metadata_confidence`
- `content_hash`

기존 `source_id`, `law_id`, `version_id`, `promulgation_date`, `effective_date` 및 출처 UI 계약은 유지한다.

`normalize_source_dict()`와 `build_source_from_chroma_doc()`가 이 항목을 보존하도록 변경한다.

### 2.3 레거시 PDF 날짜 추정의 차단

수정: `rag/chunker.py` (Fixed-size, Article-aware, Parent-child 전체 전략)

- PDF 파일명에서 추출한 날짜를 **조문 시행일로 저장하지 않는다.**
- `filename_date_hint`로 분리한다.
- `effective_date_basis=FILENAME_INFERRED`
- `temporal_status=UNCONFIRMED`
- 레거시 `version_date`는 호환 목적으로 남지만 적용시점 판정 근거로 사용하지 않는다.

기존 이미 생성된 Chroma 레거시 청크는 자동으로 수정하지 않는다. 그 마이그레이션은 후속 P10에서 수행한다.

### 2.4 공식 조문 시행일 출처 보존

수정: `tools/official_statute_search.py`

- 공식 XML `조문시행일자`가 있다면 우선한다.
- 해당 공포번호의 부칙에서 안전하게 계산할 수 있는 시행일은 출처를 기록한다.
- 개별 조문 시행일 미확인 시 법령 전체 시행일을 자동 대입하지 않는다.
- `law_effective_date`와 `article_effective_date`를 분리한다.
- `effective_date_basis` 및 `temporal_status`를 전달한다.
- 공식 검색으로 시행일을 확보해도 적용례·경과규정 검토 전에는 `EFFECTIVE_DATE_VERIFIED`에만 둔다.
- 해당 버전의 부칙과 연결할 수 있는 공포번호·버전 정보는 유지한다.

### 2.5 레거시 Boolean API

기존 `is_statute_applicable_to_date()` 함수는 반환 타입 호환성 유지를 위해 남겨두었다.

- 시행일 없음 또는 사건일 파싱 실패 시 `False`로 **fail closed**한다.
- 더 이상 `version_date` 또는 `promulgation_date`를 `effective_date`의 대체 값으로 사용하지 않는다.
- 현재 이 함수는 **단순 날짜 전후 비교**일 뿐 법률적 적용 확정 API가 아니다.
- 신규 개발에서는 반드시 3상 `evaluate_statute_applicability()`를 사용한다.

기존 단위 테스트가 공식 `effective_date`를 가지고 단순 날짜 비교를 수행하는 사례와의 호환은 유지한다.

## 3. 신규 테스트

| 파일 | 검증 항목 |
| --- | --- |
| `test_temporal_legal_rag_p1.py` | 날짜 파싱·3상 판정·부칙 검토 필요·출처 보존·이벤트 유형·종료일 |
| `test_official_statute_temporal_metadata_p1.py` | 공식 XML의 조문별 시행일과 부칙 예외, 법령 공통 시행일의 잘못된 대입 차단 |
| `test_temporal_chunker_p1.py` | 세 가지 PDF 청킹 전략에서 날짜 추정값 격리 |
| `test_temporal_legal_rag_p0_contract.py` | 이전 xfail 2개를 필수 PASS 테스트로 전환 |

모든 신규 테스트는 실제 유료 LLM 호출이나 외부 OpenLaw 조회 없이 Mock/픽스처 기반으로 수행되도록 작성하였다.

### 실행 명령

```powershell
cd backend
python -m pytest -q tests/unit/test_temporal_legal_rag_p0_contract.py tests/unit/test_temporal_legal_rag_p1.py tests/unit/test_official_statute_temporal_metadata_p1.py tests/unit/test_temporal_chunker_p1.py tests/unit/test_statute_temporal_p0_law_02.py tests/unit/test_p1_defects_reproduction.py
```

`test_p1_defects_reproduction.py` 일부 항목은 로컬 PostgreSQL 및 기타 실행환경을 필요로 한다. 실제 구성에서 테스트한다.

## 4. 검증 상태 구분

- GitHub 소스 수정·커밋 및 코드 경로 검토: **수행**
- 로컬 Python 표준 라이브러리만으로 복제한 3상 판정 핵심 로직 Smoke 테스트: **14건 PASS**
- 저장소 실제 소스의 전체 `pytest` 실행: **미수행** (현재 컨테이너에 LangChain/LangGraph/ChromaDB 및 프로젝트 실행환경 미설치)
- PostgreSQL·ChromaDB 데이터 마이그레이션 및 외부 OpenLaw E2E: **미수행**

Smoke 테스트는 로컬에 재현한 순수 함수 로직에 대한 확인이며, 원본 저장소 전체 테스트의 통과를 의미하지 않는다. 따라서 회귀 테스트가 전부 통과했다고 보고하지 않는다.

## 5. 명시적인 미완료 범위

- Law Catalog 및 전체 법령 식별: P2
- 공통 Law Retrieval Service 및 8개 Agent 연결: P3
- 시행일 기준 공식 법령 연혁 조회 심층화: P4
- 부칙 적용례·경과규정의 실제 법적 요건 판정: P5
- LangGraph 선행 검색 및 HITL 연결: P6
- Verification의 3상 API 적용 및 오판정 차단: P8
- PostgreSQL 법령 카탈로그·버전 관계·작업 큐 마이그레이션: P2/P9
- 백그라운드 법령 임베딩·기존 Vector 마이그레이션: P9/P10

P1 구현만으로 실제 사용자 답변의 법령 적용시점 정확도가 개선되었다고 주장하지 않는다. **현재 상담 경로와 새로운 3상 판정의 연결 전에는 제품 차별화 기능이 완성되지 않았다.**

## 6. 변경 완료 기준

P1은 코드 작성과 테스트 자산 준비까지 수행했다. 병합 후에도 다음 검증 게이트는 유지한다.

- 신규·기존 테스트 전체 PASS
- 기존 문서/사건 상담 및 HITL 회귀 PASS
- 공식 XML에서 조문별 시행일·부칙·법령 대표 시행일의 불일치 테스트 PASS
- 기존 법령·사건 데이터 손실 없음
- 임베딩 메타데이터 기준으로 확인된 시행일만 `APPLICABLE` 판정
- Langfuse Trace 측정을 위한 코드 버전 기록

후속 P2 진입 전에 실제 개발환경에서 pytest를 실행하고 실패 여부를 기록해야 한다.
