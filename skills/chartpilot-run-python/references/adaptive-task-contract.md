# Adaptive Task Contract

## Contents

1. MCP operations
2. Task context
3. Inspect output
4. Analysis output
5. Render output
6. Execution and retry rules
7. Runtime boundary

## 1. MCP Operations

Prepare once:

```text
chartpilot_prepare_adaptive_task(
  source_path,
  request_text=null,
  request_path=null,
  task_id=null
)
```

Provide exactly one request form. The result contains `task_id`, `context`, and the complete
`inspect`, `analysis`, and `render` template sources.

Run each stage with the complete edited source:

```text
chartpilot_run_task_python(task_id, stage, source_code)
```

Valid stages are `inspect`, `analysis`, and `render`, in that order. A failed attempt returns an
execution-record path. Correct the source and submit the complete replacement in a new attempt.

## 2. Task Context

Every template receives:

```text
<bundled-python> -I <generated-script> --context <attempt-task-context.json>
```

The context uses schema `chartpilot.adaptive-task/v1` and provides:

- `task_id`;
- source path, size, SHA-256, encoding/delimiter hints, headers, and bounded samples;
- request path, SHA-256, and origin;
- bundled interpreter/runtime identity and installed distributions;
- task/input/output artifact paths;
- current stage, attempt, and submitted script hash.

Always read paths from the context. `context.paths.output_dir` is an attempt-specific write
directory and changes between retries; never read upstream artifacts from it. Read upstream data
from `context.source.path`, `context.paths.prepared_csv`, `context.paths.result_csv`, or
`context.paths.analysis_result` as appropriate.

## 3. Inspect Output

Write `inspection.json` under `context.paths.output_dir`:

```json
{
  "schema_version": "chartpilot.inspection/v1",
  "task_id": "T001",
  "row_count": 100,
  "column_count": 4,
  "columns": [],
  "quality": {},
  "semantic_roles": {},
  "notes": []
}
```

`columns` must be a list. You may also write nonempty `prepared.csv` when task-specific parsing or
cleaning creates a useful analysis input. Do not create XLSX as an intermediate format.

## 4. Analysis Output

Write nonempty UTF-8/UTF-8-SIG `result.csv` and `adaptive_analysis.json`:

```json
{
  "schema_version": "chartpilot.adaptive-analysis/v1",
  "task_id": "T001",
  "question": "The exact analytical question",
  "assumptions": [],
  "result_schema": [
    {"name": "category", "type": "text", "role": "dimension"},
    {"name": "value", "type": "number", "role": "metric", "unit": null}
  ],
  "findings": [
    {
      "id": "finding-1",
      "text": "A claim supported by result.csv",
      "evidence": [{"column": "value", "value": 10}]
    }
  ],
  "chart_intent": {"report_type": "comparison", "title": "Example"}
}
```

`result_schema[].name` must exactly match the CSV headers in order. Finding IDs must be unique and
every finding must include an evidence list. The bridge creates `analysis_result.json` after
validation.

Optional supporting files are declared in `adaptive_analysis.json`:

```json
{
  "artifacts": ["category_baseline.csv", "exceptions.csv"]
}
```

Entries are unique plain filenames with `.csv`, `.json`, `.md`, or `.txt` extensions. Declared
files must be nonempty UTF-8 text. The bridge commits them atomically and records their size/hash
under `analysis_result.json.artifacts.auxiliary`; unlisted attempt files are discarded.

## 5. Render Output

Write a valid nonblank `chart.png`, nonempty UTF-8 `summary.md`, and `adaptive_chart.json`:

```json
{
  "schema_version": "chartpilot.adaptive-chart/v1",
  "task_id": "T001",
  "report_type": "multi-panel-risk-report",
  "finding_ids": ["finding-1"],
  "presentation_notes": ["Two coordinated panels"]
}
```

The PNG must be between 320x240 and 8192x8192 and no larger than 64 MiB. The bridge verifies that
it is nonblank and creates `chart_result.json` after validation. Matplotlib missing-glyph warnings
cause recoverable `RENDER_TEXT_UNREADABLE`; replacement characters in render text are rejected.
After success, the Agent must still inspect the actual image because nonblank validation does not
judge layout, density, overlap, or whether the visual answers the request.

## 6. Execution And Retry Rules

- The bridge stores exact submitted sources as `generated_inspect.py`,
  `generated_analysis.py`, and `generated_chart.py`.
- Outputs run in staging and replace prior successful stage outputs only after validation.
- Execution records are append-only under `executions/` and include bounded stdout/stderr.
- Tool responses include bounded process diagnostics. Failures after generated code starts are
  marked recoverable and include stderr/stdout tails for source correction.
- Analysis requires a successful inspect output. Render requires a successful analysis output.
- The source CSV hash is checked before every stage. Prepare a new task if it changed.
- On failure, change the source before retrying; do not repeat an identical attempt.

## 7. Runtime Boundary

The interpreter is `runtime/winpython/python/python.exe` resolved by the MCP bridge, never `PATH`.
Use the installed package inventory returned in context. Do not install packages during a task.
The generated code is intentionally not sandboxed; keep work task-local for reproducibility and
do not mutate the runtime or source CSV.
