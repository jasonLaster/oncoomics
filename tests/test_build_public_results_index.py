from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/build_public_results_index.py"
SPEC = importlib.util.spec_from_file_location("build_public_results_index", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicIndexTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
