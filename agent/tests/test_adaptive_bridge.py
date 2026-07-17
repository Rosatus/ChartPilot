from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = PROJECT_ROOT / "workspace"
MODULE_PATH = PROJECT_ROOT / "agent/mcp/chartpilot_mcp.py"
TEMPLATE_ROOT = PROJECT_ROOT / "skills/chartpilot-run-python/assets/templates"


def load_module() -> object:
    spec = importlib.util.spec_from_file_location("chartpilot_mcp_unit", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


class AdaptiveBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        self.temporary = Path(tempfile.mkdtemp(prefix="adaptive-unit-", dir=WORKSPACE))
        self.tasks_root = self.temporary / "tasks"
        os.environ.update(
            {
                "CHARTPILOT_ROOT": str(PROJECT_ROOT),
                "CHARTPILOT_WORKSPACE_ROOT": str(self.temporary),
                "CHARTPILOT_ALLOWED_READ_ROOTS": str(self.temporary),
            }
        )
        self.source = self.temporary / "data.csv"
        self.source.write_text("group,value\nA,1\nB,2\n", encoding="utf-8-sig")
        self.request = self.temporary / "request.md"
        self.request.write_text("Compare the groups.", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temporary, ignore_errors=True)

    def prepare_through_analysis(self, task_id: str) -> Path:
        MODULE.prepare_adaptive_task(
            str(self.source), request_text="Compare the groups.", task_id=task_id
        )
        MODULE.run_task_python(
            task_id,
            "inspect",
            (TEMPLATE_ROOT / "inspect_csv.py").read_text(encoding="utf-8"),
        )
        MODULE.run_task_python(
            task_id,
            "analysis",
            (TEMPLATE_ROOT / "analyze_csv.py").read_text(encoding="utf-8"),
        )
        return self.tasks_root / task_id

    @staticmethod
    def render_source(*, summary: str, warn_missing_glyph: bool = False) -> str:
        warning = (
            'warnings.warn("Glyph 20013 missing from font(s) DejaVu Sans.")'
            if warn_missing_glyph
            else ""
        )
        return textwrap.dedent(
            f'''\
            import argparse
            import json
            import warnings
            from pathlib import Path
            from PIL import Image, ImageDraw

            parser = argparse.ArgumentParser()
            parser.add_argument("--context", required=True)
            args = parser.parse_args()
            context = json.loads(Path(args.context).read_text(encoding="utf-8"))
            output_dir = Path(context["paths"]["output_dir"])
            image = Image.new("RGB", (640, 480), "white")
            ImageDraw.Draw(image).rectangle((40, 40, 600, 300), fill="#2F6B7C")
            image.save(output_dir / "chart.png")
            {warning}
            (output_dir / "summary.md").write_text({summary!r}, encoding="utf-8")
            payload = {{
                "schema_version": "chartpilot.adaptive-chart/v1",
                "task_id": context["task_id"],
                "report_type": "comparison",
                "finding_ids": ["finding-1"],
            }}
            (output_dir / "adaptive_chart.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            '''
        )

    def test_prepare_from_request_file_returns_three_templates(self) -> None:
        result = MODULE.prepare_adaptive_task(
            str(self.source), request_path=str(self.request), task_id="prepare-test"
        )
        self.assertEqual(set(result["templates"]), {"inspect", "analysis", "render"})
        self.assertEqual(result["context"]["source"]["headers"], ["group", "value"])
        task_dir = self.tasks_root / "prepare-test"
        self.assertEqual((task_dir / "request.md").read_text(encoding="utf-8"), "Compare the groups.")

    def test_prepare_rejects_two_request_forms(self) -> None:
        with self.assertRaises(MODULE.ChartPilotBridgeError) as caught:
            MODULE.prepare_adaptive_task(
                str(self.source),
                request_text="inline",
                request_path=str(self.request),
                task_id="invalid-request",
            )
        self.assertEqual(caught.exception.code, "INVALID_REQUEST")
        self.assertFalse((self.tasks_root / "invalid-request").exists())

    def test_source_change_is_rejected_before_execution(self) -> None:
        MODULE.prepare_adaptive_task(
            str(self.source), request_text="Compare the groups.", task_id="source-change"
        )
        self.source.write_text("group,value\nA,99\n", encoding="utf-8")
        with self.assertRaises(MODULE.ChartPilotBridgeError) as caught:
            MODULE.run_task_python("source-change", "inspect", "raise SystemExit(0)\n")
        self.assertEqual(caught.exception.code, "SOURCE_CHANGED")

    def test_failed_python_writes_an_execution_record(self) -> None:
        MODULE.prepare_adaptive_task(
            str(self.source), request_text="Compare the groups.", task_id="failed-python"
        )
        with self.assertRaises(MODULE.ChartPilotBridgeError) as caught:
            MODULE.run_task_python("failed-python", "inspect", "raise RuntimeError('boom')\n")
        self.assertEqual(caught.exception.code, "PYTHON_EXECUTION_FAILED")
        error = caught.exception.payload["error"]
        self.assertTrue(error["recoverable"])
        self.assertIn("RuntimeError: boom", error["details"]["process"]["stderr_tail"])
        record = self.tasks_root / "failed-python/executions/inspect-001.json"
        self.assertTrue(record.is_file())
        self.assertIn('"status": "failed"', record.read_text(encoding="utf-8"))

    def test_declared_analysis_artifacts_are_committed_and_stale_outputs_removed(self) -> None:
        task_id = "analysis-artifacts"
        MODULE.prepare_adaptive_task(
            str(self.source), request_text="Compare the groups.", task_id=task_id
        )
        MODULE.run_task_python(
            task_id,
            "inspect",
            (TEMPLATE_ROOT / "inspect_csv.py").read_text(encoding="utf-8"),
        )
        source = textwrap.dedent(
            '''\
            import argparse
            import json
            from pathlib import Path

            parser = argparse.ArgumentParser()
            parser.add_argument("--context", required=True)
            args = parser.parse_args()
            context = json.loads(Path(args.context).read_text(encoding="utf-8"))
            output_dir = Path(context["paths"]["output_dir"])
            (output_dir / "result.csv").write_text("group,value\\nA,1\\n", encoding="utf-8")
            (output_dir / "details.csv").write_text("item,count\\nx,2\\n", encoding="utf-8")
            (output_dir / "undeclared.csv").write_text("discard,me\\n1,2\\n", encoding="utf-8")
            payload = {
                "schema_version": "chartpilot.adaptive-analysis/v1",
                "task_id": context["task_id"],
                "question": "Compare the groups.",
                "assumptions": [],
                "result_schema": [
                    {"name": "group", "type": "text", "role": "dimension"},
                    {"name": "value", "type": "number", "role": "metric"},
                ],
                "findings": [
                    {"id": "finding-1", "text": "A has value 1.", "evidence": []}
                ],
                "chart_intent": {"report_type": "comparison"},
                "artifacts": ["result.csv", "details.csv"],
            }
            (output_dir / "adaptive_analysis.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            '''
        )
        result = MODULE.run_task_python(task_id, "analysis", source)
        task_dir = self.tasks_root / task_id
        self.assertTrue((task_dir / "details.csv").is_file())
        self.assertFalse((task_dir / "undeclared.csv").exists())
        auxiliary = result["analysis"]["artifacts"]["auxiliary"]
        self.assertEqual([item["path"] for item in auxiliary], ["details.csv"])

        without_auxiliary = source.replace(
            '(output_dir / "details.csv").write_text("item,count\\n\\nx,2\\n", encoding="utf-8")',
            "",
        ).replace(
            '(output_dir / "undeclared.csv").write_text("discard,me\\n\\n1,2\\n", encoding="utf-8")',
            "",
        ).replace('["result.csv", "details.csv"]', "[]")
        MODULE.run_task_python(task_id, "analysis", without_auxiliary)
        self.assertFalse((task_dir / "details.csv").exists())

    def test_analysis_artifacts_reject_case_insensitive_collisions(self) -> None:
        with self.assertRaises(MODULE.ChartPilotBridgeError) as reserved:
            MODULE.validate_analysis_artifacts(self.temporary, ["RESULT.csv"])
        self.assertEqual(reserved.exception.code, "INVALID_STAGE_OUTPUT")
        (self.temporary / "details.csv").write_text("name,value\na,1\n", encoding="utf-8")
        with self.assertRaises(MODULE.ChartPilotBridgeError) as duplicate:
            MODULE.validate_analysis_artifacts(
                self.temporary, ["details.csv", "DETAILS.csv"]
            )
        self.assertEqual(duplicate.exception.code, "INVALID_STAGE_OUTPUT")
        self.assertIn("unique", str(duplicate.exception))

    def test_render_rejects_missing_font_glyph_warnings(self) -> None:
        task_id = "missing-glyph"
        task_dir = self.prepare_through_analysis(task_id)
        with self.assertRaises(MODULE.ChartPilotBridgeError) as caught:
            MODULE.run_task_python(
                task_id,
                "render",
                self.render_source(summary="Readable summary.", warn_missing_glyph=True),
            )
        self.assertEqual(caught.exception.code, "RENDER_TEXT_UNREADABLE")
        self.assertTrue(caught.exception.payload["error"]["recoverable"])
        self.assertEqual(
            caught.exception.details["missing_codepoints"],
            ["U+4E2D"],
        )
        self.assertFalse((task_dir / "chart.png").exists())

    def test_render_rejects_replacement_characters(self) -> None:
        task_id = "replacement-character"
        task_dir = self.prepare_through_analysis(task_id)
        with self.assertRaises(MODULE.ChartPilotBridgeError) as caught:
            MODULE.run_task_python(
                task_id,
                "render",
                self.render_source(summary="Unreadable \ufffd summary."),
            )
        self.assertEqual(caught.exception.code, "INVALID_STAGE_OUTPUT")
        self.assertTrue(caught.exception.payload["error"]["recoverable"])
        self.assertFalse((task_dir / "chart.png").exists())

    def test_unchanged_templates_render_chinese_without_missing_glyphs(self) -> None:
        task_id = "template-chinese"
        MODULE.prepare_adaptive_task(
            str(self.source), request_text="比较各组数值并生成中文图表。", task_id=task_id
        )
        responses = []
        for stage, filename in (
            ("inspect", "inspect_csv.py"),
            ("analysis", "analyze_csv.py"),
            ("render", "render_chart.py"),
        ):
            responses.append(
                MODULE.run_task_python(
                    task_id,
                    stage,
                    (TEMPLATE_ROOT / filename).read_text(encoding="utf-8"),
                )
            )
        render = responses[-1]
        self.assertEqual(render["status"], "success")
        self.assertNotIn("missing from font", render["process"]["stderr_tail"])
        self.assertTrue((self.tasks_root / task_id / "chart.png").is_file())


if __name__ == "__main__":
    unittest.main()
