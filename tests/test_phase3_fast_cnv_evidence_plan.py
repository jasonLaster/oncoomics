from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_1
from test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest

from diana_omics.commands.phase3_wgs import render_phase3_fast_cnv_evidence_plan as cnv_evidence
from diana_omics.utils import write_json


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase3FastCnvEvidencePlanTests(unittest.TestCase):
    def test_plan_renders_standard_contig_bedcov_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
            plan = cnv_evidence.build_phase3_fast_cnv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
                output_root="/scratch/diana/phase3_wgs_fast/cnv_evidence",
                bin_size=10,
                bedcov_workers=2,
            )

        self.assertEqual("phase3_wgs_fast_cnv_evidence_plan", plan["manifest_type"])
        self.assertEqual("planned", plan["status"])
        self.assertEqual("no_call", plan["interpretation"]["authorized_hrd_state"])
        self.assertEqual("coverage_cnv_evidence_not_allele_specific", plan["interpretation"]["hrd_use"])
        self.assertEqual("no_call_requires_allele_specific_cnv_loh_segments", plan["interpretation"]["scarhrd_use"])
        self.assertEqual(10, plan["runtime"]["bin_size"])
        self.assertEqual(2, plan["runtime"]["bedcov_workers"])
        self.assertEqual({"chr1", "chr2"}, {shard["contig"] for shard in plan["interval_shards"]})
        self.assertEqual(4, sum(shard["bin_count"] for shard in plan["interval_shards"]))

        tumor_bam = plan["inputs"]["tumor"]["bam"]["local_path"]
        normal_bam = plan["inputs"]["normal"]["bam"]["local_path"]
        chr1 = plan["commands"]["bedcov_by_contig"]["chr1"]
        self.assertEqual(
            [
                "samtools",
                "bedcov",
                "/scratch/diana/phase3_wgs_fast/cnv_evidence/intervals/chr1.bed",
                tumor_bam,
                normal_bam,
            ],
            chr1["argv"],
        )
        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/cnv_evidence/bedcov_shards/chr1.bedcov.tsv",
            chr1["stdout_path"],
        )
        self.assertEqual(
            "/scratch/diana/phase3_wgs_fast/cnv_evidence/coverage_cnv_summary.json",
            plan["outputs"]["summary_json"],
        )

    def test_rejects_non_ready_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["status"] = "planned"

        with self.assertRaisesRegex(cnv_evidence.ManifestError, "ready"):
            cnv_evidence.build_phase3_fast_cnv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_non_no_call_staged_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["interpretation"]["authorized_hrd_state"] = "partial_evidence"

        with self.assertRaisesRegex(cnv_evidence.ManifestError, "no_call"):
            cnv_evidence.build_phase3_fast_cnv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_matching_tumor_normal_sample_names(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["bam_pair"]["normal"]["bam"]["sample_id"] = "subject01_tumor"
        manifest["bam_pair"]["normal"]["bai"]["sample_id"] = "subject01_tumor"

        with self.assertRaisesRegex(cnv_evidence.ManifestError, "must differ"):
            cnv_evidence.build_phase3_fast_cnv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_missing_bam_sample_id(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["bam_pair"]["tumor"]["bam"].pop("sample_id")

        with self.assertRaisesRegex(cnv_evidence.ManifestError, "sample_id"):
            cnv_evidence.build_phase3_fast_cnv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_unpaired_reference_layout(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
        manifest["reference"]["fai"]["local_path"] = "/scratch/diana/elsewhere/reference.fa.fai"

        with self.assertRaisesRegex(cnv_evidence.ManifestError, "reference.fa.fai"):
            cnv_evidence.build_phase3_fast_cnv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
            )

    def test_rejects_manifest_without_standard_contigs(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))
            manifest["reference"]["standard_contigs"] = [{"contig": "chrM", "length": 5}]

            with self.assertRaisesRegex(cnv_evidence.ManifestError, "standard"):
                cnv_evidence.build_phase3_fast_cnv_evidence_plan(
                    manifest,
                    staged_inputs_manifest_sha256=SHA_1,
                )

    def test_rejects_relative_output_root(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = staged_inputs_manifest(Path(tmp))

        with self.assertRaisesRegex(cnv_evidence.ManifestError, "output_root"):
            cnv_evidence.build_phase3_fast_cnv_evidence_plan(
                manifest,
                staged_inputs_manifest_sha256=SHA_1,
                output_root="scratch/diana/phase3_wgs_fast/cnv_evidence",
            )

    def test_environment_command_writes_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "staged-inputs.json"
            output_path = root / "cnv-evidence-plan.json"
            manifest = staged_inputs_manifest(root)
            write_json(input_path, manifest)

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST": str(input_path),
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN_OUTPUT": str(output_path),
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_OUTPUT_ROOT": "/scratch/diana/test/cnv_evidence",
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_BIN_SIZE": "12",
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_BEDCOV_WORKERS": "3",
                },
                clear=False,
            ):
                plan, plan_path = cnv_evidence.load_plan_from_environment()
                cnv_evidence.write_plan(plan_path, plan)

            self.assertEqual(output_path, plan_path)
            self.assertEqual(12, plan["runtime"]["bin_size"])
            self.assertEqual(3, plan["runtime"]["bedcov_workers"])
            self.assertEqual(_sha256_json(input_path), plan["source"]["staged_inputs_manifest_sha256"])
            self.assertIn('"manifest_type": "phase3_wgs_fast_cnv_evidence_plan"', output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
