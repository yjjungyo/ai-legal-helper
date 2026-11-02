# Temporal Legal RAG — P5 Temporal Law Resolver

작성일: 2026-11-02
기준선: P4 main 34ac5d6ca9c6eb82cdd8af860a22d39f21183cc8

## 구현 내용

- 기존 법령별 P4 MST/조문/부칙 출처를 입력받아 P1의 3상 판정 API와 결합
- 질문에서 계약 체결·갱신·변경·해지통지 등 사건 기준일 후보 추출
- 공포일/시행일은 계약일로 자동 오인하지 않으며, 복수 사건일은 AMBIGUOUS 처리
- 공식 법령 ID + MST가 일치한 부칙에 포함된 개정 조문 적용례만 식별
- 시행 이후 특정 사건 유형부터 적용한다는 **단일·명시 패턴**에서만 VERIFIED로 격상
- 다중 사건 유형·예외·경과규정·소급효·시행일 미확인은 UNCONFIRMED
- 종전/시행예정 버전이 함께 있을 때 버전별 개별 판정과 사유 제공
- 검색 원문을 변경하지 않고 독립된 판정 결과 반환

모든 적용례를 기계적으로 해석하는 것은 불가능하므로, 이 API는 일반적인 법률 자문 확정기가 아니다. 복잡한 적용례와 경과조치는 추가 검증 또는 판단 유보를 요구한다.

## API

- `resolve_event(question, event_date=None, event_type=None) -> EventResolution`
- `evaluate_temporal_sources(question, sources, event_date=None, event_type=None) -> TemporalResolution`

각 결과는 `as_dict()`로 LangGraph 상태·Trace에 저장할 수 있으며, 원문 Source를 변경하지 않는다.

## 검증

GitHub Actions `Temporal RAG P5 applicability`:
- 17건 PASS
- 외부 OpenLaw/LLM/운영 PostgreSQL을 사용하지 않은 순수 Python/pytest 테스트
- 공포일/계약일 분리, 복수 사건일 보류, 날짜·법령 버전·부칙 정합성 확인
- 단일 적용례의 시행 전·후 판정, 다중 적용례·경과규정 안전 보류
- 기존 8개 Agent 및 HILT 구성 변경 없음

## 후속

- P6: 승인 전 검색계획 생성, 기준일 확정 후 HILT Resume에서 P4/P5를 호출
- P7: 공식 근거를 답변 생성에 포함하고 사건별 근거 꾸러미 제공
- P8: 판정 결과 기반 Verification의 단정 차단 및 안전 응답
- P9/P10: 공식 법령 버전별 인덱스, 데이터 마이그레이션
- P11: E2E/성능·정확성 비교 실측

P5에서는 기존 LangGraph 노드 연결을 변경하지 않는다. P6 통합 전에는 실제 상담 답변에 P5 판정이 자동 반영되지 않는다.
