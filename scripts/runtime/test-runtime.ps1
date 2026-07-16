[CmdletBinding()]
param(
    [string]$ProjectRoot,
    [string]$RuntimeRoot,
    [switch]$SkipUnitTests,
    [switch]$SkipSmokeTest,
    [switch]$NoManifestUpdate
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

$runtimeLock = Get-RuntimeLock -ProjectRoot $ProjectRoot
$manifestPath = Join-Path $RuntimeRoot "runtime-manifest.json"
$python = Get-BundledPython -RuntimeRoot $RuntimeRoot
$workspaceRoot = Join-Path $ProjectRoot "workspace\runtime-validation"
Set-ChartPilotPythonEnvironment -WorkspaceRoot $workspaceRoot

$checks = [System.Collections.Generic.List[string]]::new()
$manifest = Read-JsonFile -Path $manifestPath
if ($manifest.schema_version -ne "chartpilot.runtime/v1") {
    throw "Unsupported runtime manifest schema: $($manifest.schema_version)"
}
if ($manifest.runtime_id -ne $runtimeLock.runtime_id) {
    throw "Runtime manifest ID does not match runtime.lock.json."
}
if ($manifest.python.interpreter -ne $runtimeLock.python.interpreter) {
    throw "Runtime manifest interpreter path does not match runtime.lock.json."
}
$checks.Add("manifest-contract")

Invoke-CheckedCommand -FilePath $python -Label "Verify interpreter" -Arguments @(
    "-I",
    "-c",
    "import platform,sys; assert platform.python_implementation() == 'CPython'; assert platform.python_version() == '3.13.13'; assert platform.architecture()[0] == '64bit'; print(sys.executable)"
)
$checks.Add("interpreter")

Invoke-CheckedCommand -FilePath $python -Label "Check installed dependencies" -Arguments @(
    "-I", "-m", "pip", "check"
)
$checks.Add("pip-check")

Invoke-CheckedCommand -FilePath $python -Label "Import runtime dependencies" -Arguments @(
    "-I",
    "-c",
    "import importlib.metadata,pandas,matplotlib,PIL,mcp,yaml; print(pandas.__version__, matplotlib.__version__, PIL.__version__, importlib.metadata.version('mcp'), yaml.__version__)"
)
$checks.Add("imports")

$cliScripts = @(
    "skills\chartpilot-profile-csv\scripts\profile_csv.py",
    "skills\chartpilot-analyze-data\scripts\run_analysis.py",
    "skills\chartpilot-render-chart\scripts\render_chart.py"
)
foreach ($relativeScript in $cliScripts) {
    $scriptPath = Join-Path $ProjectRoot $relativeScript
    Invoke-CheckedCommand -FilePath $python -Label "CLI help: $relativeScript" -Arguments @(
        "-I", $scriptPath, "--help"
    )
}
$checks.Add("cli-help")

if (-not $SkipUnitTests) {
    Invoke-CheckedCommand -FilePath $python -Label "Analysis regression tests" -Arguments @(
        "-I", "-m", "unittest", "discover",
        "-s", (Join-Path $ProjectRoot "skills\chartpilot-analyze-data\tests"),
        "-v"
    )
    $checks.Add("unit-tests")
}

if (-not $SkipSmokeTest) {
    Invoke-CheckedCommand -FilePath $python -Label "End-to-end smoke test" -Arguments @(
        "-I",
        (Join-Path $ProjectRoot "scripts\runtime\smoke-test.py"),
        "--project-root", $ProjectRoot,
        "--workspace-root", $workspaceRoot
    )
    $checks.Add("csv-to-png-smoke")
}

if (-not $NoManifestUpdate) {
    $manifest.status = "ready"
    $manifest.health = [PSCustomObject]@{
        status = "success"
        checked_at_utc = [DateTime]::UtcNow.ToString("o")
        checks = @($checks)
    }
    $temporaryManifest = "$manifestPath.$([Guid]::NewGuid().ToString('N')).partial"
    $json = $manifest | ConvertTo-Json -Depth 32
    [System.IO.File]::WriteAllText(
        $temporaryManifest,
        $json + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force
}

Write-Host "Runtime validation passed: $RuntimeRoot"
