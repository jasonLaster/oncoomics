from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2, sort_keys=True)
    current = f'  "{key}": {json.dumps(payload[key], sort_keys=True)}'
    description = f"top-level JSON field {key}"
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one {description}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


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
                "version_id": f"{relative}-version",
                "bytes": path.stat().st_size,
                "sha256": STAGE.sha256(path),
                "checks": dict(STAGE.EXPECTED_DOWNLOAD_OBJECT_CHECKS),
            }
        )
    write_json(
        verification,
        {
            "schema_version": 1,
            "status": "passed",
            "publication_receipt_sha256": "a" * 64,
            "publication_receipt_uri": "s3://diana-omics-private-results-unit/receipt.json",
            "route_output_uri": "s3://diana-omics-private-results-unit/route/",
            "expected_kms_key_arn": "arn:aws:kms:us-east-1:172630973301:key/unit",
            "live_history_checks": dict(STAGE.EXPECTED_DOWNLOAD_LIVE_HISTORY_CHECKS),
            "output_dir": str(source),
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
                "version_id": f"{path.name}-version",
                "bytes": path.stat().st_size,
                "sha256": STAGE.sha256(path),
                "checks": dict(STAGE.EXPECTED_DOWNLOAD_OBJECT_CHECKS),
            }
        )
    write_json(
        verification,
        {
            "schema_version": 1,
            "status": "passed",
            "publication_receipt_sha256": "a" * 64,
            "publication_receipt_uri": "s3://diana-omics-private-results-unit/receipt.json",
            "route_output_uri": "s3://diana-omics-private-results-unit/route/",
            "expected_kms_key_arn": "arn:aws:kms:us-east-1:172630973301:key/unit",
            "live_history_checks": dict(STAGE.EXPECTED_DOWNLOAD_LIVE_HISTORY_CHECKS),
            "output_dir": str(source),
            "object_count": len(rows),
            "objects": rows,
        },
    )


