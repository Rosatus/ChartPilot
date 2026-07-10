#!/usr/bin/env python3
"""Render an auditable chart from a hash-bound ChartPilot analysis result."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import sys
import tempfile
import textwrap
import traceback
import warnings
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Any, Iterable, Sequence


ANALYSIS_SCHEMA = "chartpilot.analysis-result/v1"
CHART_SPEC_SCHEMA = "chartpilot.chart-spec/v1"
CHART_RESULT_SCHEMA = "chartpilot.chart-result/v1"
RENDERER_VERSION = "1.0.0"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
OUTPUT_FILES = (
    "chart_spec.json",
    "generated_chart.py",
    "chart.png",
    "summary.md",
    "chart_result.json",
)
ALLOWED_KINDS = {
    "metric",
    "trend",
    "comparison",
    "ranking",
    "composition",
    "contribution",
    "relationship",
    "distribution",
    "other",
}
ALLOWED_CHART_TYPES = {"auto", "line", "bar", "donut", "scatter"}
ALLOWED_SORTS = {"none", "x-asc", "x-desc", "y-asc", "y-desc"}
MAX_DONUT_CATEGORIES = 8
MAX_BAR_CATEGORIES = 50
MAX_SERIES = 12
COLORS = (
    "#176B87",
    "#D95D39",
    "#2A9D6F",
    "#E9A23B",
    "#5B5F97",
    "#A23E48",
    "#4C78A8",
    "#7A8B5A",
    "#B66D0D",
    "#6C5B7B",
    "#008B8B",
    "#C44E52",
)
CJK_FONT_NAMES = (
    "Microsoft YaHei",
    "DengXian",
    "SimHei",
    "SimSun",
    "Noto Sans CJK SC",
    "Noto Sans CJK",
    "Source Han Sans SC",
    "Source Han Sans",
    "WenQuanYi Zen Hei",
    "Droid Sans Fallback",
    "Arial Unicode MS",
)


class RenderError(Exception):
    """Represent one stable, structured renderer failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = False,
        details: dict[str, Any] | None = None,
        exit_code: int = 2,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.details = details or {}
        self.exit_code = exit_code

    def payload(self) -> dict[str, Any]:
        return {
            "status": "error",
            "stage": "chart",
            "error": {
                "code": self.code,
                "message": self.message,
                "recoverable": self.recoverable,
                "details": self.details,
            },
        }


class StructuredArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RenderError(
            "INVALID_ARGUMENT",
            message,
            recoverable=True,
            details={"usage": self.format_usage().strip()},
        )


def build_parser() -> argparse.ArgumentParser:
    parser = StructuredArgumentParser(
        description=(
            "Render a validated PNG chart from a successful, SHA-256-bound "
            "ChartPilot analysis_result.json."
        )
    )
    parser.add_argument(
        "--analysis-result",
        required=True,
        metavar="PATH",
        help="Path to chartpilot.analysis-result/v1 JSON.",
    )
    parser.add_argument(
        "--output-dir",
        metavar="PATH",
        help="Artifact directory; defaults to the manifest directory.",
    )
    parser.add_argument(
        "--chart-type",
        choices=sorted(ALLOWED_CHART_TYPES),
        help="Override chart_intent.chart_type without bypassing shape checks.",
    )
    parser.add_argument("--title", help="Override the chart title.")
    parser.add_argument(
        "--font-path",
        metavar="PATH",
        help="Explicit local TTF/TTC/OTF font, useful for Chinese text.",
    )
    parser.add_argument("--width", type=float, default=12.0, help="Figure width in inches (4-30).")
    parser.add_argument("--height", type=float, default=7.0, help="Figure height in inches (3-20).")
    parser.add_argument("--dpi", type=int, default=160, help="PNG resolution in DPI (72-600).")
    parser.add_argument(
        "--max-points",
        type=int,
        default=5000,
        help="Reject plot-ready results above this row count; never sample them.",
    )
    parser.add_argument("--debug", action="store_true", help="Include a traceback for unexpected errors.")
    return parser


def load_dependencies() -> SimpleNamespace:
    failures: dict[str, str] = {}
    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - depends on deployment
        failures["pandas"] = str(exc)
        pd = None

    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except Exception as exc:  # pragma: no cover - depends on deployment
        failures["matplotlib"] = str(exc)
        matplotlib = None
        plt = None
        font_manager = None

    try:
        from PIL import Image, ImageChops
    except Exception as exc:  # pragma: no cover - depends on deployment
        failures["Pillow"] = str(exc)
        Image = None
        ImageChops = None

    if failures:
        raise RenderError(
            "DEPENDENCY_MISSING",
            "Required chart-rendering dependencies are unavailable.",
            recoverable=True,
            details={"packages": sorted(failures), "import_errors": failures},
            exit_code=3,
        )

    return SimpleNamespace(
        pd=pd,
        matplotlib=matplotlib,
        plt=plt,
        font_manager=font_manager,
        Image=Image,
        ImageChops=ImageChops,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_size(path: Path) -> int:
    return path.stat().st_size


def write_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_text(path, content)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RenderError(
            "MANIFEST_NOT_FOUND",
            "analysis_result.json does not exist.",
            recoverable=True,
            details={"path": str(path)},
        )
    if not path.is_file():
        raise RenderError(
            "MANIFEST_NOT_FOUND",
            "The analysis result path is not a file.",
            recoverable=True,
            details={"path": str(path)},
        )
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RenderError(
            "INVALID_JSON",
            "analysis_result.json is not valid UTF-8 JSON.",
            recoverable=True,
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    except OSError as exc:
        raise RenderError(
            "INVALID_JSON",
            "analysis_result.json could not be read.",
            recoverable=True,
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    if not isinstance(payload, dict):
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "The analysis result root must be a JSON object.",
            recoverable=True,
        )
    return payload


def require_manifest_contract(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != ANALYSIS_SCHEMA:
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            f"schema_version must be {ANALYSIS_SCHEMA}.",
            recoverable=True,
            details={"actual": manifest.get("schema_version")},
        )
    if manifest.get("stage") != "analysis":
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "stage must be analysis.",
            recoverable=True,
            details={"actual": manifest.get("stage")},
        )
    if manifest.get("status") != "success":
        raise RenderError(
            "ANALYSIS_NOT_SUCCESSFUL",
            "Only a successful analysis result can be rendered.",
            recoverable=True,
            details={"actual": manifest.get("status")},
        )
    task_id = manifest.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 160:
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "task_id must be a nonempty string of at most 160 characters.",
            recoverable=True,
        )


