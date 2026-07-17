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


def read_csv(context: dict[str, Any]) -> pd.DataFrame:
    source = context["source"]
    options: dict[str, Any] = {"low_memory": False}
    if source.get("encoding_hint"):
        options["encoding"] = source["encoding_hint"]
    if source.get("delimiter_hint"):
        options["sep"] = source["delimiter_hint"]
    return pd.read_csv(source["path"], **options)


def inspect(frame: pd.DataFrame, context: dict[str, Any]) -> dict[str, Any]:
    """EDIT THIS FUNCTION to add domain-specific inspection or preparation."""
    columns: list[dict[str, Any]] = []
    roles: dict[str, list[str]] = {"identifier": [], "numeric": [], "categorical": []}
    row_count = len(frame)
    for name in frame.columns:
        series = frame[name]
        non_null = series.dropna()
        unique = int(non_null.nunique(dropna=True))
        numeric = pd.to_numeric(non_null, errors="coerce")
        numeric_ratio = float(numeric.notna().mean()) if len(non_null) else 0.0
        unique_ratio = unique / len(non_null) if len(non_null) else 0.0
        if numeric_ratio >= 0.9:
            roles["numeric"].append(str(name))
        if unique_ratio >= 0.9 and unique > 1:
            roles["identifier"].append(str(name))
        if unique <= 50 or unique_ratio <= 0.1:
            roles["categorical"].append(str(name))
        samples = [str(value)[:160] for value in non_null.head(5).tolist()]
        columns.append(
            {
                "name": str(name),
                "dtype": str(series.dtype),
                "missing": int(series.isna().sum()),
                "unique": unique,
                "numeric_ratio": round(numeric_ratio, 6),
                "samples": samples,
            }
        )
    return {
        "schema_version": "chartpilot.inspection/v1",
        "task_id": context["task_id"],
        "row_count": row_count,
        "column_count": len(frame.columns),
        "columns": columns,
        "quality": {"duplicate_rows": int(frame.duplicated().sum())},
        "semantic_roles": roles,
        "notes": [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args(argv)
    context = load_context(Path(args.context))
    output_dir = Path(context["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = inspect(read_csv(context), context)
    (output_dir / "inspection.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"ok": True, "rows": payload["row_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
