from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    context = json.loads(Path(parser.parse_args().context).read_text(encoding="utf-8"))
    frame = pd.read_csv(context["source"]["path"], encoding="utf-8-sig")
    selected = (
        frame.sort_values(
            ["device_key", "sample_count", "mean_consumption", "operating_mode"],
            ascending=[True, False, False, True],
            kind="mergesort",
        )
        .drop_duplicates("device_key")
        .rename(columns={"operating_mode": "primary_mode"})
        .copy()
    )
    selected["peer_baseline"] = selected.groupby("primary_mode")["mean_consumption"].transform(
        "mean"
    )
    selected["relative_ratio"] = selected["mean_consumption"] / selected["peer_baseline"]
    selected["above_peer"] = selected["relative_ratio"] - 1

    def risk(value: float) -> str:
        if value <= 1.0:
            return "baseline_or_below"
        if value <= 1.2:
            return "within_20"
        if value <= 1.4:
            return "above_20"
        return "above_40"

    selected["risk"] = selected["relative_ratio"].map(risk)
    result = selected[
        [
            "device_key",
            "primary_mode",
            "sample_count",
            "mean_consumption",
            "peer_baseline",
            "relative_ratio",
            "above_peer",
            "risk",
        ]
    ].sort_values(["primary_mode", "relative_ratio"], ascending=[True, False])
    above_20 = int((result["relative_ratio"] > 1.2).sum())
    above_40 = int((result["relative_ratio"] > 1.4).sum())
    output = Path(context["paths"]["output_dir"])
    result.to_csv(output / "result.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    payload = {
        "schema_version": "chartpilot.adaptive-analysis/v1",
        "task_id": context["task_id"],
        "question": Path(context["request"]["path"]).read_text(encoding="utf-8").strip(),
        "assumptions": ["Peer baseline is the arithmetic mean within each selected mode."],
        "result_schema": [
            {"name": "device_key", "type": "text", "role": "identifier"},
            {"name": "primary_mode", "type": "integer", "role": "dimension"},
            {"name": "sample_count", "type": "integer", "role": "weight"},
            {"name": "mean_consumption", "type": "number", "role": "metric"},
            {"name": "peer_baseline", "type": "number", "role": "baseline"},
            {"name": "relative_ratio", "type": "number", "role": "ratio"},
            {"name": "above_peer", "type": "number", "role": "ratio"},
            {"name": "risk", "type": "text", "role": "series"},
        ],
        "findings": [
            {
                "id": "above-20",
                "text": f"{above_20} devices are more than 20% above their selected-mode peers.",
                "evidence": [{"column": "relative_ratio", "operator": ">", "value": 1.2}],
            },
            {
                "id": "above-40",
                "text": f"{above_40} device is more than 40% above its selected-mode peers.",
                "evidence": [{"column": "relative_ratio", "operator": ">", "value": 1.4}],
            },
        ],
        "chart_intent": {
            "report_type": "multi-panel-risk-report",
            "title": "Operating-mode consumption risk",
            "thresholds": [1.2, 1.4],
        },
    }
    (output / "adaptive_analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
