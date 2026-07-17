# Error Handling

## Python Product Boundaries

Use stable, machine-readable errors at MCP and command boundaries.
`agent/mcp/chartpilot_mcp.py` defines
`ChartPilotBridgeError(code, message, details, *, recoverable=False)` and serializes:

```json
{
  "status": "error",
  "stage": "agent",
  "error": {
    "code": "SOURCE_CHANGED",
    "message": "The source CSV changed after task preparation.",
    "recoverable": false,
    "details": {}
  }
}
```

Follow these rules:

- Use a stable uppercase code for caller decisions and a concise message for humans.
- Put bounded, non-secret diagnostics in `details`; do not expose credentials or a full inherited
  environment.
- After generated code starts, return a bounded `details.process` projection with stdout/stderr
  tails and preserve `recoverable=true` when rethrowing after the execution record is written.
- Catch narrow expected exceptions and chain the cause with `raise ... from exc`.
- Validate paths, schema versions, sizes, identities, and prerequisites before side effects.
- Preserve the exact error code when rethrowing after an execution record is written.
- Treat `RENDER_TEXT_UNREADABLE` and generated stage-output corrections as recoverable; source,
  request, read-root, and runtime configuration errors remain non-recoverable.
- Convert unexpected stage failures to `ADAPTIVE_STAGE_FAILED` while recording the exception type.

For standalone Python CLIs such as `agent/initialize_goose.py` and
`scripts/runtime/write-runtime-metadata.py`, catch expected top-level failures, write one JSON error
object to stderr, and return a nonzero integer. Successful machine-readable results go to stdout.

## Transactional Filesystem Behavior

Failures must not make partial work look successful:

- Use `tempfile.mkstemp`, flush, `os.fsync`, and `os.replace` for source manifests and config files.
- Run generated task code against an attempt-specific staging directory.
- Validate every required artifact before `commit_outputs` replaces prior successful outputs.
- Commit `analysis_result.json` or `chart_result.json` last.
- On Goose Skill replacement failure, restore the backup as implemented by
  `agent/initialize_goose.py:sync_skill`.
- Always clean temporary/partial files in `finally` blocks.

## PowerShell Boundaries

All build and test scripts use:

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
```

Use `Invoke-CheckedCommand` from `scripts/runtime/common.ps1` when an external process must succeed.
After direct native command calls, inspect `$LASTEXITCODE` and throw on failure. Validate destructive
targets with `Assert-GeneratedPath` before recursive deletion. Downloads must land in a uniquely
named `.partial` file and pass expected byte/SHA-256 checks before the final move.

## Error Tests

Add a regression for every new failure code or rollback path. Trusted examples include:

- `agent/tests/test_adaptive_bridge.py`: invalid request combinations, source mutation, and failed
  generated Python with a persisted execution record and returned diagnostic tail, declared
  artifact collisions/commit cleanup, missing glyphs, and replacement characters.
- `agent/tests/test_initialize_goose.py`: idempotent config merging and stale Skill cleanup.
- `scripts/agent/test-build-contracts.ps1`: archive/build input safety.
- `scripts/runtime/test-runtime.ps1`: manifest, interpreter, dependency, template, and smoke gates.

Tests should assert the stable code/state transition, not only the exception text.

## Avoid

- Do not use `except Exception: pass`, `$ErrorActionPreference = "SilentlyContinue"`, or a zero exit
  code after a failed command.
- Do not print a traceback or raw provider configuration as a product error response.
- Do not delete or overwrite prior good output before replacement artifacts validate.
- Do not silently fall back to system Python, another runtime, or a deterministic business route.
