# Adaptive-Only CSV Analysis Design

## Decision Summary

Use one adaptive route for all prompt-plus-CSV work:

1. Remove the deterministic profile, analysis-plan, and fixed-render MCP tools.
2. Remove their three product Skills from Goose staging and release packaging.
3. Keep one adaptive product Skill that gives the Agent compact inspect, analyze, and render
   templates.
4. Execute Agent-authored task code through two explicit ChartPilot MCP operations and bundled
   WinPython, without Goose Developer or a shell.
5. Validate identity, execution, and artifacts at the bridge boundary, but do not constrain
   business logic with an operation allowlist or fixed chart selector.

This is one integrated task because the MCP surface, Skill routing, templates, packaging, and
SY135 regression must change together. There is no compatibility requirement for removed tools.

## Product Flow

```text
User prompt text or prompt.md + source.csv
  -> chartpilot_prepare_adaptive_task
     -> request.md + task_context.json
     -> returns compact inspect/analyze/render templates and task ID
  -> Agent edits inspect template
  -> chartpilot_run_task_python(stage=inspect, source_code=...)
     -> inspection.json / optional prepared.csv
  -> Agent edits analyze template using request + inspection
  -> chartpilot_run_task_python(stage=analysis, source_code=...)
     -> result.csv + adaptive_analysis.json + analysis_result.json
  -> Agent edits render template using request + analysis
  -> chartpilot_run_task_python(stage=render, source_code=...)
     -> chart.png + summary.md + adaptive_chart.json + chart_result.json
```

The Agent may leave a template mostly unchanged, but there is no deterministic alternate route.

## Skill Organization

Retain and refocus `chartpilot-run-python` as the only staged ChartPilot product Skill. Remove:

- `chartpilot-profile-csv`
- `chartpilot-analyze-data`
- `chartpilot-render-chart`

Organize the remaining Skill according to the reusable-resource model:

```text
skills/chartpilot-run-python/
  SKILL.md
  agents/openai.yaml
  assets/templates/
    inspect_csv.py
    analyze_csv.py
    render_chart.py
  references/
    adaptive-task-contract.md
    runtime-contract.md
```

Keep `SKILL.md` concise and high-freedom. Put boilerplate in assets and detailed schemas in one-
level references. Each template is compact, UTF-8, import-safe, and driven by
`--context <task_context.json>`. It has a clear editable region without SY135-specific names,
columns, thresholds, or chart geometry.

## MCP Surface

Goose must enumerate exactly two ChartPilot tools.

### `chartpilot_prepare_adaptive_task`

Inputs:

- `source_path`: existing local CSV.
- exactly one of `request_text` or `request_path`; request files are bounded UTF-8/UTF-8-BOM
  `.md` or `.txt` files.
- optional task ID.

Behavior:

- Validate the source/request paths against configured read roots and allocate the task.
- Persist `request.md` atomically.
- Record source path, size, SHA-256, bounded header/sample metadata, runtime ID, installed
  distributions, template versions, stage paths, and output directory in `task_context.json`.
- Return task context plus all three template sources. Preparation performs no business
  profiling or analysis.

### `chartpilot_run_task_python`

Inputs:

- task ID.
- stage: `inspect`, `analysis`, or `render`.
- complete UTF-8 Python source, bounded in size.

Behavior:

- Store exact source as `generated_inspect.py`, `generated_analysis.py`, or
  `generated_chart.py` beneath the task directory.
- Invoke `<bundled-python> -I <script> --context <task_context.json>` directly with the portable
  environment, finite timeout, and bounded stdout/stderr.
- Write an append-only stage attempt record with source/runtime hashes, timestamps, duration,
  exit status, output hashes, and bounded output.
- Do not apply AST/import allowlists, network isolation, shell restrictions inside Python, or a
  sandbox in this task.
- On success, validate only the stage's interoperability/output contract.

Delete the prior `chartpilot_profile_csv`, `chartpilot_analyze_data`, and
`chartpilot_render_chart` registrations and related bridge paths.

## Stage Contracts

### Inspect

The script reads the source path from task context and must write bounded `inspection.json`.
It may also write `prepared.csv`. The template demonstrates encoding-aware pandas CSV loading,
schema/quality summaries, candidate semantic roles, and evidence samples. The Agent owns the
actual inspection logic.

### Analysis

Require nonempty `result.csv` and `adaptive_analysis.json` containing task ID, question,
assumptions, result column metadata, evidence-backed findings, and chart intent. The bridge
computes hashes and emits `analysis_result.json`; generated code owns every business calculation.

### Render

Require a valid nonblank `chart.png`, UTF-8 `summary.md`, and `adaptive_chart.json` describing
report type, finding IDs, and presentation notes. The bridge validates PNG signature,
dimensions, size, and foreground content, computes hashes, and emits `chart_result.json`.
Generated code owns multi-panel composition, annotations, palette, and layout.

## SY135 Reference Interpretation

The reusable reasoning pattern is:

1. Infer entity, usage dimension, exposure/count weight, and metric from prompt plus data.
2. Select each entity's dominant category with an explicit stable tie-break.
3. Establish a peer baseline within the selected category.
4. Calculate relative deviation and prompt-defined threshold bands.
5. Preserve detailed evidence while presenting aggregate population and severity.
6. Use multiple coordinated panels when one plot cannot explain both.

The local acceptance run must reproduce 6,523 selected machines, per-gear totals
`316,19,83,413,1103,1825,1456,862,190,221,35`, 96 machines above 25%, and zero above 50%.
The PNG must contain the two semantic panels and readable Chinese labels, not pixel-match the
manual output.

## Test Data And Privacy

Do not copy the user's raw CSV, machine IDs, workbook, PNG, or Downloads path into tracked or
released files.

- Add an opt-in local SY135 test accepting the case root as an argument.
- Store only aggregate expectations in the repository.
- Add an anonymized synthetic prompt/CSV with different field names, values, and thresholds for
  continuous anti-hard-coding coverage.

## Dependencies

Existing `numpy`, `pandas`, `matplotlib`, and `Pillow` cover the intended flow. Do not add
`openpyxl`: XLSX is neither input nor output. Install no package unless implementation proves a
reusable need, then update requirements, lock, wheelhouse, runtime, licenses, and packaging.

## Migration And Rollback

- This is an intentional breaking migration: remove the three deterministic tools, Skills,
  contracts, runners, tests, and documentation paths after any shared neutral helpers are moved.
- Update Goose Skill staging from exactly four product Skills to exactly one.
- Update MCP enumeration from exactly three tools to exactly two adaptive tools.
- Existing task artifacts may remain on disk but are not supported as an execution route.
- Rollback is a Git/release rollback, not a runtime compatibility switch.

## Trade-offs

- A single route eliminates tool/Skill misrouting but makes task success more dependent on Agent-
  generated code quality.
- Passing complete source through MCP is intentionally powerful and matches the requested risk
  posture.
- Post-execution validation protects interoperability, not the correctness of business logic;
  reference and synthetic regressions carry that burden.
