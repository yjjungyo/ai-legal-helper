# AI Legal Helper E2E V8 2차 — KPI 재측정 결과보고서

- 평가 기준일: **2026-11-17**
- 대상: **SC-001(3단계), SC-002(1단계), SC-003(1단계)**, 6개 비교 서비스, 총 **30개 Trace**
- 연결 기준: **Trace ID 완전 일치** (30행 / 중복 0건)
- 성격: **AI 예비 평가(PROVISIONAL)**. 법률 전문가 검토 전 객관적 정확도 인증이 아닙니다.
- 재측정 입력: [기존 독립 채점 원장](./E2E_V8_2차_GOLD_채점근거.json), [Gold Set](./AI_Legal_Helper_E2E_V8_2차_정답지_채점기준.md), [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/tree/main/artifacts/langfuse_trace_export).
- 대조 기준 커밋: `c676b31578c5a4263cb3974e67d2790aa434a66f`.

## 1. 핵심 결론

원래 [2차 보고서](./AI_Legal_Helper_E2E_V8_2차_Report.md)의 **전 항목 100% 정확성/완성도 달성 주장은 유지할 수 없습니다.** Trace-기반 독립 평가 원장에서는 **V8 2차 법률 점수 평균 95.0점, 근거 90.0점, 필수 대응절차 89.7%, 처리성공률 100%**입니다.

**중요한 정의 차이**: 사용자 지정 신규 KPI `법률 상담 답변 정확도`는 *Gold Set의 필수 법률 쟁점 중 정답을 맞힌 개수 ÷ 평가 가능한 필수 쟁점 개수*로 산출해야 합니다. 아래 **법률 95.0점은 기존 Trace별 0~100 서술형 점수의 평균**으로, 항목별 정답률 95.0%를 의미하지 않습니다. 개별 필수 쟁점 TP/FN 전수가 없는 상태에서 새 정확률을 확정하지 않았습니다.

### 목표 KPI 재측정

| 성과 지표 | 목표 | 확인된 현재 수준 | 목표 판정 | 측정 방식 및 한계 |
|---|---:|---:|---|---|
| **법률 상담 답변 정확도** | **90% 이상** | **AI 예비 법률점수 95.0/100** | **정의상 판정 보류** | 필수 쟁점별 정답 개수 기반의 비율은 별도 체크 필요; 현재 95.0은 항목별 정답률 아님 |
| **법령·판례 근거 정확도** | **95% 이상** | **AI 예비 평가 90.0/100** | **잠정 미달** | 실제 인용, 존재 여부, 사건 관련성, 법적 적용 시점 확인. 공식 원문 전수 대조·전문가 검증 별도 필요 |
| **필수 대응절차 안내 완성도** | **90% 이상** | **AI 예비 평가 89.7%** | **잠정 미달** | Gold Next Action의 완전 포함 1, 부분 포함 0.5, 누락 0; Trace 축약 구간은 확정 불가 |
| **상담 처리 성공률(보조)** | **100%** | **100.0%** | **달성(처리 관점)** | 법률 결론 중대 오류 등은 성공 처리에서 제외, 내부 Verification PASS와 독립 |
| 증거 원문 사실추출 Precision/Recall(참고) | 원래 목표와 별도 | **N/A** | **미측정** | 상담 Trace에 추출 원시 후보와 HITL 승인 결과 전건 없음. SC-003은 증거문서 자체가 없음 |

**집계 모집단**: V8 2차 동일 5회 상담에 대한 단순 평균(가중 평균이 아님). 목표표에서 중복 기재된 근거·Next Action 항목은 한 번만 집계했습니다.

## 2. 성능 실측 비교 (5개 상담 합산)

| 서비스 | 법률점수 평균 | 근거점수 평균 | Next Action 평균 | 처리 성공 | 총 시간(초) | 총 입력토큰 | 총 출력토큰 | 총 토큰 | LLM 비용(USD) | LLM 호출 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LegalChat | 73.00 | 61.00 | 66.00% | 80.0% | 154.28 | 41,106 | 16,528 | 57,634 | $0.35068 | 5 |
| LegalRag | 72.00 | 63.00 | 66.00% | 80.0% | 432.74 | 61,864 | 36,497 | 112,697 | $0.70212 | 32 |
| LegalAgent POC | 96.00 | 92.00 | 100.00% | 100.0% | 2195.73 | 923,936 | 201,531 | 1,125,467 | $5.33281 | 52 |
| LegalAgent E2E | 97.00 | 95.00 | 100.00% | 100.0% | 848.39 | 422,163 | 68,903 | 491,066 | $2.08895 | 114 |
| LegalAgent E2E V8 | 95.00 | 89.00 | 87.67% | 100.0% | 962.22 | 703,166 | 93,587 | 796,753 | $3.16172 | 79 |
| LegalAgent E2E V8 2차 | 95.00 | 90.00 | 89.67% | 100.0% | 568.46 | 327,660 | 44,919 | 372,579 | $1.49293 | 21 |

