from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
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
STAGE_SCRIPT = SCRIPT_DIR / "stage_ai_review_inputs.py"
STAGE_SPEC = importlib.util.spec_from_file_location(
    "stage_ai_review_inputs",
    STAGE_SCRIPT,
)
assert STAGE_SPEC and STAGE_SPEC.loader
STAGE = importlib.util.module_from_spec(STAGE_SPEC)
STAGE_SPEC.loader.exec_module(STAGE)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class StageAiReviewInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.write_bundle(self.bundle)
        self.output_root = self.root / "inputs"
        self.receipt = self.root / "stage-receipt.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_bundle(self, bundle: Path) -> None:
        bundle.mkdir()
        (bundle / "review_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "generated_at": "2026-07-18T00:00:00+00:00",
                    "purpose": "deidentified_independent_narrative_crosscheck",
                    "subject_alias": "subject01",
                    "authorized_hrd_state": "no_call",
                    "required_method_ids": ["deterministic_full_wgs"],
                    "method_inventory": {"inventory_id": "unit"},
                    "method_inventory_sha256": "a" * 64,
                    "evidence_sources": [],
                    "quantitative_facts": [],
                    "model_execution_contracts": {},
                    "model_catalog_receipt_sha256": "b" * 64,
                    "policy": {},
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (bundle / "reviewer-a.prompt.md").write_text(
            "reviewer A\n",
            encoding="utf-8",
        )
        (bundle / "reviewer-b.prompt.md").write_text(
            "reviewer B\n",
            encoding="utf-8",
        )
        self.write_bundle_manifest(bundle)

    def write_manifest(self) -> None:
        self.write_bundle_manifest(self.bundle)

    def write_bundle_manifest(self, bundle: Path) -> None:
        (bundle / "bundle_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "generated_at": "2026-07-18T00:00:01+00:00",
                    "subject_alias": "subject01",
                    "authorized_hrd_state": "no_call",
                    "required_method_ids": ["deterministic_full_wgs"],
                    "method_inventory": {"inventory_id": "unit"},
                    "method_inventory_sha256": "a" * 64,
                    "input_manifest_sha256": {},
                    "forbidden_token_sha256": {},
                    "review_bundle_sha256": sha256(
                        bundle / "review_bundle.json"
                    ),
                    "prompt_sha256": {
                        "A": sha256(bundle / "reviewer-a.prompt.md"),
                        "B": sha256(bundle / "reviewer-b.prompt.md"),
                    },
                    "model_execution_contracts": {},
                    "model_catalog_receipt_sha256": "b" * 64,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_stages_exact_two_file_directories_from_bundle_manifest(self) -> None:
        receipt = STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(stat.S_IMODE(self.receipt.stat().st_mode), 0o600)
        for role, prompt in (
            ("A", "reviewer-a.prompt.md"),
            ("B", "reviewer-b.prompt.md"),
        ):
            directory = self.output_root / STAGE.ROLE_DIRS[role]
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(
                sorted(path.name for path in directory.iterdir()),
                ["review_bundle.json", prompt],
            )
            self.assertEqual(
                sha256(directory / "review_bundle.json"),
                sha256(self.bundle / "review_bundle.json"),
            )
            self.assertEqual(
                sha256(directory / prompt),
                sha256(self.bundle / prompt),
            )

    def test_cli_prints_reviewer_input_locations(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(
                STAGE.main(
                    [
                        "--bundle-dir",
                        str(self.bundle),
                        "--output-root",
                        str(self.output_root),
                        "--receipt-output",
                        str(self.receipt),
                    ]
                ),
                0,
            )

        payload = json.loads(out.getvalue())
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(
            payload["reviewer_a_input"],
            str(self.output_root.resolve() / "reviewer-a-input"),
        )
        self.assertEqual(
            payload["reviewer_b_input"],
            str(self.output_root.resolve() / "reviewer-b-input"),
        )
        self.assertEqual(payload["receipt_output"], str(self.receipt))

    def test_rejects_tampered_prompt_before_creating_outputs(self) -> None:
        (self.bundle / "reviewer-a.prompt.md").write_text(
            "tampered\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "AI review bundle manifest is stale for reviewer-a.prompt.md",
        ):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse(self.output_root.exists())
        self.assertFalse(self.receipt.exists())

    def test_rejects_non_lowercase_manifest_sha_before_creating_outputs(self) -> None:
        manifest_path = self.bundle / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["prompt_sha256"]["A"] = manifest["prompt_sha256"]["A"].upper()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "AI review bundle manifest has malformed SHA-256 for reviewer-a.prompt.md",
        ):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse(self.output_root.exists())
        self.assertFalse(self.receipt.exists())

    def test_rejects_unbound_bundle_files_before_creating_outputs(self) -> None:
        (self.bundle / "unbound-scratch.json").write_text(
            "{}\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "bundle inventory is not exact"):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse(self.output_root.exists())
        self.assertFalse(self.receipt.exists())

    def test_rejects_rebound_bundle_with_non_exact_envelopes(self) -> None:
        cases = (
            (
                "review bundle",
                "review_bundle.json",
                "AI review bundle envelope is not exact",
            ),
            (
                "bundle manifest",
                "bundle_manifest.json",
                "AI review bundle manifest envelope is not exact",
            ),
        )
        for label, relative, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle = root / "bundle"
                self.write_bundle(bundle)
                output_root = root / "inputs"
                receipt = root / "stage-receipt.json"

                path = bundle / relative
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["legacy_note"] = "accepted"
                path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                if relative == "review_bundle.json":
                    self.write_bundle_manifest(bundle)

                with self.assertRaisesRegex(ValueError, message):
                    STAGE.stage(bundle, output_root, receipt)

                self.assertFalse(output_root.exists())
                self.assertFalse(receipt.exists())

    def test_rejects_non_exact_bundle_manifest_schema_before_creating_outputs(
        self,
    ) -> None:
        manifest_path = self.bundle / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 2.0
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "AI review bundle manifest envelope is not exact",
        ):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse(self.output_root.exists())
        self.assertFalse(self.receipt.exists())

    def test_schema_version_checks_use_exact_integer_helper(self) -> None:
        cases = (
            (2, 2, True),
            (2.0, 2, False),
            ("2", 2, False),
            (1, 2, False),
            (None, 2, False),
            (True, 1, False),
            (False, 0, False),
        )
        for value, expected, accepted in cases:
            with self.subTest(value=value, expected=expected):
                self.assertIs(STAGE.is_exact_int(value, expected), accepted)

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(STAGE_SCRIPT.read_text(encoding="utf-8"))
        raw_schema_version_comparisons = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Compare)
            and "schema_version" in ast.unparse(node)
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_write_once_fsyncs_file_and_parent_directory(self) -> None:
        output = self.root / "complete.json"

        with mock.patch.object(
            STAGE.os,
            "fsync",
            wraps=STAGE.os.fsync,
        ) as fsync:
            STAGE.write_once(output, b"complete\n")

        self.assertEqual(output.read_text(encoding="utf-8"), "complete\n")
        self.assertEqual(fsync.call_count, 2)

    def test_write_once_removes_partial_output_after_file_fsync_failure(self) -> None:
        output = self.root / "partial.json"

        with (
            mock.patch.object(
                STAGE.os,
                "fsync",
                side_effect=OSError("synthetic file fsync failure"),
            ),
            self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
        ):
            STAGE.write_once(output, b"partial\n")

        self.assertFalse(output.exists())

    def test_write_once_removes_partial_output_after_directory_fsync_failure(
        self,
    ) -> None:
        output = self.root / "partial.json"

        with (
            mock.patch.object(
                STAGE.os,
                "fsync",
                side_effect=(None, OSError("synthetic directory fsync failure")),
            ),
            self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
        ):
            STAGE.write_once(output, b"partial\n")

        self.assertFalse(output.exists())

    def test_write_once_rehashes_after_directory_fsync(self) -> None:
        output = self.root / "complete.json"
        real_fsync_directory = STAGE.fsync_directory

        def tamper_after_directory_fsync(path: Path) -> None:
            real_fsync_directory(path)
            output.write_bytes(b"tampered\n")

        with (
            mock.patch.object(
                STAGE,
                "fsync_directory",
                side_effect=tamper_after_directory_fsync,
            ),
            self.assertRaisesRegex(
                ValueError,
                "staged AI review input changed during write",
            ),
        ):
            STAGE.write_once(output, b"complete\n")

        self.assertFalse(output.exists())

    def test_write_once_removes_output_after_mode_change(self) -> None:
        output = self.root / "complete.json"
        real_fsync_directory = STAGE.fsync_directory

        def chmod_after_directory_fsync(path: Path) -> None:
            real_fsync_directory(path)
            output.chmod(0o644)

        with (
            mock.patch.object(
                STAGE,
                "fsync_directory",
                side_effect=chmod_after_directory_fsync,
            ),
            self.assertRaisesRegex(
                ValueError,
                "staged AI review input mode is not 0600",
            ),
        ):
            STAGE.write_once(output, b"complete\n")

        self.assertFalse(output.exists())

    def test_stage_fsyncs_published_input_directories(self) -> None:
        with mock.patch.object(
            STAGE,
            "fsync_directory",
            wraps=STAGE.fsync_directory,
        ) as fsync_directory:
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertIn(mock.call(self.output_root.resolve()), fsync_directory.mock_calls)

    def test_stage_removes_published_inputs_after_output_root_fsync_failure(
        self,
    ) -> None:
        with (
            mock.patch.object(
                STAGE,
                "fsync_directory",
                side_effect=(
                    None,
                    None,
                    None,
                    None,
                    OSError("synthetic publish fsync failure"),
                ),
            ),
            self.assertRaisesRegex(OSError, "synthetic publish fsync failure"),
        ):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse((self.output_root / "reviewer-a-input").exists())
        self.assertFalse((self.output_root / "reviewer-b-input").exists())
        self.assertFalse(self.receipt.exists())

    def test_stage_rechecks_published_inputs_after_rename(self) -> None:
        attacker = self.root / "attacker"
        attacker.mkdir()
        quarantined = self.root / "quarantined-inputs"
        real_rename = STAGE.os.rename

        def malicious_tree(path: Path) -> None:
            path.mkdir(parents=True, exist_ok=True)
            (path / "review_bundle.json").write_text(
                "malicious bundle\n",
                encoding="utf-8",
            )
            (path / "reviewer-a.prompt.md").write_text(
                "malicious A\n",
                encoding="utf-8",
            )
            (path / "reviewer-b.prompt.md").write_text(
                "malicious B\n",
                encoding="utf-8",
            )

        def swap_and_rename(source: Path, destination: Path) -> None:
            if not getattr(swap_and_rename, "swapped", False):
                temporary_name = Path(source).parent.name
                real_rename(self.output_root, quarantined)
                self.output_root.symlink_to(attacker, target_is_directory=True)
                malicious_tree(attacker / temporary_name / "reviewer-a-input")
                malicious_tree(attacker / temporary_name / "reviewer-b-input")
                swap_and_rename.swapped = True
            real_rename(source, destination)

        with (
            mock.patch.object(
                STAGE.os,
                "rename",
                side_effect=swap_and_rename,
            ),
            self.assertRaisesRegex(ValueError, "parent may not be a symlink"),
        ):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse((attacker / "reviewer-a-input").exists())
        self.assertFalse((attacker / "reviewer-b-input").exists())
        self.assertFalse(self.receipt.exists())

    def test_stage_rechecks_published_inputs_after_output_root_fsync(self) -> None:
        real_fsync_directory = STAGE.fsync_directory

        def tamper_after_output_root_fsync(path: Path) -> None:
            real_fsync_directory(path)
            if path == self.output_root.resolve():
                (
                    self.output_root
                    / "reviewer-a-input"
                    / "reviewer-a.prompt.md"
                ).write_text("tampered after publish fsync\n", encoding="utf-8")

        with (
            mock.patch.object(
                STAGE,
                "fsync_directory",
                side_effect=tamper_after_output_root_fsync,
            ),
            self.assertRaisesRegex(ValueError, "reviewer A .* SHA-256 mismatch"),
        ):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse((self.output_root / "reviewer-a-input").exists())
        self.assertFalse((self.output_root / "reviewer-b-input").exists())
        self.assertFalse(self.receipt.exists())

    def test_stage_rechecks_published_input_modes_after_output_root_fsync(
        self,
    ) -> None:
        real_fsync_directory = STAGE.fsync_directory

        def chmod_after_output_root_fsync(path: Path) -> None:
            real_fsync_directory(path)
            if path == self.output_root.resolve():
                (
                    self.output_root
                    / "reviewer-a-input"
                    / "reviewer-a.prompt.md"
                ).chmod(0o644)

        with (
            mock.patch.object(
                STAGE,
                "fsync_directory",
                side_effect=chmod_after_output_root_fsync,
            ),
            self.assertRaisesRegex(
                ValueError,
                "reviewer A reviewer-a.prompt.md mode is not 0600",
            ),
        ):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse((self.output_root / "reviewer-a-input").exists())
        self.assertFalse((self.output_root / "reviewer-b-input").exists())
        self.assertFalse(self.receipt.exists())

    def test_rejects_staged_bytes_that_differ_from_bundle_manifest(self) -> None:
        real_write_once = STAGE.write_once

        def write_tampered_once(path: Path, data: bytes) -> None:
            real_write_once(path, data)
            if path.name == "reviewer-a.prompt.md":
                path.write_text("tampered during staging\n", encoding="utf-8")

        with mock.patch.object(
            STAGE,
            "write_once",
            side_effect=write_tampered_once,
        ):
            with self.assertRaisesRegex(ValueError, "reviewer A .* SHA-256 mismatch"):
                STAGE.stage(self.bundle, self.output_root, self.receipt)

        self.assertFalse((self.output_root / "reviewer-a-input").exists())
        self.assertFalse(self.receipt.exists())

    def test_refuses_existing_reviewer_directories(self) -> None:
        (self.output_root / STAGE.ROLE_DIRS["A"]).mkdir(parents=True)

        with self.assertRaisesRegex(FileExistsError, "exists"):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

    def test_refuses_existing_receipt(self) -> None:
        self.receipt.write_text("do not replace\n", encoding="utf-8")

        with self.assertRaisesRegex(FileExistsError, "receipt output already exists"):
            STAGE.stage(self.bundle, self.output_root, self.receipt)

    def test_reviewer_inventory_rejects_broad_input_directory_mode(self) -> None:
        STAGE.stage(self.bundle, self.output_root, self.receipt)
        directory = self.output_root / "reviewer-a-input"
        directory.chmod(0o755)

        with self.assertRaisesRegex(
            ValueError,
            "reviewer A input directory mode is not 0700",
        ):
            STAGE.reviewer_inventory(
                directory,
                "A",
                STAGE.validate_bundle(self.bundle),
            )

    def test_rejects_symlinked_custody_paths(self) -> None:
        self.assertFalse(STAGE.is_platform_root_alias(Path("linked-parent")))

        cases = (
            "bundle",
            "bundle-parent",
            "output-root",
            "output-root-parent",
            "output-root-existing-parent",
            "receipt",
            "receipt-parent",
            "receipt-existing-parent",
            "bundle-manifest",
        )

        for target in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle = root / "bundle"
                output_root = root / "inputs"
                receipt = root / "stage-receipt.json"
                self.write_bundle(bundle)

                if target == "bundle":
                    real_bundle = root / "bundle-real"
                    bundle.rename(real_bundle)
                    bundle.symlink_to(real_bundle, target_is_directory=True)
                    message = "bundle directory"
                elif target == "bundle-parent":
                    real_parent = root / "real-bundle-parent"
                    real_bundle = real_parent / "bundle"
                    real_bundle.mkdir(parents=True)
                    bundle.rename(real_bundle / "stale")
                    linked_parent = root / "linked-bundle-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    bundle = linked_parent / "bundle" / "stale"
                    message = "bundle directory parent"
                elif target == "output-root":
                    output_root.symlink_to(
                        root / "inputs-real",
                        target_is_directory=True,
                    )
                    message = "output root"
                elif target == "output-root-parent":
                    real_parent = root / "real-output-parent"
                    real_parent.mkdir()
                    linked_parent = root / "linked-output-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    output_root = linked_parent / "missing" / "inputs"
                    message = "output root parent"
                elif target == "output-root-existing-parent":
                    real_parent = root / "real-output-parent"
                    real_child = real_parent / "existing"
                    real_child.mkdir(parents=True)
                    linked_parent = root / "linked-output-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    output_root = linked_parent / "existing" / "inputs"
                    message = "output root parent"
                elif target == "receipt":
                    receipt.symlink_to(root / "receipt-real.json")
                    message = "receipt output"
                elif target == "receipt-parent":
                    real_parent = root / "real-receipt-parent"
                    real_parent.mkdir()
                    linked_parent = root / "linked-receipt-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    receipt = linked_parent / "missing" / "stage-receipt.json"
                    message = "receipt output parent"
                elif target == "receipt-existing-parent":
                    real_parent = root / "real-receipt-parent"
                    real_child = real_parent / "existing"
                    real_child.mkdir(parents=True)
                    linked_parent = root / "linked-receipt-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    receipt = linked_parent / "existing" / "stage-receipt.json"
                    message = "receipt output parent"
                else:
                    real_manifest = root / "bundle_manifest.real.json"
                    (bundle / "bundle_manifest.json").rename(real_manifest)
                    (bundle / "bundle_manifest.json").symlink_to(real_manifest)
                    message = "bundle_manifest.json"

                with self.assertRaisesRegex(ValueError, message):
                    STAGE.stage(bundle, output_root, receipt)

                self.assertFalse((output_root / "reviewer-a-input").exists())
                self.assertFalse((output_root / "reviewer-b-input").exists())
                self.assertFalse(receipt.exists())
                self.assertFalse((root / "real-output-parent" / "missing").exists())
                self.assertFalse((root / "real-receipt-parent" / "missing").exists())
                self.assertFalse(
                    (root / "real-output-parent" / "existing" / "inputs").exists()
                )
                self.assertFalse(
                    (
                        root
                        / "real-receipt-parent"
                        / "existing"
                        / "stage-receipt.json"
                    ).exists()
                )

    def test_rejects_overlapping_bundle_output_and_receipt_paths(self) -> None:
        cases = (
            (
                self.bundle / "reviewer-inputs",
                self.receipt,
                "output root must be separate",
            ),
            (
                self.output_root,
                self.output_root / "reviewer-a-input" / "stage-receipt.json",
                "receipt output must be separate",
            ),
            (
                self.output_root,
                self.bundle / "stage-receipt.json",
                "receipt output must be separate",
            ),
        )

        for output_root, receipt, message in cases:
            with self.subTest(output_root=output_root, receipt=receipt):
                with self.assertRaisesRegex(ValueError, message):
                    STAGE.stage(self.bundle, output_root, receipt)

                self.assertFalse((self.bundle / "reviewer-inputs").exists())
                self.assertFalse((self.output_root / "reviewer-a-input").exists())
                self.assertFalse((self.output_root / "reviewer-b-input").exists())
                self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
