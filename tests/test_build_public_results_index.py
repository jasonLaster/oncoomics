from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SCRIPT = SCRIPT_DIR / "build_public_results_index.py"
SPEC = importlib.util.spec_from_file_location("build_public_results_index", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_reviewed_public_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_reviewed_public_report", PUBLISH_SCRIPT
)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)


def write_public_receipts(root: Path) -> list[Path]:
    receipt_root = root / "receipts"
    receipt_root.mkdir()
    receipts = []
    for method_id in MODULE.REPORT_METHOD_IDS:
        contract = MODULE.METHOD_CONTRACTS[method_id]
        expected_files = tuple(sorted(contract["files"]))
        private_destination = (
            f"s3://{PUBLISH.PRIVATE_BUCKET}/runs/{PUBLISH.SUBJECT_ALIAS}/"
            f"{PUBLISH.RUN_ID}/reports/{method_id}/revisions/"
            f"{hashlib.sha256(method_id.encode()).hexdigest()}/"
        )
        private_prefix = private_destination.removeprefix(
            f"s3://{PUBLISH.PRIVATE_BUCKET}/"
        )
        receipt = {
            "schema_version": 1,
            "status": "passed",
            "apply": True,
            "method_id": method_id,
            "subject_alias": PUBLISH.SUBJECT_ALIAS,
            "run_id": PUBLISH.RUN_ID,
            "classification": PUBLISH.CLASSIFICATION,
            "destination_prefix": (
                f"s3://{MODULE.BUCKET}/"
                f"{PUBLISH.PUBLIC_ROOT}{contract['destination']}"
            ),
            "expected_files": list(expected_files),
            "checks": dict(MODULE.REVIEWED_PUBLIC_APPLY_CHECKS),
            "private_publication_receipt": {
                "path": str(receipt_root / f"{method_id}.private.json"),
                "sha256": hashlib.sha256(
                    f"private/{method_id}".encode()
                ).hexdigest(),
                "destination_prefix": private_destination,
            },
            "source_objects": [],
            "destination_objects": [],
        }
        for index, relative in enumerate(expected_files, 1):
            digest = hashlib.sha256(f"{method_id}/{relative}".encode()).hexdigest()
            private_key = f"{private_prefix}{relative}"
            key = f"{PUBLISH.PUBLIC_ROOT}{contract['destination']}{relative}"
            source_row = {
                "relative_path": relative,
                "bucket": PUBLISH.PRIVATE_BUCKET,
                "key": private_key,
                "version_id": f"{method_id}-private-version-{index}",
                "bytes": 100 + index,
                "sha256": digest,
                "checksum_sha256": PUBLISH.checksum_sha256(digest),
                "status": "passed",
                "checks": dict(PUBLISH.SOURCE_PREFLIGHT_CHECKS),
            }
            receipt["source_objects"].append(source_row)
            receipt["destination_objects"].append(
                {
                    "relative_path": relative,
                    "bucket": MODULE.BUCKET,
                    "key": key,
                    "uri": f"s3://{MODULE.BUCKET}/{key}",
                    "version_id": f"{method_id}-public-version-{index}",
                    "bytes": 100 + index,
                    "sha256": digest,
                    "checksum_sha256": PUBLISH.checksum_sha256(digest),
                    "server_side_encryption": "AES256",
                    "status": "passed",
                    "checks": dict(PUBLISH.PUBLIC_DESTINATION_OBJECT_CHECKS),
                }
            )
        path = receipt_root / f"{method_id}.json"
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        receipts.append(path)
    return receipts


def expected_public_objects(receipts: list[Path]) -> list[dict[str, object]]:
    objects = []
    for receipt in receipts:
        for row in json.loads(receipt.read_text(encoding="utf-8"))["destination_objects"]:
            objects.append(
                {
                    "key": row["key"],
                    "size": row["bytes"],
                    "last_modified": "2026-07-17T00:00:00Z",
                }
            )
    return sorted(objects, key=lambda row: str(row["key"]))


def expected_public_heads(receipts: list[Path]) -> dict[str, dict[str, object]]:
    heads = {}
    for receipt in receipts:
        for row in json.loads(receipt.read_text(encoding="utf-8"))["destination_objects"]:
            heads[row["key"]] = {
                "VersionId": row["version_id"],
                "ContentLength": row["bytes"],
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": row["checksum_sha256"],
                "ServerSideEncryption": "AES256",
                "Metadata": {
                    "classification": PUBLISH.CLASSIFICATION,
                    "sha256": row["sha256"],
                },
            }
    return heads


