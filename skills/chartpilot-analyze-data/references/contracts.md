# Analysis contracts

## Contents

- Command line
- Required input profile
- Analysis plan
- Execution order and semantics
- Success artifacts
- Error contract
- Safety and determinism

## Command line

```text
<chartpilot-root>\runtime\winpython\python\python.exe -I <chartpilot-root>\skills\chartpilot-analyze-data\scripts\run_analysis.py \
  --profile PATH_TO_INPUT_PROFILE_JSON \
  --plan PATH_TO_ANALYSIS_PLAN_JSON \
  --output-dir TASK_DIRECTORY \
  [--allowed-read-root ROOT ...] \
  [--allowed-write-root ROOT] \
  [--max-source-bytes N] \
  [--max-result-rows N] \
  [--no-overwrite] \
  [--allow-unc]
```

Resolve the interpreter through the `chartpilot-run-python` contract. Invoke it directly with a
process argument array and never fall back to a system Python interpreter.

All paths support Unicode and spaces. Pass arguments as a process argument array. `--allowed-read-root` is repeatable and `--allowed-write-root` accepts one trusted deployment root. If the deployment omits these policy options, the explicitly supplied files and output directory are treated as authorized by the caller.

`--max-result-rows` defaults to 5000 to match the renderer's default point limit. Raise both stages' limits explicitly when deployment policy permits a larger plot-ready result.

The command writes UTF-8 JSON to standard output on success and one UTF-8 JSON error object to standard error on failure. It does not print rows or cell values.

## Required input profile

Accept only `schema_version: chartpilot.input-profile/v1`, `stage: profile`, and `status: success`. Require these fields:

```json
{
  "schema_version": "chartpilot.input-profile/v1",
  "task_id": "T001",
  "stage": "profile",
  "status": "success",
  "source": {
    "path": "C:\\data\\sales.csv",
    "sha256": "64 lowercase hexadecimal characters",
    "size_bytes": 12345,
    "encoding": "utf-8-sig",
    "delimiter": ","
  },
  "shape": {"row_count": 100, "column_count": 4},
  "columns": [
    {"id": "c0001", "index": 0, "source_name": "月份", "inferred_type": "date", "type_details": {"dominant_kind": "date", "parse_ratio": 1.0}},
    {"id": "c0002", "index": 1, "source_name": "地区", "inferred_type": "string", "type_details": {"dominant_kind": "string", "parse_ratio": 1.0}},
    {"id": "c0003", "index": 2, "source_name": "销售额", "inferred_type": "number", "type_details": {"dominant_kind": "number", "parse_ratio": 1.0}},
    {"id": "c0004", "index": 3, "source_name": "订单号", "inferred_type": "string", "type_details": {"dominant_kind": "string", "parse_ratio": 1.0}}
  ]
}
```

The canonical shape keys are `row_count` and `column_count`; the runner also accepts legacy `rows` and `columns` keys. The canonical `inferred_type` is a string and detailed inference evidence lives under `type_details`. The runner also accepts encoding and delimiter under `format` for compatibility, but `source.path` and `source.sha256` are mandatory. Column IDs must be unique and source-ordered. The runner reads all CSV fields lexically, maps them to these IDs by position, and converts only fields explicitly named by the plan.

## Analysis plan

Use `schema_version: chartpilot.analysis-plan/v1`. Keep the plan declarative and reject unknown operations.

Before setting `status: ready`, inspect the profile quality section. Treat a data-quality choice as material when it can change the requested metric, ranking, trend, or comparison. In particular, when exact duplicate rows can be counted more than once and no user or trusted policy says whether they are valid repeated events, stop with `status: needs_clarification`; do not proceed by placing an include-or-delete decision in `assumptions`. Apply the same gate to suspected key duplicates and missing required dimensions or metrics. Assumptions may document non-material interpretation details only.

