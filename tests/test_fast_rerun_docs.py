from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXT_GEN = ROOT / "docs/operations/next-generation-fast-rerun.md"
SUMMARY = ROOT / "docs/operations/fast-rerun-performance-cost-summary.md"
RUNNING_PIPELINE = ROOT / "docs/operations/running-the-pipeline.md"
AWS_README = ROOT / "infra/aws/README.md"
SCRIPTS_README = ROOT / "scripts/README.md"


class FastRerunDocsTests(unittest.TestCase):
    def test_next_generation_doc_records_operator_stopped_v4(self) -> None:
        text = NEXT_GEN.read_text(encoding="utf-8")

        self.assertIn("observed through 2026-07-18 04:49 UTC", text)
        self.assertIn("single-node CPU evidence retry was intentionally stopped during v4", text)
        self.assertIn("Do not restart that S3-only\nworker", text)
        self.assertIn("GetPileupSummaries", text)
        self.assertIn("Track the 384 On-Demand P vCPU request", text)
        self.assertIn("FAST_BAM_CNV_SV_EVIDENCE", text)
        self.assertIn("FAST_EVIDENCE_JOIN", text)
        self.assertIn("FAST_VERIFY_AND_PUBLISH", text)
        self.assertIn("FAST_STAGE_DETERMINISTIC_REPORT", text)
        self.assertIn("FAST_STAGE_ROSALIND_PACKET", text)
        self.assertIn("FAST_STAGE_BLOCKED_CROSSCHECKS", text)
        self.assertIn("five of the seven source packets", text)
        self.assertIn("scripts/render_source_report_freeze_runbook.py", text)
        self.assertIn("sequenza_scarhrd", text)
        self.assertIn("sigprofiler_sbs3", text)
        self.assertIn("--deterministic-report-dir", text)
        self.assertIn("--rosalind-report-dir", text)
        self.assertIn("--blocked-crosscheck-root", text)
        self.assertIn(
            "$FAST_ROOT/deterministic_report/workspace/results/phase3_wgs_fast/deterministic_report",
            text,
        )
        self.assertIn(
            "$FAST_ROOT/rosalind_hrd/workspace/results/rosalind_hrd/diana_wgs/${RUN_ID}",
            text,
        )
        self.assertIn(
            "$FAST_ROOT/blocked_crosschecks/workspace/results/phase3_wgs_fast/blocked_crosschecks",
            text,
        )
        self.assertIn("published, versioned,\nalias-only cross-check input contract", text)
        self.assertIn("evidence_join_manifest.json", text)
        self.assertIn("final_evidence_manifest.json", text)
        self.assertIn("generate_blocked_hrd_crosscheck_reports.py", text)

    def test_next_generation_doc_tracks_bam_qc_plan_seam(self) -> None:
        text = NEXT_GEN.read_text(encoding="utf-8")

        self.assertIn("FAST_BAM_QC_PLAN", text)
        self.assertIn("exact quickcheck, flagstat, and idxstats plan", text)
        self.assertIn("samtools quickcheck", text)
        self.assertIn("QC-only `no_call` artifact", text)
        self.assertIn("run:phase3-fast-bam-qc", text)
        self.assertIn("empty successful `quickcheck` log", text)

    def test_next_generation_doc_tracks_cnv_evidence_plan_seam(self) -> None:
        text = NEXT_GEN.read_text(encoding="utf-8")

        self.assertIn("FAST_CNV_EVIDENCE_PLAN", text)
        self.assertIn("exact full-depth bedcov coverage-bin plan", text)
        self.assertIn("one\nstandard-contig BED shard", text)
        self.assertIn("scarHRD `no_call`", text)
        self.assertIn("reference.standard_contigs", text)
        self.assertIn("run:phase3-fast-cnv-evidence", text)

    def test_next_generation_doc_tracks_sv_evidence_plan_seam(self) -> None:
        text = NEXT_GEN.read_text(encoding="utf-8")

        self.assertIn("FAST_SV_EVIDENCE_PLAN", text)
        self.assertIn("exact split/discordant read evidence plan", text)
        self.assertIn("mechanical supplementary/split-read and discordant-pair evidence", text)
        self.assertIn("CHORD or HRDetect use remains `no_call`", text)
        self.assertIn("run:phase3-fast-sv-evidence", text)
        self.assertIn("zero-byte discordant-pair SAM", text)

    def test_fast_rerun_summary_does_not_revive_the_cpu_retry(self) -> None:
        text = SUMMARY.read_text(encoding="utf-8")

        self.assertIn("operator-stopped v4 retry", text)
        self.assertIn("Do not restart\nthat same monolithic single-node CPU topology", text)
        self.assertIn("checked-in resumable DAG", text)
        self.assertNotIn("keep the CPU job alive", text)

    def test_running_pipeline_documents_guarded_phase3_fast_execute(self) -> None:
        text = RUNNING_PIPELINE.read_text(encoding="utf-8")

        self.assertIn("nf:aws:phase3-wgs-fast:execute", text)
        self.assertIn("ALLOW_PHASE3_FAST_AWS_EXECUTE=YES", text)
        self.assertIn("PARABRICKS_MIRROR_RECEIPT", text)
        self.assertIn("PHASE3_FAST_GPU_SMOKE_RESULT", text)
        self.assertIn("alias-only forbidden-token inventory after `--`", text)
        self.assertIn("mirror-receipt, cache, ECR-image, live\nP-instance quota", text)

    def test_legacy_full_wgs_launcher_is_not_current_diana_rerun_path(self) -> None:
        text = AWS_README.read_text(encoding="utf-8")

        self.assertIn("Do not use this legacy full-source CPU launcher", text)
        self.assertIn("phase3_wgs_fast", text)
        self.assertIn("P5en/Parabricks", text)

    def test_scripts_readme_tracks_six_file_deterministic_report(self) -> None:
        text = SCRIPTS_README.read_text(encoding="utf-8")

        self.assertIn("six-file\n  `deterministic_full_wgs` packet", text)
        self.assertNotIn("five-file\n  `deterministic_full_wgs` packet", text)


if __name__ == "__main__":
    unittest.main()
