from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager


RISK_ORDER = ["低风险", "中低风险", "中高风险", "高风险", "极致高风险"]
COLORS = ["#7FC4E2", "#CDE52B", "#FFBC12", "#FF6232", "#9C2AB7"]


def font() -> font_manager.FontProperties:
    for path in (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/simhei.ttf")):
        if path.is_file():
            return font_manager.FontProperties(fname=str(path))
    return font_manager.FontProperties()


def apply_font(axis: plt.Axes, selected: font_manager.FontProperties) -> None:
    axis.title.set_fontproperties(selected)
    axis.xaxis.label.set_fontproperties(selected)
    axis.yaxis.label.set_fontproperties(selected)
    for label in axis.get_xticklabels() + axis.get_yticklabels():
        label.set_fontproperties(selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    context = json.loads(Path(parser.parse_args().context).read_text(encoding="utf-8"))
    result = pd.read_csv(context["paths"]["result_csv"], encoding="utf-8-sig")
    analysis = json.loads(Path(context["paths"]["analysis_result"]).read_text(encoding="utf-8"))
    output = Path(context["paths"]["output_dir"])
    gears = sorted(result["gear"].unique())
    selected_font = font()

    figure = plt.figure(figsize=(18, 12), constrained_layout=True)
    grid = figure.add_gridspec(2, 2, width_ratios=[4.7, 1.25], height_ratios=[1, 1])
    top = figure.add_subplot(grid[0, 0])
    bottom = figure.add_subplot(grid[1, 0])
    note = figure.add_subplot(grid[:, 1])

    counts = result.groupby(["gear", "risk"]).size().unstack(fill_value=0).reindex(
        index=gears, columns=RISK_ORDER, fill_value=0
    )
    base = pd.Series(0, index=gears, dtype=float)
    for risk, color in zip(RISK_ORDER, COLORS):
        values = counts[risk]
        bars = top.bar(gears, values, bottom=base, label=risk, color=color, width=0.65)
        for bar, value, offset in zip(bars, values, base):
            if value:
                top.text(
                    bar.get_x() + bar.get_width() / 2,
                    offset + value / 2,
                    f"{int(value)}",
                    ha="center",
                    va="center",
                    fontsize=8,
                )
        base += values
    for gear, total in base.items():
        top.text(gear, total + max(base) * 0.015, f"{int(total)}", ha="center", fontsize=9)
    top.set_title("SY135I4 - 各主档位风险等级分布（数量）", pad=18)
    top.set_xlabel("主档位")
    top.set_ylabel("机号数量")
    top.set_xticks(gears)
    top.grid(axis="y", color="#DDE2E5", linewidth=0.8)
    top.legend(prop=selected_font, ncol=3, loc="upper right", bbox_to_anchor=(0.99, 0.91))

    baselines = result.groupby("gear")["gear_baseline"].first().reindex(gears)
    bottom.fill_between(gears, 0, baselines, color="#E8F4FA", alpha=0.8)
    bottom.fill_between(gears, baselines, baselines * 1.25, color="#F6F9DB", alpha=0.7)
    bottom.fill_between(gears, baselines * 1.25, baselines * 1.50, color="#FFF0D9", alpha=0.7)
    bottom.fill_between(gears, baselines * 1.50, baselines * 2.0, color="#F6E8F8", alpha=0.6)
    for multiplier, label, color in (
        (1.0, "基准线", "#2676B8"),
        (1.25, "+25%线", "#E5A823"),
        (1.50, "+50%线", "#F07A24"),
        (1.75, "+75%线", "#D4483B"),
    ):
        bottom.plot(gears, baselines * multiplier, "--", label=label, color=color, linewidth=1.2)
    summary = result.groupby(["gear", "risk"], as_index=False).agg(
        mean_fuel=("mean_fuel", "mean"), machine_count=("login_id", "size")
    )
    for risk, color in zip(RISK_ORDER, COLORS):
        subset = summary[summary["risk"] == risk]
        bottom.scatter(
            subset["gear"],
            subset["mean_fuel"],
            s=30 + subset["machine_count"] * 0.8,
            color=color,
            edgecolor="#202020",
            linewidth=0.7,
            alpha=0.9,
        )
        for row in subset.itertuples():
            bottom.annotate(
                f"{row.mean_fuel:.1f}\n({row.machine_count})",
                (row.gear, row.mean_fuel),
                ha="center",
                va="center",
                fontsize=7,
            )
    bottom.set_title("SY135I4 - 平均油耗趋势与风险分布")
    bottom.set_xlabel("主档位")
    bottom.set_ylabel("平均油耗")
    bottom.set_xticks(gears)
    bottom.set_ylim(bottom=0)
    bottom.grid(color="#DDE2E5", linewidth=0.8)
    bottom.legend(prop=selected_font, ncol=4, loc="upper left")

    note.axis("off")
    finding_text = "\n\n".join(
        textwrap.fill(finding["text"], width=25) for finding in analysis["findings"]
    )
    note_text = (
        "报告统计说明\n\n"
        "每台机号取样本数最多档位\n"
        "作为主档位。\n\n"
        "上图：风险等级设备数量。\n\n"
        "下图：气泡标注平均油耗\n"
        "与机号数，虚线为同主档位\n"
        "平均值及 25%/50%/75% 阈值。\n\n"
        + finding_text
    )
    note.text(0.04, 0.98, note_text, va="top", fontproperties=selected_font, fontsize=10, linespacing=1.5)
    apply_font(top, selected_font)
    apply_font(bottom, selected_font)
    figure.savefig(output / "chart.png", dpi=150, facecolor="white")
    plt.close(figure)

    summary_text = "\n\n".join(finding["text"] for finding in analysis["findings"])
    (output / "summary.md").write_text(summary_text + "\n", encoding="utf-8")
    payload = {
        "schema_version": "chartpilot.adaptive-chart/v1",
        "task_id": context["task_id"],
        "report_type": "multi-panel-risk-report",
        "finding_ids": [finding["id"] for finding in analysis["findings"]],
        "presentation_notes": [
            "上半区展示各主档位风险等级数量。",
            "下半区展示油耗、设备数和同档位阈值。",
            "右侧说明区域解释统计口径和关键发现。",
        ],
    }
    (output / "adaptive_chart.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
