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

---

# 7. 상세 개발 설계 — 구현 방식·호출 정책·데이터 계약·실패 처리

> 이 장은 **개발자가 그대로 구현을 시작할 수 있는 설계 지시**다. 위 00~10 순서는 유지한다. 아래의 함수·타입은 **제안 인터페이스**이며 기존 코드에 동일 이름이 이미 존재한다는 뜻이 아니다. 실제 수정 전에 해당 파일의 최신 함수 시그니처·테스트·DB 스키마를 확인하여 **기존 기능을 재사용**한다. 단일 거대 PR 금지.

## 7.1 룰 기반 / LLM / DB / 검색의 책임 구분

| 작업 | 우선 방식 | LLM 사용 조건 | 금지 사항 |
|---|---|---|---|
| 날짜 문자열 추출·ISO 정규화 | Python 정규식+datetime/dateutil | **없음**: 추출 자체는 결정적 | 날짜 발견만으로 계약일로 확정 |
| 날짜가 무엇을 뜻하는지(계약/갱신/통지/시행) | 구조화 승인 사실·문서 필드 우선, 애매하면 **기존 의도/사실 추출 LLM 호출에 포함** | 역할 모호하고 결론에 중요한 경우에만 **1회 구조화 판정** | 문장에 '계약' 단어만 있다고 무조건 계약일로 지정 |
| 날짜의 선후/기한/산술 | Python date arithmetic | 없음 | LLM에게 날짜 계산 위임 |
| 부칙의 적용대상·경과조치 해석 | 공식 법령 원문+LLM 의미 해석 | 법령 적용 판정의 기존 LLM 호출에 **통합**, 원문과 조건·사건사실 함께 제공 | '경우부터 적용' 같은 특정 regex로 PASS/FAIL |
| 법령 조문/시행본 식별 | 공식 API ID/metadata + 버전별 DB key | 공식 API 후보 다수·법령명 불명확할 때 기존 planner LLM에 통합 | 법령명만으로 다른 시행본 dedup |
| 승인·거절 상태·권한·증거 snapshot | DB 트랜잭션/해시/상태머신 | 없음 | LLM이 승인 상태 변경 |
| 원문 evidence span offset/해시 | Python+DB | 없음 | LLM이 만든 텍스트를 검증 없이 원문 span으로 저장 |
| 사실 후보 추출/금액 의미 역할/실질 상충 | 기존 사실추출 LLM의 구조화 출력 + 근거 | **문서당 기존 추출 호출에 포함**; 모호한 결정적 사실만 후속 호출 | regex 첫 금액으로 전체 보증금 확정 |
| 금액 산술·중복 확인 | Decimal/정규화·구조화 role | 없음 | 산술을 위해 별도 LLM 호출 |
| 법적 결론·증거 해석·검증 | 기존 answer/verification LLM | 기존 호출 유지; 실패 항목만 추가 호출 | 법적 적용을 Python 키워드로 최종 판정 |
| UI 섹션 분할/중복 표시 | 구조화 presentation schema·Python/TS parser | 없음 | UI를 위해 법률 결론 LLM 재작성 |
| 검색 cache/dedup/토큰 집계 | Python/DB/observability | 없음 | 다른 사건/시행본의 cache 공유 |

**원칙:** 룰은 **형식·산술·상태·무결성**을 담당하고, LLM은 **문맥 의미·법적 해석·실질 충돌**을 담당한다. LLM 호출을 추가하기 전에 기존 호출의 구조화 출력에 필드를 추가할 수 있는지 먼저 검토한다. 모든 새 호출은 `reason`, `input_tokens`, `latency`, `cost`, `source_ids` 계측.

## 7.2 카드 00 — 재현 가능한 기준선: 구체 구현

- `EvaluationRunManifest`: `git_sha, scenario_id, question_id, case_snapshot_hash, approved_fact_ids, evidence_hashes, law_index_version, model/deployment, temperature, prompt_version, trace_id, started_at`. 인증키·민감 원문은 로그에 넣지 않는다.
- Langfuse generation별 `input_tokens/output_tokens/cache_read_tokens/model/cost`와 서버 request_id를 연결한다. 로그·Trace·KPI가 다른 날짜/버전이면 `COMPARABLE=false`로 표기.
- `latency_total = finished-started`, `latency_active = total - HITL_wait`; 중첩 노드 시간을 단순 합산해 총 시간으로 오인하지 않는다. P50/P95는 **동일 시나리오 여러 반복 측정**에서만 계산하며 표본 수 표시.
- 변경 전 답변을 `gold_claims`(핵심 결론/법령 적용/증거 사실/조치/미확인 조건)로 분해하되, LLM 평가점수만으로 PASS를 확정하지 말고 법률 Gold와 인용 근거를 함께 확인.
- **테스트:** 동일 케이스 2회 baseline 실행, 실행 식별자/토큰 합계/법령 시행본 기록. 환경 차이 있으면 원인 기록.

## 7.3 카드 01 — 관측성·체크포인터: 구체 구현

- 먼저 최신 main에서 `run_legal_consultation()`이 그래프 `compile(checkpointer=...)`에 무엇을 전달하는지 호출 체인을 추적. `get_checkpointer()` 단독 반환만 보고 버그 판정 금지.
- `GraphInterrupt`는 정상 HITL 제어 흐름이면 INFO + `WAITING_APPROVAL` 상태로 기록; 일반 예외만 ERROR. 인터럽트 시 DB checkpoint를 commit/flush한 뒤 요청 종료. resume 시 `thread_id`, `case_id`, `approval_request_id`, `evidence_snapshot_hash`를 검증한다.
- 지연 callback: 비동기 context propagation을 확인하고, 완료된 span에 나중에 도착한 callback은 idempotent 처리. 유실된 generation이 있으면 `telemetry_incomplete=true`로 KPI 제외.
- UI가 재시도해도 중복 상담 생성/중복 승인되지 않도록 request idempotency key 확인. DB schema migration은 실제 존재 여부 확인 후 추가.
- **테스트:** 승인 대기→API 재시작→resume, 이중 클릭, 다른 사건 thread_id로 재개 거부, 증거 변경 중 재개 시 안전 중단, Langfuse와 LLM gateway 호출수 일치.

## 7.4 카드 02 — 날짜·법령 적용: 상세 알고리즘

### A. 날짜 추출은 **룰 기반**, 의미 역할은 **구조화 사실 우선 + 조건부 LLM**

**Step A1. 후보 날짜 추출 (LLM 0회)**  
Python에서 `YYYY-MM-DD`, `YYYY.MM.DD`, `YYYY년 M월 D일`, 문서의 표준 날짜 필드를 파싱한다. 연도 생략 `9월 30일`은 **사건 타임라인과 문맥으로 연도 확정 가능한 경우만** 정규화; 아니면 `year_unknown`. `2026-02-30` 같은 불가능한 날짜는 오류. `다음 달 말` 같은 상대일은 명확한 기준일과 시점이 있을 때만 계산. 모든 후보에 `text_span, source_id, source_field, date_iso, parse_confidence`를 부여한다. **날짜만 추출해서 법률 사건 날짜로 확정하지 않는다.**

