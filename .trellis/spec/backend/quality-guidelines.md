# Quality Guidelines

## Baseline Standards

- Target the bundled CPython 3.13 Windows x64 interpreter. Product/runtime commands must never
  discover Python through `PATH`, `py.exe`, Conda, a venv, or user site-packages.
- Keep Python source typed where practical (`Path`, `Mapping`, `Sequence`, concrete return types),
  import-safe, and guarded by `if __name__ == "__main__"` for CLI modules.
- Use structured parsers for JSON, YAML, CSV, and ZIP metadata; do not parse these formats with
  regexes or ad hoc string splitting when a standard parser exists.
- Use argument arrays and `shell=False` for subprocess execution.
- Keep PowerShell compatible with Windows PowerShell 5.1: strict mode, terminating errors, ASCII
  source, and explicit UTF-8 handling for data files.
- Preserve user-owned configuration and unrelated dirty files. Generated output belongs only in
  ignored output roots.

## Product Invariants

Changes must preserve the contracts in `runtime-guidelines.md`, especially:

- exactly one product Skill: `chartpilot-run-python`;
- exactly two ChartPilot MCP tools;
- editable inspect/analyze/render templates;
- role-matched visual archetypes remain advisory source blueprints, with a generic fallback rather
  than a deterministic chart router;
- task code executed only by bundled WinPython;
- no deterministic simple-task route or hidden system shell fallback;
- locks, hashes, licenses, and release inventory kept in sync.

Do not add a dependency unless it is pinned in direct requirements, resolved into the complete
runtime lock, downloaded into the wheelhouse, installed into the portable runtime, represented in
licenses/manifests, and covered by packaging checks.

## Test Placement And Style

- Put focused behavior tests in `agent/tests/test_*.py` using `unittest` and temporary directories
  under ignored `workspace/`.
- Keep committed CSV/Markdown fixtures small and anonymous. External acceptance cases receive a
  root path at runtime and store only aggregate expectations in Git.
- Test failure state as well as success: error code, absence of premature outputs, rollback, and
  execution record when applicable.
- Use `scripts/runtime/test-runtime.ps1` for portable Python, dependency imports, templates, unit
  tests, and end-to-end CSV-to-PNG smoke.
- Use `scripts/agent/test-agent.ps1` for Goose archive, initialization, MCP stdio, Skill discovery,
  and removed-Skill checks.
- `scripts/runtime/package-release.ps1` is the release gate and must run both suites before creating
  the ZIP.

## Required Checks

For Python/MCP/Skill changes:

```powershell
runtime\winpython\python\python.exe -I -m unittest discover `
  -s agent\tests -p test_*.py -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\runtime\test-runtime.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\agent\test-agent.ps1
```

For Skill changes, also run the available `quick_validate.py` against
`skills/chartpilot-run-python`. For release changes, run `package-release.ps1` and audit ZIP entries
for required and forbidden paths. Always run `git diff --check` before committing.

## Review Checklist

- Are schemas, tool names, Skill names, paths, environment keys, docs, and tests synchronized?
- Are file writes atomic and replacement/rollback order correct?
- Are path roots resolved and recursive deletes constrained to generated directories?
- Are process timeouts, output bounds, exit codes, and stderr handled?
- Are source/runtime hashes checked at the boundary where they matter?
- Does the test fail if the new behavior is removed, or is it tautological?
- Are machine-specific paths, secrets, runtime binaries, caches, and external user data excluded?
- Does the release still work without system Python or network-time installation?
- For a selected visual archetype, does generated source implement the declared aggregation,
  panels, marks, and reference lines before image-level review?

## Forbidden Patterns

- Suppressed warnings, broad ignored exceptions, or tests that only print results.
- Mutable default configuration that overwrites explicit user choices.
- Business-specific fields or thresholds in the MCP bridge or reusable templates.
- Hand-edited generated lock hashes or manifests presented as source truth.
- Unvalidated recursive deletion, ZIP extraction without path checks, or final placement before
  verification.
- Unrelated refactors bundled with runtime/MCP contract changes.
