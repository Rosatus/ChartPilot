from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_bridge(project_root: Path) -> Any:
    path = project_root / "agent/mcp/chartpilot_mcp.py"
    spec = importlib.util.spec_from_file_location("chartpilot_mcp_smoke", path)
    if not spec or not spec.loader:
        raise RuntimeError("Could not load the ChartPilot MCP bridge.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute(project_root: Path, workspace_root: Path) -> dict[str, Any]:
    template_root = project_root / "skills/chartpilot-run-python/assets/templates"
    templates = {
        "inspect": template_root / "inspect_csv.py",
        "analysis": template_root / "analyze_csv.py",
        "render": template_root / "render_chart.py",
    }
    for path in templates.values():
        if not path.is_file():
            raise RuntimeError(f"Required adaptive template not found: {path}")

    workspace_root.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "CHARTPILOT_ROOT": str(project_root),
            "CHARTPILOT_WORKSPACE_ROOT": str(workspace_root),
            "CHARTPILOT_ALLOWED_READ_ROOTS": str(workspace_root),
        }
    )
    bridge = load_bridge(project_root)
    with tempfile.TemporaryDirectory(prefix="chartpilot-smoke-", dir=workspace_root) as temporary:
        source = Path(temporary) / "sales.csv"
        source.write_text(
            "region,sales\nEast,100\nSouth,80\nEast,50\n",
            encoding="utf-8-sig",
            newline="",
        )
        original_hash = sha256_file(source)
        task_id = f"runtime-smoke-{uuid.uuid4().hex[:8]}"
        task_dir = workspace_root / "tasks" / task_id
        try:
            prepared = bridge.prepare_adaptive_task(
                str(source), request_text="Compare sales by region.", task_id=task_id
            )
            if set(prepared["templates"]) != {"inspect", "analysis", "render"}:
                raise RuntimeError("Prepare did not return all adaptive templates.")
            for stage, path in templates.items():
                bridge.run_task_python(task_id, stage, path.read_text(encoding="utf-8"))
            expected = [
                "request.md",
                "task_context.json",
                "inspection.json",
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
            return {
                "ok": True,
                "python": sys.version.split()[0],
                "executable": sys.executable,
                "adaptive_tools": 2,
                "product_skills": 1,
            }
        finally:
            shutil.rmtree(task_dir, ignore_errors=True)


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
