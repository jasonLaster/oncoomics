from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REPO_ROOT = SCRIPT_DIR.parent
RUNBOOK_ROOT = Path("/repo")
LOCAL_MODULES = {
    path.stem: path.relative_to(REPO_ROOT)
    for directory in ("aws", "scripts")
    for path in (REPO_ROOT / directory).glob("*.py")
}
LOCAL_MODULE_PATHS = set(LOCAL_MODULES.values())
RENDERERS = (
    "render_post_success_runbook",
    "render_source_report_freeze_runbook",
    "render_ai_synthesis_runbook",
    "render_reviewed_publication_runbook",
)


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_imports(path: Path) -> dict[Path, int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: dict[Path, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.partition(".")[0]
                if name in LOCAL_MODULES:
                    imports[LOCAL_MODULES[name]] = node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            name = node.module.partition(".")[0]
            if name in LOCAL_MODULES:
                imports[LOCAL_MODULES[name]] = node.lineno
    return imports


def required_local_paths(renderer: str) -> set[Path]:
    module = load_script(renderer)
    return {
        path.relative_to(RUNBOOK_ROOT)
        for path in module.required_existing(RUNBOOK_ROOT)
        if path.is_relative_to(RUNBOOK_ROOT)
        and path.relative_to(RUNBOOK_ROOT) in LOCAL_MODULE_PATHS
    }


def missing_preflight_imports(renderer: str) -> set[str]:
    local_paths = required_local_paths(renderer)
    return {
        f"{path}:{line} imports {dependency}"
        for path in local_paths
        for dependency, line in local_imports(REPO_ROOT / path).items()
        if dependency not in local_paths
    }


class RunbookPreflightDependencyTests(unittest.TestCase):
    def test_handoff_preflights_include_transitive_local_imports(self) -> None:
        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                self.assertEqual(missing_preflight_imports(renderer), set())

    def test_post_success_preflight_covers_aws_route_submitter_imports(self) -> None:
        local_paths = required_local_paths("render_post_success_runbook")

        self.assertIn(Path("aws/submit_route.py"), local_paths)
        self.assertIn(Path("scripts/check_contract.py"), local_paths)


if __name__ == "__main__":
    unittest.main()
