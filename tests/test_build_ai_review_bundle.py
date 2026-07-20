from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_ai_review_bundle as BUILD  # noqa: E402
import hrd_report_inventory as INVENTORY  # noqa: E402
import stage_ai_review_inputs as STAGE  # noqa: E402

from diana_omics.commands.hrd_context import build_rosalind_hrd_packet as PACKET  # noqa: E402
from tests.test_rosalind_hrd_packet import (  # noqa: E402
    PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
    write_phase3_fast_deterministic_report,
)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_staged_bundle(root: Path) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    shared = {
        "schema_version": 2,
        "subject_alias": "subject01",
        "authorized_hrd_state": "no_call",
        "required_method_ids": list(INVENTORY.REQUIRED_METHOD_IDS),
        "method_inventory": INVENTORY.inventory_payload(),
        "method_inventory_sha256": INVENTORY.inventory_sha256(),
        "model_execution_contracts": {
            "A": {
                "provider": "synthetic-provider-a",
                "model_id": "synthetic-model-a-current",
                "catalog_verified_at": "2026-07-18T00:00:00+00:00",
                "latest_available_attested": True,
            },
            "B": {
                "provider": "synthetic-provider-b",
                "model_id": "synthetic-model-b-current",
                "catalog_verified_at": "2026-07-18T00:00:00+00:00",
                "latest_available_attested": True,
            },
        },
        "model_catalog_receipt_sha256": "a" * 64,
    }
    review_bundle = {
        **shared,
        "generated_at": "2026-07-18T00:00:00+00:00",
        "purpose": "deidentified_independent_narrative_crosscheck",
        "evidence_sources": [],
        "quantitative_facts": [],
        "policy": {
            "raw_inputs_prohibited": True,
            "external_research_prohibited": True,
            "reviewers_independent": True,
            "other_reviewer_outputs_prohibited": True,
            "numerical_results_immutable": True,
            "classification_may_not_exceed_authorized_state": True,
        },
    }
    BUILD.write_staged_bytes(
        root / "review_bundle.json",
        BUILD.json_bytes(review_bundle),
    )
    BUILD.write_staged_bytes(root / "reviewer-a.prompt.md", b"prompt a\n")
    BUILD.write_staged_bytes(root / "reviewer-b.prompt.md", b"prompt b\n")
    BUILD.write_staged_bytes(
        root / "bundle_manifest.json",
        BUILD.json_bytes(
            {
                **shared,
                "generated_at": "2026-07-18T00:00:01+00:00",
                "input_manifest_sha256": {},
                "forbidden_token_sha256": {},
                "review_bundle_sha256": BUILD.sha256(root / "review_bundle.json"),
                "prompt_sha256": {
                    "A": BUILD.sha256(root / "reviewer-a.prompt.md"),
                    "B": BUILD.sha256(root / "reviewer-b.prompt.md"),
                },
            }
        ),
    )
    return [root / name for name in BUILD.BUNDLE_FILENAMES]


