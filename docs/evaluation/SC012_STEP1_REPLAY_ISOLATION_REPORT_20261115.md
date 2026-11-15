# SC-012 최종 개선 1단계 개발·코드리뷰·테스트 보고서

- 작성일: 2026-11-15
- 기준 main: `f8f497477dedf605dff5e13d3b16eb4a9f7dd6f0`
- 작업 브랜치: `fix/sc012-step1-replay-isolation-20261115`
- 상위 설계서: `docs/development/SC012_RETRIEVAL_ROOT_CAUSE_REMEDIATION_DESIGN_20261115.md`
- 단계: **1/6 완료 — 사용자 DB+LLM 수동 테스트 전. main 병합 보류**
- 법률 상담 로직 자체의 품질 향상과 SC-012 정답 통과는 아직 주장할 수 없다.

## 1. 원인 및 작업 범위

SC-012 2차 상담의 실패 Trace에는 3차 증거(E05~E07)가 포함되었다. 현재의 `run_complex_10cases_e2ev6_hitl_auto.py`는 일반 10사건 전체 실행 시 매 사건마다 새 Case ID를 생성하므로 전체 실행기 자체가 기존 사건을 재사용한다는 주장은 소스와 부합하지 않는다. 그러나 과거 DB 사건 ID로 2차 질문만 재실행하면 3차 증거와 파생 사실이 남아 있는 상태에서 상담이 이루어질 수 있다.

같은 Trace에서 내보내기용 상담 응답(228자)과 finalize_node 출력(263자)이 달랐다. 후처리 변환 또는 계층 차이일 수 있어 어느 한쪽으로 원문을 덮어쓰면 안 된다.

### 이번 변경에서 의도적으로 하지 않은 것
- Issue Planner·검색기·법령·판례·검증기·법률 답변 생성 수정 없음.
- 기존 완료 사건에 임의 증거를 삭제하거나 데이터베이스를 초기화하지 않음.
- 기존 E2E V6 체크포인트, KPI Excel, 보고서, Trace Catalog 수정 없음.
- 2~6단계는 설계만 문서화. 사용자 수동 테스트 전 개발 진척도를 과장하지 않음.

## 2. 변경 파일과 구현 사유

| 파일 | 변경 | 이유 및 영향 |
| --- | --- | --- |
| `scripts/evaluation/e2e_turn_audit.py` (신규) | 순차 단계별 DB 증거 파일명/원본 SHA256의 일치, 누락·미래·중복 증거 차단; API 답변과 finalize 노드 답변 SHA256 별도 기록 | 순수 표준 라이브러리로 재현성·테스트 용이성 유지 |
| `scripts/evaluation/run_complex_10cases_e2ev6_hitl_auto.py` (수정) | `stop_after_turn: Optional[int]=None` 추가; 부분 턴만 실행; 상담 직전 evidence_snapshot; Trace에 증거 감사 결과 및 답변 provenance 추가; 재현 실행이면 대응계획/문서/KPI 전에 즉시 반환 | 기존 전체 V6 동작의 기본값을 유지하며 공통 비즈니스 실행 경로 재사용 |
| `scripts/evaluation/replay_case_turn_v6.py` (신규) | `--case`, `--through-turn`; 신규 Case/Conversation; 1~N턴 실행; 별도 재현 결과 JSON 출력 | 기존 사건 ID 사용 금지, 이전 대화 맥락 보존, 전체 KPI 오염 방지 |
| `backend/tests/unit/test_e2e_turn_audit.py` (신규) | 시점별 증거, 누락/중복/변조, Trace 동일·불일치·누락 테스트 총 15개 | 외부 LLM/API/DB 없이 감사 계약 검증 |
| `docs/development/SC012_RETRIEVAL_ROOT_CAUSE_REMEDIATION_DESIGN_20261115.md` (신규) | 전체 6단계 설계 원칙 및 순서 | Gemini/ChatGPT 공통 인계 기준 |
| 본 보고서 (신규) | 변경 이유·코드리뷰·테스트·수동 검증 지침 기록 | 평가 및 후속 개발 추적성 |

