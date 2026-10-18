# AI Legal Helper — 개발 가이드 (Development Guide)

**문서 버전:** 1.0.0  
**최종 갱신일:** 2026-10-18  
**적용 대상:** `ai-legal-helper` 프로젝트의 모든 백엔드/프론트엔드 개발자 및 AI 코딩 에이전트

---

## 1. 백엔드 라이브러리 및 의존성 관리 규칙 (필수)

백엔드 소스코드 작성 중 새로운 외부 라이브러리 또는 파이썬 패키지를 임포트하여 사용할 때는 반드시 다음 절차를 준수해야 합니다.

### 1.1 `requirements.txt` 및 `pyproject.toml` 즉시 동기화
- 신규 라이브러리 모듈을 설치하거나 코드에서 임포트할 경우, **반드시 아래 두 파일에 해당 패키지와 버전 제약을 즉시 추가**합니다:
  1. [`backend/requirements.txt`](../../backend/requirements.txt): 배포 및 가상환경 직접 설치용
  2. [`backend/pyproject.toml`](../../backend/pyproject.toml): 표준 패키징 및 빌드용 (`[project.dependencies]`)
- **주의:** 개발자 로컬 가상환경(`.venv`)에만 `pip install`로 설치하고 형상관리 의존성 파일에 반영하지 않을 경우, 다른 개발자 또는 서버 실행 시 `ModuleNotFoundError`로 Uvicorn이 크래시되는 치명적 장애가 발생합니다.

### 1.2 의존성 추가 예시
```txt
# backend/requirements.txt
# --- 3. AI & Orchestration (LangChain / LangGraph) ---
langgraph-checkpoint-postgres>=2.0.0
psycopg-pool>=3.2.0
```

```toml
# backend/pyproject.toml
dependencies = [
    # ...
    "langgraph-checkpoint-postgres>=2.0.0",
    "psycopg-pool>=3.2.0",
]
```

### 1.3 가상환경 의존성 최신화 명령
패키지 의존성이 변경된 경우 다음 명령어로 가상환경을 동기화합니다:

```powershell
cd C:\myprjs\ai-legal-helper\backend
.\.venv\Scripts\pip install -r requirements.txt
```

---

## 2. 코드 주석 및 문서화 표준

모든 신규 소스코드 및 수정 사항은 [`docs/development/CODING_COMMENT_STANDARD.md`](CODING_COMMENT_STANDARD.md)를 따라야 합니다.

- **Python (FastAPI, LangGraph, RAG 등):**
  - 한국어 모듈 Docstring 작성
  - Google 스타일 함수/클래스 Docstring (`Args:`, `Returns:`, `Raises:`)
  - 조건 분기, 예외 처리, 비동기 파이프라인 흐름에 대한 명확한 사유 주석 작성
- **TypeScript / React:**
  - 한국어 TSDoc/JSDoc 작성
  - Props 인터페이스 및 반환 JSX에 대한 역할 명시

---

## 3. 테스트 및 품질 보증

1. **단위 테스트 실행:**
   ```powershell
   python -m pytest backend/tests/unit -q
   ```
2. **프론트엔드 빌드 검사:**
   ```powershell
   cd frontend
   npm run build
   ```
3. **무결점 원칙:**
   - 기존의 모든 테스트를 통과(0 Regression)해야 하며, 신규 기능이나 결함 수정 시 재현/검증 테스트를 반드시 추가합니다.

