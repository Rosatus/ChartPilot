#!/usr/bin/env python3
"""Execute a validated ChartPilot analysis plan without arbitrary code execution."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import numbers
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_VERSION = "1.0.0"
PROFILE_SCHEMA = "chartpilot.input-profile/v1"
PLAN_SCHEMA = "chartpilot.analysis-plan/v1"
RESULT_SCHEMA = "chartpilot.analysis-result/v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TASK_ID_RE = re.compile(r"^[^/\\\x00-\x1f]{1,128}$")
COLUMN_ID_RE = re.compile(r"^c[0-9]{4,}$")
MAX_PLAN_STEPS = 256


class AnalysisError(Exception):
    """A stable, non-sensitive operational error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        exit_code: int = 5,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
        self.exit_code = exit_code

    def payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AnalysisError(
            "INVALID_ARGUMENT",
            "Command-line arguments are invalid.",
            details={"reason": message},
            exit_code=2,
        )


def configure_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (OSError, ValueError):
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description=(
            "Validate and execute an allowlisted ChartPilot analysis plan against "
            "one profiled CSV."
        )
    )
    parser.add_argument("--profile", required=True, help="Path to input_profile.json")
    parser.add_argument("--plan", required=True, help="Path to analysis_plan.json")
    parser.add_argument("--output-dir", required=True, help="Task output directory")
    parser.add_argument(
        "--allowed-read-root",
        action="append",
        default=[],
        help="Trusted readable root; repeat for multiple roots",
    )
    parser.add_argument(
        "--allowed-write-root",
        help="Trusted writable root containing the output directory",
    )
    parser.add_argument(
        "--max-json-bytes",
        type=int,
        default=5 * 1024 * 1024,
        help="Maximum size of each JSON input (default: 5 MiB)",
    )
    parser.add_argument(
        "--max-source-bytes",
        type=int,
        default=1024 * 1024 * 1024,
        help="Maximum source CSV size (default: 1 GiB)",
    )
    parser.add_argument(
        "--max-result-rows",
        type=int,
        default=5_000,
        help="Maximum successful result rows (default: 5000)",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail if a managed output artifact already exists",
    )
    parser.add_argument(
        "--allow-unc",
        action="store_true",
        help="Allow UNC paths when deployment policy explicitly permits them",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the success response",
    )
    parser.add_argument("--version", action="version", version=SCRIPT_VERSION)
    return parser


def emit_json(payload: Mapping[str, Any], stream: Any, *, pretty: bool = False) -> None:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        allow_nan=False,
    )
    stream.write(text + "\n")
    stream.flush()


def load_pandas() -> Any:
    try:
        import pandas as pd  # type: ignore
    except (ImportError, ModuleNotFoundError) as exc:
        raise AnalysisError(
            "DEPENDENCY_MISSING",
            "The offline pandas dependency is not installed.",
            details={"dependency": "pandas", "exception_type": type(exc).__name__},
            exit_code=7,
        ) from None
    return pd


def require_positive(value: int, name: str) -> None:
    if value <= 0:
        raise AnalysisError(
            "INVALID_ARGUMENT",
            f"{name} must be a positive integer.",
            details={"argument": name},
            exit_code=2,
        )


def is_unc_path(path: str | os.PathLike[str]) -> bool:
    value = os.fspath(path)
    return value.startswith("\\\\") or value.startswith("//")


def reject_unc(path: str | os.PathLike[str], allow_unc: bool, label: str) -> None:
    if is_unc_path(path) and not allow_unc:
        raise AnalysisError(
            "UNC_PATH_NOT_ALLOWED",
            f"{label} uses a UNC path that deployment policy has not allowed.",
            details={"path_role": label},
            exit_code=3,
        )


def resolve_existing(path_value: str, label: str, allow_unc: bool) -> Path:
    reject_unc(path_value, allow_unc, label)
    path = Path(path_value).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise AnalysisError(
            "FILE_NOT_FOUND",
            f"{label} does not exist.",
            details={"path_role": label},
            exit_code=3,
        ) from None
    except (OSError, RuntimeError) as exc:
        raise AnalysisError(
            "FILE_BUSY_OR_PERMISSION",
            f"{label} cannot be resolved.",
            details={"path_role": label, "exception_type": type(exc).__name__},
            exit_code=3,
        ) from None
    return resolved


def resolve_output_dir(path_value: str, allow_unc: bool) -> Path:
    reject_unc(path_value, allow_unc, "output directory")
    path = Path(path_value).expanduser()
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise AnalysisError(
            "PATH_NOT_ALLOWED",
            "The output directory cannot be resolved safely.",
            details={"path_role": "output directory", "exception_type": type(exc).__name__},
            exit_code=3,
        ) from None
    return resolved


def path_is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(root))) == os.fspath(root)
    except ValueError:
        return False


def enforce_roots(path: Path, roots: Sequence[Path], label: str) -> None:
    if roots and not any(path_is_within(path, root) for root in roots):
        raise AnalysisError(
            "PATH_NOT_ALLOWED",
            f"{label} is outside the configured roots.",
            details={"path_role": label},
            exit_code=3,
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except (OSError, PermissionError) as exc:
        raise AnalysisError(
            "FILE_BUSY_OR_PERMISSION",
            "A required file could not be read for hashing.",
            details={"path_role": "source or input", "exception_type": type(exc).__name__},
            exit_code=4,
        ) from None
    return digest.hexdigest()


def reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AnalysisError(
                "INVALID_JSON",
                "A JSON object contains a duplicate key.",
                details={"key": key},
                exit_code=3,
            )
        result[key] = value
    return result


def load_json(path: Path, max_bytes: int, label: str) -> dict[str, Any]:
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise AnalysisError(
                "INVALID_JSON",
                f"{label} exceeds the configured size limit.",
                details={"path_role": label, "size_bytes": size, "max_bytes": max_bytes},
                exit_code=3,
            )
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8-sig"), object_pairs_hook=reject_duplicate_keys
        )
    except AnalysisError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnalysisError(
            "INVALID_JSON",
            f"{label} is not valid UTF-8 JSON.",
            details={"path_role": label, "exception_type": type(exc).__name__},
            exit_code=3,
        ) from None
    except (OSError, PermissionError) as exc:
        raise AnalysisError(
            "FILE_BUSY_OR_PERMISSION",
            f"{label} cannot be read.",
            details={"path_role": label, "exception_type": type(exc).__name__},
            exit_code=3,
        ) from None
    if not isinstance(value, dict):
        raise AnalysisError(
            "INVALID_JSON",
            f"{label} must contain a JSON object.",
            details={"path_role": label},
            exit_code=3,
        )
    return value


def ensure_keys(
    value: Mapping[str, Any],
    *,
    required: Iterable[str],
    allowed: Iterable[str],
    context: str,
    code: str = "INVALID_PLAN",
) -> None:
    required_set = set(required)
    allowed_set = set(allowed)
    missing = sorted(required_set - set(value))
    unknown = sorted(set(value) - allowed_set)
    if missing or unknown:
        raise AnalysisError(
            code,
            f"{context} has missing or unknown fields.",
            details={"context": context, "missing": missing, "unknown": unknown},
            exit_code=3 if code == "INVALID_PROFILE" else 5,
        )


