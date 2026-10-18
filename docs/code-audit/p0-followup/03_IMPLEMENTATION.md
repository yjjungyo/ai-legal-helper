# P0 핵심 결함 4건 상세 구현 내역서

**문서 번호:** `docs/code-audit/p0-followup/03_IMPLEMENTATION.md`  
**작성 일자:** 2026-10-18  
**대상 저장소:** `yjjungyo/ai-legal-helper`

---

## 1. 수정 파일 및 모듈 요약

| 파일 경로 | 수정 목적 | 결함 ID |
|---|---|---|
| `backend/src/ai_legal_helper/agents/verification.py` | 강제 PASS 제거, claim_type 도입, 결정론적 사후 판정 강화, cited_sources 분리 | P0-01, P0-03 |
| `backend/src/ai_legal_helper/workflows/legal_workflow.py` | insufficient_node 미검증 초안 차단, finalize_node 출처 동기화, re_analyze_node 도메인 중립화 | P0-02, P0-03, P0-04 |
| `backend/src/ai_legal_helper/api/routes/consultation.py` | answer_status 3단계 상태 및 레거시 호환 보정, HILT 재개 시 임시 문구 클리어 | P0-02 |
| `frontend/src/components/ChatSection.tsx` | DELIVERED/CAUTIONARY/WITHHELD 상태 기반 명시적 렌더링 및 진행 상태 시각화 | P0-02 |
| `frontend/src/hooks/useConsultation.ts` | HILT 승인 시 낙관적 상태 전이(IN_PROGRESS) 및 폴링 동기화 | P0-02 |
| `backend/tests/unit/test_p0_followup_defects.py` | P0 핵심 결함 4건에 대한 재현 및 방어 단위 테스트 14종 신규 구현 | 전 체 |

---

## 2. 파일별 핵심 변경 코드

### 2.1 `verification.py`
1. **`ClaimVerification` 스키마 확장:**
   ```python
   class ClaimVerification(BaseModel):
       claim: str = Field(description="검증할 법률 주장")
       claim_type: Optional[str] = Field(
           default="LEGAL_APPLICATION",
           description="주장 유형: LEGAL_RULE (법률 규범/조문), CASE_FACT (사건 사실), LEGAL_APPLICATION (법률 적용 판단), RECOMMENDATION (후속 행동 제안)"
       )
       source_ids: List[str] = Field(default_factory=list)
       grounding_status: str = Field(default="UNCERTAIN")
       reason: str = Field(default="")
   ```
2. **`VERIFICATION_PROMPT` 강제 PASS 제거:**
   - 기존의 `OFFICIAL_STATUTE_SEARCH... status는 반드시 'PASS'로 판정하세요` 조항 완전 삭제.
   - "공식 법령 검색 성공만을 이유로 PASS를 반환해서는 절대 안 되며, 법률요건 누락, 법령 적용 시점 오류, 사실관계의 잘못된 확정, 법률 효과의 왜곡이 있다면 반드시 REVISE 또는 INSUFFICIENT로 엄격히 판정하라"는 원칙 명문화.
3. **`audit_citations_and_claims`에서 `cited_sources` 분리:**
   - 검색된 전체 출처(`retrieval_source_ids`)는 100% 보존.
   - `cited_sources`에는 `validated_sources_map.values()` 중 최종 답변에 실제 인용되고 본문 뒷받침이 검증된 출처만 선별 수록. 미인용 출처 완전 배제.
4. **결정론적 사후 판정(Deterministic Policy Enforcement):**
   - `len(result.claims) == 0` -> PASS 금지 (주장 목록 누락 시 REVISE 강등).
   - `UNSUPPORTED` 주장 존재 시 -> PASS 취소 및 REVISE 강등.
   - 결론에 영향을 미치는 `UNCERTAIN` 주장 존재 시 -> PASS 취소 및 REVISE 강등.
   - 허위 인용(`unverified_citations`) 또는 본문 불일치 인용(`unsupported_citations`) 감지 시 -> PASS 취소 및 REVISE 강등.

---

### 2.2 `legal_workflow.py`
1. **`insufficient_node`의 미검증 초안 고객 노출 차단:**
   - 경고문 아래에 미검증 초안(`sanitized_draft`)을 붙이던 로직 완전 삭제.
   - 고객용 `final_answer`에는 판단 유보 안내문, 확인 필요 쟁점/법령, 안전한 후속 행동 가이드(대한법률구조공단 대면 상담 권고 등)만 안전하게 전달.
   - 미검증 초안은 `internal_draft`, 실패 사유는 `verification_failure_reason`으로 분리하여 내부 감사용으로만 보존.
2. **`finalize_node`의 고객 출처 일치 보장:**
   - 최종 정제된 텍스트(`final`)에 대해 `audit_citations_and_claims`를 재실행하여, 실제 최종 답변에 인용된 출처(`cited_sources`)만 `sources`로 전달.
3. **`re_analyze_node`의 도메인 중립화 및 동적 맥락 주입:**
   - 전세보증금, 임차권등기명령, 임대인 상대 내용증명 하드코딩 완전 제거.
   - `categories`, `agent_context_text`, `case_context`, `official_statutes_text`를 주입하여 사건 분야(대여금, 노동 등)에 부합하는 분석 동적 생성.
   - 서두의 시스템 경과 안내 강제를 제거하고, `[1. 핵심 결론]`, `[2. 지금 해야 할 일]`, `[3. 쟁점별 상세 법률 분석]`, `[4. 추가 확인사항 및 유의사항]`의 4단계 표준 구조 적용.

---

### 2.3 `consultation.py`
1. **`answer_status` 3단계 상태 반영:**
   - `verification_status == "PASS"` -> `DELIVERED`
   - `verification_status == "REVISE"` -> `CAUTIONARY`
   - `verification_status in ("INSUFFICIENT", "FAIL", "UNVERIFIED")` -> `WITHHELD`
2. **레거시 DB 호환 함수 `_resolve_legacy_answer_status` 도입:**
   - 과거 DB 레코드에 `answer_status`가 없는 경우에도 검증 상태에 따라 안전하게 보정하여, 미검증 기록이 임의로 `DELIVERED` 처리되는 취약점을 원천 차단.

---

### 2.4 `ChatSection.tsx`
1. **상태 기반 답변 렌더링 도입:**
   - `DELIVERED`: 정밀 검증 통과(PASS) 답변 렌더링.
   - `CAUTIONARY`: 조건부 안내 및 주의 배너(⚠️)가 포함된 답변 렌더링.
   - `WITHHELD`: 미검증 법률 초안 대신 판단 유보 카드(🛡️) 및 보강 안내문 렌더링.
2. **Two-Tier 출처 인스펙터 보호:**
   - `item.answer_status !== 'WITHHELD'`일 때만 출처 토글 바가 표시되도록 조치.

