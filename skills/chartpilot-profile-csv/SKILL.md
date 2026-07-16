---
name: chartpilot-profile-csv
description: Profile one local CSV file into an auditable input_profile.json using deterministic, offline-safe parsing. Use when ChartPilot needs to inspect a CSV's encoding, delimiter, shape, field types, missing and unique values, duplicate rows, empty or constant columns, representative samples, and candidate time, numeric, categorical, or identifier fields before analysis. Supports UTF-8, UTF-8 BOM, GBK/GB18030 Chinese data and comma, tab, semicolon, or pipe delimiters on native Windows paths.
---

# Profile a CSV

Use the bundled deterministic script for all file reading and factual profiling. Keep this Skill limited to ingestion and data-quality discovery; do not clean data, calculate business metrics, generate analysis plans, or draw charts.

## Run the profiler

Use `chartpilot-run-python` to resolve and validate the bundled interpreter. Invoke the profiler
with the local CSV path and task output directory:

```text
<chartpilot-root>\runtime\winpython\python\python.exe -I <chartpilot-root>\skills\chartpilot-profile-csv\scripts\profile_csv.py "C:\data\sales.csv" --task-id T001 --output-dir "C:\ChartPilot\workspace\tasks\T001"
```

Pass arguments as a process argument array, never as a shell-composed command. Set `--allowed-read-root` and `--allowed-write-root` when the runtime supplies controlled workspace roots. Let the caller enforce the process timeout.

Use automatic encoding and delimiter detection first. If the script returns `ENCODING_DECODE_ERROR`, `DELIMITER_AMBIGUOUS`, or `CSV_PARSE_ERROR`, report the structured error and request an explicit `--encoding` or `--delimiter` only when the evidence permits retrying. Do not silently replace undecodable bytes, skip malformed rows, or retry with arbitrary settings.

Control data disclosure with `--sample-mode`:

- Use `redacted` by default to mask values in sensitive-looking columns.
- Use `none` when deployment policy allows metadata only.
- Use `raw` only when the user or deployment policy explicitly permits raw sample values to enter the profile.

Read [references/contracts.md](references/contracts.md) when integrating the CLI, consuming `input_profile.json`, or handling errors.

## Interpret the result

Treat `input_profile.json` as the source of truth. Preserve column IDs such as `c0001`; duplicate and blank source headers are intentionally not rewritten. Distinguish exact counts from `lower_bound` counts before making claims about uniqueness or duplicates.

Summarize only:

- detected format and table shape;
- field types and candidate roles;
- material quality warnings;
- whether samples were omitted, redacted, or retained;
- the absolute path returned for `input_profile.json`.

Pass `input_profile.json` to the analysis Skill. Its local `source.path` and `source.sha256` identify the exact input; verify the hash before downstream execution. Do not send the original file contents to the model outside the configured sample policy.

## Enforce boundaries

- Keep the source file read-only and write only `input_profile.json` under the requested output directory.
- Reject format ambiguity instead of guessing.
- Preserve existing complete output until a replacement profile has been fully written and atomically installed.
- Never invoke network clients, generated Python, subprocesses, `eval`, or `exec` from this Skill.
- Never fall back to a system Python interpreter or install dependencies at runtime.
- Stop after profiling. Delegate cleaning and computation to the analysis Skill and visualization to the charting Skill.
