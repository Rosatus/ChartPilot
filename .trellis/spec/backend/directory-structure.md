# Directory Structure

## Repository Shape

ChartPilot is a Windows-first portable tool, not a web service. Keep source inputs separate from
generated runtimes and task output:

```text
agent/                      Goose integration and the ChartPilot MCP bridge
  config/                   Checked-in Goose configuration templates
  mcp/                      Product MCP server and interoperability validation
  tests/                    Python unit, integration, and regression tests
scripts/
  agent/                    Goose build, launch, and validation entry points
  runtime/                  WinPython build, lock, metadata, test, and release scripts
skills/chartpilot-run-python/
  SKILL.md                  Product workflow instructions
  agents/openai.yaml        Skill discovery metadata
  assets/templates/         Agent-editable inspect/analyze/render Python starters
  references/               Detailed adaptive-task and runtime contracts
runtime.lock.json           Portable Python source and environment contract
goose.lock.json             Portable Goose source contract
requirements*.txt           Direct and complete pinned Python dependencies
release.files.json          Explicit release root-file allowlist
runtime/, wheelhouse/       Generated portable dependencies; never tracked
workspace/, build/, dist/   Generated state, staging, validation, and release output
```

Reference implementations are `agent/mcp/chartpilot_mcp.py`,
`agent/initialize_goose.py`, `scripts/runtime/common.ps1`, and
`scripts/agent/start-chartpilot.ps1`.

## Ownership Boundaries

- Put product tool registration, task preparation, task-local process execution, hashes, and
  artifact contract validation in `agent/mcp/chartpilot_mcp.py`.
- Put Goose config merging and Skill staging in `agent/initialize_goose.py`; preserve user provider
  settings and explicit extension enable/disable choices.
- Put task-specific business analysis and visual composition in editable files derived from
  `skills/chartpilot-run-python/assets/templates/`. Do not move prompt-specific fields,
  thresholds, or chart geometry into the MCP bridge.
- Put reusable PowerShell build primitives in `scripts/runtime/common.ps1` or
  `scripts/agent/common.ps1`; keep orchestration in named `build-*`, `test-*`, `update-*`, or
  `package-*` entry points.
- Put portable identity and dependency decisions in checked-in JSON/text locks. Generated
  manifests under `runtime/` describe a built instance and are not source contracts.

## File Conventions

- Python modules and tests use lowercase snake-case file names and `pathlib.Path` for path logic.
- PowerShell entry points use verb-noun names and dot-source their local `common.ps1`.
- PowerShell source stays ASCII for Windows PowerShell 5.1 compatibility. Store Chinese text in
  UTF-8 Markdown, JSON, CSV, or Python source instead.
- JSON schemas use explicit values such as `chartpilot.adaptive-task/v1`; validate the schema at
  every process or artifact boundary.
- Write generated files under `runtime/`, `workspace/`, `build/`, `dist/`, or `wheelhouse/`, never
  beside source modules.

## Adding New Functionality

1. Decide whether the change belongs to the portable runtime, Goose integration, MCP
   interoperability, or task-specific generated code.
2. Extend an existing lock/schema rather than creating an unversioned side file.
3. Add tests beside the owning layer: `agent/tests/` for Python behavior and
   `scripts/{runtime,agent}/test-*.ps1` for portable integration contracts.
4. Update `release.files.json` or `package-release.ps1` only when the new source must ship.
5. Update `runtime-guidelines.md` when a runtime, MCP, environment, or release contract changes.

## Avoid

- Do not create a generic `src/`, service/repository/controller hierarchy, or database package;
  none exists in this codebase.
- Do not add a second MCP server or Skill for a request that belongs to the adaptive CSV workflow.
- Do not import code from generated `runtime/` or `workspace/` paths into checked-in modules.
- Do not place user data, external SY135 files, generated charts, credentials, or machine-specific
  absolute paths in tracked fixtures.
