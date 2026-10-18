# 07. 사건 및 엔티티 상태 전이 다이어그램 (Case & Entity State Flow)

이 문서는 [`models.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/database/models.py)와 [`workflow.py`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/routes/workflow.py)에 구현된 **실제 상태 모델(State Model)**을 기반으로, 사건(`Case`), 파생 워크플로우 5단계(`WorkflowStep`), 증거 문서(`EvidenceDocument`), 추출 주장(`EvidenceClaim`), 법률 상담(`ConsultationRecord`), 동기화 태스크(`GraphSyncTask`)의 상태 전이를 시각화한다.

---

## 1. 사건(`Case.status`) DB 저장 상태 vs 파생 워크플로우 상태

### 1.1 `cases.status` 컬럼의 실제 전이 (As-Is DB State)
[`models.py:61`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/database/models.py#L61)의 주석에는 `"OPEN, IN_PROGRESS, CLOSED"`가 명시되어 있으나, 실제 애플리케이션 코드에서 `Case.status`를 변경하는 로직을 추적하면 다음과 같다.

```mermaid
stateDiagram-v2
    [*] --> OPEN : EVT-003 사건 등록\n(CaseMemoryManager.create_case\nmanager.py:42 -> status="OPEN")
    OPEN --> [*] : EVT-007 사건 삭제\n(DELETE /api/v1/cases/{case_id})

    note right of OPEN
        ⚠️ 실제 코드 분석 결과:
        - 진술 추가(EVT-032), 증거 업로드(EVT-008),
          상담 실행(EVT-012), 대응계획(EVT-025),
          문서 생성(EVT-026) 중 어느 코드도
          Case.status를 'IN_PROGRESS'나 'CLOSED'로
          UPDATE하지 않음!
        - 또한 사건 수정 API(EVT-006)가 미구현이므로
          UI/API를 통해 생성된 사건은 삭제 전까지
          영구히 status="OPEN" 상태로 유지됨.
        (DB의 synth-case-lease-001만 시드 스크립트로
         status="IN_PROGRESS"가 입력된 상태)
    end note
```

---

### 1.2 통합 워크플로우 5단계 파생 상태 전이 (`workflow.py:115-315`)
`Case.status`가 갱신되지 않는 대신, 프런트엔드 `OverviewTab`은 [`GET /api/v1/cases/{case_id}/workflow/summary`](file:///c:/myprjs/ai-legal-helper/backend/src/ai_legal_helper/api/routes/workflow.py#L115-L315)가 하위 테이블들의 레코드 존재 여부를 실시간 집계하여 계산하는 **5단계 파생 워크플로우 상태(`WAITING` | `IN_PROGRESS` | `COMPLETED`)**를 사건 진행 상태로 사용한다.

```mermaid
stateDiagram-v2
    direction TB

    state "Step 1: 사건 및 사실관계 정리 (INTAKE)" as S1 {
        S1_IP : IN_PROGRESS\n(facts == 0 AND parties == 0)
        S1_COMP : COMPLETED\n(len(facts) > 0 OR len(parties) > 0)
        [*] --> S1_IP : 사건 최초 생성 (EVT-003)
        S1_IP --> S1_COMP : 진술 추가 (EVT-032) 또는\n증거 Claim 승인 (EVT-033)
    }

    state "Step 2: 증거 업로드 및 검증 (EVIDENCE)" as S2 {
        S2_WAIT : WAITING\n(evidence_documents == 0)
        S2_IP : IN_PROGRESS\n(문서 존재 & pending_claims > 0 OR approved_claims == 0)
        S2_COMP : COMPLETED\n(pending_claims == 0 AND approved_claims > 0)
        [*] --> S2_WAIT
        S2_WAIT --> S2_IP : 증거 업로드 및 추출 (EVT-008, EVT-009)
        S2_IP --> S2_COMP : 모든 PENDING Claim 검토 완료\n& 최소 1건 APPROVE/EDIT (EVT-033)
        S2_COMP --> S2_IP : 신규 증거 추가 업로드 (EVT-008, EVT-023)
    }

    state "Step 3: 법률 쟁점 및 판례 분석 (ANALYSIS)" as S3 {
        S3_WAIT : WAITING\n(completed_consultations == 0 AND legal_issues == 0)
        S3_IP : IN_PROGRESS\n(completed_consultations == 0 AND legal_issues > 0)
        S3_COMP : COMPLETED\n(completed_consultations > 0)
        [*] --> S3_WAIT
        S3_WAIT --> S3_IP : 진술 추가로 LegalIssue 추출됨 (EVT-032)
        S3_WAIT --> S3_COMP : 법률 상담 COMPLETED (EVT-012 ~ EVT-021)
        S3_IP --> S3_COMP : 법률 상담 COMPLETED (EVT-012 ~ EVT-021)
    }

    state "Step 4: 대응 계획 수립 (ACTION_PLAN)" as S4 {
        S4_WAIT : WAITING\n(legal_actions == 0)
        S4_COMP : COMPLETED\n(len(legal_actions) > 0)
        [*] --> S4_WAIT
        S4_WAIT --> S4_COMP : AI Action Plan 생성 (EVT-025)
    }

    state "Step 5: 법률 문서 초안 작성 (DOCUMENT)" as S5 {
        S5_WAIT : WAITING\n(legal_documents == 0)
        S5_COMP : COMPLETED\n(len(legal_documents) > 0)\n⚠️ 단, workflow.py:305 d.doc_type 버그로\n실제 문서 생성 시 HTTP 500 발생!
        [*] --> S5_WAIT
        S5_WAIT --> S5_COMP : 내용증명/통지서 초안 생성 (EVT-026)
    }

    S1 --> S2 : Next Action 추천 우선순위 1 -> 2
    S2 --> S3 : Next Action 추천 우선순위 2 -> 3
    S3 --> S4 : Next Action 추천 우선순위 3 -> 4
    S4 --> S5 : Next Action 추천 우선순위 4 -> 5
```

---

## 2. 하위 도메인 엔티티별 상태 전이 다이어그램

### 2.1 증거 문서 (`EvidenceDocument.status`) 및 추출 주장 (`EvidenceClaim.review_status`)

```mermaid
stateDiagram-v2
    direction LR

    state "EvidenceDocument.status (evidence_ingestion.py / evidence.py)" as DocState {
        [*] --> UPLOADED : EVT-008 파일 업로드\n(ingest_evidence)
        UPLOADED --> EXTRACTING : EVT-009 추출 시작\n(extract_from_document / manual trigger)
        EXTRACTING --> EXTRACTED : 텍스트 파싱 + Span/Claim 추출 성공
        EXTRACTING --> FAILED : 파일 없음 / 파싱 실패 / 예외 발생
        FAILED --> EXTRACTING : EVT-009 수동 '사실 추출' 재실행
        EXTRACTED --> EXTRACTING : EVT-009 수동 '사실 추출' 재실행\n(기존 Span/Claim 삭제 후 재추출)
        UPLOADED --> [*] : EVT-034 증거 삭제
        EXTRACTED --> [*] : EVT-034 증거 삭제
        FAILED --> [*] : EVT-034 증거 삭제
    }

    state "EvidenceClaim.review_status (evidence_manager.py / evidence.py)" as ClaimState {
        [*] --> PENDING : EVT-009 LLM Claim 추출
        PENDING --> APPROVED : EVT-033 action='APPROVE'\n-> Fact(source='evidence_promoted') 생성\n+ EvidenceLink(SUPPORTS) 생성
        PENDING --> EDITED : EVT-033 action='EDIT'\n-> 수정된 문장으로 Fact 생성\n+ EvidenceLink(SUPPORTS) 생성
        PENDING --> REJECTED : EVT-033 action='REJECT'\n-> review_reason 기록 (Fact 미생성)
    }
```

### 2.2 법률 상담 (`ConsultationRecord.status`) 및 그래프 동기화 (`GraphSyncTask.status`)

```mermaid
stateDiagram-v2
    direction LR

    state "ConsultationRecord.status (consultation.py)" as ConsState {
        [*] --> IN_PROGRESS : EVT-012 POST /consultations\n(백그라운드 태스크 시작)
        IN_PROGRESS --> COMPLETED : EVT-021 LangGraph 정상 종료\n⚠️ 현재 retrieved_sources가 비어있지 않으면\n147행 os.path.basename NameError로 도달 실패!
        IN_PROGRESS --> ERROR : 예외 발생 시 (NameError, LLM 오류 등)\nresp.answer = "상담 처리 중 오류가 발생했습니다"
    }

    state "GraphSyncTask.status (graph_sync_worker.py)" as SyncState {
        [*] --> PENDING : queue_sync_task(db, case_id)
        PENDING --> IN_PROGRESS : 워커 폴링 픽업 (5초 주기)
        IN_PROGRESS --> COMPLETED : Neo4j 스냅샷 쓰기 성공\n(ChromaDB 실패는 warning 후 무시)
        IN_PROGRESS --> FAILED : Neo4j 오류 / 예외 발생\n(retry_count += 1, error_log 기록)
        FAILED --> IN_PROGRESS : retry_count < 3 일 때\n다음 폴링 주기에서 재시도
        FAILED --> [*] : retry_count >= 3 도달 시\n영구 FAILED 상태 유지
    }
```

