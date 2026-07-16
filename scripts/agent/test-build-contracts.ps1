[CmdletBinding()]
param(
    [string]$ProjectRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if (-not $ProjectRoot) {
    $ProjectRoot = Get-ChartPilotRoot
}
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$testRoot = Join-Path $ProjectRoot "workspace\goose-archive-contract-$([Guid]::NewGuid().ToString('N'))"
$archivePath = Join-Path $testRoot "unsafe.zip"
try {
    New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
    Add-Type -AssemblyName "System.IO.Compression"
    Add-Type -AssemblyName "System.IO.Compression.FileSystem"
    $stream = [System.IO.File]::Open($archivePath, [System.IO.FileMode]::CreateNew)
    try {
        $archive = New-Object System.IO.Compression.ZipArchive(
            $stream,
            [System.IO.Compression.ZipArchiveMode]::Create,
            $false
        )
        try {
            $entry = $archive.CreateEntry("dist-windows/../escape.txt")
            $writer = New-Object System.IO.StreamWriter($entry.Open(), $script:Utf8NoBom)
            try {
                $writer.Write("escape")
            }
            finally {
                $writer.Dispose()
            }
        }
        finally {
            $archive.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }

    $item = Get-Item -LiteralPath $archivePath
    $testLock = [PSCustomObject]@{
        upstream = [PSCustomObject]@{
            size_bytes = [int64]$item.Length
            sha256 = Get-FileSha256 -Path $archivePath
        }
        goose = [PSCustomObject]@{
            archive_root = "dist-windows"
        }
        required_files = @()
    }
    $rejected = $false
    try {
        Assert-GooseArchive -ArchivePath $archivePath -Lock $testLock
    }
    catch {
        if ($_.Exception.Message -match "traversal") {
            $rejected = $true
        }
        else {
            throw
        }
    }
    if (-not $rejected) {
        throw "Goose archive validation accepted a traversal entry."
    }
    Write-Host "Goose archive safety contract test passed."
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-GeneratedDirectory -Path $testRoot -ProjectRoot $ProjectRoot -AllowedTopLevelNames @("workspace")
    }
}
