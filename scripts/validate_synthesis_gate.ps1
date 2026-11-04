# Run on the development Windows machine with backend dependencies and evaluation DB configured.
param(
    [string]$CaseId = "",
    [string]$Baseline = "",
    [switch]$SkipEvaluation
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$python = ".\\.venv\\Scripts\\python.exe"
if (-not (Test-Path $python)) { $python = ".\\backend\\.venv\\Scripts\\python.exe" }
if (-not (Test-Path $python)) { throw "Python venv not found (.venv or backend/.venv)." }
$env:PYTHONPATH = (Join-Path (Get-Location) "backend\\src")
Write-Host "[1/3] Synthesis law gate regression tests"
& $python -m pytest backend/tests/test_synthesis_law_gate.py -q
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed. Evaluation stopped." }
if ($SkipEvaluation) { return }
Write-Host "[2/3] Available SC-001 scenarios"
& $python -m evaluation_harness.cli list-scenarios
if ($LASTEXITCODE -ne 0) { throw "Scenario discovery failed." }
if (-not $CaseId) {
    Write-Host "Specify -CaseId with the isolated evaluation case ID to run SC-001."
    return
}
$runId = "synthesis_gate_" + (Get-Date -Format "yyyyMMdd_HHmmss")
Write-Host "[3/3] Evaluation run: $runId"
& $python -m evaluation_harness.cli run --dataset sc001_dev --case-id $CaseId --run-id $runId
if ($LASTEXITCODE -ne 0) { throw "Evaluation failed." }
if ($Baseline) {
    & $python -m evaluation_harness.cli compare --baseline $Baseline --candidate $runId
    if ($LASTEXITCODE -ne 0) { throw "Comparison failed." }
}
Write-Host "Inspect Langfuse trace IDs for LLM calls, latency, and revision count."
