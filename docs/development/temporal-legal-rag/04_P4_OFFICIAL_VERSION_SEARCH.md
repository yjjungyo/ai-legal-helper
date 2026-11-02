# Temporal Legal RAG — P4 공식 법령 연혁·시행일 검색 고도화

작성일: 2026-11-02  
기준 main: fd3170ae65f46f4b204c3f21e04fbb939c2914b7  
브랜치: feature/temporal-legal-rag-p4-official-versioned-search

## 1. 문제와 목표

기존 official_statute_search.py는 국가법령정보센터의 공포일 기준 target=law
목록에서 최신 MST를 얻어 조문을 조회했다. 이 방식만으로는 과거 계약에
적용되는 종전 규정과 아직 시행되지 않은 개정 규정을 구분할 수 없다.
또한 호출 인자 effective_date는 실제 검색 대상 버전 선정에 사용되지 않았다.

P4에서는 **공식 시행일/연혁 목록에 기초한 버전 식별과 부칙 원문 확보**를
구현한다. 검색 출처가 공식이라는 사실과 법률적으로 해당 계약에 적용된다는
판단은 별개의 문제이므로, 적용례 확정은 P5에서 다룬다.

공식 API 문서:
- 시행일 기준 법령 목록: https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsEfYdListGuide
- 시행일 기준 법령 본문: https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsEfYdInfoGuide
- 공포일 기준 법령 본문: https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsNwInfoGuide

## 2. 실제 개발 파일

| 파일 | 목적 |
| --- | --- |
| backend/src/ai_legal_helper/tools/official_statute_versions.py | eflaw 연혁 목록 전 페이지 확인·법령ID/MST 검증·사건 기준일의 버전 후보 선택 |
| backend/src/ai_legal_helper/tools/official_statute_asof.py | MST+efYd 본문 조회·조문 고유 시행일·해당 공포번호 부칙·버전별 Source 생성 |
| backend/src/ai_legal_helper/tools/official_statute_search.py | 기존 API에 as_of_date 지원, 명시 날짜 시 eflaw 분기, 공식 XML 가상 PDF/페이지 생성 제거 |
| backend/src/ai_legal_helper/rag/source_schema.py | requested_as_of_date, version_relation, version_lookup_status, history_code 보존 |
| backend/tests/unit/test_official_statute_versions_p4.py | 버전 선택·공포/시행 구분·불완전 목록·부칙·원문위변조 회귀 테스트 |
| .github/workflows/temporal-legal-rag-p4.yml | P4/P1 및 HILT·기존 검색 경로를 각각 CI에서 검증 |

기존 8개 Agent, Router, LangGraph 노드/HILT 정책, PostgreSQL, Neo4j,
ChromaDB의 저장소 구조 및 운영 데이터는 변경하지 않았다.

## 3. 시행일 기준 조회 프로세스

1. 기존 승인된 외부 검색에서 법령명과 명시 조문을 정규화한다.
2. 법제처 lawSearch.do, target=eflaw, nw=1,2,3
   (연혁·시행예정·현행 전체), 필요한 경우 LID를 지정하여 조회한다.
3. 법령ID/이름 정확일치, totalCnt, 모든 페이지, 중복 MST를 검증한다.
4. 요청 사건일에 시행일이 가장 가까운 과거/현재 버전을
   AS_OF_CANDIDATE로, 다음 시행 예정 버전을 NEXT_EFFECTIVE_CANDIDATE로 보존한다.
5. 법제처 lawService.do, target=eflaw, MST=선정 버전,
   efYd=목록 시행일로 각각 공식 XML 원문을 조회한다.
6. 본문에 법령ID/MST/법령명이 존재하면 목록과 일치하는지 확인한다.
7. 요청 조문을 우선 추출하고 해당 공포번호의 부칙 전체 원문을 함께 수집한다.
8. 조문시행일자 > 부칙에 근거하여 안전하게 계산할 수 있는 날짜 순으로
   article_effective_date와 effective_date_basis를 기록한다.
9. Source에 law_id, version_id, promulgation_date, law_effective_date,
   article_effective_date, addendum_id, content_hash, version_relation,
   requested_as_of_date를 기록하고 표준 Source로 정규화한다.

명시적 사건 기준일이 없는 기존 공식 검색은 기존 target=law와
관련 조문 검색을 유지하며 공식 XML의 출처 표시만 수정한다.
두 날짜 인자(effective_date와 as_of_date)가 서로 다르면 조회를 중단한다.

## 4. 오판정 방지 규칙

- 법령 목록 시행일을 개별 조문의 시행일로 무조건 대입하지 않는다.
- 조문 시행일이 확인되었어도 P5 부칙 적용례/경과규정 검토 없이
  temporal_status=VERIFIED로 올리지 않는다.
- 공식 목록의 totalCnt 누락, 중도 장애, 재조회 중 값 변경, 중복 MST,
  페이지 제한 초과, 동일 시행일 다중 MST, 같은 이름의 복수 법령ID는
  UNCONFIRMED로 처리한다.
- 사건일보다 나중에 공포했지만 시행일이 앞서는 소급 규정이 발견되면
  소급효 검토가 필요하므로 자동 적용 후보를 확정하지 않는다.
