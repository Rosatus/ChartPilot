# CSV Profiler Contracts

## Command line

```text
<chartpilot-root>\runtime\winpython\python\python.exe -I <chartpilot-root>\skills\chartpilot-profile-csv\scripts\profile_csv.py INPUT --task-id TASK_ID --output-dir DIRECTORY [OPTIONS]
```

`INPUT` must be one regular local file. The command always writes `DIRECTORY/input_profile.json`; callers cannot choose another output filename.

Resolve the interpreter through the `chartpilot-run-python` contract. Invoke it directly with a
process argument array and never fall back to a system Python interpreter.

Core options:

| Option | Values and default | Meaning |
| --- | --- | --- |
| `--task-id` | required, `[A-Za-z0-9._-]{1,128}` | Stable task identifier copied into the cross-stage profile contract. |
| `--encoding` | `auto`, `utf-8`, `utf-8-sig`, `gbk`, `gb18030`; default `auto` | Override strict decoding. Auto checks a UTF-8 BOM, then strict UTF-8, then strict GB18030. |
| `--delimiter` | `auto`, `comma`, `tab`, `semicolon`, `pipe`; default `auto` | Override dialect detection. |
| `--sample-mode` | `none`, `redacted`, `raw`; default `redacted` | Control values included in `samples`. |
| `--sample-rows` | integer, default `5`, maximum `100` | Bound the number of logical data records included as samples. |
| `--allowed-read-root` | repeatable path | Require the resolved input to remain under one supplied root. |
| `--allowed-write-root` | path | Require the resolved output directory to remain under this root. |
| `--allow-unc` | flag, default off | Permit a UNC path when deployment policy explicitly allows it. |
| `--no-overwrite` | flag, default off | Fail if `input_profile.json` already exists. |
| `--max-file-bytes` | integer, default 1 GiB | Reject larger files before scanning. |
| `--sniff-bytes` | integer, default 1 MiB | Bound the sample used for format detection. |
| `--unique-exact-cap` | integer, default `100000` | Bound distinct values retained per field. |
| `--duplicate-exact-cap` | integer, default `1000000` | Bound complete rows retained for duplicate detection. |
| `--max-columns` | integer, default `10000` | Reject unexpectedly wide input. |
| `--max-field-chars` | integer, default 8 MiB | Reject oversized decoded fields. |

All paths support Unicode and spaces. Invoke the command with a process argument array. Standard output and standard error are UTF-8 JSON, independent of the Windows console code page.

## Success response

Exit code `0` writes one line to standard output:

```json
{
  "ok": true,
  "profile_path": "C:\\ChartPilot\\workspace\\tasks\\T001\\input_profile.json",
  "source_sha256": "64 lowercase hexadecimal characters"
}
```

The output file is written to a temporary file in the same directory, flushed, and atomically replaced. A failed run does not truncate an existing complete profile.

## Profile schema

The top-level contract always contains `schema_version: chartpilot.input-profile/v1`, the requested `task_id`, `stage: profile`, and `status: success`.

| Field | Contract |
| --- | --- |
| `profiler` | Script name, semantic version, and effective bounded-statistics configuration. |
| `source` | Resolved absolute path, basename, byte size, full-file SHA-256, selected encoding, and literal delimiter. Downstream stages must verify the hash before using the path. |
| `format` | Encoding and delimiter values plus decision methods, quote character, line ending, and optional delimiter candidate scores. |
| `shape` | Exact logical data-row count and source column count. Blank physical records outside records are excluded and reported separately. |
| `scan` | Sample policy, emitted sample count, skipped blank records, and whether bounded counters remained exact. |
| `columns` | Source-ordered field profiles keyed by stable IDs `c0001`, `c0002`, and so forth. |
| `candidate_fields` | Source-ordered IDs grouped into `time`, `numeric`, `categorical`, and `identifier`. |
| `quality` | Duplicate-row count, duplicate and blank headers, suspected keys, suspected-key duplicates, empty columns, and constant columns. |
| `samples` | At most the configured number of source-ordered logical records. Values are keyed by stable column ID. |
| `warnings` | Deterministically ordered structured warnings with code, severity, message, and affected column IDs where applicable. |

Each item in `columns` contains:

```json
{
  "id": "c0001",
  "index": 0,
  "name": "订单编号",
  "source_name": "订单编号",
  "inferred_type": "string",
  "type_details": {
    "dominant_kind": "integer",
    "parse_ratio": 1.0
  },
  "non_missing_count": 100,
  "missing_count": 0,
  "missing_rate": 0.0,
  "null_like_count": 0,
  "unique_count": 100,
  "unique_count_mode": "exact",
  "candidate_roles": ["identifier"],
  "flags": ["leading_zero_values", "suspected_primary_key"],
  "sensitive": false
}
```

`missing_count` counts empty or whitespace-only cells. Text such as `NA`, `null`, `None`, `nan`, `无`, or `缺失` is reported in `null_like_count` but is not silently converted to missing data.

`source_name` is the authoritative original header text. `name` contains the same value for compatibility with existing consumers; neither field is normalized or silently deduplicated.

`unique_count_mode` and `quality.duplicate_rows.mode` are either `exact` or `lower_bound`. A lower bound means the configured retention cap was reached; consumers must not state that the reported value is the final count.

`inferred_type` is one of `empty`, `boolean`, `integer`, `number`, `date`, `datetime`, `string`, or `mixed`. Inference is lexical and never converts the source. Leading-zero integer-like values remain strings and are candidates for identifiers. Ambiguous day/month dates remain strings.

In `redacted` sample mode, every value from a sensitive-looking column becomes `<redacted>`. Sensitivity is inferred from header terms and common email, mainland China mobile-number, and resident-ID patterns. This is a conservative aid, not a complete data-loss-prevention system.

## Error response

Every operational failure uses a nonzero exit code and emits one UTF-8 JSON object to standard error:

```json
{
  "ok": false,
  "error": {
    "code": "DELIMITER_AMBIGUOUS",
    "message": "CSV delimiter detection is ambiguous; pass --delimiter explicitly.",
    "details": {
      "candidates": ["comma", "semicolon"]
    }
  }
}
```

Error details contain structural evidence only, never cell contents. Stable codes include:

- `INVALID_ARGUMENT`, `FILE_NOT_FOUND`, `NOT_REGULAR_FILE`, `FILE_TOO_LARGE`
- `PATH_NOT_ALLOWED`, `UNC_PATH_NOT_ALLOWED`, `INPUT_OUTPUT_COLLISION`
- `FILE_BUSY_OR_PERMISSION`, `SOURCE_READ_ERROR`, `SOURCE_CHANGED`
- `UNSUPPORTED_ENCODING`, `ENCODING_DECODE_ERROR`
- `DELIMITER_CONFLICT`, `DELIMITER_AMBIGUOUS`, `CSV_PARSE_ERROR`
- `TOO_MANY_COLUMNS`, `FIELD_TOO_LARGE`
- `OUTPUT_EXISTS`, `OUTPUT_WRITE_ERROR`, `INTERNAL_ERROR`

Exit code categories are `2` for arguments, `3` for path policy, `4` for source I/O, `5` for format or parse failures, `6` for output failures, and `70` for an unexpected internal failure.

## Determinism and ownership

The profile omits generation time and host name. JSON keys and warning arrays use stable ordering, ratios use six decimal places, and samples use the first bounded logical data records. For an unchanged input path, content, effective configuration, task ID, and profiler version, repeated output is byte-identical.

This profiler does not clean, transform, aggregate, execute generated code, draw charts, call the network, or modify the source CSV. The analysis Skill owns those later operations.
