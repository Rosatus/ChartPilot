---
name: chartpilot-analyze-data
description: Execute deterministic, auditable analysis of one profiled local CSV from a versioned analysis_plan.json. Use when ChartPilot needs to validate field mappings, apply explicit cleaning and filters, bucket dates, aggregate sum, mean, count, distinct count, minimum, or maximum, calculate shares or period changes, rank or select Top N results, and produce plot-ready result.csv plus evidence-backed findings without drawing charts or running arbitrary generated code.
---

# Analyze profiled CSV data

Use the bundled deterministic runner for factual calculations. Keep this Skill between CSV profiling and chart rendering; never draw a chart, encode an image, or reopen a different data source.

## Prepare the plan

Read [references/contracts.md](references/contracts.md) before creating or consuming a plan. Use profile column IDs such as `c0001`, not display headers, so duplicate and blank CSV headers remain unambiguous.

Create `analysis_plan.json` with only allowlisted operations. Resolve field or business-definition ambiguity before execution. Set `status` to `needs_clarification` and stop when a metric, filter, time grain, unit, or comparison baseline is materially ambiguous.

Inspect `input_profile.json.quality` before planning. If exact duplicate rows, suspected key duplicates, or missing values in required fields can materially change an aggregate and neither the user nor a trusted deployment policy defines how to handle them, set `status: needs_clarification`. Do not hide a material data-quality choice in `assumptions`, and do not silently include, remove, or fill the affected rows.

Keep all business transformations in the plan:

- Declare type conversions and every row-changing cleaning step with a reason.
- Declare filters as typed operators, never Python expressions.
- Complete aggregation, time bucketing, ranking, Top N, share, and percentage-change calculations before charting.
- Make `chart_intent.y` one plot-ready result column. Use `x: null` only for a single-row `auto` or `bar` chart.
- Produce distribution bins or summary statistics during analysis; do not ask the chart Skill to calculate them.

Return `UNSUPPORTED_OPERATION` when the request cannot be represented by the contract. Do not fall back to generated expressions, `eval`, `exec`, arbitrary imports, shell commands, or network access.

## Run the analysis

Invoke the script with process arguments rather than a shell-composed command:

```text
python scripts/run_analysis.py --profile "C:\ChartPilot\workspace\tasks\T001\input_profile.json" --plan "C:\ChartPilot\workspace\tasks\T001\analysis_plan.json" --output-dir "C:\ChartPilot\workspace\tasks\T001" --allowed-read-root "C:\ChartPilot\workspace" --allowed-read-root "C:\data" --allowed-write-root "C:\ChartPilot\workspace"
```

Let the Agent runtime impose a process timeout and Windows resource limits. Supply trusted read and write roots from deployment configuration; never derive them from model output. Treat a zero exit code and `analysis_result.json` with `status: success` as the only successful completion signal.

The runner verifies the task ID and source hash, reads the CSV as lexical strings, applies the validated plan locally with pandas, checks evidence against the serialized result, rechecks the source hash, and installs outputs atomically with `analysis_result.json` last.

## Handle results

Pass only `analysis_result.json` to the chart Skill. Let that manifest bind `result.csv` by relative path and SHA-256. Use `findings[].evidence` for numerical claims; do not quote an unverified number from generated prose.

Handle structured errors by code:

- Ask for clarification on `NEEDS_CLARIFICATION`.
- Revise the declarative plan on `INVALID_PLAN` or `UNSUPPORTED_OPERATION`.
- Report source replacement on `SOURCE_HASH_MISMATCH` or `SOURCE_CHANGED` and rerun profiling.
- Report `EMPTY_RESULT`, `DIVIDE_BY_ZERO`, or `NO_FINITE_METRIC` without inventing a value.
- Install the bundled pandas wheel on `DEPENDENCY_MISSING`; do not download dependencies at runtime.

Retry only after changing the identified cause and respect the runtime retry cap.

## Enforce boundaries

- Keep the original CSV read-only and verify its hash before and after analysis.
- Write only `generated_analysis.py`, optional `cleaned_data.csv`, `result.csv`, and `analysis_result.json` under the requested output directory.
- Keep `generated_analysis.py` as a deterministic, human-readable compilation record; execute calculations through the allowlisted runner.
- Keep API keys, raw rows, and cell values out of logs and error details.
- Stop after analysis. Delegate all PNG, font, layout, and Base64 work to `chartpilot-render-chart`.