PoC 대비 V8 2차는 **3.86배 빠르며** 실행시간 **74.1%**, 총 토큰 **66.9%**, 비용 **72.0%** 절감입니다. **법률의 정답률과 성능 지표는 서로 다른 평가 축**입니다.

## 3. Gold Set 정답지 (평가에 실제 적용되는 사건별 범위)

### SC001-S1

**필수 사실(사건 증거):** F01 계약/보증금 300,000,000원(E01); F02 보증금 30,000,000+270,000,000 지급(E02); F03 입주·전입·확정일자(E03); F04 재계약서·갱신 통지 미확인(E04); F05 2026-04-01 해지 통지·임대인 수신(E05); F06 분할반환 제안과 명시적 거절(E06,E07).

**법령·판단 정답:** 주택임대차보호법 제6조; 주택임대차보호법 제6조의2; 민법 제536조(동시이행).

**필수 대응절차:** 해지 통지·도달 자료 보존; 전액 반환 요구/분할 거절 증거 유지; 점유·전입 보호; 필요 시 권리보전/반환절차 검토.

### SC001-S2

**필수 사실(사건 증거):** F07 은행 가압류 7,200만/2026-07-18(E09); F08 HUG 가압류 1억2천만/2026-08-28(E10); F09 등기 열람 메모의 근저당 표시 없음·원본 미확인(E11); F10 반환지연·대출 곤란 정황(E12~E14).

**법령·판단 정답:** 주택임대차보호법 제3조; 주택임대차보호법 제3조의2; 가압류·담보권·배당순위 구분.

**필수 대응절차:** 등기사항전부증명서·말소/토지 권리 확인; 점유·주민등록 유지; 가압류/반환지연 증거 보존; 선순위 조세·경매 진행 여부 확인.

### SC001-S3

**필수 사실(사건 증거):** F11 2026-09-30 미반환, 10-05 일정 미확정(E15); F12 점유·전입·열쇠 유지(E16); F13 반환보증 가입 여부 미확인(E17); F14 원금 3억·변제 입증자료 없음(E01,E02,E15).

**법령·판단 정답:** 주택임대차보호법 제3조; 제3조의2; 제3조의3; 제6조의2.

**필수 대응절차:** 이사·전출 전 점유/전입 유지; 임차권등기명령 신청과 등기 완료 구별; 보증금반환청구/지급명령/소송 검토; 등기·조세·선순위 위험 확인; 반환보증 가입 확인.

### SC002-S1

**필수 사실(사건 증거):** 보증금 220,000,000원(01); 최초 전액 지급(04); 2026-09-20 반환 20,000,000원(05/06 동일 거래); 2026-10-10 반환 30,000,000원(06); 총 반환 50,000,000원·잔액 170,000,000원; 임대인의 총 1억 주장 추가 5천만 미입증(09); 임차권등기 신청만, 등기 미완료(07/08).

**법령·판단 정답:** 주택임대차보호법 제3조; 제3조의2; 제3조의3; 변제 입증·동시이행 원칙.

**필수 대응절차:** 입금 원장/거래번호로 중복 검증; 미입증 추가 변제자료 요청; 임차권등기 완료 확인 전 점유·전입 유지; 내용증명·정산기준 통지; 지급명령/반환소송·집행권원 검토.

### SC003-S1

**필수 사실(사건 증거):** 증거문서 없음, 사실추출 KPI N/A.

**법령·판단 정답:** 2026-10-27 공포 개정 민간임대주택법 시행령 제36조; 시행령 부칙 제1조: 2027-04-28 시행; 부칙 제2조: 시행 후 체결·갱신·변경 계약부터 적용; 2026-11-01 계약: 미래 추가 신고항목 미적용.

