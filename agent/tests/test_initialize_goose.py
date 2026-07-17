from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "agent/initialize_goose.py"
SPEC = importlib.util.spec_from_file_location("initialize_goose", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InitializeGooseTests(unittest.TestCase):
    def test_initialization_preserves_user_config_and_stages_only_product_skills(self) -> None:
        workspace = PROJECT_ROOT / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="goose-init-test-", dir=workspace))
        try:
            goose_home = temporary / "goose"
            template = PROJECT_ROOT / "agent/config/goose-config.template.json"
            MODULE.initialize(PROJECT_ROOT, goose_home, template, [PROJECT_ROOT])
            config_path = goose_home / "config/config.yaml"
            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            skills_root = goose_home / "config/skills"
            for removed_name in MODULE.REMOVED_SKILL_NAMES:
                stale = skills_root / removed_name
                stale.mkdir(parents=True)
                (stale / "SKILL.md").write_text("stale", encoding="utf-8")
            config["active_provider"] = "test-provider"
            config["providers"] = {"test-provider": {"enabled": True, "model": "test"}}
            config["extensions"]["chartpilot"]["enabled"] = False
            config_path.write_text(
                yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
                newline="\n",
            )

            MODULE.initialize(PROJECT_ROOT, goose_home, template, [PROJECT_ROOT])
            updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["active_provider"], "test-provider")
            self.assertIn("test-provider", updated["providers"])
            self.assertFalse(updated["extensions"]["chartpilot"]["enabled"])
            self.assertEqual(updated["extensions"]["chartpilot"]["type"], "stdio")
            self.assertEqual(
                updated["extensions"]["chartpilot"]["available_tools"],
                ["chartpilot_prepare_adaptive_task", "chartpilot_run_task_python"],
            )
            self.assertEqual(
                Path(updated["extensions"]["chartpilot"]["cmd"]).resolve(),
                PROJECT_ROOT / "runtime/winpython/python/python.exe",
            )
            skill_names = sorted(
                path.name for path in skills_root.iterdir() if path.is_dir()
            )
            self.assertEqual(skill_names, sorted(MODULE.SKILL_NAMES))
            staged_reference = (
                skills_root
                / "chartpilot-run-python/references/visual-archetypes.md"
            )
            self.assertTrue(staged_reference.is_file())
            self.assertEqual(
                staged_reference.read_bytes(),
                (
                    PROJECT_ROOT
                    / "skills/chartpilot-run-python/references/visual-archetypes.md"
                ).read_bytes(),
            )
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
