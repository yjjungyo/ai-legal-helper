# Temporal Legal RAG — P8 적용시점 Verification 최종 안전 게이트

기준선: P7 main 969447c3382f9f38a017f7d0b246db594f9a5999

## 목표

일반 LLM이 본문을 읽었더라도 개정 조문이 계약일에 시행되기 전이면 이를
현재 적용 규정처럼 안내할 수 있다. P8에서는 단순 인용 존재성 및 LLM의
검증 PASS 위에 결정론적 적용시점 안전 게이트를 추가했다.

## 구현

- `legal_knowledge/temporal_verification.py`:
  - 개정/시행/적용 등 시점 질문에 한해 사건일과 P5 3상 판정 검토
  - `NOT_APPLICABLE` 개정 법령을 '현재 적용된다'고 단정 시 BLOCK
  - 적용례 미확인 상태에서 긍정/부정 확정 시 BLOCK
  - 불확실성을 명시하면 CAUTION, 시점 문제가 없는 기존 질문은 NOT_REQUIRED
  - 결과에 source_id·reason_code·event_date 보존
- `workflows/legal_workflow.py`:
  - 일반·문서 상담 Verification 양쪽에 동일 게이트 적용
  - 기존 쟁점 단위 부분 답변보다 BLOCK을 우선해 unsafe finalize 방지
  - 법령 시점 미확인 시 사용자 친화적인 보류 사유 안내
- `workflows/document_consultation.py`:
  - BLOCK 판단을 제한 답변 재생성/재검증으로 우회하지 못하도록 방어

## 품질·안전 설계

- 법령 특정 조문/날짜 하드코딩 없음
- LLM 인용 검증 통과와 시점 적용 가능 검증 결과를 구분
- 미확인 법령을 확인된 것처럼 만드는 대신 보류/조건부 판정으로 처리
- 비교 전용 차기 시행예정 버전을 계약일에 적용하지 않도록 차단
- 법령 적용 문장 의미를 모든 문법에 대해 완벽히 판독하는 것이 아니므로
  규칙의 포괄 범위와 반례를 향후 골드셋으로 측정·보강해야 함
- P8은 위험한 문구 전달을 줄이는 안전장치이며 법률 정답률 100% 보장은 아님

## 회귀 결과

GitHub Actions `Temporal RAG P8 verification`:
- P8 게이트·P7 Evidence·P6 HITL·P5 적용례 회귀 **52건 PASS**
- 실 OpenLaw API·실 회사 LLM·운영 Langfuse의 E2E는 미수행
- 기존 8개 Agent, 사용자 승인/거절, Graph 구조 전반 보존

## 후속

P9 공식 법령 버전별 전체 조문 비동기 인덱싱, P10 레거시 Vector
메타데이터 마이그레이션, P11 성능/정답률 검증·A/B/C 비교.
