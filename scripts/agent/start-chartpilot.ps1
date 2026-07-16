[CmdletBinding()]
param(
    [switch]$NoLaunch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\runtime\common.ps1")

$projectRoot = Get-ChartPilotRoot
$runtimeRoot = Join-Path $projectRoot "runtime"
$gooseHome = Join-Path $projectRoot "workspace\goose"
$sessionRoot = Join-Path $projectRoot "workspace\session"
$pythonWorkspace = Join-Path $projectRoot "workspace\python"
$python = Get-BundledPython -RuntimeRoot $runtimeRoot
$desktop = Join-Path $runtimeRoot "goose\Goose.exe"
$initializer = Join-Path $projectRoot "agent\initialize_goose.py"
$template = Join-Path $projectRoot "agent\config\goose-config.template.json"
New-Item -ItemType Directory -Path $sessionRoot -Force | Out-Null

& (Join-Path $PSScriptRoot "test-goose.ps1") `
    -ProjectRoot $projectRoot `
    -RuntimeRoot $runtimeRoot `
    -Quick

Set-ChartPilotPythonEnvironment -WorkspaceRoot $pythonWorkspace
$allowedReadRoots = @($projectRoot)
if ($env:USERPROFILE -and (Test-Path -LiteralPath $env:USERPROFILE -PathType Container)) {
    $allowedReadRoots += [System.IO.Path]::GetFullPath($env:USERPROFILE)
}
$arguments = @(
    "-I", $initializer,
    "--project-root", $projectRoot,
    "--goose-home", $gooseHome,
    "--template", $template
)
foreach ($root in $allowedReadRoots | Select-Object -Unique) {
    $arguments += @("--allowed-read-root", $root)
}
Invoke-CheckedCommand -FilePath $python -Arguments $arguments -Label "Initialize portable Goose"

$env:GOOSE_PATH_ROOT = [System.IO.Path]::GetFullPath($gooseHome)
$env:CHARTPILOT_ROOT = $projectRoot
$env:CHARTPILOT_WORKSPACE_ROOT = Join-Path $projectRoot "workspace"
$env:CHARTPILOT_ALLOWED_READ_ROOTS = ($allowedReadRoots | Select-Object -Unique) -join [System.IO.Path]::PathSeparator
$env:GOOSE_MODE = "smart_approve"
$env:GOOSE_TELEMETRY_ENABLED = "false"
$env:GOOSE_LOCALE = "zh-CN"

if ($NoLaunch) {
    Write-Host "Portable Goose initialization completed: $gooseHome"
    return
}

Write-Host "Starting ChartPilot with Goose Desktop $($desktop)"
Start-Process `
    -FilePath $desktop `
    -WorkingDirectory $sessionRoot `
    -ArgumentList @("`"$sessionRoot`"")
