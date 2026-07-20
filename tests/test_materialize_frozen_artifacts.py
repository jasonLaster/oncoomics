from __future__ import annotations

import ast
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


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2, sort_keys=True)
    current = f'  "{key}": {json.dumps(payload[key], sort_keys=True)}'
    description = f"top-level JSON field {key}"
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one {description}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


class MaterializeFrozenArtifactsTests(unittest.TestCase):
    def freeze_fixture(self, root: Path, kms: str) -> Path:
        receipt = root / "freeze.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "generated_at": "2026-07-19T00:00:00+00:00",
                    "run_id": "synthetic-run",
                    "batch_job_id": "synthetic-job",
                    "batch_status": "SUCCEEDED",
                    "execution_receipt": {
                        "path": str(root / "terminal.execution.succeeded.json"),
                        "sha256": "a" * 64,
                    },
                    "source_prefix": (
                        "s3://diana-omics-work-test/runs/diana-hrd/"
                        "synthetic-run/private-results/final/artifacts/"
                    ),
                    "kms_key_arn": kms,
                    "script_sha256": "b" * 64,
                    "destination_bucket_versioning": "Enabled",
                    "destination_initial_version_history_count": 0,
                    "receipt_anchor_strategy": "sha256_content_addressed_create_only",
                    "destination_prefix": (
                        "s3://diana-omics-private-results-test/"
                        "runs/subject01/synthetic-run/deterministic/artifacts/"
                    ),
                    "object_count": 1,
                    "objects": [
                        {
                            "relative_key": "variants/final.vcf.gz",
                            "status": "passed",
                            "source": {
                                "bucket": "diana-omics-work-test",
                                "key": (
                                    "runs/diana-hrd/synthetic-run/private-results/"
                                    "final/artifacts/variants/final.vcf.gz"
                                ),
                                "version_id": "source-version",
                                "bytes": 5,
                                "etag": "source-etag",
                                "checksums": {"ChecksumCRC64NVME": "checksum"},
                                "checksum_type": "FULL_OBJECT",
                            },
                            "destination": {
                                "bucket": "diana-omics-private-results-test",
                                "key": (
                                    "runs/subject01/synthetic-run/deterministic/"
                                    "artifacts/variants/final.vcf.gz"
                                ),
                                "version_id": "exact-version",
                                "bytes": 5,
                                "etag": "destination-etag",
                                "checksums": {"ChecksumCRC64NVME": "checksum"},
                                "checksum_type": "FULL_OBJECT",
                                "server_side_encryption": "aws:kms",
                                "kms_key_id": kms,
                            },
                            "checks": {
                                "listed_inventory_stable": True,
                                "source_stable": True,
                                "size_matches": True,
                                "common_checksum_matches": True,
                                "exact_kms_matches": True,
                                "destination_versioned": True,
                                "copy_response_version_matches": True,
                            },
                        }
                    ],
                    "initial_inventory_identity": [
                        {
                            "relative_key": "variants/final.vcf.gz",
                            "key": (
                                "runs/diana-hrd/synthetic-run/private-results/"
                                "final/artifacts/variants/final.vcf.gz"
                            ),
                            "bytes": 5,
                            "etag": "source-etag",
                            "version_id": "source-version",
                        }
                    ],
                    "final_inventory_identity": [
                        {
                            "relative_key": "variants/final.vcf.gz",
                            "key": (
                                "runs/diana-hrd/synthetic-run/private-results/"
                                "final/artifacts/variants/final.vcf.gz"
                            ),
                            "bytes": 5,
                            "etag": "source-etag",
                            "version_id": "source-version",
                        }
                    ],
                    "destination_inventory": [
                        {
                            "relative_key": "variants/final.vcf.gz",
                            "key": (
                                "runs/subject01/synthetic-run/deterministic/"
                                "artifacts/variants/final.vcf.gz"
                            ),
                            "version_id": "exact-version",
                            "bytes": 5,
                            "etag": "destination-etag",
                            "checksums": {"ChecksumCRC64NVME": "checksum"},
                            "checksum_type": "FULL_OBJECT",
                            "kms_key_id": kms,
                        }
                    ],
                    "checks": {
                        "execution_receipt_bound": True,
                        "complete_source_inventory_unchanged": True,
                        "destination_exact_history_and_receipt_match": True,
                    },
                    "completed_at": "2026-07-19T00:00:01+00:00",
                    "passed_count": 1,
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
        for value in (
            "",
            "/absolute",
            "../escape",
            "variants/../../escape",
            True,
            1,
            None,
        ):
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
            for value in (0, True, "1"):
                with self.subTest(value=value), self.assertRaisesRegex(
                    ValueError,
                    "positive byte count",
                ):
                    MODULE.validate_materialized(
                        {
                            "version_id": "v",
                            "bytes": value,
                            "checksums": {"ChecksumCRC64NVME": "c"},
                            "checksum_type": "FULL_OBJECT",
                        },
                        {},
                        path,
                        "kms",
                    )

    def test_exact_version_and_checksums_must_be_strings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact"
            path.write_bytes(b"1")
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            expected = {
                "version_id": "frozen-version",
                "bytes": 1,
                "checksums": {"ChecksumCRC64NVME": "checksum"},
                "checksum_type": "FULL_OBJECT",
            }
            response = {
                "VersionId": "frozen-version",
                "ContentLength": 1,
                "ChecksumCRC64NVME": "checksum",
                "ChecksumType": "FULL_OBJECT",
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": kms,
            }

            for value in (True, "null", "None", "has space"):
                with self.subTest(version_id=value), self.assertRaisesRegex(
                    ValueError,
                    "exact VersionId",
                ):
                    MODULE.validate_materialized(
                        {**expected, "version_id": value},
                        response,
                        path,
                        kms,
                    )

            for value in (True, 123, ""):
                with self.subTest(checksum=value), self.assertRaisesRegex(
                    ValueError,
                    "exact S3 checksum",
                ):
                    MODULE.validate_materialized(
                        {
                            **expected,
                            "checksums": {"ChecksumCRC64NVME": value},
                        },
                        response,
                        path,
                        kms,
                    )

            with self.assertRaisesRegex(ValueError, "materialization checks failed"):
                MODULE.validate_materialized(
                    expected,
                    {**response, "VersionId": True},
                    path,
                    kms,
                )

            with self.assertRaisesRegex(ValueError, "materialization checks failed"):
                MODULE.validate_materialized(
                    expected,
                    {**response, "ChecksumCRC64NVME": True},
                    path,
                    kms,
                )

    def test_exact_version_download_rejects_boolean_content_length(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact"
            path.write_bytes(b"1")
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"

            with self.assertRaisesRegex(
                ValueError,
                "materialization checks failed",
            ):
                MODULE.validate_materialized(
                    {
                        "version_id": "frozen-version",
                        "bytes": 1,
                        "checksums": {"ChecksumCRC64NVME": "checksum"},
                        "checksum_type": "FULL_OBJECT",
                    },
                    {
                        "VersionId": "frozen-version",
                        "ContentLength": True,
                        "ChecksumCRC64NVME": "checksum",
                        "ChecksumType": "FULL_OBJECT",
                        "ServerSideEncryption": "aws:kms",
                        "SSEKMSKeyId": kms,
                    },
                    path,
                    kms,
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

    def test_rejects_stale_final_freeze_receipt_before_download(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            base = json.loads(freeze.read_text(encoding="utf-8"))

            def set_one_object_boolean_count(receipt: dict) -> None:
                receipt["objects"] = receipt["objects"][:1]
                receipt["destination_inventory"] = receipt["destination_inventory"][:1]
                receipt["object_count"] = True
                receipt["passed_count"] = 1

            def set_boolean_destination_bytes(receipt: dict) -> None:
                receipt["objects"][0]["destination"]["bytes"] = 1
                receipt["destination_inventory"][0]["bytes"] = True

            def set_destination_version(receipt: dict, value: object) -> None:
                receipt["objects"][0]["destination"]["version_id"] = value
                receipt["destination_inventory"][0]["version_id"] = value

            def set_destination_checksum(receipt: dict, value: object) -> None:
                checksums = {"ChecksumCRC64NVME": value}
                receipt["objects"][0]["destination"]["checksums"] = checksums
                receipt["destination_inventory"][0]["checksums"] = checksums

            for label, mutate in (
                (
                    "extra-top-level",
                    lambda receipt: receipt.__setitem__("legacy_note", "accepted"),
                ),
                (
                    "failed-check",
                    lambda receipt: receipt["checks"].__setitem__(
                        "destination_exact_history_and_receipt_match", False
                    ),
                ),
                (
                    "truthy-int-check",
                    lambda receipt: receipt["checks"].__setitem__(
                        "destination_exact_history_and_receipt_match", 1
                    ),
                ),
                (
                    "non-exact-schema",
                    lambda receipt: receipt.__setitem__("schema_version", 1.0),
                ),
                (
                    "boolean-destination-history-count",
                    lambda receipt: receipt.__setitem__(
                        "destination_initial_version_history_count",
                        False,
                    ),
                ),
                (
                    "float-destination-history-count",
                    lambda receipt: receipt.__setitem__(
                        "destination_initial_version_history_count",
                        0.0,
                    ),
                ),
                (
                    "boolean-object-count",
                    set_one_object_boolean_count,
                ),
                (
                    "boolean-destination-bytes",
                    set_boolean_destination_bytes,
                ),
                (
                    "missing-row-checks",
                    lambda receipt: receipt["objects"][0].pop("checks"),
                ),
                (
                    "truthy-int-row-check",
                    lambda receipt: receipt["objects"][0]["checks"].__setitem__(
                        "copy_response_version_matches", 1
                    ),
                ),
                (
                    "extra-destination",
                    lambda receipt: receipt["objects"][0]["destination"].__setitem__(
                        "legacy_note", "accepted"
                    ),
                ),
                (
                    "stale-destination-inventory",
                    lambda receipt: receipt["destination_inventory"][0].__setitem__(
                        "version_id", "stale-version"
                    ),
                ),
                (
                    "coerced-destination-version",
                    lambda receipt: set_destination_version(receipt, True),
                ),
                (
                    "sentinel-destination-version",
                    lambda receipt: set_destination_version(receipt, "null"),
                ),
                (
                    "coerced-destination-checksum",
                    lambda receipt: set_destination_checksum(receipt, True),
                ),
            ):
                with self.subTest(label=label):
                    candidate = json.loads(json.dumps(base))
                    mutate(candidate)
                    freeze.write_text(
                        json.dumps(candidate, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    output = root / f"{label}-materialized"
                    receipt = root / f"{label}-materialization.json"

                    with (
                        patch.object(
                            MODULE,
                            "get_exact_object",
                            side_effect=AssertionError("AWS called"),
                        ) as get_exact,
                        self.assertRaisesRegex(
                            SystemExit,
                            (
                                "private freeze receipt.*not exact"
                                "|destination inventory differs"
                                "|exact VersionId"
                                "|exact S3 checksum"
                            ),
                        ),
                    ):
                        MODULE.main(self.args(freeze, output, receipt, kms))

                    get_exact.assert_not_called()
                    self.assertFalse(output.exists())
                    self.assertFalse(receipt.exists())

    def test_rejects_duplicate_final_freeze_receipt_object_names_before_download(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            write_duplicate_json_field(freeze, "schema_version", 0)
            output = root / "materialized"
            receipt = root / "materialization.json"

            with (
                patch.object(
                    MODULE,
                    "get_exact_object",
                    side_effect=AssertionError("AWS called"),
                ) as get_exact,
                self.assertRaisesRegex(
                    SystemExit,
                    "duplicate JSON object name in freeze receipt: schema_version",
                ),
            ):
                MODULE.main(self.args(freeze, output, receipt, kms))

            get_exact.assert_not_called()
            self.assertFalse(output.exists())
            self.assertFalse(receipt.exists())

    def test_hashes_validated_final_freeze_receipt_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            expected_sha = MODULE.sha256(freeze)
            output = root / "materialized"
            receipt = root / "materialization.json"

            def validate_then_tamper(
                payload: dict,
                expected_kms_key_arn: str,
            ) -> list[dict]:
                self.assertEqual("synthetic-run", payload.get("run_id"))
                self.assertEqual(kms, expected_kms_key_arn)
                freeze.write_text('{"status":"tampered"}\n', encoding="utf-8")
                return []

            with patch.object(
                MODULE,
                "require_exact_final_freeze",
                side_effect=validate_then_tamper,
            ):
                MODULE.main(self.args(freeze, output, receipt, kms))

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(expected_sha, payload["freeze_receipt_sha256"])
            self.assertEqual("passed", payload["status"])

    def test_hashes_validated_prior_materialization_receipt_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"
            prior = {
                "schema_version": 1,
                "status": "failed",
                "run_id": "synthetic-run",
                "batch_job_id": "synthetic-job",
                "script_sha256": MODULE.sha256(
                    SCRIPT_DIR / "materialize_frozen_artifacts.py"
                ),
                "freeze_receipt_sha256": MODULE.sha256(freeze),
                "expected_kms_key_arn": kms,
                "materialization_dir": str(output.resolve()),
                "object_count": 0,
                "objects": [],
                "error": "synthetic failure",
            }
            MODULE.reserve_json(receipt, prior)
            expected_prior_sha = MODULE.sha256(receipt)

            def tamper_prior_and_continue(
                payload: dict,
                _staging: Path,
                _output: Path,
                receipt_output: Path,
            ) -> bool:
                self.assertEqual(prior, payload)
                receipt_output.write_text(
                    '{"status":"tampered"}\n',
                    encoding="utf-8",
                )
                return False

            with patch.object(
                MODULE,
                "recover_local_cutover",
                side_effect=tamper_prior_and_continue,
            ), patch.object(MODULE, "require_exact_final_freeze", return_value=[]):
                MODULE.main(self.args(freeze, output, receipt, kms))

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(expected_prior_sha, payload["prior_receipt_sha256"])
            self.assertEqual("failed", payload["recovered_from_status"])
            self.assertEqual("passed", payload["status"])

    def test_load_object_with_sha256_hashes_parsed_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            payload = b'{"status":"passed"}\n'
            receipt.write_bytes(payload)

            parsed, digest = MODULE.load_object_with_sha256(receipt, "receipt")

        self.assertEqual({"status": "passed"}, parsed)
        self.assertEqual(MODULE.sha256_bytes(payload), digest)

    def test_load_object_with_sha256_rejects_stale_local_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")

            with (
                patch.object(MODULE, "sha256", return_value="0" * 64),
                self.assertRaisesRegex(ValueError, "receipt changed during read"),
            ):
                MODULE.load_object_with_sha256(receipt, "receipt")

    def test_prepared_receipt_recovery_requires_exact_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"
            MODULE.reserve_json(
                receipt,
                {
                    "schema_version": 1.0,
                    "status": "prepared",
                    "run_id": "synthetic-run",
                    "batch_job_id": "synthetic-job",
                    "script_sha256": MODULE.sha256(
                        SCRIPT_DIR / "materialize_frozen_artifacts.py"
                    ),
                    "freeze_receipt_sha256": MODULE.sha256(freeze),
                    "expected_kms_key_arn": kms,
                    "materialization_dir": str(output.resolve()),
                    "object_count": 1,
                    "objects": [],
                },
            )

            with (
                patch.object(
                    MODULE,
                    "get_exact_object",
                    side_effect=AssertionError("AWS called"),
                ) as get_exact,
                self.assertRaisesRegex(
                    SystemExit,
                    "belongs to another operation",
                ),
            ):
                MODULE.main(self.args(freeze, output, receipt, kms))

            get_exact.assert_not_called()
            self.assertFalse(output.exists())

    def test_prepared_receipt_recovery_rejects_duplicate_object_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"
            MODULE.reserve_json(
                receipt,
                {
                    "schema_version": 1,
                    "status": "prepared",
                    "run_id": "synthetic-run",
                    "batch_job_id": "synthetic-job",
                    "script_sha256": MODULE.sha256(
                        SCRIPT_DIR / "materialize_frozen_artifacts.py"
                    ),
                    "freeze_receipt_sha256": MODULE.sha256(freeze),
                    "expected_kms_key_arn": kms,
                    "materialization_dir": str(output.resolve()),
                    "object_count": 1,
                    "objects": [],
                },
            )
            write_duplicate_json_field(receipt, "schema_version", 0)

            with (
                patch.object(
                    MODULE,
                    "get_exact_object",
                    side_effect=AssertionError("AWS called"),
                ) as get_exact,
                self.assertRaisesRegex(
                    SystemExit,
                    "duplicate JSON object name in "
                    "materialization receipt: schema_version",
                ),
            ):
                MODULE.main(self.args(freeze, output, receipt, kms))

            get_exact.assert_not_called()
            self.assertFalse(output.exists())

    def test_prepared_receipt_recovery_requires_exact_object_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kms = "arn:aws:kms:us-east-1:172630973301:key/test"
            freeze = self.freeze_fixture(root, kms)
            output = root / "materialized"
            receipt = root / "materialization.json"
            MODULE.reserve_json(
                receipt,
                {
                    "schema_version": 1,
                    "status": "prepared",
                    "run_id": "synthetic-run",
                    "batch_job_id": "synthetic-job",
                    "script_sha256": MODULE.sha256(
                        SCRIPT_DIR / "materialize_frozen_artifacts.py"
                    ),
                    "freeze_receipt_sha256": MODULE.sha256(freeze),
                    "expected_kms_key_arn": kms,
                    "materialization_dir": str(output.resolve()),
                    "object_count": True,
                    "objects": [],
                },
            )

            with (
                patch.object(
                    MODULE,
                    "get_exact_object",
                    side_effect=AssertionError("AWS called"),
                ) as get_exact,
                self.assertRaisesRegex(
                    SystemExit,
                    "belongs to another operation",
                ),
            ):
                MODULE.main(self.args(freeze, output, receipt, kms))

            get_exact.assert_not_called()
            self.assertFalse(output.exists())

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
            (SCRIPT_DIR / "materialize_frozen_artifacts.py").read_text(
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

    def test_sha256_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_input = root / "real-materialization.json"
            linked_input = root / "materialization-link.json"
            real_input.write_text("{}\n", encoding="utf-8")
            linked_input.symlink_to(real_input)

            real_parent = root / "real-inputs"
            real_parent.mkdir()
            (real_parent / "materialization.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            linked_parent = root / "linked-inputs"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            cases = (
                (
                    linked_input,
                    "materialization-link.json SHA-256 input must be a real file",
                ),
                (
                    linked_parent / "materialization.json",
                    "materialization.json SHA-256 input parent may not be a symlink",
                ),
            )
            for path, message in cases:
                with self.subTest(path=path):
                    with self.assertRaisesRegex(ValueError, message):
                        MODULE.sha256(path)

    def test_sha256_rejects_hash_input_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "materialization.json"
            receipt.write_text('{"stable": true}\n', encoding="utf-8")

            original_sha256_file_once = MODULE.sha256_file_once
            mutated = False

            def mutate_after_first_read(path: Path) -> str:
                nonlocal mutated
                digest = original_sha256_file_once(path)
                if path == receipt and not mutated:
                    mutated = True
                    path.write_text('{"stable": false}\n', encoding="utf-8")
                return digest

            with (
                patch.object(
                    MODULE,
                    "sha256_file_once",
                    side_effect=mutate_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "materialization.json SHA-256 input changed during read",
                ),
            ):
                MODULE.sha256(receipt)

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

    def test_prepared_receipt_recovery_rejects_boolean_object_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / ".materialized.staging"
            staged_file = staging / "variants/final.vcf.gz"
            staged_file.parent.mkdir(parents=True)
            staged_file.write_bytes(b"1")

            with self.assertRaisesRegex(
                ValueError,
                "materialized tree differs from its receipt",
            ):
                MODULE.validate_local_tree(
                    staging,
                    [
                        {
                            "relative_key": "variants/final.vcf.gz",
                            "bytes": True,
                            "sha256": MODULE.sha256(staged_file),
                        }
                    ],
                )

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
