---
document_id: ALH-P7-DESIGN
title: AI 법률도우미 P7 Case Intelligence & Explainability 상세설계
version: 1.0
status: Design Baseline
parent: ALH-DEV-001
---

# P7 Case Intelligence

## 목적
Evidence↔Fact↔Event↔Issue↔Law↔Precedent↔Action 관계를 Query 가능한 Case Graph로 연결하고 설명가능성을 제공한다.

## Task
P7.1 Graph Model  
P7.2 Evidence→Fact  
P7.3 Fact→Event  
P7.4 Fact/Event→Issue  
P7.5 Issue→Law  
P7.6 Issue→Precedent  
P7.7 Issue→Action  
P7.8 Provenance Query  
P7.9 Incremental Graph Update  
P7.10 Integrity Validation

## Graph 원칙
Graph DB 사용 여부는 Repository/PoC 규모를 보고 결정한다. 관계형 DB + edge table로 충분하면 불필요한 Graph DB 도입 금지.

## Edge
`edge_id, case_id, from_type/id, relation, to_type/id, provenance, confidence, created_by, created_at`

관계 예:
`SUPPORTS, CONTRADICTS, OCCURRED_IN, RELEVANT_TO, GOVERNED_BY, SIMILAR_TO, JUSTIFIES, REQUIRES`

## Explainability Query
- `why_issue_detected(issue_id)`
- `evidence_for_fact(fact_id)`
- `legal_basis_for_action(action_id)`
- `precedents_for_issue(issue_id)`
- `trace_conclusion(conclusion_id)`
- `build_case_graph(case_id)`

## 사용자 설명
내부 graph를 그대로 노출하지 않고:
`결론 → 이유 → 근거 Evidence → 법령/판례 → 불확실성` 구조로 변환.

## DoD
SC-001에서 주요 결론/Action을 Evidence까지 역추적, conflict edge, source provenance, incremental update, orphan/reference validation.
