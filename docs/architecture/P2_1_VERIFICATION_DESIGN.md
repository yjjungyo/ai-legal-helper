# Verification Agent Design

## 1. 개요
P2.1에서는 LLM의 법률 상담 결과가 실제 검색된 근거에 의해 지지되는지 검증(Grounding Verification)하는 체계를 신설했습니다.

## 2. 역할 (Role)
- **Specialist Agent**: 주어진 질문에 대해 RAG 검색을 수행하고, 법률 지식과 검색된 근거를 섞어 초안 답변을 작성합니다.
- **Verification Agent**: 수석 법률 검증관 역할을 수행하며, 초안 답변이 오로지 검색된 출처 내용에 의해 뒷받침되는지만 팩트체크합니다.

## 3. 검증 정책 (Grounding Policy)
1. **주장 추출**: 답변 내 주요 법률 주장을 최소 단위로 분리합니다.
2. **출처 대조**: 주장을 뒷받침하는 내용이 `retrieved_sources` 원문에 명확히 존재하는지 매핑합니다.
3. **엄격성**: 출처가 존재한다는 사실만으로 통과시키지 않고, 논리적 연결을 확인합니다.
4. **구분**: 사실/조문과 단순 추론을 분리하여, 근거 없는 추론은 `UNSUPPORTED`나 `UNCERTAIN`으로 마킹합니다.

## 4. 입출력 구조
**Input:**
- Question (사용자 질문)
- Draft Answer (초안 답변)
- Retrieved Sources (검색된 출처 목록, `source_id`, `category`, `content` 포함)

**Output (Structured JSON):**
```json
{
  "status": "PASS | REVISE | INSUFFICIENT",
  "claims": [
    {
      "claim": "묵시적 갱신 시 해지 통보는 3개월 후 효력이 발생한다.",
      "source_ids": ["housing_lease_act_6_2"],
      "grounding_status": "SUPPORTED",
      "reason": "검색된 주택임대차보호법 제6조의2 제2항에 명시됨."
    }
  ],
  "missing_issues": [],
  "contradictions": [],
  "revision_instructions": [],
  "warnings": []
}
```

## 5. 예외 처리
- API 오류 등 검증 노드 자체가 실패할 경우, 서비스 중단을 막기 위해 `PASS` 상태와 경고 메시지(`warnings`)를 함께 반환하여 폴백(Fallback) 처리합니다.