**Step A2. 날짜의 의미 역할 지정**  
우선순위: ① 승인된 DB 사실의 `event_type`과 근거 span ② 계약서 구조화 필드(체결일/시작일/종료일) ③ 동일 문장의 명시적 동사·주어·목적어 ④ 여전히 모호한 경우 **기존 fact extraction / intent analysis LLM의 구조화 결과** ⑤ 결정적 모호성만 단일 LLM 호출 또는 사용자 확인. 규칙이 추출한 `2026-09-30`을 `CONTRACT_SIGNED`로 무조건 지정하는 코드를 제거한다. 날짜 역할 후보: `CONTRACT_SIGNED, CONTRACT_START, CONTRACT_END, RENEWED, CONTRACT_CHANGED, NOTICE_SENT, NOTICE_RECEIVED, MOVE_OUT, PAYMENT, LAW_PROMULGATED, LAW_EFFECTIVE, UNKNOWN`. '통지'는 발송/도달을 구별한다.

**Step A3. 제안 타입**  
```python
class TemporalEvent(BaseModel):
    event_id: str
    date_iso: date | None
    event_type: Literal["CONTRACT_SIGNED","CONTRACT_START","CONTRACT_END",
                        "RENEWED","CONTRACT_CHANGED","NOTICE_SENT",
                        "NOTICE_RECEIVED","MOVE_OUT","PAYMENT",
                        "LAW_PROMULGATED","LAW_EFFECTIVE","UNKNOWN"]
    actor: str | None = None
    source_id: str
    evidence_span_id: str | None = None
    approval_status: str
    confidence: float
    unresolved_reason: str | None = None
```
**호환성:** 새 모델 강제 DB migration보다 기존 fact/event DTO에 선택 필드 추가 우선. `UNKNOWN`은 임의 계약일로 대체하지 않는다.

**Step A4. 법령 적용 (기존 LLM verification에 통합)**  
공식 API에서 `law_id, article, promulgation_date, effective_date, version_id, full_article, supplementary_provisions, source_url` 확보. **사건의 어떤 날짜가 법령의 적용 기준인지** 부칙을 읽고 LLM이 구조화 판단한다. 제안 출력:
```json
{
  "statute_id": "...",
  "article": "...",
  "version_id": "...",
  "trigger_event_type": "CONTRACT_SIGNED",
  "trigger_event_ids": ["..."],
  "transitional_rule": "시행 후 체결/갱신/변경 계약부터 적용",
  "applicable": false,
  "reasoning_summary": "사건 계약일이 시행일 이전이며 부칙의 적용 범위 밖",
  "supporting_source_ids": ["..."],
  "missing_conditions": []
}
```
**법적 의미 해석은 LLM**, 정해진 trigger event와 effective date의 날짜 비교는 **Python**. 부칙의 예외·소급/경과조치가 복잡하면 단순 `date >= effective_date`로 결론 내리지 않고 LLM이 공식 원문으로 재검증. `applicable=false`도 원문 출처와 이유를 저장. 공식 조문/부칙 부족 시 `UNCONFIRMED`로 표기하고 공식 검색 재시도/보류.

**Step A5. 실제 회귀**  
2026-10-27 개정, 2027-04-28 시행 민간임대주택 시행령 제36조: 2026-11-01 체결 계약 비적용, 시행 후 체결 계약 적용 여부, 시행 후 갱신/변경 계약, 2026년 통지와 2027년 갱신이 함께 있는 질문, '개정' 단어 없는 과거 계약. **정확한 조문과 부칙 원문을 테스트 fixture로 보존**하고 실제 API 결과와 버전 비교. 허위 regex 거절 0.

### B. 법령 버전·중복 제거

- `StatuteSourceKey = (official_law_id, article_no, version_id/effective_date, supplement_section, content_hash)`. 조문별 동일 내용 chunk는 중복 압축하되 **서로 다른 시행본/부칙은 독립**.
- `SOURCE_VERSION_ID_UNCONFIRMED`이면 공식 API 메타데이터 재조회. 그래도 불명확하면 `UNVERIFIED_VERSION` 상태로 답변 검증에 전달; 최신본이라고 단정 금지.
- `DIGEST_TRUNCATED`이면 `dropped_source_ids`, `dropped_chars`, `has_supplement`, `has_counterevidence`를 manifest로 기록. 부칙·결정적 반증 잘림이면 해당 부분만 다시 조회/첨부.
- 기존 8개 계승 법령은 `law_id+version+event_date+snapshot` 검증 후 재사용. 과거 답변에 인용되었다는 이유만으로 신뢰하지 않는다.

## 7.5 카드 03 — EvidenceSpan·승인·반대 증거: DB 트랜잭션 설계

**Step 1 (추출):** LLM은 문서에서 `claim_text, normalized_fact, evidence_quote, page/paragraph_hint, amount_role, event_role` 후보를 생성. 이때 **LLM의 quote/offset은 검증 전 후보**. Python이 정규화 원문에서 quote를 정확히 찾아 `start_offset/end_offset/content_hash`를 산출. 중복 매치/원문 부재 시 `SPAN_UNRESOLVED`을 기록하고 **가짜 span 저장 금지**.

**Step 2 (승인):** 사용자의 일괄 승인 요청에서 **각 claim_id별 상태 변경**을 수행하고, EvidenceSpan의 `document_id/version_hash/claim_id` 연결 및 DB FK/commit 확인. 일부 실패 시 전부 롤백할지 부분 성공할지 **기존 API 계약을 먼저 확인**하고 명시적인 결과 목록 반환. 승인하지 않은 claim을 `APPROVED`로 추정하지 않는다.

**Step 3 (상담 입력):** `EvidenceRecord`를 `source_file_name, document_hash, claim_id, claim_approval_status, span_id, span_text, source_kind, temporal_scope`로 직렬화. 원본 문서 존재와 사실 승인 상태를 별개로 표시. 승인 사실은 확정 근거 후보, 미승인 사실은 사용자 주장/확인 필요로 분리; 기존 제품의 원문 사용 정책을 임의 변경하지 않는다.

**Step 4 (반대 증거):** 검증 근거 선택은 draft의 인용 목록만 따르지 말고 `issue_id`별 관련 승인 사실·불일치 후보·반대 근거를 함께 선택. 전체 원문 무제한 전송 대신 결정적 span 및 원문 reference를 유지. 실제 상충 판정은 주체·시간·금액 역할·모달리티·범위를 고려하는 기존 의미 판단에 포함. '분할 반환 제안'과 '전액 즉시 반환 곤란'은 자동 모순 판정 금지.

