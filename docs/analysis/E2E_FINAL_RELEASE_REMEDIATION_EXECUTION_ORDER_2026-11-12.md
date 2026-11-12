# AI Legal Helper E2E — 최종 통합 개선작업 실행지시서

**작성:** 2026-11-12 · **출시 판단 마감:** 2026-11-13  
**대상:** `yjjungyo/ai-legal-helper` · **성격:** Gemini/ChatGPT 통합 단일 실행안. **비교 보고서가 아니다.**  
**상태:** GitHub에 있는 소스·로그·감사·Trace 비교 보고서 기반 **최종 작업 계획**. 이 문서 작성으로 실제 코드 수정이나 E2E 재실행이 수행된 것은 아니다.

## 1. 반드시 보존할 고객가치

사건 중심 연속 상담: 증거 등록·추출·승인 → 사실/타임라인·상충 관리 → 질문 → **사건 시점에 맞는 실제 법령/부칙** → 검증된 답변·대응 계획·문서. 정확한 결론뿐 아니라 **왜 그런 결론인지**, 어떤 사실이 승인·미승인·불명확한지, 출처 파일명과 조문/시행본이 무엇인지 확인 가능해야 한다. **답변 품질·정확성은 응답속도/비용보다 우선**한다. 임대차 MVP 범위 유지, 일반 사용자 친화적 서술, HITL·증거 변경 시 재상담 경고·PostgreSQL 체크포인트 재개를 보존한다.

## 2. 이번 계획의 실제 근거 및 신뢰 한계

### 2.1 확인한 자료

1. **2026-11-12 Codebase Audit (Gemini)**: `docs/analysis/CODEBASE_IMPROVEMENT_AND_PERFORMANCE_AUDIT_REPORT_2026-11-12.md`; 로컬 동일 버전 소스·실행 로그·Langfuse trace를 Gemini가 검토한 결과.
2. **2026-11-12 Consultation Quality/Performance/Cost (ChatGPT)**: `docs/analysis/CONSULTATION_QUALITY_PERFORMANCE_COST_REVIEW_2026-11-12.md`.
3. **2026-11-11 종합 소스·로그 감사**: `docs/analysis/COMPREHENSIVE_CODE_LOGIC_PROMPT_AUDIT_REPORT.md`; 27개 `backend/logs/app.log*`를 집계했다고 기록. **과거 날짜의 집계는 현재 결함 확정 증거가 아니다.**
4. **GitHub 원본 로그 직접 확인**: `backend/logs/app.log.2026-11-10`의 18:25 상담 구간, `backend/logs/app.log.2026-10-27`의 서버/체크포인터 초기화 구간.
5. **실제 Langfuse 비교 보고서**: `docs/evaluation/kpi/TRACE_COMPARISON_A99777E7_VS_9AA92B46.md` (2026-11-01). 141.3→220.2초, 96,420→169,294 토큰, 5→7회 LLM, $0.3765→$0.6493. **품질 개선이 시간·비용 증가를 동반한 실제 사례**.
6. **Gemini KPI 자동평가**: `docs/evaluation/kpi/AI_Legal_Helper_KPI_202611120608_자동평가_e2ev2.xlsx`의 GitHub 추가 커밋 `05b9e79b40ae8999ec83cd38b0bd0e4b397d76b6` 확인. **이 검토에서 엑셀 내부 셀/수식과 로컬 Langfuse 원본 API를 직접 재계산하지는 않았다.** Gemini가 동일 로컬 환경에서 실측한 결과를 1차 근거로 삼고, 변경 후 같은 기준으로 재측정한다.
7. 현재 관련 소스: `legal_workflow.py`, `temporal_search_plan.py`, `grounding_context.py`, `document_answer.py`, `document_consultation.py`, `qa_checker.py`, `case_briefing.py`, `verification.py`, 프론트 `VerifiedPresentationView.tsx` 등.

### 2.2 로그가 실제로 보여준 것 — 작업 순서 결정의 핵심

