import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_known_answer_readiness as known


class KnownAnswerReadinessTest(unittest.TestCase):
    def test_validate_manifest_requires_unlocked_planned_fixtures(self):
        rows = [_fixture_row("hg008_small_variants", "giab_hg008", "small_variant_snv_indel", "small_variant_feature_validation")]
        rows[0]["current_status"] = "implemented"
        rows[0]["threshold_status"] = "locked"
        errors = "\n".join(known.validate_manifest(rows))
        self.assertIn("must remain planned_not_run", errors)
        self.assertIn("cannot lock thresholds", errors)

    def test_main_writes_planned_fixture_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / known.MANIFEST_PATH
            manifest_path.parent.mkdir(parents=True)
            utils.write_csv(
                manifest_path,
                [
                    _fixture_row("hg008_small_variants", "giab_hg008", "small_variant_snv_indel", "small_variant_feature_validation"),
                    _fixture_row("hg008_sv_cnv", "giab_hg008", "sv_cnv", "sv_cnv_feature_validation"),
                    _fixture_row("hg008_signature_qc", "giab_hg008", "signature_qc", "signature_adapter_validation"),
                    _fixture_row("colo829_driver_signature", "colo829", "driver_signature_guardrail", "negative_guardrail_validation"),
                    _fixture_row("colo829_sv_cna", "colo829", "sv_cna", "sv_cnv_feature_validation"),
                    _fixture_row(
                        "colo829_purity_series",
                        "colo829_purity_series",
                        "dilution_sensitivity",
                        "limit_of_detection_stress_validation",
                    ),
                ],
            )
            utils.write_json(root / known.PHASE3_SUMMARY_PATH, {"status": "passed", "phase3Complete": True})
            (root / known.HRD_INTERPRETATION_READINESS_PATH).parent.mkdir(parents=True, exist_ok=True)
            utils.write_json(
                root / known.HRD_INTERPRETATION_READINESS_PATH,
                {"status": "passed", "summary": {"ready_for_clinical_interpretation": "no"}},
            )
            utils.write_json(
                root / known.BENCHMARK_PLAN_SUMMARY_PATH,
                {"status": "passed", "summary": {"ready_for_benchmark_execution": "no"}},
            )
            with patch.object(known, "path_from_root", lambda relative: root / relative):
                known.main()
            summary = utils.read_json(root / known.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["fixture_count"], 6)
        self.assertEqual(summary["summary"]["locked_threshold_count"], 0)
        self.assertEqual(summary["summary"]["ready_for_clinical_interpretation"], "no")
        self.assertEqual(summary["summary"]["benchmark_execution_ready"], "no")
        self.assertEqual({row["clinical_interpretation_allowed"] for row in summary["rows"]}, {"no"})


def _fixture_row(fixture_id: str, dataset_id: str, truth_scope: str, gate: str) -> dict[str, str]:
    return {
        "fixture_id": fixture_id,
        "priority": "1",
        "dataset_id": dataset_id,
        "sample_pair": "tumor/normal",
        "modality": "tumor_normal_wgs",
        "truth_scope": truth_scope,
        "required_truth_or_expected_answer": "truth files",
        "required_output": "summary",
        "clinicalization_gate": gate,
        "current_status": "planned_not_run",
        "threshold_status": "not_locked",
        "source_url": "https://example.test",
        "caveat": "not validated",
    }


if __name__ == "__main__":
    unittest.main()
