from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_checked(arguments: Sequence[str], label: str) -> dict[str, Any]:
    completed = subprocess.run(
        list(arguments),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{label} failed with exit code {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    if not completed.stdout.strip():
        return {}
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} did not return a JSON object.")
    return value


def build_plan(profile: dict[str, Any]) -> dict[str, Any]:
    columns = {item["source_name"]: item["id"] for item in profile["columns"]}
    return {
        "schema_version": "chartpilot.analysis-plan/v1",
        "task_id": profile["task_id"],
        "status": "ready",
        "source_sha256": profile["source"]["sha256"],
        "question": "比较各地区销售额",
        "assumptions": [],
        "cleaning": [
            {
                "operation": "cast",
                "column": columns["销售额"],
                "to": "number",
                "on_error": "raise",
                "reason": "销售额求和需要数值类型",
            }
        ],
        "filters": [],
        "time_bucket": None,
        "group_by": [{"column": columns["地区"], "output": "region"}],
        "metrics": [
            {
                "column": columns["销售额"],
                "aggregation": "sum",
                "output": "sales",
                "unit": "元",
            }
        ],
        "post_calculations": [],
        "top_n": None,
        "sort": [{"column": "sales", "direction": "desc", "nulls": "last"}],
        "chart_intent": {
            "analysis_kind": "comparison",
            "chart_type": "bar",
            "x": "region",
            "y": "sales",
            "series": None,
            "title": "各地区销售额",
            "unit": "元",
            "time_range": None,
            "source_note": "ChartPilot 运行时冒烟测试",
            "plot_ready": True,
            "sort": "y-desc",
        },
    }


def execute(project_root: Path, workspace_root: Path) -> dict[str, Any]:
    profiler = project_root / "skills/chartpilot-profile-csv/scripts/profile_csv.py"
    analyzer = project_root / "skills/chartpilot-analyze-data/scripts/run_analysis.py"
    renderer = project_root / "skills/chartpilot-render-chart/scripts/render_chart.py"
    for path in (profiler, analyzer, renderer):
        if not path.is_file():
            raise RuntimeError(f"Required ChartPilot script not found: {path}")

    workspace_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="chartpilot-smoke-中文-", dir=workspace_root
    ) as temporary:
        task_dir = Path(temporary)
        source = task_dir / "销售 数据.csv"
        source.write_text(
            "日期,地区,销售额,订单号\n"
            "2026-01-01,华东,100,A\n"
            "2026-01-02,华南,80,B\n"
            "2026-01-03,华东,50,C\n",
            encoding="utf-8-sig",
            newline="",
        )
        original_hash = sha256_file(source)
        run_checked(
            [
                sys.executable,
                str(profiler),
                str(source),
                "--task-id",
                "runtime-smoke",
                "--output-dir",
                str(task_dir),
                "--allowed-read-root",
                str(task_dir),
                "--allowed-write-root",
                str(task_dir),
            ],
            "CSV profiler",
        )
        profile_path = task_dir / "input_profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        plan_path = task_dir / "analysis_plan.json"
        plan_path.write_text(
            json.dumps(build_plan(profile), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        run_checked(
            [
                sys.executable,
                str(analyzer),
                "--profile",
                str(profile_path),
                "--plan",
                str(plan_path),
                "--output-dir",
                str(task_dir),
                "--allowed-read-root",
                str(task_dir),
                "--allowed-write-root",
                str(task_dir),
            ],
            "data analysis",
        )
        analysis_result = task_dir / "analysis_result.json"
        run_checked(
            [
                sys.executable,
                str(renderer),
                "--analysis-result",
                str(analysis_result),
                "--output-dir",
                str(task_dir),
            ],
            "chart renderer",
        )
        expected = [
            "input_profile.json",
            "analysis_plan.json",
            "result.csv",
            "analysis_result.json",
            "chart.png",
            "chart_result.json",
            "summary.md",
        ]
        missing = [name for name in expected if not (task_dir / name).is_file()]
        if missing:
            raise RuntimeError(f"Smoke test artifacts missing: {', '.join(missing)}")
        if (task_dir / "chart.png").read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("Smoke test chart is not a PNG file.")
        if sha256_file(source) != original_hash:
            raise RuntimeError("Smoke test modified the source CSV.")
        with (task_dir / "result.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != 2:
            raise RuntimeError("Smoke test analysis returned an unexpected row count.")
        return {
            "ok": True,
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "result_rows": len(rows),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--workspace-root", required=True)
    args = parser.parse_args()
    try:
        result = execute(Path(args.project_root).resolve(), Path(args.workspace_root).resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "RUNTIME_SMOKE_TEST_FAILED",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                    },
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