**필수 대응절차:** 2026-11-01에 적용되는 종전 신고항목으로 신고; 2027-04-28 이후 계약·갱신·변경 시 신설항목 적용; 관할 신고 서식·주택 유형 확인.

### 증거 범위 제한

- SC-001 1단계 E01~E08, 2단계 누적 E01~E14, 3단계 누적 E01~E17만 사용합니다. **E18은 증거가 아닙니다.**
- SC-002는 01~09 증거를 종합하되 9/20의 2,000만 원 입금과 그 영수증을 중복 합산하지 않습니다. 확인 반환액 5,000만 원, 미반환 1억 7,000만 원입니다.
- SC-003은 공식 시행일 **2027-04-28**과 시행 후 계약·변경·갱신 적용례가 핵심이며 2026-11-01 계약에는 추가항목 신고의무를 소급 적용하지 않습니다.

## 4. Trace ID별 평가 및 구체적 이유 (30건 전수)

| 사건/단계 | 서비스 | Trace ID | 법률/100 | 근거/100 | 대응/% | 성공 | Verification | 평가 이유 |
|---|---|---|---:|---:|---:|---:|---|---|
| SC-001 / 1단계 | LegalChat | [d860ca38](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_d860ca38-be7a-42d2-acc3-eba8d97d7131.json) | 90 | 70 | 75.00 | 1 | NONE | 핵심 3억·해지통보·묵시적 갱신·분할반환 거절을 반영. 다만 주임법 제6조의2의 구체 조문 및 E01~E08 출처 연결이 약함. |
| SC-001 / 1단계 | LegalRag | [2490a3cf](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_2490a3cf-d04c-4c6e-8f4b-ece8a46377dc.json) | 85 | 75 | 75.00 | 1 | NONE | 주요 결론과 E01~E08 인용은 타당하나 주택임대차의 특별 해지규정 대신 민법 제635조(건물 1개월)를 인용하며 주임법 제6조의2 원문 근거가 부족함. |
| SC-001 / 1단계 | LegalAgent POC | [635eb356](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_635eb356-006a-4911-b7a9-7f5a4338c29b.json) | 95 | 95 | 100.00 | 1 | PASS | E01~E08 및 주임법 제6조·제6조의2를 연결하고 합의 부존재·종료시점·동시이행관계를 설명. 전문가 검증 전 100점 확정 유보. |
| SC-001 / 1단계 | LegalAgent E2E | [620376c0](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_620376c0-cf02-456b-b2ee-dfc5008855b0.json) | 95 | 95 | 100.00 | 1 | PASS | 계약·도달·3개월·분할변제 무합의를 설명하고 임차권등기·보전 안내. CAUTIONARY는 경계 안내로 처리; 속도는 원본 실측으로 보정. |
| SC-001 / 1단계 | LegalAgent E2E V8 | [9a6ea3b1](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9a6ea3b1-5817-480d-a934-67eeb402ccab.json) | 95 | 90 | 87.50 | 1 | PASS | 종료·3개월·보전조치가 맞지만 Trace의 최종 답변에 '[총 ...자 축약]'이 포함되어 세부 근거 전수 확인이 불가. |
| SC-001 / 1단계 | LegalAgent E2E V8 2차 | [8a1edfd9](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8a1edfd9-4749-4f3e-847d-b5398a1ce385.json) | 95 | 90 | 87.50 | 1 | PASS | E01/E04/E05 및 제6조의2를 연결하고 3개월 적용이 타당. 다만 최종 답변이 일부 축약되어 전체 출처·행동 순서 검토가 제한됨. |
| SC-001 / 2단계 | LegalChat | [4a6bb262](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_4a6bb262-c3ef-4c81-b2d2-bc05bad6a21b.json) | 90 | 75 | 75.00 | 1 | NONE | 가압류 자체로 임차인 권리가 소멸하지 않고 배당재원·선순위 권리 확인 필요성을 제시. 정확한 조문 인용은 부족. |
| SC-001 / 2단계 | LegalRag | [de5e6f16](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_de5e6f16-7bc1-4acd-af4b-5022bc35782b.json) | 90 | 80 | 75.00 | 1 | NONE | 은행 7,200만/HUG 1억2천만과 가압류·근저당 차이를 인식. 민법 제356조 등의 일반 담보권 중심 인용으로 우선변제 법령의 직접근거가 다소 약함. |
| SC-001 / 2단계 | LegalAgent POC | [67828544](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_67828544-db3b-4e94-8cc2-1657a265a91c.json) | 95 | 90 | 100.00 | 1 | PASS | E03/E09/E10 인용과 가압류의 순위 비교를 반영. 다만 열람 메모만으로 모든 선순위를 단정하지 않는 조건부 주의 필요. |
| SC-001 / 2단계 | LegalAgent E2E | [8acaa910](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8acaa910-fe98-4daa-8b4d-9d94bb8b0147.json) | 95 | 95 | 100.00 | 1 | PASS | 주임법 제3조·제3조의2 및 E09~E11로 대항력/우선변제·회수 위험을 분리. 낙찰가·조세 미확인을 표시함. |
| SC-001 / 2단계 | LegalAgent E2E V8 | [3fe378fc](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_3fe378fc-1ac5-4c90-adf6-0de614c0e65d.json) | 95 | 90 | 87.50 | 1 | PASS | 가압류의 후순위 가능성 및 원본등기·조세 확인 필요성 반영. 답변 전문 일부 축약으로 세부 출처의 전수검증 보류. |
| SC-001 / 2단계 | LegalAgent E2E V8 2차 | [bbe82634](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_bbe82634-4b9d-4f6d-b301-eb216214e333.json) | 95 | 90 | 87.50 | 1 | PASS | E03/E09/E10/E11과 법령 조문을 연결하고 후발 가압류와 전액 회수 보장 금지를 구분. 축약 Trace로 전체 조치 항목 확인 제한. |
| SC-001 / 3단계 | LegalChat | [8072caf6](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8072caf6-e9d7-45cd-b9c3-a181f1200e39.json) | 90 | 75 | 80.00 | 1 | NONE | 점유·전입 유지, 임차권등기, 소송 등 조치 방향은 적절. E15~E17 사실 출처와 반환보증 미확인에 대한 구조화가 상대적으로 약함. |
| SC-001 / 3단계 | LegalRag | [dc9bca1f](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_dc9bca1f-4ba9-4da4-9eb3-7bbd0c576975.json) | 90 | 80 | 80.00 | 1 | NONE | 권리보전과 명령 신청/등기 효력 안내는 유용하나 출처 정밀성과 신청·등기 완료의 표현 검토 필요. |
| SC-001 / 3단계 | LegalAgent POC | [35afce36](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_35afce36-dea0-4eba-9077-8d9b89cf329d.json) | 95 | 90 | 100.00 | 1 | REVISE | 미반환·점유와 권리보전, 법원 절차를 종합하고 경매/환급을 보장하지 않음. 서면 답변의 법령 적용은 추가 전문가 확인 필요. |
| SC-001 / 3단계 | LegalAgent E2E | [20fd1ab5](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_20fd1ab5-24ea-4b1e-8a73-d00b44f2549d.json) | 95 | 95 | 100.00 | 1 | PASS | E15~E17·주임법 제3조의3·권리보전·집행권원 확보를 연결하여 실행순서를 안내. |
| SC-001 / 3단계 | LegalAgent E2E V8 | [d049beb7](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_d049beb7-f807-403c-b288-3012d9359db2.json) | 95 | 90 | 90.00 | 1 | PASS | 임차권등기 완료 후 이사 및 지급명령/소송을 안내. 최종 답변 축약으로 반환보증 확인 등 전 항목 대조 제한. |
| SC-001 / 3단계 | LegalAgent E2E V8 2차 | [9ea1c180](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9ea1c180-cf37-45fc-85b3-fe6bf7dce8ae.json) | 95 | 90 | 90.00 | 1 | PASS | 이사 전 점유·전입 보전과 반환소송 방향은 적절. 서두의 '임차권등기명령 신청해 ... 이동'은 실제 등기 완료 요건을 더 명료하게 표현해야 함. |
| SC-002 / 1단계 | LegalChat | [0f35b09e](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_0f35b09e-c6b4-47fd-bca5-034ca13c9849.json) | 95 | 85 | 100.00 | 1 | NONE | 원금 2.2억−실제 반환 2천만·3천만=1.7억 및 임대인의 1억 주장 미입증을 구분. 법령 출처 직접 확인과 동일 거래 식별 설명은 보강 여지. |
| SC-002 / 1단계 | LegalRag | [020f194c](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_020f194c-7a85-4e0b-82df-644d676af417.json) | 95 | 80 | 100.00 | 1 | NONE | 2건 반환액 합계·등기 완료 전 이사 위험을 정확히 안내. 검색 도구가 관련 조문 회수에 실패했다고 명시하여 근거 정확도 감점. |
| SC-002 / 1단계 | LegalAgent POC | [07cc223a](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_07cc223a-ac34-4dfe-845a-6e6f0e86969d.json) | 95 | 90 | 100.00 | 1 | REVISE | 잔액 1.7억, 반환 주장 미입증, 임차권등기 신청/완료를 구분. 내부 검증 최종 REVISE이므로 PASS로 표시 금지. |
| SC-002 / 1단계 | LegalAgent E2E | [71d359c1](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_71d359c1-0d51-4f40-92df-d4eb2ba82828.json) | 100 | 95 | 100.00 | 1 | PASS | 실제 변제 5천만·상대방 주장 1억·등기 미완료·절차를 정확히 연결하고 법률 근거를 제시. |
| SC-002 / 1단계 | LegalAgent E2E V8 | [22da7384](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_22da7384-3dfc-4522-a4ac-5107501db41b.json) | 95 | 85 | 90.00 | 1 | REVISE | 미반환 1.7억 판단은 맞으나 원본 Trace 검증 상태는 REVISE이며 최종문 축약; 전부 100점 부여는 근거 부족. |
| SC-002 / 1단계 | LegalAgent E2E V8 2차 | [9feaf829](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9feaf829-c86a-42a7-b208-6865a97a6235.json) | 100 | 95 | 100.00 | 1 | PASS | 중복 반영 없는 5천만 실입금·1.7억 잔액·등기 완료 전 이사 위험 안내 적절. 발췌된 답변 범위에서 근거 확인 가능. |
| SC-003 / 1단계 | LegalChat | [83abd075](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_83abd075-1474-481e-9624-e126792a7757.json) | 0 | 0 | 0.00 | 0 | NONE | 중대오류: 2026-10-27 공포를 시행으로 오인하여 2026-11-01 계약에 관리비·공과금 신고의무가 있다고 안내. 정답은 부칙상 2027-04-28 이후 계약부터 적용. |
| SC-003 / 1단계 | LegalRag | [c8c770bb](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_c8c770bb-ae14-4311-aa9e-eda54bbe67c5.json) | 0 | 0 | 0.00 | 0 | NONE | 중대오류: 관련 시행령·부칙 원문 대신 다른 법령을 검색하여 미시행 신고항목을 현재 계약에 적용. 과태료·서식 판단도 신뢰 불가. |
| SC-003 / 1단계 | LegalAgent POC | [4062ee92](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_4062ee92-ed2e-47f9-81a9-cd0b2eb9a268.json) | 100 | 95 | 100.00 | 1 | PASS | 시행일 2027-04-28, 부칙 제2조의 시행 후 체결/갱신/변경 적용례를 정확히 설명. 2026-11-01 계약에는 새로운 신고항목 미적용. |
| SC-003 / 1단계 | LegalAgent E2E | [033755c3](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_033755c3-d654-44df-ac3e-545c9e1ea67e.json) | 100 | 95 | 100.00 | 1 | PASS | 법 제46조·시행령 제36조·부칙 제2조 및 계약일 대비 시행일을 구분. 정답이나 359.23초·92 LLM 호출의 성능 병목 확인. |
| SC-003 / 1단계 | LegalAgent E2E V8 | [cac6f0da](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_cac6f0da-defe-498b-83bf-3a647591f0ef.json) | 95 | 90 | 83.33 | 1 | PASS | 2026-11-01 미적용과 2027-04-28 이후 적용례를 명시. 최종 답변은 축약되어 적용례 전체 문구 확인에 제한. |
| SC-003 / 1단계 | LegalAgent E2E V8 2차 | [aefa1b77](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_aefa1b77-0c62-4cd0-892f-1bbbcefc1e40.json) | 90 | 85 | 83.33 | 1 | PASS | 핵심 결론(2026-11-01 미적용)·시행일은 맞음. 그러나 답변 첫 단어 '네'는 뒤의 '신고해야 한다고 보기 어렵다'와 양립하지 않는 혼동을 줄 수 있고, 부칙 적용례 명시가 약함. |

