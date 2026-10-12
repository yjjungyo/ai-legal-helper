# Langfuse 설정 및 실행 가이드

본 문서는 AI Legal Helper 내부에 통합된 Langfuse Observability 시스템의 실행 방법을 안내합니다.

## 1. 사전 요구사항

* Docker 및 Docker Compose가 설치된 환경.
* 기본 서비스(Postgres 등)가 구동 가능한 RAM 리소스 (권장 16GB 이상).

## 2. 환경 변수 설정

`.env` 파일에 다음 설정이 포함되어야 합니다 (`.env.example` 참고).

```env
# Langfuse 활성화 여부
LANGFUSE_ENABLED=true

# Langfuse 접속 주소 (로컬 실행 시)
LANGFUSE_HOST=http://localhost:3001

# Langfuse 인증키 (임의의 무작위 값 사용 가능)
LANGFUSE_PUBLIC_KEY=pk-lf-12345
LANGFUSE_SECRET_KEY=sk-lf-12345

# 보안을 위해 본문 수집 금지
LANGFUSE_CAPTURE_CONTENT=false
```

## 3. 서비스 실행

Langfuse 대시보드와 백엔드를 모두 실행하려면 통합 스크립트를 사용합니다.

### Windows (PowerShell)
```powershell
.\scripts\windows-langfuse-start.ps1
```

이 스크립트는 `docker-compose.yml`과 `docker-compose.langfuse.yml`을 결합하여 실행합니다. 
초기 실행 시 Langfuse DB 마이그레이션이 진행되며, 약 1~2분이 소요될 수 있습니다.

## 4. 접속 방법

* **Langfuse Web UI**: [http://localhost:3001](http://localhost:3001)
  - 초기화면에서 회원가입(Sign Up) 버튼을 눌러 로컬 계정을 생성하세요. (이메일 인증 불필요)
  - 프로젝트를 생성한 뒤 발급되는 API Key를 복사하여 `.env` 파일의 `LANGFUSE_PUBLIC_KEY` 및 `LANGFUSE_SECRET_KEY`를 업데이트하고 서버를 재시작하면 실제 연동이 완료됩니다.

## 5. 확인 사항

1. **AI 상담(Consultation) 실행**: AI 상담을 진행하면 Langfuse 대시보드의 `Traces` 메뉴에서 `Workflow:run_legal_consultation` 항목이 생성되는지 확인합니다.
2. **토큰 추적**: 생성된 Trace 내부의 `AzureOpenAI_Call` Generation에서 토큰 소모량이 기록되는지 확인합니다.
3. **개인정보 보호**: 프롬프트 및 응답 본문이 `[MASKED FOR PRIVACY]`로 블라인드 처리되어 표시되는지 확인합니다.

## 6. 서비스 중지

```powershell
.\scripts\windows-langfuse-stop.ps1
```
위 명령은 메모리 점유를 해제하기 위해 Langfuse와 관련된 모든 컨테이너를 안전하게 중단합니다.

