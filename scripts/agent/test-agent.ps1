[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$RuntimeRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $ProjectRoot) {
    $ProjectRoot = Get-ChartPilotRoot
}
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
if (-not $RuntimeRoot) {
    $RuntimeRoot = Join-Path $ProjectRoot "runtime"
}
$RuntimeRoot = [System.IO.Path]::GetFullPath($RuntimeRoot)
$python = Get-BundledPython -RuntimeRoot $RuntimeRoot

& (Join-Path $PSScriptRoot "test-goose.ps1") `
    -ProjectRoot $ProjectRoot `
    -RuntimeRoot $RuntimeRoot
& (Join-Path $PSScriptRoot "test-build-contracts.ps1") -ProjectRoot $ProjectRoot

Set-ChartPilotPythonEnvironment -WorkspaceRoot (Join-Path $ProjectRoot "workspace\agent-validation")
Invoke-CheckedCommand -FilePath $python -Label "Portable Goose initialization tests" -Arguments @(
    "-I",
    (Join-Path $ProjectRoot "agent\tests\test_initialize_goose.py")
)
Invoke-CheckedCommand -FilePath $python -Label "ChartPilot MCP integration test" -Arguments @(
    "-I",
    (Join-Path $ProjectRoot "agent\tests\test_chartpilot_mcp.py")
)

& (Join-Path $PSScriptRoot "start-chartpilot.ps1") -NoLaunch
$env:GOOSE_PATH_ROOT = Join-Path $ProjectRoot "workspace\goose"
$sessionRoot = Join-Path $ProjectRoot "workspace\session"
$gooseCli = Join-Path $RuntimeRoot "goose\resources\bin\goose.exe"
Push-Location $sessionRoot
try {
    $skillList = @(& $gooseCli skills list 2>&1) -join "`n"
    if ($LASTEXITCODE -ne 0) {
        throw "Goose Skill discovery failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
foreach ($skillName in @(
    "chartpilot-run-python",
    "chartpilot-profile-csv",
    "chartpilot-analyze-data",
    "chartpilot-render-chart"
)) {
    if ($skillList -notmatch [regex]::Escape($skillName)) {
        throw "Goose did not discover required Skill: $skillName"
    }
}
if ($skillList -match "trellis-") {
    throw "Portable Goose session discovered project-only Trellis Skills."
}
Write-Host "ChartPilot Goose Agent validation passed."
