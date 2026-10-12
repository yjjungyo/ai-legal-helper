<#
.SYNOPSIS
Langfuse를 포함하여 AI Legal Helper를 시작합니다.

.DESCRIPTION
기본 모드: 데이터베이스(Postgres, Neo4j, ChromaDB)와 Langfuse 컨테이너를 시작합니다.
-FullDocker 스위치: API 및 Frontend 컨테이너까지 모두 Docker로 빌드하여 실행합니다.
#>
param(
    [switch]$FullDocker
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

if ($FullDocker) {
    Write-Host "전체 스택(DB + API + Frontend + Langfuse)을 Docker로 빌드 및 실행합니다..." -ForegroundColor Green
    docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up --build -d
} else {
    Write-Host "데이터베이스 및 Langfuse 서비스를 시작합니다..." -ForegroundColor Green
    docker compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d postgres neo4j chromadb langfuse
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "오류가 발생했습니다." -ForegroundColor Red
    exit 1
}

Write-Host "서비스 시작 완료!" -ForegroundColor Green
Write-Host " Langfuse: http://localhost:3001" -ForegroundColor Yellow
if ($FullDocker) {
    Write-Host " Frontend: http://localhost:3000"
    Write-Host " API Docs: http://localhost:8000/docs"
} else {
    Write-Host " 로컬 개발 모드: 백엔드(.env의 LANGFUSE_ENABLED=true)와 연동하여 LLM 호출을 관측할 수 있습니다."
}



