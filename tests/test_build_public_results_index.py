from __future__ import annotations

import hashlib
import importlib.util
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
    required_checks = {
        "private_receipt_exact_and_passed": True,
        "source_exact_versions": True,
        "source_sha256_and_bytes": True,
        "second_forbidden_token_scan": True,
        "all_destination_writes_create_only": True,
        "destination_sse_s3": True,
        "destination_full_object_sha256": True,
        "destination_non_null_versions": True,
        "destination_exact_one_version_no_delete_history": True,
    }
    for method_id in MODULE.REPORT_METHOD_IDS:
        contract = MODULE.METHOD_CONTRACTS[method_id]
        expected_files = tuple(sorted(contract["files"]))
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
            "checks": required_checks,
            "destination_objects": [],
        }
        for index, relative in enumerate(expected_files, 1):
            digest = hashlib.sha256(f"{method_id}/{relative}".encode()).hexdigest()
            key = f"{PUBLISH.PUBLIC_ROOT}{contract['destination']}{relative}"
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
                    "checks": {
                        "version_exact": True,
                        "bytes_exact": True,
                        "checksum_sha256": True,
                    },
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


def expected_public_prefix_pages(receipts: list[Path]) -> list[list[dict[str, object]]]:
    objects = expected_public_objects(receipts)
    return [
        [row for row in objects if str(row["key"]).startswith(prefix)]
        for prefix in MODULE.PUBLIC_PREFIXES
    ]


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
                MODULE.main(["--output", str(Path(temporary) / "objects.json")])

    def test_main_writes_index_atomically_without_following_symlinks(self) -> None:
        objects = [
            {
                "key": MODULE.PUBLIC_PREFIXES[0] + "report.md",
                "size": 100,
                "last_modified": "2026-07-17T00:00:00Z",
            }
        ]

        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(
            MODULE,
            "list_prefix",
            side_effect=[objects] + [[] for _ in MODULE.PUBLIC_PREFIXES[1:]],
        ) as list_prefix:
            root = Path(temporary)
            output = root / "objects.json"
            stale = root / "stale.json"
            symlink = root / "symlink.json"

            output.write_text("stale\n", encoding="utf-8")
            MODULE.main(["--output", str(output)])

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

            with self.assertRaisesRegex(RuntimeError, "through symlink"):
                MODULE.write_index(symlink, {"objects": []})

            self.assertEqual(stale.read_text(encoding="utf-8"), "do not overwrite\n")

    def test_reviewed_public_receipts_must_be_passed_in_canonical_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipts = write_public_receipts(Path(temporary))
            MODULE.validate_reviewed_public_receipts(receipts)

            with self.assertRaisesRegex(RuntimeError, "deterministic_full_wgs"):
                MODULE.validate_reviewed_public_receipts(list(reversed(receipts)))

            failed = json.loads(receipts[0].read_text(encoding="utf-8"))
            failed["status"] = "dry_run"
            receipts[0].write_text(json.dumps(failed), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "not exact"):
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
        )

        for mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                receipts = write_public_receipts(Path(temporary))
                receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
                mutate(receipt["destination_objects"][0])
                receipts[0].write_text(json.dumps(receipt), encoding="utf-8")

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
            ) as list_prefix:
                argv = ["--output", str(output)]
                for receipt in receipts:
                    argv.extend(["--reviewed-public-receipt", str(receipt)])
                MODULE.main(argv)

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["objects"], expected_public_objects(receipts))
            self.assertEqual(payload["object_count"], len(expected_public_objects(receipts)))
            self.assertEqual(list_prefix.call_count, len(MODULE.PUBLIC_PREFIXES))

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
