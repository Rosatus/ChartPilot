[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$RuntimeRoot,
    [switch]$Quick
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
$lock = Get-GooseLock -ProjectRoot $ProjectRoot
$manifestPath = Join-Path $RuntimeRoot "goose-manifest.json"
$manifest = Read-JsonFile -Path $manifestPath
if ($manifest.schema_version -ne "chartpilot.goose-runtime/v1" -or $manifest.status -ne "ready") {
    throw "Goose runtime manifest is not ready."
}
if ($manifest.runtime_id -ne $lock.runtime_id -or $manifest.goose.version -ne $lock.goose.version) {
    throw "Goose runtime manifest does not match goose.lock.json."
}
if ($manifest.upstream.sha256 -ne $lock.upstream.sha256 -or [int64]$manifest.upstream.size_bytes -ne [int64]$lock.upstream.size_bytes) {
    throw "Goose runtime upstream identity does not match goose.lock.json."
}
if ($manifest.health.status -ne "success") {
    throw "Goose runtime health status is not success."
}

$gooseRoot = Join-Path $RuntimeRoot "goose"
$manifestFiles = @($manifest.files)
if ($manifestFiles.Count -ne @($lock.required_files).Count) {
    throw "Goose runtime manifest file count is unexpected."
}
foreach ($record in $manifestFiles) {
    $relative = [string]$record.path
    if (-not $relative -or [System.IO.Path]::IsPathRooted($relative) -or $relative.Contains("..")) {
        throw "Goose runtime manifest contains an invalid relative path: $relative"
    }
    $path = Join-Path $gooseRoot $relative.Replace('/', '\')
    if (-not (Test-FileArtifact `
        -Path $path `
        -ExpectedBytes ([int64]$record.size_bytes) `
        -ExpectedSha256 ([string]$record.sha256))) {
        throw "Goose runtime file failed integrity validation: $relative"
    }
}

if (-not $Quick) {
    $versionOutput = Get-GooseCliVersion -CliPath (Join-Path $gooseRoot "resources\bin\goose.exe")
    if ($versionOutput -notmatch [regex]::Escape([string]$lock.goose.version)) {
        throw "Goose CLI version mismatch: $versionOutput"
    }
}

Write-Host "Goose runtime validation passed: $($lock.runtime_id)"
