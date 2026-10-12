<#
.SYNOPSIS
AI Legal Helper를 Windows 환경에서 실행합니다.

.DESCRIPTION
Docker Compose를 사용하여 전체 서비스(DB, API, Frontend)를 빌드하고 백그라운드에서 실행합니다.
실행 후 프론트엔드 URL과 API 문서를 출력합니다.
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " AI Legal Helper 서비스 시작" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host ".env 파일이 없습니다. .env.example을 복사하여 생성합니다." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "주의: Azure OpenAI 키 등 필요한 설정을 .env 파일에 입력해주세요." -ForegroundColor Red
}

# Run docker-compose
Write-Host "Docker 컨테이너를 빌드하고 시작합니다..." -ForegroundColor Green
docker compose up --build -d

if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker Compose 실행 중 오류가 발생했습니다." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "모든 서비스가 백그라운드에서 시작되었습니다." -ForegroundColor Green
Write-Host "-----------------------------------------"
Write-Host " 프론트엔드: http://localhost:3000"
Write-Host " API 문서:   http://localhost:8000/docs"
Write-Host " Neo4j:      http://localhost:7474 (기본 계정: neo4j / ai_password_dev)"
Write-Host "-----------------------------------------"
Write-Host "로그를 확인하려면 다음 명령어를 사용하세요:" -ForegroundColor Yellow
Write-Host "  docker compose logs -f" -ForegroundColor Yellow
Write-Host "서비스를 중지하려면:" -ForegroundColor Yellow
Write-Host "  docker compose down" -ForegroundColor Yellow
Write-Host "=========================================" -ForegroundColor Cyan



