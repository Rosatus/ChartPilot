from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from mcp.server.fastmcp import FastMCP


SERVER_NAME = "ChartPilot"
TASK_SCHEMA = "chartpilot.adaptive-task/v1"
INSPECTION_SCHEMA = "chartpilot.inspection/v1"
ADAPTIVE_ANALYSIS_SCHEMA = "chartpilot.adaptive-analysis/v1"
ANALYSIS_RESULT_SCHEMA = "chartpilot.analysis-result/v2"
ADAPTIVE_CHART_SCHEMA = "chartpilot.adaptive-chart/v1"
CHART_RESULT_SCHEMA = "chartpilot.chart-result/v2"
TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
TASK_STAGES = ("inspect", "analysis", "render")
SCRIPT_NAMES = {
    "inspect": "generated_inspect.py",
    "analysis": "generated_analysis.py",
    "render": "generated_chart.py",
}
TEMPLATE_NAMES = {
    "inspect": "inspect_csv.py",
    "analysis": "analyze_csv.py",
    "render": "render_chart.py",
}
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_REQUEST_BYTES = 128 * 1024
MAX_SOURCE_CODE_BYTES = 512 * 1024
MAX_PROCESS_OUTPUT_BYTES = 1024 * 1024
MAX_PNG_BYTES = 64 * 1024 * 1024
PROCESS_TIMEOUT_SECONDS = 300
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SENSITIVE_ENV_PATTERN = re.compile(
    r"(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE
)
NETWORK_ENV_NAMES = {"ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}


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
        self.code = code
        self.details = dict(details or {})
        self.payload = {
            "status": "error",
            "stage": "agent",
            "error": {
                "code": code,
                "message": message,
                "recoverable": False,
                "details": self.details,
            },
        }
        super().__init__(json.dumps(self.payload, ensure_ascii=False, sort_keys=True))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path, maximum: int = MAX_JSON_BYTES) -> dict[str, Any]:
    if not path.is_file():
        raise ChartPilotBridgeError(
            "ARTIFACT_NOT_FOUND", "A required task artifact is missing.", {"name": path.name}
        )
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
        raise ChartPilotBridgeError(
            "INVALID_ARTIFACT", "A task artifact must contain a JSON object.", {"name": path.name}
        )
    return value


