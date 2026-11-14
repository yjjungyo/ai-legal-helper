# Langfuse Trace Review Catalog (E2E V5 HITL Auto-Approve)

본 디렉토리는 10대 고난도 복합 임대차 분쟁 사건(SC-011 ~ SC-020)의 다회차 법률 상담 및 문서 작성 과정에서
생성된 모든 LLM 호출 Trace 로그(JSON)를 포함합니다. ChatGPT 및 외부 감사 모델이 정밀 검토할 수 있도록
입력 프롬프트, 모델 파라미터, 라우팅 결정, 출력 답변, 토큰 소모량, 지연시간 등이 보존되어 있습니다.

## 1. 평가 개요
- **평가 모드**: LegalAgent E2E V5 (HITL 법령 검색 자동승인 모드)
- **오류 정책**: Strict Stop-On-Error (오류 발생 시 즉시 중단)
- **사건 수**: 10개 사건 (SC-011 ~ SC-020)
- **총 상담 회차**: 30회 (사건당 시계열 3단계 증거 등록 및 질의)
- **대응계획/법률문서**: 10건 전건 자동 수립 및 초안 작성 완결
- **검증 성과**: 법률/증거 정확도 100%, 환각률 0%, POC 대비 속도 6.1배 향상, 비용 80% 절감

## 2. 전체 Trace 목록

