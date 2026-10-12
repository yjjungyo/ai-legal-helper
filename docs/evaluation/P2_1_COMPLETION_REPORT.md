# P2.1 Completion Report

## 1. P2.1 개발 목표 및 달성 현황

- [x] Supervisor 실행 구조 구현: LangGraph 워크플로우를 Supervisor 중심으로 재설계 (START -> Init -> Route -> Plan -> Agents -> Synthesize -> Verification -> End)
- [x] Verification Agent 구현: `verification_agent.py` 신설, `VERIFICATION_PROMPT` 작성
- [x] 법률 주장별 근거 연결: Verification 결과에 `claims`와 `source_ids` 매핑 (JSON 구조)
- [x] 근거 없는 주장 탐지: `grounding_status` (SUPPORTED / UNSUPPORTED / UNCERTAIN) 식별
- [x] 재검토 최대 1회 제한: `revision_count`를 State에 추가하여 무한 루프 방지
- [x] Grounding Policy 적용: 프롬프트를 통해 존재하지 않는 출처 생성 금지, 사실/추론 구분 지시
- [x] 기존 법률 엔진 정상 실행: `ai-legal-agent` 코드를 수정하지 않고 런타임 종속성 없이 동작 유지
- [x] React 검증 결과 표시: `ConsultationResponse` 확장 및 `App.tsx` UI 개선 (상태, 재검토 횟수, 경고, 개발자 정보 표시)
- [x] AOP 및 TokenTracker 통합: ContextVar(`_retrieved_sources_var`) 추가 전파 및 Trace별 토큰 계측 합산 보완
- [x] 자동 테스트 통과: AzureChatOpenAI 연동 이슈 해결 및 `test_housing_lease.py` 실행 완료
- [x] 주택임대차 실제 질문 검증: 묵시적 갱신 해지 등 실전 질의 테스트 결과 분석
- [x] 개발 및 평가 문서 작성: 요구된 7개 문서 작성 완료

## 2. 발생 이슈 및 해결 사항
- **비동기 ContextVar 충돌**: `asyncio.to_thread(ctx.run)` 직접 호출로 인한 에러를 파이썬 3.9+ 기본 컨텍스트 복제 동작에 위임하여 해결.
- **RAG 출처 누락**: 기존 AgentExecutor 구조에서 반환되지 않던 검색 문서 정보를 ContextVar를 통해 우회 추출하여 State로 승격.
- **Azure OpenAI 구조화된 출력 미지원**: `.with_structured_output()` 호출 시 400 에러가 발생하는 구형 Azure 모델 호환성 문제를 JSON 수동 파싱 방식으로 교체.

## 3. 미검증 사항 및 한계점
- **국제법 등 데이터 없는 RAG**: 이번 단계의 요구사항에 따라 RAG 데이터 확충은 제외되었습니다.
- **UI 디자인 한계**: 복잡한 사건 관리 화면은 제외하라는 지시에 따라, React 기본 화면에 최소한의 박스 형태로 정보 패널만 추가했습니다.

## 4. 향후 계획
P2.1 완료에 따라, 위 내용 검토 후 P2.2 혹은 다음 단계 착수 지시를 기다리겠습니다.