def resolve_result_path(manifest_path: Path, manifest: dict[str, Any]) -> tuple[Path, str, str]:
    artifacts = manifest.get("artifacts")
    result_ref = artifacts.get("result_csv") if isinstance(artifacts, dict) else None
    if not isinstance(result_ref, dict):
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "artifacts.result_csv must be an object.",
            recoverable=True,
        )
    raw_path = result_ref.get("path")
    expected_hash = result_ref.get("sha256")
    if not isinstance(raw_path, str) or not raw_path.strip() or "\x00" in raw_path:
        raise RenderError(
            "INVALID_RESULT_PATH",
            "artifacts.result_csv.path must be a nonempty relative path.",
            recoverable=True,
        )
    if (
        Path(raw_path).is_absolute()
        or PureWindowsPath(raw_path).is_absolute()
        or bool(PureWindowsPath(raw_path).drive)
    ):
        raise RenderError(
            "INVALID_RESULT_PATH",
            "The result CSV path must be relative to the analysis manifest.",
            recoverable=True,
            details={"path": raw_path},
        )

    normalized = raw_path.replace("\\", "/")
    pure_path = PurePosixPath(normalized)
    if any(part == ".." for part in pure_path.parts) or pure_path.name != "result.csv":
        raise RenderError(
            "INVALID_RESULT_PATH",
            "The bound artifact must be a traversal-free relative path named result.csv.",
            recoverable=True,
            details={"path": raw_path},
        )

    base_dir = manifest_path.parent.resolve()
    unresolved = base_dir.joinpath(*pure_path.parts)
    if not unresolved.exists() or not unresolved.is_file():
        raise RenderError(
            "RESULT_NOT_FOUND",
            "The result.csv declared by the analysis manifest does not exist.",
            recoverable=True,
            details={"path": raw_path},
        )
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError as exc:
        raise RenderError(
            "INVALID_RESULT_PATH",
            "The resolved result CSV escapes the analysis task directory.",
            recoverable=False,
            details={"path": raw_path},
        ) from exc

    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "artifacts.result_csv.sha256 must contain 64 hexadecimal characters.",
            recoverable=True,
        )
    actual_hash = sha256_file(resolved)
    if not hmac.compare_digest(actual_hash, expected_hash.lower()):
        raise RenderError(
            "RESULT_HASH_MISMATCH",
            "result.csv does not match the SHA-256 declared by analysis_result.json.",
            recoverable=False,
            details={"expected": expected_hash.lower(), "actual": actual_hash},
        )
    return resolved, normalized, actual_hash


def expected_column_names(result_schema: dict[str, Any]) -> list[str]:
    raw_columns = result_schema.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "result_schema.columns must be a nonempty ordered list.",
            recoverable=True,
        )
    names: list[str] = []
    for index, item in enumerate(raw_columns):
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("name")
        else:
            name = None
        if not isinstance(name, str) or not name:
            raise RenderError(
                "INVALID_ANALYSIS_RESULT",
                "Every result_schema column must have a nonempty name.",
                recoverable=True,
                details={"column_index": index},
            )
        names.append(name)
    return names


def read_and_validate_result(deps: SimpleNamespace, path: Path, manifest: dict[str, Any]) -> Any:
    try:
        frame = deps.pd.read_csv(
            path,
            encoding="utf-8-sig",
            dtype=str,
            keep_default_na=False,
            na_filter=False,
        )
    except Exception as exc:
        raise RenderError(
            "CSV_READ_FAILED",
            "The bound result.csv could not be parsed as UTF-8 CSV.",
            recoverable=True,
            details={"reason": str(exc)},
        ) from exc
    if frame.empty:
        raise RenderError(
            "EMPTY_RESULT",
            "The saved analysis result contains no rows.",
            recoverable=True,
        )
    result_schema = manifest.get("result_schema")
    if not isinstance(result_schema, dict):
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "result_schema must be an object.",
            recoverable=True,
        )
    expected_rows = result_schema.get("row_count")
    if isinstance(expected_rows, bool) or not isinstance(expected_rows, int) or expected_rows < 0:
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "result_schema.row_count must be a nonnegative integer.",
            recoverable=True,
        )
    expected_columns = expected_column_names(result_schema)
    actual_columns = [str(column) for column in frame.columns]
    if expected_rows != len(frame) or expected_columns != actual_columns:
        raise RenderError(
            "RESULT_SCHEMA_MISMATCH",
            "result.csv does not match result_schema.",
            recoverable=False,
            details={
                "expected_row_count": expected_rows,
                "actual_row_count": len(frame),
                "expected_columns": expected_columns,
                "actual_columns": actual_columns,
            },
        )
    return frame


