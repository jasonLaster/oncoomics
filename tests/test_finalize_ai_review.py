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
import publish_private_report as PUBLISH_PRIVATE  # noqa: E402

from tests.test_build_ai_review_bundle import write_json  # noqa: E402
from tests.test_validate_ai_review import ValidateReviewFixture  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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

    def test_rejects_extra_review_file_before_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            (review / "notes.md").write_text("stale scratch\n", encoding="utf-8")

            finalized = self.execute(fixture, review)

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("review directory inventory is not exact", finalized.stderr)
            self.assertFalse((review / "report_manifest.json").exists())

    def test_rejects_report_manifest_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture, review = self.validated_review(temporary)
            (review / "report_manifest.json").mkdir()

            finalized = self.execute(fixture, review)

            self.assertNotEqual(finalized.returncode, 0)
            self.assertIn("report_manifest.json already exists", finalized.stderr)

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
                lambda fixture, review: (
                    write_json(
                        fixture.bundle_dir / "review_bundle.json",
                        {
                            **load_json(fixture.bundle_dir / "review_bundle.json"),
                            "required_method_ids": ["deterministic_full_wgs"],
                        },
                    )
                ),
                "review input inventory",
            ),
        ):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                fixture, review = self.validated_review(temporary)
                mutate(fixture, review)

                finalized = self.execute(fixture, review)

                self.assertNotEqual(finalized.returncode, 0)
                self.assertIn(message, finalized.stderr)


if __name__ == "__main__":
    unittest.main()