def require_string(value: Any, context: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise AnalysisError(
            "INVALID_PLAN",
            f"{context} must be a non-empty string.",
            details={"context": context},
            exit_code=5,
        )
    if any(ord(character) < 32 for character in value):
        raise AnalysisError(
            "INVALID_PLAN",
            f"{context} contains a control character.",
            details={"context": context},
            exit_code=5,
        )
    return value


def require_output_name(value: Any, context: str) -> str:
    return require_string(value, context, max_length=128)


def normalize_scalar(value: Any, context: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            raise AnalysisError(
                "INVALID_PLAN",
                f"{context} must be a finite JSON scalar.",
                details={"context": context},
                exit_code=5,
            )
        return value
    raise AnalysisError(
        "INVALID_PLAN",
        f"{context} must be a JSON scalar.",
        details={"context": context},
        exit_code=5,
    )


def extract_format_value(container: Mapping[str, Any], key: str) -> Any:
    value = container.get(key)
    if isinstance(value, Mapping):
        for nested_key in ("value", "name", "encoding", "delimiter"):
            if nested_key in value:
                return value[nested_key]
    return value


def normalize_encoding(value: Any) -> str:
    if not isinstance(value, str):
        raise AnalysisError(
            "INVALID_PROFILE",
            "The profile must declare the detected source encoding.",
            details={"field": "source.encoding"},
            exit_code=3,
        )
    encoding = value.strip().lower().replace("_", "-")
    aliases = {"utf8": "utf-8", "utf8-sig": "utf-8-sig", "gb-18030": "gb18030"}
    encoding = aliases.get(encoding, encoding)
    if encoding not in {"utf-8", "utf-8-sig", "gbk", "gb18030"}:
        raise AnalysisError(
            "INVALID_PROFILE",
            "The profile declares an unsupported CSV encoding.",
            details={"encoding": encoding},
            exit_code=3,
        )
    return encoding


def normalize_delimiter(value: Any) -> str:
    names = {"comma": ",", "tab": "\t", "semicolon": ";", "pipe": "|"}
    if isinstance(value, str):
        delimiter = names.get(value.strip().lower(), value)
        if delimiter in {",", "\t", ";", "|"}:
            return delimiter
    raise AnalysisError(
        "INVALID_PROFILE",
        "The profile declares an unsupported CSV delimiter.",
        details={"field": "source.delimiter"},
        exit_code=3,
    )


def validate_task_id(value: Any, context: str) -> str:
    if not isinstance(value, str) or TASK_ID_RE.fullmatch(value) is None:
        raise AnalysisError(
            "INVALID_PROFILE" if context == "profile" else "INVALID_PLAN",
            f"{context} task_id is invalid.",
            details={"context": context},
            exit_code=3 if context == "profile" else 5,
        )
    return value


def validate_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    if profile.get("schema_version") != PROFILE_SCHEMA:
        raise AnalysisError(
            "INVALID_PROFILE",
            "input_profile.json has an unsupported schema version.",
            details={"expected": PROFILE_SCHEMA, "actual": profile.get("schema_version")},
            exit_code=3,
        )
    if profile.get("stage") != "profile" or profile.get("status") != "success":
        raise AnalysisError(
            "INVALID_PROFILE",
            "input_profile.json is not a successful profile result.",
            details={"stage": profile.get("stage"), "status": profile.get("status")},
            exit_code=3,
        )
    task_id = validate_task_id(profile.get("task_id"), "profile")
    source = profile.get("source")
    shape = profile.get("shape")
    columns = profile.get("columns")
    if not isinstance(source, Mapping) or not isinstance(shape, Mapping) or not isinstance(columns, list):
        raise AnalysisError(
            "INVALID_PROFILE",
            "input_profile.json is missing source, shape, or columns.",
            details={},
            exit_code=3,
        )
    source_path = source.get("path")
    source_hash = source.get("sha256")
    if not isinstance(source_path, str) or not Path(source_path).is_absolute():
        raise AnalysisError(
            "INVALID_PROFILE",
            "The profile source.path must be absolute.",
            details={"field": "source.path"},
            exit_code=3,
        )
    if not isinstance(source_hash, str) or SHA256_RE.fullmatch(source_hash) is None:
        raise AnalysisError(
            "INVALID_PROFILE",
            "The profile source.sha256 is invalid.",
            details={"field": "source.sha256"},
            exit_code=3,
        )
    row_count = shape.get("rows", shape.get("row_count"))
    column_count = shape.get("columns", shape.get("column_count"))
    if (
        not isinstance(row_count, int)
        or isinstance(row_count, bool)
        or row_count < 0
        or not isinstance(column_count, int)
        or isinstance(column_count, bool)
        or column_count <= 0
        or column_count != len(columns)
    ):
        raise AnalysisError(
            "INVALID_PROFILE",
            "The profile shape is invalid or inconsistent with columns.",
            details={"row_count": row_count, "column_count": column_count},
            exit_code=3,
        )
    normalized_columns: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for expected_index, item in enumerate(columns):
        if not isinstance(item, Mapping):
            raise AnalysisError(
                "INVALID_PROFILE",
                "A profile column is not an object.",
                details={"column_index": expected_index},
                exit_code=3,
            )
        column_id = item.get("id")
        index = item.get("index")
        source_name = item.get("source_name")
        if (
            not isinstance(column_id, str)
            or COLUMN_ID_RE.fullmatch(column_id) is None
            or column_id in seen_ids
            or index != expected_index
            or not isinstance(source_name, str)
        ):
            raise AnalysisError(
                "INVALID_PROFILE",
                "Profile column IDs, indexes, or source names are invalid.",
                details={"column_index": expected_index},
                exit_code=3,
            )
        seen_ids.add(column_id)
        normalized_columns.append(
            {"id": column_id, "index": index, "source_name": source_name}
        )
    format_object = profile.get("format")
    format_mapping = format_object if isinstance(format_object, Mapping) else {}
    encoding_value = source.get("encoding", extract_format_value(format_mapping, "encoding"))
    delimiter_value = source.get("delimiter", extract_format_value(format_mapping, "delimiter"))
    quotechar = extract_format_value(format_mapping, "quotechar") or '"'
    if not isinstance(quotechar, str) or len(quotechar) != 1:
        raise AnalysisError(
            "INVALID_PROFILE",
            "The profile quote character is invalid.",
            details={"field": "format.quotechar"},
            exit_code=3,
        )
    return {
        "task_id": task_id,
        "source_path": source_path,
        "source_sha256": source_hash,
        "source_size_bytes": source.get("size_bytes"),
        "encoding": normalize_encoding(encoding_value),
        "delimiter": normalize_delimiter(delimiter_value),
        "quotechar": quotechar,
        "row_count": row_count,
        "column_count": column_count,
        "columns": normalized_columns,
    }


def require_column(value: Any, available: set[str], context: str) -> str:
    column = require_string(value, context, max_length=128)
    if column not in available:
        raise AnalysisError(
            "INVALID_PLAN",
            f"{context} references an unavailable column.",
            details={"context": context, "column": column},
            exit_code=5,
        )
    return column


def require_string_list(value: Any, context: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise AnalysisError(
            "INVALID_PLAN",
            f"{context} must be a {'non-empty ' if not allow_empty else ''}array of strings.",
            details={"context": context},
            exit_code=5,
        )
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(require_string(item, f"{context}[{index}]", max_length=128))
    return result


def unsupported_operation(operation: Any, context: str) -> AnalysisError:
    return AnalysisError(
        "UNSUPPORTED_OPERATION",
        "The plan requests an operation outside the deterministic MVP allowlist.",
        details={"context": context, "operation": operation},
        exit_code=5,
    )


def validate_plan(
    plan: Mapping[str, Any], profile: Mapping[str, Any]
) -> dict[str, Any]:
    allowed_top = {
        "schema_version",
        "task_id",
        "status",
        "source_sha256",
        "question",
        "assumptions",
        "cleaning",
        "filters",
        "time_bucket",
        "group_by",
        "metrics",
        "post_calculations",
        "top_n",
        "sort",
        "chart_intent",
    }
    ensure_keys(
        plan,
        required={
            "schema_version",
            "task_id",
            "status",
            "source_sha256",
            "question",
            "metrics",
            "chart_intent",
        },
        allowed=allowed_top,
        context="analysis plan",
    )
    if plan.get("schema_version") != PLAN_SCHEMA:
        raise AnalysisError(
            "INVALID_PLAN",
            "analysis_plan.json has an unsupported schema version.",
            details={"expected": PLAN_SCHEMA, "actual": plan.get("schema_version")},
            exit_code=5,
        )
    task_id = validate_task_id(plan.get("task_id"), "plan")
    if task_id != profile["task_id"]:
        raise AnalysisError(
            "INVALID_PLAN",
            "The plan task_id does not match input_profile.json.",
            details={"profile_task_id": profile["task_id"], "plan_task_id": task_id},
            exit_code=5,
        )
    status = plan.get("status")
    if status == "needs_clarification":
        raise AnalysisError(
            "NEEDS_CLARIFICATION",
            "The analysis plan has unresolved business ambiguity.",
            details={"task_id": task_id},
            exit_code=5,
        )
    if status != "ready":
        raise AnalysisError(
            "INVALID_PLAN",
            "The analysis plan status must be ready or needs_clarification.",
            details={"status": status},
            exit_code=5,
        )
    source_sha256 = plan.get("source_sha256")
    if source_sha256 != profile["source_sha256"]:
        raise AnalysisError(
            "INVALID_PLAN",
            "The plan source hash does not match input_profile.json.",
            details={
                "profile_sha256": profile["source_sha256"],
                "plan_sha256": source_sha256,
            },
            exit_code=5,
        )
    question = require_string(plan.get("question"), "question", max_length=4000)
    assumptions = require_string_list(plan.get("assumptions", []), "assumptions")
    source_columns = {item["id"] for item in profile["columns"]}

    cleaning_value = plan.get("cleaning", [])
    if not isinstance(cleaning_value, list) or len(cleaning_value) > MAX_PLAN_STEPS:
        raise AnalysisError(
            "INVALID_PLAN",
            "cleaning must be a bounded array.",
            details={"max_steps": MAX_PLAN_STEPS},
            exit_code=5,
        )
    cleaning: list[dict[str, Any]] = []
    for index, raw in enumerate(cleaning_value):
        context = f"cleaning[{index}]"
        if not isinstance(raw, Mapping):
            raise AnalysisError("INVALID_PLAN", f"{context} must be an object.", exit_code=5)
        operation = raw.get("operation")
        if operation == "cast":
            ensure_keys(
                raw,
                required={"operation", "column", "to", "reason"},
                allowed={"operation", "column", "to", "format", "on_error", "reason"},
                context=context,
            )
            target = raw.get("to")
            if target not in {"string", "number", "integer", "boolean", "date", "datetime"}:
                raise unsupported_operation(target, f"{context}.to")
            on_error = raw.get("on_error", "raise")
            if on_error not in {"raise", "coerce"}:
                raise AnalysisError(
                    "INVALID_PLAN",
                    f"{context}.on_error is invalid.",
                    details={"on_error": on_error},
                    exit_code=5,
                )
            date_format = raw.get("format")
            if target in {"date", "datetime"}:
                date_format = require_string(date_format, f"{context}.format", max_length=128)
            elif date_format is not None:
                raise AnalysisError(
                    "INVALID_PLAN",
                    f"{context}.format is only valid for date casts.",
                    details={},
                    exit_code=5,
                )
            cleaning.append(
                {
                    "operation": operation,
                    "column": require_column(raw.get("column"), source_columns, f"{context}.column"),
                    "to": target,
                    "format": date_format,
                    "on_error": on_error,
                    "reason": require_string(raw.get("reason"), f"{context}.reason", max_length=1000),
                }
            )
        elif operation == "fill_missing":
            ensure_keys(
                raw,
                required={"operation", "column", "value", "reason"},
                allowed={"operation", "column", "value", "reason"},
                context=context,
            )
            fill_value = normalize_scalar(raw.get("value"), f"{context}.value")
            if fill_value is None:
                raise AnalysisError(
                    "INVALID_PLAN",
                    f"{context}.value cannot be null.",
                    details={},
                    exit_code=5,
                )
            cleaning.append(
                {
                    "operation": operation,
                    "column": require_column(raw.get("column"), source_columns, f"{context}.column"),
                    "value": fill_value,
                    "reason": require_string(raw.get("reason"), f"{context}.reason", max_length=1000),
                }
            )
        elif operation == "drop_missing":
            ensure_keys(
                raw,
                required={"operation", "columns", "reason"},
                allowed={"operation", "columns", "how", "reason"},
                context=context,
            )
            columns = require_string_list(raw.get("columns"), f"{context}.columns", allow_empty=False)
            for column in columns:
                require_column(column, source_columns, f"{context}.columns")
            how = raw.get("how", "any")
            if how not in {"any", "all"}:
                raise AnalysisError(
                    "INVALID_PLAN", f"{context}.how is invalid.", details={"how": how}, exit_code=5
                )
            cleaning.append(
                {
                    "operation": operation,
                    "columns": columns,
                    "how": how,
                    "reason": require_string(raw.get("reason"), f"{context}.reason", max_length=1000),
                }
            )
        elif operation == "deduplicate":
            ensure_keys(
                raw,
                required={"operation", "reason"},
                allowed={"operation", "subset", "keep", "reason"},
                context=context,
            )
            subset = require_string_list(
                raw.get("subset", [item["id"] for item in profile["columns"]]),
                f"{context}.subset",
                allow_empty=False,
            )
            for column in subset:
                require_column(column, source_columns, f"{context}.subset")
            keep = raw.get("keep", "first")
            if keep not in {"first", "last"}:
                raise AnalysisError(
                    "INVALID_PLAN", f"{context}.keep is invalid.", details={"keep": keep}, exit_code=5
                )
            cleaning.append(
                {
                    "operation": operation,
                    "subset": subset,
                    "keep": keep,
                    "reason": require_string(raw.get("reason"), f"{context}.reason", max_length=1000),
                }
            )
        else:
            raise unsupported_operation(operation, context)

    filters_value = plan.get("filters", [])
    if not isinstance(filters_value, list) or len(filters_value) > MAX_PLAN_STEPS:
        raise AnalysisError(
            "INVALID_PLAN", "filters must be a bounded array.", details={"max_steps": MAX_PLAN_STEPS}, exit_code=5
        )
    filters: list[dict[str, Any]] = []
    allowed_operators = {
        "eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "between",
        "contains", "starts_with", "ends_with", "is_missing", "not_missing",
    }
    for index, raw in enumerate(filters_value):
        context = f"filters[{index}]"
        if not isinstance(raw, Mapping):
            raise AnalysisError("INVALID_PLAN", f"{context} must be an object.", exit_code=5)
        ensure_keys(
            raw,
            required={"column", "operator"},
            allowed={"column", "operator", "value", "case_sensitive"},
            context=context,
        )
        operator = raw.get("operator")
        if operator not in allowed_operators:
            raise unsupported_operation(operator, f"{context}.operator")
        has_value = "value" in raw
        if operator in {"is_missing", "not_missing"} and has_value:
            raise AnalysisError(
                "INVALID_PLAN", f"{context} must not declare value for a missing-value operator.", exit_code=5
            )
        if operator not in {"is_missing", "not_missing"} and not has_value:
            raise AnalysisError("INVALID_PLAN", f"{context} must declare value.", exit_code=5)
        raw_value = raw.get("value")
        if operator == "between":
            if not isinstance(raw_value, list) or len(raw_value) != 2:
                raise AnalysisError("INVALID_PLAN", f"{context}.value must contain two bounds.", exit_code=5)
            filter_value = [normalize_scalar(item, f"{context}.value") for item in raw_value]
        elif operator in {"in", "not_in"}:
            if not isinstance(raw_value, list) or not raw_value:
                raise AnalysisError("INVALID_PLAN", f"{context}.value must be a non-empty array.", exit_code=5)
            filter_value = [normalize_scalar(item, f"{context}.value") for item in raw_value]
        elif has_value:
            filter_value = normalize_scalar(raw_value, f"{context}.value")
        else:
            filter_value = None
        case_sensitive = raw.get("case_sensitive", True)
        if not isinstance(case_sensitive, bool):
            raise AnalysisError("INVALID_PLAN", f"{context}.case_sensitive must be boolean.", exit_code=5)
        if "case_sensitive" in raw and operator not in {"contains", "starts_with", "ends_with"}:
            raise AnalysisError(
                "INVALID_PLAN",
                f"{context}.case_sensitive is supported only for literal string-pattern filters.",
                exit_code=5,
            )
        values_to_check = filter_value if isinstance(filter_value, list) else [filter_value]
        if operator not in {"is_missing", "not_missing"} and any(
            item is None for item in values_to_check
        ):
            raise AnalysisError(
                "INVALID_PLAN",
                f"{context} must use is_missing or not_missing instead of a null value.",
                exit_code=5,
            )
        filters.append(
            {
                "column": require_column(raw.get("column"), source_columns, f"{context}.column"),
                "operator": operator,
                "value": filter_value,
                "case_sensitive": case_sensitive,
            }
        )

    time_bucket_raw = plan.get("time_bucket")
    time_bucket: dict[str, Any] | None = None
    derived_columns: set[str] = set()
    if time_bucket_raw is not None:
        if not isinstance(time_bucket_raw, Mapping):
            raise AnalysisError("INVALID_PLAN", "time_bucket must be null or an object.", exit_code=5)
        ensure_keys(
            time_bucket_raw,
            required={"column", "frequency", "output"},
            allowed={"column", "frequency", "output"},
            context="time_bucket",
        )
        frequency = time_bucket_raw.get("frequency")
        if frequency not in {"day", "week", "month", "quarter", "year"}:
            raise unsupported_operation(frequency, "time_bucket.frequency")
        output = require_output_name(time_bucket_raw.get("output"), "time_bucket.output")
        if output in source_columns:
            raise AnalysisError(
                "INVALID_PLAN", "time_bucket.output collides with a profile column ID.", details={"output": output}, exit_code=5
            )
        derived_columns.add(output)
        time_bucket = {
            "column": require_column(time_bucket_raw.get("column"), source_columns, "time_bucket.column"),
            "frequency": frequency,
            "output": output,
        }

    group_by_value = plan.get("group_by", [])
    if not isinstance(group_by_value, list) or len(group_by_value) > 32:
        raise AnalysisError("INVALID_PLAN", "group_by must be an array of at most 32 items.", exit_code=5)
    group_by: list[dict[str, str]] = []
    result_names: set[str] = set()
    grouped_sources: set[str] = set()
    group_sources = source_columns | derived_columns
    for index, raw in enumerate(group_by_value):
        context = f"group_by[{index}]"
        if not isinstance(raw, Mapping):
            raise AnalysisError("INVALID_PLAN", f"{context} must be an object.", exit_code=5)
        ensure_keys(raw, required={"column", "output"}, allowed={"column", "output"}, context=context)
        column = require_column(raw.get("column"), group_sources, f"{context}.column")
        if column in grouped_sources:
            raise AnalysisError(
                "INVALID_PLAN",
                "A group-by source column may be declared only once.",
                details={"column": column},
                exit_code=5,
            )
        grouped_sources.add(column)
        output = require_output_name(raw.get("output"), f"{context}.output")
        if output in result_names:
            raise AnalysisError("INVALID_PLAN", "Result output names must be unique.", details={"output": output}, exit_code=5)
        result_names.add(output)
        group_by.append({"column": column, "output": output})

    metrics_value = plan.get("metrics")
    if not isinstance(metrics_value, list) or not metrics_value or len(metrics_value) > 64:
        raise AnalysisError("INVALID_PLAN", "metrics must be a non-empty array of at most 64 items.", exit_code=5)
    metrics: list[dict[str, Any]] = []
    for index, raw in enumerate(metrics_value):
        context = f"metrics[{index}]"
        if not isinstance(raw, Mapping):
            raise AnalysisError("INVALID_PLAN", f"{context} must be an object.", exit_code=5)
        ensure_keys(
            raw,
            required={"column", "aggregation", "output"},
            allowed={"column", "aggregation", "output", "unit"},
            context=context,
        )
        aggregation = raw.get("aggregation")
        if aggregation not in {"sum", "mean", "count", "nunique", "min", "max"}:
            raise unsupported_operation(aggregation, f"{context}.aggregation")
        column_value = raw.get("column")
        if column_value == "*":
            if aggregation != "count":
                raise AnalysisError(
                    "INVALID_PLAN", "column '*' is allowed only for count.", details={"context": context}, exit_code=5
                )
            column = "*"
        else:
            column = require_column(column_value, source_columns, f"{context}.column")
        output = require_output_name(raw.get("output"), f"{context}.output")
        if output in result_names:
            raise AnalysisError("INVALID_PLAN", "Result output names must be unique.", details={"output": output}, exit_code=5)
        result_names.add(output)
        unit = raw.get("unit")
        if unit is not None:
            unit = require_string(unit, f"{context}.unit", max_length=40)
        metrics.append({"column": column, "aggregation": aggregation, "output": output, "unit": unit})

    post_value = plan.get("post_calculations", [])
    if not isinstance(post_value, list) or len(post_value) > 64:
        raise AnalysisError("INVALID_PLAN", "post_calculations must be an array of at most 64 items.", exit_code=5)
    post_calculations: list[dict[str, Any]] = []
    for index, raw in enumerate(post_value):
        context = f"post_calculations[{index}]"
        if not isinstance(raw, Mapping):
            raise AnalysisError("INVALID_PLAN", f"{context} must be an object.", exit_code=5)
        operation = raw.get("operation")
        if operation == "share":
            ensure_keys(
                raw,
                required={"operation", "column", "output"},
                allowed={"operation", "column", "output", "partition_by", "as_percent"},
                context=context,
            )
            order_by = None
            periods = None
        elif operation == "pct_change":
            ensure_keys(
                raw,
                required={"operation", "column", "output", "order_by"},
                allowed={"operation", "column", "output", "partition_by", "order_by", "periods", "as_percent"},
                context=context,
            )
            order_by = require_column(raw.get("order_by"), result_names, f"{context}.order_by")
            periods = raw.get("periods", 1)
            if not isinstance(periods, int) or isinstance(periods, bool) or periods <= 0 or periods > 120:
                raise AnalysisError("INVALID_PLAN", f"{context}.periods must be between 1 and 120.", exit_code=5)
        else:
            raise unsupported_operation(operation, context)
        column = require_column(raw.get("column"), result_names, f"{context}.column")
        partition_by = require_string_list(raw.get("partition_by", []), f"{context}.partition_by")
        for partition in partition_by:
            require_column(partition, result_names, f"{context}.partition_by")
        output = require_output_name(raw.get("output"), f"{context}.output")
        if output in result_names:
            raise AnalysisError("INVALID_PLAN", "Result output names must be unique.", details={"output": output}, exit_code=5)
        as_percent = raw.get("as_percent", False)
        if not isinstance(as_percent, bool):
            raise AnalysisError("INVALID_PLAN", f"{context}.as_percent must be boolean.", exit_code=5)
        result_names.add(output)
        post_calculations.append(
            {
                "operation": operation,
                "column": column,
                "output": output,
                "partition_by": partition_by,
                "order_by": order_by,
                "periods": periods,
                "as_percent": as_percent,
            }
        )

    top_n_raw = plan.get("top_n")
    top_n: dict[str, Any] | None = None
    if top_n_raw is not None:
        if not isinstance(top_n_raw, Mapping):
            raise AnalysisError("INVALID_PLAN", "top_n must be null or an object.", exit_code=5)
        ensure_keys(
            top_n_raw,
            required={"count", "by", "direction"},
            allowed={"count", "by", "direction", "per_group"},
            context="top_n",
        )
        count = top_n_raw.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0 or count > 100_000:
            raise AnalysisError("INVALID_PLAN", "top_n.count must be between 1 and 100000.", exit_code=5)
        direction = top_n_raw.get("direction")
        if direction not in {"asc", "desc"}:
            raise AnalysisError("INVALID_PLAN", "top_n.direction must be asc or desc.", exit_code=5)
        per_group = require_string_list(top_n_raw.get("per_group", []), "top_n.per_group")
        for column in per_group:
            require_column(column, result_names, "top_n.per_group")
        top_n = {
            "count": count,
            "by": require_column(top_n_raw.get("by"), result_names, "top_n.by"),
            "direction": direction,
            "per_group": per_group,
        }

    sort_value = plan.get("sort", [])
    if not isinstance(sort_value, list) or len(sort_value) > 32:
        raise AnalysisError("INVALID_PLAN", "sort must be an array of at most 32 items.", exit_code=5)
    sort: list[dict[str, str]] = []
    for index, raw in enumerate(sort_value):
        context = f"sort[{index}]"
        if not isinstance(raw, Mapping):
            raise AnalysisError("INVALID_PLAN", f"{context} must be an object.", exit_code=5)
        ensure_keys(
            raw,
            required={"column", "direction"},
            allowed={"column", "direction", "nulls"},
            context=context,
        )
        direction = raw.get("direction")
        nulls = raw.get("nulls", "last")
        if direction not in {"asc", "desc"} or nulls not in {"first", "last"}:
            raise AnalysisError("INVALID_PLAN", f"{context} direction or null placement is invalid.", exit_code=5)
        sort.append(
            {
                "column": require_column(raw.get("column"), result_names, f"{context}.column"),
                "direction": direction,
                "nulls": nulls,
            }
        )

    chart_raw = plan.get("chart_intent")
    if not isinstance(chart_raw, Mapping):
        raise AnalysisError("INVALID_PLAN", "chart_intent must be an object.", exit_code=5)
    ensure_keys(
        chart_raw,
        required={"analysis_kind", "chart_type", "x", "y"},
        allowed={
            "analysis_kind", "chart_type", "x", "y", "series", "title", "unit",
            "time_range", "source_note", "plot_ready", "sort",
        },
        context="chart_intent",
    )
    analysis_kind = chart_raw.get("analysis_kind")
    if analysis_kind not in {
        "metric", "trend", "comparison", "ranking", "composition", "distribution",
        "relationship", "other", "contribution"
    }:
        raise unsupported_operation(analysis_kind, "chart_intent.analysis_kind")
    chart_type = chart_raw.get("chart_type")
    if chart_type not in {"auto", "line", "bar", "donut", "scatter"}:
        raise unsupported_operation(chart_type, "chart_intent.chart_type")
    x_value = chart_raw.get("x")
    x = None if x_value is None else require_column(x_value, result_names, "chart_intent.x")
    if chart_type in {"line", "donut", "scatter"} and x is None:
        raise AnalysisError("INVALID_PLAN", f"chart type {chart_type} requires chart_intent.x.", exit_code=5)
    y = require_column(chart_raw.get("y"), result_names, "chart_intent.y")
    series_value = chart_raw.get("series")
    series = None if series_value is None else require_column(series_value, result_names, "chart_intent.series")
    chart_sort = chart_raw.get("sort", "none")
    if chart_sort not in {"none", "x-asc", "x-desc", "y-asc", "y-desc"}:
        raise AnalysisError("INVALID_PLAN", "chart_intent.sort is invalid.", exit_code=5)
    if x is None and chart_sort.startswith("x-"):
        raise AnalysisError(
            "INVALID_PLAN", "An x sort requires chart_intent.x.", exit_code=5
        )
    plot_ready = chart_raw.get("plot_ready", True)
    if plot_ready is not True:
        raise AnalysisError("INVALID_PLAN", "chart_intent.plot_ready must be true before execution.", exit_code=5)
    title = chart_raw.get("title", question)
    title = require_string(title, "chart_intent.title", max_length=160)
    unit = chart_raw.get("unit")
    if unit is not None:
        unit = require_string(unit, "chart_intent.unit", max_length=40)
    source_note = chart_raw.get("source_note")
    if source_note is not None:
        source_note = require_string(source_note, "chart_intent.source_note", max_length=240)
    time_range = chart_raw.get("time_range")
    if time_range is not None:
        time_range = require_string(time_range, "chart_intent.time_range", max_length=100)
    chart_intent = {
        "analysis_kind": analysis_kind,
        "chart_type": chart_type,
        "x": x,
        "y": y,
        "series": series,
        "title": title,
        "unit": unit,
        "time_range": time_range,
        "source_note": source_note,
        "plot_ready": True,
        "sort": chart_sort,
    }

    return {
        "schema_version": PLAN_SCHEMA,
        "task_id": task_id,
        "status": "ready",
        "source_sha256": source_sha256,
        "question": question,
        "assumptions": assumptions,
        "cleaning": cleaning,
        "filters": filters,
        "time_bucket": time_bucket,
        "group_by": group_by,
        "metrics": metrics,
        "post_calculations": post_calculations,
        "top_n": top_n,
        "sort": sort,
        "chart_intent": chart_intent,
    }


def read_source(pd: Any, source_path: Path, profile: Mapping[str, Any]) -> Any:
    column_ids = [item["id"] for item in profile["columns"]]
    try:
        frame = pd.read_csv(
            source_path,
            sep=profile["delimiter"],
            encoding=profile["encoding"],
            quotechar=profile["quotechar"],
            header=0,
            names=column_ids,
            dtype="string",
            keep_default_na=False,
            na_filter=False,
            skip_blank_lines=True,
            on_bad_lines="error",
        )
    except (OSError, PermissionError) as exc:
        raise AnalysisError(
            "SOURCE_READ_ERROR",
            "The source CSV could not be read.",
            details={"exception_type": type(exc).__name__},
            exit_code=4,
        ) from None
    except Exception as exc:
        raise AnalysisError(
            "SOURCE_READ_ERROR",
            "pandas could not parse the source CSV using the profiled format.",
            details={"exception_type": type(exc).__name__},
            exit_code=4,
        ) from None
    for column in column_ids:
        series = frame[column]
        blank_mask = series.notna() & series.str.strip().eq("")
        if bool(blank_mask.any()):
            frame.loc[blank_mask, column] = pd.NA
    if len(frame) != profile["row_count"] or len(frame.columns) != profile["column_count"]:
        raise AnalysisError(
            "SOURCE_PROFILE_MISMATCH",
            "The parsed CSV shape does not match input_profile.json.",
            details={
                "profile_rows": profile["row_count"],
                "actual_rows": len(frame),
                "profile_columns": profile["column_count"],
                "actual_columns": len(frame.columns),
            },
            exit_code=4,
        )
    return frame


def conversion_error(column: str, target: str, invalid_count: int) -> AnalysisError:
    return AnalysisError(
        "TYPE_CONVERSION_FAILED",
        "A declared type conversion found invalid non-missing values.",
        details={"column": column, "target_type": target, "invalid_count": invalid_count},
        exit_code=6,
    )


def cast_series(pd: Any, series: Any, step: Mapping[str, Any]) -> tuple[Any, int]:
    target = step["to"]
    original_non_missing = series.notna()
    if target == "string":
        return series.astype("string"), 0
    if target in {"number", "integer"}:
        converted = pd.to_numeric(series, errors="coerce")
        invalid = original_non_missing & converted.isna()
        non_finite = converted.notna() & converted.isin([float("inf"), float("-inf")])
        invalid = invalid | non_finite
        converted = converted.mask(non_finite)
        if target == "integer":
            fractional = converted.notna() & ((converted % 1).abs() > 1e-12)
            invalid = invalid | fractional
            converted = converted.mask(fractional)
        invalid_count = int(invalid.sum())
        if invalid_count and step["on_error"] == "raise":
            raise conversion_error(step["column"], target, invalid_count)
        if target == "integer":
            return converted.astype("Int64"), invalid_count
        return converted.astype("Float64"), invalid_count
    if target == "boolean":
        normalized = series.astype("string").str.strip().str.lower()
        mapping = {
            "true": True, "1": True, "yes": True, "y": True, "是": True, "真": True,
            "false": False, "0": False, "no": False, "n": False, "否": False, "假": False,
        }
        converted = normalized.map(mapping).astype("boolean")
        invalid = original_non_missing & converted.isna()
        invalid_count = int(invalid.sum())
        if invalid_count and step["on_error"] == "raise":
            raise conversion_error(step["column"], target, invalid_count)
        return converted, invalid_count
    if target in {"date", "datetime"}:
        try:
            converted = pd.to_datetime(series, format=step["format"], errors="coerce")
        except Exception:
            raise conversion_error(step["column"], target, int(original_non_missing.sum())) from None
        invalid = original_non_missing & converted.isna()
        invalid_count = int(invalid.sum())
        if invalid_count and step["on_error"] == "raise":
            raise conversion_error(step["column"], target, invalid_count)
        if target == "date":
            converted = converted.dt.normalize()
        return converted, invalid_count
    raise unsupported_operation(target, "cleaning.cast")


def execute_cleaning(pd: Any, frame: Any, steps: Sequence[Mapping[str, Any]]) -> tuple[Any, list[dict[str, Any]]]:
    working = frame.copy()
    audit: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        before = len(working)
        operation = step["operation"]
        entry: dict[str, Any] = {
            "step": index,
            "operation": operation,
            "reason": step["reason"],
            "rows_before": before,
        }
        try:
            if operation == "cast":
                converted, invalid_count = cast_series(pd, working[step["column"]], step)
                working[step["column"]] = converted
                entry.update(
                    {
                        "column": step["column"],
                        "target_type": step["to"],
                        "invalid_count": invalid_count,
                        "values_affected": int(converted.notna().sum()),
                    }
                )
            elif operation == "fill_missing":
                missing_before = int(working[step["column"]].isna().sum())
                working[step["column"]] = working[step["column"]].fillna(step["value"])
                entry.update({"column": step["column"], "values_affected": missing_before})
            elif operation == "drop_missing":
                working = working.dropna(subset=step["columns"], how=step["how"])
                entry.update({"columns": step["columns"], "how": step["how"]})
            elif operation == "deduplicate":
                working = working.drop_duplicates(subset=step["subset"], keep=step["keep"])
                entry.update({"subset": step["subset"], "keep": step["keep"]})
            else:
                raise unsupported_operation(operation, "cleaning")
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError(
                "TYPE_CONVERSION_FAILED" if operation == "cast" else "INVALID_PLAN",
                "A declared cleaning operation could not be applied.",
                details={"step": index, "operation": operation, "exception_type": type(exc).__name__},
                exit_code=6,
            ) from None
        after = len(working)
        entry.update({"rows_after": after, "rows_removed": before - after})
        audit.append(entry)
    return working, audit


def coerce_filter_value(pd: Any, series: Any, value: Any, column: str) -> Any:
    try:
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            if not isinstance(value, str) or re.fullmatch(
                r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)?",
                value,
            ) is None:
                raise ValueError("datetime filter values must be ISO-8601")
            return pd.Timestamp(value)
        if pd.api.types.is_bool_dtype(series.dtype):
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().lower()
            if normalized in {"true", "1", "yes", "y", "是", "真"}:
                return True
            if normalized in {"false", "0", "no", "n", "否", "假"}:
                return False
            raise ValueError("invalid boolean")
        if pd.api.types.is_numeric_dtype(series.dtype):
            if isinstance(value, bool):
                raise ValueError("boolean is not a numeric filter value")
            return float(value)
        return str(value)
    except (TypeError, ValueError, OverflowError):
        raise AnalysisError(
            "FILTER_FAILED",
            "A filter value is incompatible with its typed column.",
            details={"column": column},
            exit_code=6,
        ) from None


def build_filter_mask(pd: Any, series: Any, step: Mapping[str, Any]) -> Any:
    operator = step["operator"]
    if operator == "is_missing":
        return series.isna()
    if operator == "not_missing":
        return series.notna()
    if operator in {"contains", "starts_with", "ends_with"}:
        needle = str(step["value"])
        string_series = series.astype("string")
        if operator == "contains":
            return string_series.str.contains(
                needle, case=step["case_sensitive"], regex=False, na=False
            )
        if not step["case_sensitive"]:
            string_series = string_series.str.casefold()
            needle = needle.casefold()
        if operator == "starts_with":
            return string_series.str.startswith(needle, na=False)
        return string_series.str.endswith(needle, na=False)
    if operator in {"in", "not_in"}:
        values = [coerce_filter_value(pd, series, value, step["column"]) for value in step["value"]]
        mask = series.isin(values)
        if operator == "not_in":
            mask = series.notna() & ~mask
        return mask
    if operator == "between":
        lower = coerce_filter_value(pd, series, step["value"][0], step["column"])
        upper = coerce_filter_value(pd, series, step["value"][1], step["column"])
        return series.notna() & series.between(lower, upper, inclusive="both")
    value = coerce_filter_value(pd, series, step["value"], step["column"])
    if operator == "eq":
        return series.notna() & series.eq(value)
    if operator == "ne":
        return series.notna() & series.ne(value)
    if operator == "gt":
        return series.notna() & series.gt(value)
    if operator == "gte":
        return series.notna() & series.ge(value)
    if operator == "lt":
        return series.notna() & series.lt(value)
    if operator == "lte":
        return series.notna() & series.le(value)
    raise unsupported_operation(operator, "filters")


def execute_filters(pd: Any, frame: Any, steps: Sequence[Mapping[str, Any]]) -> tuple[Any, list[dict[str, Any]]]:
    working = frame
    audit: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        before = len(working)
        try:
            mask = build_filter_mask(pd, working[step["column"]], step).fillna(False)
            working = working.loc[mask]
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError(
                "FILTER_FAILED",
                "A declared filter could not be applied.",
                details={
                    "step": index,
                    "column": step["column"],
                    "operator": step["operator"],
                    "exception_type": type(exc).__name__,
                },
                exit_code=6,
            ) from None
        after = len(working)
        audit.append(
            {
                "step": index,
                "column": step["column"],
                "operator": step["operator"],
                "rows_before": before,
                "rows_after": after,
                "rows_removed": before - after,
            }
        )
    return working, audit


def apply_time_bucket(pd: Any, frame: Any, spec: Mapping[str, Any] | None) -> Any:
    if spec is None:
        return frame
    series = frame[spec["column"]]
    if not pd.api.types.is_datetime64_any_dtype(series.dtype):
        raise AnalysisError(
            "INVALID_PLAN",
            "time_bucket.column must be cast to date or datetime first.",
            details={"column": spec["column"]},
            exit_code=6,
        )
    frequency = spec["frequency"]
    result = frame.copy()
    if frequency == "day":
        bucket = series.dt.normalize()
    elif frequency == "week":
        bucket = series.dt.normalize() - pd.to_timedelta(series.dt.weekday, unit="D")
    elif frequency == "month":
        bucket = series.dt.to_period("M").dt.to_timestamp()
    elif frequency == "quarter":
        bucket = series.dt.to_period("Q").dt.start_time
    elif frequency == "year":
        bucket = series.dt.to_period("Y").dt.start_time
    else:
        raise unsupported_operation(frequency, "time_bucket.frequency")
    result[spec["output"]] = bucket
    return result


def aggregate_scalar(series: Any, aggregation: str) -> Any:
    if aggregation == "sum":
        return series.sum(min_count=1)
    if aggregation == "mean":
        return series.mean()
    if aggregation == "count":
        return series.count()
    if aggregation == "nunique":
        return series.nunique(dropna=True)
    if aggregation == "min":
        return series.min()
    if aggregation == "max":
        return series.max()
    raise unsupported_operation(aggregation, "metrics.aggregation")


def sum_with_missing_preserved(series: Any) -> Any:
    """Keep an all-missing group missing instead of coercing it to zero."""
    return series.sum(min_count=1)


def execute_aggregation(pd: Any, frame: Any, plan: Mapping[str, Any]) -> Any:
    for metric in plan["metrics"]:
        if metric["aggregation"] in {"sum", "mean"}:
            if metric["column"] == "*" or not pd.api.types.is_numeric_dtype(frame[metric["column"]].dtype):
                raise AnalysisError(
                    "AGGREGATION_FAILED",
                    "sum and mean require a numeric column cast in the cleaning plan.",
                    details={"column": metric["column"], "aggregation": metric["aggregation"]},
                    exit_code=6,
                )
    group_columns = [item["column"] for item in plan["group_by"]]
    try:
        if group_columns:
            named_aggregations: dict[str, tuple[str, str]] = {}
            fallback_column = frame.columns[0]
            for metric in plan["metrics"]:
                if metric["column"] == "*":
                    named_aggregations[metric["output"]] = (fallback_column, "size")
                elif metric["aggregation"] == "sum":
                    named_aggregations[metric["output"]] = (
                        metric["column"], sum_with_missing_preserved
                    )
                else:
                    named_aggregations[metric["output"]] = (
                        metric["column"], metric["aggregation"]
                    )
            result = (
                frame.groupby(group_columns, dropna=False, sort=False)
                .agg(**named_aggregations)
                .reset_index()
            )
            rename_map = {item["column"]: item["output"] for item in plan["group_by"]}
            result = result.rename(columns=rename_map)
        else:
            row: dict[str, Any] = {}
            for metric in plan["metrics"]:
                if metric["column"] == "*":
                    row[metric["output"]] = len(frame)
                else:
                    row[metric["output"]] = aggregate_scalar(
                        frame[metric["column"]], metric["aggregation"]
                    )
            result = pd.DataFrame([row])
    except AnalysisError:
        raise
    except Exception as exc:
        raise AnalysisError(
            "AGGREGATION_FAILED",
            "The declared grouped metrics could not be computed.",
            details={"exception_type": type(exc).__name__},
            exit_code=6,
        ) from None
    return result


def execute_post_calculations(
    pd: Any, result: Any, steps: Sequence[Mapping[str, Any]]
) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]]]:
    calculated = result.copy()
    audit: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        column = step["column"]
        if not pd.api.types.is_numeric_dtype(calculated[column].dtype):
            raise AnalysisError(
                "AGGREGATION_FAILED",
                "A post calculation requires a numeric result column.",
                details={"step": index, "column": column, "operation": step["operation"]},
                exit_code=6,
            )
        operation = step["operation"]
        zero_count = 0
        try:
            if operation == "share":
                if step["partition_by"]:
                    denominator = calculated.groupby(
                        step["partition_by"], dropna=False
                    )[column].transform("sum")
                else:
                    denominator = calculated[column].sum()
                if hasattr(denominator, "eq"):
                    zero_mask = denominator.eq(0)
                    zero_count = int(zero_mask.sum())
                    values = calculated[column].div(denominator.mask(zero_mask))
                elif denominator == 0:
                    zero_count = len(calculated)
                    values = calculated[column] * float("nan")
                else:
                    values = calculated[column] / denominator
            elif operation == "pct_change":
                order_columns = [*step["partition_by"], step["order_by"]]
                calculated = calculated.sort_values(order_columns, kind="mergesort", na_position="last")
                if step["partition_by"]:
                    previous = calculated.groupby(step["partition_by"], dropna=False)[column].shift(
                        step["periods"]
                    )
                    values = calculated.groupby(step["partition_by"], dropna=False)[column].pct_change(
                        periods=step["periods"], fill_method=None
                    )
                else:
                    previous = calculated[column].shift(step["periods"])
                    values = calculated[column].pct_change(
                        periods=step["periods"], fill_method=None
                    )
                infinite_mask = values.isin([float("inf"), float("-inf")])
                zero_denominator_mask = previous.eq(0) & calculated[column].notna()
                zero_count = int((infinite_mask | zero_denominator_mask.fillna(False)).sum())
                values = values.mask(infinite_mask | zero_denominator_mask.fillna(False))
            else:
                raise unsupported_operation(operation, "post_calculations")
            if step["as_percent"]:
                values = values * 100.0
            calculated[step["output"]] = values.astype("Float64")
        except AnalysisError:
            raise
        except Exception as exc:
            raise AnalysisError(
                "AGGREGATION_FAILED",
                "A post calculation could not be computed.",
                details={"step": index, "operation": operation, "exception_type": type(exc).__name__},
                exit_code=6,
            ) from None
        audit.append(
            {
                "step": index,
                "operation": operation,
                "column": column,
                "output": step["output"],
                "partition_by": step["partition_by"],
                "order_by": step["order_by"],
                "periods": step["periods"],
                "as_percent": step["as_percent"],
                "zero_denominator_count": zero_count,
            }
        )
        if zero_count:
            warnings.append(
                {
                    "code": "DIVIDE_BY_ZERO",
                    "severity": "warning",
                    "operation": operation,
                    "output": step["output"],
                    "affected_count": zero_count,
                    "message": "Zero denominators were serialized as empty values.",
                }
            )
    return calculated, audit, warnings