| 직접 확인된 실행 로그 | 의미 | 개선 결론 |
|---|---|---|
| 11/10 18:25:13 `DB 누적 10턴 중 최근 3턴 유지`, 현재 11턴 | 실제 3턴 이력 로드 | 후속 질문 보존하면서 중복 입력 줄일 것 |
| 같은 상담 `이전 턴 검증 법령 출처 8건 계승` | 과거 출처 재사용 존재 | 법령 버전·시점 확인 없이 무조건 재사용 금지 |
| `supervisor_initialize` 컨텍스트 4,016자 | 초기 컨텍스트 크기 확인 | 전체 토큰 급증의 유일 원인이라고 단정 금지 |
| `statute_search_plan status=SKIP ... OFFICIAL_LAW_ID_UNCONFIRMED` | 공식 법령 ID 부족으로 시간성 사전 점검 건너뜀 | **검색/법령 ID 매핑과 시간성 커버리지 개선 우선** |
| `run_agents`에서 주택임대차보호법 6건·민법 2건 로컬 사전 적재 | 로컬 조문 선확보 실제 동작 | 이미 확보한 **동일 시행본** 재검색만 줄일 것 |
| `run_agents` 문서 검색 27건, 완료 **972.9ms** | 검색 자체는 해당 구간 약 1초 | 이 구간을 100초 병목으로 오판 금지 |
| `legal_evidence_bundle` 완료 **11.8ms** | 이 실행에서는 노드 자체 극히 짧음 | **노드 인라인화는 출시 전 우선순위 제외** |
| `EVIDENCE_BUNDLE warnings=['DIGEST_TRUNCATED','SOURCE_VERSION_ID_UNCONFIRMED','TEMPORAL_APPLICABILITY_UNCONFIRMED']` | 검색량/버전/적용시점 위험이 **동일 상담에서 관측** | 법령 버전·원문 누락을 먼저 해결 |
| 10/27 `PostgreSQL checkpoint tables initialized successfully` | 초기화 성공 실행 존재 | '항상 메모리 강등' 단정 금지; 재개 테스트로 판정 |

**추가 해석:** 11/10 로그는 검색 완료 이후 전체 상담의 최종 latency·LLM 토큰을 증명하지 않는다. 여기서 인용한 수치는 **특정 노드의 특정 실행**이며 전체 시스템 평균이 아니다. 로그의 `SOURCE_VERSION_ID_UNCONFIRMED`는 법령 버전이 실제로 틀렸다는 증거가 아니라 **확인되지 않았다는 신호**다. `DIGEST_TRUNCATED`는 누락된 부분이 법률 결론에 중요한지 추가 검증해야 한다.

### 2.3 오래된 감사 진단의 현재 적용 주의

11/11 감사에는 `GraphInterrupt` ERROR 오인, `get_checkpointer()`가 항상 메모리 반환, 지연 콜백 352회, parent span 미해결 300+회, `ConsultationIntent` 역직렬화 97회, OTel status 경고 94회, DB `conversation_id` 컬럼 오류 12회, timeout 6회 등이 기록되어 있다. **이들은 과거 로그 집계/해당 시점 코드에 대한 진단**이다. 최신 `observability/decorators.py`의 GraphInterrupt 처리와 `run_legal_consultation()`의 AsyncPostgresSaver 주입 경로가 이미 개선되어 있을 수 있다. **오래된 집계 수치만 보고 수정하지 말고 최신 로그·현재 테스트로 잔존 여부 확인**. 단, **Langfuse 누락이 실제 지속되면 KPI 신뢰성을 직접 해치므로 먼저 수정**한다.

## 3. 최종 작업 원칙 및 순서

**순서 고정:** 기준선/관측성 → 실제 법령·증거 무결성 → 검증/답변 일관성 → 실제 병목 최적화 → 사용자 화면/HITL → 전체 E2E 회귀 → 출시 판단. 각 단계는 **최소 변경 + 재현 테스트 + 전체 영향 검토 + 커밋 + 사용자 승인** 후 다음 단계. 11월 13일 마감 때문에 대규모 graph 분할, 도메인 확장, 미사용 코드 일괄 삭제는 금지한다.

