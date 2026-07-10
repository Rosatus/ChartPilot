# ChartPilot

English | [简体中文](README.zh-CN.md)

ChartPilot is a local-first CSV analysis skill set for Windows-oriented data agents. It profiles local CSV files, executes auditable declarative analysis plans, and renders validated PNG charts without sending data processing or chart generation to a remote service.

> [!IMPORTANT]
> This repository currently contains the three business Skills and their deterministic Python tools. It does not yet include the final Agent runtime, Windows offline bundle, or graphical interface.

## Capabilities

- Detect UTF-8, UTF-8 BOM, GBK/GB18030, delimiters, field types, missing values, duplicates, and candidate field roles.
- Apply explicit cleaning, filtering, date bucketing, grouped metrics, Top N, share, and percentage-change operations through an allowlisted plan.
- Render line, bar, donut, and scatter charts from a SHA-256-bound `result.csv` without recomputing business metrics.
- Preserve source files, emit structured errors, and install multi-file results transactionally.
- Support Chinese paths, headers, labels, and offline dependency installation.

## Repository Layout

```text
ChartPilot/
├── skills/
│   ├── chartpilot-profile-csv/
│   ├── chartpilot-analyze-data/
│   └── chartpilot-render-chart/
├── ChartPilot需求规格说明.md
├── Skill开发说明.md
├── Windows离线部署方案.md
└── requirements.txt
```

Each Skill contains a concise `SKILL.md`, UI metadata, a detailed contract, and a deterministic Python entry point. The analysis Skill also includes regression tests.

## Requirements

- Python 3.12 recommended
- Windows 10 or Windows 11 for the target deployment
- `pandas`, `matplotlib`, and `Pillow` from [`requirements.txt`](requirements.txt)

Create a local development environment:

```bash
python -m venv .venv
```

Activate it, then install dependencies:

```bash
python -m pip install -r requirements.txt
```

For an offline Windows deployment, download compatible Windows wheels on a connected build machine and install them from a local wheel directory. See [Windows离线部署方案.md](Windows离线部署方案.md).

## Workflow

Profile a CSV:

```bash
python skills/chartpilot-profile-csv/scripts/profile_csv.py "data/sales.csv" \
  --task-id demo-001 \
  --output-dir "workspace/tasks/demo-001"
```

Create `analysis_plan.json` according to the [analysis contract](skills/chartpilot-analyze-data/references/contracts.md), then run it:

```bash
python skills/chartpilot-analyze-data/scripts/run_analysis.py \
  --profile "workspace/tasks/demo-001/input_profile.json" \
  --plan "workspace/tasks/demo-001/analysis_plan.json" \
  --output-dir "workspace/tasks/demo-001"
```

Render the saved result:

```bash
python skills/chartpilot-render-chart/scripts/render_chart.py \
  --analysis-result "workspace/tasks/demo-001/analysis_result.json"
```

The normal artifact chain is:

```text
input_profile.json
  -> analysis_plan.json
  -> result.csv + analysis_result.json
  -> chart.png + chart_result.json + summary.md
```

## Tests

Run the analysis regression suite:

```bash
python -m unittest discover -s skills/chartpilot-analyze-data/tests -v
```

Every CLI also supports `--help`. The current implementation has been integration-tested with Chinese paths and CSV content on Python 3.12. Native Windows 10/11 acceptance testing remains pending.

## Security Boundary

- The bundled Python tools do not make network requests or execute model-provided Python expressions.
- Source and upstream artifacts are bound by SHA-256 and checked before downstream use.
- Sample disclosure can be disabled or redacted during profiling.
- API keys must remain in runtime configuration and must never be written to plans, generated code, logs, or results.
- Skills are not an operating-system sandbox. The final Windows runtime must enforce directory ACLs, process timeouts, resource limits, and an LLM-endpoint-only network policy.

## Documentation

- [Requirements specification](ChartPilot需求规格说明.md)
- [Skill development guide](Skill开发说明.md)
- [Windows offline deployment plan](Windows离线部署方案.md)

## License

No software license has been selected yet. Repository visibility does not grant permission to use, modify, or redistribute the code beyond rights provided by applicable law.
