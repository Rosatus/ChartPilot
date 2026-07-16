# ChartPilot

English | [简体中文](README.zh-CN.md)

ChartPilot is a local-first CSV analysis skill set for Windows data agents. It ships with a
pinned WinPython runtime and performs CSV profiling, declarative analysis, and PNG rendering
locally without relying on system Python or sending data-processing work to a remote service.

> [!IMPORTANT]
> The repository currently contains three business skills, one Python runtime skill,
> deterministic Python tools, and the portable-runtime build flow. It does not yet include the
> final Agent base or a graphical interface.

## Core capabilities

- Detect UTF-8, UTF-8 BOM, GBK/GB18030, delimiters, field types, missing values, duplicates,
  and candidate field roles.
- Execute allowlisted cleaning, filtering, time bucketing, aggregation, Top N, share, and
  percentage-change operations from a versioned analysis plan.
- Render line, bar, donut, and scatter PNG charts from SHA-256-bound `result.csv` artifacts
  without recomputing business metrics during charting.
- Use a pinned WinPython CPython 3.13.13 Windows x64 runtime instead of system `python` or
  `py.exe`.
- Protect source files, return structured errors, and commit multi-file artifact sets
  transactionally.
- Support Chinese paths, headers, chart labels, and offline execution.

## Repository structure

```text
ChartPilot/
├── runtime.lock.json
├── requirements.txt
├── requirements.runtime.lock.txt
├── scripts/runtime/
├── skills/
│   ├── chartpilot-run-python/
│   ├── chartpilot-profile-csv/
│   ├── chartpilot-analyze-data/
│   └── chartpilot-render-chart/
├── ChartPilot需求规格说明.md
├── Skill开发说明.md
└── Windows离线部署方案.md
```

`runtime/`, `wheelhouse/`, `build/`, and `dist/` are generated locally and excluded from Git.

## Build the portable runtime

The build host needs Windows 10/11 x64 and PowerShell 5.1 or later. A preinstalled Python is
not required. ChartPilot pins `WinPython64-3.13.13.0dot.zip` from WinPython release
`17.4.20260511final` and verifies its byte size and SHA-256 before extraction.

Build the runtime:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\build-runtime.ps1
```

This creates `runtime/`, installs dependencies from the hash-locked wheelhouse, and runs
dependency checks, CLI smoke tests, regression tests, and a CSV-to-PNG end-to-end test.

Refresh the full dependency lock only after changing `requirements.txt`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
```

Review every version and hash change in `requirements.runtime.lock.txt`.

## Run the pipeline

Use the bundled interpreter for every command:

```powershell
$python = ".\runtime\winpython\python\python.exe"
```

Profile a CSV:

```powershell
& $python -I .\skills\chartpilot-profile-csv\scripts\profile_csv.py "data\sales.csv" `
  --task-id demo-001 `
  --output-dir "workspace\tasks\demo-001"
```

Create `analysis_plan.json` according to the
[analysis contract](skills/chartpilot-analyze-data/references/contracts.md), then run:

```powershell
& $python -I .\skills\chartpilot-analyze-data\scripts\run_analysis.py `
  --profile "workspace\tasks\demo-001\input_profile.json" `
  --plan "workspace\tasks\demo-001\analysis_plan.json" `
  --output-dir "workspace\tasks\demo-001"
```

Render the saved result:

```powershell
& $python -I .\skills\chartpilot-render-chart\scripts\render_chart.py `
  --analysis-result "workspace\tasks\demo-001\analysis_result.json"
```

Artifact flow:

```text
input_profile.json
  -> analysis_plan.json
  -> result.csv + analysis_result.json
  -> chart.png + chart_result.json + summary.md
```

## Validate and package

Run the complete validation suite:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\test-runtime.ps1
```

Create the release ZIP:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

The output is `dist/ChartPilot-runtime-win-x64-py3.13.zip`. Perform a final manual acceptance
pass on clean, non-admin Windows 10 and Windows 11 hosts before release.

## Agent runtime contract

`chartpilot-run-python` defines how a future Agent base reads
`runtime/runtime-manifest.json`, validates the interpreter, sanitizes Python environment
variables, starts the process with an argument array, and records generated code and execution
evidence. The three business skills continue to prefer deterministic runners and do not admit
arbitrary expressions into the standard CSV pipeline.

## Security boundaries

- Bundled business tools do not make network requests or execute model-provided Python
  expressions.
- Source files and upstream artifacts are SHA-256-bound and revalidated downstream.
- CSV samples can be omitted or redacted for sensitive-looking fields.
- Target machines must not run online pip installs; dependencies change only during a
  hash-reviewed build.
- API keys must never be written to plans, generated code, logs, or results.
- WinPython is not an operating-system sandbox. The future Agent base still owns ACLs,
  process timeouts, resource limits, and network policy.

## Project documents

- [Requirements specification](ChartPilot需求规格说明.md)
- [Skill development notes](Skill开发说明.md)
- [Windows offline deployment](Windows离线部署方案.md)

## License

The project has not selected a software license. Public availability does not grant rights to
use, modify, or redistribute the repository beyond applicable law. The generated
`runtime/third-party-licenses.json` records license metadata for installed distributions.
