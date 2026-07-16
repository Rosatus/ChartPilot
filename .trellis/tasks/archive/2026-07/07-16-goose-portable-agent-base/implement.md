# Portable Goose Agent Base Implementation Plan

## 1. Lock And Build Goose

- Add `goose.lock.json` with the verified `v1.43.0` non-CUDA Desktop asset contract.
- Add Goose archive validation, safe extraction, staged replacement, manifest generation, and
  runtime smoke-test scripts under `scripts/agent/`.
- Build from the user-supplied `Goose-win32-x64.zip` via an explicit command argument; never
  persist its local source path.
- Validate Desktop and bundled CLI version/entrypoints and capture required Apache-2.0 notices.

## 2. Add Portable Initialization And Launcher

- Add a root `Start-ChartPilot.cmd` that invokes an ASCII PowerShell launcher.
- Add structured initialization for Goose YAML config and portable Agent Skills staging.
- Set `GOOSE_PATH_ROOT`, `CHARTPILOT_ROOT`, locale, telemetry, approval, and Python environment
  values without changing the machine-level environment.
- Validate both runtime manifests and critical hashes before launching the Desktop executable.

## 3. Add The MCP Bridge

- Pin the official `mcp==1.28.1` SDK and refresh the complete hash-locked wheelhouse.
- Implement the stdio server and three deterministic tools under `agent/mcp/`.
- Reuse current CLI contracts; add task-ID, path-root, environment, timeout, output-bound, and
  structured-error enforcement at the bridge boundary.
- Add protocol and end-to-end tests that need no Provider credentials or network access.

## 4. Adapt Skills And Packaging

- Update all relevant Skills to prefer named ChartPilot MCP tools when hosted by Goose while
  retaining direct bundled-CLI diagnostics.
- Extend release manifests and packaging to include launcher, agent files, Goose runtime,
  staged Agent Skills, locks, manifests, and licenses; rename the product ZIP appropriately.
- Exclude project-only Trellis/Codex files, downloaded archives, portable state, and credentials.

## 5. Documentation

- Update English and Chinese README files, Skill development notes, requirements, and Windows
  deployment documentation for the Goose architecture and first-launch flow.
- Record that Goose is pinned, no-CUDA, and not a Windows OS sandbox; document deliberate
  upgrade and rollback steps.

## 6. Validation Gates

Run, in order:

1. Goose lock/archive verification and safe-extraction negative tests.
2. `runtime/goose/resources/bin/goose.exe --version` and Desktop binary presence/signature
   checks.
3. Python lock consistency, `pip check`, imports, and existing runtime smoke tests.
4. MCP initialize, `tools/list`, invalid-path rejection, and CSV-to-PNG integration tests.
5. All four Skill `quick_validate.py` checks and Python compilation.
6. PowerShell parser checks plus Windows PowerShell 5.1 ASCII scan.
7. Full release packaging inspection for required and forbidden entries and third-party notices.

## Risk And Rollback Points

- Do not replace `runtime/goose` until staged validation succeeds; restore the prior directory
  on post-install failure.
- Do not overwrite an existing Goose user config. Back up and atomically replace only after a
  structured merge succeeds.
- Keep the old deterministic CLI path working throughout implementation.
- If the MCP SDK dependency set cannot be locked for CPython 3.13 Windows x64, stop before
  modifying the generated runtime and reassess the bridge implementation.
- If the official Desktop build cannot honor the configured portable backend root, keep the
  CLI/MCP integration but do not claim full portable state in documentation.
