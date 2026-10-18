# P0 핵심 결함 4건의 재현 결과 및 근본 원인 분석 보고서

**문서 번호:** `docs/code-audit/p0-followup/01_ROOT_CAUSE.md`  
**작성 일자:** 2026-10-18  
**대상 저장소:** `yjjungyo/ai-legal-helper`  
**기준 브랜치/커밋:** `main` (`aa792416827c509a7292fd70d0311e6fba0ebefa`)

---

## 1. 개요

본 문서는 `AI Legal Helper — P0 핵심 결함 4건 수정 개발지시서`에 명시된 4대 핵심 결함의 재현 결과 및 코드베이스 수준의 근본 원인을 상술한다.

| 결함 ID | 결함 명칭 | 위험도 | 영향 범위 |
|---|---|---|---|
| **P0-01** | 공식 법령 검색 이후 Verifier의 부적절한 PASS 판정 가능성 | Critical | 법률검증 신뢰성 상실, 잘못된 법률 자문 위험 |
| **P0-02** | `WITHHELD` 상태의 미검증 답변이 고객에게 노출되는 문제 | Critical | 미검증 법률 의견서 유출, 고객 혼란 유발 |
| **P0-03** | 검색된 출처 전체와 실제 검증된 출처가 혼동되는 문제 | Critical | 답변에 미인용된 무관 법령이 검증 출처로 둔갑 |
| **P0-04** | HILT 재분석 프롬프트의 전세보증금 사건 하드코딩 | High | 대여금·노동 등 타 분야 사건에 임대차 조치 혼입 |

---

## 2. 결함별 근본 원인 및 재현 결과

### 2.1 P0-01: Verifier의 강제 PASS 및 법률 검증 누락

#### [근본 원인 분석]
- **파일 위치:** `backend/src/ai_legal_helper/agents/verification.py` (`VERIFICATION_PROMPT`)
- **원인 코드:**
  ```text
  6. 공식 법령 원문 연동(OFFICIAL_STATUTE_SEARCH) 결과 반영 시:
     - [검색된 출처 목록]에 retrieval_method가 "OFFICIAL_STATUTE_SEARCH"인 법령 조문이 포함되어 있고,
       초안이 해당 조문 원문과 일치하게 분석되었다면 status는 반드시 "PASS"로 판정하세요.
  ```
- **문제 메커니즘:**
  1. 외부 API(open.law.go.kr)를 통해 공식 법령이 검색되어 초안에 포함되기만 하면, 법률 요건 누락, 법령 적용 시점 오류, 사실관계의 잘못된 확정, 법률 효과의 왜곡, 손해배상 청구 주체의 혼동이 있더라도 Verifier 프롬프트 규칙에 의해 무조건 `PASS`를 강제함.
  2. LLM이 `claims` 목록을 빈 배열(`[]`)로 반환하거나, `grounding_status == "UNSUPPORTED"` 주장이 존재해도 결정론적 사후 판정(Deterministic Policy Enforcement)이 부재하여 그대로 PASS로 확정될 위험이 존재함.

#### [재현 테스트 결과]
- `tests/unit/test_p0_followup_defects.py::test_v01_v02_prompt_does_not_contain_forced_official_statute_pass` -> **FAILED** (강제 PASS 규칙 존재 확인)
- `tests/unit/test_p0_followup_defects.py::test_v05_rejects_pass_when_claims_list_is_empty` -> **FAILED** (claims 비어있음에도 PASS 허용 확인)

---

### 2.2 P0-02: `WITHHELD` 상태의 미검증 답변 고객 노출

#### [근본 원인 분석]
- **파일 위치:**
  - `backend/src/ai_legal_helper/workflows/legal_workflow.py` (`insufficient_node`)
  - `backend/src/ai_legal_helper/api/routes/consultation.py` (`answer_status` 정책)
  - `frontend/src/components/ChatSection.tsx` (단순 `item.answer ?` 렌더링)
- **원인 코드:**
  ```python
  # legal_workflow.py (insufficient_node)
  parts.append("========================================\n")
  parts.append("[참고: 미검증 참고 초안 (법적 효력 없음)]")
  parts.append("경고: 아래 내용은 검색된 제한적 자료를 바탕으로 작성된 미검증 초안으로...")
  parts.append(clean_markdown_formatting(sanitized_draft))
  final = clean_markdown_formatting("\n".join(parts))
  return {"final_answer": final, ...}
  ```