def write_bytes_atomic(path: Path, value: bytes, maximum: int, code: str) -> None:
    if len(value) > maximum:
        raise ChartPilotBridgeError(
            code,
            "Content exceeds the configured size limit.",
            {"name": path.name, "size_bytes": len(value), "max_bytes": maximum},
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_text_atomic(path: Path, value: str, maximum: int, code: str) -> None:
    write_bytes_atomic(path, value.encode("utf-8"), maximum, code)


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    try:
        text = json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as exc:
        raise ChartPilotBridgeError(
            "INVALID_ARTIFACT", "A generated artifact is not JSON serializable.", {"name": path.name}
        ) from exc
    write_text_atomic(path, text, MAX_JSON_BYTES, "ARTIFACT_TOO_LARGE")


def is_within(path: Path, roots: Sequence[Path]) -> bool:
    return any(_relative_to(path, root) for root in roots)


def _relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def require_text(value: Any, field: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ChartPilotBridgeError("INVALID_ARTIFACT", f"{field} must be text.")
    if not allow_empty and not value.strip():
        raise ChartPilotBridgeError("INVALID_ARTIFACT", f"{field} must not be empty.")
    if len(value) > maximum:
        raise ChartPilotBridgeError(
            "INVALID_ARTIFACT", f"{field} is too long.", {"max_characters": maximum}
        )
    return value


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

        self.runtime_manifest_path = self.project_root / "runtime/runtime-manifest.json"
        self.runtime_manifest = load_json(self.runtime_manifest_path)
        if self.runtime_manifest.get("schema_version") != "chartpilot.runtime/v1":
            raise ChartPilotBridgeError(
                "RUNTIME_MANIFEST_INVALID", "The bundled Python runtime manifest is unsupported."
            )
        python_config = self.runtime_manifest.get("python")
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
        environment = self.runtime_manifest.get("environment")
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

    def create_task_dir(self, task_id: str) -> Path:
        path = self.tasks_root / self.task_id(task_id)
        if path.exists():
            raise ChartPilotBridgeError("TASK_EXISTS", "The requested ChartPilot task already exists.")
        path.mkdir(parents=False)
        return path.resolve(strict=True)

    def task_dir(self, task_id: str) -> Path:
        path = self.tasks_root / self.task_id(task_id)
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
        if not isinstance(set_values, dict) or not isinstance(unset_values, list):
            raise ChartPilotBridgeError("RUNTIME_MANIFEST_INVALID", "Environment policy is malformed.")
        if not isinstance(workspace_paths, dict):
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


def resolve_allowed_file(context: RuntimeContext, raw_path: str, suffixes: set[str]) -> Path:
    try:
        path = Path(raw_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ChartPilotBridgeError("FILE_NOT_FOUND", "An input file was not found.") from exc
    if not path.is_file() or path.suffix.lower() not in suffixes:
        raise ChartPilotBridgeError(
            "INVALID_INPUT", "The input file type is not supported.", {"suffix": path.suffix.lower()}
        )
    if not is_within(path, context.read_roots):
        raise ChartPilotBridgeError("PATH_NOT_ALLOWED", "An input file is outside allowed read roots.")
    return path


def read_request(
    context: RuntimeContext, request_text: str | None, request_path: str | None
) -> tuple[str, str]:
    if (request_text is None) == (request_path is None):
        raise ChartPilotBridgeError(
            "INVALID_REQUEST", "Provide exactly one of request_text or request_path."
        )
    if request_text is not None:
        encoded = request_text.encode("utf-8")
        if not request_text.strip() or len(encoded) > MAX_REQUEST_BYTES:
            raise ChartPilotBridgeError("INVALID_REQUEST", "The inline request is empty or too large.")
        return request_text, "inline"
    assert request_path is not None
    path = resolve_allowed_file(context, request_path, {".md", ".txt"})
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise ChartPilotBridgeError("INVALID_REQUEST", "The request file is too large.")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise ChartPilotBridgeError("INVALID_REQUEST", "The request file must be UTF-8.") from exc
    if not text.strip():
        raise ChartPilotBridgeError("INVALID_REQUEST", "The request file is empty.")
    return text, str(path)


def csv_preview(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        raw = handle.read(128 * 1024)
    encoding = "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        encoding = "gb18030"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            return {"encoding_hint": None, "delimiter_hint": None, "headers": [], "sample_rows": []}
    try:
        dialect = csv.Sniffer().sniff(text, delimiters=",\t;|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    rows = list(csv.reader(text.splitlines()[:8], delimiter=delimiter))
    bounded = [[str(value)[:200] for value in row[:100]] for row in rows]
    return {
        "encoding_hint": encoding,
        "delimiter_hint": delimiter,
        "headers": bounded[0] if bounded else [],
        "sample_rows": bounded[1:4],
    }


def load_templates(context: RuntimeContext) -> dict[str, dict[str, str]]:
    root = context.project_root / "skills/chartpilot-run-python/assets/templates"
    templates: dict[str, dict[str, str]] = {}
    for stage in TASK_STAGES:
        path = root / TEMPLATE_NAMES[stage]
        if not path.is_file():
            raise ChartPilotBridgeError(
                "TEMPLATE_NOT_FOUND", "A required adaptive template is missing.", {"stage": stage}
            )
        source = path.read_text(encoding="utf-8")
        templates[stage] = {
            "name": path.name,
            "sha256": sha256_bytes(source.encode("utf-8")),
            "source_code": source,
        }
    return templates


def prepare_adaptive_task(
    source_path: str,
    request_text: str | None = None,
    request_path: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    context = RuntimeContext()
    source = resolve_allowed_file(context, source_path, {".csv"})
    request, request_origin = read_request(context, request_text, request_path)
    resolved_task_id = context.task_id(task_id)
    task_dir = context.create_task_dir(resolved_task_id)
    try:
        templates = load_templates(context)
        request_file = task_dir / "request.md"
        write_text_atomic(request_file, request, MAX_REQUEST_BYTES, "INVALID_REQUEST")
        runtime_distributions = context.runtime_manifest.get("installed_distributions", [])
        if not isinstance(runtime_distributions, list):
            runtime_distributions = []
        task_context = {
            "schema_version": TASK_SCHEMA,
            "task_id": resolved_task_id,
            "created_at_utc": utc_now(),
            "source": {
                "path": str(source),
                "size_bytes": source.stat().st_size,
                "sha256": sha256_file(source),
                **csv_preview(source),
            },
            "request": {
                "path": str(request_file),
                "sha256": sha256_file(request_file),
                "origin": request_origin,
            },
            "runtime": {
                "runtime_id": context.runtime_manifest.get("runtime_id"),
                "manifest_path": str(context.runtime_manifest_path),
                "manifest_sha256": sha256_file(context.runtime_manifest_path),
                "interpreter": str(context.python),
                "installed_distributions": runtime_distributions,
            },
            "paths": {
                "task_dir": str(task_dir),
                "output_dir": str(task_dir),
                "inspection": str(task_dir / "inspection.json"),
                "prepared_csv": str(task_dir / "prepared.csv"),
                "result_csv": str(task_dir / "result.csv"),
                "analysis_result": str(task_dir / "analysis_result.json"),
                "chart_png": str(task_dir / "chart.png"),
                "summary": str(task_dir / "summary.md"),
            },
            "templates": {
                stage: {"name": value["name"], "sha256": value["sha256"]}
                for stage, value in templates.items()
            },
            "artifacts": {},
        }
        write_json_atomic(task_dir / "task_context.json", task_context)
        return {"task_id": resolved_task_id, "context": task_context, "templates": templates}
    except Exception:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise


def load_task_context(context: RuntimeContext, task_id: str) -> tuple[Path, dict[str, Any]]:
    task_dir = context.task_dir(task_id)
    task_context = load_json(task_dir / "task_context.json")
    if task_context.get("schema_version") != TASK_SCHEMA or task_context.get("task_id") != task_id:
        raise ChartPilotBridgeError("INVALID_TASK_CONTEXT", "The adaptive task context is invalid.")
    return task_dir, task_context


def next_attempt(task_dir: Path, stage: str) -> int:
    executions = task_dir / "executions"
    executions.mkdir(exist_ok=True)
    return len(list(executions.glob(f"{stage}-*.json"))) + 1


def run_python_process(
    context: RuntimeContext, task_dir: Path, script: Path, attempt_context: Path
) -> dict[str, Any]:
    command = [str(context.python), "-I", str(script), "--context", str(attempt_context)]
    started_at = utc_now()
    started = time.monotonic()
    timed_out = False
    with tempfile.TemporaryFile(mode="w+b") as stdout_file, tempfile.TemporaryFile(
        mode="w+b"
    ) as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=task_dir,
            env=context.child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            shell=False,
        )
        try:
            returncode = process.wait(timeout=PROCESS_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            returncode = process.wait()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout_bytes = stdout_file.read(MAX_PROCESS_OUTPUT_BYTES + 1)
        stderr_bytes = stderr_file.read(MAX_PROCESS_OUTPUT_BYTES + 1)
    return {
        "command": {"interpreter": str(context.python), "arguments": command[1:]},
        "started_at_utc": started_at,
        "finished_at_utc": utc_now(),
        "duration_ms": round((time.monotonic() - started) * 1000),
        "exit_code": returncode,
        "timed_out": timed_out,
        "output_too_large": (
            len(stdout_bytes) > MAX_PROCESS_OUTPUT_BYTES
            or len(stderr_bytes) > MAX_PROCESS_OUTPUT_BYTES
        ),
        "stdout": stdout_bytes[:MAX_PROCESS_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "stderr": stderr_bytes[:MAX_PROCESS_OUTPUT_BYTES].decode("utf-8", errors="replace"),
    }


def validate_identity(payload: Mapping[str, Any], schema: str, task_id: str, name: str) -> None:
    if payload.get("schema_version") != schema or payload.get("task_id") != task_id:
        raise ChartPilotBridgeError(
            "INVALID_STAGE_OUTPUT", f"{name} has the wrong schema or task identity."
        )


def validate_inspection(staging: Path, task_id: str) -> tuple[dict[str, Any], list[str]]:
    payload = load_json(staging / "inspection.json")
    validate_identity(payload, INSPECTION_SCHEMA, task_id, "inspection.json")
    columns = payload.get("columns")
    if not isinstance(columns, list):
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "inspection.columns must be a list.")
    outputs = ["inspection.json"]
    prepared = staging / "prepared.csv"
    if prepared.exists():
        if not prepared.is_file() or prepared.stat().st_size == 0:
            raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "prepared.csv must be nonempty.")
        outputs.append("prepared.csv")
    return payload, outputs


def validate_result_csv(path: Path, result_schema: Any) -> list[str]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "result.csv must be nonempty.")
    if not isinstance(result_schema, list) or not result_schema:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "result_schema must be a nonempty list.")
    names: list[str] = []
    for item in result_schema:
        if not isinstance(item, dict):
            raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "result_schema entries must be objects.")
        name = require_text(item.get("name"), "result_schema.name", 256)
        if name in names:
            raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "result_schema names must be unique.")
        names.append(name)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            headers = next(reader)
            first_row = next(reader, None)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "result.csv is not valid UTF-8 CSV.") from exc
    if headers != names or first_row is None:
        raise ChartPilotBridgeError(
            "INVALID_STAGE_OUTPUT", "result.csv headers must match result_schema and contain data."
        )
    return headers