**테스트:** 다중 문서 같은 문구, OCR/공백 차이, claim 10건 일괄 승인 중 1건 실패, 승인 후 파일 수정, span이 없는 기존 데이터, 반려 claim만 있는 사건, 인용되지 않은 결정적 반증. 모든 답변 인용은 `source_file_name+span_id 또는 문서 원문 ref`로 역추적 가능해야 한다.

## 7.6 카드 04 — 금액·검증·Repair: 호출 정책

**금액 추출:** `1억 7천만 원`, `170,000,000원` 등을 Python `Decimal` 원화 정수로 정규화(LLM 0회). **역할 부여**는 기존 문서 사실 추출 LLM의 구조화 필드 또는 승인 사실을 우선. 제안 `MonetaryFact(amount_krw, role, party, event_date, source_id, approval_status)`; role = `TOTAL_DEPOSIT/EARNEST/BALANCE_DUE/REFUNDED/OUTSTANDING/PROMISED/ATTACHMENT_CLAIM/UNKNOWN`. `UNKNOWN`을 `TOTAL_DEPOSIT`으로 강제하지 않는다.

**금액 검증:** 동일 role+시점+사건 scope 내에서만 비교. `OUTSTANDING = TOTAL_DEPOSIT - SUM(실제 지급 확인된 REFUNDED)`를 **근거가 충분할 때만** Python으로 계산. 분할 반환 **제안**은 실제 반환액에 더하지 않는다. `deposit_matches[0]` 기반 자동 REPAIR 제거. 정확한 잔액을 계약 총액과 다르다는 이유로 수정하지 않음.

**Verification:** 기존 LLM이 `GROUNDING, STATUTE_ACCURACY, TEMPORAL_APPLICABILITY, QUESTION_COVERAGE`를 판정하고 `claim_id/source_ids/contradiction_ids`를 구조화 출력. Python은 **스키마·원문 존재·인용 해시·금액 산술**만 결정적으로 확인; 법률 의미의 PASS/FAIL을 regex로 덮어쓰지 않는다. 실제 source conflict가 확인되면 PASS도 차단 가능하되 이유/근거 기록.

**Repair state machine:** `DRAFT → VERIFY → (PASS → FINAL | FAIL → PATCH)`. `PATCH`는 `old_text` 유일 매치·근거 출처 유효·변경 hash 확인 후 적용. `patch_applied=false`면 동일 hash로 재검증하지 않는다. 1회 안전한 재생성 또는 `WITHHELD/NEEDS_REVIEW`로 종료. 반복 횟수는 품질과 trace 기준으로 정하며 무조건 1회로 고정 금지. 전체 재생성 시 원래 검증된 사실·법령 출처와 diff를 검사한다.

**테스트:** 3억 보증금/계약금/일부 반환/잔액/가압류액 혼재, patch target 중복/공백 변경, 유효한 LLM PASS가 부칙 regex로 거절되는 경우, 검증 JSON 파싱 실패. 파싱 실패는 PASS가 아니다.

## 7.7 카드 05 — 답변 데이터 계약과 UI 표시

- 기존 최종 답변을 **한 번만** 구조화해 `FinalAnswerPresentation{lead, actions[], analysis_sections[], evidence_citations[], statute_citations[], open_questions[], raw_verified_answer, verification_status}`로 전달. 이 작업은 **결정적 parser**로 수행하고 별도 LLM 호출하지 않는다. 파싱 불확실하면 검증된 원문을 **한 번만** 렌더.
- `synthesizer/document_consultation/final_disposition`의 모든 분기에서 `raw_verified_answer` 원본 hash와 source IDs 보존. Markdown의 강조를 UI에서 지원하되 일반 번호 목록을 제목으로 오인하지 않도록 **알려진 섹션명+헤딩 구조**만 분리.
- `lead`만 추출되고 상세가 비어 있으면 `raw_verified_answer`를 중복으로 붙이지 말고 **하나의 원문 모드**로 표시. 출처는 E01 같은 내부 별칭만 보여주지 말고 전체 파일명.
- **테스트:** `# 핵심 결론`, `1. 핵심 결론`, 일반 `1. 계약금을 지급했다`, 긴 인용/테이블, 결론 없는 답변, `WITHHELD` 상태, Markdown 볼드.

## 7.8 카드 06 — 검색·LLM 호출 최적화: 실제 의사결정

- 검색 이전 `SourceCoverage` 계산: `required_issues, required_law_ids, articles, event_date, version_verified, supplement_present, contradictions_checked, missing_items`.
- `missing_items=[]`이며 버전·부칙 검증 완료일 때만 동일 법령 재검색 생략(**Python 결정적 검사**). 충분성 자체가 의미 판단을 요구하면 **기존 planner/verification LLM의 구조화 결과** 사용; 새 LLM 호출은 원칙적으로 추가하지 않음.
- `NEED_MORE_LAW` 루프 진입 시 `why_missing`과 새로 요청할 조문·시행본만 전달. 이전과 동일 `source_hash+question_issue+version`이면 재검색 대신 검증 결과를 재사용하거나 근거 부족을 명시. 단, 기존 검색이 실패/잘림/버전 미확인인 경우에는 동일 해시만 보고 중단하지 않는다.
- cache key: `law_id/article/version/effective_date/supplement_hash`; API 오류 fallback 시 `source_origin=VECTOR_FALLBACK`, `official_verified=false` 유지. 임의로 official PASS로 승격 금지.
- 먼저 trace에서 **비용 상위 2개 generation**을 선정하여 입력 payload 중복만 제거. 검색 노드의 1초 수준 지연보다 수십 초 LLM generation이 병목이라면 후자를 우선. 재검증 생략은 법률 Gold 유지 증명 후 적용.
- **성능 결과:** 각 PR별 `before/after node latency, total active latency, LLM calls, input/output tokens, USD cost, answer_quality_delta`; 같은 시나리오·동일 법령/증거 snapshot이 아니면 개선율 계산 금지.

## 7.9 카드 07 — 대화 컨텍스트: 세부 선택 규칙

- 기존 `format_context_for_prompt(max_turns=2)`, `to_chat_history_messages(max_turns=3)`, `document_consultation.user_history`에서 **실제로 어떤 노드에 동일 내용이 두 번 들어가는지** trace payload hash로 측정.
- **일반 새 질문:** 사건 승인 사실·현재 질문·필수 쟁점/법령만 포함; 이전 AI 답변 전문 제외. **후속 지시어 질문:** 최근 사용자 발언 중 지시 대상과 필요한 이전 상담 결론의 **식별자/요약**만 추가; 이전 AI 출력 전체를 무조건 3턴 첨부하지 않는다.
- **새 증거 등록:** evidence snapshot fingerprint 변경 시 이전 법률 결론을 캐시 답변으로 재사용 금지. 이전 턴의 법령도 시행본·사건일이 맞는지 재확인.
- `ContextBudget`에 `question_tokens, case_fact_tokens, evidence_tokens, statute_tokens, prior_turn_tokens, verification_tokens`를 기록. 한도가 초과하면 **과거 답변 서술·중복 메타데이터부터** 줄이고, 승인된 핵심 사실·반대 증거·부칙을 먼저 자르지 않는다.
- **테스트:** '그럼 이사해도 되나요?' 같은 후속 질문, 증거 변경 후 동일 질문, 과거 법령의 다른 시행본, 사건 A/B 분리, 원문 18건 이상.

