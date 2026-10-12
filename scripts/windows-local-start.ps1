<#
.SYNOPSIS
AI Legal Helper 로컬 개발 환경(FastAPI + React Vite) 원클릭 실행 스크립트.

.DESCRIPTION
1. 필수 데이터베이스(PostgreSQL, Neo4j, ChromaDB)를 Docker 백그라운드로 기동합니다.
2. 새 터미널 창에서 FastAPI(uvicorn)를 핫 리로드 모드로 실행합니다.
3. 새 터미널 창에서 React(Vite) 개발 서버를 실행합니다.
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " AI Legal Helper 로컬 개발 모드 시작" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

# 1. Start Docker Databases
Write-Host "1. 필수 데이터베이스(Postgres, Neo4j, ChromaDB) 기동 중..." -ForegroundColor Green
docker compose up -d postgres neo4j chromadb

if ($LASTEXITCODE -ne 0) {
    Write-Host "데이터베이스 컨테이너 실행 중 오류가 발생했습니다." -ForegroundColor Red
    exit 1
}

# 2. Launch FastAPI backend in a new window
Write-Host "2. 백엔드 API (FastAPI / uvicorn) 실행 창을 띄웁니다..." -ForegroundColor Green
$backendCmd = "cd '$ProjectRoot'; & '.\.venv\Scripts\Activate.ps1'; uvicorn ai_legal_helper.api.main:app --host 0.0.0.0 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "$backendCmd"

# 3. Launch React frontend in a new window
Write-Host "3. 프론트엔드 UI (React / Vite) 실행 창을 띄웁니다..." -ForegroundColor Green
$frontendCmd = "cd '$ProjectRoot\frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "$frontendCmd"

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "로컬 개발 서버가 각각 새 창에서 실행되었습니다!" -ForegroundColor Green
Write-Host "-----------------------------------------"
Write-Host " 프론트엔드 UI: http://localhost:5173" -ForegroundColor Yellow
Write-Host " API 문서(Swagger): http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host " Neo4j 브라우저:   http://localhost:7474"
Write-Host "-----------------------------------------"
Write-Host "코드를 수정하면 브라우저와 API에 즉시 자동 반영(Hot Reload)됩니다."
Write-Host "=========================================" -ForegroundColor Cyan