| 순서 | 카드 | 필수 결과 | 우선순위 |
|---|---|---|---|
| **00** | 실행 버전·KPI·Trace 고정 | 동일 SHA/입력/trace ID 기준선 | 필수 |
| **01** | Langfuse·로그 신뢰성 및 체크포인트 재개 확인 | 누락/오염 없는 계측, HITL resume | 필수 |
| **02** | 법령 ID·버전·시행일·부칙·날짜 역할 정합 | 시점 오판·출처 소실 방지 | 차단 |
| **03** | 증거·승인·EvidenceSpan·반대 증거 보존 | 근거/승인 오염 방지 | 차단 |
| **04** | 금액 QA·검증·부분 수정 루프 안전화 | 올바른 답변 오수정/허위 PASS 방지 | 차단 |
| **05** | 답변 생성·최종 표시 의미 일관성 | 결론/조치/근거/불확실성 보존 | 필수 |
| **06** | 실제 병목: NEED_MORE_LAW·법령 검색/검증 중복 | 정확도 유지하며 지연·호출 축소 | 조건부 |
| **07** | 사건 컨텍스트·대화 이력·프롬프트 중복 제거 | 후속 질문 유지, 입력 토큰 감소 | 조건부 |
| **08** | UI 중복 렌더·진행상태·HITL UX | 정상 화면/대기/재개 | 필수 |
| **09** | 전체 E2E 품질·성능·비용·장애 회귀 | 출시 판정 근거 | 필수 |
| **10** | 출시 Go/No-Go·릴리스 고정 | 증거 기반 결정 | 필수 |

## 4. 카드별 Gemini 실행 지시

### 00 — 기준선·KPI·Trace 동결 (코드 수정 금지)

1. 현재 `main` SHA, 로컬 `git status`, 로컬 HEAD, 테스트 환경 모델/DB/법령 인덱스 버전을 기록하고 작업 브랜치 생성.
2. 기존 KPI 자동평가 엑셀의 **실제 시트/행/trace ID/점수 산식/비용**을 읽어 `baseline_manifest` 작성. SC001-1/2/3, SC002-1, SC003-1을 **각각 같은 입력 조건**으로 매핑. Gold/증거 등록 순서·승인 상태·사건 DB snapshot 기록.
3. 각 trace의 `node→generation→token→latency→search→HITL wait→verify→revise`를 트리로 작성. input/output/cached token, 비용/통화, 모델명, 대기 포함/제외 경과시간 분리.
4. 11/10 로그와 KPI의 시점·SHA가 다르면 **다른 실행을 같은 측정치로 혼합 금지**.
5. **제출:** baseline 표, trace 링크/ID, 실행 명령, 데이터/모델 버전, 미확인 측정 항목.

**Gate:** baseline 재현 가능. 실패 시 다음 코드 변경 금지.

### 01 — 관측성 신뢰성·HITL/체크포인트 (진단 후 최소 수정)

1. 최신 로그에서 `DELAYED_CALLBACK_IGNORED`, `SPAN_PARENT_UNRESOLVED`, `GraphInterrupt` ERROR, `ProactorEventLoop`, `conversation_id` DB 오류를 검색해 **현재 발생/과거만 발생**으로 구분.
2. trace generation 수와 LLM gateway 실제 호출 수, input/output token 합, 비용 합이 일치하는지 점검. 불일치가 있으면 **누락된 Langfuse 값을 0으로 취급해 최적화 성과로 계산하지 말 것**.
3. PostgreSQL `AsyncPostgresSaver` 활성 실행에서 승인 대기→프로세스 재시작→동일 thread/case 재개, 거절/중복 승인, 증거 snapshot 변경 테스트.
4. 현재 정상 동작 중인 GraphInterrupt 예외 처리·checkpointer를 다시 바꾸지 않는다. 지연 콜백은 비동기 span 종료 순서·flush/await·context propagation을 원인으로 재현한 뒤 국소 수정.
5. **Gate:** 실제 호출/토큰 계측 정합, HITL 재개 PASS. 미해결 관측성 문제는 KPI 신뢰도에 표시.

