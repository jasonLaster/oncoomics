from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_phase3_fast_evidence_join import SHA_4
from test_phase3_fast_final_evidence import _join_manifest

from diana_omics.commands.phase3_wgs import plan_phase3_fast_crosscheck_inputs as crosscheck_plan
from diana_omics.commands.phase3_wgs import publish_phase3_fast_final_evidence as final_evidence
from diana_omics.utils import write_json


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
    def test_plans_post_freeze_alias_inputs_for_sigprofiler_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            final_manifest = _final_evidence(root)
            plan = crosscheck_plan.build_phase3_fast_crosscheck_materialization_plan(
                final_manifest,
                final_evidence_sha256=SHA_4,
            )

        final_sources = plan["sigprofiler_sbs3"]["final_sources"]
        reference_sources = plan["sigprofiler_sbs3"]["reference_sources"]

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
        self.assertEqual("awaiting_allele_specific_cnv_loh_segments", plan["blocked_routes"]["sequenza_scarhrd"])
        self.assertNotIn(str(root), json.dumps(plan))
        self.assertNotIn("commands", plan)
        self.assertNotIn("inputs", plan)

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


if __name__ == "__main__":
    unittest.main()
