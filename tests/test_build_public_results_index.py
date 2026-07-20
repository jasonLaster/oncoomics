from __future__ import annotations

import ast
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
            "generated_at_utc": "2026-07-18T00:00:00+00:00",
            "apply": True,
            "method_id": method_id,
            "subject_alias": PUBLISH.SUBJECT_ALIAS,
            "run_id": PUBLISH.RUN_ID,
            "classification": PUBLISH.CLASSIFICATION,
            "script_sha256": PUBLISH.sha256(PUBLISH_SCRIPT),
            "destination_prefix": (
                f"s3://{MODULE.BUCKET}/"
                f"{PUBLISH.PUBLIC_ROOT}{contract['destination']}"
            ),
            "expected_files": list(expected_files),
            "forbidden_token_count": 1,
            "forbidden_token_sha256": ["f" * 64],
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
            "destination_initial_history_count": 0,
            "dry_run_receipt": {
                "path": str(receipt_root / f"{method_id}.dry-run.json"),
                "sha256": hashlib.sha256(
                    f"dry-run/{method_id}".encode()
                ).hexdigest(),
                "method_id": method_id,
                "status": "dry_run",
            },
            "destination_final_history_count": len(expected_files),
            "completed_at_utc": "2026-07-18T00:01:00+00:00",
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
                    "reviewed_public": {
                        "version_id": row["version_id"],
                        "sha256": row["sha256"],
                        "checksum_sha256": row["checksum_sha256"],
                    },
                }
            )
    return sorted(objects, key=lambda row: str(row["key"]))


def public_listing_objects(receipts: list[Path]) -> list[dict[str, object]]:
    objects = expected_public_objects(receipts)
    return [
        {
            "key": row["key"],
            "size": row["size"],
            "last_modified": row["last_modified"],
        }
        for row in objects
    ]


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
    objects = public_listing_objects(receipts)
    return [
        [row for row in objects if str(row["key"]).startswith(prefix)]
        for prefix in MODULE.PUBLIC_PREFIXES
    ]


def fake_reviewed_public_receipt_args(root: Path) -> list[str]:
    return ["--reviewed-public-receipt", str(root / "reviewed-public.json")]


