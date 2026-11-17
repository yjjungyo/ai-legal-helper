# AI Legal Helper E2E V8 2차 KPI 재측정 보고서 (Trace ID 원본 정합성 교정본)

- **재측정 기준일**: 2026년 11월 17일
- **평가 범위**: SC-001의 3단계, SC-002의 1단계, SC-003의 1단계 × 6개 비교 서비스 = 총 30개 상담
- **입력 원본**: [E2E V8 Langfuse Trace 30개](https://github.com/yjjungyo/ai-legal-helper/tree/main/artifacts/langfuse_trace_export), [Gold Set](./AI_Legal_Helper_E2E_V8_2차_정답지_채점기준.md)
- **완성 엑셀**: [결과 파일](./AI_Legal_Helper_KPI_202611151124_자동평가-E2EV8-2차_chatgpt.xlsx)
- **평가 신뢰도**: AI 예비 채점(Provisional). 법률전문가의 공식 법령·판례 적용시점 확인 및 일부 축약 답변 원문 확인 전에는 정확도 인증으로 사용하지 않습니다.

## 1. 핵심 결론 및 목표 KPI

| 성과지표 | 목표 | V8 2차 현재 수준 | 판정 |
|---|---:|---:|---|
| **법률 상담 답변 정확도(필수 쟁점 정답률)** | ≥ 90% | **N/A — 정확한 정답률 산출 보류** (참고: 법률 AI 예비점수 평균 **96.0/100**) | 정의상 평가 불충분 |
| **법령·판례 근거 정확도** | ≥ 95% | **91.0/100** (AI 예비 평균) | **잠정 미달** |
| **필수 대응절차 안내 완성도** | ≥ 90% | **89.67%** | **잠정 미달** |
| 상담 처리 성공률 (보조) | 100% | **100%** | 잠정 달성 |

**정의상 가장 중요한 점**: 기존의 0~100 법률 채점 평균과 신규 KPI `필수 법률 쟁점별 정답 개수 / 평가 가능한 쟁점 총수`는 서로 다른 값입니다. 현재 Gold는 필수 
  법조문과 평가기준을 나열하지만 각 Trace별 법률 쟁점의 개별 정오(TP/FN) 판정은 완료되지 않았습니다. 따라서 **96.0점의 법률 예비점수를 96.0% 정답률이라고 
  기재하지 않았습니다.** 새 Excel `법률_쟁점별_검토` 시트의 판정칸은 검수 전 N/A입니다.

## 2. 서비스별 정량 성능 및 품질 비교

| 서비스 | 상담 | 법률점수(평균)* | 근거점수(평균)* | 대응절차 | 성공률 | 평균 시간(초) | 총 토큰 | 총 비용(USD) | 총 LLM 호출 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LegalChat | 5 | 73.0 | 61.0 | 66.00% | 80% | 30.86 | 57,634 | $0.3507 | 5 |
| LegalRag | 5 | 72.0 | 63.0 | 66.00% | 80% | 86.55 | 112,697 | $0.7021 | 32 |
| LegalAgent POC | 5 | 96.0 | 92.0 | 100.00% | 100% | 439.15 | 1,125,467 | $5.3328 | 52 |
| LegalAgent E2E | 5 | 97.0 | 95.0 | 100.00% | 100% | 169.68 | 491,066 | $2.0890 | 114 |
| LegalAgent E2E V8 | 5 | 95.0 | 89.0 | 87.67% | 100% | 192.44 | 796,753 | $3.1617 | 79 |
| LegalAgent E2E V8 2차 † | 5 | 96.0 | 91.0 | 89.67% | 100% | 101.68 | 377,804 | $1.5142 | 19 |


V8 2차의 5회 실행 합계는 **508.39초, 377,804토큰, $1.514185, LLM 19회**입니다. POC의 동일 5개 평가행 대비 단순 수치상 평균 처리시간 **4.32배**, 토큰 **66.4%**, 비용 **71.6%** 절감입니다. V8 1차 대비 시간 **1.89배**, 토큰 **52.6%**, 비용 **52.1%** 절감입니다. 

## 3. V8 2차 사건별 Gold 기준과 감점 사유

### SC001-S1 — 임대차 종료·분할반환

- **Trace ID**: [`8a1edfd9-4749-4f3e-847d-b5398a1ce385`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8a1edfd9-4749-4f3e-847d-b5398a1ce385.json)
- **AI 예비점수**: 법률 95/100, 근거 90/100, 대응절차 87.5%, 성공 1.
- **평가 이유**: E01/E04/E05 및 제6조의2를 연결하고 3개월 적용이 타당. 다만 최종 답변이 일부 축약되어 전체 출처·행동 순서 검토가 제한됨.
- **Gold 법률 기준**: 주택임대차보호법 제6조; 주택임대차보호법 제6조의2; 민법 제536조(동시이행).
- **Gold 필수 대응절차**: 해지 통지·도달 자료 보존; 전액 반환 요구/분할 거절 증거 유지; 점유·전입 보호; 필요 시 권리보전/반환절차 검토.

### SC001-S2 — 가압류·배당순위

- **Trace ID**: [`bbe82634-4b9d-4f6d-b301-eb216214e333`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_bbe82634-4b9d-4f6d-b301-eb216214e333.json)
- **AI 예비점수**: 법률 95/100, 근거 90/100, 대응절차 87.5%, 성공 1.
- **평가 이유**: E03/E09/E10/E11과 법령 조문을 연결하고 후발 가압류와 전액 회수 보장 금지를 구분. 축약 Trace로 전체 조치 항목 확인 제한.
- **Gold 법률 기준**: 주택임대차보호법 제3조; 주택임대차보호법 제3조의2; 가압류·담보권·배당순위 구분.
- **Gold 필수 대응절차**: 등기사항전부증명서·말소/토지 권리 확인; 점유·주민등록 유지; 가압류/반환지연 증거 보존; 선순위 조세·경매 진행 여부 확인.

### SC001-S3 — 미반환·이사·권리보전

- **Trace ID**: [`9ea1c180-cf37-45fc-85b3-fe6bf7dce8ae`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9ea1c180-cf37-45fc-85b3-fe6bf7dce8ae.json)
- **AI 예비점수**: 법률 95/100, 근거 90/100, 대응절차 90%, 성공 1.
- **평가 이유**: 이사 전 점유·전입 보전과 반환소송 방향은 적절. 서두의 '임차권등기명령 신청해 ... 이동'은 실제 등기 완료 요건을 더 명료하게 표현해야 함.
- **Gold 법률 기준**: 주택임대차보호법 제3조; 제3조의2; 제3조의3; 제6조의2.
- **Gold 필수 대응절차**: 이사·전출 전 점유/전입 유지; 임차권등기명령 신청과 등기 완료 구별; 보증금반환청구/지급명령/소송 검토; 등기·조세·선순위 위험 확인; 반환보증 가입 확인.

### SC002-S1 — 일부 변제·중복 영수증

- **Trace ID**: [`9feaf829-c86a-42a7-b208-6865a97a6235`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9feaf829-c86a-42a7-b208-6865a97a6235.json)
- **AI 예비점수**: 법률 100/100, 근거 95/100, 대응절차 100%, 성공 1.
- **평가 이유**: 중복 반영 없는 5천만 실입금·1.7억 잔액·등기 완료 전 이사 위험 안내 적절. 발췌된 답변 범위에서 근거 확인 가능.
- **Gold 법률 기준**: 주택임대차보호법 제3조; 제3조의2; 제3조의3; 변제 입증·동시이행 원칙.
- **Gold 필수 대응절차**: 입금 원장/거래번호로 중복 검증; 미입증 추가 변제자료 요청; 임차권등기 완료 확인 전 점유·전입 유지; 내용증명·정산기준 통지; 지급명령/반환소송·집행권원 검토.

### SC003-S1 — 시행일·부칙 적용

- **Trace ID**: [`f7a1a47d-bdd2-4d94-b0de-bd6280392e0a`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_f7a1a47d-bdd2-4d94-b0de-bd6280392e0a.json)
- **AI 예비점수**: 법률 95/100, 근거 90/100, 대응절차 83.33%, 성공 1.
- **평가 이유**: 최종 응답은 2026-11-01 계약에 2027-04-28 시행 신규 관리비·공과금 신고항목이 적용되지 않음을 정확히 안내하고 법 제46조·시행령 제36조를 연결합니다. 다만 부칙 제2조의 '시행 후 체결·갱신·변경 계약' 적용례를 문구 전체로 인용하지 않았고, 법 제46조 검색 메타데이터에 사건일 이후 시행본(2027-03-09)이 혼재돼 근거 시점 검증을 보완해야 합니다. 원본 응답에 [총 2158자 축약]이 남아 후반부 확인 불가. 원본 export_metadata=SC-003_g/Manual로 기존 2차 정규 배치와 동일 실행 조건인지 확인 필요.
- **Gold 법률 기준**: 2026-10-27 공포 개정 민간임대주택법 시행령 제36조; 시행령 부칙 제1조: 2027-04-28 시행; 부칙 제2조: 시행 후 체결·갱신·변경 계약부터 적용; 2026-11-01 계약: 미래 추가 신고항목 미적용.
- **Gold 필수 대응절차**: 2026-11-01에 적용되는 종전 신고항목으로 신고; 2027-04-28 이후 계약·갱신·변경 시 신설항목 적용; 관할 신고 서식·주택 유형 확인.


## 4. 전 서비스 30개 Trace별 재집계

| Gold ID | 비교 서비스 | Trace ID (원본) | 법률* | 근거* | 대응절차 | 실행시간(초) | 총 토큰 | 비용 | LLM 호출 | Verification |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| SC001-S1 | LegalChat | [`d860ca38`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_d860ca38-be7a-42d2-acc3-eba8d97d7131.json) | 90 | 70 | 75.00% | 26.87 | 5,356 | $0.0485 | 1 | NONE |
| SC001-S1 | LegalRag | [`2490a3cf`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_2490a3cf-d04c-4c6e-8f4b-ece8a46377dc.json) | 85 | 75 | 75.00% | 87.81 | 21,556 | $0.1386 | 5 | NONE |
| SC001-S1 | LegalAgent POC | [`635eb356`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_635eb356-006a-4911-b7a9-7f5a4338c29b.json) | 95 | 95 | 100.00% | 233.92 | 78,545 | $0.4096 | 5 | PASS |
| SC001-S1 | LegalAgent E2E | [`620376c0`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_620376c0-cf02-456b-b2ee-dfc5008855b0.json) | 95 | 95 | 100.00% | 136.38 | 90,300 | $0.4137 | 8 | PASS |
| SC001-S1 | LegalAgent E2E V8 | [`9a6ea3b1`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9a6ea3b1-5817-480d-a934-67eeb402ccab.json) | 95 | 90 | 87.50% | 191.59 | 79,691 | $0.3330 | 3 | PASS |
| SC001-S1 | LegalAgent E2E V8 2차 | [`8a1edfd9`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8a1edfd9-4749-4f3e-847d-b5398a1ce385.json) | 95 | 90 | 87.50% | 120.17 | 63,655 | $0.2942 | 2 | PASS |
| SC001-S2 | LegalChat | [`4a6bb262`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_4a6bb262-c3ef-4c81-b2d2-bc05bad6a21b.json) | 90 | 75 | 75.00% | 31.75 | 17,237 | $0.0906 | 1 | NONE |
| SC001-S2 | LegalRag | [`de5e6f16`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_de5e6f16-7bc1-4acd-af4b-5022bc35782b.json) | 90 | 80 | 75.00% | 91.93 | 28,170 | $0.1574 | 6 | NONE |
| SC001-S2 | LegalAgent POC | [`67828544`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_67828544-db3b-4e94-8cc2-1657a265a91c.json) | 95 | 90 | 100.00% | 649.26 | 235,907 | $1.2231 | 11 | PASS |
| SC001-S2 | LegalAgent E2E | [`8acaa910`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8acaa910-fe98-4daa-8b4d-9d94bb8b0147.json) | 95 | 95 | 100.00% | 112.13 | 73,952 | $0.3550 | 4 | PASS |
| SC001-S2 | LegalAgent E2E V8 | [`3fe378fc`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_3fe378fc-1ac5-4c90-adf6-0de614c0e65d.json) | 95 | 90 | 87.50% | 183.77 | 174,267 | $0.6953 | 8 | PASS |
| SC001-S2 | LegalAgent E2E V8 2차 | [`bbe82634`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_bbe82634-4b9d-4f6d-b301-eb216214e333.json) | 95 | 90 | 87.50% | 135.38 | 83,674 | $0.3396 | 4 | PASS |
| SC001-S3 | LegalChat | [`8072caf6`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8072caf6-e9d7-45cd-b9c3-a181f1200e39.json) | 90 | 75 | 80.00% | 54.00 | 27,860 | $0.1394 | 1 | NONE |
| SC001-S3 | LegalRag | [`dc9bca1f`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_dc9bca1f-4ba9-4da4-9eb3-7bbd0c576975.json) | 90 | 80 | 80.00% | 119.42 | 28,503 | $0.1769 | 6 | NONE |
| SC001-S3 | LegalAgent POC | [`35afce36`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_35afce36-dea0-4eba-9077-8d9b89cf329d.json) | 95 | 90 | 100.00% | 585.58 | 339,826 | $1.6627 | 13 | REVISE |
| SC001-S3 | LegalAgent E2E | [`20fd1ab5`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_20fd1ab5-24ea-4b1e-8a73-d00b44f2549d.json) | 95 | 95 | 100.00% | 149.39 | 74,384 | $0.3893 | 5 | PASS |
| SC001-S3 | LegalAgent E2E V8 | [`d049beb7`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_d049beb7-f807-403c-b288-3012d9359db2.json) | 95 | 90 | 90.00% | 93.37 | 75,912 | $0.3366 | 4 | PASS |
| SC001-S3 | LegalAgent E2E V8 2차 | [`9ea1c180`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9ea1c180-cf37-45fc-85b3-fe6bf7dce8ae.json) | 95 | 90 | 90.00% | 103.29 | 100,475 | $0.3731 | 4 | PASS |
| SC002-S1 | LegalChat | [`0f35b09e`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_0f35b09e-c6b4-47fd-bca5-034ca13c9849.json) | 95 | 85 | 100.00% | 36.01 | 6,209 | $0.0642 | 1 | NONE |
| SC002-S1 | LegalRag | [`020f194c`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_020f194c-7a85-4e0b-82df-644d676af417.json) | 95 | 80 | 100.00% | 81.56 | 22,036 | $0.1468 | 6 | NONE |
| SC002-S1 | LegalAgent POC | [`07cc223a`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_07cc223a-ac34-4dfe-845a-6e6f0e86969d.json) | 95 | 90 | 100.00% | 555.11 | 263,289 | $1.3239 | 13 | REVISE |
| SC002-S1 | LegalAgent E2E | [`71d359c1`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_71d359c1-0d51-4f40-92df-d4eb2ba82828.json) | 100 | 95 | 100.00% | 91.26 | 56,119 | $0.2582 | 5 | PASS |
| SC002-S1 | LegalAgent E2E V8 | [`22da7384`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_22da7384-3dfc-4522-a4ac-5107501db41b.json) | 95 | 85 | 90.00% | 319.46 | 283,368 | $1.2108 | 11 | REVISE |
| SC002-S1 | LegalAgent E2E V8 2차 | [`9feaf829`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9feaf829-c86a-42a7-b208-6865a97a6235.json) | 100 | 95 | 100.00% | 101.20 | 93,759 | $0.3585 | 3 | PASS |
| SC003-S1 | LegalChat | [`83abd075`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_83abd075-1474-481e-9624-e126792a7757.json) | 0 | 0 | 0.00% | 5.65 | 972 | $0.0080 | 1 | NONE |
| SC003-S1 | LegalRag | [`c8c770bb`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_c8c770bb-ae14-4311-aa9e-eda54bbe67c5.json) | 0 | 0 | 0.00% | 52.02 | 12,432 | $0.0824 | 9 | NONE |
| SC003-S1 | LegalAgent POC | [`4062ee92`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_4062ee92-ed2e-47f9-81a9-cd0b2eb9a268.json) | 100 | 95 | 100.00% | 171.86 | 207,900 | $0.7135 | 10 | PASS |
| SC003-S1 | LegalAgent E2E | [`033755c3`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_033755c3-d654-44df-ac3e-545c9e1ea67e.json) | 100 | 95 | 100.00% | 359.23 | 196,311 | $0.6729 | 92 | PASS |
| SC003-S1 | LegalAgent E2E V8 | [`cac6f0da`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_cac6f0da-defe-498b-83bf-3a647591f0ef.json) | 95 | 90 | 83.33% | 174.03 | 183,515 | $0.5861 | 53 | PASS |
| SC003-S1 | LegalAgent E2E V8 2차 | [`f7a1a47d`](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_f7a1a47d-bdd2-4d94-b0de-bd6280392e0a.json) | 95 | 90 | 83.33% | 48.35 | 36,241 | $0.1488 | 6 | PASS (Manual†) |

## 5. 엑셀 수정 내용 및 검증 규칙

- **기존 9개 시트와 30개 평가행 유지**: `실행_KPI_기록`의 F~R열(답변내용/법률점수/근거점수/처리성공/실행시간/입출력 토큰/비용/호출횟수/Verification/오류·특이사항/성능비교)을 **E열 Trace ID 정확히 일치**하는 행에 덮어썼습니다. S~Z열에 Gold ID, 감점/평가 이유, 대응절차 완성도, GitHub 원본 URL, Trace 매칭 및 답변 축약 여부, 엄밀 법률 정답률 확정 상태를 추가했습니다.
- **`목표KPI_기록` 정정**: 법률 상담 답변 정확도 항목에 사실추출 Precision/Recall=N/A를 잘못 쓰던 값을 법률 AI 예비점수로 분리 수정하고 법령·판례 근거, Next Action 완성도, Gold ID·평가 이유를 반영했습니다.
- **`정량적목표(KPI)` 보충**: 기존의 비어 있던 `현재 수준`에 목표별 수치, 판정 및 측정 한계를 기록했습니다.
- **추가 4개 시트**: `KPI_재측정_요약`, `Trace_매칭_검증`, `정답지_상세_재측정`, `법률_쟁점별_검토`. 개별 법률 쟁점 정오 판정 열은 검증 전 공란으로 보존합니다.
- **답변 원문 처리**: Trace에서 관측 가능한 답변만 입력합니다. 총 **10개** 원장 답변에 `[총 ...자 축약]` 표기가 있어, 생략된 내용을 지어내지 않았습니다. 최종 답변 전체를 확인하려면 원본 저장/추출 단계의 개선이 필요합니다.
- **사실추출 Precision/Recall**은 상담 Trace만으로 원시 Fact 추출 TP/FP/FN이 검증되지 않으므로 N/A이며, 별도 상담 답변 KPI와 혼동하지 않습니다.
- **Verification PASS ≠ 법률 정답**: 내부 검증상 PASS여도 사실·법령 적용시점·안전한 조치순서는 Gold 기준으로 독립 검토해야 합니다. 답변 분량 및 지연시간은 법률 정확도 점수에 반영하지 않았습니다.

## 7. 평가서 및 발표자료 반영 시 주의할 문구

> E2E V8 2차 평가에서 LegalAgent는 SC-001~SC-003의 상담 5회에 대해 법률 답변 AI 예비점수 평균 96.0점, 근거 정확도 예비점수 평균 91.0점, 필수 대응절차 완성도 89.67%를 기록했습니다. 전체 상담은 완료되었으나, 근거 정확도 95% 및 대응절차 완성도 90% 목표는 예비평가상 미달했습니다.
