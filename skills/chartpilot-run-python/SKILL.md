---
name: chartpilot-run-python
description: Analyze a local CSV from a natural-language request by adapting and executing ChartPilot's inspect, analysis, and chart Python templates with bundled WinPython. Use for every ChartPilot prompt-plus-CSV task, including custom cleaning, nested grouping, domain calculations, anomaly thresholds, multi-panel Chinese reports, and bespoke visualizations. The Agent is expected to modify task code when that improves correctness or presentation.
---

# Build An Adaptive CSV Report

Use the two ChartPilot MCP tools. Do not look for legacy profile, analysis-plan, render, shell,
Developer, or system-Python routes.

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

## Analyze

Start from `analyze_csv.py` and rewrite the editable analysis function to match the request.
Direct pandas/numpy code is expected for multi-step operations such as per-entity dominant
category selection, peer baselines, stable tie-breaks, ratios, risk bands, and multiple result
tables. Keep the original CSV read-only and keep outputs under the task directory.

Write a plot-ready `result.csv` plus evidence-backed `adaptive_analysis.json`, then run stage
`analysis`. Check the returned manifest and revise the code when findings or chart intent do not
faithfully answer the request.

## Render

Start from `render_chart.py`. Modify layout, panels, chart types, annotation density, palette,
Chinese typography, labels, and explanatory text for the task. A multi-panel report is preferred
when one plot cannot explain both population and severity.

Write `chart.png`, `summary.md`, and `adaptive_chart.json`, then run stage `render`. Inspect the
result and iterate when labels overlap, text is unreadable, important groups are hidden, or the
visual does not support the findings.

## Runtime

Use only packages listed in the returned runtime inventory. Do not call `pip`, a system Python,
or a shell. ChartPilot executes the complete submitted source with bundled WinPython and records
the script hash, runtime, output, duration, status, and artifacts. This is reproducible portable
execution, not a sandbox.
