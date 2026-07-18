from __future__ import annotations

import argparse
import base64
import hashlib
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

import download_materializer_staged_validation as MODULE  # noqa: E402

KMS = "arn:aws:kms:us-east-1:172630973301:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
URI = (
    "s3://diana-omics-private-results-172630973301-us-east-1/runs/subject01/"
    "diana-wgs-hrd-test/deterministic/final/staged_input_validation.json"
)


def checksum(payload: bytes) -> str:
    return base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def receipt(payload: bytes) -> dict:
    return {
        "schema_version": 2,
        "status": "passed",
        "outputs": {
            "staged_input_validation.json": {
                "uri": URI,
                "version_id": "version-1",
                "bytes": len(payload),
                "sha256": sha(payload),
                "kms_key_arn": KMS,
                "checksums": {"ChecksumSHA256": checksum(payload)},
                "checks": {
                    "create_only_put": True,
                    "version_exact": True,
                    "bytes_exact": True,
                    "metadata_sha256_exact": True,
                    "exact_kms": True,
                    "single_version_history": True,
                },
            }
        },
        "checks": {
            "all_sources_exact_version_and_sha256": True,
            "all_outputs_create_only": True,
            "destination_exact_single_version_history": True,
        },
    }


class DownloadMaterializerStagedValidationTests(unittest.TestCase):
    def test_validate_receipt_requires_exact_staged_validation_custody(self) -> None:
        row = MODULE.validate_receipt(receipt(b'{"schema_version":1}\n'), KMS)

        self.assertEqual(row["version_id"], "version-1")
        self.assertEqual(row["key"].split("/")[-1], "staged_input_validation.json")

        missing = receipt(b"{}")
        missing["outputs"]["other.json"] = missing["outputs"][
            "staged_input_validation.json"
        ]
        missing["outputs"].pop("staged_input_validation.json")
        with self.assertRaisesRegex(ValueError, "does not contain"):
            MODULE.validate_receipt(missing, KMS)

        promoted = receipt(b"{}")
        promoted["checks"]["all_outputs_create_only"] = False
        with self.assertRaisesRegex(ValueError, "incomplete"):
            MODULE.validate_receipt(promoted, KMS)

        wrong_kms = receipt(b"{}")
        wrong_kms["outputs"]["staged_input_validation.json"]["kms_key_arn"] = "wrong"
        with self.assertRaisesRegex(ValueError, "lacks exact"):
            MODULE.validate_receipt(wrong_kms, KMS)

    def test_head_and_get_request_exact_version_with_checksum_mode(self) -> None:
        with patch.object(MODULE, "aws_json", return_value={"ok": True}) as aws:
            self.assertEqual(
                MODULE.head_object(
                    "private-bucket",
                    "path/to/staged_input_validation.json",
                    "version-1",
                    "us-east-1",
                ),
                {"ok": True},
            )

        aws.assert_called_once_with(
            [
                "s3api",
                "head-object",
                "--bucket",
                "private-bucket",
                "--key",
                "path/to/staged_input_validation.json",
                "--version-id",
                "version-1",
                "--checksum-mode",
                "ENABLED",
            ],
            "us-east-1",
        )

        with tempfile.TemporaryDirectory() as value:
            destination = Path(value) / "staged_input_validation.json"
            def aws_json(arguments: list[str], region: str) -> dict[str, object]:
                destination.write_text('{"schema_version":1}\n', encoding="utf-8")
                return {"ok": True}

            with patch.object(MODULE, "aws_json", side_effect=aws_json) as aws:
                self.assertEqual(
                    MODULE.get_object(
                        "private-bucket",
                        "path/to/staged_input_validation.json",
                        "version-1",
                        destination,
                        "us-east-1",
                    ),
                    {"ok": True},
                )

        aws.assert_called_once_with(
            [
                "s3api",
                "get-object",
                "--bucket",
                "private-bucket",
                "--key",
                "path/to/staged_input_validation.json",
                "--version-id",
                "version-1",
                "--checksum-mode",
                "ENABLED",
                str(destination),
            ],
            "us-east-1",
        )

    def test_get_object_rejects_symlinked_destination_after_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            destination = root / "staged_input_validation.json"

            def aws_json(_arguments: list[str], _region: str) -> dict[str, object]:
                real_download = root / "real-staged_input_validation.json"
                real_download.write_text('{"schema_version":1}\n', encoding="utf-8")
                destination.symlink_to(real_download)
                return {"ok": True}

            with (
                patch.object(MODULE, "aws_json", side_effect=aws_json),
                self.assertRaisesRegex(
                    ValueError,
                    "downloaded staged_input_validation.json may not be a symlink",
                ),
            ):
                MODULE.get_object(
                    "private-bucket",
                    "path/to/staged_input_validation.json",
                    "version-1",
                    destination,
                    "us-east-1",
                )

    def test_install_file_create_only_revalidates_source_and_destination(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_source = root / "real-staging.json"
            real_source.write_text('{"schema_version":1}\n', encoding="utf-8")
            linked_source = root / ".staging"
            linked_source.symlink_to(real_source)

            with self.assertRaisesRegex(
                ValueError,
                "staged materializer output may not be a symlink",
            ):
                MODULE.install_file_create_only(
                    linked_source,
                    root / "staged_input_validation.json",
                )

            real_parent = root / "real-parent"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "materializer output parent may not be a symlink",
            ):
                MODULE.install_file_create_only(
                    real_source,
                    linked_parent / "existing" / "staged_input_validation.json",
                )

            self.assertFalse(
                (real_parent / "existing" / "staged_input_validation.json").exists()
            )

    def test_materialize_downloads_exact_version_and_writes_mode_0600_receipt(self) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            output = root / "staged_input_validation.json"
            verification = root / "verification.json"
            receipt_path.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            def get_object(
                bucket: str,
                key: str,
                version_id: str,
                destination: Path,
                region: str,
            ) -> dict:
                self.assertEqual(version_id, "version-1")
                destination.write_bytes(payload)
                return {
                    "VersionId": "version-1",
                    "ContentLength": len(payload),
                    "ChecksumSHA256": checksum(payload),
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            with patch.object(
                MODULE,
                "head_object",
                return_value={
                    "VersionId": "version-1",
                    "ContentLength": len(payload),
                    "ChecksumSHA256": checksum(payload),
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                },
            ), patch.object(MODULE, "get_object", side_effect=get_object):
                result = MODULE.materialize(
                    argparse.Namespace(
                        materializer_receipt=receipt_path,
                        output=output,
                        verification_output=verification,
                        expected_kms_key_arn=KMS,
                        region="us-east-1",
                    )
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(output.read_bytes(), payload)
            self.assertEqual(stat.S_IMODE(verification.stat().st_mode), 0o600)
            with self.assertRaisesRegex(FileExistsError, "refusing to replace"):
                MODULE.materialize(
                    argparse.Namespace(
                        materializer_receipt=receipt_path,
                        output=output,
                        verification_output=verification,
                        expected_kms_key_arn=KMS,
                        region="us-east-1",
                    )
                )

    def test_download_mismatch_records_failed_receipt(self) -> None:
        good = json.dumps({"schema_version": 1}).encode()
        bad = json.dumps({"schema_version": 1, "changed": True}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            output = root / "staged_input_validation.json"
            verification = root / "verification.json"
            receipt_path.write_text(
                json.dumps(receipt(good), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            def get_object(
                _bucket: str,
                _key: str,
                _version_id: str,
                destination: Path,
                _region: str,
            ) -> dict:
                destination.write_bytes(bad)
                return {
                    "VersionId": "version-1",
                    "ContentLength": len(bad),
                    "ChecksumSHA256": checksum(bad),
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            with patch.object(
                MODULE,
                "head_object",
                return_value={
                    "VersionId": "version-1",
                    "ContentLength": len(good),
                    "ChecksumSHA256": checksum(good),
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                },
            ), patch.object(MODULE, "get_object", side_effect=get_object):
                with self.assertRaisesRegex(ValueError, "download validation"):
                    MODULE.materialize(
                        argparse.Namespace(
                            materializer_receipt=receipt_path,
                            output=output,
                            verification_output=verification,
                            expected_kms_key_arn=KMS,
                            region="us-east-1",
                        )
                    )

            self.assertFalse(output.exists())
            self.assertEqual(
                json.loads(verification.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_rejects_symlinked_download_before_installing_output(self) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            output = root / "staged_input_validation.json"
            verification = root / "verification.json"
            redirected = root / "redirected-staged-input-validation.json"
            receipt_path.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            def get_object(
                _bucket: str,
                _key: str,
                _version_id: str,
                destination: Path,
                _region: str,
            ) -> dict:
                redirected.write_bytes(payload)
                destination.symlink_to(redirected)
                return {
                    "VersionId": "version-1",
                    "ContentLength": len(payload),
                    "ChecksumSHA256": checksum(payload),
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            with (
                patch.object(
                    MODULE,
                    "head_object",
                    return_value={
                        "VersionId": "version-1",
                        "ContentLength": len(payload),
                        "ChecksumSHA256": checksum(payload),
                        "ChecksumType": "FULL_OBJECT",
                        "ServerSideEncryption": "aws:kms",
                        "SSEKMSKeyId": KMS,
                    },
                ),
                patch.object(MODULE, "get_object", side_effect=get_object),
                self.assertRaisesRegex(ValueError, "may not be a symlink"),
            ):
                MODULE.materialize(
                    argparse.Namespace(
                        materializer_receipt=receipt_path,
                        output=output,
                        verification_output=verification,
                        expected_kms_key_arn=KMS,
                        region="us-east-1",
                    )
                )

            self.assertFalse(output.exists())
            self.assertEqual(redirected.read_bytes(), payload)
            self.assertEqual(
                json.loads(verification.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_late_existing_output_records_failed_receipt_without_replacement(
        self,
    ) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            output = root / "staged_input_validation.json"
            verification = root / "verification.json"
            receipt_path.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            def get_object(
                _bucket: str,
                _key: str,
                _version_id: str,
                destination: Path,
                _region: str,
            ) -> dict:
                destination.write_bytes(payload)
                return {
                    "VersionId": "version-1",
                    "ContentLength": len(payload),
                    "ChecksumSHA256": checksum(payload),
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            real_validate_download = MODULE.validate_download

            def validate_download(
                row: dict,
                head: dict,
                get: dict,
                local_path: Path,
                expected_kms: str,
            ) -> dict:
                checks = real_validate_download(row, head, get, local_path, expected_kms)
                output.write_bytes(b"keep me\n")
                return checks

            with patch.object(
                MODULE,
                "head_object",
                return_value={
                    "VersionId": "version-1",
                    "ContentLength": len(payload),
                    "ChecksumSHA256": checksum(payload),
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                },
            ), patch.object(
                MODULE, "get_object", side_effect=get_object
            ), patch.object(
                MODULE, "validate_download", side_effect=validate_download
            ):
                with self.assertRaisesRegex(
                    FileExistsError, "refusing to replace local materializer output"
                ):
                    MODULE.materialize(
                        argparse.Namespace(
                            materializer_receipt=receipt_path,
                            output=output,
                            verification_output=verification,
                            expected_kms_key_arn=KMS,
                            region="us-east-1",
                        )
                    )

            self.assertEqual(output.read_bytes(), b"keep me\n")
            self.assertFalse((root / ".staged_input_validation.json.staging").exists())
            failed = json.loads(verification.read_text(encoding="utf-8"))
            self.assertEqual(failed["status"], "failed")
            self.assertIn(
                "FileExistsError: refusing to replace local materializer output",
                failed["error"],
            )

    def test_refuses_symlinked_receipt_before_writes(self) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_receipt = root / "real-materializer.json"
            real_receipt.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            linked_receipt = root / "linked-materializer.json"
            linked_receipt.symlink_to(real_receipt)
            real_receipt_parent = root / "real-receipts"
            real_receipt_parent.mkdir()
            parent_target_receipt = real_receipt_parent / "materializer.json"
            parent_target_receipt.write_text(
                real_receipt.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            linked_receipt_parent = root / "linked-receipts"
            linked_receipt_parent.symlink_to(
                real_receipt_parent,
                target_is_directory=True,
            )

            for receipt_path in (
                linked_receipt,
                linked_receipt_parent / "materializer.json",
            ):
                with self.subTest(receipt=receipt_path):
                    output = (
                        root / f"{receipt_path.name}.staged_input_validation.json"
                    )
                    verification = root / f"{receipt_path.name}.verification.json"

                    with self.assertRaisesRegex(
                        ValueError,
                        "materializer receipt.* may not be a symlink",
                    ):
                        MODULE.materialize(
                            argparse.Namespace(
                                materializer_receipt=receipt_path,
                                output=output,
                                verification_output=verification,
                                expected_kms_key_arn=KMS,
                                region="us-east-1",
                            )
                        )

                    self.assertFalse(output.exists())
                    self.assertFalse(verification.exists())

    def test_refuses_receipt_below_symlinked_parent_before_writes(self) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            real_receipt_parent = root / "real-receipts"
            real_receipt_dir = real_receipt_parent / "existing"
            real_receipt_dir.mkdir(parents=True)
            linked_receipt_parent = root / "linked-receipts"
            linked_receipt_parent.symlink_to(
                real_receipt_parent,
                target_is_directory=True,
            )

            receipt_path = linked_receipt_parent / "existing" / "materializer.json"
            (real_receipt_dir / "materializer.json").write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            output = root / "staged_input_validation.json"
            verification = root / "verification.json"

            with patch.object(
                MODULE, "head_object", side_effect=AssertionError("AWS called")
            ), patch.object(
                MODULE, "get_object", side_effect=AssertionError("AWS called")
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "materializer receipt.* parent may not be a symlink",
                ):
                    MODULE.materialize(
                        argparse.Namespace(
                            materializer_receipt=receipt_path,
                            output=output,
                            verification_output=verification,
                            expected_kms_key_arn=KMS,
                            region="us-east-1",
                        )
                    )

            self.assertFalse(output.exists())
            self.assertFalse(verification.exists())

    def test_refuses_symlinked_output_before_verification_reservation(self) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            receipt_path.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            real_parent = root / "real-parent"
            real_parent.mkdir()
            direct_target = real_parent / "direct-target"
            direct_target.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            linked_output = root / "linked-staged-input-validation.json"
            linked_output.symlink_to(direct_target)

            for output in (
                linked_output,
                linked_parent / "staged_input_validation.json",
            ):
                with self.subTest(output=output):
                    verification = root / f"{output.name}.verification.json"

                    with self.assertRaisesRegex(
                        ValueError,
                        "materializer output.* may not be a symlink",
                    ):
                        MODULE.materialize(
                            argparse.Namespace(
                                materializer_receipt=receipt_path,
                                output=output,
                                verification_output=verification,
                                expected_kms_key_arn=KMS,
                                region="us-east-1",
                            )
                        )

                    self.assertFalse(verification.exists())
                    self.assertFalse(
                        (real_parent / "staged_input_validation.json").exists()
                    )

    def test_refuses_output_below_symlinked_parent_before_verification_reservation(
        self,
    ) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            receipt_path.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            output = linked_parent / "missing" / "staged_input_validation.json"
            verification = root / "verification.json"

            with self.assertRaisesRegex(
                ValueError,
                "materializer output.* parent may not be a symlink",
            ):
                MODULE.materialize(
                    argparse.Namespace(
                        materializer_receipt=receipt_path,
                        output=output,
                        verification_output=verification,
                        expected_kms_key_arn=KMS,
                        region="us-east-1",
                    )
                )

            self.assertFalse(verification.exists())
            self.assertFalse((real_parent / "missing").exists())

    def test_refuses_symlinked_verification_before_writes(self) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            receipt_path.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            real_verification = root / "real-verification.json"
            real_verification.write_text('{"status":"passed"}\n', encoding="utf-8")
            linked_verification = root / "linked-verification.json"
            linked_verification.symlink_to(real_verification)
            real_verification_parent = root / "real-verifications"
            real_verification_parent.mkdir()
            linked_verification_parent = root / "linked-verifications"
            linked_verification_parent.symlink_to(
                real_verification_parent,
                target_is_directory=True,
            )

            for verification in (
                linked_verification,
                linked_verification_parent / "verification.json",
            ):
                with self.subTest(verification=verification):
                    output = root / f"{verification.name}.staged_input_validation.json"

                    with self.assertRaisesRegex(
                        ValueError,
                        "verification output.* may not be a symlink",
                    ):
                        MODULE.materialize(
                            argparse.Namespace(
                                materializer_receipt=receipt_path,
                                output=output,
                                verification_output=verification,
                                expected_kms_key_arn=KMS,
                                region="us-east-1",
                            )
                        )

                    self.assertEqual(
                        real_verification.read_text(encoding="utf-8"),
                        '{"status":"passed"}\n',
                    )

    def test_refuses_verification_below_symlinked_parent_before_writes(self) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            receipt_path.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            real_verification_parent = root / "real-verifications"
            real_verification_parent.mkdir()
            linked_verification_parent = root / "linked-verifications"
            linked_verification_parent.symlink_to(
                real_verification_parent,
                target_is_directory=True,
            )

            output = root / "staged_input_validation.json"
            verification = linked_verification_parent / "missing" / "verification.json"

            with self.assertRaisesRegex(
                ValueError,
                "verification output.* parent may not be a symlink",
            ):
                MODULE.materialize(
                    argparse.Namespace(
                        materializer_receipt=receipt_path,
                        output=output,
                        verification_output=verification,
                        expected_kms_key_arn=KMS,
                        region="us-east-1",
                    )
                )

            self.assertFalse(output.exists())
            self.assertFalse((real_verification_parent / "missing").exists())

    def test_refuses_output_below_existing_dir_under_symlinked_parent(self) -> None:
        payload = json.dumps({"schema_version": 1, "status": "passed"}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            receipt_path.write_text(
                json.dumps(receipt(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            real_parent = root / "real-parent"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            output = linked_parent / "existing" / "staged_input_validation.json"
            verification = root / "verification.json"

            with self.assertRaisesRegex(
                ValueError,
                "materializer output.* parent may not be a symlink",
            ):
                MODULE.materialize(
                    argparse.Namespace(
                        materializer_receipt=receipt_path,
                        output=output,
                        verification_output=verification,
                        expected_kms_key_arn=KMS,
                        region="us-east-1",
                    )
                )

            self.assertFalse(verification.exists())
            self.assertFalse(
                (real_parent / "existing" / "staged_input_validation.json").exists()
            )

if __name__ == "__main__":
    unittest.main()
