[CmdletBinding()]
param(
    [string]$OutputName = "ChartPilot-win-x64-goose-py3.13.zip"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

function Copy-FilteredTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Source,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    $separator = [System.IO.Path]::DirectorySeparatorChar
    $sourceRoot = [System.IO.Path]::GetFullPath($Source).TrimEnd($separator)
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force -File |
        Where-Object {
            $_.FullName -notmatch "[\\/]__pycache__[\\/]" -and
            $_.Extension -notin @(".pyc", ".pyo")
        } |
        ForEach-Object {
            $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart($separator)
            $target = Join-Path $Destination $relative
            New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
}

$projectRoot = Get-ChartPilotRoot
$runtimeRoot = Join-Path $projectRoot "runtime"
$distRoot = Join-Path $projectRoot "dist"
$buildRoot = Join-Path $projectRoot "build"
$stageRoot = Join-Path $buildRoot "package-$([Guid]::NewGuid().ToString('N'))"
$packageRoot = Join-Path $stageRoot "ChartPilot"
$outputPath = Join-Path $distRoot $OutputName
$temporaryZip = "$outputPath.$([Guid]::NewGuid().ToString('N')).partial.zip"
$completed = $false

try {
    & (Join-Path $PSScriptRoot "test-runtime.ps1") `
        -ProjectRoot $projectRoot `
        -RuntimeRoot $runtimeRoot
    & (Join-Path $projectRoot "scripts\agent\test-agent.ps1") `
        -ProjectRoot $projectRoot `
        -RuntimeRoot $runtimeRoot

    New-Item -ItemType Directory -Path $packageRoot, $distRoot -Force | Out-Null
    Copy-FilteredTree -Source $runtimeRoot -Destination (Join-Path $packageRoot "runtime")
    Copy-FilteredTree -Source (Join-Path $projectRoot "agent") -Destination (Join-Path $packageRoot "agent")
    Copy-FilteredTree -Source (Join-Path $projectRoot "skills") -Destination (Join-Path $packageRoot "skills")
    Copy-FilteredTree -Source (Join-Path $projectRoot "skills") -Destination (Join-Path $packageRoot ".agents\skills")
    Copy-FilteredTree -Source (Join-Path $projectRoot "scripts\agent") -Destination (Join-Path $packageRoot "scripts\agent")
    Copy-FilteredTree -Source (Join-Path $projectRoot "scripts\runtime") -Destination (Join-Path $packageRoot "scripts\runtime")

    $releaseFilesPath = Join-Path $projectRoot "release.files.json"
    $releaseFiles = Read-JsonFile -Path $releaseFilesPath
    if ($releaseFiles.schema_version -ne "chartpilot.release-files/v1") {
        throw "Unsupported release file manifest schema: $($releaseFiles.schema_version)"
    }
    foreach ($relativePath in @($releaseFiles.root_files)) {
        if (-not $relativePath -or [System.IO.Path]::IsPathRooted($relativePath) -or $relativePath.Contains("..")) {
            throw "Invalid release root file entry: $relativePath"
        }
        $source = Join-Path $projectRoot $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Release input not found: $source"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $packageRoot $relativePath) -Force
    }

    if (Test-Path -LiteralPath $outputPath) {
        Remove-Item -LiteralPath $outputPath -Force
    }
    Compress-Archive -LiteralPath $packageRoot -DestinationPath $temporaryZip -CompressionLevel Optimal
    Move-Item -LiteralPath $temporaryZip -Destination $outputPath

    Add-Type -AssemblyName "System.IO.Compression.FileSystem"
    $archive = [System.IO.Compression.ZipFile]::OpenRead($outputPath)
    try {
        $entries = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
        $requiredEntries = @(
            "ChartPilot/runtime/runtime-manifest.json",
            "ChartPilot/runtime/goose-manifest.json",
            "ChartPilot/runtime/third-party-licenses.json",
            "ChartPilot/runtime/winpython/python/python.exe",
            "ChartPilot/runtime/goose/Goose.exe",
            "ChartPilot/runtime/goose/resources/bin/goose.exe",
            "ChartPilot/runtime/goose/LICENSE",
            "ChartPilot/Start-ChartPilot.cmd",
            "ChartPilot/agent/mcp/chartpilot_mcp.py",
            "ChartPilot/skills/chartpilot-run-python/SKILL.md",
            "ChartPilot/skills/chartpilot-run-python/assets/templates/inspect_csv.py",
            "ChartPilot/skills/chartpilot-run-python/assets/templates/analyze_csv.py",
            "ChartPilot/skills/chartpilot-run-python/assets/templates/render_chart.py",
            "ChartPilot/skills/chartpilot-run-python/references/visual-archetypes.md",
            "ChartPilot/.agents/skills/chartpilot-run-python/SKILL.md",
            "ChartPilot/.agents/skills/chartpilot-run-python/assets/templates/inspect_csv.py",
            "ChartPilot/.agents/skills/chartpilot-run-python/assets/templates/analyze_csv.py",
            "ChartPilot/.agents/skills/chartpilot-run-python/assets/templates/render_chart.py",
            "ChartPilot/.agents/skills/chartpilot-run-python/references/visual-archetypes.md",
            "ChartPilot/scripts/agent/start-chartpilot.ps1",
            "ChartPilot/scripts/agent/test-agent.ps1",
            "ChartPilot/scripts/runtime/test-runtime.ps1",
            "ChartPilot/release.files.json",
            "ChartPilot/requirements.runtime.lock.txt",
            "ChartPilot/runtime.lock.json",
            "ChartPilot/goose.lock.json"
        )
        $missingEntries = @($requiredEntries | Where-Object { $entries -notcontains $_ })
        if ($missingEntries.Count -gt 0) {
            throw "Release ZIP is missing required entries: $($missingEntries -join ', ')"
        }
        $forbiddenPrefixes = @(
            "ChartPilot/.git/",
            "ChartPilot/.trellis/",
            "ChartPilot/.codex/",
            "ChartPilot/build/",
            "ChartPilot/dist/",
            "ChartPilot/wheelhouse/",
            "ChartPilot/workspace/"
        )
        $forbiddenEntries = @(
            $entries | Where-Object {
                $entry = $_
                @($forbiddenPrefixes | Where-Object {
                    $entry.StartsWith($_, [System.StringComparison]::OrdinalIgnoreCase)
                }).Count -gt 0
            }
        )
        if ($forbiddenEntries.Count -gt 0) {
            throw "Release ZIP contains forbidden project data: $($forbiddenEntries -join ', ')"
        }
        $removedEntries = @(
            $entries | Where-Object {
                $_ -match "chartpilot-(profile-csv|analyze-data|render-chart)"
            }
        )
        if ($removedEntries.Count -gt 0) {
            throw "Release ZIP contains removed deterministic routes: $($removedEntries -join ', ')"
        }
    }
    finally {
        $archive.Dispose()
    }

    $completed = $true
    Write-Host "Release package created: $outputPath"
}
finally {
    if (Test-Path -LiteralPath $temporaryZip) {
        Remove-Item -LiteralPath $temporaryZip -Force
    }
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-GeneratedDirectory -Path $stageRoot -ProjectRoot $projectRoot -AllowedTopLevelNames @("build")
    }
    if (-not $completed) {
        Write-Warning "Release packaging failed."
    }
}