## 7.10 카드 08 — 진행 상태 및 HITL 이벤트 계약

- 제안 서버 이벤트 `{consultation_id, phase, node, state, step_index, message, requires_approval, approval_request_id, timestamp}`; `state=QUEUED|RUNNING|WAITING_APPROVAL|RESUMED|COMPLETED|FAILED`.
- `phase`는 `CASE_CONTEXT, ISSUE_ANALYSIS, LAW_SEARCH, EVIDENCE_REVIEW, ANSWER_DRAFT, VERIFICATION, FINALIZATION`처럼 **사용자 이해 중심**. 내부 노드명은 UI 계약으로 직접 노출하지 않는다.
- 프론트의 `DEFAULT_STEPS`·`STATUTE_APPROVAL` 비교와 서버 `step_1..step_6` 불일치는 단일 mapping 함수에서 해결. approval 여부는 `requires_approval` 필드로 판단하며 특정 `step_3`에 묶지 않는다.
- 진행률 숫자는 실제 완료된 phase가 있을 때만 증가. HITL 승인 대기는 멈춤/사용자 조치로 표시하고, resume 후 동일 consultation_id 유지.
- **테스트:** 정상/실패/승인 대기/거절/재시작, 중복 이벤트, SSE 재연결, 완료 후 답변 렌더.

## 7.11 카드 09~10 — 자동화 회귀·출시 차단

- 테스트 피라미드: **unit**(날짜 파서·금액 정규화·span offset·cache key·section parser), **integration**(Postgres 승인 트랜잭션·공식 API 응답 fixture·checkpoint resume·Langfuse span), **E2E**(SC001/002/003 + 반증/HITL/UI).
- 법률 Gold는 `scenario_id, fact_snapshot, applicable_law_version, correct_legal_conclusion, required_citations, forbidden_claims, uncertainty_requirements` 구조로 고정. **특정 시나리오 문구에 맞춘 분기 구현 금지**.
- 테스트 실행 시 모든 사례에 `code SHA, trace ID, question, evidence hash, statute version, pass/fail, human reviewer, reason` 기록. 실패한 법률 결론을 단순 프롬프트 표현 점수로 덮지 않는다.
- **Go 조건:** 차단급 법률 오류 0, 승인/원문 무결성 0건 위반, HITL resume PASS, UI 답변 중복 0, 재현 가능한 trace/KPI. 목표 60초·30% 절감은 **품질이 유지될 때만** 성능 목표로 평가.
- **No-Go:** 시행일·부칙 적용 오판, 결정적 반증 소실, 미승인 사실 확정, 금액 role 오판에 의한 자동 수정, 핵심 인용 누락, 사건 간 데이터 누출, checkpoint 소실.

## 7.12 구현 PR 순서와 작업자별 완료 조건

| PR | 변경 단위 | 구현/테스트 완료 조건 |
|---|---|---|
| PR-00 | baseline manifest/측정 스크립트 | 동일 실행 추적 가능, 원본 보존 |
| PR-01 | observability/HITL (잔존 결함만) | 최신 로그로 재현, 재시작 resume PASS |
| PR-02A | 날짜 후보 파서+event role DTO | Python 단위 테스트, 모호한 날짜 UNKNOWN |
| PR-02B | 법령 version/supplement source manifest | 다른 시행본 dedup 금지, 공식 API fixture PASS |
| PR-02C | temporal applicability LLM schema + 검증 | 실제 부칙·경과조치 Gold PASS |
| PR-03A | EvidenceSpan·일괄 승인 | DB FK/offset/transaction PASS |
| PR-03B | 검증용 반대 증거 source selection | 미인용 반증도 검증기에서 확인 |
| PR-04A | monetary role QA | 원금/반환/잔액/가압류액 혼동 0 |
| PR-04B | repair no-op 방지 | 동일 draft hash 무의미 재검증 0 |
| PR-05 | final answer presentation contract | 의미/출처/Markdown 보존, 중복 0 |
| PR-06 | trace 기반 검색/검증 중복 제거 | 법률 Gold 동등, 실측 성능 개선 |
| PR-07 | history/context budget | 후속 질문 PASS, 토큰 감소 |
| PR-08 | progress/HITL frontend contract | 대기/재개/완료 표시 PASS |
| PR-09 | SC 통합 회귀·KPI·릴리스 게이트 | 차단 오류 0, 사용자 Go 승인 |

**작업 통제:** 각 PR마다 최신 main에서 재확인 → 원인/로그/기존 동작 확인 → 최소 구현 → 단위/통합 테스트 → 동일 Gold 회귀 → trace 비용 비교 → PR/커밋 → 사용자 검토. 출시 전 시간이 부족하면 **정확도 PR을 우선**하고 PR-06/07은 미완료 상태로 남겨도 된다. 변경 코드가 검증되지 않았다면 **속도 개선보다 이전의 검증된 동작 유지**가 우선이다.

---

# 8. 최종 소스코드 우선 재검토 및 기존 판단 정정 (2026-11-12)

> **이 장은 2·3·4·7장의 로그 기반 판단과 충돌하는 경우 우선 적용한다.** 최종 판정 기준은 **최신 main 소스 + 호출 경로 + 테스트**이다. 로그는 그 버전의 실행 사례와 병목 크기를 설명하는 **보조 근거**일 뿐이며, 로그에 오류가 없다는 이유로 코드 결함을 부정하거나 오래된 로그의 오류가 현재도 남아 있다고 단정하지 않는다. 본 장의 확인은 GitHub main의 아래 파일들을 직접 읽어 수행했으며, **런타임 E2E 재실행은 하지 않았다**.

## 8.1 근거 등급과 의사결정 절차 변경

- **S1 소스 확정:** 최신 함수/분기/조건에서 위험한 로직이 직접 확인됨. **그 분기가 존재함은 확정**, 실제 오답 발생 여부는 테스트로 별도 확인.
- **S2 호출 경로 확인 필요:** 소스에 로직이 있으나 활성 모드·상태·호출 경로에 따라 영향이 달라짐. 먼저 실제 경로 확인.
- **S3 로그/Trace 관측:** 특정 과거 실행에서 나타난 상태·지연·경고. 최신 코드의 현재 결함으로 승격 금지.
- **S4 수정 효과 예측:** 개선 후 속도·정확도 예상. 동일 소스/Gold E2E로 검증 전까지 실측치 아님.

