import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_clinical_qc_thresholds as verify


class ClinicalQcThresholdsTest(unittest.TestCase):
    def test_threshold_manifest_writes_not_locked_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / verify.MANIFEST_PATH, _all_threshold_rows())
            (root / verify.CLINICAL_BOUNDARIES_PATH).parent.mkdir(parents=True, exist_ok=True)
            utils.write_json(
                root / verify.CLINICAL_BOUNDARIES_PATH,
                {
                    "status": "passed",
                    "summary": {
                        "clinical_reporting_allowed": "no",
                        "reportable_range_locked": "no",
                    },
                },
            )
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["threshold_count"], 10)
        self.assertEqual(summary["summary"]["locked_threshold_count"], 0)
        self.assertEqual(summary["summary"]["clinical_use_allowed_count"], 0)
        self.assertEqual(summary["summary"]["reportable_range_locked"], "no")

    def test_threshold_manifest_rejects_locked_or_clinical_rows(self):
        rows = _all_threshold_rows()
        rows[0]["lock_status"] = "locked"
        rows[0]["clinical_use_allowed"] = "yes"
        rows[0]["signoff_status"] = "approved"
        errors = "\n".join(verify.validate_manifest(rows))
        self.assertIn("cannot lock thresholds", errors)
        self.assertIn("clinical_use_allowed=no", errors)
        self.assertIn("cannot be approved", errors)

    def test_threshold_manifest_requires_no_call_impact(self):
        rows = _all_threshold_rows()
        rows[0]["no_call_if_unmet"] = "no"
        rows[0]["reportable_range_impact"] = "Proceed with interpretation"
        errors = "\n".join(verify.validate_manifest(rows))
        self.assertIn("no_call_if_unmet=yes", errors)
        self.assertIn("no-call reportable-range impact", errors)


def _all_threshold_rows() -> list[dict[str, str]]:
    rows = [
        _row("raw_input_identity", "preanalytic_qc", "input"),
        _row("sample_pairing_qc", "preanalytic_qc", "input"),
        _row("bam_reference_compatibility", "alignment_qc", "alignment"),
        _row("bam_coverage_acceptance", "alignment_qc", "alignment"),
        _row("small_variant_concordance", "accuracy_qc", "small_variant"),
        _row("allele_specific_cnv_loh_overlap", "accuracy_qc", "cnv_loh"),
        _row("sv_caller_overlap", "accuracy_qc", "sv"),
        _row("signature_mutation_count", "signature_qc", "signature"),
        _row("integrated_hrd_model_inputs", "model_qc", "integrated_hrd"),
        _row("report_generation_gate", "reporting_qc", "reporting"),
    ]
    return rows


def _row(threshold_id: str, domain: str, feature_class: str) -> dict[str, str]:
    return {
        "threshold_id": threshold_id,
        "threshold_domain": domain,
        "feature_class": feature_class,
        "metric_name": "metric",
        "threshold_kind": "qualitative",
        "proposed_threshold": "validation_required",
        "lock_status": "draft_not_locked",
        "evidence_dependency": "validation evidence",
        "no_call_if_unmet": "yes",
        "reportable_range_impact": "No interpretation if threshold is unmet.",
        "clinical_use_allowed": "no",
        "signoff_status": "not_approved",
        "next_action": "Collect validation evidence before locking.",
    }


if __name__ == "__main__":
    unittest.main()
