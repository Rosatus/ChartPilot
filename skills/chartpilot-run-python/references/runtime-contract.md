# ChartPilot Python Runtime Contract

## Contents

1. Runtime files
2. Resolution and validation
3. Child environment
4. Process invocation
5. Generated-code contract
6. Execution record
7. Failure contract
8. Security boundary

## 1. Runtime Files

The installed project contains:

```text
runtime/
  runtime-manifest.json
  third-party-licenses.json
  winpython/
    python/
      python.exe
```

The source-controlled `runtime.lock.json` defines the selected upstream distribution and the
canonical interpreter path. The generated `runtime/runtime-manifest.json` describes the actual
installed environment.

Require these manifest fields:

```json
{
  "schema_version": "chartpilot.runtime/v1",
  "runtime_id": "winpython-cpython-3.13.13-win-amd64",
  "status": "ready",
  "python": {
    "implementation": "CPython",
    "version": "3.13.13",
    "architecture": "64bit",
    "interpreter": "runtime/winpython/python/python.exe"
  },
  "health": {
    "status": "success",
    "checks": []
  }
}
```

Treat `installed_distributions` as the package allowlist available to generated code. Do not
assume that a package exists because it is common in another Python environment.

## 2. Resolution And Validation

The Agent base owns runtime resolution:

1. Accept a trusted absolute ChartPilot root from installation configuration.
2. Read the complete manifest as UTF-8 JSON and reject duplicate or unknown schema versions.
3. Require a relative interpreter path without `..` segments.
4. Resolve the interpreter, including symlinks/reparse points, and require it to remain beneath
   the trusted project root.
5. Start it once with `-I -c` to verify CPython 3.13.13 and 64-bit architecture.
6. Cache successful validation only while the manifest identity and interpreter file identity
   remain unchanged.

Do not search `PATH`, the registry, `PYTHONHOME`, virtual environments, Conda, or the Windows
Python launcher.

## 3. Child Environment

Build a minimal child environment from trusted deployment configuration. Apply the manifest's
environment contract:

```text
set:
  PYTHONNOUSERSITE=1
  PYTHONUTF8=1
  PYTHONDONTWRITEBYTECODE=1
  MPLBACKEND=Agg

unset:
  PYTHONHOME
  PYTHONPATH
  VIRTUAL_ENV
  CONDA_PREFIX
  CONDA_DEFAULT_ENV
```

Resolve these values beneath a writable task/runtime workspace and create the directories before
execution:

```text
HOME=<workspace>/home
TEMP=<workspace>/temp
TMP=<workspace>/temp
MPLCONFIGDIR=<workspace>/matplotlib
PYTHONPYCACHEPREFIX=<workspace>/pycache
```

Remove unrelated API keys, proxy credentials and tool tokens. Add a trusted value only when the
specific operation requires it and policy permits it.

## 4. Process Invocation

Use a process API with an executable and argument array:

```json
{
  "executable": "C:\\ChartPilot\\runtime\\winpython\\python\\python.exe",
  "arguments": [
    "-I",
    "C:\\ChartPilot\\skills\\chartpilot-profile-csv\\scripts\\profile_csv.py",
    "C:\\data\\销售 数据.csv",
    "--task-id",
    "T001",
    "--output-dir",
    "C:\\ChartPilot\\workspace\\tasks\\T001"
  ]
}
```

Do not concatenate a shell command, interpolate user paths into PowerShell/cmd text, or route the
invocation through a command-shell wrapper. Preserve Unicode arguments exactly.

Use `-I` for ChartPilot scripts so user site packages and Python environment variables cannot
alter imports. Do not use `-S`; the bundled dependencies live in site-packages.

## 5. Generated-Code Contract

Prefer the existing deterministic business runners. When deployment policy permits a general
generated script, require this structure:

```python
from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Read only the authorized input and write only the authorized output.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Before execution:

- save the UTF-8 source beneath the active task directory;
- compute and record its SHA-256;
- inspect imports and operations against deployment policy;
- reject dependency installation, network access, subprocesses, shell commands, dynamic code
  evaluation, credential reads, persistence and writes outside authorized roots;
- set a finite timeout and retry cap in the Agent base.

Generated code must not mutate the runtime, the source checkout, or the original data file.

## 6. Execution Record

The future Agent base should record a versioned task-local execution object containing:

- task ID and attempt number;
- runtime ID and manifest SHA-256;
- interpreter-relative path;
- script-relative path and SHA-256;
- non-sensitive argument names and authorized path roles;
- start/end timestamps and elapsed time;
- exit code and termination reason;
- bounded stdout/stderr references or hashes;
- timeout, resource and network policy identifiers.

Do not record API keys, full inherited environments, raw data rows or unbounded process output.

## 7. Failure Contract

Use stable runtime failure categories in the future Agent base:

| Code | Meaning |
| --- | --- |
| `RUNTIME_MANIFEST_NOT_FOUND` | The installed runtime manifest is missing. |
| `INVALID_RUNTIME_MANIFEST` | Schema, status or declared paths are invalid. |
| `RUNTIME_PATH_NOT_ALLOWED` | The interpreter resolves outside the project root. |
| `RUNTIME_INTERPRETER_NOT_FOUND` | The declared interpreter is missing. |
| `RUNTIME_VERSION_MISMATCH` | Implementation, version or architecture differs. |
| `RUNTIME_HEALTH_FAILED` | The built environment did not pass health checks. |
| `GENERATED_CODE_NOT_ALLOWED` | Deployment policy forbids the proposed script. |
| `PYTHON_EXECUTION_FAILED` | The child returned a nonzero exit code. |
| `PYTHON_EXECUTION_TIMEOUT` | The Agent terminated the child at its deadline. |

Never recover by searching for another Python interpreter or installing packages online.

## 8. Security Boundary

The bundled runtime provides version and dependency isolation only. It does not restrict file,
process, registry or network access. The Agent base must enforce directory ACLs, child-process
policy, time and memory limits, network controls and credential minimization before permitting
general generated-code execution.
