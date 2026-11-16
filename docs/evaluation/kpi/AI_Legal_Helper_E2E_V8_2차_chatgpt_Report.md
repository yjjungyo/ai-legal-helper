# AI Legal Helper — E2E V8 2차 ChatGPT 독립 재평가 결과보고서

**평가 기준일**: 2026-11-16  
**대상**: SC-001 3회, SC-002 1회, SC-003 1회 × 6개 서비스 = **30개 Trace**  
**결과 상태**: 원본 계측 재검증 완료 / 법률 품질 점수는 AI 예비 평가(PROVISIONAL) / 증거 사실추출 Precision·Recall 측정 불가(N/A)

## 1. 핵심 결론

1. **Trace ID를 기준으로 총 30개 원본을 다시 읽어 집계**했습니다. 기존 2차 보고서의 일부 E2E 실행시간·토큰·호출 수 및 Verification 기재는 실제 Trace와 다릅니다.
2. **V8 2차**의 총 시간은 **568.46초**, 총 토큰 **372,579**, 총 LLM 비용 **$1.49293**이며, PoC의 2,195.73초·1,125,467토큰·$5.33281 대비 **3.86배 빠르고 토큰 66.9% 및 비용 72.0% 절감**되었습니다.
3. 법률 내용의 **AI 예비 채점 평균**은 V8 2차 기준 법률 **95.0/100**, 증거·법령 근거 **90.0/100**, 필수 대응절차 **89.7%**입니다. 이는 사람 법률전문가가 검증한 공식 합격률이 아니며, 근거 목표 95% 및 절차 목표 90%를 **잠정적으로 충족하지 못했습니다**.
4. **사실 추출 Precision·Recall은 미측정(N/A)**입니다. 이 30건은 상담 Trace이며 원문→추출 Fact 전건이 포함되지 않았기 때문입니다. 답변 속 사실 언급률을 사실 *추출* KPI로 둔갑시키지 않았습니다.
5. SC-003에서 LegalChat과 LegalRag는 2026-10-27 공포 규정의 시행시점과 부칙을 놓쳐 2026-11-01 계약에 추가 신고의무가 있다는 잘못된 결론을 제시했습니다. V8 2차는 법률 결론이 맞지만 첫 단어 **“네.”**와 이어지는 부정적 법률 결론 사이에 독자 혼동 가능성이 있습니다.

## 2. 평가 기준 및 주의사항

- 정답지: [AI_Legal_Helper_E2E_V8_2차_정답지_채점기준.md](./AI_Legal_Helper_E2E_V8_2차_정답지_채점기준.md)
- 각 Trace의 실제 응답·Usage·Latency·Verification을 읽었고, 전수 비교용 수치와 근거를 [E2E_V8_2차_GOLD_채점근거.json](./E2E_V8_2차_GOLD_채점근거.json)에 보존했습니다.
- 점수는 **실제 답변 내용과 Gold 법률 판단·행동 항목을 대조한 AI 예비 평가**입니다. 조문 출처·시점의 원문 미제공 또는 답변 축약은 점수 한계로 명시합니다.
- 공식 검증 PASS와 사용자를 위한 **상담 처리 성공(0/1)**은 별도로 기록하였습니다. LegalChat/Rag에는 독립 Verification 노드가 없으므로 `NONE`입니다. **SC-002의 V8 1차 내부 상태는 REVISE**이며 성공 상담 여부와는 별개입니다.
- SC-001 3차의 증거는 **E15~E17**, 누적 총 **E01~E17**입니다. **E18은 증거가 아니며 채점에서 제외**했습니다.

## 3. 서비스별 재집계 성능 및 예비 점수