### 쟁점별 교차 확인

1. **SC-001 3차 V8 2차**: 최종 답변의 '임차권등기명령을 신청해 권리를 보전한 뒤 이동'이라는 도입부는 **신청과 실제 등기 완료를 혼동**할 여지가 있어 별도 확인 항목입니다. 등기부 기재 전 전출·이사를 권고한 것으로 해석되면 중요한 안전상 오류가 됩니다.
2. **SC-002**: 2천만 원 영수증/이체 동일거래를 다시 빼지 않아야 합니다. V8 1차 `22da7384`의 내부 최종 상태는 원장상 **REVISE**이며 PASS로 바꾸지 않습니다.
3. **SC-003**: LegalChat(`83abd075`)과 LegalRag(`c8c770bb`)의 **공포일=시행일 혼동**은 중대 결론 오류입니다. V8 2차(`aefa1b77`)의 결론은 맞지만 첫 단어 '네.'와 뒤 문장의 '신고해야 한다고 보기 어렵다'는 표현이 혼란을 줄 수 있습니다. 부칙 제2조의 갱신·변경 적용례를 명시적으로 적시했는지도 확인해야 합니다.
4. **SC-003 초기 E2E 성능**: [기존 원장](./E2E_V8_2차_GOLD_채점근거.json)상 **359.23초, 196,311토큰, 92 LLM 호출**로 확인되며, 이전 2차 보고서의 72.79초·55,492토큰과 다릅니다.

