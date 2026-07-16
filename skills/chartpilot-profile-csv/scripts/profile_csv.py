#!/usr/bin/env python3
"""Deterministically profile one local CSV file into input_profile.json."""

from __future__ import annotations

import argparse
import codecs
import csv
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


PROFILER_VERSION = "1.0.0"
PROFILE_SCHEMA_VERSION = "chartpilot.input-profile/v1"
DEFAULT_MAX_FILE_BYTES = 1024 * 1024 * 1024
DEFAULT_SNIFF_BYTES = 1024 * 1024
DEFAULT_UNIQUE_EXACT_CAP = 100_000
DEFAULT_DUPLICATE_EXACT_CAP = 1_000_000
DEFAULT_MAX_COLUMNS = 10_000
DEFAULT_MAX_FIELD_CHARS = 8 * 1024 * 1024
MAX_SAMPLE_ROWS = 100

DELIMITERS: tuple[tuple[str, str], ...] = (
    ("comma", ","),
    ("tab", "\t"),
    ("semicolon", ";"),
    ("pipe", "|"),
)
DELIMITER_BY_NAME = dict(DELIMITERS)
DELIMITER_NAME_BY_VALUE = {value: name for name, value in DELIMITERS}

BOOLEAN_VALUES = frozenset(
    {"true", "false", "yes", "no", "y", "n", "是", "否", "真", "假"}
)
NULL_LIKE_VALUES = frozenset({"na", "n/a", "null", "none", "nan", "无", "缺失"})

