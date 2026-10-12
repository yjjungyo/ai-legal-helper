# Architecture Amendment 001 — Case Supervisor / Router
Document ID: ALH-ARCH-AMD-001
Status: APPROVED

## 변경 이유
기존 설계에는 전문 Agent와 Orchestrator는 있었으나 사용자 요청과 Case Context를 의미적으로 해석하여 Workflow를 선택하는 명시적 AI Control Plane이 부족했다.

## 변경
`User/Application → Case Supervisor/Router → RoutingPlan → Orchestrator → Specialist Agents → Synthesizer → Verification → Orchestrator`

기존 9개 Logical Agent에 Supervisor/Router를 추가하여 **총 10개 Logical Agent**로 한다.

## Phase 영향
- P5: Supervisor Persona/Prompt/I-O/Tool boundary 추가
- P6: RoutingPlan 검증 및 실행, State 변경권은 Orchestrator 유지
- P8: UI가 Specialist Agent를 직접 선택하지 않음
- P9: routing accuracy/unnecessary calls/clarification/forbidden routing 평가
- P10: Router prompt/version/regression을 Release Gate에 포함

## 변경하지 않는 것
기존 9개 Agent 책임, Verification 독립성, deterministic state control, Evidence traceability, Playbook, P2/P3/P4 구조.

## Architecture Rule
> Supervisor decides what should be attempted.
> Orchestrator decides what is allowed and how it is executed.
> Specialist Agents perform bounded expert tasks.
> Verification determines whether outputs are sufficiently grounded.
