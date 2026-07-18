from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_1
from test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest
from test_phase3_fast_parabricks_mutect_run import MaterializingParabricksRunner, RecordingRunner

from diana_omics.commands.phase3_wgs import render_phase3_fast_filter_mutect_plan as filter_mutect
from diana_omics.commands.phase3_wgs import render_phase3_fast_parabricks_mutect_plan as parabricks
from diana_omics.commands.phase3_wgs import run_phase3_fast_filter_mutect as run_filter
from diana_omics.commands.phase3_wgs import run_phase3_fast_parabricks_mutect as run_parabricks
from diana_omics.utils import write_json

SHA_2 = "b" * 64
SHA_3 = "c" * 64


class FilterMutectRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, argv: list[str]) -> None:
        self.commands.append(list(argv))
        if "GetPileupSummaries" in argv or "LearnReadOrientationModel" in argv:
            self._write_option_output(argv, "-O")
        elif "CalculateContamination" in argv:
            self._write_option_output(argv, "-O")
            self._write_option_output(argv, "--tumor-segmentation")
        elif "FilterMutectCalls" in argv:
            self._write_option_output(argv, "-O")
        elif argv[:2] == ["bcftools", "index"]:
            self._write(Path(f"{argv[-1]}.tbi"))

    def _write_option_output(self, argv: list[str], option: str) -> None:
        self._write(Path(argv[argv.index(option) + 1]))

    def _write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{path.name}\n".encode())


class IncompleteFilterMutectRunner(FilterMutectRunner):
    def run(self, argv: list[str]) -> None:
        self.commands.append(list(argv))
        if "GetPileupSummaries" in argv or "LearnReadOrientationModel" in argv:
            self._write_option_output(argv, "-O")
        elif "CalculateContamination" in argv:
            self._write_option_output(argv, "-O")
            self._write_option_output(argv, "--tumor-segmentation")
        elif "FilterMutectCalls" in argv:
            self._write_option_output(argv, "-O")


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def filter_plan_and_parabricks_receipt(root: Path) -> tuple[dict, dict]:
    staged = staged_inputs_manifest(root)
    mutect_plan = parabricks.build_phase3_fast_parabricks_mutect_plan(
        staged,
        staged_inputs_manifest_sha256=SHA_1,
        output_root=root / "parabricks",
        num_gpus=8,
    )
    parabricks_receipt = run_parabricks.run_phase3_fast_parabricks_mutect(
        mutect_plan,
        runner=MaterializingParabricksRunner(mutect_plan),
        parabricks_mutect_plan_sha256=SHA_2,
    )
    filter_plan = filter_mutect.build_phase3_fast_filter_mutect_plan(
        staged,
        mutect_plan,
        staged_inputs_manifest_sha256=SHA_1,
        mutect_plan_sha256=SHA_2,
        output_root=root / "filter_mutect",
    )
    return filter_plan, parabricks_receipt


