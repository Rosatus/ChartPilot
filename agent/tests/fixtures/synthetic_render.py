from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


RISK_ORDER = ["baseline_or_below", "within_20", "above_20", "above_40"]
COLORS = ["#79B6D2", "#B7D43A", "#F2B134", "#D95D39"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    context = json.loads(Path(parser.parse_args().context).read_text(encoding="utf-8"))
    result = pd.read_csv(context["paths"]["result_csv"], encoding="utf-8-sig")
    analysis = json.loads(Path(context["paths"]["analysis_result"]).read_text(encoding="utf-8"))
    output = Path(context["paths"]["output_dir"])
    modes = sorted(result["primary_mode"].unique())
    counts = (
        result.groupby(["primary_mode", "risk"]).size().unstack(fill_value=0).reindex(
            index=modes, columns=RISK_ORDER, fill_value=0
        )
    )
    figure, (top, bottom) = plt.subplots(2, 1, figsize=(16, 10), constrained_layout=True)
    base = pd.Series(0, index=modes, dtype=float)
    for risk, color in zip(RISK_ORDER, COLORS):
        top.bar(modes, counts[risk], bottom=base, label=risk, color=color)
        base += counts[risk]
    top.set_title("Risk distribution by selected operating mode")
    top.set_ylabel("Device count")
    top.legend(ncol=4)
    top.grid(axis="y", color="#D9DEE2")

    baseline = result.groupby("primary_mode")["peer_baseline"].first().reindex(modes)
    bottom.plot(modes, baseline, "--", label="peer baseline", color="#2676B8")
    bottom.plot(modes, baseline * 1.2, "--", label="+20%", color="#E5A823")
    bottom.plot(modes, baseline * 1.4, "--", label="+40%", color="#D95D39")
    for risk, color in zip(RISK_ORDER, COLORS):
        subset = result[result["risk"] == risk]
        bottom.scatter(
            subset["primary_mode"],
            subset["mean_consumption"],
            s=subset["sample_count"] * 1.2,
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
