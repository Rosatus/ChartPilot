from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from PIL import Image, ImageStat


def load_bridge(project_root: Path) -> Any:
    path = project_root / "agent/mcp/chartpilot_mcp.py"
    spec = importlib.util.spec_from_file_location("chartpilot_mcp_sy135", path)
    if not spec or not spec.loader:
        raise RuntimeError("Could not load ChartPilot MCP bridge.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute(project_root: Path, case_root: Path, keep_output: bool) -> dict[str, Any]:
    input_root = case_root / "输入原csv数据"
    request = input_root / "原prompt.md"
    csv_files = list(input_root.glob("*.csv"))
    if not request.is_file() or len(csv_files) != 1:
        raise RuntimeError("The SY135 case must contain one prompt and one CSV input.")
    source = csv_files[0]
    workspace = project_root / "workspace/sy135-validation"
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "CHARTPILOT_ROOT": str(project_root),
            "CHARTPILOT_WORKSPACE_ROOT": str(workspace),
            "CHARTPILOT_ALLOWED_READ_ROOTS": os.pathsep.join([str(case_root), str(workspace)]),
        }
    )
    bridge = load_bridge(project_root)
    fixtures = project_root / "agent/tests/fixtures"
    expected = json.loads((fixtures / "sy135-expected.json").read_text(encoding="utf-8"))
    task_id = f"sy135-{uuid.uuid4().hex[:8]}"
    task_dir = workspace / "tasks" / task_id
    success = False
    try:
        bridge.prepare_adaptive_task(str(source), request_path=str(request), task_id=task_id)
        bridge.run_task_python(
            task_id,
            "inspect",
            (project_root / "skills/chartpilot-run-python/assets/templates/inspect_csv.py").read_text(
                encoding="utf-8"
            ),
        )
        bridge.run_task_python(
            task_id, "analysis", (fixtures / "sy135_analysis.py").read_text(encoding="utf-8")
        )
        bridge.run_task_python(
            task_id, "render", (fixtures / "sy135_render.py").read_text(encoding="utf-8")
        )
        inspection = json.loads((task_dir / "inspection.json").read_text(encoding="utf-8"))
        analysis_manifest = json.loads(
            (task_dir / "analysis_result.json").read_text(encoding="utf-8")
        )
        result = pd.read_csv(task_dir / "result.csv", encoding="utf-8-sig")
        counts = result.groupby("gear").size().sort_index().tolist()
        checks = {
            "source_rows": int(inspection["row_count"]) == expected["source_rows"],
            "machines": len(result) == expected["machines"],
            "gears": [int(value) for value in sorted(result["gear"].unique())] == expected["gears"],
            "machines_by_gear": [int(value) for value in counts] == expected["machines_by_gear"],
            "above_25": int((result["relative_ratio"] > 1.25).sum()) == expected["above_25"],
            "above_50": int((result["relative_ratio"] > 1.50).sum()) == expected["above_50"],
            "auxiliary_artifacts": {
                item["path"] for item in analysis_manifest["artifacts"]["auxiliary"]
            }
            == {"gear_baseline.csv", "above_25_percent.csv", "above_50_percent.csv"},
            "auxiliary_files_exist": all(
                (task_dir / name).is_file()
                for name in (
                    "gear_baseline.csv",
                    "above_25_percent.csv",
                    "above_50_percent.csv",
                )
            ),
        }
        with Image.open(task_dir / "chart.png") as image:
            width, height = image.size
            top = image.crop((0, 0, width * 3 // 4, height // 2)).convert("L")
            bottom = image.crop((0, height // 2, width * 3 // 4, height)).convert("L")
            checks["two_populated_panels"] = (
                ImageStat.Stat(top).stddev[0] > 5.0 and ImageStat.Stat(bottom).stddev[0] > 5.0
            )
            checks["report_dimensions"] = width >= 2400 and height >= 1500
        if not all(checks.values()):
            failed = [name for name, passed in checks.items() if not passed]
            raise RuntimeError(f"SY135 adaptive checks failed: {', '.join(failed)}")
        success = True
        return {
            "ok": True,
            "task_id": task_id,
            "task_dir": str(task_dir),
            "chart": str(task_dir / "chart.png"),
            "checks": checks,
        }
    finally:
        if not keep_output or not success:
            shutil.rmtree(task_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--case-root", required=True)
    parser.add_argument("--keep-output", action="store_true")
    args = parser.parse_args()
    try:
        result = execute(
            Path(args.project_root).resolve(), Path(args.case_root).resolve(strict=True), args.keep_output
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {"message": str(exc), "exception_type": type(exc).__name__},
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
