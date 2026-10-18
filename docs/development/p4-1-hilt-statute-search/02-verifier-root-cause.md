# P4.1 Verifier-Guided HILT 법령 검색 — 02. Verifier 근거 부족 원인 분류 구현

## 1. 개요
기존 Verifier는 답변 검증 결과로 단순히 `PASS`, `REVISE`, `INSUFFICIENT`라는 3단계 상태값만 반환하여, 시스템이 후속 조치를 지능적으로 분기할 수 없었다.
P4.1에서는 Verifier가 검증 실패 시 **원인(Root Cause)**과 **필요한 후보 법령(Candidate Laws)**, **구체적 법률 쟁점(Missing Legal Issues)**, **권장 행동(Recommended Action)**을 구조화하여 출력하도록 개선하였다.

---

## 2. 근거 부족 원인 분류 체계 (Reason Code)

Verifier 프롬프트와 Pydantic 모델에 정의된 표준 `reason_code`는 다음과 같다:

| 사유 코드 (`reason_code`) | 정의 및 발생 상황 | 권장 후속 조치 (`recommended_action`) |
| :--- | :--- | :--- |
| `LEGAL_SOURCE_MISSING` | 특별법 등 필요한 필수 법령이 검색 결과에 완전히 누락됨 (예: 주택임대차보호법 부재) | `REQUEST_STATUTE_SEARCH_APPROVAL` (HILT 승인 요청) |
| `LEGAL_SOURCE_INSUFFICIENT`| 일반 법률(민법 등)은 검색되었으나 질문의 핵심 특별법 쟁점을 해결하기에 불충분함 | `REQUEST_STATUTE_SEARCH_APPROVAL` (HILT 승인 요청) |
| `CASE_EVIDENCE_MISSING` | 법령은 충분하나 의뢰인의 사건 사실관계 또는 증거(계약서, 영수증 등)가 부족함 | `REQUEST_EVIDENCE` (증거 추가 요청) |
| `EVIDENCE_CONFLICT` | 제출된 증거 간 또는 사실관계 간 명백한 상충/모순이 감지됨 | `REQUEST_EVIDENCE` (사실관계 소명 요청) |
| `ANSWER_REVISION_REQUIRED` | 근거 문서는 충분하나 답변 문장의 논리 비약, 조문 번호 오기, 허위 인용 등 작성 오류 | `REVISE_DRAFT` (초안 답변 재작성) |
| `CITATION_INVALID` | 검색된 Source Registry에 없는 파일명을 허위 인용하거나 조문 내용 불일치 | `REVISE_DRAFT` (인용 정화 및 수정) |
| `NONE` | 모든 필수 쟁점 및 출처가 완전히 검증됨 (PASS) | `FINALIZE` (답변 확정) |

---

## 3. Pydantic 스키마 구현 (`VerificationOutput`)

`backend/src/ai_legal_helper/agents/verification.py` 파일의 확장된 스키마는 다음과 같다:

```python
class VerificationOutput(BaseModel):
    """법률검증 Agent 에이전트의 종합 검증 출력 스키마."""
    status: str = Field(description="PASS, REVISE, 또는 INSUFFICIENT")
    reason_code: Optional[str] = Field(
        default="NONE",
        description="LEGAL_SOURCE_MISSING, LEGAL_SOURCE_INSUFFICIENT, CASE_EVIDENCE_MISSING, EVIDENCE_CONFLICT, ANSWER_REVISION_REQUIRED, CITATION_INVALID, 또는 NONE"
    )
    missing_legal_issues: List[str] = Field(
        default_factory=list, 
        description="법령 검색이 필요한 구체적 법률 쟁점 목록 (예: ['묵시적 갱신 후 해지통보 효력'])"
    )
    candidate_laws: List[str] = Field(
        default_factory=list, 
        description="부족한 쟁점을 규율하는 후보 법령명 목록 (예: ['주택임대차보호법'])"
    )
    recommended_action: Optional[str] = Field(
        default="FINALIZE",
        description="REQUEST_STATUTE_SEARCH_APPROVAL, REQUEST_EVIDENCE, REVISE_DRAFT, 또는 FINALIZE"
    )
    explanation: Optional[str] = Field(
        default="", 
        description="검증 결과 및 권장 후속 조치 사유 설명"
    )
    claims: List[ClaimVerification] = Field(default_factory=list, description="주요 법률 주장 목록 및 검증 결과")
    missing_issues: List[str] = Field(default_factory=list, description="질문의 핵심 쟁점 중 누락된 항목")
    contradictions: List[str] = Field(default_factory=list, description="답변 내부의 모순된 논리")
    revision_instructions: List[str] = Field(default_factory=list, description="답변 수정을 위한 지침")
    warnings: List[str] = Field(default_factory=list, description="사용자에게 보여줄 경고 메시지 목록")
    citation_audit: Dict[str, Any] = Field(default_factory=dict, description="결정론적 인용 검증 메트릭")
```

---

## 4. 프롬프트 엔지니어링 개선 (`VERIFICATION_PROMPT`)

Verifier LLM이 법령 부족을 정확히 포착하도록 프롬프트 지침 4조를 신설하였다:

