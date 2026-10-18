<#
.SYNOPSIS
Langfuse를 포함하여 AI Legal Helper를 시작합니다.

.DESCRIPTION
기본 모드: 데이터베이스(Postgres, Neo4j, ChromaDB)와 Langfuse 컨테이너를 시작합니다.
-FullDocker 스위치: API 및 Frontend 컨테이너까지 모두 Docker로 빌드하여 실행합니다.
기본 Compose와 Langfuse 확장을 저장소 루트에서 함께 실행하고 호출자의 작업 위치를 복원합니다.
루트 .env를 우선 사용하며, 없으면 backend/.env를 사용하거나 backend/.env.example에서 생성합니다.
#>
param(
    [switch]$FullDocker
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BackendDir = Split-Path -Parent $ScriptDir
$ProjectRoot = Split-Path -Parent $BackendDir

Push-Location -LiteralPath $ProjectRoot
try {
    # 기존 루트 설정은 유지하고, 없으면 백엔드와 같은 설정을 사용해 DB 인증 불일치를 방지합니다.
    $EnvFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        $EnvFile = Join-Path $BackendDir ".env"
        if (-not (Test-Path -LiteralPath $EnvFile)) {
            Copy-Item -LiteralPath (Join-Path $BackendDir ".env.example") -Destination $EnvFile
        }
    }
    $ComposeArgs = @("--env-file", $EnvFile, "-f", "docker-compose.yml", "-f", "docker-compose.langfuse.yml")

    if ($FullDocker) {
        Write-Host "전체 스택(DB + API + Frontend + Langfuse)을 Docker로 빌드 및 실행합니다..." -ForegroundColor Green
        docker compose @ComposeArgs up --build -d
    } else {
        Write-Host "데이터베이스 및 Langfuse 서비스를 시작합니다..." -ForegroundColor Green
        docker compose @ComposeArgs up -d postgres neo4j chromadb langfuse
    }

    # Docker 실패를 성공 안내로 덮지 않고 호출자에게 같은 종료 코드를 전달합니다.
    $ComposeExitCode = $LASTEXITCODE
    if ($ComposeExitCode -ne 0) {
        Write-Host "Docker Compose 실행 중 오류가 발생했습니다." -ForegroundColor Red
        exit $ComposeExitCode
    }

    Write-Host "서비스 시작 완료!" -ForegroundColor Green
    Write-Host " Langfuse: http://localhost:3001" -ForegroundColor Yellow
    if ($FullDocker) {
        Write-Host " Frontend: http://localhost:3000"
        Write-Host " API Docs: http://localhost:8000/docs"
    } else {
        Write-Host " 로컬 개발 모드: 백엔드(.env의 LANGFUSE_ENABLED=true)와 연동하여 LLM 호출을 관측할 수 있습니다."
    }
} finally {
    # 오류나 조기 종료에도 스크립트를 호출하기 전 작업 위치로 돌아갑니다.
    Pop-Location
}
exit $ComposeExitCode