def apply_top_n_and_sort(result: Any, plan: Mapping[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    selected = result
    top_n = plan["top_n"]
    top_audit: dict[str, Any] | None = None
    if top_n is not None:
        before = len(selected)
        sort_columns = [*top_n["per_group"], top_n["by"]]
        ascending = [True] * len(top_n["per_group"]) + [top_n["direction"] == "asc"]
        selected = selected.sort_values(
            sort_columns, ascending=ascending, kind="mergesort", na_position="last"
        )
        if top_n["per_group"]:
            selected = selected.groupby(top_n["per_group"], dropna=False, sort=False).head(top_n["count"])
        else:
            selected = selected.head(top_n["count"])
        top_audit = {
            "operation": "top_n",
            "by": top_n["by"],
            "direction": top_n["direction"],
            "per_group": top_n["per_group"],
            "count": top_n["count"],
            "rows_before": before,
            "rows_after": len(selected),
        }
    for spec in reversed(plan["sort"]):
        selected = selected.sort_values(
            spec["column"],
            ascending=spec["direction"] == "asc",
            kind="mergesort",
            na_position=spec["nulls"],
        )
    return selected.reset_index(drop=True), top_audit


def result_type(pd: Any, series: Any, *, is_time: bool) -> str:
    if is_time:
        return "date"
    if pd.api.types.is_integer_dtype(series.dtype):
        return "integer"
    if pd.api.types.is_numeric_dtype(series.dtype):
        return "number"
    if pd.api.types.is_bool_dtype(series.dtype):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "datetime"
    return "string"


def build_result_schema(pd: Any, result: Any, plan: Mapping[str, Any]) -> dict[str, Any]:
    time_output = plan["time_bucket"]["output"] if plan["time_bucket"] else None
    group_outputs = {item["output"] for item in plan["group_by"]}
    units = {item["output"]: item["unit"] for item in plan["metrics"]}
    for item in plan["post_calculations"]:
        units[item["output"]] = "%" if item["as_percent"] else "ratio"
    columns: list[dict[str, Any]] = []
    for name in result.columns:
        if name == time_output:
            role = "time"
        elif name in group_outputs:
            role = "dimension"
        else:
            role = "metric"
        columns.append(
            {
                "name": name,
                "type": result_type(pd, result[name], is_time=name == time_output),
                "role": role,
                "unit": units.get(name),
                "nullable": bool(result[name].isna().any()),
            }
        )
    return {"row_count": len(result), "columns": columns}


def serialize_result_frame(pd: Any, result: Any, schema: Mapping[str, Any]) -> Any:
    serialized = result.copy()
    types = {item["name"]: item["type"] for item in schema["columns"]}
    for name in serialized.columns:
        if types[name] == "date" and pd.api.types.is_datetime64_any_dtype(serialized[name].dtype):
            serialized[name] = serialized[name].dt.strftime("%Y-%m-%d")
        elif types[name] == "datetime" and pd.api.types.is_datetime64_any_dtype(serialized[name].dtype):
            serialized[name] = serialized[name].dt.strftime("%Y-%m-%dT%H:%M:%S")
    return serialized


def json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if type(value).__name__ in {"NAType", "NaTType"}:
        return None
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, bool):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value)
    return text


