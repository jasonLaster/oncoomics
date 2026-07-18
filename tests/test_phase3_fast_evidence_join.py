from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.test_phase3_fast_bam_qc_run import MaterializingSamtoolsRunner as BamQcRunner
from tests.test_phase3_fast_bam_qc_run import phase3_fast_bam_qc_plan
from tests.test_phase3_fast_cnv_evidence_run import MaterializingBedcovRunner, phase3_fast_cnv_evidence_plan
from tests.test_phase3_fast_filter_mutect_run import FilterMutectRunner, filter_plan_and_parabricks_receipt
from tests.test_phase3_fast_input_manifest import SHA_1
from tests.test_phase3_fast_small_variant_export import SHA_2, SHA_3
from tests.test_phase3_fast_sv_evidence_run import MaterializingSamtoolsRunner as SvEvidenceRunner
from tests.test_phase3_fast_sv_evidence_run import phase3_fast_sv_evidence_plan

from diana_omics.commands.phase3_wgs import export_phase3_fast_small_variant_artifacts as export_small_variants
from diana_omics.commands.phase3_wgs import join_phase3_fast_evidence as join_evidence
from diana_omics.commands.phase3_wgs import run_phase3_fast_bam_qc as run_bam_qc
from diana_omics.commands.phase3_wgs import run_phase3_fast_cnv_evidence as run_cnv
from diana_omics.commands.phase3_wgs import run_phase3_fast_filter_mutect as run_filter
from diana_omics.commands.phase3_wgs import run_phase3_fast_sv_evidence as run_sv
from diana_omics.utils import write_json

SHA_4 = "d" * 64
SHA_5 = "e" * 64
SHA_6 = "f" * 64
SHA_7 = "1" * 64


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase3_fast_receipts(root: Path) -> tuple[dict, dict, dict, dict]:
    filter_plan, parabricks_receipt = filter_plan_and_parabricks_receipt(root)
    filter_receipt = run_filter.run_phase3_fast_filter_mutect(
        filter_plan,
        parabricks_receipt,
        runner=FilterMutectRunner(),
        filter_mutect_plan_sha256=SHA_1,
        parabricks_mutect_receipt_sha256=SHA_2,
    )
    small_variant_export = export_small_variants.export_phase3_fast_small_variant_artifacts(
        parabricks_receipt,
        filter_receipt,
        parabricks_mutect_receipt_sha256=SHA_2,
        filter_mutect_receipt_sha256=SHA_3,
        output_root=root / "small_variant_export",
    )
    bam_qc_receipt = run_bam_qc.run_phase3_fast_bam_qc(
        phase3_fast_bam_qc_plan(root),
        runner=BamQcRunner(),
        bam_qc_plan_sha256=SHA_4,
    )
    cnv_evidence_receipt = run_cnv.run_phase3_fast_cnv_evidence(
        phase3_fast_cnv_evidence_plan(root),
        runner=MaterializingBedcovRunner(),
        cnv_evidence_plan_sha256=SHA_5,
    )
    sv_evidence_receipt = run_sv.run_phase3_fast_sv_evidence(
        phase3_fast_sv_evidence_plan(root),
        runner=SvEvidenceRunner(),
        sv_evidence_plan_sha256=SHA_6,
    )
    return small_variant_export, bam_qc_receipt, cnv_evidence_receipt, sv_evidence_receipt