### 02 — 법령·시간성 정확도 (최우선 법률 품질)

**관련:** `legal_workflow.py`, `temporal_search_plan.py`, `grounding_context.py`, `document_answer.py`, `temporal_verification.py`, `official_statute_search.py`.

1. **실제 관측 경고부터:** `OFFICIAL_LAW_ID_UNCONFIRMED`, `SOURCE_VERSION_ID_UNCONFIRMED`, `TEMPORAL_APPLICABILITY_UNCONFIRMED`, `DIGEST_TRUNCATED`의 발생 조건/후속 영향/회복 경로를 trace로 추적.
2. `normalize_statute_key`의 dedup은 법령 ID·조문·시행본·개정번호·부칙·원문 해시를 구분. 다른 시행본을 같은 조문명이라는 이유로 소거 금지. 단, 실제 중복 문서는 압축 가능.
3. `event_type='CONTRACT_SIGNED' if extracted_date`와 temporal planner `explicit_pair`의 결합을 수정: 질문의 날짜가 **계약/갱신/변경/통지/법령 공포/시행 중 무엇인지** 의미 해석; 확실하지 않으면 null 및 추가 판단. 날짜 정규식은 후보 추출에만 사용.
4. `document_answer.py`의 '최근 시행본 기본 법리는 과거 계약에도 원칙적 적용' 가정을 제거. 법령 본문+부칙+사건일의 실제 적용을 의미적으로 검증. `계약부터 적용한다` 등 표현을 특정 regex와 불일치한다고 LLM의 올바른 PASS를 뒤집지 않음.
5. `temporal_verification.py`의 키워드 기반 트리거만으로 시점 검증을 결정하지 않도록 **사건일과 법령 버전 충돌**도 판단. '개정' 단어 없는 과거 계약 질문 포함.
6. **회귀:** 실제 2026-10-27 개정/2027-04-28 시행 민간임대주택 시행령 제36조와 부칙 제1·2조; 2026-11-01 계약, 시행 후 계약·갱신·변경, 법령 ID 미확인, 두 시행본 혼재, 부칙 없는 검색 결과.
7. **Gate:** 조문 신설 사실과 현재 비적용을 모두 정확히 설명, 근거 링크/시행본 보존. **공식법령 부족이면 조용히 READY 강제 금지**.

### 03 — 증거·승인·EvidenceSpan·검증 근거 (최우선 고객가치)

**관련:** `case_briefing.py`, `document_consultation.py`, `grounding_context.py`, `verification.py`, 증거 일괄 승인 API/DB.

1. 실제 `증거 업로드→사실추출→일괄 승인→Claim/Fact/EvidenceSpan DB→briefing→답변 인용`을 재현하고 EvidenceSpan 공란 원인을 FK/transaction/offset/배치 저장별로 구분.
2. `case_briefing.py` 최근 fallback의 `approved_claims→전체 doc_claims→원본 파일` 경로를 **원문/승인 사실/미승인 진술로 타입 분리**. `APPROVED` 문서 상태와 개별 Claim 승인 상태를 혼동하지 않음. 원문 없는 Claim 목록을 '원문 발췌'라고 표시 금지.
3. `grounding_context.py`의 메타데이터 다이어트로 `source_kind`, review/approval scope, 원본 파일명, 법령 시행본이 사라지지 않는지 테스트.
4. 검증기가 **초안이 인용하지 않은 반대 증거**도 볼 수 있도록 쟁점별 relevant+contradictory span을 독립 선택. 모든 원문 무제한 재투입 대신 원문 ref/범위/해시 manifest 유지.
5. `DIGEST_TRUNCATED` 발생 시 **중요 반증/부칙이 잘린 상태로 PASS하지 않는지** 검증. 필요 시 targeted retrieval 또는 '근거 부족' 명시.
6. **회귀:** E01~E17 일부 승인/반려, 문서 추가/수정, 원본 파일명, 보증금 분할 반환 제안과 전액 즉시 반환 곤란의 비상충, 선순위/후순위 권리, 상담 후 증거 변경 경고.
7. **Gate:** 반려 사실의 확정 채택 0, 인용한 원문 span 추적 가능, 미인용 결정적 반증 누락에 따른 허위 PASS 0.

