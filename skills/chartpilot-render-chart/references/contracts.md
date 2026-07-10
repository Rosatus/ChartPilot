# ChartPilot Chart Rendering Contracts

## Contents

1. Input boundary
2. Analysis result contract
3. Chart intent contract
4. Selection rules
5. Output contracts
6. Validation rules
7. Atomic commit behavior
8. CLI contract
9. Error contract

## 1. Input Boundary

Pass exactly one `analysis_result.json` to the renderer. The renderer may read only:

- the supplied manifest;
- the relative `artifacts.result_csv.path` declared by that manifest;
- an explicit font file supplied with `--font-path`;
- installed system font metadata.

The renderer must not read `source.path`, the original CSV, `cleaned_data.csv`, an analysis plan, or another data file. It must not access the network.

Resolve `artifacts.result_csv.path` beneath the directory containing `analysis_result.json`. Require the basename `result.csv`, reject absolute paths and `..` traversal, resolve symlinks, and reject a resolved path outside that directory.

## 2. Analysis Result Contract

Require this shape:

```json
{
  "schema_version": "chartpilot.analysis-result/v1",
  "task_id": "task-20260710-001",
  "stage": "analysis",
  "status": "success",
  "artifacts": {
    "result_csv": {
      "path": "result.csv",
      "sha256": "64-lowercase-or-uppercase-hex-characters"
    }
  },
  "result_schema": {
    "row_count": 3,
    "columns": [
      {"name": "月份", "type": "string"},
      {"name": "销售额", "type": "number"}
    ]
  },
  "findings": [
    {
      "id": "finding-1",
      "text": "6 月销售额高于 5 月。",
      "evidence": [
        {
          "selector": {"月份": "2026-06"},
          "column": "销售额",
          "expected": 125000,
          "abs_tol": 1e-09,
          "rel_tol": 1e-09
        }
      ]
    }
  ],
  "chart_intent": {
    "analysis_kind": "trend",
    "chart_type": "auto",
    "x": "月份",
    "y": "销售额",
    "series": null,
    "title": "月度销售额趋势",
    "unit": "元",
    "time_range": "2026-04 至 2026-06",
    "source_note": "ChartPilot 已保存分析结果",
    "plot_ready": true,
    "sort": "x-asc"
  },
  "validation": {
    "passed": true,
    "checks": [],
    "warnings": []
  }
}
```

Require `result_schema.row_count` to match the parsed CSV row count. Accept `result_schema.columns` as either an ordered list of column names or an ordered list of objects containing `name`; require the names and order to match the CSV exactly. Read every CSV field lexically as text so identifiers such as `001` remain unchanged. Convert only the selected numeric x/y presentation series, and reject conversion failures.

Require every finding to contain a nonempty `id`, nonempty `text`, and list-valued `evidence`. Evidence is owned and validated by the analysis stage; its canonical fields are `selector`, `column`, `expected`, `abs_tol`, and `rel_tol`. Copy finding text into the summary without numerical reinterpretation.

Treat `validation.warnings` as the authoritative analysis warning list. Accept a top-level `warnings` list only for compatibility with an older producer.

## 3. Chart Intent Contract

Use these fields:

| Field | Type | Rule |
| --- | --- | --- |
| `analysis_kind` | string | One of `metric`, `trend`, `comparison`, `ranking`, `composition`, `contribution`, `relationship`, `distribution`, `other`. |
| `chart_type` | string | One of `auto`, `line`, `bar`, `donut`, `scatter`. |
| `x` | string or null | Name an existing result column. Allow null only for a one-row bar. |
| `y` | string | Name one existing numeric result column. |
| `series` | string or null | Name an existing grouping column used only to partition already-computed rows. |
| `title` | string | Require a nonempty value and keep at most 160 normalized characters. |
| `unit` | string or null | Keep at most 40 normalized characters. |
| `time_range` | string or null | Keep at most 100 normalized characters. |
| `source_note` | string | Require a nonempty value and keep at most 240 normalized characters. |
| `plot_ready` | boolean | Require `true`; never transform raw observations into plot-ready data. |
| `sort` | string | One of `none`, `x-asc`, `x-desc`, `y-asc`, `y-desc`. |

Allow `--chart-type` and `--title` to override the corresponding presentation fields. Do not allow an override to bypass data-shape checks.

Treat sorting as presentation ordering only. Do not filter, sample, fill, aggregate, normalize, calculate a ratio, or derive a new metric.

## 4. Selection Rules

Apply an explicit non-`auto` chart type after validating it. For `auto`, select:

| Analysis kind | Chart |
| --- | --- |
| `trend` | `line` |
| `metric`, `comparison`, `ranking`, or `contribution` | `bar` |
| `composition` | `donut` for 2-8 valid categories, otherwise `bar` |
| `relationship` | `scatter` |
| `distribution` | `bar`, using only precomputed bins/statistics |
| `other` | `scatter` when both axes are numeric, otherwise `bar` |

Require `x` for line, donut, and scatter charts. Permit no series on donut charts. Require finite numeric `x` and `y` for scatter. Require finite numeric `y` for every chart.

Require nonblank x/category/series values. Require unique `x` keys for an ungrouped line, bar, or donut. Require unique `(x, series)` keys for a grouped line or bar. Reject duplicate keys rather than combining or implicitly interpreting their values.

