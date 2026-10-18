# AI Legal Helper — Self-Correction 및 Self-Evolving 개념 적용 검토 보고서
## 1. 개념 정의 및 차이점 비교

두 개념은 모두 시스템이 오류를 극복하고 성능을 높이는 메커니즘이지만, **작동 시점(Time Horizon)**과 **영향 범위(Scope)**에서 본질적인 차이가 있습니다.

비교 항목	Self-Correction (즉각적 자기 교정)	Self-Evolving (지속적 자기 진화)
작동 시점	세션 내부 (In-Session / Runtime)
단일 상담 요청 처리 중 실시간 실행	세션 간 (Cross-Session / Offline & Async)
수많은 상담 경험이 누적된 후 지속적 갱신
핵심 목적	현재 사용자의 특정 질문에 대한 답변 무결성·환각 차단	다음 사용자의 질문에 대한 초기 적중률·추론 능력 향상
수정 대상	현재 작성 중인 초안(draft_answer), 검색 질의, 인용 부호	프롬프트 템플릿, Few-shot 예시 라이브러리, RAG 지식베이스, 라우터 가중치
주요 기술	Reflexion, Critique-and-Refine, Corrective RAG (CRAG)	Episodic Memory, Dynamic Few-shot, Prompt Optimization (DSPy/TextGrad), 지식 자동 수집
2. 현재 AI Legal Helper의 구현 현황 및 한계점 진단
2.1 Self-Correction 현황: 초기 수준 (Level 2) 구축 완료
기구현 내용:
Synthesizer → Verification Agent의 검증 피드백 → Revise 노드의 적응형 보강 검색(1회).
법률 근거 누락 감지 시 HILT (statute_search_approval) → 법제처 API 연동 → re_analyze 재분석.
결정론적 출처 감사(audit_citations_and_claims)를 통한 허위 인용 정제(sanitize_unverified_citations).
한계점:
전면 재생성(Full Regeneration) 비용: 경미한 모순이나 조문 오기가 발생해도 답변 전체를 다시 생성하여 LLM 비용과 지연시간(Latency)이 증가함.
단일 관점 검증의 맹점: 한 명의 Verifier LLM이 법리, 사실관계, 인용을 한 번에 검토하다 보니 서두 안내문과 본문 설명의 사소한 차이를 모순으로 오탐하는 현상 발생.
2.2 Self-Evolving 현황: 미도입 상태 (Level 0, 정적 파이프라인)
한계점:
경험 휘발성 (Static Agent): HILT를 통해 어렵게 법제처에서 주택임대차보호법 제6조의2를 확보하고 완벽한 답변을 작성했더라도, 세션이 종료되면 그 경험이 휘발됨. 다음 사용자가 동일한 묵시적 갱신을 질문하면 또다시 RAG 부재 → HILT 승인 요청 절차를 반복해야 함.
반복 오류 학습 부재: Verifier가 자주 지적하는 실무상 주의사항 누락이나 질문 분석 실패 패턴이 프롬프트 개선에 자동으로 피드백되지 않음.
3. Self-Correction 고도화 방안 (세션 내 즉각 교정)

단일 상담 내에서 환각을 원천 차단하고 빠르게 수렴하기 위한 3단계 고도화 전략입니다.

3.1 Surgical Correction (부분 정밀 교정)
개념: 전체 답변을 재작성하지 않고, Verifier가 grounding_status == UNSUPPORTED 또는 contradictions로 지정한 특정 문장/단락만 핀포인트로 교정.
효과: 응답 속도 50% 단축, 다른 잘 작성된 단락의 부수적 왜곡(Regression) 방지.
3.2 Corrective RAG (CRAG) 기반 쿼리 자체 교정
단순 키워드 결합(질문 + missing_issues)에 의존하지 않고, Verifier가 식별한 쟁점을 바탕으로 LLM이 법률 검색에 최적화된 **가상 법조문/판례 요지(HyDE: Hypothetical Document Embeddings)**나 표준 법률 개념어로 질의를 재구성하여 벡터/그래프 검색을 재수행.
4. Self-Evolving 아키텍처 설계 (세션 간 지속 진화)

누적된 상담 데이터와 사용자 상호작용을 자산화하여 시스템이 스스로 똑똑해지는 3대 진화 루프입니다.

