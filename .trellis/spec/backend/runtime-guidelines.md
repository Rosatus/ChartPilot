# Portable Runtime Guidelines

## Scenario: Build And Invoke The ChartPilot Python Runtime

### 1. Scope / Trigger

Use this contract when changing the pinned Python version, direct dependencies, runtime build
scripts, release packaging, Agent process invocation, or file durability behavior on Windows.

The generated `runtime/`, `wheelhouse/`, `build/`, and `dist/` directories are local artifacts.
Commit their source contracts and scripts, not the generated binaries.

### 2. Signatures

Supported build commands:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\build-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\test-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

Canonical interpreter path:

```text
runtime/winpython/python/python.exe
```

Business CLI processes use this shape:

```text
<absolute-bundled-python> -I <absolute-script> <argument-array-items...>
```

### 3. Contracts

Source of truth:

- `runtime.lock.json`: upstream release URL, byte size, SHA-256, Python version/architecture,
  interpreter-relative path, dependency files, and child environment policy.
- `requirements.txt`: exact direct dependency pins.
- `requirements.runtime.lock.txt`: exact direct and transitive Windows x64 CPython 3.13 wheels,
  each with SHA-256.
- `release.files.json`: explicit root-file allowlist for release packaging.
- `runtime/runtime-manifest.json`: generated installed-runtime identity, packages, wheels, hashes,
  environment contract, and health results.

Child environment:

```text
set: PYTHONNOUSERSITE=1, PYTHONUTF8=1, PYTHONDONTWRITEBYTECODE=1, MPLBACKEND=Agg
unset: PYTHONHOME, PYTHONPATH, VIRTUAL_ENV, CONDA_PREFIX, CONDA_DEFAULT_ENV
workspace paths: HOME, TEMP, TMP, MPLCONFIGDIR, PYTHONPYCACHEPREFIX
```

Build scripts must remain ASCII so Windows PowerShell 5.1 does not misdecode source literals.
Store non-ASCII release filenames in UTF-8 JSON and read them with an explicit JSON parser.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Upstream byte size or SHA-256 mismatch | Stop before extraction; keep prior verified cache/runtime. |
| Source distribution or wrong wheel platform | Reject lock refresh. |
| Lock missing or wheel hash mismatch | Stop build before installation. |
| Python implementation/version/architecture mismatch | Fail runtime health check. |
| Runtime manifest path escapes project root | Reject invocation; never search system Python. |
| Dependency import or `pip check` failure | Keep staging; do not replace the prior runtime. |
| CLI/unit/end-to-end test failure | Keep staging and prior runtime unchanged. |
| Final runtime placement failure | Restore the complete prior runtime. |
| Release allowlist entry missing | Fail packaging. |
| Windows `os.fsync()` uses a read-only descriptor | Treat as a bug; reopen the created file as `r+b`. |

### 5. Good / Base / Bad Cases

- Good: refresh a reviewed hash lock, build in staging, run all checks, then replace `runtime/`.
- Base: rebuild from an unchanged lock and cached verified ZIP/wheelhouse without dependency drift.
- Bad: call `python` from `PATH`, run online pip on the target machine, accept an unverified ZIP,
  install an sdist, or package every root file with a wildcard.

### 6. Tests Required

- Assert the WinPython asset matches both expected bytes and SHA-256.
- Regenerate a lock from `wheelhouse/` and compare it byte-for-byte with the committed lock.
- Assert `pip check` and imports of pandas, matplotlib, and Pillow succeed.
- Assert all three business CLIs support `--help` through the bundled interpreter.
- Run analysis regression tests with the bundled interpreter.
- Run one profile -> analysis -> render test using Chinese content and a data path with spaces.
- Assert `runtime-manifest.json` reports CPython 3.13.13, 64-bit, health `success`, and matching
  asset/dependency hashes.
- Validate every Skill with the skill-creator validator.
- Inspect the release ZIP inventory for required files and forbidden project metadata/cache roots.
- Regression-test `fsync_path()` on an existing file under Windows CPython 3.13.

### 7. Wrong Vs Correct

#### Wrong: interpreter selection

```text
python skills/chartpilot-analyze-data/scripts/run_analysis.py ...
```

This can execute an unknown system interpreter and user site-packages.

#### Correct: interpreter selection

```text
C:\ChartPilot\runtime\winpython\python\python.exe -I C:\ChartPilot\skills\chartpilot-analyze-data\scripts\run_analysis.py ...
```

Resolve both paths beneath a trusted project root and pass arguments through a process array.

#### Wrong: Windows durability

```python
with path.open("rb") as handle:
    os.fsync(handle.fileno())
```

CPython 3.13 on Windows can raise `OSError: [Errno 9] Bad file descriptor` because the descriptor
is read-only.

#### Correct: Windows durability

```python
with path.open("r+b") as handle:
    os.fsync(handle.fileno())
```

Text/JSON writers may fsync their already writable handles directly. Reopen pandas-generated CSV
artifacts as `r+b` before fsync.

## Scenario: Build And Launch The Portable Goose Agent Base

### 1. Scope / Trigger

Use this contract when changing the Goose version, agent launcher, portable Goose configuration,
Skill staging, ChartPilot MCP tools, Agent tests, or release packaging.

Goose is the graphical/model-provider base. It must not replace the deterministic Python business
CLIs or turn the standard CSV path into general shell/code execution.

### 2. Signatures

Supported Agent commands:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\build-goose.ps1 `
  -SourceArchive "C:\path\to\Goose-win32-x64.zip"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\test-agent.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\start-chartpilot.ps1
```