def expected_public_prefix_pages(receipts: list[Path]) -> list[list[dict[str, object]]]:
    objects = expected_public_objects(receipts)
    return [
        [row for row in objects if str(row["key"]).startswith(prefix)]
        for prefix in MODULE.PUBLIC_PREFIXES
    ]


def fake_reviewed_public_receipt_args(root: Path) -> list[str]:
    return ["--reviewed-public-receipt", str(root / "reviewed-public.json")]


class PublicIndexTests(unittest.TestCase):
    def test_diana_public_prefixes_are_exact_reviewed_report_destinations(self) -> None:
        expected = tuple(
            PUBLISH.PUBLIC_ROOT + str(contract["destination"])
            for contract in PUBLISH.METHOD_CONTRACTS.values()
        )

        self.assertEqual(MODULE.DIANA_HRD_PUBLIC_PREFIXES, expected)
        self.assertEqual(
            MODULE.PUBLIC_PREFIXES[: len(expected)],
            expected,
        )
        self.assertNotIn(PUBLISH.PUBLIC_ROOT, MODULE.PUBLIC_PREFIXES)
        self.assertFalse(
            any(
                (
                    PUBLISH.PUBLIC_ROOT + "unreviewed-scratch/report.md"
                ).startswith(prefix)
                for prefix in MODULE.PUBLIC_PREFIXES
            )
        )
        self.assertNotIn(f"runs/diana-hrd/{PUBLISH.RUN_ID}/", MODULE.PUBLIC_PREFIXES)

        for method_id, contract in PUBLISH.METHOD_CONTRACTS.items():
            with self.subTest(method_id=method_id):
                key = (
                    PUBLISH.PUBLIC_ROOT
                    + str(contract["destination"])
                    + "report.md"
                )

                self.assertTrue(
                    any(key.startswith(prefix) for prefix in MODULE.PUBLIC_PREFIXES)
                )
                self.assertFalse(
                    any(key.startswith(blocked) for blocked in MODULE.FORBIDDEN_PREFIXES)
                )

    def test_list_prefix_paginates_and_omits_directory_markers(self) -> None:
        pages = [
            {
                "IsTruncated": True,
                "NextContinuationToken": "page-2",
                "Contents": [
                    {
                        "Key": "runs/example/a.json",
                        "Size": 10,
                        "LastModified": "2026-07-17T00:00:00Z",
                    },
                    {
                        "Key": "runs/example/folder/",
                        "Size": 0,
                        "LastModified": "2026-07-17T00:00:01Z",
                    },
                ],
            },
            {
                "IsTruncated": False,
                "Contents": [
                    {
                        "Key": "runs/example/b.json",
                        "Size": 20,
                        "LastModified": "2026-07-17T00:00:02Z",
                    }
                ],
            },
        ]
        commands: list[list[str]] = []

        def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
            commands.append(command)
            return SimpleNamespace(stdout=json.dumps(pages.pop(0)))

        with mock.patch.object(MODULE.subprocess, "run", side_effect=fake_run):
            self.assertEqual(
                MODULE.list_prefix("runs/example/"),
                [
                    {
                        "key": "runs/example/a.json",
                        "size": 10,
                        "last_modified": "2026-07-17T00:00:00Z",
                    },
                    {
                        "key": "runs/example/b.json",
                        "size": 20,
                        "last_modified": "2026-07-17T00:00:02Z",
                    },
                ],
            )

        self.assertNotIn("--continuation-token", commands[0])
        self.assertEqual(commands[1][-2:], ["--continuation-token", "page-2"])

    def test_list_prefix_rejects_stuck_pagination(self) -> None:
        page = {
            "IsTruncated": True,
            "NextContinuationToken": "same-token",
            "Contents": [],
        }

        with mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=json.dumps(page)),
        ):
            with self.assertRaisesRegex(RuntimeError, "pagination did not advance"):
                MODULE.list_prefix("runs/example/")

    def test_list_prefix_rejects_private_or_out_of_prefix_objects(self) -> None:
        for key, message in (
            ("runs/private/object.json", "outside"),
            (
                "runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/object.json",
                "private",
            ),
        ):
            with self.subTest(key=key):
                page = {
                    "Contents": [
                        {
                            "Key": key,
                            "Size": 10,
                            "LastModified": "2026-07-17T00:00:00Z",
                        }
                    ]
                }
                with mock.patch.object(
                    MODULE.subprocess,
                    "run",
                    return_value=SimpleNamespace(stdout=json.dumps(page)),
                ):
                    with self.assertRaisesRegex(RuntimeError, message):
                        MODULE.list_prefix(
                            "runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/"
                            if message == "private"
                            else "runs/example/"
                        )

    def test_main_rejects_duplicate_keys_from_overlapping_public_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE,
            "PUBLIC_PREFIXES",
            ("runs/example/", "runs/example/nested/"),
        ), mock.patch.object(
            MODULE,
            "validate_reviewed_public_receipts",
            return_value=({}, []),
        ), mock.patch.object(
            MODULE,
            "list_prefix",
            side_effect=[
                [
                    {
                        "key": "runs/example/nested/report.md",
                        "size": 100,
                        "last_modified": "2026-07-17T00:00:00Z",
                    }
                ],
                [
                    {
                        "key": "runs/example/nested/report.md",
                        "size": 100,
                        "last_modified": "2026-07-17T00:00:00Z",
                    }
                ],
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "duplicate keys"):
                MODULE.main(
                    [
                        "--output",
                        str(Path(temporary) / "objects.json"),
                        *fake_reviewed_public_receipt_args(Path(temporary)),
                    ]
                )

    def test_main_writes_index_atomically_without_following_symlinks(self) -> None:
        objects = [
            {
                "key": MODULE.PUBLIC_PREFIXES[-1] + "report.md",
                "size": 100,
                "last_modified": "2026-07-17T00:00:00Z",
            }
        ]

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE,
            "validate_reviewed_public_receipts",
            return_value=({}, []),
        ), mock.patch.object(
            MODULE,
            "list_prefix",
            side_effect=[objects] + [[] for _ in MODULE.PUBLIC_PREFIXES[1:]],
        ) as list_prefix:
            root = Path(temporary)
            output = root / "objects.json"
            MODULE.main(
                [
                    "--output",
                    str(output),
                    *fake_reviewed_public_receipt_args(root),
                ]
            )

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["objects"], objects)
            self.assertEqual(payload["object_count"], 1)
            self.assertEqual(list_prefix.call_count, len(MODULE.PUBLIC_PREFIXES))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = root / "stale.json"
            symlink = root / "symlink.json"
            stale.write_text("do not overwrite\n", encoding="utf-8")
            symlink.symlink_to(stale)

            with self.assertRaisesRegex(FileExistsError, "already exists"):
                MODULE.write_index(symlink, {"objects": []})

            self.assertEqual(stale.read_text(encoding="utf-8"), "do not overwrite\n")

    def test_reviewed_public_receipts_must_be_passed_in_canonical_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = write_public_receipts(root)
            MODULE.validate_reviewed_public_receipts(receipts)

            with self.assertRaisesRegex(RuntimeError, "deterministic_full_wgs"):
                MODULE.validate_reviewed_public_receipts(list(reversed(receipts)))

            failed = json.loads(receipts[0].read_text(encoding="utf-8"))
            failed["status"] = "dry_run"
            receipts[0].write_text(json.dumps(failed), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "not exact"):
                MODULE.validate_reviewed_public_receipts(receipts)

    def test_reviewed_public_receipts_reject_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = write_public_receipts(root)
            real_parent = root / "real-receipts"
            (root / "receipts").rename(real_parent)
            (root / "receipts").symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "parent may not be a symlink"):
                MODULE.validate_reviewed_public_receipts(receipts)

    def test_reviewed_public_receipts_require_full_source_preflight_checks(
        self,
    ) -> None:
        newly_bound_checks = (
            "source_exact_kms",
            "manifest_no_call_boundary",
            "destination_initially_empty",
            "packet_size_bounded",
        )

        for check_id in newly_bound_checks:
            with self.subTest(check_id=check_id), tempfile.TemporaryDirectory() as temporary:
                receipts = write_public_receipts(Path(temporary))
                receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
                self.assertTrue(receipt["checks"].pop(check_id))
                receipts[0].write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    RuntimeError,
                    "failed required checks",
                ):
                    MODULE.validate_reviewed_public_receipts(receipts)

    def test_reviewed_public_receipts_reject_extra_final_apply_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts = write_public_receipts(Path(temporary))
            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            receipt["checks"]["unexpected_late_check"] = True
            receipts[0].write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "failed required checks"):
                MODULE.validate_reviewed_public_receipts(receipts)

    def test_reviewed_public_destination_rows_must_be_exact(self) -> None:
        cases = (
            (
                lambda row: row.update({"relative_path": "raw.fastq.gz"}),
                "not exact",
            ),
            (
                lambda row: row.update({"version_id": "null"}),
                "not exact",
            ),
            (
                lambda row: row.update({"checksum_sha256": "not-the-checksum"}),
                "not exact",
            ),
            (
                lambda row: row.update({"server_side_encryption": "aws:kms"}),
                "not exact",
            ),
            (
                lambda row: row.update({"checks": {"checksum_sha256": False}}),
                "not exact",
            ),
            (
                lambda row: row.update({"checks": {"version_exact": True}}),
                "not exact",
            ),
            (
                lambda row: row["checks"].update({"unexpected_late_check": True}),
                "not exact",
            ),
        )

        for mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                receipts = write_public_receipts(Path(temporary))
                receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
                mutate(receipt["destination_objects"][0])
                receipts[0].write_text(json.dumps(receipt), encoding="utf-8")

                with self.assertRaisesRegex(RuntimeError, message):
                    MODULE.validate_reviewed_public_receipts(receipts)

    def test_reviewed_public_receipt_binding_hashes_current_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts = write_public_receipts(Path(temporary))
            _, original_binding = MODULE.validate_reviewed_public_receipts(receipts)

            receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
            receipt["extra_review_note"] = "hash-current-receipt-bytes"
            receipts[0].write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            _, updated_binding = MODULE.validate_reviewed_public_receipts(receipts)

        self.assertNotEqual(original_binding[0]["sha256"], updated_binding[0]["sha256"])
        self.assertEqual(original_binding[0]["method_id"], updated_binding[0]["method_id"])

    def test_reviewed_public_receipts_must_bind_source_objects(self) -> None:
        cases = (
            (
                lambda receipt: receipt.update(
                    {
                        "private_publication_receipt": {
                            "sha256": "0" * 64,
                            "destination_prefix": "s3://wrong/",
                        }
                    }
                ),
                "private receipt is not exact",
            ),
            (
                lambda receipt: receipt["source_objects"][0].update(
                    {"relative_path": "raw.fastq.gz"}
                ),
                "source object is not exact",
            ),
            (
                lambda receipt: receipt["source_objects"][0].update(
                    {"checks": {"exact_version_head": False}}
                ),
                "source object is not exact",
            ),
            (
                lambda receipt: receipt["source_objects"][0].update(
                    {"version_id": "null"}
                ),
                "source object is not exact",
            ),
            (
                lambda receipt: receipt["destination_objects"][0].update(
                    {
                        "sha256": "0" * 64,
                        "checksum_sha256": PUBLISH.checksum_sha256("0" * 64),
                    }
                ),
                "destination object is not source-bound",
            ),
        )

        for mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                receipts = write_public_receipts(Path(temporary))
                receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
                mutate(receipt)
                receipts[0].write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(RuntimeError, message):
                    MODULE.validate_reviewed_public_receipts(receipts)

    def test_main_can_bind_index_build_to_reviewed_public_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = write_public_receipts(root)
            output = root / "objects.json"

            with mock.patch.object(
                MODULE,
                "list_prefix",
                side_effect=expected_public_prefix_pages(receipts),
            ) as list_prefix, mock.patch.object(
                MODULE,
                "head_object",
                side_effect=expected_public_heads(receipts).__getitem__,
            ):
                argv = ["--output", str(output)]
                for receipt in receipts:
                    argv.extend(["--reviewed-public-receipt", str(receipt)])
                MODULE.main(argv)

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["objects"], expected_public_objects(receipts))
            self.assertEqual(payload["object_count"], len(expected_public_objects(receipts)))
            self.assertEqual(
                [row["method_id"] for row in payload["reviewed_public_receipts"]],
                list(MODULE.REPORT_METHOD_IDS),
            )
            for row, receipt in zip(payload["reviewed_public_receipts"], receipts):
                self.assertEqual(row["sha256"], MODULE.sha256(receipt))
            self.assertEqual(list_prefix.call_count, len(MODULE.PUBLIC_PREFIXES))

    def test_main_requires_reviewed_public_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "objects.json"

            with (
                self.assertRaises(SystemExit) as raised,
                mock.patch("sys.stderr", new=io.StringIO()),
            ):
                MODULE.main(["--output", str(output)])

            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(output.exists())

    def test_main_rejects_reviewed_public_state_that_differs_from_receipts(self) -> None:
        cases = (
            (
                lambda pages: pages[0].pop(),
                "missing",
            ),
            (
                lambda pages: pages[0].append(
                    {
                        "key": MODULE.PUBLIC_PREFIXES[0] + "unexpected.json",
                        "size": 1,
                        "last_modified": "2026-07-17T00:00:00Z",
                    }
                ),
                "unexpected",
            ),
            (
                lambda pages: pages[0][0].update({"size": int(pages[0][0]["size"]) + 1}),
                "size_mismatches",
            ),
        )

        for mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                receipts = write_public_receipts(root)
                pages = expected_public_prefix_pages(receipts)
                mutate(pages)
                argv = ["--output", str(root / "objects.json")]
                for receipt in receipts:
                    argv.extend(["--reviewed-public-receipt", str(receipt)])

                with mock.patch.object(MODULE, "list_prefix", side_effect=pages):
                    with self.assertRaisesRegex(RuntimeError, message):
                        MODULE.main(argv)

    def test_main_rejects_current_reviewed_public_object_version_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = write_public_receipts(root)
            pages = expected_public_prefix_pages(receipts)
            heads = expected_public_heads(receipts)
            stale_key = str(pages[0][0]["key"])
            heads[stale_key] = {
                **heads[stale_key],
                "VersionId": "unexpected-overwrite",
                "ChecksumSHA256": PUBLISH.checksum_sha256("0" * 64),
                "Metadata": {
                    "classification": PUBLISH.CLASSIFICATION,
                    "sha256": "0" * 64,
                },
            }
            argv = ["--output", str(root / "objects.json")]
            for receipt in receipts:
                argv.extend(["--reviewed-public-receipt", str(receipt)])

            with mock.patch.object(
                MODULE,
                "list_prefix",
                side_effect=pages,
            ), mock.patch.object(
                MODULE,
                "head_object",
                side_effect=heads.__getitem__,
            ):
                with self.assertRaisesRegex(RuntimeError, "current reviewed-public"):
                    MODULE.main(argv)

    def test_write_index_fsyncs_file_and_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "objects.json"

            with mock.patch.object(
                MODULE.os,
                "fsync",
                wraps=MODULE.os.fsync,
            ) as fsync:
                MODULE.write_index(output, {"objects": []})

            self.assertEqual(fsync.call_count, 2)

    def test_write_index_refuses_to_replace_old_index_before_io(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "objects.json"
            output.write_text("preserve\n", encoding="utf-8")

            with (
                mock.patch.object(
                    MODULE.os,
                    "fsync",
                    side_effect=AssertionError("fsync should not run"),
                ) as fsync,
                self.assertRaisesRegex(FileExistsError, "already exists"),
            ):
                MODULE.write_index(output, {"objects": []})

            fsync.assert_not_called()
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve\n")
            self.assertEqual(list(root.glob(".objects.json.*")), [])

    def test_main_rejects_existing_output_before_s3_listing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "objects.json"
            output.write_text("preserve\n", encoding="utf-8")
            receipts = write_public_receipts(root)
            argv = ["--output", str(output)]
            for receipt in receipts:
                argv.extend(["--reviewed-public-receipt", str(receipt)])

            with (
                mock.patch.object(
                    MODULE,
                    "list_prefix",
                    side_effect=AssertionError("S3 should not be listed"),
                ) as list_prefix,
                self.assertRaisesRegex(FileExistsError, "already exists"),
            ):
                MODULE.main(argv)

            list_prefix.assert_not_called()
            self.assertEqual(output.read_text(encoding="utf-8"), "preserve\n")

    def test_write_index_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "objects.json"
            original_fsync_directory = MODULE.fsync_directory

            def tamper_after_parent_fsync(parent: Path) -> None:
                original_fsync_directory(parent)
                output.write_text(
                    json.dumps({"objects": [{"key": "tampered"}]}) + "\n",
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    MODULE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "public index output changed during write",
                ),
            ):
                MODULE.write_index(output, {"objects": []})

            self.assertFalse(output.exists())

    def test_write_index_rejects_symlinked_parent_without_writing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-index"
            real_parent.mkdir()
            linked_parent = root / "linked-index"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "symlinked parent"):
                MODULE.write_index(linked_parent / "objects.json", {"objects": []})

            self.assertFalse((real_parent / "objects.json").exists())

    def test_write_index_rejects_output_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-index"
            real_parent.mkdir()
            linked_parent = root / "linked-index"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "symlinked parent"):
                MODULE.write_index(
                    linked_parent / "missing" / "objects.json",
                    {"objects": []},
                )

            self.assertFalse((real_parent / "missing").exists())

    def test_write_index_rejects_existing_dir_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-index"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "linked-index"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(RuntimeError, "symlinked parent"):
                MODULE.write_index(
                    linked_parent / "existing" / "objects.json",
                    {"objects": []},
                )

            self.assertFalse((real_parent / "existing" / "objects.json").exists())


if __name__ == "__main__":
    unittest.main()
