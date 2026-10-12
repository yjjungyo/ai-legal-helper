---
document_id: ALH-P4-DESIGN
title: AI 법률도우미 P4 Legal Playbook 상세설계
version: 1.0
status: Design Baseline
parent: ALH-DEV-001
---

# P4 Legal Playbook

## 목적
법률 사건처리의 Process Knowledge를 코드가 아닌 Versioned Data로 관리한다.

> Legal Playbook(법률 사건처리 표준) = Workflow + Decision Rules + Required Facts/Evidence + Legal Sources + Exceptions + Actions

## Task
P4.1 Lease Taxonomy  
P4.2 Case Types  
P4.3 Issue Taxonomy  
P4.4 Required Facts  
P4.5 Required Evidence  
P4.6 Legal Source Links  
P4.7 Precedent Query Templates  
P4.8 Decision Nodes  
P4.9 Action Catalog  
P4.10 Next Action Rules  
P4.11 YAML/JSON Schema  
P4.12 Deposit Return PB  
P4.13 Contract Termination PB  
P4.14 Tacit Renewal PB  
P4.15 Validation Engine  
P4.16 Versioning

## Playbook Schema
```yaml
playbook_id:
version:
domain:
case_type:
effective_from:
entry_conditions:
required_facts:
required_evidence:
issues:
nodes:
  - node_id:
    condition:
    required_facts:
    required_evidence:
    legal_source_queries:
    precedent_queries:
    on_true:
    on_false:
    on_unknown:
actions:
verification:
```

## Rule 원칙
- LLM 자유판단 대신 구조화 Condition을 우선한다.
- UNKNOWN branch를 반드시 허용한다.
- 법령 변경 시 코드보다 Playbook data 수정으로 대응한다.
- 조건식 DSL이 필요하면 최소 기능으로 시작하고 안전한 evaluator를 사용한다.
- `eval()`류 임의 코드 실행 금지.

## Composition
거대한 단일 Playbook보다:
`contract_termination`, `tacit_renewal`, `deposit_return` 등을 조합한다.

## Functions
- `load_playbook()`
- `validate_playbook()`
- `select_playbook()`
- `evaluate_entry_conditions()`
- `evaluate_node()`
- `evaluate_case_state()`
- `get_required_facts()`
- `get_required_evidence()`
- `determine_available_actions()`
- `determine_next_action()`

## 검증
Playbook마다 positive/negative/unknown fixture를 둔다. 법률전문 검토가 필요한 규칙은 `REVIEW_REQUIRED` 상태를 지원한다.

## DoD
3개 임대차 Playbook, Schema Validation, UNKNOWN path, versioning, 법률 source refs, Evidence Gap 연계, deterministic next-action evaluation.
