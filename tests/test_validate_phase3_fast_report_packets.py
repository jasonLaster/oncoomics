from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

VALIDATOR_SCRIPT = SCRIPT_DIR / "validate_phase3_fast_report_packets.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location("validate_phase3_fast_report_packets", VALIDATOR_SCRIPT)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_reviewed_public_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location("publish_reviewed_public_report", PUBLISH_SCRIPT)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_packet(directory: Path, method_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in PUBLISH.METHOD_CONTRACTS[method_id]["files"]:
        if name == "report_manifest.json":
            continue
        suffix = Path(name).suffix
        if suffix == ".json":
            payload = {"schema_version": 1, "method_id": method_id, "file": name}
            directory.joinpath(name).write_text(
                json.dumps(payload, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            directory.joinpath(name).write_text(
                f"{method_id},{name},no_call\n",
                encoding="utf-8",
            )

    source_report_manifests = {
        "deterministic_full_wgs": "b" * 64,
        "rosalind_diana_wgs": "c" * 64,
    }
    if method_id.endswith("_blocked"):
        method_spec_path = directory / "method_spec.json"
        method_spec = json.loads(method_spec_path.read_text(encoding="utf-8"))
        method_spec.update(
            {
                "source_report_binding_scope": "pre_route_deterministic_rosalind",
                "source_report_manifests": source_report_manifests,
            }
        )
        method_spec_path.write_text(
            json.dumps(method_spec, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    support_names = set(PUBLISH.METHOD_CONTRACTS[method_id]["files"]) - {
        "report.md",
        "report_manifest.json",
    }
    manifest = {
        "schema_version": 1,
        "method_id": method_id,
        "report_kind": "unit_test_packet",
        "evidence_status": "blocked" if method_id.endswith("_blocked") else "partial_evidence",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "classification_qc_status": "not_applicable",
        **(
            {
                "source_report_binding_scope": "pre_route_deterministic_rosalind",
            }
            if method_id.endswith("_blocked")
            else {}
        ),
        "source_sha256": (
            {
                "generator": sha256(SCRIPT_DIR / "generate_blocked_hrd_crosscheck_reports.py"),
                **{
                    f"{source_id}_report_manifest": digest
                    for source_id, digest in source_report_manifests.items()
                },
            }
            if method_id.endswith("_blocked")
            else {"unit_source": "a" * 64}
        ),
        "support_sha256": {name: sha256(directory / name) for name in sorted(support_names)},
        "report_sha256": sha256(directory / "report.md"),
        "review_summary": {
            **(
                {
                    "source_report_binding_scope": "pre_route_deterministic_rosalind",
                    "source_report_manifests": source_report_manifests,
                }
                if method_id.endswith("_blocked")
                else {}
            ),
            "overall": {
                "authorized_hrd_state": "no_call",
            }
        },
    }
    directory.joinpath("report_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class ValidatePhase3FastReportPacketsTests(unittest.TestCase):
    def test_schema_versions_are_exact_json_integers(self) -> None:
        for value in (True, 1.0, "1", 2, None):
            with self.subTest(value=value):
                self.assertFalse(
                    VALIDATOR.exact_schema_version({"schema_version": value})
                )

        self.assertTrue(VALIDATOR.exact_schema_version({"schema_version": 1}))

    def test_schema_guards_use_exact_integer_helper(self) -> None:
        source = VALIDATOR_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(VALIDATOR_SCRIPT))

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

    def write_phase3_fast_packets(self, root: Path) -> dict[str, Path]:
        packet_dirs = {
            "deterministic_full_wgs": root / "deterministic_full_wgs",
            "rosalind_diana_wgs": root / "rosalind_diana_wgs",
            "facets_scarhrd_blocked": root / "facets_scarhrd_blocked",
            "oncoanalyser_chord_blocked": root / "oncoanalyser_chord_blocked",
            "hrdetect_blocked": root / "hrdetect_blocked",
        }
        for method_id, directory in packet_dirs.items():
            write_packet(directory, method_id)
        return packet_dirs

    def test_validates_all_five_phase3_fast_report_packets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "manifests" / "report_packet_validation.json"
            self.write_phase3_fast_packets(root)

            receipt = VALIDATOR.run(
                argparse.Namespace(
                    **{
                        "deterministic_report_dir": root / "deterministic_full_wgs",
                        "rosalind_report_dir": root / "rosalind_diana_wgs",
                        "facets_scarhrd_report_dir": root / "facets_scarhrd_blocked",
                        "oncoanalyser_chord_report_dir": root / "oncoanalyser_chord_blocked",
                        "hrdetect_report_dir": root / "hrdetect_blocked",
                        "forbidden_tokens_json": json.dumps(["Run-Private-Token"]),
                        "output": output,
                    }
                )
            )

            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(receipt, written)
            self.assertEqual(written["status"], "passed")
            self.assertEqual(written["validated_packet_count"], 5)
            self.assertEqual(written["run_forbidden_token_count"], 1)
            self.assertGreaterEqual(written["static_forbidden_token_count"], 4)
            self.assertEqual(
                [
                    "deterministic_full_wgs",
                    "rosalind_diana_wgs",
                    "facets_scarhrd_blocked",
                    "oncoanalyser_chord_blocked",
                    "hrdetect_blocked",
                ],
                [packet["method_id"] for packet in written["packets"]],
            )
            self.assertGreaterEqual(written["forbidden_token_count"], 5)
            self.assertRegex(written["forbidden_tokens_sha256"], re.compile(r"^[0-9a-f]{64}$"))
            self.assertEqual(
                VALIDATOR.expected_forbidden_tokens_sha256(json.dumps(["Run-Private-Token"])),
                written["forbidden_tokens_sha256"],
            )
            self.assertNotIn("Run-Private-Token", json.dumps(written))
            self.assertEqual(
                {"relative_path", "bytes", "sha256", "checksum_sha256"},
                set(written["packets"][0]["files"][0]),
            )
            self.assertNotIn("path", written["packets"][0]["files"][0])

    def test_rejects_terminal_bound_blocked_packets_in_fast_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_dirs = self.write_phase3_fast_packets(root)
            blocked = packet_dirs["facets_scarhrd_blocked"]

            method_spec_path = blocked / "method_spec.json"
            method_spec = json.loads(method_spec_path.read_text(encoding="utf-8"))
            method_spec["source_report_binding_scope"] = "terminal_source_reports"
            method_spec_path.write_text(
                json.dumps(method_spec, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path = blocked / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_report_binding_scope"] = "terminal_source_reports"
            manifest["review_summary"]["source_report_binding_scope"] = (
                "terminal_source_reports"
            )
            manifest["support_sha256"]["method_spec.json"] = sha256(method_spec_path)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "must use pre_route_deterministic_rosalind",
            ):
                VALIDATOR.validate_packets(
                    packet_dirs,
                    json.dumps(["Run-Private-Token"]),
                )

    def test_rejects_pre_route_blocked_packet_source_digest_drift(self) -> None:
        def drift_method_spec(method_spec: dict, manifest: dict) -> None:
            method_spec["source_report_manifests"]["deterministic_full_wgs"] = "d" * 64

        def drift_manifest_source(method_spec: dict, manifest: dict) -> None:
            manifest["source_sha256"]["deterministic_full_wgs_report_manifest"] = (
                "d" * 64
            )

        def drift_review_summary(method_spec: dict, manifest: dict) -> None:
            manifest["review_summary"]["source_report_manifests"][
                "deterministic_full_wgs"
            ] = "d" * 64

        cases = (
            ("method_spec", drift_method_spec),
            ("manifest_source", drift_manifest_source),
            ("review_summary", drift_review_summary),
        )

        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                packet_dirs = self.write_phase3_fast_packets(root)
                blocked = packet_dirs["facets_scarhrd_blocked"]

                method_spec_path = blocked / "method_spec.json"
                method_spec = json.loads(method_spec_path.read_text(encoding="utf-8"))
                manifest_path = blocked / "report_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

                mutate(method_spec, manifest)
                method_spec_path.write_text(
                    json.dumps(method_spec, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                manifest["support_sha256"]["method_spec.json"] = sha256(
                    method_spec_path,
                )
                manifest_path.write_text(
                    json.dumps(manifest, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "must use pre_route_deterministic_rosalind",
                ):
                    VALIDATOR.validate_packets(
                        packet_dirs,
                        json.dumps(["Run-Private-Token"]),
                    )

    def test_rejects_pre_route_blocked_packet_extra_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_dirs = self.write_phase3_fast_packets(root)
            blocked = packet_dirs["hrdetect_blocked"]

            manifest_path = blocked / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source_sha256"]["legacy_unit_source"] = "0" * 64
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "must use pre_route_deterministic_rosalind",
            ):
                VALIDATOR.validate_packets(
                    packet_dirs,
                    json.dumps(["Run-Private-Token"]),
                )

    def test_rejects_run_supplied_forbidden_token_leak(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_dirs = self.write_phase3_fast_packets(root)
            (packet_dirs["rosalind_diana_wgs"] / "report.md").write_text(
                "No-call report still containing Run-Private-Token.\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "forbidden identifier token"):
                VALIDATOR.validate_packets(
                    packet_dirs,
                    json.dumps(["Run-Private-Token"]),
                )

    def test_writes_validation_receipt_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "report_packet_validation.json"
            self.write_phase3_fast_packets(root)

            args = argparse.Namespace(
                deterministic_report_dir=root / "deterministic_full_wgs",
                rosalind_report_dir=root / "rosalind_diana_wgs",
                facets_scarhrd_report_dir=root / "facets_scarhrd_blocked",
                oncoanalyser_chord_report_dir=root / "oncoanalyser_chord_blocked",
                hrdetect_report_dir=root / "hrdetect_blocked",
                forbidden_tokens_json=json.dumps(["Run-Private-Token"]),
                output=output,
            )
            VALIDATOR.run(args)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

            with self.assertRaises(FileExistsError):
                VALIDATOR.run(args)

    def test_rejects_validation_receipt_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "real-manifests"
            linked_parent = root / "manifests"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                VALIDATOR.write_json_create_only(
                    linked_parent / "report_packet_validation.json",
                    {"status": "passed"},
                )

            self.assertFalse((real_parent / "report_packet_validation.json").exists())

    def test_rejects_validation_receipt_input_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            packet_dirs = self.write_phase3_fast_packets(root)
            real_parent = root / "real-manifests"
            linked_parent = root / "manifests"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            receipt = real_parent / "report_packet_validation.json"
            receipt.write_text(
                json.dumps(
                    VALIDATOR.validate_packets(
                        packet_dirs,
                        json.dumps(["Run-Private-Token"]),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            linked_receipt = linked_parent / receipt.name

            self.assertTrue(linked_receipt.is_file())
            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                VALIDATOR.load_validation_receipt_packet_sha256s(linked_receipt)

    def test_removes_partial_validation_receipt_after_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report_packet_validation.json"

            with (
                mock.patch.object(
                    VALIDATOR.os,
                    "fsync",
                    side_effect=OSError("synthetic fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic fsync failure"),
            ):
                VALIDATOR.write_json_create_only(output, {"status": "partial"})

            self.assertFalse(output.exists())

    def test_validation_receipt_rehashes_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report_packet_validation.json"
            real_fsync_directory = VALIDATOR.fsync_directory

            def tamper_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    VALIDATOR,
                    "fsync_directory",
                    side_effect=tamper_after_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report packet validation output changed during write",
                ),
            ):
                VALIDATOR.write_json_create_only(output, {"status": "passed"})

            self.assertFalse(output.exists())

    def test_rejects_malformed_receipt_token_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_dirs = self.write_phase3_fast_packets(root)
            receipt = VALIDATOR.validate_packets(packet_dirs, json.dumps(["Run-Private-Token"]))

            for field, value in (
                ("static_forbidden_token_count", 0),
                ("run_forbidden_token_count", 0),
                ("forbidden_token_count", 999),
            ):
                with self.subTest(field=field):
                    malformed = dict(receipt)
                    malformed[field] = value

                    with self.assertRaisesRegex(ValueError, "forbidden-token"):
                        VALIDATOR.require_validation_receipt_packet_sha256s(malformed)

    def test_rejects_inexact_validation_receipt_envelopes(self) -> None:
        cases = (
            (
                "top-level",
                lambda receipt: receipt.update({"legacy_field": True}),
                "report packet validation receipt is malformed",
            ),
            (
                "float-schema",
                lambda receipt: receipt.__setitem__("schema_version", 1.0),
                "report packet validation receipt is malformed",
            ),
            (
                "packet",
                lambda receipt: receipt["packets"][0].update({"legacy_file_count": 1}),
                "packet rows",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                packet_dirs = self.write_phase3_fast_packets(root)
                receipt = VALIDATOR.validate_packets(
                    packet_dirs,
                    json.dumps(["Run-Private-Token"]),
                )
                mutate(receipt)

                with self.assertRaisesRegex(
                    ValueError,
                    message,
                ):
                    VALIDATOR.require_validation_receipt_packet_sha256s(receipt)

    def test_rejects_malformed_receipt_packet_file_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_dirs = self.write_phase3_fast_packets(root)
            receipt = VALIDATOR.validate_packets(packet_dirs, json.dumps(["Run-Private-Token"]))

            malformed = json.loads(json.dumps(receipt))
            malformed["packets"][0]["files"][0]["bytes"] = 0

            with self.assertRaisesRegex(ValueError, "file rows"):
                VALIDATOR.require_validation_receipt_packet_sha256s(malformed)

            malformed = json.loads(json.dumps(receipt))
            malformed["packets"][0]["total_bytes"] += 1

            with self.assertRaisesRegex(ValueError, "byte summary"):
                VALIDATOR.require_validation_receipt_packet_sha256s(malformed)

            malformed = json.loads(json.dumps(receipt))
            malformed["packets"][0]["files"][0]["relative_path"] = "renamed.md"

            with self.assertRaisesRegex(ValueError, "digest summary"):
                VALIDATOR.require_validation_receipt_packet_sha256s(malformed)

            malformed = json.loads(json.dumps(receipt))
            malformed["packets"][0]["files"][0]["checksum_sha256"] = "A" * 43 + "="

            with self.assertRaisesRegex(ValueError, "file rows"):
                VALIDATOR.require_validation_receipt_packet_sha256s(malformed)

    def test_rejects_receipt_from_different_run_forbidden_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_dirs = self.write_phase3_fast_packets(root)
            receipt_path = root / "report_packet_validation.json"
            receipt_path.write_text(
                json.dumps(
                    VALIDATOR.validate_packets(
                        packet_dirs,
                        json.dumps(["Run-Private-Token"]),
                    ),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "forbidden-token digest"):
                VALIDATOR.validate_validation_receipt_matches_packets(
                    receipt_path,
                    packet_dirs,
                    tuple(VALIDATOR.FORBIDDEN_TOKENS),
                    VALIDATOR.expected_forbidden_tokens_sha256(json.dumps(["Other-Private-Token"])),
                )


if __name__ == "__main__":
    unittest.main()
