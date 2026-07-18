from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "publish_public_results_index.py"
SPEC = importlib.util.spec_from_file_location("publish_public_results_index", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def checksum(value: bytes) -> str:
    return base64.b64encode(hashlib.sha256(value).digest()).decode("ascii")


class FakeAws:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.put_calls: list[list[str]] = []
        self.public: dict[str, object] = {}
        self.versioning_status = "Enabled"
        self.null_version = False
        self.literal_null_version = False
        self.wrong_checksum = False

    @staticmethod
    def value(arguments: list[str], name: str) -> str:
        return arguments[arguments.index(name) + 1]

    def aws_json(self, arguments: list[str], region: str) -> dict[str, object]:
        if region != MODULE.REGION:
            raise AssertionError(f"wrong region: {region}")
        operation = tuple(arguments[:2])
        if operation == ("s3api", "get-bucket-versioning"):
            return {"Status": self.versioning_status}
        if operation == ("s3api", "put-object"):
            self.put_calls.append(list(arguments))
            if self.null_version:
                return {}
            body = Path(self.value(arguments, "--body"))
            payload = body.read_bytes()
            if payload != self.payload:
                raise AssertionError("unexpected uploaded body")
            observed_checksum = checksum(b"different" if self.wrong_checksum else payload)
            self.public = {
                "VersionId": "null" if self.literal_null_version else "public-index-version-1",
                "ContentLength": len(payload),
                "ChecksumType": MODULE.CHECKSUM_TYPE,
                "ChecksumSHA256": observed_checksum,
                "ServerSideEncryption": MODULE.SERVER_SIDE_ENCRYPTION,
                "Metadata": json.loads(self.value(arguments, "--metadata")),
                "CacheControl": self.value(arguments, "--cache-control"),
                "ContentType": self.value(arguments, "--content-type"),
            }
            return {"VersionId": self.public["VersionId"]}
        if operation == ("s3api", "head-object"):
            return dict(self.public)
        raise AssertionError(f"unexpected AWS call: {arguments}")


class PublishPublicResultsIndexTests(unittest.TestCase):
    def write_index(self, root: Path, **updates: object) -> Path:
        payload = {
            "schema_version": 1,
            "bucket": MODULE.BUCKET,
            "classification": "reviewed_public_validation_and_alias_only_analysis_outputs",
            "generated_at": "2026-07-17T00:00:00+00:00",
            "prefixes": list(MODULE.PUBLIC_PREFIXES),
            "object_count": 2,
            "total_size": 30,
            "objects": [
                {
                    "key": MODULE.PUBLIC_PREFIXES[0] + "a.json",
                    "size": 10,
                    "last_modified": "2026-07-17T00:00:00+00:00",
                },
                {
                    "key": MODULE.PUBLIC_PREFIXES[0] + "b.json",
                    "size": 20,
                    "last_modified": "2026-07-17T00:00:01+00:00",
                },
            ],
        }
        payload.update(updates)
        path = root / "objects.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return path

    def args(
        self,
        index: Path,
        receipt: Path,
        *,
        apply: bool = False,
        dry_run_receipt: Path | None = None,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            index=index,
            receipt_output=receipt,
            dry_run_receipt=dry_run_receipt,
            region=MODULE.REGION,
            apply=apply,
        )

    def write_dry_run_receipt(self, root: Path, index: Path) -> Path:
        receipt = root / "dry-run-receipt.json"
        with mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")):
            MODULE.run(self.args(index, receipt))
        return receipt

    def test_dry_run_validates_index_without_uploading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = self.write_index(root)
            receipt = root / "receipt.json"
            with mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")):
                result = MODULE.run(self.args(index, receipt))

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["index"]["sha256"], digest(index.read_bytes()))
            self.assertEqual(result["index"]["object_count"], 2)
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)

    def test_apply_uses_sse_sha256_cache_control_and_index_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = self.write_index(root)
            receipt = root / "receipt.json"
            dry_run_receipt = self.write_dry_run_receipt(root, index)
            fake = FakeAws(index.read_bytes())

            with mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json):
                result = MODULE.run(
                    self.args(index, receipt, apply=True, dry_run_receipt=dry_run_receipt)
                )

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["dry_run_receipt"]["path"], str(dry_run_receipt.resolve()))
            self.assertEqual(
                result["dry_run_receipt"]["sha256"],
                digest(dry_run_receipt.read_bytes()),
            )
            self.assertEqual(result["destination_object"]["version_id"], "public-index-version-1")
            self.assertTrue(result["checks"]["destination_current_version_exact"])
            self.assertTrue(result["checks"]["dry_run_receipt"])
            self.assertEqual(len(fake.put_calls), 1)
            self.assertEqual(FakeAws.value(fake.put_calls[0], "--bucket"), MODULE.BUCKET)
            self.assertEqual(FakeAws.value(fake.put_calls[0], "--key"), MODULE.INDEX_KEY)
            self.assertEqual(
                FakeAws.value(fake.put_calls[0], "--checksum-algorithm"), "SHA256"
            )
            self.assertEqual(
                json.loads(FakeAws.value(fake.put_calls[0], "--metadata")),
                {
                    "classification": MODULE.CLASSIFICATION,
                    "sha256": digest(index.read_bytes()),
                },
            )

    def test_apply_rejects_suspended_bucket_versioning_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = self.write_index(root)
            receipt = root / "receipt.json"
            dry_run_receipt = self.write_dry_run_receipt(root, index)
            fake = FakeAws(index.read_bytes())
            fake.versioning_status = "Suspended"

            with mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json):
                with self.assertRaisesRegex(ValueError, "versioning is not enabled"):
                    MODULE.run(
                        self.args(index, receipt, apply=True, dry_run_receipt=dry_run_receipt)
                    )

            self.assertEqual(fake.put_calls, [])
            self.assertEqual(json.loads(receipt.read_text())["status"], "failed")

    def test_rejects_private_or_out_of_order_index_keys_before_aws(self) -> None:
        for objects, message in (
            (
                [
                    {
                        "key": "runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/report.md",
                        "size": 10,
                        "last_modified": "2026-07-17T00:00:00+00:00",
                    }
                ],
                "not allowlisted",
            ),
            (
                [
                    {
                        "key": (
                            "runs/diana-hrd-public/subject01/"
                            "diana-wgs-hrd-20260716T033101Z/"
                            "unreviewed-scratch/report.md"
                        ),
                        "size": 10,
                        "last_modified": "2026-07-17T00:00:00+00:00",
                    }
                ],
                "not allowlisted",
            ),
            (
                [
                    {
                        "key": MODULE.PUBLIC_PREFIXES[0] + "b.json",
                        "size": 20,
                        "last_modified": "2026-07-17T00:00:01+00:00",
                    },
                    {
                        "key": MODULE.PUBLIC_PREFIXES[0] + "a.json",
                        "size": 10,
                        "last_modified": "2026-07-17T00:00:00+00:00",
                    },
                ],
                "inventory is not exact",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index = self.write_index(
                    root,
                    objects=objects,
                    object_count=len(objects),
                    total_size=sum(row["size"] for row in objects),
                )
                with self.assertRaisesRegex(ValueError, message), mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ):
                    MODULE.run(self.args(index, root / "receipt.json"))

    def test_apply_rejects_destination_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = self.write_index(root)
            receipt = root / "receipt.json"
            dry_run_receipt = self.write_dry_run_receipt(root, index)
            fake = FakeAws(index.read_bytes())
            fake.wrong_checksum = True

            with mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json):
                with self.assertRaisesRegex(ValueError, "destination verification failed"):
                    MODULE.run(
                        self.args(index, receipt, apply=True, dry_run_receipt=dry_run_receipt)
                    )

            self.assertEqual(json.loads(receipt.read_text())["status"], "failed")

    def test_apply_rejects_missing_or_null_destination_version(self) -> None:
        for field in ("null_version", "literal_null_version"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index = self.write_index(root)
                receipt = root / "receipt.json"
                dry_run_receipt = self.write_dry_run_receipt(root, index)
                fake = FakeAws(index.read_bytes())
                setattr(fake, field, True)

                with mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json):
                    with self.assertRaisesRegex(ValueError, "non-null VersionId"):
                        MODULE.run(
                            self.args(index, receipt, apply=True, dry_run_receipt=dry_run_receipt)
                        )

                self.assertEqual(json.loads(receipt.read_text())["status"], "failed")

    def test_apply_requires_matching_dry_run_receipt_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = self.write_index(root)

            with self.assertRaisesRegex(
                ValueError, "requires --dry-run-receipt"
            ), mock.patch.object(
                MODULE, "aws_json", side_effect=AssertionError("AWS called")
            ):
                MODULE.run(self.args(index, root / "missing.json", apply=True))

            dry_run_index = self.write_index(
                root, generated_at="2026-07-18T00:00:00+00:00"
            )
            dry_run_receipt = self.write_dry_run_receipt(root, dry_run_index)
            index = self.write_index(root)

            with self.assertRaisesRegex(
                ValueError, "does not match the index"
            ), mock.patch.object(
                MODULE, "aws_json", side_effect=AssertionError("AWS called")
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "mismatched.json",
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                    )
                )

    def test_apply_rejects_failed_or_redirected_dry_run_receipts_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = self.write_index(root)
            dry_run_receipt = self.write_dry_run_receipt(root, index)
            failed_receipt = json.loads(dry_run_receipt.read_text())
            failed_receipt["status"] = "failed"
            dry_run_receipt.write_text(
                json.dumps(failed_receipt, indent=2, sort_keys=True) + "\n"
            )

            with self.assertRaisesRegex(
                ValueError, "contract is malformed"
            ), mock.patch.object(
                MODULE, "aws_json", side_effect=AssertionError("AWS called")
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "apply.json",
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                    )
                )

            real_receipt = root / "real-receipt.json"
            dry_run_receipt.replace(real_receipt)
            dry_run_receipt.symlink_to(real_receipt)

            with self.assertRaisesRegex(
                ValueError, "must be a real file"
            ), mock.patch.object(
                MODULE, "aws_json", side_effect=AssertionError("AWS called")
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "redirected.json",
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                    )
                )

    def test_existing_receipt_output_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = self.write_index(root)
            receipt = root / "receipt.json"
            receipt.write_text("preserve\n")

            with self.assertRaises(FileExistsError):
                MODULE.run(self.args(index, receipt))

            self.assertEqual(receipt.read_text(), "preserve\n")

    def test_receipt_output_rejects_symlinked_parent_without_writing_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            index = self.write_index(root)
            real_parent = root / "real-receipts"
            real_parent.mkdir()
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.run(self.args(index, linked_parent / "receipt.json"))

            self.assertFalse((real_parent / "receipt.json").exists())

    def test_receipt_output_rejects_nested_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-receipts"
            real_parent.mkdir()
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            receipt = linked_parent / "missing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "redirected"},
                    create=True,
                )

            self.assertFalse((real_parent / "missing" / "receipt.json").exists())

    def test_receipt_output_rejects_existing_dir_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-receipts"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            receipt = linked_parent / "existing" / "receipt.json"

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "redirected"},
                    create=True,
                )

            self.assertFalse((real_parent / "existing" / "receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