def display_scalar(value: Any) -> str:
    scalar = json_scalar(value)
    if scalar is None:
        return "空值"
    if isinstance(scalar, float):
        return format(scalar, ".15g")
    return str(scalar)


def build_findings(pd: Any, result: Any, schema: Mapping[str, Any], chart_intent: Mapping[str, Any]) -> list[dict[str, Any]]:
    y = chart_intent["y"]
    numeric = pd.to_numeric(result[y], errors="coerce")
    finite_mask = numeric.notna() & ~numeric.isin([float("inf"), float("-inf")])
    if not bool(finite_mask.any()):
        raise AnalysisError(
            "NO_FINITE_METRIC",
            "The chart metric has no finite result value.",
            details={"column": y},
            exit_code=6,
        )
    dimension_columns = [
        item["name"] for item in schema["columns"] if item["role"] in {"dimension", "time"}
    ]
    finite_values = numeric[finite_mask]
    max_index = finite_values.idxmax()
    min_index = finite_values.idxmin()
    indexes = [("最大值", max_index)]
    if min_index != max_index:
        indexes.append(("最小值", min_index))
    findings: list[dict[str, Any]] = []
    for finding_index, (label, row_index) in enumerate(indexes, start=1):
        selector = {
            column: json_scalar(result.at[row_index, column]) for column in dimension_columns
        }
        selector_text = "、".join(
            f"{column}={display_scalar(result.at[row_index, column])}"
            for column in dimension_columns
        ) or "汇总结果"
        expected = json_scalar(result.at[row_index, y])
        findings.append(
            {
                "id": f"finding-{finding_index:03d}",
                "text": f"{selector_text} 的 {y} 为{label} {display_scalar(expected)}。",
                "evidence": [
                    {
                        "selector": selector,
                        "column": y,
                        "expected": expected,
                        "abs_tol": 1e-9,
                        "rel_tol": 1e-9,
                    }
                ],
            }
        )
    return findings