**작업 절차:** 최신 main SHA 확인 → 해당 소스의 입력·상태·분기·호출자·하위 호출 확인 → 최소 재현 단위 테스트 → 영향 범위 확정 → 수정 설계/적용 → 회귀 테스트 → Langfuse 비교. 소스와 로그가 불일치하면 **소스를 기준으로 현재 로직을 설명**하고 로그는 실행 버전이 일치하는지 별도 검증.

## 8.2 최신 소스에서 직접 확인한 수정 대상

| 우선순위 | 실제 소스와 코드 위치 | 소스에서 확인된 현재 동작 | 수정 설계 및 테스트 |
|---|---|---|---|
| **P0-A** | `workflows/legal_workflow.py:337-344, 473-474, 968-972` | 질문의 첫 날짜를 regex로 추출하고 `event_type='CONTRACT_SIGNED' if extracted_date else None` 설정. 이후 날짜만 있고 역할이 없으면 `CONTRACT_SIGNED` 기본값 | **날짜 파싱은 Python**, 날짜 의미는 승인 이벤트/문서 필드/기존 LLM 구조화 출력으로 확정. 기본 CONTRACT_SIGNED 강제 제거. 다중 날짜·통지일·퇴거일·갱신일 단위 테스트 |
| **P0-B** | `rag/grounding_context.py:112-153, 156-211` | 법령 중복키가 법령명+조문 중심; 공식 검색 출처를 우선하여 나머지를 생략 | 법령 ID+조문+시행본+부칙/본문 hash 구분. **버전이 불명확하면 서로 다른 내용을 무조건 병합하지 않음**. 시행 전후 2개 버전·부칙 테스트 |
| **P0-C** | `agents/document_answer.py:55-56` | 사건 이후 시행된 법령을 시행일만으로 거부하지 말라는 프롬프트 문구가 있음 | 일반적 적용 추정 대신 **법령 본문·부칙·사건일을 검증하여 적용 여부 결정**하도록 프롬프트 수정. 올바른 과거 계약 비적용 테스트 |
| **P0-D** | `agents/qa_checker.py:223-244` | `deposit_matches[0]`을 사건 실제 보증금으로 삼아 다른 답변 금액에 REPAIR 제안 | 첫 금액 기준 비교 제거. 승인된 `MonetaryFact(role,date,source)`로 총액/계약금/반환액/잔액 분리. 계산만 Python. 정확한 미반환 잔액을 오수정하지 않는 테스트 |
| **P0-E** | `case_intelligence/case_briefing.py:382-411` | EvidenceSpan이 비면 승인 claim, 없으면 **전체 doc_claims**, 이후 원본 파일 순서로 본문 대체 | 전체 claim 사용 시 **미승인/반려 포함 가능성**을 표시하는 provenance 타입 필수. 원본 문서와 승인된 사실 구분. 상담에 확정 사실로 들어가는지 호출 경로 테스트 |
| **P0-F** | `workflows/document_consultation.py:189-200`, `workflows/legal_workflow.py:1363-1385` | 공식 검색 수행 여부/`hitl_executed`를 근거로 `NEED_MORE_LAW` 요청을 차단하거나 `allow_need_more_law=False`로 재생성 | **검색 실행 여부 != 법령 충분성**. 필수 쟁점·조문·시행본·부칙·적용시점 coverage가 충분할 때만 재검색 생략. 부족하면 targeted search 또는 근거 부족 명시; 무조건 강제 초안 금지 |
| **P1-A** | `workflows/legal_workflow.py:362,5034,5402`; `agents/document_answer.py:247` | 이전 대화 맥락을 서로 다른 max_turns로 포맷하고, document_answer에서 history 중복 문자열을 제거 | 실제 **같은 LLM 호출에 중복 전달되는지** 함수 인자·프롬프트 조립을 추적. 중복 시에만 삭제. 후속 질문 맥락 회귀 |
| **P1-B** | `rag/grounding_context.py:156+` | 초안 비인용 증거는 150자 스니펫 중심으로 축약하는 함수 존재 | **실제 verifier 호출 시 사용되는지 확인**. 반대 증거가 인용되지 않았다는 이유로 검증에서 빠지지 않도록 relevant/counter-evidence 선택 |

**특히 주의:** P0-F는 이전 보고서에서 주로 'Gemini가 로그로 발견한 중복 NEED_MORE_LAW 성능 병목'으로 서술했지만, **최신 소스에서 더 본질적인 안전성 문제(검색 완료 플래그만으로 법령 충분성을 대체하는 강제 초안 분기)**가 확인되었다. 따라서 작업 순서를 **성능 최적화 06보다 앞선 법률 정확도 02로 이동**한다. 성능 개선은 안전한 충분성 검사 후 부산물로 측정한다.

## 8.3 기존 로그 기반 권고의 재분류

| 기존 문구/판단 | 최종 정정 |
|---|---|
| '11/10 로그의 `OFFICIAL_LAW_ID_UNCONFIRMED`를 최우선 원인으로 수정' | **S3 관측 신호**다. 현재 소스에서 law ID를 누가/어떻게 만들고 실패 시 무엇을 하는지 확인 후 수정. 로그 문구만 보고 새 LLM 호출 추가 금지 |
| '11/10 `DIGEST_TRUNCATED`가 실제 정확도 오류를 증명' | 경고 자체는 관측. **누락된 원문이 실제 verification 입력에서 배제되는지** 최신 source builder/formatter를 확인하고 재현해야 결함 확정 |
| '11/10 evidence bundle 11.8ms이므로 인라인화 불필요' | 그 **한 실행의 시간**일 뿐. 노드 인라인화는 현재 우선순위 낮지만, 그 근거는 **품질/체크포인트/변경 위험 대비 명확한 구조적 이득 부족**이며 로그 시간 하나로 영구 배제하지 않음 |
| '11/10 최근 3턴 로드이므로 3턴 삭제' | 실제 소스에 `max_turns=2/3`, `history[-4:]` 등이 **서로 다른 경로**로 존재. 어느 모델 호출에 어떤 중복이 들어가는지 확인한 후 최소화. 연속 상담 기능 삭제 금지 |
| '11/10 8개 법령 계승은 최적화 대상' | 계승 여부보다 **현재 소스에서 버전·사건일·증거 변경에 따라 재검증하는지**가 우선. 캐시 제거/유지 결정은 소스 호출 경로+테스트로 판단 |
| '10/27 PostgreSQL 초기화 성공이므로 체크포인터 문제 해결' | 초기화 성공은 **실제 graph compile에 PostgreSQL saver가 연결되고 재시작 resume되는지**를 증명하지 않음. 현재 소스 호출 경로 + 재시작 테스트로만 PASS |
| '과거 로그의 OTel/GraphInterrupt 오류는 현재도 반드시 수정' | 과거 오류 수치는 **현재 미확정**. 최신 decorators/observability 경로와 현재 재현 여부 확인; 이미 고쳐진 로직 재수정 금지 |
| '기존 Trace 141.3→220.2초를 최신 개선안 KPI로 사용' | 다른 버전·다른 검색 조건의 **역사적 비교 사례**. 최신 main의 개선 전후 목표치·성능 보장으로 사용 금지 |
| 'KPI XLSX의 실측이 최신 main을 대표' | 엑셀 생성 시점 SHA·환경·trace가 현재 main과 일치할 때만 **현행 baseline**. 아니면 과거 baseline으로 라벨 |

