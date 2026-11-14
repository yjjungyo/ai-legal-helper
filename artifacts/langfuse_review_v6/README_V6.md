# Langfuse Trace Review Catalog (E2E V6 HITL Auto-Approve & k=10 RAG)

본 디렉토리는 10대 고난도 복합 임대차 분쟁 사건(SC-011 ~ SC-020)의 다회차 법률 상담 및 문서 작성 과정에서
생성된 모든 LLM 호출 Trace 로그(JSON)를 포함합니다. ChatGPT 및 외부 감사 모델이 정밀 검토할 수 있도록
입력 프롬프트, 모델 파라미터, 라우팅 결정, 출력 답변, 토큰 소모량, 지연시간 등이 영구 보존되어 있습니다.

## 1. 평가 개요
- **평가 모드**: LegalAgent E2E V6 (HITL 법령 검색 자동승인 + k=10 공통 RAG + Fast Retrieval)
- **오류 정책**: Strict Stop-On-Error (오류 발생 시 즉시 중단)
- **사건 수**: 10개 사건 (SC-011 ~ SC-020)
- **사건 등록 타이틀**: `[사건ID] 사건명 20261114_E2E_V6`
- **총 상담 회차**: 30회 (사건당 시계열 3단계 증거 등록 및 질의)
- **대응계획/법률문서**: 10건 전건 자동 수립 및 초안 작성 완결

## 2. 전체 Trace 목록

