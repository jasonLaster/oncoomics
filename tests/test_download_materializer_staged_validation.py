from __future__ import annotations

import argparse
import ast
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
        "generated_at_utc": "2026-07-18T00:00:00+00:00",
        "run_alias": "diana-wgs-hrd-test",
        "script_sha256": "a" * 64,
        "destination_prefix": (
            "s3://diana-omics-private-results-172630973301-us-east-1/"
            "runs/subject01/diana-wgs-hrd-test/deterministic/final/"
        ),
        "destination_bucket_versioning": "Enabled",
        "destination_initial_version_history_count": 0,
        "receipt_anchor_strategy": "sha256_content_addressed_create_only",
        "source_custody": {},
        "validation": {},
        "input_sha256": {},
        "outputs": {
            "staged_input_validation.json": {
                "uri": URI,
                "version_id": "version-1",
                "bytes": len(payload),
                "etag": '"synthetic-etag"',
                "sha256": sha(payload),
                "kms_key_arn": KMS,
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": checksum(payload),
                },
                "checks": dict(MODULE.EXPECTED_OUTPUT_CHECKS),
            }
        },
        "destination_inventory": [],
        "checks": dict(MODULE.EXPECTED_RECEIPT_CHECKS),
        "classification_authorization": {},
        "authorized_hrd_state": "no_call",
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

        wrong_checksum = receipt(b"{}")
        wrong_checksum["outputs"]["staged_input_validation.json"]["checksums"][
            "ChecksumSHA256"
        ] = checksum(b'{"changed":true}')
        with self.assertRaisesRegex(ValueError, "lacks exact"):
            MODULE.validate_receipt(wrong_checksum, KMS)

        composite_checksum = receipt(b"{}")
        composite_checksum["outputs"]["staged_input_validation.json"]["checksums"][
            "ChecksumType"
        ] = "COMPOSITE"
        with self.assertRaisesRegex(ValueError, "lacks exact"):
            MODULE.validate_receipt(composite_checksum, KMS)

        non_string_checksum = receipt(b"{}")
        non_string_checksum["outputs"]["staged_input_validation.json"]["checksums"][
            "ChecksumCRC32"
        ] = True
        with self.assertRaisesRegex(ValueError, "lacks exact"):
            MODULE.validate_receipt(non_string_checksum, KMS)

    def test_validate_receipt_rejects_non_integer_schema_version(self) -> None:
        payload = receipt(b'{"schema_version":1}\n')
        payload["schema_version"] = 2.0

        with self.assertRaisesRegex(ValueError, "incomplete or not passed"):
            MODULE.validate_receipt(payload, KMS)

    def test_validate_receipt_rejects_boolean_staged_validation_bytes(self) -> None:
        payload = receipt(b"1")
        payload["outputs"][MODULE.OUTPUT_NAME]["bytes"] = True

        with self.assertRaisesRegex(ValueError, "lacks exact materializer custody"):
            MODULE.validate_receipt(payload, KMS)

    def test_validate_receipt_requires_string_version_and_sha(self) -> None:
        numeric_sha256 = "1" * 64
        cases = (
            ("numeric_version", "version_id", 1234567890),
            ("numeric_sha256", "sha256", int(numeric_sha256)),
        )

        for name, field, value in cases:
            with self.subTest(name=name):
                payload = receipt(b"1")
                output = payload["outputs"][MODULE.OUTPUT_NAME]
                output[field] = value
                output["checksums"]["ChecksumSHA256"] = MODULE.checksum_sha256(
                    numeric_sha256
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "lacks exact materializer custody",
                ):
                    MODULE.validate_receipt(payload, KMS)

    def test_validate_receipt_rejects_missing_unexpected_or_failed_check_maps(
        self,
    ) -> None:
        for location, label, mutate, error in (
            (
                "receipt",
                "missing",
                lambda payload: payload["checks"].pop("alias_only_pass_snv_vcf"),
                "incomplete",
            ),
            (
                "receipt",
                "unexpected",
                lambda payload: payload["checks"].__setitem__(
                    "forged_extra",
                    True,
                ),
                "incomplete",
            ),
            (
                "receipt",
                "failed",
                lambda payload: payload["checks"].__setitem__(
                    "sbs96_matches_independent_pass_vcf_derivation",
                    False,
                ),
                "incomplete",
            ),
            (
                "output",
                "missing",
                lambda payload: payload["outputs"][MODULE.OUTPUT_NAME]["checks"].pop(
                    "sha256_checksum_exact"
                ),
                "lacks exact",
            ),
            (
                "output",
                "unexpected",
                lambda payload: payload["outputs"][MODULE.OUTPUT_NAME][
                    "checks"
                ].__setitem__("forged_extra", True),
                "lacks exact",
            ),
            (
                "output",
                "failed",
                lambda payload: payload["outputs"][MODULE.OUTPUT_NAME][
                    "checks"
                ].__setitem__("single_version_history", False),
                "lacks exact",
            ),
        ):
            with self.subTest(location=location, label=label):
                payload = receipt(b"{}")
                mutate(payload)

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_receipt(payload, KMS)

    def test_validate_receipt_rejects_inexact_receipt_and_output_envelopes(self) -> None:
        cases = (
            (
                "receipt",
                lambda payload: payload.__setitem__("legacy_note", "accepted"),
                "receipt envelope is not exact",
            ),
            (
                "output",
                lambda payload: payload["outputs"][MODULE.OUTPUT_NAME].__setitem__(
                    "legacy_note",
                    "accepted",
                ),
                "lacks exact",
            ),
        )
        for location, mutate, error in cases:
            with self.subTest(location=location):
                payload = receipt(b'{"schema_version":1}\n')
                mutate(payload)

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_receipt(payload, KMS)

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

    def test_install_file_create_only_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            source = root / ".staging"
            destination = root / "staged_input_validation.json"
            source.write_text('{"schema_version":1}\n', encoding="utf-8")
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                real_fsync_directory(parent)
                destination.write_text("tampered\n", encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "materializer output changed during write",
                ),
            ):
                MODULE.install_file_create_only(source, destination)

            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())

    def test_reserve_json_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            output = Path(value) / "verification.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                real_fsync_directory(parent)
                output.write_text("tampered\n", encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(ValueError, "JSON output changed during write"),
            ):
                MODULE.reserve_json(output, {"status": "in_progress"})

            self.assertFalse(output.exists())

    def test_write_json_atomic_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            output = Path(value) / "verification.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                real_fsync_directory(parent)
                output.write_text("tampered\n", encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(ValueError, "JSON output changed during write"),
            ):
                MODULE.write_json_atomic(output, {"status": "passed"})

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

    def test_materialize_rejects_non_integer_downloaded_schema_version(self) -> None:
        payload = json.dumps({"schema_version": 1.0, "status": "passed"}).encode()

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
                with self.assertRaisesRegex(
                    ValueError,
                    f"{MODULE.OUTPUT_NAME} is not a schema-1 JSON object",
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
            failed = json.loads(verification.read_text(encoding="utf-8"))
            self.assertEqual(failed["status"], "failed")
            self.assertIn(
                "ValueError: staged_input_validation.json is not a schema-1 JSON object",
                failed["error"],
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

    def test_download_requires_exact_full_object_sha256(self) -> None:
        payload = json.dumps({"schema_version": 1}).encode()

        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            receipt_path = root / "materializer.json"
            output = root / "staged_input_validation.json"
            verification = root / "verification.json"
            stored_receipt = receipt(payload)
            stored_receipt["outputs"]["staged_input_validation.json"]["checksums"][
                "ChecksumCRC32"
            ] = "shared-but-not-sufficient"
            stale_checksums = {
                "ChecksumCRC32": "shared-but-not-sufficient",
                "ChecksumSHA256": MODULE.checksum_sha256("0" * 64),
                "ChecksumType": "FULL_OBJECT",
            }
            receipt_path.write_text(
                json.dumps(stored_receipt, indent=2, sort_keys=True) + "\n",
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
                    **stale_checksums,
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            with patch.object(
                MODULE,
                "head_object",
                return_value={
                    "VersionId": "version-1",
                    "ContentLength": len(payload),
                    **stale_checksums,
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
            failed = json.loads(verification.read_text(encoding="utf-8"))
            self.assertEqual(failed["status"], "failed")
            self.assertTrue(failed["checks"]["sha256_exact"])
            self.assertFalse(failed["checks"]["full_object_sha256_exact"])

    def test_validate_download_rejects_boolean_content_lengths(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            payload = b"1"
            output = root / "staged_input_validation.json"
            output.write_bytes(payload)
            row = {
                "version_id": "version-1",
                "bytes": len(payload),
                "sha256": sha(payload),
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": checksum(payload),
                },
            }
            response = {
                "VersionId": "version-1",
                "ContentLength": len(payload),
                "ChecksumSHA256": checksum(payload),
                "ChecksumType": "FULL_OBJECT",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS,
            }

            for source, head_size, get_size in (
                ("head", True, len(payload)),
                ("get", len(payload), True),
            ):
                with self.subTest(source=source):
                    head = dict(response, ContentLength=head_size)
                    get = dict(response, ContentLength=get_size)

                    checks = MODULE.validate_download(row, head, get, output, KMS)

                    self.assertFalse(checks["bytes_exact"])

    def test_validate_download_rejects_non_string_s3_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            payload = b"1"
            output = root / "staged_input_validation.json"
            output.write_bytes(payload)
            row = {
                "version_id": "version-1",
                "bytes": len(payload),
                "sha256": sha(payload),
                "checksums": {
                    "ChecksumType": "FULL_OBJECT",
                    "ChecksumSHA256": checksum(payload),
                },
            }
            response = {
                "VersionId": "version-1",
                "ContentLength": len(payload),
                "ChecksumSHA256": checksum(payload),
                "ChecksumCRC32": True,
                "ChecksumType": "FULL_OBJECT",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": KMS,
            }

            checks = MODULE.validate_download(row, response, response, output, KMS)

            self.assertFalse(checks["get_checksum_present"])
            self.assertFalse(checks["head_checksum_present"])

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

    def test_schema_version_checks_use_exact_integer_helper(self) -> None:
        cases = (
            (1, 1, True),
            (1.0, 1, False),
            ("1", 1, False),
            (2, 1, False),
            (None, 1, False),
            (True, 1, False),
            (False, 0, False),
        )
        for value, expected, accepted in cases:
            with self.subTest(value=value, expected=expected):
                self.assertIs(
                    MODULE.exact_schema_version(
                        {"schema_version": value},
                        expected,
                    ),
                    accepted,
                )

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "download_materializer_staged_validation.py").read_text(
                encoding="utf-8"
            )
        )
        parent_by_child = {
            child: parent
            for parent in ast.walk(module)
            for child in ast.iter_child_nodes(parent)
        }

        def in_exact_schema_helper(node: ast.AST) -> bool:
            parent = parent_by_child.get(node)
            while parent is not None:
                if isinstance(parent, ast.FunctionDef):
                    return parent.name == "exact_schema_version"
                parent = parent_by_child.get(parent)
            return False

        raw_schema_version_comparisons = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Compare)
            and "schema_version" in ast.unparse(node)
            and not in_exact_schema_helper(node)
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_checksum_guards_avoid_raw_string_coercion(self) -> None:
        module = ast.parse(
            (SCRIPT_DIR / "download_materializer_staged_validation.py").read_text(
                encoding="utf-8"
            )
        )
        raw_string_coercions = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
            and node.args
            and any(
                token in ast.unparse(node.args[0])
                for token in ("Checksum", "checksums")
            )
        ]

        self.assertEqual(raw_string_coercions, [])


if __name__ == "__main__":
    unittest.main()
