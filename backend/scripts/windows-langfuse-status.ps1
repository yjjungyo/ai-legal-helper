<#
.SYNOPSIS
전체 서비스의 상태를 확인합니다.

.DESCRIPTION
저장소 루트의 기본 Compose와 Langfuse 확장을 함께 조회하고 호출자의 작업 위치를 복원합니다.
루트 .env를 우선 사용하며, 없으면 기존 backend/.env를 사용합니다. 설정 파일을 생성하지 않습니다.
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BackendDir = Split-Path -Parent $ScriptDir
$ProjectRoot = Split-Path -Parent $BackendDir

Push-Location -LiteralPath $ProjectRoot
try {
    # 시작 스크립트와 같은 설정을 선택해 DB 인증과 Compose 프로젝트 해석을 일치시킵니다.
    $EnvFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        $EnvFile = Join-Path $BackendDir ".env"
    }
    $ComposeArgs = @("-f", "docker-compose.yml", "-f", "docker-compose.langfuse.yml")
    if (Test-Path -LiteralPath $EnvFile) {
        $ComposeArgs = @("--env-file", $EnvFile) + $ComposeArgs
    }

    Write-Host "컨테이너 상태:" -ForegroundColor Cyan
    docker compose @ComposeArgs ps
    $ComposeExitCode = $LASTEXITCODE
} finally {
    # 조회 실패 시에도 호출자의 작업 위치를 유지합니다.
    Pop-Location
}
exit $ComposeExitCode
