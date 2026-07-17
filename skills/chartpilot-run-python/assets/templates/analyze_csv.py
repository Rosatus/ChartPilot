from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


def load_context(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "chartpilot.adaptive-task/v1":
        raise ValueError("Unsupported adaptive task context.")
    return value


def read_source(context: dict[str, Any]) -> pd.DataFrame:
    prepared = Path(context["paths"]["prepared_csv"])
    if prepared.is_file():
        return pd.read_csv(prepared, encoding="utf-8-sig", low_memory=False)
    source = context["source"]
    options: dict[str, Any] = {"low_memory": False}
    if source.get("encoding_hint"):
        options["encoding"] = source["encoding_hint"]
    if source.get("delimiter_hint"):
        options["sep"] = source["delimiter_hint"]
    return pd.read_csv(source["path"], **options)


def analyze(frame: pd.DataFrame, context: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    """EDIT: implement the request and separate detail-output grain from visual grain."""
    converted: dict[str, pd.Series] = {}
    for name in frame.columns:
        numeric = pd.to_numeric(frame[name], errors="coerce")
        if numeric.notna().mean() >= 0.9:
            converted[str(name)] = numeric
    numeric_name = next(iter(converted), None)
    dimension_name = next((str(name) for name in frame.columns if str(name) != numeric_name), None)
    if numeric_name and dimension_name:
        working = pd.DataFrame(
            {"category": frame[dimension_name].astype("string"), "value": converted[numeric_name]}
        ).dropna()
        result = (
            working.groupby("category", as_index=False, dropna=False)
            .agg(value_mean=("value", "mean"), row_count=("value", "size"))
            .sort_values("value_mean", ascending=False)
            .head(30)
        )
        result_schema = [
            {"name": "category", "type": "text", "role": "dimension"},
            {"name": "value_mean", "type": "number", "role": "metric", "unit": None},
            {"name": "row_count", "type": "integer", "role": "weight", "unit": "rows"},
        ]
        top = result.iloc[0]
        finding_text = f"{top['category']} has the highest mean {numeric_name}: {top['value_mean']:.4g}."
        evidence = [
            {"column": "category", "value": str(top["category"])},
            {"column": "value_mean", "value": float(top["value_mean"])},
        ]
    else:
        name = str(frame.columns[0])
        result = frame[name].astype("string").value_counts(dropna=False).head(30).rename_axis(
            "category"
        ).reset_index(name="row_count")
        result_schema = [
            {"name": "category", "type": "text", "role": "dimension"},
            {"name": "row_count", "type": "integer", "role": "metric", "unit": "rows"},
        ]
        top = result.iloc[0]
        finding_text = f"{top['category']} is the most frequent value with {int(top['row_count'])} rows."
        evidence = [
            {"column": "category", "value": str(top["category"])},
            {"column": "row_count", "value": int(top["row_count"])},
        ]
    request = Path(context["request"]["path"]).read_text(encoding="utf-8")
    payload = {
        "schema_version": "chartpilot.adaptive-analysis/v1",
        "task_id": context["task_id"],
        "question": request.strip(),
        "assumptions": ["The unchanged starter template selected fields heuristically."],
        "result_schema": result_schema,
        "findings": [{"id": "finding-1", "text": finding_text, "evidence": evidence}],
        "chart_intent": {
            "report_type": "comparison",
            "title": request.strip()[:160],
            "detail_grain": "one result row per category",
            "visual_grain": "one mark per category",
            "panel_purposes": ["compare the selected metric across categories"],
            "encodings": {
                "x": "category",
                "y": "value_mean" if "value_mean" in result.columns else "row_count",
                "weight": "row_count",
            },
            "density_strategy": "show the bounded category result directly",
        },
        # Add plain filenames here when this stage writes supporting CSV/JSON/Markdown/text files.
        "artifacts": [],
    }
    return result, payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args(argv)
    context = load_context(Path(args.context))
    # output_dir is write-only for this attempt. Read inputs through context.paths/source.
    output_dir = Path(context["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    result, payload = analyze(read_source(context), context)
    result.to_csv(output_dir / "result.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    (output_dir / "adaptive_analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"ok": True, "result_rows": len(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
