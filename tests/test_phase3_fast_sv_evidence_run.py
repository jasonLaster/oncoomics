from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import render_phase3_fast_sv_evidence_plan as sv_evidence
from diana_omics.commands.phase3_wgs import run_phase3_fast_sv_evidence as run_sv
from diana_omics.utils import write_json
from tests.test_phase3_fast_input_manifest import SHA_1
from tests.test_phase3_fast_parabricks_mutect_plan import staged_inputs_manifest


class MaterializingSamtoolsRunner:
    def __init__(
        self,
        *,
        skip: set[tuple[str, str]] | None = None,
        malformed: set[tuple[str, str]] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
        self.skip = skip or set()
        self.malformed = malformed or set()

    def run(self, argv: list[str], *, stdout_path: Path) -> None:
        self.commands.append(list(argv))
        role = stdout_path.parent.name
        name = _command_name(stdout_path)
        if (role, name) in self.skip:
            return

        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        if name == "idxstats":
            stdout_path.write_text("chr1\t25\t10\t0\n", encoding="utf-8")
        elif name == "supplementary_alignments" and (role, name) in self.malformed:
            stdout_path.write_text("not-a-count\n", encoding="utf-8")
        elif name == "supplementary_alignments":
            stdout_path.write_text("7\n", encoding="utf-8")
        elif role == "normal":
            stdout_path.write_bytes(b"")
        else:
            stdout_path.write_bytes(b"read1\t99\tchr1\t1\t60\t1M\t=\t10\t9\tA\t*\n")


def _command_name(path: Path) -> str:
    if path.name == "idxstats.tsv":
        return "idxstats"
    if path.name == "supplementary_alignments.count.txt":
        return "supplementary_alignments"
    if path.name == "discordant_mapped_pairs.sam":
        return "discordant_mapped_pairs"
    raise ValueError(f"Unexpected SV evidence output path: {path}")


def _sha256_json(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase3_fast_sv_evidence_plan(root: Path) -> dict:
    return sv_evidence.build_phase3_fast_sv_evidence_plan(
        staged_inputs_manifest(root),
        staged_inputs_manifest_sha256=SHA_1,
        output_root=root / "sv_evidence",
        threads=8,
    )


class Phase3FastSvEvidenceRunTests(unittest.TestCase):
    def test_runs_samtools_commands_and_writes_completed_receipt(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_sv_evidence_plan(Path(tmp))
            runner = MaterializingSamtoolsRunner()

            receipt = run_sv.run_phase3_fast_sv_evidence(
                plan,
                runner=runner,
                sv_evidence_plan_sha256=SHA_1,
            )

        self.assertEqual(
            [
                plan["commands"][role][name]["argv"]
                for role in run_sv.ROLES
                for name in run_sv.EXPECTED_COMMANDS
            ],
            runner.commands,
        )
        self.assertEqual("phase3_wgs_fast_sv_evidence_receipt", receipt["manifest_type"])
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("no_call", receipt["interpretation"]["authorized_hrd_state"])
        self.assertEqual("no_call_requires_validated_production_sv_caller_vcf", receipt["interpretation"]["chord_use"])
        self.assertEqual(
            "no_call_requires_validated_structural_variant_features",
            receipt["interpretation"]["hrdetect_use"],
        )
        self.assertEqual(SHA_1, receipt["source"]["sv_evidence_plan_sha256"])
        self.assertEqual(7, receipt["metrics"]["tumor"]["supplementary_alignments"])
        self.assertEqual(0, receipt["materialized_outputs"]["normal"]["discordant_mapped_pairs"]["bytes"])
        self.assertGreater(receipt["materialized_outputs"]["tumor"]["idxstats"]["bytes"], 0)
        self.assertEqual(
            ["idxstats", "supplementary_alignments", "discordant_mapped_pairs"],
            list(receipt["commands"]["tumor"]),
        )

    def test_environment_command_writes_receipt_after_running_planned_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "sv-plan.json"
            receipt_path = root / "sv-receipt.json"
            plan = phase3_fast_sv_evidence_plan(root)
            write_json(plan_path, plan)

            runner = MaterializingSamtoolsRunner()
            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_SV_EVIDENCE_PLAN": str(plan_path),
                    "PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT_OUTPUT": str(receipt_path),
                },
                clear=False,
            ):
                receipt, output = run_sv.load_receipt_from_environment(runner=runner)
                run_sv.write_receipt(output, receipt)
            expected_plan_sha256 = _sha256_json(plan_path)
            receipt_text = receipt_path.read_text(encoding="utf-8")

        self.assertEqual(receipt_path, output)
        self.assertEqual(expected_plan_sha256, receipt["source"]["sv_evidence_plan_sha256"])
        self.assertEqual(6, len(runner.commands))
        self.assertIn('"manifest_type": "phase3_wgs_fast_sv_evidence_receipt"', receipt_text)

    def test_environment_command_rejects_redirected_plan_before_running_samtools(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_plan = root / "real-sv-plan.json"
            redirected_plan = root / "sv-plan.json"
            write_json(real_plan, phase3_fast_sv_evidence_plan(root))
            redirected_plan.symlink_to(real_plan)

            runner = MaterializingSamtoolsRunner()
            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_SV_EVIDENCE_PLAN": str(redirected_plan),
                    "PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT_OUTPUT": str(root / "sv-receipt.json"),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(run_sv.ManifestError, "real JSON file"):
                    run_sv.load_receipt_from_environment(runner=runner)

        self.assertEqual([], runner.commands)

    def test_rejects_missing_planned_command(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_sv_evidence_plan(Path(tmp))
        plan["commands"]["normal"].pop("discordant_mapped_pairs")

        with self.assertRaisesRegex(run_sv.ManifestError, "commands.normal"):
            run_sv.run_phase3_fast_sv_evidence(
                plan,
                runner=MaterializingSamtoolsRunner(),
                sv_evidence_plan_sha256=SHA_1,
            )

    def test_rejects_command_that_would_skip_samtools(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_sv_evidence_plan(Path(tmp))
        plan["commands"]["tumor"]["idxstats"]["argv"] = ["true"]

        with self.assertRaisesRegex(run_sv.ManifestError, "samtools idxstats"):
            run_sv.run_phase3_fast_sv_evidence(
                plan,
                runner=MaterializingSamtoolsRunner(),
                sv_evidence_plan_sha256=SHA_1,
            )

    def test_clears_stale_output_before_requiring_fresh_materialization(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_sv_evidence_plan(Path(tmp))
            stale_supplementary = Path(plan["outputs"]["normal"]["supplementary_alignments"])
            stale_supplementary.parent.mkdir(parents=True, exist_ok=True)
            stale_supplementary.write_text("11\n", encoding="utf-8")

            with self.assertRaisesRegex(run_sv.ManifestError, "normal supplementary_alignments"):
                run_sv.run_phase3_fast_sv_evidence(
                    plan,
                    runner=MaterializingSamtoolsRunner(skip={("normal", "supplementary_alignments")}),
                    sv_evidence_plan_sha256=SHA_1,
                )

            self.assertFalse(stale_supplementary.exists())

    def test_rejects_malformed_supplementary_count(self) -> None:
        with TemporaryDirectory() as tmp:
            plan = phase3_fast_sv_evidence_plan(Path(tmp))

            with self.assertRaisesRegex(run_sv.ManifestError, "tumor supplementary_alignments count"):
                run_sv.run_phase3_fast_sv_evidence(
                    plan,
                    runner=MaterializingSamtoolsRunner(malformed={("tumor", "supplementary_alignments")}),
                    sv_evidence_plan_sha256=SHA_1,
                )

    def test_rejects_output_below_symlinked_parent_before_running_commands(self) -> None:
        for nested in ("missing", "existing"):
            with self.subTest(nested=nested), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_output = root / "real-sv-evidence"
                if nested == "existing":
                    (real_output / nested / "tumor").mkdir(parents=True)
                    (real_output / nested / "normal").mkdir(parents=True)
                else:
                    real_output.mkdir()
                output_root = root / "sv_evidence"
                output_root.symlink_to(real_output, target_is_directory=True)
                plan = phase3_fast_sv_evidence_plan(root)
                if nested == "existing":
                    for outputs in plan["outputs"].values():
                        for path in outputs.values():
                            Path(path).parent.mkdir(parents=True, exist_ok=True)
                runner = MaterializingSamtoolsRunner()

                with self.assertRaisesRegex(
                    run_sv.ManifestError, "parent may not be a symlink"
                ):
                    run_sv.run_phase3_fast_sv_evidence(
                        plan,
                        runner=runner,
                        sv_evidence_plan_sha256=SHA_1,
                    )

                self.assertEqual([], runner.commands)
                self.assertEqual([], [path for path in real_output.rglob("*") if path.is_file()])


if __name__ == "__main__":
    unittest.main()