## 5. 답변 전문 축약과 채점 신뢰도

본 Trace 내 일부 `finalize_node.output.answer`에는 실제로 **`[총 ...자 축약]`**이 기록돼 있습니다. 이는 이번 표를 줄여서 표시한 문제가 아니라 **기록된 원본의 일부가 축약된 것**입니다. 축약 구간의 인용, 행동 조치, 법률 연결은 검증됐다고 간주할 수 없습니다. `실행_KPI_기록`의 답변 내용과 부속 CSV는 관측 가능한 본문만 사용합니다. 사용자에게 표시된 실제 전체 답변을 평가하려면 축약 이전 최종 응답 원문 저장이 필요합니다.

법률 정확도와 근거 정확도는 **내부 Verification PASS를 그대로 100점으로 치환하지 않았습니다.** 과거 ChatGPT 채점 수치는 AI 예비 판단이며 독립 법률 전문가 검증을 거쳐야 합니다.

## 6. Trace ID 매칭·집계 품질 점검

- JSON 원장 30건, 고유 Trace ID **30건**.
- 사건·단계: SC001-S1, SC001-S2, SC001-S3, SC002-S1, SC003-S1. 각각 6개 서비스가 존재하는지 재검사했습니다.
- `답변내용` 저장값에 원본 Trace 자체 축약 표기를 그대로 보존하고, 중간 생략을 조작하지 않았습니다.
- 입력/출력/합계 토큰, 비용, 호출횟수, 실행시간, Verification은 JSON 원장 실측값을 사용했습니다. **새로운 서비스 재실행을 한 것은 아닙니다.**