class PublicIndexTests(unittest.TestCase):
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

    def test_runtime_type_aliases_are_python39_safe(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(SCRIPT))

        unsafe_aliases = []
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id.endswith("Object")
                    and any(
                        isinstance(child, ast.BinOp)
                        and isinstance(child.op, ast.BitOr)
                        for child in ast.walk(node.value)
                    )
                ):
                    unsafe_aliases.append(target.id)

        self.assertEqual(unsafe_aliases, [])

    def test_sha256_rejects_symlinked_hash_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "real-source.txt"
            real_source.write_text("real source\n", encoding="utf-8")
            source_link = root / "source-link.txt"
            source_link.symlink_to(real_source)

            with self.assertRaisesRegex(
                RuntimeError,
                "source-link.txt SHA-256 input must be a real file",
            ):
                MODULE.sha256(source_link)

            real_inputs = root / "real-inputs"
            real_inputs.mkdir()
            receipt = real_inputs / "reviewed-public.json"
            receipt.write_text(
                '{"status": "passed"}\n',
                encoding="utf-8",
            )
            linked_inputs = root / "linked-inputs"
            linked_inputs.symlink_to(real_inputs, target_is_directory=True)

            with self.assertRaisesRegex(
                RuntimeError,
                "reviewed-public.json SHA-256 input parent may not be a symlink",
            ):
                MODULE.sha256(linked_inputs / "reviewed-public.json")

    def test_sha256_rejects_inputs_that_change_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "reviewed-public.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            real_sha256_bytes = MODULE.sha256_bytes

            def tamper_after_initial_read(data: bytes) -> str:
                digest = real_sha256_bytes(data)
                receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")
                return digest

            with (
                mock.patch.object(
                    MODULE,
                    "sha256_bytes",
                    side_effect=tamper_after_initial_read,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "reviewed-public.json SHA-256 input changed during read",
                ),
            ):
                MODULE.sha256(receipt)

    def test_sha256_rejects_same_byte_leaf_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = root / "reviewed-public.json"
            replacement = root / "replacement-reviewed-public.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            replacement.write_text('{"status":"passed"}\n', encoding="utf-8")
            real_read_once = MODULE.read_real_input_file_once
            swapped = False

            def replace_after_initial_read(path: Path, label: str):
                nonlocal swapped
                data = real_read_once(path, label)
                if path == receipt and not swapped:
                    swapped = True
                    replacement.replace(receipt)
                return data

            with (
                mock.patch.object(
                    MODULE,
                    "read_real_input_file_once",
                    side_effect=replace_after_initial_read,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "reviewed-public.json SHA-256 input changed during read",
                ),
            ):
                MODULE.sha256(receipt)

            self.assertTrue(swapped)

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

    def test_list_prefix_rejects_malformed_pagination_token(self) -> None:
        page = {
            "IsTruncated": True,
            "NextContinuationToken": True,
            "Contents": [],
        }

        with mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=json.dumps(page)),
        ):
            with self.assertRaisesRegex(RuntimeError, "malformed pagination token"):
                MODULE.list_prefix("runs/example/")

    def test_list_prefix_rejects_non_exact_object_size(self) -> None:
        page = {
            "IsTruncated": False,
            "Contents": [
                {
                    "Key": "runs/example/one-byte.json",
                    "Size": True,
                    "LastModified": "2026-07-17T00:00:00Z",
                }
            ],
        }

        with mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=json.dumps(page)),
        ):
            with self.assertRaisesRegex(RuntimeError, "malformed object size"):
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

    def test_reviewed_public_receipt_binding_uses_loaded_digest_after_symlink(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = write_public_receipts(root)
            expected_sha256 = MODULE.sha256(receipts[0])
            real_load_json_object_with_sha256 = MODULE.load_json_object_with_sha256
            swapped = False

            def swap_receipt_after_stable_load(
                path: Path, label: str
            ) -> tuple[dict, str]:
                nonlocal swapped
                receipt, digest = real_load_json_object_with_sha256(path, label)
                if not swapped:
                    moved = root / "reviewed-public.real.json"
                    path.rename(moved)
                    path.symlink_to(moved)
                    swapped = True
                return receipt, digest

            with mock.patch.object(
                MODULE,
                "load_json_object_with_sha256",
                side_effect=swap_receipt_after_stable_load,
            ):
                _, receipt_binding = MODULE.validate_reviewed_public_receipts(
                    receipts
                )

            self.assertTrue(swapped)
            self.assertEqual(receipt_binding[0]["sha256"], expected_sha256)

    def test_reviewed_public_receipts_reject_invalid_json_objects(self) -> None:
        cases = (
            (
                "duplicate.json",
                '{"status":"passed","status":"passed"}\n',
                "duplicate JSON object name",
            ),
            (
                "array.json",
                '["not", "an", "object"]\n',
                "must be a JSON object",
            ),
            (
                "invalid.json",
                '{"status":\n',
                "invalid JSON",
            ),
        )
        for filename, text, message in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                receipt = Path(temporary) / filename
                receipt.write_text(text, encoding="utf-8")

                with self.assertRaisesRegex(RuntimeError, message):
                    MODULE.load_json_object(receipt, "reviewed-public receipt")

    def test_reviewed_public_receipts_reject_json_that_changes_during_read(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt = Path(temporary) / "reviewed-public.json"
            receipt.write_text('{"status":"passed"}\n', encoding="utf-8")
            real_sha256_bytes = MODULE.sha256_bytes

            def tamper_after_initial_read(data: bytes) -> str:
                digest = real_sha256_bytes(data)
                receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")
                return digest

            with (
                mock.patch.object(
                    MODULE,
                    "sha256_bytes",
                    side_effect=tamper_after_initial_read,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "reviewed-public receipt changed during read",
                ),
            ):
                MODULE.load_json_object(receipt, "reviewed-public receipt")

    def test_reviewed_public_receipt_binding_uses_loaded_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipts = write_public_receipts(root)
            expected_sha256 = MODULE.sha256(receipts[0])
            real_load_json_object_with_sha256 = MODULE.load_json_object_with_sha256
            swapped = False

            def swap_receipt_after_stable_load(
                path: Path, label: str
            ) -> tuple[dict, str]:
                nonlocal swapped
                receipt, digest = real_load_json_object_with_sha256(path, label)
                if not swapped:
                    path.write_text(
                        '{"status":"tampered"}\n',
                        encoding="utf-8",
                    )
                    swapped = True
                return receipt, digest

            with mock.patch.object(
                MODULE,
                "load_json_object_with_sha256",
                side_effect=swap_receipt_after_stable_load,
            ):
                _, receipt_binding = MODULE.validate_reviewed_public_receipts(
                    receipts
                )

            self.assertTrue(swapped)
            self.assertEqual(receipt_binding[0]["sha256"], expected_sha256)
            self.assertNotEqual(MODULE.sha256(receipts[0]), expected_sha256)

    def test_reviewed_public_receipts_require_full_source_preflight_checks(
        self,
    ) -> None:
        newly_bound_checks = (
            "source_exact_kms",
            "manifest_no_call_boundary",
            "source_report_kind_exact",
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
        cases = (
            (
                "unexpected-late-check",
                lambda receipt: receipt["checks"].__setitem__(
                    "unexpected_late_check",
                    True,
                ),
            ),
            (
                "truthy-integer-check",
                lambda receipt: receipt["checks"].__setitem__(
                    "destination_sse_s3",
                    1,
                ),
            )
        )

        for name, mutate in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                receipts = write_public_receipts(Path(temporary))
                receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
                mutate(receipt)
                receipts[0].write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(RuntimeError, "failed required checks"):
                    MODULE.validate_reviewed_public_receipts(receipts)

    def test_reviewed_public_receipts_require_exact_apply_envelope(self) -> None:
        cases = (
            (
                lambda receipt: receipt.update({"legacy_apply_receipt": True}),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt.pop("dry_run_receipt"),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt.__setitem__("schema_version", 1.0),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt["dry_run_receipt"].update(
                    {"method_id": "ai_review_reviewer_b"}
                ),
                "reviewed-public dry-run receipt is not exact",
            ),
            (
                lambda receipt: receipt["dry_run_receipt"].update({"path": True}),
                "reviewed-public dry-run receipt is not exact",
            ),
            (
                lambda receipt: receipt["dry_run_receipt"].update(
                    {"path": " dry-run.json"}
                ),
                "reviewed-public dry-run receipt is not exact",
            ),
            (
                lambda receipt: receipt["private_publication_receipt"].update(
                    {"legacy_destination": "s3://old-bucket/old-prefix/"}
                ),
                "reviewed-public private receipt is not exact",
            ),
            (
                lambda receipt: receipt["private_publication_receipt"].update(
                    {"path": False}
                ),
                "reviewed-public private receipt is not exact",
            ),
            (
                lambda receipt: receipt["private_publication_receipt"].update(
                    {"path": "private.json\n"}
                ),
                "reviewed-public private receipt is not exact",
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

    def test_reviewed_public_receipt_integer_fields_must_be_exact(self) -> None:
        cases = (
            (
                lambda receipt: receipt.update({"forbidden_token_count": True}),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt.update(
                    {"destination_initial_history_count": False}
                ),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt.update(
                    {"destination_initial_history_count": 0.0}
                ),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt.update(
                    {
                        "destination_final_history_count": float(
                            len(receipt["expected_files"])
                        )
                    }
                ),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt.update(
                    {
                        "destination_final_history_count": str(
                            len(receipt["expected_files"])
                        )
                    }
                ),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt["source_objects"][0].update({"bytes": True}),
                "reviewed-public source object is not exact",
            ),
            (
                lambda receipt: receipt["destination_objects"][0].update(
                    {"bytes": True}
                ),
                "reviewed-public destination object is not exact",
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

    def test_reviewed_public_receipt_hashes_must_be_exact_strings(self) -> None:
        numeric_digest = int("1" * 64)
        digest = "1" * 64
        checksum = PUBLISH.checksum_sha256(digest)
        cases = (
            (
                lambda receipt: receipt.update({"script_sha256": numeric_digest}),
                "reviewed-public receipt is not exact",
            ),
            (
                lambda receipt: receipt["dry_run_receipt"].update(
                    {"sha256": numeric_digest}
                ),
                "reviewed-public dry-run receipt is not exact",
            ),
            (
                lambda receipt: receipt["private_publication_receipt"].update(
                    {"sha256": numeric_digest}
                ),
                "reviewed-public private receipt is not exact",
            ),
            (
                lambda receipt: receipt["source_objects"][0].update(
                    {"sha256": numeric_digest, "checksum_sha256": checksum}
                ),
                "reviewed-public source object is not exact",
            ),
            (
                lambda receipt: (
                    receipt["source_objects"][0].update(
                        {"sha256": digest, "checksum_sha256": checksum}
                    ),
                    receipt["destination_objects"][0].update(
                        {"sha256": numeric_digest, "checksum_sha256": checksum}
                    ),
                ),
                "reviewed-public destination object is not exact",
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

    def test_reviewed_public_destination_rows_must_be_exact(self) -> None:
        cases = (
            (
                lambda row: row.update({"relative_path": "raw.fastq.gz"}),
                "not exact",
            ),
            (
                lambda row: row.update({"version_id": 1234567890}),
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
                lambda row: row["checks"].update({"version_exact": 1}),
                "not exact",
            ),
            (
                lambda row: row["checks"].update({"unexpected_late_check": True}),
                "not exact",
            ),
            (
                lambda row: row.update({"legacy_etag": "abc123"}),
                "destination object is incomplete",
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
            receipt["completed_at_utc"] = "2026-07-18T00:02:00+00:00"
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
                lambda receipt: receipt["source_objects"][0]["checks"].update(
                    {"exact_version_head": 1.0}
                ),
                "source object is not exact",
            ),
            (
                lambda receipt: receipt["source_objects"][0].update(
                    {"version_id": 1234567890}
                ),
                "source object is not exact",
            ),
            (
                lambda receipt: receipt["source_objects"][0].update(
                    {"legacy_checksum": "multipart-etag"}
                ),
                "source object is incomplete",
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
                set(payload["objects"][0]["reviewed_public"]),
                {"version_id", "sha256", "checksum_sha256"},
            )
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

    def test_reviewed_public_s3_state_size_must_be_exact_int(self) -> None:
        key = MODULE.DIANA_HRD_PUBLIC_PREFIXES[0] + "one-byte.json"
        with self.assertRaisesRegex(RuntimeError, "size_mismatches"):
            MODULE.validate_reviewed_public_s3_state(
                [
                    {
                        "key": key,
                        "size": True,
                        "last_modified": "2026-07-17T00:00:00Z",
                    }
                ],
                {key: {"bytes": 1}},
            )

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

    def test_current_reviewed_public_content_length_must_be_exact_int(self) -> None:
        key = MODULE.DIANA_HRD_PUBLIC_PREFIXES[0] + "one-byte.json"
        sha = "a" * 64
        expected = {
            key: {
                "version_id": "public-version-1",
                "bytes": 1,
                "sha256": sha,
                "checksum_sha256": MODULE.checksum_sha256(sha),
            }
        }

        def head_current(observed_key: str) -> dict[str, object]:
            self.assertEqual(observed_key, key)
            return {
                "VersionId": "public-version-1",
                "ContentLength": True,
                "ChecksumType": "FULL_OBJECT",
                "ChecksumSHA256": MODULE.checksum_sha256(sha),
                "ServerSideEncryption": "AES256",
                "Metadata": {
                    "classification": PUBLISH.CLASSIFICATION,
                    "sha256": sha,
                },
            }

        with self.assertRaisesRegex(RuntimeError, "current reviewed-public"):
            MODULE.validate_reviewed_public_current_versions(
                expected,
                head_current=head_current,
            )

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