class Phase3FastEvidenceJoinTests(unittest.TestCase):
    def test_joins_completed_receipts_into_pointer_only_no_call_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = phase3_fast_receipts(Path(tmp))

            manifest = join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

        self.assertEqual("phase3_wgs_fast_evidence_join_manifest", manifest["manifest_type"])
        self.assertEqual("completed", manifest["status"])
        self.assertEqual("phase3_wgs_fast", manifest["workflow"]["name"])
        self.assertEqual("no_call", manifest["interpretation"]["authorized_hrd_state"])
        self.assertEqual("deterministic_sample_evidence_not_scalar_hrd", manifest["interpretation"]["small_variants_use"])
        self.assertEqual("qc_only_not_hrd_evidence", manifest["interpretation"]["bam_qc_use"])
        self.assertEqual("no_call_requires_allele_specific_cnv_loh_segments", manifest["interpretation"]["scarhrd_use"])
        self.assertEqual("no_call_requires_validated_production_sv_caller_vcf", manifest["interpretation"]["chord_use"])
        self.assertEqual("no_call_requires_validated_structural_variant_features", manifest["interpretation"]["hrdetect_use"])
        self.assertEqual(SHA_1, manifest["source"]["receipt_sha256"]["small_variant_artifact_export"])
        self.assertIn("filter_mutect", manifest["evidence"]["small_variants"]["exports"])
        self.assertIn("tumor", manifest["evidence"]["bam_qc"]["materialized_outputs"])
        self.assertIn("coverage_bins", manifest["evidence"]["cnv_evidence"]["materialized_outputs"])
        self.assertEqual(7, manifest["evidence"]["sv_evidence"]["metrics"]["tumor"]["supplementary_alignments"])
        self.assertEqual("copy-version-5", manifest["input_sources"]["reference"]["fasta"]["version_id"])
        self.assertEqual("copy-version-8", manifest["input_sources"]["caller_resources"]["common_sites_index"]["version_id"])
        self.assertNotIn("commands", manifest)
        self.assertNotIn("inputs", manifest)

    def test_environment_command_writes_manifest_with_receipt_hashes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            small_path = root / "small-export.json"
            bam_path = root / "bam-qc.json"
            cnv_path = root / "cnv.json"
            sv_path = root / "sv.json"
            output_path = root / "joined.json"
            receipts = phase3_fast_receipts(root)
            for path, receipt in zip((small_path, bam_path, cnv_path, sv_path), receipts):
                write_json(path, receipt)

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT": str(small_path),
                    "PHASE3_WGS_FAST_BAM_QC_RECEIPT": str(bam_path),
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT": str(cnv_path),
                    "PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT": str(sv_path),
                    "PHASE3_WGS_FAST_EVIDENCE_JOIN_OUTPUT": str(output_path),
                },
                clear=False,
            ):
                manifest, output = join_evidence.load_manifest_from_environment()
                join_evidence.write_manifest(output, manifest)
            output_text = output_path.read_text(encoding="utf-8")
            expected_hashes = {
                "small_variant_artifact_export": _sha256_json(small_path),
                "bam_qc": _sha256_json(bam_path),
                "cnv_evidence": _sha256_json(cnv_path),
                "sv_evidence": _sha256_json(sv_path),
            }

        self.assertEqual(output_path, output)
        self.assertEqual(expected_hashes, manifest["source"]["receipt_sha256"])
        self.assertIn('"manifest_type": "phase3_wgs_fast_evidence_join_manifest"', output_text)

    def test_rejects_non_completed_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[1]["status"] = "stubbed"

        with self.assertRaisesRegex(join_evidence.ManifestError, "bam_qc status"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_mismatched_run_identity(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[3]["run"]["run_id"] = "other"

        with self.assertRaisesRegex(join_evidence.ManifestError, "sv_evidence run"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_promoted_cnv_scarhrd_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[2]["interpretation"]["scarhrd_use"] = "ready"

        with self.assertRaisesRegex(join_evidence.ManifestError, "scarhrd_use"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_promoted_sv_chord_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[3]["interpretation"]["chord_use"] = "ready"

        with self.assertRaisesRegex(join_evidence.ManifestError, "chord_use"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_7,
            )

    def test_rejects_bam_qc_inputs_from_another_cached_bam_version(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[1]["inputs"]["tumor"]["bam"]["source"]["version_id"] = "other-copy-version"

        with self.assertRaisesRegex(join_evidence.ManifestError, "bam_qc tumor.bam input source"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_cnv_inputs_from_another_reference_version(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[2]["inputs"]["reference"]["fasta"]["source"][
            "uri"
        ] = "s3://diana-omics-private-cache-us-east-2/wgs-v2/references/reference.fa/other/reference.fa"

        with self.assertRaisesRegex(join_evidence.ManifestError, "cnv_evidence reference.fasta input source"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_rejects_sv_inputs_from_another_cached_bai_version(self) -> None:
        with TemporaryDirectory() as tmp:
            receipts = list(phase3_fast_receipts(Path(tmp)))
        receipts[3]["inputs"]["normal"]["bai"]["source"]["version_id"] = "other-copy-version"

        with self.assertRaisesRegex(join_evidence.ManifestError, "sv_evidence normal.bai input source"):
            join_evidence.build_phase3_fast_evidence_join_manifest(
                *receipts,
                small_variant_artifact_export_sha256=SHA_1,
                bam_qc_receipt_sha256=SHA_2,
                cnv_evidence_receipt_sha256=SHA_3,
                sv_evidence_receipt_sha256=SHA_4,
            )

    def test_manifest_output_rejects_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_output = root / "real-output"
            real_output.mkdir()
            linked_output = root / "linked-output"
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(join_evidence.ManifestError, "parent may not be a symlink"):
                join_evidence.write_manifest(
                    linked_output / "evidence-join.json",
                    {"status": "redirected"},
                )

            self.assertEqual([], list(real_output.rglob("*")))


if __name__ == "__main__":
    unittest.main()
