# Backend Development Guidelines

## Scope

ChartPilot is a Windows-first portable Python and Goose toolchain. These specs cover build scripts,
runtime metadata, Goose integration, the stdio MCP bridge, Agent Skills/templates, tests, and
release packaging.

## Guidelines

| Guide | Use When |
| --- | --- |
| [Directory Structure](./directory-structure.md) | Locating new code or deciding ownership between runtime, Agent, MCP, and task templates |
| [Database Guidelines](./database-guidelines.md) | Working with persisted file state or considering a new persistence layer |
| [Error Handling](./error-handling.md) | Adding validation, subprocesses, file replacement, rollback, or caller-facing errors |
| [Logging Guidelines](./logging-guidelines.md) | Adding CLI output, build progress, execution records, or diagnostics |
| [Quality Guidelines](./quality-guidelines.md) | Implementing, testing, reviewing, or preparing a release |
| [Portable Runtime Guidelines](./runtime-guidelines.md) | Changing WinPython, Goose, MCP signatures, templates, environment policy, or release contracts |

## Pre-Development Checklist

1. Read `directory-structure.md` to identify the owning layer.
2. Read `runtime-guidelines.md` for any runtime, dependency, Goose, MCP, Skill, or packaging change.
3. Read `error-handling.md` when a change can fail after side effects begin.
4. Read `logging-guidelines.md` before changing stdout/stderr or persisted execution records.
5. Read `quality-guidelines.md` and choose checks proportional to the changed contract.
6. Read `database-guidelines.md` only for persisted state; the current product has no database.

All specs describe the current repository and use English. Update them when a new local convention
or cross-layer contract is introduced.
