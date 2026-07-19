from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diana_omics.commands.phase3_wgs import plan_phase3_fast_crosscheck_inputs as crosscheck_plan
from diana_omics.commands.phase3_wgs import publish_phase3_fast_final_evidence as final_evidence
from diana_omics.utils import write_json
from tests.test_phase3_fast_evidence_join import SHA_4
from tests.test_phase3_fast_final_evidence import _join_manifest


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _final_evidence(root: Path) -> dict:
    return final_evidence.build_phase3_fast_final_evidence_manifest(
        _join_manifest(root),
        evidence_join_sha256=SHA_4,
        small_variant_artifact_root=root / "small_variant_export",
        bam_qc_artifact_root=root / "bam_qc",
        cnv_evidence_artifact_root=root / "cnv_evidence",
        sv_evidence_artifact_root=root / "sv_evidence",
        output_root=root / "final",
    )


class Phase3FastCrosscheckMaterializationPlanTests(unittest.TestCase):
    def test_plans_post_freeze_alias_inputs_for_sigprofiler_and_binds_sequenza_bams(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            final_manifest = _final_evidence(root)
            plan = crosscheck_plan.build_phase3_fast_crosscheck_materialization_plan(
                final_manifest,
                final_evidence_sha256=SHA_4,
            )

        final_sources = plan["sigprofiler_sbs3"]["final_sources"]
        reference_sources = plan["sigprofiler_sbs3"]["reference_sources"]
        sequenza_sources = plan["sequenza_scarhrd"]["source_artifacts"]

        self.assertEqual("phase3_wgs_fast_crosscheck_materialization_plan", plan["manifest_type"])
        self.assertEqual("awaiting_private_results_freeze", plan["status"])
        self.assertEqual("awaiting_private_results_freeze", plan["sigprofiler_sbs3"]["status"])
        self.assertEqual("no_call", plan["interpretation"]["authorized_hrd_state"])
        self.assertEqual(
            final_manifest["artifacts"]["small_variants"]["filter_mutect"]["filtered_vcf"]["relative_path"],
            final_sources["source_vcf"]["final_relative_path"],
        )
        self.assertEqual(
            final_manifest["artifacts"]["small_variants"]["filter_mutect"]["filtered_vcf_index"]["sha256"],
            final_sources["source_vcf_index"]["sha256"],
        )
        self.assertEqual(
            final_manifest["artifacts"]["small_variants"]["filter_mutect"]["sbs96_matrix"]["bytes"],
            final_sources["source_matrix"]["bytes"],
        )
        self.assertEqual(
            final_manifest["input_sources"]["reference"]["fasta"]["version_id"],
            reference_sources["reference_fasta"]["version_id"],
        )
        self.assertEqual(
            final_manifest["input_sources"]["reference"]["fai"]["sha256"],
            reference_sources["reference_fai"]["sha256"],
        )
        self.assertEqual("somatic.pass.vcf.gz", plan["sigprofiler_sbs3"]["outputs"]["somatic_vcf"])
        self.assertEqual("blocked", plan["sequenza_scarhrd"]["status"])
        self.assertEqual(
            {"sequenza": {"female": True}},
            plan["sequenza_scarhrd"]["method_parameters"],
        )
        self.assertEqual(
            [],
            plan["sequenza_scarhrd"]["required_method_parameters"],
        )
        self.assertEqual(
            final_manifest["input_sources"]["bam_pair"]["tumor"]["bam"]["version_id"],
            sequenza_sources["tumor_bam"]["version_id"],
        )
        self.assertEqual(
            final_manifest["input_sources"]["bam_pair"]["normal"]["bai"]["sha256"],
            sequenza_sources["normal_bai"]["sha256"],
        )
        self.assertEqual(
            "subject01_tumor",
            sequenza_sources["tumor_bam"]["sample_id"],
        )
        self.assertEqual(
            {
                "tumor_sample": "subject01_tumor",
                "normal_sample": "subject01_normal",
            },
            plan["sequenza_scarhrd"]["alias_input_contract"]["planned_aliases"],
        )
        self.assertEqual(
            final_manifest["input_sources"]["reference"]["sequence_dictionary"]["version_id"],
            plan["sequenza_scarhrd"]["alias_input_contract"]["reference"]["sequence_dictionary"]["version_id"],
        )
        self.assertEqual(
            final_manifest["input_sources"]["bam_pair"]["tumor"]["bam"]["sha256"],
            plan["sequenza_scarhrd"]["alias_input_contract"]["artifacts"]["tumor_bam"]["sha256"],
        )
        self.assertNotIn(
            "sample_id",
            plan["sequenza_scarhrd"]["alias_input_contract"]["artifacts"]["tumor_bam"],
        )
        self.assertEqual(
            "tumor.bam.bai",
            plan["sequenza_scarhrd"]["alias_input_contract"]["planned_alias_outputs"]["tumor_bai"],
        )
        self.assertFalse(
            plan["sequenza_scarhrd"]["alias_input_contract"]["attestations"]["final_bam_contract_published"],
        )
        self.assertEqual(
            "awaiting_final_bam_contract_and_validated_runtime",
            plan["blocked_routes"]["sequenza_scarhrd"],
        )
        self.assertNotIn(str(root), json.dumps(plan))
        self.assertNotIn("commands", plan)
        self.assertNotIn("inputs", plan)

    def test_rejects_unaliased_sequenza_bam_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _final_evidence(Path(tmp))
        manifest["input_sources"]["bam_pair"]["tumor"]["bam"]["sample_id"] = "source_tumor"

        with self.assertRaisesRegex(crosscheck_plan.ManifestError, "subject01_tumor"):
            crosscheck_plan.build_phase3_fast_crosscheck_materialization_plan(
                manifest,
                final_evidence_sha256=SHA_4,
            )

    def test_rejects_promoted_sbs3_boundary(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _final_evidence(Path(tmp))
        manifest["interpretation"]["sbs96_use"] = "ready"

        with self.assertRaisesRegex(crosscheck_plan.ManifestError, "sbs96_use"):
            crosscheck_plan.build_phase3_fast_crosscheck_materialization_plan(
                manifest,
                final_evidence_sha256=SHA_4,
            )

    def test_rejects_missing_final_artifact(self) -> None:
        with TemporaryDirectory() as tmp:
            manifest = _final_evidence(Path(tmp))
        manifest["artifacts"]["small_variants"]["filter_mutect"].pop("sbs96_matrix")

        with self.assertRaisesRegex(crosscheck_plan.ManifestError, "sbs96_matrix"):
            crosscheck_plan.build_phase3_fast_crosscheck_materialization_plan(
                manifest,
                final_evidence_sha256=SHA_4,
            )

    def test_rejects_boolean_byte_counts(self) -> None:
        cases = (
            (
                "artifacts.small_variants.filter_mutect.sbs96_matrix.bytes",
                lambda manifest: manifest["artifacts"]["small_variants"]["filter_mutect"]["sbs96_matrix"],
            ),
            (
                "input_sources.reference.fasta.bytes",
                lambda manifest: manifest["input_sources"]["reference"]["fasta"],
            ),
            (
                "input_sources.reference.sequence_dictionary.bytes",
                lambda manifest: manifest["input_sources"]["reference"]["sequence_dictionary"],
            ),
            (
                "input_sources.bam_pair.tumor.bam.bytes",
                lambda manifest: manifest["input_sources"]["bam_pair"]["tumor"]["bam"],
            ),
        )

        for label, select_row in cases:
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                manifest = _final_evidence(Path(tmp))
                select_row(manifest)["bytes"] = True

                with self.assertRaisesRegex(crosscheck_plan.ManifestError, label):
                    crosscheck_plan.build_phase3_fast_crosscheck_materialization_plan(
                        manifest,
                        final_evidence_sha256=SHA_4,
                    )

    def test_rejects_non_lowercase_sha256_values(self) -> None:
        cases = (
            (
                "final-evidence",
                lambda _manifest: None,
                SHA_4.upper(),
                "final_evidence_sha256",
            ),
            (
                "final-artifact",
                lambda manifest: manifest["artifacts"]["small_variants"][
                    "filter_mutect"
                ]["sbs96_matrix"].__setitem__(
                    "sha256",
                    manifest["artifacts"]["small_variants"]["filter_mutect"][
                        "sbs96_matrix"
                    ]["sha256"].upper(),
                ),
                SHA_4,
                "artifacts.small_variants.filter_mutect.sbs96_matrix.sha256",
            ),
            (
                "reference",
                lambda manifest: manifest["input_sources"]["reference"]["fasta"].__setitem__(
                    "sha256",
                    manifest["input_sources"]["reference"]["fasta"]["sha256"].upper(),
                ),
                SHA_4,
                "input_sources.reference.fasta.sha256",
            ),
            (
                "sequenza-bam",
                lambda manifest: manifest["input_sources"]["bam_pair"]["tumor"][
                    "bam"
                ].__setitem__(
                    "sha256",
                    manifest["input_sources"]["bam_pair"]["tumor"]["bam"][
                        "sha256"
                    ].upper(),
                ),
                SHA_4,
                "input_sources.bam_pair.tumor.bam.sha256",
            ),
        )

        for label, mutate, final_evidence_sha256, error in cases:
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                manifest = _final_evidence(Path(tmp))
                mutate(manifest)

                with self.assertRaisesRegex(crosscheck_plan.ManifestError, error):
                    crosscheck_plan.build_phase3_fast_crosscheck_materialization_plan(
                        manifest,
                        final_evidence_sha256=final_evidence_sha256,
                    )

    def test_environment_command_writes_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_path = root / "final-evidence.json"
            output_path = root / "crosscheck-materialization-plan.json"
            write_json(input_path, _final_evidence(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST": str(input_path),
                    "PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN": str(output_path),
                },
                clear=False,
            ):
                plan, output = crosscheck_plan.load_plan_from_environment()
                crosscheck_plan.write_plan(output, plan)
            output_text = output_path.read_text(encoding="utf-8")
            expected_manifest_sha256 = _sha256_path(input_path)

        self.assertEqual(output_path, output)
        self.assertEqual(expected_manifest_sha256, plan["source"]["final_evidence_manifest_sha256"])
        self.assertIn('"manifest_type": "phase3_wgs_fast_crosscheck_materialization_plan"', output_text)

    def test_environment_command_rejects_missing_directory_or_symlinked_final_evidence(self) -> None:
        cases = ("missing", "directory", "symlink")
        for bad_kind in cases:
            with self.subTest(bad_kind=bad_kind), TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_input = root / "real-final-evidence.json"
                bad_input = root / f"final-evidence-{bad_kind}.json"
                write_json(real_input, _final_evidence(root))
                if bad_kind == "directory":
                    bad_input.mkdir()
                elif bad_kind == "symlink":
                    bad_input.symlink_to(real_input)

                with patch.dict(
                    "os.environ",
                    {
                        "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST": str(bad_input),
                        "PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN": str(root / "plan.json"),
                    },
                    clear=False,
                ):
                    with self.assertRaisesRegex(crosscheck_plan.ManifestError, "final evidence"):
                        crosscheck_plan.load_plan_from_environment()

    def test_environment_command_rejects_final_evidence_below_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-inputs"
            linked_parent = root / "linked-inputs"
            real_parent.mkdir()
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            input_path = linked_parent / "final-evidence.json"
            write_json(input_path, _final_evidence(root))

            with patch.dict(
                "os.environ",
                {
                    "PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST": str(input_path),
                    "PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN": str(root / "plan.json"),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(crosscheck_plan.ManifestError, "final evidence parent may not be a symlink"):
                    crosscheck_plan.load_plan_from_environment()

    def test_sha256_path_rejects_symlinked_hash_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_parent = root / "real-parent"
            real_parent.mkdir()

            real_final = root / "real-final-evidence.json"
            real_final.write_text("{}\n", encoding="utf-8")
            symlinked_final = root / "final-evidence.json"
            symlinked_final.symlink_to(real_final)

            parent_final = real_parent / "final-evidence.json"
            parent_final.write_text("{}\n", encoding="utf-8")
            symlinked_parent = root / "symlinked-parent"
            symlinked_parent.symlink_to(real_parent, target_is_directory=True)

            cases = (
                (symlinked_final, "SHA-256 input"),
                (symlinked_parent / parent_final.name, "parent may not be a symlink"),
            )
            for hash_input, message in cases:
                with self.subTest(hash_input=hash_input), self.assertRaisesRegex(crosscheck_plan.ManifestError, message):
                    crosscheck_plan._sha256_path(hash_input)

    def test_plan_output_rejects_symlinked_parent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_output = root / "real-output"
            real_output.mkdir()
            linked_output = root / "linked-output"
            linked_output.symlink_to(real_output, target_is_directory=True)

            with self.assertRaisesRegex(crosscheck_plan.ManifestError, "parent may not be a symlink"):
                crosscheck_plan.write_plan(
                    linked_output / "crosscheck-materialization-plan.json",
                    {"status": "redirected"},
                )

            self.assertEqual([], list(real_output.rglob("*")))


if __name__ == "__main__":
    unittest.main()
