# AI Legal Helper 발표용 아키텍처 구성도 (2026-11-17)

## 용도와 구성

AI Master 최종 평가 발표자료에 삽입하기 위한 **16:9(1600×900 기준), 한국어 슬라이드 3장**입니다. 각각 상단에 주요 특징을 한 줄로 제시하고, 본문을 **좌측 구성도 약 60% / 우측 핵심 단계 설명 약 40%**로 배치했습니다. 주 처리 흐름은 왼쪽→오른쪽 또는 위→아래로 배열했습니다. 그림은 실제 `main` 소스의 기능과 관계에 기반한 **논리적 개념도**이므로 실제 배포 서버 수나 모든 코드 호출을 1:1로 묘사하지 않습니다.

| 순서 | 발표 슬라이드 | 핵심 메시지 | 관련 코드 |
|---|---|---|---|
| 01 | `01_사용자경험_서비스개념도.svg` | 사건을 기준으로 증거·사실·상담·계획·문서 맥락이 연결 | `frontend/src/App.tsx`, `frontend/src/pages/CaseWorkspace.tsx`, `backend/src/ai_legal_helper/api/routes/{cases,evidence,consultation,documents,workflow}.py` |
| 02 | `02_전체시스템_아키텍처.svg` | React → FastAPI → AI 업무 계층, PostgreSQL·Neo4j·ChromaDB·파일 저장소와 Azure OpenAI·공식 법령 API·Langfuse 연계 | `docker-compose.yml`, `backend/src/ai_legal_helper/api/main.py`, `backend/src/ai_legal_helper/llm/gateway.py`, `backend/src/ai_legal_helper/database/graph_sync_worker.py` |
| 03 | `03_LangGraph_상담처리흐름도.svg` | 실제 상담 LangGraph의 초기 분기, RAG/답변 초안, 검증, 공식 법령 추가 검색·수정·재검증 및 최종 종료 | `backend/src/ai_legal_helper/workflows/legal_workflow.py`의 `build_legal_graph()` |

## 소스 검증 기준

- 기준 브랜치: `main`; 확인 당시 HEAD: `d82ef121a60adae15935e18ce3bb5cb385a806bb`.
- 상담 Graph는 **활성 노드 14개(START·END 제외), 연결 30개(START·END 포함), 조건 분기 지점 6개**입니다.
- `followup_action_node`, `statute_search_plan_node`, `legal_evidence_bundle_node`는 소스에 함수 정의가 남아 있어도 현재 `build_legal_graph()`의 활성 노드로 등록되지 않았습니다.
- `execute_statute_search → finalize`는 **`DOCUMENT_MODE` + 검색 추가 출처 0건 + 기존 답변 초안 및 검증 주장 존재** 시에 한해 가능한 예외 분기입니다. 처음 수정할 수 있는 조건이면 `revise`로 먼저 분기하며, `finalize_node` 내 `finish_answer()`는 기존 검증 스냅샷·출처 매니페스트·법령 적용 시점·지지 주장의 안전성을 추가 검사합니다. `verification`을 다시 실행하는 경로와는 구분됩니다.
- 법률 상담의 LangGraph(`legal_workflow.py`)와 법률문서 작성 LangGraph(`document_workflow.py`)는 **별도 워크플로우**입니다.
- 사용자 화면은 사건별 증거 관리, 사실·타임라인, 상담, 대응 계획, 법률 문서를 제공합니다. Neo4j는 관계 조회용이고, PostgreSQL의 사건 데이터를 Graph Sync Worker가 반영합니다. ChromaDB는 법령 벡터 검색에 사용됩니다.
- **슬라이드 03의 선은 발표 가독성을 고려한 주 경로 중심의 개념 표현**입니다. 정확한 전체 조건부 Edge는 아래 표를 참고하십시오. 그림에 없는 Edge를 존재하지 않는 것으로 해석하면 안 됩니다.

## 상담 LangGraph 전체 연결 목록 (30개)

| 출발 노드 | 다음 노드(조건부 분기 포함) | 개수 |
|---|---|---:|
| `START` | `supervisor_initialize` | 1 |
| `supervisor_initialize` | `general_conversation`, `evidence_unavailable`, `routing_exit`, `route` | 4 |
| `general_conversation` | `END` | 1 |
| `evidence_unavailable` | `END` | 1 |
| `route` | `run_agents`, `routing_exit` | 2 |
| `routing_exit` | `END` | 1 |
| `run_agents` | `synthesize` | 1 |
| `synthesize` | `verification`, `statute_search_approval`, `insufficient` | 3 |
| `verification` | `finalize`, `statute_search_approval`, `execute_statute_search`, `revise`, `insufficient` | 5 |
| `statute_search_approval` | `execute_statute_search`, `insufficient` | 2 |
| `execute_statute_search` | `run_agents`, `re_analyze`, `revise`, `finalize`, `insufficient` | 5 |
| `re_analyze` | `verification` | 1 |
| `revise` | `verification` | 1 |
| `insufficient` | `END` | 1 |
| `finalize` | `END` | 1 |
| **합계** |  | **30** |

위 표의 `finalize`는 정상적인 통과 또는 기존 검증 결과를 조건부 보존하는 최종화이고, `insufficient`는 판단 유보·보완 안내로 이어집니다. 법령 검색의 선행(`PRE_ANALYSIS`)·후행(`POST_VERIFICATION`) 단계에 따라 분기가 달라집니다.

## 출력·재생성

- 각 SVG: 편집 가능한 벡터 원본. GitHub 미리보기 또는 SVG 지원 편집기에서 열 수 있습니다.
- `build_slides.py`: SVG 3장과 발표용 PNG, 개별 PDF 및 3페이지 PDF를 재생성합니다.
- 필요 패키지: `python3`, `svgwrite`, `PyMuPDF (fitz)`, `Inkscape` 및 한국어 폰트(`Noto Sans CJK KR` 권장).
- 실행: `python build_slides.py` (스크립트 상단의 출력 경로를 사용할 위치에 맞게 변경할 수 있습니다).

**주의:** 이 자료는 아키텍처 설명용이며, 실제 E2E V8에서 어떤 조건부 노드가 실행되었는지는 별도 Langfuse Trace로 입증해야 합니다.