# P4.1 Verifier-Guided HILT 법령 검색 — 05. FastAPI Resume API 및 React UI 구현

## 1. 개요
본 문서는 사용자에게 법령 검색 승인을 요청하고, 결정을 접수하여 중단된 LangGraph 워크플로우를 재개(Resume)하는 **FastAPI 백엔드 엔드포인트**와 **React 프론트엔드 UI 인터랙션 컴포넌트**의 구현 내용을 설명한다.

---

## 2. FastAPI 백엔드 엔드포인트 명세

### 2.1 승인/거절 접수 API: `POST /consultations/{request_id}/approve`
사용자가 프론트엔드에서 승인 또는 거절 버튼을 클릭했을 때 호출되는 핵심 엔드포인트이다.

- **요청 Body**:
  ```json
  {
    "approved": true,
    "reason": "주택임대차보호법 조문 확인 요청"
  }
  ```
- **처리 로직**:
  1. `request_id`로 DB(`ConsultationRecord`) 및 In-memory 캐시 조회 (없으면 404).
  2. 사건 및 사용자 소유권 검증 (미인증/타인 상담 접근 시 403 차단).
  3. 현재 상태가 `APPROVAL_REQUIRED`인지 확인 (아니면 400 Bad Request).
  4. 상태를 즉시 `IN_PROGRESS`로 변경하여 중복 클릭/Resume 원천 방지.
  5. 백그라운드 태스크 `process_consultation_resume` 스케줄링.
  6. 갱신된 `ConsultationResponse` 즉시 반환.

### 2.2 비동기 재개 태스크: `process_consultation_resume`
```python
async def process_consultation_resume(
    request_id: str, 
    trace_id: str, 
    case_id: Optional[str],
    decision: ApprovalDecisionRequest
):
    # LangGraph Command(resume=...) 호출로 인터럽트된 statute_search_approval 노드 재개
    result = await run_legal_consultation(
        question="",
        thread_id=request_id,
        resume_data={"approved": decision.approved, "reason": decision.reason}
    )
    # 토큰 사용량 집계, 출처 정규화, PostgreSQL 및 Langfuse 최종 결과 갱신
```

### 2.3 상담 조회 API 확장
`GET /consultations/{request_id}` 및 `GET /cases/{case_id}/consultations`에서 `approval_request` 필드를 응답 JSON에 포함하여, 새로고침이나 화면 이동 후에도 승인 대기 상태 카드가 유지되도록 보장한다.

---

## 3. React 프론트엔드 구현

### 3.1 `useConsultation` Hook 생명주기 관리
`frontend/src/hooks/useConsultation.ts`에 `respondApproval` 함수를 추가하였다:

```typescript
const respondApproval = async (requestId: string, approved: boolean, reason?: string) => {
  clearPollInterval();
  setLoading(true);
  setError(null);
  
  // 1. 서버에 승인/거절 전송
  const updated = await approveStatuteSearch(requestId, approved, reason);
  setResult(updated);

  // 2. 재개된 워크플로우가 완료(SUCCESS 또는 INSUFFICIENT)될 때까지 2초 주기로 폴링
  pollIntervalRef.current = setInterval(async () => {
    const current = await getConsultation(requestId);
    setResult(current);
    if (current.status !== 'IN_PROGRESS' && current.status !== 'APPROVAL_REQUIRED') {
      clearPollInterval();
      setLoading(false);
      loadHistory();
    }
  }, 2000);
};
```

### 3.2 HILT 승인 대기 카드 UI (`ChatSection.tsx`)
실시간 진행 카드 및 상담 이력 목록 모두에서 `item.status === 'APPROVAL_REQUIRED'`인 경우 전용 카드가 렌더링된다:

```tsx
{result && result.status === 'APPROVAL_REQUIRED' && (
  <div className="hilt-approval-card">
    <div className="header">
      <span>⚖️</span>
      <strong>공식 법령 원문 추가 검색 승인 요청 (Human-in-the-Loop)</strong>
      <span className="badge badge-blue">사용자 결정 대기</span>
    </div>
    <p>{result.approval_request?.explanation}</p>
    <div className="meta-box">
      <div><strong>확인 필요 쟁점: </strong>{result.approval_request?.missing_issue}</div>
      <div><strong>조회 후보 법령: </strong>{result.approval_request?.candidate_laws.join(', ')}</div>
      <div><strong>검색 출처: </strong>{result.approval_request?.search_scope}</div>
    </div>
    <div className="actions">
      <button onClick={() => handleApprovalDecision(result.request_id, false)}>
        ✕ 추가 검색 없이 종료 (판단 유보)
      </button>
      <button onClick={() => handleApprovalDecision(result.request_id, true)} className="btn-primary">
        ✓ 공식 법령 검색 승인 및 재분석
      </button>
    </div>
  </div>
)}
```

### 3.3 실무 권고사항(Practical Cautions)과 검증 경고의 UI 분리 렌더링 (`ChatSection.tsx`)
답변 종결 후 의뢰인에게 실무상 유의사항을 전달할 때, 상담 결과 상태에 따라 UI를 명확히 분리하여 모순된 인상을 방지한다:

1. **상담 성공 종결(`item.status === 'SUCCESS'`) 시**:
   - `warnings` 목록에서 과거 중간 단계의 `INSUFFICIENT` 관련 시스템 에러 문구를 자동 필터링.
   - 레이블을 `🛡️ 실무 권고사항 및 소송상 유의사항:`으로 표시하고 차분한 소프트 서피스(`var(--surface-alt)`) 스타일로 렌더링하여 실무 가이드로서의 신뢰성을 극대화.
2. **검증 차단 종결(`item.status === 'INSUFFICIENT'`) 시**:
   - `⚠️ 주의 및 검증 안내:` 레이블과 경고 배경색(`var(--warning-bg)`)으로 명확히 경고를 표기.

---

## 4. UI/UX 및 에러 처리 검증
- **로딩 스피너**: 승인 또는 거절 버튼 클릭 즉시 버튼이 `disabled` 처리되고 상단 진행 인디케이터가 활성화되어 중복 입력을 방지.
- **중복 승인 차단**: 이미 승인 또는 거절 처리된 요청에 대해 중복 호출 시 HTTP 400 (`이미 처리된 승인 요청입니다.`) 반환.
- **화면 실시간 갱신**: 폴링 완료 시 `loadHistory()`를 호출하여 좌측 사이드바 및 상담 목록이 즉시 동기화됨.
- **상태 배지**: 이력 목록에서 '답변 완료(초록)', '처리 중(노랑)', '승인 대기(파랑)', '오류(빨강)'로 시각적 상태가 명확히 구분됨.
- **플레인 텍스트 출력**: 마크다운 원시 기호(`#`, `**`)가 배제되어 UI 화면에 깨짐 없이 깔끔한 법률 답변 레이아웃이 유지됨.