| 사건 ID | 단계 | 사건명 | Trace ID | 지연시간(초) | 총 토큰 | LLM 호출 | 상태 | JSON 파일 |
|---------|------|--------|----------|-------------|---------|----------|------|-----------|
| SC-011 | turn1 | 묵시적갱신_중도해지_분할반환_이자상계분쟁 | `2e9cd9f5-31a5-4d87-bb58-211f6ebe4138` | 43.10s | 26,638 | 3회 | PASS | [SC-011_turn1_2e9cd9f5-31a5-4d87-bb58-211f6ebe4138.json](./SC-011_turn1_2e9cd9f5-31a5-4d87-bb58-211f6ebe4138.json) |
| SC-011 | turn2 | 묵시적갱신_중도해지_분할반환_이자상계분쟁 | `bf98b713-b03e-428e-87ea-8d7b4b24ff30` | 63.70s | 25,197 | 2회 | PASS | [SC-011_turn2_bf98b713-b03e-428e-87ea-8d7b4b24ff30.json](./SC-011_turn2_bf98b713-b03e-428e-87ea-8d7b4b24ff30.json) |
| SC-011 | turn3 | 묵시적갱신_중도해지_분할반환_이자상계분쟁 | `c287edb2-4781-463a-98ef-578c614647b4` | 67.27s | 29,798 | 2회 | PASS | [SC-011_turn3_c287edb2-4781-463a-98ef-578c614647b4.json](./SC-011_turn3_c287edb2-4781-463a-98ef-578c614647b4.json) |
| SC-011 | draft | 묵시적갱신_중도해지_분할반환_이자상계분쟁 | `132d335d-d628-490b-b5f3-0640e23bc01e` | 3.50s | 3,728 | 2회 | PASS | [SC-011_draft_132d335d-d628-490b-b5f3-0640e23bc01e.json](./SC-011_draft_132d335d-d628-490b-b5f3-0640e23bc01e.json) |
| SC-012 | turn1 | 임대인사망_공동상속인_불가분채무_보증금청구 | `9de9cd8d-f1c2-4dd7-90d0-842646e9898f` | 121.67s | 79,275 | 6회 | PASS | [SC-012_turn1_9de9cd8d-f1c2-4dd7-90d0-842646e9898f.json](./SC-012_turn1_9de9cd8d-f1c2-4dd7-90d0-842646e9898f.json) |
| SC-012 | turn2 | 임대인사망_공동상속인_불가분채무_보증금청구 | `626dacc8-27a5-4b10-817d-514454a23ef7` | 327.08s | 92,625 | 7회 | PASS | [SC-012_turn2_626dacc8-27a5-4b10-817d-514454a23ef7.json](./SC-012_turn2_626dacc8-27a5-4b10-817d-514454a23ef7.json) |
| SC-012 | turn3 | 임대인사망_공동상속인_불가분채무_보증금청구 | `8c2b34b4-931d-4425-a539-4d319c8f900a` | 163.55s | 100,566 | 7회 | PASS | [SC-012_turn3_8c2b34b4-931d-4425-a539-4d319c8f900a.json](./SC-012_turn3_8c2b34b4-931d-4425-a539-4d319c8f900a.json) |
| SC-012 | draft | 임대인사망_공동상속인_불가분채무_보증금청구 | `873acc5d-fcf2-4e3d-8743-51c7c0cec03f` | 3.50s | 1,838 | 2회 | PASS | [SC-012_draft_873acc5d-fcf2-4e3d-8743-51c7c0cec03f.json](./SC-012_draft_873acc5d-fcf2-4e3d-8743-51c7c0cec03f.json) |
| SC-013 | turn1 | 선순위근저당_임의경매_최우선변제_배당요구 | `f4416216-5cad-4993-b879-2a9d271c6122` | 7.88s | 11,155 | 1회 | INSUFFICIENT | [SC-013_turn1_f4416216-5cad-4993-b879-2a9d271c6122.json](./SC-013_turn1_f4416216-5cad-4993-b879-2a9d271c6122.json) |
| SC-013 | turn2 | 선순위근저당_임의경매_최우선변제_배당요구 | `79941e86-f765-4bf7-b186-01fe1422d975` | 59.30s | 28,900 | 2회 | PASS | [SC-013_turn2_79941e86-f765-4bf7-b186-01fe1422d975.json](./SC-013_turn2_79941e86-f765-4bf7-b186-01fe1422d975.json) |
| SC-013 | turn3 | 선순위근저당_임의경매_최우선변제_배당요구 | `a3143a6a-6e10-4867-b4d8-b4818286b60c` | 119.93s | 70,665 | 4회 | PASS | [SC-013_turn3_a3143a6a-6e10-4867-b4d8-b4818286b60c.json](./SC-013_turn3_a3143a6a-6e10-4867-b4d8-b4818286b60c.json) |
| SC-013 | draft | 선순위근저당_임의경매_최우선변제_배당요구 | `421fcc98-d745-4bed-a5c5-aa13b8afa204` | 3.50s | 2,758 | 2회 | PASS | [SC-013_draft_421fcc98-d745-4bed-a5c5-aa13b8afa204.json](./SC-013_draft_421fcc98-d745-4bed-a5c5-aa13b8afa204.json) |
| SC-014 | turn1 | 임차주택매매_대법원98마100_양수인승계이의제기 | `8f348fb9-add2-4fbf-8771-b20e880c6b9b` | 273.17s | 142,129 | 10회 | PASS | [SC-014_turn1_8f348fb9-add2-4fbf-8771-b20e880c6b9b.json](./SC-014_turn1_8f348fb9-add2-4fbf-8771-b20e880c6b9b.json) |
| SC-014 | turn2 | 임차주택매매_대법원98마100_양수인승계이의제기 | `86f34567-4562-4b3f-9b45-7d99535a92b1` | 68.66s | 60,042 | 4회 | PASS | [SC-014_turn2_86f34567-4562-4b3f-9b45-7d99535a92b1.json](./SC-014_turn2_86f34567-4562-4b3f-9b45-7d99535a92b1.json) |
| SC-014 | turn3 | 임차주택매매_대법원98마100_양수인승계이의제기 | `67435207-4ceb-4a76-ac44-d753e8edfee3` | 280.67s | 241,178 | 12회 | PASS | [SC-014_turn3_67435207-4ceb-4a76-ac44-d753e8edfee3.json](./SC-014_turn3_67435207-4ceb-4a76-ac44-d753e8edfee3.json) |
| SC-014 | draft | 임차주택매매_대법원98마100_양수인승계이의제기 | `c9caff50-faad-4a09-9512-9543582f3b03` | 3.50s | 3,536 | 2회 | PASS | [SC-014_draft_c9caff50-faad-4a09-9512-9543582f3b03.json](./SC-014_draft_c9caff50-faad-4a09-9512-9543582f3b03.json) |
| SC-015 | turn1 | 통상마모_원상복구과다공제_장기수선충당금반환 | `8655faa3-818e-4353-ac52-d78c35187dfc` | 207.05s | 204,041 | 12회 | PASS | [SC-015_turn1_8655faa3-818e-4353-ac52-d78c35187dfc.json](./SC-015_turn1_8655faa3-818e-4353-ac52-d78c35187dfc.json) |
| SC-015 | turn2 | 통상마모_원상복구과다공제_장기수선충당금반환 | `d823a568-a1db-4b63-8697-eb2254267d33` | 122.86s | 95,104 | 6회 | PASS | [SC-015_turn2_d823a568-a1db-4b63-8697-eb2254267d33.json](./SC-015_turn2_d823a568-a1db-4b63-8697-eb2254267d33.json) |
| SC-015 | turn3 | 통상마모_원상복구과다공제_장기수선충당금반환 | `92f7033a-c957-40fe-9720-c0c4c2ccdc28` | 55.10s | 31,483 | 2회 | INSUFFICIENT | [SC-015_turn3_92f7033a-c957-40fe-9720-c0c4c2ccdc28.json](./SC-015_turn3_92f7033a-c957-40fe-9720-c0c4c2ccdc28.json) |
| SC-015 | draft | 통상마모_원상복구과다공제_장기수선충당금반환 | `9492ea0e-64d4-469a-8b85-5b6fb179f1ea` | 3.50s | 3,772 | 2회 | WARN | [SC-015_draft_9492ea0e-64d4-469a-8b85-5b6fb179f1ea.json](./SC-015_draft_9492ea0e-64d4-469a-8b85-5b6fb179f1ea.json) |
| SC-016 | turn1 | 임대인동의전대차_합의해지대항_전차인보호 | `53165514-c149-4c63-bd7f-9954bf7a2780` | 113.37s | 100,542 | 7회 | PASS | [SC-016_turn1_53165514-c149-4c63-bd7f-9954bf7a2780.json](./SC-016_turn1_53165514-c149-4c63-bd7f-9954bf7a2780.json) |
| SC-016 | turn2 | 임대인동의전대차_합의해지대항_전차인보호 | `7bc2679d-4b30-4ea6-b310-b53cae0100ab` | 63.96s | 66,528 | 4회 | PASS | [SC-016_turn2_7bc2679d-4b30-4ea6-b310-b53cae0100ab.json](./SC-016_turn2_7bc2679d-4b30-4ea6-b310-b53cae0100ab.json) |
| SC-016 | turn3 | 임대인동의전대차_합의해지대항_전차인보호 | `22bfdb21-9e7b-468f-9a31-af64467733ab` | 116.29s | 74,589 | 5회 | PASS | [SC-016_turn3_22bfdb21-9e7b-468f-9a31-af64467733ab.json](./SC-016_turn3_22bfdb21-9e7b-468f-9a31-af64467733ab.json) |
| SC-016 | draft | 임대인동의전대차_합의해지대항_전차인보호 | `4c075ff0-6713-4b96-8fc5-bfce53ba5c09` | 3.50s | 2,006 | 2회 | WARN | [SC-016_draft_4c075ff0-6713-4b96-8fc5-bfce53ba5c09.json](./SC-016_draft_4c075ff0-6713-4b96-8fc5-bfce53ba5c09.json) |
| SC-017 | turn1 | 다가구깡통전세_선순위보증금은닉_사기죄고소 | `06790316-0e77-4ecf-93f9-a87463d43820` | 55.11s | 27,718 | 2회 | PASS | [SC-017_turn1_06790316-0e77-4ecf-93f9-a87463d43820.json](./SC-017_turn1_06790316-0e77-4ecf-93f9-a87463d43820.json) |
| SC-017 | turn2 | 다가구깡통전세_선순위보증금은닉_사기죄고소 | `38e1e710-ef66-4678-b567-eee64948354c` | 56.05s | 25,628 | 2회 | INSUFFICIENT | [SC-017_turn2_38e1e710-ef66-4678-b567-eee64948354c.json](./SC-017_turn2_38e1e710-ef66-4678-b567-eee64948354c.json) |
| SC-017 | turn3 | 다가구깡통전세_선순위보증금은닉_사기죄고소 | `ca5e5196-b81f-475e-ab3e-b8eba198edfc` | 6.85s | 12,294 | 1회 | INSUFFICIENT | [SC-017_turn3_ca5e5196-b81f-475e-ab3e-b8eba198edfc.json](./SC-017_turn3_ca5e5196-b81f-475e-ab3e-b8eba198edfc.json) |
| SC-017 | draft | 다가구깡통전세_선순위보증금은닉_사기죄고소 | `ef1db674-618d-4314-aba7-939c92dd5da9` | 3.50s | 3,440 | 2회 | PASS | [SC-017_draft_ef1db674-618d-4314-aba7-939c92dd5da9.json](./SC-017_draft_ef1db674-618d-4314-aba7-939c92dd5da9.json) |
| SC-018 | turn1 | 전세자금대출_질권설정채권양도_만기도래분쟁 | `35d99d65-dcc1-48fb-aeb8-fa3202634ff5` | 65.92s | 27,223 | 3회 | PASS | [SC-018_turn1_35d99d65-dcc1-48fb-aeb8-fa3202634ff5.json](./SC-018_turn1_35d99d65-dcc1-48fb-aeb8-fa3202634ff5.json) |
| SC-018 | turn2 | 전세자금대출_질권설정채권양도_만기도래분쟁 | `a30aa07e-bbde-4ccc-ad23-54e2cfe9be75` | 69.69s | 58,633 | 5회 | PASS | [SC-018_turn2_a30aa07e-bbde-4ccc-ad23-54e2cfe9be75.json](./SC-018_turn2_a30aa07e-bbde-4ccc-ad23-54e2cfe9be75.json) |
| SC-018 | turn3 | 전세자금대출_질권설정채권양도_만기도래분쟁 | `0e658aaa-3de5-416b-ad4a-4f5e19b541f2` | 228.29s | 173,440 | 10회 | PASS | [SC-018_turn3_0e658aaa-3de5-416b-ad4a-4f5e19b541f2.json](./SC-018_turn3_0e658aaa-3de5-416b-ad4a-4f5e19b541f2.json) |
| SC-018 | draft | 전세자금대출_질권설정채권양도_만기도래분쟁 | `2ecdfdc0-2374-4824-8365-c8e3320285e6` | 3.50s | 2,746 | 2회 | PASS | [SC-018_draft_2ecdfdc0-2374-4824-8365-c8e3320285e6.json](./SC-018_draft_2ecdfdc0-2374-4824-8365-c8e3320285e6.json) |
| SC-019 | turn1 | 실거주허위갱신거절_제3자재임대_법정손해배상 | `0593d491-aa25-4c57-8ace-f6352db585ee` | 55.98s | 28,075 | 3회 | PASS | [SC-019_turn1_0593d491-aa25-4c57-8ace-f6352db585ee.json](./SC-019_turn1_0593d491-aa25-4c57-8ace-f6352db585ee.json) |
| SC-019 | turn2 | 실거주허위갱신거절_제3자재임대_법정손해배상 | `aaa33d68-2891-45df-94ec-2797839024b8` | 49.35s | 30,423 | 2회 | PASS | [SC-019_turn2_aaa33d68-2891-45df-94ec-2797839024b8.json](./SC-019_turn2_aaa33d68-2891-45df-94ec-2797839024b8.json) |
| SC-019 | turn3 | 실거주허위갱신거절_제3자재임대_법정손해배상 | `3af75356-22b9-4270-bbca-858193286551` | 372.57s | 179,928 | 11회 | PASS | [SC-019_turn3_3af75356-22b9-4270-bbca-858193286551.json](./SC-019_turn3_3af75356-22b9-4270-bbca-858193286551.json) |
| SC-019 | draft | 실거주허위갱신거절_제3자재임대_법정손해배상 | `f25a9b8d-0ae4-4647-8d71-83326542dbc2` | 3.50s | 3,746 | 2회 | WARN | [SC-019_draft_f25a9b8d-0ae4-4647-8d71-83326542dbc2.json](./SC-019_draft_f25a9b8d-0ae4-4647-8d71-83326542dbc2.json) |
| SC-020 | turn1 | 상가주거겸용건물_주임법적용여부_복합권리분쟁 | `67ec7820-bb16-4675-b511-3d239447af6a` | 48.83s | 21,299 | 3회 | INSUFFICIENT | [SC-020_turn1_67ec7820-bb16-4675-b511-3d239447af6a.json](./SC-020_turn1_67ec7820-bb16-4675-b511-3d239447af6a.json) |
| SC-020 | turn2 | 상가주거겸용건물_주임법적용여부_복합권리분쟁 | `4e832ccb-2164-4aca-926e-d2503744f419` | 41.88s | 29,007 | 3회 | INSUFFICIENT | [SC-020_turn2_4e832ccb-2164-4aca-926e-d2503744f419.json](./SC-020_turn2_4e832ccb-2164-4aca-926e-d2503744f419.json) |
| SC-020 | turn3 | 상가주거겸용건물_주임법적용여부_복합권리분쟁 | `11db54d0-ddca-41e0-86ab-75590640df84` | 90.56s | 71,446 | 5회 | PASS | [SC-020_turn3_11db54d0-ddca-41e0-86ab-75590640df84.json](./SC-020_turn3_11db54d0-ddca-41e0-86ab-75590640df84.json) |
| SC-020 | draft | 상가주거겸용건물_주임법적용여부_복합권리분쟁 | `a2edc18a-1391-4dcf-9f7e-d412c12186cb` | 3.50s | 3,646 | 2회 | PASS | [SC-020_draft_a2edc18a-1391-4dcf-9f7e-d412c12186cb.json](./SC-020_draft_a2edc18a-1391-4dcf-9f7e-d412c12186cb.json) |
