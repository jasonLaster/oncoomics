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
GENERATOR_SPEC = importlib.util.spec_from_file_location("generate_blocked_hrd_crosscheck_reports", GENERATOR_SCRIPT)
assert GENERATOR_SPEC and GENERATOR_SPEC.loader
GENERATOR = importlib.util.module_from_spec(GENERATOR_SPEC)
GENERATOR_SPEC.loader.exec_module(GENERATOR)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_private_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location("publish_private_report", PUBLISH_SCRIPT)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_source_report_manifest(path: Path, **updates: object) -> None:
    report = path.parent / "report.md"
    report.write_text("# Source report\n\nNo-call source packet.\n", encoding="utf-8")
    payload = {
        "schema_version": 1,
        "method_id": "rosalind_diana_wgs",
        "report_kind": "rosalind_hrd_reviewer_packet",
        "evidence_status": "partial_evidence",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "classification_qc_status": "not_applicable",
        "report_sha256": sha256(report),
        "review_summary": {
            "overall": {
                "evidence_status": "partial_evidence",
                "authorized_hrd_state": "no_call",
            },
        },
    }
    payload.update(updates)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
            self.assertEqual(fsync.call_count, 2)

            with self.assertRaises(FileExistsError):
                GENERATOR.write_file_create_only(output, b"second\n")
            self.assertEqual(output.read_bytes(), b"first\n")

    def test_packet_file_removes_partial_after_file_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.md"

            with (
                mock.patch.object(
                    GENERATOR.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                GENERATOR.write_file_create_only(output, b"first\n")

            self.assertFalse(output.exists())

    def test_packet_file_removes_partial_after_directory_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.md"

            with (
                mock.patch.object(
                    GENERATOR.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                GENERATOR.write_file_create_only(output, b"first\n")

            self.assertFalse(output.exists())

    def test_packet_file_rejects_symlinked_output_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = root / "stale.md"
            output = root / "report.md"
            stale.write_text("stale blocked packet\n", encoding="utf-8")
            output.symlink_to(stale)

            with self.assertRaisesRegex(
                ValueError,
                "blocked cross-check packet may not be a symlink",
            ):
                GENERATOR.write_file_create_only(output, b"first\n")

            self.assertEqual(
                stale.read_text(encoding="utf-8"),
                "stale blocked packet\n",
            )

    def test_packet_file_rejects_symlinked_parent_without_writing_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "real-parent"
            linked_parent = root / "linked-parent"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "blocked cross-check packet parent may not be a symlink",
            ):
                GENERATOR.write_file_create_only(
                    linked_parent / "report.md",
                    b"first\n",
                )

            self.assertFalse((real_parent / "report.md").exists())

    def test_packet_file_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report.md"
            real_fsync_directory = GENERATOR.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text("tampered blocked packet\n", encoding="utf-8")

            with (
                mock.patch.object(
                    GENERATOR,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "blocked cross-check packet changed during write",
                ),
            ):
                GENERATOR.write_file_create_only(output, b"first\n")

            self.assertFalse(output.exists())

    def test_packet_manifest_rejects_stale_report_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            target = output / GENERATOR.METHODS[0]["directory"]
            real_fsync_directory = GENERATOR.fsync_directory
            tampered = False

            def tamper_report_after_manifest_fsync(path: Path) -> None:
                nonlocal tampered
                real_fsync_directory(path)
                manifest = target / "report_manifest.json"
                if manifest.exists() and not tampered:
                    tampered = True
                    (target / "report.md").write_text(
                        "tampered blocked packet\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    GENERATOR,
                    "fsync_directory",
                    side_effect=tamper_report_after_manifest_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "blocked cross-check report manifest is stale for report.md",
                ),
            ):
                GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            self.assertTrue(tampered)
            self.assertFalse(output.exists())

    def test_packet_manifest_rejects_stale_method_spec_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            target = output / GENERATOR.METHODS[0]["directory"]
            real_fsync_directory = GENERATOR.fsync_directory
            tampered = False

            def tamper_spec_after_manifest_fsync(path: Path) -> None:
                nonlocal tampered
                real_fsync_directory(path)
                manifest = target / "report_manifest.json"
                if manifest.exists() and not tampered:
                    tampered = True
                    (target / "method_spec.json").write_text(
                        '{"tampered": true}\n',
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    GENERATOR,
                    "fsync_directory",
                    side_effect=tamper_spec_after_manifest_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "blocked cross-check report manifest is stale for method_spec.json",
                ),
            ):
                GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            self.assertTrue(tampered)
            self.assertFalse(output.exists())

    def test_generation_fsyncs_output_root_after_method_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"

            with mock.patch.object(
                GENERATOR,
                "fsync_directory",
                wraps=GENERATOR.fsync_directory,
            ) as fsync_directory:
                GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            self.assertIn(mock.call(output.resolve()), fsync_directory.mock_calls)

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
                manifest = json.loads((directory / "report_manifest.json").read_text(encoding="utf-8"))
                spec = json.loads((directory / "method_spec.json").read_text(encoding="utf-8"))

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

            serialized = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*.*"))
            for forbidden in ("E019", "DRF-", "Personalis", "Echo"):
                self.assertNotIn(forbidden.casefold(), serialized.casefold())

    def test_reports_bind_upstream_report_manifests_without_exposing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deterministic = root / "deterministic" / "report_manifest.json"
            rosalind = root / "rosalind" / "report_manifest.json"
            deterministic.parent.mkdir()
            rosalind.parent.mkdir()
            write_source_report_manifest(deterministic, method_id="deterministic_full_wgs")
            write_source_report_manifest(rosalind, method_id="rosalind_diana_wgs")
            output = root / "blocked"
            source_manifests = {
                "deterministic_full_wgs": sha256(deterministic),
                "rosalind_diana_wgs": sha256(rosalind),
            }

            GENERATOR.generate(
                output,
                "2026-07-17T00:00:00+00:00",
                run_id="diana-wgs-hrd-unit",
                source_report_manifests=GENERATOR.load_source_report_manifests(
                    [
                        f"deterministic_full_wgs={deterministic}",
                        f"rosalind_diana_wgs={rosalind}",
                    ]
                ),
            )

            for method in GENERATOR.METHODS:
                directory = output / method["directory"]
                report = (directory / "report.md").read_text(encoding="utf-8")
                manifest = json.loads((directory / "report_manifest.json").read_text(encoding="utf-8"))
                spec = json.loads((directory / "method_spec.json").read_text(encoding="utf-8"))

                self.assertIn("diana-wgs-hrd-unit", report)
                self.assertIn("deterministic_full_wgs report_manifest_sha256", report)
                self.assertIn("rosalind_diana_wgs report_manifest_sha256", report)
                self.assertEqual("diana-wgs-hrd-unit", manifest["run_id"])
                self.assertEqual(source_manifests, spec["source_report_manifests"])
                self.assertEqual(
                    {f"{method_id}_report_manifest": digest for method_id, digest in source_manifests.items()},
                    {key: digest for key, digest in manifest["source_sha256"].items() if key.endswith("_report_manifest")},
                )
                self.assertEqual(source_manifests, manifest["review_summary"]["source_report_manifests"])

            serialized = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*.*"))
            self.assertNotIn(str(root), serialized)

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

    def test_generation_cleans_created_method_directories_after_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            original_write = GENERATOR.write_file_create_only

            def fail_after_first_method(path: Path, data: bytes) -> None:
                if path.name == "method_spec.json" and path.parent.name == GENERATOR.METHODS[1]["directory"]:
                    path.write_text("partial blocked packet\n", encoding="utf-8")
                    raise OSError("synthetic blocked packet failure")
                original_write(path, data)

            with mock.patch.object(
                GENERATOR,
                "write_file_create_only",
                side_effect=fail_after_first_method,
            ):
                with self.assertRaisesRegex(OSError, "synthetic blocked packet failure"):
                    GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            self.assertFalse(output.exists())

    def test_generation_preserves_untracked_child_after_later_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            original_write = GENERATOR.write_file_create_only

            def fail_after_first_method(path: Path, data: bytes) -> None:
                if path.name == "method_spec.json" and path.parent.name == GENERATOR.METHODS[1]["directory"]:
                    (output / GENERATOR.METHODS[0]["directory"] / "unexpected.tmp").write_text(
                        "stray blocked packet file\n",
                        encoding="utf-8",
                    )
                    path.write_text("partial blocked packet\n", encoding="utf-8")
                    raise OSError("synthetic blocked packet failure")
                original_write(path, data)

            with mock.patch.object(
                GENERATOR,
                "write_file_create_only",
                side_effect=fail_after_first_method,
            ):
                with self.assertRaisesRegex(OSError, "synthetic blocked packet failure"):
                    GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            first = output / GENERATOR.METHODS[0]["directory"]
            second = output / GENERATOR.METHODS[1]["directory"]
            self.assertEqual(
                [path.name for path in first.iterdir()],
                ["unexpected.tmp"],
            )
            self.assertEqual(
                (first / "unexpected.tmp").read_text(encoding="utf-8"),
                "stray blocked packet file\n",
            )
            self.assertFalse(second.exists())

    def test_generation_cleans_created_method_directories_after_final_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            side_effects = [None for _ in range(len(GENERATOR.METHODS) * 3)]
            side_effects.append(OSError("synthetic output root fsync failure"))

            with (
                mock.patch.object(
                    GENERATOR,
                    "fsync_directory",
                    side_effect=side_effects,
                ),
                self.assertRaisesRegex(OSError, "synthetic output root fsync failure"),
            ):
                GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

            self.assertFalse(output.exists())

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

    def test_cli_rejects_malformed_source_report_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"

            with self.assertRaisesRegex(
                SystemExit,
                "source report manifests must use method_id=path",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--source-report-manifest",
                        "rosalind_diana_wgs",
                    ]
                )

            self.assertFalse(output.exists())

    def test_cli_rejects_mismatched_source_report_manifest_method(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mismatched = root / "mismatched.json"
            write_source_report_manifest(mismatched, method_id="deterministic_full_wgs")
            output = root / "blocked"

            with self.assertRaisesRegex(
                SystemExit,
                "source report manifest method_id does not match rosalind_diana_wgs",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--source-report-manifest",
                        f"rosalind_diana_wgs={mismatched}",
                    ]
                )

            self.assertFalse(output.exists())

    def test_cli_rejects_source_report_manifest_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source-real"
            source.mkdir()
            manifest = source / "report_manifest.json"
            write_source_report_manifest(manifest)
            linked_source = root / "source-link"
            linked_source.symlink_to(source, target_is_directory=True)
            output = root / "blocked"

            with self.assertRaisesRegex(
                SystemExit,
                "rosalind_diana_wgs source report manifest parent may not be a symlink",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--source-report-manifest",
                        f"rosalind_diana_wgs={linked_source / 'report_manifest.json'}",
                    ]
                )

            self.assertFalse(output.exists())

    def test_cli_rejects_classifying_source_report_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            classifying = root / "classifying.json"
            write_source_report_manifest(
                classifying,
                authorized_hrd_state="positive",
                classification_authorized=True,
            )
            output = root / "blocked"

            with self.assertRaisesRegex(
                SystemExit,
                "source report manifest must preserve no_call: rosalind_diana_wgs",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--source-report-manifest",
                        f"rosalind_diana_wgs={classifying}",
                    ]
                )

            self.assertFalse(output.exists())

    def test_cli_rejects_no_call_source_report_with_applicable_classification_qc(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            classified_qc = root / "classified-qc.json"
            write_source_report_manifest(
                classified_qc,
                classification_qc_status="passed",
            )
            output = root / "blocked"

            with self.assertRaisesRegex(
                SystemExit,
                "source report manifest classification QC must remain not_applicable: rosalind_diana_wgs",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--source-report-manifest",
                        f"rosalind_diana_wgs={classified_qc}",
                    ]
                )

            self.assertFalse(output.exists())

    def test_cli_rejects_unbound_source_report_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            unbound = root / "unbound.json"
            write_source_report_manifest(unbound, report_sha256="unbound")
            output = root / "blocked"

            with self.assertRaisesRegex(
                SystemExit,
                "source report manifest report_sha256 is malformed: rosalind_diana_wgs",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--source-report-manifest",
                        f"rosalind_diana_wgs={unbound}",
                    ]
                )

            self.assertFalse(output.exists())

    def test_cli_rejects_source_report_manifest_with_stale_report_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = root / "report_manifest.json"
            write_source_report_manifest(stale)
            (root / "report.md").write_text("# Mutated report\n", encoding="utf-8")
            output = root / "blocked"

            with self.assertRaisesRegex(
                SystemExit,
                "source report manifest hash differs from report.md: rosalind_diana_wgs",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--source-report-manifest",
                        f"rosalind_diana_wgs={stale}",
                    ]
                )

            self.assertFalse(output.exists())

    def test_rejects_output_below_symlinked_parent_without_writing_packets(
        self,
    ) -> None:
        self.assertFalse(GENERATOR.is_platform_root_alias(Path("blocked-link")))

        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                real_parent = root / "blocked-real"
                if nested == "existing":
                    (real_parent / nested).mkdir(parents=True)
                else:
                    real_parent.mkdir()
                linked_parent = root / "blocked-link"
                linked_parent.symlink_to(real_parent, target_is_directory=True)

                output = linked_parent / nested / "blocked"

                with self.assertRaisesRegex(
                    ValueError,
                    "blocked cross-check output parent may not be a symlink",
                ):
                    GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")

                self.assertFalse((real_parent / nested / "blocked").exists())

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