def validate_findings(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    findings = manifest.get("findings")
    if not isinstance(findings, list):
        raise RenderError(
            "INVALID_ANALYSIS_RESULT",
            "findings must be a list.",
            recoverable=True,
        )
    validated: list[dict[str, Any]] = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise RenderError(
                "INVALID_ANALYSIS_RESULT",
                "Every finding must be an object.",
                recoverable=True,
                details={"finding_index": index},
            )
        finding_id = finding.get("id")
        text = finding.get("text")
        evidence = finding.get("evidence")
        if (
            not isinstance(finding_id, str)
            or not finding_id.strip()
            or not isinstance(text, str)
            or not text.strip()
            or not isinstance(evidence, list)
        ):
            raise RenderError(
                "INVALID_ANALYSIS_RESULT",
                "Each finding requires nonempty id/text strings and list-valued evidence.",
                recoverable=True,
                details={"finding_index": index},
            )
        validated.append(finding)
    return validated


def normalize_text(value: Any, field: str, maximum: int, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise RenderError(
                "INVALID_CHART_INTENT",
                f"chart_intent.{field} is required.",
                recoverable=True,
            )
        return ""
    if not isinstance(value, str):
        raise RenderError(
            "INVALID_CHART_INTENT",
            f"chart_intent.{field} must be a string or null.",
            recoverable=True,
        )
    normalized = " ".join(value.split())
    if required and not normalized:
        raise RenderError(
            "INVALID_CHART_INTENT",
            f"chart_intent.{field} must not be empty.",
            recoverable=True,
        )
    if len(normalized) > maximum:
        raise RenderError(
            "INVALID_CHART_INTENT",
            f"chart_intent.{field} exceeds {maximum} characters.",
            recoverable=True,
        )
    return normalized


def numeric_series(deps: SimpleNamespace, values: Any, column: str) -> Any:
    converted = deps.pd.to_numeric(values, errors="coerce")
    conversion_failures = values.notna() & converted.isna()
    if bool(conversion_failures.any()) or bool(converted.isna().any()):
        bad_rows = [int(index) for index in converted[converted.isna()].index[:10]]
        raise RenderError(
            "NON_NUMERIC_DATA",
            f"Column {column!r} must contain a numeric value in every result row.",
            recoverable=True,
            details={"column": column, "row_indices": bad_rows},
        )
    nonfinite = [int(index) for index, value in converted.items() if not math.isfinite(float(value))]
    if nonfinite:
        raise RenderError(
            "NON_FINITE_DATA",
            f"Column {column!r} contains infinite values.",
            recoverable=True,
            details={"column": column, "row_indices": nonfinite[:10]},
        )
    return converted.astype(float)


def parse_intent(
    deps: SimpleNamespace,
    manifest: dict[str, Any],
    frame: Any,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Any, str, list[str]]:
    raw = manifest.get("chart_intent")
    if not isinstance(raw, dict):
        raise RenderError(
            "INVALID_CHART_INTENT",
            "chart_intent must be an object.",
            recoverable=True,
        )
    kind = raw.get("analysis_kind", "other")
    if kind not in ALLOWED_KINDS:
        raise RenderError(
            "INVALID_CHART_INTENT",
            "analysis_kind is not supported.",
            recoverable=True,
            details={"actual": kind, "allowed": sorted(ALLOWED_KINDS)},
        )
    plot_ready = raw.get("plot_ready")
    if kind == "distribution" and plot_ready is not True:
        raise RenderError(
            "DISTRIBUTION_NOT_PLOT_READY",
            "Distribution charts require precomputed plot-ready bins or statistics.",
            recoverable=True,
        )
    if plot_ready is not True:
        raise RenderError(
            "INVALID_CHART_INTENT",
            "chart_intent.plot_ready must be true.",
            recoverable=True,
        )

    requested_chart = args.chart_type or raw.get("chart_type", "auto")
    if requested_chart not in ALLOWED_CHART_TYPES:
        raise RenderError(
            "UNSUPPORTED_CHART_TYPE",
            "chart_type is not supported.",
            recoverable=True,
            details={"actual": requested_chart, "allowed": sorted(ALLOWED_CHART_TYPES)},
        )
    x = raw.get("x")
    if x is not None and (not isinstance(x, str) or not x):
        raise RenderError(
            "INVALID_CHART_INTENT",
            "chart_intent.x must be an existing column name or null.",
            recoverable=True,
        )
    y = raw.get("y")
    if not isinstance(y, str) or not y:
        raise RenderError(
            "INVALID_CHART_INTENT",
            "chart_intent.y must be a nonempty column name.",
            recoverable=True,
        )
    series = raw.get("series")
    if series is not None and (not isinstance(series, str) or not series):
        raise RenderError(
            "INVALID_CHART_INTENT",
            "chart_intent.series must be an existing column name or null.",
            recoverable=True,
        )
    for role, column in (("x", x), ("y", y), ("series", series)):
        if column is not None and column not in frame.columns:
            raise RenderError(
                "INVALID_CHART_INTENT",
                f"chart_intent.{role} does not name a result column.",
                recoverable=True,
                details={"column": column, "available": [str(item) for item in frame.columns]},
            )
    if series is not None and (series == x or series == y):
        raise RenderError(
            "INVALID_CHART_INTENT",
            "series must differ from x and y.",
            recoverable=True,
        )

    sort = raw.get("sort", "none")
    if sort not in ALLOWED_SORTS:
        raise RenderError(
            "INVALID_CHART_INTENT",
            "chart_intent.sort is not supported.",
            recoverable=True,
            details={"actual": sort, "allowed": sorted(ALLOWED_SORTS)},
        )
    if x is None and sort.startswith("x-"):
        raise RenderError(
            "INVALID_CHART_INTENT",
            "An x sort requires chart_intent.x.",
            recoverable=True,
        )
    if len(frame) > args.max_points:
        raise RenderError(
            "TOO_MANY_POINTS",
            "The plot-ready result exceeds --max-points and will not be sampled.",
            recoverable=True,
            details={"row_count": len(frame), "max_points": args.max_points},
        )

    columns = [column for column in (x, y, series) if column is not None]
    plot_frame = frame.loc[:, columns].copy()
    if x is not None and bool(plot_frame[x].astype(str).str.strip().eq("").any()):
        raise RenderError(
            "INVALID_CHART_INTENT",
            "The x column contains blank values; regenerate plot-ready results.",
            recoverable=True,
            details={"column": x},
        )
    if series is not None and bool(
        plot_frame[series].astype(str).str.strip().eq("").any()
    ):
        raise RenderError(
            "INVALID_CHART_INTENT",
            "The series column contains blank values; regenerate plot-ready results.",
            recoverable=True,
            details={"column": series},
        )

    internal_y = "__chartpilot_y_numeric__"
    while internal_y in plot_frame.columns:
        internal_y += "_"
    plot_frame[internal_y] = numeric_series(deps, plot_frame[y], y)

    selection_warnings: list[str] = []
    if requested_chart == "auto":
        if x is None:
            chart_type = "bar"
            reason = "single_metric"
        elif kind == "trend":
            chart_type = "line"
            reason = "analysis_kind_trend"
        elif kind in {"metric", "comparison", "ranking", "contribution"}:
            chart_type = "bar"
            reason = f"analysis_kind_{kind}"
        elif kind == "composition":
            category_count = int(plot_frame[x].nunique(dropna=False))
            valid_donut = (
                2 <= category_count <= MAX_DONUT_CATEGORIES
                and not bool(plot_frame[x].duplicated().any())
                and bool((plot_frame[internal_y] >= 0).all())
                and bool((plot_frame[internal_y] > 0).any())
                and series is None
            )
            chart_type = "donut" if valid_donut else "bar"
            reason = "composition_compact" if valid_donut else "composition_bar_fallback"
            if not valid_donut:
                selection_warnings.append(
                    "Composition data did not meet compact donut constraints; selected bar."
                )
        elif kind == "relationship":
            chart_type = "scatter"
            reason = "analysis_kind_relationship"
        elif kind == "distribution":
            chart_type = "bar"
            reason = "precomputed_distribution"
        else:
            try:
                numeric_series(deps, plot_frame[x], x)
                chart_type = "scatter"
                reason = "numeric_axes_fallback"
            except RenderError:
                chart_type = "bar"
                reason = "categorical_fallback"
    else:
        chart_type = requested_chart
        reason = "explicit_override" if args.chart_type else "analysis_intent"

    if x is None:
        if chart_type != "bar" or len(plot_frame) != 1 or series is not None:
            raise RenderError(
                "INVALID_CHART_INTENT",
                "x may be null only for a one-row bar chart without series.",
                recoverable=True,
            )
    elif chart_type in {"line", "donut", "scatter"} and not x:
        raise RenderError(
            "INVALID_CHART_INTENT",
            f"A {chart_type} chart requires x.",
            recoverable=True,
        )

    if chart_type == "donut":
        if series is not None:
            raise RenderError(
                "INVALID_CHART_INTENT",
                "Donut charts do not accept series.",
                recoverable=True,
            )
        category_count = int(plot_frame[x].nunique(dropna=False))
        if not 2 <= category_count <= MAX_DONUT_CATEGORIES:
            raise RenderError(
                "INVALID_CHART_INTENT",
                f"Donut charts require 2-{MAX_DONUT_CATEGORIES} unique categories.",
                recoverable=True,
                details={"category_count": category_count},
            )
        if bool(plot_frame[x].duplicated().any()):
            raise RenderError(
                "DUPLICATE_PLOT_KEY",
                "Donut category keys must be unique; the renderer will not aggregate them.",
                recoverable=True,
                details={"column": x},
            )
        if bool((plot_frame[internal_y] < 0).any()) or not bool((plot_frame[internal_y] > 0).any()):
            raise RenderError(
                "INVALID_CHART_INTENT",
                "Donut values must be nonnegative with at least one positive value.",
                recoverable=True,
            )

    if chart_type == "bar" and x is not None:
        if series is None:
            duplicates = plot_frame[x].duplicated()
        else:
            duplicates = plot_frame.duplicated(subset=[x, series])
        if bool(duplicates.any()):
            raise RenderError(
                "DUPLICATE_PLOT_KEY",
                "Bar plot keys must be unique; the renderer will not aggregate them.",
                recoverable=True,
                details={"x": x, "series": series},
            )
        category_count = int(plot_frame[x].nunique(dropna=False))
        if category_count > MAX_BAR_CATEGORIES:
            raise RenderError(
                "TOO_MANY_POINTS",
                "The bar chart has too many categories and will not be truncated.",
                recoverable=True,
                details={"category_count": category_count, "maximum": MAX_BAR_CATEGORIES},
            )

    if chart_type == "line":
        duplicates = (
            plot_frame[x].duplicated()
            if series is None
            else plot_frame.duplicated(subset=[x, series])
        )
        if bool(duplicates.any()):
            raise RenderError(
                "DUPLICATE_PLOT_KEY",
                "Line plot keys must be unique; the renderer will not interpret duplicate points.",
                recoverable=True,
                details={"x": x, "series": series},
            )

    if chart_type == "scatter":
        internal_x = "__chartpilot_x_numeric__"
        while internal_x in plot_frame.columns:
            internal_x += "_"
        plot_frame[internal_x] = numeric_series(deps, plot_frame[x], x)
    else:
        internal_x = ""

    if series is not None:
        series_count = int(plot_frame[series].nunique(dropna=False))
        if series_count > MAX_SERIES:
            raise RenderError(
                "TOO_MANY_POINTS",
                "The chart has too many series and will not merge them.",
                recoverable=True,
                details={"series_count": series_count, "maximum": MAX_SERIES},
            )

    if sort != "none":
        sort_column = x if sort.startswith("x-") else internal_y
        ascending = sort.endswith("asc")
        try:
            plot_frame = plot_frame.sort_values(sort_column, ascending=ascending, kind="mergesort")
        except Exception as exc:
            raise RenderError(
                "INVALID_CHART_INTENT",
                "The requested presentation sort could not be applied.",
                recoverable=True,
                details={"sort": sort, "reason": str(exc)},
            ) from exc

    title_override = args.title if args.title is not None else raw.get("title")
    title = normalize_text(title_override, "title", 160, required=True)
    config = {
        "analysis_kind": kind,
        "chart_type": chart_type,
        "selection_reason": reason,
        "x": x,
        "y": y,
        "series": series,
        "title": title,
        "unit": normalize_text(raw.get("unit"), "unit", 40),
        "time_range": normalize_text(raw.get("time_range"), "time_range", 100),
        "source_note": normalize_text(
            raw.get("source_note"), "source_note", 240, required=True
        ),
        "plot_ready": True,
        "sort": sort,
        "internal_y": internal_y,
        "internal_x": internal_x,
    }
    return config, plot_frame, requested_chart, selection_warnings


def contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))


