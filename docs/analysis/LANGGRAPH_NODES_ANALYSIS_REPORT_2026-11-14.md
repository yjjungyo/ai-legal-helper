# LangGraph 노드 역할 분류, 필요성 평가 및 아키텍처 개선 분석 보고서 (2026-11-14)

- **작성일**: 2026-11-14
- **대상 브랜치**: `feature/sc013-subsumption-fix`
- **분석 대상 소스**:
  - 주 상담 워크플로우: [`backend/src/ai_legal_helper/workflows/legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py)
  - 문서 상담 전용 핸들러: [`backend/src/ai_legal_helper/workflows/document_consultation.py`](../../backend/src/ai_legal_helper/workflows/document_consultation.py)
  - 법률 서식 초안 워크플로우: [`backend/src/ai_legal_helper/workflows/document_workflow.py`](../../backend/src/ai_legal_helper/workflows/document_workflow.py)
  - API 진행 단계 매핑: [`backend/src/ai_legal_helper/api/routes/consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py)

---

## 1. 개요 및 전체 그래프 토폴로지

현재 `AI Legal Helper` 백엔드는 크게 **2개의 LangGraph 상태 머신**을 보유하고 있으며, 핵심 법률 상담을 처리하는 [`build_legal_graph()`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5305-L5476)에는 **총 16개의 활성 노드(Active Nodes)**와 그래프에서 분리된 **2개의 레거시 호환 노드(Legacy Nodes)**가 정의되어 있습니다.

### 1.1 통합 법률 상담 그래프 (`build_legal_graph`) 전체 구조

```mermaid
flowchart TD
    START((START)) --> SI["1. supervisor_initialize<br/>(사건·맥락·브리핑·쟁점 초기화)"]

    SI -->|GENERAL_CONVERSATION / OUT_OF_SCOPE| GC["2. general_conversation<br/>(일상 인사·범위 밖 안내)"]
    SI -->|evidence_unavailable=True| EU["3. evidence_unavailable<br/>(승인 원문 부재 안내)"]
    SI -->|NEEDS_CLARIFICATION| RE["4. routing_exit<br/>(질의 구체화/오류 안내)"]
    SI -->|정상 법률 질의| RT["5. route<br/>(법률 분야 분류)"]

    GC --> END((END))
    EU --> END
    RE --> END

    RT -->|NEEDS_CLARIFICATION / ERROR| RE
    RT -->|CLASSIFIED| SSP["6. statute_search_plan<br/>(시점 법령 검색 계획)"]

    SSP -->|PRE_ANALYSIS READY| SSA["10. statute_search_approval<br/>(HITL 외부 검색 승인/자동승인)"]
    SSP -->|SKIP / 로컬 충분| RA["7. run_agents<br/>(벡터DB 검색 & 로컬 사전적재)"]

    RA --> LEB["8. legal_evidence_bundle<br/>(공식/벡터 법령 번들 요약)"]
    LEB --> SYN["9. synthesize<br/>(초안 답변 단일 생성)"]

    SYN -->|NEED_MORE_LAW| SSA
    SYN -->|ERROR| INS["14. insufficient<br/>(판단 유보 안내 생성)"]
    SYN -->|READY| VER["13. verification<br/>(결정론적 QA + LLM 대입 검증)"]

    VER -->|PASS / 조건부 확정| FIN["15. finalize<br/>(인용 복원·출처 확정·배지 결정)"]
    VER -->|LEGAL_SOURCE_MISSING| SSA
    VER -->|이미 승인된 법령 존재| ESS["11. execute_statute_search<br/>(OpenLaw API 호출 및 버전 판정)"]
    VER -->|REVISE (재작성 한도 내)| REV["12. revise<br/>(핀포인트 교정 또는 전체 재작성)"]
    VER -->|INSUFFICIENT / 중대 결함| INS

    SSA -->|APPROVED| ESS
    SSA -->|REJECTED| INS

    ESS -->|PRE_ANALYSIS / 초안 전| RA
    ESS -->|POST_VERIFICATION| REA["16. re_analyze<br/>(확보 법령 기반 재분석)"]
    ESS -->|API_ERROR| INS

    REA --> VER
    REV --> VER
    FIN --> END
    INS --> END

    FA["[고립 노드] followup_action<br/>(진입 엣지 없음)"] -.-> VER
```

---

## 2. LangGraph 노드 역할 분류 (6대 기능군)