### 04 — QA·Verification·Repair의 의미적 안전성

**관련:** `qa_checker.py`, `verification.py`, `document_answer.py`, `document_consultation.py`, `final_disposition.py`.

1. `deposit_matches[0]`를 보증금 원금의 근거로 자동 선택해 정확한 잔액을 오수정하는 경로 제거. 계약금/잔금/원보증금/반환액/미반환액/약속액/가압류 청구액을 **role+date+source**로 구분. 계산은 Python, 역할·증거 해석은 구조화 사실/의미 판단.
2. `verification`의 Grounding/Statute/Temporal/Question Coverage 각 판단에 **실제 사용한 source ID·시행본·Claim**을 연결. source conflict 없는 올바른 PASS를 문자열 regex가 뒤집지 않게 함.
3. **부분 패치 실패**(`AMBIGUOUS_PARTIAL_REVISION_TARGET`) 시 **수정 전 초안을 다시 그대로 검증하는 no-op loop**가 있는지 재현. patch가 적용되지 않으면 무의미한 재검증 금지. 원문 보존이 중요하므로 변경 영역 한정 재작성 우선; 안전한 단일 전체 재작성은 원문/근거 비교 검증을 조건으로 1회만 허용.
4. 검증 JSON 스키마 축약은 **필수 검증 필드 유지·parser 회귀 테스트** 후 별도 적용. 스키마 단순화가 누락 판정으로 이어지면 롤백.
5. **Gate:** 허위 QA REPAIR 0, no-op 재검증 0, 필수 근거/조건/예외 유지.

### 05 — 상담 결과 생성·표시의 단일 의미 계약

1. `document_consultation`, `synthesizer`, `final_disposition`, `presentation/builder`, `consultationDigest`, `VerifiedPresentationView`의 **실제 호출 분기와 데이터 계약**을 작성. 서로 다른 답변 경로를 출시 전 무조건 통합하지 말 것.
2. 공통 `AnswerPresentation` 의미 필드: 핵심 결론, 지금 해야 할 일, 상세 분석, 증거·법령 근거, 추가 확인사항, 불확실성, source IDs. **검증 완료 답변의 의미를 formatter가 재작성하지 않도록**.
3. 일반 상담의 `clean_markdown_formatting`으로 볼드/헤더가 삭제되는 경로와 문서 상담의 Markdown 유지 경로를 동일 렌더 규칙으로 조정. 법률 문구를 단순 UI 목적으로 수정하지 않음.
4. `1. 핵심 결론` 등 **정식 섹션 헤딩만** 인식하고 일반 번호 목록은 보존. `LEAD=fullAnswer`일 때 상세에 같은 원문 다시 표시 금지.
5. **Gate:** 결론/상세 중복 0, 출처 링크/전체 파일명 유지, 답변 내용·조건·예외 유실 0.

### 06 — Langfuse 실측 최대 병목부터 최적화

**출시 전 적용은 정확도 02~05가 PASS한 범위에 한정.**