4.1 동적 지식베이스 자동 진화 (Knowledge Self-Ingestion)
작동 방식:
HILT를 통해 법제처 API에서 성공적으로 조회된 법령 조문(주택임대차보호법 제6조의2 등)을 세션 종료 후 백그라운드 Worker가 로컬 ChromaDB(law_docs_civil) 및 Neo4j 그래프에 자동 색인.
기대 효과:
첫 번째 사용자는 HILT를 거치지만, 두 번째 사용자부터는 내부 RAG에서 0.3초 만에 즉각 검색 성공! (시스템의 법률 커버리지가 사용할수록 자연 확장됨)
4.2 에피소딕 사례 메모리 및 Dynamic Few-Shot (Case-Based Reasoning)
작동 방식:
Verifier 종합 점수 1.0(PASS, 출처 일치도 100%)을 기록하고 의뢰인이 유용하게 활용한 고품질 상담 케이스를 개인정보(PII) 탈색 후 LegalCaseMemory 벡터스토어에 저장.
신규 질의 인입 시 가장 유사한 성공 상담 사례 1~2건을 프롬프트의 Few-Shot 예시로 동적 주입.
기대 효과:
복잡한 사실관계(예: 배우자 전화 통지의 효력 등)에서 모범적인 법률 추론 경로(Chain-of-Thought)를 학습하여 초기 초안의 품질이 대폭 향상됨.
4.3 실패 패턴 기반 프롬프트/가이드라인 자율 진화 (Prompt Optimization)
작동 방식:
Langfuse에 기록된 REVISE, INSUFFICIENT, 검증 모순 지적 트레이스를 주기적(주간 단위)으로 분석.
반복 지적되는 엣지 케이스를 추출하여 에이전트 프롬프트의 주의사항(Guideline) 섹션에 자동으로 후보 규칙을 생성하고, 벤치마크 테스트 통과 시 운영 프롬프트로 승격.
5. 법률 AI 특화 가드레일 (환각 전염 방지 대책)

일반 도메인과 달리 법률 시스템의 자율 진화에는 환각 자가 증폭(Self-Reinforcing Hallucination) 위험이 있습니다. 잘못된 분석 결과가 지식베이스에 들어가면 이후 모든 답변이 오염되기 때문입니다.

엄격한 승격 게이트 (Gating Policy):
오직 Verifier PASS 1.0 + 출처 완전 뒷받침(Support Rate 1.0) + 미검증 출처 0건을 동시에 만족한 데이터만 진화 데이터셋으로 승격.
법령 원문과 해설의 분리:
법제처 API에서 내려온 공인 조문 원문은 즉시 지식베이스로 적재하되, LLM의 해석이나 추론은 에피소드 메모리(참고용)로만 분리 격리.
개인정보 비식별화 (Anonymization):
사건 메모리 저장 전 인명, 지명, 전화번호, 금액의 고유 식별값을 일반 토큰([임대인 A], [보증금 N억원])으로 자동 마스킹.
6. 단계별 도입 로드맵 제안
단계	추진 과제	난이도	기대 효과
Phase 1
(즉시 추진)	HILT 조회 법령 로컬 RAG 자동 캐싱
- 법제처에서 조회한 법령을 로컬 ChromaDB에 영구 적재	낮음	동일 특별법 질문 시 반복적인 HILT 승인 대기 제거
Phase 2
(단기)	Surgical Self-Correction & CRAG 도입
- Verifier 오류 단락 부분 수정
- 법률 용어 기반 쿼리 재구성	중간	응답 속도 향상, 토큰 비용 절감, 검색 재적중률 향상
Phase 3
(중기)	에피소딕 메모리 기반 Dynamic Few-Shot
- 검증 완료된 우수 상담 케이스의 동적 추론 주입	중간	복잡한 쟁점에 대한 초안 작성 완성도 극대화
Phase 4
(고도화)	Langfuse 트레이스 기반 프롬프트 자동 튜닝
- 실패 로그 군집화 및 가이드라인 자동 개선 파이프라인	높음	운영자의 수동 개입 없는 지속 가능한 제품 진화 달성

이상의 방향 중 가장 우선적으로 프로토타입을 적용해보고 싶으신 단계나 세부 항목이 있으시면 말씀해 주세요. 상세 설계 및 구현 방안을 구체화하겠습니다.