## 8.4 수정된 개발 우선순위: 소스 확정 위험 먼저

**0. 버전 고정:** 최신 main SHA, 소스 함수/분기 지도, 평가 입력·Trace 연결. 로그는 이 단계에서 해당 SHA에 매핑.

**1. 코드 확정 정확도 문제 우선 처리:**
- **PR-02A:** `CONTRACT_SIGNED` 자동 기본값 제거, 후보 날짜 파싱/역할 구분.
- **PR-02B:** 법령 중복키에 시행본·부칙 식별 포함.
- **PR-02C:** 최근 시행본을 과거 계약에 일반 적용할 수 있다는 프롬프트 오해 제거.
- **PR-02D (신설):** `NEED_MORE_LAW`의 **검색 완료 기반 강제 초안**을 coverage 기반 안전한 재검색/보류로 수정.
- **PR-03:** EvidenceSpan 공란 및 미승인 claim fallback provenance 수정.
- **PR-04:** `deposit_matches[0]` QA 오판 및 patch no-op 루프 재현/수정.

**2. 코드 호출 경로 확인 후 처리:** 검증기 반대 증거 축약, 대화 이력 중복, verification·presentation 분기, GraphInterrupt/체크포인터, UI 이벤트 계약. **위험 코드의 존재와 실제 활성 경로는 별개**이므로 테스트로 활성 여부 확인.

**3. 품질 회귀 후 성능 최적화:** 동일 Gold에서 `NEED_MORE_LAW` 호출·재검색·컨텍스트 중복을 최적화. 정확도 우선; 로그 지연 순위는 **해당 소스 버전과 동일한 최신 trace**에서 재측정.

**4. 최종 SC001/002/003 E2E, UI/HITL, KPI, Go/No-Go:** 출처·법령 시점·금액·승인·후속 질문·재시작을 포함.

## 8.5 구현 세부 조정: LLM 호출을 늘리기 전에 코드 수정

- **날짜:** `re.search` 첫 매치 대신 `finditer`로 날짜 후보 모두 추출하고 `datetime.date`로 유효성 검증(**LLM 0회**). `event_type`은 승인된 사건 DB 이벤트 또는 기존 `intent_analyzer`/fact extractor가 반환한 구조화 값 우선. 기존 LLM 호출이 없다면 날짜 의미가 핵심인데 모호할 때만 LLM 1회, 그 외 `UNKNOWN`. `event_type='CONTRACT_SIGNED'`의 암묵 기본값 금지.
- **법령:** 버전/부칙 키 생성·source dedup은 Python(**LLM 0회**). 공식 API ID·시행일·본문/부칙 metadata가 불충분하면 공식 출처 재조회; 법적 적용의 의미 해석만 기존 verification LLM에 통합.
- **법령 충분성:** `statute_search_count>0`만으로 강제 초안 금지. Python은 필수 source manifest의 **존재/버전/부칙/해시**를 검증, LLM은 법률 쟁점에 대한 **실질적 커버리지**를 기존 planner/verification 호출에서 판단. 부족하면 **구체적으로 누락된 조문만** 검색; 일정 한도 이후에도 부족하면 불확실성을 표시하고 보류. '이미 검색했다'는 사실로 READY 강제 금지.
- **증거:** 승인 상태·span offset·원문 hash·DB commit은 Python/SQL(**LLM 0회**). 사실 후보와 의미 역할만 기존 추출 LLM 활용. `doc_claims`는 원문이 아니며 승인되지 않은 Claim은 확정 사실로 취급하지 않음.
- **금액:** regex는 금액 후보 수집, Python Decimal은 산술, 역할은 승인된 사실 또는 기존 추출 LLM. `deposit_matches[0]`에 따른 REPAIR는 제거. 역할 불확실하면 수정 강제 대신 확인 필요로 남김.
- **검증:** 출처·해시·상태·중복 실행 차단은 Python; 법령 적용·부칙·증거 충돌의 **의미 판단은 LLM**. regex 기반 법률 정오 판정 재도입 금지.

## 8.6 다음 작업자에게 주는 수정 지시

1. **본 문서 8장부터 읽고** 과거 로그만으로 확정된 표현은 모두 '과거 관측'으로 취급한다.
2. 최신 main의 소스 함수·분기·호출자와 테스트를 확인하고, 위 **S1 위험 6개**를 우선 최소 재현한다.
3. 정확도 개선은 **PR-02A → 02B → 02C → 02D → 03 → 04** 순서로, 각 PR의 법률 Gold PASS 후 다음으로 넘어간다.
4. Langfuse/로그는 **동일 SHA에서 발생한 실제 영향·빈도·지연**을 확인할 때만 사용한다. 과거 오류 수치를 현재 오류 수치로 재인용하지 않는다.
5. 수정하지 않은 항목은 '보류/확인 필요', 소스에서 분기만 발견된 항목은 '위험 코드 확인', 재현한 항목만 '실제 결함 재현'으로 표기한다.

---

# 9. 항목별 변경 영향도 및 안전한 적용 순서

> **영향도는 최신 소스의 확인된 분기와 연결 관계를 바탕으로 한 정성 평가**다. 모든 호출자/테스트를 실행해 검증한 확정 영향 범위는 아니다. **정확도 영향**은 해당 기능이 잘못 동작할 때의 결과, **수정 위험**은 코드를 바꿀 때 다른 기능을 깨뜨릴 가능성이다. 과거 로그의 횟수/지연은 이 평가의 근거로 사용하지 않았다.

