from __future__ import annotations

import json
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

import finalize_ai_review as FINALIZE  # noqa: E402
import build_ai_review_bundle as BUILD_BUNDLE  # noqa: E402
import publish_private_report as PUBLISH_PRIVATE  # noqa: E402

from tests.test_build_ai_review_bundle import write_json  # noqa: E402
from tests.test_validate_ai_review import ValidateReviewFixture  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_bound_review_bundle(fixture: ValidateReviewFixture, value: dict) -> None:
    bundle = fixture.bundle_dir / "review_bundle.json"
    write_json(bundle, value)
    bundle_manifest = load_json(fixture.bundle_dir / "bundle_manifest.json")
    for field in (
        "schema_version",
        "subject_alias",
        "authorized_hrd_state",
        "required_method_ids",
        "method_inventory",
        "method_inventory_sha256",
        "model_execution_contracts",
        "model_catalog_receipt_sha256",
    ):
        bundle_manifest[field] = value[field]
    bundle_manifest["review_bundle_sha256"] = FINALIZE.sha256(bundle)
    write_json(fixture.bundle_dir / "bundle_manifest.json", bundle_manifest)


def write_hash_bound_catalog_schema(
    fixture: ValidateReviewFixture,
    review_dir: Path,
    schema_version: object,
) -> None:
    catalog = load_json(fixture.catalog_receipt)
    catalog["schema_version"] = schema_version
    write_json(fixture.catalog_receipt, catalog)
    catalog_hash = FINALIZE.sha256(fixture.catalog_receipt)

    bundle_path = fixture.bundle_dir / "review_bundle.json"
    bundle = load_json(bundle_path)
    bundle["model_catalog_receipt_sha256"] = catalog_hash
    write_json(bundle_path, bundle)
    bundle_hash = FINALIZE.sha256(bundle_path)

    manifest_path = fixture.bundle_dir / "bundle_manifest.json"
    bundle_manifest = load_json(manifest_path)
    bundle_manifest["model_catalog_receipt_sha256"] = catalog_hash
    bundle_manifest["review_bundle_sha256"] = bundle_hash
    prompt_hashes = {}
    for role in ("A", "B"):
        prompt_path = fixture.bundle_dir / f"reviewer-{role.lower()}.prompt.md"
        prompt_path.write_text(
            BUILD_BUNDLE.prompt(
                role,
                bundle_hash,
                bundle_manifest["subject_alias"],
                bundle_manifest["model_execution_contracts"][role],
                bundle_manifest["method_inventory_sha256"],
            ),
            encoding="utf-8",
        )
        prompt_hashes[role] = FINALIZE.sha256(prompt_path)
    bundle_manifest["prompt_sha256"] = prompt_hashes
    write_json(manifest_path, bundle_manifest)

    review_manifest_path = review_dir / "review_manifest.json"
    review_manifest = load_json(review_manifest_path)
    review_manifest["prompt_sha256"] = prompt_hashes[review_manifest["reviewer_id"]]
    review_manifest["input_bundle_sha256"] = bundle_hash
    review_manifest["input_artifact_sha256"] = {
        "review_bundle.json": bundle_hash,
        f"reviewer-{review_manifest['reviewer_id'].lower()}.prompt.md": (
            prompt_hashes[review_manifest["reviewer_id"]]
        ),
    }
    write_json(review_manifest_path, review_manifest)
    review_manifest_hash = FINALIZE.sha256(review_manifest_path)

    validation_path = review_dir / "validation.json"
    validation = load_json(validation_path)
    validation["model_catalog_receipt_sha256"] = catalog_hash
    validation["review_bundle_sha256"] = bundle_hash
    validation["prompt_sha256"] = prompt_hashes[validation["reviewer_id"]]
    validation["review_manifest_sha256"] = review_manifest_hash
    write_json(validation_path, validation)


