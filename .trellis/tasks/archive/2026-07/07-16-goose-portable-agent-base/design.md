# Portable Goose Agent Base Design

## Architecture

```text
Start-ChartPilot.cmd
  -> scripts/agent/start-chartpilot.ps1
     -> verify runtime/goose-manifest.json and runtime/runtime-manifest.json
     -> initialize workspace/goose/{config,data,state}
     -> stage skills/* into workspace/goose/config/skills
     -> set GOOSE_PATH_ROOT + CHARTPILOT_ROOT
     -> runtime/goose/Goose.exe
        -> bundled goosed/goose backend
        -> Summon loads ChartPilot Skills
        -> stdio ChartPilot MCP extension
           -> bundled python.exe -I agent/mcp/chartpilot_mcp.py
              -> deterministic profile/analyze/render CLI subprocesses
              -> workspace/tasks/<task-id>/ artifacts
```

The official Goose ZIP is treated as an immutable vendor runtime. Source-controlled files own
the lock, initialization templates, MCP bridge, launcher, tests, and documentation. Generated
runtime and workspace directories remain ignored.

## Runtime Layout

```text
ChartPilot/
  Start-ChartPilot.cmd
  agent/
    config/goose-config.yaml
    mcp/chartpilot_mcp.py
    tests/test_chartpilot_mcp.py
  runtime/
    goose/                    # generated from locked upstream ZIP
      Goose.exe
      resources/bin/goose.exe
    goose-manifest.json       # generated, hashes critical files
    winpython/...
    runtime-manifest.json
  skills/                     # source of truth
  workspace/
    goose/                    # GOOSE_PATH_ROOT, generated and writable
      config/config.yaml
      config/skills/...
    tasks/<task-id>/...
```

## Build And Integrity Contracts

`goose.lock.json` uses a dedicated schema and records the upstream archive contract. The Goose
build script accepts `-SourceArchive` for the user's existing download; otherwise it uses the
locked URL and cache. It validates size and SHA-256 before inspecting or extracting.

ZIP entries are normalized and rejected if rooted, traversal-bearing, duplicated after
case-folding, or outside `dist-windows/`. Extraction occurs in a generated staging directory.
The wrapper directory is removed while installing into `runtime/goose`. A generated manifest
records Goose version, architecture, critical relative paths, hashes, build time, and health.
Installation replaces an existing generated Goose runtime transactionally with rollback.

The launcher validates the manifest schema/status and critical hashes before each launch. This
also detects an upstream auto-update or local modification that would violate the pinned base.

## Portable Configuration

The launcher sets `GOOSE_PATH_ROOT=<root>/workspace/goose`, which Goose `v1.43.0` maps to its
backend config, data, state, plugin, and Agent directories. It also sets `CHARTPILOT_ROOT` and
the existing sanitized Python environment contract.

The initial Goose YAML config is copied only when absent. It enables `summon` and a stdio
`chartpilot` extension whose command is the bundled interpreter and whose arguments reference
the MCP bridge. Paths are relative to a launcher-controlled working directory or generated as
absolute values during initialization. Subsequent launches update only ChartPilot-owned config
keys through a structured YAML helper and preserve Provider entries, user preferences, and
secret storage.

Electron UI settings and caches use upstream Electron behavior and may remain in `%APPDATA%`.
They contain UI state, not the ChartPilot Python runtime or business artifacts. A future branded
source build may redirect them fully.

## MCP Tool Contract

The bridge uses official `mcp` `1.28.1` with stdio transport. It logs only to stderr so stdout
remains valid JSON-RPC.

### `chartpilot_profile_csv`

Input: CSV path, optional validated task ID, and sample mode. The bridge accepts only a regular
`.csv` file under deployment-derived read roots, allocates a safe task directory, invokes the
existing profiler, and returns the bounded `input_profile.json` object plus task ID.

### `chartpilot_analyze_data`

Input: task ID and a JSON analysis-plan object. The bridge resolves the existing profile and
task directory, writes `analysis_plan.json` atomically after structural bounds checks, invokes
the existing analysis CLI, and returns `analysis_result.json`. The deterministic CLI remains
responsible for full plan validation and calculation.

### `chartpilot_render_chart`

Input: task ID and optional font path under trusted read roots. The bridge resolves the frozen
analysis result, invokes the renderer, and returns `chart_result.json`, `summary.md`, and PNG
content or a bounded image reference supported by the MCP SDK.

All tools use fixed executable/script paths and process argument arrays. The bridge applies a
timeout, bounds captured output, supplies trusted roots from launcher configuration, and maps a
nonzero exit plus the final structured stderr object into an MCP tool error.

## Security Boundaries

- The default Goose config does not enable the Developer extension.
- Summon supplies instructions; it does not grant shell execution.
- MCP exposes no general file reader, shell, pip, network, or arbitrary Python tool.
- Source files are accessed only by the profiler, while downstream stages use task IDs and
  hash-bound artifacts.
- Write access is limited to `workspace/tasks/` and Goose's portable state directory.
- Provider credentials stay in Goose's credential mechanism and are never copied into
  ChartPilot plans, logs, or artifacts.
- `smart_approve` is a user-interaction safeguard, not an OS sandbox claim.

## Compatibility And Rollback

The target is native Windows 10/11 x64 with PowerShell 5.1 compatibility. No CUDA, installer,
admin permission, or system Python is required. Build scripts use ASCII syntax and direct
argument arrays.

Goose and Python locks remain independent so either runtime can be upgraded deliberately. A
failed staged build restores the prior generated runtime. Rollback of this feature removes the
Goose launcher/runtime integration while leaving the existing deterministic Python CLIs and
their direct invocation contracts usable.

## Trade-offs

- Using the official Desktop ZIP delivers the UI quickly but retains Goose branding and some
  Electron user-profile state. A custom source distribution is deferred.
- The official Python MCP SDK adds dependencies to the locked wheelhouse, but avoids a custom
  protocol implementation and gives a testable standard boundary.
- A restricted MCP surface sacrifices generic coding-agent flexibility in exchange for
  deterministic data processing and a smaller Windows risk surface.
