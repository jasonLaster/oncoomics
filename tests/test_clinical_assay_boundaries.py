import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_clinical_assay_boundaries as boundaries


class ClinicalAssayBoundariesTest(unittest.TestCase):
    def test_validate_manifest_rejects_clinical_ready_or_approved_rows(self):
        rows = [_boundary_row("intended_use_candidate", "assay_claim")]
        rows[0]["current_status"] = "clinical_ready"
        rows[0]["signoff_status"] = "approved"
        errors = "\n".join(boundaries.validate_manifest(rows))
        self.assertIn("cannot be marked clinically ready", errors)
        self.assertIn("cannot be approved", errors)

    def test_main_writes_not_clinical_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / boundaries.MANIFEST_PATH
            manifest_path.parent.mkdir(parents=True)
            utils.write_csv(
                manifest_path,
                [
                    _boundary_row("intended_use_candidate", "assay_claim"),
                    _boundary_row("reportable_range_wgs_hrd", "reportable_range"),
                    _boundary_row("qc_raw_fastq", "qc_gate"),
                    _boundary_row("qc_alignment_bam", "qc_gate"),
                    _boundary_row("qc_small_variant", "qc_gate"),
                    _boundary_row("qc_cnv_loh", "qc_gate"),
                    _boundary_row("qc_sv", "qc_gate"),
                    _boundary_row("qc_signature", "qc_gate"),
                    _boundary_row("report_no_call_language", "report_language"),
                    _boundary_row("report_candidate_language", "report_language"),
                    _boundary_row("prohibit_treatment_recommendation", "exclusion"),
                    _boundary_row("reviewer_signoff", "signoff"),
                ],
            )
            (root / boundaries.KNOWN_ANSWER_READINESS_PATH).parent.mkdir(parents=True, exist_ok=True)
            utils.write_json(
                root / boundaries.KNOWN_ANSWER_READINESS_PATH,
                {
                    "status": "passed",
                    "summary": {
                        "ready_for_clinical_interpretation": "no",
                        "locked_threshold_count": 0,
                    },
                },
            )
            utils.write_json(
                root / boundaries.HRD_INTERPRETATION_READINESS_PATH,
                {"status": "passed", "summary": {"ready_for_clinical_interpretation": "no"}},
            )
            with patch.object(boundaries, "path_from_root", lambda relative: root / relative):
                boundaries.main()
            summary = utils.read_json(root / boundaries.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["clinical_reporting_allowed"], "no")
        self.assertEqual(summary["summary"]["reportable_range_locked"], "no")
        self.assertEqual(summary["summary"]["qc_gate_count"], 6)
        self.assertEqual({row["clinical_reporting_allowed"] for row in summary["rows"]}, {"no"})


def _boundary_row(boundary_id: str, boundary_type: str) -> dict[str, str]:
    return {
        "boundary_id": boundary_id,
        "boundary_type": boundary_type,
        "requirement": "requirement",
        "current_policy": "policy",
        "permitted_report_language": "candidate only",
        "prohibited_language": "clinical claim",
        "evidence_dependency": "validation",
        "current_status": "not_locked",
        "signoff_status": "not_approved",
        "caveat": "not validated",
    }


if __name__ == "__main__":
    unittest.main()
