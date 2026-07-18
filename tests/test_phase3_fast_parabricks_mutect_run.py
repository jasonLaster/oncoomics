from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_input_manifest import SHA_1
from test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest

from diana_omics.commands.phase3_wgs import render_phase3_fast_parabricks_mutect_plan as parabricks
from diana_omics.commands.phase3_wgs import run_phase3_fast_parabricks_mutect as run_mutect
from diana_omics.utils import write_json


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, argv: list[str]) -> None:
        self.commands.append(list(argv))


class MaterializingParabricksRunner(RecordingRunner):
    def __init__(self, plan: dict, *, skip: set[str] | None = None, empty: set[str] | None = None) -> None:
        super().__init__()
        self.plan = plan
        self.skip = skip or set()
        self.empty = empty or set()
        self.payloads: dict[str, bytes] = {}

    def run(self, argv: list[str]) -> None:
        super().run(argv)
        if argv[:2] == ["pbrun", "mutectcaller"]:
            for key in ("raw_vcf", "raw_vcf_stats", "f1r2_tar_gz"):
                self._write_output(key)
        elif argv[:2] == ["pbrun", "postpon"]:
            self._write_output("pon_annotated_vcf")

    def _write_output(self, key: str) -> None:
        if key in self.skip:
            return
        path = Path(self.plan["outputs"][key])
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"" if key in self.empty else f"fresh {key}\n".encode()
        path.write_bytes(payload)
        self.payloads[key] = payload


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parabricks_plan(root: Path) -> dict:
    return parabricks.build_phase3_fast_parabricks_mutect_plan(
        staged_inputs_manifest(root),
        staged_inputs_manifest_sha256=SHA_1,
        output_root=root / "parabricks",
        num_gpus=8,
    )


def write_materialized_outputs(plan: dict) -> dict[str, bytes]:
    payloads = {
        key: f"{key}\n".encode()
        for key in run_mutect.MATERIALIZED_OUTPUTS
    }
    for key, payload in payloads.items():
        path = Path(plan["outputs"][key])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return payloads


