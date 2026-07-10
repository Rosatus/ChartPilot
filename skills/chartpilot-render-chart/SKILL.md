---
name: chartpilot-render-chart
description: Render and validate a ChartPilot PNG chart and evidence-bound Chinese summary from a successful chartpilot.analysis-result/v1 manifest and its SHA-256-bound plot-ready result.csv. Use when a completed ChartPilot analysis must become an auditable line, bar, donut, or scatter chart without reopening source data or recomputing business metrics.
---

# ChartPilot Render Chart

Render only the frozen analysis result. Treat the analysis manifest and its hash-bound `result.csv` as the complete data boundary.

## Run The Workflow

1. Read [references/contracts.md](references/contracts.md) completely before the first render in a task.
2. Confirm that `analysis_result.json` has schema `chartpilot.analysis-result/v1`, stage `analysis`, and status `success`.
3. Invoke the bundled renderer with quoted paths:

```bash
python scripts/render_chart.py \
  --analysis-result "<task-dir>/analysis_result.json" \
  --output-dir "<task-dir>"
```

4. Pass `--font-path "<font-file>"` when the chart contains Chinese text and automatic Windows font discovery cannot find a CJK font.
5. Treat exit code `0` and `chart_result.json` with `status: success` as the only successful outcome.
6. Return `chart.png`, `summary.md`, `chart_spec.json`, `generated_chart.py`, and `chart_result.json` to the calling workflow.

## Preserve The Data Boundary

- Read the CSV path only from `artifacts.result_csv.path` in `analysis_result.json`.
- Require a relative path named `result.csv`, resolve it beneath the manifest directory, and verify its declared SHA-256 before parsing it.
- Never inspect `source.path`, `cleaned_data.csv`, the original CSV, or any other tabular file.
- Never group, aggregate, calculate Top N, fill missing values, drop rows, derive shares, or alter business values.
- Require plot-ready distribution results. Reject raw observations presented as a distribution request.
- Use `findings[].text` verbatim as the analytical content of `summary.md`; do not invent new numerical conclusions.

## Apply Chart Rules

- Select a line chart for `trend`.
- Select a bar chart for `comparison`, `ranking`, and precomputed `distribution` results.
- Select a donut chart for `composition` only when there are two through eight unique nonnegative categories; fall back to bar only when selection is automatic.
- Select a scatter chart for `relationship`.
- Accept `x: null` only for a one-row, one-metric bar chart with no series.
- Reject duplicate bar or donut category keys and duplicate grouped-bar `(x, series)` keys instead of aggregating them.
- Preserve result rows. Allow only the explicit presentation sort declared by `chart_intent.sort`.

## Handle Failures

Read the single JSON error object written to stderr. Use `error.code` to decide whether to repair the upstream manifest, regenerate the result, provide a font, or install dependencies. Do not retry unchanged inputs.

Do not accept partially generated files as success. The renderer stages and validates all artifacts, commits `chart_result.json` last, and leaves a prior successful artifact set intact when rendering fails before commit.

## Resources

- Use `scripts/render_chart.py` for deterministic rendering and validation.
- Use `references/contracts.md` for the exact input, output, chart-selection, validation, and error contracts.
