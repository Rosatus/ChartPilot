from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager


def load_context(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "chartpilot.adaptive-task/v1":
        raise ValueError("Unsupported adaptive task context.")
    return value


def configure_fonts() -> font_manager.FontProperties:
    """Configure one discovered font globally so every Matplotlib text element inherits it."""
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/msyhbd.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    path = next((item for item in candidates if item.is_file()), None)
    if path:
        font_manager.fontManager.addfont(str(path))
        font = font_manager.FontProperties(fname=str(path))
        family = font.get_name()
        plt.rcParams["font.family"] = [family]
        plt.rcParams["font.sans-serif"] = [family]
    else:
        font = font_manager.FontProperties()
    plt.rcParams["axes.unicode_minus"] = False
    return font


def render(
    frame: pd.DataFrame,
    analysis: dict[str, Any],
    output_dir: Path,
    font: font_manager.FontProperties,
) -> dict[str, Any]:
    """EDIT: implement analysis.chart_intent; keep font setup and its declared visual story."""
    intent = analysis["chart_intent"]
    numeric = [name for name in frame.columns if pd.api.types.is_numeric_dtype(frame[name])]
    if not numeric:
        raise ValueError("The starter renderer needs at least one numeric result column.")
    y_name = numeric[0]
    x_name = next((name for name in frame.columns if name != y_name), frame.columns[0])
    plot = frame.head(30)
    figure, axis = plt.subplots(figsize=(16, 9), constrained_layout=True)
    axis.bar(plot[x_name].astype(str), plot[y_name], color="#2F6B7C")
    axis.set_title(str(intent.get("title", "ChartPilot report")), fontproperties=font)
    axis.set_xlabel(str(x_name), fontproperties=font)
    axis.set_ylabel(str(y_name), fontproperties=font)
    axis.grid(axis="y", color="#D9DEE2", linewidth=0.8)
    axis.tick_params(axis="x", rotation=35)
    for label in axis.get_xticklabels() + axis.get_yticklabels():
        label.set_fontproperties(font)
    figure.savefig(output_dir / "chart.png", dpi=150, facecolor="white")
    plt.close(figure)
    return {
        "report_type": "adaptive-comparison",
        "archetype": str(intent.get("archetype", "free-form")),
        "panel_ids": [str(item.get("id")) for item in intent.get("panels", []) if item.get("id")],
        "presentation_notes": ["The unchanged starter template rendered the first numeric metric."],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    args = parser.parse_args(argv)
    context = load_context(Path(args.context))
    # output_dir is write-only. Always read upstream data from the named context paths below.
    output_dir = Path(context["paths"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis = json.loads(Path(context["paths"]["analysis_result"]).read_text(encoding="utf-8"))
    frame = pd.read_csv(context["paths"]["result_csv"], encoding="utf-8-sig")
    metadata = render(frame, analysis, output_dir, configure_fonts())
    findings = analysis.get("findings", [])
    summary = "\n\n".join(str(item.get("text", "")) for item in findings if item.get("text"))
    (output_dir / "summary.md").write_text(summary + "\n", encoding="utf-8", newline="\n")
    payload = {
        "schema_version": "chartpilot.adaptive-chart/v1",
        "task_id": context["task_id"],
        "report_type": metadata["report_type"],
        "visual_archetype": metadata["archetype"],
        "panel_ids": metadata["panel_ids"],
        "finding_ids": [str(item["id"]) for item in findings],
        "presentation_notes": metadata.get("presentation_notes", []),
    }
    (output_dir / "adaptive_chart.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"ok": True, "chart": "chart.png"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
