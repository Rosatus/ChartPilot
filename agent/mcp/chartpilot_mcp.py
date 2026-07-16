from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from mcp.server.fastmcp import FastMCP


SERVER_NAME = "ChartPilot"
TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024
PROCESS_TIMEOUT_SECONDS = 300
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SENSITIVE_ENV_PATTERN = re.compile(
    r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE
)
NETWORK_ENV_NAMES = {
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
}


def sanitize_server_environment() -> None:
    for name in tuple(os.environ):
        upper = name.upper()
        if upper.startswith("CHARTPILOT_"):
            continue
        if upper in NETWORK_ENV_NAMES or SENSITIVE_ENV_PATTERN.search(upper):
            os.environ.pop(name, None)


sanitize_server_environment()

mcp = FastMCP(SERVER_NAME)


class ChartPilotBridgeError(RuntimeError):
    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.payload = {
            "status": "error",
            "stage": "agent",
            "error": {
                "code": code,
                "message": message,
                "recoverable": False,
                "details": dict(details or {}),
            },
        }
        super().__init__(json.dumps(self.payload, ensure_ascii=False, sort_keys=True))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
    if not path.is_file():
        raise ChartPilotBridgeError("ARTIFACT_NOT_FOUND", "A required task artifact is missing.")
    size = path.stat().st_size
    if size > maximum:
        raise ChartPilotBridgeError(
            "ARTIFACT_TOO_LARGE",
            "A task artifact exceeds the configured size limit.",
            {"name": path.name, "size_bytes": size, "max_bytes": maximum},
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChartPilotBridgeError(
            "INVALID_ARTIFACT", "A task artifact is not valid UTF-8 JSON.", {"name": path.name}
        ) from exc
    if not isinstance(value, dict):
        raise ChartPilotBridgeError("INVALID_ARTIFACT", "A task artifact must contain a JSON object.")
    return value


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    text = json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_JSON_BYTES:
        raise ChartPilotBridgeError(
            "PLAN_TOO_LARGE",
            "The analysis plan exceeds the configured size limit.",
            {"size_bytes": len(encoded), "max_bytes": MAX_JSON_BYTES},
        )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def is_within(path: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


class RuntimeContext:
    def __init__(self) -> None:
        raw_root = os.environ.get("CHARTPILOT_ROOT")
        raw_workspace = os.environ.get("CHARTPILOT_WORKSPACE_ROOT")
        raw_read_roots = os.environ.get("CHARTPILOT_ALLOWED_READ_ROOTS", "")
        if not raw_root or not raw_workspace or not raw_read_roots:
            raise ChartPilotBridgeError(
                "RUNTIME_CONFIGURATION_MISSING",
                "ChartPilot root, workspace, and allowed read roots must be configured.",
            )
        self.project_root = Path(raw_root).resolve(strict=True)
        self.workspace_root = Path(raw_workspace).resolve(strict=True)
        if not self.workspace_root.is_dir():
            raise ChartPilotBridgeError(
                "RUNTIME_CONFIGURATION_INVALID", "The ChartPilot workspace root is not a directory."
            )
        self.tasks_root = self.workspace_root / "tasks"
        self.tasks_root.mkdir(parents=True, exist_ok=True)
        self.tasks_root = self.tasks_root.resolve(strict=True)

        roots: list[Path] = []
        for raw_value in raw_read_roots.split(os.pathsep):
            if not raw_value:
                continue
            root = Path(raw_value).resolve(strict=True)
            if not root.is_dir():
                raise ChartPilotBridgeError(
                    "RUNTIME_CONFIGURATION_INVALID", "An allowed read root is not a directory."
                )
            if root not in roots:
                roots.append(root)
        if not roots:
            raise ChartPilotBridgeError(
                "RUNTIME_CONFIGURATION_INVALID", "No valid allowed read roots were configured."
            )
        self.read_roots = tuple(roots)

        runtime_manifest = load_json(self.project_root / "runtime/runtime-manifest.json")
        if runtime_manifest.get("schema_version") != "chartpilot.runtime/v1":
            raise ChartPilotBridgeError(
                "RUNTIME_MANIFEST_INVALID", "The bundled Python runtime manifest is unsupported."
            )
        python_config = runtime_manifest.get("python")
        if not isinstance(python_config, dict):
            raise ChartPilotBridgeError("RUNTIME_MANIFEST_INVALID", "Python metadata is missing.")
        raw_interpreter = python_config.get("interpreter")
        if not isinstance(raw_interpreter, str) or Path(raw_interpreter).is_absolute():
            raise ChartPilotBridgeError("RUNTIME_MANIFEST_INVALID", "Python path is invalid.")
        self.python = (self.project_root / raw_interpreter).resolve(strict=True)
        if self.python != Path(sys.executable).resolve(strict=True):
            raise ChartPilotBridgeError(
                "WRONG_PYTHON_RUNTIME", "The MCP server is not running under bundled WinPython."
            )
        environment = runtime_manifest.get("environment")
        if not isinstance(environment, dict):
            raise ChartPilotBridgeError("RUNTIME_MANIFEST_INVALID", "Environment policy is missing.")
        self.environment_policy = environment

    def task_id(self, value: str | None) -> str:
        if value is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            return f"csv-{timestamp}-{uuid.uuid4().hex[:8]}"
        if not TASK_ID_PATTERN.fullmatch(value):
            raise ChartPilotBridgeError(
                "INVALID_TASK_ID",
                "task_id must be 1-64 ASCII letters, digits, dots, underscores, or hyphens.",
            )
        return value

    def task_dir(self, task_id: str, *, create: bool = False) -> Path:
        task_id = self.task_id(task_id)
        path = self.tasks_root / task_id
        if create:
            path.mkdir(parents=False, exist_ok=True)
        if not path.is_dir():
            raise ChartPilotBridgeError("TASK_NOT_FOUND", "The requested ChartPilot task does not exist.")
        resolved = path.resolve(strict=True)
        if not is_within(resolved, (self.tasks_root,)):
            raise ChartPilotBridgeError("PATH_NOT_ALLOWED", "The task directory escapes the workspace.")
        return resolved

    def child_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        set_values = self.environment_policy.get("set", {})
        unset_values = self.environment_policy.get("unset", [])
        workspace_paths = self.environment_policy.get("workspace_paths", {})
        if not isinstance(set_values, dict) or not isinstance(unset_values, list) or not isinstance(workspace_paths, dict):
            raise ChartPilotBridgeError("RUNTIME_MANIFEST_INVALID", "Environment policy is malformed.")
        for name in unset_values:
            if isinstance(name, str):
                environment.pop(name, None)
        for name, value in set_values.items():
            if isinstance(name, str) and isinstance(value, str):
                environment[name] = value
        environment_root = self.workspace_root / "runtime-environment"
        for name, relative in workspace_paths.items():
            if not isinstance(name, str) or not isinstance(relative, str):
                raise ChartPilotBridgeError("RUNTIME_MANIFEST_INVALID", "Workspace path policy is malformed.")
            path = environment_root / relative
            path.mkdir(parents=True, exist_ok=True)
            environment[name] = str(path)
        return environment


def parse_process_error(stderr: str, returncode: int) -> dict[str, Any]:
    for raw_line in reversed(stderr.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {
        "status": "error",
        "stage": "agent",
        "error": {
            "code": "BUSINESS_CLI_FAILED",
            "message": "A ChartPilot business CLI failed without a structured error.",
            "recoverable": False,
            "details": {"exit_code": returncode},
        },
    }


def run_cli(context: RuntimeContext, script: Path, arguments: Sequence[str]) -> dict[str, Any]:
    command = [str(context.python), "-I", str(script), *arguments]
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(mode="w+b") as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=context.project_root,
            env=context.child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
        )
        try:
            returncode = process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise ChartPilotBridgeError(
                "PROCESS_TIMEOUT",
                "A ChartPilot business CLI exceeded its execution timeout.",
                {"timeout_seconds": PROCESS_TIMEOUT_SECONDS},
            ) from exc
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout_bytes = stdout_file.read(MAX_PROCESS_OUTPUT_BYTES + 1)
        stderr_bytes = stderr_file.read(MAX_PROCESS_OUTPUT_BYTES + 1)
    if len(stdout_bytes) > MAX_PROCESS_OUTPUT_BYTES or len(stderr_bytes) > MAX_PROCESS_OUTPUT_BYTES:
        raise ChartPilotBridgeError(
            "PROCESS_OUTPUT_TOO_LARGE", "A ChartPilot business CLI exceeded its output limit."
        )
    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    if returncode != 0:
        payload = parse_process_error(stderr, returncode)
        raise ChartPilotBridgeError(
            "BUSINESS_CLI_ERROR",
            "A deterministic ChartPilot stage reported an error.",
            {"exit_code": returncode, "cause": payload},
        )
    try:
        value = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as exc:
        raise ChartPilotBridgeError(
            "INVALID_PROCESS_OUTPUT", "A ChartPilot business CLI returned invalid JSON."
        ) from exc
    if not isinstance(value, dict):
        raise ChartPilotBridgeError(
            "INVALID_PROCESS_OUTPUT", "A ChartPilot business CLI must return a JSON object."
        )
    return value


def profile_csv(
    source_path: str, task_id: str | None = None, sample_mode: str = "redacted"
) -> dict[str, Any]:
    context = RuntimeContext()
    if sample_mode not in {"none", "redacted", "raw"}:
        raise ChartPilotBridgeError("INVALID_SAMPLE_MODE", "sample_mode is not supported.")
    source = Path(source_path).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() != ".csv":
        raise ChartPilotBridgeError("INVALID_SOURCE", "The source must be a regular .csv file.")
    if not is_within(source, context.read_roots):
        raise ChartPilotBridgeError("PATH_NOT_ALLOWED", "The source CSV is outside allowed read roots.")
    resolved_task_id = context.task_id(task_id)
    task_dir = context.task_dir(resolved_task_id, create=True)
    script = context.project_root / "skills/chartpilot-profile-csv/scripts/profile_csv.py"
    arguments = [
        str(source),
        "--task-id",
        resolved_task_id,
        "--output-dir",
        str(task_dir),
        "--sample-mode",
        sample_mode,
        "--allowed-write-root",
        str(context.tasks_root),
    ]
    for root in context.read_roots:
        arguments.extend(("--allowed-read-root", str(root)))
    run_cli(context, script, arguments)
    return {"task_id": resolved_task_id, "profile": load_json(task_dir / "input_profile.json")}


def analyze_data(task_id: str, analysis_plan: dict[str, Any]) -> dict[str, Any]:
    context = RuntimeContext()
    task_dir = context.task_dir(task_id)
    if not isinstance(analysis_plan, dict):
        raise ChartPilotBridgeError("INVALID_PLAN", "analysis_plan must be a JSON object.")
    if analysis_plan.get("task_id") != task_id:
        raise ChartPilotBridgeError("INVALID_PLAN", "analysis_plan.task_id must match task_id.")
    plan_path = task_dir / "analysis_plan.json"
    write_json_atomic(plan_path, analysis_plan)
    script = context.project_root / "skills/chartpilot-analyze-data/scripts/run_analysis.py"
    arguments = [
        "--profile",
        str(task_dir / "input_profile.json"),
        "--plan",
        str(plan_path),
        "--output-dir",
        str(task_dir),
        "--allowed-write-root",
        str(context.tasks_root),
    ]
    for root in (*context.read_roots, context.tasks_root):
        arguments.extend(("--allowed-read-root", str(root)))
    run_cli(context, script, arguments)
    return {"task_id": task_id, "analysis": load_json(task_dir / "analysis_result.json")}


def render_chart(task_id: str, font_path: str | None = None) -> dict[str, Any]:
    context = RuntimeContext()
    task_dir = context.task_dir(task_id)
    script = context.project_root / "skills/chartpilot-render-chart/scripts/render_chart.py"
    arguments = [
        "--analysis-result",
        str(task_dir / "analysis_result.json"),
        "--output-dir",
        str(task_dir),
    ]
    if font_path:
        font = Path(font_path).resolve(strict=True)
        if not font.is_file() or not is_within(font, context.read_roots):
            raise ChartPilotBridgeError("PATH_NOT_ALLOWED", "The font is outside allowed read roots.")
        arguments.extend(("--font-path", str(font)))
    run_cli(context, script, arguments)
    chart_path = task_dir / "chart.png"
    if not chart_path.is_file() or chart_path.read_bytes()[:8] != PNG_SIGNATURE:
        raise ChartPilotBridgeError("INVALID_CHART", "The renderer did not create a valid PNG.")
    summary_path = task_dir / "summary.md"
    if summary_path.stat().st_size > MAX_JSON_BYTES:
        raise ChartPilotBridgeError("ARTIFACT_TOO_LARGE", "The chart summary is too large.")
    return {
        "task_id": task_id,
        "chart": load_json(task_dir / "chart_result.json"),
        "chart_path": str(chart_path),
        "chart_sha256": sha256_file(chart_path),
        "summary": summary_path.read_text(encoding="utf-8"),
    }


@mcp.tool(name="chartpilot_profile_csv")
def chartpilot_profile_csv(
    source_path: str, task_id: str | None = None, sample_mode: str = "redacted"
) -> dict[str, Any]:
    """Profile one allowed local CSV into a new deterministic ChartPilot task."""
    return profile_csv(source_path, task_id, sample_mode)


@mcp.tool(name="chartpilot_analyze_data")
def chartpilot_analyze_data(task_id: str, analysis_plan: dict[str, Any]) -> dict[str, Any]:
    """Execute an allowlisted ChartPilot analysis plan for an existing profiled task."""
    return analyze_data(task_id, analysis_plan)


@mcp.tool(name="chartpilot_render_chart")
def chartpilot_render_chart(task_id: str, font_path: str | None = None) -> dict[str, Any]:
    """Render the frozen analysis result for a ChartPilot task as a validated PNG."""
    return render_chart(task_id, font_path)


def main() -> int:
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
