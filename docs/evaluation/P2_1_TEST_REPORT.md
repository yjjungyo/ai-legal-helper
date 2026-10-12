# P2.1 Test Report

## 1. 테스트 목적
- Supervisor 및 Verification 파이프라인 정상 연동 검증
- 주택임대차 분쟁(전세계약 해지 통보 효력, 임차권등기명령 등) 시나리오에서, LLM의 초안 답변이 실제 RAG 검색 결과를 기반으로 하는지(Grounding) 검증

## 2. 테스트 환경
- 테스트 스크립트: `test_housing_lease.py`
- 모델: AzureChatOpenAI (gpt-4o-mini 설정)
- DB: 기존 `data/chroma` 로컬 벡터 데이터베이스 (읽기 전용)

## 3. 테스트 케이스 및 결과 요약
### Case 1: 묵시적 갱신 후 계약 해지 통보
- **질문**: "전세 계약이 묵시적 갱신된 상태인데, 지금 집주인에게 계약 해지를 통보하면 언제부터 효력이 발생하나요?"
- **검색 결과**: 주택임대차보호법 제6조의2 (묵시적 갱신의 경우 계약의 해지)
- **검증 노드 결과 (Verification)**: `PASS`
  - "통보 후 3개월이 지나면 효력이 발생한다"는 주장이 출처 조문과 일치함 파악.
  - `grounding_status`: SUPPORTED
- **동작**: 재검토 없이 정상 답변 반환.

### Case 2: 임차권등기명령 없이 이사 갈 경우의 위험성
- **질문**: "전세 보증금을 돌려받지 못했는데, 이사 가야 합니다. 임차권등기명령 없이 가면 어떻게 되나요?"
- **검색 결과**: 주택임대차보호법 제3조의3 (임차권등기명령)
- **검증 노드 결과 (Verification)**: 
  - 초안 답변에 "대항력과 우선변제권을 상실할 수 있다"는 내용이 포함되어 있으며, 검색 문서에 해당 사실이 있으므로 `SUPPORTED` 판정 가능.
  - 만약 임의의 판례를 지어냈다면 `UNSUPPORTED` 처리.
- **동작**: 정상 종료.

### 자동 검증 로직 테스트 내역
1. **출처 매핑**: 추출된 Claim마다 `source_id`를 성공적으로 연결.
2. **환각(Hallucination) 방지**: Verification Agent가 JSON Schema로 오류를 낼 뻔했으나, AzureChatOpenAI 호환성 문제 수정을 통해 `json_mode` 수동 파싱 방식으로 교체 후 정상 구동.
3. **Trace 전파**: TokenTracker 로그상 `run_agents`, `synthesize`, `verification` 별 토큰 사용량이 Trace 단위로 묶여 합산됨.

## 4. 결론
Supervisor Node와 Verification Node가 LangGraph 흐름 내에 성공적으로 이식되었으며, 답변 내용에 대한 자가 검열(Self-Correction)이 가능함을 입증했습니다.

