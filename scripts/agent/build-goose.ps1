[CmdletBinding()]
param(
    [string]$SourceArchive,
    [switch]$ForceDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$projectRoot = Get-ChartPilotRoot
$lock = Get-GooseLock -ProjectRoot $projectRoot
$buildRoot = Join-Path $projectRoot "build"
$runtimeRoot = Join-Path $projectRoot "runtime"
$cacheRoot = Join-Path $buildRoot "goose-cache"
$cachedArchive = Join-Path $cacheRoot ([string]$lock.upstream.asset)
$stageRoot = Join-Path $buildRoot "goose-build-$([Guid]::NewGuid().ToString('N'))"
$stageRuntime = Join-Path $stageRoot "runtime"
$stageGoose = Join-Path $stageRuntime "goose"
$stageManifest = Join-Path $stageRuntime "goose-manifest.json"
$completed = $false

try {
    New-Item -ItemType Directory -Path $stageRuntime -Force | Out-Null
    if ($SourceArchive) {
        $archivePath = [System.IO.Path]::GetFullPath($SourceArchive)
        Assert-GooseArchive -ArchivePath $archivePath -Lock $lock
        Write-Host "Using verified local Goose archive: $archivePath"
    }
    else {
        $archivePath = Get-VerifiedDownload `
            -Uri $lock.upstream.url `
            -Destination $cachedArchive `
            -ExpectedBytes ([int64]$lock.upstream.size_bytes) `
            -ExpectedSha256 $lock.upstream.sha256 `
            -Force:$ForceDownload
    }

    Expand-GooseArchive `
        -ArchivePath $archivePath `
        -Destination $stageGoose `
        -ProjectRoot $projectRoot `
        -Lock $lock

    $cli = Join-Path $stageGoose "resources\bin\goose.exe"
    $desktop = Join-Path $stageGoose "Goose.exe"
    $versionOutput = Get-GooseCliVersion -CliPath $cli
    if ($versionOutput -notmatch [regex]::Escape([string]$lock.goose.version)) {
        throw "Goose CLI version mismatch: $versionOutput"
    }

    $fileRecords = @()
    foreach ($relative in @($lock.required_files)) {
        $path = Join-Path $stageGoose ([string]$relative).Replace('/', '\')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Extracted Goose runtime is missing: $relative"
        }
        $item = Get-Item -LiteralPath $path
        $fileRecords += [ordered]@{
            path = ([string]$relative).Replace('\', '/')
            size_bytes = [int64]$item.Length
            sha256 = Get-FileSha256 -Path $path
        }
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $desktop
    $manifest = [ordered]@{
        schema_version = "chartpilot.goose-runtime/v1"
        runtime_id = [string]$lock.runtime_id
        status = "ready"
        upstream = $lock.upstream
        goose = [ordered]@{
            version = [string]$lock.goose.version
            architecture = [string]$lock.goose.architecture
            platform = [string]$lock.goose.platform
            variant = [string]$lock.goose.variant
            desktop = "goose/Goose.exe"
            cli = "goose/resources/bin/goose.exe"
            cli_version_output = $versionOutput
            desktop_signature_status = [string]$signature.Status
            desktop_signer = if ($signature.SignerCertificate) { [string]$signature.SignerCertificate.Subject } else { $null }
        }
        files = $fileRecords
        environment = [ordered]@{
            path_root = "workspace/goose"
            project_root_variable = "CHARTPILOT_ROOT"
            workspace_root_variable = "CHARTPILOT_WORKSPACE_ROOT"
            allowed_read_roots_variable = "CHARTPILOT_ALLOWED_READ_ROOTS"
        }
        health = [ordered]@{
            status = "success"
            checks = @("archive-integrity", "required-files", "cli-version")
        }
        builder = [ordered]@{
            script_version = "1.0.0"
            built_at_utc = [DateTime]::UtcNow.ToString("o")
        }
    }
    Write-Utf8JsonAtomic -Path $stageManifest -Value $manifest

    & (Join-Path $PSScriptRoot "test-goose.ps1") `
        -ProjectRoot $projectRoot `
        -RuntimeRoot $stageRuntime

    $finalGoose = Join-Path $runtimeRoot "goose"
    $finalManifest = Join-Path $runtimeRoot "goose-manifest.json"
    $backupRoot = Join-Path $buildRoot "goose-backup-$([Guid]::NewGuid().ToString('N'))"
    $backupGoose = Join-Path $backupRoot "goose"
    $backupManifest = Join-Path $backupRoot "goose-manifest.json"
    $backedUp = $false
    try {
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        if (Test-Path -LiteralPath $finalGoose) {
            Move-Item -LiteralPath $finalGoose -Destination $backupGoose
            $backedUp = $true
        }
        if (Test-Path -LiteralPath $finalManifest) {
            Move-Item -LiteralPath $finalManifest -Destination $backupManifest
        }
        Move-Item -LiteralPath $stageGoose -Destination $finalGoose
        Move-Item -LiteralPath $stageManifest -Destination $finalManifest
        & (Join-Path $PSScriptRoot "test-goose.ps1") `
            -ProjectRoot $projectRoot `
            -RuntimeRoot $runtimeRoot
    }
    catch {
        if (Test-Path -LiteralPath $finalGoose) {
            Remove-GeneratedDirectory -Path $finalGoose -ProjectRoot $projectRoot -AllowedTopLevelNames @("runtime")
        }
        if (Test-Path -LiteralPath $finalManifest) {
            Remove-Item -LiteralPath $finalManifest -Force
        }
        if ($backedUp -and (Test-Path -LiteralPath $backupGoose)) {
            Move-Item -LiteralPath $backupGoose -Destination $finalGoose
        }
        if (Test-Path -LiteralPath $backupManifest) {
            Move-Item -LiteralPath $backupManifest -Destination $finalManifest
        }
        throw
    }
    finally {
        if (Test-Path -LiteralPath $backupRoot) {
            Remove-GeneratedDirectory -Path $backupRoot -ProjectRoot $projectRoot -AllowedTopLevelNames @("build")
        }
    }

    $completed = $true
    Write-Host "Portable Goose runtime built successfully: $(Join-Path $runtimeRoot 'goose')"
}
finally {
    if ($completed -and (Test-Path -LiteralPath $stageRoot)) {
        Remove-GeneratedDirectory -Path $stageRoot -ProjectRoot $projectRoot -AllowedTopLevelNames @("build")
    }
    elseif (-not $completed) {
        Write-Warning "Goose build failed; staging retained for diagnosis: $stageRoot"
    }
}
