<#
.SYNOPSIS
전체 서비스의 상태를 확인합니다.
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

Write-Host "컨테이너 상태:" -ForegroundColor Cyan
docker compose -f docker-compose.yml -f docker-compose.langfuse.yml ps