def csv_scalar_matches(cell: str, expected: Any, abs_tol: float, rel_tol: float) -> bool:
    if expected is None:
        return cell == ""
    if isinstance(expected, bool):
        return cell.strip().lower() == str(expected).lower()
    if isinstance(expected, numbers.Real):
        try:
            actual = float(cell)
        except (TypeError, ValueError):
            return False
        return math.isclose(actual, float(expected), abs_tol=abs_tol, rel_tol=rel_tol)
    return cell == str(expected)


def validate_serialized_findings(result_path: Path, findings: Sequence[Mapping[str, Any]]) -> None:
    try:
        with result_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "The staged result CSV could not be read back for validation.",
            details={"exception_type": type(exc).__name__},
            exit_code=6,
        ) from None
    for finding in findings:
        for evidence in finding["evidence"]:
            selector = evidence["selector"]
            matches = []
            for row in rows:
                if all(csv_scalar_matches(row.get(key, ""), value, 1e-12, 1e-12) for key, value in selector.items()):
                    matches.append(row)
            if len(matches) != 1 or not csv_scalar_matches(
                matches[0].get(evidence["column"], "") if matches else "",
                evidence["expected"],
                evidence["abs_tol"],
                evidence["rel_tol"],
            ):
                raise AnalysisError(
                    "OUTPUT_WRITE_ERROR",
                    "A generated finding cannot be verified against result.csv.",
                    details={"finding_id": finding["id"]},
                    exit_code=6,
                )