Permit at most 8 donut categories, 50 bar categories, 12 series, and the CLI `--max-points` row limit. Reject excess data; do not silently sample it.

## 5. Output Contracts

Write all successful artifacts into `--output-dir`, defaulting to the manifest directory:

```text
chart_spec.json
generated_chart.py
chart.png
chart_result.json
summary.md
```

Record upstream manifest and result paths relative to this output directory. When it differs from the analysis task directory, retain the necessary `..` segments so each recorded path still resolves to the real artifact.

### chart_spec.json

Use schema `chartpilot.chart-spec/v1`. Record:

- renderer version and task ID;
- analysis manifest and result CSV hashes;
- selected chart type and selection reason;
- exact x, y, series, title, unit, time range, source note, and sort;
- figure width, height, and DPI;
- plot-ready assertion and analysis kind.

### generated_chart.py

Write a valid Python audit snapshot containing the complete chart spec and renderer source hash. Treat it as an immutable record of the render decision, not as an alternate analysis program. It must not contain source-data paths, source rows, API keys, or business calculations.

### chart.png

Write a standards-compliant PNG from the Matplotlib `Agg` backend. Use a fixed white background and the requested dimensions. Do not return Base64 unless a separate caller explicitly converts the saved artifact.

### chart_result.json

Use schema `chartpilot.chart-result/v1`, stage `chart`, and status `success`. Record hashes for every upstream and generated artifact, PNG MIME type and byte size, pixel dimensions, foreground pixel count and ratio, data-point count, artist count, font details, and warnings. Do not write timestamps so identical inputs and renderer versions produce stable metadata.

### summary.md

Identify the selected chart and its x/y/series mapping. State that the chart uses the frozen `result.csv` without recomputation. Reproduce `findings[].text` exactly as the analytical findings. Do not introduce new business numbers.

## 6. Validation Rules

Before committing output, verify:

- the result file hash with SHA-256;
- CSV row count and ordered columns against `result_schema`;
- all requested fields and numeric values;
- chart-specific uniqueness and cardinality limits;
- at least one plotted data point and at least one data artist;
- the eight-byte PNG signature;
- Pillow recognition as PNG;
- dimensions of at least 320 by 240 pixels;
- at least 100 pixels and a `foreground_ratio` of at least `0.005` (0.5 percent) differing visibly from the corner background color.

Detect Chinese chart text in titles, labels, notes, categories, and series. Prefer, in order, an explicit font, Microsoft YaHei, DengXian, SimHei, SimSun, Noto Sans CJK SC, Source Han Sans SC, WenQuanYi Zen Hei, Droid Sans Fallback, and Arial Unicode MS. Accept regional Noto Sans CJK family names when the installed TTC reports a different face name. Return `CHINESE_FONT_NOT_FOUND` rather than silently producing missing-glyph boxes.

## 7. Atomic Commit Behavior

Render every file into a staging directory located inside the output directory. Validate the complete staged artifact set before replacing destination files. Back up existing destination files during replacement and restore them if a commit operation fails. Commit `chart_result.json` last so it acts as the success marker.

Do not overwrite a prior successful artifact set when validation fails before commit.

## 8. CLI Contract

```text
python render_chart.py --analysis-result PATH [options]

required:
  --analysis-result PATH

options:
  --output-dir PATH
  --chart-type auto|line|bar|donut|scatter
  --title TEXT
  --font-path PATH
  --width FLOAT
  --height FLOAT
  --dpi INTEGER
  --max-points INTEGER
  --debug
```

Make `--help` work even when pandas, Matplotlib, or Pillow is not installed. On success, write one JSON object to stdout and return exit code `0`.

## 9. Error Contract

Write one JSON object to stderr and return a nonzero exit code:

```json
{
  "status": "error",
  "stage": "chart",
  "error": {
    "code": "RESULT_HASH_MISMATCH",
    "message": "result.csv does not match the SHA-256 declared by analysis_result.json.",
    "recoverable": false,
    "details": {
      "expected": "...",
      "actual": "..."
    }
  }
}
```

Use stable codes including `DEPENDENCY_MISSING`, `MANIFEST_NOT_FOUND`, `INVALID_JSON`, `INVALID_ANALYSIS_RESULT`, `ANALYSIS_NOT_SUCCESSFUL`, `INVALID_RESULT_PATH`, `RESULT_NOT_FOUND`, `RESULT_HASH_MISMATCH`, `RESULT_SCHEMA_MISMATCH`, `CSV_READ_FAILED`, `EMPTY_RESULT`, `INVALID_CHART_INTENT`, `DISTRIBUTION_NOT_PLOT_READY`, `UNSUPPORTED_CHART_TYPE`, `NON_NUMERIC_DATA`, `NON_FINITE_DATA`, `DUPLICATE_PLOT_KEY`, `TOO_MANY_POINTS`, `CHINESE_FONT_NOT_FOUND`, `CHART_RENDER_FAILED`, `PNG_VALIDATION_FAILED`, and `ATOMIC_COMMIT_FAILED`.

Set `recoverable` to true only when changing the manifest, regenerating analysis output, supplying a valid font, or installing dependencies can resolve the failure. Include a traceback only with `--debug`.
