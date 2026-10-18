# Phase P2 구현 변경 이력서 (Implementation Changelog)

**프로젝트명:** AI Legal Helper  
**문서 버전:** 1.0.0  
**작성일자:** 2026-10-18  
**적용 범위:** Phase P2 — 품질 및 평가 고도화 (`P2-01`, `P2-02`, `P2-03`)  
**표준 준수:** `docs/development/CODING_COMMENT_STANDARD.md` (한국어 Google Style Docstring / TSDoc)

---

## 1. 개요 및 목적

Phase P2는 `AI Legal Helper 소스코드 결함 수정 및 품질 고도화 개발지시서`에 명시된 검색 품질, 관측 가능성(Observability), 사용자 경험 및 답변 구조화 항목을 체계적으로 해결하였다.
모든 구현은 특정 사례(SC-001)에 국한된 하드코딩을 엄격히 금지하고 범용적인 패턴 매칭, 하이브리드 리랭킹, 개인정보 마스킹, 안전한 마크다운 파서로 설계되었다.

---

## 2. 세부 변경 내역

### 2.1 P2-01: 검색 품질 개선 (하이브리드 리랭킹 및 중복 청크 제거)

- **수정 파일:** [`backend/src/ai_legal_helper/rag/retrieval.py`](../../backend/src/ai_legal_helper/rag/retrieval.py)
- **주요 변경 사항:**
  1. `deduplicate_chunks`:
     - 텍스트 자카드(Jaccard) 어휘 유사도 기반 중복 청크 제거 함수 추가 (기본 임계치 `similarity_threshold=0.85`).
     - 동일 컬렉션 또는 다중 컬렉션 간 중복된 조문/판례 청크를 효과적으로 필터링하여 컨텍스트 윈도우 낭비 방지.
  2. `rerank_with_article_and_keywords`:
     - 하이브리드 리랭킹 알고리즘 구현.
     - 종합 점수 계산 공식:
       $$\text{Score} = (\text{Dense Score} \times 0.60) + (\text{Article Boost} \times 0.25) + (\text{Lexical Overlap} \times 0.15)$$
     - 질의 내에 조문 번호(예: `제6조의2`, `제10조의8` 등)가 존재하고 검색 문서의 메타데이터 또는 본문에 해당 조문이 일치하는 경우 가중치 +0.25 부여.
     - 질의 키워드 토큰과 문서 내용 간 어휘 중첩 비율에 따라 최대 +0.15 가중치 부여.
  3. `retrieve_with_status`:
     - 단일 컬렉션 및 다중 컬렉션(Multi-collection) 검색 결과 파이프라인에 `deduplicate_chunks` 및 `rerank_with_article_and_keywords` 적용.
     - 검색 점수(`score`)와 근거 충분성 판별 기준 분리.

---

### 2.2 P2-02: Langfuse Observability 개선 (종합 Trace 요약 및 PII 마스킹)

- **수정 파일:**
  - [`backend/src/ai_legal_helper/observability/langfuse_client.py`](../../backend/src/ai_legal_helper/observability/langfuse_client.py)
  - [`backend/src/ai_legal_helper/api/routes/consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py)
- **주요 변경 사항:**
  1. `mask_pii`:
     - 민감 개인정보(주민등록번호 `\1-*******`, 휴대폰번호 `\1-****-\3`, OpenAI/Google/Langfuse API 키 `\1...****`)를 마스킹하는 정규식 필터 함수 구현.
     - Langfuse Trace 입력/출력 및 메타데이터에 원문 민감정보가 노출되지 않도록 전처리.
  2. `build_consultation_trace_summary`:
     - 단일 상담 Trace에서 전체 워크플로우를 한눈에 파악할 수 있는 표준 메타데이터 딕셔너리 빌더 구현:
       - 상담 요청 ID (`request_id`), 사건 ID (`case_id`)
       - 워크플로우 3계층 상태 (`execution_status`, `verification_status`, `answer_status`)
       - 참여 Agent 목록 (`selected_agents`), 재분석/재검증 횟수 (`revision_count`)
       - 검색 메트릭 (`retrieval`: 방법, 검색 건수, Source ID 목록)
       - 검증 메트릭 (`verification`: 상태, 거절 사유 코드, Citation 메트릭, 기각된 출처)
       - 토큰 및 지연시간 메트릭 (`usage`: 호출 횟수, 총 토큰, 경과시간 ms)
  3. `process_consultation` 및 `process_consultation_resume`:
     - 상담 시작 시 `start_trace`에 마스킹된 질문 전달.
     - 상담 완료 및 재개(Resume) 완료 시 `build_consultation_trace_summary`를 호출하여 루트 Span 메타데이터를 일관되게 갱신.

---

### 2.3 P2-03: 사용자 최종 답변 및 UI 개선 (구조화 답변 및 상태 배지 차별화)

- **수정 파일:**
  - [`frontend/src/components/LegalAnswerView.tsx`](../../frontend/src/components/LegalAnswerView.tsx)
  - [`frontend/src/components/ChatSection.tsx`](../../frontend/src/components/ChatSection.tsx)
- **주요 변경 사항:**
  1. `LegalAnswerView.tsx`:
     - 기존의 파괴적인 정규식 마크다운 제거(`cleanRawMarkdown`)를 폐지.
     - XSS 취약점 없이 안전하게 JSX 요소를 반환하는 경량 인라인 마크다운 파서 `renderInlineMarkdown` 구현 (`**볼드**`, `*이탤릭*`, `` `인라인 코드/조문` ``).
     - 개발지시서 권장 8대 구성요소 분류 및 전용 스타일링 지원:
       1. 사건 요약 (📋)
       2. 확인된 사실 (🔍)
       3. 법률 쟁점 (⚖️)
       4. 적용 법령 및 근거 (📜)
       5. 분석 결과 (💡)
       6. 불확실하거나 추가 확인이 필요한 사항 (⚠️ - 앰버 주의 박스)
       7. 다음 행동 (🚀 - 그린/블루 조치 카드)
       8. 검증된 출처 (📚)
     - 불릿(`- `, `• `), 번호 목록(`1. `, `가. `), 인용구(`> `) 내부 인라인 마크다운 서식 지원.
  2. `ChatSection.tsx`:
     - 전용 상태 배지 렌더러 `renderStatusBadge` 도입.
     - 기존에 `item.status === 'SUCCESS'`이면 무조건 "답변 완료(초록색)"로 표시되던 문제를 수정하여, `answer_status === 'WITHHELD'`(또는 `verification_status === 'FAIL'`)인 경우 **🛡️ 판단 유보 (근거 부족)** 배지(앰버/호박색)로 명확히 분리 렌더링.
     - `answer_status === 'CAUTIONARY'`인 경우 **⚠️ 주의 안내 포함** 배지(보라색) 렌더링.
     - `answer_status === 'DELIVERED'`인 경우에만 **✓ 검증 완료 (답변)** 배지(초록색) 렌더링.

---

## 3. 회귀 검증 및 호환성 평가

- **신규 검증 테스트:** [`backend/tests/unit/test_p2_defects_reproduction.py`](../../backend/tests/unit/test_p2_defects_reproduction.py) (3/3 PASS)
- **전체 단위 테스트:** 80/80 PASS (기존 77건 + P2 3건, 100% 성공)
- **프론트엔드 빌드:** TypeScript strict 타입 검사 및 롤다운 번들링 정상 완료 (`built in 212ms`).

