# P4.1 Verifier-Guided HILT 법령 검색 — 03. LangGraph HILT 노드 및 승인/거절 분기

## 1. 개요
본 문서는 `backend/src/ai_legal_helper/workflows/legal_workflow.py`에 구현된 **LangGraph 0.6+ 기반 Human-in-the-Loop(HILT) 노드와 조건부 라우팅** 메커니즘을 상술한다.

---

## 2. 상태 스키마 확장 (`LegalState`)

HILT 승인 생명주기를 관리하기 위해 `LegalState`(`backend/src/ai_legal_helper/workflows/state.py`)에 다음 필드가 추가되었다:

```python
class LegalState(MessagesState):
    ...
    # P4.1 HILT 관련 상태
    approval_request: Optional[Dict[str, Any]]  # 승인 요청 페이로드
    approval_status: Optional[str]              # NONE, PENDING, APPROVED, REJECTED, EXPIRED
    statute_search_results: Optional[List[Dict[str, Any]]]  # 공식 법령 API 검색 결과
    hilt_executed: Optional[bool]               # HILT 1회 실행 여부 (무한루프 방지)
```

---

## 3. HILT 노드 구현 상세

### 3.1 `statute_search_approval_node`
Verifier가 법률 근거 부족을 감지했을 때 진입하여 사용자에게 승인 요청 데이터를 전달하고 그래프 실행을 일시 중단(interrupt)한다.

```python
@trace
def statute_search_approval_node(state: LegalState) -> Dict:
    ver_res = state.get("verification_result", {}) or {}
    candidate_laws = ver_res.get("candidate_laws", [])
    missing_issues = ver_res.get("missing_legal_issues", []) or ver_res.get("missing_issues", [])
    reason_code = ver_res.get("reason_code", "LEGAL_SOURCE_MISSING")
    explanation = ver_res.get("explanation", "현재 검색된 법률 자료만으로는 해당 쟁점을 충분히 검증할 수 없습니다.")

    case_id = state.get("case_id") or get_case_id() or "GENERAL_CONSULTATION"
    req_id = state.get("request_id") or get_request_id() or str(uuid.uuid4())
    trace_id = state.get("trace_id") or get_trace_id() or str(uuid.uuid4())
    approval_req_id = f"APPR-{str(uuid.uuid4())[:8]}"

    approval_payload = {
        "type": "STATUTE_SEARCH_APPROVAL",
        "case_id": case_id,
        "thread_id": req_id,
        "trace_id": trace_id,
        "approval_request_id": approval_req_id,
        "reason": reason_code,
        "explanation": explanation,
        "missing_issue": ", ".join(missing_issues) if missing_issues else "관련 법령 조문 확인 필요",
        "missing_legal_issues": missing_issues,
        "candidate_laws": candidate_laws,
        "search_scope": "공식 법령 원문 (국가법령정보공동활용 open.law.go.kr)",
        "approval_required": True,
    }

    # LangGraph 표준 interrupt: 상태를 보존하고 호출자(API)에 중단 통보
    decision = interrupt(approval_payload)

    # 호출자가 Command(resume={"approved": bool, ...})로 재개 시 실행 복귀
    approved = False
    if isinstance(decision, dict):
        approved = bool(decision.get("approved", False))
    elif isinstance(decision, bool):
        approved = decision

    return {
        "approval_request": approval_payload,
        "approval_status": "APPROVED" if approved else "REJECTED",
        "hilt_executed": True,
    }
```

### 3.2 조건부 분기 함수 및 에지 연결

1. **`verification_condition`**:
   - `PASS` → `finalize`
   - `not hilt_executed and candidate_laws and reason_code in ("LEGAL_SOURCE_MISSING", "LEGAL_SOURCE_INSUFFICIENT")` → `statute_search_approval`
   - `revision_count < 1 and status == "REVISE"` → `revise`
   - **`hilt_executed == True`**: 공식 법령 검색 및 재분석을 거친 상태이므로, 잔여 미검증 인용을 `finalize_node`의 정화(Sanitization) 로직을 거쳐 안전하게 정제한 후 `finalize`로 확정 종결하여 불필요한 폐기를 방지.
   - 그 외(출처 위조, 거절 등) → `insufficient`

2. **`statute_search_approval_condition`**:
   - `approval_status == "APPROVED"` → `execute_statute_search`
   - `approval_status == "REJECTED"` → `insufficient` (외부 검색 없이 판단 유보)

3. **`statute_search_result_condition`**:
   - 조문 확보 성공(`statute_search_results` 존재) → `re_analyze`
   - 조문 검색 실패(공식 API에서도 미확인) → `insufficient`

4. **`re_analyze` 노드 서두 필수 안내 명세 (하드코딩 배제 및 동적 조문 바인딩)**:
   - 답변 최상단에 **`[공식 법령 원문 연동 및 근거 보강 안내]`** 섹션을 강제하여, 의뢰인에게 검증관의 1차 검토 경과, 승인(HITL)에 따른 `open.law.go.kr` 공식 연동 출처, 답변에 반영된 실제 법령 조문 번호 목록(`retrieved_articles_summary`)을 특정 도메인 하드코딩 없이 동적으로 고지한다.

5. **`re_analyze` → `verification`**:
   - 새로 확보된 공식 조문을 기반으로 초안 재작성 후 다시 Verifier에 투입하여 철저한 재검증(PASS 판정)을 수행.

---

## 4. Checkpointer 지속성 및 중복 Resume 방지

### 4.1 Checkpointer와 PostgreSQL 이중 보존
- **LangGraph Checkpointer (`MemorySaver`)**: 비동기 워크플로우 이벤트 루프의 인터럽트 위치와 그래프 스택 상태를 보존.
- **PostgreSQL Database (`ConsultationRecord`)**:
  - `status: "APPROVAL_REQUIRED"`
  - `approval_request`: JSON 페이로드
  - `request_id`, `trace_id`, `case_id` 연결

### 4.2 중복 실행 및 재개(Resume) 안전장치
1. **상태 전이 락**: 사용자가 승인/거절 버튼을 누르는 즉시 서버 API는 상태를 `IN_PROGRESS`로 변경하여 동일 요청에 대한 중복 `POST /consultations/{request_id}/approve` 호출을 `400 Bad Request`로 차단.
2. **`hilt_executed: True` 플래그**: 워크플로우 상태에 HILT 실행 여부를 영구 기록하여, 재분석 후 다시 근거가 부족하더라도 2차 HILT가 반복 발생하는 무한 루프를 원천 차단.

