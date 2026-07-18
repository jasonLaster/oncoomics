from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import render_phase3_fast_bam_qc_plan as bam_qc
from diana_omics.commands.phase3_wgs import run_phase3_fast_bam_qc as run_qc
from diana_omics.utils import write_json
from tests.test_phase3_fast_input_manifest import SHA_1
from tests.test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest


class MaterializingSamtoolsRunner:
    def __init__(
        self,
        *,
        skip: set[tuple[str, str]] | None = None,
        empty: set[tuple[str, str]] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
        self.skip = skip or set()
        self.empty = empty or set()

    def run(
        self,
        argv: list[str],
        *,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> None:
        self.commands.append(list(argv))
        role = (stderr_path or stdout_path).parent.name
        name = _command_name(stdout_path=stdout_path, stderr_path=stderr_path)
        if (role, name) in self.skip:
            return

        output_path = stderr_path or stdout_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if (role, name) in self.empty or name == "quickcheck":
            output_path.write_bytes(b"")
        elif name == "flagstat":
            output_path.write_text(
                "100 + 0 in total (QC-passed reads + QC-failed reads)\n"
                "90 + 0 mapped (90.00% : N/A)\n",
                encoding="utf-8",
            )
        else:
            output_path.write_text("chr1\t25\t10\t0\n", encoding="utf-8")


class SymlinkSamtoolsRunner(MaterializingSamtoolsRunner):
    def run(
        self,
        argv: list[str],
        *,
        stdout_path: Path | None = None,
        stderr_path: Path | None = None,
    ) -> None:
        super().run(argv, stdout_path=stdout_path, stderr_path=stderr_path)
        role = (stderr_path or stdout_path).parent.name
        name = _command_name(stdout_path=stdout_path, stderr_path=stderr_path)
        if (role, name) != ("normal", "idxstats"):
            return

        output_path = stdout_path or stderr_path
        target = output_path.parent / "idxstats.redirected.tsv"
        target.write_text("chr1\t25\t10\t0\n", encoding="utf-8")
        output_path.unlink()
        output_path.symlink_to(target)


def _command_name(*, stdout_path: Path | None, stderr_path: Path | None) -> str:
    if stderr_path is not None:
        return "quickcheck"
    if stdout_path is not None and stdout_path.name == "flagstat.txt":
        return "flagstat"
    if stdout_path is not None and stdout_path.name == "idxstats.tsv":
        return "idxstats"
    raise ValueError(f"Unexpected BAM QC output path: {stdout_path or stderr_path}")


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase3_fast_bam_qc_plan(root: Path) -> dict:
    return bam_qc.build_phase3_fast_bam_qc_plan(
        staged_inputs_manifest(root),
        staged_inputs_manifest_sha256=SHA_1,
        output_root=root / "bam_qc",
        threads=8,
    )


class Phase3FastBamQcRunTests(unittest.TestCase):
    def test_runs_samtools_qc_and_writes_completed_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_bam_qc_plan(Path(tmp))
            runner = MaterializingSamtoolsRunner()

            receipt = run_qc.run_phase3_fast_bam_qc(
                plan,
                runner=runner,
                bam_qc_plan_sha256=SHA_1,
            )

        self.assertEqual(
            [
                plan["commands"][role][name]["argv"]
                for role in run_qc.ROLES
                for name in run_qc.EXPECTED_COMMANDS
            ],
            runner.commands,
        )
        self.assertEqual("phase3_wgs_fast_bam_qc_receipt", receipt["manifest_type"])
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("no_call", receipt["interpretation"]["authorized_hrd_state"])
        self.assertEqual("qc_only_not_hrd_evidence", receipt["interpretation"]["hrd_use"])
        self.assertEqual(SHA_1, receipt["source"]["bam_qc_plan_sha256"])
        self.assertEqual(0, receipt["materialized_outputs"]["tumor"]["quickcheck_log"]["bytes"])
        self.assertGreater(receipt["materialized_outputs"]["normal"]["flagstat"]["bytes"], 0)
        self.assertEqual(
            ["quickcheck", "flagstat", "idxstats"],
            list(receipt["commands"]["tumor"]),
        )

    def test_environment_command_writes_receipt_after_running_planned_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "bam-qc-plan.json"
            receipt_path = root / "bam-qc-receipt.json"
            plan = phase3_fast_bam_qc_plan(root)
            write_json(plan_path, plan)

            runner = MaterializingSamtoolsRunner()
            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_BAM_QC_PLAN": str(plan_path),
                    "PHASE3_WGS_FAST_BAM_QC_RECEIPT_OUTPUT": str(receipt_path),
                },
                clear=False,
            ):
                receipt, output = run_qc.load_receipt_from_environment(runner=runner)
                run_qc.write_receipt(output, receipt)
            expected_plan_sha256 = _sha256_json(plan_path)
            receipt_text = receipt_path.read_text(encoding="utf-8")

        self.assertEqual(receipt_path, output)
        self.assertEqual(expected_plan_sha256, receipt["source"]["bam_qc_plan_sha256"])
        self.assertEqual(6, len(runner.commands))
        self.assertIn('"manifest_type": "phase3_wgs_fast_bam_qc_receipt"', receipt_text)

    def test_environment_command_rejects_redirected_plan_before_running_samtools(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_plan = root / "real-bam-qc-plan.json"
            redirected_plan = root / "bam-qc-plan.json"
            write_json(real_plan, phase3_fast_bam_qc_plan(root))
            redirected_plan.symlink_to(real_plan)

            runner = MaterializingSamtoolsRunner()
            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_BAM_QC_PLAN": str(redirected_plan),
                    "PHASE3_WGS_FAST_BAM_QC_RECEIPT_OUTPUT": str(root / "bam-qc-receipt.json"),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(run_qc.ManifestError, "real JSON file"):
                    run_qc.load_receipt_from_environment(runner=runner)

        self.assertEqual([], runner.commands)

    def test_rejects_missing_planned_command(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_bam_qc_plan(Path(tmp))
        plan["commands"]["tumor"].pop("idxstats")

        with self.assertRaisesRegex(run_qc.ManifestError, "commands.tumor"):
            run_qc.run_phase3_fast_bam_qc(
                plan,
                runner=MaterializingSamtoolsRunner(),
                bam_qc_plan_sha256=SHA_1,
            )

    def test_rejects_command_that_would_skip_samtools(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_bam_qc_plan(Path(tmp))
        plan["commands"]["normal"]["flagstat"]["argv"] = ["true"]

        with self.assertRaisesRegex(run_qc.ManifestError, "samtools flagstat"):
            run_qc.run_phase3_fast_bam_qc(
                plan,
                runner=MaterializingSamtoolsRunner(),
                bam_qc_plan_sha256=SHA_1,
            )

    def test_clears_stale_output_before_requiring_fresh_materialization(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_bam_qc_plan(Path(tmp))
            stale_idxstats = Path(plan["outputs"]["tumor"]["idxstats"])
            stale_idxstats.parent.mkdir(parents=True, exist_ok=True)
            stale_idxstats.write_text("chr1\t25\t10\t0\n", encoding="utf-8")

            with self.assertRaisesRegex(run_qc.ManifestError, "tumor idxstats"):
                run_qc.run_phase3_fast_bam_qc(
                    plan,
                    runner=MaterializingSamtoolsRunner(skip={("tumor", "idxstats")}),
                    bam_qc_plan_sha256=SHA_1,
                )

            self.assertFalse(stale_idxstats.exists())

    def test_rejects_empty_flagstat_output(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_bam_qc_plan(Path(tmp))

            with self.assertRaisesRegex(run_qc.ManifestError, "normal flagstat"):
                run_qc.run_phase3_fast_bam_qc(
                    plan,
                    runner=MaterializingSamtoolsRunner(empty={("normal", "flagstat")}),
                    bam_qc_plan_sha256=SHA_1,
                )

    def test_rejects_tool_created_symlink_output_before_hashing_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_bam_qc_plan(Path(tmp))

            with self.assertRaisesRegex(run_qc.ManifestError, "may not be a symlink"):
                run_qc.run_phase3_fast_bam_qc(
                    plan,
                    runner=SymlinkSamtoolsRunner(),
                    bam_qc_plan_sha256=SHA_1,
                )

    def test_rejects_output_below_symlinked_parent_before_running_commands(self) -> None:
        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_output = root / "real-bam-qc"
                if nested == "existing":
                    (real_output / nested / "tumor").mkdir(parents=True)
                    (real_output / nested / "normal").mkdir(parents=True)
                else:
                    real_output.mkdir()
                output_root = root / "bam_qc"
                output_root.symlink_to(real_output, target_is_directory=True)
                plan = phase3_fast_bam_qc_plan(root)
                if nested == "existing":
                    for outputs in plan["outputs"].values():
                        for path in outputs.values():
                            Path(path).parent.mkdir(parents=True, exist_ok=True)
                runner = MaterializingSamtoolsRunner()

                with self.assertRaisesRegex(
                    run_qc.ManifestError, "parent may not be a symlink"
                ):
                    run_qc.run_phase3_fast_bam_qc(
                        plan,
                        runner=runner,
                        bam_qc_plan_sha256=SHA_1,
                    )

                self.assertEqual([], runner.commands)
                self.assertEqual([], [path for path in real_output.rglob("*") if path.is_file()])


if __name__ == "__main__":
    unittest.main()
