from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = PROJECT_ROOT / "workspace"
MODULE_PATH = PROJECT_ROOT / "agent/mcp/chartpilot_mcp.py"


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
        record = self.tasks_root / "failed-python/executions/inspect-001.json"
        self.assertTrue(record.is_file())
        self.assertIn('"status": "failed"', record.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