def validate_analysis(
    staging: Path, task_context: Mapping[str, Any], script_name: str, script_hash: str
) -> tuple[dict[str, Any], list[str]]:
    task_id = str(task_context["task_id"])
    payload = load_json(staging / "adaptive_analysis.json")
    validate_identity(payload, ADAPTIVE_ANALYSIS_SCHEMA, task_id, "adaptive_analysis.json")
    require_text(payload.get("question"), "question", 4000)
    assumptions = payload.get("assumptions")
    findings = payload.get("findings")
    chart_intent = payload.get("chart_intent")
    if not isinstance(assumptions, list) or not isinstance(findings, list) or not findings:
        raise ChartPilotBridgeError(
            "INVALID_STAGE_OUTPUT", "assumptions must be a list and findings must be nonempty."
        )
    if not isinstance(chart_intent, dict):
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "chart_intent must be an object.")
    finding_ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "findings entries must be objects.")
        finding_id = require_text(finding.get("id"), "finding.id", 128)
        require_text(finding.get("text"), "finding.text", 4000)
        if finding_id in finding_ids:
            raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "finding IDs must be unique.")
        finding_ids.add(finding_id)
        if not isinstance(finding.get("evidence"), list):
            raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "finding.evidence must be a list.")
    result_path = staging / "result.csv"
    validate_result_csv(result_path, payload.get("result_schema"))
    adaptive_path = staging / "adaptive_analysis.json"
    request = task_context["request"]
    source = task_context["source"]
    manifest = {
        "schema_version": ANALYSIS_RESULT_SCHEMA,
        "task_id": task_id,
        "stage": "analysis",
        "status": "success",
        "execution_mode": "adaptive-python",
        "source": {"path": source["path"], "sha256": source["sha256"]},
        "request": {"path": request["path"], "sha256": request["sha256"]},
        "script": {"path": script_name, "sha256": script_hash},
        "question": payload["question"],
        "assumptions": assumptions,
        "result_schema": payload["result_schema"],
        "findings": findings,
        "chart_intent": chart_intent,
        "artifacts": {
            "result_csv": {"path": "result.csv", "sha256": sha256_file(result_path)},
            "adaptive_analysis": {
                "path": "adaptive_analysis.json",
                "sha256": sha256_file(adaptive_path),
            },
        },
        "validation": {"passed": True, "checks": ["task_identity", "result_csv_contract"]},
    }
    write_json_atomic(staging / "analysis_result.json", manifest)
    return manifest, ["result.csv", "adaptive_analysis.json", "analysis_result.json"]


