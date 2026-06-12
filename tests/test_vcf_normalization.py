"""Regression tests for VCF normalization before truth/caller comparison.

The benchmark normalizes truth and caller VCFs with ``bcftools norm`` so that
indels and multiallelics use one representation before exact-key matching. The
naive ``bcftools norm -f ref`` aborts the whole benchmark (exit 255) on a single
REF-allele mismatch, so the hardened version uses ``--check-ref x`` (exclude the
mismatch, keep going) and fails closed only when a flood of mismatches signals
the wrong reference.

The integration tests drive the real ``normalize_vcf_for_comparison`` against a
tiny synthetic reference + VCFs using a real ``bcftools``; they skip cleanly when
the bioinformatics tools are unavailable. The parser tests are pure and always
run.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import paths, utils
from diana_omics.commands import run_full_wes_benchmark as wes
from diana_omics.commands import run_phase3_wgs_smoke as wgs

HAS_BCFTOOLS = all(shutil.which(tool) for tool in ("bcftools", "samtools", "bgzip", "tabix"))

# 1-based: ...12:T, 13-20:A(run), 21:T...  -> a one-base insertion anywhere in the
# A-run left-aligns to pos 12 (T -> TA).
REFERENCE = "ACGTACGTACGTAAAAAAAATCGATCGATCGGGGGGGGCC"


class BcftoolsNormSummaryParserTest(unittest.TestCase):
    MODERN = "REF_MISMATCH\tchr1\t13\tG\tA\nLines   total/split/joined/realigned/mismatch_removed/dup_removed/skipped:\t3/1/0/1/1/0/0\n"
    LEGACY = "Lines   total/split/realigned/skipped:\t100/2/5/4\n"

    def test_parses_modern_field_set(self):
        summary = utils.parse_bcftools_norm_summary(self.MODERN)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["split"], 1)
        self.assertEqual(summary["mismatch_removed"], 1)
        self.assertEqual(summary["skipped"], 0)

    def test_ref_mismatch_count_prefers_mismatch_removed(self):
        self.assertEqual(utils.bcftools_norm_ref_mismatch_count(self.MODERN), 1)

    def test_ref_mismatch_count_falls_back_to_skipped_on_legacy(self):
        # Older bcftools has no mismatch_removed field; excluded records land in skipped.
        self.assertEqual(utils.bcftools_norm_ref_mismatch_count(self.LEGACY), 4)

    def test_missing_summary_returns_zero(self):
        self.assertEqual(utils.parse_bcftools_norm_summary("no summary here\n"), {})
        self.assertEqual(utils.bcftools_norm_ref_mismatch_count(""), 0)


def _write_reference(root: Path) -> None:
    fasta = root / "ref.fa"
    fasta.write_text(f">chr1\n{REFERENCE}\n")
    subprocess.run(["samtools", "faidx", str(fasta)], check=True, capture_output=True)


def _write_vcf(root: Path, name: str, records: list[str]) -> str:
    header = [
        "##fileformat=VCFv4.2",
        f"##contig=<ID=chr1,length={len(REFERENCE)}>",
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
    ]
    raw = root / f"{name}.vcf"
    raw.write_text("\n".join(header + records) + "\n")
    gz = root / f"{name}.vcf.gz"
    subprocess.run(["bash", "-lc", f"bgzip -f -c {raw} > {gz} && tabix -f -p vcf {gz}"], check=True, capture_output=True)
    return f"{name}.vcf.gz"


def _keys(root: Path, relative_vcf: str) -> set[str]:
    result = subprocess.run(["bcftools", "view", "-H", str(root / relative_vcf)], check=True, capture_output=True, text=True)
    keys = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        contig, position, _id, ref, alt = line.split("\t")[:5]
        for one_alt in alt.split(","):
            keys.add(f"{contig}:{position}:{ref}:{one_alt}")
    return keys


@unittest.skipUnless(HAS_BCFTOOLS, "bcftools/samtools/bgzip/tabix not available")
class NormalizeVcfForComparisonIntegrationTest(unittest.TestCase):
    def _root(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="diana-norm-test-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "logs").mkdir(parents=True, exist_ok=True)
        (tmp / "out").mkdir(parents=True, exist_ok=True)
        _write_reference(tmp)
        return tmp

    def test_single_ref_mismatch_does_not_abort_and_is_excluded(self):
        root = self._root()
        # pos13 claims REF=G but the reference is A there -> the abort-on-mismatch case.
        vcf = _write_vcf(root, "truth", ["chr1\t5\t.\tA\tC,T\t.\tPASS\t.", "chr1\t13\t.\tG\tC\t.\tPASS\t."])
        with patch.object(paths, "ROOT", root):
            out = wes.normalize_vcf_for_comparison(vcf, "ref.fa", "out/truth.norm.vcf.gz", "logs/truth.norm.log")
        self.assertTrue((root / out).exists())
        self.assertTrue((root / f"{out}.tbi").exists(), "normalized output must be tabix-indexable")
        keys = _keys(root, out)
        self.assertEqual(keys, {"chr1:5:A:C", "chr1:5:A:T"})  # multiallelic split kept, mismatch dropped
        self.assertNotIn("chr1:13:G:C", keys)

    def test_indel_left_alignment_is_canonicalized(self):
        root = self._root()
        # A one-base insertion at pos20 (right end of the A-run) must left-align to pos12.
        vcf = _write_vcf(root, "indel", ["chr1\t20\t.\tA\tAA\t.\tPASS\t."])
        with patch.object(paths, "ROOT", root):
            out = wes.normalize_vcf_for_comparison(vcf, "ref.fa", "out/indel.norm.vcf.gz", "logs/indel.norm.log")
        self.assertEqual(_keys(root, out), {"chr1:12:T:TA"})

    def test_caller_and_truth_indel_reconcile_to_same_key(self):
        # The whole point: the same insertion written at different positions in the
        # homopolymer must normalize to one key so the exact-key match works.
        root = self._root()
        truth = _write_vcf(root, "truth", ["chr1\t20\t.\tA\tAA\t.\tPASS\t."])
        caller = _write_vcf(root, "caller", ["chr1\t14\t.\tA\tAA\t.\tPASS\t."])
        with patch.object(paths, "ROOT", root):
            truth_out = wgs.normalize_vcf_for_comparison(truth, "ref.fa", "out/truth.norm.vcf.gz", "logs/t.norm.log")
            caller_out = wgs.normalize_vcf_for_comparison(caller, "ref.fa", "out/caller.norm.vcf.gz", "logs/c.norm.log")
        truth_keys = _keys(root, truth_out)
        caller_keys = _keys(root, caller_out)
        self.assertEqual(truth_keys, caller_keys)
        self.assertEqual(truth_keys, {"chr1:12:T:TA"})

    def test_flood_of_ref_mismatches_fails_closed(self):
        root = self._root()
        # Three REF mismatches; cap them at 2 so the run fails closed (wrong-reference signal).
        vcf = _write_vcf(
            root,
            "wrongref",
            ["chr1\t5\t.\tG\tC\t.\tPASS\t.", "chr1\t6\t.\tG\tA\t.\tPASS\t.", "chr1\t7\t.\tA\tT\t.\tPASS\t."],
        )
        with patch.object(paths, "ROOT", root), patch.object(wes, "NORM_MAX_REF_MISMATCH", 2):
            with self.assertRaises(RuntimeError) as caught:
                wes.normalize_vcf_for_comparison(vcf, "ref.fa", "out/wrongref.norm.vcf.gz", "logs/wrongref.norm.log")
        self.assertIn("does not match this VCF build", str(caught.exception))

    def test_clean_vcf_normalizes_without_warning_or_failure(self):
        root = self._root()
        # All REF alleles correct -> no mismatches, no exclusions, output matches input set.
        vcf = _write_vcf(root, "clean", ["chr1\t5\t.\tA\tC\t.\tPASS\t.", "chr1\t21\t.\tT\tC\t.\tPASS\t."])
        with patch.object(paths, "ROOT", root):
            out = wgs.normalize_vcf_for_comparison(vcf, "ref.fa", "out/clean.norm.vcf.gz", "logs/clean.norm.log")
            log_text = utils.read_text(paths.path_from_root("logs/clean.norm.log"))
        self.assertEqual(_keys(root, out), {"chr1:5:A:C", "chr1:21:T:C"})
        self.assertEqual(utils.bcftools_norm_ref_mismatch_count(log_text), 0)


if __name__ == "__main__":
    unittest.main()