| 서비스 | 시간 합계(초) | 입력 토큰 | 출력 토큰 | 총 토큰 | 비용(USD) | LLM 호출 | 법률 점수 평균 | 근거 점수 평균 | 대응절차 평균 | 상담 성공률 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| LegalChat | 154.28 | 41,106 | 16,528 | 57,634 | $0.35068 | 5 | 73.0 | 61.0 | 66.0% | 80.0% |
| LegalRag | 432.74 | 61,864 | 36,497 | 112,697 | $0.70212 | 32 | 72.0 | 63.0 | 66.0% | 80.0% |
| LegalAgent POC | 2195.73 | 923,936 | 201,531 | 1,125,467 | $5.33281 | 52 | 96.0 | 92.0 | 100.0% | 100.0% |
| LegalAgent E2E | 848.39 | 422,163 | 68,903 | 491,066 | $2.08895 | 114 | 97.0 | 95.0 | 100.0% | 100.0% |
| LegalAgent E2E V8 | 962.22 | 703,166 | 93,587 | 796,753 | $3.16172 | 79 | 95.0 | 89.0 | 87.7% | 100.0% |
| LegalAgent E2E V8 2차 | 568.46 | 327,660 | 44,919 | 372,579 | $1.49293 | 21 | 95.0 | 90.0 | 89.7% | 100.0% |

> 성능 비교는 **LegalAgent 계열끼리** 동일한 5회 상담의 합산값으로 계산했습니다. 일반 LegalChat·LegalRag는 PoC 비교 대상에서 제외하였습니다.

### PoC 대비 에이전트 계열 성능 변화

| 서비스 | 속도 배수(POC/현재) | 시간 절감 | 토큰 절감 | 비용 절감 |
|---|---:|---:|---:|---:|
| LegalAgent POC | 1.00배 | 0.0% | 0.0% | 0.0% |
| LegalAgent E2E | 2.59배 | 61.4% | 56.4% | 60.8% |
| LegalAgent E2E V8 | 2.28배 | 56.2% | 29.2% | 40.7% |
| LegalAgent E2E V8 2차 | 3.86배 | 74.1% | 66.9% | 72.0% |

## 4. Trace 원본과 기존 보고서의 수치 불일치

| 사건·서비스 | 기존 2차 보고서 | 원본 Trace 재집계 | 판정 |
|---|---|---|---|
| SC-001 1차 LegalAgent E2E | 104.78초·64,319토큰 | **136.38초·90,300토큰** | 원본 수정 |
| SC-002 LegalAgent E2E V8 1차 | Verification PASS | **Verification REVISE** (최종 CAUTIONARY 교부) | 내부 상태 수정 |
| SC-003 LegalAgent E2E | 72.79초·55,492토큰 | **359.23초·196,311토큰, LLM 92회** | 성능 병목 재평가 |
| SC-001 1차 LegalAgent E2E V8 2차 | 120.17초·63,655토큰 | 120.17초·63,655토큰 | 일치 |
| SC-003 LegalAgent E2E V8 2차 | 108.42초·31,016토큰 | 108.42초·31,016토큰 | 일치 |

**검증 원칙**: 변경 이전 보고서의 숫자를 복사하지 않았고, 사용자가 지정한 Trace ID를 통해 30건을 다시 집계했습니다.

## 5. 시나리오별 정답 요지

| Gold ID | 핵심 사실·법률 정답 | 필수 다음 행동 |
|---|---|---|
| SC001-S1 | 보증금 3억, 2026-04-01 해지통지 도달, 묵시적 갱신의 3개월 규정, 분할반환 제안 거절 | 통지·거절 자료 보관, 반환 요구, 점유·전입 보전 |
| SC001-S2 | 은행 가압류 7,200만(7/18), HUG 1억2천만(8/28), 후발 가압류와 선순위 근저당권·배당재원 구분 | 최신 등기사항전부증명서, 조세·선순위 권리, 경매 진행상태 확인 |
| SC001-S3 | 9/30 미반환, 점유·전입 유지, E17 반환보증 가입 미확인, 원금 3억 | 임차권등기 신청과 **등기 완료** 구별, 등기 완료 전 이사/전출 보류, 지급명령/소송 검토 |
| SC002-S1 | 보증금 2.2억, 반환 2천만+3천만=5천만(중복 거래 배제), 미반환 1.7억, 임대인의 추가 5천만 미입증 | 임차권등기 완료 확인, 금액 증빙 확보·내용증명, 반환소송 검토 |
| SC003-S1 | 2026-10-27 공포 → 2027-04-28 시행, 시행 후 체결·갱신·변경 계약부터 적용; 2026-11-01 신규계약에는 추가 신고항목 미적용 | 종전 신고사항 준수, 신고서식 확인, 미래 적용 계약 대비 |

