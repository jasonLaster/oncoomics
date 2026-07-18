from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
