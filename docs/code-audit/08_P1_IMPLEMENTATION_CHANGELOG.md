# P1 결함 수정 구현 변경 내역 보고서 (P1 Implementation Changelog)

**작성일시:** 2026-10-18  
**대상 단계:** P1 (신뢰성 및 논리 개선 — P1-01 ~ P1-06)  
**수행자:** Gemini Antigravity  
**원칙 준수:** 하드코딩 금지, 무검증 성공 보고 금지, 기존 API/DB 하위 호환성 유지, 한국어 주석 표준 준수

---

## 1. 개요 및 구현 범위 요약

| 항목 ID | 결함 및 개선 대상 | 수정 파일 | 주요 변경 내용 |
|---|---|---|---|
| **P1-01** | 검색 결과와 검색 장애 미구분 | `rag/retrieval.py`, `rag/retrieval_factory.py` | `RetrievalStatus` Enum 및 `RetrievalResult` 도입. 컬렉션 부재(`COLLECTION_MISSING`)와 연결 장애(`RETRIEVER_UNAVAILABLE`)를 일반 검색 결과 없음(`NO_MATCH`)과 명확히 분리 |
| **P1-02** | 법령 시행일 및 버전 관리 누락 | `rag/source_schema.py`, `tools/official_statute_search.py` | `law_id`, `version_id`, `promulgation_date`, `promulgation_number`, `effective_date` 보존 및 `is_statute_applicable_to_date()` 함수를 통한 사건 당시 시행 여부 판정 로직 구현 |
| **P1-03** | Source Registry 및 Citation Validator 고도화 | `agents/verification.py` | 공식 법령 인용 정규식(`STATUTE_CITATION_PATTERN`) 도입, 법률 효과 왜곡(기간 유예 vs 즉시 효력 모순) 탐지, 인용 없는 답변의 제로 분모 `N/A` 및 `citation_coverage_rate` 산출 |
| **P1-04** | 차별화된 Adaptive Retrieval 분기 | `workflows/legal_workflow.py` | 검색 인프라 장애 시 무한 루프 차단 및 `insufficient` 안전 전이, 법령 부재 시에만 HILT 승인 요청(`statute_search_approval`), 사실관계 부족 시 사용자 증거 요청 |
| **P1-05** | 3계층 상태 모델 분리 | `database/models.py`, `api/schemas/consultation.py`, `api/routes/consultation.py`, `frontend/src/types/consultation.ts` | 단일 `status` 혼재를 `execution_status`, `verification_status`, `answer_status` 3계층으로 분리하여 파이프라인 완료와 법률적 답변 유보 상태의 모순 해소 |
| **P1-06** | 동시 승인 호출 원자적 차단 | `api/routes/consultation.py` | PostgreSQL 원자적 조건부 UPDATE (`WHERE request_id = :id AND status = 'APPROVAL_REQUIRED'`)를 통한 동시 다중 승인/Resume 중복 가동 방지 (409 Conflict 반환) |

---

## 2. 파일별 세부 변경 내역

### 2.1 `backend/src/ai_legal_helper/rag/retrieval.py`
- `RetrievalStatus` 열거형 추가:
  - `SUCCESS`: 정상 검색 완료
  - `NO_MATCH`: 쿼리와 일치하는 문서 없음 (지식 부재)
  - `COLLECTION_MISSING`: 카테고리 인덱스 컬렉션 부재 (인프라 설정 오류)
  - `RETRIEVER_UNAVAILABLE`: ChromaDB 서버 연결 오류 또는 검색 엔진 불능
  - `EMBEDDING_ERROR`: 임베딩 생성 실패
  - `CONFIGURATION_ERROR`: 잘못된 설정값
- `RetrievalResult` 데이터클래스 정의 (`status`, `documents`, `query`, `category`, `error_detail`).
- `retrieve_with_status()` 신설: 컬렉션 부재 및 ChromaDB 연결 예외를 포착하여 적절한 `RetrievalStatus` 반환.
- 기존 `retrieve()` 함수는 `retrieve_with_status()`를 래핑하여 100% 하위 호환성 유지.

### 2.2 `backend/src/ai_legal_helper/rag/retrieval_factory.py`
- `make_fixed_retrieval_tool._run`에서 `retrieve_with_status`를 호출하여 인프라 장애 발생 시 사용자/에이전트에 명확한 에러 안내 반환:
  - `[검색 인프라 장애: 컬렉션 부재] ...`
  - `[검색 인프라 장애: 서비스 연결 오류] ...`
- 기존 단위 테스트 Mocking(`unittest.mock.patch`)과의 완벽한 하위 호환성 유지 로직 추가.

### 2.3 `backend/src/ai_legal_helper/rag/source_schema.py`
- `StandardSource` 스키마에 법령 메타데이터 필드 보강:
  - `law_id`: 법제처 법령 고유 ID (예: "001684")
  - `version_id`: 법령 일련번호/MST (예: "276291")
  - `promulgation_date`: 공포일자 (YYYY-MM-DD)
  - `promulgation_number`: 공포번호
