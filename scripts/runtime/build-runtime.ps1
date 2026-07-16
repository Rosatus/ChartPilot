[CmdletBinding()]
param(
    [switch]$ForceDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$projectRoot = Get-ChartPilotRoot
$runtimeLock = Get-RuntimeLock -ProjectRoot $projectRoot
$buildRoot = Join-Path $projectRoot "build"
$cacheRoot = Join-Path $buildRoot "runtime-cache"
$archivePath = Join-Path $cacheRoot $runtimeLock.upstream.asset
$dependencyLock = Join-Path $projectRoot $runtimeLock.dependencies.locked_requirements
$wheelhouse = Join-Path $projectRoot $runtimeLock.dependencies.wheelhouse
$finalRuntime = Join-Path $projectRoot "runtime"
$stageRoot = Join-Path $buildRoot "runtime-build-$([Guid]::NewGuid().ToString('N'))"
$stageRuntime = Join-Path $stageRoot "runtime"
$stageWinPython = Join-Path $stageRuntime "winpython"
$completed = $false

if (-not (Test-Path -LiteralPath $dependencyLock -PathType Leaf)) {
    throw "Dependency lock not found. Run scripts/runtime/update-lock.ps1 first."
}

try {
    New-Item -ItemType Directory -Path $stageRuntime, $wheelhouse -Force | Out-Null
    Get-VerifiedDownload `
        -Uri $runtimeLock.upstream.url `
        -Destination $archivePath `
        -ExpectedBytes ([int64]$runtimeLock.upstream.size_bytes) `
        -ExpectedSha256 $runtimeLock.upstream.sha256 `
        -Force:$ForceDownload | Out-Null
    Expand-WinPythonArchive `
        -ArchivePath $archivePath `
        -Destination $stageWinPython `
        -ProjectRoot $projectRoot

    $python = Get-BundledPython -RuntimeRoot $stageRuntime
    Set-ChartPilotPythonEnvironment -WorkspaceRoot (Join-Path $stageRoot "workspace")
    Invoke-CheckedCommand -FilePath $python -Label "Verify WinPython" -Arguments @(
        "-I",
        "-c",
        "import platform; assert platform.python_version() == '3.13.13'; assert platform.architecture()[0] == '64bit'"
    )
    Invoke-CheckedCommand -FilePath $python -Label "Populate locked wheelhouse" -Arguments @(
        "-I", "-m", "pip", "download",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--require-hashes",
        "--dest", $wheelhouse,
        "--requirement", $dependencyLock
    )
    Invoke-CheckedCommand -FilePath $python -Label "Install locked dependencies" -Arguments @(
        "-I", "-m", "pip", "install",
        "--disable-pip-version-check",
        "--no-index",
        "--find-links", $wheelhouse,
        "--require-hashes",
        "--requirement", $dependencyLock
    )

    Invoke-CheckedCommand -FilePath $python -Label "Write runtime metadata" -Arguments @(
        "-I",
        (Join-Path $projectRoot "scripts\runtime\write-runtime-metadata.py"),
        "runtime-manifest",
        "--runtime-lock", (Join-Path $projectRoot "runtime.lock.json"),
        "--dependency-lock", $dependencyLock,
        "--wheelhouse", $wheelhouse,
        "--output", (Join-Path $stageRuntime "runtime-manifest.json"),
        "--licenses-output", (Join-Path $stageRuntime "third-party-licenses.json")
    )

    & (Join-Path $PSScriptRoot "test-runtime.ps1") `
        -ProjectRoot $projectRoot `
        -RuntimeRoot $stageRuntime

    $backupRuntime = Join-Path $buildRoot "runtime-backup-$([Guid]::NewGuid().ToString('N'))"
    $runtimeBackedUp = $false
    try {
        if (Test-Path -LiteralPath $finalRuntime) {
            Move-Item -LiteralPath $finalRuntime -Destination $backupRuntime
            $runtimeBackedUp = $true
        }
        Move-Item -LiteralPath $stageRuntime -Destination $finalRuntime
        & (Join-Path $PSScriptRoot "test-runtime.ps1") `
            -ProjectRoot $projectRoot `
            -RuntimeRoot $finalRuntime
    }
    catch {
        if (Test-Path -LiteralPath $finalRuntime) {
            Remove-GeneratedDirectory -Path $finalRuntime -ProjectRoot $projectRoot -AllowedTopLevelNames @("runtime")
        }
        if ($runtimeBackedUp -and (Test-Path -LiteralPath $backupRuntime)) {
            Move-Item -LiteralPath $backupRuntime -Destination $finalRuntime
        }
        throw
    }
    finally {
        if (Test-Path -LiteralPath $backupRuntime) {
            Remove-GeneratedDirectory -Path $backupRuntime -ProjectRoot $projectRoot -AllowedTopLevelNames @("build")
        }
    }

    $completed = $true
    Write-Host "Portable runtime built successfully: $finalRuntime"
}
finally {
    if ($completed -and (Test-Path -LiteralPath $stageRoot)) {
        Remove-GeneratedDirectory -Path $stageRoot -ProjectRoot $projectRoot -AllowedTopLevelNames @("build")
    }
    elseif (-not $completed) {
        Write-Warning "Runtime build failed; staging retained for diagnosis: $stageRoot"
    }
}
