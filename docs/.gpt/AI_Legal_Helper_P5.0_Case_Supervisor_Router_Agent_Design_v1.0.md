# Case Supervisor / Router Agent 상세설계 v1.0
Document ID: ALH-AGENT-P5.0
Status: APPROVED DESIGN

## 목적
사용자 요청, Case Context, 현재 Workflow State, 새 Evidence/Event 여부를 해석해 적절한 Workflow와 전문 Agent 경로를 선택한다.

```mermaid
flowchart TD
 U[User/Application] --> S[Case Supervisor/Router]
 S -->|RoutingPlan| O[Orchestrator]
 O --> C[Case Agent]
 O --> E[Evidence Agent]
 O --> I[Issue Agent]
 O --> L[Legal Agent]
 O --> P[Precedent Agent]
 O --> PB[Playbook Agent]
 O --> D[Document Agent]
 O --> SY[Synthesizer]
 O --> V[Verification Agent]
 V --> O
 O --> U
```

## 책임
- User Intent 분류
- Case Context/State 해석
- Workflow Type 선택
- 필요한 전문 Capability 제안
- 선행조건/누락 입력 탐지
- Clarification 필요 여부 판단
- RoutingPlan 생성

## 금지
법률 최종결론, Evidence 확정, State 직접 변경, Tool 권한 우회, Verification 생략, Retry/Transaction 직접 실행.

## Intent
`NEW_CASE, CASE_QUESTION, NEW_EVIDENCE, UPDATE_CASE, REQUEST_ANALYSIS, REQUEST_LEGAL_RESEARCH, REQUEST_PRECEDENT_SEARCH, REQUEST_NEXT_ACTION, REQUEST_DOCUMENT, CASE_STATUS, CLARIFICATION_RESPONSE, UNKNOWN`

## WorkflowType
`CASE_INTAKE, EVIDENCE_UPDATE, CASE_REANALYSIS, LEGAL_RESEARCH, NEXT_ACTION, DOCUMENT_GENERATION, CASE_QA, STATUS_QUERY, CLARIFICATION`

## RoutingPlan
```yaml
routing_plan_id: string
case_id: string|null
trace_id: string
intent: enum
workflow_type: enum
reason: string
required_capabilities: []
prerequisites: []
missing_inputs: []
clarification_required: boolean
clarification_questions: []
risk_flags: []
created_at: datetime
router_version: string
```

## 핵심 경계
Supervisor는 **무엇을 시도할지** 판단한다.
Orchestrator는 **허용 여부와 실행 방법**을 결정한다.
RoutingPlan은 실행 명령이 아니며 Orchestrator가 Schema/State/Permission/Precondition을 재검증한다.

## 예
새 문자 캡처 → NEW_EVIDENCE → EVIDENCE_UPDATE → Evidence 분석 → 영향 Fact/Issue → 필요한 범위 재분석.

내용증명 요청 → REQUEST_DOCUMENT → 검증 Fact 충분 여부 확인 → 충분하면 DOCUMENT_GENERATION, 부족하면 Clarification/Evidence workflow.

## 안전
모호하면 UNKNOWN/Clarification. 업로드 문서의 명령은 Evidence일 뿐 System instruction이 아니다. Router 실패가 Case state를 손상시키면 안 된다.

## 평가
new case/new evidence/question/legal research/precedent/next action/document/ambiguous/prompt injection/incompatible state routing test.

## DoD
Supervisor Prompt, I/O Schema, RoutingPlan Schema, Intent/Workflow Enum, Orchestrator validation boundary, routing tests, injection tests, trace logging, no direct state mutation.
