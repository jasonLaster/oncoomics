from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_1
from test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest

from diana_omics.commands.phase3_wgs import render_phase3_fast_cnv_evidence_plan as cnv_plan
from diana_omics.commands.phase3_wgs import run_phase3_fast_cnv_evidence as run_cnv
from diana_omics.utils import write_json


class MaterializingBedcovRunner:
    def __init__(self, *, skip: set[str] | None = None, first_bin_only: bool = False) -> None:
        self.commands: list[list[str]] = []
        self.skip = skip or set()
        self.first_bin_only = first_bin_only

    def run(self, argv: list[str], *, stdout_path: Path) -> None:
        self.commands.append(list(argv))
        contig = stdout_path.name.split(".", 1)[0]
        if contig in self.skip:
            return

        rows = []
        for index, line in enumerate(Path(argv[2]).read_text(encoding="utf-8").splitlines()):
            if self.first_bin_only and index:
                break
            shard_contig, start_text, end_text = line.split("\t")
            length = int(end_text) - int(start_text)
            rows.append(f"{shard_contig}\t{start_text}\t{end_text}\t{length * 20}\t{length * 10}")

        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase3_fast_cnv_evidence_plan(root: Path) -> dict:
    return cnv_plan.build_phase3_fast_cnv_evidence_plan(
        staged_inputs_manifest(root),
        staged_inputs_manifest_sha256=SHA_1,
        output_root=root / "cnv_evidence",
        bin_size=10,
        bedcov_workers=1,
    )


class Phase3FastCnvEvidenceRunTests(unittest.TestCase):
    def test_runs_bedcov_shards_and_writes_completed_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_cnv_evidence_plan(Path(tmp))
            runner = MaterializingBedcovRunner()

            receipt = run_cnv.run_phase3_fast_cnv_evidence(
                plan,
                runner=runner,
                cnv_evidence_plan_sha256=SHA_1,
            )
            coverage_bins = Path(receipt["outputs"]["coverage_bins"]).read_text(encoding="utf-8")
            summary_json = Path(receipt["outputs"]["summary_json"]).read_text()

        self.assertEqual(
            [plan["commands"]["bedcov_by_contig"]["chr1"]["argv"], plan["commands"]["bedcov_by_contig"]["chr2"]["argv"]],
            runner.commands,
        )
        self.assertEqual("phase3_wgs_fast_cnv_evidence_receipt", receipt["manifest_type"])
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("no_call", receipt["interpretation"]["authorized_hrd_state"])
        self.assertEqual("no_call_requires_allele_specific_cnv_loh_segments", receipt["interpretation"]["scarhrd_use"])
        self.assertEqual(SHA_1, receipt["source"]["cnv_evidence_plan_sha256"])
        self.assertEqual(4, sum(shard["bin_count"] for shard in receipt["interval_shards"]))
        self.assertIn("combined_bedcov", receipt["materialized_outputs"])
        self.assertIn("chr1", receipt["materialized_outputs"]["interval_shards"])
        self.assertGreater(receipt["materialized_outputs"]["coverage_bins"]["bytes"], 0)

        self.assertIn("log2_tumor_normal", coverage_bins)
        self.assertIn("relative_gain", coverage_bins)
        self.assertIn('"coverage_cnv_mode": "full_depth_bedcov"', summary_json)

    def test_environment_command_writes_receipt_after_running_planned_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "cnv-plan.json"
            receipt_path = root / "cnv-receipt.json"
            plan = phase3_fast_cnv_evidence_plan(root)
            write_json(plan_path, plan)

            runner = MaterializingBedcovRunner()
            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN": str(plan_path),
                    "PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT_OUTPUT": str(receipt_path),
                },
                clear=False,
            ):
                receipt, output = run_cnv.load_receipt_from_environment(runner=runner)
                run_cnv.write_receipt(output, receipt)
            expected_plan_sha256 = _sha256_json(plan_path)
            receipt_text = receipt_path.read_text()

        self.assertEqual(receipt_path, output)
        self.assertEqual(expected_plan_sha256, receipt["source"]["cnv_evidence_plan_sha256"])
        self.assertEqual(2, len(runner.commands))
        self.assertIn('"manifest_type": "phase3_wgs_fast_cnv_evidence_receipt"', receipt_text)

    def test_rejects_missing_planned_command(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_cnv_evidence_plan(Path(tmp))
        plan["commands"]["bedcov_by_contig"].pop("chr2")

        with self.assertRaisesRegex(run_cnv.ManifestError, "one command per interval shard"):
            run_cnv.run_phase3_fast_cnv_evidence(
                plan,
                runner=MaterializingBedcovRunner(),
                cnv_evidence_plan_sha256=SHA_1,
            )

    def test_rejects_command_that_would_skip_bedcov(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_cnv_evidence_plan(Path(tmp))
        plan["commands"]["bedcov_by_contig"]["chr1"]["argv"] = ["true"]

        with self.assertRaisesRegex(run_cnv.ManifestError, "samtools bedcov"):
            run_cnv.run_phase3_fast_cnv_evidence(
                plan,
                runner=MaterializingBedcovRunner(),
                cnv_evidence_plan_sha256=SHA_1,
            )

    def test_clears_stale_bedcov_before_requiring_fresh_materialization(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_cnv_evidence_plan(Path(tmp))
            stale_chr2 = Path(plan["commands"]["bedcov_by_contig"]["chr2"]["stdout_path"])
            stale_chr2.parent.mkdir(parents=True, exist_ok=True)
            stale_chr2.write_text("chr2\t0\t10\t10\t10\n", encoding="utf-8")

            with self.assertRaisesRegex(run_cnv.ManifestError, "chr2 bedcov output"):
                run_cnv.run_phase3_fast_cnv_evidence(
                    plan,
                    runner=MaterializingBedcovRunner(skip={"chr2"}),
                    cnv_evidence_plan_sha256=SHA_1,
                )

            self.assertFalse(stale_chr2.exists())

    def test_rejects_bedcov_row_count_mismatch(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_cnv_evidence_plan(Path(tmp))

            with self.assertRaisesRegex(run_cnv.ManifestError, "row count"):
                run_cnv.run_phase3_fast_cnv_evidence(
                    plan,
                    runner=MaterializingBedcovRunner(first_bin_only=True),
                    cnv_evidence_plan_sha256=SHA_1,
                )


if __name__ == "__main__":
    unittest.main()
