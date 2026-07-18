from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"

SPEC = importlib.util.spec_from_file_location(
    "ai_model_catalog", SCRIPT_DIR / "ai_model_catalog.py"
)
assert SPEC and SPEC.loader
CATALOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CATALOG)


class WriteAiModelCatalogReceiptTests(unittest.TestCase):
    def run_writer(self, output: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "write_ai_model_catalog_receipt.py"),
                "--output",
                str(output),
                "--attest-models-latest",
            ],
            text=True,
            capture_output=True,
        )

    def test_writes_pinned_receipt_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "model-catalog-receipt.json"

            result = self.run_writer(output)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                CATALOG.model_catalog_receipt(),
            )
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

            second = self.run_writer(output)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("output already exists", second.stderr)

    def test_rejects_direct_output_symlink_without_overwriting_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / "real-receipt.json"
            target.write_text("keep original\n", encoding="utf-8")
            output = root / "model-catalog-receipt.json"
            output.symlink_to(target)

            result = self.run_writer(output)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output already exists", result.stderr)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep original\n")

    def test_rejects_symlinked_output_parent_without_writing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-output"
            real_parent.mkdir()
            symlink_parent = root / "linked-output"
            symlink_parent.symlink_to(real_parent, target_is_directory=True)
            output = symlink_parent / "model-catalog-receipt.json"

            result = self.run_writer(output)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output parent is a symlink", result.stderr)
            self.assertFalse((real_parent / "model-catalog-receipt.json").exists())

    def test_requires_latest_model_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "model-catalog-receipt.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "write_ai_model_catalog_receipt.py"),
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--attest-models-latest", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