```
[근거 부족 원인 분석 및 후속 조치 지침]
- 만약 질문의 핵심 쟁점을 해결하기 위해 특정 특별법(예: 주택임대차보호법, 상가건물임대차보호법, 근로기준법 등)이 반드시 필요한데도, 검색된 출처 목록에 해당 법률이 전혀 없거나 일반 민법/형법 조문만 검색되어 사안을 해결할 수 없는 경우:
  * status: "INSUFFICIENT"
  * reason_code: "LEGAL_SOURCE_MISSING" (완전 누락) 또는 "LEGAL_SOURCE_INSUFFICIENT" (부분 누락)
  * missing_legal_issues: ["구체적 법률 쟁점 명시"]
  * candidate_laws: ["필요한 실제 대한민국 법령명 (예: 주택임대차보호법)"]
  * recommended_action: "REQUEST_STATUTE_SEARCH_APPROVAL"
---

## 5. Langfuse Observability 기록

검증 수행 후 `run_verification` 함수는 Langfuse Span 메타데이터에 다음과 같이 원인 및 후보 법령을 실시간으로 보존한다:

```python
update_span(get_current_span_id(), {
    "claims_count": len(result.claims),
    "supported_count": len(result.claims) - unsupported_total,
    "warnings_count": len(result.warnings),
    "is_fail": result.status == "INSUFFICIENT",
    "is_revise": result.status == "REVISE",
    "reason_code": result.reason_code,
    "candidate_laws": result.candidate_laws,
    "recommended_action": result.recommended_action,
    "missing_legal_issues": result.missing_legal_issues,
})
```

이로써 운영자는 Langfuse 대시보드에서 어떤 법률이 자주 누락되는지, 어떤 쟁점에서 HILT가 승인 요청되는지 정량적으로 모니터링할 수 있다.

---

## 6. 실무상 유의사항(Legal Caution)과 근거 결함의 구분 원칙

### 6.1 문제 정의
의뢰인에게 실무상 입증 요령(예: 통화내역/녹취록 확보 필요, 배우자 대리권 확인 권고, 대출이자/위약금 영수증 지참)을 조언하는 것은 전문 법률가의 필수적이고 정상적인 법률 자문(Legal Caution)이다.
초기 설계에서는 Verifier가 이를 "사건 증거 부족(`CASE_EVIDENCE_MISSING`)"이나 "근거 부족(`INSUFFICIENT`)"으로 오인하여, 답변이 법령에 맞게 잘 작성되었음에도 재검토 실패 및 강제 폐기로 이어지는 문제가 발생하였다.

### 6.2 보정된 검증 기준
1. **실무상 유의사항 안내의 허용**:
   - 초안에서 "입증 자료 준비가 필요하다", "상대방의 항변이 있을 수 있으니 주의하라"고 안내하는 것은 정상적인 `PASS` 사유이며, 이를 이유로 `REVISE`나 `INSUFFICIENT`로 강등하지 않는다.
   - 단, 미입증 사실이나 법적 효력을 기정사실로 단정·확정 왜곡하는 경우에만 `REVISE`한다.
2. **공식 법령 원문 연동(`OFFICIAL_STATUTE_SEARCH`) 조문 반영 시**:
   - 출처에 공식 법령 검색 결과가 포함되어 있고 초안이 해당 조문 원문과 일치하면 `status: PASS`로 확정한다.
3. **`warnings` 필드의 역할 분리**:
   - 치명적 검증 실패 경고와 구분하여, 의뢰인이 분쟁 해결 시 챙겨야 할 "실무 권고사항 및 유의사항" 목록으로 관리한다.

### 6.3 인용 표기 괄호 중복(`((...))`) 및 정규식 정제
1. **문제 현상**:
   - LLM이 조문 인용 시 괄호 내부에 인용을 작성하면서 `((파일명.pdf, p.1))` 형태로 이중 괄호가 형성됨.
   - 정규식 `CITATION_PATTERN`이 여는 괄호 `(`를 파일명으로 포함시켜 `clean_file`이 `(파일명.pdf`로 오인식되어 미검증 출처(`NOT_IN_SOURCE_REGISTRY`)로 오판정됨.
2. **개선 대책**:
   - `CITATION_PATTERN`을 `\(+\s*([^\n,]+?\.(?:pdf|docx|txt))\s*,\s*p\.?\s*([0-9\-~]+|\?)\s*\)+`로 개편하여 중복 괄호를 완전 흡수.
   - `raw_file` 추출 시 `.strip("()[]{}\"' \t")`로 외곽 기호를 전처리하여 Source Registry 파일명과 100% 매칭 보장.
   - `sanitize_unverified_citations`에서 `[근거 미확인])` 등 잔여 괄호가 남지 않도록 정규식 정화 강화.

### 6.4 재분석 서두 안내문의 동적 조문 바인딩 (하드코딩 배제)
1. **문제 현상**:
   - 재분석 프롬프트 템플릿에 "손해배상 청구 요건을 재분석했다"는 문구가 고정되어 있어, 본문에서 "공식 조문에 채무불이행 규정이 없다"고 설명할 때 Verifier가 이를 내부 모순(`contradictions`)으로 지적함.
2. **개선 대책 (일반화 및 하드코딩 배제)**:
   - 특정 도메인(임대차, 손해배상 등) 키워드를 프롬프트 템플릿에서 전면 배제.
   - 실제 수집된 조문 번호 목록(`retrieved_articles_summary`)을 동적으로 포맷팅하여 "확보된 공식 법령 조문 원문({retrieved_articles_summary})을 바탕으로 질문의 핵심 법률 쟁점 및 당사자의 법적 권리·의무 관계를 재분석"하도록 일반화.

### 6.5 HILT 완료 후 finalize 전이 보장 정책
- 사용자 승인 및 법제처 공식 원문 검색, 재분석이 성공적으로 수행된 경우 경미한 서술 차이로 `insufficient_node`에 진입하지 않고 `finalize`로 라우팅하여 검증된 법률 조언과 정제된 출처를 사용자에게 안전하게 확정 전달한다.

---

## 7. 결론
이로써 Verifier는 단순한 텍스트 매칭을 넘어, 법률 자문으로서의 권고사항과 실제 법리/출처 결함을 명확히 구분하고, 동적 바인딩과 견고한 정규식을 통해 오탐지 없는 신뢰도 높은 판정을 내리게 되었다.


