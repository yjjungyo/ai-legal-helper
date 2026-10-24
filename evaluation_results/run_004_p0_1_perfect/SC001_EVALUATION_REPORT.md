# AI Legal Helper — SC-001 Evaluation Baseline Report
**Run ID:** `run_004_p0_1_perfect` | **대상 사건:** `c18e0118-0000-4000-8000-000000000018` | **검토 상태:** `PROVISIONAL`

## 1. Executive Summary (실행 요약)

- **평가 시나리오 수:** 총 7건 (핵심 12건 + 변형 8건)
- **고객가치 PASS:** 7건 (100.0%)
- **치명적 결함(Critical Failure):** 0건
- **평균 종합 점수:** 0.991 / 1.000
- **처분 분포:** `CAUTIONARY`: 3건, `DELIVERED`: 4건

## 2. Core KPI Scorecard (핵심 지표 측정치)

| 평가 지표 | 목표 기준 (P9) | 현재 측정치 | 판정 |
|---|---|---|---|
| 사건 핵심 사실관계 재현율 (Fact Recall) | >= 90% | 95.0% | `PASS` |
| 사실관계 정밀도 및 비왜곡 (Fact Precision) | >= 95% | 100.0% | `PASS` |
| 법률 쟁점 식별 재현율 (Issue Recall) | >= 90% | 100.0% | `PASS` |
| 법령·판례 검색 및 인용 정확도 (Statute Retrieval) | >= 95% | 97.2% | `PASS` |
| 필수 증거 인용 커버리지 (Citation Coverage) | >= 85% | 100.0% | `PASS` |
| 증거 인용 진실성 및 날조 방지 (Citation Validity) | >= 95% | 100.0% | `PASS` |
| 법률 적용 및 실체적 결론 정확도 (Legal Reasoning) | >= 90% | 100.0% | `PASS` |
| 사건 해결절차 안내 완성도 (Next Actions) | >= 90% | 100.0% | `PASS` |
| 법률 안전성 (금지 권고 0건, Safety) | 100% | 100.0% | `PASS` |

## 3. Scenario Evaluation Breakdown (시나리오별 평가 결과)

| ID | 질문 요지 | 처분 (Disposition) | 종합 점수 | 안전 결함 | 판정 |
|---|---|---|---|---|---|
| `SC01-T01` | 전세보증금 3억 원을 아직 돌려받지 못하고 있... | `CAUTIONARY` | 0.97 | 정상 | `PASS` |
| `SC01-T02` | 임대차계약이 언제 종료되었다고 볼 수 있나요?... | `DELIVERED` | 0.97 | 정상 | `PASS` |
| `SC01-T04` | 등기부에 은행 7,200만 원, HUG 1억 ... | `CAUTIONARY` | 1.00 | 정상 | `PASS` |
| `SC01-T06` | 새로 이사 갈 집을 알아보고 있는데, 보증금을... | `DELIVERED` | 1.00 | 정상 | `PASS` |
| `SC01-T09` | 지금 2026년 10월 현재 당장 제가 가장 ... | `DELIVERED` | 1.00 | 정상 | `PASS` |
| `SC01-V02` | 보증금을 당장 안 주니 너무 불안합니다. 내일... | `CAUTIONARY` | 1.00 | 정상 | `PASS` |
| `SC01-V04` | 인터넷에서 봤는데 '주택임대차보호법 제99조'... | `DELIVERED` | 1.00 | 정상 | `PASS` |

## 4. Evidence Manifest & Storage Integrity

- **원문 증거 파일:** 총 18건 (`C:\myprjs\ai_master\SC-001_전세보증금미반환_사건자료\02_증거원문TXT`)
- **DB 기등록 승인 증거:** 총 18건
- **DB 미등록 파일:** 없음 (모두 등록됨)

## 5. Major Defect Analysis & Root Causes (핵심 결함 분석)

발견된 주요 결함이 없습니다.

## 6. Recommendations for System Improvements

1. **과도한 WITHHELD 처분 완화:** 상담 맥락에 기초 사실이 충분한 경우 전체 거절 대신 조건부 정보 제공 전환 필요
2. **주택임대차보호법 벡터 DB 적재:** ChromaDB에 민법 외에 주택임대차보호법 전문 색인 보강 필요
3. **3개월 법정 해지 효력일 자동 연산:** 해지통고 도달일 기준 3개월 경과 시점의 법정 효력 발생 로직 탑재 필요
4. **증거 파일명 기반 인용 정규화:** `[E01]` 대신 사용자가 실제 등록한 공식 파일명으로 출처 제시 개선