- 본문에 다른 MST/법령ID/법령명이 포함되어 있으면 해당 법령의
  선택 버전 전체를 채택하지 않는다.
- 부칙은 정확한 공포번호로만 연결한다. 부칙 예외가 포함된 조문에
  개정 공통 시행일을 단정하지 않는다.
- XML을 PDF로 위장하지 않는다. 가짜 파일명, p.1, 작성되지 않은
  페이지 번호를 삭제하고 공식 법령명/조문/URL/법령ID/MST를 보존한다.
- Source ID는 공식 법령ID, MST, 조문, 원문 SHA256 일부를 포함하여
  개정 버전 간 동일한 Source로 합쳐지지 않도록 한다.
- 외부 API에는 법령명 및 공식 식별자만 전송하고, 사건 원문과 개인정보를
  검색어로 사용하지 않는다. API 키 마스킹 및 재시도 정책은 재사용한다.

## 5. 인공 법령 기반 시점 시나리오

고정 XML에서 가상의 계약법 시행령을 사용하였다.

| 항목 | 종전 버전 | 시행예정 개정 버전 |
| --- | --- | --- |
| MST | 100 | 200 |
| 목록 시행일 | 2024-01-01 | 2027-04-28 |
| 개정 공포일 | 2023-12-01 | 2026-10-27 |
| 사건 계약일 | 2026-11-01 | 2026-11-01 |
| 버전 관계 | AS_OF_CANDIDATE | NEXT_EFFECTIVE_CANDIDATE |

두 버전의 제36조와 각 공포번호에 대응하는 부칙을 **서로 다른 Source**로
반환한다. 종전 규정·개정 규정이 공식 자료로 조회됐다는 사실은 확인하지만
계약 체결/갱신 등 부칙 적용례의 최종 법률적 판단은 P5에서 수행한다.

이 값들은 테스트 전용 가상 법령이며 실제 개정 법령의 적용 여부를
예시 데이터만으로 확정하지 않는다.

## 6. 테스트 및 결과 (GitHub Actions)

Workflow: Temporal Legal RAG P4 official version regression

- Official history / MST / addenda Mock API + P1 시점 회귀: **52 PASS**
- 기존 HILT 승인/거절 및 공식 검색 회귀: **34 PASS**
- 합계: **86 PASS, 실패 0건**
- 종전 P3 회귀 워크플로도 성공
- 테스트 환경: Python 3.11, Mock XML, 실제 OpenLaw/LLM/운영 DB 미사용

추가로 검증한 사례:
- 사건일 이전 시행 버전과 이후 시행 예정 버전의 분리
- 사건일 이후에는 새로운 버전이 기준 후보로 선정
- 모든 페이지 미확인, 중복 MST, 동일 시행일 복수 버전 보류
- 법령ID/명칭/MST 오배정 차단
- 공포 후 유예 개정·부칙의 적용례 텍스트 보존
- 잘못된 기준일 및 상충한 날짜 인자 입력 시 네트워크 차단
- 기존 공포일 검색의 가짜 PDF/페이지 생성 방지
- 기존 사용자 HILT 거절/재검색 호환 경로 보호

## 7. 로컬 검증 명령

PowerShell에서 backend 디렉터리 기준:

    python -m pytest -q tests/unit/test_official_statute_versions_p4.py tests/unit/test_official_statute_temporal_metadata_p1.py tests/unit/test_statute_temporal_p0_law_02.py tests/unit/test_temporal_legal_rag_p0_contract.py tests/unit/test_temporal_legal_rag_p1.py

기존 HILT 테스트는 다음 중 DB 연결이 없는 항목과 별도 수행한다.

    python -m pytest -q tests/unit/test_step3_statute_search.py tests/unit/test_statute_search_reference_normalization.py

실제 LAW_OPENAPI_KEY를 이용한 통합 테스트는 공식 API 이용권한과
실제 응답을 확인한 다음 별도로 실행한다.

## 8. 정확한 완료 범위 및 후속 게이트

P4에서 **시점별 공식 법령 원문 확보와 버전·부칙 구분**을 구현했다.
하지만 기존 상담 그래프는 아직 일반 검색 시 effective_date=None으로
호출하므로 모든 사용자 질문에서 자동으로 새 버전 검색이 수행되지는 않는다.

- P5: 사건 기준일의 법률적 의미, 부칙 적용례·경과규정, 3상 적용 판정
- P6: 공식 검색 선행 계획 및 기존 HILT 체크포인트·승인과 시점 연결
- P7/P8: 버전별 Evidence Bundle과 Claim-to-Source Verification 연결
- P9: 동일 법령별 버전 독립 임베딩 Worker 및 증분 처리
- P10: 기존 벡터의 시행일/버전 메타데이터 마이그레이션

실제 한국 법령의 연혁 목록 형식은 개발 환경의 OpenLaw API로 다시
E2E 확인해야 한다. CI의 Mock XML 성공이 실제 법령 적용 정답률이나
응답시간 향상을 증명하는 것은 아니다.

**P4 구현 완료의 의미 = 공식 연혁·부칙 버전 검색 엔진과 Mock 기반
회귀검증 완료. 법률적 적용 판정 자동화의 최종 완료는 아직 아님.**
