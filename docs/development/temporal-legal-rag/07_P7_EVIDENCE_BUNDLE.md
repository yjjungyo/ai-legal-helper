# Temporal Legal RAG — P7 공식 법령 Evidence Bundle

기준선: P6 main cf22643f9e5d7f123c3f78d85c4b9714a5bf52e1

## 구현

- 공식 법령ID·MST·조문·부칙·시행일·버전역할을 하나의 Source 기반 Evidence Bundle로 조립
- P5의 출처별 3상 판정 및 사유를 source_id 기준으로 결합
- 시행예정 버전 NEXT_EFFECTIVE_CANDIDATE를 명시적으로 표시해 현행법과 분리
- 전문 Agent brief에 승인된 공식 법령 원문 미리보기·시행일 정보를 제공
- Synthesizer 시스템 지침에도 공식 법령 Evidence Bundle을 전달
- Source Registry에 저장된 실제 법령 원문은 축약/삭제하지 않음
- 프롬프트에 들어가는 법령 내용만 길이 제한해 추가 토큰 폭증 방지
- 없는 PDF나 페이지를 생성하지 않고 공식 law_id/MST와 source_url을 유지
- 기존 8개 Agent·HITL·Vector DB·Verification 노드 구성 유지

## 출력 계약

LegalState.legal_evidence_bundle:
- items[]: source_id, law_id, law_name, article, version_id, version_relation, article_effective_date, rule_status, rule_reason, source_url, preview
- digest: LLM에 전달할 길이 제한 근거 텍스트
- warning_codes: FUTURE_VERSION_NOT_CURRENT, TEMPORAL_APPLICABILITY_UNCONFIRMED, SOURCE_VERSION_ID_UNCONFIRMED 등
- source_count, truncated

이 bundle은 **검색 출처 및 P5 기계 판정의 전달 형식**이지 법률적 적용 확정 또는 전체 질문의 검증 PASS가 아니다.

## 검증 범위

- 같은 조문의 두 MST가 각각 독립적으로 보존되는지
- 시행예정 버전의 P5 불적용 판정이 미래로 오용되지 않는지
- Source Registry의 원문과 법령ID가 유지되는지
- 신규 Agent 브리프 및 Synthesizer 입력에 실제 Source 정보가 전달되는지
- 기존 일반 질문에서 추가 LLM 호출이 발생하지 않는지
- HITL, P5·P6 회귀 및 LangGraph 전체 노드 정의 유지

## 후속

P8에서 Verification이 bundle 및 P5 3상 판정을 직접 검사하고 시행예정 개정 규정의 오적용을 차단해야 한다.
P9는 공식 법령을 버전별로 안전하게 인덱싱하며, P10은 레거시 Vector를 마이그레이션한다. P11은 Gold Set·응답 지연·토큰 실측 결과를 수집한다.
