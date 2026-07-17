from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_ai_review_bundle as BUILD  # noqa: E402
import hrd_report_inventory as INVENTORY  # noqa: E402
import stage_ai_review_inputs as STAGE  # noqa: E402


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        manifest = {
            "schema_version": 1,
            "report_kind": "deterministic" if index == 0 else "method",
            "method_id": method_id,
            "evidence_status": "blocked" if index >= 4 else "partial_evidence",
            "interpretation_status": "no_call",
            "authorized_hrd_state": "no_call",
            "classification_authorized": False,
            "classification_qc_status": "blocked" if index >= 4 else "not_applicable",
            "review_summary": review_summary,
            "report_sha256": BUILD.sha256(report),
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
        command = [sys.executable, str(SCRIPT_DIR / "build_ai_review_bundle.py")]
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
        return subprocess.run(command, text=True, capture_output=True)


class BuildAiReviewBundleTests(unittest.TestCase):
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

    def test_records_exact_numeric_tokens_as_quantitative_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = AiReviewBundleFixture(Path(temporary))
            self.assertEqual(fixture.run().returncode, 0)

            bundle = json.loads((fixture.bundle_dir / "review_bundle.json").read_text())
            exact_text = {row["exact_text"] for row in bundle["quantitative_facts"]}

            self.assertIn("3", exact_text)
            self.assertIn("1.5%", exact_text)

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
