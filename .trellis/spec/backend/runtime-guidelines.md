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