def normalize_chart_intent(
    pd: Any,
    chart_intent: Mapping[str, Any],
    result: Any,
    source_path: Path,
    metric_units: Mapping[str, Any],
) -> dict[str, Any]:
    x = chart_intent["x"]
    chart_type = chart_intent["chart_type"]
    if x is None and (len(result) != 1 or chart_type not in {"auto", "bar"}):
        raise AnalysisError(
            "INVALID_PLAN",
            "chart_intent.x may be null only for a one-row auto or bar result.",
            details={"row_count": len(result), "chart_type": chart_type},
            exit_code=6,
        )
    y = chart_intent["y"]
    if not pd.api.types.is_numeric_dtype(result[y].dtype):
        raise AnalysisError(
            "INVALID_PLAN",
            "chart_intent.y must reference a numeric result column.",
            details={"column": y},
            exit_code=6,
        )
    y_numeric = pd.to_numeric(result[y], errors="coerce")
    if bool(y_numeric.isna().any()) or bool(
        y_numeric.isin([float("inf"), float("-inf")]).any()
    ):
        raise AnalysisError(
            "NO_FINITE_METRIC",
            "chart_intent.y must contain a finite value in every result row.",
            details={"column": y, "invalid_count": int(y_numeric.isna().sum())},
            exit_code=6,
        )
    series = chart_intent.get("series")
    if x is None and series is not None:
        raise AnalysisError(
            "INVALID_PLAN",
            "A one-row chart with x=null cannot declare series.",
            details={"series": series},
            exit_code=6,
        )
    if series is not None and series in {x, y}:
        raise AnalysisError(
            "INVALID_PLAN",
            "chart_intent.series must differ from x and y.",
            details={"series": series},
            exit_code=6,
        )
    for role, column in (("x", x), ("series", series)):
        if column is not None:
            blank = result[column].isna() | result[column].astype("string").str.strip().eq("")
            if bool(blank.any()):
                raise AnalysisError(
                    "INVALID_PLAN",
                    f"chart_intent.{role} contains blank result values.",
                    details={"column": column, "blank_count": int(blank.sum())},
                    exit_code=6,
                )

    analysis_kind = chart_intent["analysis_kind"]
    selected_type = chart_type
    if chart_type == "auto":
        if x is None:
            selected_type = "bar"
        elif analysis_kind == "trend":
            selected_type = "line"
        elif analysis_kind in {"metric", "comparison", "ranking", "contribution"}:
            selected_type = "bar"
        elif analysis_kind == "composition":
            compact_donut = (
                series is None
                and 2 <= int(result[x].nunique(dropna=False)) <= 8
                and not bool(result[x].duplicated().any())
                and bool((y_numeric >= 0).all())
                and bool((y_numeric > 0).any())
            )
            selected_type = "donut" if compact_donut else "bar"
        elif analysis_kind == "relationship":
            selected_type = "scatter"
        elif analysis_kind == "distribution":
            selected_type = "bar"
        else:
            x_numeric = pd.to_numeric(result[x], errors="coerce")
            selected_type = (
                "scatter"
                if not bool(x_numeric.isna().any())
                and not bool(x_numeric.isin([float("inf"), float("-inf")]).any())
                else "bar"
            )

    if selected_type in {"line", "bar", "donut"} and x is not None:
        key_columns = [x]
        if series is not None and selected_type in {"line", "bar"}:
            key_columns.append(series)
        duplicate_count = int(result.duplicated(subset=key_columns, keep=False).sum())
        if duplicate_count:
            raise AnalysisError(
                "INVALID_PLAN",
                f"A {selected_type} chart requires unique plot keys.",
                details={
                    "chart_type": selected_type,
                    "key_columns": key_columns,
                    "duplicate_row_count": duplicate_count,
                },
                exit_code=6,
            )
    if selected_type == "bar" and x is not None:
        category_count = int(result[x].nunique(dropna=False))
        if category_count > 50:
            raise AnalysisError(
                "RESULT_TOO_LARGE",
                "A bar result exceeds the renderer's category limit.",
                details={"category_count": category_count, "maximum": 50},
                exit_code=6,
            )
    if selected_type == "donut":
        if x is None or series is not None:
            raise AnalysisError(
                "INVALID_PLAN",
                "A donut result requires x and does not allow series.",
                details={},
                exit_code=6,
            )
        category_count = int(result[x].nunique(dropna=False))
        if not 2 <= category_count <= 8 or bool((y_numeric < 0).any()) or not bool(
            (y_numeric > 0).any()
        ):
            raise AnalysisError(
                "INVALID_PLAN",
                "A donut result requires 2-8 categories and nonnegative values with one positive value.",
                details={"category_count": category_count},
                exit_code=6,
            )
    if selected_type == "scatter":
        if x is None:
            raise AnalysisError(
                "INVALID_PLAN", "A scatter result requires chart_intent.x.", exit_code=6
            )
        x_numeric = pd.to_numeric(result[x], errors="coerce")
        if bool(x_numeric.isna().any()) or bool(
            x_numeric.isin([float("inf"), float("-inf")]).any()
        ):
            raise AnalysisError(
                "INVALID_PLAN",
                "A scatter result requires finite numeric x values.",
                details={"column": x},
                exit_code=6,
            )
    if series is not None:
        series_count = int(result[series].nunique(dropna=False))
        if series_count > 12:
            raise AnalysisError(
                "RESULT_TOO_LARGE",
                "The result exceeds the renderer's series limit.",
                details={"series_count": series_count, "maximum": 12},
                exit_code=6,
            )
    source_name = os.fspath(source_path).replace("\\", "/").rsplit("/", 1)[-1]
    normalized = dict(chart_intent)
    normalized["unit"] = normalized.get("unit") or metric_units.get(y)
    default_source_note = f"数据来源：{source_name}"
    if len(default_source_note) > 240:
        default_source_note = default_source_note[:237] + "..."
    normalized["source_note"] = normalized.get("source_note") or default_source_note
    normalized["plot_ready"] = True
    return normalized


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def render_generated_code(plan: Mapping[str, Any], plan_sha256: str, source_sha256: str) -> str:
    plan_json = canonical_json(plan)
    return (
        '"""Deterministic compilation record for one ChartPilot analysis.\n\n'
        "Execute the calculations with the chartpilot-analyze-data bundled runner.\n"
        'This file contains no source rows and performs no file, network, or shell access.\n"""\n\n'
        "from __future__ import annotations\n\n"
        "import json\n\n"
        f"RUNNER_VERSION = {SCRIPT_VERSION!r}\n"
        f"PLAN_SHA256 = {plan_sha256!r}\n"
        f"SOURCE_SHA256 = {source_sha256!r}\n"
        f"_PLAN_JSON = {plan_json!r}\n\n"
        "def get_analysis_plan():\n"
        "    \"\"\"Return an isolated copy of the validated executable plan.\"\"\"\n"
        "    return json.loads(_PLAN_JSON)\n\n"
        "if __name__ == \"__main__\":\n"
        "    print(json.dumps(get_analysis_plan(), ensure_ascii=False, sort_keys=True, indent=2))\n"
    )