```json
{
  "schema_version": "chartpilot.analysis-plan/v1",
  "task_id": "T001",
  "status": "ready",
  "source_sha256": "same hash as input_profile.json",
  "question": "展示各地区月度销售额及环比变化",
  "assumptions": [],
  "cleaning": [
    {
      "operation": "cast",
      "column": "c0001",
      "to": "date",
      "format": "%Y-%m-%d",
      "on_error": "raise",
      "reason": "按月聚合需要明确日期类型"
    },
    {
      "operation": "cast",
      "column": "c0003",
      "to": "number",
      "on_error": "raise",
      "reason": "销售额求和需要数值类型"
    },
    {
      "operation": "drop_missing",
      "columns": ["c0001", "c0003"],
      "how": "any",
      "reason": "日期或指标为空的记录无法参与该分析"
    }
  ],
  "filters": [
    {"column": "c0002", "operator": "in", "value": ["华东", "华南"]}
  ],
  "time_bucket": {"column": "c0001", "frequency": "month", "output": "month"},
  "group_by": [
    {"column": "month", "output": "month"},
    {"column": "c0002", "output": "region"}
  ],
  "metrics": [
    {"column": "c0003", "aggregation": "sum", "output": "sales", "unit": "元"},
    {"column": "c0004", "aggregation": "nunique", "output": "orders", "unit": "单"}
  ],
  "post_calculations": [
    {
      "operation": "pct_change",
      "column": "sales",
      "output": "sales_mom",
      "partition_by": ["region"],
      "order_by": "month",
      "periods": 1,
      "as_percent": true
    }
  ],
  "top_n": null,
  "sort": [
    {"column": "month", "direction": "asc", "nulls": "last"},
    {"column": "region", "direction": "asc", "nulls": "last"}
  ],
  "chart_intent": {
    "analysis_kind": "trend",
    "chart_type": "line",
    "x": "month",
    "y": "sales",
    "series": "region",
    "title": "各地区月度销售额",
    "unit": "元",
    "time_range": null,
    "source_note": "数据来源：sales.csv",
    "plot_ready": true,
    "sort": "x-asc"
  }
}
```

Set `status` to `needs_clarification` when a key mapping or business definition is unresolved. The runner returns `NEEDS_CLARIFICATION` and creates no success manifest.

### Cleaning operations

Support only:

| Operation | Required fields | Optional fields and defaults |
| --- | --- | --- |
| `cast` | `column`, `to`, `reason` | `on_error: raise`; concrete `format` is required for `date` and `datetime` |
| `fill_missing` | `column`, non-null `value`, `reason` | none |
| `drop_missing` | non-empty `columns`, `reason` | `how: any` |
| `deduplicate` | `reason` | `subset`: all source columns; `keep: first` |

Allow cast targets `string`, `number`, `integer`, `boolean`, `date`, and `datetime`. Boolean conversion recognizes true/false, 1/0, yes/no, y/n, and Chinese 是/否 or 真/假, case-insensitively. `on_error: coerce` records invalid values as new missing values; `raise` returns `TYPE_CONVERSION_FAILED` without exposing those values.

Do not support silent outlier removal, arbitrary fill algorithms, interpolation, joins, user expressions, or custom Python. Return `UNSUPPORTED_OPERATION` for them.

### Filter operators

