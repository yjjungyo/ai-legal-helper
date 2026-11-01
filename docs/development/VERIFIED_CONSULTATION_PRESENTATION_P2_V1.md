# P2: Verified Consultation Presentation v1.0

## 목적
최종 법률 답변을 수정하거나 다시 판단하지 않고, 검증 통과한 원문을
연속적인 표시 블록으로 제공한다. 기존 `answer` 및 `sources`는 유지한다.

## 데이터 계약
- `presentation` 은 `ConsultationResponse` 의 선택 필드다.
- `schema_version=1.0`; `blocks[].markdown` 은 최종 `answer` 의 실제 연속 부분 문자열이다.
- 모든 블록의 markdown을 배열 순서대로 결합하면 최종 answer와 정확히 동일해야 한다.
- `start,end` 는 Python 문자열 오프셋(Unicode code point)이며, UTF-16 JS 인덱스로 변환해 직접 사용하지 않는다.
- `direct_answer_block_id` 는 최초 무제목 문단 구간을 가리키는 표시 메타데이터다. 새로운 요약문을 만들지 않는다.
- `claims` 는 Verification의 SUPPORTED 주장 중 원문에 정확히 한 번 등장하고 출처 ID가 실제 목록에 있는 경우에만 연결한다.
- `verification_binding=HASH_MATCHED` 는 기존 `verified_answer_sha256` 과 최종 answer 해시가 일치할 때만 사용한다.
- SHA가 없는 구 경로는 `STATUS_MATCHED` 로 표현하며 같은 강도로 검증되었다고 주장하지 않는다.
- Verification PASS가 아니거나 WITHHELD인 경우 presentation=null 이다.
- 구조화 실패 시 기존 answer 뷰어로 폴백한다. 구조화 과정에서는 새로운 LLM 호출이 없다.

## 저장 전략
P2에서는 DB 컬럼을 추가하지 않는다. 기존 `answer`, `sources`,
`verification_result` 에서 GET 및 사건 이력 응답 시 동일 모델을 재생성한다.
따라서 재시작 후 데이터 소실이 없으며 마이그레이션 리스크를 방지한다.
P4에서 스키마 버전 영속화 및 불변 스냅샷을 별도로 다룬다.

## 연결 경로
`GET /consultations/{request_id}` (메모리/DB),
`GET /cases/{case_id}/consultations` 모두 구조화 데이터를 포함한다.
React AssistantMessage는 `presentation`이 있으면 VerifiedPresentationView,
없으면 기존 LegalAnswerView를 사용한다.

## 주의
P2는 표시용 구조 모델이다. 아직 의미 단위 ACTION/FACT/ISSUE를 새로 생성하거나,
원문에서 확인되지 않은 행동 우선순위를 추론하지 않는다. P3 이후에
검증된 의미 구조의 직접 생성·검증과 사용자 화면 최적화를 진행한다.