class AiReviewBundleFixture:
    def __init__(self, root: Path):
        self.root = root
        self.bundle_dir = root / "bundle"
        self.manifests: list[Path] = []
        self.catalog_verified_at = datetime.now(timezone.utc).isoformat()
        self.catalog_receipt = root / "model-catalog-receipt.json"
        write_json(
            self.catalog_receipt,
            {
                "schema_version": 1,
                "provider_catalog": "synthetic-test-catalog",
                "catalog_source": "offline-test-fixture",
                "catalog_verified_at": self.catalog_verified_at,
                "models": [
                    {
                        "provider": "synthetic-provider-a",
                        "model_id": "synthetic-model-a-current",
                        "available": True,
                        "latest_available": True,
                    },
                    {
                        "provider": "synthetic-provider-b",
                        "model_id": "synthetic-model-b-current",
                        "available": True,
                        "latest_available": True,
                    },
                ],
            },
        )
        for index, method_id in enumerate(INVENTORY.REQUIRED_METHOD_IDS):
            blocked = index >= 4
            self.write_manifest(
                index,
                method_id,
                {
                    "readiness": {
                        "route": "blocked" if blocked else "partial_evidence",
                        "overall_hrd": "no_call",
                    },
                    "limitations": [
                        "No completed model output in this synthetic fixture."
                        if blocked
                        else "No validated HRD threshold."
                    ],
                    "metrics": {
                        "coverage_bin_count": index + 3,
                        "activity_percent": f"{index + 1}.5%",
                    },
                },
            )

    def write_manifest(
        self,
        index: int,
        method_id: str,
        review_summary: dict,
    ) -> None:
        directory = self.root / f"method-{index + 1:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        report = directory / "report.md"
        report.write_text(
            "# Safe synthetic source report\n\nNo direct identifiers or raw data.\n",
            encoding="utf-8",
        )
        support = directory / "support.json"
        support.write_text('{"status":"passed"}\n', encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "report_kind": (
                "deterministic_baseline"
                if index == 0
                else "rosalind_hrd_reviewer_packet"
            ),
            "method_id": method_id,
            "evidence_status": "blocked" if index >= 4 else "partial_evidence",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "not_applicable",
            "review_summary": review_summary,
            "report_sha256": BUILD.sha256(report),
            "support_sha256": {"support.json": BUILD.sha256(support)},
            "source_sha256": {"safe_summary": "a" * 64},
        }
        path = directory / "report_manifest.json"
        write_json(path, manifest)
        self.manifests.append(path)

    def update_manifest(self, index: int, patch: dict) -> None:
        path = self.manifests[index]
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(patch)
        write_json(path, manifest)

    def run(
        self,
        *,
        methods: tuple[str, ...] = INVENTORY.REQUIRED_METHOD_IDS,
        extra_args: list[str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *self.argv(methods=methods, extra_args=extra_args)],
            text=True,
            capture_output=True,
        )

    def argv(
        self,
        *,
        methods: tuple[str, ...] = INVENTORY.REQUIRED_METHOD_IDS,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        command = [str(SCRIPT_DIR / "build_ai_review_bundle.py")]
        for manifest in self.manifests:
            command.extend(["--manifest", str(manifest)])
        for method_id in methods:
            command.extend(["--require-method", method_id])
        command.extend(
            [
                "--output-dir",
                str(self.bundle_dir),
                "--forbidden-token",
                "DirectIdentifier",
                "--subject-alias",
                "subject01",
                "--reviewer-a-provider",
                "synthetic-provider-a",
                "--reviewer-a-model-id",
                "synthetic-model-a-current",
                "--reviewer-b-provider",
                "synthetic-provider-b",
                "--reviewer-b-model-id",
                "synthetic-model-b-current",
                "--model-catalog-verified-at",
                self.catalog_verified_at,
                "--model-catalog-receipt",
                str(self.catalog_receipt),
                "--attest-models-latest",
            ]
        )
        command.extend(extra_args or [])
        return command


class BuildAiReviewBundleTests(unittest.TestCase):
    def test_schema_guards_use_exact_integer_helper(self) -> None:
        source = (SCRIPT_DIR / "build_ai_review_bundle.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source, filename=str(SCRIPT_DIR / "build_ai_review_bundle.py"))

        raw_comparisons = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "schema_version" not in segment:
                continue
            raw_comparisons.append(f"{node.lineno}: {segment}")

        self.assertEqual(raw_comparisons, [])

    def test_rejects_stale_model_catalog_receipt_envelope(self) -> None:
        for label, mutate in (
            ("top-level", lambda receipt: receipt.update(legacy=True)),
            ("model row", lambda receipt: receipt["models"][0].update(legacy=True)),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = AiReviewBundleFixture(Path(temporary))
                receipt = json.loads(
                    fixture.catalog_receipt.read_text(encoding="utf-8")
                )
                mutate(receipt)
                write_json(fixture.catalog_receipt, receipt)

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("model catalog receipt", result.stderr)
                self.assertIn("envelope is not exact", result.stderr)

    def test_rejects_non_integer_model_catalog_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            receipt = json.loads(fixture.catalog_receipt.read_text(encoding="utf-8"))
            receipt["schema_version"] = 1.0
            write_json(fixture.catalog_receipt, receipt)

            result = fixture.run()

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("model catalog receipt schema is unsupported", result.stderr)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_non_exact_model_catalog_strings(self) -> None:
        cases = (
            (
                "numeric provider catalog",
                lambda receipt: receipt.__setitem__("provider_catalog", 123),
                [],
                "provider catalog is not exact",
            ),
            (
                "numeric catalog source",
                lambda receipt: receipt.__setitem__("catalog_source", True),
                [],
                "catalog source is not exact",
            ),
            (
                "coerced provider row",
                lambda receipt: receipt["models"][0].__setitem__("provider", 123),
                ["--reviewer-a-provider", "123"],
                "model identity is not exact",
            ),
            (
                "coerced model row",
                lambda receipt: receipt["models"][0].__setitem__("model_id", 123),
                ["--reviewer-a-model-id", "123"],
                "model identity is not exact",
            ),
        )

        for label, mutate, extra_args, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = AiReviewBundleFixture(Path(temporary))
                receipt = json.loads(fixture.catalog_receipt.read_text(encoding="utf-8"))
                mutate(receipt)
                write_json(fixture.catalog_receipt, receipt)

                result = fixture.run(extra_args=extra_args)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_non_integer_source_packet_schema(self) -> None:
        for value in (True, 1.0):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                fixture = AiReviewBundleFixture(Path(temporary))
                fixture.update_manifest(0, {"schema_version": value})

                result = fixture.run()

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unsupported report-manifest schema", result.stderr)
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_bundle_file_install_is_create_only_and_fsynced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "review_bundle.json"
            source.write_bytes(b"one\n")

            with mock.patch.object(
                BUILD.os,
                "fsync",
                wraps=BUILD.os.fsync,
            ) as fsync:
                BUILD.copy_create_only(source, destination)

            self.assertEqual(destination.read_bytes(), b"one\n")
            self.assertEqual(fsync.call_count, 2)

            source.write_bytes(b"two\n")
            with self.assertRaisesRegex(
                ValueError,
                "AI review bundle output already exists",
            ):
                BUILD.copy_create_only(source, destination)

            self.assertEqual(destination.read_bytes(), b"one\n")

    def test_bundle_install_failure_removes_only_installed_bundle_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            staging.mkdir()
            output.mkdir()
            staged_paths = []
            for name in BUILD.BUNDLE_FILENAMES:
                path = staging / name
                path.write_text(f"{name}\n", encoding="utf-8")
                staged_paths.append(path)

            real_copy = BUILD.copy_create_only

            def fail_with_unexpected_child(source: Path, destination: Path) -> None:
                real_copy(source, destination)
                if destination.name == "reviewer-a.prompt.md":
                    (destination.parent / "unexpected.tmp").write_text(
                        "stray partial file\n",
                        encoding="utf-8",
                    )
                    raise ValueError("synthetic bundle install failure")

            with (
                mock.patch.object(
                    BUILD,
                    "copy_create_only",
                    side_effect=fail_with_unexpected_child,
                ),
                self.assertRaisesRegex(ValueError, "synthetic bundle install failure"),
            ):
                BUILD.install_bundle_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            for name in BUILD.BUNDLE_FILENAMES:
                self.assertFalse((output / name).exists())
            self.assertEqual(
                (output / "unexpected.tmp").read_text(encoding="utf-8"),
                "stray partial file\n",
            )

    def test_bundle_file_install_removes_partial_output_after_file_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "review_bundle.json"
            source.write_bytes(b"one\n")

            with (
                mock.patch.object(
                    BUILD.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                BUILD.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_bundle_file_install_removes_partial_output_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "review_bundle.json"
            source.write_bytes(b"one\n")

            with (
                mock.patch.object(
                    BUILD.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                BUILD.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_bundle_file_install_rejects_symlinked_staged_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_source = root / "real-review-bundle.json"
            real_source.write_bytes(b"one\n")
            symlink_source = root / "review_bundle.json"
            symlink_source.symlink_to(real_source)
            destination = root / "output" / "review_bundle.json"
            destination.parent.mkdir()

            with self.assertRaisesRegex(
                ValueError,
                "staged AI review bundle file",
            ):
                BUILD.copy_create_only(symlink_source, destination)

            self.assertFalse(destination.exists())

    def test_bundle_file_install_rejects_symlinked_destination_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "review_bundle.json"
            source.write_bytes(b"one\n")
            real_output = root / "real-output"
            real_output.mkdir()
            linked_output = root / "linked-output"
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "AI review bundle output parent may not be a symlink",
            ):
                BUILD.copy_create_only(
                    source,
                    linked_output / "review_bundle.json",
                )

            self.assertFalse((real_output / "review_bundle.json").exists())

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
                BUILD.sha256(source_link)

            real_inputs = root / "real-inputs"
            real_inputs.mkdir()
            report_manifest = real_inputs / "report_manifest.json"
            report_manifest.write_text(
                '{"method_id": "deterministic_full_wgs"}\n',
                encoding="utf-8",
            )
            linked_inputs = root / "linked-inputs"
            linked_inputs.symlink_to(real_inputs, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "report_manifest.json SHA-256 input parent may not be a symlink",
            ):
                BUILD.sha256(linked_inputs / "report_manifest.json")

    def test_sha256_rejects_hash_input_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "input.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")
            real_read_once = BUILD.read_real_hash_input_once
            calls = 0

            def mutating_read_once(path: Path, label: str) -> bytes:
                nonlocal calls
                data = real_read_once(path, label)
                calls += 1
                if calls == 1:
                    input_path.write_text(
                        '{"status": "mutated"}\n',
                        encoding="utf-8",
                    )
                return data

            with mock.patch.object(
                BUILD,
                "read_real_hash_input_once",
                side_effect=mutating_read_once,
            ):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    BUILD.sha256(input_path)

    def test_load_object_rejects_json_input_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "input.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")
            real_read_once = BUILD.read_real_hash_input_once
            calls = 0

            def mutating_read_once(path: Path, label: str) -> bytes:
                nonlocal calls
                data = real_read_once(path, label)
                calls += 1
                if calls == 1:
                    input_path.write_text(
                        '{"status": "mutated"}\n',
                        encoding="utf-8",
                    )
                return data

            with mock.patch.object(
                BUILD,
                "read_real_hash_input_once",
                side_effect=mutating_read_once,
            ):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    BUILD.load_object(input_path)

    def test_sha256_rejects_same_byte_leaf_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "input.json"
            replacement = root / "replacement-input.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")
            replacement.write_text('{"status": "ready"}\n', encoding="utf-8")
            real_read_once = BUILD.read_real_hash_input_once
            swapped = False

            def replace_after_initial_read(path: Path, label: str):
                nonlocal swapped
                data = real_read_once(path, label)
                if path == input_path and not swapped:
                    swapped = True
                    replacement.replace(input_path)
                return data

            with mock.patch.object(
                BUILD,
                "read_real_hash_input_once",
                side_effect=replace_after_initial_read,
            ):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    BUILD.sha256(input_path)

            self.assertTrue(swapped)

    def test_hash_input_rejects_leaf_replaced_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "input.json"
            target_path = root / "target.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")
            target_path.write_text('{"status": "redirected"}\n', encoding="utf-8")
            real_require = BUILD.require_real_hash_input
            swapped = False

            def swap_leaf_after_preflight(path: Path) -> None:
                nonlocal swapped
                real_require(path)
                if path == input_path and not swapped:
                    swapped = True
                    input_path.unlink()
                    input_path.symlink_to(target_path)

            with mock.patch.object(
                BUILD,
                "require_real_hash_input",
                side_effect=swap_leaf_after_preflight,
            ):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    BUILD.sha256(input_path)

    def test_bundle_file_install_revalidates_copied_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "review_bundle.json"
            source.write_bytes(b"one\n")
            real_fsync_directory = BUILD.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                destination.write_bytes(b"tampered bundle\n")

            with (
                mock.patch.object(
                    BUILD,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged AI review bundle file changed during copy",
                ),
            ):
                BUILD.copy_create_only(source, destination)

            self.assertFalse(destination.exists())

    def test_bundle_file_install_copies_exact_stable_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "review_bundle.json"
            source.write_bytes(b"one\n")
            real_read_stable = BUILD.read_stable_file_with_sha256
            swapped = False

            def mutate_source_after_stable_read(
                path: Path,
                label: str,
            ) -> tuple[bytes, str]:
                nonlocal swapped
                data, digest = real_read_stable(path, label)
                if path.name == source.name and not swapped:
                    swapped = True
                    source.write_bytes(b"two\n")
                return data, digest

            with mock.patch.object(
                BUILD,
                "read_stable_file_with_sha256",
                side_effect=mutate_source_after_stable_read,
            ):
                BUILD.copy_create_only(source, destination)

            self.assertEqual(source.read_bytes(), b"two\n")
            self.assertEqual(destination.read_bytes(), b"one\n")

    def test_bundle_staged_file_write_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "review_bundle.json"
            real_fsync_directory = BUILD.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_bytes(b"tampered bundle\n")

            with (
                mock.patch.object(
                    BUILD,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged AI review bundle file changed during write",
                ),
            ):
                BUILD.write_staged_bytes(output, b"review bundle\n")

            self.assertFalse(output.exists())

    def test_bundle_rejects_stale_staged_prompt_manifest_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            write_staged_bundle(staging)
            (staging / "reviewer-a.prompt.md").write_text(
                "stale prompt\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "AI review bundle manifest is stale for reviewer-a.prompt.md",
            ):
                BUILD.require_staged_bundle_manifest(staging)

    def test_bundle_rejects_stale_staged_bundle_manifest_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            write_staged_bundle(staging)
            bundle_path = staging / "review_bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["generated_at"] = "2026-07-18T00:00:02+00:00"
            write_json(bundle_path, bundle)

            with self.assertRaisesRegex(
                ValueError,
                "AI review bundle manifest is stale for review_bundle.json",
            ):
                BUILD.require_staged_bundle_manifest(staging)

    def test_bundle_rejects_non_exact_staged_envelopes(self) -> None:
        cases = (
            (
                "review bundle extra",
                "review_bundle.json",
                lambda payload: payload.update(legacy_note="accepted"),
                "AI review bundle envelope is not exact",
            ),
            (
                "bundle manifest extra",
                "bundle_manifest.json",
                lambda payload: payload.update(legacy_note="accepted"),
                "AI review bundle manifest envelope is not exact",
            ),
            (
                "review bundle float schema",
                "review_bundle.json",
                lambda payload: payload.update(schema_version=2.0),
                "AI review bundle envelope is not exact",
            ),
            (
                "bundle manifest float schema",
                "bundle_manifest.json",
                lambda payload: payload.update(schema_version=2.0),
                "AI review bundle manifest envelope is not exact",
            ),
        )
        for label, relative, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                staging = Path(temporary)
                write_staged_bundle(staging)

                path = staging / relative
                payload = json.loads(path.read_text(encoding="utf-8"))
                mutate(payload)
                write_json(path, payload)

                if relative == "review_bundle.json":
                    manifest_path = staging / "bundle_manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["review_bundle_sha256"] = BUILD.sha256(path)
                    write_json(manifest_path, manifest)

                with self.assertRaisesRegex(ValueError, message):
                    BUILD.require_staged_bundle_manifest(staging)

    def test_bundle_rejects_inexact_staged_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            staging = Path(temporary)
            write_staged_bundle(staging)
            (staging / "unexpected.tmp").write_text(
                "unbound scratch\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "AI review bundle inventory is not exact",
            ):
                BUILD.require_staged_bundle_manifest(staging)

    def test_bundle_install_removes_installed_files_after_final_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            output.mkdir()
            staged_paths = write_staged_bundle(staging)

            with (
                mock.patch.object(
                    BUILD,
                    "fsync_directory",
                    side_effect=(
                        *(None for _ in BUILD.BUNDLE_FILENAMES),
                        OSError(
                            "synthetic bundle directory fsync failure"
                        ),
                    ),
                ),
                self.assertRaisesRegex(
                    OSError,
                    "synthetic bundle directory fsync failure",
                ),
            ):
                BUILD.install_bundle_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))

    def test_bundle_install_removes_installed_files_after_stale_final_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            output.mkdir()
            staged_paths = write_staged_bundle(staging)
            real_fsync_directory = BUILD.fsync_directory
            fsyncs = 0

            def tamper_after_final_directory_fsync(path: Path) -> None:
                nonlocal fsyncs
                real_fsync_directory(path)
                fsyncs += 1
                if fsyncs == len(BUILD.BUNDLE_FILENAMES) + 1:
                    (output / "reviewer-b.prompt.md").write_text(
                        "stale final prompt\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    BUILD,
                    "fsync_directory",
                    side_effect=tamper_after_final_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "AI review bundle output changed during install: reviewer-b.prompt.md",
                ),
            ):
                BUILD.install_bundle_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))

    def test_bundle_install_removes_installed_files_after_inexact_final_inventory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            output.mkdir()
            staged_paths = write_staged_bundle(staging)
            real_fsync_directory = BUILD.fsync_directory
            fsyncs = 0

            def create_unexpected_file_after_final_fsync(path: Path) -> None:
                nonlocal fsyncs
                real_fsync_directory(path)
                fsyncs += 1
                if fsyncs == len(BUILD.BUNDLE_FILENAMES) + 1:
                    (output / "unexpected.tmp").write_text(
                        "unbound final file\n",
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    BUILD,
                    "fsync_directory",
                    side_effect=create_unexpected_file_after_final_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "AI review bundle inventory is not exact",
                ),
            ):
                BUILD.install_bundle_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            for name in BUILD.BUNDLE_FILENAMES:
                self.assertFalse((output / name).exists())
            self.assertEqual(
                (output / "unexpected.tmp").read_text(encoding="utf-8"),
                "unbound final file\n",
            )

    def test_bundle_install_removes_installed_files_after_self_consistent_rewrite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            output.mkdir()
            staged_paths = write_staged_bundle(staging)
            real_fsync_directory = BUILD.fsync_directory
            fsyncs = 0

            def rewrite_bundle_after_final_fsync(path: Path) -> None:
                nonlocal fsyncs
                real_fsync_directory(path)
                fsyncs += 1
                if fsyncs == len(BUILD.BUNDLE_FILENAMES) + 1:
                    bundle_path = output / "review_bundle.json"
                    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
                    bundle["generated_at"] = "2026-07-18T00:00:02+00:00"
                    write_json(bundle_path, bundle)

                    prompt_a = output / "reviewer-a.prompt.md"
                    prompt_b = output / "reviewer-b.prompt.md"
                    prompt_a.write_text("rewritten prompt a\n", encoding="utf-8")
                    prompt_b.write_text("rewritten prompt b\n", encoding="utf-8")

                    manifest_path = output / "bundle_manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["generated_at"] = "2026-07-18T00:00:03+00:00"
                    manifest["review_bundle_sha256"] = BUILD.sha256(bundle_path)
                    manifest["prompt_sha256"] = {
                        "A": BUILD.sha256(prompt_a),
                        "B": BUILD.sha256(prompt_b),
                    }
                    write_json(manifest_path, manifest)

            with (
                mock.patch.object(
                    BUILD,
                    "fsync_directory",
                    side_effect=rewrite_bundle_after_final_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "AI review bundle output changed during install: review_bundle.json",
                ),
            ):
                BUILD.install_bundle_create_only(staged_paths, output)

            self.assertTrue(output.is_dir())
            self.assertEqual([], list(output.iterdir()))

    def test_bundle_install_rejects_manifest_that_differs_from_review_bundle(
        self,
    ) -> None:
        cases = {
            "subject_alias": "subject02",
            "authorized_hrd_state": "positive",
            "required_method_ids": ["deterministic_full_wgs"],
            "method_inventory_sha256": "0" * 64,
            "model_execution_contracts": {},
            "model_catalog_receipt_sha256": "0" * 64,
        }
        for field, replacement in cases.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                staging = root / "staging"
                output = root / "ai-review"
                output.mkdir()
                staged_paths = write_staged_bundle(staging)

                manifest_path = staging / "bundle_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertNotEqual(manifest[field], replacement)
                manifest[field] = replacement
                write_json(manifest_path, manifest)

                with self.assertRaisesRegex(
                    ValueError,
                    "AI review bundle manifest differs from "
                    f"review_bundle.json for {field}",
                ):
                    BUILD.install_bundle_create_only(staged_paths, output)

                self.assertTrue(output.is_dir())
                self.assertEqual([], list(output.iterdir()))

    def test_builds_bundle_for_staged_two_file_reviewer_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            built = fixture.run()

            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            self.assertIn("no model invoked", built.stdout)

            bundle = json.loads((fixture.bundle_dir / "review_bundle.json").read_text())
            manifest = json.loads((fixture.bundle_dir / "bundle_manifest.json").read_text())
            self.assertEqual(bundle["authorized_hrd_state"], "no_call")
            self.assertEqual(
                bundle["required_method_ids"],
                list(INVENTORY.REQUIRED_METHOD_IDS),
            )
            self.assertEqual(len(bundle["evidence_sources"]), 7)
            self.assertEqual(manifest["review_bundle_sha256"], BUILD.sha256(fixture.bundle_dir / "review_bundle.json"))
            self.assertNotIn("report_manifest.json", json.dumps(bundle))
            self.assertNotIn("s3://", json.dumps(bundle))
            self.assertNotIn("DirectIdentifier", json.dumps(bundle))
            self.assertNotEqual(
                (fixture.bundle_dir / "reviewer-a.prompt.md").read_text(),
                (fixture.bundle_dir / "reviewer-b.prompt.md").read_text(),
            )

            receipt = STAGE.stage(
                fixture.bundle_dir,
                Path(temporary) / "reviewer-inputs",
                Path(temporary) / "stage-receipt.json",
            )
            self.assertEqual(receipt["status"], "passed")

    def test_rejects_stale_source_packet_support_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            support = fixture.manifests[0].parent / "support.json"
            support.write_text('{"status":"tampered"}\n', encoding="utf-8")

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn(
                "support hash mismatch for deterministic_full_wgs: support.json",
                built.stderr,
            )
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_inexact_source_packet_support_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            (fixture.manifests[0].parent / "unbound.json").write_text(
                "{}\n",
                encoding="utf-8",
            )

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn(
                "support inventory is not exact for deterministic_full_wgs",
                built.stderr,
            )
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_malformed_source_packet_support_bindings(self) -> None:
        cases = (
            ("missing", {}, "missing support hashes"),
            ("nested", {"nested/support.json": "a" * 64}, "malformed support path"),
            ("core", {"report.md": "a" * 64}, "malformed support path"),
            ("bad_sha", {"support.json": "BAD"}, "malformed support SHA-256"),
        )

        for name, support_sha256, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                fixture = AiReviewBundleFixture(Path(temporary))
                fixture.update_manifest(0, {"support_sha256": support_sha256})

                built = fixture.run()

                self.assertNotEqual(built.returncode, 0)
                self.assertIn(message, built.stderr)
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_non_lowercase_source_packet_hashes(self) -> None:
        cases = (
            (
                "report",
                lambda fixture: fixture.update_manifest(
                    0,
                    {
                        "report_sha256": BUILD.sha256(
                            fixture.manifests[0].parent / "report.md"
                        ).upper(),
                    },
                ),
                "missing report SHA-256",
            ),
            (
                "support",
                lambda fixture: fixture.update_manifest(
                    0,
                    {
                        "support_sha256": {
                            "support.json": BUILD.sha256(
                                fixture.manifests[0].parent / "support.json"
                            ).upper(),
                        },
                    },
                ),
                "malformed support SHA-256",
            ),
            (
                "source",
                lambda fixture: fixture.update_manifest(
                    0,
                    {"source_sha256": {"safe_summary": "A" * 64}},
                ),
                "malformed source hashes",
            ),
        )

        for name, mutate, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                fixture = AiReviewBundleFixture(Path(temporary))
                mutate(fixture)

                built = fixture.run()

                self.assertNotEqual(built.returncode, 0)
                self.assertIn(message, built.stderr)
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_malformed_source_packet_hash_ids(self) -> None:
        for malformed in (
            "",
            " safe_summary",
            "safe summary",
            "safe/summary",
            "safe|summary",
            "true",
            "false",
            "null",
            7,
            True,
        ):
            with (
                self.subTest(malformed=malformed),
                tempfile.TemporaryDirectory() as temporary,
            ):
                fixture = AiReviewBundleFixture(Path(temporary))
                fixture.update_manifest(
                    0,
                    {"source_sha256": {malformed: "a" * 64}},
                )

                built = fixture.run()

                self.assertNotEqual(built.returncode, 0)
                self.assertIn(
                    "malformed source-artifact ID for deterministic_full_wgs",
                    built.stderr,
                )
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_duplicate_source_packet_hash_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            manifest_path = fixture.manifests[0]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            digest = "a" * 64
            manifest["source_sha256"] = {}
            payload = (
                json.dumps(manifest, indent=2, sort_keys=True)
                .replace(
                    '  "source_sha256": {},',
                    (
                        '  "source_sha256": {\n'
                        f'    "safe_summary": "{digest}",\n'
                        f'    "safe_summary": "{digest}"\n'
                        "  },"
                    ),
                )
                + "\n"
            )
            manifest_path.write_text(payload, encoding="utf-8")

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn(
                (
                    "duplicate JSON object name in manifest report_manifest.json: "
                    "safe_summary"
                ),
                built.stderr,
            )
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_inexact_source_packet_report_manifest_envelope(self) -> None:
        cases = (
            ("extra_legacy_key", {"legacy_support": {}}, {}),
            ("unknown_report_kind", {"report_kind": "unknown_packet"}, {}),
        )

        for name, patch, remove in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                fixture = AiReviewBundleFixture(Path(temporary))
                manifest_path = fixture.manifests[0]
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest.update(patch)
                for key in remove:
                    manifest.pop(key)
                write_json(manifest_path, manifest)

                built = fixture.run()

                self.assertNotEqual(built.returncode, 0)
                self.assertIn(
                    "report manifest envelope is not exact for deterministic_full_wgs",
                    built.stderr,
                )
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_non_exact_source_packet_manifest_fields(self) -> None:
        cases = (
            (
                "legacy route fallback",
                {"route": "deterministic_full_wgs"},
                {"method_id"},
                "invalid or missing method identifier",
            ),
            (
                "non-string method",
                {"method_id": 12},
                set(),
                "invalid or missing method identifier",
            ),
            (
                "non-string evidence status",
                {"evidence_status": True},
                set(),
                "invalid evidence status for deterministic_full_wgs",
            ),
            (
                "legacy interpretation fallback",
                {"interpretation_status": "no_call"},
                {"authorized_hrd_state"},
                "invalid authorized HRD state for deterministic_full_wgs",
            ),
            (
                "non-string HRD state",
                {"authorized_hrd_state": False},
                set(),
                "invalid authorized HRD state for deterministic_full_wgs",
            ),
            (
                "non-string classification QC",
                {"classification_qc_status": True},
                set(),
                "invalid classification QC state for deterministic_full_wgs",
            ),
            (
                "missing report kind",
                {},
                {"report_kind"},
                "invalid report kind for deterministic_full_wgs",
            ),
            (
                "non-string report kind",
                {"report_kind": 12},
                set(),
                "invalid report kind for deterministic_full_wgs",
            ),
        )

        for name, patch, remove, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                fixture = AiReviewBundleFixture(Path(temporary))
                manifest_path = fixture.manifests[0]
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest.update(patch)
                for key in remove:
                    manifest.pop(key)
                write_json(manifest_path, manifest)

                built = fixture.run()

                self.assertNotEqual(built.returncode, 0)
                self.assertIn(message, built.stderr)
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_non_boolean_source_packet_classification_authorization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(
                0,
                {
                    "classification_authorized": "false",
                },
            )

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn(
                (
                    "report manifest classification authorization is not exact "
                    "for deterministic_full_wgs"
                ),
                built.stderr,
            )
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_symlinked_source_packet_support_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            support = fixture.manifests[0].parent / "support.json"
            linked_support = root / "linked-support.json"
            support.replace(linked_support)
            support.symlink_to(linked_support)

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn(
                "support hash mismatch for deterministic_full_wgs: support.json",
                built.stderr,
            )
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_accepts_real_phase3_fast_rosalind_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deterministic_root, final_root = write_phase3_fast_deterministic_report(
                root / "phase3_fast"
            )
            with (
                mock.patch.object(PACKET, "path_from_root", lambda relative: root / relative),
                mock.patch.dict(
                    "os.environ",
                    {
                        "ROSALIND_HRD_ARTIFACT_ROOT": str(final_root),
                        "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR": str(deterministic_root),
                        "ROSALIND_HRD_FORBIDDEN_TOKENS_JSON": PHASE3_FAST_FORBIDDEN_TOKENS_JSON,
                    },
                ),
            ):
                PACKET.write_packet(PACKET.PACKET_SPECS["diana_wgs"], "phase3-fast")

            fixture = AiReviewBundleFixture(root / "bundle-fixture")
            fixture.manifests[1] = (
                root
                / "results/rosalind_hrd/diana_wgs/phase3-fast/report_manifest.json"
            )

            built = fixture.run()

            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            bundle = (fixture.bundle_dir / "review_bundle.json").read_text(
                encoding="utf-8"
            )
            self.assertIn("sequenza_scarhrd_alias_input_contract", bundle)
            self.assertIn("subject01_tumor", bundle)
            self.assertIn("subject01_normal", bundle)
            self.assertNotIn("final/artifacts", bundle)
            self.assertNotIn(".vcf.gz", bundle)
            self.assertNotIn("tumor_sample", bundle)
            self.assertNotIn("normal_sample", bundle)

    def test_records_exact_numeric_tokens_as_quantitative_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)

            bundle = json.loads((fixture.bundle_dir / "review_bundle.json").read_text())
            exact_text = {row["exact_text"] for row in bundle["quantitative_facts"]}

            self.assertIn("3", exact_text)
            self.assertIn("1.5%", exact_text)

    def test_accepts_hcc1395_known_answer_inventory_without_diana_relabeling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(1, {"method_id": "rosalind_hcc1395_wgs"})

            built = fixture.run(
                methods=INVENTORY.HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS,
                extra_args=[
                    "--inventory-id",
                    INVENTORY.HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
                ],
            )

            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            bundle = json.loads(
                (fixture.bundle_dir / "review_bundle.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                bundle["method_inventory"]["inventory_id"],
                INVENTORY.HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID,
            )
            self.assertEqual(
                bundle["required_method_ids"],
                list(INVENTORY.HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS),
            )
            self.assertIn("rosalind_hcc1395_wgs", bundle["required_method_ids"])
            self.assertNotIn("rosalind_diana_wgs", bundle["required_method_ids"])
            self.assertIn(
                INVENTORY.inventory_sha256(
                    INVENTORY.HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID
                ),
                (fixture.bundle_dir / "reviewer-a.prompt.md").read_text(
                    encoding="utf-8"
                ),
            )

    def test_rejects_missing_duplicate_or_reordered_method_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))

            fixture.manifests = fixture.manifests[:-1]
            missing = fixture.run()
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("ordered required method inventory", missing.stderr)

            fixture = AiReviewBundleFixture(Path(temporary) / "duplicate")
            fixture.manifests[1] = fixture.manifests[0]
            duplicate = fixture.run()
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("duplicate method manifest", duplicate.stderr)

            fixture = AiReviewBundleFixture(Path(temporary) / "reordered")
            reordered = (
                INVENTORY.REQUIRED_METHOD_IDS[1],
                INVENTORY.REQUIRED_METHOD_IDS[0],
                *INVENTORY.REQUIRED_METHOD_IDS[2:],
            )
            wrong_order = fixture.run(methods=reordered)
            self.assertNotEqual(wrong_order.returncode, 0)
            self.assertIn("pinned seven-method inventory", wrong_order.stderr)

            fixture = AiReviewBundleFixture(Path(temporary) / "whitespace")
            padded = (
                f" {INVENTORY.REQUIRED_METHOD_IDS[0]}",
                *INVENTORY.REQUIRED_METHOD_IDS[1:],
            )
            padded_result = fixture.run(methods=padded)
            self.assertNotEqual(padded_result.returncode, 0)
            self.assertIn(
                "required method inventory is empty, invalid, or duplicated",
                padded_result.stderr,
            )

    def test_rejects_raw_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(
                0,
                {
                    "review_summary": {"source_uri": "s3://private/raw.bam"},
                },
            )

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("identifier or location key is prohibited", built.stderr)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_explicit_forbidden_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(
                0,
                {
                    "review_summary": {"comment": "DirectIdentifier"},
                },
            )

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("forbidden token found", built.stderr)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_malformed_explicit_forbidden_tokens(self) -> None:
        cases = (
            ("blank", " ", "forbidden token\\[1\\] must be a non-empty string"),
            ("short", "ab", "forbidden token\\[1\\] must be at least 3 characters"),
            (
                "control",
                "Direct\nIdentifier",
                "forbidden token\\[1\\] must not contain control characters",
            ),
        )
        for name, token, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                fixture = AiReviewBundleFixture(Path(temporary))

                built = fixture.run(extra_args=["--forbidden-token", token])

                self.assertNotEqual(built.returncode, 0)
                self.assertIn(message.replace("\\", ""), built.stderr)
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_symlinked_manifest_or_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            manifest_fixture = AiReviewBundleFixture(root / "manifest")
            manifest = manifest_fixture.manifests[0]
            linked_manifest = root / "linked-report-manifest.json"
            manifest.replace(linked_manifest)
            manifest.symlink_to(linked_manifest)

            built = manifest_fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("missing or unsafe report manifest", built.stderr)
            self.assertFalse(
                (manifest_fixture.bundle_dir / "review_bundle.json").exists()
            )

            report_fixture = AiReviewBundleFixture(root / "report")
            report = report_fixture.manifests[0].parent / "report.md"
            linked_report = root / "linked-report.md"
            report.replace(linked_report)
            report.symlink_to(linked_report)

            built = report_fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("report hash mismatch", built.stderr)
            self.assertFalse(
                (report_fixture.bundle_dir / "review_bundle.json").exists()
            )

    def test_rejects_symlinked_report_manifest_after_file_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            real_require = BUILD.require_real_input_file
            swapped = False

            def swap_manifest_after_file_audit(path: Path, label: str) -> Path:
                nonlocal swapped
                resolved = real_require(path, label)
                if label == "report manifest" and not swapped:
                    moved = root / "report_manifest.real.json"
                    resolved.rename(moved)
                    resolved.symlink_to(moved)
                    swapped = True
                return resolved

            with (
                mock.patch.object(
                    BUILD,
                    "require_real_input_file",
                    side_effect=swap_manifest_after_file_audit,
                ),
                mock.patch.object(sys, "argv", fixture.argv()),
                self.assertRaisesRegex(
                    SystemExit,
                    "manifest report_manifest.json is missing, unsafe, or empty",
                ),
            ):
                BUILD.main()

            self.assertTrue(swapped)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_input_manifest_binds_parsed_source_manifest_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            manifest_path = fixture.manifests[0]
            expected_manifest_hash = BUILD.sha256(manifest_path)
            real_load_object_with_sha256 = BUILD.load_object_with_sha256

            def mutate_manifest_after_read(path: Path) -> tuple[dict, str]:
                value, digest = real_load_object_with_sha256(path)
                if path == manifest_path:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["schema_version"] = 2
                    write_json(manifest_path, manifest)
                return value, digest

            with (
                mock.patch.object(
                    BUILD,
                    "load_object_with_sha256",
                    side_effect=mutate_manifest_after_read,
                ),
                mock.patch.object(sys, "argv", fixture.argv()),
            ):
                BUILD.main()

            bundle_manifest = json.loads(
                (fixture.bundle_dir / "bundle_manifest.json").read_text(
                    encoding="utf-8",
                )
            )
            self.assertEqual(
                bundle_manifest["input_manifest_sha256"]["E001"],
                expected_manifest_hash,
            )

    def test_model_catalog_binding_uses_parsed_receipt_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            expected_receipt_hash = BUILD.sha256(fixture.catalog_receipt)
            real_load_object_with_sha256 = BUILD.load_object_with_sha256

            def mutate_catalog_after_read(path: Path) -> tuple[dict, str]:
                value, digest = real_load_object_with_sha256(path)
                if path == fixture.catalog_receipt:
                    receipt = json.loads(
                        fixture.catalog_receipt.read_text(encoding="utf-8")
                    )
                    receipt["schema_version"] = 2
                    write_json(fixture.catalog_receipt, receipt)
                return value, digest

            with (
                mock.patch.object(
                    BUILD,
                    "load_object_with_sha256",
                    side_effect=mutate_catalog_after_read,
                ),
                mock.patch.object(sys, "argv", fixture.argv()),
            ):
                BUILD.main()

            bundle_manifest = json.loads(
                (fixture.bundle_dir / "bundle_manifest.json").read_text(
                    encoding="utf-8",
                )
            )
            review_bundle = json.loads(
                (fixture.bundle_dir / "review_bundle.json").read_text(
                    encoding="utf-8",
                )
            )
            self.assertEqual(
                bundle_manifest["model_catalog_receipt_sha256"],
                expected_receipt_hash,
            )
            self.assertEqual(
                review_bundle["model_catalog_receipt_sha256"],
                expected_receipt_hash,
            )

    def test_rejects_symlinked_model_catalog_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            real_receipt = root / "model-catalog-receipt-real.json"
            fixture.catalog_receipt.rename(real_receipt)
            fixture.catalog_receipt.symlink_to(real_receipt)

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("model catalog receipt", built.stderr)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_model_catalog_receipt_below_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            real_parent = root / "real-receipts"
            real_parent.mkdir()
            moved = real_parent / "model-catalog-receipt.json"
            fixture.catalog_receipt.rename(moved)
            linked_parent = root / "linked-receipts"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            fixture.catalog_receipt = linked_parent / moved.name

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("model catalog receipt parent may not be a symlink", built.stderr)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_manifest_and_report_below_symlinked_parent(self) -> None:
        for name in ("report_manifest.json", "report.md"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = AiReviewBundleFixture(root)
                real_parent = root / "real-reports"
                real_packet = real_parent / "method-01"
                real_packet.mkdir(parents=True)
                linked_parent = root / "linked-reports"
                linked_parent.symlink_to(real_parent, target_is_directory=True)

                source = fixture.manifests[0].parent / name
                source.rename(real_packet / name)
                other = "report.md" if name == "report_manifest.json" else "report_manifest.json"
                (real_packet / other).write_bytes(
                    (fixture.manifests[0].parent / other).read_bytes()
                )
                fixture.manifests[0] = linked_parent / "method-01/report_manifest.json"

                built = fixture.run()

                self.assertNotEqual(built.returncode, 0)
                self.assertIn("parent may not be a symlink", built.stderr)
                self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_symlinked_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            real_bundle = root / "bundle-real"
            real_bundle.mkdir()
            fixture.bundle_dir.symlink_to(real_bundle, target_is_directory=True)

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("AI review bundle output may not be a symlink", built.stderr)
            self.assertFalse((real_bundle / "review_bundle.json").exists())

    def test_rejects_output_below_symlinked_parent(self) -> None:
        self.assertFalse(BUILD.is_platform_root_alias(Path("linked-parent")))

        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = AiReviewBundleFixture(root)
                real_parent = root / "real-parent"
                if nested == "existing":
                    (real_parent / nested).mkdir(parents=True)
                else:
                    real_parent.mkdir()
                linked_parent = root / "linked-parent"
                linked_parent.symlink_to(real_parent, target_is_directory=True)
                fixture.bundle_dir = linked_parent / nested / "nested-bundle"

                built = fixture.run()

                self.assertNotEqual(built.returncode, 0)
                self.assertIn(
                    "AI review bundle output parent may not be a symlink",
                    built.stderr,
                )
                self.assertFalse((real_parent / nested / "nested-bundle").exists())

    def test_rejects_duplicate_pinned_models(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))

            built = fixture.run(
                extra_args=[
                    "--reviewer-b-provider",
                    "synthetic-provider-a",
                    "--reviewer-b-model-id",
                    "synthetic-model-a-current",
                ]
            )

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("distinct pinned models", built.stderr)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_positive_classification_without_ready_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(
                0,
                {
                    "evidence_status": "partial_evidence",
                    "authorized_hrd_state": "positive",
                    "classification_authorized": False,
                    "classification_qc_status": "not_applicable",
                },
            )

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("positive/negative manifest state lacks", built.stderr)

    def test_rejects_no_call_manifest_with_classification_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(0, {"classification_authorized": True})

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("no_call manifest state", built.stderr)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_promoted_rosalind_reviewer_packet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(
                1,
                {
                    "evidence_status": "ready",
                    "authorized_hrd_state": "positive",
                    "classification_authorized": True,
                    "classification_qc_status": "passed",
                },
            )

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn(
                "rosalind_hrd_reviewer_packet report manifest cannot authorize",
                built.stderr,
            )
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_rejects_no_call_manifest_with_applicable_classification_qc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(0, {"classification_qc_status": "passed"})

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn("mark classification QC as applicable", built.stderr)
            self.assertFalse((fixture.bundle_dir / "review_bundle.json").exists())

    def test_existing_bundle_files_fail_create_only_and_remain_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)
            original_hashes = {
                filename: BUILD.sha256(fixture.bundle_dir / filename)
                for filename in BUILD.BUNDLE_FILENAMES
            }
            fixture.update_manifest(0, {"review_summary": {}})

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn(
                "AI review bundle output already contains bundle files",
                built.stderr,
            )
            self.assertEqual(
                {
                    filename: BUILD.sha256(fixture.bundle_dir / filename)
                    for filename in original_hashes
                },
                original_hashes,
            )

    def test_preexisting_prompt_fails_create_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.bundle_dir.mkdir()
            stale_prompt = fixture.bundle_dir / "reviewer-a.prompt.md"
            stale_prompt.write_text("stale prompt\n", encoding="utf-8")

            built = fixture.run()

            self.assertNotEqual(built.returncode, 0)
            self.assertIn(
                "AI review bundle output already contains bundle files: "
                "reviewer-a.prompt.md",
                built.stderr,
            )
            self.assertEqual(stale_prompt.read_text(encoding="utf-8"), "stale prompt\n")


if __name__ == "__main__":
    unittest.main()