| 항목 | 정확도 영향 | 성능 영향 | 수정 위험 | 주요 코드 및 영향 범위 | 권장 수정 방식 |
|---|---|---|---|---|---|
| 1 날짜·event_type | **매우 높음** | 낮음~중간 | **높음** | `legal_workflow.py` 질문→state→`temporal_search_plan.py`→법령 검색/적용 | 날짜 후보 추출과 역할 지정 분리, fallback UNKNOWN |
| 2 법령 시행본·부칙 | **매우 높음** | 중간 | **높음** | `grounding_context.py` 법령 dedup→verification; 법령 검색 metadata | version-aware key, 원문·부칙 보존 |
| 3 법령 검색 충분성 | **매우 높음** | **높음** | **매우 높음** | `document_consultation.py`, `legal_workflow.py`, `document_answer.py`의 NEED_MORE_LAW gate | 충분성 확인과 검색 횟수 분리; 최대 재검색/보류 |
| 4 EvidenceSpan·승인 | **높음** | 낮음~중간 | **높음** | 사실추출→claim/span DB→일괄승인→`case_briefing.py`→상담 입력 | 기존 승인 모델 유지, provenance 추가, 데이터 migration 신중 |
| 5 금액 QA·Verification | **매우 높음** | 중간 | **높음** | `qa_checker.py` repair targets→검증→최종 답변 | 위험한 자동 수정 차단부터, role 기반 QA |
| 6 이전 상담·중복 입력 | 중간~높음 | **매우 높음** | 중간~높음 | `legal_workflow.py`의 2/3턴 history + `document_consultation.py` history[-4:] + 프롬프트 | 입력 중복 측정→특정 호출부터 축소 |
| 7 최종 답변·UI | 중간 | 낮음~중간 | 중간 | `document_consultation.py`→final disposition→API→React | 검증된 답변 불변, 표시 adapter만 우선 |
| 8 E2E·측정 | 정확도 보증 | 성능 실측 | 낮음 | 테스트/Gold/Langfuse/KPI | 매 PR 필수 회귀, 동일 SHA 비교 |

## 9.1 날짜 변경의 전파 영향

- **변경 위치:** `legal_workflow.py`의 첫 날짜 regex, `event_date/event_type` 상태 생성, `temporal_search_plan.py` 입력.
- **영향:** 날짜를 `CONTRACT_SIGNED`로 가정하던 기존 경로가 `UNKNOWN`을 받을 수 있다. 이 경우 공식 법령 검색 계획이 SKIP되거나 LLM 보완 경로로 이동할 수 있으므로 **검색 계획 출력도 반드시 회귀**.
- **수정 경계:** state 키를 한 번에 삭제하거나 그래프 노드를 제거하지 않는다. 기존 필드는 유지하고 `event_type`이 근거 없는 경우에만 `None/UNKNOWN`으로 처리. 파서의 유효성 검증은 `datetime.date` 사용.
- **테스트:** 계약일만/퇴거일만/통지일만/다중 날짜/연도 미상/잘못된 날짜/후속 질문; 기존 검색 계획 생성과 정답 법령 비교.
- **롤백:** 기존 state 스키마 유지, 기능 플래그로 새 role resolver만 되돌릴 수 있게 분리. 단, 알려진 잘못된 계약일 강제 동작을 영구 복원하는 롤백은 허용하지 않음.

## 9.2 법령 버전·부칙 변경의 전파 영향

- **변경 위치:** `grounding_context.py:normalize_statute_key`와 `prune_sources_for_verification`, 법령 검색 결과 metadata.
- **영향:** 같은 조문의 시행본이 두 개면 둘 다 검증 입력에 남아 **토큰이 증가**할 수 있다. 반대로 버전 정보가 비어 있으면 중복 제거 효과가 줄어든다. 기존 citation/source_id의 형식이 바뀌면 답변 출처 표시에도 영향.
- **수정 경계:** 원래 `source_id`는 유지하고 **별도 내부 dedup_key**를 생성. 부칙과 조문은 별도 유형으로 관리. 버전 미상인 두 출처를 법령명만으로 합치지 않는다.
- **테스트:** 같은 버전 동일 내용 중복/다른 버전 동일 조문/부칙 단독/공식+벡터 결과/출처 ID 보존/verification 토큰 크기.
- **롤백:** dedup 최적화만 원복 가능; 버전이 다른 원문을 소실시키는 병합은 허용하지 않음.

## 9.3 NEED_MORE_LAW 변경의 전파 영향 — 최고 위험

- **변경 위치:** `document_consultation.py:189+` 및 `legal_workflow.py:1363+`, 검색 계획·재진입 라우팅.
- **영향:** 지금까지 검색 1회 후 답변을 생성하던 질문이 추가 검색/승인/보류로 갈 수 있어 **응답시간·비용·HITL 횟수·UI 진행 상태**가 변한다. 잘못 구현하면 무한 검색 루프나 답변 누락 발생.
- **수정 경계:** `search_count`는 루프 방지용 상한으로만 사용하고, **충분성 판정은 source coverage와 분리**. 필수 법령이 없으면 특정 조문만 추가 검색; 재검색 상한 이후에는 근거 부족을 명시하고 종료. 충분성 LLM 호출을 새로 추가하기보다 기존 planner/verification 출력 활용.
- **테스트:** 검색 성공/부분 성공/실패, 같은 요청 반복, 부칙만 누락, 공식 API 실패, HITL 승인 대기, 비용 상한, 정상 상담의 기존 답변 생성 유지.
- **롤백:** 새 재검색 정책만 기능 플래그로 원복할 수 있으나, 근거 부족 상태를 법령 충족으로 위장하는 강제 PASS는 허용하지 않음.

## 9.4 EvidenceSpan·승인 변경의 전파 영향

- **변경 위치:** 원문 추출 저장/일괄 승인/claim 연결과 `case_briefing.py` fallback.
- **영향:** 기존 EvidenceSpan 없는 사건 데이터가 상담에서 갑자기 누락될 수 있음. 문서 원문이 존재해도 승인 Claim이 없을 수 있으므로 **증거 검색과 승인 사실의 범위를 혼동하면 회귀**. DB schema·일괄 승인 UX·그래프/타임라인에도 파급 가능.
- **수정 경계:** 기존 데이터 삭제/전면 재추출 금지. `APPROVED/UNAPPROVED/REJECTED/UNKNOWN`을 유지하고, 과거 span 없는 데이터는 `source_missing_span`으로 표시한 뒤 복구. 문서 원문은 원문으로, 미승인 claim은 미확인 주장으로만 전달.
- **테스트:** 신규/기존 문서, span 0건, 일괄 승인 부분 실패, 문서 삭제·수정, 승인/반려 혼재, 원문/claim 인용 구분, case isolation.
- **롤백:** DB migration은 확장형(선택 필드 추가)으로 만들고 구 스키마와 호환. 승인 이력 손실 방지.

## 9.5 금액 QA·Verification 변경의 전파 영향

- **변경 위치:** `qa_checker.py:223+` 금액 정규식과 `RepairTarget` 생성; verification/repair 호출자.
- **영향:** 오수정은 줄지만, 기존 regex가 잡던 **실제 잘못된 금액**을 놓칠 수 있음. 역할 판정이 없는 문서에서는 QA 경고가 줄어들 수 있다.
- **수정 경계:** 첫 금액 자동 정정 **즉시 비활성화**하되 단순 금액 후보 수집/표시는 유지. 승인된 role이 확인된 경우에만 동일 역할 금액 비교. 불확실하면 `NEEDS_REVIEW` 경고만 표시.
- **테스트:** 보증금/계약금/잔액/반환액/가압류액 혼재, 잘못된 전체 보증금, 실제 잔액, 문서 간 금액 상충, patch 적용 성공/실패.
- **롤백:** QA 경고 기능은 복원 가능하되 역할 없는 자동 금액 치환은 재활성화 금지.

