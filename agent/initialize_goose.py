from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml


SKILL_NAMES = (
    "chartpilot-run-python",
    "chartpilot-profile-csv",
    "chartpilot-analyze-data",
    "chartpilot-render-chart",
)


def load_mapping(path: Path, *, yaml_input: bool = False) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    value = yaml.safe_load(text) if yaml_input else json.loads(text)
    if value is None and yaml_input:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected a mapping in {path}.")
    return value


def replace_placeholders(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        return value
    if isinstance(value, list):
        return [replace_placeholders(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            str(key): replace_placeholders(item, replacements)
            for key, item in value.items()
        }
    return value


def write_yaml_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(
        dict(value),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def merge_managed_config(
    current: dict[str, Any], template: Mapping[str, Any]
) -> dict[str, Any]:
    for key in ("GOOSE_MODE", "GOOSE_TELEMETRY_ENABLED", "GOOSE_DISABLE_SESSION_NAMING"):
        current.setdefault(key, template[key])

    extensions = current.setdefault("extensions", {})
    if not isinstance(extensions, dict):
        raise ValueError("Goose config field 'extensions' must be a mapping.")
    template_extensions = template["extensions"]
    if not isinstance(template_extensions, dict):
        raise ValueError("Goose template field 'extensions' must be a mapping.")

    summon_template = template_extensions["summon"]
    if "summon" not in extensions:
        extensions["summon"] = summon_template

    chartpilot_template = template_extensions["chartpilot"]
    existing_chartpilot = extensions.get("chartpilot", {})
    if existing_chartpilot is None:
        existing_chartpilot = {}
    if not isinstance(existing_chartpilot, dict):
        raise ValueError("Goose ChartPilot extension config must be a mapping.")
    enabled = existing_chartpilot.get("enabled", True)
    existing_chartpilot.update(chartpilot_template)
    existing_chartpilot["enabled"] = enabled
    extensions["chartpilot"] = existing_chartpilot
    return current


def sync_skill(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{os.getpid()}.new"
    backup = destination.parent / f".{destination.name}.{os.getpid()}.old"
    shutil.rmtree(temporary, ignore_errors=True)
    shutil.rmtree(backup, ignore_errors=True)
    try:
        shutil.copytree(
            source,
            temporary,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        if destination.exists():
            shutil.move(str(destination), str(backup))
        shutil.move(str(temporary), str(destination))
        shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        if backup.exists() and not destination.exists():
            shutil.move(str(backup), str(destination))
        raise


def initialize(
    project_root: Path,
    goose_home: Path,
    template_path: Path,
    allowed_read_roots: Sequence[Path],
) -> dict[str, Any]:
    project_root = project_root.resolve(strict=True)
    goose_home = goose_home.resolve()
    template_path = template_path.resolve(strict=True)
    python = project_root / "runtime/winpython/python/python.exe"
    mcp_server = project_root / "agent/mcp/chartpilot_mcp.py"
    for required in (python, mcp_server):
        if not required.is_file():
            raise FileNotFoundError(f"Required ChartPilot file not found: {required}")

    resolved_roots: list[Path] = []
    for root in allowed_read_roots:
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Allowed read root is not a directory: {resolved}")
        if resolved not in resolved_roots:
            resolved_roots.append(resolved)
    if project_root not in resolved_roots:
        resolved_roots.append(project_root)

    workspace_root = project_root / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    goose_home.mkdir(parents=True, exist_ok=True)
    replacements = {
        "${CHARTPILOT_ROOT}": str(project_root),
        "${CHARTPILOT_PYTHON}": str(python),
        "${CHARTPILOT_MCP_SERVER}": str(mcp_server),
        "${CHARTPILOT_WORKSPACE_ROOT}": str(workspace_root),
        "${CHARTPILOT_ALLOWED_READ_ROOTS}": os.pathsep.join(
            str(root) for root in resolved_roots
        ),
    }
    template = replace_placeholders(load_mapping(template_path), replacements)

    config_path = goose_home / "config/config.yaml"
    current = load_mapping(config_path, yaml_input=True) if config_path.exists() else {}
    merged = merge_managed_config(current, template)
    write_yaml_atomic(config_path, merged)

    # Goose v1.43.0 includes GOOSE_PATH_ROOT/config/skills in global discovery.
    skills_root = goose_home / "config/skills"
    source_skills = project_root / "skills"
    for name in SKILL_NAMES:
        source = source_skills / name
        if not (source / "SKILL.md").is_file():
            raise FileNotFoundError(f"Required ChartPilot Skill not found: {source}")
        sync_skill(source, skills_root / name)

    return {
        "ok": True,
        "config": str(config_path),
        "goose_home": str(goose_home),
        "skills": list(SKILL_NAMES),
        "allowed_read_roots": [str(root) for root in resolved_roots],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize portable ChartPilot Goose state.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--goose-home", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--allowed-read-root", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        roots = [Path(value) for value in args.allowed_read_root]
        result = initialize(
            Path(args.project_root), Path(args.goose_home), Path(args.template), roots
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "GOOSE_INITIALIZATION_FAILED",
                        "message": str(exc),
                        "exception_type": type(exc).__name__,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=os.sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