INTEGER_RE = re.compile(r"^[+-]?\d+$")
NUMBER_RE = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$"
)
LEADING_ZERO_RE = re.compile(r"^[+-]?0\d+$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
CN_MOBILE_RE = re.compile(r"^1[3-9]\d{9}$")
CN_RESIDENT_ID_RE = re.compile(r"^\d{17}[\dXx]$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

TIME_HINTS = (
    "date",
    "time",
    "timestamp",
    "year",
    "month",
    "day",
    "日期",
    "时间",
    "年月",
    "年度",
    "月份",
)
IDENTIFIER_HINTS = (
    "id",
    "code",
    "number",
    "编号",
    "编码",
    "单号",
    "序号",
    "流水号",
    "订单号",
    "sku",
)
CATEGORY_HINTS = (
    "region",
    "product",
    "channel",
    "category",
    "type",
    "status",
    "department",
    "city",
    "province",
    "地区",
    "区域",
    "产品",
    "渠道",
    "类别",
    "类型",
    "状态",
    "部门",
    "城市",
    "省份",
)
SENSITIVE_HINTS = (
    "name",
    "phone",
    "mobile",
    "email",
    "address",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "姓名",
    "手机",
    "电话",
    "邮箱",
    "地址",
    "身份证",
    "密码",
    "密钥",
)


class ProfileError(Exception):
    """An expected failure with a stable machine-readable contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        exit_code: int = 5,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
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


class StructuredArgumentParser(argparse.ArgumentParser):
    """Convert argparse failures into the script's JSON error contract."""

    def error(self, message: str) -> None:
        raise ProfileError(
            "INVALID_ARGUMENT",
            message,
            exit_code=2,
        )


@dataclass
class EncodingDecision:
    name: str
    method: str
    bom: bool


@dataclass
class DelimiterDecision:
    value: str
    name: str
    method: str
    skip_sep_declaration: bool
    candidates: list[dict[str, Any]] = field(default_factory=list)
    single_column_default: bool = False


@dataclass
class ColumnAccumulator:
    non_missing_count: int = 0
    missing_count: int = 0
    null_like_count: int = 0
    boolean_count: int = 0
    integer_count: int = 0
    number_count: int = 0
    date_count: int = 0
    datetime_count: int = 0
    leading_zero_count: int = 0
    sensitive_value_count: int = 0
    unique_values: set[str] = field(default_factory=set)
    unique_capped: bool = False

    def observe(self, raw_value: str, unique_cap: int) -> None:
        stripped = raw_value.strip()
        if stripped == "":
            self.missing_count += 1
            return

        self.non_missing_count += 1
        folded = stripped.casefold()
        if folded in NULL_LIKE_VALUES:
            self.null_like_count += 1

        if not self.unique_capped:
            self.unique_values.add(raw_value)
            if len(self.unique_values) > unique_cap:
                self.unique_capped = True

        if folded in BOOLEAN_VALUES:
            self.boolean_count += 1

        if INTEGER_RE.fullmatch(stripped):
            self.integer_count += 1
        if NUMBER_RE.fullmatch(stripped):
            self.number_count += 1
        if LEADING_ZERO_RE.fullmatch(stripped):
            self.leading_zero_count += 1

        temporal_kind = infer_temporal_kind(stripped)
        if temporal_kind == "date":
            self.date_count += 1
        elif temporal_kind == "datetime":
            self.datetime_count += 1

        if is_sensitive_value(stripped):
            self.sensitive_value_count += 1


def infer_temporal_kind(value: str) -> str | None:
    """Recognize only year-first, unambiguous date and datetime forms."""

    date_formats = (
        (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),
        (r"^\d{4}/\d{2}/\d{2}$", "%Y/%m/%d"),
        (r"^\d{4}\.\d{2}\.\d{2}$", "%Y.%m.%d"),
        (r"^\d{4}年\d{1,2}月\d{1,2}日$", "%Y年%m月%d日"),
    )
    for pattern, date_format in date_formats:
        if re.fullmatch(pattern, value):
            try:
                datetime.strptime(value, date_format)
            except ValueError:
                return None
            return "date"

    if re.fullmatch(
        r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$",
        value,
    ):
        normalized = value.replace("Z", "+00:00")
        if re.search(r"[+-]\d{4}$", normalized):
            normalized = normalized[:-5] + normalized[-5:-2] + ":" + normalized[-2:]
        try:
            datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return "datetime"

    if re.fullmatch(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}(?::\d{2})?$", value):
        date_format = "%Y/%m/%d %H:%M:%S" if value.count(":") == 2 else "%Y/%m/%d %H:%M"
        try:
            datetime.strptime(value, date_format)
        except ValueError:
            return None
        return "datetime"

    return None


def is_sensitive_value(value: str) -> bool:
    return bool(
        EMAIL_RE.fullmatch(value)
        or CN_MOBILE_RE.fullmatch(value)
        or CN_RESIDENT_ID_RE.fullmatch(value)
    )


def normalize_header_name(name: str) -> str:
    return name.strip().casefold()


def header_has_hint(name: str, hints: Iterable[str]) -> bool:
    normalized = normalize_header_name(name)
    ascii_tokens = set(re.findall(r"[a-z0-9]+", normalized))
    compact_ascii = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    for hint in hints:
        folded_hint = hint.casefold()
        if any("\u4e00" <= char <= "\u9fff" for char in folded_hint):
            if folded_hint in normalized:
                return True
        elif folded_hint in ascii_tokens or folded_hint == compact_ascii:
            return True
    return False


def emit_json(stream: Any, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    binary_stream = getattr(stream, "buffer", None)
    if binary_stream is not None:
        binary_stream.write(text.encode("utf-8"))
        binary_stream.flush()
    else:
        stream.write(text)
        stream.flush()


def build_parser() -> StructuredArgumentParser:
    parser = StructuredArgumentParser(
        description="Profile one local CSV into deterministic input_profile.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  <bundled-python> profile_csv.py sales.csv --task-id T001 --output-dir task-output\n"
            "  <bundled-python> profile_csv.py \"C:\\数据\\销售 2026.csv\" --task-id T001 "
            "--output-dir \"C:\\ChartPilot\\workspace\\tasks\\T001\" "
            "--allowed-read-root \"C:\\数据\" "
            "--allowed-write-root \"C:\\ChartPilot\\workspace\"\n"
            "  <bundled-python> profile_csv.py data.csv --task-id T002 --output-dir out "
            "--encoding gbk --delimiter semicolon --sample-mode none"
        ),
    )
    parser.add_argument("input", help="Path to one local CSV file.")
    parser.add_argument("--task-id", required=True, help="Stable task identifier written into the profile.")
    parser.add_argument("--output-dir", required=True, help="Directory that will contain input_profile.json.")
    parser.add_argument(
        "--encoding",
        choices=("auto", "utf-8", "utf-8-sig", "gbk", "gb18030"),
        default="auto",
        help="Strict source encoding override (default: auto).",
    )
    parser.add_argument(
        "--delimiter",
        choices=("auto", "comma", "tab", "semicolon", "pipe"),
        default="auto",
        help="CSV delimiter override (default: auto).",
    )
    parser.add_argument(
        "--sample-mode",
        choices=("none", "redacted", "raw"),
        default="redacted",
        help="Sample disclosure policy (default: redacted).",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=5,
        help="Maximum logical data records included as samples (default: 5, max: 100).",
    )
    parser.add_argument(
        "--allowed-read-root",
        action="append",
        default=[],
        help="Require the resolved input to remain under this root; repeatable.",
    )
    parser.add_argument(
        "--allowed-write-root",
        help="Require the resolved output directory to remain under this root.",
    )
    parser.add_argument(
        "--allow-unc",
        action="store_true",
        help="Allow UNC input or output paths when deployment policy permits them.",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Fail when input_profile.json already exists.",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help=f"Maximum source size (default: {DEFAULT_MAX_FILE_BYTES}).",
    )
    parser.add_argument(
        "--sniff-bytes",
        type=int,
        default=DEFAULT_SNIFF_BYTES,
        help=f"Bytes used for format detection (default: {DEFAULT_SNIFF_BYTES}).",
    )
    parser.add_argument(
        "--unique-exact-cap",
        type=int,
        default=DEFAULT_UNIQUE_EXACT_CAP,
        help=f"Distinct values retained per column (default: {DEFAULT_UNIQUE_EXACT_CAP}).",
    )
    parser.add_argument(
        "--duplicate-exact-cap",
        type=int,
        default=DEFAULT_DUPLICATE_EXACT_CAP,
        help=f"Distinct rows retained for duplicate checks (default: {DEFAULT_DUPLICATE_EXACT_CAP}).",
    )
    parser.add_argument(
        "--max-columns",
        type=int,
        default=DEFAULT_MAX_COLUMNS,
        help=f"Maximum source columns (default: {DEFAULT_MAX_COLUMNS}).",
    )
    parser.add_argument(
        "--max-field-chars",
        type=int,
        default=DEFAULT_MAX_FIELD_CHARS,
        help=f"Maximum decoded characters in one field (default: {DEFAULT_MAX_FIELD_CHARS}).",
    )
    parser.add_argument("--version", action="version", version=PROFILER_VERSION)
    return parser


def validate_arguments(args: argparse.Namespace) -> None:
    if not TASK_ID_RE.fullmatch(args.task_id):
        raise ProfileError(
            "INVALID_ARGUMENT",
            "--task-id must contain 1-128 ASCII letters, digits, dots, underscores, or hyphens.",
            exit_code=2,
        )
    bounded_positive = {
        "--max-file-bytes": args.max_file_bytes,
        "--sniff-bytes": args.sniff_bytes,
        "--unique-exact-cap": args.unique_exact_cap,
        "--duplicate-exact-cap": args.duplicate_exact_cap,
        "--max-columns": args.max_columns,
        "--max-field-chars": args.max_field_chars,
    }
    for option, value in bounded_positive.items():
        if value <= 0:
            raise ProfileError(
                "INVALID_ARGUMENT",
                f"{option} must be greater than zero.",
                exit_code=2,
            )
    if not 0 <= args.sample_rows <= MAX_SAMPLE_ROWS:
        raise ProfileError(
            "INVALID_ARGUMENT",
            f"--sample-rows must be between 0 and {MAX_SAMPLE_ROWS}.",
            exit_code=2,
        )


def looks_like_unc(raw_path: str) -> bool:
    normalized = raw_path.replace("/", "\\")
    return normalized.startswith("\\\\")


def looks_like_device_path(raw_path: str) -> bool:
    normalized = raw_path.replace("/", "\\")
    folded = normalized.casefold()
    return folded.startswith("\\\\.\\") or folded.startswith("\\\\?\\")


def validate_path_syntax(raw_path: str, allow_unc: bool) -> None:
    if looks_like_device_path(raw_path):
        raise ProfileError(
            "PATH_NOT_ALLOWED",
            "Windows device paths are not allowed.",
            exit_code=3,
        )
    if looks_like_unc(raw_path) and not allow_unc:
        raise ProfileError(
            "UNC_PATH_NOT_ALLOWED",
            "UNC paths are disabled; pass --allow-unc only when deployment policy permits them.",
            exit_code=3,
        )
    if os.name == "nt":
        _drive, tail = os.path.splitdrive(raw_path)
        if ":" in tail:
            raise ProfileError(
                "PATH_NOT_ALLOWED",
                "Windows alternate data stream paths are not allowed.",
                exit_code=3,
            )


def is_within(candidate: Path, root: Path) -> bool:
    candidate_text = os.path.normcase(os.path.abspath(str(candidate)))
    root_text = os.path.normcase(os.path.abspath(str(root)))
    try:
        return os.path.commonpath((candidate_text, root_text)) == root_text
    except ValueError:
        return False


def resolve_existing_root(raw_root: str, allow_unc: bool, option_name: str) -> Path:
    validate_path_syntax(raw_root, allow_unc)
    try:
        root = Path(raw_root).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise ProfileError(
            "INVALID_ARGUMENT",
            f"{option_name} does not exist.",
            details={"option": option_name},
            exit_code=2,
        ) from exc
    except (OSError, RuntimeError) as exc:
        raise ProfileError(
            "INVALID_ARGUMENT",
            f"{option_name} cannot be resolved.",
            details={"option": option_name, "os_error": type(exc).__name__},
            exit_code=2,
        ) from exc
    if not root.is_dir():
        raise ProfileError(
            "INVALID_ARGUMENT",
            f"{option_name} must be a directory.",
            details={"option": option_name},
            exit_code=2,
        )
    return root


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    validate_path_syntax(args.input, args.allow_unc)
    validate_path_syntax(args.output_dir, args.allow_unc)

    try:
        input_path = Path(args.input).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise ProfileError(
            "FILE_NOT_FOUND",
            "The input CSV does not exist.",
            exit_code=4,
        ) from exc
    except PermissionError as exc:
        raise ProfileError(
            "FILE_BUSY_OR_PERMISSION",
            "The input CSV cannot be resolved because access is denied.",
            exit_code=4,
        ) from exc
    except (OSError, RuntimeError) as exc:
        raise ProfileError(
            "SOURCE_READ_ERROR",
            "The input CSV path cannot be resolved.",
            details={"os_error": type(exc).__name__},
            exit_code=4,
        ) from exc

    try:
        source_stat = input_path.stat()
    except PermissionError as exc:
        raise ProfileError(
            "FILE_BUSY_OR_PERMISSION",
            "The input CSV cannot be inspected because access is denied.",
            exit_code=4,
        ) from exc
    except OSError as exc:
        raise ProfileError(
            "SOURCE_READ_ERROR",
            "The input CSV cannot be inspected.",
            details={"os_error": type(exc).__name__},
            exit_code=4,
        ) from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise ProfileError(
            "NOT_REGULAR_FILE",
            "The input path must refer to one regular file.",
            exit_code=4,
        )
    if source_stat.st_size > args.max_file_bytes:
        raise ProfileError(
            "FILE_TOO_LARGE",
            "The input CSV exceeds --max-file-bytes.",
            details={"size_bytes": source_stat.st_size, "max_file_bytes": args.max_file_bytes},
            exit_code=4,
        )

    read_roots = [
        resolve_existing_root(raw_root, args.allow_unc, "--allowed-read-root")
        for raw_root in args.allowed_read_root
    ]
    if read_roots and not any(is_within(input_path, root) for root in read_roots):
        raise ProfileError(
            "PATH_NOT_ALLOWED",
            "The resolved input CSV is outside the allowed read roots.",
            exit_code=3,
        )

    try:
        output_dir = Path(args.output_dir).expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ProfileError(
            "OUTPUT_WRITE_ERROR",
            "The output directory cannot be resolved.",
            details={"os_error": type(exc).__name__},
            exit_code=6,
        ) from exc

    write_root: Path | None = None
    if args.allowed_write_root:
        validate_path_syntax(args.allowed_write_root, args.allow_unc)
        write_root = resolve_existing_root(
            args.allowed_write_root,
            args.allow_unc,
            "--allowed-write-root",
        )
        if not is_within(output_dir, write_root):
            raise ProfileError(
                "PATH_NOT_ALLOWED",
                "The resolved output directory is outside the allowed write root.",
                exit_code=3,
            )

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_dir = output_dir.resolve(strict=True)
    except PermissionError as exc:
        raise ProfileError(
            "OUTPUT_WRITE_ERROR",
            "The output directory cannot be created because access is denied.",
            exit_code=6,
        ) from exc
    except OSError as exc:
        raise ProfileError(
            "OUTPUT_WRITE_ERROR",
            "The output directory cannot be created.",
            details={"os_error": type(exc).__name__},
            exit_code=6,
        ) from exc
    if not output_dir.is_dir():
        raise ProfileError(
            "OUTPUT_WRITE_ERROR",
            "--output-dir must refer to a directory.",
            exit_code=6,
        )
    if write_root is not None and not is_within(output_dir, write_root):
        raise ProfileError(
            "PATH_NOT_ALLOWED",
            "The created output directory escaped the allowed write root.",
            exit_code=3,
        )

    output_path = output_dir / "input_profile.json"
    if input_path == output_path:
        raise ProfileError(
            "INPUT_OUTPUT_COLLISION",
            "The output profile would overwrite the input CSV.",
            exit_code=3,
        )
    if args.no_overwrite and output_path.exists():
        raise ProfileError(
            "OUTPUT_EXISTS",
            "input_profile.json already exists and --no-overwrite was supplied.",
            exit_code=6,
        )
    return input_path, output_dir, output_path


def read_sniff_bytes(input_path: Path, sniff_bytes: int) -> bytes:
    try:
        with input_path.open("rb") as source:
            return source.read(sniff_bytes)
    except PermissionError as exc:
        raise ProfileError(
            "FILE_BUSY_OR_PERMISSION",
            "The input CSV cannot be read because it is locked or access is denied.",
            exit_code=4,
        ) from exc
    except OSError as exc:
        raise ProfileError(
            "SOURCE_READ_ERROR",
            "The input CSV cannot be sampled.",
            details={"os_error": type(exc).__name__},
            exit_code=4,
        ) from exc


def sha256_file(input_path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with input_path.open("rb") as source:
            while True:
                block = source.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
    except PermissionError as exc:
        raise ProfileError(
            "FILE_BUSY_OR_PERMISSION",
            "The input CSV cannot be hashed because it is locked or access is denied.",
            exit_code=4,
        ) from exc
    except OSError as exc:
        raise ProfileError(
            "SOURCE_READ_ERROR",
            "The input CSV cannot be hashed.",
            details={"os_error": type(exc).__name__},
            exit_code=4,
        ) from exc
    return digest.hexdigest()


def decode_prefix(raw_prefix: bytes, encoding: str) -> str:
    try:
        decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
        return decoder.decode(raw_prefix, final=False)
    except UnicodeDecodeError as exc:
        raise ProfileError(
            "ENCODING_DECODE_ERROR",
            "The sampled bytes cannot be decoded with the selected encoding.",
            details={
                "encoding": encoding,
                "byte_offset": exc.start,
            },
            exit_code=5,
        ) from exc
    except LookupError as exc:
        raise ProfileError(
            "UNSUPPORTED_ENCODING",
            "The selected Python runtime does not provide the requested encoding.",
            details={"encoding": encoding},
            exit_code=5,
        ) from exc


def validate_text_prefix(text: str) -> None:
    if "\x00" in text:
        raise ProfileError(
            "UNSUPPORTED_ENCODING",
            "The decoded sample contains NUL characters and is likely not a supported CSV encoding.",
            exit_code=5,
        )
    if not text:
        return
    disallowed_controls = sum(
        1
        for character in text
        if ord(character) < 32 and character not in "\r\n\t"
    )
    if disallowed_controls / len(text) > 0.01:
        raise ProfileError(
            "UNSUPPORTED_ENCODING",
            "The decoded sample contains too many control characters.",
            details={"control_character_count": disallowed_controls},
            exit_code=5,
        )


def detect_encoding(raw_prefix: bytes, requested: str) -> tuple[EncodingDecision, str]:
    if raw_prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        raise ProfileError(
            "UNSUPPORTED_ENCODING",
            "UTF-16 CSV input is outside this Skill's supported encoding contract.",
            details={"supported": ["utf-8", "utf-8-sig", "gbk", "gb18030"]},
            exit_code=5,
        )

    has_utf8_bom = raw_prefix.startswith(codecs.BOM_UTF8)
    if requested != "auto":
        encoding = requested
        method = "explicit"
        if has_utf8_bom and requested in {"utf-8", "utf-8-sig"}:
            encoding = "utf-8-sig"
            method = "explicit-with-bom"
        text = decode_prefix(raw_prefix, encoding)
        validate_text_prefix(text)
        return EncodingDecision(encoding, method, has_utf8_bom), text

    if has_utf8_bom:
        text = decode_prefix(raw_prefix, "utf-8-sig")
        validate_text_prefix(text)
        return EncodingDecision("utf-8-sig", "bom", True), text

    try:
        text = codecs.getincrementaldecoder("utf-8")(errors="strict").decode(
            raw_prefix,
            final=False,
        )
    except UnicodeDecodeError:
        text = decode_prefix(raw_prefix, "gb18030")
        validate_text_prefix(text)
        return EncodingDecision("gb18030", "strict-fallback", False), text

    validate_text_prefix(text)
    return EncodingDecision("utf-8", "strict-utf8", False), text


def detect_line_ending(raw_prefix: bytes) -> str:
    crlf_count = raw_prefix.count(b"\r\n")
    lf_count = raw_prefix.count(b"\n") - crlf_count
    cr_count = raw_prefix.count(b"\r") - crlf_count
    present = [
        name
        for name, count in (("crlf", crlf_count), ("lf", lf_count), ("cr", cr_count))
        if count > 0
    ]
    if not present:
        return "none"
    if len(present) > 1:
        return "mixed"
    return present[0]


def find_sep_declaration(text: str) -> str | None:
    match = re.match(r"^\ufeff?sep=([,;|\t])\s*(?:\r\n|\n|\r|$)", text, flags=re.IGNORECASE)
    return match.group(1) if match else None


def score_delimiter(text: str, name: str, delimiter: str) -> dict[str, Any]:
    rows: list[list[str]] = []
    parse_error = False
    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=delimiter,
        quotechar='"',
        doublequote=True,
        strict=True,
    )
    try:
        for row in reader:
            if not row:
                continue
            rows.append(row)
            if len(rows) >= 100:
                break
    except csv.Error:
        parse_error = True

    if not rows:
        return {
            "name": name,
            "value": delimiter,
            "sample_records": 0,
            "modal_width": 0,
            "consistent_ratio": 0.0,
            "header_matches_mode": False,
            "parse_error": parse_error,
            "plausible": False,
        }

    width_counts = Counter(len(row) for row in rows)
    modal_width, modal_count = max(
        width_counts.items(),
        key=lambda item: (item[1], item[0]),
    )
    consistency = modal_count / len(rows)
    header_matches = len(rows[0]) == modal_width
    plausible = (
        modal_width > 1
        and header_matches
        and consistency >= 0.8
        and not parse_error
    )
    return {
        "name": name,
        "value": delimiter,
        "sample_records": len(rows),
        "modal_width": modal_width,
        "consistent_ratio": round(consistency, 6),
        "header_matches_mode": header_matches,
        "parse_error": parse_error,
        "plausible": plausible,
    }


def delimiter_rank(score: dict[str, Any]) -> tuple[int, int, float, int, int]:
    return (
        int(not score["parse_error"]),
        int(score["header_matches_mode"]),
        float(score["consistent_ratio"]),
        int(score["sample_records"]),
        int(score["modal_width"]),
    )


def detect_delimiter(text: str, requested: str) -> DelimiterDecision:
    sep_declaration = find_sep_declaration(text)
    if requested != "auto":
        explicit = DELIMITER_BY_NAME[requested]
        if sep_declaration is not None and sep_declaration != explicit:
            raise ProfileError(
                "DELIMITER_CONFLICT",
                "The explicit delimiter conflicts with the file's sep= declaration.",
                details={
                    "explicit": requested,
                    "declared": DELIMITER_NAME_BY_VALUE[sep_declaration],
                },
                exit_code=5,
            )
        return DelimiterDecision(
            value=explicit,
            name=requested,
            method="explicit-with-sep-declaration" if sep_declaration else "explicit",
            skip_sep_declaration=sep_declaration is not None,
        )

    if sep_declaration is not None:
        return DelimiterDecision(
            value=sep_declaration,
            name=DELIMITER_NAME_BY_VALUE[sep_declaration],
            method="sep-declaration",
            skip_sep_declaration=True,
        )

    scores = [score_delimiter(text, name, value) for name, value in DELIMITERS]
    plausible = [score for score in scores if score["plausible"]]
    if not plausible:
        return DelimiterDecision(
            value=",",
            name="comma",
            method="single-column-default",
            skip_sep_declaration=False,
            candidates=scores,
            single_column_default=True,
        )

    ordered = sorted(
        plausible,
        key=lambda score: (
            delimiter_rank(score),
            -list(DELIMITER_BY_NAME).index(score["name"]),
        ),
        reverse=True,
    )
    top = ordered[0]
    if len(ordered) > 1 and delimiter_rank(top) == delimiter_rank(ordered[1]):
        tied_rank = delimiter_rank(top)
        tied = [score["name"] for score in ordered if delimiter_rank(score) == tied_rank]
        raise ProfileError(
            "DELIMITER_AMBIGUOUS",
            "CSV delimiter detection is ambiguous; pass --delimiter explicitly.",
            details={"candidates": tied},
            exit_code=5,
        )

    return DelimiterDecision(
        value=str(top["value"]),
        name=str(top["name"]),
        method="detected",
        skip_sep_declaration=False,
        candidates=scores,
    )


def infer_column_type(accumulator: ColumnAccumulator) -> tuple[str, str | None, float]:
    count = accumulator.non_missing_count
    if count == 0:
        return "empty", None, 1.0
    if accumulator.boolean_count == count:
        return "boolean", "boolean", 1.0
    if accumulator.number_count == count:
        dominant = "integer" if accumulator.integer_count == count else "number"
        if accumulator.leading_zero_count > 0:
            return "string", dominant, 1.0
        return dominant, dominant, 1.0
    temporal_count = accumulator.date_count + accumulator.datetime_count
    if temporal_count == count:
        dominant = "datetime" if accumulator.datetime_count > 0 else "date"
        return dominant, dominant, 1.0

    numeric_kind = "integer" if accumulator.integer_count == accumulator.number_count else "number"
    candidates = (
        ("boolean", accumulator.boolean_count),
        (numeric_kind, accumulator.number_count),
        ("datetime" if accumulator.datetime_count else "date", temporal_count),
    )
    dominant_kind, dominant_count = max(candidates, key=lambda item: (item[1], item[0]))
    if dominant_count / count >= 0.5:
        return "mixed", dominant_kind, round(dominant_count / count, 6)
    return "string", None, 1.0


def build_header_groups(headers: Sequence[str]) -> tuple[list[str], list[dict[str, Any]]]:
    blank_ids: list[str] = []
    grouped: dict[str, list[str]] = {}
    for index, header in enumerate(headers):
        column_id = f"c{index + 1:04d}"
        normalized = normalize_header_name(header)
        if normalized == "":
            blank_ids.append(column_id)
        else:
            grouped.setdefault(normalized, []).append(column_id)
    duplicate_groups = [
        {"normalized_name": normalized, "column_ids": column_ids}
        for normalized, column_ids in sorted(grouped.items())
        if len(column_ids) > 1
    ]
    return blank_ids, duplicate_groups


def determine_candidate_roles(
    header: str,
    kind: str,
    accumulator: ColumnAccumulator,
    unique_count: int,
    unique_mode: str,
) -> list[str]:
    roles: list[str] = []
    non_missing = accumulator.non_missing_count
    unique_ratio = unique_count / non_missing if non_missing and unique_mode == "exact" else 0.0

    is_time = kind in {"date", "datetime"} or header_has_hint(header, TIME_HINTS)
    identifier_hint = header_has_hint(header, IDENTIFIER_HINTS)
    is_identifier = (
        identifier_hint
        or accumulator.leading_zero_count > 0
        or (
            kind == "string"
            and non_missing >= 5
            and unique_mode == "exact"
            and unique_ratio >= 0.98
        )
    )
    is_numeric = kind in {"integer", "number"} and not identifier_hint
    categorical_by_cardinality = (
        unique_mode == "exact"
        and non_missing > 0
        and unique_count <= 50
        and unique_ratio <= 0.5
    )
    is_categorical = (
        not is_time
        and (
            kind == "boolean"
            or header_has_hint(header, CATEGORY_HINTS)
            or (kind in {"string", "integer"} and categorical_by_cardinality)
        )
    )

    if is_time:
        roles.append("time")
    if is_numeric:
        roles.append("numeric")
    if is_categorical:
        roles.append("categorical")
    if is_identifier:
        roles.append("identifier")
    return roles


def parse_csv(
    input_path: Path,
    encoding: EncodingDecision,
    delimiter: DelimiterDecision,
    args: argparse.Namespace,
) -> dict[str, Any]:
    try:
        csv.field_size_limit(args.max_field_chars)
    except OverflowError as exc:
        raise ProfileError(
            "INVALID_ARGUMENT",
            "--max-field-chars exceeds this Python runtime's supported integer range.",
            exit_code=2,
        ) from exc

    try:
        source = input_path.open(
            "r",
            encoding=encoding.name,
            errors="strict",
            newline="",
        )
    except PermissionError as exc:
        raise ProfileError(
            "FILE_BUSY_OR_PERMISSION",
            "The input CSV cannot be opened because it is locked or access is denied.",
            exit_code=4,
        ) from exc
    except OSError as exc:
        raise ProfileError(
            "SOURCE_READ_ERROR",
            "The input CSV cannot be opened.",
            details={"os_error": type(exc).__name__},
            exit_code=4,
        ) from exc

    with source:
        reader = csv.reader(
            source,
            delimiter=delimiter.value,
            quotechar='"',
            doublequote=True,
            strict=True,
        )
        try:
            if delimiter.skip_sep_declaration:
                try:
                    next(reader)
                except StopIteration as exc:
                    raise ProfileError(
                        "CSV_PARSE_ERROR",
                        "The CSV contains a sep= declaration but no header record.",
                        exit_code=5,
                    ) from exc

            leading_blank_records = 0
            headers: list[str] | None = None
            for row in reader:
                if row == []:
                    leading_blank_records += 1
                    continue
                headers = row
                break
            if headers is None:
                raise ProfileError(
                    "CSV_PARSE_ERROR",
                    "The CSV does not contain a header record.",
                    exit_code=5,
                )
            if any("\x00" in value for value in headers):
                raise ProfileError(
                    "CSV_PARSE_ERROR",
                    "The CSV header contains a NUL character.",
                    details={"line_number": reader.line_num},
                    exit_code=5,
                )
            if len(headers) > args.max_columns:
                raise ProfileError(
                    "TOO_MANY_COLUMNS",
                    "The CSV header exceeds --max-columns.",
                    details={"column_count": len(headers), "max_columns": args.max_columns},
                    exit_code=5,
                )

            accumulators = [ColumnAccumulator() for _header in headers]
            row_count = 0
            blank_records_skipped = 0
            retained_samples: list[tuple[int, list[str]]] = []
            retained_rows: set[tuple[str, ...]] = set()
            duplicate_count = 0
            duplicate_capped = False

            for row in reader:
                if row == []:
                    blank_records_skipped += 1
                    continue
                if len(row) != len(headers):
                    raise ProfileError(
                        "CSV_PARSE_ERROR",
                        "A logical CSV record has a different field count from the header.",
                        details={
                            "line_number": reader.line_num,
                            "expected_fields": len(headers),
                            "actual_fields": len(row),
                        },
                        exit_code=5,
                    )
                if any("\x00" in value for value in row):
                    raise ProfileError(
                        "CSV_PARSE_ERROR",
                        "A logical CSV record contains a NUL character.",
                        details={"line_number": reader.line_num},
                        exit_code=5,
                    )

                row_count += 1
                if len(retained_samples) < args.sample_rows and args.sample_mode != "none":
                    retained_samples.append((row_count, list(row)))

                row_key = tuple(row)
                if row_key in retained_rows:
                    duplicate_count += 1
                elif not duplicate_capped:
                    if len(retained_rows) < args.duplicate_exact_cap:
                        retained_rows.add(row_key)
                    else:
                        duplicate_capped = True

                for accumulator, value in zip(accumulators, row):
                    accumulator.observe(value, args.unique_exact_cap)

        except UnicodeDecodeError as exc:
            raise ProfileError(
                "ENCODING_DECODE_ERROR",
                "The full CSV cannot be decoded with the selected encoding.",
                details={"encoding": encoding.name, "byte_offset_in_buffer": exc.start},
                exit_code=5,
            ) from exc
        except csv.Error as exc:
            message = str(exc)
            code = "FIELD_TOO_LARGE" if "field larger than field limit" in message.casefold() else "CSV_PARSE_ERROR"
            raise ProfileError(
                code,
                "The CSV parser rejected the file structure.",
                details={"line_number": reader.line_num, "parser_error": message},
                exit_code=5,
            ) from exc

    blank_header_ids, duplicate_header_groups = build_header_groups(headers)
    duplicate_header_ids = {
        column_id
        for group in duplicate_header_groups
        for column_id in group["column_ids"]
    }

    columns: list[dict[str, Any]] = []
    candidate_fields: dict[str, list[str]] = {
        "time": [],
        "numeric": [],
        "categorical": [],
        "identifier": [],
    }
    empty_columns: list[str] = []
    constant_columns: list[str] = []
    suspected_primary_keys: list[str] = []
    suspected_key_duplicates: list[dict[str, Any]] = []
    sensitive_column_ids: set[str] = set()
    unique_capped_ids: list[str] = []
    mixed_type_ids: list[str] = []
    null_like_ids: list[str] = []
    leading_zero_ids: list[str] = []

    for index, (header, accumulator) in enumerate(zip(headers, accumulators)):
        column_id = f"c{index + 1:04d}"
        kind, dominant_kind, parse_ratio = infer_column_type(accumulator)
        unique_mode = "lower_bound" if accumulator.unique_capped else "exact"
        unique_count = len(accumulator.unique_values)
        roles = determine_candidate_roles(
            header,
            kind,
            accumulator,
            unique_count,
            unique_mode,
        )
        sensitive = header_has_hint(header, SENSITIVE_HINTS) or accumulator.sensitive_value_count > 0
        if sensitive:
            sensitive_column_ids.add(column_id)

        flags: list[str] = []
        if column_id in blank_header_ids:
            flags.append("blank_header")
        if column_id in duplicate_header_ids:
            flags.append("duplicate_header")
        if accumulator.non_missing_count == 0:
            flags.append("empty_column")
            empty_columns.append(column_id)
        elif unique_mode == "exact" and unique_count == 1:
            flags.append("constant_column")
            constant_columns.append(column_id)
        if accumulator.leading_zero_count > 0:
            flags.append("leading_zero_values")
            leading_zero_ids.append(column_id)
        if accumulator.null_like_count > 0:
            flags.append("null_like_values_present")
            null_like_ids.append(column_id)
        if kind == "mixed":
            flags.append("mixed_types")
            mixed_type_ids.append(column_id)
        if sensitive:
            flags.append("sensitive_values")
        if accumulator.unique_capped:
            flags.append("unique_count_capped")
            unique_capped_ids.append(column_id)

        is_suspected_primary_key = (
            "identifier" in roles
            and row_count > 0
            and accumulator.missing_count == 0
            and unique_mode == "exact"
            and unique_count == row_count
        )
        if is_suspected_primary_key:
            flags.append("suspected_primary_key")
            suspected_primary_keys.append(column_id)

        duplicate_non_missing = 0
        if "identifier" in roles and unique_mode == "exact":
            duplicate_non_missing = accumulator.non_missing_count - unique_count
        if duplicate_non_missing > 0:
            flags.append("suspected_key_duplicates")
            suspected_key_duplicates.append(
                {
                    "column_id": column_id,
                    "duplicate_non_missing_count": duplicate_non_missing,
                    "mode": "exact",
                }
            )

        for role in roles:
            candidate_fields[role].append(column_id)

        columns.append(
            {
                "id": column_id,
                "name": header,
                "source_name": header,
                "index": index,
                "inferred_type": kind,
                "type_details": {
                    "dominant_kind": dominant_kind,
                    "parse_ratio": parse_ratio,
                },
                "non_missing_count": accumulator.non_missing_count,
                "missing_count": accumulator.missing_count,
                "missing_rate": round(accumulator.missing_count / row_count, 6)
                if row_count
                else 0.0,
                "null_like_count": accumulator.null_like_count,
                "unique_count": unique_count,
                "unique_count_mode": unique_mode,
                "candidate_roles": roles,
                "flags": flags,
                "sensitive": sensitive,
            }
        )

    samples: list[dict[str, Any]] = []
    if args.sample_mode != "none":
        for record_number, values in retained_samples:
            sample_values: dict[str, str] = {}
            for index, value in enumerate(values):
                column_id = f"c{index + 1:04d}"
                if (
                    args.sample_mode == "redacted"
                    and column_id in sensitive_column_ids
                    and value.strip() != ""
                ):
                    sample_values[column_id] = "<redacted>"
                else:
                    sample_values[column_id] = value
            samples.append({"record_number": record_number, "values": sample_values})

    warnings = build_warnings(
        delimiter=delimiter,
        leading_blank_records=leading_blank_records,
        blank_records_skipped=blank_records_skipped,
        blank_header_ids=blank_header_ids,
        duplicate_header_groups=duplicate_header_groups,
        duplicate_count=duplicate_count,
        duplicate_capped=duplicate_capped,
        empty_columns=empty_columns,
        constant_columns=constant_columns,
        null_like_ids=null_like_ids,
        mixed_type_ids=mixed_type_ids,
        leading_zero_ids=leading_zero_ids,
        unique_capped_ids=unique_capped_ids,
        suspected_key_duplicates=suspected_key_duplicates,
        sensitive_column_ids=sorted(sensitive_column_ids),
        sample_mode=args.sample_mode,
    )

    return {
        "headers": headers,
        "row_count": row_count,
        "columns": columns,
        "candidate_fields": candidate_fields,
        "quality": {
            "duplicate_rows": {
                "count": duplicate_count,
                "mode": "lower_bound" if duplicate_capped else "exact",
            },
            "blank_headers": blank_header_ids,
            "duplicate_headers": duplicate_header_groups,
            "suspected_primary_keys": suspected_primary_keys,
            "suspected_key_duplicates": suspected_key_duplicates,
            "empty_columns": empty_columns,
            "constant_columns": constant_columns,
        },
        "samples": samples,
        "warnings": warnings,
        "leading_blank_records": leading_blank_records,
        "blank_records_skipped": blank_records_skipped,
        "duplicate_capped": duplicate_capped,
        "unique_capped_ids": unique_capped_ids,
    }


def warning(
    code: str,
    message: str,
    *,
    columns: Sequence[str] | None = None,
    details: dict[str, Any] | None = None,
    severity: str = "warning",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if columns:
        item["columns"] = list(columns)
    if details:
        item["details"] = details
    return item


def build_warnings(
    *,
    delimiter: DelimiterDecision,
    leading_blank_records: int,
    blank_records_skipped: int,
    blank_header_ids: Sequence[str],
    duplicate_header_groups: Sequence[dict[str, Any]],
    duplicate_count: int,
    duplicate_capped: bool,
    empty_columns: Sequence[str],
    constant_columns: Sequence[str],
    null_like_ids: Sequence[str],
    mixed_type_ids: Sequence[str],
    leading_zero_ids: Sequence[str],
    unique_capped_ids: Sequence[str],
    suspected_key_duplicates: Sequence[dict[str, Any]],
    sensitive_column_ids: Sequence[str],
    sample_mode: str,
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if delimiter.single_column_default:
        warnings.append(
            warning(
                "SINGLE_COLUMN_DELIMITER_DEFAULT",
                "No supported delimiter produced multiple fields; comma was used for a single-column CSV.",
            )
        )
    if leading_blank_records:
        warnings.append(
            warning(
                "LEADING_BLANK_RECORDS",
                "Blank physical records before the header were ignored.",
                details={"count": leading_blank_records},
            )
        )
    if blank_records_skipped:
        warnings.append(
            warning(
                "BLANK_RECORDS_SKIPPED",
                "Blank physical records after the header were excluded from row_count.",
                details={"count": blank_records_skipped},
            )
        )
    if blank_header_ids:
        warnings.append(
            warning(
                "BLANK_HEADERS",
                "One or more source header cells are blank; stable column IDs must be used.",
                columns=blank_header_ids,
            )
        )
    if duplicate_header_groups:
        affected = [
            column_id
            for group in duplicate_header_groups
            for column_id in group["column_ids"]
        ]
        warnings.append(
            warning(
                "DUPLICATE_HEADERS",
                "One or more source header names are duplicated after trimming and case folding.",
                columns=affected,
                details={"group_count": len(duplicate_header_groups)},
            )
        )
    if duplicate_count:
        warnings.append(
            warning(
                "DUPLICATE_ROWS",
                "Duplicate logical data records were detected.",
                details={
                    "count": duplicate_count,
                    "mode": "lower_bound" if duplicate_capped else "exact",
                },
            )
        )
    if duplicate_capped:
        warnings.append(
            warning(
                "DUPLICATE_COUNT_CAPPED",
                "The duplicate-row retention cap was reached; the duplicate count is a lower bound.",
            )
        )
    if empty_columns:
        warnings.append(
            warning(
                "EMPTY_COLUMNS",
                "One or more columns contain no non-missing values.",
                columns=empty_columns,
            )
        )
    if constant_columns:
        warnings.append(
            warning(
                "CONSTANT_COLUMNS",
                "One or more columns contain one distinct non-missing value.",
                columns=constant_columns,
            )
        )
    if null_like_ids:
        warnings.append(
            warning(
                "NULL_LIKE_VALUES",
                "Null-like text is present but was not silently converted to missing data.",
                columns=null_like_ids,
            )
        )
    if mixed_type_ids:
        warnings.append(
            warning(
                "MIXED_TYPES",
                "One or more columns contain mixed lexical types.",
                columns=mixed_type_ids,
            )
        )
    if leading_zero_ids:
        warnings.append(
            warning(
                "LEADING_ZERO_VALUES",
                "Integer-like values with leading zeros were preserved as strings.",
                columns=leading_zero_ids,
            )
        )
    if unique_capped_ids:
        warnings.append(
            warning(
                "UNIQUE_COUNT_CAPPED",
                "The exact unique-value cap was reached for one or more columns.",
                columns=unique_capped_ids,
            )
        )
    if suspected_key_duplicates:
        warnings.append(
            warning(
                "SUSPECTED_KEY_DUPLICATES",
                "Identifier candidate columns contain duplicate non-missing values.",
                columns=[item["column_id"] for item in suspected_key_duplicates],
            )
        )
    if sensitive_column_ids and sample_mode == "redacted":
        warnings.append(
            warning(
                "SENSITIVE_SAMPLES_REDACTED",
                "Sample values from sensitive-looking columns were redacted.",
                columns=sensitive_column_ids,
                severity="info",
            )
        )
    if sensitive_column_ids and sample_mode == "raw":
        warnings.append(
            warning(
                "RAW_SENSITIVE_SAMPLES_INCLUDED",
                "Raw samples include values from sensitive-looking columns.",
                columns=sensitive_column_ids,
                severity="warning",
            )
        )
    return warnings


def build_profile(
    *,
    args: argparse.Namespace,
    input_path: Path,
    source_size: int,
    source_sha256: str,
    encoding: EncodingDecision,
    delimiter: DelimiterDecision,
    line_ending: str,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "task_id": args.task_id,
        "stage": "profile",
        "status": "success",
        "profiler": {
            "name": "chartpilot-profile-csv",
            "version": PROFILER_VERSION,
            "settings": {
                "sample_mode": args.sample_mode,
                "sample_rows": args.sample_rows,
                "max_file_bytes": args.max_file_bytes,
                "sniff_bytes": args.sniff_bytes,
                "unique_exact_cap": args.unique_exact_cap,
                "duplicate_exact_cap": args.duplicate_exact_cap,
                "max_columns": args.max_columns,
                "max_field_chars": args.max_field_chars,
            },
        },
        "source": {
            "path": str(input_path),
            "file_name": input_path.name,
            "size_bytes": source_size,
            "sha256": source_sha256,
            "encoding": encoding.name,
            "delimiter": delimiter.value,
        },
        "format": {
            "encoding": {
                "value": encoding.name,
                "method": encoding.method,
                "bom": encoding.bom,
            },
            "delimiter": {
                "value": delimiter.value,
                "name": delimiter.name,
                "method": delimiter.method,
                "candidates": delimiter.candidates,
            },
            "quotechar": '"',
            "line_ending": line_ending,
        },
        "shape": {
            "row_count": parsed["row_count"],
            "column_count": len(parsed["headers"]),
        },
        "scan": {
            "mode": "full-stream",
            "sample_mode": args.sample_mode,
            "sample_count": len(parsed["samples"]),
            "leading_blank_records": parsed["leading_blank_records"],
            "blank_records_skipped": parsed["blank_records_skipped"],
            "duplicate_count_mode": "lower_bound" if parsed["duplicate_capped"] else "exact",
            "unique_count_capped_columns": parsed["unique_capped_ids"],
        },
        "columns": parsed["columns"],
        "candidate_fields": parsed["candidate_fields"],
        "quality": parsed["quality"],
        "samples": parsed["samples"],
        "warnings": parsed["warnings"],
    }


def atomic_write_profile(
    output_path: Path,
    profile: dict[str, Any],
    no_overwrite: bool,
) -> None:
    if no_overwrite and output_path.exists():
        raise ProfileError(
            "OUTPUT_EXISTS",
            "input_profile.json already exists and --no-overwrite was supplied.",
            exit_code=6,
        )

    file_descriptor: int | None = None
    temporary_path: str | None = None
    try:
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=".input_profile.",
            suffix=".tmp",
            dir=str(output_path.parent),
        )
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as destination:
            file_descriptor = None
            json.dump(
                profile,
                destination,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        if no_overwrite and output_path.exists():
            raise ProfileError(
                "OUTPUT_EXISTS",
                "input_profile.json appeared while --no-overwrite was active.",
                exit_code=6,
            )
        os.replace(temporary_path, output_path)
        temporary_path = None
    except ProfileError:
        raise
    except PermissionError as exc:
        raise ProfileError(
            "OUTPUT_WRITE_ERROR",
            "input_profile.json cannot be installed because access is denied or the file is locked.",
            exit_code=6,
        ) from exc
    except (OSError, TypeError, ValueError) as exc:
        raise ProfileError(
            "OUTPUT_WRITE_ERROR",
            "input_profile.json could not be written.",
            details={"os_error": type(exc).__name__},
            exit_code=6,
        ) from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_arguments(args)
    input_path, _output_dir, output_path = resolve_paths(args)

    try:
        before_stat = input_path.stat()
    except PermissionError as exc:
        raise ProfileError(
            "FILE_BUSY_OR_PERMISSION",
            "The input CSV cannot be inspected because access is denied.",
            exit_code=4,
        ) from exc
    except OSError as exc:
        raise ProfileError(
            "SOURCE_READ_ERROR",
            "The input CSV cannot be inspected before scanning.",
            details={"os_error": type(exc).__name__},
            exit_code=4,
        ) from exc

    raw_prefix = read_sniff_bytes(input_path, args.sniff_bytes)
    if not raw_prefix:
        raise ProfileError(
            "CSV_PARSE_ERROR",
            "The input CSV is empty.",
            exit_code=5,
        )
    source_sha256 = sha256_file(input_path)
    encoding, decoded_prefix = detect_encoding(raw_prefix, args.encoding)
    delimiter = detect_delimiter(decoded_prefix, args.delimiter)
    line_ending = detect_line_ending(raw_prefix)
    parsed = parse_csv(input_path, encoding, delimiter, args)

    try:
        after_stat = input_path.stat()
    except OSError as exc:
        raise ProfileError(
            "SOURCE_CHANGED",
            "The input CSV became unavailable during profiling.",
            details={"os_error": type(exc).__name__},
            exit_code=4,
        ) from exc
    before_identity = (
        before_stat.st_size,
        before_stat.st_mtime_ns,
        getattr(before_stat, "st_ino", None),
    )
    after_identity = (
        after_stat.st_size,
        after_stat.st_mtime_ns,
        getattr(after_stat, "st_ino", None),
    )
    if before_identity != after_identity:
        raise ProfileError(
            "SOURCE_CHANGED",
            "The input CSV changed during profiling; no profile was installed.",
            exit_code=4,
        )

    profile = build_profile(
        args=args,
        input_path=input_path,
        source_size=after_stat.st_size,
        source_sha256=source_sha256,
        encoding=encoding,
        delimiter=delimiter,
        line_ending=line_ending,
        parsed=parsed,
    )
    atomic_write_profile(output_path, profile, args.no_overwrite)
    return {
        "ok": True,
        "profile_path": str(output_path),
        "source_sha256": source_sha256,
    }


def main() -> int:
    try:
        payload = run()
    except ProfileError as exc:
        emit_json(sys.stderr, exc.payload())
        return exc.exit_code
    except KeyboardInterrupt:
        emit_json(
            sys.stderr,
            ProfileError(
                "SOURCE_READ_ERROR",
                "CSV profiling was interrupted.",
                exit_code=4,
            ).payload(),
        )
        return 4
    except Exception as exc:
        emit_json(
            sys.stderr,
            ProfileError(
                "INTERNAL_ERROR",
                "An unexpected internal profiler error occurred.",
                details={"exception_type": type(exc).__name__},
                exit_code=70,
            ).payload(),
        )
        return 70

    emit_json(sys.stdout, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
