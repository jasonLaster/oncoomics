from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_build_public_results_index import (
    MODULE as BUILD_INDEX,
)
from tests.test_build_public_results_index import (
    expected_public_heads,
    expected_public_prefix_pages,
    write_public_receipts,
)

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
        self.boolean_version = False
        self.wrong_checksum = False
        self.boolean_content_length = False

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
            if self.value(arguments, "--checksum-sha256") != checksum(payload):
                raise AssertionError("unexpected put-object checksum")
            self.public = {
                "VersionId": (
                    True
                    if self.boolean_version
                    else "null"
                    if self.literal_null_version
                    else "public-index-version-1"
                ),
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
            metadata = dict(self.public)
            if self.boolean_content_length:
                metadata["ContentLength"] = True
            return metadata
        raise AssertionError(f"unexpected AWS call: {arguments}")


class PublishPublicResultsIndexTests(unittest.TestCase):
    def test_schema_versions_are_exact_json_integers(self) -> None:
        for value in (True, 1.0, "1", 2, None):
            with self.subTest(value=value):
                self.assertFalse(
                    MODULE.exact_schema_version({"schema_version": value})
                )

        self.assertTrue(MODULE.exact_schema_version({"schema_version": 1}))

    def test_schema_guards_use_exact_integer_helper(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SCRIPT))

        raw_comparisons = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "schema_version" not in segment:
                continue
            raw_comparisons.append(f"{node.lineno}: {segment}")

        self.assertEqual(raw_comparisons, [])

    def test_sha256_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "real-source.txt"
            real_source.write_text("real source\n", encoding="utf-8")
            source_link = root / "source-link.txt"
            source_link.symlink_to(real_source)

            with self.assertRaisesRegex(
                ValueError,
                "source-link.txt SHA-256 input must be a real file",
            ):
                MODULE.sha256(source_link)

            real_inputs = root / "real-inputs"
            real_inputs.mkdir()
            public_index = real_inputs / "objects.json"
            public_index.write_text(
                '{"object_count": 0}\n',
                encoding="utf-8",
            )
            linked_inputs = root / "linked-inputs"
            linked_inputs.symlink_to(real_inputs, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "objects.json SHA-256 input parent may not be a symlink",
            ):
                MODULE.sha256(linked_inputs / "objects.json")

    def test_public_index_hash_rejects_symlink_after_receipt_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index = self.write_index(root)
            moved = root / "objects.real.json"

            def swap_index_after_receipt_validation(
                reviewed_public_receipts: list[Path],
            ) -> tuple[dict, list]:
                index.rename(moved)
                index.symlink_to(moved)
                return {}, []

            with (
                mock.patch.object(
                    MODULE,
                    "validate_reviewed_public_receipts",
                    side_effect=swap_index_after_receipt_validation,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "objects.json SHA-256 input must be a real file",
                ),
            ):
                MODULE.validate_public_index(index, [])

    def write_index(self, root: Path, **updates: object) -> Path:
        payload = {
            "schema_version": 1,
            "bucket": MODULE.BUCKET,
            "classification": "reviewed_public_validation_and_alias_only_analysis_outputs",
            "generated_at": "2026-07-17T00:00:00+00:00",
            "prefixes": list(MODULE.PUBLIC_PREFIXES),
            "object_count": 2,
            "total_size": 30,
            "reviewed_public_receipts": [],
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

    def write_receipt_bound_index(self, root: Path) -> tuple[Path, list[Path]]:
        receipts = write_public_receipts(root)
        index = root / "objects.json"
        with mock.patch.object(
            BUILD_INDEX,
            "list_prefix",
            side_effect=expected_public_prefix_pages(receipts),
        ), mock.patch.object(
            BUILD_INDEX,
            "head_object",
            side_effect=expected_public_heads(receipts).__getitem__,
        ):
            argv = ["--output", str(index)]
            for receipt in receipts:
                argv.extend(["--reviewed-public-receipt", str(receipt)])
            BUILD_INDEX.main(argv)
        return index, receipts

    def args(
        self,
        index: Path,
        receipt: Path,
        *,
        apply: bool = False,
        dry_run_receipt: Path | None = None,
        reviewed_public_receipts: list[Path] | None = None,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            index=index,
            receipt_output=receipt,
            dry_run_receipt=dry_run_receipt,
            reviewed_public_receipt=reviewed_public_receipts or [],
            region=MODULE.REGION,
            apply=apply,
        )

    def write_dry_run_receipt(
        self,
        root: Path,
        index: Path,
        reviewed_public_receipts: list[Path],
    ) -> Path:
        receipt = root / "dry-run-receipt.json"
        with mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")):
            MODULE.run(
                self.args(
                    index,
                    receipt,
                    reviewed_public_receipts=reviewed_public_receipts,
                )
            )
        return receipt

    def test_dry_run_validates_index_without_uploading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            receipt = root / "receipt.json"
            with mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")):
                result = MODULE.run(
                    self.args(index, receipt, reviewed_public_receipts=receipts)
                )

            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["index"]["sha256"], digest(index.read_bytes()))
            self.assertEqual(result["index"]["reviewed_public_receipt_count"], 10)
            self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)

    def test_apply_uses_sse_sha256_cache_control_and_index_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            receipt = root / "receipt.json"
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            fake = FakeAws(index.read_bytes())

            with (
                mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
                mock.patch.object(
                    MODULE,
                    "validate_reviewed_public_apply_state",
                ) as validate_apply_state,
            ):
                result = MODULE.run(
                    self.args(
                        index,
                        receipt,
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                        reviewed_public_receipts=receipts,
                    )
                )

            self.assertEqual(result["status"], "passed")
            validate_apply_state.assert_called_once_with(receipts, MODULE.REGION)
            self.assertEqual(result["dry_run_receipt"]["path"], str(dry_run_receipt.resolve()))
            self.assertEqual(
                result["dry_run_receipt"]["sha256"],
                digest(dry_run_receipt.read_bytes()),
            )
            self.assertEqual(result["destination_object"]["version_id"], "public-index-version-1")
            self.assertEqual(result["index"]["reviewed_public_receipt_count"], 10)
            self.assertTrue(result["checks"]["destination_current_version_exact"])
            self.assertTrue(result["checks"]["dry_run_receipt"])
            self.assertEqual(len(fake.put_calls), 1)
            self.assertEqual(FakeAws.value(fake.put_calls[0], "--bucket"), MODULE.BUCKET)
            self.assertEqual(FakeAws.value(fake.put_calls[0], "--key"), MODULE.INDEX_KEY)
            self.assertEqual(
                FakeAws.value(fake.put_calls[0], "--checksum-algorithm"), "SHA256"
            )
            self.assertEqual(
                FakeAws.value(fake.put_calls[0], "--checksum-sha256"),
                checksum(index.read_bytes()),
            )
            self.assertEqual(
                json.loads(FakeAws.value(fake.put_calls[0], "--metadata")),
                {
                    "classification": MODULE.CLASSIFICATION,
                    "sha256": digest(index.read_bytes()),
                },
            )

    def test_apply_rejects_reviewed_public_version_drift_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            heads = expected_public_heads(receipts)
            stale_key = next(iter(heads))
            heads[stale_key] = {
                **heads[stale_key],
                "VersionId": "unexpected-overwrite",
            }

            with (
                mock.patch.object(
                    MODULE,
                    "head_object",
                    side_effect=lambda _bucket, key, _region: heads[key],
                ),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=AssertionError("index AWS called"),
                ),
                self.assertRaisesRegex(RuntimeError, "current reviewed-public"),
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "apply.json",
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                        reviewed_public_receipts=receipts,
                    )
                )

            self.assertFalse((root / "apply.json").exists())

    def test_apply_rejects_suspended_bucket_versioning_before_upload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            receipt = root / "receipt.json"
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            fake = FakeAws(index.read_bytes())
            fake.versioning_status = "Suspended"

            with (
                mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
                mock.patch.object(MODULE, "validate_reviewed_public_apply_state"),
            ):
                with self.assertRaisesRegex(ValueError, "versioning is not enabled"):
                    MODULE.run(
                        self.args(
                            index,
                            receipt,
                            apply=True,
                            dry_run_receipt=dry_run_receipt,
                            reviewed_public_receipts=receipts,
                        )
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
                    MODULE.run(
                        self.args(
                            index,
                            root / "receipt.json",
                            reviewed_public_receipts=write_public_receipts(root),
                        )
                    )

    def test_rejects_stale_public_index_envelopes_before_aws(self) -> None:
        cases = (
            (
                lambda payload: payload.__setitem__("legacy_receipt_sha256", "0" * 64),
                "public index contract is malformed",
            ),
            (
                lambda payload: payload["objects"][0].__setitem__(
                    "legacy_version_id",
                    "old-public-version",
                ),
                "public index object envelope is not exact",
            ),
            (
                lambda payload: payload.__setitem__("object_count", True),
                "public index contract is malformed",
            ),
            (
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "public index contract is malformed",
            ),
            (
                lambda payload: (
                    payload["objects"].__setitem__(
                        0,
                        {
                            "key": MODULE.PUBLIC_PREFIXES[-1] + "one-byte.json",
                            "size": True,
                            "last_modified": "2026-07-17T00:00:00+00:00",
                        },
                    ),
                    payload.__setitem__("objects", payload["objects"][:1]),
                    payload.__setitem__("object_count", 1),
                    payload.__setitem__("total_size", 1),
                    payload.__setitem__("reviewed_public_receipts", []),
                ),
                "public index object is not allowlisted",
            ),
            (
                lambda payload: (
                    payload.__setitem__("objects", []),
                    payload.__setitem__("object_count", 0),
                    payload.__setitem__("total_size", False),
                    payload.__setitem__("reviewed_public_receipts", []),
                ),
                "public index contract is malformed",
            ),
        )
        for mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index, receipts = self.write_receipt_bound_index(root)
                payload = json.loads(index.read_text(encoding="utf-8"))
                mutate(payload)
                index.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    self.assertRaisesRegex(ValueError, message),
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        side_effect=AssertionError("AWS called"),
                    ),
                ):
                    MODULE.run(
                        self.args(
                            index,
                            root / "receipt.json",
                            reviewed_public_receipts=receipts,
                        )
                    )

    def test_rejects_index_with_duplicate_json_object_names_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            payload = json.loads(index.read_text(encoding="utf-8"))
            text = json.dumps(payload, indent=2, sort_keys=True).replace(
                f'  "object_count": {payload["object_count"]},',
                (
                    '  "object_count": 0,\n'
                    f'  "object_count": {payload["object_count"]},'
                ),
                1,
            )
            index.write_text(text + "\n", encoding="utf-8")

            with (
                self.assertRaisesRegex(
                    ValueError,
                    "duplicate JSON object name in public index: object_count",
                ),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "receipt.json",
                        reviewed_public_receipts=receipts,
                    )
                )

    def test_rejects_index_symlinked_after_sha256_before_json_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            forged = root / "forged-objects.json"
            forged.write_text(index.read_text(encoding="utf-8"))
            real_sha256 = MODULE.sha256
            swapped = False
            index_resolved = index.resolve()

            def swap_index_after_sha256(path: Path) -> str:
                nonlocal swapped
                digest = real_sha256(path)
                if path == index_resolved and not swapped:
                    swapped = True
                    path.unlink()
                    path.symlink_to(forged)
                return digest

            with (
                self.assertRaisesRegex(ValueError, "public index must be a real file"),
                mock.patch.object(MODULE, "sha256", side_effect=swap_index_after_sha256),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "receipt.json",
                        reviewed_public_receipts=receipts,
                    )
                )

            self.assertTrue(swapped)
            self.assertFalse((root / "receipt.json").exists())

    def test_rejects_index_below_symlinked_parent_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-indexes"
            real_parent.mkdir()
            index, receipts = self.write_receipt_bound_index(real_parent)
            linked_parent = root / "linked-indexes"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            linked_index = linked_parent / index.name
            receipt = root / "receipt.json"

            with (
                self.assertRaisesRegex(
                    ValueError, "public index parent may not be a symlink"
                ),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(
                    self.args(linked_index, receipt, reviewed_public_receipts=receipts)
                )

            self.assertFalse(receipt.exists())

    def test_apply_rejects_destination_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            receipt = root / "receipt.json"
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            fake = FakeAws(index.read_bytes())
            fake.wrong_checksum = True

            with (
                mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
                mock.patch.object(MODULE, "validate_reviewed_public_apply_state"),
            ):
                with self.assertRaisesRegex(ValueError, "destination verification failed"):
                    MODULE.run(
                        self.args(
                            index,
                            receipt,
                            apply=True,
                            dry_run_receipt=dry_run_receipt,
                            reviewed_public_receipts=receipts,
                        )
                    )

            self.assertEqual(json.loads(receipt.read_text())["status"], "failed")

    def test_upload_index_rejects_boolean_destination_content_length(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = b"x"
            index = Path(temporary) / "objects.json"
            index.write_bytes(payload)
            fake = FakeAws(payload)
            fake.boolean_content_length = True

            with (
                mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
                self.assertRaisesRegex(
                    ValueError,
                    "public index destination verification failed",
                ),
            ):
                MODULE.upload_index(
                    index,
                    {"sha256": digest(payload), "bytes": len(payload)},
                    MODULE.REGION,
                )

    def test_public_index_destination_checks_must_be_exact(self) -> None:
        cases = (
            {"version_exact": True},
            {
                **MODULE.PUBLIC_INDEX_DESTINATION_CHECKS,
                "unexpected_late_check": True,
            },
        )

        for checks in cases:
            with self.subTest(checks=checks):
                with self.assertRaisesRegex(
                    ValueError,
                    "public index destination verification failed",
                ):
                    MODULE.require_public_index_destination_checks_exact(checks)

    def test_apply_rejects_outdated_public_index_destination_check_set(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            receipt = root / "receipt.json"
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            fake = FakeAws(index.read_bytes())

            with (
                mock.patch.object(
                    MODULE,
                    "PUBLIC_INDEX_DESTINATION_CHECKS",
                    {
                        **MODULE.PUBLIC_INDEX_DESTINATION_CHECKS,
                        "unexpected_late_check": True,
                    },
                ),
                mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
                mock.patch.object(MODULE, "validate_reviewed_public_apply_state"),
                self.assertRaisesRegex(
                    ValueError,
                    "public index destination verification failed",
                ),
            ):
                MODULE.run(
                    self.args(
                        index,
                        receipt,
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                        reviewed_public_receipts=receipts,
                    )
                )

    def test_apply_rejects_missing_or_null_destination_version(self) -> None:
        for field in ("null_version", "literal_null_version", "boolean_version"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index, receipts = self.write_receipt_bound_index(root)
                receipt = root / "receipt.json"
                dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
                fake = FakeAws(index.read_bytes())
                setattr(fake, field, True)

                with (
                    mock.patch.object(MODULE, "aws_json", side_effect=fake.aws_json),
                    mock.patch.object(
                        MODULE,
                        "validate_reviewed_public_apply_state",
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, "non-null VersionId"):
                        MODULE.run(
                            self.args(
                                index,
                                receipt,
                                apply=True,
                                dry_run_receipt=dry_run_receipt,
                                reviewed_public_receipts=receipts,
                            )
                        )

                self.assertEqual(json.loads(receipt.read_text())["status"], "failed")

    def test_apply_requires_matching_dry_run_receipt_before_aws(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)

            with self.assertRaisesRegex(
                ValueError, "requires --dry-run-receipt"
            ), mock.patch.object(
                MODULE, "aws_json", side_effect=AssertionError("AWS called")
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "missing.json",
                        apply=True,
                        reviewed_public_receipts=receipts,
                    )
                )

            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["generated_at"] = "2026-07-18T00:00:00+00:00"
            index.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

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
                        reviewed_public_receipts=receipts,
                    )
                )

    def test_apply_rejects_failed_or_redirected_dry_run_receipts_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
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
                        reviewed_public_receipts=receipts,
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
                        reviewed_public_receipts=receipts,
                    )
                )

    def test_apply_rejects_dry_run_receipt_with_extra_failed_check_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            payload = json.loads(dry_run_receipt.read_text(encoding="utf-8"))
            payload["checks"]["unexpected_late_check"] = False
            dry_run_receipt.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with (
                self.assertRaisesRegex(ValueError, "did not pass preflight checks"),
                mock.patch.object(
                    MODULE, "aws_json", side_effect=AssertionError("AWS called")
                ),
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "apply.json",
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                        reviewed_public_receipts=receipts,
                    )
                )

            self.assertFalse((root / "apply.json").exists())

    def test_apply_rejects_dry_run_receipt_with_stale_extra_metadata_before_aws(
        self,
    ) -> None:
        cases = (
            (
                "top-level",
                lambda payload: payload.update(
                    {"stale_reviewed_public_receipt_count": 9}
                ),
                "contract is malformed",
            ),
            (
                "float schema_version",
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "contract is malformed",
            ),
            (
                "nested index",
                lambda payload: payload["index"].update({"old_sha256": "0" * 64}),
                "does not match the index",
            ),
            (
                "index bytes float",
                lambda payload: payload["index"].__setitem__(
                    "bytes", float(payload["index"]["bytes"])
                ),
                "does not match the index",
            ),
            (
                "index object_count float",
                lambda payload: payload["index"].__setitem__(
                    "object_count", float(payload["index"]["object_count"])
                ),
                "does not match the index",
            ),
            (
                "index total_size string",
                lambda payload: payload["index"].__setitem__(
                    "total_size", str(payload["index"]["total_size"])
                ),
                "does not match the index",
            ),
            (
                "index reviewed_public_receipt_count float",
                lambda payload: payload["index"].__setitem__(
                    "reviewed_public_receipt_count",
                    float(payload["index"]["reviewed_public_receipt_count"]),
                ),
                "does not match the index",
            ),
            (
                "nested destination",
                lambda payload: payload["destination"].update(
                    {"old_uri": f"s3://{MODULE.BUCKET}/public-index/old.json"}
                ),
                "does not match the destination",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index, receipts = self.write_receipt_bound_index(root)
                dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
                payload = json.loads(dry_run_receipt.read_text(encoding="utf-8"))
                mutate(payload)
                dry_run_receipt.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    self.assertRaisesRegex(ValueError, message),
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        side_effect=AssertionError("AWS called"),
                    ),
                ):
                    MODULE.run(
                        self.args(
                            index,
                            root / "apply.json",
                            apply=True,
                            dry_run_receipt=dry_run_receipt,
                            reviewed_public_receipts=receipts,
                        )
                    )

                self.assertFalse((root / "apply.json").exists())

    def test_apply_rejects_dry_run_receipt_with_duplicate_json_object_names_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            payload = json.loads(dry_run_receipt.read_text(encoding="utf-8"))
            text = json.dumps(payload, indent=2, sort_keys=True)
            status = f'  "status": "{payload["status"]}"'
            self.assertEqual(text.count(status), 1)
            text = text.replace(status, f'  "status": "failed",\n{status}', 1)
            dry_run_receipt.write_text(text + "\n", encoding="utf-8")

            with (
                self.assertRaisesRegex(
                    ValueError,
                    (
                        "duplicate JSON object name in "
                        "public index dry-run receipt: status"
                    ),
                ),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "apply.json",
                        apply=True,
                        dry_run_receipt=dry_run_receipt,
                        reviewed_public_receipts=receipts,
                    )
                )

            self.assertFalse((root / "apply.json").exists())

    def test_apply_rejects_dry_run_receipt_below_symlinked_parent_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            dry_run_receipt = self.write_dry_run_receipt(root, index, receipts)
            real_parent = root / "real-dry-run-receipts"
            real_parent.mkdir()
            moved_receipt = real_parent / "dry-run-receipt.json"
            dry_run_receipt.rename(moved_receipt)
            linked_parent = root / "linked-dry-run-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with (
                self.assertRaisesRegex(
                    ValueError,
                    "public index dry-run receipt parent may not be a symlink",
                ),
                mock.patch.object(MODULE, "aws_json", side_effect=AssertionError("AWS called")),
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "apply.json",
                        apply=True,
                        dry_run_receipt=linked_parent / "dry-run-receipt.json",
                        reviewed_public_receipts=receipts,
                    )
                )

    def test_existing_receipt_output_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            receipt = root / "receipt.json"
            receipt.write_text("preserve\n")

            with self.assertRaises(FileExistsError):
                MODULE.run(self.args(index, receipt, reviewed_public_receipts=receipts))

            self.assertEqual(receipt.read_text(), "preserve\n")

    def test_receipt_output_rejects_symlinked_parent_without_writing_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            index, receipts = self.write_receipt_bound_index(root)
            real_parent = root / "real-receipts"
            real_parent.mkdir()
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                MODULE.run(
                    self.args(
                        index,
                        linked_parent / "receipt.json",
                        reviewed_public_receipts=receipts,
                    )
                )

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

    def test_create_receipt_fsyncs_file_and_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with mock.patch.object(
                MODULE.os,
                "fsync",
                wraps=MODULE.os.fsync,
            ) as fsync:
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "preflighting"},
                    create=True,
                )

            self.assertEqual(fsync.call_count, 2)

    def test_create_receipt_removes_partial_output_after_file_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "preflighting"},
                    create=True,
                )

            self.assertFalse(receipt.exists())

    def test_create_receipt_removes_partial_output_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "preflighting"},
                    create=True,
                )

            self.assertFalse(receipt.exists())

    def test_create_receipt_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            original_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                original_fsync_directory(parent)
                receipt.write_text(
                    json.dumps({"status": "tampered"}) + "\n",
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private output changed during write",
                ),
            ):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "preflighting"},
                    create=True,
                )

            self.assertFalse(receipt.exists())

    def test_replace_receipt_fsyncs_parent_after_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            MODULE.write_private_atomic(
                receipt,
                {"status": "preflighting"},
                create=True,
            )

            with mock.patch.object(
                MODULE,
                "fsync_directory",
                wraps=MODULE.fsync_directory,
            ) as fsync_directory:
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "dry_run"},
                    create=False,
                )

            fsync_directory.assert_called_once_with(receipt.parent)
            self.assertEqual(
                json.loads(receipt.read_text(encoding="utf-8")),
                {"status": "dry_run"},
            )

    def test_replace_receipt_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "receipt.json"
            MODULE.write_private_atomic(
                receipt,
                {"status": "preflighting"},
                create=True,
            )
            original_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                original_fsync_directory(parent)
                receipt.write_text(
                    json.dumps({"status": "tampered"}) + "\n",
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "private output changed during write",
                ),
            ):
                MODULE.write_private_atomic(
                    receipt,
                    {"status": "dry_run"},
                    create=False,
                )

            self.assertEqual(
                json.loads(receipt.read_text(encoding="utf-8")),
                {"status": "tampered"},
            )

    def test_rejects_index_with_stale_reviewed_public_receipt_binding_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["reviewed_public_receipts"][0]["sha256"] = "0" * 64
            index.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with (
                self.assertRaisesRegex(
                    ValueError,
                    "reviewed-public receipt binding",
                ),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "receipt.json",
                        reviewed_public_receipts=receipts,
                    )
                )

    def test_rejects_index_with_stale_reviewed_public_row_binding_before_aws(
        self,
    ) -> None:
        cases = (
            (
                lambda row: row["reviewed_public"].__setitem__(
                    "version_id",
                    "old-version-same-size",
                ),
                "binding is stale",
            ),
            (
                lambda row: row["reviewed_public"].__setitem__(
                    "sha256",
                    "0" * 64,
                ),
                "binding is stale",
            ),
            (
                lambda row: row.pop("reviewed_public"),
                "object envelope is not exact",
            ),
            (
                lambda row: row["reviewed_public"].__setitem__(
                    "sha256",
                    "A" * 64,
                ),
                "binding is stale",
            ),
            (
                lambda row: row["reviewed_public"].__setitem__(
                    "version_id",
                    True,
                ),
                "binding is stale",
            ),
        )
        for mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                index, receipts = self.write_receipt_bound_index(root)
                payload = json.loads(index.read_text(encoding="utf-8"))
                mutate(payload["objects"][0])
                index.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with (
                    self.assertRaisesRegex(ValueError, message),
                    mock.patch.object(
                        MODULE,
                        "aws_json",
                        side_effect=AssertionError("AWS called"),
                    ),
                ):
                    MODULE.run(
                        self.args(
                            index,
                            root / "receipt.json",
                            reviewed_public_receipts=receipts,
                        )
                    )

    def test_rejects_index_with_reviewed_public_object_drift_before_aws(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            index, receipts = self.write_receipt_bound_index(root)
            payload = json.loads(index.read_text(encoding="utf-8"))
            payload["objects"].pop(0)
            payload["object_count"] = len(payload["objects"])
            payload["total_size"] = sum(row["size"] for row in payload["objects"])
            index.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with (
                self.assertRaisesRegex(
                    RuntimeError,
                    "reviewed-public S3 state does not match publication receipts",
                ),
                mock.patch.object(
                    MODULE,
                    "aws_json",
                    side_effect=AssertionError("AWS called"),
                ),
            ):
                MODULE.run(
                    self.args(
                        index,
                        root / "receipt.json",
                        reviewed_public_receipts=receipts,
                    )
                )


if __name__ == "__main__":
    unittest.main()
