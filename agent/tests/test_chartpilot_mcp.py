from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER = PROJECT_ROOT / "agent/mcp/chartpilot_mcp.py"
WORKSPACE = PROJECT_ROOT / "workspace"


def build_plan(profile: dict[str, Any]) -> dict[str, Any]:
    columns = {item["source_name"]: item["id"] for item in profile["columns"]}
    return {
        "schema_version": "chartpilot.analysis-plan/v1",
        "task_id": profile["task_id"],
        "status": "ready",
        "source_sha256": profile["source"]["sha256"],
        "question": "Compare sales by region",
        "assumptions": [],
        "cleaning": [
            {
                "operation": "cast",
                "column": columns["sales"],
                "to": "number",
                "on_error": "raise",
                "reason": "Sales aggregation requires numeric values",
            }
        ],
        "filters": [],
        "time_bucket": None,
        "group_by": [{"column": columns["region"], "output": "region"}],
        "metrics": [
            {
                "column": columns["sales"],
                "aggregation": "sum",
                "output": "sales",
                "unit": "USD",
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
            "title": "Sales by region",
            "unit": "USD",
            "time_range": None,
            "source_note": "ChartPilot MCP integration test",
            "plot_ready": True,
            "sort": "y-desc",
        },
    }


async def execute_test() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    task_id = f"mcp-test-{uuid.uuid4().hex[:10]}"
    source = WORKSPACE / f"{task_id}.csv"
    outside_source = PROJECT_ROOT / "build" / f"{task_id}-outside.csv"
    task_dir = WORKSPACE / "tasks" / task_id
    outside_source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "region,sales\nEast,100\nWest,80\nEast,50\n",
        encoding="utf-8-sig",
        newline="",
    )
    outside_source.write_text("region,sales\nEast,1\n", encoding="utf-8", newline="")
    environment = os.environ.copy()
    environment.update(
        {
            "CHARTPILOT_ROOT": str(PROJECT_ROOT),
            "CHARTPILOT_WORKSPACE_ROOT": str(WORKSPACE),
            "CHARTPILOT_ALLOWED_READ_ROOTS": str(WORKSPACE),
        }
    )
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-I", str(SERVER)],
        env=environment,
        cwd=str(PROJECT_ROOT),
    )
    try:
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                self_names = {tool.name for tool in listed.tools}
                expected = {
                    "chartpilot_profile_csv",
                    "chartpilot_analyze_data",
                    "chartpilot_render_chart",
                }
                if self_names != expected:
                    raise AssertionError(f"Unexpected MCP tools: {sorted(self_names)}")

                rejected = await session.call_tool(
                    "chartpilot_profile_csv",
                    {"source_path": str(outside_source), "task_id": f"{task_id}-outside"},
                )
                if not rejected.isError:
                    raise AssertionError("MCP accepted a CSV outside the configured read root.")

                result = await session.call_tool(
                    "chartpilot_profile_csv",
                    {"source_path": str(source), "task_id": task_id, "sample_mode": "none"},
                )
                if result.isError:
                    raise AssertionError(f"Profile tool failed: {result.content}")
                profile = json.loads((task_dir / "input_profile.json").read_text(encoding="utf-8"))

                result = await session.call_tool(
                    "chartpilot_analyze_data",
                    {"task_id": task_id, "analysis_plan": build_plan(profile)},
                )
                if result.isError:
                    raise AssertionError(f"Analysis tool failed: {result.content}")

                result = await session.call_tool(
                    "chartpilot_render_chart", {"task_id": task_id}
                )
                if result.isError:
                    raise AssertionError(f"Render tool failed: {result.content}")
                if (task_dir / "chart.png").read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                    raise AssertionError("MCP workflow did not create a valid PNG.")
    finally:
        source.unlink(missing_ok=True)
        outside_source.unlink(missing_ok=True)
        shutil.rmtree(task_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(execute_test())