def validate_png(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_PNG_BYTES:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "chart.png is missing or too large.")
    if path.read_bytes()[:8] != PNG_SIGNATURE:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "chart.png does not have a PNG signature.")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            sample = image.convert("RGB")
            sample.thumbnail((256, 256))
            colors = sample.getcolors(maxcolors=256 * 256)
    except (OSError, ValueError) as exc:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "chart.png is not a valid PNG.") from exc
    if width < 320 or height < 240 or width > 8192 or height > 8192:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "chart.png dimensions are unsupported.")
    if not colors:
        foreground_ratio = 1.0
    else:
        total = sum(count for count, _ in colors)
        foreground_ratio = (total - max(count for count, _ in colors)) / total
    if foreground_ratio < 0.005:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "chart.png appears blank.")
    return {"width": width, "height": height, "foreground_ratio": foreground_ratio}


def validate_render(
    staging: Path, task_context: Mapping[str, Any], script_name: str, script_hash: str
) -> tuple[dict[str, Any], list[str]]:
    task_id = str(task_context["task_id"])
    payload = load_json(staging / "adaptive_chart.json")
    validate_identity(payload, ADAPTIVE_CHART_SCHEMA, task_id, "adaptive_chart.json")
    require_text(payload.get("report_type"), "report_type", 200)
    finding_ids = payload.get("finding_ids")
    if not isinstance(finding_ids, list) or not all(isinstance(value, str) for value in finding_ids):
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "finding_ids must be a list of text IDs.")
    summary_path = staging / "summary.md"
    if not summary_path.is_file() or summary_path.stat().st_size > MAX_JSON_BYTES:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "summary.md is missing or too large.")
    try:
        summary = summary_path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "summary.md must be UTF-8.") from exc
    if not summary.strip():
        raise ChartPilotBridgeError("INVALID_STAGE_OUTPUT", "summary.md must not be empty.")
    png_path = staging / "chart.png"
    png = validate_png(png_path)
    adaptive_path = staging / "adaptive_chart.json"
    analysis_path = Path(str(task_context["paths"]["analysis_result"]))
    analysis_hash = sha256_file(analysis_path)
    manifest = {
        "schema_version": CHART_RESULT_SCHEMA,
        "task_id": task_id,
        "stage": "chart",
        "status": "success",
        "execution_mode": "adaptive-python",
        "script": {"path": script_name, "sha256": script_hash},
        "upstream": {"analysis_result": {"path": "analysis_result.json", "sha256": analysis_hash}},
        "report": {
            "type": payload["report_type"],
            "finding_ids": finding_ids,
            "presentation_notes": payload.get("presentation_notes", []),
        },
        "artifacts": {
            "chart_png": {
                "path": "chart.png",
                "sha256": sha256_file(png_path),
                "mime_type": "image/png",
                "bytes": png_path.stat().st_size,
                **png,
            },
            "summary": {"path": "summary.md", "sha256": sha256_file(summary_path)},
            "adaptive_chart": {
                "path": "adaptive_chart.json",
                "sha256": sha256_file(adaptive_path),
            },
        },
        "validation": {"passed": True, "checks": ["task_identity", "png_nonblank"]},
    }
    write_json_atomic(staging / "chart_result.json", manifest)
    return manifest, ["chart.png", "summary.md", "adaptive_chart.json", "chart_result.json"]


