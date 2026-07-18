from __future__ import annotations

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

import download_exact_report_tree as MODULE  # noqa: E402

KMS = "arn:aws:kms:us-east-1:172630973301:key/unit"
BUCKET = "diana-omics-private-results-172630973301-us-east-1"
PREFIX = "runs/subject01/unit/crosschecks/contract/route/attempt/"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
            "content_length": len(data),
            "checksum_sha256": checksum_sha256(data),
            "ssekms_key_id": KMS,
        }

        receipt = root / "publication.json"
        write_json(
            receipt,
            {
                "schema_version": 1,
                "status": "passed",
                "route_output_uri": f"s3://{BUCKET}/{PREFIX}",
                "route_output_initial_version_history_count": 0,
                "route_output_bucket_versioning": "Enabled",
                "publication_strategy": "one_shot_create_only_exact_version_history",
                "objects": [row],
                "checks": {"exact": True},
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
                "checks": {"exact": True},
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

    def test_version_history_rejects_missing_version_marker(self) -> None:
        with patch.object(
            MODULE,
            "aws_json",
            return_value={
                "IsTruncated": True,
                "Versions": [],
                "DeleteMarkers": [],
                "NextKeyMarker": f"{PREFIX}report.md",
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
            self.assertTrue(all(result["objects"][0]["checks"].values()))
            self.assertEqual(stat.S_IMODE(verification.stat().st_mode), 0o600)

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
