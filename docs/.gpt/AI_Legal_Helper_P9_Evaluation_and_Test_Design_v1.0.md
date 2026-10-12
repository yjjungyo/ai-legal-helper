---
document_id: ALH-P9-DESIGN
title: AI 법률도우미 P9 Evaluation & Test 상세설계
version: 1.0
status: Design Baseline
parent: ALH-DEV-001
---

# P9 Evaluation & Test

## 목적
'그럴듯한 데모'가 아니라 측정 가능한 정확도·근거성·절차 완성도를 검증한다.

## 평가 Dataset
- SC-LEASE-001
- SC-LEASE-002
- SC-LEASE-003 Challenge
- 변형/Negative/Incomplete/Conflicting cases

Gold Set:
Facts, Evidence links, Timeline, Issues, applicable sources, relevant precedents, expected process steps, acceptable next actions.

Gold는 AI 단독 생성물을 정답으로 취급하지 않고 Human Review/공식근거 검증을 거친다.

## KPI
| KPI | 목표 |
|---|---:|
| 사건 핵심정보·쟁점 분석 정확도 | >=90% |
| 법령·판례 근거 정확도 | >=95% |
| 사건 해결절차 안내 완성도 | >=90% |

## Submetrics
Fact precision/recall, timeline accuracy, issue precision/recall, citation validity, retrieval Recall@K, evidence traceability, unsupported claim rate, next-action coverage, schema failure, latency/cost(참고).

## Test Layers
Unit → Contract → Integration → Retrieval → Agent → Orchestration → E2E → Challenge → Regression.

## Baseline
현재 수준을 조작하지 않는다. 신규 기능은 `미측정`에서 시작하고 첫 평가 결과를 Baseline으로 기록한다.

## Functions
- `load_gold_case()`
- `run_evaluation_case()`
- `score_fact_extraction()`
- `score_issue_detection()`
- `score_retrieval()`
- `verify_citations()`
- `score_next_action()`
- `measure_unsupported_claims()`
- `generate_evaluation_report()`

## Challenge
SC-003은 multimodal, long timeline, conflicting/partial evidence, multiple issues, downstream damages 가능성을 포함한다.

## DoD
재현 가능한 evaluation harness, versioned dataset, KPI report, failure taxonomy, regression suite, challenge result.
