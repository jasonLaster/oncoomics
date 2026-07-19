from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import render_phase3_fast_parabricks_mutect_plan as parabricks
from diana_omics.commands.phase3_wgs import run_phase3_fast_parabricks_mutect as run_mutect
from diana_omics.utils import write_json
from tests.test_phase3_fast_input_manifest import SHA_1
from tests.test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest


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


class SymlinkMaterializingParabricksRunner(MaterializingParabricksRunner):
    def _write_output(self, key: str) -> None:
        super()._write_output(key)
        if key != "pon_annotated_vcf":
            return

        path = Path(self.plan["outputs"][key])
        target = path.parent / f"{key}.redirected"
        target.write_bytes(b"redirected pon annotated vcf\n")
        path.unlink()
        path.symlink_to(target)


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


def _without_flag(argv: list[str], flag: str) -> list[str]:
    index = argv.index(flag)
    return [*argv[:index], *argv[index + 2 :]]


def _replace_flag_value(argv: list[str], flag: str, value: str) -> list[str]:
    updated = list(argv)
    updated[updated.index(flag) + 1] = value
    return updated


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

    def test_environment_command_rejects_redirected_plan_before_running_pbrun(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_plan = root / "real-parabricks-plan.json"
            redirected_plan = root / "parabricks-plan.json"
            write_json(real_plan, parabricks_plan(root))
            redirected_plan.symlink_to(real_plan)

            runner = MaterializingParabricksRunner(parabricks_plan(root))
            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN": str(redirected_plan),
                    "PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT_OUTPUT": str(root / "parabricks-receipt.json"),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(run_mutect.ManifestError, "real JSON file"):
                    run_mutect.load_receipt_from_environment(runner=runner)

        self.assertEqual([], runner.commands)

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

    def test_rejects_tool_created_symlink_output_before_hashing_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))

            with self.assertRaisesRegex(run_mutect.ManifestError, "may not be a symlink"):
                run_mutect.run_phase3_fast_parabricks_mutect(
                    plan,
                    runner=SymlinkMaterializingParabricksRunner(plan),
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

    def test_rejects_non_p5en_runtime_gpu_count_before_running_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
        plan["runtime"]["num_gpus"] = 4

        runner = RecordingRunner()
        with self.assertRaisesRegex(run_mutect.ManifestError, "runtime.num_gpus"):
            run_mutect.run_phase3_fast_parabricks_mutect(
                plan,
                runner=runner,
                parabricks_mutect_plan_sha256=SHA_1,
            )

        self.assertEqual([], runner.commands)

    def test_rejects_boolean_runtime_gpu_count_before_running_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
        plan["runtime"]["num_gpus"] = True

        runner = RecordingRunner()
        with self.assertRaisesRegex(run_mutect.ManifestError, "runtime.num_gpus"):
            run_mutect.run_phase3_fast_parabricks_mutect(
                plan,
                runner=runner,
                parabricks_mutect_plan_sha256=SHA_1,
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

    def test_rejects_parabricks_command_missing_required_flag(self) -> None:
        cases = (
            ("prepon", "--in-pon-file"),
            ("mutectcaller", "--out-vcf"),
            ("mutectcaller", "--mutect-f1r2-tar-gz"),
            ("postpon", "--out-vcf"),
            ("postpon", "--num-gpus"),
        )
        for command_name, flag in cases:
            with self.subTest(command_name=command_name, flag=flag), TemporaryDirectory() as tmp:
                plan = parabricks_plan(Path(tmp))
                plan["commands"][command_name]["argv"] = _without_flag(
                    plan["commands"][command_name]["argv"],
                    flag,
                )
                runner = RecordingRunner()

                with self.assertRaisesRegex(run_mutect.ManifestError, flag):
                    run_mutect.run_phase3_fast_parabricks_mutect(
                        plan,
                        runner=runner,
                        parabricks_mutect_plan_sha256=SHA_1,
                    )

            self.assertEqual([], runner.commands)

    def test_rejects_parabricks_command_with_unplanned_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = parabricks_plan(Path(tmp))
        plan["commands"]["mutectcaller"]["argv"].extend(["--dry-run", "true"])

        with self.assertRaisesRegex(run_mutect.ManifestError, "unexpected --dry-run"):
            run_mutect.run_phase3_fast_parabricks_mutect(
                plan,
                runner=RecordingRunner(),
                parabricks_mutect_plan_sha256=SHA_1,
            )

    def test_rejects_parabricks_command_that_drifts_from_plan_contract(self) -> None:
        cases = (
            ("mutectcaller", "--out-vcf", "mutectcaller.wrong.vcf.gz"),
            ("mutectcaller", "--tumor-name", "normal-disguised-as-tumor"),
            ("postpon", "--in-vcf", "postpon.wrong.vcf.gz"),
        )
        for command_name, flag, file_name in cases:
            with self.subTest(command_name=command_name, flag=flag), TemporaryDirectory() as tmp:
                root = Path(tmp)
                value = str(root / "wrong" / file_name) if flag.endswith("vcf") else file_name
                plan = parabricks_plan(root)
                plan["commands"][command_name]["argv"] = _replace_flag_value(
                    plan["commands"][command_name]["argv"],
                    flag,
                    value,
                )
                runner = RecordingRunner()

                with self.assertRaisesRegex(run_mutect.ManifestError, flag):
                    run_mutect.run_phase3_fast_parabricks_mutect(
                        plan,
                        runner=runner,
                        parabricks_mutect_plan_sha256=SHA_1,
                    )

            self.assertEqual([], runner.commands)

    def test_rejects_output_below_symlinked_parent_before_running_commands(self) -> None:
        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), TemporaryDirectory() as tmp:
                root = Path(tmp)
                plan = parabricks_plan(root)
                real_output = root / "real-parabricks"
                if nested == "existing":
                    (real_output / nested / "variants").mkdir(parents=True)
                else:
                    real_output.mkdir()
                linked_output = root / "parabricks"
                linked_output.symlink_to(real_output, target_is_directory=True)
                if nested == "existing":
                    for path in plan["outputs"].values():
                        Path(path).parent.mkdir(parents=True, exist_ok=True)
                runner = RecordingRunner()

                with self.assertRaisesRegex(
                    run_mutect.ManifestError, "parent may not be a symlink"
                ):
                    run_mutect.run_phase3_fast_parabricks_mutect(
                        plan,
                        runner=runner,
                        parabricks_mutect_plan_sha256=SHA_1,
                    )

                self.assertEqual([], runner.commands)
                self.assertEqual([], [path for path in real_output.rglob("*") if path.is_file()])


if __name__ == "__main__":
    unittest.main()
