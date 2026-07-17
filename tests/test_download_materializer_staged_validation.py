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


if __name__ == "__main__":
    unittest.main()