[`legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py)에 정의된 총 18개 노드 함수(활성 16개 + 미연결 2개)를 역할에 따라 **6대 기능군**으로 분류하면 다음과 같습니다.

| 분류군 | 노드명 (함수명) | UI 진행 단계 (`step_id`) | LLM 호출 여부 | 핵심 역할 요약 |
| :--- | :--- | :---: | :---: | :--- |
| **① 진입·컨텍스트 준비 및 라우팅** | `supervisor_initialize`<br>([`supervisor_initialize_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L291-L498)) | `step_1` | X (0회) | 사건 ID 복원, 이전 턴 인용 법령 계승, PostgreSQL `CaseEvidenceBriefing` 로딩, 규칙 기반 단위 쟁점([`plan_legal_issues`](../../backend/src/ai_legal_helper/workflows/issue_planner.py#L184)) 도출, `DOCUMENT_GROUNDED` 모드 결정 |
| **① 진입·컨텍스트 준비 및 라우팅** | `route`<br>([`route_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L678-L748)) | `step_2` | 문서모드: X<br>일반모드: 0~1회 | 문서 상담(`DOCUMENT_MODE`)은 LLM 없이 즉시 `case_type`(`민법` 등)을 채택(0.00s)하고, 일반 상담은 필요 시 LLM 라우터로 8대 법률 분야를 분류 |
| **② 조기 종료 (Fast-Exit)** | `general_conversation`<br>([`general_conversation_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5030-L5134)) | `step_6` | X (0회) | 단순 인사말("안녕하세요", "감사합니다") 및 법률 무관 질문(`OUT_OF_SCOPE`)에 대해 RAG·검증 없이 즉시 정중한 안내 반환 (`DELIVERED`) |
| **② 조기 종료 (Fast-Exit)** | `evidence_unavailable`<br>([`evidence_unavailable_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L4966-L5022)) | 미매핑 | X (0회) | 사건 기반 상담(`case_id` 존재)이나 승인(`APPROVED`)된 증거 원문이 1건도 없을 때 성급한 추측을 차단하고 증거 등록 안내 반환 (`WITHHELD`) |
| **② 조기 종료 (Fast-Exit)** | `routing_exit`<br>([`routing_exit_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L819-L919)) | 미매핑 | X (0회) | 질문이 지나치게 모호(`NEEDS_CLARIFICATION`)하거나 라우터 오류(`ROUTER_ERROR`) 발생 시 구체화 요청 안내문 반환 (`WITHHELD`) |
| **③ 법령 검색 및 시점 계획** | `statute_search_plan`<br>([`statute_search_plan_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L943-L999)) | `step_2` | 일반질의: X<br>시점미상: 0~1회 | 질문에 특정 기준일/개정법/시행일 쟁점이 있을 때 로컬 카탈로그(`law_catalog`)를 조회하여 사전 공식 검색(`PRE_ANALYSIS`) 필요 여부 판정 |
| **③ 법령 검색 및 시점 계획** | `run_agents`<br>([`run_agents_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1079-L1391)) | `step_3` | 문서/단일: X<br>복합일반: 0~2회 | **[문서 상담]** ChromaDB 벡터 검색(`k=6`, 질문+쟁점 쿼리 결합) + `issue_tasks` 필수/후보 법령 로컬 인덱스 사전 적재(Local-First Pre-fetch)<br>**[일반 상담]** 고속 검색 모드(`fast_retrieval_only`) 또는 분야별 Specialist 에이전트 병렬 실행 |
| **③ 법령 검색 및 시점 계획** | `legal_evidence_bundle`<br>([`legal_evidence_bundle_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1397-L1427)) | 미매핑 | X (0회) | 검색된 법령 조문과 부칙 적용례 판정(`temporal_resolution`)을 결합하여 일반 상담 Synthesizer 주입용 요약 번들(`digest`) 생성 |
| **④ HITL 공식 법령 검색** | `statute_search_approval`<br>([`statute_search_approval_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L3776-L3972)) | `step_3` | X (0회) | 로컬 벡터DB에 없는 필수 법령 조문이 필요할 때 LangGraph `interrupt()`를 호출하여 사용자 승인 대기 (또는 `AUTO_APPROVE_STATUTE_SEARCH`로 자동 승인) |
| **④ HITL 공식 법령 검색** | `execute_statute_search`<br>([`execute_statute_search_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L4010-L4328)) | `step_3` | 부칙해석 시 0~1회 | 국가법령정보센터(OpenLaw API)에서 승인된 법령·조문 원문을 실시간 조회하고, 백그라운드 인덱싱 큐(`index_jobs`)에 적재 요청 |
| **⑤ 초안 생성 및 보강·재작성** | `synthesize`<br>([`synthesize_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1435-L1546)) | `step_4` | **1회** | **[문서 상담]** [`generate_answer()`](../../backend/src/ai_legal_helper/workflows/document_consultation.py#L168)를 통해 사건 사실·타임라인·확보 법령 기반 답변 초안 및 출처 매니페스트 생성<br>**[일반 상담]** [`synthesize()`](../../backend/src/ai_legal_helper/agents/synthesizer.py#L157)를 통해 종합 답변 초안 생성 |
| **⑤ 초안 생성 및 보강·재작성** | `revise`<br>([`revise_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L2700-L3025)) | `step_5` | **1회**<br>(시점재검증 시 0회) | 검증(`REVISE`) 피드백을 반영하여 **[문서 상담]** `generate_answer(state, repair=True)` 실행, **[일반 상담]** 결함 문장 핀포인트 교정(`repair_draft_answer`) 또는 보강 RAG 검색 후 재작성 |
| **⑤ 초안 생성 및 보강·재작성** | `re_analyze`<br>([`re_analyze_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L4405-L4603)) | `step_4` | **1회** | 사후 HITL 외부 법령 검색(`POST_VERIFICATION`) 완료 후 새로 확보된 법령 원문을 반영하여 초안 재작성 |
| **⑤ 초안 생성 및 보강·재작성** | `followup_action`<br>([`followup_action_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5195-L5301)) | `step_4` | 1회 | 후속 실무 행동 요령 질의에 대해 3단 구조로 신속 답변 생성 (**현재 그래프 진입 엣지 단절 상태 — 3절 참조**) |
| **⑥ 검증 및 최종 처분 확정** | `verification`<br>([`verification_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1576-L2136)) | `step_5` | **1회**<br>(QA 통과 시 경량화) | 결정론적 인용·날짜·금액 QA 검사 + LLM 기반 사실·증거·법령 시행일·포섭(`LEGAL_APPLICATION` 4단계 대입) 검증 수행 |
| **⑥ 검증 및 최종 처분 확정** | `finalize`<br>([`finalize_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L3331-L3686)) | `step_6` | **X (0회)** | 추가 LLM 호출 없이 검증된 초안을 보존(`DRAFT_PRESERVED`), 축약 증거 인용(`[E01]`)을 전체 파일명으로 복원, 최종 처분(`DELIVERED`/`CAUTIONARY`) 및 인용 출처 확정 |
| **⑥ 검증 및 최종 처분 확정** | `insufficient`<br>([`insufficient_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L3031-L3324)) | `step_6` | **X (0회)** | 미검증 초안 노출을 차단하고, 부족한 법령·증거 요건과 이미 확인된 사건 사실을 정리하여 안전한 판단 유보(`WITHHELD`) 안내문 생성 |
| **⑦ 레거시 미연결 노드** | `plan_node` / `intent_analysis_node` | - | - | 그래프(`build_legal_graph`)에서 제거되었으나 하위 단위 테스트 호환성을 위해 파일 내에 남아 있는 레거시 함수 |

---

## 3. 노드별 필요성 평가 및 핵심 개선 사항 분석

각 노드가 실제 런타임에서 반드시 필요한지 평가하고, 소스코드와 트레이스 분석을 통해 확인된 **6가지 구조적 개선 과제**를 도출했습니다.

### 3.1 노드별 필요성 판정 요약

| 노드명 | 필요성 판정 | 판정 근거 및 진단 요약 |
| :--- | :---: | :--- |
| `supervisor_initialize` | **필수 (핵심)** | 초기 의도 판별, 사건 브리핑 로딩, 쟁점 분해를 LLM 호출 없이 0.01초 내에 일괄 처리하는 핵심 진입점 |
| `general_conversation` | **필수** | 인사말·법률 무관 질의를 비용 0원으로 즉시 응답하여 불필요한 RAG·LLM 비용 낭비 차단 |
| `evidence_unavailable` | **필수** | 사건 문서 미승인 상태에서 환각 답변이 생성되는 것을 원천 차단하는 안전 게이트 |
| `routing_exit` | **필수** | 모호한 질의나 라우터 장애 시 미검증 추측 답변 대신 명확화 안내를 반환하는 안전 출구 |
| `route` | **유지 (모드별 분기 개선 가능)** | 일반 상담(`STANDARD`)에서는 분야 분류에 필수적이나, 문서 상담(`DOCUMENT_MODE`)에서는 이미 `supervisor_initialize`에서 결정 가능한 값만 복사하는 Pass-through 상태 |
| `statute_search_plan` | **필수** | 개정법·시행일·부칙 쟁점 질의 시 사전 법령 버전을 계획하는 시점 정합성 핵심 노드 |
| `run_agents` | **필수 (핵심)** | 벡터DB(`law_docs_*`, `law_docs_global`) 검색 및 쟁점 기반 필수 법령 사전 적재(Pre-fetch) 수행 |
| `legal_evidence_bundle` | **조건부 필요 (개선 필요)** | 일반 상담(`STANDARD`)의 `synthesize()`에는 사용되나, **문서 상담(`DOCUMENT_MODE`)에서는 생성된 `legal_evidence_bundle`을 `generate_answer()`가 전혀 읽지 않아 불필요한 중간 노드로 동작** |
| `synthesize` | **필수 (핵심)** | 수집된 사건 사실·타임라인·법령 원문을 결합해 초안을 단일 생성하는 핵심 노드 |
| `verification` | **필수 (핵심)** | 출처 존재성, 사실 부합성, 법률 요건 포섭(`LEGAL_APPLICATION`), 시행일 정합성을 검증하는 품질 관문 |
| `statute_search_approval` | **필수** | 외부 OpenLaw API 호출 전 사용자 동의(HITL Interrupt) 및 승인 법령 범위를 통제하는 보안·거버넌스 노드 |
| `execute_statute_search` | **필수** | 로컬 DB에 없는 법령·조문을 국가법령정보센터에서 실시간 보충하고 백그라운드 인덱싱 큐에 등록 |
| `revise` | **필수** | 검증 실패 시 결함 문장 핀포인트 교정 또는 검증 피드백 반영 재작성을 수행 |
| `re_analyze` | **통합 검토 가능** | 일반 상담에서는 별도 프롬프트를 쓰나, **문서 상담(`DOCUMENT_MODE`)에서는 `revise`와 완전히 동일한 `generate_answer(state, repair=True)`를 호출**하므로 역할이 중복됨 |
| `finalize` | **필수 (핵심)** | LLM 재호출 없이 검증 통과 초안을 보존하고 증거 파일명 확장·배지 처분·스냅샷 해시를 확정 |
| `insufficient` | **필수 (핵심)** | 검증 미통과·법령 미확보 시 미검증 초안 유출을 막고 고객 친화적인 판단 유보 가이드를 조립 |
| `followup_action` | **구조 결함 (즉시 점검 필요)** | `build_legal_graph`에 노드로 등록되어 있으나 **`supervisor_condition`에서 이 노드로 연결되는 진입 엣지(Incoming Edge)가 누락되어 그래프 상에서 도달 불가능(Dead Node)** |
| `plan_node` / `intent_analysis_node` | **불필요 (레거시 분리 권장)** | 그래프에서 이미 제거된 구버전 노드로, `legal_workflow.py` 파일 비대화(5,920라인)의 원인 |

---

### 3.2 상세 개선 과제 (우선순위순)

#### 개선 과제 1 (중요도: 상): `run_agents_node`의 `@trace` 누락 복원
- **현상**: [`legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1079)에서 16개 활성 그래프 노드 중 유일하게 [`run_agents_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1079)에만 `@trace` 데코레이터가 빠져 있습니다.
- **원인**: 과거 `run_agents_node` 바로 위에 있던 `@trace`와 함수 정의 사이에 헬퍼 함수 `format_statute_display`가 삽입되면서 `@trace`가 헬퍼 함수에 잘못 붙었던 것이 원인입니다.
- **영향**: Langfuse Trace에서 3단계 핵심 노드인 `run_agents` 상위 Span이 생성되지 않아, 하위 `retrieve_with_status` Span들이 루트 Trace에 직접 매달리거나(`[SPAN_PARENT_UNRESOLVED]`) 3단계 전체 소요시간 계측이 누락됩니다.
- **개선 방안**: [`run_agents_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1079) 함수 상단에 `@trace`를 부착하여 모든 LangGraph 노드의 Span 계층 구조를 일관되게 복원합니다.

#### 개선 과제 2 (중요도: 상): `followup_action` 고립 노드(Unreachable Node) 정리 또는 연결 복원
- **현상**: [`build_legal_graph()`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5337)에 `graph.add_node("followup_action", followup_action_node)`와 `graph.add_edge("followup_action", "verification")`(L5385)이 등록되어 있지만, [`supervisor_condition()`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L501-L520)의 분기 맵(L5369-L5379)에는 `"followup_action"`이 존재하지 않습니다.
- **원인**: 과거 `intent_analysis_node`를 `supervisor_initialize_node`로 통합할 때 모든 법률 질의를 `NEW_LEGAL_ANALYSIS`로 설정하고 복합 쟁점 누락 방지를 위해 정규 파이프라인(`route`)으로 일원화하면서 `followup_action`으로 가는 진입 분기가 제거되었습니다.
- **개선 방안**:
  - **옵션 A (권장)**: 모든 법률 질의가 정규 검색·검증 파이프라인을 거치도록 설계된 현행 정책에 맞춰, 그래프 노드 등록(`add_node("followup_action")`, `add_edge("followup_action", "verification")`)을 제거하여 Dead Node를 없애고, 필요한 경우에만 `revise_node` 내부 헬퍼 함수로 유지합니다.
  - **옵션 B**: 단순 절차 후속 질문에 한해 Fast-Path를 다시 활성화하려면 `supervisor_initialize_node`와 `supervisor_condition`에 `FOLLOWUP_ACTION` 분기 조건과 엣지를 명시적으로 연결해야 합니다.

#### 개선 과제 3 (중요도: 중): 문서 상담(`DOCUMENT_MODE`)에서 `legal_evidence_bundle` 노드 우회 또는 통합
- **현상**: 현재 그래프는 `run_agents` → `legal_evidence_bundle` → `synthesize`로 고정 연결되어 있습니다. 그러나 문서 상담(`answer_mode == "DOCUMENT_GROUNDED"`)에서는 [`synthesize_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1463-L1465)가 [`generate_answer(state)`](../../backend/src/ai_legal_helper/workflows/document_consultation.py#L168)를 호출하며, `generate_answer()`는 `legal_evidence_bundle`을 전혀 참조하지 않고 `document_sources(state)`로 직접 원문과 법령을 포맷팅합니다.
- **영향**: 문서 상담 시 매 턴마다 사용하지도 않는 `legal_evidence_bundle` 객체를 생성·직렬화하여 LangGraph 체크포인터(PostgreSQL) 상태 크기를 불필요하게 증가시킵니다.
- **개선 방안**: `legal_evidence_bundle_node` 초입에서 `if state.get("answer_mode") == DOCUMENT_MODE: return {}`로 즉시 스킵하거나, 일반 상담 `synthesize_node` 내부에서 `build_legal_evidence_bundle()`을 직접 호출하도록 통합하면 그래프 노드를 1개 줄이고 체크포인트 페이로드를 경량화할 수 있습니다.

#### 개선 과제 4 (중요도: 중): `re_analyze` 노드와 `revise` 노드의 역할 통합 검토
- **현상**:
  - `revise_node` (검증 실패 후 재작성)와 `re_analyze_node` (HITL 법령 검색 후 재작성)는 모두 **"초안을 보강하여 다시 `verification` 노드로 보낸다"**는 동일한 상태 전이(`-> verification`)를 가집니다.
  - 특히 문서 상담(`DOCUMENT_MODE`)에서는 두 노드 모두 똑같이 `generate_answer(state, repair=True)`를 호출합니다.
- **개선 방안**: 중장기적으로 `re_analyze`를 별도 노드로 두는 대신 `revise` 노드(또는 `synthesize` 노드의 재진입)로 통합하고, `execute_statute_search` 완료 후 `synthesize` 또는 `revise`로 분기하게 하면 그래프의 루프 구조(`verification ↔ revise/statute_search`)가 훨씬 단순하고 명확해집니다.

#### 개선 과제 5 (중요도: 중): `consultation.py`의 `NODE_TO_PROGRESS_STEP` 매핑 현행화
- **현상**: [`consultation.py`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L120-L137)의 `NODE_TO_PROGRESS_STEP` 딕셔너리에 이미 그래프에서 제거된 `"intent_analysis"`와 `"plan"`이 남아 있는 반면, 실제 활성 노드인 `"legal_evidence_bundle"`, `"evidence_unavailable"`, `"routing_exit"`는 매핑되어 있지 않습니다.
- **영향**: 기능상 치명적 오류는 없으나, `on_step_callback` 호출 시 미매핑 노드는 진행 단계 갱신이 무시되고 레거시 키가 남아 코드 가독성을 떨어뜨립니다.
- **개선 방안**: `NODE_TO_PROGRESS_STEP`에서 미사용 레거시 키를 정리하고 실제 16개 활성 노드와 1:1로 정합성을 맞춥니다.

#### 개선 과제 6 (중요도: 하): `legal_workflow.py` 내 레거시 미연결 함수 분리 및 모듈화
- **현상**: [`legal_workflow.py`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py) 단일 파일이 약 **5,920라인**에 달하며, 그래프에 연결되지 않은 구버전 노드(`plan_node`, `intent_analysis_node`, `intent_condition`, `_collect_graph_evidence`)가 함께 혼재되어 있습니다.
- **개선 방안**: 하위 호환용 레거시 노드 및 조건 함수들을 별도 모듈(예: `workflows/legacy_nodes.py`)로 분리하거나 미사용 테스트 정리 후 제거하여 주 워크플로우 파일의 응집도와 유지보수성을 높입니다.

---

## 4. 부록: 법률 문서(서식) 초안 생성 그래프 (`document_workflow.py`) 분석

상담 챗봇 그래프와 별개로, 사건 상세 화면에서 내용증명·임차권등기명령 신청서 등 **법률 서식 초안**을 생성할 때 사용되는 [`document_workflow.py`](../../backend/src/ai_legal_helper/workflows/document_workflow.py#L198-L217)는 5개의 선형 노드로 구성되어 있습니다.

| 순서 | 노드명 (함수명) | 역할 및 필요성 | 개선 검토 사항 |
| :---: | :--- | :--- | :--- |
| 1 | `context` ([`context_node`](../../backend/src/ai_legal_helper/workflows/document_workflow.py#L56)) | PostgreSQL에서 사건 개요, 당사자(`Party`), 확정 사실(`Fact`), 타임라인(`Event`), 승인된 증거(`EvidenceClaim`)를 조회 (**필수**) | `CaseEvidenceBriefing` 빌더를 재사용하면 상담 워크플로우와 사실/증거 포맷 일관성 향상 가능 |
| 2 | `requirements` ([`requirements_node`](../../backend/src/ai_legal_helper/workflows/document_workflow.py#L92)) | 서식 작성에 필요한 최소 사건 정보 존재 여부 검사 (**필수**) | 현행 유지 (단순·명확한 가드레일) |
| 3 | `generation` ([`generate_node`](../../backend/src/ai_legal_helper/workflows/document_workflow.py#L105)) | `DocumentDraftSchema` 구조화 출력으로 서식 초안 생성 (**필수**) | `res.dict()`(Pydantic v1 방식) 대신 `res.model_dump()`(Pydantic v2 표준) 사용 권장 |
| 4 | `verification` ([`verification_node`](../../backend/src/ai_legal_helper/workflows/document_workflow.py#L132)) | 생성된 서식 내 날짜·금액을 정규화하여 사건 원문과 대조 검증 (**필수**) | 현행 유지 (결정론적 수량 비교로 빠르고 정확함) |
| 5 | `review_gate` ([`review_gate_node`](../../backend/src/ai_legal_helper/workflows/document_workflow.py#L172)) | 검증 통과/경고 초안을 `LegalDocument` 및 `DocumentRevision` 테이블에 저장 (**필수**) | 현행 유지 |


---

## 5. 6대 개선 과제 재검토(타당성·회귀 영향 검증) 및 조치 결과

보고서 3.2절에서 도출한 6개 개선 과제를 기존 단위·통합 테스트 계약(`backend/tests/unit/`) 및 런타임 아키텍처 불변식과 대조하여 재검토하고, 타당한 항목을 코드에 즉시 반영했습니다.

| 과제 번호 | 개선 과제명 | 재검토 판정 | 타당성 검증 근거 및 조치 내용 |
| :---: | :--- | :---: | :--- |
| **과제 1** | `run_agents_node`의 `@trace` 누락 복원 | **타당 (즉시 반영 완료)** | • 15개 활성 그래프 노드 중 유일하게 [`run_agents_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1079)에만 `@trace`가 빠져 있어 3단계 상위 Span이 누락되던 결함 확인.<br>• `@trace` 데코레이터는 `asyncio.iscoroutinefunction`을 지원하므로 비동기 시그니처(`async def`)와 단위 테스트 호환성을 100% 유지하며 복원 완료. |
| **과제 2** | `followup_action` 고립 노드(Unreachable Dead Node) 정리 | **타당 (그래프 등록 해제 완료)** | • [`build_legal_graph()`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L5315)에서 진입 엣지가 단절된 `add_node("followup_action")` 및 `add_edge("followup_action", "verification")`을 제거하여 활성 노드를 16개 → **15개**로 정돈.<br>• 단, [`revise_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L2761) 내부의 헬퍼 호출 및 [`test_adaptive_workflow.py`](../../backend/tests/unit/test_adaptive_workflow.py) 단위 테스트 계약을 유지하기 위해 `followup_action_node()` 함수 자체는 보존. |
| **과제 3** | 문서 상담(`DOCUMENT_MODE`)에서 `legal_evidence_bundle` 스킵 | **타당 (최적화 반영 완료)** | • [`test_legal_evidence_bundle_p7.py`](../../backend/tests/unit/test_legal_evidence_bundle_p7.py#L157)가 `compiled.nodes` 내 `"legal_evidence_bundle"` 노드 존재를 검증하므로 그래프 노드 구조는 유지.<br>• 대신 [`legal_evidence_bundle_node`](../../backend/src/ai_legal_helper/workflows/legal_workflow.py#L1398) 초입에서 `state.get("answer_mode") == DOCUMENT_MODE`일 때 불필요한 요약 번들(`build_legal_evidence_bundle`) 생성을 생략하고 `{"legal_evidence_bundle": None}`을 즉시 반환하도록 최적화 완료. |
| **과제 4** | `re_analyze` 노드와 `revise` 노드의 역할 통합 검토 | **분리 유지 타당 + 진행상태 보완 완료** | • **재검토 결과 무리한 노드 통합보다 분리 유지가 타당함**:<br>  1) `re_analyze`는 외부 법령 검색(`step_3`) 직후 **4단계(`step_4`: 법령 검색 결과 기반 재분석 중)**로 표시되어야 하는 반면, `revise`는 **5단계(`step_5`: 검증 피드백 기반 보강 중)**에 해당.<br>  2) 문서 상담(`DOCUMENT_MODE`)에서 `re_analyze`는 `increment_revision=False`로 호출되어 **공식 법령 확보 후 첫 재작성 시 `revision_count`를 소모하지 않는 정책**([`test_document_consultation.py`](../../backend/tests/unit/test_document_consultation.py#L453))을 보장함.<br>• **보완 조치**: `re_analyze_node` 진입 시 `DOCUMENT_MODE`에서도 실시간으로 `step_4` 진행 상태(`update_progress_step`)가 갱신되도록 보완 완료. |
| **과제 5** | `consultation.py`의 `NODE_TO_PROGRESS_STEP` 매핑 현행화 | **부분 수정 타당 (반영 완료)** | • [`test_case_centric_chat_api.py`](../../backend/tests/unit/test_case_centric_chat_api.py#L85-L92)가 `"intent_analysis"`와 `"plan"` 키를 명시적으로 검증하므로 하위 호환을 위해 두 키는 주석과 함께 유지.<br>• 누락되어 있던 활성 노드 3종(`"legal_evidence_bundle": step_3`, `"evidence_unavailable": step_6`, `"routing_exit": step_6`)을 [`NODE_TO_PROGRESS_STEP`](../../backend/src/ai_legal_helper/api/routes/consultation.py#L120-L143)에 추가 완료. |
| **과제 6** | 레거시 미연결 함수 정리 및 `document_workflow.py` 개선 | **호환성 유지 + Pydantic v2 반영 완료** | • `plan_node` 및 `intent_analysis_node`는 다수의 단위 테스트에서 `ai_legal_helper.workflows.legal_workflow` 경로로 직접 임포트 및 `unittest.mock.patch` 대상이 되므로 동일 모듈 내에 보존하되 레거시 호환 목적 Docstring을 명시.<br>• [`document_workflow.py`](../../backend/src/ai_legal_helper/workflows/document_workflow.py#L123)의 Pydantic v1 방식 `res.dict()`를 Pydantic v2 표준 `res.model_dump()` 우선 호출 방식으로 개선 완료. |
