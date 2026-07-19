from __future__ import annotations

import ast
import base64
import hashlib
import json
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import download_exact_report_tree as MODULE  # noqa: E402

KMS = "arn:aws:kms:us-east-1:172630973301:key/unit"
BUCKET = "diana-omics-private-results-172630973301-us-east-1"
PREFIX = "runs/subject01/unit/crosschecks/contract/route/attempt/"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2, sort_keys=True)
    if key not in payload:
        raise AssertionError(f"missing top-level JSON field {key}")
    current = f'  "{key}": '
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one top-level JSON field {key}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


def checksum_sha256(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


class ExactReportDownloadTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, bytes, dict]:
        data = b"# private research report\n"
        row = {
            "relative_path": "report.md",
            "uri": f"s3://{BUCKET}/{PREFIX}report.md",
            "key": f"{PREFIX}report.md",
            "version_id": "report-version",
            "sha256": hashlib.sha256(data).hexdigest(),
            "etag": '"synthetic-etag"',
            "content_length": len(data),
            "server_side_encryption": "aws:kms",
            "checksum_sha256": checksum_sha256(data),
            "ssekms_key_id": KMS,
            "checks": dict(MODULE.EXPECTED_PUBLICATION_OBJECT_CHECKS),
        }
        history_audit = {
            "key": row["key"],
            "version_id": row["version_id"],
            "sha256": row["sha256"],
            "checks": dict(MODULE.EXPECTED_HISTORY_AUDIT_CHECKS),
        }

        receipt = root / "publication.json"
        write_json(
            receipt,
            {
                "schema_version": 1,
                "status": "passed",
                "route": "sigprofiler_sbs3",
                "submission_id": "20260717T200000Z-a1b2c3d4",
                "contract": {
                    "uri": f"s3://{BUCKET}/input-contract/deadbeef.json",
                    "version_id": "contract-version",
                    "sha256": "c" * 64,
                },
                "route_output_uri": f"s3://{BUCKET}/{PREFIX}",
                "route_output_initial_version_history_count": 0,
                "route_output_bucket_versioning": "Enabled",
                "publication_strategy": "one_shot_create_only_exact_version_history",
                "objects": [row],
                "history_audit": [history_audit],
                "checks": dict(MODULE.EXPECTED_PUBLICATION_RECEIPT_CHECKS),
            },
        )
        anchor = root / "anchor.json"
        write_json(
            anchor,
            {
                "schema_version": 1,
                "status": "passed",
                "receipt_sha256": MODULE.sha256(receipt),
                "receipt_bytes": receipt.stat().st_size,
                "receipt_uri": (
                    f"s3://{BUCKET}/publication-receipts/"
                    f"{MODULE.sha256(receipt)}.json"
                ),
                "receipt_version_id": "publication-version",
                "route_output_uri": f"s3://{BUCKET}/{PREFIX}",
                "checks": dict(MODULE.EXPECTED_PUBLICATION_ANCHOR_CHECKS),
            },
        )
        return receipt, anchor, data, row

    def args(
        self,
        receipt: Path,
        anchor: Path,
        output: Path,
        verification: Path,
    ) -> list[str]:
        return [
            "--publication-receipt",
            str(receipt),
            "--publication-anchor",
            str(anchor),
            "--kms-key-arn",
            KMS,
            "--output-dir",
            str(output),
            "--verification-output",
            str(verification),
        ]

    def history(self, row: dict) -> list[dict]:
        return [
            {
                "history_kind": "version",
                "Key": row["key"],
                "VersionId": row["version_id"],
                "IsLatest": True,
            }
        ]

    def reanchor(self, receipt: Path, anchor: Path) -> None:
        payload = json.loads(anchor.read_text(encoding="utf-8"))
        payload["receipt_sha256"] = MODULE.sha256(receipt)
        payload["receipt_bytes"] = receipt.stat().st_size
        write_json(anchor, payload)

    def test_version_history_consumes_key_and_version_markers(self) -> None:
        pages = [
            {
                "IsTruncated": True,
                "Versions": [{"Key": f"{PREFIX}report.md", "VersionId": "v1"}],
                "DeleteMarkers": [],
                "NextKeyMarker": f"{PREFIX}report.md",
                "NextVersionIdMarker": "v1",
            },
            {
                "IsTruncated": False,
                "Versions": [],
                "DeleteMarkers": [{"Key": f"{PREFIX}old.md", "VersionId": "d1"}],
            },
        ]

        with patch.object(MODULE, "aws_json", side_effect=pages) as aws_json:
            self.assertEqual(
                MODULE.version_history(BUCKET, PREFIX, "us-east-1"),
                [
                    {
                        "Key": f"{PREFIX}report.md",
                        "VersionId": "v1",
                        "history_kind": "version",
                    },
                    {
                        "Key": f"{PREFIX}old.md",
                        "VersionId": "d1",
                        "history_kind": "delete_marker",
                    },
                ],
            )

        self.assertEqual(
            aws_json.call_args_list[1].args,
            (
                [
                    "s3api",
                    "list-object-versions",
                    "--bucket",
                    BUCKET,
                    "--prefix",
                    PREFIX,
                    "--key-marker",
                    f"{PREFIX}report.md",
                    "--version-id-marker",
                    "v1",
                ],
                "us-east-1",
            ),
        )

    def test_version_history_rejects_malformed_markers(self) -> None:
        cases = (
            {"NextKeyMarker": f"{PREFIX}report.md"},
            {"NextKeyMarker": True, "NextVersionIdMarker": "v1"},
            {"NextKeyMarker": f"{PREFIX}report.md", "NextVersionIdMarker": True},
        )
        for case in cases:
            with self.subTest(case=case), patch.object(
                MODULE,
                "aws_json",
                return_value={
                    **case,
                    "IsTruncated": True,
                    "Versions": [],
                    "DeleteMarkers": [],
                },
            ):
                with self.assertRaisesRegex(ValueError, "key/version markers"):
                    MODULE.version_history(BUCKET, PREFIX, "us-east-1")

    def test_version_history_rejects_stalled_pagination(self) -> None:
        page = {
            "IsTruncated": True,
            "Versions": [],
            "DeleteMarkers": [],
            "NextKeyMarker": f"{PREFIX}report.md",
            "NextVersionIdMarker": "v1",
        }

        with patch.object(MODULE, "aws_json", side_effect=[page, page]):
            with self.assertRaisesRegex(ValueError, "did not advance"):
                MODULE.version_history(BUCKET, PREFIX, "us-east-1")

    def test_exact_version_history_and_download_are_both_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, data, row = self.fixture(root)
            output = root / "report-tree"
            verification = root / "verification.json"

            def fake_get(
                _bucket: str,
                _key: str,
                version_id: str,
                destination: Path,
                _region: str,
            ) -> dict:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                return {
                    "VersionId": version_id,
                    "ContentLength": len(data),
                    "ChecksumSHA256": row["checksum_sha256"],
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            with patch.object(
                MODULE, "version_history", return_value=self.history(row)
            ), patch.object(MODULE, "get_exact", side_effect=fake_get):
                self.assertEqual(
                    MODULE.main(self.args(receipt, anchor, output, verification)),
                    0,
                )

            self.assertEqual((output / "report.md").read_bytes(), data)
            result = json.loads(verification.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "passed")
            self.assertEqual(
                result["live_history_checks"],
                MODULE.EXPECTED_LIVE_HISTORY_CHECKS,
            )
            self.assertEqual(
                result["objects"][0]["checks"],
                MODULE.EXPECTED_DOWNLOAD_OBJECT_CHECKS,
            )
            self.assertEqual(stat.S_IMODE(verification.stat().st_mode), 0o600)

    def test_rejects_missing_unexpected_or_failed_live_history_check_maps(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, _, _, row = self.fixture(root)
            expected_without_latest = dict(MODULE.EXPECTED_LIVE_HISTORY_CHECKS)
            expected_without_latest.pop("all_versions_latest")

            for label, history, expected in (
                (
                    "missing",
                    self.history(row),
                    expected_without_latest,
                ),
                (
                    "unexpected",
                    self.history(row),
                    {
                        **MODULE.EXPECTED_LIVE_HISTORY_CHECKS,
                        "forged_extra": True,
                    },
                ),
                (
                    "failed",
                    [],
                    MODULE.EXPECTED_LIVE_HISTORY_CHECKS,
                ),
            ):
                with self.subTest(label=label), patch.object(
                    MODULE,
                    "EXPECTED_LIVE_HISTORY_CHECKS",
                    expected,
                ), self.assertRaisesRegex(
                    ValueError,
                    "live report version history differs from receipt",
                ):
                    MODULE.validate_live_history(history, [row])

    def test_rejects_missing_unexpected_or_failed_download_check_maps(
        self,
    ) -> None:
        expected_without_kms = dict(MODULE.EXPECTED_DOWNLOAD_OBJECT_CHECKS)
        expected_without_kms.pop("exact_kms")

        for label, expected, break_response in (
            (
                "missing",
                expected_without_kms,
                False,
            ),
            (
                "unexpected",
                {
                    **MODULE.EXPECTED_DOWNLOAD_OBJECT_CHECKS,
                    "forged_extra": True,
                },
                False,
            ),
            (
                "failed",
                MODULE.EXPECTED_DOWNLOAD_OBJECT_CHECKS,
                True,
            ),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                receipt, anchor, data, row = self.fixture(root)
                output = root / "report-tree"
                verification = root / "verification.json"

                def fake_get(
                    _bucket: str,
                    _key: str,
                    version_id: str,
                    destination: Path,
                    _region: str,
                ) -> dict:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
                    return {
                        "VersionId": version_id,
                        "ContentLength": len(data),
                        "ChecksumSHA256": (
                            "wrong" if break_response else row["checksum_sha256"]
                        ),
                        "ChecksumType": "FULL_OBJECT",
                        "ServerSideEncryption": "aws:kms",
                        "SSEKMSKeyId": KMS,
                    }

                with (
                    patch.object(
                        MODULE,
                        "EXPECTED_DOWNLOAD_OBJECT_CHECKS",
                        expected,
                    ),
                    patch.object(
                        MODULE,
                        "version_history",
                        return_value=self.history(row),
                    ),
                    patch.object(MODULE, "get_exact", side_effect=fake_get),
                    self.assertRaisesRegex(
                        SystemExit,
                        "exact report download failed for report.md",
                    ),
                ):
                    MODULE.main(
                        self.args(receipt, anchor, output, verification)
                    )

                self.assertFalse(output.exists())
                self.assertFalse((root / ".report-tree.staging").exists())
                self.assertEqual(
                    json.loads(verification.read_text(encoding="utf-8"))["status"],
                    "failed",
                )

    def test_rejects_missing_unexpected_or_failed_publication_check_maps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)

            def rewrite_receipt(payload: dict) -> None:
                write_json(receipt, payload)
                anchor_payload = json.loads(anchor.read_text(encoding="utf-8"))
                anchor_payload["receipt_sha256"] = MODULE.sha256(receipt)
                anchor_payload["receipt_bytes"] = receipt.stat().st_size
                write_json(anchor, anchor_payload)

            for location, label, mutate, error in (
                (
                    "receipt",
                    "missing",
                    lambda payload: payload["checks"].pop("all_outputs_create_only"),
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
                        "all_output_versions_exact",
                        False,
                    ),
                    "incomplete",
                ),
                (
                    "anchor",
                    "missing",
                    lambda payload: payload["checks"].pop("sha256_exact"),
                    "anchor",
                ),
                (
                    "anchor",
                    "unexpected",
                    lambda payload: payload["checks"].__setitem__(
                        "forged_extra",
                        True,
                    ),
                    "anchor",
                ),
                (
                    "anchor",
                    "failed",
                    lambda payload: payload["checks"].__setitem__(
                        "exact_kms",
                        False,
                    ),
                    "anchor",
                ),
                (
                    "object",
                    "missing",
                    lambda payload: payload["objects"][0]["checks"].pop(
                        "create_only_put"
                    ),
                    "exact custody",
                ),
                (
                    "object",
                    "unexpected",
                    lambda payload: payload["objects"][0]["checks"].__setitem__(
                        "forged_extra",
                        True,
                    ),
                    "exact custody",
                ),
                (
                    "object",
                    "failed",
                    lambda payload: payload["objects"][0]["checks"].__setitem__(
                        "version_exact",
                        False,
                    ),
                    "exact custody",
                ),
            ):
                with self.subTest(location=location, label=label):
                    self.fixture(root)
                    if location == "anchor":
                        payload = json.loads(anchor.read_text(encoding="utf-8"))
                        mutate(payload)
                        write_json(anchor, payload)
                    else:
                        payload = json.loads(receipt.read_text(encoding="utf-8"))
                        mutate(payload)
                        rewrite_receipt(payload)

                    with self.assertRaisesRegex(ValueError, error):
                        MODULE.validate_publication(receipt, anchor, KMS)

    def test_rejects_inexact_publication_receipt_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)

            def rewrite_receipt(payload: dict) -> None:
                write_json(receipt, payload)
                anchor_payload = json.loads(anchor.read_text(encoding="utf-8"))
                anchor_payload["receipt_sha256"] = MODULE.sha256(receipt)
                anchor_payload["receipt_bytes"] = receipt.stat().st_size
                write_json(anchor, anchor_payload)

            for location, mutate, error in (
                (
                    "receipt",
                    lambda payload: payload.__setitem__("legacy_note", "accepted"),
                    "receipt envelope",
                ),
                (
                    "object",
                    lambda payload: payload["objects"][0].__setitem__(
                        "legacy_note",
                        "accepted",
                    ),
                    "object row",
                ),
                (
                    "history",
                    lambda payload: payload["history_audit"][0].__setitem__(
                        "legacy_note",
                        "accepted",
                    ),
                    "history audit",
                ),
            ):
                with self.subTest(location=location):
                    self.fixture(root)
                    payload = json.loads(receipt.read_text(encoding="utf-8"))
                    mutate(payload)
                    rewrite_receipt(payload)

                    with self.assertRaisesRegex(ValueError, error):
                        MODULE.validate_publication(receipt, anchor, KMS)

            payload = json.loads(anchor.read_text(encoding="utf-8"))
            payload["legacy_note"] = "accepted"
            write_json(anchor, payload)

            with self.assertRaisesRegex(ValueError, "anchor envelope"):
                MODULE.validate_publication(receipt, anchor, KMS)

    def test_rejects_non_exact_publication_receipt_sha256_values(self) -> None:
        cases = (
            (
                "numeric_contract",
                lambda payload: payload["contract"].__setitem__(
                    "sha256",
                    int("1" * 64),
                ),
                "publication contract SHA-256",
            ),
            (
                "uppercase_contract",
                lambda payload: payload["contract"].__setitem__(
                    "sha256",
                    "C" * 64,
                ),
                "publication contract SHA-256",
            ),
            (
                "numeric_object",
                lambda payload: (
                    payload["objects"][0].__setitem__("sha256", int("1" * 64)),
                    payload["history_audit"][0].__setitem__(
                        "sha256",
                        int("1" * 64),
                    ),
                ),
                "publication object SHA-256",
            ),
            (
                "numeric_history",
                lambda payload: (
                    payload["objects"][0].__setitem__("sha256", "1" * 64),
                    payload["history_audit"][0].__setitem__(
                        "sha256",
                        int("1" * 64),
                    ),
                ),
                "publication history SHA-256",
            ),
        )

        for name, mutate, error in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                receipt, anchor, _, _ = self.fixture(root)
                payload = json.loads(receipt.read_text(encoding="utf-8"))
                mutate(payload)
                write_json(receipt, payload)
                self.reanchor(receipt, anchor)

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_publication(receipt, anchor, KMS)

    def test_rejects_coerced_publication_receipt_version_ids(self) -> None:
        receipt_cases = (
            (
                "numeric_contract",
                lambda payload: payload["contract"].__setitem__(
                    "version_id",
                    1234567890,
                ),
                "publication receipt contract",
            ),
            (
                "numeric_object",
                lambda payload: (
                    payload["objects"][0].__setitem__("version_id", 1234567890),
                    payload["history_audit"][0].__setitem__(
                        "version_id",
                        1234567890,
                    ),
                ),
                "exact custody",
            ),
            (
                "numeric_history",
                lambda payload: payload["history_audit"][0].__setitem__(
                    "version_id",
                    1234567890,
                ),
                "history audit",
            ),
        )

        for name, mutate, error in receipt_cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                receipt, anchor, _, _ = self.fixture(root)
                payload = json.loads(receipt.read_text(encoding="utf-8"))
                mutate(payload)
                write_json(receipt, payload)
                self.reanchor(receipt, anchor)

                with self.assertRaisesRegex(ValueError, error):
                    MODULE.validate_publication(receipt, anchor, KMS)

        with self.subTest(name="numeric_anchor"), tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)
            payload = json.loads(anchor.read_text(encoding="utf-8"))
            payload["receipt_version_id"] = 1234567890
            write_json(anchor, payload)

            with self.assertRaisesRegex(ValueError, "publication anchor"):
                MODULE.validate_publication(receipt, anchor, KMS)

    def test_rejects_inexact_publication_receipt_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)
            payload = json.loads(anchor.read_text(encoding="utf-8"))
            payload["receipt_bytes"] = str(receipt.stat().st_size)
            write_json(anchor, payload)

            with self.assertRaisesRegex(ValueError, "anchor"):
                MODULE.validate_publication(receipt, anchor, KMS)

            receipt, anchor, _, _ = self.fixture(root)
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["objects"][0]["content_length"] = True
            write_json(receipt, payload)
            self.reanchor(receipt, anchor)

            with self.assertRaisesRegex(ValueError, "exact custody"):
                MODULE.validate_publication(receipt, anchor, KMS)

    def test_download_rejects_boolean_content_length_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, row = self.fixture(root)
            output = root / "report-tree"
            verification = root / "verification.json"
            data = b"1"
            digest = hashlib.sha256(data).hexdigest()
            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["objects"][0]["sha256"] = digest
            payload["objects"][0]["content_length"] = 1
            payload["objects"][0]["checksum_sha256"] = checksum_sha256(data)
            payload["history_audit"][0]["sha256"] = digest
            write_json(receipt, payload)
            self.reanchor(receipt, anchor)

            def fake_get(
                _bucket: str,
                _key: str,
                version_id: str,
                destination: Path,
                _region: str,
            ) -> dict:
                destination.write_bytes(data)
                return {
                    "VersionId": version_id,
                    "ContentLength": True,
                    "ChecksumSHA256": checksum_sha256(data),
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            with (
                patch.object(MODULE, "version_history", return_value=self.history(row)),
                patch.object(MODULE, "get_exact", side_effect=fake_get),
                self.assertRaisesRegex(
                    SystemExit,
                    "exact report download failed for report.md",
                ),
            ):
                MODULE.main(self.args(receipt, anchor, output, verification))

            self.assertFalse(output.exists())
            self.assertFalse((root / ".report-tree.staging").exists())
            self.assertEqual(
                json.loads(verification.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_prepared_verification_rejects_boolean_object_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report-tree" / "report.md"
            report.parent.mkdir()
            report.write_bytes(b"1")

            with self.assertRaisesRegex(
                ValueError,
                "downloaded report differs from its receipt",
            ):
                MODULE.validate_local_tree(
                    report.parent,
                    [
                        {
                            "relative_path": "report.md",
                            "bytes": True,
                            "sha256": MODULE.sha256(report),
                        }
                    ],
                )

    def test_rejects_non_exact_publication_schema_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)

            def rewrite_receipt(payload: dict) -> None:
                write_json(receipt, payload)
                anchor_payload = json.loads(anchor.read_text(encoding="utf-8"))
                anchor_payload["receipt_sha256"] = MODULE.sha256(receipt)
                anchor_payload["receipt_bytes"] = receipt.stat().st_size
                write_json(anchor, anchor_payload)

            payload = json.loads(receipt.read_text(encoding="utf-8"))
            payload["schema_version"] = 1.0
            rewrite_receipt(payload)

            with self.assertRaisesRegex(ValueError, "incomplete"):
                MODULE.validate_publication(receipt, anchor, KMS)

            self.fixture(root)
            payload = json.loads(anchor.read_text(encoding="utf-8"))
            payload["schema_version"] = 1.0
            write_json(anchor, payload)

            with self.assertRaisesRegex(ValueError, "anchor"):
                MODULE.validate_publication(receipt, anchor, KMS)

    def test_rejects_unexpected_staging_child_before_local_cutover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, data, row = self.fixture(root)
            output = root / "report-tree"
            verification = root / "verification.json"

            def fake_get(
                _bucket: str,
                _key: str,
                version_id: str,
                destination: Path,
                _region: str,
            ) -> dict:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                (destination.parent / "unexpected.md").write_text(
                    "extra\n",
                    encoding="utf-8",
                )
                return {
                    "VersionId": version_id,
                    "ContentLength": len(data),
                    "ChecksumSHA256": row["checksum_sha256"],
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            with (
                patch.object(MODULE, "version_history", return_value=self.history(row)),
                patch.object(MODULE, "get_exact", side_effect=fake_get),
                self.assertRaisesRegex(
                    SystemExit,
                    "downloaded report inventory differs from its receipt",
                ),
            ):
                MODULE.main(self.args(receipt, anchor, output, verification))

            self.assertFalse(output.exists())
            self.assertFalse((root / ".report-tree.staging").exists())
            self.assertEqual(
                json.loads(verification.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_revalidates_output_tree_after_final_cutover_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, data, row = self.fixture(root)
            output = root / "report-tree"
            verification = root / "verification.json"
            real_fsync_directory = MODULE.fsync_directory

            def fake_get(
                _bucket: str,
                _key: str,
                version_id: str,
                destination: Path,
                _region: str,
            ) -> dict:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                return {
                    "VersionId": version_id,
                    "ContentLength": len(data),
                    "ChecksumSHA256": row["checksum_sha256"],
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            def tamper_after_cutover_fsync(path: Path) -> None:
                real_fsync_directory(path)
                local = output / "report.md"
                if local.exists():
                    local.write_bytes(b"tampered\n")

            with (
                patch.object(MODULE, "version_history", return_value=self.history(row)),
                patch.object(MODULE, "get_exact", side_effect=fake_get),
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_cutover_fsync,
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    "downloaded report differs from its receipt",
                ),
            ):
                MODULE.main(self.args(receipt, anchor, output, verification))

            self.assertFalse(output.exists())
            self.assertFalse((root / ".report-tree.staging").exists())
            self.assertEqual(
                json.loads(verification.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_rejects_symlinked_exact_version_report_before_local_cutover(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, data, row = self.fixture(root)
            output = root / "report-tree"
            verification = root / "verification.json"
            redirected = root / "redirected-report.md"

            def fake_get(_arguments: list[str], _region: str) -> dict:
                destination = output.with_name(f".{output.name}.staging") / "report.md"
                destination.parent.mkdir(parents=True, exist_ok=True)
                redirected.write_bytes(data)
                destination.symlink_to(redirected)
                return {
                    "VersionId": row["version_id"],
                    "ContentLength": len(data),
                    "ChecksumSHA256": row["checksum_sha256"],
                    "ChecksumType": "FULL_OBJECT",
                    "ServerSideEncryption": "aws:kms",
                    "SSEKMSKeyId": KMS,
                }

            with (
                patch.object(MODULE, "version_history", return_value=self.history(row)),
                patch.object(MODULE, "aws_json", side_effect=fake_get),
                self.assertRaisesRegex(SystemExit, "downloaded report object must be a real file"),
            ):
                MODULE.main(self.args(receipt, anchor, output, verification))

            self.assertFalse(output.exists())
            self.assertFalse((root / ".report-tree.staging").exists())
            self.assertEqual(redirected.read_bytes(), data)
            self.assertEqual(
                json.loads(verification.read_text(encoding="utf-8"))["status"],
                "failed",
            )

    def test_reserve_json_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            verification = Path(temporary) / "verification.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                verification.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "verification output changed during write",
                ),
            ):
                MODULE.reserve_json(verification, {"status": "in_progress"})

            self.assertFalse(verification.exists())

    def test_write_json_atomic_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            verification = Path(temporary) / "verification.json"
            real_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                verification.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "verification output changed during write",
                ),
            ):
                MODULE.write_json_atomic(verification, {"status": "passed"})

    def test_prepared_verification_recovers_cutover_without_redownload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, data, row = self.fixture(root)
            output = root / "report-tree"
            staging = root / ".report-tree.staging"
            staging.mkdir()
            (staging / "report.md").write_bytes(data)
            verification = root / "verification.json"
            prepared = {
                "schema_version": 1,
                "status": "prepared",
                "publication_receipt_sha256": MODULE.sha256(receipt),
                "publication_receipt_uri": json.loads(
                    anchor.read_text(encoding="utf-8")
                )["receipt_uri"],
                "route_output_uri": f"s3://{BUCKET}/{PREFIX}",
                "expected_kms_key_arn": KMS,
                "output_dir": str(output.resolve()),
                "objects": [
                    {
                        "relative_path": "report.md",
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                ],
            }
            MODULE.reserve_json(verification, prepared)

            with patch.object(
                MODULE, "version_history", return_value=self.history(row)
            ), patch.object(MODULE, "get_exact") as get_exact:
                self.assertEqual(
                    MODULE.main(self.args(receipt, anchor, output, verification)),
                    0,
                )

            get_exact.assert_not_called()
            self.assertEqual((output / "report.md").read_bytes(), data)
            result = json.loads(verification.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "passed")
            self.assertTrue(result["recovered_prepared_cutover"])

    def test_prepared_verification_requires_exact_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, data, row = self.fixture(root)
            output = root / "report-tree"
            staging = root / ".report-tree.staging"
            staging.mkdir()
            (staging / "report.md").write_bytes(data)
            verification = root / "verification.json"
            MODULE.reserve_json(
                verification,
                {
                    "schema_version": 1.0,
                    "status": "prepared",
                    "publication_receipt_sha256": MODULE.sha256(receipt),
                    "publication_receipt_uri": json.loads(
                        anchor.read_text(encoding="utf-8")
                    )["receipt_uri"],
                    "route_output_uri": f"s3://{BUCKET}/{PREFIX}",
                    "expected_kms_key_arn": KMS,
                    "output_dir": str(output.resolve()),
                    "objects": [
                        {
                            "relative_path": "report.md",
                            "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                        }
                    ],
                },
            )

            with (
                patch.object(MODULE, "version_history", return_value=self.history(row)),
                patch.object(MODULE, "get_exact") as get_exact,
                self.assertRaisesRegex(
                    SystemExit,
                    "existing verification receipt belongs to another replay",
                ),
            ):
                MODULE.main(self.args(receipt, anchor, output, verification))

            get_exact.assert_not_called()

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
            (SCRIPT_DIR / "download_exact_report_tree.py").read_text(
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

    def test_refuses_symlinked_output_before_verification_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            direct_target = real_parent / "direct-target"
            direct_target.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            linked_output = root / "linked-output"
            linked_output.symlink_to(direct_target, target_is_directory=True)

            for output in (linked_output, linked_parent / "report-tree"):
                with self.subTest(output=output):
                    verification = root / f"{output.name}.verification.json"
                    with self.assertRaisesRegex(
                        SystemExit,
                        "report output.* may not be a symlink",
                    ):
                        MODULE.main(
                            self.args(receipt, anchor, output, verification)
                        )

                    self.assertFalse(verification.exists())
                    self.assertFalse((real_parent / "report-tree").exists())

    def test_refuses_output_below_symlinked_parent_before_verification_reservation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            output = linked_parent / "missing" / "report-tree"
            verification = root / "verification.json"
            with self.assertRaisesRegex(
                SystemExit,
                "report output.* parent may not be a symlink",
            ):
                MODULE.main(self.args(receipt, anchor, output, verification))

            self.assertFalse(verification.exists())
            self.assertFalse((real_parent / "missing").exists())

    def test_refuses_symlinked_verification_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)
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
                    output = root / f"{verification.name}.report-tree"
                    with self.assertRaisesRegex(
                        SystemExit,
                        "verification output.* may not be a symlink",
                    ):
                        MODULE.main(
                            self.args(receipt, anchor, output, verification)
                        )

                    self.assertEqual(
                        real_verification.read_text(encoding="utf-8"),
                        '{"status":"passed"}\n',
                    )

    def test_refuses_verification_below_symlinked_parent_before_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)
            real_verification_parent = root / "real-verifications"
            real_verification_parent.mkdir()
            linked_verification_parent = root / "linked-verifications"
            linked_verification_parent.symlink_to(
                real_verification_parent,
                target_is_directory=True,
            )

            output = root / "report-tree"
            verification = linked_verification_parent / "missing" / "verification.json"
            with self.assertRaisesRegex(
                SystemExit,
                "verification output.* parent may not be a symlink",
            ):
                MODULE.main(self.args(receipt, anchor, output, verification))

            self.assertFalse(output.exists())
            self.assertFalse((real_verification_parent / "missing").exists())

    def test_refuses_receipt_or_anchor_below_symlinked_parent_before_aws(
        self,
    ) -> None:
        cases = (
            ("publication receipt", "receipt"),
            ("publication anchor", "anchor"),
        )
        for message, moved_name in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                receipt, anchor, _, _row = self.fixture(root)
                real_parent = root / "real-inputs"
                real_parent.mkdir()
                linked_parent = root / "linked-inputs"
                linked_parent.symlink_to(real_parent, target_is_directory=True)

                moved = real_parent / f"{moved_name}.json"
                source = receipt if message == "publication receipt" else anchor
                shutil.copy2(source, moved)
                if message == "publication receipt":
                    receipt = linked_parent / moved.name
                else:
                    anchor = linked_parent / moved.name

                output = root / "report-tree"
                verification = root / "verification.json"
                with (
                    patch.object(
                        MODULE,
                        "version_history",
                        side_effect=AssertionError("AWS called"),
                    ),
                    patch.object(
                        MODULE,
                        "get_exact",
                        side_effect=AssertionError("AWS called"),
                    ),
                    self.assertRaisesRegex(
                        SystemExit,
                        f"{message} parent may not be a symlink",
                    ),
                ):
                    MODULE.main(self.args(receipt, anchor, output, verification))

                self.assertFalse(output.exists())
                self.assertFalse(verification.exists())

    def test_sha256_requires_real_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, _anchor, data, _row = self.fixture(root)

            receipt_link = root / "publication-link.json"
            receipt_link.symlink_to(receipt)
            with self.assertRaisesRegex(
                ValueError,
                "publication-link\\.json SHA-256 input must be a real file",
            ):
                MODULE.sha256(receipt_link)

            real_parent = root / "real-report"
            real_parent.mkdir()
            linked_parent = root / "linked-report"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            (real_parent / "report.md").write_bytes(data)

            with self.assertRaisesRegex(
                ValueError,
                "report\\.md SHA-256 input parent may not be a symlink",
            ):
                MODULE.sha256(linked_parent / "report.md")

    def test_rejects_duplicate_receipt_object_names_before_download(self) -> None:
        cases = (
            (
                "publication receipt",
                lambda receipt, _anchor, _verification: receipt,
                "publication receipt",
                False,
            ),
            (
                "publication anchor",
                lambda _receipt, anchor, _verification: anchor,
                "publication anchor",
                False,
            ),
            (
                "verification receipt",
                lambda _receipt, _anchor, verification: verification,
                "verification receipt",
                True,
            ),
        )
        for label, select_path, error_label, needs_history in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                receipt, anchor, _, row = self.fixture(root)
                output = root / "report-tree"
                verification = root / "verification.json"
                if needs_history:
                    write_json(verification, {"schema_version": 1, "status": "failed"})

                write_duplicate_json_field(
                    select_path(receipt, anchor, verification),
                    "schema_version",
                    0,
                )

                history = (
                    patch.object(
                        MODULE,
                        "version_history",
                        return_value=self.history(row),
                    )
                    if needs_history
                    else patch.object(
                        MODULE,
                        "version_history",
                        side_effect=AssertionError("AWS called"),
                    )
                )
                with (
                    history,
                    patch.object(
                        MODULE,
                        "get_exact",
                        side_effect=AssertionError("AWS called"),
                    ) as get_exact,
                    self.assertRaisesRegex(
                        SystemExit,
                        f"duplicate JSON object name in {error_label}: "
                        "schema_version",
                    ),
                ):
                    MODULE.main(self.args(receipt, anchor, output, verification))

                get_exact.assert_not_called()
                self.assertFalse(output.exists())

    def test_refuses_output_below_existing_dir_under_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, _ = self.fixture(root)
            real_parent = root / "real-parent"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            output = linked_parent / "existing" / "report-tree"
            verification = root / "verification.json"
            with self.assertRaisesRegex(
                SystemExit,
                "report output.* parent may not be a symlink",
            ):
                MODULE.main(self.args(receipt, anchor, output, verification))

            self.assertFalse(verification.exists())
            self.assertFalse((real_parent / "existing" / "report-tree").exists())

    def test_changed_history_and_traversal_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt, anchor, _, row = self.fixture(root)
            value = json.loads(receipt.read_text(encoding="utf-8"))
            value["objects"][0]["relative_path"] = "../report.md"
            write_json(receipt, value)
            anchor_value = json.loads(anchor.read_text(encoding="utf-8"))
            anchor_value["receipt_sha256"] = MODULE.sha256(receipt)
            anchor_value["receipt_bytes"] = receipt.stat().st_size
            write_json(anchor, anchor_value)

            with self.assertRaisesRegex(ValueError, "unsafe report"):
                MODULE.validate_publication(receipt, anchor, KMS)

            receipt, anchor, _, row = self.fixture(root)
            with patch.object(
                MODULE, "version_history", return_value=[]
            ), self.assertRaisesRegex(
                SystemExit, "live report version history differs"
            ):
                MODULE.main(
                    self.args(
                        receipt,
                        anchor,
                        root / "output",
                        root / "verification.json",
                    )
                )


if __name__ == "__main__":
    unittest.main()
