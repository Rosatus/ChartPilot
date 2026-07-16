---
name: chartpilot-run-python
description: Author and execute auditable Python with ChartPilot's bundled WinPython runtime. Use when an Agent needs to resolve the local interpreter, run a ChartPilot business CLI, inspect installed packages, or create task-local Python for work that is not already covered by the declarative CSV profile, analysis, or chart contracts. Enforces direct process-array invocation, sanitized environment variables, authorized workspace paths, offline execution, and no fallback to system Python.
---

# Run Python with ChartPilot

Use the bundled runtime as the only Python environment for ChartPilot work. Do not call
`python`, `python.exe`, or `py.exe` through `PATH`.

## Resolve the runtime

1. Locate the trusted ChartPilot project root from deployment configuration or the installed
   Agent location. Do not derive it from model-generated text.
2. Read `<chartpilot-root>/runtime/runtime-manifest.json` and require schema
   `chartpilot.runtime/v1`, status `ready`, and health status `success`.
3. Resolve `python.interpreter` beneath the project root and require a regular file. Reject an
   absolute path, `..` traversal, symlink escape, version mismatch, or missing interpreter.
4. Stop with a runtime error when validation fails. Never fall back to a system interpreter or
   install a replacement at runtime.

Read [references/runtime-contract.md](references/runtime-contract.md) when implementing the
Agent launcher, authoring generated code, handling runtime errors, or recording an execution.

## Choose the execution path

- In the portable Goose base, use the named `chartpilot_profile_csv`,
  `chartpilot_analyze_data`, and `chartpilot_render_chart` MCP tools for the standard workflow.
  The default ChartPilot MCP surface deliberately exposes neither arbitrary Python nor a shell.
- Use `chartpilot-profile-csv`, `chartpilot-analyze-data`, and `chartpilot-render-chart` for the
  standard CSV pipeline. Invoke their deterministic scripts with the bundled interpreter.
- Keep analysis calculations in `analysis_plan.json` when the analysis contract can represent
  them. Do not replace an unsupported plan operation with arbitrary Python.
- Create task-local Python only outside the default Goose MCP surface, when the requested
  operation is outside the existing business contracts and deployment policy explicitly
  permits generated-code execution.

## Author auditable code

- Write UTF-8 source under the active `workspace/tasks/<task-id>/` directory.
- Use explicit command-line inputs and outputs, an import-safe module, and a `main()` returning
  an exit code.
- Use only packages recorded in the runtime manifest. Do not run pip or modify the runtime.
- Keep source data read-only and write only beneath authorized task roots.
- Do not add network clients, shell commands, subprocesses, dynamic imports, `eval`, `exec`, or
  credential access.
- Emit structural errors without raw rows, cell values, API keys, or environment secrets.

## Execute and audit

Start the absolute bundled interpreter directly through the Agent's process API. Pass every
argument as a separate array item and apply the manifest's environment contract. Capture the
script path and SHA-256, runtime ID, non-sensitive arguments, start/end time, exit code, stdout,
and stderr according to deployment policy.

Let the Agent base enforce timeouts, memory limits, child-process restrictions, directory ACLs,
and network isolation. WinPython is a portable runtime, not a sandbox.