Root user entrypoint:

```text
Start-ChartPilot.cmd
```

The stdio MCP server exposes exactly:

```text
chartpilot_profile_csv(source_path, task_id?, sample_mode="redacted")
chartpilot_analyze_data(task_id, analysis_plan)
chartpilot_render_chart(task_id, font_path?)
```

### 3. Contracts

Source of truth:

- `goose.lock.json`: Goose `v1.43.0`, non-CUDA Windows x64 Desktop asset, byte size,
  SHA-256, archive root, entrypoints, and required files.
- `runtime/goose-manifest.json`: generated critical-file hashes, CLI version, Authenticode
  observation, environment names, and health status.
- `agent/config/goose-config.template.json`: initial `smart_approve`, telemetry, Summon, and
  constrained ChartPilot stdio extension settings.
- `agent/mcp/chartpilot_mcp.py`: the only default bridge from Goose to business CLIs.

Required process environment:

```text
GOOSE_PATH_ROOT=<project>/workspace/goose
CHARTPILOT_ROOT=<trusted project root>
CHARTPILOT_WORKSPACE_ROOT=<project>/workspace
CHARTPILOT_ALLOWED_READ_ROOTS=<os.pathsep-separated trusted roots>
```

Goose `v1.43.0` portable Skill discovery uses
`GOOSE_PATH_ROOT/config/skills`, because that maps to
`Paths::config_dir().join("skills")`. Do not assume that
`GOOSE_PATH_ROOT/.agents/skills` replaces `~/.agents/skills`; Goose's
`global_skills_dir()` still resolves the real user home. Project
`.agents/skills` also has higher discovery precedence, so launch product sessions from the
isolated `workspace/session` directory rather than the repository root.

The launcher may update only the managed ChartPilot extension paths. It must preserve Provider
configuration, credentials, unrelated extensions, and an explicit user choice to disable the
ChartPilot extension.

The MCP server clears proxy and credential-shaped environment variables before importing or
running business tools. It invokes the absolute bundled interpreter with `-I`, argument arrays,
fixed scripts, trusted roots, bounded output, and a timeout. It never exposes shell, pip,
network, or arbitrary-Python tools.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Goose archive size/hash mismatch | Stop before ZIP inspection or extraction. |
| Rooted, traversal, duplicate, or out-of-root ZIP entry | Reject archive and retain prior runtime. |
| Required Goose file or CLI version missing | Fail staged build; do not replace runtime. |
| Critical extracted file hash changes | Launcher refuses to start the unpinned runtime. |
| Existing Goose YAML is malformed | Fail initialization without overwriting config. |
| CSV is outside trusted read roots | MCP returns an error before profiling. |
| Invalid task ID or task path escape | MCP returns an error before reading/writing artifacts. |
| Business CLI timeout or oversized output | Kill the process and return a bounded structured error. |
| Business CLI structured error | Preserve it under the MCP bridge error `details.cause`. |
| Provider is not configured | Goose UI/CLI asks for Provider setup; do not inject credentials. |
| Nonempty Skill directory refresh on Windows | Move old directory to backup, use `shutil.move`, restore on failure. |

### 5. Good / Base / Bad Cases

- Good: verify a local upstream ZIP, build in staging, hash critical files, initialize portable
  config, discover only ChartPilot Skills, and pass MCP CSV-to-PNG integration before packaging.
- Base: rebuild from unchanged locks and preserve an existing Provider configuration and disabled
  extension preference.
- Bad: run Goose from the repository root and leak Trellis Skills into the product session; stage
  Skills under `GOOSE_PATH_ROOT/.agents/skills`; enable Developer by default; accept Goose
  self-update drift; or invoke `python`/`goose` through `PATH`.

### 6. Tests Required

- Verify the Goose archive byte size and SHA-256 and reject a synthetic traversal ZIP.
- Verify `runtime/goose-manifest.json` and every recorded critical file hash.
- Assert the bundled Goose CLI reports the locked version and the Desktop binary is present.
- Initialize twice; preserve Provider data and a disabled ChartPilot extension while refreshing
  managed absolute paths.
- From `workspace/session`, assert Goose lists all four ChartPilot Skills and no Trellis Skills.
- Initialize MCP, assert exactly three tools, and reject a CSV outside allowed roots.
- Run profile -> analysis -> render through MCP and assert a valid PNG signature.
- Inspect the release ZIP for both runtimes, launcher, MCP, four `.agents/skills`, licenses, and
  absence of project metadata, caches, wheelhouse, and workspace.

### 7. Wrong Vs Correct

#### Wrong: portable Skill location

```text
<GOOSE_PATH_ROOT>/.agents/skills/chartpilot-profile-csv
```

This location is not the `GOOSE_PATH_ROOT`-redirected global Skill directory in Goose `v1.43.0`.

#### Correct: portable Skill location

```text
<GOOSE_PATH_ROOT>/config/skills/chartpilot-profile-csv
```

Launch with `workspace/session` as the Goose working directory so repository-only `.agents`
content cannot shadow or pollute the product Skill set.

#### Wrong: replace a populated Skill directory on Windows

```python
os.replace(staged_skill_dir, installed_skill_dir)
```

This can raise `PermissionError: [WinError 5]` for nonempty directories.

#### Correct: backup, move, restore

```python
shutil.move(str(installed_skill_dir), str(backup_dir))
try:
    shutil.move(str(staged_skill_dir), str(installed_skill_dir))
except Exception:
    shutil.move(str(backup_dir), str(installed_skill_dir))
    raise
```
