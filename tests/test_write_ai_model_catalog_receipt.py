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
    def test_writes_pinned_receipt_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "model-catalog-receipt.json"

            result = subprocess.run(
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

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                CATALOG.model_catalog_receipt(),
            )
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

            second = subprocess.run(
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
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("output already exists", second.stderr)

    def test_requires_latest_model_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "model-catalog-receipt.json"

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
