# P11 — Temporal Law RAG E2E·품질·성능 통합 평가

작성일: 2026-11-02  
단계: P0~P11의 개발 검증 / 운영 E2E 검증은 별도

## 1. 구현 내용

- 1개 시나리오의 1회 전체 LangGraph 실행을 1개 평가 표본으로 관리
- A/B/C: LLMCHAT / LLMRAG / LEGALAGENT 3종 결과 JSONL 통합
- 시점 상태 정확도 APPLICABLE / NOT_APPLICABLE / UNCONFIRMED 일치율
- 인용 source_id가 실제 retrieved_sources에 포함되었는지 무결성 검사
- 법률적 정답은 수동 전문가 검토(manual_legal_correct) 전에는 미측정
- 정량지표: 시점 판정 정확도, 수동 검수 정답률, 인용 ID 무결성,
  시나리오 완료율, 안전 위반 건수, 응답 지연 P50/P95,
  입력/출력 LLM 토큰 총합 및 샘플 수
- 실제 입력값이 없으면 0으로 위조하지 않고 null/- 표시
- 미완료/HILT 승인대기/Error를 완료된 정답 평가 결과로 취급하지 않음
- 동일 시스템/시나리오가 두 번 들어오면 에러(한 사건 1회 원칙)
- P5 temporal_resolution, P7 legal_evidence_bundle, P6 law_search_plan은
  상담 API 결과에서도 Trace/평가할 수 있도록 반환 필드를 추가

## 2. 평가 파일 형식

Gold Set: scenario_id, question, expected_temporal_status, event_date,
event_type, 법률전문가 검토 여부 등을 정의한 JSONL.

실행 결과: system, scenario_id, run_id, temporal_status,
retrieved_sources, cited_sources, latency_ms,
input_tokens, output_tokens, manual_legal_correct,
manual_unsafe 등을 담은 JSONL.

12개 fixture Gold는 시스템 검사용 **가상 법률 시나리오**다.
실제 대한민국 법령의 적용 정답지나 최종 평가용 검증 Gold Set으로
사용하지 않는다. SC-001 및 2026년 개정법 관련 실제 Gold는
적용 조문/부칙/사실관계 및 전문가 확인 후 별도로 Freeze 해야 한다.

## 3. 로컬 환경 실제 실행 절차

PostgreSQL/Neo4j/Chroma/Langfuse 및 회사 LLM 실행 확인.

A. 별도 평가 환경의 Gold 검토/Freeze.

B. LEGALAGENT 실제 실행 (미승인 외부 검색은 HILT 대기 처리):

    cd backend
    python scripts/evaluation/run_temporal_rag_p11.py --gold tests/fixtures/temporal_rag_p11_fixture_gold.jsonl --out p11_legalagent_runs.jsonl --incomplete-out p11_incomplete.jsonl

공식 검색 승인을 테스트 명령에서 명시적으로 허용하는 경우에만:

    python scripts/evaluation/run_temporal_rag_p11.py --gold tests/fixtures/temporal_rag_p11_fixture_gold.jsonl --out p11_legalagent_runs.jsonl --incomplete-out p11_incomplete.jsonl --approve-official

주의: 기본 가상법령 Gold는 실제 OpenLaw에 없는 법령이므로 실제
운영 정확도 측정에는 반드시 전문가 검토된 현실 법령 Gold로 교체한다.

C. LLMCHAT/LLMRAG 실행 결과를 같은 JSONL 형식으로 변환하여 합친다.
각 시스템의 실행 환경, 모델, 프롬프트, 데이터 접근 및 기준시점을
비교 가능하게 고정하여 기록해야 한다.

D. 사용자/전문가가 각 답변을 원문과 공식 조문/부칙에 대조하여
manual_legal_correct 및 manual_unsafe를 채운다.
추출한 Langfuse Trace의 input_tokens/output_tokens를 각 run_id 또는
trace_id와 결합해 기록한다. 데이터가 없으면 null로 둔다.

E. 평가 집계:

    python scripts/evaluation/temporal_rag_eval.py --gold tests/fixtures/temporal_rag_p11_fixture_gold.jsonl --runs p11_abc_runs.jsonl --json-out p11_results.json --md-out p11_report.md

## 4. 검증의 의미

CI에서 검증하는 것은 평가 로직이 미측정·중복 실행·허위 인용·미검수
정답을 올바르게 처리하는지다. CI 테스트에 실법령 OpenLaw/회사 LLM/
운영 PostgreSQL/Chroma/Langfuse를 연결하지 않는다.

실제 법령의 시행일 판단 정확도·응답시간 P95·토큰 개선을 실측하지
않은 상태이므로 P11을 완료했다고 하더라도 해당 지표가 개선되었다고
주장해서는 안 된다.

## 5. 완료 게이트 / 운영 권장

운영 기본 Feature Flag는 변경하지 않고 안전한 로컬 재현 완료 시까지
P9 자동 인덱싱을 OFF로 유지한다.

아직 필요한 운영 작업:
- 공식 OpenLaw 실제 법령·시행예정·연혁 조회 결과 구조 E2E 검증
- P2/P9 Alembic 마이그레이션 실행과 PostgreSQL 실확인
- P9 Worker의 비정상 종료 작업 복구 및 배치 일부 실패 무결성 강화
- P10 전체 레거시 Vector 감사·건수/해시 대조
- LangGraph 실제 HILT 승인·거절·Resume + 기존 사건 상담 E2E
- SC-001 동결 Gold 및 2026 개정법 시점 반례 전문가 검증
- LLMCHAT/LLMRAG/LEGALAGENT 동일 환경 A/B/C 1회 전체 실행과
  Trace/토큰 집계·법률전문가 정답 검수
- 결과가 준비된 뒤 안전한 단계별 운영 플래그 전환

즉, P11의 **평가 자동화 코드·집계표·샘플 회귀**와
**실제 제품의 최신 법령 적용 능력 검증 완료**는 다른 상태다.