def commit_outputs(staging: Path, task_dir: Path, names: Sequence[str]) -> None:
    backup = staging / ".backup"
    backup.mkdir()
    installed: list[Path] = []
    backed_up: list[tuple[Path, Path]] = []
    try:
        for name in names:
            source = staging / name
            if not source.is_file():
                raise ChartPilotBridgeError(
                    "INVALID_STAGE_OUTPUT", "A validated stage output is missing.", {"name": name}
                )
            destination = task_dir / name
            if destination.exists():
                backup_path = backup / name
                os.replace(destination, backup_path)
                backed_up.append((backup_path, destination))
            os.replace(source, destination)
            installed.append(destination)
    except Exception:
        for destination in reversed(installed):
            destination.unlink(missing_ok=True)
        for backup_path, destination in reversed(backed_up):
            if backup_path.exists():
                os.replace(backup_path, destination)
        raise


def artifact_snapshot(task_dir: Path, names: Sequence[str]) -> list[dict[str, Any]]:
    return [
        {"path": name, "bytes": (task_dir / name).stat().st_size, "sha256": sha256_file(task_dir / name)}
        for name in names
    ]


def run_task_python(task_id: str, stage: str, source_code: str) -> dict[str, Any]:
    if stage not in TASK_STAGES:
        raise ChartPilotBridgeError("INVALID_STAGE", "stage must be inspect, analysis, or render.")
    encoded = source_code.encode("utf-8") if isinstance(source_code, str) else b""
    if not encoded or len(encoded) > MAX_SOURCE_CODE_BYTES or b"\x00" in encoded:
        raise ChartPilotBridgeError("INVALID_SOURCE_CODE", "Python source is empty, invalid, or too large.")
    context = RuntimeContext()
    task_dir, task_context = load_task_context(context, task_id)
    if sha256_file(Path(str(task_context["source"]["path"]))) != task_context["source"]["sha256"]:
        raise ChartPilotBridgeError("SOURCE_CHANGED", "The source CSV changed after task preparation.")
    if stage == "analysis" and not (task_dir / "inspection.json").is_file():
        raise ChartPilotBridgeError("STAGE_PREREQUISITE_MISSING", "Run the inspect stage before analysis.")
    if stage == "render" and not (task_dir / "analysis_result.json").is_file():
        raise ChartPilotBridgeError("STAGE_PREREQUISITE_MISSING", "Run the analysis stage before render.")

    attempt = next_attempt(task_dir, stage)
    script_name = SCRIPT_NAMES[stage]
    script_path = task_dir / script_name
    write_bytes_atomic(script_path, encoded, MAX_SOURCE_CODE_BYTES, "INVALID_SOURCE_CODE")
    script_hash = sha256_file(script_path)
    staging = Path(tempfile.mkdtemp(prefix=f".adaptive-{stage}-", dir=task_dir))
    process_result: dict[str, Any] | None = None
    status = "failed"
    error_payload: dict[str, Any] | None = None
    outputs: list[str] = []
    response: dict[str, Any] = {}
    try:
        attempt_context = deepcopy(task_context)
        attempt_context["paths"]["output_dir"] = str(staging)
        attempt_context["execution"] = {
            "stage": stage,
            "attempt": attempt,
            "script_path": str(script_path),
            "script_sha256": script_hash,
        }
        attempt_context_path = staging / "task_context.json"
        write_json_atomic(attempt_context_path, attempt_context)
        process_result = run_python_process(context, task_dir, script_path, attempt_context_path)
        if process_result["timed_out"]:
            raise ChartPilotBridgeError(
                "PROCESS_TIMEOUT",
                "Generated task Python exceeded its execution timeout.",
                {"timeout_seconds": PROCESS_TIMEOUT_SECONDS},
            )
        if process_result["output_too_large"]:
            raise ChartPilotBridgeError(
                "PROCESS_OUTPUT_TOO_LARGE", "Generated task Python exceeded its output limit."
            )
        if process_result["exit_code"] != 0:
            raise ChartPilotBridgeError(
                "PYTHON_EXECUTION_FAILED",
                "Generated task Python returned a nonzero exit code.",
                {"exit_code": process_result["exit_code"]},
            )

        if stage == "inspect":
            payload, outputs = validate_inspection(staging, task_id)
            response = {"inspection": payload}
        elif stage == "analysis":
            payload, outputs = validate_analysis(staging, task_context, script_name, script_hash)
            response = {"analysis": payload}
        else:
            payload, outputs = validate_render(staging, task_context, script_name, script_hash)
            response = {"chart": payload}
        commit_outputs(staging, task_dir, outputs)
        task_context["artifacts"][stage] = artifact_snapshot(task_dir, outputs)
        write_json_atomic(task_dir / "task_context.json", task_context)
        status = "success"
    except ChartPilotBridgeError as exc:
        error_payload = exc.payload
    except Exception as exc:
        error_payload = ChartPilotBridgeError(
            "ADAPTIVE_STAGE_FAILED",
            "The adaptive stage failed unexpectedly.",
            {"exception_type": type(exc).__name__},
        ).payload
    finally:
        record = {
            "schema_version": "chartpilot.execution-record/v1",
            "task_id": task_id,
            "stage": stage,
            "attempt": attempt,
            "status": status,
            "script": {"path": script_name, "sha256": script_hash, "bytes": len(encoded)},
            "runtime": {
                "runtime_id": context.runtime_manifest.get("runtime_id"),
                "manifest_sha256": sha256_file(context.runtime_manifest_path),
            },
            "process": process_result,
            "artifacts": artifact_snapshot(task_dir, outputs) if status == "success" else [],
            "error": error_payload,
        }
        record_path = task_dir / "executions" / f"{stage}-{attempt:03d}.json"
        write_json_atomic(record_path, record)
        shutil.rmtree(staging, ignore_errors=True)
    if error_payload is not None:
        error = error_payload["error"]
        raise ChartPilotBridgeError(
            str(error["code"]),
            str(error["message"]),
            {**dict(error.get("details", {})), "execution_record": str(record_path)},
        )
    return {
        "task_id": task_id,
        "stage": stage,
        "status": "success",
        "execution_record": str(record_path),
        **response,
    }


@mcp.tool(name="chartpilot_prepare_adaptive_task")
def chartpilot_prepare_adaptive_task(
    source_path: str,
    request_text: str | None = None,
    request_path: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Prepare one prompt-plus-CSV task and return three editable Python templates."""
    return prepare_adaptive_task(source_path, request_text, request_path, task_id)


@mcp.tool(name="chartpilot_run_task_python")
def chartpilot_run_task_python(task_id: str, stage: str, source_code: str) -> dict[str, Any]:
    """Store and execute Agent-authored task Python with bundled WinPython."""
    return run_task_python(task_id, stage, source_code)


def main() -> int:
    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
