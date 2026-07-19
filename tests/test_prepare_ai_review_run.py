from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

import hrd_report_inventory as INVENTORY  # noqa: E402
import prepare_ai_review_run as PREPARE  # noqa: E402

from tests.test_build_ai_review_bundle import AiReviewBundleFixture, write_json  # noqa: E402


def write_staged_run(staging: Path) -> None:
    staging.mkdir()
    for name in PREPARE.STAGED_RUN_ENTRIES:
        path = staging / name
        if name in {"bundle", "reviewer-inputs"}:
            path.mkdir()
            (path / "payload.json").write_text("{}\n", encoding="utf-8")
        else:
            path.write_text("{}\n", encoding="utf-8")


def namespace(
    fixture: AiReviewBundleFixture,
    output_dir: Path,
    *,
    inventory_id: str = INVENTORY.INVENTORY_ID,
    methods: tuple[str, ...] = INVENTORY.REQUIRED_METHOD_IDS,
) -> SimpleNamespace:
    by_method = dict(zip(methods, fixture.manifests))
    args = {
        argument: by_method[method_id]
        for method_id, argument in zip(methods, PREPARE.MANIFEST_ARGUMENTS)
    }
    args.update(
        {
            "inventory_id": inventory_id,
            "output_dir": output_dir,
            "subject_alias": "subject01",
            "model_catalog_receipt": fixture.catalog_receipt,
            "model_catalog_verified_at": fixture.catalog_verified_at,
            "reviewer_a_provider": "synthetic-provider-a",
            "reviewer_a_model_id": "synthetic-model-a-current",
            "reviewer_b_provider": "synthetic-provider-b",
            "reviewer_b_model_id": "synthetic-model-b-current",
            "forbidden_token": ["DirectIdentifier"],
            "forbidden_tokens_file": [],
            "expected_source_manifest_sha256": [
                f"{method_id}={PREPARE.sha256(by_method[method_id])}"
                for method_id in methods
            ],
        }
    )
    return SimpleNamespace(**args)


def command(
    fixture: AiReviewBundleFixture,
    output_dir: Path,
    *,
    inventory_id: str = INVENTORY.INVENTORY_ID,
    methods: tuple[str, ...] = INVENTORY.REQUIRED_METHOD_IDS,
) -> list[str]:
    by_method = dict(zip(methods, fixture.manifests))
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "prepare_ai_review_run.py"),
        "--inventory-id",
        inventory_id,
    ]
    for method_id, argument in zip(methods, PREPARE.MANIFEST_ARGUMENTS):
        cmd.extend(
            [
                "--" + argument.replace("_", "-"),
                str(by_method[method_id]),
            ]
        )
    cmd.extend(
        [
            "--output-dir",
            str(output_dir),
            "--subject-alias",
            "subject01",
            "--model-catalog-receipt",
            str(fixture.catalog_receipt),
            "--model-catalog-verified-at",
            fixture.catalog_verified_at,
            "--reviewer-a-provider",
            "synthetic-provider-a",
            "--reviewer-a-model-id",
            "synthetic-model-a-current",
            "--reviewer-b-provider",
            "synthetic-provider-b",
            "--reviewer-b-model-id",
            "synthetic-model-b-current",
            "--forbidden-token",
            "DirectIdentifier",
            *[
                token
                for method_id in methods
                for token in (
                    "--expected-source-manifest-sha256",
                    f"{method_id}={PREPARE.sha256(by_method[method_id])}",
                )
            ],
        ]
    )
    return cmd


def command_with_forbidden_tokens_file(
    fixture: AiReviewBundleFixture,
    output_dir: Path,
    forbidden_tokens_file: Path,
) -> list[str]:
    cmd = command(fixture, output_dir)
    index = cmd.index("--forbidden-token")
    del cmd[index : index + 2]
    cmd.extend(["--forbidden-tokens-file", str(forbidden_tokens_file)])
    return cmd


