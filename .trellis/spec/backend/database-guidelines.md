# Database Guidelines

## Current State

ChartPilot has no database, ORM, migration system, network service, or durable shared datastore.
Do not invent database conventions for this repository.

Durable product state currently uses explicit local files:

- JSON lock files at the repository root define portable runtime inputs.
- `runtime/*.json` records a generated runtime's identity and health.
- `workspace/tasks/<task-id>/task_context.json` and execution records capture adaptive work.
- CSV, JSON, Markdown, and PNG artifacts form the task interoperability contract.
- Goose user configuration lives under the generated `workspace/goose/` tree.

Representative code is in `agent/mcp/chartpilot_mcp.py` (`load_json`, `write_json_atomic`,
`prepare_adaptive_task`) and `scripts/runtime/write-runtime-metadata.py`.

## File-State Rules

- Version every JSON contract with `schema_version` and reject unsupported versions.
- Use exact task/runtime IDs and SHA-256 hashes to connect source, generated code, and artifacts.
- Write completion files atomically through a temporary file plus `os.replace`, or the equivalent
  PowerShell partial-file move.
- Keep task attempts append-only under `executions/`; replace successful stage outputs only after
  staging validation succeeds.
- Keep generated data in ignored output roots. Checked-in fixtures must be small, anonymous, and
  deterministic.

## If Persistence Requirements Change

Adding a database is an architectural change, not a local helper decision. Before adding one,
define a Trellis task covering:

1. Why explicit local files no longer satisfy portable/offline operation.
2. The portable Windows deployment and upgrade story.
3. Schema ownership, migrations, backup, concurrency, and corruption recovery.
4. How the database remains relocatable after ZIP extraction.
5. New dependency locks, licenses, tests, and release packaging rules.

Until such a design is accepted, prefer existing versioned JSON/CSV artifacts.

## Avoid

- Do not add SQLite, an ORM, or a server database merely to index task folders.
- Do not treat Goose configuration or task manifests as an unversioned key-value store.
- Do not modify a successful task's historical execution records in place.
- Do not write runtime state into tracked source directories.
