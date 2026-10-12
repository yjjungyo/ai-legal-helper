# AI Legal Helper — 사용자 테스트 가이드 (Windows 환경)

본 문서는 `AI Legal Helper`의 E2E(End-to-End) 서비스 통합 테스트 가이드입니다.

## 1. 사전 준비 (Prerequisites)

*   **운영체제**: Windows 10/11
*   **필수 설치**: 
    *   Docker Desktop (실행 중이어야 함)
    *   PowerShell 5.1 이상
*   **권장 환경**: 
    *   RAM 16GB 이상 (DB 및 Docker 컨테이너 다수 구동 목적)

## 2. 서비스 실행 방법

1.  저장소 루트(`C:\myprjs\ai-legal-helper`)로 이동합니다.
2.  (최초 1회) 환경변수 파일을 준비합니다:
    ```powershell
    Copy-Item .env.example .env
    ```
    `.env` 파일을 열어 `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`를 실제 값으로 수정합니다.
3.  상태 점검 스크립트를 실행하여 환경에 문제가 없는지 확인합니다:
    ```powershell
    .\scripts\windows-doctor.ps1
    ```
4.  서비스를 시작합니다 (초기 빌드에 시간이 소요될 수 있습니다):
    ```powershell
    .\scripts\windows-start.ps1
    ```

## 3. 기능 테스트 시나리오

서비스가 시작되면 브라우저에서 `http://localhost:3000` 으로 접속하여 다음 과정을 수행해 보십시오.

### 시나리오 1: 사용자 로그인 및 사건 등록
1. UI 화면에서 기본 제공되는 사용자로 로그인합니다 (기본 설정된 임시 사용자 또는 생성 버튼).
2. "새 사건 등록" 버튼을 클릭합니다.
3. 임대차 보증금 반환 문제와 관련된 사실 관계를 대략적으로 입력합니다.

### 시나리오 2: 증거 업로드 및 사실 추출 (AI 상담)
1. 생성된 사건 상세 페이지로 들어갑니다.
2. `PDF`, `DOCX`, `TXT`, `PNG` 형식의 계약서 또는 문자 내역(증거자료)을 업로드합니다.
3. **증거 분석** 기능이 동작하여 자동으로 사실관계와 타임라인이 구성되는 것을 확인합니다.
4. 부족한 사실관계가 있다면 AI가 상담 메시지를 통해 추가 질문을 던지는지 확인합니다.

### 시나리오 3: GraphRAG 기반 법률 쟁점 분석
1. "법률 분석 요청" 또는 대응 플랜 버튼을 클릭합니다.
2. 백엔드에서 PostgreSQL, ChromaDB, Neo4j 연계 검색이 동작하며, 적절한 법률 쟁점과 Action Plan이 도출되는지 확인합니다.

### 시나리오 4: 법률문서 생성 및 PDF/DOCX 다운로드
1. "법률 문서 (Legal Documents)" 섹션으로 이동합니다.
2. "내용증명 생성" 버튼을 눌러 초안을 생성합니다.
3. 생성이 완료되면 `PDF 다운로드` 버튼과 `DOCX 다운로드` 버튼을 클릭하여 결과물을 다운로드합니다.
4. 다운로드된 파일 내용에 한글이 깨지지 않고 정상적으로 렌더링되었는지 확인합니다 (Malgun Gothic 폰트 지원).

## 4. 서비스 중지 및 초기화

*   **서비스 중지**:
    ```powershell
    .\scripts\windows-stop.ps1
    ```
*   **문제 발생 시 로그 확인**:
    ```powershell
    docker compose logs -f api
    docker compose logs -f frontend
    ```