class Phase3FastParabricksMutectRunTests(unittest.TestCase):
    def test_runs_prepon_mutectcaller_and_postpon_then_writes_completed_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
            runner = MaterializingParabricksRunner(plan)
            receipt = run_mutect.run_phase3_fast_parabricks_mutect(
                plan,
                runner=runner,
                parabricks_mutect_plan_sha256=SHA_1,
            )

        self.assertEqual(
            [
                plan["commands"]["prepon"]["argv"],
                plan["commands"]["mutectcaller"]["argv"],
                plan["commands"]["postpon"]["argv"],
            ],
            runner.commands,
        )
        self.assertEqual("phase3_wgs_fast_parabricks_mutect_receipt", receipt["manifest_type"])
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("no_call", receipt["interpretation"]["authorized_hrd_state"])
        self.assertEqual(SHA_1, receipt["source"]["parabricks_mutect_plan_sha256"])
        self.assertEqual(plan["workflow"], receipt["workflow"])
        self.assertEqual(plan["run"], receipt["run"])
        self.assertEqual(plan["runtime"], receipt["runtime"])
        self.assertEqual(plan["inputs"], receipt["inputs"])
        self.assertEqual(plan["outputs"], receipt["outputs"])
        self.assertEqual(set(run_mutect.MATERIALIZED_OUTPUTS), set(receipt["materialized_outputs"]))
        self.assertEqual(
            hashlib.sha256(runner.payloads["raw_vcf"]).hexdigest(),
            receipt["materialized_outputs"]["raw_vcf"]["sha256"],
        )
        self.assertEqual(
            len(runner.payloads["pon_annotated_vcf"]),
            receipt["materialized_outputs"]["pon_annotated_vcf"]["bytes"],
        )
        self.assertEqual(
            ["prepon", "mutectcaller", "postpon"],
            list(receipt["commands"]),
        )
        self.assertEqual("completed", receipt["commands"]["prepon"]["status"])

    def test_environment_command_writes_receipt_after_running_planned_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "parabricks-plan.json"
            receipt_path = root / "parabricks-receipt.json"
            plan = parabricks_plan(root)
            write_json(plan_path, plan)

            runner = MaterializingParabricksRunner(plan)
            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN": str(plan_path),
                    "PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT_OUTPUT": str(receipt_path),
                },
                clear=False,
            ):
                receipt, output = run_mutect.load_receipt_from_environment(runner=runner)
                run_mutect.write_receipt(output, receipt)
            expected_plan_sha256 = _sha256_json(plan_path)
            receipt_text = receipt_path.read_text(encoding="utf-8")

        self.assertEqual(receipt_path, output)
        self.assertEqual(expected_plan_sha256, receipt["source"]["parabricks_mutect_plan_sha256"])
        self.assertEqual(plan["commands"]["prepon"]["argv"], runner.commands[0])
        self.assertIn('"manifest_type": "phase3_wgs_fast_parabricks_mutect_receipt"', receipt_text)

    def test_rejects_missing_materialized_output(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
            runner = MaterializingParabricksRunner(plan, skip={"f1r2_tar_gz"})

            with self.assertRaisesRegex(run_mutect.ManifestError, "f1r2_tar_gz"):
                run_mutect.run_phase3_fast_parabricks_mutect(
                    plan,
                    runner=runner,
                    parabricks_mutect_plan_sha256=SHA_1,
                )

    def test_rejects_empty_materialized_output(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
            runner = MaterializingParabricksRunner(plan, empty={"raw_vcf_stats"})

            with self.assertRaisesRegex(run_mutect.ManifestError, "raw_vcf_stats"):
                run_mutect.run_phase3_fast_parabricks_mutect(
                    plan,
                    runner=runner,
                    parabricks_mutect_plan_sha256=SHA_1,
                )

    def test_removes_stale_outputs_before_running_planned_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
            write_materialized_outputs(plan)

            with self.assertRaisesRegex(run_mutect.ManifestError, "f1r2_tar_gz"):
                run_mutect.run_phase3_fast_parabricks_mutect(
                    plan,
                    runner=MaterializingParabricksRunner(plan, skip={"f1r2_tar_gz"}),
                    parabricks_mutect_plan_sha256=SHA_1,
                )

    def test_rejects_missing_planned_command(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
        plan["commands"].pop("postpon")

        with self.assertRaisesRegex(run_mutect.ManifestError, "commands"):
            run_mutect.run_phase3_fast_parabricks_mutect(
                plan,
                runner=RecordingRunner(),
                parabricks_mutect_plan_sha256=SHA_1,
            )

    def test_rejects_misordered_planned_command(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
        plan["commands"] = {
            "mutectcaller": plan["commands"]["mutectcaller"],
            "prepon": plan["commands"]["prepon"],
            "postpon": plan["commands"]["postpon"],
        }

        with self.assertRaisesRegex(run_mutect.ManifestError, "execution order"):
            run_mutect.run_phase3_fast_parabricks_mutect(
                plan,
                runner=RecordingRunner(),
                parabricks_mutect_plan_sha256=SHA_1,
            )

    def test_rejects_non_no_call_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
        plan["interpretation"]["authorized_hrd_state"] = "partial_evidence"

        with self.assertRaisesRegex(run_mutect.ManifestError, "no_call"):
            run_mutect.run_phase3_fast_parabricks_mutect(
                plan,
                runner=RecordingRunner(),
                parabricks_mutect_plan_sha256=SHA_1,
            )

    def test_rejects_invalid_plan_sha_before_running_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
            write_materialized_outputs(plan)

            runner = RecordingRunner()
            with self.assertRaisesRegex(run_mutect.ManifestError, "parabricks_mutect_plan_sha256"):
                run_mutect.run_phase3_fast_parabricks_mutect(
                    plan,
                    runner=runner,
                    parabricks_mutect_plan_sha256="not-a-sha",
                )

        self.assertEqual([], runner.commands)

    def test_rejects_command_that_would_skip_pbrun(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
        plan["commands"]["prepon"]["argv"] = ["true"]

        with self.assertRaisesRegex(run_mutect.ManifestError, "pbrun prepon"):
            run_mutect.run_phase3_fast_parabricks_mutect(
                plan,
                runner=RecordingRunner(),
                parabricks_mutect_plan_sha256=SHA_1,
            )


if __name__ == "__main__":
    unittest.main()
