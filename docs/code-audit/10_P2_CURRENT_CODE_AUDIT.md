# P2 현재 소스코드 감사 보고서 (P2 Current Code Audit)

**감사 일시:** 2026-10-18  
**대상 프로젝트:** `ai-legal-helper`  
**감사 범위:** P2 — 품질 및 평가 고도화 (P2-01 ~ P2-03)  
**감사 수행자:** Gemini Antigravity  

---

## 1. P2-01: 검색 품질 및 Hybrid RAG 현황 분석

### 1.1 현재 구현 상태 (`rag/retrieval.py`, `rag/retrieval_factory.py`)
1. **Dense Vector Search 단독 의존**:
   - 현재 ChromaDB 검색은 순수 Dense Vector 유사도 검색(`vs.similarity_search` 또는 `similarity_search_with_relevance_scores`)에 전적으로 의존한다.
   - 한국어 법률 질의(예: "주택임대차보호법 제6조의2", "묵시적 갱신 계약 해지 3개월")에서 조문 번호나 특정한 법률 전문 용어(예: "임차권등기명령", "대항력")가 질의에 명시되어도, 임베딩 벡터의 의미적 유사도에만 의존하여 정확한 조문 청크가 상위에 노출되지 못하거나 탈락할 위험이 있다.
2. **조문 번호 직접 매칭 및 메타데이터 필터링 부재**:
   - 청크 본문이나 메타데이터에 특정 조문 번호(`제N조`, `제N조의M`)가 존재하더라도, 질의에 포함된 조문 번호와 직접 대조하여 가중치를 부여하는 하이브리드 리랭킹(Hybrid Re-ranking) 로직이 없다.
3. **중복 청크(Redundant Chunks) 반환 문제**:
   - 동일 법령이나 판례에서 연속된 페이지 또는 슬라이딩 윈도우 분할로 인해 텍스트 내용의 80% 이상이 겹치는 청크들이 `top_k`를 독점하여, 다양한 쟁점 조문이 검색 결과에 포함되지 못하는 현상이 발생한다.

---

## 2. P2-02: Langfuse Observability 추적 심도 분석

### 2.1 현재 구현 상태 (`observability/langfuse_client.py`, `api/routes/consultation.py`)
1. **메타데이터 파편화 및 단편적 기록**:
   - 현재 `update_span`을 통해 `elapsed_ms`, `total_tokens`, `citation_audit` 일부 지표가 기록되고 있으나, 상담 워크플로우의 전체 의사결정 흐름(Supervisor 선택 에이전트, HILT 승인 여부, 공식 법령 원문 검색 결과 건수, 최종 3계층 상태)이 루트 Trace 수준에서 일목요연하게 태깅되지 않는다.
2. **민감정보(PII) 마스킹 미흡**:
   - 사용자 질문이나 사건 맥락에 포함될 수 있는 주민등록번호, 전화번호, 이메일 주소, 외부 API Key 등이 Span metadata나 입력값에 원문 그대로 전송될 수 있는 보안 취약점이 존재한다.
3. **검색 실패 원인 및 인덱스 정보 추적 부재**:
   - P1-01에서 도입된 `RetrievalResult.used_index_info` 및 `error_detail`이 Langfuse 루트 Trace 메타데이터에 체계적으로 기록되지 않아, 대시보드에서 장애 분석이 제한된다.

---

## 3. P2-03: 사용자 최종 답변 및 UI 출력 정책 분석

### 3.1 현재 프론트엔드 구현 (`frontend/src/components/LegalAnswerView.tsx`, `ChatSection.tsx`)
1. **마크다운 기호의 기계적 제거(Strip) 문제**:
   - `LegalAnswerView.tsx`의 `cleanRawMarkdown` 함수는 `**굵게**`, `# 헤더`, `*기울임*`, `> 인용` 등의 마크다운 기호를 정규식으로 일괄 제거하여 플레인 텍스트로 치환하고 있다.
   - 이로 인해 LLM이 가독성을 위해 작성한 소제목, 글머리 기호, 핵심 강조 텍스트가 밋밋하게 표시되고 시각적 계층 구조가 훼손된다.
2. **권장 8단계 출력 구조의 시각적 구분 부족**:
   - 개발지시서에서 권장하는 8대 구성요소(1. 사건 요약, 2. 확인된 사실, 3. 법률 쟁점, 4. 적용 법령 및 근거, 5. 분석 결과, 6. 불확실/추가 확인 사항, 7. 다음 행동, 8. 검증된 출처)가 명확한 섹션 블록으로 스타일링되지 않는다.
3. **단일 상태 배지 혼란 (답변 완료 vs 판단 유보)**:
   - `ChatSection.tsx`는 백엔드의 단일 `status === 'SUCCESS'`만 확인하여 초록색 '답변 완료' 배지를 표시한다. 검증관이 `INSUFFICIENT`로 판정하여 법률 조언이 유보(`answer_status = 'WITHHELD'`)된 경우에도 '답변 완료'로 표시되어 사용자에게 혼란을 준다.

---

## 4. 감사 결론 및 개선 방향

- **P2-01**: `rag/retrieval.py`에 키워드/조문 매칭 기반 Hybrid 점수 산정 및 중복 청크 제거 알고리즘 도입.
- **P2-02**: Langfuse 루트 Trace 메타데이터 종합 기록 및 주민등록번호/전화번호/API키 자동 마스킹 필터 구축.
- **P2-03**: `LegalAnswerView.tsx`의 마크다운 안전 렌더링 지원 및 `ChatSection.tsx`의 3계층 상태 배지 구분(`검증 완료`, `판단 유보`, `승인 대기` 등).

