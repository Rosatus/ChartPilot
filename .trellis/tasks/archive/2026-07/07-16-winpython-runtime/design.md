# WinPython Runtime Technical Design

## 1. Design Summary

Build ChartPilot's Windows runtime from the official WinPython `dot` ZIP, add only the
current CSV MVP dependencies, validate the complete environment, and package it beside the
skills. Keep generated binaries outside Git while committing every input needed to rebuild
and audit them.

The runtime integration has two consumers:

1. Existing deterministic business skills invoke their fixed Python entry scripts with the
   bundled interpreter.
2. A new `chartpilot-run-python` skill teaches a future Agent base how to create task-local,
   auditable Python files and execute them with the same interpreter and environment policy.

The second consumer does not change the current analysis contract. The existing analysis
runner continues to reject arbitrary operations and never executes model-provided code.

## 2. Selected Runtime

| Field | Value |
| --- | --- |
| Release | `17.4.20260511final` |
| Asset | `WinPython64-3.13.13.0dot.zip` |
| Architecture | Windows x64 |
| Python | Standard CPython 3.13.13 |
| Size | `27,697,763` bytes |
| SHA-256 | `c6ada5d0a2fef7dc7ae79e4f9c046a55f98e7221a221a250e34dfcab02f384d1` |

Reject prereleases, free-threaded builds and `slim` distributions. CPython 3.13 provides a
more conservative third-party wheel target than 3.14/3.15 while all current pins publish
standard `cp313-cp313-win_amd64` wheels.

## 3. Repository Layout

Source-controlled files:

```text
ChartPilot/
  runtime.lock.json
  requirements.txt
  requirements.runtime.lock.txt
  scripts/
    runtime/
      build-runtime.ps1
      update-lock.ps1
      test-runtime.ps1
      package-release.ps1
      write-runtime-metadata.py
  skills/
    chartpilot-run-python/
      SKILL.md
      agents/openai.yaml
      references/runtime-contract.md
```

Generated and ignored files:

```text
ChartPilot/
  runtime/
    runtime-manifest.json
    third-party-licenses.json
    winpython/
      python/python.exe
  wheelhouse/
  build/
  dist/
```

`runtime.lock.json` is the source-of-truth acquisition contract. It records a versioned
schema, release tag, source URL, expected bytes, SHA-256, target architecture, expected
Python version, final interpreter path and required environment values.

`requirements.txt` remains the human-maintained direct dependency list.
`requirements.runtime.lock.txt` is the generated, committed, platform-specific lock for all
direct and transitive wheels with `--hash=sha256:...` entries.

## 4. Build Flow

```text
runtime.lock.json + requirements.txt
        |
        v
download fixed WinPython ZIP -> verify size and SHA-256
        |
        v
extract into build staging -> normalize to runtime/winpython
        |
        v
download Windows x64 cp313 wheels -> generate/verify hash lock
        |
        v
offline pip install from wheelhouse with --require-hashes
        |
        v
write runtime manifest + dependency/license inventory
        |
        v
pip check + imports + CLI tests + end-to-end smoke test
        |
        v
replace prior runtime only after staging passes
```

Normal builds consume the committed lock and may download missing locked wheels on the
connected build host. `update-lock.ps1` is the only workflow allowed to resolve newer
transitive dependencies from `requirements.txt`; its resulting lock diff must be reviewed.

Installation always uses the staged WinPython interpreter:

```text
<stage>/winpython/python/python.exe -m pip install
  --no-index --find-links <wheelhouse>
  --require-hashes -r requirements.runtime.lock.txt
```

No build step calls system `python`, `py.exe`, or a user virtual environment.

## 5. Runtime Resolution Contract

The canonical interpreter path relative to the project root is:

```text
runtime/winpython/python/python.exe
```

Future Agent bases must read `runtime/runtime-manifest.json`, validate its schema and resolve
the declared interpreter beneath the project root. They must compare the actual Python
version and architecture with the manifest before first use.

The Agent starts the interpreter directly through a process API using an argument array. It
must not build a shell command string. The child environment must:

- set `PYTHONNOUSERSITE=1`;
- set `PYTHONUTF8=1`;
- remove `PYTHONPATH`, `PYTHONHOME` and inherited virtual-environment markers;
- point `HOME`, `TEMP`, `TMP`, `MPLCONFIGDIR`, `PYTHONPYCACHEPREFIX` and application caches
  into a writable task/workspace subtree;
