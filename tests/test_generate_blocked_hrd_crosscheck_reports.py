from __future__ import annotations

import ast
import hashlib
import io
import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from collections.abc import Callable
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


def write_duplicate_json_field(path: Path, key: str, stale_value: object) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload, indent=2, sort_keys=True)
    current = f'  "{key}": {json.dumps(payload[key], sort_keys=True)}'
    description = f"top-level JSON field {key}"
    if text.count(current) != 1:
        raise AssertionError(f"expected exactly one {description}")
    duplicate = f'  "{key}": {json.dumps(stale_value, sort_keys=True)},\n{current}'
    path.write_text(text.replace(current, duplicate, 1) + "\n", encoding="utf-8")


def rebind_mutated_method_spec(
    directory: Path,
    mutate: Callable[[dict], None],
) -> None:
    spec_path = directory / "method_spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    mutate(spec)
    spec_path.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_path = directory / "report_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["support_sha256"]["method_spec.json"] = sha256(spec_path)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_source_report_manifest(path: Path, **updates: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    report = path.parent / "report.md"
    support = path.parent / "support.json"
    report.write_text("# Source report\n\nNo-call source packet.\n", encoding="utf-8")
    support.write_text(
        json.dumps(
            {
                "method_id": updates.get("method_id", "rosalind_diana_wgs"),
                "status": "no_call",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
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
        "source_sha256": {
            "source_support": "b" * 64,
        },
        "support_sha256": {
            "support.json": sha256(support),
        },
    }
    payload.update(updates)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_source_report_manifests(root: Path) -> dict[str, str]:
    values = []
    for method_id in GENERATOR.SOURCE_REPORT_METHOD_IDS:
        path = root / "sources" / method_id / "report_manifest.json"
        write_source_report_manifest(path, method_id=method_id)
        values.append(f"{method_id}={path}")
    return GENERATOR.load_source_report_manifests(values)


def source_report_manifest_args(root: Path) -> list[str]:
    args: list[str] = []
    for method_id in GENERATOR.SOURCE_REPORT_METHOD_IDS:
        path = root / "sources" / method_id / "report_manifest.json"
        write_source_report_manifest(path, method_id=method_id)
        args.extend(["--source-report-manifest", f"{method_id}={path}"])
    return args


ORIGINAL_GENERATE = GENERATOR.generate


def generate(
    output_root: Path,
    generated_at: str,
    **kwargs: object,
) -> list[Path]:
    if "source_report_manifests" in kwargs:
        return ORIGINAL_GENERATE(output_root, generated_at, **kwargs)
    with tempfile.TemporaryDirectory() as temporary:
        return ORIGINAL_GENERATE(
            output_root,
            generated_at,
            source_report_manifests=write_source_report_manifests(Path(temporary)),
            **kwargs,
        )


GENERATOR.generate = generate


class GenerateBlockedHrdCrosscheckReportsTests(unittest.TestCase):
    def test_schema_versions_are_exact_json_integers(self) -> None:
        for value in (True, 1.0, "1", 2, None):
            with self.subTest(value=value):
                self.assertFalse(
                    GENERATOR.exact_schema_version({"schema_version": value})
                )

        self.assertTrue(GENERATOR.exact_schema_version({"schema_version": 1}))

    def test_schema_guards_use_exact_integer_helper(self) -> None:
        source = GENERATOR_SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(GENERATOR_SCRIPT))

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

    def test_sha256_file_rejects_symlinked_leaf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "real-source.txt"
            source_link = root / "source-link.txt"
            real_source.write_text("real source\n", encoding="utf-8")
            source_link.symlink_to(real_source)

            with self.assertRaisesRegex(
                ValueError,
                "source-link.txt SHA-256 input must be a real non-empty file",
            ):
                GENERATOR.sha256_file(source_link)

    def test_sha256_file_rejects_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_inputs = root / "real-inputs"
            linked_inputs = root / "linked-inputs"
            real_inputs.mkdir()
            (real_inputs / "report_manifest.json").write_text(
                "{}\n",
                encoding="utf-8",
            )
            linked_inputs.symlink_to(real_inputs, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "report_manifest.json SHA-256 input parent may not be a symlink",
            ):
                GENERATOR.sha256_file(linked_inputs / "report_manifest.json")

    def test_sha256_file_rejects_mid_read_rewrites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "report_manifest.json"
            source.write_text('{"stable": true}\n', encoding="utf-8")

            original_read_once = GENERATOR.read_real_nonempty_file_once
            mutated = False

            def mutate_after_first_read(path: Path, label: str) -> bytes:
                nonlocal mutated
                data = original_read_once(path, label)
                if path == source and not mutated:
                    mutated = True
                    path.write_text('{"stable": false}\n', encoding="utf-8")
                return data

            with (
                mock.patch.object(
                    GENERATOR,
                    "read_real_nonempty_file_once",
                    side_effect=mutate_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json SHA-256 input changed during read",
                ),
            ):
                GENERATOR.sha256_file(source)

    def test_sha256_file_rejects_symlink_swap_between_reads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "report_manifest.json"
            relocated = root / "relocated_report_manifest.json"
            source.write_text('{"stable": true}\n', encoding="utf-8")

            original_read_once = GENERATOR.read_real_nonempty_file_once
            swapped = False

            def swap_after_first_read(path: Path, label: str) -> bytes:
                nonlocal swapped
                data = original_read_once(path, label)
                if path == source and not swapped:
                    swapped = True
                    source.unlink()
                    relocated.write_text('{"stable": true}\n', encoding="utf-8")
                    source.symlink_to(relocated)
                return data

            with (
                mock.patch.object(
                    GENERATOR,
                    "read_real_nonempty_file_once",
                    side_effect=swap_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json SHA-256 input must be a real "
                    "non-empty file",
                ),
            ):
                GENERATOR.sha256_file(source)

    def test_sha256_file_rejects_same_byte_leaf_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "report_manifest.json"
            replacement = root / "replacement_report_manifest.json"
            source.write_text('{"stable": true}\n', encoding="utf-8")
            replacement.write_text('{"stable": true}\n', encoding="utf-8")

            original_read_once = GENERATOR.read_real_nonempty_file_once
            swapped = False

            def replace_leaf_after_first_read(path: Path, label: str):
                nonlocal swapped
                data = original_read_once(path, label)
                if path == source and not swapped:
                    swapped = True
                    replacement.replace(source)
                return data

            with (
                mock.patch.object(
                    GENERATOR,
                    "read_real_nonempty_file_once",
                    side_effect=replace_leaf_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json SHA-256 input changed during read",
                ),
            ):
                GENERATOR.sha256_file(source)

            self.assertTrue(swapped)

    def test_sha256_file_rejects_symlink_swap_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "report_manifest.json"
            relocated = root / "relocated_report_manifest.json"
            source.write_text('{"stable": true}\n', encoding="utf-8")
            real_os_open = GENERATOR.os.open
            swapped = False

            def swap_before_open(
                path: Path,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if path == source and not swapped:
                    swapped = True
                    source.unlink()
                    relocated.write_text('{"stable": true}\n', encoding="utf-8")
                    source.symlink_to(relocated)
                return real_os_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(
                    GENERATOR.os,
                    "open",
                    side_effect=swap_before_open,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json SHA-256 input changed during read",
                ),
            ):
                GENERATOR.sha256_file(source)

            self.assertTrue(swapped)

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

    def test_packet_file_rejects_symlink_swap_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "report.md"
            relocated = root / "relocated.md"
            real_fsync_directory = GENERATOR.fsync_directory

            def swap_to_symlink_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                relocated.write_text(
                    "relocated blocked packet\n",
                    encoding="utf-8",
                )
                output.unlink()
                output.symlink_to(relocated)

            with (
                mock.patch.object(
                    GENERATOR,
                    "fsync_directory",
                    side_effect=swap_to_symlink_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report.md SHA-256 input must be a real non-empty file",
                ),
            ):
                GENERATOR.write_file_create_only(output, b"first\n")

            self.assertTrue(relocated.exists())
            self.assertFalse(output.exists())

    def test_packet_file_rejects_same_byte_leaf_replacement_during_rehash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "report.md"
            resolved_output = output.resolve(strict=False)
            replacement = root / "replacement.md"
            replacement.write_text("first\n", encoding="utf-8")
            original_read_once = GENERATOR.read_real_nonempty_file_once
            swapped = False

            def replace_leaf_after_first_read(path: Path, label: str):
                nonlocal swapped
                data = original_read_once(path, label)
                if path == resolved_output and not swapped:
                    swapped = True
                    replacement.replace(resolved_output)
                return data

            with (
                mock.patch.object(
                    GENERATOR,
                    "read_real_nonempty_file_once",
                    side_effect=replace_leaf_after_first_read,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report.md SHA-256 input changed during read",
                ),
            ):
                GENERATOR.write_file_create_only(output, b"first\n")

            self.assertTrue(swapped)
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

    def test_packet_manifest_requires_exact_envelope_and_source_hashes(self) -> None:
        mutations = {
            "extra_top_level": (
                lambda manifest: manifest.__setitem__("legacy_note", "accepted"),
                "envelope is not exact",
            ),
            "classification_authorized": (
                lambda manifest: manifest.__setitem__(
                    "classification_authorized",
                    True,
                ),
                "envelope is not exact",
            ),
            "float_schema_version": (
                lambda manifest: manifest.__setitem__("schema_version", 1.0),
                "envelope is not exact",
            ),
            "extra_source_hash": (
                lambda manifest: manifest["source_sha256"].__setitem__(
                    "stale_report_manifest",
                    "0" * 64,
                ),
                "source hashes are not exact",
            ),
            "changed_generator_hash": (
                lambda manifest: manifest["source_sha256"].__setitem__(
                    "generator",
                    "0" * 64,
                ),
                "source hashes are not exact",
            ),
            "extra_review_summary": (
                lambda manifest: manifest["review_summary"].__setitem__(
                    "late_local_rewrite",
                    "not validated",
                ),
                "review summary is not exact",
            ),
            "extra_readiness": (
                lambda manifest: manifest["review_summary"][
                    "readiness"
                ].__setitem__(
                    "promoted_hrd_state",
                    "ready",
                ),
                "review summary is not exact",
            ),
            "promoted_readiness": (
                lambda manifest: manifest["review_summary"][
                    "readiness"
                ].__setitem__(
                    "authorized_hrd_state",
                    "called",
                ),
                "review summary is not exact",
            ),
            "stale_observation": (
                lambda manifest: manifest["review_summary"][
                    "observations"
                ].__setitem__(
                    "late_local_rewrite",
                    "accepted",
                ),
                "review summary is not exact",
            ),
            "stale_limitation": (
                lambda manifest: manifest["review_summary"][
                    "limitations"
                ].append(
                    "Late local rewrite accepted this blocked route.",
                ),
                "review summary is not exact",
            ),
            "mismatched_source_scope": (
                lambda manifest: manifest.__setitem__(
                    "source_report_binding_scope",
                    "pre_route_deterministic_rosalind",
                ),
                "source scope is not exact",
            ),
            "coerced_generated_at": (
                lambda manifest: manifest.__setitem__("generated_at", True),
                "report inputs are not exact",
            ),
        }

        for label, (mutate, message) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "blocked"
                GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")
                manifest_path = (
                    output
                    / GENERATOR.METHODS[0]["directory"]
                    / "report_manifest.json"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest)
                manifest_path.write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaisesRegex(ValueError, message):
                    GENERATOR.require_blocked_report_manifest(manifest_path.parent)

    def test_packet_manifest_requires_exact_rebound_method_spec(self) -> None:
        mutations = {
            "extra_top_level": (
                lambda spec: spec.__setitem__("legacy_note", "accepted"),
                "method spec is not exact",
            ),
            "float_schema_version": (
                lambda spec: spec.__setitem__("schema_version", 1.0),
                "method spec is not exact",
            ),
            "stale_method_id": (
                lambda spec: spec.__setitem__(
                    "method_id",
                    GENERATOR.METHODS[1]["method_id"],
                ),
                "method spec is not exact",
            ),
            "promoted_status": (
                lambda spec: spec.__setitem__("evidence_status", "complete"),
                "method spec is not exact",
            ),
            "added_blocker": (
                lambda spec: spec["blockers"].append(
                    "Late local rewrite accepted this blocked route.",
                ),
                "method spec is not exact",
            ),
            "rewritten_sources": (
                lambda spec: spec.__setitem__("sources", []),
                "method spec is not exact",
            ),
            "stale_run": (
                lambda spec: spec.__setitem__(
                    "run_id",
                    "diana-wgs-hrd-late-rewrite",
                ),
                "method spec is not exact",
            ),
            "stale_scope": (
                lambda spec: spec.__setitem__(
                    "source_report_binding_scope",
                    "pre_route_deterministic_rosalind",
                ),
                "method spec is not exact",
            ),
            "stale_source_report": (
                lambda spec: spec["source_report_manifests"].__setitem__(
                    "deterministic_full_wgs",
                    "0" * 64,
                ),
                "method spec source reports are not exact",
            ),
        }

        for label, (mutate, message) in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "blocked"
                GENERATOR.generate(
                    output,
                    "2026-07-17T00:00:00+00:00",
                    run_id="diana-wgs-hrd-unit",
                )
                directory = output / GENERATOR.METHODS[0]["directory"]
                rebind_mutated_method_spec(directory, mutate)

                with self.assertRaisesRegex(ValueError, message):
                    GENERATOR.require_blocked_report_manifest(directory)

    def test_packet_manifest_rejects_duplicate_json_object_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")
            manifest_path = (
                output
                / GENERATOR.METHODS[0]["directory"]
                / "report_manifest.json"
            )
            write_duplicate_json_field(manifest_path, "schema_version", 0)

            with self.assertRaisesRegex(
                ValueError,
                "duplicate JSON object name in "
                "blocked cross-check packet: schema_version",
            ):
                GENERATOR.require_blocked_report_manifest(manifest_path.parent)

    def test_packet_manifest_rejects_rebound_stale_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"
            GENERATOR.generate(output, "2026-07-17T00:00:00+00:00")
            directory = output / GENERATOR.METHODS[0]["directory"]

            report_path = directory / "report.md"
            report_path.write_text(
                "# Hand-edited blocked report\n\n"
                "This copied report keeps the right hashes only because the "
                "manifest was rebound.\n",
                encoding="utf-8",
            )
            manifest_path = directory / "report_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["report_sha256"] = sha256(report_path)
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "blocked cross-check report is stale",
            ):
                GENERATOR.require_blocked_report_manifest(directory)

    def test_packet_manifest_bound_hashes_must_be_exact_strings(self) -> None:
        numeric_digest = int("1" * 64)

        with tempfile.TemporaryDirectory() as temporary:
            packet_dir = Path(temporary)
            target = packet_dir / "method_spec.json"
            target.write_text("{}\n", encoding="utf-8")

            with (
                mock.patch.object(GENERATOR, "sha256_file", return_value="1" * 64),
                self.assertRaisesRegex(
                    ValueError,
                    "blocked cross-check report manifest has malformed SHA-256 "
                    "for method_spec.json",
                ),
            ):
                GENERATOR.require_bound_packet_file(
                    packet_dir,
                    "method_spec.json",
                    numeric_digest,
                )

    def test_reports_bind_upstream_report_manifests_without_exposing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_manifest_paths = []
            for method_id in GENERATOR.SOURCE_REPORT_METHOD_IDS:
                path = root / "upstream" / method_id / "report_manifest.json"
                write_source_report_manifest(path, method_id=method_id)
                source_manifest_paths.append(f"{method_id}={path}")
            output = root / "blocked"
            source_manifests = GENERATOR.load_source_report_manifests(
                source_manifest_paths
            )

            GENERATOR.generate(
                output,
                "2026-07-17T00:00:00+00:00",
                run_id="diana-wgs-hrd-unit",
                source_report_manifests=source_manifests,
            )

            for method in GENERATOR.METHODS:
                directory = output / method["directory"]
                report = (directory / "report.md").read_text(encoding="utf-8")
                manifest = json.loads((directory / "report_manifest.json").read_text(encoding="utf-8"))
                spec = json.loads((directory / "method_spec.json").read_text(encoding="utf-8"))

                self.assertIn("diana-wgs-hrd-unit", report)
                for method_id in GENERATOR.SOURCE_REPORT_METHOD_IDS:
                    self.assertIn(
                        f"{method_id} report_manifest_sha256",
                        report,
                    )
                self.assertEqual("diana-wgs-hrd-unit", manifest["run_id"])
                self.assertEqual(source_manifests, spec["source_report_manifests"])
                self.assertEqual(
                    {f"{method_id}_report_manifest": digest for method_id, digest in source_manifests.items()},
                    {key: digest for key, digest in manifest["source_sha256"].items() if key.endswith("_report_manifest")},
                )
                self.assertEqual(
                    manifest["source_report_binding_scope"],
                    "terminal_source_reports",
                )
                self.assertEqual(
                    spec["source_report_binding_scope"],
                    "terminal_source_reports",
                )
                self.assertEqual(
                    manifest["review_summary"]["source_report_binding_scope"],
                    "terminal_source_reports",
                )
                self.assertEqual(source_manifests, manifest["review_summary"]["source_report_manifests"])

            serialized = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*.*"))
            self.assertNotIn(str(root), serialized)

    def test_pre_route_generation_binds_deterministic_and_rosalind_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_manifest_paths = []
            for method_id in GENERATOR.PRE_ROUTE_SOURCE_REPORT_METHOD_IDS:
                path = root / "upstream" / method_id / "report_manifest.json"
                write_source_report_manifest(path, method_id=method_id)
                source_manifest_paths.append(f"{method_id}={path}")
            output = root / "blocked"
            source_manifests = GENERATOR.load_source_report_manifests(
                source_manifest_paths,
                allow_pre_route_source_reports=True,
            )

            GENERATOR.generate(
                output,
                "2026-07-17T00:00:00+00:00",
                run_id="diana-wgs-hrd-unit",
                source_report_manifests=source_manifests,
                allow_pre_route_source_reports=True,
            )

            for method in GENERATOR.METHODS:
                directory = output / method["directory"]
                report = (directory / "report.md").read_text(encoding="utf-8")
                manifest = json.loads((directory / "report_manifest.json").read_text(encoding="utf-8"))
                spec = json.loads((directory / "method_spec.json").read_text(encoding="utf-8"))

                self.assertIn(
                    "source_report_binding_scope: `pre_route_deterministic_rosalind`",
                    report,
                )
                self.assertEqual(
                    spec["source_report_binding_scope"],
                    "pre_route_deterministic_rosalind",
                )
                self.assertEqual(
                    manifest["source_report_binding_scope"],
                    "pre_route_deterministic_rosalind",
                )
                self.assertEqual(
                    tuple(spec["source_report_manifests"]),
                    GENERATOR.PRE_ROUTE_SOURCE_REPORT_METHOD_IDS,
                )
                self.assertNotIn(
                    "sequenza_scarhrd_report_manifest",
                    manifest["source_sha256"],
                )
                self.assertNotIn(
                    "sigprofiler_sbs3_report_manifest",
                    manifest["source_sha256"],
                )

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
                        *source_report_manifest_args(root),
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

    def test_cli_requires_source_report_manifests_before_writing_packets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"

            with (
                self.assertRaises(SystemExit) as raised,
                mock.patch("sys.stderr", new=io.StringIO()),
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--generated-at",
                        "2026-07-17T00:00:00+00:00",
                    ]
                )

            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(output.exists())

    def test_generation_requires_exact_upstream_manifests_before_writing_packets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "blocked"

            with self.assertRaisesRegex(
                ValueError,
                "source report manifests must bind the four upstream report packets",
            ):
                ORIGINAL_GENERATE(
                    output,
                    "2026-07-17T00:00:00+00:00",
                    source_report_manifests={},
                )

            self.assertFalse(output.exists())

    def test_generation_rejects_pre_route_manifests_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_manifests = {
                method_id: "a" * 64
                for method_id in GENERATOR.PRE_ROUTE_SOURCE_REPORT_METHOD_IDS
            }
            output = root / "blocked"

            with self.assertRaisesRegex(
                ValueError,
                "source report manifests must bind the four upstream report packets",
            ):
                ORIGINAL_GENERATE(
                    output,
                    "2026-07-17T00:00:00+00:00",
                    source_report_manifests=source_manifests,
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

    def test_cli_rejects_source_report_manifest_with_duplicate_json_object_names(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "source" / "report_manifest.json"
            write_source_report_manifest(manifest)
            write_duplicate_json_field(manifest, "method_id", "legacy")
            output = root / "blocked"

            with self.assertRaisesRegex(
                SystemExit,
                "duplicate JSON object name in "
                "rosalind_diana_wgs source report manifest: method_id",
            ):
                GENERATOR.main(
                    [
                        "--output-dir",
                        str(output),
                        "--source-report-manifest",
                        f"rosalind_diana_wgs={manifest}",
                    ]
                )

            self.assertFalse(output.exists())

    def test_cli_rejects_inexact_source_report_manifest_envelope(self) -> None:
        cases = (
            (
                "extra_legacy_key",
                {"legacy_support": {}},
                "report manifest envelope is not exact for rosalind_diana_wgs",
            ),
            (
                "unknown_report_kind",
                {"report_kind": "legacy_packet"},
                "report manifest envelope is not exact for rosalind_diana_wgs",
            ),
            (
                "stale_support_hash",
                {"support_sha256": {"support.json": "0" * 64}},
                "support hash mismatch for rosalind_diana_wgs: support.json",
            ),
        )

        for name, updates, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest = root / "source" / "report_manifest.json"
                write_source_report_manifest(manifest, **updates)
                output = root / "blocked"

                with self.assertRaisesRegex(SystemExit, message):
                    GENERATOR.main(
                        [
                            "--output-dir",
                            str(output),
                            "--source-report-manifest",
                            f"rosalind_diana_wgs={manifest}",
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

    def test_source_report_hashes_must_be_exact_strings(self) -> None:
        numeric_digest = int("1" * 64)
        values = {
            method_id: "a" * 64
            for method_id in GENERATOR.SOURCE_REPORT_METHOD_IDS
        }
        values[GENERATOR.SOURCE_REPORT_METHOD_IDS[0]] = numeric_digest

        with self.assertRaisesRegex(
            ValueError,
            "source report manifest SHA-256 is malformed",
        ):
            GENERATOR.validate_source_report_manifests(values)

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

    def test_source_report_manifest_binding_uses_parsed_digest_after_rewrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = []
            for method_id in GENERATOR.SOURCE_REPORT_METHOD_IDS:
                path = root / "sources" / method_id / "report_manifest.json"
                write_source_report_manifest(path, method_id=method_id)
                values.append(f"{method_id}={path}")

            target = (
                root
                / "sources"
                / "deterministic_full_wgs"
                / "report_manifest.json"
            )
            expected_sha256 = sha256(target)
            real_load = GENERATOR.load_json_object_with_sha256
            mutated = False

            def mutate_after_stable_load(
                path: Path,
                label: str,
            ) -> tuple[dict, str]:
                nonlocal mutated
                manifest, digest = real_load(path, label)
                if path == target and not mutated:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["review_summary"]["late_local_rewrite"] = (
                        "not validated"
                    )
                    path.write_text(
                        json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    mutated = True
                return manifest, digest

            with mock.patch.object(
                GENERATOR,
                "load_json_object_with_sha256",
                side_effect=mutate_after_stable_load,
            ):
                observed = GENERATOR.load_source_report_manifests(values)

            self.assertTrue(mutated)
            self.assertEqual(
                observed["deterministic_full_wgs"],
                expected_sha256,
            )
            self.assertNotEqual(sha256(target), expected_sha256)

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