def make_temp_path(output_dir: Path, destination_name: str) -> Path:
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{destination_name}.", suffix=".tmp", dir=output_dir
        )
        os.close(descriptor)
        return Path(name)
    except (OSError, PermissionError) as exc:
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "A temporary output file could not be created.",
            details={"artifact": destination_name, "exception_type": type(exc).__name__},
            exit_code=6,
        ) from None


def fsync_path(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def write_text_temp(path: Path, text: str, encoding: str = "utf-8") -> None:
    try:
        with path.open("w", encoding=encoding, newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, PermissionError) as exc:
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "An output artifact could not be staged.",
            details={"exception_type": type(exc).__name__},
            exit_code=6,
        ) from None


def write_json_temp(path: Path, value: Mapping[str, Any]) -> None:
    text = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    write_text_temp(path, text)


def write_csv_temp(frame: Any, path: Path, headers: Sequence[str] | None = None) -> None:
    try:
        frame.to_csv(
            path,
            index=False,
            header=list(headers) if headers is not None else True,
            encoding="utf-8-sig",
            lineterminator="\n",
            na_rep="",
            float_format="%.15g",
        )
        fsync_path(path)
    except (OSError, PermissionError, ValueError) as exc:
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "A CSV output artifact could not be staged.",
            details={"exception_type": type(exc).__name__},
            exit_code=6,
        ) from None


def safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def install_artifact(temp_path: Path, destination: Path) -> None:
    try:
        os.replace(temp_path, destination)
    except (OSError, PermissionError) as exc:
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "A staged output artifact could not be installed atomically.",
            details={"artifact": destination.name, "exception_type": type(exc).__name__},
            exit_code=6,
        ) from None


def commit_artifact_set(
    staged: Mapping[str, Path],
    destinations: Mapping[str, Path],
    *,
    installer: Any = install_artifact,
) -> None:
    """Install all managed outputs or restore the complete previous set."""
    required_destinations = {
        "generated_analysis", "cleaned_data", "result_csv", "analysis_result"
    }
    if set(destinations) != required_destinations:
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "The managed artifact destination set is incomplete.",
            details={"destinations": sorted(destinations)},
            exit_code=6,
        )
    if "analysis_result" not in staged or "result_csv" not in staged or "generated_analysis" not in staged:
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "The staged artifact set is incomplete.",
            details={"staged": sorted(staged)},
            exit_code=6,
        )

    backup_order = [
        "analysis_result", "generated_analysis", "cleaned_data", "result_csv"
    ]
    install_order = [
        "generated_analysis", "cleaned_data", "result_csv", "analysis_result"
    ]
    backups: dict[str, Path] = {}
    installed: set[str] = set()
    original_error: BaseException | None = None
    try:
        for name in backup_order:
            destination = destinations[name]
            if destination.exists():
                backup = make_temp_path(destination.parent, f"{destination.name}.backup")
                try:
                    os.replace(destination, backup)
                except (OSError, PermissionError) as exc:
                    safe_unlink(backup)
                    raise AnalysisError(
                        "OUTPUT_WRITE_ERROR",
                        "An existing artifact could not be backed up for transactional commit.",
                        details={"artifact": destination.name, "exception_type": type(exc).__name__},
                        exit_code=6,
                    ) from None
                backups[name] = backup
        for name in install_order:
            if name not in staged:
                continue
            installed.add(name)
            installer(staged[name], destinations[name])
    except BaseException as exc:
        original_error = exc

    if original_error is not None:
        rollback_errors: list[str] = []
        for name in reversed(install_order):
            destination = destinations[name]
            if name in installed and destination.exists():
                try:
                    destination.unlink()
                except (OSError, PermissionError):
                    rollback_errors.append(f"remove:{destination.name}")
        for name in reversed(backup_order):
            backup = backups.get(name)
            if backup is None:
                continue
            try:
                os.replace(backup, destinations[name])
            except (OSError, PermissionError):
                rollback_errors.append(f"restore:{destinations[name].name}")
        for backup in backups.values():
            safe_unlink(backup)
        if rollback_errors:
            raise AnalysisError(
                "OUTPUT_WRITE_ERROR",
                "Artifact commit failed and the previous set could not be fully restored.",
                details={"rollback_errors": rollback_errors},
                exit_code=6,
            ) from None
        if isinstance(original_error, AnalysisError):
            raise original_error
        if isinstance(original_error, (KeyboardInterrupt, SystemExit)):
            raise original_error
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "Artifact-set commit failed; the previous complete set was restored.",
            details={"exception_type": type(original_error).__name__},
            exit_code=6,
        ) from None

    for backup in backups.values():
        safe_unlink(backup)


