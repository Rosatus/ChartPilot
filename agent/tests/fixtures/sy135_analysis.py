from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    context = json.loads(Path(parser.parse_args().context).read_text(encoding="utf-8"))
    source = pd.read_csv(context["source"]["path"], encoding="utf-8-sig")
    source["_weighted_fuel"] = source["avg_fuel"] * source["gear_record_count"]
    grouped = source.groupby(["login_id", "gear"], as_index=False).agg(
        sample_count=("gear_record_count", "sum"),
        weighted_fuel=("_weighted_fuel", "sum"),
    )
    grouped["mean_fuel"] = grouped["weighted_fuel"] / grouped["sample_count"]
    selected = (
        grouped.sort_values(
            ["login_id", "sample_count", "mean_fuel", "gear"],
            ascending=[True, False, False, True],
            kind="mergesort",
        )
        .drop_duplicates("login_id")
        .copy()
    )
    selected["gear_baseline"] = selected.groupby("gear")["mean_fuel"].transform("mean")
    selected["relative_ratio"] = selected["mean_fuel"] / selected["gear_baseline"]
    selected["above_baseline"] = selected["relative_ratio"] - 1

    def risk(value: float) -> str:
        if value <= 1.0:
            return "低风险"
        if value <= 1.25:
            return "中低风险"
        if value <= 1.50:
            return "中高风险"
        if value <= 1.75:
            return "高风险"
        return "极致高风险"

    selected["risk"] = selected["relative_ratio"].map(risk)
    result = selected[
        [
            "login_id",
            "gear",
            "sample_count",
            "mean_fuel",
            "gear_baseline",
            "relative_ratio",
            "above_baseline",
            "risk",
        ]
    ].sort_values(["gear", "relative_ratio"], ascending=[True, False])
    gear_counts = result.groupby("gear").size().sort_index()
    above_25 = int((result["relative_ratio"] > 1.25).sum())
    above_50 = int((result["relative_ratio"] > 1.50).sum())
    output = Path(context["paths"]["output_dir"])
    result.to_csv(output / "result.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    gear_baseline = result.groupby("gear", as_index=False).agg(
        machine_count=("login_id", "size"),
        mean_fuel=("mean_fuel", "mean"),
        gear_baseline=("gear_baseline", "first"),
    )
    gear_baseline.to_csv(
        output / "gear_baseline.csv", index=False, encoding="utf-8-sig", lineterminator="\n"
    )
    result[result["relative_ratio"] > 1.25].to_csv(
        output / "above_25_percent.csv", index=False, encoding="utf-8-sig", lineterminator="\n"
    )
    result[result["relative_ratio"] > 1.50].to_csv(
        output / "above_50_percent.csv", index=False, encoding="utf-8-sig", lineterminator="\n"
    )
    payload = {
        "schema_version": "chartpilot.adaptive-analysis/v1",
        "task_id": context["task_id"],
        "question": Path(context["request"]["path"]).read_text(encoding="utf-8").strip(),
        "assumptions": [
            "主档位按样本数最大选择；并列时先取平均油耗高者，再取档位小者。",
            "同主档位基准采用各机号主档位平均油耗的算术平均值。",
        ],
        "result_schema": [
            {"name": "login_id", "type": "text", "role": "identifier"},
            {"name": "gear", "type": "integer", "role": "dimension"},
            {"name": "sample_count", "type": "integer", "role": "weight"},
            {"name": "mean_fuel", "type": "number", "role": "metric"},
            {"name": "gear_baseline", "type": "number", "role": "baseline"},
            {"name": "relative_ratio", "type": "number", "role": "ratio"},
            {"name": "above_baseline", "type": "number", "role": "ratio"},
            {"name": "risk", "type": "text", "role": "series"},
        ],
        "findings": [
            {
                "id": "machine-total",
                "text": f"共识别 {len(result):,} 台设备的主档位。",
                "evidence": [{"metric": "machine_count", "value": int(len(result))}],
            },
            {
                "id": "gear-counts",
                "text": "各主档位设备数为 " + ", ".join(
                    f"{int(gear)}档 {int(count):,} 台" for gear, count in gear_counts.items()
                ) + "。",
                "evidence": [
                    {"gear": int(gear), "machine_count": int(count)}
                    for gear, count in gear_counts.items()
                ],
            },
            {
                "id": "above-25",
                "text": f"{above_25} 台设备高于同主档位平均油耗 25%。",
                "evidence": [{"column": "relative_ratio", "operator": ">", "value": 1.25}],
            },
            {
                "id": "above-50",
                "text": f"{above_50} 台设备高于同主档位平均油耗 50%。",
                "evidence": [{"column": "relative_ratio", "operator": ">", "value": 1.50}],
            },
        ],
        "chart_intent": {
            "report_type": "multi-panel-risk-report",
            "title": "SY135I4 主档位油耗风险分析",
            "thresholds": [1.25, 1.50, 1.75],
            "detail_grain": "one row per machine",
            "visual_grain": "one mark per gear and risk band",
            "panel_purposes": [
                "compare population composition by gear and risk band",
                "compare aggregated fuel severity against gear thresholds",
            ],
            "encodings": {
                "x": "gear",
                "y": "mean_fuel",
                "area": "machine_count",
                "color": "risk",
            },
            "density_strategy": "aggregate machine detail by gear and risk band for rendering",
        },
        "artifacts": [
            "gear_baseline.csv",
            "above_25_percent.csv",
            "above_50_percent.csv",
        ],
    }
    (output / "adaptive_analysis.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
