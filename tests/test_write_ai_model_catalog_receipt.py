from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SPEC = importlib.util.spec_from_file_location(
    "ai_model_catalog", SCRIPT_DIR / "ai_model_catalog.py"
)
assert SPEC and SPEC.loader
CATALOG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CATALOG)

WRITER_SPEC = importlib.util.spec_from_file_location(
    "write_ai_model_catalog_receipt",
    SCRIPT_DIR / "write_ai_model_catalog_receipt.py",
)
assert WRITER_SPEC and WRITER_SPEC.loader
WRITER = importlib.util.module_from_spec(WRITER_SPEC)
WRITER_SPEC.loader.exec_module(WRITER)


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

    def test_write_once_rechecks_output_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-output"
            real_parent.mkdir()
            symlink_parent = root / "linked-output"
            symlink_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(SystemExit, "output parent is a symlink"):
                WRITER.write_once(
                    symlink_parent / "model-catalog-receipt.json",
                    "{}\n",
                )

            self.assertFalse((real_parent / "model-catalog-receipt.json").exists())

    def test_write_once_fsyncs_file_and_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "model-catalog-receipt.json"

            with (
                mock.patch.object(
                    WRITER.os,
                    "fsync",
                    wraps=WRITER.os.fsync,
                ) as fsync,
            ):
                WRITER.write_once(output, "{}\n")

            self.assertEqual(output.read_text(encoding="utf-8"), "{}\n")
            self.assertEqual(fsync.call_count, 2)

    def test_write_once_removes_partial_output_after_file_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "model-catalog-receipt.json"

            with (
                mock.patch.object(
                    WRITER.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                WRITER.write_once(output, "{}\n")

            self.assertFalse(output.exists())

    def test_write_once_removes_partial_output_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "model-catalog-receipt.json"

            with (
                mock.patch.object(
                    WRITER.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                WRITER.write_once(output, "{}\n")

            self.assertFalse(output.exists())

    def test_write_once_rehashes_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "model-catalog-receipt.json"
            real_fsync_directory = WRITER.fsync_directory

            def tamper_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    WRITER,
                    "fsync_directory",
                    side_effect=tamper_after_directory_fsync,
                ),
                self.assertRaisesRegex(ValueError, "output changed during write"),
            ):
                WRITER.write_once(output, "{}\n")

            self.assertFalse(output.exists())

    def test_write_once_rechecks_output_mode_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "model-catalog-receipt.json"
            real_fsync_directory = WRITER.fsync_directory

            def chmod_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.chmod(0o644)

            with (
                mock.patch.object(
                    WRITER,
                    "fsync_directory",
                    side_effect=chmod_after_directory_fsync,
                ),
                self.assertRaisesRegex(ValueError, "output mode changed during write"),
            ):
                WRITER.write_once(output, "{}\n")

            self.assertFalse(output.exists())

    def test_write_once_rejects_output_swapped_to_symlink_before_digest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "model-catalog-receipt.json"
            relocated = root / "relocated-receipt.json"
            real_is_file = Path.is_file
            swapped = False

            def swap_after_first_output_file_check(path: Path) -> bool:
                nonlocal swapped
                result = real_is_file(path)
                if path == output and result and not swapped:
                    output.unlink()
                    relocated.write_text("{}\n", encoding="utf-8")
                    relocated.chmod(0o600)
                    output.symlink_to(relocated)
                    swapped = True
                return result

            with (
                mock.patch.object(
                    Path,
                    "is_file",
                    autospec=True,
                    side_effect=swap_after_first_output_file_check,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "model-catalog-receipt.json SHA-256 input is missing or a symlink",
                ),
            ):
                WRITER.write_once(output, "{}\n")

            self.assertTrue(swapped)
            self.assertFalse(output.exists())
            self.assertFalse(output.is_symlink())
            self.assertEqual(relocated.read_text(encoding="utf-8"), "{}\n")

    def test_sha256_file_rejects_symlinked_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_source = root / "real-model-catalog-receipt.json"
            real_source.write_text("{}\n", encoding="utf-8")
            source_link = root / "model-catalog-receipt.json"
            source_link.symlink_to(real_source)

            with self.assertRaisesRegex(
                ValueError,
                "model-catalog-receipt.json SHA-256 input is missing or a symlink",
            ):
                WRITER.sha256_file(source_link)

    def test_sha256_file_rejects_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-receipts"
            real_parent.mkdir()
            (real_parent / "model-catalog-receipt.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "model-catalog-receipt.json SHA-256 input parent may not be a symlink",
            ):
                WRITER.sha256_file(linked_parent / "model-catalog-receipt.json")

    def test_sha256_file_rejects_mid_read_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "model-catalog-receipt.json"
            source.write_text('{"stable": true}\n', encoding="utf-8")

            original_read_bytes = Path.read_bytes
            mutated = False

            def mutate_after_first_read(path: Path) -> bytes:
                nonlocal mutated
                data = original_read_bytes(path)
                if path == source and not mutated:
                    mutated = True
                    path.write_text('{"stable": false}\n', encoding="utf-8")
                return data

            with (
                mock.patch.object(Path, "read_bytes", mutate_after_first_read),
                self.assertRaisesRegex(
                    ValueError,
                    "model-catalog-receipt.json SHA-256 input changed during read",
                ),
            ):
                WRITER.sha256_file(source)

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

    def test_model_catalog_receipt_envelope_is_exact(self) -> None:
        receipt = CATALOG.model_catalog_receipt()

        self.assertEqual(set(receipt), CATALOG.MODEL_CATALOG_RECEIPT_KEYS)
        for row in receipt["models"]:
            self.assertEqual(set(row), CATALOG.MODEL_CATALOG_MODEL_KEYS)

    def test_model_catalog_requires_distinct_reviewer_models(self) -> None:
        with mock.patch.object(CATALOG, "REVIEWER_B", CATALOG.REVIEWER_A):
            with self.assertRaisesRegex(ValueError, "distinct reviewer model"):
                CATALOG.model_catalog_receipt()


if __name__ == "__main__":
    unittest.main()
