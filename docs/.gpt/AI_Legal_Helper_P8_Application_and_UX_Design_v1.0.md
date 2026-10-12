---
document_id: ALH-P8-DESIGN
title: AI 법률도우미 P8 Application & UX 상세설계
version: 1.0
status: Design Baseline
parent: ALH-DEV-001
---

# P8 Application & UX

## 목적
일반인이 법률용어를 몰라도 사건을 등록하고 자료를 올리고 현재 상황과 다음 행동을 이해할 수 있는 PoC를 구현한다.

## 핵심 UX
```text
내 사건
├ 사건 설명
├ 자료 등록
├ 사건 요약
├ Timeline
├ 핵심 Fact
├ 법적 쟁점
├ Evidence 현황/부족자료
├ 관련 법령
├ 유사 판례 비교
├ 현재 진행상태
├ Next Action
├ 문서 작성
└ AI 대화
```

## 주요 Flow
1. 새 사건
2. 자연어 설명
3. 파일 Drag/Upload
4. Processing progress
5. AI 추가질문
6. 사건 Dashboard
7. Next Action
8. 새 자료 추가
9. 자동 재분석
10. 문서 초안

## UX 원칙
- 법률분류를 사용자에게 요구하지 않는다.
- 확정 Fact / 주장 / AI 해석 / 불확실성을 시각적으로 구분.
- 근거를 펼쳐볼 수 있게 한다.
- Next Action을 우선한다.
- 실패/처리중/추가자료 필요 상태를 숨기지 않는다.
- 모바일 대응은 하되 PoC의 실제 Frontend stack은 기존 환경 Audit 후 결정.

## API Boundary
UI는 Orchestration/Application API를 호출하고 Agent를 직접 호출하지 않는다.

예:
`POST /cases`
`GET /cases/{id}`
`POST /cases/{id}/evidence`
`GET /cases/{id}/timeline`
`GET /cases/{id}/issues`
`GET /cases/{id}/analysis`
`GET /cases/{id}/actions`
`POST /cases/{id}/documents`

실제 Route naming은 기존 API convention 우선.

## Document Generation
초안임을 명시, source facts 사용, placeholder/unknown 처리, generation audit 유지.

## DoD
SC-LEASE-001을 UI에서 E2E 실행, 새 evidence 재분석, 근거 표시, error/loading state, document draft, no direct agent coupling.
