from __future__ import annotations

import asyncio
import os
import shutil
import sys
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER = PROJECT_ROOT / "agent/mcp/chartpilot_mcp.py"
WORKSPACE = PROJECT_ROOT / "workspace"
TEMPLATE_ROOT = PROJECT_ROOT / "skills/chartpilot-run-python/assets/templates"


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
                names = {tool.name for tool in listed.tools}
                expected = {
                    "chartpilot_prepare_adaptive_task",
                    "chartpilot_run_task_python",
                }
                if names != expected:
                    raise AssertionError(f"Unexpected MCP tools: {sorted(names)}")

                rejected = await session.call_tool(
                    "chartpilot_prepare_adaptive_task",
                    {
                        "source_path": str(outside_source),
                        "request_text": "Compare sales by region.",
                        "task_id": f"{task_id}-outside",
                    },
                )
                if not rejected.isError:
                    raise AssertionError("MCP accepted a CSV outside the configured read root.")

                prepared = await session.call_tool(
                    "chartpilot_prepare_adaptive_task",
                    {
                        "source_path": str(source),
                        "request_text": "Compare sales by region.",
                        "task_id": task_id,
                    },
                )
                if prepared.isError:
                    raise AssertionError(f"Prepare tool failed: {prepared.content}")
                if not (task_dir / "request.md").is_file():
                    raise AssertionError("Prepare tool did not persist the request.")

                for stage, template_name in (
                    ("inspect", "inspect_csv.py"),
                    ("analysis", "analyze_csv.py"),
                    ("render", "render_chart.py"),
                ):
                    result = await session.call_tool(
                        "chartpilot_run_task_python",
                        {
                            "task_id": task_id,
                            "stage": stage,
                            "source_code": (TEMPLATE_ROOT / template_name).read_text(encoding="utf-8"),
                        },
                    )
                    if result.isError:
                        raise AssertionError(f"Adaptive {stage} failed: {result.content}")
                if (task_dir / "chart.png").read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                    raise AssertionError("Adaptive MCP workflow did not create a valid PNG.")
                records = sorted((task_dir / "executions").glob("*.json"))
                if len(records) != 3:
                    raise AssertionError("Adaptive MCP workflow did not record all stage executions.")
    finally:
        source.unlink(missing_ok=True)
        outside_source.unlink(missing_ok=True)
        shutil.rmtree(task_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(execute_test())