## 3. 핵심 불변식 및 비정상 처리

1. **fresh-case**: 리플레이는 이전 DB 사건 ID를 받지 않는다. `run_case_evaluation()`이 언제나 `Case()`를 새로 생성한다.
2. **multi-turn**: N차만 실행하지 않는다. `case_meta["turns"][:N]`을 1차부터 순서대로 실행하여 대화/증거 누적을 보존한다.
3. **pre-consult evidence contract**: N차 상담 직전 해당 신규 Case에 등록된 EvidenceDocument의 이름 *중복 개수 포함*과 `1차~N차` 디렉터리 파일명 및 SHA256을 정확히 비교한다. 차이가 나면 `ValueError`로 즉시 중단한다.
4. **no retroactive future docs**: 3차 디렉터리의 파일이 존재해도 2차 리플레이에서는 적재하지 않는다. DB에 미래 증거가 있다면 검색 전에 차단한다.
5. **answer provenance**: `consultation_context.answer`는 사용자 반환문 그대로, `langfuse_trace.observations[name=finalize_node].output.answer`는 워크플로우 출력 그대로 둔다. 차이를 `MATCH/DIFFERENT/UNAVAILABLE`로 표시한다. 파편화된 Trace를 MATCH로 간주하지 않는다.
6. **report isolation**: 재현 종료점은 기존 전체 V6의 대응계획/법률문서/체크포인트/KPI 생성보다 앞이다. 재현 결과 JSON만 `artifacts/langfuse_review_v6/isolated_replays`에 별도 작성한다. 개별 Trace JSON은 기존 보관 폴더에 이름/Trace ID가 다른 새 파일로 생성한다.
7. **no false quality PASS**: `scope_status=MATCHED`는 증거 집합의 범위 일치를 뜻하며 답변 정확도 PASS가 아니다.

## 4. 코드 리뷰 메모

- **원문 근거**: 현재 `case_briefing.py`가 동일 case_id의 모든 EvidenceDocument/Claim/Fact를 로드한다. 기존 완주 사건 재사용 시 미래 데이터가 함께 로드되는 것은 예상된 동작이다. 상담 검색기만 부분 필터링해도 Fact가 이미 누적되어 있기 때문에 격리 재현은 독립 사건 생성으로 처리했다.
- **계층 차이 확인**: 기존 export 기능은 원래 답변과 Langfuse Trace를 병행 저장했다. 이번에는 누락/불일치를 자동 판별하는 `answer_provenance`를 추가했을 뿐 원본 출력의 실제 형식/내용은 바꾸지 않았다.
- **정적 코드 리뷰 중 수정**: `Counter(expected)`는 기대 파일명 딕셔너리의 해시 값이 카운트로 해석될 수 있으므로 `Counter(expected.keys())`로 수정했다. 이후 테스트가 통과했다.
- **파급 영향**: 새 전용 CLI + optional 인자. 기존 `main()`의 호출 인자는 변하지 않으므로 기본 전체 E2E의 3차까지 실행, 문서 생성, KPI 업데이트 경로는 보존된다. 다만 기존 full-run 전체 DB+LLM 회귀는 이번 환경에서 실행하지 못했으므로 사용자 테스트를 통해 재확인해야 한다.
- **보안/프라이버시**: 프로비넌스 요약에는 답변 원문을 중복 기록하지 않고 길이/해시만 추가. 기존 Trace에는 본래 사용자가 확인해야 할 원문 데이터가 남으므로 운영 공유 시 별도 비식별화가 필요하다.

## 5. 자동 검증 결과

