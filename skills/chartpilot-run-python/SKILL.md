---
name: chartpilot-run-python
description: Analyze a local CSV from a natural-language request by adapting and executing ChartPilot's inspect, analysis, and chart Python templates with bundled WinPython. Use for every ChartPilot prompt-plus-CSV task, including custom cleaning, nested grouping, domain calculations, anomaly thresholds, multi-panel Chinese reports, and bespoke visualizations. The Agent is expected to modify task code when that improves correctness or presentation.
---

# Build An Adaptive CSV Report

Use only the two ChartPilot MCP tools. Do not use legacy deterministic tools, a shell, Developer,
system Python, or `pip` for this workflow. Generated task Python is the flexible execution route.

## Critical Path Rules

- `context.paths.output_dir` is a write destination for the current attempt. It changes on every
  retry. Never read upstream inputs from it.
- Read the CSV from `context.source.path` (or `context.paths.prepared_csv` when it exists), analysis
  input from `context.paths.result_csv`, and analysis metadata from
  `context.paths.analysis_result`.
- Preserve or deliberately extend the templates' context loading, output writing, and font
  bootstrap. Rewrite the business logic and chart composition as freely as the task requires.
- Tool failures include a bounded `process` diagnostic. Read its stderr/stdout tail and correct
  the submitted source directly; do not open execution records through a shell merely to find the
  traceback.

## Prepare

Call `chartpilot_prepare_adaptive_task` with the CSV path and exactly one of the user's inline
request or local `.md`/`.txt` request path. Keep the returned task ID, context, and three template
sources.

Read the request, CSV header/sample metadata, runtime package inventory, and template code before
choosing the analysis. Read [references/adaptive-task-contract.md](references/adaptive-task-contract.md)
for exact outputs and retry behavior.

## Inspect

Start from `inspect_csv.py`. Modify its editable function whenever the schema, encoding, quality
checks, semantic roles, or preparation needs are task-specific. Call
`chartpilot_run_task_python` with stage `inspect` and the complete resulting source.

Use `inspection.json` as evidence, then decide the entity, dimensions, weights, metrics,
comparisons, thresholds, and required visual explanation. Do not force the request into a fixed
aggregation vocabulary.

Before analysis, explicitly separate:

- source row grain and analytical entity;
- detail-output grain for auditing;
- visual grain for comparison;
- metric, baseline, weight, thresholds, tie policy, and missing/invalid-value policy.

Detail and visual grain often differ. Thousands of entity rows may belong in `result.csv` while a
chart uses category/risk aggregates. Entity-level marks are still valid when the request truly
needs individual exceptions and the result remains readable.

Finding or exporting exceptional entities does not imply plotting every entity. Put auditable
exception rows in a declared CSV. If entity marks merge into opaque columns/blocks even with
transparency, the primary view must aggregate to a decision-ready grain; an entity view may remain
as a smaller exception-focused panel. For peer-baseline/threshold questions, a useful but optional
pattern is a population-composition panel plus an aggregate metric/threshold panel, with bubble
area encoding group size.

## Analyze

Start from `analyze_csv.py` and rewrite the editable analysis function to match the request.
Direct pandas/numpy code is expected for multi-step operations such as per-entity dominant
category selection, peer baselines, stable tie-breaks, ratios, risk bands, and multiple result
tables. Keep the original CSV read-only and keep outputs under the task directory.

Write a plot-ready `result.csv` plus evidence-backed `adaptive_analysis.json`, then run stage
`analysis`. Check the returned manifest and revise the code when findings or chart intent do not
faithfully answer the request.

When the task needs extra baselines, exception lists, or supporting tables, write them during the
analysis stage and list their plain filenames in `adaptive_analysis.json.artifacts`. Only declared
artifacts are committed; temporary unlisted files are discarded. Make `chart_intent` describe what
each panel answers, what one mark represents, and how position, area, and color are encoded.

## Render

Start from `render_chart.py`. Modify layout, panels, chart types, annotation density, palette,
Chinese typography, labels, and explanatory text for the task. A multi-panel report is preferred
when one plot cannot explain both population and severity.

For dense data, choose a visual aggregation that exposes the requested comparison instead of
plotting every detail row by default. For a bubble chart, make bubble area represent a meaningful
nonnegative count/weight and state what one bubble means. Preserve the template's global font
configuration for Chinese text; a missing-glyph diagnostic is a failed render, not a warning to
ignore.

Write `chart.png`, `summary.md`, and `adaptive_chart.json`, then run stage `render`. Inspect the
result and iterate when labels overlap, text is unreadable, important groups are hidden, or the
visual does not support the findings.

After the bridge accepts the PNG, use the available image-reading tool to inspect the actual
`chart.png`. The bridge's nonblank check verifies transport, not visual quality. Do not mark the
task complete until Chinese text, density, overlap, encodings, thresholds, and the main business
message are readable. Reconcile the final file list with the committed artifacts in returned
manifests; never advertise a file that existed only in an attempt directory.

Treat opaque point clouds, colliding title/legend/annotation text, clipped labels, and unreadable
small groups as failed visual review. Revise and rerun `render` after seeing any of them; alpha
transparency alone does not solve overplotting.

## Runtime

Use only packages listed in the returned runtime inventory. Do not call `pip`, a system Python,
or a shell. ChartPilot executes the complete submitted source with bundled WinPython and records
the script hash, runtime, output, duration, status, and artifacts. This is reproducible portable
execution, not a sandbox.
