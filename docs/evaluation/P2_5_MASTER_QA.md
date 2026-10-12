# AI Legal Helper — P2.5 Master QA Checklist

이 문서는 P2.5 GraphRAG 고도화 및 성능 검증 구현에 대한 주요 점검 사항을 기록합니다.

## 1. 아키텍처 및 원칙 준수
- [x] P0~P2.4 기능 정상 유지 여부.
- [x] 원본 `ai-legal-agent` 수정 없이 보존.
- [x] PostgreSQL이 사건 데이터의 Source of Truth 로 기능함.
- [x] Neo4j를 읽기 전용 관계 탐색 파생 DB 로만 사용.
- [x] 유료 외부 API, 신규 라이선스 불필요.

## 2. 하이브리드 검색 및 GraphRAG
- [x] Vector(ChromaDB) 검색 로직 추가 (사건별 Evidence Vector Store 구축 완료).
- [x] Vector 결과를 Seed 노드로 사용하여 그래프 확장(Traversal) 실행 구현.
- [x] 승인되지 않은 증거(REJECTED, PENDING)의 검색 배제 원칙 준수.
- [x] `evidence_id`, `span_id` 추적성을 보장하는 Graph Path 반환 확인.
- [x] 타 사건 정보 누출 방지 (Cypher/Vector 메타데이터 기반 완벽 격리 검증 완료).

## 3. 안정성 및 동기화
- [x] Neo4j 장애 / 연결 실패 시 상담 전체를 멈추지 않고 Vector 기반 Fallback 모드로 즉각 전환.
- [x] `graph_paths_to_sources` 및 Supervisor 단에서 Fallback Vector 결과 정상 전달 및 파싱.
- [x] Outbox 패턴(Background Task)을 활용한 안전한 백그라운드 동기화 스케줄러 구현 (`graph_sync_worker`).
- [x] 멱등성 유지 (단일 트랜잭션 `DETACH DELETE` 후 일괄 재구축 방식을 통한 삭제된 증거의 노드 청소).

## 4. 벤치마크 평가 결과
- [x] 주택 임대차 분쟁 기반 합성 테스트 사건(`synth-case-lease-001`) 벤치마크 데이터셋 작성 (`P2_5_BENCHMARK_DATASET.md`).
- [x] `scripts/run_p2_5_benchmark.py` 실행을 통한 결과 도출.
- [x] Baseline 대비 Hybrid 검색이 *증거 상충성*과 *증거 공백*을 입체적으로 추출해 내는 우월성 검증(`P2_5_BASELINE_VS_GRAPHRAG.md`).

## 5. 코드 주석 및 컨벤션
- [x] `CODING_COMMENT_STANDARD.md`에 의거, 추가 및 수정된 모든 모듈(`graph_rag.py`, `legal_workflow.py`, `evidence_vector.py` 등) 내 한국어 설명 주석 및 Docstring 기입 완료.
- [x] 로그 및 테스트 결과 내 실제 사용자 민감 정보 기록 배제 확인 (합성 데이터로만 테스트 진행).

