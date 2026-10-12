# ADR 005: Supervisor & Verification Architecture

## Context
기존 P1.2 엔진은 사용자 질문을 분류하고 전문 법률 에이전트를 호출하여 종합된 답변을 제시했습니다. 하지만 LLM의 특성상 검색된 법령이나 판례를 과도하게 해석하거나, 없는 조항을 지어내는(Hallucination) 위험성이 있었습니다. 이를 통제하기 위해 답변이 실제 출처에 기반했는지 검증하는 과정이 필요합니다.

## Decision
- **Supervisor Workflow 도입**: 기존 일방향 흐름(Router -> Plan -> Agent -> Synthesize) 끝에 Verification(검증) 단계를 추가하는 LangGraph 상태 머신으로 확장합니다.
- **분리된 Verification Agent**: 답변을 생성한 LLM과 독립적인 프롬프트(수석 법률 검증관)를 사용하는 별도의 Verification 노드를 두어 객관적인 검증(Grounding 체크)을 수행합니다.
- **최대 1회 제한적 재검토(Revise)**: 검증 실패(REVISE) 시, 수정을 지시하는 프롬프트를 통해 1회에 한정하여 수정된 답변을 생성합니다. 반복 루프에 빠지는 것을 막고 API 비용을 통제하기 위함입니다.
- **근거 부족(INSUFFICIENT)의 명시화**: 재검토 후에도 근거가 부족하거나 아예 출처가 없는 경우, 답변 자체를 폐기하기보다는 "근거가 부족한 참고용"임을 명시하여 사용자에게 최종 전달합니다.

## Consequences
- **장점**: 법률 답변의 신뢰성 및 안전성 확보. 할루시네이션(거짓 정보)을 프론트엔드 노출 전에 차단하거나 경고할 수 있음.
- **단점**: LLM 호출 횟수 증가로 인한 토큰 비용 및 지연시간(Latency) 증가.

