# ChartPilot

English | [简体中文](README.zh-CN.md)

ChartPilot is a local-first Windows CSV analysis Agent built on Goose Desktop. It ships with
pinned Goose and WinPython runtimes, adapts Python templates to each natural-language request and
CSV, and performs analysis and PNG rendering locally without system Python.

> [!IMPORTANT]
> ChartPilot exposes exactly two adaptive MCP tools: prepare a prompt-plus-CSV task, then execute
> Agent-authored stage Python. Goose's generic Developer extension is not enabled by default.

## Core capabilities

- Start from compact inspect, analysis, and render templates and modify them for the actual
  schema, business logic, thresholds, and presentation request.
- Handle nested and domain-specific operations directly with pandas/numpy instead of routing
  through a fixed operation vocabulary.
- Build task-specific single- or multi-panel PNG reports with matplotlib/Pillow and Chinese font
  support.
- Match peer-baseline/threshold/bubble requests to an evidence-backed chart archetype while keeping
  a free-form route for other analytical intents.
- Use pinned WinPython CPython 3.13.13 Windows x64 instead of system `python` or `py.exe`.
- Use pinned Goose Desktop 1.43.0 Windows x64 without CUDA, Node.js, Rust, or an installer.
- Preserve exact generated source, runtime identity, bounded process output, execution status,
  artifact hashes, and task-local results.

## Repository structure

```text
ChartPilot/
├── Start-ChartPilot.cmd
├── goose.lock.json
├── runtime.lock.json
├── requirements.txt
├── requirements.runtime.lock.txt
├── agent/
├── scripts/agent/
├── scripts/runtime/
├── skills/
│   └── chartpilot-run-python/
├── ChartPilot需求规格说明.md
├── Skill开发说明.md
└── Windows离线部署方案.md
```

`runtime/`, `wheelhouse/`, `workspace/`, `build/`, and `dist/` are generated locally and excluded
from Git.

## Build the portable runtimes

The build host needs Windows 10/11 x64 and PowerShell 5.1 or later. A preinstalled Python is not
required. ChartPilot pins `WinPython64-3.13.13.0dot.zip` from WinPython release
`17.4.20260511final` and verifies its byte size and SHA-256 before extraction.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\build-runtime.ps1
```

ChartPilot also pins the non-CUDA `Goose-win32-x64.zip` asset from Goose release `v1.43.0`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\build-goose.ps1 `
  -SourceArchive "C:\path\to\Goose-win32-x64.zip"
```

Omit `-SourceArchive` to download the locked asset. Refresh the dependency lock only after
changing `requirements.txt`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
```

Review every version and hash change in `requirements.runtime.lock.txt`.

## Start ChartPilot

Run `Start-ChartPilot.cmd`. The launcher validates both runtime manifests, initializes portable
Goose state under `workspace/goose`, stages the single ChartPilot adaptive Skill, and starts
Goose Desktop. Configure a model Provider in Goose on first use.

The launcher allows reads beneath the ChartPilot directory and current Windows user profile by
default. Generated task code and artifacts are stored beneath `workspace/tasks/`.

## Run the adaptive workflow

Give Goose a request and CSV path, or a local UTF-8 `.md`/`.txt` request file and CSV path. The
Skill calls `chartpilot_prepare_adaptive_task`, reviews the returned task context and three
templates, modifies each stage when useful, then calls `chartpilot_run_task_python` for
`inspect`, `analysis`, and `render`.

```text
request.md + task_context.json + generated_inspect.py
  -> inspection.json
  -> generated_analysis.py + result.csv + optional declared supporting files + analysis_result.json
  -> generated_chart.py + chart.png + chart_result.json + summary.md
```

Before analysis, the Agent matches analytical roles against Skill visual archetypes. A matching
group/peer-baseline/threshold request uses coordinated population-composition and aggregate-bubble
panels; nonmatching requests keep a task-specific free-form plan. The Agent reviews generated
render source against that plan, then iterates when calculations, labels, chart composition, or
presentation do not satisfy the request. Execution responses include bounded process diagnostics;
missing font glyphs fail render. The Agent visually inspects the actual PNG before reporting only
committed artifacts. There is no deterministic alternate route or fixed renderer.

## Validate and package

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\test-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\test-agent.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

The output is `dist/ChartPilot-win-x64-goose-py3.13.zip`. The optional SY135 reference acceptance
test accepts its external case directory through `scripts/agent/test-sy135-adaptive.py`; it does
not package the source data or manual artifacts.

## Runtime and security boundaries

- The MCP bridge validates `runtime/runtime-manifest.json`, stores exact submitted code, invokes
  bundled WinPython with argument arrays, stages outputs, and records every attempt.
- Generated task Python is intentionally flexible and is not checked against an operation or
  import allowlist.
- Source files are SHA-256-bound and checked before every stage. Stage completion manifests are
  installed only after artifact validation.
- Target machines do not run online pip; dependencies change only during a hash-reviewed build.
- Goose and WinPython are not Windows operating-system sandboxes. Generated code uses the current
  user's permissions; deployment ACL and network policy remain external.
- Do not use Goose self-update in the pinned distribution. Upgrade `goose.lock.json` and rebuild
  deliberately.

## Project documents

- [Requirements specification](ChartPilot需求规格说明.md)
- [Skill development notes](Skill开发说明.md)
- [Windows offline deployment](Windows离线部署方案.md)

## License

The project has not selected a software license. Public availability does not grant rights to
use, modify, or redistribute the repository beyond applicable law. Generated
`runtime/third-party-licenses.json` records Python distribution licenses. Bundled Goose
Apache-2.0 and Chromium notices are retained under `runtime/goose/`.
