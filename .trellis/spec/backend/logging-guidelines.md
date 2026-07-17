# Logging And Process Output

## Current Model

ChartPilot does not use a long-running application logging framework. Output is split by audience:

- Python command success: one compact JSON object on stdout.
- Python command failure: one structured JSON error object on stderr plus a nonzero exit code.
- PowerShell build/test progress: concise labeled human-readable lines through `Write-Host`.
- Recoverable build fallback: `Write-Warning`, followed by another verified strategy.
- Generated task execution: bounded stdout/stderr stored in append-only execution records.

Examples are `scripts/runtime/write-runtime-metadata.py:main`,
`agent/initialize_goose.py:main`, `scripts/runtime/common.ps1:Invoke-CheckedCommand`, and
`agent/mcp/chartpilot_mcp.py:run_python_process`.

## Structured Output Rules

- Keep stdout parseable when a Python CLI documents JSON output; progress belongs on stderr or in
  the calling PowerShell layer.
- Include `ok` or `status`, a stable error code, and the minimum paths/counts needed to diagnose the
  operation.
- Serialize JSON as UTF-8 with `ensure_ascii=False` when user-visible text may be Chinese.
- Use UTC ISO-8601 timestamps for persisted records.
- Bound generated process stdout and stderr. `chartpilot_mcp.py` currently caps each stream at
  `MAX_PROCESS_OUTPUT_BYTES` and fails attempts that exceed the limit.
- Record script/runtime hashes, duration, exit status, and artifact hashes instead of copying large
  data into logs.

## Sensitive Data

Never log provider configuration, credentials, environment dumps, raw user CSV rows, machine IDs,
or the full contents of external prompts. The MCP bridge removes proxy and credential-shaped
environment variables before importing FastMCP or launching task code; preserve this behavior.

Paths may be recorded when required for local reproducibility, but tracked tests/docs must not
contain a developer's Downloads path or private external case root.

## PowerShell Progress

Use stable labels such as:

```text
[Verify interpreter] <command>
[Adaptive Agent unit tests] <command>
Runtime validation passed: <path>
```

Avoid verbose per-file chatter during archive copy/compression. Report phase transitions, verified
identity, and the final artifact path. Warnings must explain the fallback or action taken.

## Avoid

- Do not add `print()` debugging in library functions or MCP tool handlers.
- Do not mix human prose into a JSON-only stdout contract.
- Do not persist unbounded subprocess output.
- Do not claim that path organization, logging, or hashes form a security sandbox.
- Do not log secrets even in tests or failure diagnostics.
