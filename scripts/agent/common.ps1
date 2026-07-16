Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\runtime\common.ps1")

function Get-GooseLock {
    param(
        [string]$ProjectRoot = (Get-ChartPilotRoot)
    )

    $lockPath = Join-Path $ProjectRoot "goose.lock.json"
    $lock = Read-JsonFile -Path $lockPath
    if ($lock.schema_version -ne "chartpilot.goose-lock/v1") {
        throw "Unsupported Goose lock schema: $($lock.schema_version)"
    }
    if ($lock.upstream.sha256 -notmatch "^[0-9a-f]{64}$") {
        throw "goose.lock.json contains an invalid upstream SHA-256."
    }
    if ([int64]$lock.upstream.size_bytes -le 0) {
        throw "goose.lock.json contains an invalid upstream size."
    }
    if ($lock.goose.platform -ne "windows" -or $lock.goose.architecture -ne "x86_64") {
        throw "goose.lock.json is not a Windows x64 distribution."
    }
    if ($lock.goose.variant -ne "desktop-nocuda") {
        throw "goose.lock.json must select the non-CUDA Desktop variant."
    }
    return $lock
}

function Assert-GooseArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,
        [Parameter(Mandatory = $true)]
        [object]$Lock
    )

    if (-not (Test-FileArtifact `
        -Path $ArchivePath `
        -ExpectedBytes ([int64]$Lock.upstream.size_bytes) `
        -ExpectedSha256 $Lock.upstream.sha256)) {
        if (-not (Test-Path -LiteralPath $ArchivePath -PathType Leaf)) {
            throw "Goose archive not found: $ArchivePath"
        }
        $actualBytes = (Get-Item -LiteralPath $ArchivePath).Length
        $actualHash = Get-FileSha256 -Path $ArchivePath
        throw "Goose archive failed verification (bytes=$actualBytes, sha256=$actualHash)."
    }

    Add-Type -AssemblyName "System.IO.Compression.FileSystem"
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $root = [string]$Lock.goose.archive_root
        $prefix = "$root/"
        $seen = New-Object "System.Collections.Generic.HashSet[string]" ([System.StringComparer]::OrdinalIgnoreCase)
        $files = New-Object "System.Collections.Generic.HashSet[string]" ([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            if (-not $name -or $name.StartsWith('/') -or $name.StartsWith('//') -or $name -match '^[A-Za-z]:') {
                throw "Goose archive contains a rooted or empty path."
            }
            if (-not $name.StartsWith($prefix, [System.StringComparison]::Ordinal)) {
                throw "Goose archive entry is outside '$prefix': $name"
            }
            $parts = @($name.Split('/') | Where-Object { $_ -ne "" })
            if ($parts -contains "." -or $parts -contains "..") {
                throw "Goose archive contains a traversal path: $name"
            }
            if (-not $seen.Add($name)) {
                throw "Goose archive contains a duplicate path: $name"
            }
            if (-not $name.EndsWith('/')) {
                $relative = $name.Substring($prefix.Length)
                [void]$files.Add($relative)
            }
        }
        foreach ($relative in @($Lock.required_files)) {
            if (-not $files.Contains([string]$relative)) {
                throw "Goose archive is missing required file: $relative"
            }
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Expand-GooseArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,
        [Parameter(Mandatory = $true)]
        [string]$Destination,
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot,
        [Parameter(Mandatory = $true)]
        [object]$Lock
    )

    Assert-GooseArchive -ArchivePath $ArchivePath -Lock $Lock
    $extractRoot = Join-Path (Split-Path -Parent $Destination) "extract-$([Guid]::NewGuid().ToString('N'))"
    Assert-GeneratedPath -Path $extractRoot -ProjectRoot $ProjectRoot -AllowedTopLevelNames @("build") | Out-Null
    try {
        New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
        [System.IO.Compression.ZipFile]::ExtractToDirectory($ArchivePath, $extractRoot)
        $sourceRoot = Join-Path $extractRoot ([string]$Lock.goose.archive_root)
        if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) {
            throw "Goose archive root was not extracted: $sourceRoot"
        }
        if (Test-Path -LiteralPath $Destination) {
            throw "Goose staging destination already exists: $Destination"
        }
        Move-Item -LiteralPath $sourceRoot -Destination $Destination
    }
    finally {
        if (Test-Path -LiteralPath $extractRoot) {
            Remove-GeneratedDirectory -Path $extractRoot -ProjectRoot $ProjectRoot -AllowedTopLevelNames @("build")
        }
    }
}

function Get-GooseCliVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CliPath
    )

    $lines = @(& $CliPath --version 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Goose CLI version check failed with exit code $exitCode."
    }
    return ($lines -join "`n").Trim()
}

function Write-Utf8JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temporary = "$Path.$([Guid]::NewGuid().ToString('N')).partial"
    try {
        $text = $Value | ConvertTo-Json -Depth 20
        [System.IO.File]::WriteAllText($temporary, "$text`n", $script:Utf8NoBom)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}