class PrepareAiReviewRunTests(unittest.TestCase):
    def test_prepares_bundle_and_isolated_reviewer_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            output = Path(temporary) / "ai-review"

            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                sorted(path.name for path in output.iterdir()),
                [
                    "bundle",
                    "prepare_ai_review_run_receipt.json",
                    "reviewer-inputs",
                    "stage_ai_review_inputs_receipt.json",
                ],
            )
            bundle = json.loads((output / "bundle/review_bundle.json").read_text(encoding="utf-8"))
            receipt = json.loads((output / "prepare_ai_review_run_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(len(bundle["evidence_sources"]), 7)
            self.assertEqual(receipt["status"], "passed")
            self.assertEqual(
                receipt["method_inventory"]["ordered_method_ids"],
                list(INVENTORY.REQUIRED_METHOD_IDS),
            )
            self.assertEqual(
                sorted(path.name for path in (output / "reviewer-inputs/reviewer-a-input").iterdir()),
                ["review_bundle.json", "reviewer-a.prompt.md"],
            )
            self.assertEqual(
                sorted(path.name for path in (output / "reviewer-inputs/reviewer-b-input").iterdir()),
                ["review_bundle.json", "reviewer-b.prompt.md"],
            )

    def test_prepares_hcc1395_known_answer_inventory_without_diana_relabeling(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            fixture.update_manifest(1, {"method_id": "rosalind_hcc1395_wgs"})
            inventory_id = INVENTORY.HCC1395_WGS_KNOWN_ANSWER_INVENTORY_ID
            methods = INVENTORY.HCC1395_WGS_KNOWN_ANSWER_METHOD_IDS
            output = Path(temporary) / "ai-review"

            result = subprocess.run(
                command(
                    fixture,
                    output,
                    inventory_id=inventory_id,
                    methods=methods,
                ),
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipt = json.loads(
                (output / "prepare_ai_review_run_receipt.json").read_text(
                    encoding="utf-8"
                )
            )
            bundle = json.loads(
                (output / "bundle/review_bundle.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                receipt["method_inventory"],
                INVENTORY.inventory_payload(inventory_id),
            )
            self.assertEqual(
                receipt["method_inventory_sha256"],
                INVENTORY.inventory_sha256(inventory_id),
            )
            self.assertEqual(bundle["required_method_ids"], list(methods))
            self.assertIn("rosalind_hcc1395_wgs", receipt["source_manifests"])
            self.assertNotIn("rosalind_diana_wgs", receipt["source_manifests"])

    def test_manifest_argument_inventory_must_match_required_method_count(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one manifest argument"):
            PREPARE.manifest_arguments_for_methods(
                (*INVENTORY.REQUIRED_METHOD_IDS, "extra_method")
            )

    def test_prepares_bundle_with_forbidden_tokens_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            output = Path(temporary) / "ai-review"
            forbidden_tokens = Path(temporary) / "forbidden_tokens.json"
            forbidden_tokens.write_text('["DirectIdentifier"]\n', encoding="utf-8")

            result = subprocess.run(
                command_with_forbidden_tokens_file(fixture, output, forbidden_tokens),
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            bundle_manifest = json.loads((output / "bundle/bundle_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(bundle_manifest["forbidden_token_sha256"])

    def test_receipt_binds_manifest_and_bundle_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            output = Path(temporary) / "ai-review"
            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            receipt = json.loads((output / "prepare_ai_review_run_receipt.json").read_text(encoding="utf-8"))
            bundle_manifest = output / "bundle/bundle_manifest.json"
            stage_receipt = output / "stage_ai_review_inputs_receipt.json"
            self.assertEqual(
                receipt["bundle_manifest_sha256"],
                PREPARE.sha256(bundle_manifest),
            )
            self.assertEqual(
                receipt["review_bundle_sha256"],
                PREPARE.sha256(output / "bundle/review_bundle.json"),
            )
            self.assertEqual(
                receipt["stage_receipt_sha256"],
                PREPARE.sha256(stage_receipt),
            )
            for method_id, manifest in zip(INVENTORY.REQUIRED_METHOD_IDS, fixture.manifests):
                self.assertEqual(
                    receipt["source_manifests"][method_id]["sha256"],
                    PREPARE.sha256(manifest),
                )
            self.assertFalse((output / "reviewer-inputs" / "reviewer-a-input" / "prepare_ai_review_run_receipt.json").exists())

    def test_prepare_postcondition_checks_must_be_exact(self) -> None:
        cases = {
            "missing": (
                lambda checks: checks.pop("reviewer_b_prompt_bound"),
                "missing reviewer_b_prompt_bound",
            ),
            "unexpected": (
                lambda checks: checks.update({"extra_postcondition": True}),
                "unexpected extra_postcondition",
            ),
            "failed": (
                lambda checks: checks.update({"source_report_hashes_match": False}),
                "failed source_report_hashes_match",
            ),
            "non_bool": (
                lambda checks: checks.update({"no_model_invoked": 1}),
                "failed no_model_invoked",
            ),
        }
        for name, (mutate, error) in cases.items():
            with self.subTest(name=name):
                checks = dict(PREPARE.EXPECTED_PREPARE_POSTCONDITION_CHECKS)
                mutate(checks)

                with self.assertRaisesRegex(ValueError, error):
                    PREPARE.require_exact_postcondition_checks(checks)

    def test_rejects_stage_receipt_with_stale_reviewer_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            output = root / "ai-review"
            real_stage_inputs = PREPARE.stage_inputs

            def stage_then_stale_hash(
                bundle_dir: Path,
                output_root: Path,
                receipt: Path,
            ) -> None:
                real_stage_inputs(bundle_dir, output_root, receipt)
                payload = json.loads(receipt.read_text(encoding="utf-8"))
                payload["reviewers"]["A"]["files"]["review_bundle.json"]["sha256"] = "0" * 64
                write_json(receipt, payload)

            with (
                mock.patch.object(
                    PREPARE,
                    "stage_inputs",
                    side_effect=stage_then_stale_hash,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "stage AI review input receipt is not exact",
                ),
            ):
                PREPARE.prepare(namespace(fixture, output))

            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".ai-review.*")))

    def test_rejects_stage_receipt_with_failed_child_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            output = root / "ai-review"
            real_stage_inputs = PREPARE.stage_inputs

            def stage_then_failed_check(
                bundle_dir: Path,
                output_root: Path,
                receipt: Path,
            ) -> None:
                real_stage_inputs(bundle_dir, output_root, receipt)
                payload = json.loads(receipt.read_text(encoding="utf-8"))
                payload["checks"]["bundle_manifest_bound"] = False
                write_json(receipt, payload)

            with (
                mock.patch.object(
                    PREPARE,
                    "stage_inputs",
                    side_effect=stage_then_failed_check,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "stage AI review input receipt is not exact",
                ),
            ):
                PREPARE.prepare(namespace(fixture, output))

            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".ai-review.*")))

    def test_rejects_stage_receipt_with_reviewer_inventory_drift(self) -> None:
        cases = {
            "missing_prompt": lambda payload, root: payload["reviewers"]["B"][
                "files"
            ].pop("reviewer-b.prompt.md"),
            "misrebased_path": lambda payload, root: payload["reviewers"]["A"].update(
                {"directory": str(root / "elsewhere")}
            ),
            "extra_reviewer": lambda payload, root: payload["reviewers"].update(
                {"C": dict(payload["reviewers"]["A"])}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = AiReviewBundleFixture(root)
                output = root / "ai-review"
                real_stage_inputs = PREPARE.stage_inputs

                def stage_then_drift(
                    bundle_dir: Path,
                    output_root: Path,
                    receipt: Path,
                ) -> None:
                    real_stage_inputs(bundle_dir, output_root, receipt)
                    payload = json.loads(receipt.read_text(encoding="utf-8"))
                    mutate(payload, root)
                    write_json(receipt, payload)

                with (
                    mock.patch.object(
                        PREPARE,
                        "stage_inputs",
                        side_effect=stage_then_drift,
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "stage AI review input receipt is not exact",
                    ),
                ):
                    PREPARE.prepare(namespace(fixture, output))

                self.assertFalse(output.exists())
                self.assertFalse(any(root.glob(".ai-review.*")))

    def test_refuses_wrong_explicit_mapping_without_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            output = Path(temporary) / "ai-review"
            args = command(fixture, output)
            rosalind_index = args.index("--rosalind-manifest") + 1
            args[rosalind_index] = str(fixture.manifests[0])

            result = subprocess.run(args, text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("rosalind_diana_wgs", result.stderr)
            self.assertFalse(output.exists())

    def test_refuses_stale_receipt_bound_manifest_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            output = Path(temporary) / "ai-review"
            args = command(fixture, output)
            manifest_path = fixture.manifests[0]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["review_summary"]["stale"] = "true"
            write_json(manifest_path, manifest)

            result = subprocess.run(args, text=True, capture_output=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source manifest SHA-256 is not receipt-bound", result.stderr)
            self.assertFalse(output.exists())

    def test_refuses_symlinked_source_manifest_without_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            manifest = fixture.manifests[0]
            link = root / "source-manifest-link.json"
            link.symlink_to(manifest)
            fixture.manifests[0] = link
            output = root / "ai-review"

            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "deterministic_full_wgs manifest must be a real non-empty file",
                result.stderr,
            )
            self.assertFalse(output.exists())

    def test_refuses_source_manifest_below_symlinked_parent_without_final_output(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            real_parent = root / "real-source-parent"
            real_packet = real_parent / "existing"
            shutil.copytree(fixture.manifests[0].parent, real_packet)
            linked_parent = root / "linked-source-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            fixture.manifests[0] = linked_parent / "existing" / "report_manifest.json"
            output = root / "ai-review"

            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "deterministic_full_wgs manifest parent may not be a symlink",
                result.stderr,
            )
            self.assertFalse(output.exists())

    def test_refuses_symlinked_output_without_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            real_output = root / "ai-review-real"
            real_output.mkdir()
            output = root / "ai-review"
            output.symlink_to(real_output, target_is_directory=True)

            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output may not be a symlink", result.stderr)
            self.assertFalse((real_output / "bundle").exists())

    def test_refuses_symlinked_output_parent_without_final_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = linked_parent / "missing" / "ai-review"

            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output parent may not be a symlink", result.stderr)
            self.assertFalse((real_parent / "missing").exists())

    def test_refuses_output_below_existing_dir_under_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            real_parent = root / "real-parent"
            real_output_parent = real_parent / "existing"
            real_output_parent.mkdir(parents=True)
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = linked_parent / "existing" / "ai-review"

            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output parent may not be a symlink", result.stderr)
            self.assertFalse((real_output_parent / "ai-review").exists())

    def test_propagates_builder_fail_closed_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            output = Path(temporary) / "ai-review"
            path = fixture.manifests[0]
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["review_summary"] = {"source_uri": "s3://private/raw.bam"}
            write_json(path, manifest)

            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("identifier or location key", result.stderr)
            self.assertFalse(output.exists())

    def test_refuses_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            output = Path(temporary) / "ai-review"
            output.mkdir()

            result = subprocess.run(
                command(fixture, output),
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("output already exists", result.stderr)

    def test_rebase_stage_receipt_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            final = root / "ai-review"
            staging.mkdir()
            stage_receipt = staging / "stage_ai_review_inputs_receipt.json"
            stage_receipt.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "bundle_dir": str(staging / "bundle"),
                        "output_root": str(staging),
                        "reviewers": {
                            "A": {
                                "directory": str(staging / "reviewer-inputs" / "reviewer-a-input"),
                            },
                        },
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            real_fsync_directory = PREPARE.fsync_directory

            def tamper_after_parent_fsync(path: Path) -> None:
                real_fsync_directory(path)
                stage_receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    PREPARE,
                    "fsync_directory",
                    side_effect=tamper_after_parent_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged AI review JSON changed during write",
                ),
            ):
                PREPARE.rebase_stage_receipt(stage_receipt, staging, final)

            self.assertFalse(any(staging.glob(".stage_ai_review_inputs_receipt.json.*.tmp")))

    def test_prepare_receipt_rehashes_after_parent_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = AiReviewBundleFixture(root)
            output = root / "ai-review"
            real_fsync_directory = PREPARE.fsync_directory

            def tamper_after_prepare_receipt_fsync(path: Path) -> None:
                real_fsync_directory(path)
                receipt = path / "prepare_ai_review_run_receipt.json"
                if receipt.exists():
                    receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    PREPARE,
                    "fsync_directory",
                    side_effect=tamper_after_prepare_receipt_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged AI review JSON changed during write",
                ),
            ):
                PREPARE.prepare(namespace(fixture, output))

            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".ai-review.*")))

    def test_cleans_current_attempt_after_install_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            output = Path(temporary) / "ai-review"
            moved: list[str] = []
            real_move = PREPARE.move_staged_entry

            def fail_after_first_move(source: Path, destination: Path) -> None:
                if moved:
                    raise ValueError("synthetic install failure")
                real_move(source, destination)
                moved.append(destination.name)

            with mock.patch.object(
                PREPARE,
                "move_staged_entry",
                side_effect=fail_after_first_move,
            ):
                with self.assertRaisesRegex(ValueError, "synthetic install failure"):
                    PREPARE.prepare(namespace(fixture, output))

            self.assertEqual(moved, ["bundle"])
            self.assertFalse(output.exists())

    def test_install_preserves_untracked_child_after_move_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            write_staged_run(staging)

            real_move = PREPARE.move_staged_entry
            moved: list[str] = []

            def fail_after_second_move(source: Path, destination: Path) -> None:
                real_move(source, destination)
                moved.append(destination.name)
                if destination.name == "reviewer-inputs":
                    (destination.parent / "unexpected.tmp").write_text(
                        "stray staged AI input\n",
                        encoding="utf-8",
                    )
                    raise ValueError("synthetic install failure")

            with (
                mock.patch.object(
                    PREPARE,
                    "move_staged_entry",
                    side_effect=fail_after_second_move,
                ),
                self.assertRaisesRegex(ValueError, "synthetic install failure"),
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertEqual(
                moved,
                [
                    "bundle",
                    "prepare_ai_review_run_receipt.json",
                    "reviewer-inputs",
                ],
            )
            self.assertFalse((output / "bundle").exists())
            self.assertFalse((output / "prepare_ai_review_run_receipt.json").exists())
            self.assertFalse((output / "reviewer-inputs").exists())
            self.assertEqual(
                (output / "unexpected.tmp").read_text(encoding="utf-8"),
                "stray staged AI input\n",
            )

    def test_install_rejects_symlinked_parent_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            write_staged_run(staging)
            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "parent may not be a symlink"):
                PREPARE.install_staged_run(staging, linked_parent / "ai-review")

            self.assertFalse((real_parent / "ai-review").exists())

    def test_install_rejects_incomplete_staged_run_inventory_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            write_staged_run(staging)
            (staging / "stage_ai_review_inputs_receipt.json").unlink()

            with self.assertRaisesRegex(
                ValueError,
                "staged AI review run inventory is not exact",
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertFalse(output.exists())

    def test_install_rejects_unexpected_staged_run_inventory_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            write_staged_run(staging)
            (staging / "raw.fastq").write_text("undeclared artifact\n", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                "staged AI review run inventory is not exact",
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertFalse(output.exists())

    def test_install_rejects_symlinked_staged_entry_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            write_staged_run(staging)
            real_bundle = root / "real-bundle"
            real_bundle.mkdir()
            (real_bundle / "payload.json").write_text("{}\n", encoding="utf-8")
            shutil.rmtree(staging / "bundle")
            (staging / "bundle").symlink_to(
                real_bundle,
                target_is_directory=True,
            )
            output = root / "ai-review"

            with self.assertRaisesRegex(
                ValueError,
                "staged AI review entry may not be a symlink",
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertFalse(output.exists())

    def test_install_rejects_symlinked_staged_descendant_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            write_staged_run(staging)
            bundle = staging / "bundle"
            outside = root / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            (bundle / "payload-link.json").symlink_to(outside)
            output = root / "ai-review"

            with self.assertRaisesRegex(
                ValueError,
                "staged AI review entry may not be a symlink",
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertFalse(output.exists())

    def test_install_rejects_post_move_staged_entry_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            write_staged_run(staging)

            real_move = PREPARE.move_staged_entry

            def tamper_after_move(source: Path, destination: Path) -> None:
                real_move(source, destination)
                if destination.name == "bundle":
                    (destination / "payload.json").write_text(
                        '{"tampered": true}\n',
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    PREPARE,
                    "move_staged_entry",
                    side_effect=tamper_after_move,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged AI review entry changed during install",
                ),
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertFalse(output.exists())

    def test_install_fsyncs_parent_and_output_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            write_staged_run(staging)

            with mock.patch.object(
                PREPARE,
                "fsync_directory",
                wraps=PREPARE.fsync_directory,
            ) as fsync_directory:
                PREPARE.install_staged_run(staging, output)

            self.assertEqual(
                fsync_directory.mock_calls,
                [mock.call(output.parent), mock.call(output)],
            )

    def test_install_cleans_output_after_parent_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            write_staged_run(staging)

            with (
                mock.patch.object(
                    PREPARE,
                    "fsync_directory",
                    side_effect=OSError("synthetic parent fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic parent fsync failure"),
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertFalse(output.exists())

    def test_install_cleans_output_after_output_fsync_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            write_staged_run(staging)

            with (
                mock.patch.object(
                    PREPARE,
                    "fsync_directory",
                    side_effect=(None, OSError("synthetic output fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic output fsync failure"),
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertFalse(output.exists())

    def test_install_rechecks_entries_after_output_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            output = root / "ai-review"
            write_staged_run(staging)
            real_fsync_directory = PREPARE.fsync_directory

            def tamper_after_output_fsync(path: Path) -> None:
                real_fsync_directory(path)
                if path == output:
                    (output / "bundle" / "payload.json").write_text(
                        '{"tampered": true}\n',
                        encoding="utf-8",
                    )

            with (
                mock.patch.object(
                    PREPARE,
                    "fsync_directory",
                    side_effect=tamper_after_output_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "staged AI review entry changed during install: bundle",
                ),
            ):
                PREPARE.install_staged_run(staging, output)

            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