| 사건 ID | 단계 | 사건명 | Trace ID | 지연시간(초) | 총 토큰 | LLM 호출 | 상태 | JSON 파일 |
|---------|------|--------|----------|-------------|---------|----------|------|-----------|
| SC-011 | turn1 | 묵시적갱신_중도해지_분할반환_이자상계분쟁 | `07e1be00-3973-4334-b1f2-11ba2000a1b9` | 36.31s | 27,433 | 2회 | PASS | [SC-011_turn1_07e1be00-3973-4334-b1f2-11ba2000a1b9.json](./SC-011_turn1_07e1be00-3973-4334-b1f2-11ba2000a1b9.json) |
| SC-011 | turn2 | 묵시적갱신_중도해지_분할반환_이자상계분쟁 | `16bbac41-bac1-4bb5-9e99-ed17e9b9f4ce` | 36.69s | 29,966 | 2회 | PASS | [SC-011_turn2_16bbac41-bac1-4bb5-9e99-ed17e9b9f4ce.json](./SC-011_turn2_16bbac41-bac1-4bb5-9e99-ed17e9b9f4ce.json) |
| SC-011 | turn3 | 묵시적갱신_중도해지_분할반환_이자상계분쟁 | `32c22fbb-a8d2-4cee-b4eb-143ec5353272` | 72.49s | 77,350 | 4회 | PASS | [SC-011_turn3_32c22fbb-a8d2-4cee-b4eb-143ec5353272.json](./SC-011_turn3_32c22fbb-a8d2-4cee-b4eb-143ec5353272.json) |
| SC-011 | draft | 묵시적갱신_중도해지_분할반환_이자상계분쟁 | `8a7b66f5-8ce0-4d1a-8fca-85e1052fcdf3` | 3.00s | 2,418 | 2회 | PASS | [SC-011_draft_8a7b66f5-8ce0-4d1a-8fca-85e1052fcdf3.json](./SC-011_draft_8a7b66f5-8ce0-4d1a-8fca-85e1052fcdf3.json) |
| SC-012 | turn1 | 임대인사망_공동상속인_불가분채무_보증금청구 | `f5a61fe6-5033-4068-b499-111e08cda89d` | 83.77s | 110,954 | 8회 | INSUFFICIENT | [SC-012_turn1_f5a61fe6-5033-4068-b499-111e08cda89d.json](./SC-012_turn1_f5a61fe6-5033-4068-b499-111e08cda89d.json) |
| SC-012 | turn2 | 임대인사망_공동상속인_불가분채무_보증금청구 | `839797fd-21af-459f-be1d-23ddb4098a35` | 211.72s | 197,375 | 11회 | INSUFFICIENT | [SC-012_turn2_839797fd-21af-459f-be1d-23ddb4098a35.json](./SC-012_turn2_839797fd-21af-459f-be1d-23ddb4098a35.json) |
| SC-012 | turn3 | 임대인사망_공동상속인_불가분채무_보증금청구 | `39240f42-ceea-4eef-9f37-12178414a712` | 179.01s | 206,778 | 11회 | INSUFFICIENT | [SC-012_turn3_39240f42-ceea-4eef-9f37-12178414a712.json](./SC-012_turn3_39240f42-ceea-4eef-9f37-12178414a712.json) |
| SC-012 | draft | 임대인사망_공동상속인_불가분채무_보증금청구 | `725e0d7d-b0ee-4e9e-a7d5-b85ebbdf2b68` | 3.00s | 2,462 | 2회 | PASS | [SC-012_draft_725e0d7d-b0ee-4e9e-a7d5-b85ebbdf2b68.json](./SC-012_draft_725e0d7d-b0ee-4e9e-a7d5-b85ebbdf2b68.json) |
| SC-013 | turn1 | 선순위근저당_임의경매_최우선변제_배당요구 | `3f3069dc-7c1c-4563-915b-aa26e95d0e04` | 144.18s | 66,743 | 4회 | PASS | [SC-013_turn1_3f3069dc-7c1c-4563-915b-aa26e95d0e04.json](./SC-013_turn1_3f3069dc-7c1c-4563-915b-aa26e95d0e04.json) |
| SC-013 | turn2 | 선순위근저당_임의경매_최우선변제_배당요구 | `30c0a62d-465a-48a8-94df-3958754170e9` | 74.55s | 34,523 | 2회 | PASS | [SC-013_turn2_30c0a62d-465a-48a8-94df-3958754170e9.json](./SC-013_turn2_30c0a62d-465a-48a8-94df-3958754170e9.json) |
| SC-013 | turn3 | 선순위근저당_임의경매_최우선변제_배당요구 | `b8563af4-6729-497f-831f-f953d8d2c708` | 143.84s | 85,672 | 4회 | PASS | [SC-013_turn3_b8563af4-6729-497f-831f-f953d8d2c708.json](./SC-013_turn3_b8563af4-6729-497f-831f-f953d8d2c708.json) |
| SC-013 | draft | 선순위근저당_임의경매_최우선변제_배당요구 | `0d0e2b41-a08d-487a-b9ab-d89f1a7f3caf` | 3.00s | 1,752 | 2회 | PASS | [SC-013_draft_0d0e2b41-a08d-487a-b9ab-d89f1a7f3caf.json](./SC-013_draft_0d0e2b41-a08d-487a-b9ab-d89f1a7f3caf.json) |
| SC-014 | turn1 | 임차주택매매_대법원98마100_양수인승계이의제기 | `39676d05-11ba-4d67-a213-84f8f4dcfaf5` | 134.53s | 64,670 | 5회 | PASS | [SC-014_turn1_39676d05-11ba-4d67-a213-84f8f4dcfaf5.json](./SC-014_turn1_39676d05-11ba-4d67-a213-84f8f4dcfaf5.json) |
| SC-014 | turn2 | 임차주택매매_대법원98마100_양수인승계이의제기 | `2d31fd57-be36-4ab4-8eac-c34ae5966e5f` | 53.33s | 61,219 | 4회 | PASS | [SC-014_turn2_2d31fd57-be36-4ab4-8eac-c34ae5966e5f.json](./SC-014_turn2_2d31fd57-be36-4ab4-8eac-c34ae5966e5f.json) |
| SC-014 | turn3 | 임차주택매매_대법원98마100_양수인승계이의제기 | `1d067533-549d-46ce-b39f-cd9b67b8de65` | 240.12s | 261,978 | 12회 | INSUFFICIENT | [SC-014_turn3_1d067533-549d-46ce-b39f-cd9b67b8de65.json](./SC-014_turn3_1d067533-549d-46ce-b39f-cd9b67b8de65.json) |
| SC-014 | draft | 임차주택매매_대법원98마100_양수인승계이의제기 | `d3c70be1-3b4e-4cca-b308-1d83df047874` | 3.00s | 2,286 | 2회 | PASS | [SC-014_draft_d3c70be1-3b4e-4cca-b308-1d83df047874.json](./SC-014_draft_d3c70be1-3b4e-4cca-b308-1d83df047874.json) |
| SC-015 | turn1 | 통상마모_원상복구과다공제_장기수선충당금반환 | `962f4a08-057b-4547-af7f-57664a09c5c3` | 182.90s | 204,501 | 12회 | INSUFFICIENT | [SC-015_turn1_962f4a08-057b-4547-af7f-57664a09c5c3.json](./SC-015_turn1_962f4a08-057b-4547-af7f-57664a09c5c3.json) |
| SC-015 | turn2 | 통상마모_원상복구과다공제_장기수선충당금반환 | `69431fc2-d375-4218-b0c4-37f931f18755` | 89.06s | 76,941 | 4회 | PASS | [SC-015_turn2_69431fc2-d375-4218-b0c4-37f931f18755.json](./SC-015_turn2_69431fc2-d375-4218-b0c4-37f931f18755.json) |
| SC-015 | turn3 | 통상마모_원상복구과다공제_장기수선충당금반환 | `c4ffef3f-5e48-4793-afcd-5a23163930fa` | 198.56s | 208,685 | 10회 | INSUFFICIENT | [SC-015_turn3_c4ffef3f-5e48-4793-afcd-5a23163930fa.json](./SC-015_turn3_c4ffef3f-5e48-4793-afcd-5a23163930fa.json) |
| SC-015 | draft | 통상마모_원상복구과다공제_장기수선충당금반환 | `7c4a1df4-5f65-4b11-a2a6-a75977070441` | 3.00s | 2,536 | 2회 | PASS | [SC-015_draft_7c4a1df4-5f65-4b11-a2a6-a75977070441.json](./SC-015_draft_7c4a1df4-5f65-4b11-a2a6-a75977070441.json) |
| SC-016 | turn1 | 임대인동의전대차_합의해지대항_전차인보호 | `43b2f666-237d-4587-b157-59c523330ead` | 158.29s | 181,061 | 11회 | PASS | [SC-016_turn1_43b2f666-237d-4587-b157-59c523330ead.json](./SC-016_turn1_43b2f666-237d-4587-b157-59c523330ead.json) |
| SC-016 | turn2 | 임대인동의전대차_합의해지대항_전차인보호 | `fce6f257-9fea-4ca3-a147-7305d56c3622` | 51.97s | 70,246 | 4회 | PASS | [SC-016_turn2_fce6f257-9fea-4ca3-a147-7305d56c3622.json](./SC-016_turn2_fce6f257-9fea-4ca3-a147-7305d56c3622.json) |
| SC-016 | turn3 | 임대인동의전대차_합의해지대항_전차인보호 | `0496535e-3b92-4b6c-867f-8521356236c0` | 106.14s | 72,111 | 4회 | PASS | [SC-016_turn3_0496535e-3b92-4b6c-867f-8521356236c0.json](./SC-016_turn3_0496535e-3b92-4b6c-867f-8521356236c0.json) |
| SC-016 | draft | 임대인동의전대차_합의해지대항_전차인보호 | `c7f7c164-d56e-46c3-8095-b7317a6995d0` | 3.00s | 596 | 2회 | PASS | [SC-016_draft_c7f7c164-d56e-46c3-8095-b7317a6995d0.json](./SC-016_draft_c7f7c164-d56e-46c3-8095-b7317a6995d0.json) |
| SC-017 | turn1 | 다가구깡통전세_선순위보증금은닉_사기죄고소 | `b5bbad44-99f4-4c8b-8310-af48807613b6` | 62.80s | 30,869 | 2회 | PASS | [SC-017_turn1_b5bbad44-99f4-4c8b-8310-af48807613b6.json](./SC-017_turn1_b5bbad44-99f4-4c8b-8310-af48807613b6.json) |
| SC-017 | turn2 | 다가구깡통전세_선순위보증금은닉_사기죄고소 | `8edc8f6f-61a2-426f-898e-4182b893cd11` | 93.45s | 83,315 | 5회 | PASS | [SC-017_turn2_8edc8f6f-61a2-426f-898e-4182b893cd11.json](./SC-017_turn2_8edc8f6f-61a2-426f-898e-4182b893cd11.json) |
| SC-017 | turn3 | 다가구깡통전세_선순위보증금은닉_사기죄고소 | `20617a9e-95f1-4ba8-9586-53b04e8058b7` | 98.12s | 107,247 | 5회 | PASS | [SC-017_turn3_20617a9e-95f1-4ba8-9586-53b04e8058b7.json](./SC-017_turn3_20617a9e-95f1-4ba8-9586-53b04e8058b7.json) |
| SC-017 | draft | 다가구깡통전세_선순위보증금은닉_사기죄고소 | `621fc40c-c1ce-4119-b94b-8552ab666208` | 3.00s | 2,048 | 2회 | PASS | [SC-017_draft_621fc40c-c1ce-4119-b94b-8552ab666208.json](./SC-017_draft_621fc40c-c1ce-4119-b94b-8552ab666208.json) |
| SC-018 | turn1 | 전세자금대출_질권설정채권양도_만기도래분쟁 | `29a5a404-810a-4aa7-96b2-54726432d4d3` | 168.17s | 117,496 | 9회 | INSUFFICIENT | [SC-018_turn1_29a5a404-810a-4aa7-96b2-54726432d4d3.json](./SC-018_turn1_29a5a404-810a-4aa7-96b2-54726432d4d3.json) |
| SC-018 | turn2 | 전세자금대출_질권설정채권양도_만기도래분쟁 | `a2783fe9-e885-4224-b851-e94f393ccbfa` | 42.83s | 31,512 | 3회 | PASS | [SC-018_turn2_a2783fe9-e885-4224-b851-e94f393ccbfa.json](./SC-018_turn2_a2783fe9-e885-4224-b851-e94f393ccbfa.json) |
| SC-018 | turn3 | 전세자금대출_질권설정채권양도_만기도래분쟁 | `03259197-d411-4755-b294-000a445eef3b` | 73.37s | 65,549 | 4회 | PASS | [SC-018_turn3_03259197-d411-4755-b294-000a445eef3b.json](./SC-018_turn3_03259197-d411-4755-b294-000a445eef3b.json) |
| SC-018 | draft | 전세자금대출_질권설정채권양도_만기도래분쟁 | `d9f00b60-82ff-4914-b912-bd69a30a0de1` | 3.00s | 582 | 2회 | PASS | [SC-018_draft_d9f00b60-82ff-4914-b912-bd69a30a0de1.json](./SC-018_draft_d9f00b60-82ff-4914-b912-bd69a30a0de1.json) |
| SC-019 | turn1 | 실거주허위갱신거절_제3자재임대_법정손해배상 | `e0331a6d-aa93-4b66-9eac-5da842a23e57` | 60.13s | 29,383 | 2회 | PASS | [SC-019_turn1_e0331a6d-aa93-4b66-9eac-5da842a23e57.json](./SC-019_turn1_e0331a6d-aa93-4b66-9eac-5da842a23e57.json) |
| SC-019 | turn2 | 실거주허위갱신거절_제3자재임대_법정손해배상 | `091c4309-b1cb-4d54-967b-cf8d3844f0e1` | 60.09s | 48,413 | 3회 | PASS | [SC-019_turn2_091c4309-b1cb-4d54-967b-cf8d3844f0e1.json](./SC-019_turn2_091c4309-b1cb-4d54-967b-cf8d3844f0e1.json) |
| SC-019 | turn3 | 실거주허위갱신거절_제3자재임대_법정손해배상 | `b77ea323-b37b-4f05-99dc-2f6d3b16f363` | 339.63s | 156,334 | 9회 | INSUFFICIENT | [SC-019_turn3_b77ea323-b37b-4f05-99dc-2f6d3b16f363.json](./SC-019_turn3_b77ea323-b37b-4f05-99dc-2f6d3b16f363.json) |
| SC-019 | draft | 실거주허위갱신거절_제3자재임대_법정손해배상 | `0b9c71e6-70f6-4782-9f06-15203eb0d299` | 3.00s | 3,324 | 2회 | WARN | [SC-019_draft_0b9c71e6-70f6-4782-9f06-15203eb0d299.json](./SC-019_draft_0b9c71e6-70f6-4782-9f06-15203eb0d299.json) |
| SC-020 | turn1 | 상가주거겸용건물_주임법적용여부_복합권리분쟁 | `d0179d0f-6eba-4713-9b71-2c0761f5f504` | 277.33s | 173,305 | 11회 | INSUFFICIENT | [SC-020_turn1_d0179d0f-6eba-4713-9b71-2c0761f5f504.json](./SC-020_turn1_d0179d0f-6eba-4713-9b71-2c0761f5f504.json) |
| SC-020 | turn2 | 상가주거겸용건물_주임법적용여부_복합권리분쟁 | `68d3037d-ed9d-4b91-8cab-6c77007514b8` | 67.73s | 75,513 | 5회 | PASS | [SC-020_turn2_68d3037d-ed9d-4b91-8cab-6c77007514b8.json](./SC-020_turn2_68d3037d-ed9d-4b91-8cab-6c77007514b8.json) |
| SC-020 | turn3 | 상가주거겸용건물_주임법적용여부_복합권리분쟁 | `ae135ddf-1853-494a-9441-f433369fb9fa` | 58.36s | 55,954 | 3회 | PASS | [SC-020_turn3_ae135ddf-1853-494a-9441-f433369fb9fa.json](./SC-020_turn3_ae135ddf-1853-494a-9441-f433369fb9fa.json) |
| SC-020 | draft | 상가주거겸용건물_주임법적용여부_복합권리분쟁 | `cd5bb1b6-1e4d-4705-91e3-cb8c4e285601` | 3.00s | 1,534 | 2회 | PASS | [SC-020_draft_cd5bb1b6-1e4d-4705-91e3-cb8c4e285601.json](./SC-020_draft_cd5bb1b6-1e4d-4705-91e3-cb8c4e285601.json) |
