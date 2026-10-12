<#
.SYNOPSIS
AI Legal Helper Windows 환경 점검 스크립트.

.DESCRIPTION
필수 프로그램(Docker, Docker Compose 등) 설치 여부를 확인하고, 포트 충돌 및 .env 상태를 점검합니다.
#>

$ErrorActionPreference = "Continue"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " AI Legal Helper 상태 점검 (Windows Doctor)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

$allPass = $true

# 1. Check Docker
Write-Host "1. Docker 설치 및 실행 상태 점검..." -NoNewline
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " [PASS]" -ForegroundColor Green
    } else {
        Write-Host " [FAIL]" -ForegroundColor Red
        Write-Host "  -> Docker가 실행 중이지 않거나 설치되지 않았습니다." -ForegroundColor Yellow
        $allPass = $false
    }
} catch {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "  -> Docker 명령어(CLI)를 찾을 수 없습니다." -ForegroundColor Yellow
    $allPass = $false
}

# 2. Check ports
Write-Host "2. 포트 충돌 점검..."
$portsToCheck = [ordered]@{
    3000 = "React (Frontend)"
    3001 = "Langfuse (Observability)"
    5432 = "PostgreSQL"
    7474 = "Neo4j (HTTP)"
    7687 = "Neo4j (Bolt)"
    8000 = "FastAPI (Backend)"
    8001 = "ChromaDB"
}
foreach ($entry in $portsToCheck.GetEnumerator()) {
    $port = $entry.Name
    $appName = $entry.Value
    Write-Host "   ${appName} 포트 ${port} 확인 중... " -NoNewline
    $portInUse = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($portInUse) {
        Write-Host " [WARNING - 사용 중]" -ForegroundColor Yellow
        $allPass = $false
    } else {
        Write-Host " [PASS]" -ForegroundColor Green
    }
}

# 3. Check .env
Write-Host "3. 환경변수(.env) 파일 점검..." -NoNewline
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir
if (Test-Path (Join-Path $ProjectRoot ".env")) {
    Write-Host " [PASS]" -ForegroundColor Green
} else {
    Write-Host " [WARNING]" -ForegroundColor Yellow
    Write-Host "  -> .env 파일이 없습니다. .env.example을 복사하여 생성하세요." -ForegroundColor Yellow
    $allPass = $false
}

Write-Host "=========================================" -ForegroundColor Cyan
if ($allPass) {
    Write-Host "모든 점검을 통과했습니다! 서비스 실행이 가능합니다." -ForegroundColor Green
    Write-Host "실행 방법: .\scripts\windows-start.ps1" -ForegroundColor Cyan
} else {
    Write-Host "일부 항목에 문제가 있습니다. 위 경고를 확인하세요." -ForegroundColor Red
}
Write-Host "=========================================" -ForegroundColor Cyan