1. KPI/trace에서 실제 최대 지연 순위(LLM draft, verify, re-analyze, HITL wait, official search, DB, checkpoint)를 확정. **11/10 로그의 evidence bundle 11.8ms를 성능 핵심으로 선정하지 않는다.**
2. `NEED_MORE_LAW`는 로컬 조문 **존재**가 아닌 `law_id+article+version+effective_date+supplementary_provision+issue_coverage` 충분성으로 판단. 이미 충분한 동일 출처의 재검색만 제거. 법령이 불충분하면 공식 검색·HITL 유지.
3. 법령 검색 요청 dedup/cache는 시행본·조회시점·부칙·공식 출처를 cache key로 하고 TTL/무효화 정책 기록. 최신 법령 요청에서 오래된 cache를 무조건 사용 금지.
4. 검증이 실패했을 때 새 출처/수정 초안/판정 변경이 없다면 동일 입력의 재검증 반복을 중단하고 근거 부족을 명시. **법률 검증 횟수를 고정 1회로 제한하지 않는다.**
5. 2026-11-01 trace 비교의 **141.3초·96,420토큰(불완전 법령 검색)**과 **220.2초·169,294토큰(신설 조문·부칙 확보)** 사례는 성능 개선의 **금지 회귀 사례**로 사용: 단순히 빠른 옛 결과로 돌아가면 실패. 올바른 법령 해석을 유지한 상태에서 비용만 절감해야 한다.
6. **Gate:** 동일 Gold·동일 source coverage·동일 핵심 결론에서 latency/input/output tokens/LLM calls/cost 감소. 미개선·품질 하락 시 롤백.

### 07 — 입력 토큰·사건 이력 최적화

1. 11/10 로그의 최근 3턴 로드와 검증 법령 8건 계승 경로를 기준으로, `messages`, `case_context`, `user_history`, 법령 원문, 증거 원문, verification JSON의 **각 토큰 구성비**를 계산.
2. **사건 SSOT는 승인된 사실/증거/타임라인 DB**. 이전 LLM 답변은 법률적 사실의 원본이 아니다. 기본 질문에서는 필요 없는 이전 AI 답변 원문을 제외; '그럼?', '앞서 말한 계약' 등 후속 질문만 필요한 최소 발언·사건 참조를 복원.
3. 이전 턴 법령 8건을 계승할 때 **출처 ID·시행본·질문 기준일·증거 snapshot**을 확인. 법령 계승을 없애 재검색을 늘리는 것도, 오래된 법령을 무검증 재사용하는 것도 금지.
4. 중복 메타데이터 제거는 가능하나 원문 파일명/승인 상태/시행일/부칙/반대 증거는 보존. `DIGEST_TRUNCATED` 발생 빈도·원인 추적.
5. **Gate:** SC001 3턴 연속·새 증거 등록 후 재상담·후속 지시어 복원 PASS; 토큰 실제 절감. 대화 맥락 손상 시 즉시 롤백.

### 08 — UI·진행상태·HITL 최종 품질

1. `ConsultationProgress.tsx`의 단계 ID와 서버 `step_1..step_6`·`STATUTE_APPROVAL` 이벤트 계약을 통일. 특정 단계 번호에 승인 대기를 고정하지 않음.
2. 노드 시작/완료/실패/승인 대기/재개를 사용자에게 정확히 표시. LangGraph updates가 완료 이벤트만 주는 경우 서버 측 상태 전이를 보완. **가짜 진행률 금지**.
3. 답변 중복, 인용 클릭, 증거 수정 후 '재상담 필요', ChatGPT형 하단 입력창, 기존 상담 이력 유지 테스트.
4. **Gate:** 승인·거절·재시작/재개 UI PASS, 표시 답변 중복/누락 0.

### 09 — 최종 통합 회귀 및 KPI 재측정