## 6. 각 Trace ID별 평가 및 이유

다음 표의 법률·근거·대응 점수는 **AI 예비 채점**입니다. 정확도를 나타내는 객관적 독립 검증률로 해석해서는 안 됩니다.

| 사건 | 단계 | 서비스 | Trace ID | 법률(100) | 근거(100) | Next Action(%) | 처리(0/1) | 검증 상태 |
|---|---:|---|---|---:|---:|---:|---:|---|
| SC-001 | 1 | LegalChat | `d860ca38-be7a-42d2-acc3-eba8d97d7131` | 90 | 70 | 75 | 1 | NONE |
| SC-001 | 1 | LegalRag | `2490a3cf-d04c-4c6e-8f4b-ece8a46377dc` | 85 | 75 | 75 | 1 | NONE |
| SC-001 | 1 | LegalAgent POC | `635eb356-006a-4911-b7a9-7f5a4338c29b` | 95 | 95 | 100 | 1 | PASS |
| SC-001 | 1 | LegalAgent E2E | `620376c0-cf02-456b-b2ee-dfc5008855b0` | 95 | 95 | 100 | 1 | PASS |
| SC-001 | 1 | LegalAgent E2E V8 | `9a6ea3b1-5817-480d-a934-67eeb402ccab` | 95 | 90 | 87.5 | 1 | PASS |
| SC-001 | 1 | LegalAgent E2E V8 2차 | `8a1edfd9-4749-4f3e-847d-b5398a1ce385` | 95 | 90 | 87.5 | 1 | PASS |
| SC-001 | 2 | LegalChat | `4a6bb262-c3ef-4c81-b2d2-bc05bad6a21b` | 90 | 75 | 75 | 1 | NONE |
| SC-001 | 2 | LegalRag | `de5e6f16-7bc1-4acd-af4b-5022bc35782b` | 90 | 80 | 75 | 1 | NONE |
| SC-001 | 2 | LegalAgent POC | `67828544-db3b-4e94-8cc2-1657a265a91c` | 95 | 90 | 100 | 1 | PASS |
| SC-001 | 2 | LegalAgent E2E | `8acaa910-fe98-4daa-8b4d-9d94bb8b0147` | 95 | 95 | 100 | 1 | PASS |
| SC-001 | 2 | LegalAgent E2E V8 | `3fe378fc-1ac5-4c90-adf6-0de614c0e65d` | 95 | 90 | 87.5 | 1 | PASS |
| SC-001 | 2 | LegalAgent E2E V8 2차 | `bbe82634-4b9d-4f6d-b301-eb216214e333` | 95 | 90 | 87.5 | 1 | PASS |
| SC-001 | 3 | LegalChat | `8072caf6-e9d7-45cd-b9c3-a181f1200e39` | 90 | 75 | 80 | 1 | NONE |
| SC-001 | 3 | LegalRag | `dc9bca1f-4ba9-4da4-9eb3-7bbd0c576975` | 90 | 80 | 80 | 1 | NONE |
| SC-001 | 3 | LegalAgent POC | `35afce36-dea0-4eba-9077-8d9b89cf329d` | 95 | 90 | 100 | 1 | REVISE |
| SC-001 | 3 | LegalAgent E2E | `20fd1ab5-24ea-4b1e-8a73-d00b44f2549d` | 95 | 95 | 100 | 1 | PASS |
| SC-001 | 3 | LegalAgent E2E V8 | `d049beb7-f807-403c-b288-3012d9359db2` | 95 | 90 | 90 | 1 | PASS |
| SC-001 | 3 | LegalAgent E2E V8 2차 | `9ea1c180-cf37-45fc-85b3-fe6bf7dce8ae` | 95 | 90 | 90 | 1 | PASS |
| SC-002 | 1 | LegalChat | `0f35b09e-c6b4-47fd-bca5-034ca13c9849` | 95 | 85 | 100 | 1 | NONE |
| SC-002 | 1 | LegalRag | `020f194c-7a85-4e0b-82df-644d676af417` | 95 | 80 | 100 | 1 | NONE |
| SC-002 | 1 | LegalAgent POC | `07cc223a-ac34-4dfe-845a-6e6f0e86969d` | 95 | 90 | 100 | 1 | REVISE |
| SC-002 | 1 | LegalAgent E2E | `71d359c1-0d51-4f40-92df-d4eb2ba82828` | 100 | 95 | 100 | 1 | PASS |
| SC-002 | 1 | LegalAgent E2E V8 | `22da7384-3dfc-4522-a4ac-5107501db41b` | 95 | 85 | 90 | 1 | REVISE |
| SC-002 | 1 | LegalAgent E2E V8 2차 | `9feaf829-c86a-42a7-b208-6865a97a6235` | 100 | 95 | 100 | 1 | PASS |
| SC-003 | 1 | LegalChat | `83abd075-1474-481e-9624-e126792a7757` | 0 | 0 | 0 | 0 | NONE |
| SC-003 | 1 | LegalRag | `c8c770bb-ae14-4311-aa9e-eda54bbe67c5` | 0 | 0 | 0 | 0 | NONE |
| SC-003 | 1 | LegalAgent POC | `4062ee92-ed2e-47f9-81a9-cd0b2eb9a268` | 100 | 95 | 100 | 1 | PASS |
| SC-003 | 1 | LegalAgent E2E | `033755c3-d654-44df-ac3e-545c9e1ea67e` | 100 | 95 | 100 | 1 | PASS |
| SC-003 | 1 | LegalAgent E2E V8 | `cac6f0da-defe-498b-83bf-3a647591f0ef` | 95 | 90 | 83.33 | 1 | PASS |
| SC-003 | 1 | LegalAgent E2E V8 2차 | `aefa1b77-0c62-4cd0-892f-1bbbcefc1e40` | 90 | 85 | 83.33 | 1 | PASS |