- remove unrelated credentials, proxies and API keys unless the invoked operation explicitly
  requires a trusted value;
- preserve the future Agent base's timeout, memory, process and network controls.

If the manifest, interpreter, version or health check is invalid, execution fails with a
structured runtime error. There is no system-Python fallback.

## 6. Skill Design

### 6.1 New `chartpilot-run-python` Skill

The skill triggers when ChartPilot needs to author or execute Python, inspect the bundled
environment, or invoke one of the business scripts. Keep `SKILL.md` concise and place the
detailed runtime schema, environment contract and invocation examples in
`references/runtime-contract.md`.

The skill requires the Agent to:

- resolve and validate the bundled runtime before authoring code that depends on packages;
- write generated Python only under the active task directory;
- use UTF-8 source, explicit inputs/outputs and a deterministic `main()` entry point;
- keep business calculations in declared plans when an existing business skill supports them;
- prohibit dependency installation, network clients, shell commands, `eval`, `exec`, dynamic
  package loading and writes outside authorized roots;
- invoke the interpreter directly with an argument array and capture stdout, stderr, exit code
  and elapsed time through the Agent base;
- retain generated code and execution metadata for audit.

WinPython is not described as a sandbox. The Skill must state that hard isolation is owned by
the future Agent base.

### 6.2 Existing Business Skills

Update the profiler, analysis and renderer skills plus their CLI contract examples to use the
runtime contract. Preserve their current ownership rules:

- profiler never cleans, calculates or executes generated code;
- analysis accepts only allowlisted declarative operations;
- renderer never reopens source data or recomputes business metrics.

The existing scripts do not need to discover the runtime themselves. Runtime selection is a
caller/Agent responsibility, keeping scripts independently testable with any compatible
interpreter.

## 7. Runtime Manifest And Supply-Chain Records

`runtime/runtime-manifest.json` uses schema `chartpilot.runtime/v1` and records:

- upstream release, URL, asset SHA-256 and size;
- Python implementation, version, architecture and interpreter relative path;
- the lock-file SHA-256;
- installed distributions and versions;
- wheel filenames and SHA-256 values;
- required environment map;
- health-check commands and results;
- build timestamp and builder script version.

`third-party-licenses.json` records each installed distribution's normalized name, version,
license expression or metadata value, classifiers, homepage and discovered license files.
Unknown license metadata is retained as `unknown` and reported by validation rather than
silently omitted.

The release package includes both generated records. The wheelhouse remains a separate build
archive and is not required at end-user runtime.

## 8. Failure And Rollback Behavior

- Downloads use temporary files and are renamed only after size/hash validation.
- Extraction and dependency installation occur in a staging directory under `build/`.
- Path deletion/replacement helpers verify that every target resolves beneath the repository
  root and matches an expected generated directory.
- A valid existing `runtime/` remains untouched until all staged checks pass.
- During installation, move the prior runtime to a backup, install the staged directory, and
  restore the backup if final placement fails.
- Keep cache and staging data after a failure when useful for diagnosis; never report a partial
  runtime as successful.

## 9. Packaging And Compatibility

`package-release.ps1` creates a versioned ZIP under `dist/` containing the generated runtime,
skills, runtime lock/manifest, dependency lock, user documentation and current deterministic
scripts. It excludes Git/Trellis/Codex metadata, caches, wheelhouse, tests' bytecode and local
workspace data. The task does not re-extract and execute the completed release ZIP.

Target acceptance environments are clean Windows 10 and Windows 11 x64 hosts, non-admin
accounts, no WSL/Docker/system Python, and no general Internet access. Clean-host validation is
a later manual release gate rather than an automated packaging step in this task.

## 10. Trade-Offs

- Minimal dependencies reduce size and audit surface but defer Excel, SQL and Arrow formats.
- A committed platform lock makes builds reproducible but must be regenerated deliberately
  when direct pins or Python versions change.
- Direct interpreter invocation is less convenient than a global command but avoids PATH and
  shell ambiguity. A future native launcher can wrap this contract without changing Skills.
- General generated-code guidance satisfies the product requirement but is not isolation;
  strict process and network controls remain a future Agent-base responsibility.
