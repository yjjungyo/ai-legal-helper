# P2.4 Evidence GraphRAG 스키마 (Graph Schema)

## 1. 노드 (Nodes)

| 노드 레이블 | 목적 및 설명 | 주요 속성 (Properties) |
|---|---|---|
| `Case` | 단일 사건 단위 | `case_id`, `title`, `case_type`, `status` |
| `Party` | 사건 당사자 | `party_id`, `name`, `role` |
| `Fact` | 확정된 개별 사실 | `fact_id`, `statement`, `fact_type`, `occurred_at` |
| `Event` | 타임라인 상의 이벤트 | `event_id`, `title`, `event_date`, `event_type` |
| `EvidenceDocument` | 증거 원본 문서 | `evidence_id`, `original_filename`, `media_type` |
| `EvidenceSpan` | 문서 내 텍스트 발췌 부분 | `span_id`, `text_excerpt`, `page_number` |
| `EvidenceClaim` | 추출된 주장 후보 | `claim_id`, `statement`, `assertion_status` |
| `LegalIssue` | 법률적 검토 쟁점 | `issue_id`, `title`, `status` |
| `LegalAuthority` | 법령/판례 참조 | `authority_id`, `title`, `type` (law/case) |
| `Action` | 권고 행동 | `action_id`, `description` |

모든 노드는 식별 및 PostgreSQL 연동을 위해 `case_id` 속성을 공유(선택)하거나 개별 ID 속성을 지닌다.

## 2. 관계 (Relationships)

| 시작 노드 | 관계 (Type) | 대상 노드 | 의미 |
|---|---|---|---|
| `Case` | `INVOLVES_PARTY` | `Party` | 사건의 당사자 포함 |
| `Case` | `HAS_FACT` | `Fact` | 사건의 주요 사실 포함 |
| `Case` | `HAS_EVENT` | `Event` | 타임라인 상의 이벤트 포함 |
| `Case` | `HAS_EVIDENCE` | `EvidenceDocument` | 제출/수집된 증거 문서 |
| `Case` | `HAS_ISSUE` | `LegalIssue` | 법률적 검토 쟁점 |
| `EvidenceDocument`| `CONTAINS_SPAN` | `EvidenceSpan` | 문서 내 텍스트 발췌 위치 |
| `EvidenceDocument`| `HAS_CLAIM` | `EvidenceClaim` | 문서에서 추출된 주장 |
| `EvidenceSpan` | `SUPPORTS` | `EvidenceClaim` | 원문 텍스트가 주장을 뒷받침함 |
| `EvidenceClaim` | `SUPPORTS` / `CONTRADICTS` | `Fact` / `Event` / `LegalIssue` | 주장이 특정 사실이나 쟁점을 뒷받침하거나 반박함 |
| `Fact` | `RELATED_TO` | `Fact` / `LegalIssue` | 사실 간의 연관성 또는 쟁점과의 연관성 |
| `Event` | `OCCURRED_BEFORE` | `Event` | 이벤트 발생 순서 |
| `LegalIssue` | `REQUIRES_EVIDENCE`| `Fact` / `EvidenceClaim` | 쟁점 판단을 위해 특정 사실/증거가 요구됨 |
| `LegalIssue` | `GROUNDED_IN` | `LegalAuthority` | 쟁점이 특정 법적 근거에 기반함 |
| `LegalIssue` | `SUGGESTS_ACTION` | `Action` | 쟁점 해결을 위한 대응 행동 권고 |

## 3. 속성 규칙 (Properties Rule)
- 시간/버전 관리: `created_at`, `updated_at`, `source_version`을 기록.
- 출처 관리: AI가 추론한 관계와 사용자가 승인한 관계를 분리하기 위해 관계(Edge)에 `is_ai_inferred` (boolean) 또는 `review_status` 속성 부여.

