from __future__ import annotations

import ast
import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

LOCAL_SCRIPTS = {path.stem for path in SCRIPT_DIR.glob("*.py")}
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


def local_script_imports(script: str) -> dict[str, int]:
    tree = ast.parse((SCRIPT_DIR / f"{script}.py").read_text(encoding="utf-8"))
    imports: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.partition(".")[0]
                if name in LOCAL_SCRIPTS:
                    imports[name] = node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            name = node.module.partition(".")[0]
            if name in LOCAL_SCRIPTS:
                imports[name] = node.lineno
    return imports


class RunbookPreflightDependencyTests(unittest.TestCase):
    def test_handoff_preflights_include_transitive_local_imports(self) -> None:
        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                module = load_script(renderer)
                script_paths = {
                    path.stem
                    for path in module.required_existing(Path("/repo"))
                    if path.parent == Path("/repo/scripts")
                }

                missing = {
                    f"scripts/{script}.py:{line} imports scripts/{dependency}.py"
                    for script in script_paths
                    for dependency, line in local_script_imports(script).items()
                    if dependency not in script_paths
                }

                self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