### Trace별 평가 이유

- **SC-001 1차 / LegalChat** (`d860ca38`): 핵심 3억·해지통보·묵시적 갱신·분할반환 거절을 반영. 다만 주임법 제6조의2의 구체 조문 및 E01~E08 출처 연결이 약함. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_d860ca38-be7a-42d2-acc3-eba8d97d7131.json)
- **SC-001 1차 / LegalRag** (`2490a3cf`): 주요 결론과 E01~E08 인용은 타당하나 주택임대차의 특별 해지규정 대신 민법 제635조(건물 1개월)를 인용하며 주임법 제6조의2 원문 근거가 부족함. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_2490a3cf-d04c-4c6e-8f4b-ece8a46377dc.json)
- **SC-001 1차 / LegalAgent POC** (`635eb356`): E01~E08 및 주임법 제6조·제6조의2를 연결하고 합의 부존재·종료시점·동시이행관계를 설명. 전문가 검증 전 100점 확정 유보. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_635eb356-006a-4911-b7a9-7f5a4338c29b.json)
- **SC-001 1차 / LegalAgent E2E** (`620376c0`): 계약·도달·3개월·분할변제 무합의를 설명하고 임차권등기·보전 안내. CAUTIONARY는 경계 안내로 처리; 속도는 원본 실측으로 보정. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_620376c0-cf02-456b-b2ee-dfc5008855b0.json)
- **SC-001 1차 / LegalAgent E2E V8** (`9a6ea3b1`): 종료·3개월·보전조치가 맞지만 Trace의 최종 답변에 '[총 ...자 축약]'이 포함되어 세부 근거 전수 확인이 불가. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9a6ea3b1-5817-480d-a934-67eeb402ccab.json)
- **SC-001 1차 / LegalAgent E2E V8 2차** (`8a1edfd9`): E01/E04/E05 및 제6조의2를 연결하고 3개월 적용이 타당. 다만 최종 답변이 일부 축약되어 전체 출처·행동 순서 검토가 제한됨. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8a1edfd9-4749-4f3e-847d-b5398a1ce385.json)
- **SC-001 2차 / LegalChat** (`4a6bb262`): 가압류 자체로 임차인 권리가 소멸하지 않고 배당재원·선순위 권리 확인 필요성을 제시. 정확한 조문 인용은 부족. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_4a6bb262-c3ef-4c81-b2d2-bc05bad6a21b.json)
- **SC-001 2차 / LegalRag** (`de5e6f16`): 은행 7,200만/HUG 1억2천만과 가압류·근저당 차이를 인식. 민법 제356조 등의 일반 담보권 중심 인용으로 우선변제 법령의 직접근거가 다소 약함. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_de5e6f16-7bc1-4acd-af4b-5022bc35782b.json)
- **SC-001 2차 / LegalAgent POC** (`67828544`): E03/E09/E10 인용과 가압류의 순위 비교를 반영. 다만 열람 메모만으로 모든 선순위를 단정하지 않는 조건부 주의 필요. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_67828544-db3b-4e94-8cc2-1657a265a91c.json)
- **SC-001 2차 / LegalAgent E2E** (`8acaa910`): 주임법 제3조·제3조의2 및 E09~E11로 대항력/우선변제·회수 위험을 분리. 낙찰가·조세 미확인을 표시함. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8acaa910-fe98-4daa-8b4d-9d94bb8b0147.json)
- **SC-001 2차 / LegalAgent E2E V8** (`3fe378fc`): 가압류의 후순위 가능성 및 원본등기·조세 확인 필요성 반영. 답변 전문 일부 축약으로 세부 출처의 전수검증 보류. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_3fe378fc-1ac5-4c90-adf6-0de614c0e65d.json)
- **SC-001 2차 / LegalAgent E2E V8 2차** (`bbe82634`): E03/E09/E10/E11과 법령 조문을 연결하고 후발 가압류와 전액 회수 보장 금지를 구분. 축약 Trace로 전체 조치 항목 확인 제한. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_bbe82634-4b9d-4f6d-b301-eb216214e333.json)
- **SC-001 3차 / LegalChat** (`8072caf6`): 점유·전입 유지, 임차권등기, 소송 등 조치 방향은 적절. E15~E17 사실 출처와 반환보증 미확인에 대한 구조화가 상대적으로 약함. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_8072caf6-e9d7-45cd-b9c3-a181f1200e39.json)
- **SC-001 3차 / LegalRag** (`dc9bca1f`): 권리보전과 명령 신청/등기 효력 안내는 유용하나 출처 정밀성과 신청·등기 완료의 표현 검토 필요. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_dc9bca1f-4ba9-4da4-9eb3-7bbd0c576975.json)
- **SC-001 3차 / LegalAgent POC** (`35afce36`): 미반환·점유와 권리보전, 법원 절차를 종합하고 경매/환급을 보장하지 않음. 서면 답변의 법령 적용은 추가 전문가 확인 필요. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_35afce36-dea0-4eba-9077-8d9b89cf329d.json)
- **SC-001 3차 / LegalAgent E2E** (`20fd1ab5`): E15~E17·주임법 제3조의3·권리보전·집행권원 확보를 연결하여 실행순서를 안내. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_20fd1ab5-24ea-4b1e-8a73-d00b44f2549d.json)
- **SC-001 3차 / LegalAgent E2E V8** (`d049beb7`): 임차권등기 완료 후 이사 및 지급명령/소송을 안내. 최종 답변 축약으로 반환보증 확인 등 전 항목 대조 제한. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_d049beb7-f807-403c-b288-3012d9359db2.json)
- **SC-001 3차 / LegalAgent E2E V8 2차** (`9ea1c180`): 이사 전 점유·전입 보전과 반환소송 방향은 적절. 서두의 '임차권등기명령 신청해 ... 이동'은 실제 등기 완료 요건을 더 명료하게 표현해야 함. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9ea1c180-cf37-45fc-85b3-fe6bf7dce8ae.json)
- **SC-002 1차 / LegalChat** (`0f35b09e`): 원금 2.2억−실제 반환 2천만·3천만=1.7억 및 임대인의 1억 주장 미입증을 구분. 법령 출처 직접 확인과 동일 거래 식별 설명은 보강 여지. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_0f35b09e-c6b4-47fd-bca5-034ca13c9849.json)
- **SC-002 1차 / LegalRag** (`020f194c`): 2건 반환액 합계·등기 완료 전 이사 위험을 정확히 안내. 검색 도구가 관련 조문 회수에 실패했다고 명시하여 근거 정확도 감점. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_020f194c-7a85-4e0b-82df-644d676af417.json)
- **SC-002 1차 / LegalAgent POC** (`07cc223a`): 잔액 1.7억, 반환 주장 미입증, 임차권등기 신청/완료를 구분. 내부 검증 최종 REVISE이므로 PASS로 표시 금지. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_07cc223a-ac34-4dfe-845a-6e6f0e86969d.json)
- **SC-002 1차 / LegalAgent E2E** (`71d359c1`): 실제 변제 5천만·상대방 주장 1억·등기 미완료·절차를 정확히 연결하고 법률 근거를 제시. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_71d359c1-0d51-4f40-92df-d4eb2ba82828.json)
- **SC-002 1차 / LegalAgent E2E V8** (`22da7384`): 미반환 1.7억 판단은 맞으나 원본 Trace 검증 상태는 REVISE이며 최종문 축약; 전부 100점 부여는 근거 부족. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_22da7384-3dfc-4522-a4ac-5107501db41b.json)
- **SC-002 1차 / LegalAgent E2E V8 2차** (`9feaf829`): 중복 반영 없는 5천만 실입금·1.7억 잔액·등기 완료 전 이사 위험 안내 적절. 발췌된 답변 범위에서 근거 확인 가능. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_9feaf829-c86a-42a7-b208-6865a97a6235.json)
- **SC-003 1차 / LegalChat** (`83abd075`): 중대오류: 2026-10-27 공포를 시행으로 오인하여 2026-11-01 계약에 관리비·공과금 신고의무가 있다고 안내. 정답은 부칙상 2027-04-28 이후 계약부터 적용. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_83abd075-1474-481e-9624-e126792a7757.json)
- **SC-003 1차 / LegalRag** (`c8c770bb`): 중대오류: 관련 시행령·부칙 원문 대신 다른 법령을 검색하여 미시행 신고항목을 현재 계약에 적용. 과태료·서식 판단도 신뢰 불가. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_c8c770bb-ae14-4311-aa9e-eda54bbe67c5.json)
- **SC-003 1차 / LegalAgent POC** (`4062ee92`): 시행일 2027-04-28, 부칙 제2조의 시행 후 체결/갱신/변경 적용례를 정확히 설명. 2026-11-01 계약에는 새로운 신고항목 미적용. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_4062ee92-ed2e-47f9-81a9-cd0b2eb9a268.json)
- **SC-003 1차 / LegalAgent E2E** (`033755c3`): 법 제46조·시행령 제36조·부칙 제2조 및 계약일 대비 시행일을 구분. 정답이나 359.23초·92 LLM 호출의 성능 병목 확인. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_033755c3-d654-44df-ac3e-545c9e1ea67e.json)
- **SC-003 1차 / LegalAgent E2E V8** (`cac6f0da`): 2026-11-01 미적용과 2027-04-28 이후 적용례를 명시. 최종 답변은 축약되어 적용례 전체 문구 확인에 제한. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_cac6f0da-defe-498b-83bf-3a647591f0ef.json)
- **SC-003 1차 / LegalAgent E2E V8 2차** (`aefa1b77`): 핵심 결론(2026-11-01 미적용)·시행일은 맞음. 그러나 답변 첫 단어 '네'는 뒤의 '신고해야 한다고 보기 어렵다'와 양립하지 않는 혼동을 줄 수 있고, 부칙 적용례 명시가 약함. [원본 Trace](https://github.com/yjjungyo/ai-legal-helper/blob/main/artifacts/langfuse_trace_export/E2E_V8_stepbatch_LegalAgent_E2E_V8_aefa1b77-0c62-4cd0-892f-1bbbcefc1e40.json)

## 7. 정량적 목표(KPI) 측정 상태

| KPI | 목표 | V8 2차 현 수준 | 근거·결론 |
|---|---|---|---|
| **핵심 사실 추출 정확도** | 정밀도·재현율 각각 90% 이상 | **N/A (측정 불가)** | 상담 Trace에는 Fact 추출 노드 원시 출력 및 TP/FP/FN의 분모가 없음. 별도 Fact 추출 Trace 필요 |
| **법령·판례 근거 정확도** | 95% 이상 | **AI 예비 평가 90.0/100 (미달)** | 법령 조문·증거 출처·시점·적용례와 답변을 대조한 잠정 점수; 전문가 검토 전 확정 금지 |
| **필수 대응절차 안내 완성도** | 90% 이상 | **AI 예비 평가 89.7% (미달)** | 골드 필수 행동의 완전/부분 포함 여부 기준. 긴 답변 축약 등으로 일부 항목 확증 불가 |

### 사실 추출을 별도 측정해야 하는 이유

상담 Trace에는 E01~E17 원문을 이용한 답변 생성과 검증 과정이 기록되어 있으나, 증거 원문→사실 후보 추출 단계의 **전체 후보 리스트 및 사용자 승인 결과가 없습니다**. Gold와 답변의 키워드가 같다는 이유로 Precision/Recall 100%라고 발표하면 KPI 정의를 위반합니다. 미측정은 0점도 100점도 아니며 **N/A**입니다. SC-003은 처음부터 증거문서가 없으므로 해당 지표 적용 자체가 성립하지 않습니다.

## 8. 품질 개선 우선순위

1. **SC-003 법령 적용의 일관성**: 공포일/시행일/부칙 적용례를 기준으로 판단하고, 첫 문장의 긍정·부정 표현과 결론의 모순을 검사합니다.
2. **V8 최종 답변 원문 보존**: 실제 Trace의 `final_answer`에 `[총 ...자 축약]` 텍스트가 포함되어 있어 전체 법률 인용을 재검증할 수 없습니다. Trace 기록량 한도와 실제 사용자 출력의 차이를 구분하고, 평가용 원문을 별도 보존해야 합니다.
3. **SC-002 Verification 반복/오탐 점검**: V8 1차는 최종 Verification `REVISE`로 기록되어 있으며 PASS로 변경하지 않습니다. 실패 이유를 정확히 확인한 뒤 수정·재검증합니다.
4. **SC-003 E2E 병목 재조사**: 실제 92회 LLM Generation, 359.23초가 집계되었습니다. 이전 보고서의 72.79초 기록은 해당 Trace와 일치하지 않아 원인 분석이 필요합니다.
5. **추출 KPI 실측용 별도 실행**: 증거 등록/추출/HITL 승인 Trace와 Gold Fact 단위를 연결하여 TP/FP/FN을 독립 집계합니다.

## 9. 산출물 및 근거 파일

- [엑셀 KPI 파일](./AI_Legal_Helper_KPI_202611151124_자동평가-E2EV8-2차_chatgpt.xlsx) — 각 시트의 Trace ID 일치 여부로 행 갱신
- [상세 Gold Set·채점 기준](./AI_Legal_Helper_E2E_V8_2차_정답지_채점기준.md)
- [원본 재집계 및 30개 평가 이유 JSON](./E2E_V8_2차_GOLD_채점근거.json)
- [기존 2차 보고서](./AI_Legal_Helper_E2E_V8_2차_Report.md) — 이번 재평가와 수치 차이 명시
- [Trace 원본 폴더](https://github.com/yjjungyo/ai-legal-helper/tree/main/artifacts/langfuse_trace_export)

**평가 한계**: 본 보고서는 제공된 Trace·정답지와 확인 가능한 자료를 바탕으로 작성한 AI 서면 평가입니다. 공식 법령 원문 및 개별 사건의 실제 법률 판단에 관한 전문가의 독립 검증을 대체하지 않습니다.