def refresh_review_manifest_validation_hash(review_dir: Path) -> None:
    validation_path = review_dir / "validation.json"
    validation = load_json(validation_path)
    validation["review_manifest_sha256"] = FINALIZE.sha256(
        review_dir / "review_manifest.json"
    )
    write_json(validation_path, validation)


class FinalizeAiReviewTests(unittest.TestCase):
    def execute(
        self,
        fixture: ValidateReviewFixture,
        review_dir: Path,
        *,
        reviewer: str = "A",
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "finalize_ai_review.py"),
                "--bundle-dir",
                str(fixture.bundle_dir),
                "--review-dir",
                str(review_dir),
                "--reviewer",
                reviewer,
                "--model-catalog-receipt",
                str(fixture.catalog_receipt),
                "--output",
                str(review_dir / "report_manifest.json"),
            ],
            text=True,
            capture_output=True,
        )

    def validated_review(
        self,
        temporary: str,
        *,
        reviewer: str = "A",
    ) -> tuple[ValidateReviewFixture, Path]:
        root = Path(temporary)
        fixture = ValidateReviewFixture(root)
        fixture.build()
        if reviewer == "B":
            review_a = root / "review-a"
            fixture.write_review(review_a, reviewer="A")
            validated_a = fixture.validate(review_a, reviewer="A")
            if validated_a.returncode != 0:
                raise AssertionError(validated_a.stderr + validated_a.stdout)
        review = root / f"review-{reviewer.lower()}"
        fixture.write_review(
            review,
            reviewer=reviewer,
            body=(
                "Reviewer B independently keeps the coverage evidence "
                "descriptive [C001|E001]."
            )
            if reviewer == "B"
            else (
                "The coverage evidence is descriptive and not allele-specific "
                "[C001|E001]."
            ),
            claim=(
                "The coverage signal remains descriptive in reviewer B."
                if reviewer == "B"
                else (
                    "The coverage signal is a descriptive proxy and not "
                    "allele-specific copy number."
                )
            ),
        )
        validated = fixture.validate(
            review,
            reviewer=reviewer,
            other_review_dir=root / "review-a" if reviewer == "B" else None,
        )
        if validated.returncode != 0:
            raise AssertionError(validated.stderr + validated.stdout)
        return fixture, review

    def test_final_manifest_is_born_private_create_only_and_fsynced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report_manifest.json"
            with mock.patch.object(
                FINALIZE.os,
                "fsync",
                wraps=FINALIZE.os.fsync,
            ) as fsync:
                FINALIZE.write_create_only(output, {"status": "passed"})

            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(
                load_json(output),
                {"status": "passed"},
            )
            self.assertEqual(fsync.call_count, 2)

            original = output.read_bytes()
            with self.assertRaisesRegex(
                ValueError,
                "report_manifest.json already exists",
            ):
                FINALIZE.write_create_only(output, {"status": "failed"})
            self.assertEqual(output.read_bytes(), original)

    def test_final_manifest_removes_partial_output_after_file_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report_manifest.json"

            with (
                mock.patch.object(
                    FINALIZE.os,
                    "fsync",
                    side_effect=OSError("synthetic file fsync failure"),
                ),
                self.assertRaisesRegex(OSError, "synthetic file fsync failure"),
            ):
                FINALIZE.write_create_only(output, {"status": "partial"})

            self.assertFalse(output.exists())

    def test_final_manifest_removes_partial_output_after_directory_fsync_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report_manifest.json"

            with (
                mock.patch.object(
                    FINALIZE.os,
                    "fsync",
                    side_effect=(None, OSError("synthetic directory fsync failure")),
                ),
                self.assertRaisesRegex(OSError, "synthetic directory fsync failure"),
            ):
                FINALIZE.write_create_only(output, {"status": "partial"})

            self.assertFalse(output.exists())

    def test_final_manifest_rehashes_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report_manifest.json"
            real_fsync_directory = FINALIZE.fsync_directory

            def tamper_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.write_text('{"status":"tampered"}\n', encoding="utf-8")

            with (
                mock.patch.object(
                    FINALIZE,
                    "fsync_directory",
                    side_effect=tamper_after_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json changed during write",
                ),
            ):
                FINALIZE.write_create_only(output, {"status": "passed"})

            self.assertFalse(output.exists())

    def test_final_manifest_rechecks_mode_after_directory_fsync(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report_manifest.json"
            real_fsync_directory = FINALIZE.fsync_directory

            def relax_mode_after_directory_fsync(path: Path) -> None:
                real_fsync_directory(path)
                output.chmod(0o644)

            with (
                mock.patch.object(
                    FINALIZE,
                    "fsync_directory",
                    side_effect=relax_mode_after_directory_fsync,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json changed during write",
                ),
            ):
                FINALIZE.write_create_only(output, {"status": "passed"})

            self.assertFalse(output.exists())

    def test_final_manifest_refuses_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_parent = root / "review-real"
            real_parent.mkdir()
            linked_parent = root / "review-link"
            linked_parent.symlink_to(real_parent, target_is_directory=True)

            with self.assertRaisesRegex(ValueError, "output path may not be a symlink"):
                FINALIZE.write_create_only(
                    linked_parent / "report_manifest.json",
                    {"status": "passed"},
                )

            self.assertFalse((real_parent / "report_manifest.json").exists())

    def test_final_manifest_refuses_existing_dir_below_symlinked_parent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            real_parent = root / "review-real"
            (real_parent / "existing").mkdir(parents=True)
            linked_parent = root / "review-link"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            output = linked_parent / "existing" / "report_manifest.json"

            with self.assertRaisesRegex(ValueError, "output path may not be a symlink"):
                FINALIZE.write_create_only(
                    output,
                    {"status": "passed"},
                )

            self.assertFalse(
                (real_parent / "existing" / "report_manifest.json").exists()
            )

    def test_wraps_passed_ai_review_for_private_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)

            finalized = self.execute(fixture, review)

            self.assertEqual(finalized.returncode, 0, finalized.stderr)
            manifest = load_json(review / "report_manifest.json")
            self.assertEqual(manifest["method_id"], "ai_review_reviewer_a")
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertFalse(manifest["classification_authorized"])
            self.assertEqual(
                set(manifest["support_sha256"]),
                {"claims.csv", "review_manifest.json", "validation.json"},
            )
            self.assertEqual(manifest["review_summary"]["reviewer_id"], "A")
            self.assertEqual(
                manifest["source_sha256"]["review_bundle.json"],
                FINALIZE.sha256(fixture.bundle_dir / "review_bundle.json"),
            )
            rows = PUBLISH_PRIVATE.validate_packet_dir(
                review,
                "ai_review_reviewer_a",
                ("DirectIdentifier",),
            )
            self.assertEqual([row["relative_path"] for row in rows], sorted(
                {
                    "claims.csv",
                    "report.md",
                    "report_manifest.json",
                    "review_manifest.json",
                    "validation.json",
                }
            ))

    def test_reviewer_b_uses_distinct_method_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary, reviewer="B")

            finalized = self.execute(fixture, review, reviewer="B")

            self.assertEqual(finalized.returncode, 0, finalized.stderr)
            manifest = load_json(review / "report_manifest.json")
            self.assertEqual(manifest["method_id"], "ai_review_reviewer_b")
            self.assertEqual(manifest["review_summary"]["reviewer_id"], "B")

    def test_refuses_stale_validation_or_output_outside_review_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            (review / "report.md").write_text("changed\n", encoding="utf-8")
            outside_report = Path(temporary) / "report_manifest.json"
            outside_report.write_text("keep me\n", encoding="utf-8")

            stale = self.execute(fixture, review)
            outside = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "finalize_ai_review.py"),
                    "--bundle-dir",
                    str(fixture.bundle_dir),
                    "--review-dir",
                    str(review),
                    "--reviewer",
                    "A",
                    "--model-catalog-receipt",
                    str(fixture.catalog_receipt),
                    "--output",
                    str(Path(temporary) / "report_manifest.json"),
                ],
                text=True,
                capture_output=True,
            )

            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("output hashes", stale.stderr)
            self.assertNotEqual(outside.returncode, 0)
            self.assertIn("output must be report_manifest", outside.stderr)
            self.assertEqual(outside_report.read_text(encoding="utf-8"), "keep me\n")

    def test_rejects_malformed_validation_counts(self) -> None:
        cases = (
            ("claim_count", True),
            ("disagreement_claim_count", False),
            ("disagreement_claim_count", 999),
        )

        for field, value in cases:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                fixture, review = self.validated_review(temporary)
                validation_path = review / "validation.json"
                validation = load_json(validation_path)
                validation[field] = value
                write_json(validation_path, validation)

                finalized = self.execute(fixture, review)

                self.assertNotEqual(finalized.returncode, 0)
                self.assertIn("review validation counts are not exact", finalized.stderr)
                self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_stale_validation_claim_summary(self) -> None:
        cases = (
            (
                "claim_count",
                lambda validation: validation.__setitem__(
                    "claim_count",
                    validation["claim_count"] + 1,
                ),
            ),
            (
                "disagreement_claim_count",
                lambda validation: validation.__setitem__(
                    "disagreement_claim_count",
                    validation["disagreement_claim_count"] + 1,
                ),
            ),
            (
                "covered_evidence_ids",
                lambda validation: validation.__setitem__(
                    "covered_evidence_ids",
                    validation["covered_evidence_ids"][:-1],
                ),
            ),
        )

        for label, mutate in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture, review = self.validated_review(temporary)
                validation_path = review / "validation.json"
                validation = load_json(validation_path)
                mutate(validation)
                write_json(validation_path, validation)

                finalized = self.execute(fixture, review)

                self.assertNotEqual(finalized.returncode, 0)
                self.assertIn("review validation claim summary is stale", finalized.stderr)
                self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_extra_review_file_before_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            (review / "notes.md").write_text("stale scratch\n", encoding="utf-8")

            finalized = self.execute(fixture, review)

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("review directory inventory is not exact", finalized.stderr)
            self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_stale_support_after_final_manifest_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            real_write_create_only = FINALIZE.write_create_only

            def tamper_after_manifest_write(path: Path, value: dict) -> None:
                real_write_create_only(path, value)
                (review / "claims.csv").write_text("claim,changed\n", encoding="utf-8")

            with (
                mock.patch.object(
                    FINALIZE,
                    "write_create_only",
                    side_effect=tamper_after_manifest_write,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "support hash mismatch for ai_review_reviewer_a: claims.csv",
                ),
            ):
                FINALIZE.finalize(
                    fixture.bundle_dir,
                    review,
                    "A",
                    fixture.catalog_receipt,
                    review / "report_manifest.json",
                )

            self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_stale_source_after_final_manifest_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            real_write_create_only = FINALIZE.write_create_only

            def tamper_after_manifest_write(path: Path, value: dict) -> str:
                digest = real_write_create_only(path, value)
                (fixture.bundle_dir / "reviewer-a.prompt.md").write_text(
                    "stale reviewer prompt\n",
                    encoding="utf-8",
                )
                return digest

            with (
                mock.patch.object(
                    FINALIZE,
                    "write_create_only",
                    side_effect=tamper_after_manifest_write,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "AI review source hashes are not exact",
                ),
            ):
                FINALIZE.finalize(
                    fixture.bundle_dir,
                    review,
                    "A",
                    fixture.catalog_receipt,
                    review / "report_manifest.json",
                )

            self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_stale_final_manifest_after_support_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            real_validate_report_manifest_support = (
                FINALIZE.validate_report_manifest_support
            )

            def tamper_after_support_validation(
                packet_dir: Path,
                manifest: dict,
                method: str,
            ) -> None:
                real_validate_report_manifest_support(packet_dir, manifest, method)
                (review / "report_manifest.json").write_text(
                    '{"changed": true}\n',
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    FINALIZE,
                    "validate_report_manifest_support",
                    side_effect=tamper_after_support_validation,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "report_manifest.json changed during write",
                ),
            ):
                FINALIZE.finalize(
                    fixture.bundle_dir,
                    review,
                    "A",
                    fixture.catalog_receipt,
                    review / "report_manifest.json",
                )

            self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_report_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            (review / "report_manifest.json").mkdir()

            finalized = self.execute(fixture, review)

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("report_manifest.json already exists", finalized.stderr)

    def test_rejects_symlinked_review_manifest_after_file_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            real_require_file = FINALIZE.require_file
            swapped = False

            def swap_manifest_after_file_audit(path: Path, label: str) -> None:
                nonlocal swapped
                real_require_file(path, label)
                if label == "model_catalog_receipt.json" and not swapped:
                    review_manifest = review / "review_manifest.json"
                    relocated = review.parent / "review_manifest.real.json"
                    review_manifest.rename(relocated)
                    review_manifest.symlink_to(relocated)
                    swapped = True

            with (
                mock.patch.object(
                    FINALIZE,
                    "require_file",
                    side_effect=swap_manifest_after_file_audit,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "review manifest must be a non-empty real file",
                ),
            ):
                FINALIZE.finalize(
                    fixture.bundle_dir,
                    review,
                    "A",
                    fixture.catalog_receipt,
                    review / "report_manifest.json",
                )

            self.assertFalse((review / "report_manifest.json").exists())

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
                FINALIZE.sha256(source_link)

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
                FINALIZE.sha256(linked_inputs / "review_manifest.json")

    def test_sha256_rejects_hash_input_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "input.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")
            real_read_bytes = Path.read_bytes
            calls = 0

            def mutating_read_bytes(path: Path) -> bytes:
                nonlocal calls
                data = real_read_bytes(path)
                calls += 1
                if calls == 1:
                    input_path.write_text(
                        '{"status": "mutated"}\n',
                        encoding="utf-8",
                    )
                return data

            with mock.patch.object(Path, "read_bytes", mutating_read_bytes):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    FINALIZE.sha256(input_path)

    def test_load_object_rejects_json_input_that_changes_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            input_path = Path(temporary) / "input.json"
            input_path.write_text('{"status": "ready"}\n', encoding="utf-8")
            real_read_bytes = Path.read_bytes
            calls = 0

            def mutating_read_bytes(path: Path) -> bytes:
                nonlocal calls
                data = real_read_bytes(path)
                calls += 1
                if calls == 1:
                    input_path.write_text(
                        '{"status": "mutated"}\n',
                        encoding="utf-8",
                    )
                return data

            with mock.patch.object(Path, "read_bytes", mutating_read_bytes):
                with self.assertRaisesRegex(ValueError, "changed during read"):
                    FINALIZE.load_object(input_path, "input")

    def test_final_manifest_binds_parsed_validation_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            validation_path = review / "validation.json"
            expected_validation_hash = FINALIZE.sha256(validation_path)
            real_load_object_with_sha256 = FINALIZE.load_object_with_sha256

            def mutate_validation_after_read(
                path: Path,
                label: str,
            ) -> tuple[dict[str, object], str]:
                value, digest = real_load_object_with_sha256(path, label)
                if path == validation_path:
                    validation = load_json(validation_path)
                    validation["status"] = "failed"
                    write_json(validation_path, validation)
                return value, digest

            with mock.patch.object(
                FINALIZE,
                "load_object_with_sha256",
                side_effect=mutate_validation_after_read,
            ):
                manifest = FINALIZE.build_manifest(
                    fixture.bundle_dir,
                    review,
                    "A",
                    fixture.catalog_receipt,
                )

        self.assertEqual(
            manifest["support_sha256"]["validation.json"],
            expected_validation_hash,
        )
        self.assertEqual(
            manifest["source_sha256"]["validation.json"],
            expected_validation_hash,
        )

    def test_final_manifest_rechecks_bundle_envelopes_after_manifest_preflight(
        self,
    ) -> None:
        for filename, message in (
            ("review_bundle.json", "AI review bundle envelope is not exact"),
            (
                "bundle_manifest.json",
                "AI review bundle manifest envelope is not exact",
            ),
        ):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                fixture, review = self.validated_review(temporary)
                real_require_bundle_manifest = FINALIZE.require_bundle_manifest

                def mutate_after_manifest_preflight(bundle_dir: Path) -> None:
                    real_require_bundle_manifest(bundle_dir)
                    path = bundle_dir / filename
                    payload = load_json(path)
                    payload["legacy_note"] = "accepted after preflight"
                    write_json(path, payload)

                with (
                    mock.patch.object(
                        FINALIZE,
                        "require_bundle_manifest",
                        side_effect=mutate_after_manifest_preflight,
                    ),
                    self.assertRaisesRegex(ValueError, message),
                ):
                    FINALIZE.finalize(
                        fixture.bundle_dir,
                        review,
                        "A",
                        fixture.catalog_receipt,
                        review / "report_manifest.json",
                    )

                self.assertFalse((review / "report_manifest.json").exists())

    def test_final_manifest_parses_claims_from_stable_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            claims_path = review / "claims.csv"
            expected_claims_hash = FINALIZE.sha256(claims_path)
            real_read_stable_text_with_sha256 = (
                FINALIZE.read_stable_text_with_sha256
            )

            def mutate_claims_after_read(
                path: Path,
                label: str,
            ) -> tuple[str, str]:
                text, digest = real_read_stable_text_with_sha256(path, label)
                if path == claims_path:
                    claims_path.write_text(
                        "claim_id,changed\nC001,stale\n",
                        encoding="utf-8",
                    )
                return text, digest

            with mock.patch.object(
                FINALIZE,
                "read_stable_text_with_sha256",
                side_effect=mutate_claims_after_read,
            ):
                manifest = FINALIZE.build_manifest(
                    fixture.bundle_dir,
                    review,
                    "A",
                    fixture.catalog_receipt,
                )

        self.assertEqual(manifest["support_sha256"]["claims.csv"], expected_claims_hash)
        self.assertEqual(manifest["source_sha256"]["claims.csv"], expected_claims_hash)

    def test_rejects_symlinked_hash_inputs_after_file_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            real_require_file = FINALIZE.require_file
            swapped = False

            def swap_claims_after_file_audit(path: Path, label: str) -> None:
                nonlocal swapped
                real_require_file(path, label)
                if label == "model_catalog_receipt.json" and not swapped:
                    claims = review / "claims.csv"
                    relocated = review.parent / "claims.real.csv"
                    claims.rename(relocated)
                    claims.symlink_to(relocated)
                    swapped = True

            with (
                mock.patch.object(
                    FINALIZE,
                    "require_file",
                    side_effect=swap_claims_after_file_audit,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "claims.csv SHA-256 input must be a real file",
                ),
            ):
                FINALIZE.finalize(
                    fixture.bundle_dir,
                    review,
                    "A",
                    fixture.catalog_receipt,
                    review / "report_manifest.json",
                )

            self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_symlinked_custody_inputs(self) -> None:
        cases = (
            ("bundle directory", "bundle directory", "bundle"),
            ("bundle directory parent", "bundle directory parent", "bundle-parent"),
            ("review directory", "review directory", "review"),
            ("review directory parent", "review directory parent", "review-parent"),
            ("model catalog receipt", "model catalog receipt", "catalog"),
            (
                "model catalog receipt parent",
                "model catalog receipt parent",
                "catalog-parent",
            ),
        )

        for label, message, target in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fixture, review = self.validated_review(temporary)
                if target == "bundle":
                    real_bundle = root / "bundle-real"
                    fixture.bundle_dir.rename(real_bundle)
                    fixture.bundle_dir.symlink_to(
                        real_bundle,
                        target_is_directory=True,
                    )
                elif target == "bundle-parent":
                    real_parent = root / "bundle-real-parent"
                    real_parent.mkdir()
                    real_bundle = real_parent / "bundle"
                    fixture.bundle_dir.rename(real_bundle)
                    linked_parent = root / "bundle-linked-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    fixture.bundle_dir = linked_parent / "bundle"
                elif target == "review":
                    real_review = root / "review-a-real"
                    review.rename(real_review)
                    review.symlink_to(real_review, target_is_directory=True)
                elif target == "review-parent":
                    real_parent = root / "review-real-parent"
                    real_parent.mkdir()
                    real_review = real_parent / "review-a"
                    review.rename(real_review)
                    linked_parent = root / "review-linked-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    review = linked_parent / "review-a"
                elif target == "catalog-parent":
                    real_parent = root / "catalog-real-parent"
                    real_parent.mkdir()
                    real_receipt = real_parent / "model-catalog-receipt.json"
                    fixture.catalog_receipt.rename(real_receipt)
                    linked_parent = root / "catalog-linked-parent"
                    linked_parent.symlink_to(
                        real_parent,
                        target_is_directory=True,
                    )
                    fixture.catalog_receipt = (
                        linked_parent / "model-catalog-receipt.json"
                    )
                else:
                    real_receipt = root / "model-catalog-receipt-real.json"
                    fixture.catalog_receipt.rename(real_receipt)
                    fixture.catalog_receipt.symlink_to(real_receipt)

                finalized = self.execute(fixture, review)

                self.assertNotEqual(finalized.returncode, 0)
                self.assertIn(message, finalized.stderr)
                self.assertFalse((review / "report_manifest.json").exists())

    def test_refuses_to_replace_existing_report_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            manifest = review / "report_manifest.json"
            manifest.write_text("keep me\n", encoding="utf-8")

            finalized = self.execute(fixture, review)

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("report_manifest.json already exists", finalized.stderr)
            self.assertEqual(manifest.read_text(encoding="utf-8"), "keep me\n")

    def test_rejects_non_integer_validated_review_schemas(self) -> None:
        cases = (
            "review_manifest.json",
            "validation.json",
        )
        for filename in cases:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                fixture, review = self.validated_review(temporary)
                path = review / filename
                payload = load_json(path)
                payload["schema_version"] = 2.0
                write_json(path, payload)

                finalized = self.execute(fixture, review)

                self.assertNotEqual(finalized.returncode, 0)
                self.assertIn(
                    "review and validation schemas must both be version 2",
                    finalized.stderr,
                )
                self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_model_catalog_and_bundle_drift(self) -> None:
        for mutate, message in (
            (
                lambda fixture, review: write_json(
                    fixture.catalog_receipt,
                    {"schema_version": 2},
                ),
                "model catalog receipt binding",
            ),
            (
                lambda fixture, review: write_hash_bound_catalog_schema(
                    fixture,
                    review,
                    1.0,
                ),
                "model catalog receipt binding",
            ),
            (
                lambda fixture, review: (
                    write_bound_review_bundle(
                        fixture,
                        {
                            **load_json(fixture.bundle_dir / "review_bundle.json"),
                            "required_method_ids": ["deterministic_full_wgs"],
                        },
                    )
                ),
                "review input inventory",
            ),
            (
                lambda fixture, review: (
                    write_json(
                        fixture.bundle_dir / "bundle_manifest.json",
                        {
                            **load_json(fixture.bundle_dir / "bundle_manifest.json"),
                            "prompt_sha256": {
                                **load_json(
                                    fixture.bundle_dir / "bundle_manifest.json"
                                )["prompt_sha256"],
                                "B": "0" * 64,
                            },
                        },
                    )
                ),
                "AI review bundle manifest is stale for reviewer-b.prompt.md",
            ),
            (
                lambda fixture, review: (
                    write_json(
                        review / "validation.json",
                        {
                            **load_json(review / "validation.json"),
                            "method_inventory": {
                                "inventory_id": "stale-reviewer-inventory",
                                "ordered_method_ids": ["deterministic_full_wgs"],
                            },
                        },
                    )
                ),
                "review validation method inventory binding",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                fixture, review = self.validated_review(temporary)
                mutate(fixture, review)

                finalized = self.execute(fixture, review)

                self.assertNotEqual(finalized.returncode, 0)
                self.assertIn(message, finalized.stderr)
                self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_non_exact_review_manifest_or_validation_envelope(self) -> None:
        cases = (
            (
                "review_manifest",
                lambda review: write_json(
                    review / "review_manifest.json",
                    {
                        **load_json(review / "review_manifest.json"),
                        "legacy_note": "accepted",
                    },
                ),
                "review manifest envelope is not exact",
            ),
            (
                "validation",
                lambda review: write_json(
                    review / "validation.json",
                    {
                        **load_json(review / "validation.json"),
                        "legacy_note": "accepted",
                    },
                ),
                "validation envelope is not exact",
            ),
        )
        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture, review = self.validated_review(temporary)
                mutate(review)

                finalized = self.execute(fixture, review)

                self.assertNotEqual(finalized.returncode, 0)
                self.assertIn(message, finalized.stderr)
                self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_non_exact_invocation_metadata_after_validation(
        self,
    ) -> None:
        cases = (
            (
                "missing_field",
                lambda invocation: {
                    key: value
                    for key, value in invocation.items()
                    if key != "invocation_id"
                },
                "review invocation envelope is not exact",
            ),
            (
                "extra_field",
                lambda invocation: {
                    **invocation,
                    "legacy_invocation_id": invocation["invocation_id"],
                },
                "review invocation envelope is not exact",
            ),
            (
                "empty_field",
                lambda invocation: {
                    **invocation,
                    "invocation_id": "",
                },
                "complete invocation metadata is required",
            ),
            (
                "padded_field",
                lambda invocation: {
                    **invocation,
                    "invocation_id": f" {invocation['invocation_id']} ",
                },
                "complete invocation metadata is required",
            ),
            (
                "non_string_field",
                lambda invocation: {
                    **invocation,
                    "invocation_id": True,
                },
                "complete invocation metadata is required",
            ),
        )

        for label, mutate, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                fixture, review = self.validated_review(temporary)
                review_manifest_path = review / "review_manifest.json"
                review_manifest = load_json(review_manifest_path)
                review_manifest["invocation"] = mutate(review_manifest["invocation"])
                write_json(review_manifest_path, review_manifest)
                refresh_review_manifest_validation_hash(review)

                finalized = self.execute(fixture, review)

                self.assertNotEqual(finalized.returncode, 0)
                self.assertIn(message, finalized.stderr)
                self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_duplicate_object_names_in_review_json_after_validation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            review_manifest_path = review / "review_manifest.json"
            raw = review_manifest_path.read_text(encoding="utf-8")
            duplicate_schema = raw.replace(
                "{\n",
                '{\n  "schema_version": 2,\n',
                1,
            )
            self.assertNotEqual(duplicate_schema, raw)
            review_manifest_path.write_text(duplicate_schema, encoding="utf-8")
            refresh_review_manifest_validation_hash(review)

            finalized = self.execute(fixture, review)

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn(
                "duplicate JSON object name in review manifest",
                finalized.stderr,
            )
            self.assertFalse((review / "report_manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
