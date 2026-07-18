from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_evidence_join import SHA_4, SHA_5, SHA_6, SHA_7, phase3_fast_receipts

from diana_omics.commands.phase3_wgs import join_phase3_fast_evidence as join_evidence
from diana_omics.commands.phase3_wgs import publish_phase3_fast_final_evidence as final_evidence
from diana_omics.utils import write_json


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _join_manifest(root: Path) -> dict:
    return join_evidence.build_phase3_fast_evidence_join_manifest(
        *phase3_fast_receipts(root),
        small_variant_artifact_export_sha256=SHA_4,
        bam_qc_receipt_sha256=SHA_5,
        cnv_evidence_receipt_sha256=SHA_6,
        sv_evidence_receipt_sha256=SHA_7,
    )


class Phase3FastFinalEvidenceTests(unittest.TestCase):
    def test_copies_joined_artifacts_into_portable_final_tree(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"
            manifest = final_evidence.build_phase3_fast_final_evidence_manifest(
                _join_manifest(root),
                evidence_join_sha256=SHA_4,
                small_variant_artifact_root=root / "small_variant_export",
                bam_qc_artifact_root=root / "bam_qc",
                cnv_evidence_artifact_root=root / "cnv_evidence",
                sv_evidence_artifact_root=root / "sv_evidence",
                output_root=output_root,
            )

            filtered_vcf = output_root / manifest["artifacts"]["small_variants"]["filter_mutect"]["filtered_vcf"][
                "relative_path"
            ]
            cnv_bins = output_root / manifest["artifacts"]["cnv_evidence"]["coverage_bins"]["relative_path"]
            sbs96 = output_root / manifest["artifacts"]["small_variants"]["filter_mutect"]["sbs96_matrix"][
                "relative_path"
            ]
            sv_discordant = output_root / manifest["artifacts"]["sv_evidence"]["normal"]["discordant_mapped_pairs"][
                "relative_path"
            ]
            filtered_vcf_group = filtered_vcf.parent.parent.parent.as_posix().rsplit("/final/", 1)[1]
            cnv_bins_sha256 = _sha256_path(cnv_bins)
            sbs96_rows = sbs96.read_text(encoding="utf-8").splitlines()
            sv_discordant_bytes = sv_discordant.stat().st_size

        self.assertEqual("phase3_wgs_fast_final_evidence_manifest", manifest["manifest_type"])
        self.assertEqual("completed", manifest["status"])
        self.assertEqual("no_call", manifest["interpretation"]["authorized_hrd_state"])
        self.assertEqual(35, manifest["artifact_count"])
        self.assertEqual("artifacts/small_variants", filtered_vcf_group)
        self.assertEqual(manifest["artifacts"]["cnv_evidence"]["coverage_bins"]["sha256"], cnv_bins_sha256)
        self.assertEqual(97, len(sbs96_rows))
        self.assertEqual(0, sv_discordant_bytes)
        self.assertEqual("copy-version-5", manifest["input_sources"]["reference"]["fasta"]["version_id"])
        self.assertEqual("copy-version-13", manifest["input_sources"]["caller_resources"]["mutect2_interval_set"]["version_id"])
        self.assertNotIn(str(root), json.dumps(manifest))
        self.assertNotIn("commands", manifest)
        self.assertNotIn("inputs", manifest)

    def test_environment_command_writes_final_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join_path = root / "join.json"
            output_path = root / "final-manifest.json"
            output_root = root / "final"
            write_json(join_path, _join_manifest(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_EVIDENCE_JOIN": str(join_path),
                    "PHASE3_WGS_FAST_SMALL_VARIANT_ARTIFACT_ROOT": str(root / "small_variant_export"),
                    "PHASE3_WGS_FAST_BAM_QC_ARTIFACT_ROOT": str(root / "bam_qc"),
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_ARTIFACT_ROOT": str(root / "cnv_evidence"),
                    "PHASE3_WGS_FAST_SV_EVIDENCE_ARTIFACT_ROOT": str(root / "sv_evidence"),
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT": str(output_root),
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_OUTPUT": str(output_path),
                },
                clear=False,
            ):
                manifest, output = final_evidence.load_manifest_from_environment()
                final_evidence.write_manifest(output, manifest)
            output_text = output_path.read_text(encoding="utf-8")
            expected_join_sha256 = _sha256_path(join_path)

        self.assertEqual(output_path, output)
        self.assertEqual(expected_join_sha256, manifest["source"]["evidence_join_manifest_sha256"])
        self.assertIn('"manifest_type": "phase3_wgs_fast_final_evidence_manifest"', output_text)

    def test_rejects_non_completed_join(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = _join_manifest(root)
            join["status"] = "stubbed"

            with self.assertRaisesRegex(final_evidence.ManifestError, "status"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    join,
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_promoted_hrd_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = _join_manifest(root)
            join["interpretation"]["chord_use"] = "ready"

            with self.assertRaisesRegex(final_evidence.ManifestError, "chord_use"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    join,
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_artifact_tampering_before_copy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            join = _join_manifest(root)
            (root / "bam_qc" / "normal" / "idxstats.tsv").write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(final_evidence.ManifestError, "bam_qc.normal.idxstats"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    join,
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_unexpected_existing_final_artifacts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            unexpected = root / "final" / "artifacts" / "unexpected.txt"
            unexpected.parent.mkdir(parents=True)
            unexpected.write_text("stale\n", encoding="utf-8")

            with self.assertRaisesRegex(final_evidence.ManifestError, "unexpected existing final artifact"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    _join_manifest(root),
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=root / "final",
                )

    def test_rejects_unexpected_symlink_in_existing_final_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "final"
            linked_dir = output_root / "artifacts" / "old"
            real_dir = root / "real-old"
            real_dir.mkdir()
            linked_dir.parent.mkdir(parents=True)
            linked_dir.symlink_to(real_dir, target_is_directory=True)

            with self.assertRaisesRegex(final_evidence.ManifestError, "output_root contains a symlink"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    _join_manifest(root),
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=output_root,
                )

            self.assertEqual([], list(real_dir.rglob("*")))

    def test_rejects_symlinked_output_root_without_copying_outputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_output = root / "real-final"
            real_output.mkdir()
            output_root = root / "final"
            output_root.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(final_evidence.ManifestError, "output_root.*symlink"):
                final_evidence.build_phase3_fast_final_evidence_manifest(
                    _join_manifest(root),
                    evidence_join_sha256=SHA_4,
                    small_variant_artifact_root=root / "small_variant_export",
                    bam_qc_artifact_root=root / "bam_qc",
                    cnv_evidence_artifact_root=root / "cnv_evidence",
                    sv_evidence_artifact_root=root / "sv_evidence",
                    output_root=output_root,
                )

            self.assertEqual([], list(real_output.rglob("*")))


if __name__ == "__main__":
    unittest.main()
