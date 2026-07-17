from __future__ import annotations

import json
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
from test_build_ai_review_bundle import AiReviewBundleFixture, write_json  # noqa: E402


def namespace(fixture: AiReviewBundleFixture, output_dir: Path) -> SimpleNamespace:
    by_method = dict(zip(INVENTORY.REQUIRED_METHOD_IDS, fixture.manifests))
    args = {
        argument: by_method[method_id]
        for method_id, argument in PREPARE.METHOD_ARGUMENTS
    }
    args.update(
        {
            "output_dir": output_dir,
            "subject_alias": "subject01",
            "model_catalog_receipt": fixture.catalog_receipt,
            "model_catalog_verified_at": fixture.catalog_verified_at,
            "reviewer_a_provider": "synthetic-provider-a",
            "reviewer_a_model_id": "synthetic-model-a-current",
            "reviewer_b_provider": "synthetic-provider-b",
            "reviewer_b_model_id": "synthetic-model-b-current",
            "forbidden_token": ["DirectIdentifier"],
        }
    )
    return SimpleNamespace(**args)


def command(fixture: AiReviewBundleFixture, output_dir: Path) -> list[str]:
    by_method = dict(zip(INVENTORY.REQUIRED_METHOD_IDS, fixture.manifests))
    return [
        sys.executable,
        str(SCRIPT_DIR / "prepare_ai_review_run.py"),
        "--deterministic-manifest",
        str(by_method["deterministic_full_wgs"]),
        "--rosalind-manifest",
        str(by_method["rosalind_diana_wgs"]),
        "--sequenza-manifest",
        str(by_method["sequenza_scarhrd"]),
        "--sigprofiler-manifest",
        str(by_method["sigprofiler_sbs3"]),
        "--facets-blocked-manifest",
        str(by_method["facets_scarhrd_blocked"]),
        "--oncoanalyser-blocked-manifest",
        str(by_method["oncoanalyser_chord_blocked"]),
        "--hrdetect-blocked-manifest",
        str(by_method["hrdetect_blocked"]),
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
    ]


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
            bundle = json.loads(
                (output / "bundle/review_bundle.json").read_text(
                    encoding="utf-8"
                )
            )
            receipt = json.loads(
                (output / "prepare_ai_review_run_receipt.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(bundle["evidence_sources"]), 7)
            self.assertEqual(receipt["status"], "passed")
            self.assertEqual(
                receipt["method_inventory"]["ordered_method_ids"],
                list(INVENTORY.REQUIRED_METHOD_IDS),
            )
            self.assertEqual(
                sorted(
                    path.name
                    for path in (
                        output / "reviewer-inputs/reviewer-a-input"
                    ).iterdir()
                ),
                ["review_bundle.json", "reviewer-a.prompt.md"],
            )
            self.assertEqual(
                sorted(
                    path.name
                    for path in (
                        output / "reviewer-inputs/reviewer-b-input"
                    ).iterdir()
                ),
                ["review_bundle.json", "reviewer-b.prompt.md"],
            )

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

            receipt = json.loads(
                (output / "prepare_ai_review_run_receipt.json").read_text(
                    encoding="utf-8"
                )
            )
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
            for method_id, manifest in zip(
                INVENTORY.REQUIRED_METHOD_IDS, fixture.manifests
            ):
                self.assertEqual(
                    receipt["source_manifests"][method_id]["sha256"],
                    PREPARE.sha256(manifest),
                )
            self.assertFalse(
                (
                    output
                    / "reviewer-inputs"
                    / "reviewer-a-input"
                    / "prepare_ai_review_run_receipt.json"
                ).exists()
            )

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


if __name__ == "__main__":
    unittest.main()