def font_texts(config: dict[str, Any], frame: Any) -> Iterable[str]:
    for field in ("title", "x", "y", "series", "unit", "time_range", "source_note"):
        value = config.get(field)
        if value is not None:
            yield str(value)
    for column in (config.get("x"), config.get("series")):
        if column is not None:
            for value in frame[column].tolist():
                yield str(value)


def normalized_font_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def font_style_rank(path: Path) -> tuple[int, str]:
    name = path.name.casefold()
    style_order = (
        "regular",
        "normal",
        "medium",
        "demilight",
        "light",
        "semibold",
        "bold",
        "thin",
        "black",
    )
    rank = next((index for index, style in enumerate(style_order) if style in name), 20)
    return rank, os.path.normcase(str(path))


def choose_font(
    deps: SimpleNamespace,
    explicit_path: str | None,
    requires_cjk: bool,
) -> tuple[Any, dict[str, Any]]:
    manager = deps.font_manager
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise RenderError(
                "CHINESE_FONT_NOT_FOUND",
                "The explicit font path is not a readable file.",
                recoverable=True,
                details={"path": str(path)},
            )
        try:
            manager.fontManager.addfont(str(path))
            properties = manager.FontProperties(fname=str(path))
            name = properties.get_name()
        except Exception as exc:
            raise RenderError(
                "CHINESE_FONT_NOT_FOUND",
                "The explicit font could not be loaded by Matplotlib.",
                recoverable=True,
                details={"path": str(path), "reason": str(exc)},
            ) from exc
        return properties, {
            "name": name,
            "path": str(path),
            "source": "explicit",
            "required_for_cjk": requires_cjk,
        }

    if not requires_cjk:
        properties = manager.FontProperties(family="DejaVu Sans")
        path = manager.findfont(properties, fallback_to_default=True)
        return properties, {
            "name": properties.get_name(),
            "path": str(path),
            "source": "matplotlib-default",
            "required_for_cjk": False,
        }

    candidates: list[Path] = []
    windows_dir = os.environ.get("WINDIR")
    if windows_dir:
        font_dir = Path(windows_dir) / "Fonts"
        for filename in ("msyh.ttc", "msyh.ttf", "Deng.ttf", "simhei.ttf", "simsun.ttc"):
            path = font_dir / filename
            if path.is_file():
                candidates.append(path)
    try:
        candidates.extend(Path(item) for item in manager.findSystemFonts(fontext="ttf"))
        candidates.extend(Path(item) for item in manager.findSystemFonts(fontext="otf"))
    except Exception:
        pass

    seen: set[str] = set()
    font_records: list[tuple[str, Path]] = []
    for path in sorted(candidates, key=lambda item: os.path.normcase(str(item))):
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        try:
            name = manager.FontProperties(fname=str(path)).get_name()
        except Exception:
            continue
        font_records.append((name, path))

    for preferred in CJK_FONT_NAMES:
        preferred_key = normalized_font_name(preferred)
        matches = [
            (name, path)
            for name, path in font_records
            if preferred_key in normalized_font_name(name)
        ]
        for name, path in sorted(matches, key=lambda item: font_style_rank(item[1])):
            try:
                manager.fontManager.addfont(str(path))
                properties = manager.FontProperties(fname=str(path))
                return properties, {
                    "name": properties.get_name(),
                    "path": str(path),
                    "source": "system-discovery",
                    "required_for_cjk": True,
                }
            except Exception:
                continue

    raise RenderError(
        "CHINESE_FONT_NOT_FOUND",
        "Chinese chart text was detected, but no supported CJK font was found.",
        recoverable=True,
        details={"searched_names": list(CJK_FONT_NAMES), "hint": "Pass --font-path."},
    )