- `normalize_source_dict`에서 상기 필드를 누락 없이 표준 정규화 딕셔너리로 보존.
- `is_statute_applicable_to_date(source_dict, target_date_str) -> bool` 신설:
  - 사건 발생일(또는 계약/해지 기준일)과 법령 시행일자(`effective_date`)를 비교하여 적용 대상 법령 여부 정밀 판정.

### 2.4 `backend/src/ai_legal_helper/tools/official_statute_search.py`
- 법제처 XML 응답에서 `법령ID`, `일련번호(MST)`, `공포번호`, `공포일자`, `시행일자`를 정밀 파싱.
- 검색된 각 조문 출처 딕셔너리에 `law_id`, `version_id`, `promulgation_date`, `promulgation_number`를 일관되게 주입.
- 가상의 PDF 파일명 의존을 줄이고 법령 공식 식별자 기반 메타데이터 표준화.

### 2.5 `backend/src/ai_legal_helper/agents/verification.py`
- `STATUTE_CITATION_PATTERN = re.compile(r"\(+\s*([가-힣]+(?:법률|법|시행령|시행규칙))\s+(제\s*\d+\s*조(?:\s*의\s*\d+)?)\s*\)+")` 추가:
  - `(주택임대차보호법 제6조의2)` 등의 공식 법령 조문 인용 형식 정규식 파싱 지원.
- `_check_claim_supported_by_source` 고도화:
  - 법률 효과 반대 왜곡 탐지: 출처 본문의 기간 유예 요건(예: "3개월이 지나면 효력이 발생")과 초안의 즉시/당일 효력 발생 주장("도달 즉시 효력이 발생") 간의 모순을 감지하여 `LEGAL_EFFECT_CONTRADICTION`으로 즉각 거절.
- `_extract_containing_segment` 문장 경계 보정:
  - 문장 종결 마침표 뒤에 붙은 인용(`...합니다. (법 제N조)`)의 경우 앞 문장을 정상 문맥으로 정확히 인식하도록 개선.
- 정량 평가 지표 제로 분모 처리:
  - 인용이 전혀 없는 답변에 대해 `citation_existence_rate`와 `citation_support_rate`를 `N/A`로 표기 (100% 왜곡 방지).
  - 실질 본문 문장 대비 인용 문장 비율인 `citation_coverage_rate` 지표 산출.

### 2.6 `backend/src/ai_legal_helper/workflows/legal_workflow.py`
- `verification_condition` 분기 함수 고도화:
  - `reason_code in ("RETRIEVER_UNAVAILABLE", "COLLECTION_MISSING")`: 검색 인프라 장애 시 무의미한 외부 API 호출이나 무한 루프를 방지하고 `insufficient` 노드로 안전 전이.
  - `LEGAL_SOURCE_MISSING`: 공식 법령 조문 검색이 필요하므로 `statute_search_approval` 노드로 HILT 전이.
  - `CASE_EVIDENCE_MISSING`: 사건 사실관계 및 증거 수집 노출을 위해 `insufficient` 노드로 전이.
  - `ANSWER_REVISION_REQUIRED`: 초안 수정이 가능한 경우 `revise` 노드로 재작성 루프 진행.

### 2.7 `backend/src/ai_legal_helper/database/models.py`
- `ConsultationRecord` ORM 모델에 3계층 상태 컬럼 추가:
  - `execution_status = Column(String(50), default="IN_PROGRESS", nullable=True)`
  - `verification_status = Column(String(50), nullable=True)`
  - `answer_status = Column(String(50), default="WITHHELD", nullable=True)`

### 2.8 `backend/src/ai_legal_helper/api/schemas/consultation.py`
- `ConsultationResponse` Pydantic 스키마에 3계층 상태 필드 반영:
  - `execution_status: Optional[str] = "COMPLETED"`
  - `verification_status: Optional[str] = None`
  - `answer_status: Optional[str] = None`
- `Source` 스키마에 `law_id`, `promulgation_date`, `promulgation_number`, `version_id` 필드 추가.

### 2.9 `backend/src/ai_legal_helper/api/routes/consultation.py`
- `decide_statute_search_approval` 원자적 중복 방지 가드:
  - SQLAlchemy `UPDATE ... WHERE request_id = :id AND status = 'APPROVAL_REQUIRED'` 원자적 쿼리 실행.
  - 갱신 대상 행 수가 0인 경우 409 Conflict 반환하여 다중 동시 승인 호출 차단.
- `start_consultation`, `process_consultation`, `process_consultation_resume`, `get_consultation`, `list_case_consultations`:
  - 3계층 상태(`execution_status`, `verification_status`, `answer_status`)를 일관되게 생성 및 DB 영구 저장.
  - Langfuse `N/A` 문자열 메트릭 로깅 시 float 변환 예외 안전 처리.

### 2.10 `frontend/src/types/consultation.ts`
- `Source` 및 `ConsultationResponse` 인터페이스에 백엔드와 동일한 3계층 상태 및 법령 메타데이터 필드 추가.

