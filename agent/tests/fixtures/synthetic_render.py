from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


COLORS = ["#79B6D2", "#B7D43A", "#F2B134", "#D95D39"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    context = json.loads(Path(parser.parse_args().context).read_text(encoding="utf-8"))
    result = pd.read_csv(context["paths"]["result_csv"], encoding="utf-8-sig")
    analysis = json.loads(Path(context["paths"]["analysis_result"]).read_text(encoding="utf-8"))
    intent = analysis["chart_intent"]
    output = Path(context["paths"]["output_dir"])
    modes = sorted(result["primary_mode"].unique())
    risk_order = intent["risk_order"]
    summary = result.groupby(["primary_mode", "risk"], as_index=False).agg(
        entity_count=("device_key", "nunique"),
        aggregate_metric=("mean_consumption", "mean"),
        peer_baseline=("peer_baseline", "first"),
    )
    counts = (
        summary.pivot_table(
            index="primary_mode", columns="risk", values="entity_count", aggfunc="sum", fill_value=0
        ).reindex(
            index=modes, columns=risk_order, fill_value=0
        )
    )
    figure, (top, bottom) = plt.subplots(2, 1, figsize=(16, 10), constrained_layout=True)
    base = pd.Series(0, index=modes, dtype=float)
    for risk, color in zip(risk_order, COLORS):
        top.bar(modes, counts[risk], bottom=base, label=risk, color=color)
        base += counts[risk]
    top.set_title("Risk distribution by selected operating mode")
    top.set_ylabel("Device count")
    top.legend(ncol=4)
    top.grid(axis="y", color="#D9DEE2")

    baseline = result.groupby("primary_mode")["peer_baseline"].first().reindex(modes)
    for threshold in intent["thresholds"]:
        bottom.plot(
            modes,
            baseline * float(threshold["multiplier"]),
            "--",
            label=str(threshold["label"]),
            color=str(threshold["color"]),
        )
    for risk, color in zip(risk_order, COLORS):
        subset = summary[summary["risk"] == risk]
        bottom.scatter(
            subset["primary_mode"],
            subset["aggregate_metric"],
            s=45 + subset["entity_count"] * 90,
            color=color,
            edgecolor="#222222",
            alpha=0.85,
            label=risk,
        )
    bottom.set_title("Consumption vs peer baseline")
    bottom.set_xlabel("Selected operating mode")
    bottom.set_ylabel("Mean consumption")
    bottom.grid(color="#D9DEE2")
    bottom.legend(ncol=4)
    figure.savefig(output / "chart.png", dpi=150, facecolor="white")
    plt.close(figure)

    summary = "\n\n".join(finding["text"] for finding in analysis["findings"])
    (output / "summary.md").write_text(summary + "\n", encoding="utf-8")
    payload = {
        "schema_version": "chartpilot.adaptive-chart/v1",
        "task_id": context["task_id"],
        "report_type": "multi-panel-risk-report",
        "visual_archetype": intent["archetype"],
        "panel_ids": [item["id"] for item in intent["panels"]],
        "finding_ids": [finding["id"] for finding in analysis["findings"]],
        "presentation_notes": [
            "Top panel shows population by risk.",
            "Bottom panel shows severity against peer thresholds.",
        ],
    }
    (output / "adaptive_chart.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
