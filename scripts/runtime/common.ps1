Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$script:Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $script:Utf8NoBom
[Console]::OutputEncoding = $script:Utf8NoBom
$OutputEncoding = $script:Utf8NoBom

function Get-ChartPilotRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}

function Read-JsonFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required JSON file not found: $Path"
    }

    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "Invalid JSON file '$Path': $($_.Exception.Message)"
    }
}

function Get-RuntimeLock {
    param(
        [string]$ProjectRoot = (Get-ChartPilotRoot)
    )

    $lockPath = Join-Path $ProjectRoot "runtime.lock.json"
    $lock = Read-JsonFile -Path $lockPath
    if ($lock.schema_version -ne "chartpilot.runtime-lock/v1") {
        throw "Unsupported runtime lock schema: $($lock.schema_version)"
    }
    if ($lock.upstream.sha256 -notmatch "^[0-9a-f]{64}$") {
        throw "runtime.lock.json contains an invalid upstream SHA-256."
    }
    if ([int64]$lock.upstream.size_bytes -le 0) {
        throw "runtime.lock.json contains an invalid upstream size."
    }
    return $lock
}

function Get-FileSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-FileArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [int64]$ExpectedBytes,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha256
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $ExpectedBytes) {
        return $false
    }
    return (Get-FileSha256 -Path $Path) -eq $ExpectedSha256.ToLowerInvariant()
}

function Get-VerifiedDownload {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [Parameter(Mandatory = $true)]
        [int64]$ExpectedBytes,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha256,
        [switch]$Force
    )

    $destinationPath = [System.IO.Path]::GetFullPath($Destination)
    $parent = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null

    if (-not $Force -and (Test-FileArtifact -Path $destinationPath -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256)) {
        Write-Host "Using verified cached asset: $destinationPath"
        return $destinationPath
    }

    $destinationName = Split-Path -Leaf $destinationPath
    Get-ChildItem -LiteralPath $parent -Filter "$destinationName.*.partial" -File -ErrorAction SilentlyContinue |
        Remove-Item -Force
    $temporary = "$destinationPath.$([Guid]::NewGuid().ToString('N')).partial"
    try {
        Write-Host "Downloading $Uri"
        $downloaded = $false
        $bits = Get-Command "Start-BitsTransfer" -ErrorAction SilentlyContinue
        if ($bits) {
            try {
                Start-BitsTransfer `
                    -Source $Uri `
                    -Destination $temporary `
                    -DisplayName "ChartPilot runtime download" `
                    -Description $destinationName `
                    -ErrorAction Stop
                $downloaded = $true
            }
            catch {
                Write-Warning "BITS download failed; falling back: $($_.Exception.Message)"
                if (Test-Path -LiteralPath $temporary) {
                    Remove-Item -LiteralPath $temporary -Force
                }
            }
        }

        $curl = Get-Command "curl.exe" -ErrorAction SilentlyContinue
        if (-not $downloaded -and $curl) {
            & $curl.Source `
                --location `
                --fail `
                --retry 3 `
                --retry-delay 2 `
                --connect-timeout 30 `
                --max-time 900 `
                --silent `
                --show-error `
                --user-agent "ChartPilot-runtime-builder/1.0" `
                --output $temporary `
                $Uri
            if ($LASTEXITCODE -ne 0 -and -not (Test-FileArtifact -Path $temporary -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256)) {
                throw "curl.exe failed with exit code $LASTEXITCODE."
            }
            $downloaded = $true
        }
        elseif (-not $downloaded) {
            Invoke-WebRequest `
                -Headers @{ "User-Agent" = "ChartPilot-runtime-builder/1.0" } `
                -Uri $Uri `
                -OutFile $temporary `
                -UseBasicParsing
            $downloaded = $true
        }
        if (-not (Test-FileArtifact -Path $temporary -ExpectedBytes $ExpectedBytes -ExpectedSha256 $ExpectedSha256)) {
            $actualBytes = (Get-Item -LiteralPath $temporary).Length
            $actualHash = Get-FileSha256 -Path $temporary
            throw "Downloaded asset failed verification (bytes=$actualBytes, sha256=$actualHash)."
        }
        Move-Item -LiteralPath $temporary -Destination $destinationPath -Force
        return $destinationPath
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Assert-GeneratedPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,
        [Parameter(Mandatory = $true)]
        [string[]]$AllowedTopLevelNames
    )

    $separator = [System.IO.Path]::DirectorySeparatorChar
    $root = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd($separator)
    $candidate = [System.IO.Path]::GetFullPath($Path).TrimEnd($separator)
    $prefix = "$root\"
    if (-not $candidate.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Generated path escapes the project root: $candidate"
    }
    $relative = $candidate.Substring($prefix.Length)
    $topLevel = $relative.Split($separator, 2)[0]
    if ($AllowedTopLevelNames -notcontains $topLevel) {
        throw "Generated path is not in an allowed output directory: $candidate"
    }
    return $candidate
}

function Remove-GeneratedDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,
        [Parameter(Mandatory = $true)]
        [string[]]$AllowedTopLevelNames
    )

    $safePath = Assert-GeneratedPath -Path $Path -ProjectRoot $ProjectRoot -AllowedTopLevelNames $AllowedTopLevelNames
    if (Test-Path -LiteralPath $safePath) {
        Remove-Item -LiteralPath $safePath -Recurse -Force
    }
}

function Expand-WinPythonArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $extractRoot = Join-Path (Split-Path -Parent $Destination) "extract-$([Guid]::NewGuid().ToString('N'))"
    Assert-GeneratedPath -Path $extractRoot -ProjectRoot $ProjectRoot -AllowedTopLevelNames @("build") | Out-Null
    try {
        New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
        Expand-Archive -LiteralPath $ArchivePath -DestinationPath $extractRoot -Force
        $candidates = @(
            Get-ChildItem -LiteralPath $extractRoot -Recurse -File -Filter "python.exe" |
                Where-Object { $_.Directory.Name -eq "python" }
        )
        if ($candidates.Count -ne 1) {
            throw "Expected exactly one WinPython python/python.exe, found $($candidates.Count)."
        }
        $sourceRoot = $candidates[0].Directory.Parent.FullName
        if (Test-Path -LiteralPath $Destination) {
            throw "WinPython staging destination already exists: $Destination"
        }
        Move-Item -LiteralPath $sourceRoot -Destination $Destination
    }
    finally {
        if (Test-Path -LiteralPath $extractRoot) {
            Remove-Item -LiteralPath $extractRoot -Recurse -Force
        }
    }
}

function Get-BundledPython {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RuntimeRoot
    )

    $python = Join-Path $RuntimeRoot "winpython\python\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "Bundled Python interpreter not found: $python"
    }
    return [System.IO.Path]::GetFullPath($python)
}

function Set-ChartPilotPythonEnvironment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$WorkspaceRoot
    )

    $workspace = [System.IO.Path]::GetFullPath($WorkspaceRoot)
    $paths = @{
        HOME = Join-Path $workspace "home"
        TEMP = Join-Path $workspace "temp"
        TMP = Join-Path $workspace "temp"
        MPLCONFIGDIR = Join-Path $workspace "matplotlib"
        PYTHONPYCACHEPREFIX = Join-Path $workspace "pycache"
    }
    foreach ($path in $paths.Values) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }

    $env:PYTHONNOUSERSITE = "1"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:MPLBACKEND = "Agg"
    foreach ($name in @("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV")) {
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
    foreach ($entry in $paths.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    Write-Host "[$Label] $FilePath $($Arguments -join ' ')"
    & $FilePath @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Label failed with exit code $exitCode."
    }
}
