from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from PIL import Image, ImageStat

from chart_script_contract import (
    validate_chart_intent,
    validate_render_metadata,
    validate_render_source,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT_ROOT / "agent/tests/fixtures"
BRIDGE_PATH = PROJECT_ROOT / "agent/mcp/chartpilot_mcp.py"


def load_bridge() -> object:
    spec = importlib.util.spec_from_file_location("chartpilot_mcp_synthetic", BRIDGE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BRIDGE = load_bridge()


class AdaptiveSyntheticTests(unittest.TestCase):
    def test_customized_templates_generalize_to_changed_schema_and_thresholds(self) -> None:
        workspace_root = PROJECT_ROOT / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="adaptive-synthetic-", dir=workspace_root))
        source = temporary / "machines.csv"
        request = temporary / "request.md"
        shutil.copyfile(FIXTURES / "adaptive-machines.csv", source)
        shutil.copyfile(FIXTURES / "adaptive-request.md", request)
        os.environ.update(
            {
                "CHARTPILOT_ROOT": str(PROJECT_ROOT),
                "CHARTPILOT_WORKSPACE_ROOT": str(temporary),
                "CHARTPILOT_ALLOWED_READ_ROOTS": str(temporary),
            }
        )
        task_id = "synthetic-generalization"
        task_dir = temporary / "tasks" / task_id
        try:
            BRIDGE.prepare_adaptive_task(
                str(source), request_path=str(request), task_id=task_id
            )
            BRIDGE.run_task_python(
                task_id,
                "inspect",
                (PROJECT_ROOT / "skills/chartpilot-run-python/assets/templates/inspect_csv.py").read_text(
                    encoding="utf-8"
                ),
            )
            BRIDGE.run_task_python(
                task_id,
                "analysis",
                (FIXTURES / "synthetic_analysis.py").read_text(encoding="utf-8"),
            )
            BRIDGE.run_task_python(
                task_id,
                "render",
                (FIXTURES / "synthetic_render.py").read_text(encoding="utf-8"),
            )
            result = pd.read_csv(task_dir / "result.csv", encoding="utf-8-sig")
            self.assertEqual(len(result), 6)
            self.assertEqual(int((result["relative_ratio"] > 1.2).sum()), 2)
            self.assertEqual(int((result["relative_ratio"] > 1.4).sum()), 1)
            analysis = json.loads((task_dir / "analysis_result.json").read_text(encoding="utf-8"))
            validate_chart_intent(analysis["chart_intent"])
            render_source = (task_dir / "generated_chart.py").read_text(encoding="utf-8")
            features = validate_render_source(render_source)
            self.assertTrue(all(features.values()))
            render_metadata = json.loads(
                (task_dir / "adaptive_chart.json").read_text(encoding="utf-8")
            )
            validate_render_metadata(render_metadata)
            chart = json.loads((task_dir / "chart_result.json").read_text(encoding="utf-8"))
            self.assertEqual(chart["report"]["type"], "multi-panel-risk-report")
            with Image.open(task_dir / "chart.png") as image:
                width, height = image.size
                top = image.crop((0, 0, width, height // 2)).convert("L")
                bottom = image.crop((0, height // 2, width, height)).convert("L")
                self.assertGreater(ImageStat.Stat(top).stddev[0], 5.0)
                self.assertGreater(ImageStat.Stat(bottom).stddev[0], 5.0)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