## 9.6 상담 이력·중복 입력 변경의 전파 영향

- **변경 위치:** `legal_workflow.py` history 생성과 `document_consultation.py` 전달, 프롬프트.
- **영향:** 입력 토큰 절감 가능성이 크지만 '그럼?', '그 사람', '그때' 같은 지시어 복원이 실패할 수 있고 과거 상담 결론을 참조하는 질문 품질이 저하될 수 있음.
- **수정 경계:** 무조건 3턴 삭제 금지. 최신 질문이 독립적이면 이전 AI 출력 제거, 후속 질문이면 참조 대상·이전 결론의 최소 구조화 맥락만 전달. 승인 사실/법령 원문은 우선 보존.
- **테스트:** 독립 질문, 3턴 연속 후속 질문, 이전 답변에만 있던 지시어, 증거 변경 후 재상담, 다른 사건 대화 분리; input token과 정확도 동시 비교.
- **롤백:** prompt history budget/selection만 즉시 이전 정책으로 복원 가능.

## 9.7 답변 표시 변경의 전파 영향

- **변경 위치:** `document_consultation.py`의 답변 출력, final disposition/API/React rendering 연결.
- **영향:** 법적 결론을 생성하는 부분까지 수정하면 답변 품질과 검증 정합성이 흔들린다. UI adapter만 바꾸면 **법적 의미 영향은 낮음**이나 섹션 누락·인용 소실·중복 렌더 위험이 있다.
- **수정 경계:** `raw_verified_answer` hash를 보존하고 UI presentation adapter만 먼저 수정. parser 실패 시 원문 단일 렌더.
- **테스트:** 5개 섹션, Markdown, 긴 근거, 파일명·법령 출처, 중복 결론, 빈 섹션, 스트리밍/완료 상태.
- **롤백:** UI adapter만 이전 렌더로 복원, 검증된 답변 원문은 유지.

## 9.8 전체 적용 정책

- **선행조건:** PR-00에서 최신 SHA·기준 Gold·Trace 확보. 이후 PR마다 **코드에서 영향받는 호출자와 테스트를 먼저 찾고**, 최소 수정.
- **우선순위:** (1) **금액 QA의 무근거 자동 수정 차단**은 비교적 국소적인 안전조치로 먼저 가능, (2) 날짜 역할 오류 수정, (3) 법령 버전/부칙 보존, (4) 법령 충분성 gate 수정, (5) EvidenceSpan/승인, (6) verification repair, (7) history 최적화, (8) presentation adapter. 실제 배포는 각 PR Gold PASS 후.
- **성능 허용:** 정확도 차단급 오류 0. 입력 토큰/호출수 증가가 필요한 법령 정확도 개선은 허용하되 KPI에 별도 표기; 성능 PR은 동일 품질에서만 채택.
- **롤백 원칙:** feature flag/adapter/확장형 DB schema로 되돌릴 수 있게 하되, **이미 확인된 잘못된 법률 적용·증거 확정·금액 오수정 로직을 안전한 동작인 것처럼 복원하지 않는다**.

---

# 10. 실제 코드 변경 진행 기록 (2026-11-12)

## 변경 01: QA 첫 금액 기준 자동 수정 차단 — **부분 완료 / 테스트 미실행**

- 코드 커밋: `1ed8e747c115e89276275aaae48fcf2293f04e19`
- 수정 파일: `backend/src/ai_legal_helper/agents/qa_checker.py`
- 소스 확인: 변경 후 GitHub main 파일을 재조회하여 `deposit_matches[0]` 기반 금액 자동 정정 분기가 제거되었음을 확인.
- 변경 이유: 사건 맥락 첫 금액이 전체 보증금이라는 보장이 없어 정확한 잔액·계약금 등을 잘못 수정할 수 있음.
- 영향: 금액 오수정 가능성은 낮아지지만, 기존 단순 regex가 잡던 실제 금액 오기 자동 교정도 중단됨. 인용 검사·질문 충족·법률 위험 검사와 QA 결과 필드 구조는 유지. 금액의 역할 기반 검증은 **미구현**.
- 코드리뷰: 수정 블록과 다음 QA 단계 연결을 정적으로 확인. **실제 Python 테스트·통합 테스트·E2E 테스트는 실행하지 못했으므로 PASS로 표기하지 않음.**
- 후속 필수 작업: (1) 기존 QA 호출자와 RepairTarget 소비자 전수 확인, (2) 금액 역할 기반 판정 구현, (3) unit/integration regression, (4) 다른 항목 순차 수정.
- 상태: **전체 개발 완료 아님.** 이 기록은 실제로 수행한 범위만 명시하며 미실행 테스트를 성공으로 주장하지 않음.

---

# 11. 직접 코드 변경 기록 — 추가 작업 (2026-11-12)

**주의: 아래는 실제 GitHub main에 반영한 변경만 기록한다. 자동 테스트·통합 테스트·E2E 실행 및 전체 호출 경로 전수조사는 미완료이므로 릴리스 준비 완료가 아니다.**

| 작업 | 코드 커밋 | 변경 | 영향 및 미검증 사항 |
|---|---|---|---|
| 날짜 역할 오판 안전 수정 | `3c665e67e855c6bf41e402ffa283b1d0ee0bcc08` | `legal_workflow.py`에서 날짜만으로 `CONTRACT_SIGNED` 설정하는 2개 경로 제거 | `temporal_search_plan.py`가 역할 없는 날짜에 LLM 보완을 호출하거나 SKIP할 수 있음. 전체 시간성 회귀 미실행 |
| 법령 시행일 프롬프트 | `8150ef7e89a7adf812f12dd7e77d2cc70af39a75` | `document_answer.py`에서 과거 사건에 미래 법령을 단정하지 않고 부칙·경과조치를 확인하도록 변경 | LLM 출력 변화 예상. 실제 부칙 Gold 미실행 |
| 법령 중복 제거 안전 수정 | `f60f314b21066a73f526fc33450d6332db20c087` | `grounding_context.py`의 내부 법령 중복키에 버전·부칙·내용 해시 추가 | 중복 제거가 감소해 토큰이 늘 수 있음. 실제 검색 메타데이터와 호출자·citation 정합성 확인 필요 |

**미완료:** NEED_MORE_LAW 충분성 라우팅 수정, EvidenceSpan 생성/일괄승인, 역할 기반 금액 QA, repair/verification 전체 경로, 상담 이력 최적화, UI/최종 답변 정합성, 단위·통합 테스트. 변경 후 GitHub 커밋 성공은 **테스트 PASS가 아니다**. 해당 항목들은 완료로 표시하지 않는다.

**다음 개발 전 필수:** main SHA 고정 → 위 3개 변경의 실제 호출자/테스트 전수 확인 → 테스트 실행 및 수정 → 다음 항목. 사용자가 E2E를 수행하기 전 개발자가 단위·통합 회귀를 수행해야 한다.
