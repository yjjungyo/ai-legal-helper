# P10 — 기존 법령 Vector 메타데이터 감사·무손실 격리 이관

## 목표

과거 PDF 파일명이나 날짜 추정에서 만들어진 기존 Vector의 조문 시행일을
공식 검증된 것처럼 간주하지 않는다. 기존 8개 law_docs_* 컬렉션을
삭제하거나 직접 변형하지 않고 검토용 격리 컬렉션으로 복사한다.

## 구현

- 법령 8개 분야별 컬렉션 읽기 전용 페이지 순회
- 원본 컬렉션/원본 ID/원문 SHA256/기존 법령명·버전 힌트를 감사
- 법령 ID 또는 MST 누락 건수, 본문 누락 건수 자동 집계
- legacy_law_staging (기존 RAG의 law_docs_* 접두사 외부) 별도 생성
- 새로운 ID는 원본 컬렉션 + 원본 ID SHA256으로 생성하여 반복 Upsert 멱등 처리
- 레거시 모든 청크의 temporal_status=UNCONFIRMED, effective_date_basis=LEGACY_UNVERIFIED
- 원본 PDF 날짜는 filename_date_hint로만 저장. 조문 시행일로 승격 금지
- 상담 검색경로·8개 Agent·기존 전체 원문과 기존 분야별 Vector 변경 없음
- 기본 관리자 명령은 DRY RUN. --execute 지정할 때만 스테이징 복사

## 사용 방법

    cd backend
    python scripts/audit_legacy_law_vectors.py
    python scripts/audit_legacy_law_vectors.py --execute --batch-size 100

실서비스에서 실제 Chroma 및 회사 Embeddings를 연결해야 최종 전체 감사/
스테이징을 수행할 수 있다. 이 실행은 현재 ChatGPT 도구에서 수행하지 않았다.

## 제한

- 스테이징은 공식 법령 검증 완료/운영 검색 전환이 아니라 **격리 보관** 단계
- 법령ID/MST 없는 과거 PDF는 공식 Law Catalog + 실제 조문과 대조 후 별도 승인 필요
- 기존 법령 원문/버전의 진위가 확인된 후에만 P9 공식 law_docs_global에 재인덱싱
- 기존 데이터 삭제나 레거시 컬렉션 일괄 재생성은 수행하지 않음
- 운영 전에 원본 건수와 스테이징 건수/해시 대조, 사용량·성능 회귀 테스트 필요

## 후속

P11에서 동일 사건 Gold Set 기준 세 가지 검색 모드의 검색 품질, 시간,
LLM 토큰 및 시행일 정답률을 비교해 운영 플래그 활성화 여부 결정.