Support `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `not_in`, `between`, `contains`, `starts_with`, `ends_with`, `is_missing`, and `not_missing`. Require `value` except for the two missing-value operators. Require a two-item array for `between` and a non-empty array for `in` or `not_in`. Do not use null as a value; use the explicit missing-value operators. Require ISO-8601 strings for typed date or datetime filters. Pattern matching is literal, not regular-expression evaluation; set optional `case_sensitive` only on `contains`, `starts_with`, or `ends_with`.

### Time buckets

Support `day`, `week`, `month`, `quarter`, and `year`. Weeks start on Monday. Cast the source to `date` or `datetime` first. The output is an ISO date at the start of the bucket.

### Grouped metrics

Support `sum`, `mean`, `count`, `nunique`, `min`, and `max`. Use `column: "*"` only with `count` to count rows. Require numeric input for `sum` and `mean`. Preserve null groups with `dropna: false` semantics.

Each `group_by` entry maps either a profile column ID or the time-bucket output to a unique result column name. Every metric must declare a unique result `output` and may declare `unit`.

### Post calculations

Support:

- `share`: require `column` and `output`; optionally partition by result columns and set `as_percent`.
- `pct_change`: require `column`, `output`, and `order_by`; optionally partition, set positive integer `periods`, and set `as_percent`.

A zero denominator becomes an empty result cell, never infinity, and adds a `DIVIDE_BY_ZERO` warning to validation metadata.

### Top N and sort

Set `top_n` to null or provide `count`, `by`, `direction`, and optional `per_group`. Selection uses a stable sort and never includes hidden truncation. Apply final `sort` after Top N. Allow only `asc` or `desc` directions and `first` or `last` null placement.

### Chart intent

Provide one `y` result column and an optional `series` result column. Allow only `auto`, `line`, `bar`, `donut`, and `scatter` chart types; let the renderer choose horizontal orientation for a bar. Allow analysis kinds `trend`, `comparison`, `ranking`, `composition`, `relationship`, `distribution`, and `other`; `metric` and `contribution` are retained as compatible aliases that the renderer maps to bars. Set `x` to null only when the result has exactly one row and `chart_type` is `auto` or `bar`. Allow sort values `none`, `x-asc`, `x-desc`, `y-asc`, and `y-desc`. Limit `title` to 160 characters, `unit` to 40, `source_note` to 240, and stable string `time_range` to 100; `time_range` may also be null but never an object.

For a line chart, require every `x` value to be unique when `series` is null, or every `(x, series)` pair to be unique when `series` is present. Require non-empty `title` and `source_note`; the runner supplies a source-note default from the profiled filename when the plan omits it.

Require finite `y` in every result row, finite numeric `x` for scatter, nonblank `x` and `series`, distinct x/y/series roles, unique plot keys for bars, lines, and donuts, no more than 50 bar categories, no more than 12 series, and 2-8 nonnegative categories with at least one positive value for a donut. Return a structured analysis error instead of passing a predictably unrenderable result downstream.

Complete histogram bins, quartiles, contribution calculations, and every other business transformation in this analysis plan. The chart stage may encode values visually but must not aggregate, filter, truncate, or calculate a new metric.

## Execution order and semantics

Apply operations in this fixed order:

1. Verify contracts, trusted paths, task ID, source hash, encoding, delimiter, shape, and column order.
2. Read all cells as lexical strings and normalize only empty or whitespace-only cells to missing.
3. Apply cleaning steps in declared order.
4. Apply filters in declared order.
5. Create the optional time bucket.
6. Group and aggregate metrics.
7. Apply post calculations in declared order.
8. Apply Top N and final sorting.
9. Reject an empty result, an oversized result, or a chart metric with no finite value.
10. Serialize outputs, regenerate findings from result values, verify evidence against serialized `result.csv`, recheck the source hash, and commit the manifest last.

## Success artifacts

Write all paths relative to the task output directory in manifests.

### `generated_analysis.py`

Record the validated normalized plan and source/plan hashes as deterministic Python data. Treat the bundled runner as the normative executor. The generated artifact contains no API key, raw row, network operation, shell command, `eval`, or `exec`.

### `cleaned_data.csv`

Write this optional UTF-8 BOM CSV only when the plan declares a cleaning operation. Preserve original header text and order, including duplicate or blank headers. Never overwrite the source.

### `result.csv`

Write a UTF-8 BOM, LF-terminated, plot-ready table. Use ISO dates, machine-readable numbers, empty strings for missing values, and declared output columns only.

### `analysis_result.json`

Use this fixed cross-stage envelope:

```json
{
  "schema_version": "chartpilot.analysis-result/v1",
  "task_id": "T001",
  "stage": "analysis",
  "status": "success",
  "source": {"path": "C:\\data\\sales.csv", "sha256": "..."},
  "plan_sha256": "...",
  "artifacts": {
    "generated_analysis": {"path": "generated_analysis.py", "sha256": "..."},
    "cleaned_data": {"path": "cleaned_data.csv", "sha256": "..."},
    "result_csv": {"path": "result.csv", "sha256": "..."}
  },
  "result_schema": {
    "row_count": 24,
    "columns": [
      {"name": "month", "type": "date", "role": "time", "unit": null, "nullable": false},
      {"name": "region", "type": "string", "role": "dimension", "unit": null, "nullable": false},
      {"name": "sales", "type": "number", "role": "metric", "unit": "元", "nullable": false}
    ]
  },
  "cleaning_audit": [],
  "filter_audit": [],
  "calculation_audit": [],
  "findings": [
    {
      "id": "finding-001",
      "text": "month=2026-06-01、region=华东 的 sales 为最大值 125000。",
      "evidence": [
        {
          "selector": {"month": "2026-06-01", "region": "华东"},
          "column": "sales",
          "expected": 125000,
          "abs_tol": 1e-09,
          "rel_tol": 1e-09
        }
      ]
    }
  ],
  "chart_intent": {
    "analysis_kind": "trend",
    "chart_type": "line",
    "x": "month",
    "y": "sales",
    "series": "region",
    "title": "各地区月度销售额",
    "unit": "元",
    "time_range": null,
    "source_note": "数据来源：sales.csv",
    "plot_ready": true,
    "sort": "x-asc"
  },
  "validation": {"passed": true, "checks": [], "warnings": []}
}
```

Set `artifacts.cleaned_data` to null when no cleaning was requested. Each finding is generated from a finite result value. Its selector identifies a serialized result row, and its expected value is checked with the declared tolerances before success.

## Error contract

On failure, return a nonzero exit code and emit:

```json
{
  "ok": false,
  "error": {
    "code": "SOURCE_HASH_MISMATCH",
    "message": "The source CSV does not match input_profile.json.",
    "details": {"expected_sha256": "...", "actual_sha256": "..."}
  }
}
```

Keep details structural. Stable codes include:

- `INVALID_ARGUMENT`, `INVALID_JSON`, `INVALID_PROFILE`, `INVALID_PLAN`, `NEEDS_CLARIFICATION`
- `PATH_NOT_ALLOWED`, `UNC_PATH_NOT_ALLOWED`, `FILE_NOT_FOUND`, `FILE_BUSY_OR_PERMISSION`
- `SOURCE_HASH_MISMATCH`, `SOURCE_CHANGED`, `SOURCE_PROFILE_MISMATCH`, `SOURCE_READ_ERROR`
- `UNSUPPORTED_OPERATION`, `TYPE_CONVERSION_FAILED`, `FILTER_FAILED`, `AGGREGATION_FAILED`
- `EMPTY_RESULT`, `RESULT_TOO_LARGE`, `NO_FINITE_METRIC`, `DIVIDE_BY_ZERO`
- `DEPENDENCY_MISSING`, `OUTPUT_EXISTS`, `OUTPUT_WRITE_ERROR`, `INTERNAL_ERROR`

Use exit code `2` for CLI errors, `3` for contract or path errors, `4` for source failures, `5` for unsupported or invalid plans, `6` for execution or output failures, `7` for missing offline dependencies, and `70` for unexpected internal failures.

## Safety and determinism

- Read only the exact source path bound into the successful profile and verify SHA-256 before and after processing.
- Reject directory traversal after resolving existing path components. Reject UNC paths unless deployment policy passes `--allow-unc`.
- Accept operations only from the enumerations above. Never interpret an expression or execute model-provided code.
- Write temporary files in the output directory, flush and fsync them, back up the complete prior managed-artifact set, and install `analysis_result.json` last as the completion marker. If any replacement fails, remove newly installed files and restore every prior artifact, including an obsolete `cleaned_data.csv` that a successful new run would remove.
- Keep JSON key ordering, CSV row order, float formatting, finding order, and audit order stable. Omit timestamps, host names, and durations from deterministic artifacts.
- Run the process with a trusted environment that removes API keys and applies timeout, memory, child-process, and network controls. The script itself performs no network or subprocess operation.
