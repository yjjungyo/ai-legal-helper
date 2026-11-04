# SC-001 상담 모드 분리 개선 및 PoC 대비 평가 계획 (2026-11-04)

## 1. 문제 정의 / 변경 근거
- 제품 원칙: AI Legal Helper는 사건 중심 법률 도우미다. 사건 ID가 있으면 Supervisor가 사건·증거·GraphRAG를 먼저 조회하는 구조를 유지한다.
- 기존 결함: `supervisor_initialize_node`가 등록 문서 존재만으로 `DOCUMENT_GROUNDED`를 확정했다. `intent_analysis_node`는 이 모드에서 순수 인사 외 모든 질문을 `NEW_LEGAL_ANALYSIS`로 강제하여 일반 법률 설명까지 문서 상담으로 처리했다.
- 목표: **자료의 존재 여부와 현재 질문의 증거 활용 필요성을 분리**한다. 일반 법률 설명은 사건 증거를 답변 근거에서 격리하고, 사건 분석은 기존 원문 작성·검증을 유지한다.

## 2. 수정 내역
| 경로 | 변경 | 이유 |
|---|---|---|
| `agents/intent_analyzer.py` | `ConsultationMode(GENERAL_LEGAL, CASE_EVIDENCE)` 및 `IntentDecision.consultation_mode` 추가; 의미 기반 LLM 분류 프롬프트; 기존 응답 누락 시 CASE_EVIDENCE 보수적 폴백 | 분야/의도/근거 범위를 독립적으로 판단 |
| `workflows/legal_workflow.py` | Supervisor에서 answer_mode 선결정 제거; 문서 사건의 Intent 우회 제거; Intent 결과로 DOCUMENT_GROUNDED 지정 | 증거 존재에 의한 모드 오분기 방지 |
| `workflows/legal_workflow.py` | GENERAL_LEGAL의 브리핑·그래프·쟁점·사건 컨텍스트를 해당 턴 분석 상태에서 비움 | 일반 법률 답변으로 사건 증거 혼입 방지 |
| `backend/tests/test_consultation_mode_routing.py` | 3개 단위 회귀 시나리오 추가 | 결정론적 경로 검증 |

기존 Gold v1.2 / 평가 하네스는 변경하지 않는다. SC-001 세 질문의 최신 KPI 배분은 별도 평가표를 기준으로 한다.

## 3. 가상 시뮬레이션
| 입력 | 사건에 등록 문서 | 예상 Intent | 예상 모드 | 예상 답변 경로 |
|---|---|---|---|---|
| SC-001 질문 1: 계약서·입금·전입 자료를 분석 | 있음 | NEW_LEGAL_ANALYSIS | CASE_EVIDENCE | DOCUMENT_GROUNDED → 원문 작성 → 검증 |
| '대항력의 일반적 요건을 설명' | 있음 | NEW_LEGAL_ANALYSIS | GENERAL_LEGAL | 일반 법률 RAG/Agent → 검증 |
| '내 사건에 대항력이 있나' | 있음 | NEW_LEGAL_ANALYSIS | CASE_EVIDENCE | DOCUMENT_GROUNDED → 원문 작성 → 검증 |
| 증거 없는 일반 법률 질문 | 없음 | NEW_LEGAL_ANALYSIS | GENERAL_LEGAL | 일반 법률 RAG/Agent → 검증 |

**주의:** 위는 설계상 예상 경로이지 LLM 실측 결과가 아니다. 현재 환경에서는 회사 LLM, 로컬 PostgreSQL/Neo4j/Chroma를 실행하지 않았다.

## 4. PoC 대비 품질·성능 측정 정의
| 지표 | 측정 방법 | 현 단계 값 |
|---|---|---|
| 모드 분류 정확도 | GENERAL_LEGAL/CASE_EVIDENCE 라벨링된 질문의 정확 일치율, 사건 증거 유무별 층화 | 미측정 |
| 사건 증거 누출률 | GENERAL_LEGAL 답변에서 사건 원문 고유 사실/출처가 근거로 사용된 비율 | 미측정 |
| SC-001 질문 1 필수 사실 회수율 | 계약일·보증금·지급·기간·입주·전입·확정일자 항목의 증거 기반 정확 회수 | 미측정 |
| 미래 증거 혼입률 | 첫 질문에서 아직 등록하지 않은 갱신·해지·가압류·미반환 사실을 단정한 비율 | 미측정 |
| Citation Validity | 최종 인용 파일명이 실제 승인 원문과 일치한 비율 | 미측정 |
| Verification 오판정률 | 검증된 정답을 잘못 차단하거나 미검증 주장을 통과시킨 비율 | 미측정 |
| 지연시간 p50/p95 | 전체 응답 및 Supervisor/Intent/RAG/Verification 단계별 trace | 미측정 |
| LLM 토큰·호출 수 | trace별 prompt/completion 토큰, 호출 수, 재시도 횟수 | 미측정 |

비교는 **동일 질문, 동일 등록 증거 스냅샷, 동일 모델/환경**에서 변경 전 PoC와 변경 후를 측정해야 한다. Intent LLM 호출이 문서 사건에서도 수행되므로 지연·토큰 비용이 증가할 수 있다. 반대로 불필요한 문서 분석 경로가 제거되어 일반 법률 질문에서는 총 비용이 감소할 수 있다. 어느 쪽이 우세한지는 실측 전 단정할 수 없다.

## 5. 검증 방법 및 판정
1. 단위 회귀: `pytest backend/tests/test_consultation_mode_routing.py -q` (저장소 루트 기준, 설치/환경 설정 필요)
2. 추가 통합 회귀: 사건 문서가 있는 상태에서 일반 법률 질문과 사건 질문을 같은 case_id로 연속 실행, 모드·출처·답변 비교.
3. SC-001 질문 1: E01~E03만 승인한 별도 사건에서 질문 실행, 미래 증거 미등록 상태를 확인.
4. Langfuse Trace에서 `INTENT_MODE`, 문서 개수, answer_mode, 토큰, 지연, Verifier 결과 대조.
5. 정확도 및 지연시간의 실측 전후 차이를 기록하고 회귀 없을 때만 PASS 판정.

## 6. 미해결 위험 및 후속 검토
- Supervisor의 사건 브리핑/GraphRAG 조회 비용은 그대로다. 이번 개선은 조회 최적화가 아니라 **상담 모드 정확도** 개선이다.
- LLM이 GENERAL_LEGAL/CASE_EVIDENCE를 잘못 판단할 가능성이 있다. 현재는 값 누락·오류 시 CASE_EVIDENCE를 사용해 기존 사건 분석을 보호한다.
- `FOLLOWUP_ACTION`의 민법 고정 및 별도 검증 경로는 후속 개선 과제다.
- 일반 법률 질문에서 사건 정보가 Intent LLM 프롬프트에 전달되는 것은 분류를 위한 것이며, 일반 법률 **답변 생성·검증**에는 전달하지 않는다.
- 기존 PoC 수치와 이번 변경 후의 실제 KPI 차이는 아직 확인되지 않았다. 테스트 파일 추가만으로 PASS 또는 성능 향상을 주장하지 않는다.
