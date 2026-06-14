"""Tests for the WGS-only acceptance gate (``verify:phase3-outputs``).

A full-source Phase 3 WGS run skips the WES ladder, so the whole-pipeline
``verify:outputs`` can't pass and used to run non-fatally — meaning a structurally
broken WGS output set could report success. ``verify_phase3_wgs_outputs`` gates the
Phase 3 acceptance subset fatally. These tests build a valid output tree and confirm
it passes, then mutate it to confirm it fails closed.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics.commands import verify_outputs

_PLACEHOLDER_FILES = [
    "results/phase3_wgs_smoke/README.md",
    "results/phase3_wgs_smoke/asset_summary.json",
    "results/phase3_wgs_smoke/tool_versions.json",
    "results/phase3_wgs_smoke/fastq_summary.csv",
    "results/phase3_wgs_smoke/fastq_summary.json",
    "results/phase3_wgs_smoke/bam_validation_summary.json",
    "results/phase3_wgs_smoke/mutect2_wgs_summary.csv",
    "results/phase3_wgs_smoke/mutect2_wgs_summary.json",
    "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
    "results/phase3_wgs_smoke/coverage_cnv_summary.csv",
    "results/phase3_wgs_smoke/coverage_cnv_summary.json",
    "results/phase3_wgs_smoke/signature_assignment_summary.csv",
    "results/phase3_wgs_smoke/signature_assignment_summary.json",
    "results/phase3_wgs_smoke/sv_evidence_candidates.csv",
    "results/phase3_wgs_smoke/sv_evidence_summary.csv",
    "results/phase3_wgs_smoke/sv_evidence_summary.json",
    "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json",
    "results/phase3_wgs_smoke/covered_truth_variants.csv",
]

_SAMPLESHEET_HEADER = (
    "pair_id,sample,role,assay,run_accession,source_read_pairs,read_pairs_per_end,fastq_1,fastq_2,"
    "reference_id,reference_dict_path,truth_snv_vcf_path,truth_indel_vcf_path,gatk_jar_path,"
    "mutect2_panel_of_normals_path,output_bam,output_bai,cnv_strategy,sv_strategy,signature_strategy,caveat"
)
_SUMMARY_HEADER = (
    "status,phase,read_pairs_per_end,read_pairs_mode,read_request,bam_validation_status,mutect2_status,"
    "coverage_cnv_status,sbs96_matrix_status,sv_evidence_status,phase3_complete,"
    "ready_for_phase4_when_diana_raw_arrives,boundary"
)


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _samplesheet_row(role: str, sample: str, run: str, prefix: str, source_pairs: int, read_pairs: int) -> str:
    caveat = "Full-source validation is the acceptance gate; bounded subsets are developer checks."
    return (
        f"pair,{sample},{role},WGS,{run},{source_pairs},{read_pairs},{prefix}_R1.full.fastq.gz,{prefix}_R2.full.fastq.gz,"
        f"ucsc_hg38_analysis_set_full,r.dict,s.vcf.gz,i.vcf.gz,gatk.jar,pon.vcf.gz,"
        f"x/full/bam/{role}.bam,x/full/bam/{role}.bam.bai,cnv,sv,sig,{caveat}"
    )


def _build_valid_phase3_tree(root: Path) -> None:
    for relative in _PLACEHOLDER_FILES:
        _write(root, relative, "{}" if relative.endswith(".json") else "placeholder\n")

    _write(
        root,
        "results/phase3_wgs_smoke/bam_validation_summary.csv",
        "status,output_bam,output_bai,quickcheck,sort_order,read_group_present,caveat\n"
        "passed,t.bam,t.bam.bai,passed,coordinate,yes,ok\n"
        "passed,n.bam,n.bam.bai,passed,coordinate,yes,ok\n",
    )
    _write(
        root,
        "manifests/phase3_wgs_smoke_samplesheet.csv",
        "\n".join(
            [
                _SAMPLESHEET_HEADER,
                _samplesheet_row("tumor", "HCC1395", "SRR7890824", "t", 1000, 1000),
                _samplesheet_row("normal", "HCC1395BL", "SRR7890827", "n", 1000, 1000),
            ]
        )
        + "\n",
    )
    boundary = "Full-depth Diana interpretation still requires reviewer sign-off."
    _write(
        root,
        "results/phase3_wgs_smoke/phase3_wgs_summary.csv",
        f"{_SUMMARY_HEADER}\npassed,3,1000,full,full,passed,passed,passed,passed,passed,yes,yes,{boundary}\n",
    )
    _write(
        root,
        "results/phase3_wgs_smoke/phase3_wgs_summary.json",
        json.dumps(
            {
                "phase3Complete": True,
                "readyForPhase4WhenDianaRawArrives": True,
                "readPairsMode": "full",
                "fullSourceFastqs": True,
                "coverageCnvMode": "full",
                "coverageCnvBins": 600,
            }
        ),
    )
    sbs_rows = "\n".join(f"HCC1395,C>A,A[C>A]A,{index},{index},pass_preferred" for index in range(96))
    _write(
        root,
        "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
        f"sample,mutation_type,trinucleotide,count,source_records,source_vcf_policy\n{sbs_rows}\n",
    )
    hrd_rows = "\n".join(f"{tool},evidence,produced,deferred,caveat" for tool in ["SigProfilerAssignment", "scarHRD", "CHORD"])
    _write(
        root,
        "results/phase3_wgs_smoke/hrd_tool_readiness_summary.csv",
        f"tool,evidence_input,real_output_status,interpretability_status,caveat\n{hrd_rows}\n",
    )


class VerifyPhase3OutputsTest(unittest.TestCase):
    def _root(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="diana-p3verify-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return tmp

    def _errors(self, root: Path) -> list[str]:
        errors: list[str] = []
        with patch.object(verify_outputs, "path_from_root", lambda relative: root / relative):
            verify_outputs.verify_phase3_wgs_outputs(errors)
        return errors

    def test_valid_tree_passes(self):
        root = self._root()
        _build_valid_phase3_tree(root)
        self.assertEqual(self._errors(root), [])

    def test_missing_required_file_fails_closed(self):
        root = self._root()
        _build_valid_phase3_tree(root)
        (root / "results/phase3_wgs_smoke/mutect2_wgs_summary.json").unlink()
        self.assertIn("Missing results/phase3_wgs_smoke/mutect2_wgs_summary.json", self._errors(root))

    def test_incomplete_phase3_gate_fails_closed(self):
        root = self._root()
        _build_valid_phase3_tree(root)
        boundary = "Full-depth Diana interpretation still requires reviewer sign-off."
        _write(
            root,
            "results/phase3_wgs_smoke/phase3_wgs_summary.csv",
            f"{_SUMMARY_HEADER}\npassed,3,1000,full,full,passed,passed,passed,passed,passed,no,no,{boundary}\n",
        )
        errors = self._errors(root)
        self.assertTrue(any("completed Phase 3 gate" in error for error in errors), errors)

    def test_bounded_subset_in_samplesheet_fails_closed(self):
        root = self._root()
        _build_valid_phase3_tree(root)
        # read_pairs_per_end < source_read_pairs == a bounded developer subset, not full source.
        _write(
            root,
            "manifests/phase3_wgs_smoke_samplesheet.csv",
            "\n".join(
                [
                    _SAMPLESHEET_HEADER,
                    _samplesheet_row("tumor", "HCC1395", "SRR7890824", "t", 1000, 500),
                    _samplesheet_row("normal", "HCC1395BL", "SRR7890827", "n", 1000, 500),
                ]
            )
            + "\n",
        )
        errors = self._errors(root)
        self.assertTrue(any("must use full source read pairs" in error for error in errors), errors)

    def test_sbs96_wrong_row_count_fails_closed(self):
        root = self._root()
        _build_valid_phase3_tree(root)
        short_rows = "\n".join(f"HCC1395,C>A,A[C>A]A,{index},{index},pass_preferred" for index in range(40))
        _write(
            root,
            "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
            f"sample,mutation_type,trinucleotide,count,source_records,source_vcf_policy\n{short_rows}\n",
        )
        errors = self._errors(root)
        self.assertTrue(any("SBS96 matrix must have exactly 96 rows" in error for error in errors), errors)

    def test_json_bounded_run_fails_closed(self):
        root = self._root()
        _build_valid_phase3_tree(root)
        _write(
            root,
            "results/phase3_wgs_smoke/phase3_wgs_summary.json",
            json.dumps(
                {
                    "phase3Complete": True,
                    "readyForPhase4WhenDianaRawArrives": True,
                    "readPairsMode": "bounded",
                    "fullSourceFastqs": False,
                    "coverageCnvMode": "full",
                    "coverageCnvBins": 600,
                }
            ),
        )
        errors = self._errors(root)
        self.assertTrue(any("must be from full-source FASTQs" in error for error in errors), errors)

    def test_metadata_coverage_cnv_mode_rejects_zero_bins(self):
        root = self._root()
        _build_valid_phase3_tree(root)
        boundary = "Full-depth Diana interpretation still requires reviewer sign-off."
        _write(
            root,
            "results/phase3_wgs_smoke/phase3_wgs_summary.csv",
            f"{_SUMMARY_HEADER}\npassed,3,1000,full,full,passed,skipped_public_bam_timing,passed,skipped_public_bam_timing,passed,yes,yes,{boundary}\n",
        )
        _write(
            root,
            "results/phase3_wgs_smoke/phase3_wgs_summary.json",
            json.dumps(
                {
                    "phase3Complete": True,
                    "readyForPhase4WhenDianaRawArrives": True,
                    "readPairsMode": "full",
                    "fullSourceFastqs": True,
                    "coverageCnvMode": "metadata",
                    "coverageCnvBins": 0,
                }
            ),
        )
        errors = self._errors(root)
        self.assertTrue(any("non-empty coverage CNV bins" in error for error in errors), errors)

    def test_full_coverage_cnv_mode_rejects_zero_bins(self):
        root = self._root()
        _build_valid_phase3_tree(root)
        _write(
            root,
            "results/phase3_wgs_smoke/phase3_wgs_summary.json",
            json.dumps(
                {
                    "phase3Complete": True,
                    "readyForPhase4WhenDianaRawArrives": True,
                    "readPairsMode": "full",
                    "fullSourceFastqs": True,
                    "coverageCnvMode": "full",
                    "coverageCnvBins": 0,
                }
            ),
        )
        errors = self._errors(root)
        self.assertTrue(any("non-empty coverage CNV bins" in error for error in errors), errors)

    def test_entry_command_raises_on_broken_and_passes_on_valid(self):
        broken = self._root()  # empty tree -> many missing files
        with patch.object(verify_outputs, "path_from_root", lambda relative: broken / relative):
            with self.assertRaises(SystemExit):
                verify_outputs.verify_phase3_outputs()
        valid = self._root()
        _build_valid_phase3_tree(valid)
        with patch.object(verify_outputs, "path_from_root", lambda relative: valid / relative):
            verify_outputs.verify_phase3_outputs()  # must not raise


if __name__ == "__main__":
    unittest.main()
