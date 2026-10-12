# P2.5 GraphRAG 현재 구현 현황 분석

P2.5 개발 지시서 요구사항에 따라 기존 P2.4 시스템의 현재 상태를 분석한 결과입니다.

## 1. Baseline 검색이 실제로 무엇을 사용하는지
`src/ai_legal_helper/rag/graph_rag.py` 내의 `search_baseline`은 벡터(임베딩) 검색을 사용하지 않습니다. 질문 문자열에서 형태소 분석 없이 조사와 불용어를 제거하여 단어를 추출한 뒤, Neo4j의 `CONTAINS` 키워드를 활용해 노드(`Fact`, `LegalIssue`, `Event`, `EvidenceClaim`, `EvidenceSpan`)의 텍스트 프로퍼티가 해당 키워드를 얼마나 많이 포함하는지 카운팅하여 점수를 매기는 **순수 키워드 매칭** 방식을 사용하고 있습니다.

## 2. Hybrid 검색에 벡터 검색이 포함되는지
포함되지 않습니다. `search_hybrid` 메서드는 `search_baseline`(키워드 기반 검색)의 결과를 시드(seed) 노드로 삼아 그래프 관계 탐색(`search_traversal`)을 수행한 후, `find_evidence_gaps` 및 `find_contradictions` 결과를 합쳐서 반환합니다. 즉, 현재의 Hybrid는 "키워드 기반 매칭 + 그래프 관계 탐색"이며, **벡터 유사도 검색은 결여되어 있습니다**.

## 3. Neo4j의 관계 탐색 결과가 답변에 어떻게 반영되는지
그래프 탐색 경로(Traversal path) 결과는 PostgreSQL 원본 데이터와 일치하는지 확인하는 `validate_graph_paths` 검증 과정을 거칩니다. 검증된 경로는 `format_graph_context` 및 `graph_paths_to_sources` 유틸리티 함수를 통해 텍스트로 직렬화되어 Supervisor 및 Verification Agent의 프롬프트 문맥으로 주입됩니다. AI 에이전트는 이를 바탕으로 "이 주장은 어느 문서의 어느 문장에 근거를 두고 있다"는 사실을 답변에 포함할 수 있습니다.

## 4. 증거 ID와 원본 Span이 검증되는지
`src/ai_legal_helper/rag/graph_rag.py` 내의 `validate_graph_paths` 함수가 이 역할을 수행합니다. Neo4j에서 검색된 경로에 포함된 `claim_id`, `evidence_id`, `span_id`를 PostgreSQL 세션에서 실시간으로 조회하여, 존재하는지, 승인된 상태(APPROVED/EDITED)인지, 동일 사건(case_id)에 속하는지, 그리고 서로의 매핑이 올바른지 다시 한번 엄격하게 코드 레벨로 검증합니다.

## 5. 그래프 동기화 실패 시 복구할 수 있는지
동기화 실패 시 자동으로 복구되지 않습니다. `src/ai_legal_helper/database/graph_sync.py`의 `safe_sync_case` 함수는 백그라운드 스레드에서 실행되며, 예외 발생 시 로그만 남기고 조용히 종료됩니다(실패 전파 방지). 그러나 재시도 로직이나 큐(Queue), Outbox 패턴이 없어서 일시적 네트워크 장애나 데드락 시 최신 상태로 복구할 방법이 없습니다. 복구하려면 관리자가 수동으로 `/cases/{case_id}/graph/sync` 엔드포인트를 호출해야 합니다.

## 6. 기존 테스트가 어떤 기능까지 검증하는지
`tests/integration/test_graph_rag.py` 통합 테스트는 다음을 검증합니다:
- 동기화가 멱등성(Idempotency)을 유지하는지 (동일 사건 반복 동기화 시 동일 그래프 생성)
- Traversal 검색이 올바른 경로를 반환하며 미승인된 Claim은 무시하는지
- 다른 사건의 데이터가 조회되지 않도록 격리(Isolation)가 잘 되는지
- 증거 공백(Gaps)과 상충(Contradictions) 탐지 기능
- 그래프 상에서는 관계가 남아있더라도 PostgreSQL 상에서 반려(REJECT)된 증거는 `validate_graph_paths`가 올바르게 거르고(Invalidates), 재동기화 시 그래프에서도 사라지는지
- Neo4j가 다운되거나 인증 실패 시 어플리케이션이 죽지 않고 조용히 Fallback 모드로 돌아가는지

**종합 평가:** P2.5 단계에서는 벡터 검색 도입(의미 기반 검색 보강)과 동기화 작업의 신뢰성(재시도 및 버전 관리 기능 등) 향상이 필수적으로 요구됩니다.

