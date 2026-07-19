from __future__ import annotations

import ast
import csv
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
TEST_DIR = Path(__file__).resolve().parent
for path in (SCRIPT_DIR, TEST_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import hrd_report_inventory as INVENTORY  # noqa: E402
import validate_ai_review as VALIDATE  # noqa: E402

from tests.test_build_ai_review_bundle import (  # noqa: E402
    AiReviewBundleFixture,
    write_json,
)


VALIDATE_SCRIPT = SCRIPT_DIR / "validate_ai_review.py"


def sha256(path: Path) -> str:
    return VALIDATE.sha256(path)


def write_claims(
    path: Path,
    *,
    proposed_state: str = "no_call",
    claim: str = ("The coverage signal is a descriptive proxy and not allele-specific copy number."),
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
                        f"The {method_id} evidence remains descriptive and does not authorize a categorical result."
                        if not blocked
                        else (f"The {method_id} route is blocked and cannot support a categorical result.")
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
                    "quantitative_fact_ids": quantitative_fact_ids if index == 1 else "none",
                    "disagreement_status": "missing_evidence" if blocked else "none",
                    "disagreement_evidence_ids": f"E{index:03d}" if blocked else "none",
                    "resolution_needed": "Complete and validate the blocked route." if blocked else "not_applicable",
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
        body: str = ("The coverage evidence is descriptive and not allele-specific [C001|E001]."),
        claim: str = ("The coverage signal is a descriptive proxy and not allele-specific copy number."),
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
                f"The {method_id} route remains {'blocked' if index >= 5 else 'partial_evidence'} [C{index:03d}|E{index:03d}]."
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
        bundle_manifest = json.loads((self.bundle_dir / "bundle_manifest.json").read_text(encoding="utf-8"))
        write_json(
            directory / "review_manifest.json",
            {
                "schema_version": 2,
                "reviewer_id": reviewer,
                "subject_alias": "subject01",
                "model": bundle_manifest["model_execution_contracts"][reviewer],
                "invocation": {
                    "invocation_id": invocation_id or f"synthetic-invocation-{reviewer.lower()}-001",
                    "interface": "offline-test-fixture",
                    "started_at": "2026-07-17T00:00:00+00:00",
                    "completed_at": "2026-07-17T00:00:01+00:00",
                },
                "prompt_sha256": bundle_manifest["prompt_sha256"][reviewer],
                "input_bundle_sha256": bundle_manifest["review_bundle_sha256"],
                "method_inventory_sha256": INVENTORY.inventory_sha256(),
                "input_artifact_sha256": {
                    "review_bundle.json": bundle_manifest["review_bundle_sha256"],
                    f"reviewer-{reviewer.lower()}.prompt.md": bundle_manifest["prompt_sha256"][reviewer],
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
        forbidden_token: str | None = "DirectIdentifier",
        forbidden_tokens_file: Path | None = None,
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
            ]
        )
        if forbidden_token is not None:
            command.extend(["--forbidden-token", forbidden_token])
        if forbidden_tokens_file is not None:
            command.extend(["--forbidden-tokens-file", str(forbidden_tokens_file)])
        if other_review_dir is not None:
            command.extend(["--other-review-dir", str(other_review_dir)])
        return subprocess.run(command, text=True, capture_output=True)

    def validate_argv(
        self,
        review_dir: Path,
        *,
        reviewer: str = "A",
        other_review_dir: Path | None = None,
    ) -> list[str]:
        argv = [
            "--bundle-dir",
            str(self.bundle_dir),
        ]
        for manifest in self.manifests:
            argv.extend(["--source-manifest", str(manifest)])
        argv.extend(
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
            argv.extend(["--other-review-dir", str(other_review_dir)])
        return argv

    def refresh_output_hashes(self, directory: Path) -> None:
        manifest_path = directory / "review_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["output_sha256"] = {
            "report.md": sha256(directory / "report.md"),
            "claims.csv": sha256(directory / "claims.csv"),
        }
        write_json(manifest_path, manifest)

    def refresh_source_manifest_hash(self, index: int) -> None:
        manifest_path = self.bundle_dir / "bundle_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["input_manifest_sha256"][f"E{index + 1:03d}"] = sha256(
            self.manifests[index]
        )
        write_json(manifest_path, manifest)


class ValidateAiReviewTests(unittest.TestCase):
    def test_rejects_stale_model_catalog_receipt_envelope(self) -> None:
        for label, mutate in (
            ("top-level", lambda receipt: receipt.update(legacy=True)),
            ("model row", lambda receipt: receipt["models"][0].update(legacy=True)),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = ValidateReviewFixture(root)
                fixture.build()
                review = root / "review-a"
                fixture.write_review(review)
                receipt = json.loads(
                    fixture.catalog_receipt.read_text(encoding="utf-8")
                )
                mutate(receipt)
                write_json(fixture.catalog_receipt, receipt)

                result = fixture.validate(review)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("model catalog receipt", result.stderr)
                self.assertIn("envelope is not exact", result.stderr)

    def test_rejects_non_integer_model_catalog_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = ValidateReviewFixture(root)
            fixture.build()
            review = root / "review-a"
            fixture.write_review(review)
            receipt = json.loads(fixture.catalog_receipt.read_text(encoding="utf-8"))
            receipt["schema_version"] = 1.0
            write_json(fixture.catalog_receipt, receipt)

            result = fixture.validate(review)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("model catalog receipt schema is unsupported", result.stderr)
            self.assertFalse((review / "validation.json").exists())

    def test_rejects_non_exact_model_catalog_strings(self) -> None:
        cases = (
            (
                "numeric provider catalog",
                lambda receipt, contracts: receipt.__setitem__("provider_catalog", 123),
                "model catalog receipt lacks provider catalog provenance",
            ),
            (
                "numeric catalog source",
                lambda receipt, contracts: receipt.__setitem__("catalog_source", True),
                "model catalog receipt lacks provider catalog provenance",
            ),
            (
                "coerced provider row",
                lambda receipt, contracts: (
                    receipt["models"][0].__setitem__("provider", 123),
                    contracts["A"].__setitem__("provider", 123),
                ),
                "model catalog receipt model identity is not exact",
            ),
            (
                "coerced model row",
                lambda receipt, contracts: (
                    receipt["models"][0].__setitem__("model_id", 123),
                    contracts["A"].__setitem__("model_id", 123),
                ),
                "model catalog receipt model identity is not exact",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = ValidateReviewFixture(root)
                fixture.build()
                receipt = json.loads(fixture.catalog_receipt.read_text(encoding="utf-8"))
                contracts = json.loads(
                    (fixture.bundle_dir / "review_bundle.json").read_text(
                        encoding="utf-8"
                    )
                )["model_execution_contracts"]
                mutate(receipt, contracts)
                write_json(fixture.catalog_receipt, receipt)

                with self.assertRaisesRegex(ValueError, message):
                    VALIDATE.validate_catalog_receipt(
                        fixture.catalog_receipt,
                        contracts,
                    )

    def test_schema_version_checks_avoid_raw_comparisons(self) -> None:
        module = ast.parse(VALIDATE_SCRIPT.read_text(encoding="utf-8"))
        raw_schema_version_comparisons = [
            ast.unparse(node)
            for node in ast.walk(module)
            if isinstance(node, ast.Compare)
            and "schema_version" in ast.unparse(node)
        ]

        self.assertEqual(raw_schema_version_comparisons, [])

    def test_validation_receipt_is_born_private_create_only_and_fsynced(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "validation.json"
            with mock.patch.object(
                VALIDATE.os,
                "fsync",
                wraps=VALIDATE.os.fsync,
            ) as fsync:
                VALIDATE.write_validation_create_only(output, {"status": "passed"})

            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"status": "passed"},
            )
            self.assertEqual(fsync.call_count, 2)

            original = output.read_bytes()
            with self.assertRaisesRegex(ValueError, "validation.json already exists"):
                VALIDATE.write_validation_create_only(output, {"status": "failed"})
            self.assertEqual(output.read_bytes(), original)

    def test_validation_receipt_removes_partial_output_after_file_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "validation.json"

            with (
                mock.patch.object(
                    VALIDATE.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                VALIDATE.write_validation_create_only(output, {"status": "partial"})

            self.assertFalse(output.exists())

    def test_validation_receipt_removes_partial_output_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "validation.json"

            with (
                mock.patch.object(
                    VALIDATE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                VALIDATE.write_validation_create_only(output, {"status": "partial"})

            self.assertFalse(output.exists())

    def test_validation_receipt_rehashes_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "validation.json"
            real_fsync_directory = VALIDATE.fsync_directory

            def tamper_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    VALIDATE,
                    "fsync_directory",
                    side_effect=tamper_after_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "validation.json changed during write",
                ),
            ):
                VALIDATE.write_validation_create_only(output, {"status": "passed"})

            self.assertFalse(output.exists())

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
                VALIDATE.sha256(source_link)

            real_inputs = root / "real-inputs"
            real_inputs.mkdir()
            review_manifest = real_inputs / "review_manifest.json"
            review_manifest.write_text(
                '{"reviewer_id": "A"}\n',
                encoding="utf-8",
            )
            linked_inputs = root / "linked-inputs"
            linked_inputs.symlink_to(real_inputs, target_is_directory=True)

            with self.assertRaisesRegex(
                ValueError,
                "review_manifest.json SHA-256 input parent may not be a symlink",
            ):
                VALIDATE.sha256(linked_inputs / "review_manifest.json")

    def test_validation_receipt_rechecks_mode_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "validation.json"
            real_fsync_directory = VALIDATE.fsync_directory

            def relax_mode_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.chmod(0o644)

            with (
                mock.patch.object(
                    VALIDATE,
                    "fsync_directory",
                    side_effect=relax_mode_after_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "validation.json changed during write",
                ),
            ):
                VALIDATE.write_validation_create_only(output, {"status": "passed"})

            self.assertFalse(output.exists())

    def test_validation_receipt_refuses_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "review-real"
            real_parent.mkdir()
            linked_parent = root / "review-link"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "review directory.*symlink"):
                VALIDATE.write_validation_create_only(
                    linked_parent / "validation.json",
                    {"status": "passed"},
                )

            self.assertFalse((real_parent / "validation.json").exists())

    def test_validation_receipt_refuses_existing_dir_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "review-real"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "review-link"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = linked_parent / "existing" / "validation.json"

            with self.assertRaisesRegex(ValueError, "review directory.*symlink"):
                VALIDATE.write_validation_create_only(
                    output,
                    {"status": "passed"},
                )

            self.assertFalse((real_parent / "existing" / "validation.json").exists())

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

    def test_validates_forbidden_tokens_file_without_raw_token_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            forbidden_tokens = Path(temporary) / "forbidden_tokens.json"
            forbidden_tokens.write_text('["DirectIdentifier"]\n', encoding="utf-8")
            fixture.write_review(review)

            validated = fixture.validate(
                review,
                forbidden_token=None,
                forbidden_tokens_file=forbidden_tokens,
            )

            self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)
            self.assertTrue((review / "validation.json").exists())

    def test_rejects_bundle_with_duplicate_reviewer_model_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()

            for filename in ("review_bundle.json", "bundle_manifest.json"):
                path = fixture.bundle_dir / filename
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["model_execution_contracts"]["B"] = dict(
                    payload["model_execution_contracts"]["A"]
                )
                write_json(path, payload)
            bundle_path = fixture.bundle_dir / "review_bundle.json"
            bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            bundle_manifest = json.loads(
                bundle_manifest_path.read_text(encoding="utf-8")
            )
            bundle_manifest["review_bundle_sha256"] = sha256(bundle_path)
            write_json(bundle_manifest_path, bundle_manifest)

            review = Path(temporary) / "review-a"
            fixture.write_review(review)

            validated = fixture.validate(review)

            self.assertNotEqual(validated.returncode, 0)
            self.assertIn("distinct pinned models", validated.stderr)
            self.assertFalse((review / "validation.json").exists())

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
                fixture = ValidateReviewFixture(Path(temporary))
                fixture.build()

                path = fixture.bundle_dir / relative
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["legacy_note"] = "accepted"
                write_json(path, payload)

                if relative == "review_bundle.json":
                    bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
                    bundle_manifest = json.loads(
                        bundle_manifest_path.read_text(encoding="utf-8")
                    )
                    bundle_manifest["review_bundle_sha256"] = sha256(path)
                    write_json(bundle_manifest_path, bundle_manifest)

                review = Path(temporary) / "review-a"
                fixture.write_review(review)

                validated = fixture.validate(review)

                self.assertNotEqual(validated.returncode, 0)
                self.assertIn(message, validated.stderr)
                self.assertFalse((review / "validation.json").exists())

    def test_rejects_inexact_bundle_directory_before_validation(self) -> None:
        cases = (
            (
                "extra",
                lambda fixture, root: (
                    fixture.bundle_dir / "raw.fastq"
                ).write_text("stale raw input\n", encoding="utf-8"),
                "AI review bundle inventory is not exact",
            ),
            (
                "missing prompt",
                lambda fixture, root: (
                    fixture.bundle_dir / "reviewer-b.prompt.md"
                ).unlink(),
                "AI review bundle inventory is not exact",
            ),
            (
                "symlink prompt",
                lambda fixture, root: (
                    (fixture.bundle_dir / "reviewer-b.prompt.md").replace(
                        root / "reviewer-b.prompt.real.md",
                    ),
                    (fixture.bundle_dir / "reviewer-b.prompt.md").symlink_to(
                        root / "reviewer-b.prompt.real.md",
                    ),
                ),
                "AI review bundle file is missing, unsafe, or empty",
            ),
        )
        for name, mutate, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = ValidateReviewFixture(root)
                fixture.build()
                review = root / "review-a"
                fixture.write_review(review)
                mutate(fixture, root)

                validated = fixture.validate(review)

                self.assertNotEqual(validated.returncode, 0)
                self.assertIn(message, validated.stderr)
                self.assertFalse((review / "validation.json").exists())

    def test_rejects_review_manifest_with_non_exact_envelope(self) -> None:
        cases = (
            (
                "top-level",
                lambda manifest: manifest.__setitem__("legacy_note", "accepted"),
                "review manifest envelope is not exact",
            ),
            (
                "invocation",
                lambda manifest: manifest["invocation"].__setitem__(
                    "legacy_note",
                    "accepted",
                ),
                "review invocation envelope is not exact",
            ),
            (
                "boolean invocation ID",
                lambda manifest: manifest["invocation"].__setitem__(
                    "invocation_id",
                    True,
                ),
                "complete invocation metadata is required",
            ),
            (
                "padded interface",
                lambda manifest: manifest["invocation"].__setitem__(
                    "interface",
                    " offline-test-fixture",
                ),
                "complete invocation metadata is required",
            ),
            (
                "non-exact schema",
                lambda manifest: manifest.__setitem__("schema_version", 2.0),
                "review manifest schema or reviewer ID mismatch",
            ),
        )
        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = ValidateReviewFixture(Path(temporary))
                fixture.build()
                review = Path(temporary) / "review-a"
                fixture.write_review(review)

                review_manifest_path = review / "review_manifest.json"
                review_manifest = json.loads(
                    review_manifest_path.read_text(encoding="utf-8")
                )
                mutate(review_manifest)
                write_json(review_manifest_path, review_manifest)

                validated = fixture.validate(review)

                self.assertNotEqual(validated.returncode, 0)
                self.assertIn(message, validated.stderr)
                self.assertFalse((review / "validation.json").exists())

    def test_rejects_existing_validation_create_only_and_preserves_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(review)
            self.assertEqual(fixture.validate(review).returncode, 0)
            original = (review / "validation.json").read_bytes()

            write_claims(review / "claims.csv", proposed_state="positive")
            failed = fixture.validate(review)

            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("validation.json already exists", failed.stderr)
            self.assertEqual((review / "validation.json").read_bytes(), original)

    def test_rejects_hrd_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(review, proposed_state="positive")

            failed = fixture.validate(review)

            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("classification promotion", failed.stderr)

    def test_rejects_no_call_bundle_that_authorizes_classification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()

            source_path = fixture.manifests[0]
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["classification_authorized"] = True
            write_json(source_path, source)

            bundle_path = fixture.bundle_dir / "review_bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["evidence_sources"][0]["classification_authorized"] = True
            write_json(bundle_path, bundle)

            bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
            bundle_manifest["input_manifest_sha256"]["E001"] = sha256(source_path)
            bundle_manifest["review_bundle_sha256"] = sha256(bundle_path)
            write_json(bundle_manifest_path, bundle_manifest)

            review = Path(temporary) / "review-a"
            fixture.write_review(review)

            failed = fixture.validate(review)

            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("no_call evidence", failed.stderr)
            self.assertFalse((review / "validation.json").exists())

    def test_rejects_no_call_bundle_with_applicable_classification_qc(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()

            source_path = fixture.manifests[0]
            source = json.loads(source_path.read_text(encoding="utf-8"))
            source["classification_qc_status"] = "passed"
            write_json(source_path, source)

            bundle_path = fixture.bundle_dir / "review_bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["evidence_sources"][0]["classification_qc_status"] = "passed"
            write_json(bundle_path, bundle)

            bundle_manifest_path = fixture.bundle_dir / "bundle_manifest.json"
            bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
            bundle_manifest["input_manifest_sha256"]["E001"] = sha256(source_path)
            bundle_manifest["review_bundle_sha256"] = sha256(bundle_path)
            write_json(bundle_manifest_path, bundle_manifest)

            review = Path(temporary) / "review-a"
            fixture.write_review(review)

            failed = fixture.validate(review)

            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("mark classification QC as applicable", failed.stderr)
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
            (review / "validation.json").unlink(missing_ok=True)

            report = review / "report.md"
            report.write_text(
                report.read_text(encoding="utf-8").replace("3 coverage", "4 coverage"),
                encoding="utf-8",
            )
            mutate_claims(
                review / "claims.csv",
                lambda rows: rows[0].update({"claim": "The safe summary reports 4 coverage bins."}),
            )
            fixture.refresh_output_hashes(review)
            changed = fixture.validate(review)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("changes or invents", changed.stderr)

            (review / "validation.json").unlink(missing_ok=True)
            fixture.write_review(
                review,
                body="The safe summary reports three coverage bins [C001|E001].",
                claim="The safe summary reports three coverage bins.",
                quantitative_fact_ids="Q0002",
            )
            spelled = fixture.validate(review)
            self.assertNotEqual(spelled.returncode, 0)
            self.assertIn("spells out or derives", spelled.stderr)

            (review / "validation.json").unlink(missing_ok=True)
            fixture.write_review(
                review,
                body="The summary values must not be combined as 3 / 1.5% [C001|E001].",
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
        source = {
            "schema_version": 1.0,
            "report_sha256": "0" * 64,
        }
        with tempfile.TemporaryDirectory() as temporary:
            source_path = Path(temporary) / "report_manifest.json"
            write_json(source_path, source)

            with self.assertRaisesRegex(
                ValueError,
                "unsupported source-manifest schema for E001",
            ):
                VALIDATE.validate_source_manifests(
                    [source_path],
                    [{}],
                    {"E001": sha256(source_path)},
                )

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
            fixture.write_review(review)
            fixture.manifests[0].with_name("support.json").write_text(
                '{"changed": true}\n',
                encoding="utf-8",
            )

            tampered = fixture.validate(review)

            self.assertNotEqual(tampered.returncode, 0)
            self.assertIn("source support mismatch for E001", tampered.stderr)
            self.assertIn("support hash mismatch", tampered.stderr)
            self.assertFalse((review / "validation.json").exists())

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
            fixture.write_review(
                review,
                body="The evidence was copied from /private/results/sample.bam [C001|E001].",
            )

            leaked = fixture.validate(review)

            self.assertNotEqual(leaked.returncode, 0)
            self.assertIn("raw object, URI, or local path", leaked.stderr)

    def test_source_manifests_reject_non_exact_nested_hashes(self) -> None:
        digit_hash = "1" * 64
        letter_hash = "a" * 64
        cases = (
            (
                "numeric report",
                digit_hash,
                lambda source: source.__setitem__("report_sha256", int(digit_hash)),
                "source report E001",
            ),
            (
                "uppercase report",
                letter_hash,
                lambda source: source.__setitem__(
                    "report_sha256",
                    letter_hash.upper(),
                ),
                "source report E001",
            ),
            (
                "numeric source artifact",
                digit_hash,
                lambda source: source["source_sha256"].__setitem__(
                    "source.json",
                    int(digit_hash),
                ),
                "source artifact E001",
            ),
            (
                "uppercase source artifact",
                letter_hash,
                lambda source: source["source_sha256"].__setitem__(
                    "source.json",
                    letter_hash.upper(),
                ),
                "source artifact E001",
            ),
        )

        for label, valid_hash, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                report = root / "report.md"
                report.write_text("# Safe source report\n", encoding="utf-8")
                source_path = root / "report_manifest.json"
                source = {
                    "schema_version": 1,
                    "method_id": "deterministic_full_wgs",
                    "report_kind": "deterministic_baseline",
                    "evidence_status": "partial_evidence",
                    "authorized_hrd_state": "no_call",
                    "classification_authorized": False,
                    "classification_qc_status": "not_applicable",
                    "report_sha256": valid_hash,
                    "source_sha256": {"source.json": valid_hash},
                    "support_sha256": {"support.json": valid_hash},
                    "review_summary": {"scope": "safe synthetic source"},
                }
                mutate(source)
                write_json(source_path, source)
                evidence = [
                    {
                        "method_id": "deterministic_full_wgs",
                        "report_kind": "deterministic_baseline",
                        "evidence_status": "partial_evidence",
                        "authorized_hrd_state": "no_call",
                        "classification_authorized": False,
                        "classification_qc_status": "not_applicable",
                        "report_sha256": valid_hash,
                        "source_artifact_sha256": [valid_hash],
                        "review_summary": {"scope": "safe synthetic source"},
                    }
                ]

                with (
                    mock.patch.object(VALIDATE, "sha256", return_value=valid_hash),
                    mock.patch.object(
                        VALIDATE,
                        "validate_report_manifest_support",
                        return_value=None,
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "malformed SHA-256 for " + message,
                    ),
                ):
                    VALIDATE.validate_source_manifests(
                        [source_path],
                        evidence,
                        {"E001": valid_hash},
                    )

    def test_source_manifests_reject_malformed_source_artifact_ids(self) -> None:
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
                fixture = ValidateReviewFixture(Path(temporary))
                fixture.build()
                review = Path(temporary) / "review-a"
                fixture.update_manifest(
                    0,
                    {"source_sha256": {malformed: "a" * 64}},
                )
                fixture.refresh_source_manifest_hash(0)
                fixture.write_review(review)

                validated = fixture.validate(review)

                self.assertNotEqual(validated.returncode, 0)
                self.assertIn(
                    "malformed source-artifact ID for deterministic_full_wgs",
                    validated.stderr,
                )
                self.assertFalse((review / "validation.json").exists())

    def test_source_manifests_reject_duplicate_source_artifact_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review = Path(temporary) / "review-a"
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
            fixture.refresh_source_manifest_hash(0)
            fixture.write_review(review)

            validated = fixture.validate(review)

            self.assertNotEqual(validated.returncode, 0)
            self.assertIn(
                (
                    "duplicate JSON object name in report_manifest.json: "
                    "safe_summary"
                ),
                validated.stderr,
            )
            self.assertFalse((review / "validation.json").exists())

    def test_rejects_symlinked_review_manifest_at_parse_time(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = ValidateReviewFixture(root)
            fixture.build()
            review = root / "review-a"
            fixture.write_review(review)
            real_load_object = VALIDATE.load_object
            swapped = False

            def swap_review_manifest_before_parse(path: Path) -> dict:
                nonlocal swapped
                if path.name == "review_manifest.json" and not swapped:
                    relocated = root / "review_manifest.real.json"
                    path.rename(relocated)
                    path.symlink_to(relocated)
                    swapped = True
                return real_load_object(path)

            with (
                mock.patch.object(
                    VALIDATE,
                    "load_object",
                    side_effect=swap_review_manifest_before_parse,
                ),
                self.assertRaisesRegex(
                    SystemExit,
                    "review_manifest.json is missing or a symlink",
                ),
            ):
                VALIDATE.main(fixture.validate_argv(review))

            self.assertTrue(swapped)
            self.assertFalse((review / "validation.json").exists())

    def test_rejects_symlinked_custody_inputs(self) -> None:
        cases = (
            (
                lambda fixture, review, root: (root / "source-manifest-link.json").symlink_to(fixture.manifests[0]),
                lambda fixture, root: fixture.manifests.__setitem__(
                    0,
                    root / "source-manifest-link.json",
                ),
                "source manifest",
            ),
            (
                lambda fixture, review, root: (root / "bundle-link").symlink_to(fixture.bundle_dir, target_is_directory=True),
                lambda fixture, root: setattr(
                    fixture,
                    "bundle_dir",
                    root / "bundle-link",
                ),
                "bundle directory",
            ),
            (
                lambda fixture, review, root: (root / "catalog-link.json").symlink_to(fixture.catalog_receipt),
                lambda fixture, root: setattr(
                    fixture,
                    "catalog_receipt",
                    root / "catalog-link.json",
                ),
                "model catalog receipt",
            ),
            (
                lambda fixture, review, root: (root / "review-link").symlink_to(review, target_is_directory=True),
                lambda fixture, root: None,
                "review directory",
            ),
        )
        for link, mutate, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = ValidateReviewFixture(root)
                fixture.build()
                review = root / "review-a"
                fixture.write_review(review)
                link(fixture, review, root)
                mutate(fixture, root)

                failed = fixture.validate(root / "review-link" if message == "review directory" else review)

                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(message, failed.stderr)

    def test_rejects_custody_inputs_below_symlinked_parent(self) -> None:
        cases = (
            (
                "source manifest",
                "source manifest for E001",
                lambda fixture, review, root, linked_parent: (
                    shutil.copytree(fixture.manifests[0].parent, root / "real-source" / "existing"),
                    fixture.manifests.__setitem__(
                        0,
                        linked_parent / "existing" / "report_manifest.json",
                    ),
                    review,
                )[-1],
            ),
            (
                "bundle directory",
                "bundle directory",
                lambda fixture, review, root, linked_parent: (
                    shutil.copytree(fixture.bundle_dir, root / "real-source" / "existing"),
                    setattr(fixture, "bundle_dir", linked_parent / "existing"),
                    review,
                )[-1],
            ),
            (
                "model catalog receipt",
                "model catalog receipt",
                lambda fixture, review, root, linked_parent: (
                    (root / "real-source" / "existing").mkdir(),
                    shutil.copy2(
                        fixture.catalog_receipt,
                        root / "real-source" / "existing" / "model-catalog.json",
                    ),
                    setattr(
                        fixture,
                        "catalog_receipt",
                        linked_parent / "existing" / "model-catalog.json",
                    ),
                    review,
                )[-1],
            ),
            (
                "review directory",
                "review directory",
                lambda fixture, review, root, linked_parent: (
                    shutil.copytree(review, root / "real-source" / "existing"),
                    linked_parent / "existing",
                )[-1],
            ),
        )
        for name, message, mutate in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture = ValidateReviewFixture(root)
                fixture.build()
                review = root / "review-a"
                fixture.write_review(review)
                real_parent = root / "real-source"
                real_parent.mkdir(exist_ok=True)
                linked_parent = root / "linked-source"
                linked_parent.symlink_to(real_parent, target_is_directory=True)

                review_dir = mutate(fixture, review, root, linked_parent)
                failed = fixture.validate(review_dir)

                self.assertNotEqual(failed.returncode, 0)
                self.assertIn(f"{message} parent may not be a symlink", failed.stderr)
                self.assertFalse((review_dir / "validation.json").exists())

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

    def test_rejects_stale_or_tampered_review_after_validation_write(self) -> None:
        cases = (
            (
                "extra output",
                lambda review: (review / "notes.md").write_text(
                    "stale reviewer scratch\n",
                    encoding="utf-8",
                ),
                "validated review directory must contain exactly",
            ),
            (
                "tampered validation",
                lambda review: (review / "validation.json").write_text(
                    '{"status":"tampered"}\n',
                    encoding="utf-8",
                ),
                "validation.json changed during write",
            ),
        )

        for label, tamper, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture = ValidateReviewFixture(Path(temporary))
                fixture.build()
                review = Path(temporary) / "review-a"
                fixture.write_review(review)
                real_write = VALIDATE.write_validation_create_only

                def write_then_tamper(path: Path, validation: dict) -> str:
                    digest = real_write(path, validation)
                    tamper(review)
                    return digest

                with (
                    mock.patch.object(
                        VALIDATE,
                        "write_validation_create_only",
                        side_effect=write_then_tamper,
                    ),
                    self.assertRaisesRegex(SystemExit, message),
                ):
                    VALIDATE.main(fixture.validate_argv(review))

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
                body="The missing allele-specific copy-number gate remains unresolved [C001|E001].",
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

            (review_b / "validation.json").unlink()
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

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review_a = Path(temporary) / "review-a"
            fixture.write_review(review_a, reviewer="A")
            self.assertEqual(fixture.validate(review_a).returncode, 0)
            validation_path = review_a / "validation.json"
            validation = json.loads(validation_path.read_text(encoding="utf-8"))
            validation["schema_version"] = 2.0
            write_json(validation_path, validation)

            review_b = Path(temporary) / "review-b"
            fixture.write_review(
                review_b,
                reviewer="B",
                body="The missing allele-specific copy-number gate remains unresolved [C001|E001].",
                claim="The missing allele-specific copy number prevents a categorical conclusion.",
            )

            non_exact_other = fixture.validate(
                review_b,
                reviewer="B",
                other_review_dir=review_a,
            )

            self.assertNotEqual(non_exact_other.returncode, 0)
            self.assertIn(
                "other review is not a passed reviewer A validation",
                non_exact_other.stderr,
            )
            self.assertFalse((review_b / "validation.json").exists())

        with tempfile.TemporaryDirectory() as temporary:
            fixture = ValidateReviewFixture(Path(temporary))
            fixture.build()
            review_a = Path(temporary) / "review-a"
            fixture.write_review(review_a, reviewer="A")
            self.assertEqual(fixture.validate(review_a).returncode, 0)

            a_manifest_path = review_a / "review_manifest.json"
            a_manifest = json.loads(a_manifest_path.read_text(encoding="utf-8"))
            a_manifest["invocation"]["interface"] = True
            write_json(a_manifest_path, a_manifest)
            a_validation_path = review_a / "validation.json"
            a_validation = json.loads(a_validation_path.read_text(encoding="utf-8"))
            a_validation["review_manifest_sha256"] = sha256(a_manifest_path)
            write_json(a_validation_path, a_validation)

            review_b = Path(temporary) / "review-b"
            fixture.write_review(
                review_b,
                reviewer="B",
                body="The missing allele-specific copy-number gate remains unresolved [C001|E001].",
                claim="The missing allele-specific copy number prevents a categorical conclusion.",
            )

            malformed_other = fixture.validate(
                review_b,
                reviewer="B",
                other_review_dir=review_a,
            )

            self.assertNotEqual(malformed_other.returncode, 0)
            self.assertIn(
                "complete invocation metadata is required",
                malformed_other.stderr,
            )
            self.assertFalse((review_b / "validation.json").exists())

    def test_reviewer_b_rejects_symlinked_reviewer_a_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = ValidateReviewFixture(root)
            fixture.build()
            review_a = root / "review-a"
            fixture.write_review(review_a, reviewer="A")
            self.assertEqual(fixture.validate(review_a).returncode, 0)

            real_report = root / "reviewer-a-report.real.md"
            (review_a / "report.md").replace(real_report)
            (review_a / "report.md").symlink_to(real_report)

            review_b = root / "review-b"
            fixture.write_review(
                review_b,
                reviewer="B",
                body=("The missing allele-specific copy-number gate remains unresolved [C001|E001]."),
                claim=("The missing allele-specific copy number prevents a categorical conclusion."),
            )

            symlinked = fixture.validate(
                review_b,
                reviewer="B",
                other_review_dir=review_a,
            )

            self.assertNotEqual(symlinked.returncode, 0)
            self.assertIn(
                "complete validated reviewer A output",
                symlinked.stderr,
            )


if __name__ == "__main__":
    unittest.main()
