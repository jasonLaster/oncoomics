from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import materialize_frozen_artifacts as MODULE  # noqa: E402
import submit_materializer_v4 as SUBMITTER  # noqa: E402


class MaterializeFrozenArtifactsTests(unittest.TestCase):
    def freeze_fixture(self, root: Path, kms: str) -> Path:
        receipt = root / "freeze.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "run_id": "synthetic-run",
                    "batch_job_id": "synthetic-job",
                    "kms_key_arn": kms,
                    "destination_prefix": (
                        "s3://diana-omics-private-results-test/"
                        "runs/subject01/synthetic-run/deterministic/artifacts/"
                    ),
                    "object_count": 1,
                    "objects": [
                        {
                            "relative_key": "variants/final.vcf.gz",
                            "status": "passed",
                            "destination": {
                                "bucket": "diana-omics-private-results-test",
                                "key": (
                                    "runs/subject01/synthetic-run/deterministic/"
                                    "artifacts/variants/final.vcf.gz"
                                ),
                                "version_id": "exact-version",
                                "bytes": 5,
                                "checksums": {"ChecksumCRC64NVME": "checksum"},
                                "checksum_type": "FULL_OBJECT",
                            },
                        }
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return receipt

    def args(self, freeze: Path, output: Path, receipt: Path, kms: str) -> list[str]:
        return [
            "--freeze-receipt",
            str(freeze),
            "--output-dir",
            str(output),
            "--receipt-output",
            str(receipt),
            "--expected-kms-key-arn",
            kms,
        ]

    def test_safe_relative_rejects_traversal(self) -> None:
        self.assertEqual(
            MODULE.safe_relative("variants/final.vcf.gz"),
            "variants/final.vcf.gz",
        )
        for value in ("", "/absolute", "../escape", "variants/../../escape"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MODULE.safe_relative(value)

    def test_exact_version_bytes_checksum_and_kms_bind_local_sha(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact"
            path.write_bytes(b"exact frozen bytes")
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            expected = {
                "version_id": "frozen-version",
                "bytes": path.stat().st_size,
                "checksums": {"ChecksumCRC64NVME": "checksum"},
                "checksum_type": "FULL_OBJECT",
            }
            response = {
                "VersionId": "frozen-version",
                "ContentLength": path.stat().st_size,
                "ChecksumCRC64NVME": "checksum",
                "ChecksumType": "FULL_OBJECT",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": kms,
            }
            row = MODULE.validate_materialized(expected, response, path, kms)
            self.assertEqual(row["sha256"], MODULE.sha256(path))
            self.assertEqual(row["checks"], MODULE.EXPECTED_MATERIALIZATION_CHECKS)

            for field, value in (
                ("VersionId", "other-version"),
                ("ChecksumCRC64NVME", "other-checksum"),
                ("SSEKMSKeyId", kms + "-other"),
            ):
                altered = dict(response)
                altered[field] = value
                with self.subTest(field=field), self.assertRaisesRegex(
                    ValueError, "materialization checks failed"
                ):
                    MODULE.validate_materialized(expected, altered, path, kms)

            with patch.object(
                MODULE,
                "EXPECTED_MATERIALIZATION_CHECKS",
                {**MODULE.EXPECTED_MATERIALIZATION_CHECKS, "future_check": True},
            ), self.assertRaisesRegex(
                ValueError,
                "materialization checks failed",
            ):
                MODULE.validate_materialized(expected, response, path, kms)

    def test_materialization_check_inventory_matches_v4_submitter(self) -> None:
        self.assertEqual(
            set(MODULE.EXPECTED_MATERIALIZATION_CHECKS),
            SUBMITTER.EXPECTED_MATERIALIZATION_ROW_CHECKS,
        )

    def test_positive_bytes_and_checksum_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "empty"
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "positive byte count"):
                MODULE.validate_materialized(
                    {
                        "version_id": "v",
                        "bytes": 0,
                        "checksums": {"ChecksumCRC64NVME": "c"},
                        "checksum_type": "FULL_OBJECT",
                    },
                    {},
                    path,
                    "kms",
                )

    def test_stages_then_atomically_publishes_exact_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"

            def fake_get(
                bucket: str, key: str, version_id: str, destination: Path, region: str
            ) -> dict[str, object]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"exact")
                return {
                    "VersionId": version_id,
                    "ContentLength": 5,
                    "ChecksumCRC64NVME": "checksum",
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": kms,
                }

            with patch.object(MODULE, "get_exact_object", side_effect=fake_get):
                self.assertEqual(
                    MODULE.main(self.args(freeze, output, receipt, kms)),
                    0,
                )

            self.assertEqual((output / "variants/final.vcf.gz").read_bytes(), b"exact")
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["passed_count"], 1)
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            self.assertFalse((root / ".materialized.staging").exists())

    def test_rejects_unexpected_staging_child_before_local_cutover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"

            def fake_get(
                bucket: str, key: str, version_id: str, destination: Path, region: str
            ) -> dict[str, object]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"exact")
                (destination.parents[1] / "unexpected.tmp").write_text(
                    "extra\n",
                    encoding="utf-8",
                )
                return {
                    "VersionId": version_id,
                    "ContentLength": 5,
                    "ChecksumCRC64NVME": "checksum",
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": kms,
                }

            with (
                patch.object(MODULE, "get_exact_object", side_effect=fake_get),
                self.assertRaisesRegex(
                    SystemExit,
                    "materialized tree inventory differs from its receipt",
                ),
            ):
                MODULE.main(self.args(freeze, output, receipt, kms))

            self.assertFalse(output.exists())
            self.assertFalse((root / ".materialized.staging").exists())
            self.assertEqual(
                json.loads(receipt.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_revalidates_output_tree_after_final_cutover_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"
            real_fsync_directory = MODULE.fsync_directory

            def fake_get(
                bucket: str, key: str, version_id: str, destination: Path, region: str
            ) -> dict[str, object]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"exact")
                return {
                    "VersionId": version_id,
                    "ContentLength": 5,
                    "ChecksumCRC64NVME": "checksum",
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": kms,
                }

            def tamper_after_cutover_fsync(path: Path) -> None:
                real_fsync_directory(path)
                local = output / "variants/final.vcf.gz"
                if local.exists():
                    local.write_bytes(b"tampered")

            with (
                patch.object(MODULE, "get_exact_object", side_effect=fake_get),
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_cutover_fsync,
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    "materialized tree differs from its receipt",
                ),
            ):
                MODULE.main(self.args(freeze, output, receipt, kms))

            self.assertFalse(output.exists())
            self.assertEqual(
                json.loads(receipt.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_rejects_symlinked_exact_version_object_before_materializing_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"
            redirected = root / "redirected-final.vcf.gz"

            def fake_get(command: list[str], text: bool) -> str:
                self.assertTrue(text)
                destination = Path(command[-1])
                destination.parent.mkdir(parents=True, exist_ok=True)
                redirected.write_bytes(b"exact")
                destination.symlink_to(redirected)
                return json.dumps(
                    {
                        "VersionId": "exact-version",
                        "ContentLength": 5,
                        "ChecksumCRC64NVME": "checksum",
                        "ChecksumType": "FULL_OBJECT",
                        "ServerSideEncryption": "aws:kms",
                        "SSEKMSKeyId": kms,
                    }
                )

            with (
                patch.object(MODULE.subprocess, "check_output", side_effect=fake_get),
                self.assertRaisesRegex(SystemExit, "materialized object must be a real file"),
            ):
                MODULE.main(self.args(freeze, output, receipt, kms))

            self.assertFalse(output.exists())
            self.assertFalse((root / ".materialized.staging").exists())
            self.assertEqual(redirected.read_bytes(), b"exact")
            self.assertEqual(
                json.loads(receipt.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_failure_removes_staging_but_preserves_reserved_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"

            with patch.object(
                MODULE,
                "get_exact_object",
                side_effect=RuntimeError("synthetic failure"),
            ), self.assertRaisesRegex(SystemExit, "synthetic failure"):
                MODULE.main(self.args(freeze, output, receipt, kms))

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            self.assertFalse(output.exists())
            self.assertFalse((root / ".materialized.staging").exists())

    def test_reserve_json_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "materialization.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "materialization receipt changed during write",
                ),
            ):
                MODULE.reserve_json(receipt, {"status": "in_progress"})

            self.assertFalse(receipt.exists())

    def test_write_json_atomic_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "materialization.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "materialization receipt changed during write",
                ),
            ):
                MODULE.write_json_atomic(receipt, {"status": "passed"})

    def test_prepared_receipt_recovers_cutover_without_redownload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            staging = root / ".materialized.staging"
            staged_file = staging / "variants/final.vcf.gz"
            staged_file.parent.mkdir(parents=True)
            staged_file.write_bytes(b"exact")
            receipt = root / "materialization.json"
            prepared = {
                "schema_version": 1,
                "status": "prepared",
                "run_id": "synthetic-run",
                "batch_job_id": "synthetic-job",
                "script_sha256": MODULE.sha256(SCRIPT_DIR / "materialize_frozen_artifacts.py"),
                "freeze_receipt_sha256": MODULE.sha256(freeze),
                "expected_kms_key_arn": kms,
                "materialization_dir": str(output.resolve()),
                "object_count": 1,
                "objects": [
                    {
                        "relative_key": "variants/final.vcf.gz",
                        "bytes": 5,
                        "sha256": MODULE.sha256(staged_file),
                    }
                ],
            }
            MODULE.reserve_json(receipt, prepared)

            with patch.object(MODULE, "get_exact_object") as get_exact:
                self.assertEqual(
                    MODULE.main(self.args(freeze, output, receipt, kms)),
                    0,
                )

            get_exact.assert_not_called()
            self.assertEqual((output / "variants/final.vcf.gz").read_bytes(), b"exact")
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "passed")
            self.assertTrue(payload["recovered_prepared_cutover"])

    def test_existing_unrelated_receipt_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            receipt = root / "materialization.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "belongs to another operation"):
                MODULE.main(self.args(freeze, root / "materialized", receipt, kms))

            self.assertEqual(receipt.read_text(encoding="utf-8"), '{"status":"passed"}\n')

    def test_refuses_symlinked_output_before_receipt_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            direct_target = real_parent / "direct-target"
            direct_target.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            linked_output = root / "linked-output"
            linked_output.symlink_to(direct_target, target_is_directory=True)
            linked_nested_output = linked_parent / "missing" / "materialized"

            for output in (
                linked_output,
                linked_parent / "materialized",
                linked_nested_output,
            ):
                with self.subTest(output=output):
                    receipt = root / f"{output.name}.materialization.json"
                    with self.assertRaisesRegex(
                        SystemExit,
                        "materialization output.* may not be a symlink",
                    ):
                        MODULE.main(self.args(freeze, output, receipt, kms))

                    self.assertFalse(receipt.exists())
                    self.assertFalse((real_parent / "materialized").exists())

    def test_refuses_existing_output_dir_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            (real_parent / "existing").mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            receipt = root / "materialization.json"

            with self.assertRaisesRegex(
                SystemExit,
                "materialization output.* parent may not be a symlink",
            ):
                MODULE.main(
                    self.args(
                        freeze,
                        linked_parent / "existing" / "materialized",
                        receipt,
                        kms,
                    )
                )

            self.assertFalse(receipt.exists())
            self.assertFalse((real_parent / "existing" / "materialized").exists())

    def test_refuses_materialized_object_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            (real_parent / "existing").mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with (
                patch.object(
                    MODULE.subprocess,
                    "check_output",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "materialized object parent may not be a symlink",
                ),
            ):
                MODULE.get_exact_object(
                    "diana-omics-private-results-test",
                    "runs/subject01/synthetic-run/deterministic/artifacts/final.vcf.gz",
                    "version",
                    linked_parent / "existing" / "final.vcf.gz",
                    "us-east-1",
                )

            self.assertFalse((real_parent / "existing" / "final.vcf.gz").exists())

    def test_refuses_symlinked_receipt_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            real_receipt = root / "real-receipt.json"
            real_receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            linked_receipt = root / "linked-receipt.json"
            linked_receipt.symlink_to(real_receipt)
            real_receipt_parent = root / "real-receipts"
            real_receipt_parent.mkdir()
            linked_receipt_parent = root / "linked-receipts"
            linked_receipt_parent.symlink_to(
                real_receipt_parent,
                target_is_directory=True,
            )

            for receipt in (
                linked_receipt,
                linked_receipt_parent / "materialization.json",
            ):
                with self.subTest(receipt=receipt):
                    output = root / f"{receipt.name}.materialized"
                    with self.assertRaisesRegex(
                        SystemExit,
                        "materialization receipt.* may not be a symlink",
                    ):
                        MODULE.main(self.args(freeze, output, receipt, kms))

                    self.assertEqual(
                        real_receipt.read_text(encoding="utf-8"),
                        '{"status":"passed"}\n',
                    )
                    self.assertFalse(output.exists())
                    self.assertFalse((real_receipt_parent / "materialization.json").exists())

    def test_refuses_symlinked_freeze_receipt_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            linked_freeze = root / "linked-freeze.json"
            linked_freeze.symlink_to(freeze)
            output = root / "materialized"
            receipt = root / "materialization.json"

            with (
                patch.object(
                    MODULE,
                    "get_exact_object",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(SystemExit, "freeze receipt must be a real JSON file"),
            ):
                MODULE.main(self.args(linked_freeze, output, receipt, kms))

            self.assertFalse(receipt.exists())
            self.assertFalse(output.exists())

    def test_refuses_freeze_receipt_below_symlinked_parent_before_writes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            real_parent = root / "real-freezes"
            real_parent.mkdir()
            freeze = self.freeze_fixture(real_parent, kms)
            linked_parent = root / "linked-freezes"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = root / "materialized"
            receipt = root / "materialization.json"

            with (
                patch.object(
                    MODULE,
                    "get_exact_object",
                    side_effect=AssertionError("AWS called"),
                ),
                self.assertRaisesRegex(SystemExit, "parent may not be a symlink"),
            ):
                MODULE.main(
                    self.args(linked_parent / freeze.name, output, receipt, kms)
                )

            self.assertFalse(receipt.exists())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