- **문제 메커니즘:**
  1. `insufficient_node`는 법률 근거 부족(`INSUFFICIENT`)으로 판정되었음에도, 경고문 아래에 미검증 초안 원문(`sanitized_draft`)을 통째로 붙여 `final_answer`를 생성함.
  2. 백엔드 API는 `answer_status = "WITHHELD"` 상태임에도 `resp.answer = final` 형태로 미검증 법률 문장을 클라이언트에 그대로 전송함.
  3. 프론트엔드 `ChatSection.tsx`는 `item.answer`가 문자열로 존재하기만 하면 이를 무조건 고객 화면에 렌더링하여, 사용자가 미검증 법률 의견을 검증된 자문으로 오인할 위험이 치명적이었음.

#### [재현 테스트 결과]
- `tests/unit/test_p0_followup_defects.py::test_a02_a05_insufficient_node_does_not_contain_unverified_draft` -> **FAILED** (미검증 초안 노출 확인)

---

### 2.3 P0-03: 검색 출처와 검증 출처 혼동

#### [근본 원인 분석]
- **파일 위치:** `backend/src/ai_legal_helper/agents/verification.py` (`audit_citations_and_claims`)
- **원인 코드:**
  ```python
  verified_sources: List[Dict[str, Any]] = []
  for src in normalized_registry:
      sid = str(src.get("source_id") or "")
      # 거부된 출처만 아니면 검색된 모든 출처를 verified_sources에 추가!
      if sid in rejected_citation_ids ...:
          continue
      verified_sources.append(src)
  ```
- **문제 메커니즘:**
  1. RAG 및 공식 법령 검색으로 수집된 출처가 10건, 20건 있을 때, 최종 답변에서 단 1건의 조문만 인용하더라도 답변에 인용되지 않은 나머지 9~19건의 법령까지 전부 `verified_sources`에 담김.
  2. 고객 화면의 "검증된 출처" 목록에 답변 본문과 전혀 관련 없는 법조문들이 표시되어 출처 추적 신뢰성을 훼손함.

#### [재현 테스트 결과]
- `tests/unit/test_p0_followup_defects.py::test_s01_s03_audit_separates_retrieved_and_cited_sources` -> **FAILED** (10건 중 1건 인용 시 cited_sources가 1개가 아닌 10개 전체 반환됨)

---

### 2.4 P0-04: HILT 재분석 프롬프트의 전세보증금 도메인 하드코딩

#### [근본 원인 분석]
- **파일 위치:** `backend/src/ai_legal_helper/workflows/legal_workflow.py` (`re_analyze_node`)
- **원인 코드:**
  ```text
  [1. 핵심 결론 (한눈에 보기)]
  - 의뢰인이 질문한 핵심 사항(보증금 반환 가능성, 상대방의 사전 인식 인정 여부, 추가 손해배상 청구 가능 여부)...
  [2. 지금 당장 취해야 할 행동 가이드 (Action Plan)]
  - 1단계(임대인 본인에게 내용증명 발송...), 3단계(임차권등기명령 신청 및 법적 절차)...
  [3. 쟁점별 심층 법률 분석]
  - 묵시적 갱신과 해지의 효력, 배우자 통지의 도달 인정 가능성...
  ```
- **문제 메커니즘:**
  1. HILT 공통 재분석 노드(`re_analyze_node`) 프롬프트에 임대차·보증금·임차권등기명령 관련 지침이 고정 하드코딩되어 있음.
  2. 대여금 반환 분쟁(SC-003)이나 근로기준법상 퇴직금·임금 체불 분쟁에서 HILT 공식 법령 검색을 수행할 경우, 임차권등기명령 신청, 임대인 상대 내용증명 등 도메인에 전혀 맞지 않는 법률 자문이 혼입됨.

#### [재현 테스트 결과]
- `tests/unit/test_p0_followup_defects.py::test_h02_h04_re_analyze_prompt_neutral_for_loan_dispute` -> **FAILED** (대여금 사건 재분석 프롬프트에 '임차권등기명령' 및 '임대인' 하드코딩 노출 확인)