class StageHrdCrosscheckReportTests(unittest.TestCase):
    def test_schema_versions_are_exact_json_integers(self) -> None:
        for value in (True, 1.0, "1", 2, None):
            with self.subTest(value=value):
                self.assertFalse(
                    STAGE.exact_schema_version({"schema_version": value})
                )

        self.assertTrue(STAGE.exact_schema_version({"schema_version": 1}))

    def test_schema_guards_use_exact_integer_helper(self) -> None:
        source = STAGE_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(STAGE_SCRIPT))

        raw_comparisons = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "schema_version" not in segment:
                continue
            if segment in {
                'type(payload.get("schema_version")) is int',
                'payload["schema_version"] == expected',
            }:
                continue
            raw_comparisons.append(f"{node.lineno}: {segment}")

        self.assertEqual(raw_comparisons, [])

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

    def test_packet_file_install_rejects_symlinked_staged_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "source.txt"
            symlink_source = root / "source-link.txt"
            destination = root / "report.md"
            real_source.write_bytes(b"one\n")
            symlink_source.symlink_to(real_source)

            with self.assertRaisesRegex(ValueError, "staged cross-check packet"):
                STAGE.copy_create_only(symlink_source, destination)

            self.assertFalse(destination.exists())

    def test_packet_file_install_rejects_symlinked_destination_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            real_output = root / "real-output"
            linked_output = root / "linked-output"
            source.write_bytes(b"one\n")
            real_output.mkdir()
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "staged cross-check packet parent may not be a symlink",
            ):
                STAGE.copy_create_only(source, linked_output / "report.md")

            self.assertFalse((real_output / "report.md").exists())

    def test_packet_file_install_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "report.md"
            source.write_bytes(b"one\n")
            real_fsync_directory = STAGE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                destination.write_bytes(b"tampered packet\n")

            with (
                mock.patch.object(
                    STAGE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged cross-check packet changed during copy",
                ),
            ):
                STAGE.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

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
                STAGE.sha256(source_link)

            real_inputs = root / "real-inputs"
            real_inputs.mkdir()
            route_result = real_inputs / "route_result.json"
            route_result.write_text('{"route": "sigprofiler_sbs3"}\n', encoding="utf-8")
            linked_inputs = root / "linked-inputs"
            linked_inputs.symlink_to(real_inputs, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "route_result.json SHA-256 input parent may not be a symlink",
            ):
                STAGE.sha256(linked_inputs / "route_result.json")

    def test_sha256_rejects_hash_input_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.md"
            report.write_text("stable report\n", encoding="utf-8")
            original_sha256_file_once = STAGE.sha256_file_once
            mutated = False

            def mutate_after_first_hash(path: Path) -> str:
                nonlocal mutated
                digest = original_sha256_file_once(path)
                if path == report and not mutated:
                    mutated = True
                    path.write_text("rewritten report\n", encoding="utf-8")
                return digest

            with (
                mock.patch.object(
                    STAGE,
                    "sha256_file_once",
                    side_effect=mutate_after_first_hash,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report.md SHA-256 input changed during read",
                ),
            ):
                STAGE.sha256(report)

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

    def test_stage_binds_parsed_download_verification_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            output = root / "staged"
            verified_hash = STAGE.sha256(verification)
            tampered_hash = ""
            real_load = STAGE.load_json_with_sha256

            def tamper_after_parse(path: Path, label: str):
                nonlocal tampered_hash
                value, digest = real_load(path, label)
                if label == "download verification" and not tampered_hash:
                    payload = json.loads(verification.read_text(encoding="utf-8"))
                    payload["prior_error"] = "late local mutation"
                    write_json(verification, payload)
                    tampered_hash = STAGE.sha256(verification)
                return value, digest

            with mock.patch.object(
                STAGE,
                "load_json_with_sha256",
                side_effect=tamper_after_parse,
            ):
                STAGE.stage(source, verification, output, "sigprofiler_sbs3")

            manifest = json.loads((output / "report_manifest.json").read_text())
            method_spec = json.loads((output / "method_spec.json").read_text())
            self.assertEqual(
                manifest["source_sha256"]["download_verification"],
                verified_hash,
            )
            self.assertEqual(
                method_spec["download_verification_sha256"],
                verified_hash,
            )
            self.assertNotEqual(tampered_hash, verified_hash)

    def test_stage_rejects_loaded_json_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            original_sha256_file_once = STAGE.sha256_file_once
            mutated = False

            def mutate_before_stability_hash(path: Path) -> str:
                nonlocal mutated
                if path == verification and not mutated:
                    mutated = True
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["prior_error"] = "late local mutation"
                    write_json(path, payload)
                return original_sha256_file_once(path)

            with (
                mock.patch.object(
                    STAGE,
                    "sha256_file_once",
                    side_effect=mutate_before_stability_hash,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "download verification changed during read",
                ),
            ):
                STAGE.load_json_with_sha256(verification, "download verification")

    def test_stage_binds_parsed_source_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            _verification = write_route_report(source)
            verified_hash = STAGE.sha256(source / "report_manifest.json")
            tampered_hash = ""
            real_load = STAGE.load_json_with_sha256

            def tamper_after_parse(path: Path, label: str):
                nonlocal tampered_hash
                value, digest = real_load(path, label)
                if label == "route report manifest" and not tampered_hash:
                    payload = json.loads(
                        (source / "report_manifest.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    payload["review_summary"]["limitations"].append(
                        "late local mutation"
                    )
                    write_json(source / "report_manifest.json", payload)
                    tampered_hash = STAGE.sha256(source / "report_manifest.json")
                return value, digest

            with mock.patch.object(
                STAGE,
                "load_json_with_sha256",
                side_effect=tamper_after_parse,
            ):
                summary = STAGE.require_download_verification(
                    root / "download.verification.json",
                    source,
                    "sigprofiler_sbs3",
                )

            self.assertEqual(
                summary["source_report_manifest_sha256"],
                verified_hash,
            )
            self.assertNotIn(
                "late local mutation",
                summary["source_review_summary"]["limitations"],
            )
            self.assertNotEqual(tampered_hash, verified_hash)

    def test_stage_reuses_verified_source_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            output = root / "staged"
            real_require = STAGE.require_download_verification

            def tamper_after_verification(*args, **kwargs):
                summary = real_require(*args, **kwargs)
                staging = Path(args[1])
                manifest_path = staging / "report_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["review_summary"]["limitations"].append(
                    "late unverified staging mutation"
                )
                write_json(manifest_path, manifest)
                return summary

            with mock.patch.object(
                STAGE,
                "require_download_verification",
                side_effect=tamper_after_verification,
            ):
                STAGE.stage(source, verification, output, "sigprofiler_sbs3")

            manifest = json.loads((output / "report_manifest.json").read_text())
            method_spec = json.loads((output / "method_spec.json").read_text())
            self.assertNotIn(
                "late unverified staging mutation",
                manifest["review_summary"]["limitations"],
            )
            self.assertEqual(
                method_spec["source_review_summary"],
                manifest["review_summary"],
            )

    def test_stage_rejects_duplicate_download_verification_object_names(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            write_duplicate_json_field(verification, "status", "failed")

            with self.assertRaisesRegex(
                ValueError,
                "duplicate JSON object name in download verification: status",
            ):
                STAGE.stage(source, verification, root / "staged", "sigprofiler_sbs3")

            self.assertFalse((root / "staged").exists())

    def test_stage_rejects_duplicate_route_manifest_object_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            write_duplicate_json_field(
                source / "report_manifest.json",
                "route",
                "stale_route",
            )

            with self.assertRaisesRegex(
                ValueError,
                "duplicate JSON object name in route report manifest: route",
            ):
                STAGE.stage(source, verification, root / "staged", "sigprofiler_sbs3")

            self.assertFalse((root / "staged").exists())

    def test_stage_rehashes_method_spec_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            output = root / "staged"
            real_fsync_directory = STAGE.fsync_directory

            def tamper_method_spec_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                method_spec = path / "method_spec.json"
                if method_spec.exists():
                    method_spec.write_text('{"tampered": true}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    STAGE,
                    "fsync_directory",
                    side_effect=tamper_method_spec_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged cross-check JSON changed during write",
                ),
            ):
                STAGE.stage(source, verification, output, "sigprofiler_sbs3")

            self.assertFalse(output.exists())

    def test_stage_rehashes_report_manifest_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            output = root / "staged"
            real_fsync_directory = STAGE.fsync_directory
            calls = 0

            def tamper_report_manifest_after_parent_fsync(path: Path) -> None:
                nonlocal calls
                real_fsync_directory(path)
                if (path / "method_spec.json").exists():
                    calls += 1
                if calls == 2:
                    (path / "report_manifest.json").write_text(
                        '{"tampered": true}\n',
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    STAGE,
                    "fsync_directory",
                    side_effect=tamper_report_manifest_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged cross-check JSON changed during write",
                ),
            ):
                STAGE.stage(source, verification, output, "sigprofiler_sbs3")

            self.assertFalse(output.exists())

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

    def test_stage_rejects_missing_unexpected_or_failed_download_check_maps(
        self,
    ) -> None:
        cases = (
            (
                "missing live history check",
                lambda payload: payload["live_history_checks"].pop(
                    "all_versions_latest"
                ),
                "live history check map is not exact",
            ),
            (
                "unexpected live history check",
                lambda payload: payload["live_history_checks"].__setitem__(
                    "forged_extra",
                    True,
                ),
                "live history check map is not exact",
            ),
            (
                "failed live history check",
                lambda payload: payload["live_history_checks"].__setitem__(
                    "version_count_exact",
                    False,
                ),
                "live history check map is not exact",
            ),
            (
                "missing object check",
                lambda payload: payload["objects"][0]["checks"].pop(
                    "checksum_type_full_object"
                ),
                "object report.md check map is not exact",
            ),
            (
                "unexpected object check",
                lambda payload: payload["objects"][0]["checks"].__setitem__(
                    "forged_extra",
                    True,
                ),
                "object report.md check map is not exact",
            ),
            (
                "failed object check",
                lambda payload: payload["objects"][0]["checks"].__setitem__(
                    "exact_kms",
                    False,
                ),
                "object report.md check map is not exact",
            ),
        )
        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                payload = json.loads(verification.read_text(encoding="utf-8"))
                mutate(payload)
                write_json(verification, payload)

                with self.assertRaisesRegex(ValueError, message):
                    STAGE.stage(
                        source,
                        verification,
                        root / "staged",
                        "sigprofiler_sbs3",
                    )

                self.assertFalse((root / "staged").exists())

    def test_stage_rejects_inexact_download_verification_envelopes(self) -> None:
        cases = (
            (
                "verification",
                lambda payload: payload.__setitem__("legacy_note", "accepted"),
                "download verification envelope is not exact",
            ),
            (
                "float schema version",
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "download verification is not passed and exact",
            ),
            (
                "string object count",
                lambda payload: payload.__setitem__(
                    "object_count",
                    str(len(payload["objects"])),
                ),
                "download verification object_count",
            ),
            (
                "object",
                lambda payload: payload["objects"][0].__setitem__(
                    "legacy_note",
                    "accepted",
                ),
                "download verification object row is not exact",
            ),
        )
        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                payload = json.loads(verification.read_text(encoding="utf-8"))
                mutate(payload)
                write_json(verification, payload)

                with self.assertRaisesRegex(ValueError, message):
                    STAGE.stage(
                        source,
                        verification,
                        root / "staged",
                        "sigprofiler_sbs3",
                    )

                self.assertFalse((root / "staged").exists())

    def test_stage_rejects_coerced_download_verification_object_count(self) -> None:
        cases = (float, str, lambda value: True)
        for coerce in cases:
            with self.subTest(coerce=coerce), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                payload = json.loads(verification.read_text(encoding="utf-8"))
                payload["object_count"] = coerce(len(payload["objects"]))
                write_json(verification, payload)

                with self.assertRaisesRegex(
                    ValueError,
                    "download verification object_count",
                ):
                    STAGE.stage(
                        source,
                        verification,
                        root / "staged",
                        "sigprofiler_sbs3",
                    )

                self.assertFalse((root / "staged").exists())

    def test_stage_rejects_boolean_download_verification_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            support = source / "route_result.json"
            support.write_text("1", encoding="utf-8")
            manifest_path = source / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            support_hash = STAGE.sha256(support)
            manifest["support_sha256"] = {"route_result.json": support_hash}
            manifest["source_sha256"] = {"route_result.json": support_hash}
            write_json(manifest_path, manifest)
            refresh_download_verification(source, verification)
            payload = json.loads(verification.read_text(encoding="utf-8"))
            payload["objects"][2]["bytes"] = True
            write_json(verification, payload)

            with self.assertRaisesRegex(ValueError, "stale for support"):
                STAGE.stage(
                    source,
                    verification,
                    root / "staged",
                    "sigprofiler_sbs3",
                )

            self.assertFalse((root / "staged").exists())

    def test_stage_rejects_float_schema_source_report_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            manifest_path = source / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["schema_version"] = 1.0
            write_json(manifest_path, manifest)
            refresh_download_verification(source, verification)

            with self.assertRaisesRegex(
                ValueError,
                "route report manifest is not an approved no-call cross-check",
            ):
                STAGE.stage(
                    source,
                    verification,
                    root / "staged",
                    "sigprofiler_sbs3",
                )

            self.assertFalse((root / "staged").exists())

    def test_stage_rejects_download_verification_row_without_version_id(self) -> None:
        for value in ("", "null", "none", "space separated", True):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                payload = json.loads(verification.read_text(encoding="utf-8"))
                payload["objects"][0]["version_id"] = value
                write_json(verification, payload)

                with self.assertRaisesRegex(ValueError, "lacks a VersionId"):
                    STAGE.stage(
                        source,
                        verification,
                        root / "staged",
                        "sigprofiler_sbs3",
                    )

                self.assertFalse((root / "staged").exists())

    def test_stage_rejects_copy_that_differs_from_exact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            real_fsync_directory = STAGE.fsync_directory

            def tamper_report_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                report = path / "report.md"
                if report.exists() and not (path / "method_spec.json").exists():
                    report.write_text("mutated after validation\n", encoding="utf-8")

            with mock.patch.object(
                STAGE,
                "fsync_directory",
                side_effect=tamper_report_after_parent_fsync,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "exact route replay staging file changed during copy",
                ):
                    STAGE.stage(
                        source,
                        verification,
                        root / "staged",
                        "sigprofiler_sbs3",
                    )

    def test_stage_rejects_support_copy_that_differs_from_exact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            real_fsync_directory = STAGE.fsync_directory

            def tamper_support_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                support = path / "route_result.json"
                if support.exists() and not (path / "method_spec.json").exists():
                    support.write_text('{"mutated": true}\n', encoding="utf-8")

            with mock.patch.object(
                STAGE,
                "fsync_directory",
                side_effect=tamper_support_after_parent_fsync,
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "exact route replay staging file changed during copy",
                ):
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

    def test_stage_rejects_coerced_download_verification_hashes(self) -> None:
        digest = "1" * 64
        cases = (
            (
                "core",
                lambda payload: payload["objects"][0].__setitem__(
                    "sha256",
                    int(digest),
                ),
                "download verification report.md SHA-256",
            ),
            (
                "support",
                lambda payload: payload["objects"][2].__setitem__(
                    "sha256",
                    int(digest),
                ),
                "download verification support route_result.json SHA-256",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                manifest_path = source / "report_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["report_sha256"] = digest
                manifest["support_sha256"]["route_result.json"] = digest
                manifest["source_sha256"]["route_result.json"] = digest
                write_json(manifest_path, manifest)

                payload = json.loads(verification.read_text(encoding="utf-8"))
                for row in payload["objects"]:
                    row["sha256"] = digest
                mutate(payload)
                write_json(verification, payload)

                with (
                    mock.patch.object(STAGE, "sha256", return_value=digest),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    STAGE.require_download_verification(
                        verification,
                        source,
                        "sigprofiler_sbs3",
                    )

    def test_stage_rejects_coerced_route_manifest_hashes(self) -> None:
        digest = "1" * 64
        cases = (
            (
                "report",
                lambda manifest: manifest.__setitem__("report_sha256", int(digest)),
                "route report_sha256",
            ),
            (
                "support",
                lambda manifest: manifest["support_sha256"].__setitem__(
                    "route_result.json",
                    int(digest),
                ),
                "support_sha256.route_result.json",
            ),
            (
                "source",
                lambda manifest: manifest["source_sha256"].__setitem__(
                    "route_result.json",
                    int(digest),
                ),
                "source_sha256.route_result.json",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                manifest_path = source / "report_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["report_sha256"] = digest
                manifest["support_sha256"]["route_result.json"] = digest
                manifest["source_sha256"]["route_result.json"] = digest
                mutate(manifest)
                write_json(manifest_path, manifest)

                payload = json.loads(verification.read_text(encoding="utf-8"))
                for row in payload["objects"]:
                    row["bytes"] = (source / row["relative_path"]).stat().st_size
                    row["sha256"] = digest
                write_json(verification, payload)

                with (
                    mock.patch.object(STAGE, "sha256", return_value=digest),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    STAGE.require_download_verification(
                        verification,
                        source,
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
            verification_rows = []
            for relative in (
                "report.md",
                "report_manifest.json",
                "support/route_result.json",
            ):
                if relative == "support/route_result.json":
                    path = support
                else:
                    path = source / relative
                verification_rows.append(
                    {
                        "relative_path": relative,
                        "version_id": f"{relative}-version",
                        "bytes": path.stat().st_size,
                        "sha256": STAGE.sha256(path),
                        "checks": dict(STAGE.EXPECTED_DOWNLOAD_OBJECT_CHECKS),
                    }
                )

            write_json(
                verification,
                {
                    "schema_version": 1,
                    "status": "passed",
                    "publication_receipt_sha256": "a" * 64,
                    "publication_receipt_uri": (
                        "s3://diana-omics-private-results-unit/receipt.json"
                    ),
                    "route_output_uri": "s3://diana-omics-private-results-unit/route/",
                    "expected_kms_key_arn": (
                        "arn:aws:kms:us-east-1:172630973301:key/unit"
                    ),
                    "object_count": 3,
                    "live_history_checks": dict(
                        STAGE.EXPECTED_DOWNLOAD_LIVE_HISTORY_CHECKS
                    ),
                    "output_dir": str(source),
                    "objects": verification_rows,
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

    def test_stage_rejects_source_or_verification_below_symlinked_parent(
        self,
    ) -> None:
        cases = (
            ("source", "exact route replay"),
            ("verification", "download verification"),
        )

        for target, message in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                real_parent = root / "real-inputs"
                real_parent.mkdir()
                linked_parent = root / "linked-inputs"
                linked_parent.symlink_to(real_parent, target_is_directory=True)

                if target == "source":
                    shutil.copytree(source, real_parent / source.name)
                    source = linked_parent / source.name
                else:
                    shutil.copy2(
                        verification,
                        real_parent / verification.name,
                    )
                    verification = linked_parent / verification.name

                output = root / "staged"
                with self.assertRaisesRegex(
                    ValueError,
                    f"{message} parent may not be a symlink",
                ):
                    STAGE.stage(
                        source,
                        verification,
                        output,
                        "sigprofiler_sbs3",
                    )

                self.assertFalse(output.exists())

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

    def test_stage_rejects_stale_installed_report_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            staging = root / "staging"
            output = root / "staged"
            STAGE.stage(source, verification, staging, "sigprofiler_sbs3")

            manifest = json.loads(
                (staging / "report_manifest.json").read_text(encoding="utf-8")
            )
            manifest["support_sha256"]["method_spec.json"] = "0" * 64
            write_json(staging / "report_manifest.json", manifest)

            with self.assertRaisesRegex(
                ValueError,
                "staged cross-check report manifest hash differs for method_spec.json",
            ):
                STAGE.install_staged_packet(staging, output)

            self.assertFalse(output.exists())

    def test_stage_rejects_method_spec_source_hash_that_differs_from_manifest(
        self,
    ) -> None:
        cases = {
            "download_verification_sha256": "download_verification",
            "source_report_sha256": "source_report",
            "source_report_manifest_sha256": "source_report_manifest",
        }
        for method_field, source_key in cases.items():
            with self.subTest(method_field=method_field, source_key=source_key):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / "exact"
                    verification = write_route_report(source)
                    staging = root / "staging"
                    output = root / "staged"
                    STAGE.stage(source, verification, staging, "sigprofiler_sbs3")

                    method_spec_path = staging / "method_spec.json"
                    method_spec = json.loads(
                        method_spec_path.read_text(encoding="utf-8")
                    )
                    self.assertNotEqual(method_spec[method_field], "0" * 64)
                    method_spec[method_field] = "0" * 64
                    write_json(method_spec_path, method_spec)

                    manifest_path = staging / "report_manifest.json"
                    manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    self.assertNotEqual(
                        manifest["source_sha256"][source_key],
                        method_spec[method_field],
                    )
                    manifest["support_sha256"]["method_spec.json"] = STAGE.sha256(
                        method_spec_path
                    )
                    write_json(manifest_path, manifest)

                    with self.assertRaisesRegex(
                        ValueError,
                        "method spec source hashes differ from the manifest",
                    ):
                        STAGE.install_staged_packet(staging, output)

                    self.assertFalse(output.exists())

    def test_stage_rejects_non_exact_report_manifest_or_method_spec_envelope(
        self,
    ) -> None:
        cases = (
            (
                "report manifest schema",
                "report_manifest.json",
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "report manifest is not approved",
            ),
            (
                "method spec schema",
                "method_spec.json",
                lambda payload: payload.__setitem__("schema_version", 1.0),
                "method spec differs from the manifest",
            ),
            (
                "report manifest",
                "report_manifest.json",
                lambda payload: payload.__setitem__("legacy_note", "accepted"),
                "report manifest envelope is not exact",
            ),
            (
                "method spec",
                "method_spec.json",
                lambda payload: payload.__setitem__("legacy_note", "accepted"),
                "method spec envelope is not exact",
            ),
            (
                "method spec source object count bool",
                "method_spec.json",
                lambda payload: payload.__setitem__("source_object_count", True),
                "source_object_count is not an exact positive integer",
            ),
            (
                "method spec source object count float",
                "method_spec.json",
                lambda payload: payload.__setitem__("source_object_count", 3.0),
                "source_object_count is not an exact positive integer",
            ),
            (
                "method spec source object count string",
                "method_spec.json",
                lambda payload: payload.__setitem__("source_object_count", "3"),
                "source_object_count is not an exact positive integer",
            ),
            (
                "method spec source object count zero",
                "method_spec.json",
                lambda payload: payload.__setitem__("source_object_count", 0),
                "source_object_count is not an exact positive integer",
            ),
        )

        for label, relative, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "exact"
                verification = write_route_report(source)
                staging = root / "staging"
                output = root / "staged"
                STAGE.stage(source, verification, staging, "sigprofiler_sbs3")

                packet = staging / relative
                payload = json.loads(packet.read_text(encoding="utf-8"))
                mutate(payload)
                write_json(packet, payload)

                manifest_path = staging / "report_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["support_sha256"]["method_spec.json"] = STAGE.sha256(
                    staging / "method_spec.json"
                )
                write_json(manifest_path, manifest)

                with self.assertRaisesRegex(ValueError, message):
                    STAGE.install_staged_packet(staging, output)

                self.assertFalse(output.exists())

    def test_stage_rejects_method_spec_review_summary_that_differs_from_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            staging = root / "staging"
            output = root / "staged"
            STAGE.stage(source, verification, staging, "sigprofiler_sbs3")

            method_spec_path = staging / "method_spec.json"
            method_spec = json.loads(method_spec_path.read_text(encoding="utf-8"))
            method_spec["source_review_summary"] = {
                "stale": "review summary from another route"
            }
            write_json(method_spec_path, method_spec)

            manifest_path = staging / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["support_sha256"]["method_spec.json"] = STAGE.sha256(
                method_spec_path
            )
            write_json(manifest_path, manifest)

            with self.assertRaisesRegex(
                ValueError,
                "method spec differs from the manifest",
            ):
                STAGE.install_staged_packet(staging, output)

            self.assertFalse(output.exists())

    def test_stage_rehashes_packet_after_final_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "exact"
            verification = write_route_report(source)
            staging = root / "staging"
            output = root / "staged"
            STAGE.stage(source, verification, staging, "sigprofiler_sbs3")
            real_fsync_directory = STAGE.fsync_directory
            resolved_output = output.resolve()
            output_syncs = 0

            def tamper_method_spec_after_final_directory_fsync(path: Path) -> None:
                nonlocal output_syncs
                real_fsync_directory(path)
                if path.resolve() == resolved_output:
                    output_syncs += 1
                    if output_syncs == 4:
                        (path / "method_spec.json").write_text(
                            '{"tampered": true}\n',
                            encoding="utf-8",
                        )

            with (
                mock.patch.object(
                    STAGE,
                    "fsync_directory",
                    side_effect=tamper_method_spec_after_final_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged cross-check packet changed during install: method_spec.json",
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
