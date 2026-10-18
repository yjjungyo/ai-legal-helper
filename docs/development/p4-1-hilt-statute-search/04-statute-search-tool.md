# P4.1 Verifier-Guided HILT 법령 검색 — 04. 공식 법령 검색 Tool 구현 및 Schema

## 1. 개요
본 문서는 법제처 국가법령정보공동활용 API(`open.law.go.kr`)를 기반으로 구현된 **공식 법령 원문 검색 도구(`search_official_statutes`)**의 아키텍처, 데이터 스키마 및 보안 원칙을 설명한다.

---

## 2. 외부 API 연동 구조

### 2.1 2단계 조회 프로세스
법제처 Open API는 법령 목록 검색과 상세 조문 조회가 분리되어 있어 다음 2단계 파이프라인으로 구현되었다:

1. **1단계: 법령 마스터 일련번호(MST) 조회**
   - URL: `http://www.law.go.kr/DRF/lawSearch.do?OC={API_KEY}&target=law&type=XML&query={법령명}`
   - 반환: 법령 기본정보 및 `법령일련번호(MST)` (예: 주택임대차보호법 -> MST `276291`)
2. **2단계: 조문 본문 및 항/호 상세 조회**
   - URL: `http://www.law.go.kr/DRF/lawService.do?OC={API_KEY}&target=law&MST={MST}&type=XML`
   - 반환: `조문단위(조문번호, 조문제목, 조문내용, 항, 호)` XML 구조 트리

---

## 3. 인터페이스 명세

```python
def search_official_statutes(
    query: str,
    candidate_laws: Optional[List[str]] = None,
    effective_date: Optional[str] = None
) -> List[Dict[str, Any]]:
    """공인 법령 Open API(open.law.go.kr)를 호출하여 관련 조문 원문을 검색한다.

    Args:
        query: 사용자 법률 질의 및 누락 쟁점 키워드.
        candidate_laws: Verifier가 식별한 후보 법령명 목록 (예: ['주택임대차보호법']).
        effective_date: 사건 당시 적용 법령 시행일자 (YYYYMMDD 형식, 선택).

    Returns:
        List[Dict[str, Any]]: 표준 Source Registry 규격을 준수하는 법령 원문 출처 딕셔너리 목록.
    """
```

---

## 4. 표준 Source Registry 스키마 변환

조회된 법령 조문은 시스템 전역의 Source Registry 및 결정론적 인용 검증기(`audit_citations_and_claims`)와 100% 호환되도록 표준 스키마로 변환된다:

```json
{
  "source_id": "STATUTE:주택임대차보호법:제6조의2:276291",
  "source_type": "STATUTE",
  "document_id": "MST-276291",
  "title": "주택임대차보호법 제6조의2(묵시적 갱신의 경우 계약의 해지)",
  "content": "제6조의2(묵시적 갱신의 경우 계약의 해지) ① 제6조제1항에 따라 계약이 갱신된 경우 같은 조 제2항에도 불구하고 임차인은 언제든지 임대인에게 계약해지를 통지할 수 있다.\n② 제1항에 따른 해지는 임대인이 그 통지를 받은 날부터 3개월이 지나면 그 효력이 발생한다.",
  "filename": "주택임대차보호법_제6조의2.txt",
  "page": "1",
  "statute_name": "주택임대차보호법",
  "article": "제6조의2",
  "effective_date": "20240731",
  "source_url": "https://www.law.go.kr/DRF/lawService.do?OC=[MASKED]&target=law&MST=276291&type=XML",
  "retrieval_method": "OFFICIAL_STATUTE_API",
  "retrieved_at": "2026-10-17T13:00:00+09:00"
}
```

---

## 5. 법령명 완전일치 우선 탐색 및 가중치 매칭 알고리즘

### 5.1 법령명 완전일치 우선 탐색 (유사 법령 오인 방지)
- **배경**: 법제처 `lawSearch.do?query=민법` 호출 시, `<law>` 결과의 1위가 `난민법`(MST: 188376)으로 반환되는 문제가 존재.
- **해결 알고리즘**:
  1. 1순위: XML의 전체 `<law>` 노드를 순회하며 `법령명한글 == clean_law_name` 완전 일치 노드를 탐색 (예: `민법` -> MST `284415`).
  2. 2순위: 괄호나 특수문자 제거 후 일치 비교.
  3. 3순위: 일치 항목이 없을 때만 첫 번째 노드를 폴백으로 채택.

### 5.2 핵심 쟁점 키워드 가중치 매칭 및 상위 조문 수 확대
- **쟁점 단어 가중치(`CRITICAL_ACTION_TOKENS`)**: `묵시적`, `갱신`, `해지`, `통고`, `통지`, `3개월`, `손해배상`, `특별손해`, `지연손해금`, `동시이행` 등 사건 해결 핵심 단어에 5.0배 가중치 부여.
- **일반 법률 용어 감쇄(`GENERIC_STATUTE_TERMS`)**: `임대차`, `보증금`, `임차인`, `임대인`, `주택` 등 법령 전체에 너무 흔한 단어는 가중치를 0.2배로 감쇄하여 핵심 조문(`제6조의2 묵시적 갱신의 경우 계약의 해지`)이 노이즈에 묻혀 탈락하지 않도록 보장.
- **최대 반환 조문 수 확대**: 법령당 기본 추출 조문 수를 5개에서 **8개**로 확대하여 핵심 연관 조문의 누락을 원천 차단.

---

## 6. 보안 및 무결성 원칙

1. **API Key 보안 관리**:
   - `LAW_OPENAPI_KEY`는 오직 `backend/.env` 및 환경변수에서만 로드한다.
   - 소스코드, Docstring, 단위 테스트, 프론트엔드 전송 데이터, 로그 출력에 절대 원문 키를 하드코딩하거나 노출하지 않는다.
2. **개인정보 비식별화**:
   - 외부 API 호출 쿼리(`query`)에는 사용자 사건의 주민등록번호, 실명, 주소 등 개인식별정보를 일체 포함하지 않고 법률 용어 및 쟁점 키워드(예: "묵시적 갱신 계약 해지 통보 효력 3개월")만 정제하여 전송한다.
3. **출처 검증 및 위조 차단**:
   - LLM 자체 지식에 의한 조문 생성을 불허하며, 실제 `open.law.go.kr` XML 파싱 결과로 얻은 법령 조문만 `retrieved_sources`에 등록된다.
   - 출처가 없는 인용이나 조문 불일치는 Verifier의 결정론적 검증에서 즉시 `UNSUPPORTED`로 차단된다.

