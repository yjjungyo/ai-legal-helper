<#
.SYNOPSIS
Langfuse를 포함한 전체 서비스를 중지합니다.
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

Write-Host "서비스를 중지합니다..." -ForegroundColor Cyan
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml down

Write-Host "중지 완료." -ForegroundColor Green



