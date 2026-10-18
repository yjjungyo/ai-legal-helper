# P2 결함 수정 및 품질 고도화 설계서 (P2 Remediation Design)

**설계 일시:** 2026-10-18  
**대상 단계:** P2 (품질 및 평가 고도화 — P2-01 ~ P2-03)  
**설계자:** Gemini Antigravity  

---

## 1. P2-01: 검색 품질 개선 (Hybrid Retrieval & Chunk Deduplication)

### 1.1 하이브리드 리랭킹 및 조문 직접 매칭 알고리즘
- **목표:** 벡터 유사도 점수와 키워드/조문 완전 일치 가중치를 결합(Hybrid Scoring)하여, 특정 법조문이나 핵심 법률 용어를 포함한 문서 청크의 검색 정확도를 비약적으로 향상시킨다.
- **가중치 산정 공식:**
  $$\text{Final Score} = w_{\text{vector}} \cdot \text{Dense Score} + w_{\text{article}} \cdot \mathbb{I}(\text{조문 일치}) + w_{\text{lexical}} \cdot \text{Lexical Overlap Ratio}$$
  - $w_{\text{vector}} = 0.6$: Dense 임베딩 유사도 (기본 의미적 맥락)
  - $w_{\text{article}} = 0.3$: 질의에 명시된 조문(예: "제6조의2")이 청크 본문 또는 메타데이터와 완전 일치할 때 가산
  - $w_{\text{lexical}} = 0.1$: 질의의 명사/핵심 형태소와 청크 텍스트 간의 자카드(Jaccard) 어휘 중첩도
- **중복 청크 제거 (Deduplication):**
  - 동일한 출처 파일 내에서 본문 텍스트 유사도가 85% 이상이거나, 동일 조문의 중복 분할 청크가 검색된 경우 점수가 더 높은 1개 청크만 유지하고 나머지는 제거하여 다양성(Diversity)을 확보한다.

---

## 2. P2-02: Langfuse Observability 심층 추적 및 민감정보 보호

### 2.1 종합 Trace 메타데이터 스키마
`record_consultation_trace_summary` 함수를 도입하여 상담 종료 시 루트 Trace에 다음 구조화된 메타데이터를 일괄 부착한다:
```python
{
    "request_id": str,
    "case_id": Optional[str],
    "execution_status": "COMPLETED | APPROVAL_REQUIRED | ERROR",
    "verification_status": "PASS | REVISE | INSUFFICIENT | UNVERIFIED",
    "answer_status": "DELIVERED | WITHHELD | CAUTIONARY | REVISED",
    "selected_agents": List[str],
    "revision_count": int,
    "retrieval": {
        "used_index": str,
        "methods": List[str],
        "hits_count": int,
        "source_ids": List[str],
        "error_detail": Optional[str]
    },
    "hilt": {
        "is_required": bool,
        "approved": Optional[bool],
        "official_statutes_count": int
    },
    "verification": {
        "reason_code": str,
        "citation_existence_rate": float | str,
        "citation_support_rate": float | str,
        "citation_coverage_rate": float | str,
        "rejected_citations": List[str]
    },
    "usage": {
        "total_calls": int,
        "total_tokens": int,
        "elapsed_ms": float
    }
}
```

### 2.2 민감정보(PII) 자동 마스킹
- `mask_pii(text: str) -> str`:
  - 주민등록번호: `r"\b(\d{6})[- ]?([1-4]\d{6})\b"` -> `r"\1-*******"`
  - 전화번호/휴대전화: `r"\b(01[016789]|02|0[3-6]\d)[- ]?(\d{3,4})[- ]?(\d{4})\b"` -> `r"\1-****-\3"`
  - API 키 및 비밀 토큰: `r"\b(sk-[A-Za-z0-9_\-]{20,}|OC=[A-Za-z0-9_\-]+)\b"` -> `[MASKED_API_KEY]`

---

## 3. P2-03: 사용자 최종 답변 및 UI 렌더링 고도화

### 3.1 `LegalAnswerView.tsx` 안전한 구조화 렌더러
- 마크다운 기호를 무조건 지우지 않고 안전하게 HTML 서식으로 변환:
  - `**텍스트**` -> `<strong>텍스트</strong>`
  - `### 소제목` -> 스타일링된 소제목 블록
  - `- 불릿` -> 깔끔한 리스트 아이템
- 8대 권장 구성요소(1. 사건 요약, 2. 확인된 사실, 3. 법률 쟁점, 4. 적용 법령 및 근거, 5. 분석 결과, 6. 불확실/추가 확인 사항, 7. 다음 행동, 8. 검증된 출처)의 헤더 감지 시 전용 테마 색상 및 아이콘이 적용된 카드 렌더링.

### 3.2 `ChatSection.tsx` 3계층 상태 배지 시각화
- `item.status` 대신 `item.answer_status`와 `item.verification_status`를 조합하여 배지 표시:
  - `answer_status === 'DELIVERED'` & `verification_status === 'PASS'`: `badge-green` (`검증 완료`)
  - `answer_status === 'WITHHELD'`: `badge-amber` (`판단 유보 (근거 부족)`)
  - `answer_status === 'CAUTIONARY'`: `badge-purple` (`주의 안내 포함`)
  - `status === 'APPROVAL_REQUIRED'`: `badge-blue` (`승인 대기`)
  - `status === 'ERROR'`: `badge-red` (`오류`)

