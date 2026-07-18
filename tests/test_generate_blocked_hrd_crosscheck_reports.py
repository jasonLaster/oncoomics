from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

GENERATOR_SCRIPT = SCRIPT_DIR / "generate_blocked_hrd_crosscheck_reports.py"
GENERATOR_SPEC = importlib.util.spec_from_file_location(
    "generate_blocked_hrd_crosscheck_reports", GENERATOR_SCRIPT
)
assert GENERATOR_SPEC and GENERATOR_SPEC.loader
GENERATOR = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(GENERATOR)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_private_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_private_report", PUBLISH_SCRIPT
)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GenerateBlockedHrdCrosscheckReportsTests(unittest.TestCase):
    def test_packet_files_are_create_only_fsynced_public_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.md"
            with mock.patch.object(
                GENERATOR.os,
                "fsync",
                wraps=GENERATOR.os.fsync,
            ) as fsync:
                GENERATOR.write_file_create_only(output, b"first\n")

            self.assertEqual(output.read_bytes(), b"first\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o644)
            self.assertEqual(fsync.call_count, 1)

            with self.assertRaises(FileExistsError):
                GENERATOR.write_file_create_only(output, b"second\n")
            self.assertEqual(output.read_bytes(), b"first\n")

    def test_reports_preserve_blocked_no_call_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            generated = GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            self.assertEqual(len(generated), 9)
            for method in GENERATOR.METHODS:
                directory = output / method["directory"]
                self.assertEqual(
                    sorted(path.name for path in directory.iterdir()),
                    ["method_spec.json", "report.md", "report_manifest.json"],
                )

                report = (directory / "report.md").read_text(encoding="utf-8")
                manifest = json.loads(
                    (directory / "report_manifest.json").read_text(encoding="utf-8")
                )
                spec = json.loads(
                    (directory / "method_spec.json").read_text(encoding="utf-8")
                )

                self.assertIn("## Intended computation — not executed", report)
                self.assertIn("## Exact prerequisites", report)
                self.assertIn("## Current blockers", report)
                self.assertIn("## Next gate", report)
                self.assertIn("No patient result exists", report)
                self.assertEqual(manifest["method_id"], method["method_id"])
                self.assertEqual(spec["method_id"], method["method_id"])
                self.assertEqual(manifest["evidence_status"], "blocked")
                self.assertEqual(manifest["authorized_hrd_state"], "no_call")
                self.assertFalse(manifest["classification_authorized"])
                self.assertEqual(
                    manifest["review_summary"]["readiness"]["execution_status"],
                    "not_run",
                )
                self.assertEqual(manifest["report_sha256"], sha256(directory / "report.md"))
                self.assertEqual(
                    manifest["support_sha256"],
                    {"method_spec.json": sha256(directory / "method_spec.json")},
                )

            serialized = "\n".join(
                path.read_text(encoding="utf-8") for path in output.rglob("*.*")
            )
            for forbidden in ("E019", "DRF-", "Personalis", "Echo"):
                self.assertNotIn(forbidden.casefold(), serialized.casefold())

    def test_generation_is_reproducible_with_fixed_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            second = root / "second"

            GENERATOR.generate(first, "2026-07-17T00:00:00+00:00")
            GENERATOR.generate(second, "2026-07-17T00:00:00+00:00")

            first_files = sorted(path.relative_to(first) for path in first.rglob("*.*"))
            second_files = sorted(path.relative_to(second) for path in second.rglob("*.*"))
            self.assertEqual(first_files, second_files)
            for relative in first_files:
                self.assertEqual((first / relative).read_bytes(), (second / relative).read_bytes())

    def test_generation_refuses_existing_method_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            existing = output / GENERATOR.METHODS[0]["directory"]
            existing.mkdir(parents=True)
            (existing / "unexpected.txt").write_text("stale\n", encoding="utf-8")

            with self.assertRaisesRegex(
                FileExistsError,
                "blocked cross-check output already exists",
            ):
                GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            self.assertEqual(
                sorted(path.name for path in existing.iterdir()),
                ["unexpected.txt"],
            )

    def test_generation_preflights_all_method_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            existing = output / GENERATOR.METHODS[-1]["directory"]
            existing.mkdir(parents=True)
            (existing / "unexpected.txt").write_text("stale\n", encoding="utf-8")

            with self.assertRaisesRegex(
                FileExistsError,
                "blocked cross-check output already exists",
            ):
                GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            for method in GENERATOR.METHODS[:-1]:
                self.assertFalse((output / method["directory"]).exists())

    def test_cli_rejects_symlinked_output_without_writing_packets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "blocked"
            real_output = root / "blocked-real"
            output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(
                SystemExit,
                "blocked cross-check output may not be a symlink",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--generated-at",
                        "2026-07-17T00:00:00+00:00",
                    ]
                )

            self.assertFalse(real_output.exists())

    def test_generated_packets_match_private_publication_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            for method in GENERATOR.METHODS:
                method_id = method["method_id"]
                self.assertEqual(
                    tuple(sorted(PUBLISH.METHOD_CONTRACTS[method_id]["files"])),
                    ("method_spec.json", "report.md", "report_manifest.json"),
                )
                rows = PUBLISH.validate_packet_dir(
                    output / method["directory"],
                    method_id,
                    ("E019", "DRF-", "Personalis", "Echo"),
                )
                self.assertEqual(
                    [row["relative_path"] for row in rows],
                    sorted(PUBLISH.METHOD_CONTRACTS[method_id]["files"]),
                )


if __name__ == "__main__":
    unittest.main()