**필수 실행 세트:**
- SC001: 증거 시간순 추가 + 연속 3회 상담, 사실 갱신·후속 질문.
- SC002: 전체 증거 일괄 등록 + 단일 상담, 승인/반려·충돌 판단.
- SC003: 실제 법령 개정/시행일·부칙 제1·2조, 현재/미래 계약 적용.
- 준비된 SC005~SC007 중 **실제 법령 기반**만 제품 출시 정확도 판정에 사용. 저장소 `docs/testset/README.txt`에는 SC007 가상 법령 시나리오 설명도 있으므로 **가상 법령을 실제 법률 자문 정확도 지표와 혼합 금지**.
- 추가 회귀: 두 시행본, 부칙 잘림, 미인용 반증, 금액 역할, EvidenceSpan 공란, HITL 재시작, 공식 API 오류, UI 중복, 인증/DB/ChromaDB 시작.
- 결과: 질문/증거/법령 snapshot/commit/trace ID, 법률 Gold, 핵심 결론 PASS/FAIL, 사실·증거 인용·시간성·행동 가이드, latency P50/P95, 승인 대기 포함/제외, LLM input/output/cache tokens, 호출수, 비용, 미해결 이슈.
- **목표값(보장 아님):** 평균 60초 이하, 동일 입력 기준 토큰·비용 30% 이상 절감, 평균 2~3회 호출. 성능 목표 미달과 법률 품질 미달을 별도 판단한다.

### 10 — 출시 판정과 범위 통제

**즉시 No-Go:** 법령 시점·부칙 오적용, 핵심 반대 증거 누락으로 허위 PASS, 반려 Claim을 확정 사실로 채택, 보증금 잔액 오수정, 답변 핵심 섹션/근거 누락, HITL 재시작 후 상태 소실, 사용자 사건 간 정보 혼합. 해결되지 않으면 날짜를 맞추기 위해 검증을 약화하지 않는다.

**출시 후 backlog:** `legal_workflow.py` 5,746행 분리, `plan_node`·`intent_analysis_node` 및 `pre_synthesis_coverage.py` 삭제 검토(테스트 import 확인), `legal_evidence_bundle` 인라인(11/10 관측 11.8ms라 우선순위 낮음), 그래프 전체 재설계, 노동법 등 범위 확장, 검증 병렬화. **노드 수 감소 자체를 KPI로 삼지 않는다.**

## 5. 마감 운영: 각 카드별 작업 제출 형식

```text
[카드/상태] 02 / READY_FOR_REVIEW
[Git] base SHA / head SHA / branch / 변경 파일
[원인] 실제 로그 시간·request/trace ID, 소스 함수, 최소 재현 입력
[변경] 무엇을 왜 변경했는지, 법률 의미/승인 상태/원문 영향
[테스트] 실행 명령, 단위/통합/SC 회귀 PASS·FAIL, 전후 법률 결론 diff
[측정] 동일 입력의 latency/LLM calls/input·output tokens/cost (실측/미측정 구분)
[안전] 근거 파일명, 시행본·부칙, 반대 증거, HITL, 후속 상담 영향
[결정] 유지/롤백/보류 및 사용자 승인 필요사항
```

**병렬 작업 허용:** 백엔드 정확도 02~04와 프론트 UI 08은 별도 브랜치에서 작업 가능하나, 병합 전 공통 데이터 계약 및 전체 E2E 회귀 필수. **시간 부족 시 00·01·02·03·04·05·08·09·10을 우선**, 06·07은 정확도 보장 범위에서만. **테스트 시간을 확보할 수 없는 새 최적화는 병합 금지.**

## 6. 최종 개발 지시

Gemini는 **카드 00부터 시작**하여 기존 KPI 자동평가 엑셀과 Langfuse 원본 trace를 연결한 baseline을 먼저 제출한다. 그다음 **GitHub 로그에서 이미 확인된 `SOURCE_VERSION_ID_UNCONFIRMED`, `TEMPORAL_APPLICABILITY_UNCONFIRMED`, `DIGEST_TRUNCATED`를 우선 재현**하고 02→03→04 순으로 국소 수정한다. **기존에 올바른 부칙 해석을 가능하게 한 검색/검증을 제거하지 않는다.** 개선 효과는 **올바른 답변을 유지한 동일 조건**에서만 인정한다. 사용자 승인 없이 출시 준비가 끝났다고 선언하지 않는다.

**최종 목적:** AI Legal Helper가 사건을 잊지 않고, 승인된 증거와 실제 시행 법령을 올바르게 연결하며, 일반인이 이해할 수 있는 대응 방향을 **정확하고 빠르고 경제적으로** 제공하는 E2E 제품.
