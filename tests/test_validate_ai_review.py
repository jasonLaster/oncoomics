from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
TEST_DIR = Path(__file__).resolve().parent
for path in (SCRIPT_DIR, TEST_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import hrd_report_inventory as INVENTORY  # noqa: E402
import validate_ai_review as VALIDATE  # noqa: E402
from test_build_ai_review_bundle import (  # noqa: E402
    AiReviewBundleFixture,
    write_json,
)


def sha256(path: Path) -> str:
    return VALIDATE.sha256(path)


def write_claims(
    path: Path,
    *,
    proposed_state: str = "no_call",
    claim: str = (
        "The coverage signal is a descriptive proxy and not allele-specific "
        "copy number."
    ),
    quantitative_fact_ids: str = "none",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=VALIDATE.CLAIMS_FIELDS)
        writer.writeheader()
        for index, method_id in enumerate(INVENTORY.REQUIRED_METHOD_IDS, 1):
            blocked = index >= 5
            writer.writerow(
                {
                    "claim_id": f"C{index:03d}",
                    "claim": claim
                    if index == 1
                    else (
                        f"The {method_id} evidence remains descriptive and "
                        "does not authorize a categorical result."
                        if not blocked
                        else (
                            f"The {method_id} route is blocked and cannot "
                            "support a categorical result."
                        )
                    ),
                    "evidence_ids": f"E{index:03d}",
                    "source_methods": method_id,
                    "evidence_states": "blocked" if blocked else "partial_evidence",
                    "support_level": "absent" if blocked else "direct",
                    "caveat": "A completed model output is unavailable."
                    if blocked
                    else "Purity, ploidy, and allele-specific LOH may be unavailable.",
                    "disposition": "cannot_assess" if blocked else "supported",
                    "proposed_hrd_state": proposed_state,
                    "quantitative_fact_ids": quantitative_fact_ids
                    if index == 1
                    else "none",
                    "disagreement_status": "missing_evidence" if blocked else "none",
                    "disagreement_evidence_ids": f"E{index:03d}"
                    if blocked
                    else "none",
                    "resolution_needed": "Complete and validate the blocked route."
                    if blocked
                    else "not_applicable",
                }
            )


def mutate_claims(path: Path, mutate) -> None:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    mutate(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=VALIDATE.CLAIMS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


class ValidateReviewFixture(AiReviewBundleFixture):
    def build(self) -> None:
        built = self.run()
        if built.returncode != 0:
            raise AssertionError(built.stdout + built.stderr)

    def write_review(
        self,
        directory: Path,
        *,
        proposed_state: str = "no_call",
        reviewer: str = "A",
        body: str = (
            "The coverage evidence is descriptive and not allele-specific "
            "[C001|E001]."
        ),
        claim: str = (
            "The coverage signal is a descriptive proxy and not "
            "allele-specific copy number."
        ),
        quantitative_fact_ids: str = "none",
        invocation_id: str | None = None,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        report = directory / "report.md"
        report.write_text(
            "# Independent HRD evidence review\n\n"
            "Authorized HRD state: `no_call`\n\n"
            "Subject alias: `subject01`\n\n"
            "## Methods and evidence\n\n"
            + "\n\n".join(
                f"The {method_id} route remains "
                f"{'blocked' if index >= 5 else 'partial_evidence'} "
                f"[C{index:03d}|E{index:03d}]."
                for index, method_id in enumerate(INVENTORY.REQUIRED_METHOD_IDS, 1)
            )
            + "\n\n"
            "## Findings\n\n"
            f"{body}\n\n"
            "## Disagreements\n\n"
            "The blocked routes cannot yet be compared with the available "
            "proxies [C005|E005] [C006|E006] [C007|E007].\n\n"
            "## Limitations\n\n"
            "Purity, ploidy, and allele-specific LOH remain unavailable "
            "[C001|E001].\n\n"
            "## Authorized conclusion\n\n"
            "The authorized conclusion remains no_call [C001|E001].\n",
            encoding="utf-8",
        )

        claims = directory / "claims.csv"
        write_claims(
            claims,
            proposed_state=proposed_state,
            claim=claim,
            quantitative_fact_ids=quantitative_fact_ids,
        )
        bundle_manifest = json.loads(
            (self.bundle_dir / "bundle_manifest.json").read_text(encoding="utf-8")
        )
        write_json(
            directory / "review_manifest.json",
            {
                "schema_version": 2,
                "reviewer_id": reviewer,
                "subject_alias": "subject01",
                "model": bundle_manifest["model_execution_contracts"][reviewer],
                "invocation": {
                    "invocation_id": invocation_id
                    or f"synthetic-invocation-{reviewer.lower()}-001",
                    "interface": "offline-test-fixture",
                    "started_at": "2026-07-17T00:00:00+00:00",
                    "completed_at": "2026-07-17T00:00:01+00:00",
                },
                "prompt_sha256": bundle_manifest["prompt_sha256"][reviewer],
                "input_bundle_sha256": bundle_manifest["review_bundle_sha256"],
                "method_inventory_sha256": INVENTORY.inventory_sha256(),
                "input_artifact_sha256": {
                    "review_bundle.json": bundle_manifest["review_bundle_sha256"],
                    f"reviewer-{reviewer.lower()}.prompt.md": bundle_manifest[
                        "prompt_sha256"
                    ][reviewer],
                },
                "independence_attestation": {
                    "other_reviewer_outputs_received": False,
                    "other_reviewer_context_received": False,
                    "external_research_used": False,
                    "raw_inputs_received": False,
                    "isolated_session": True,
                    "input_directory_contained_only_declared_artifacts": True,
                },
                "output_sha256": {
                    "report.md": sha256(report),
                    "claims.csv": sha256(claims),
                },
            },
        )

    def validate(
        self,
        review_dir: Path,
        *,
        reviewer: str = "A",
        other_review_dir: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(SCRIPT_DIR / "validate_ai_review.py"),
            "--bundle-dir",
            str(self.bundle_dir),
        ]
        for manifest in self.manifests:
            command.extend(["--source-manifest", str(manifest)])
        command.extend(
            [
                "--reviewer",
                reviewer,
                "--review-dir",
                str(review_dir),
                "--model-catalog-receipt",
                str(self.catalog_receipt),
                "--forbidden-token",
                "DirectIdentifier",
            ]
        )
        if other_review_dir is not None:
            command.extend(["--other-review-dir", str(other_review_dir)])
        return subprocess.run(command, text=True, capture_output=True)

    def refresh_output_hashes(self, directory: Path) -> None:
        manifest_path = directory / "review_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["output_sha256"] = {
            "report.md": sha256(directory / "report.md"),
            "claims.csv": sha256(directory / "claims.csv"),
        }
        write_json(manifest_path, manifest)


class ValidateAiReviewTests(unittest.TestCase):
    def test_validates_independent_review_against_schema_2_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(review)

            validated = fixture.validate(review)

            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            validation = json.loads((review / "validation.json").read_text())
            self.assertEqual(validation["schema_version"], 2)
            self.assertEqual(validation["status"], "passed")
            self.assertEqual(validation["reviewer_id"], "A")
            self.assertEqual(validation["authorized_hrd_state"], "no_call")
            self.assertEqual(validation["claim_count"], 7)
            self.assertEqual(
                validation["covered_evidence_ids"],
                [f"E{index:03d}" for index in range(1, 8)],
            )

    def test_rejects_hrd_promotion_and_removes_stale_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(review)
            self.assertEqual(fixture.validate(review).returncode, 0)

            write_claims(review / "claims.csv", proposed_state="positive")
            failed = fixture.validate(review)

            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("classification promotion", failed.stderr)
            self.assertFalse((review / "validation.json").exists())

    def test_rejects_changed_spelled_or_derived_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(
                review,
                body="The safe summary reports 3 coverage bins [C001|E001].",
                claim="The safe summary reports 3 coverage bins.",
                quantitative_fact_ids="Q0002",
            )
            self.assertEqual(
                fixture.validate(review).returncode,
                0,
                (review / "validation.json").read_text(),
            )

            report = review / "report.md"
            report.write_text(
                report.read_text(encoding="utf-8").replace("3 coverage", "4 coverage"),
                encoding="utf-8",
            )
            mutate_claims(
                review / "claims.csv",
                lambda rows: rows[0].update(
                    {"claim": "The safe summary reports 4 coverage bins."}
                ),
            )
            fixture.refresh_output_hashes(review)
            changed = fixture.validate(review)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("changes or invents", changed.stderr)

            fixture.write_review(
                review,
                body="The safe summary reports three coverage bins [C001|E001].",
                claim="The safe summary reports three coverage bins.",
                quantitative_fact_ids="Q0002",
            )
            spelled = fixture.validate(review)
            self.assertNotEqual(spelled.returncode, 0)
            self.assertIn("spells out or derives", spelled.stderr)

            fixture.write_review(
                review,
                body="The summary values must not be combined as 3 / 1.5% "
                "[C001|E001].",
                claim="The summary values must not be combined as 3 / 1.5%.",
                quantitative_fact_ids="Q0001;Q0002",
            )
            derived = fixture.validate(review)
            self.assertNotEqual(derived.returncode, 0)
            self.assertIn("spells out or derives", derived.stderr)

    def test_rejects_wrong_evidence_state_and_hidden_citation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(review)
            mutate_claims(
                review / "claims.csv",
                lambda rows: rows[0].update({"evidence_states": "ready"}),
            )
            fixture.refresh_output_hashes(review)

            wrong_state = fixture.validate(review)

            self.assertNotEqual(wrong_state.returncode, 0)
            self.assertIn("evidence state does not match", wrong_state.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-hidden"
            fixture.write_review(
                review,
                body="The coverage evidence is descriptive. <!-- [C001|E001] -->",
            )

            hidden = fixture.validate(review)

            self.assertNotEqual(hidden.returncode, 0)
            self.assertRegex(
                hidden.stderr,
                r"uncited substantive block|section has no evidence-cited content",
            )

    def test_rechecks_source_report_hash_and_output_location_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(review)
            fixture.manifests[0].with_name("report.md").write_text(
                "source report changed after bundling\n",
                encoding="utf-8",
            )

            tampered = fixture.validate(review)

            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("source report hash mismatch", tampered.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(
                review,
                body="The evidence was copied from /private/results/sample.bam "
                "[C001|E001].",
            )

            leaked = fixture.validate(review)

            self.assertNotEqual(leaked.returncode, 0)
            self.assertIn("raw object, URI, or local path", leaked.stderr)

    def test_rejects_extra_review_output_before_validation_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(review)
            (review / "notes.md").write_text(
                "stale reviewer scratch\n",
                encoding="utf-8",
            )

            validated = fixture.validate(review)

            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("review directory must contain exactly", validated.stderr)
            self.assertFalse((review / "validation.json").exists())

    def test_reviewer_b_requires_independent_validated_a_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review_a = Path(temporary) / "review-a"
            fixture.write_review(review_a, reviewer="A")
            self.assertEqual(fixture.validate(review_a).returncode, 0)

            review_b = Path(temporary) / "review-b"
            fixture.write_review(
                review_b,
                reviewer="B",
                body="The missing allele-specific copy-number gate remains "
                "unresolved [C001|E001].",
                claim="The missing allele-specific copy number prevents a categorical conclusion.",
            )
            missing_other = fixture.validate(review_b, reviewer="B")
            self.assertNotEqual(missing_other.returncode, 0)
            self.assertIn("requires --other-review-dir", missing_other.stderr)

            validated = fixture.validate(
                review_b,
                reviewer="B",
                other_review_dir=review_a,
            )
            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

            fixture.write_review(
                review_b,
                reviewer="B",
                invocation_id="synthetic-invocation-a-001",
            )
            copied = fixture.validate(
                review_b,
                reviewer="B",
                other_review_dir=review_a,
            )

            self.assertNotEqual(copied.returncode, 0)
            self.assertIn("share an invocation ID", copied.stderr)


if __name__ == "__main__":
    unittest.main()
