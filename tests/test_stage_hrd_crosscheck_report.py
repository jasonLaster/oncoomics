from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

STAGE_SCRIPT = SCRIPT_DIR / "stage_hrd_crosscheck_report.py"
STAGE_SPEC = importlib.util.spec_from_file_location(
    "stage_hrd_crosscheck_report", STAGE_SCRIPT
)
assert STAGE_SPEC and STAGE_SPEC.loader
STAGE = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(STAGE)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_private_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_private_report", PUBLISH_SCRIPT
)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_route_report(source: Path, route: str = "sigprofiler_sbs3") -> Path:
    source.mkdir()
    report = source / "report.md"
    support = source / "route_result.json"
    report.write_text("# SigProfiler SBS3\n\nAuthorized HRD state: `no_call`\n")
    write_json(support, {"route": route, "sbs3": {"activity": 3}})
    manifest = {
        "schema_version": 1,
        "method_id": route,
        "report_kind": route,
        "route": route,
        "evidence_status": "partial_evidence",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "classification_qc_status": "not_applicable",
        "review_summary": {
            "evidence_scope": route,
            "readiness": {"authorized_hrd_state": "no_call"},
            "observations": {"sbs3_activity": 3},
            "limitations": ["No threshold is locked."],
        },
        "source_sha256": {"route_result.json": STAGE.sha256(support)},
        "support_sha256": {"route_result.json": STAGE.sha256(support)},
        "report_sha256": STAGE.sha256(report),
    }
    write_json(source / "report_manifest.json", manifest)
    verification = source.parent / "download.verification.json"
    rows = []
    for relative in ("report.md", "report_manifest.json", "route_result.json"):
        path = source / relative
        rows.append(
            {
                "relative_path": relative,
                "bytes": path.stat().st_size,
                "sha256": STAGE.sha256(path),
            }
        )
    write_json(
        verification,
        {
            "schema_version": 1,
            "status": "passed",
            "object_count": len(rows),
            "objects": rows,
        },
    )
    return verification


def refresh_download_verification(source: Path, verification: Path) -> None:
    rows = []
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        rows.append(
            {
                "relative_path": path.name,
                "bytes": path.stat().st_size,
                "sha256": STAGE.sha256(path),
            }
        )
    write_json(
        verification,
        {
            "schema_version": 1,
            "status": "passed",
            "object_count": len(rows),
            "objects": rows,
        },
    )