class Phase3FastFilterMutectRunTests(unittest.TestCase):
    def test_runs_filter_tail_and_writes_completed_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))

            runner = FilterMutectRunner()
            receipt = run_filter.run_phase3_fast_filter_mutect(
                plan,
                parabricks_receipt,
                runner=runner,
                filter_mutect_plan_sha256=SHA_1,
                parabricks_mutect_receipt_sha256=SHA_3,
            )

        self.assertEqual([plan["commands"][name]["argv"] for name in run_filter.EXPECTED_COMMANDS], runner.commands)
        self.assertEqual("phase3_wgs_fast_filter_mutect_receipt", receipt["manifest_type"])
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("no_call", receipt["interpretation"]["authorized_hrd_state"])
        self.assertEqual(SHA_1, receipt["source"]["filter_mutect_plan_sha256"])
        self.assertEqual(SHA_3, receipt["source"]["parabricks_mutect_receipt_sha256"])
        self.assertEqual(plan["inputs"], receipt["inputs"])
        self.assertEqual(plan["outputs"], receipt["outputs"])
        self.assertEqual(set(run_filter.MATERIALIZED_OUTPUTS), set(receipt["materialized_outputs"]))
        self.assertGreater(receipt["materialized_outputs"]["filtered_vcf"]["bytes"], 0)

    def test_environment_command_writes_receipt_after_running_planned_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "filter-plan.json"
            parabricks_receipt_path = root / "parabricks-receipt.json"
            receipt_path = root / "filter-receipt.json"
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(root)
            write_json(plan_path, plan)
            write_json(parabricks_receipt_path, parabricks_receipt)

            runner = FilterMutectRunner()
            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_FILTER_MUTECT_PLAN": str(plan_path),
                    "PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT": str(parabricks_receipt_path),
                    "PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT_OUTPUT": str(receipt_path),
                },
                clear=False,
            ):
                receipt, output = run_filter.load_receipt_from_environment(runner=runner)
                run_filter.write_receipt(output, receipt)
            expected_plan_sha256 = _sha256_json(plan_path)
            expected_parabricks_sha256 = _sha256_json(parabricks_receipt_path)
            receipt_text = receipt_path.read_text(encoding="utf-8")

        self.assertEqual(receipt_path, output)
        self.assertEqual(expected_plan_sha256, receipt["source"]["filter_mutect_plan_sha256"])
        self.assertEqual(expected_parabricks_sha256, receipt["source"]["parabricks_mutect_receipt_sha256"])
        self.assertIn('"manifest_type": "phase3_wgs_fast_filter_mutect_receipt"', receipt_text)

    def test_rejects_mismatched_parabricks_plan_sha(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))
            parabricks_receipt["source"]["parabricks_mutect_plan_sha256"] = SHA_3

            with self.assertRaisesRegex(run_filter.ManifestError, "Parabricks receipt"):
                run_filter.run_phase3_fast_filter_mutect(
                    plan,
                    parabricks_receipt,
                    runner=FilterMutectRunner(),
                    filter_mutect_plan_sha256=SHA_1,
                    parabricks_mutect_receipt_sha256=SHA_3,
                )

    def test_rejects_parabricks_local_path_drift(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))
            raw_vcf = parabricks_receipt["materialized_outputs"]["raw_vcf"]
            raw_vcf["local_path"] = str(Path(tmp) / "elsewhere.vcf.gz")

            with self.assertRaisesRegex(run_filter.ManifestError, "raw_vcf local_path"):
                run_filter.run_phase3_fast_filter_mutect(
                    plan,
                    parabricks_receipt,
                    runner=FilterMutectRunner(),
                    filter_mutect_plan_sha256=SHA_1,
                    parabricks_mutect_receipt_sha256=SHA_3,
                )

    def test_rejects_parabricks_file_that_changed_after_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))
            Path(parabricks_receipt["materialized_outputs"]["raw_vcf"]["local_path"]).write_bytes(b"changed\n")

            with self.assertRaisesRegex(run_filter.ManifestError, "raw_vcf bytes and sha256"):
                run_filter.run_phase3_fast_filter_mutect(
                    plan,
                    parabricks_receipt,
                    runner=FilterMutectRunner(),
                    filter_mutect_plan_sha256=SHA_1,
                    parabricks_mutect_receipt_sha256=SHA_3,
                )

    def test_rejects_missing_planned_command(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))
            plan["commands"].pop("filter_mutect_calls")

            with self.assertRaisesRegex(run_filter.ManifestError, "commands"):
                run_filter.run_phase3_fast_filter_mutect(
                    plan,
                    parabricks_receipt,
                    runner=FilterMutectRunner(),
                    filter_mutect_plan_sha256=SHA_1,
                    parabricks_mutect_receipt_sha256=SHA_3,
                )

    def test_rejects_non_no_call_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))
            plan["interpretation"]["authorized_hrd_state"] = "partial_evidence"

            with self.assertRaisesRegex(run_filter.ManifestError, "no_call"):
                run_filter.run_phase3_fast_filter_mutect(
                    plan,
                    parabricks_receipt,
                    runner=FilterMutectRunner(),
                    filter_mutect_plan_sha256=SHA_1,
                    parabricks_mutect_receipt_sha256=SHA_3,
                )

    def test_rejects_invalid_receipt_sha_before_running_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))

            runner = FilterMutectRunner()
            with self.assertRaisesRegex(run_filter.ManifestError, "parabricks_mutect_receipt_sha256"):
                run_filter.run_phase3_fast_filter_mutect(
                    plan,
                    parabricks_receipt,
                    runner=runner,
                    filter_mutect_plan_sha256=SHA_1,
                    parabricks_mutect_receipt_sha256="not-a-sha",
                )

        self.assertEqual([], runner.commands)

    def test_rejects_missing_filter_output(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))

            with self.assertRaisesRegex(run_filter.ManifestError, "tumor_pileups"):
                run_filter.run_phase3_fast_filter_mutect(
                    plan,
                    parabricks_receipt,
                    runner=RecordingRunner(),
                    filter_mutect_plan_sha256=SHA_1,
                    parabricks_mutect_receipt_sha256=SHA_3,
                )

    def test_removes_stale_outputs_before_running_planned_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan, parabricks_receipt = filter_plan_and_parabricks_receipt(Path(tmp))
            runner = FilterMutectRunner()
            for command in plan["commands"].values():
                runner.run(command["argv"])

            with self.assertRaisesRegex(run_filter.ManifestError, "pon_annotated_vcf_index"):
                run_filter.run_phase3_fast_filter_mutect(
                    plan,
                    parabricks_receipt,
                    runner=IncompleteFilterMutectRunner(),
                    filter_mutect_plan_sha256=SHA_1,
                    parabricks_mutect_receipt_sha256=SHA_3,
                )


if __name__ == "__main__":
    unittest.main()