## 7. GitHub 산출물 및 형식 관련 명시

- [재측정 이름의 엑셀 결과 파일](./AI_Legal_Helper_KPI_202611151124_자동평가-E2EV8-2차_chatgpt_재측정.xlsx)
- [Trace별 근거·응답 확인 CSV](./AI_Legal_Helper_E2E_V8_2차_재측정_Trace별_근거.csv)
- [새 목표KPI 측정 기준표 CSV](./AI_Legal_Helper_E2E_V8_2차_재측정_KPI_목표.csv)
- [기존 원본 ChatGPT 엑셀](./AI_Legal_Helper_KPI_202611151124_자동평가-E2EV8-2차_chatgpt.xlsx)

**편집 범위 고지:** GitHub 연결 도구에서 XLSX의 바이너리 내용을 직접 편집할 수 없어, **재측정 명칭의 XLSX는 이전 독립평가 Excel의 동일 바이너리 복제본**입니다. 기존 파일의 30개 Trace 매칭 점수·정답지 양식을 보존합니다. 이번에 새로 작성한 상세 산출물은 이 보고서, Trace별 재점검 CSV와 목표KPI CSV입니다. **신규 KPI 정의 및 상세 재측정 내용을 XLSX 내부에 새로 덮어썼다고 주장하지 않습니다.** Excel 내 최신 양식 반영은 추가 편집이 필요합니다.