def stable_values(values: Sequence[Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def apply_font_to_axis(axis: Any, font_properties: Any) -> None:
    for label in list(axis.get_xticklabels()) + list(axis.get_yticklabels()):
        label.set_fontproperties(font_properties)


def render_figure(
    deps: SimpleNamespace,
    frame: Any,
    config: dict[str, Any],
    font_properties: Any,
    destination: Path,
    args: argparse.Namespace,
) -> dict[str, int]:
    plt = deps.plt
    deps.matplotlib.rcParams["axes.unicode_minus"] = False
    deps.matplotlib.rcParams["font.family"] = [font_properties.get_name()]
    figure, axis = plt.subplots(figsize=(args.width, args.height), dpi=args.dpi)
    figure.patch.set_facecolor("white")
    axis.set_facecolor("white")
    chart_type = config["chart_type"]
    x = config["x"]
    y = config["y"]
    series = config["series"]
    y_values = config["internal_y"]
    artist_count = 0
    data_point_count = len(frame)

    try:
        if chart_type == "line":
            if series is None:
                lines = axis.plot(
                    frame[x].tolist(),
                    frame[y_values].tolist(),
                    color=COLORS[0],
                    linewidth=2.2,
                    marker="o",
                    markersize=4.5,
                )
                artist_count += len(lines)
            else:
                for index, value in enumerate(stable_values(frame[series].tolist())):
                    subset = frame.loc[frame[series] == value]
                    lines = axis.plot(
                        subset[x].tolist(),
                        subset[y_values].tolist(),
                        color=COLORS[index % len(COLORS)],
                        linewidth=2.0,
                        marker="o",
                        markersize=4,
                        label=str(value),
                    )
                    artist_count += len(lines)

        elif chart_type == "bar":
            if x is None:
                labels = [str(y)]
                positions = [0]
                container = axis.bar(positions, frame[y_values].tolist(), color=COLORS[0], width=0.58)
                artist_count += len(container.patches)
                axis.set_xticks(positions, labels=labels)
            elif series is None:
                labels = [str(value) for value in frame[x].tolist()]
                positions = list(range(len(labels)))
                container = axis.bar(positions, frame[y_values].tolist(), color=COLORS[0], width=0.68)
                artist_count += len(container.patches)
                axis.set_xticks(positions, labels=labels)
            else:
                categories = stable_values(frame[x].tolist())
                series_values = stable_values(frame[series].tolist())
                positions = list(range(len(categories)))
                bar_width = min(0.78 / max(len(series_values), 1), 0.32)
                lookup = {
                    (row[x], row[series]): row[y_values]
                    for _, row in frame.iterrows()
                }
                center = (len(series_values) - 1) / 2
                for index, series_value in enumerate(series_values):
                    available_positions: list[float] = []
                    available_values: list[float] = []
                    for category_index, category in enumerate(categories):
                        key = (category, series_value)
                        if key in lookup:
                            available_positions.append(
                                category_index + (index - center) * bar_width
                            )
                            available_values.append(float(lookup[key]))
                    container = axis.bar(
                        available_positions,
                        available_values,
                        width=bar_width,
                        color=COLORS[index % len(COLORS)],
                        label=str(series_value),
                    )
                    artist_count += len(container.patches)
                axis.set_xticks(positions, labels=[str(value) for value in categories])

        elif chart_type == "donut":
            text_properties = {"fontproperties": font_properties, "fontsize": 10}
            wedges, _ = axis.pie(
                frame[y_values].tolist(),
                labels=[str(value) for value in frame[x].tolist()],
                colors=[COLORS[index % len(COLORS)] for index in range(len(frame))],
                startangle=90,
                counterclock=False,
                wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 1.5},
                textprops=text_properties,
            )
            artist_count += len(wedges)
            axis.axis("equal")

        elif chart_type == "scatter":
            x_values = config["internal_x"]
            if series is None:
                collection = axis.scatter(
                    frame[x_values].tolist(),
                    frame[y_values].tolist(),
                    color=COLORS[0],
                    s=48,
                    alpha=0.82,
                    edgecolors="white",
                    linewidths=0.6,
                )
                artist_count += int(len(collection.get_offsets()) > 0)
            else:
                for index, value in enumerate(stable_values(frame[series].tolist())):
                    subset = frame.loc[frame[series] == value]
                    collection = axis.scatter(
                        subset[x_values].tolist(),
                        subset[y_values].tolist(),
                        color=COLORS[index % len(COLORS)],
                        s=48,
                        alpha=0.82,
                        edgecolors="white",
                        linewidths=0.6,
                        label=str(value),
                    )
                    artist_count += int(len(collection.get_offsets()) > 0)
        else:  # Defensive; parse_intent already rejects this.
            raise RenderError(
                "UNSUPPORTED_CHART_TYPE",
                f"Cannot render chart type {chart_type!r}.",
                recoverable=True,
            )

        if data_point_count <= 0 or artist_count <= 0:
            raise RenderError(
                "CHART_RENDER_FAILED",
                "The chart contains no data points or data artists.",
                recoverable=True,
                details={"data_point_count": data_point_count, "artist_count": artist_count},
            )

        if chart_type != "donut":
            axis.grid(axis="y", color="#D8DEE3", linewidth=0.8, alpha=0.75)
            axis.set_axisbelow(True)
            axis.spines["top"].set_visible(False)
            axis.spines["right"].set_visible(False)
            axis.spines["left"].set_color("#AAB3BA")
            axis.spines["bottom"].set_color("#AAB3BA")
            axis.set_xlabel(str(x or ""), fontproperties=font_properties, labelpad=9)
            y_label = str(y)
            if config["unit"]:
                y_label = f"{y_label} ({config['unit']})"
            axis.set_ylabel(y_label, fontproperties=font_properties, labelpad=9)

        title = config["title"]
        if config["time_range"]:
            title = f"{title}\n{config['time_range']}"
        axis.set_title(title, fontproperties=font_properties, fontsize=15, pad=14)

        if series is not None and chart_type != "donut":
            legend = axis.legend(
                title=str(series),
                frameon=False,
                prop=font_properties,
            )
            if legend is not None:
                legend.get_title().set_fontproperties(font_properties)

        apply_font_to_axis(axis, font_properties)
        if chart_type in {"line", "bar"} and x is not None:
            labels = axis.get_xticklabels()
            longest = max((len(label.get_text()) for label in labels), default=0)
            if len(labels) > 8 or longest > 8:
                for label in labels:
                    label.set_rotation(35)
                    label.set_horizontalalignment("right")

        if config["source_note"]:
            figure.text(
                0.02,
                0.018,
                textwrap.fill(config["source_note"], width=110),
                color="#59636B",
                fontsize=8.5,
                fontproperties=font_properties,
            )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bottom = 0.10 if config["source_note"] else 0.04
            figure.tight_layout(rect=(0.02, bottom, 0.98, 0.95))
            figure.savefig(
                destination,
                format="png",
                dpi=args.dpi,
                facecolor="white",
                edgecolor="white",
            )
        missing_glyphs = [str(item.message) for item in caught if "Glyph" in str(item.message)]
        if missing_glyphs:
            raise RenderError(
                "CHINESE_FONT_NOT_FOUND",
                "The selected font is missing glyphs required by the chart.",
                recoverable=True,
                details={"warnings": missing_glyphs[:10]},
            )
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(
            "CHART_RENDER_FAILED",
            "Matplotlib failed to render the chart.",
            recoverable=True,
            details={"reason": str(exc), "chart_type": chart_type},
            exit_code=4,
        ) from exc
    finally:
        plt.close(figure)

    return {"data_point_count": data_point_count, "artist_count": artist_count}


def validate_png(deps: SimpleNamespace, path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            signature = handle.read(8)
        if signature != PNG_SIGNATURE:
            raise ValueError("invalid PNG signature")
        with deps.Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError(f"unexpected image format {image.format!r}")
            image.verify()
        with deps.Image.open(path) as image:
            image.load()
            width, height = image.size
            if width < 320 or height < 240:
                raise ValueError(f"image dimensions are too small: {width}x{height}")
            rgba = image.convert("RGBA")
            white = deps.Image.new("RGBA", rgba.size, "white")
            white.alpha_composite(rgba)
            rgb = white.convert("RGB")
            background = deps.Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
            difference = deps.ImageChops.difference(rgb, background).convert("L")
            mask = difference.point(lambda value: 255 if value > 8 else 0)
            non_background_pixels = mask.histogram()[255]
            total_pixels = width * height
            minimum = max(100, math.ceil(total_pixels * 0.005))
            if non_background_pixels < minimum:
                raise ValueError(
                    f"only {non_background_pixels} pixels differ from the background; minimum is {minimum}"
                )
    except RenderError:
        raise
    except Exception as exc:
        raise RenderError(
            "PNG_VALIDATION_FAILED",
            "The staged chart.png failed signature, dimension, or pixel validation.",
            recoverable=True,
            details={"reason": str(exc)},
            exit_code=4,
        ) from exc
    return {
        "png_signature": True,
        "width": width,
        "height": height,
        "non_background_pixels": non_background_pixels,
        "foreground_ratio": round(non_background_pixels / total_pixels, 8),
    }


def build_chart_spec(
    task_id: str,
    manifest_reference_path: str,
    manifest_hash: str,
    result_reference_path: str,
    result_hash: str,
    config: dict[str, Any],
    font_info: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "schema_version": CHART_SPEC_SCHEMA,
        "renderer_version": RENDERER_VERSION,
        "task_id": task_id,
        "upstream": {
            "analysis_result": {"path": manifest_reference_path, "sha256": manifest_hash},
            "result_csv": {"path": result_reference_path, "sha256": result_hash},
        },
        "chart": {
            "type": config["chart_type"],
            "selection_reason": config["selection_reason"],
            "analysis_kind": config["analysis_kind"],
            "x": config["x"],
            "y": config["y"],
            "series": config["series"],
            "title": config["title"],
            "unit": config["unit"],
            "time_range": config["time_range"],
            "source_note": config["source_note"],
            "plot_ready": True,
            "sort": config["sort"],
        },
        "figure": {
            "width_inches": args.width,
            "height_inches": args.height,
            "dpi": args.dpi,
            "background": "#FFFFFF",
            "font_name": font_info["name"],
        },
    }


def audit_snapshot(spec: dict[str, Any], renderer_hash: str) -> str:
    payload = {
        "schema_version": "chartpilot.generated-chart-audit/v1",
        "renderer_version": RENDERER_VERSION,
        "renderer_sha256": renderer_hash,
        "chart_spec": spec,
        "note": "Audit snapshot only; contains no source rows or business calculations.",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return (
        "#!/usr/bin/env python3\n"
        "\"\"\"ChartPilot generated chart audit snapshot.\"\"\"\n\n"
        "import json\n\n"
        f"AUDIT = json.loads({encoded!r})\n\n"
        "if __name__ == \"__main__\":\n"
        "    print(json.dumps(AUDIT, ensure_ascii=False, indent=2, sort_keys=True))\n"
    )


def build_summary(
    config: dict[str, Any],
    findings: list[dict[str, Any]],
    result_relative_path: str,
) -> str:
    chart_labels = {
        "line": "折线图",
        "bar": "条形图",
        "donut": "环形图",
        "scatter": "散点图",
    }
    lines = [f"# {config['title']}", "", "## 图表说明", ""]
    lines.append(f"- 图表类型：{chart_labels[config['chart_type']]}。")
    lines.append(f"- 指标字段：`{config['y']}`。")
    if config["x"] is not None:
        lines.append(f"- 横轴或类别字段：`{config['x']}`。")
    if config["series"] is not None:
        lines.append(f"- 系列字段：`{config['series']}`。")
    if config["unit"]:
        lines.append(f"- 指标单位：{config['unit']}。")
    if config["time_range"]:
        lines.append(f"- 时间范围：{config['time_range']}。")
    lines.append(f"- 数据边界：图表仅使用哈希校验后的 `{result_relative_path}`，未重新聚合业务数据。")
    if config["source_note"]:
        lines.append(f"- 数据说明：{config['source_note']}。")

    lines.extend(["", "## 主要发现", ""])
    if findings:
        for finding in findings:
            finding_text = finding["text"].replace("\r\n", "\n").replace("\r", "\n")
            lines.append(f"- {finding_text.replace(chr(10), chr(10) + '  ')}")
    else:
        lines.append("分析结果未提供结构化发现。")
    return "\n".join(lines) + "\n"


def commit_artifacts(staging: Path, output_dir: Path) -> None:
    backup_dir = staging / ".backup"
    backup_dir.mkdir()
    backed_up: list[str] = []
    committed: list[str] = []
    try:
        for name in OUTPUT_FILES:
            target = output_dir / name
            if target.exists():
                if target.is_dir():
                    raise OSError(f"destination is a directory: {target}")
                os.replace(target, backup_dir / name)
                backed_up.append(name)
        for name in OUTPUT_FILES:
            staged_file = staging / name
            if not staged_file.is_file():
                raise OSError(f"staged artifact is missing: {staged_file}")
            os.replace(staged_file, output_dir / name)
            committed.append(name)
    except Exception as exc:
        rollback_errors: list[str] = []
        for name in reversed(committed):
            target = output_dir / name
            try:
                if target.exists():
                    target.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        for name in reversed(backed_up):
            backup = backup_dir / name
            try:
                if backup.exists():
                    os.replace(backup, output_dir / name)
            except OSError as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        raise RenderError(
            "ATOMIC_COMMIT_FAILED",
            "The validated artifact set could not be committed atomically.",
            recoverable=True,
            details={"reason": str(exc), "rollback_errors": rollback_errors},
            exit_code=4,
        ) from exc


def validate_cli_values(args: argparse.Namespace) -> None:
    if not 4.0 <= args.width <= 30.0:
        raise RenderError("INVALID_ARGUMENT", "--width must be between 4 and 30.", recoverable=True)
    if not 3.0 <= args.height <= 20.0:
        raise RenderError("INVALID_ARGUMENT", "--height must be between 3 and 20.", recoverable=True)
    if not 72 <= args.dpi <= 600:
        raise RenderError("INVALID_ARGUMENT", "--dpi must be between 72 and 600.", recoverable=True)
    if not 1 <= args.max_points <= 100000:
        raise RenderError(
            "INVALID_ARGUMENT",
            "--max-points must be between 1 and 100000.",
            recoverable=True,
        )


def relative_output_reference(path: Path, output_dir: Path) -> str:
    try:
        return os.path.relpath(path, output_dir).replace("\\", "/")
    except ValueError as exc:
        raise RenderError(
            "INVALID_OUTPUT_PATH",
            "The output directory must share a Windows drive with the analysis artifacts.",
            recoverable=True,
            details={"path": str(path), "output_dir": str(output_dir)},
            exit_code=4,
        ) from exc


def run(args: argparse.Namespace) -> dict[str, Any]:
    validate_cli_values(args)
    dependencies = load_dependencies()
    manifest_path = Path(args.analysis_result).expanduser().resolve()
    manifest = load_manifest(manifest_path)
    require_manifest_contract(manifest)
    findings = validate_findings(manifest)
    result_path, result_relative_path, result_hash = resolve_result_path(manifest_path, manifest)
    manifest_hash = sha256_file(manifest_path)
    frame = read_and_validate_result(dependencies, result_path, manifest)
    config, plot_frame, _, selection_warnings = parse_intent(
        dependencies, manifest, frame, args
    )

    requires_cjk = any(contains_cjk(value) for value in font_texts(config, plot_frame))
    font_properties, font_info = choose_font(dependencies, args.font_path, requires_cjk)

    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else manifest_path.parent
    )
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RenderError(
            "ATOMIC_COMMIT_FAILED",
            "The output directory could not be created.",
            recoverable=True,
            details={"path": str(output_dir), "reason": str(exc)},
            exit_code=4,
        ) from exc
    if not output_dir.is_dir():
        raise RenderError(
            "ATOMIC_COMMIT_FAILED",
            "The output path is not a directory.",
            recoverable=True,
            details={"path": str(output_dir)},
            exit_code=4,
        )

    manifest_reference_path = relative_output_reference(manifest_path, output_dir)
    result_reference_path = relative_output_reference(result_path, output_dir)

    chart_spec = build_chart_spec(
        manifest["task_id"],
        manifest_reference_path,
        manifest_hash,
        result_reference_path,
        result_hash,
        config,
        font_info,
        args,
    )
    renderer_hash = sha256_file(Path(__file__).resolve())

    staging_path = Path(tempfile.mkdtemp(prefix=".chartpilot-render-", dir=output_dir))
    try:
        spec_path = staging_path / "chart_spec.json"
        audit_path = staging_path / "generated_chart.py"
        png_path = staging_path / "chart.png"
        summary_path = staging_path / "summary.md"
        result_manifest_path = staging_path / "chart_result.json"

        write_json(spec_path, chart_spec)
        write_text(audit_path, audit_snapshot(chart_spec, renderer_hash))
        render_stats = render_figure(
            dependencies,
            plot_frame,
            config,
            font_properties,
            png_path,
            args,
        )
        png_validation = validate_png(dependencies, png_path)
        write_text(summary_path, build_summary(config, findings, result_reference_path))

        validation = manifest.get("validation")
        if isinstance(validation, dict) and "warnings" in validation:
            analysis_warnings = validation.get("warnings")
        else:
            analysis_warnings = manifest.get("warnings", [])
        if not isinstance(analysis_warnings, list):
            analysis_warnings = []
        chart_result = {
            "schema_version": CHART_RESULT_SCHEMA,
            "renderer_version": RENDERER_VERSION,
            "task_id": manifest["task_id"],
            "stage": "chart",
            "status": "success",
            "upstream": {
                "analysis_result": {"path": manifest_reference_path, "sha256": manifest_hash},
                "result_csv": {"path": result_reference_path, "sha256": result_hash},
            },
            "chart": {
                "type": config["chart_type"],
                "x": config["x"],
                "y": config["y"],
                "series": config["series"],
                "finding_ids": [finding["id"] for finding in findings],
            },
            "artifacts": {
                "chart_spec": {
                    "path": "chart_spec.json",
                    "sha256": sha256_file(spec_path),
                },
                "generated_chart": {
                    "path": "generated_chart.py",
                    "sha256": sha256_file(audit_path),
                },
                "chart_png": {
                    "path": "chart.png",
                    "sha256": sha256_file(png_path),
                    "mime_type": "image/png",
                    "bytes": file_size(png_path),
                    "width": png_validation["width"],
                    "height": png_validation["height"],
                },
                "summary": {
                    "path": "summary.md",
                    "sha256": sha256_file(summary_path),
                },
            },
            "validation": {
                "result_row_count": len(frame),
                "data_point_count": render_stats["data_point_count"],
                "artist_count": render_stats["artist_count"],
                "png_signature": png_validation["png_signature"],
                "foreground_pixels": png_validation["non_background_pixels"],
                "foreground_ratio": png_validation["foreground_ratio"],
                "font": font_info,
            },
            "warnings": {
                "renderer": selection_warnings,
                "analysis": analysis_warnings,
            },
        }
        write_json(result_manifest_path, chart_result)
        commit_artifacts(staging_path, output_dir)
    finally:
        shutil.rmtree(staging_path, ignore_errors=True)

    return {
        "status": "success",
        "stage": "chart",
        "task_id": manifest["task_id"],
        "chart_type": config["chart_type"],
        "chart_result": str(output_dir / "chart_result.json"),
        "chart": str(output_dir / "chart.png"),
        "summary": str(output_dir / "summary.md"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    debug = False
    try:
        args = parser.parse_args(argv)
        debug = bool(args.debug)
        payload = run(args)
    except RenderError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # Defensive conversion to the structured error contract.
        details: dict[str, Any] = {"exception_type": type(exc).__name__}
        if debug:
            details["traceback"] = traceback.format_exc()
        error = RenderError(
            "INTERNAL_ERROR",
            "The chart renderer failed unexpectedly.",
            recoverable=False,
            details=details,
            exit_code=5,
        )
        print(json.dumps(error.payload(), ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return error.exit_code
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
