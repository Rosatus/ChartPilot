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
$requirementsPath = Join-Path $projectRoot $runtimeLock.dependencies.direct_requirements
$finalLockPath = Join-Path $projectRoot $runtimeLock.dependencies.locked_requirements
$finalWheelhouse = Join-Path $projectRoot $runtimeLock.dependencies.wheelhouse
$stageRoot = Join-Path $buildRoot "runtime-lock-$([Guid]::NewGuid().ToString('N'))"
$stageRuntime = Join-Path $stageRoot "runtime"
$stageWheelhouse = Join-Path $stageRoot "wheelhouse"
$stageLockPath = Join-Path $stageRoot "requirements.runtime.lock.txt"
$completed = $false

try {
    New-Item -ItemType Directory -Path $stageRuntime, $stageWheelhouse -Force | Out-Null
    Get-VerifiedDownload `
        -Uri $runtimeLock.upstream.url `
        -Destination $archivePath `
        -ExpectedBytes ([int64]$runtimeLock.upstream.size_bytes) `
        -ExpectedSha256 $runtimeLock.upstream.sha256 `
        -Force:$ForceDownload | Out-Null

    Expand-WinPythonArchive `
        -ArchivePath $archivePath `
        -Destination (Join-Path $stageRuntime "winpython") `
        -ProjectRoot $projectRoot
    $python = Get-BundledPython -RuntimeRoot $stageRuntime
    Set-ChartPilotPythonEnvironment -WorkspaceRoot (Join-Path $stageRoot "workspace")

    Invoke-CheckedCommand -FilePath $python -Label "Verify WinPython" -Arguments @(
        "-I",
        "-c",
        "import platform,sys; assert platform.python_implementation() == 'CPython'; assert platform.python_version() == '3.13.13'; assert platform.architecture()[0] == '64bit'; print(sys.version)"
    )
    Invoke-CheckedCommand -FilePath $python -Label "Resolve runtime wheels" -Arguments @(
        "-I", "-m", "pip", "download",
        "--disable-pip-version-check",
        "--only-binary=:all:",
        "--platform", "win_amd64",
        "--python-version", "3.13",
        "--implementation", "cp",
        "--abi", "cp313",
        "--dest", $stageWheelhouse,
        "--requirement", $requirementsPath
    )
    Invoke-CheckedCommand -FilePath $python -Label "Generate dependency lock" -Arguments @(
        "-I",
        (Join-Path $projectRoot "scripts\runtime\write-runtime-metadata.py"),
        "lock-wheels",
        "--wheelhouse", $stageWheelhouse,
        "--requirements", $requirementsPath,
        "--output", $stageLockPath
    )

    $backupWheelhouse = Join-Path $buildRoot "wheelhouse-backup-$([Guid]::NewGuid().ToString('N'))"
    $backupLock = Join-Path $buildRoot "requirements-lock-backup-$([Guid]::NewGuid().ToString('N')).txt"
    $wheelhouseBackedUp = $false
    $lockBackedUp = $false
    try {
        if (Test-Path -LiteralPath $finalWheelhouse) {
            Move-Item -LiteralPath $finalWheelhouse -Destination $backupWheelhouse
            $wheelhouseBackedUp = $true
        }
        if (Test-Path -LiteralPath $finalLockPath) {
            Move-Item -LiteralPath $finalLockPath -Destination $backupLock
            $lockBackedUp = $true
        }
        Move-Item -LiteralPath $stageWheelhouse -Destination $finalWheelhouse
        Move-Item -LiteralPath $stageLockPath -Destination $finalLockPath
    }
    catch {
        if (Test-Path -LiteralPath $finalWheelhouse) {
            Remove-GeneratedDirectory -Path $finalWheelhouse -ProjectRoot $projectRoot -AllowedTopLevelNames @("wheelhouse")
        }
        if (Test-Path -LiteralPath $finalLockPath) {
            Remove-Item -LiteralPath $finalLockPath -Force
        }
        if ($wheelhouseBackedUp -and (Test-Path -LiteralPath $backupWheelhouse)) {
            Move-Item -LiteralPath $backupWheelhouse -Destination $finalWheelhouse
        }
        if ($lockBackedUp -and (Test-Path -LiteralPath $backupLock)) {
            Move-Item -LiteralPath $backupLock -Destination $finalLockPath
        }
        throw
    }
    finally {
        if (Test-Path -LiteralPath $backupWheelhouse) {
            Remove-GeneratedDirectory -Path $backupWheelhouse -ProjectRoot $projectRoot -AllowedTopLevelNames @("build")
        }
        if (Test-Path -LiteralPath $backupLock) {
            Remove-Item -LiteralPath $backupLock -Force
        }
    }

    $completed = $true
    Write-Host "Dependency lock written to $finalLockPath"
    Write-Host "Verified wheelhouse written to $finalWheelhouse"
}
finally {
    if ($completed -and (Test-Path -LiteralPath $stageRoot)) {
        Remove-GeneratedDirectory -Path $stageRoot -ProjectRoot $projectRoot -AllowedTopLevelNames @("build")
    }
    elseif (-not $completed) {
        Write-Warning "Lock refresh failed; staging retained for diagnosis: $stageRoot"
    }
}
