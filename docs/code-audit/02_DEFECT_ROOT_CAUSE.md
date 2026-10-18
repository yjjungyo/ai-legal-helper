# AI Legal Helper — 02. 결함별 원인 분석 및 영향도 평가

## 1. 개요
본 문서는 Phase A 감사에서 식별 및 재현된 P0 결함 4건의 기술적 원인과 시스템적 영향도를 상세히 분석한다.

---

## 2. 결함별 심층 원인 및 영향

### 2.1 P0-01: Verification Agent Fail-open 취약점
- **심층 원인**:
  - `verification.py` 내 `run_verification()` 함수에서 LLM 호출(`chain.invoke`) 또는 JSON 파싱 중 예외가 발생하면 `except Exception as e:` 블록으로 진입함.
  - 이 블록에서 결정론적 인용 오류(`has_citation_defect`)가 없는 경우 `fallback_status`를 `"PASS"`로 하드코딩하고 `recommended_action: "FINALIZE"`를 반환함.
- **시스템 영향**:
  - 외부 LLM API 지연, 일시적 네트워크 장애, 할루시네이션으로 인한 파싱 불능 등 검증 시스템이 불능 상태가 되었을 때 미검증 법률 조언이 "검증 완료(PASS)"로 포장되어 의뢰인에게 전달됨.
  - 법적 신뢰성이 완전히 훼손되는 중대한 안전 결함.

### 2.2 P0-02: HILT 이후 검증 우회 및 비법령 사유 오분기
- **심층 원인**:
  - `legal_workflow.py`의 `verification_condition()`에서 `hilt_executed` 플래그가 참이면 Verifier의 판정 결과(`status`, `reason_code`)를 확인하지 않고 무조건 `"finalize"`를 반환함.
  - HILT 진입 조건에서 `or (status in ("INSUFFICIENT", "REVISE") and reason_code != "NONE")`로 인해 법령 부족이 아닌 사실관계 증거 부족(`CASE_EVIDENCE_MISSING`) 사유도 HILT 법령 검색으로 잘못 라우팅됨.
- **시스템 영향**:
  - 법령을 수집하여 재분석했음에도 불구하고 법리적 모순이나 추가 결함이 발견된 미완성 답변이 최종 확정됨.
  - 증거가 부족한 사건에서 사용자에게 엉뚱한 법령 검색 승인 모달창이 표시되는 사용자 경험 결함.

### 2.3 P0-03: LangGraph Checkpointer 휘발성(MemorySaver) 결함
- **심층 원인**:
  - `legal_workflow.py`의 `get_checkpointer()`가 프로세스 메모리 기반 `MemorySaver()`를 반환함.
  - 비동기 `ainvoke` 및 Windows 환경 호환성 문제로 인해 임시로 인메모리 방식이 유지됨.
- **시스템 영향**:
  - 사용자가 HILT 승인 대기 상태에서 브라우저를 닫거나 백엔드 서버가 재배포/재시작되면 그래프의 실행 상태와 대기 스레드가 영구 소실되어 상담이 재개되지 못함.

### 2.4 P0-04: 공식 법령 검색 통신 보안 및 임의 법령 채택 결함
- **심층 원인**:
  - `official_statute_search.py`에서 `http://www.law.go.kr` 호출로 전송 구간 암호화가 미적용됨.
  - `search_root.findall(".//law")` 검색 결과에서 완전 일치와 정제 일치 탐색이 실패했을 때 `search_root.find(".//law")`로 검색된 첫 번째 법령을 임의 선택함.
- **시스템 영향**:
  - 오타나 존재하지 않는 법률명 검색 시 엉뚱한 법률(예: 전혀 무관한 시행령/조례)의 조문이 채택되어 답변에 허위 반영될 위험.
  - 평문 HTTP 사용으로 인한 전송 데이터 감청 위험.

---

## 3. 위험도 및 수정 우선순위

| 결함 ID | 결함 명칭 | 위험도 | 영향 범위 | 수정 복잡도 |
|:---:|:---:|:---:|:---:|:---:|
| **P0-01** | Verification Agent Fail-open | **CRITICAL** | 검증 안전성, 법적 책임 | 낮음 |
| **P0-02** | HILT 이후 검증 우회 | **CRITICAL** | 워크플로 정합성 | 낮음 |
| **P0-03** | Checkpointer 비영속성 | **HIGH** | 서비스 지속성, 내결함성 | 중간 |
| **P0-04** | 법령 검색 보안 및 임의선택 | **HIGH** | 데이터 무결성, 보안 | 낮음 |