def execute(args: argparse.Namespace) -> dict[str, Any]:
    require_positive(args.max_json_bytes, "--max-json-bytes")
    require_positive(args.max_source_bytes, "--max-source-bytes")
    require_positive(args.max_result_rows, "--max-result-rows")
    pd = load_pandas()

    profile_path = resolve_existing(args.profile, "input profile", args.allow_unc)
    plan_path = resolve_existing(args.plan, "analysis plan", args.allow_unc)
    if not profile_path.is_file() or not plan_path.is_file():
        raise AnalysisError(
            "FILE_NOT_FOUND",
            "The profile and plan must both be regular files.",
            details={},
            exit_code=3,
        )
    read_roots = [resolve_existing(value, "allowed read root", args.allow_unc) for value in args.allowed_read_root]
    for root in read_roots:
        if not root.is_dir():
            raise AnalysisError("PATH_NOT_ALLOWED", "An allowed read root is not a directory.", exit_code=3)
    enforce_roots(profile_path, read_roots, "input profile")
    enforce_roots(plan_path, read_roots, "analysis plan")

    output_dir = resolve_output_dir(args.output_dir, args.allow_unc)
    if args.allowed_write_root:
        write_root = resolve_existing(args.allowed_write_root, "allowed write root", args.allow_unc)
        if not write_root.is_dir():
            raise AnalysisError("PATH_NOT_ALLOWED", "The allowed write root is not a directory.", exit_code=3)
        enforce_roots(output_dir, [write_root], "output directory")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = output_dir.resolve(strict=True)
    except (OSError, PermissionError) as exc:
        raise AnalysisError(
            "OUTPUT_WRITE_ERROR",
            "The output directory could not be created or opened.",
            details={"exception_type": type(exc).__name__},
            exit_code=6,
        ) from None
    if not output_dir.is_dir():
        raise AnalysisError("OUTPUT_WRITE_ERROR", "The output path is not a directory.", exit_code=6)

    profile_raw = load_json(profile_path, args.max_json_bytes, "input profile")
    profile = validate_profile(profile_raw)
    source_path = resolve_existing(profile["source_path"], "source CSV", args.allow_unc)
    if not source_path.is_file():
        raise AnalysisError("FILE_NOT_FOUND", "The profiled source is not a regular file.", exit_code=4)
    enforce_roots(source_path, read_roots, "source CSV")
    source_size = source_path.stat().st_size
    if source_size > args.max_source_bytes:
        raise AnalysisError(
            "SOURCE_READ_ERROR",
            "The source CSV exceeds the configured analysis size limit.",
            details={"size_bytes": source_size, "max_bytes": args.max_source_bytes},
            exit_code=4,
        )
    if isinstance(profile["source_size_bytes"], int) and profile["source_size_bytes"] != source_size:
        raise AnalysisError(
            "SOURCE_CHANGED",
            "The source CSV size changed after profiling.",
            details={"profile_size_bytes": profile["source_size_bytes"], "actual_size_bytes": source_size},
            exit_code=4,
        )
    actual_source_hash = sha256_file(source_path)
    if actual_source_hash != profile["source_sha256"]:
        raise AnalysisError(
            "SOURCE_HASH_MISMATCH",
            "The source CSV does not match input_profile.json.",
            details={"expected_sha256": profile["source_sha256"], "actual_sha256": actual_source_hash},
            exit_code=4,
        )

    plan_raw = load_json(plan_path, args.max_json_bytes, "analysis plan")
    plan = validate_plan(plan_raw, profile)
    plan_sha256 = sha256_file(plan_path)

    destinations = {
        "generated_analysis": output_dir / "generated_analysis.py",
        "cleaned_data": output_dir / "cleaned_data.csv",
        "result_csv": output_dir / "result.csv",
        "analysis_result": output_dir / "analysis_result.json",
    }
    protected_paths = {profile_path, plan_path, source_path}
    if any(path.resolve(strict=False) in protected_paths for path in destinations.values()):
        raise AnalysisError(
            "PATH_NOT_ALLOWED",
            "A managed output path collides with an input or source file.",
            details={},
            exit_code=3,
        )
    if args.no_overwrite:
        existing = sorted(path.name for path in destinations.values() if path.exists())
        if existing:
            raise AnalysisError(
                "OUTPUT_EXISTS",
                "A managed output artifact already exists.",
                details={"artifacts": existing},
                exit_code=6,
            )

    frame = read_source(pd, source_path, profile)
    cleaned, cleaning_audit = execute_cleaning(pd, frame, plan["cleaning"])
    filtered, filter_audit = execute_filters(pd, cleaned, plan["filters"])
    if filtered.empty:
        raise AnalysisError(
            "EMPTY_RESULT",
            "Cleaning and filtering removed every source row.",
            details={"rows_after_cleaning": len(cleaned), "rows_after_filters": 0},
            exit_code=6,
        )
    bucketed = apply_time_bucket(pd, filtered, plan["time_bucket"])
    result = execute_aggregation(pd, bucketed, plan)
    result, calculation_audit, warnings = execute_post_calculations(
        pd, result, plan["post_calculations"]
    )
    result, top_audit = apply_top_n_and_sort(result, plan)
    if top_audit is not None:
        calculation_audit.append(top_audit)
    if result.empty:
        raise AnalysisError(
            "EMPTY_RESULT",
            "The validated plan produced no result rows.",
            details={"rows_after_cleaning": len(cleaned), "rows_after_filters": len(filtered)},
            exit_code=6,
        )
    if len(result) > args.max_result_rows:
        raise AnalysisError(
            "RESULT_TOO_LARGE",
            "The result exceeds the configured row limit.",
            details={"row_count": len(result), "max_result_rows": args.max_result_rows},
            exit_code=6,
        )
    for column in result.columns:
        if pd.api.types.is_numeric_dtype(result[column].dtype):
            result[column] = result[column].mask(
                result[column].isin([float("inf"), float("-inf")])
            )

    metric_units = {item["output"]: item["unit"] for item in plan["metrics"]}
    for item in plan["post_calculations"]:
        metric_units[item["output"]] = "%" if item["as_percent"] else "ratio"
    chart_intent = normalize_chart_intent(
        pd, plan["chart_intent"], result, source_path, metric_units
    )
    result_schema = build_result_schema(pd, result, plan)
    serialized_result = serialize_result_frame(pd, result, result_schema)
    findings = build_findings(pd, serialized_result, result_schema, chart_intent)

    temp_paths: dict[str, Path] = {}
    try:
        temp_paths["generated_analysis"] = make_temp_path(output_dir, "generated_analysis.py")
        generated_code = render_generated_code(plan, plan_sha256, actual_source_hash)
        write_text_temp(temp_paths["generated_analysis"], generated_code)

        if plan["cleaning"]:
            temp_paths["cleaned_data"] = make_temp_path(output_dir, "cleaned_data.csv")
            source_headers = [item["source_name"] for item in profile["columns"]]
            write_csv_temp(cleaned, temp_paths["cleaned_data"], headers=source_headers)

        temp_paths["result_csv"] = make_temp_path(output_dir, "result.csv")
        write_csv_temp(serialized_result, temp_paths["result_csv"])
        validate_serialized_findings(temp_paths["result_csv"], findings)

        generated_hash = sha256_file(temp_paths["generated_analysis"])
        cleaned_hash = sha256_file(temp_paths["cleaned_data"]) if "cleaned_data" in temp_paths else None
        result_hash = sha256_file(temp_paths["result_csv"])
        artifacts = {
            "generated_analysis": {
                "path": "generated_analysis.py",
                "sha256": generated_hash,
            },
            "cleaned_data": (
                {"path": "cleaned_data.csv", "sha256": cleaned_hash}
                if cleaned_hash is not None
                else None
            ),
            "result_csv": {"path": "result.csv", "sha256": result_hash},
        }
        validation_checks = [
            {"name": "task_id_match", "status": "passed"},
            {"name": "source_hash_before_execution", "status": "passed"},
            {"name": "profile_shape_match", "status": "passed"},
            {"name": "plan_allowlist_validation", "status": "passed"},
            {"name": "result_non_empty", "status": "passed"},
            {"name": "result_finite_chart_metric", "status": "passed"},
            {"name": "finding_evidence_matches_result_csv", "status": "passed"},
            {"name": "source_hash_after_execution", "status": "passed"},
        ]
        analysis_result = {
            "schema_version": RESULT_SCHEMA,
            "task_id": profile["task_id"],
            "stage": "analysis",
            "status": "success",
            "source": {"path": os.fspath(source_path), "sha256": actual_source_hash},
            "plan_sha256": plan_sha256,
            "question": plan["question"],
            "assumptions": plan["assumptions"],
            "artifacts": artifacts,
            "result_schema": result_schema,
            "cleaning_audit": cleaning_audit,
            "filter_audit": filter_audit,
            "calculation_audit": calculation_audit,
            "findings": findings,
            "chart_intent": chart_intent,
            "validation": {
                "passed": True,
                "checks": validation_checks,
                "warnings": warnings,
            },
        }
        temp_paths["analysis_result"] = make_temp_path(output_dir, "analysis_result.json")
        write_json_temp(temp_paths["analysis_result"], analysis_result)

        final_source_hash = sha256_file(source_path)
        if final_source_hash != actual_source_hash:
            raise AnalysisError(
                "SOURCE_CHANGED",
                "The source CSV changed during analysis.",
                details={"before_sha256": actual_source_hash, "after_sha256": final_source_hash},
                exit_code=4,
            )

        commit_artifact_set(temp_paths, destinations)
    finally:
        for temp_path in temp_paths.values():
            safe_unlink(temp_path)

    return {
        "ok": True,
        "task_id": profile["task_id"],
        "analysis_result_path": os.fspath(destinations["analysis_result"]),
        "result_csv_path": os.fspath(destinations["result_csv"]),
        "result_sha256": result_hash,
    }


def main(argv: Sequence[str] | None = None) -> int:
    configure_utf8_streams()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        payload = execute(args)
        emit_json(payload, sys.stdout, pretty=args.pretty)
        return 0
    except AnalysisError as exc:
        emit_json(exc.payload(), sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        emit_json(
            {
                "ok": False,
                "error": {
                    "code": "INTERRUPTED",
                    "message": "Analysis was interrupted.",
                    "details": {},
                },
            },
            sys.stderr,
        )
        return 130
    except Exception as exc:
        emit_json(
            {
                "ok": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected internal error occurred.",
                    "details": {"exception_type": type(exc).__name__},
                },
            },
            sys.stderr,
        )
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
