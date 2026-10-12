<#
.SYNOPSIS
AI Legal Helper 서비스를 중지합니다.
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir

Set-Location $ProjectRoot

Write-Host "Docker 컨테이너를 중지합니다..." -ForegroundColor Cyan
docker compose down

Write-Host "서비스가 종료되었습니다." -ForegroundColor Green



