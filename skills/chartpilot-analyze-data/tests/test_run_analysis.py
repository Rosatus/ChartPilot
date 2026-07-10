from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER = SKILL_DIR / "scripts" / "run_analysis.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runner():
    spec = importlib.util.spec_from_file_location("chartpilot_run_analysis", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load analysis runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunAnalysisTests(unittest.TestCase):
    def test_grouped_sum_preserves_all_missing_group(self) -> None:
        with tempfile.TemporaryDirectory(prefix="chartpilot-analysis-") as temporary:
            root = Path(temporary)
            source = root / "中文 销售.csv"
            source.write_text(
                "日期,地区,销售额,订单号\n"
                "2026-01-01,华东,10,A\n"
                "2026-01-15,华东,,B\n"
                "2026-02-01,华东,0,C\n"
                "2026-03-01,华东,5,D\n"
                "2026-01-01,华南,,E\n",
                encoding="utf-8-sig",
                newline="",
            )
            source_hash = sha256(source)
            profile = {
                "schema_version": "chartpilot.input-profile/v1",
                "task_id": "T-group-sum",
                "stage": "profile",
                "status": "success",
                "source": {
                    "path": str(source.resolve()),
                    "file_name": source.name,
                    "size_bytes": source.stat().st_size,
                    "sha256": source_hash,
                    "encoding": "utf-8-sig",
                    "delimiter": ",",
                },
                "format": {"quotechar": '"'},
                "shape": {"row_count": 5, "column_count": 4},
                "columns": [
                    {"id": "c0001", "index": 0, "source_name": "日期", "inferred_type": "date"},
                    {"id": "c0002", "index": 1, "source_name": "地区", "inferred_type": "string"},
                    {"id": "c0003", "index": 2, "source_name": "销售额", "inferred_type": "number"},
                    {"id": "c0004", "index": 3, "source_name": "订单号", "inferred_type": "string"},
                ],
            }
            profile_path = root / "input_profile.json"
            profile_path.write_text(
                json.dumps(profile, ensure_ascii=False), encoding="utf-8"
            )
            plan = {
                "schema_version": "chartpilot.analysis-plan/v1",
                "task_id": "T-group-sum",
                "status": "ready",
                "source_sha256": source_hash,
                "question": "展示各地区月度销售额趋势",
                "assumptions": [],
                "cleaning": [
                    {
                        "operation": "cast",
                        "column": "c0001",
                        "to": "date",
                        "format": "%Y-%m-%d",
                        "on_error": "raise",
                        "reason": "按月分组需要日期",
                    },
                    {
                        "operation": "cast",
                        "column": "c0003",
                        "to": "number",
                        "on_error": "coerce",
                        "reason": "销售额求和需要数值",
                    },
                ],
                "filters": [],
                "time_bucket": {
                    "column": "c0001",
                    "frequency": "month",
                    "output": "month",
                },
                "group_by": [
                    {"column": "month", "output": "month"},
                    {"column": "c0002", "output": "region"},
                ],
                "metrics": [
                    {
                        "column": "c0003",
                        "aggregation": "sum",
                        "output": "sales",
                        "unit": "元",
                    },
                    {
                        "column": "*",
                        "aggregation": "count",
                        "output": "row_count",
                        "unit": "行",
                    },
                ],
                "post_calculations": [
                    {
                        "operation": "share",
                        "column": "sales",
                        "output": "sales_share",
                        "partition_by": [],
                        "as_percent": True,
                    },
                    {
                        "operation": "pct_change",
                        "column": "sales",
                        "output": "sales_mom",
                        "partition_by": ["region"],
                        "order_by": "month",
                        "periods": 1,
                        "as_percent": True,
                    },
                ],
                "top_n": None,
                "sort": [
                    {"column": "month", "direction": "asc", "nulls": "last"},
                    {"column": "region", "direction": "asc", "nulls": "last"},
                ],
                "chart_intent": {
                    "analysis_kind": "trend",
                    "chart_type": "line",
                    "x": "month",
                    "y": "row_count",
                    "series": "region",
                    "title": "各地区月度销售额",
                    "unit": "行",
                    "time_range": None,
                    "source_note": "数据来源：中文 销售.csv",
                    "plot_ready": True,
                    "sort": "x-asc",
                },
            }
            plan_path = root / "analysis_plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False), encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--profile",
                    str(profile_path),
                    "--plan",
                    str(plan_path),
                    "--output-dir",
                    str(root),
                    "--allowed-read-root",
                    str(root),
                    "--allowed-write-root",
                    str(root),
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            response = json.loads(completed.stdout)
            self.assertTrue(response["ok"])
            self.assertEqual(sha256(source), source_hash)

            result_path = root / "result.csv"
            with result_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            missing_group = next(
                row
                for row in rows
                if row["month"] == "2026-01-01" and row["region"] == "华南"
            )
            self.assertEqual(missing_group["sales"], "")

            manifest = json.loads((root / "analysis_result.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "chartpilot.analysis-result/v1")
            self.assertEqual(manifest["stage"], "analysis")
            self.assertEqual(manifest["status"], "success")
            self.assertEqual(manifest["artifacts"]["result_csv"]["sha256"], sha256(result_path))
            self.assertTrue(manifest["findings"])
            warning_codes = {
                item["code"] for item in manifest["validation"]["warnings"]
            }
            self.assertIn("DIVIDE_BY_ZERO", warning_codes)
            py_compile.compile(
                str(root / "generated_analysis.py"), doraise=True
            )

    def test_artifact_set_commit_rolls_back_when_manifest_install_fails(self) -> None:
        module = load_runner()

        with tempfile.TemporaryDirectory(prefix="chartpilot-transaction-") as temporary:
            root = Path(temporary)
            destinations = {
                "generated_analysis": root / "generated_analysis.py",
                "cleaned_data": root / "cleaned_data.csv",
                "result_csv": root / "result.csv",
                "analysis_result": root / "analysis_result.json",
            }
            old_contents = {
                name: f"old-{name}" for name in destinations
            }
            for name, destination in destinations.items():
                destination.write_text(old_contents[name], encoding="utf-8")

            staged = {
                "generated_analysis": root / ".generated.stage",
                "result_csv": root / ".result.stage",
                "analysis_result": root / ".manifest.stage",
            }
            for name, path in staged.items():
                path.write_text(f"new-{name}", encoding="utf-8")

            def fail_on_manifest(temp_path: Path, destination: Path) -> None:
                if destination.name == "analysis_result.json":
                    raise module.AnalysisError(
                        "OUTPUT_WRITE_ERROR",
                        "Injected manifest failure.",
                        exit_code=6,
                    )
                os.replace(temp_path, destination)

            with self.assertRaises(module.AnalysisError):
                module.commit_artifact_set(
                    staged,
                    destinations,
                    installer=fail_on_manifest,
                )

            for name, destination in destinations.items():
                self.assertEqual(
                    destination.read_text(encoding="utf-8"), old_contents[name]
                )

    def test_all_grouped_metric_aggregations(self) -> None:
        import pandas as pd

        module = load_runner()
        frame = pd.DataFrame(
            {
                "c0001": pd.Series(["A", "A", "B", "B"], dtype="string"),
                "c0002": pd.Series([1, 3, 2, pd.NA], dtype="Float64"),
                "c0003": pd.Series(["x", "x", "y", "z"], dtype="string"),
            }
        )
        plan = {
            "group_by": [{"column": "c0001", "output": "group"}],
            "metrics": [
                {"column": "c0002", "aggregation": "sum", "output": "total"},
                {"column": "c0002", "aggregation": "mean", "output": "average"},
                {"column": "c0002", "aggregation": "count", "output": "non_missing"},
                {"column": "c0003", "aggregation": "nunique", "output": "distinct_ids"},
                {"column": "c0002", "aggregation": "min", "output": "minimum"},
                {"column": "c0002", "aggregation": "max", "output": "maximum"},
                {"column": "*", "aggregation": "count", "output": "row_count"},
            ],
        }
        result = module.execute_aggregation(pd, frame, plan).set_index("group")
        self.assertEqual(float(result.at["A", "total"]), 4.0)
        self.assertEqual(float(result.at["A", "average"]), 2.0)
        self.assertEqual(int(result.at["A", "non_missing"]), 2)
        self.assertEqual(int(result.at["A", "distinct_ids"]), 1)
        self.assertEqual(float(result.at["A", "minimum"]), 1.0)
        self.assertEqual(float(result.at["A", "maximum"]), 3.0)
        self.assertEqual(int(result.at["A", "row_count"]), 2)
        self.assertEqual(float(result.at["B", "total"]), 2.0)
        self.assertEqual(int(result.at["B", "non_missing"]), 1)
        self.assertEqual(int(result.at["B", "distinct_ids"]), 2)
        self.assertEqual(int(result.at["B", "row_count"]), 2)


if __name__ == "__main__":
    unittest.main()
