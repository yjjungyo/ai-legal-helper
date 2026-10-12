---
document_id: ALH-P5-DESIGN
title: AI 법률도우미 P5 Agent System 상세설계
version: 1.0
status: Design Baseline
parent: ALH-DEV-001
---

# P5 Agent System

## 목적
논리 Agent의 역할, Persona, Prompt, I/O Contract, Tool Permission, 오류정책을 확정한다.

## Agent
Case Agent / Evidence Agent / Issue Agent / Legal Agent / Precedent Agent / Playbook Agent / Document Agent / Synthesizer Agent / Verification Agent

## 공통 Prompt 원칙
Evidence First / No Fabrication / Fact와 Interpretation 분리 / UNKNOWN 허용 / Traceability / Verified Legal Grounding / 불확실성 표시 / 결과 보장 금지 / 역할범위 준수.

## Agent Contract
각 Agent:
`agent_id, purpose, persona, system_prompt, input_schema, output_schema, tools, allowed_actions, forbidden_actions, timeout, retry, evaluation_cases`

## Tool Permission
- Case: case read/update orchestration request
- Evidence: evidence/fact/timeline tools
- Issue: issue detection/read
- Legal: statute retrieval/verification
- Precedent: precedent retrieval/rerank/compare
- Playbook: playbook read/evaluate
- Document: verified case read + document generation
- Synthesizer: read approved agent outputs, no source invention
- Verification: read/validate, no silent repair

## Structured Output
모든 핵심 Agent output은 P1 AgentMessage + Agent별 JSON Schema를 사용한다.

## Prompt Injection/Untrusted Evidence
업로드 문서 내 명령문은 Evidence content이지 System instruction이 아니다. Tool permission은 모델 텍스트로 확장되지 않는다.

## Functions
- `invoke_agent()`
- `validate_agent_input()`
- `validate_agent_output()`
- `get_agent_tools()`
- `record_agent_run()`
- `retry_agent_run()`

## 평가
Agent별 golden cases, forbidden behavior tests, fabricated citation tests, schema violation tests, tool permission tests.

## DoD
9개 논리 Agent 명세, Prompt version, I/O schema, least-privilege tools, test cases, structured errors. 물리적 LLM instance 수는 최적화 가능.