class StageHrdCrosscheckReportTests(unittest.TestCase):
    def test_packet_file_install_is_create_only_and_fsynced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with mock.patch.object(
                STAGE.os,
                "fsync",
                wraps=STAGE.os.fsync,
            ) as fsync:
                STAGE.copy_create_only(source, destination)

            self.assertEqual(destination.read_bytes(), b"one\n")
            self.assertEqual(fsync.call_count, 2)

            source.write_bytes(b"two\n")
            with self.assertRaisesRegex(
                ValueError,
                "staged cross-check packet already exists",
            ):
                STAGE.copy_create_only(source, destination)

            self.assertEqual(destination.read_bytes(), b"one\n")

    def test_packet_file_install_removes_partial_after_file_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with (
                mock.patch.object(
                    STAGE.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                STAGE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_packet_file_install_removes_partial_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")

            with (
                mock.patch.object(
                    STAGE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                STAGE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_stage_compacts_route_tree_and_remains_publishable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            output = root / "staged"

            STAGE.stage(source, verification, output, "sigprofiler_sbs3")

            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                ["method_spec.json", "report.md", "report_manifest.json"],
            )
            manifest = json.loads((output / "report_manifest.json").read_text())
            self.assertEqual(manifest["method_id"], "sigprofiler_sbs3")
            self.assertEqual(
                manifest["source_sha256"]["source_report_manifest"],
                STAGE.sha256(source / "report_manifest.json"),
            )

            rows = PUBLISH.validate_packet_dir(
                output, "sigprofiler_sbs3", ("E019", "DRF-", "Personalis", "Echo")
            )
            self.assertEqual(
                [row["relative_path"] for row in rows],
                sorted(PUBLISH.METHOD_CONTRACTS["sigprofiler_sbs3"]["files"]),
            )

    def test_stage_rejects_stale_download_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            (source / "report.md").write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "stale"):
                STAGE.stage(
                    source,
                    verification,
                    root / "staged",
                    "sigprofiler_sbs3",
                )

    def test_stage_rejects_copy_that_differs_from_exact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            real_copy = STAGE.shutil.copyfile

            def copy_with_mutated_report(source_path: Path, destination: Path) -> None:
                real_copy(source_path, destination)
                if destination.name == "report.md":
                    destination.write_text("mutated after validation\n", encoding="utf-8")

            with mock.patch.object(
                STAGE.shutil,
                "copyfile",
                side_effect=copy_with_mutated_report,
            ):
                with self.assertRaisesRegex(ValueError, "stale for report.md"):
                    STAGE.stage(
                        source,
                        verification,
                        root / "staged",
                        "sigprofiler_sbs3",
                    )

    def test_stage_rejects_route_manifest_that_does_not_bind_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            manifest_path = source / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = "0" * 64
            write_json(manifest_path, manifest)
            refresh_download_verification(source, verification)

            with self.assertRaisesRegex(ValueError, "manifest hash differs"):
                STAGE.stage(
                    source,
                    verification,
                    root / "staged",
                    "sigprofiler_sbs3",
                )

    def test_stage_rejects_route_manifest_that_does_not_bind_support(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)

            write_json(
                source / "route_result.json",
                {"route": "sigprofiler_sbs3", "sbs3": {"activity": 99}},
            )
            refresh_download_verification(source, verification)

            with self.assertRaisesRegex(ValueError, "support hash differs"):
                STAGE.stage(
                    source,
                    verification,
                    root / "staged",
                    "sigprofiler_sbs3",
                )

    def test_stage_rejects_unexpected_download_verification_object(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            (source / "stale.vcf").write_text("stale route output\n", encoding="utf-8")
            refresh_download_verification(source, verification)

            with self.assertRaisesRegex(ValueError, "inventory is not exact"):
                STAGE.stage(
                    source,
                    verification,
                    root / "staged",
                    "sigprofiler_sbs3",
                )

    def test_stage_rejects_support_file_behind_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            support = root / "outside/route_result.json"
            support.parent.mkdir()
            shutil.move(str(source / "route_result.json"), support)
            (source / "support").symlink_to(support.parent, target_is_directory=True)

            manifest_path = source / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            support_hash = STAGE.sha256(support)
            manifest["support_sha256"] = {"support/route_result.json": support_hash}
            manifest["source_sha256"] = {"support/route_result.json": support_hash}
            write_json(manifest_path, manifest)
            write_json(
                verification,
                {
                    "schema_version": 1,
                    "status": "passed",
                    "object_count": 3,
                    "objects": [
                        {
                            "relative_path": relative,
                            "bytes": (source / relative).stat().st_size,
                            "sha256": STAGE.sha256(source / relative),
                        }
                        for relative in (
                            "report.md",
                            "report_manifest.json",
                            "support/route_result.json",
                        )
                    ],
                },
            )

            with self.assertRaisesRegex(ValueError, "symlink"):
                STAGE.stage(
                    source,
                    verification,
                    root / "staged",
                    "sigprofiler_sbs3",
                )

    def test_stage_rejects_wrong_route_and_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source, "sequenza_scarhrd")

            with self.assertRaisesRegex(ValueError, "approved no-call"):
                STAGE.stage(
                    source,
                    verification,
                    root / "staged",
                    "sigprofiler_sbs3",
                )

            output = root / "exists"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "output already exists"):
                STAGE.stage(source, verification, output, "sequenza_scarhrd")

    def test_stage_rejects_symlinked_source_or_output(self) -> None:
        cases = ("source", "output")

        for target in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                output = root / "staged"

                if target == "source":
                    real_source = root / "exact-real"
                    source.rename(real_source)
                    source.symlink_to(real_source, target_is_directory=True)
                    message = "exact route replay"
                else:
                    output.symlink_to(
                        root / "staged-real",
                        target_is_directory=True,
                    )
                    message = "output may not be a symlink"

                with self.assertRaisesRegex(ValueError, message):
                    STAGE.stage(source, verification, output, "sigprofiler_sbs3")

                self.assertFalse((root / "staged-real").exists())

    def test_stage_rejects_output_below_symlinked_parent(self) -> None:
        self.assertFalse(STAGE.is_platform_root_alias(Path("staged-linked-parent")))

        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                real_parent = root / "staged-real-parent"
                if nested == "existing":
                    (real_parent / nested).mkdir(parents=True)
                else:
                    real_parent.mkdir()
                linked_parent = root / "staged-linked-parent"
                linked_parent.symlink_to(real_parent, target_is_directory=True)

                with self.assertRaisesRegex(ValueError, "output parent may not be a symlink"):
                    STAGE.stage(
                        source,
                        verification,
                        linked_parent / nested / "staged",
                        "sigprofiler_sbs3",
                    )

                self.assertFalse((real_parent / nested / "staged").exists())

    def test_stage_cleans_current_attempt_after_install_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            output = root / "staged"
            copied: list[str] = []
            real_copy = STAGE.copy_create_only

            def fail_after_first_copy(source_path: Path, destination: Path) -> None:
                if copied:
                    raise ValueError("synthetic install failure")
                real_copy(source_path, destination)
                copied.append(destination.name)

            with mock.patch.object(
                STAGE,
                "copy_create_only",
                side_effect=fail_after_first_copy,
            ):
                with self.assertRaisesRegex(ValueError, "synthetic install failure"):
                    STAGE.stage(source, verification, output, "sigprofiler_sbs3")

            self.assertEqual(copied, ["method_spec.json"])
            self.assertFalse(output.exists())

    def test_stage_preserves_unexpected_child_after_install_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            output = root / "staged"

            def fail_with_untracked_child(
                source_path: Path, destination: Path
            ) -> None:
                (destination.parent / "unexpected.tmp").write_text(
                    "partial write\n",
                    encoding="utf-8",
                )
                raise ValueError("synthetic untracked install failure")

            with mock.patch.object(
                STAGE,
                "copy_create_only",
                side_effect=fail_with_untracked_child,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "synthetic untracked install failure",
                ):
                    STAGE.stage(source, verification, output, "sigprofiler_sbs3")

            self.assertEqual(
                [path.name for path in output.iterdir()],
                ["unexpected.tmp"],
            )
            self.assertEqual(
                (output / "unexpected.tmp").read_text(encoding="utf-8"),
                "partial write\n",
            )

    def test_stage_cleans_output_after_final_directory_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "staged"
            staging.mkdir()
            for name in ("method_spec.json", "report.md", "report_manifest.json"):
                path = staging / name
                path.write_text(f"{name}\n", encoding="utf-8")

            with (
                mock.patch.object(
                    STAGE,
                    "fsync_directory",
                    side_effect=(
                        None,
                        None,
                        None,
                        OSError("synthetic packet directory fsync failure"),
                    ),
                ),
                self.assertRaisesRegex(
                    OSError,
                    "synthetic packet directory fsync failure",
                ),
            ):
                STAGE.install_staged_packet(staging, output)

            self.assertFalse(output.exists())

    def test_stage_rejects_output_inside_exact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)

            with self.assertRaisesRegex(ValueError, "output must be separate"):
                STAGE.stage(
                    source,
                    verification,
                    source / "staged",
                    "sequenza_scarhrd",
                )


if __name__ == "__main__":
    unittest.main()