- 검증 파일: `backend/tests/unit/test_e2e_turn_audit.py`
- 실행 명령: `PYTHONPATH=<저장소 루트> python -m pytest -q backend/tests/unit/test_e2e_turn_audit.py`
- 결과: **15 passed (0.09s, 이 실행 환경의 독립 테스트)**.
- Git blob SHA 대조: 테스트에 사용한 `e2e_turn_audit.py` (`0d9eae3036219ceb559758e4798eb38931a84d25`), pytest 파일 (`3513f8fcb3975a99d026d45fe00f7919701c5406`) 모두 GitHub 브랜치 실제 파일과 일치함을 확인.
- 검증 범위: 순수 감사 함수를 외부 DB/LLM 없이 실제 실행. 신규 runner 전체 Python import, DB ingestion/approval, Langfuse 실서버 fetch, 상담 E2E와 실제 프런트 응답은 **미실행**.
- 테스트하지 않은 것을 PASS로 기록하지 않는다.

## 6. 사용자 직접 검증 절차

### 6.1 준비
1. 해당 브랜치를 checkout/pull: `fix/sc012-step1-replay-isolation-20261115`.
2. 현재 사용 중인 backend DB/LLM/ChromaDB/Langfuse 및 `backend/.env` 준비.
3. `docs/testset/SC-012_임대인사망_공동상속인_불가분채무_보증금청구/증거/1차`, `2차` 증거 파일 존재 확인(실제 테스트셋 폴더명은 `TEST_CASES` 메타데이터를 기준으로 한다).
4. 저장소 루트에서 실행. 기존 종합 E2E의 checkpoint/KPI가 변하지 않았는지 필요 시 실행 전후 비교.

### 6.2 단위 테스트
```powershell
python -m pytest -q backend/tests/unit/test_e2e_turn_audit.py
```

### 6.3 신규 사건에서 SC-012 2차까지만 순차 재현
```powershell
python scripts/evaluation/replay_case_turn_v6.py --case SC-012 --through-turn 2
```

**기대 결과**
- 신규 DB 사건 ID가 출력되고, 과거 `acdb832e-449e-4858-9346-650e9097ed10`과 같지 않다.
- 1차 `document_count=2`, 2차 `document_count=4`. 2차 Trace의 `evidence_snapshot.expected_filenames`에는 E01~E04만 나온다.
- 1차·2차의 Trace ID가 각각 생성된다. 출력 JSON은 `artifacts/langfuse_review_v6/isolated_replays/`에 보존된다.
- `answer_provenance`이 MATCH/DIFFERENT/UNAVAILABLE로 기록된다. DIFFERENT라도 자동으로 답변을 교체하지 않는다.
- 3차 증거를 등록하지 않는다. 대응계획/법률문서 및 종합 V6 KPI는 갱신하지 않는다.

### 6.4 장애 시 확인
- `EVIDENCE_STAGE_MISMATCH`: DB와 단계 파일의 이름 또는 개수가 다름. LLM 이전에 차단된 것으로 정상 안전 동작.
- `EVIDENCE_HASH_MISMATCH`: 원본 증거 파일과 DB 저장 해시 불일치. 입력 데이터 복구 필요.
- `UNAVAILABLE` provenance: Langfuse 관측치 fetch 누락/지연 여부 점검; 실제 답변이 일치했다는 뜻 아님.
- 증거 범위가 맞는데도 Trace 상담 프롬프트에 3차 증거가 보이는 경우: 다른 경로(과거 메모리, RAG 인덱스 등)의 case_id 격리를 추가 조사하고 2단계 개발 이전에 이 원인을 먼저 해소.

## 7. 다음 단계 진입 기준

**사용자의 실제 SC-012 1차→2차 재테스트 결과와 Trace를 검토하기 전에는 2~6단계를 구현하지 않는다.**

1단계 테스트에서 확인할 것은 '법률 답변이 정확해졌는가'가 아니라 '오염되지 않은 증거와 이전 대화로 공정하게 재현했는가'이다. 결과가 안전하게 격리되면 이후 2단계 Issue Planner 및 3단계 판례 검색, 4단계 포섭 개선에 착수한다.
