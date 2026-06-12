import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_clinicalization_readiness_rollup as verify


class ClinicalizationReadinessRollupTest(unittest.TestCase):
    def test_rollup_summarizes_blockers_without_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_all_summaries(root)
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["rollup_area_count"], 7)
        self.assertEqual(summary["summary"]["passing_dependency_count"], 7)
        self.assertGreater(summary["summary"]["active_blocker_count"], 0)
        self.assertEqual(summary["summary"]["clinical_release_allowed"], "no")
        self.assertEqual(summary["summary"]["ready_for_clinical_interpretation"], "no")

    def test_rollup_rejects_premature_unlocks(self):
        summaries = _summary_dict()
        summaries["qc_thresholds"]["summary"]["locked_threshold_count"] = 1
        rows = verify.build_rollup_rows(summaries)
        errors = "\n".join(verify.validate_rollup(summaries, rows))
        self.assertIn("locked_threshold_count=0", errors)

    def test_rollup_rejects_missing_dependency(self):
        summaries = _summary_dict()
        summaries["known_answer_assets"]["status"] = "missing"
        rows = verify.build_rollup_rows(summaries)
        errors = "\n".join(verify.validate_rollup(summaries, rows))
        self.assertIn("known_answer_asset_approval_packet_summary.json", errors)


def _write_all_summaries(root: Path) -> None:
    summaries = _summary_dict()
    for area, relative_path in verify.DEPENDENCIES.items():
        utils.write_json(root / relative_path, summaries[area])


def _summary_dict() -> dict[str, dict[str, object]]:
    return {
        "assay_boundaries": {
            "status": "passed",
            "summary": {
                "clinical_reporting_allowed": "no",
                "known_answer_ready_for_clinical_interpretation": "no",
            },
        },
        "qc_thresholds": {
            "status": "passed",
            "summary": {
                "draft_not_locked_count": 10,
                "locked_threshold_count": 0,
                "ready_for_clinical_interpretation": "no",
            },
        },
        "known_answer_assets": {
            "status": "passed",
            "summary": {
                "access_terms_review_pending_count": 9,
                "checksum_pending_count": 9,
                "execution_allowed_count": 0,
                "ready_for_clinical_interpretation": "no",
            },
        },
        "benchmark_plan": {
            "status": "passed",
            "summary": {
                "approval_required_count": 6,
                "ready_for_clinical_interpretation": "no",
            },
        },
        "packet_evidence": {
            "status": "passed",
            "summary": {
                "linked_section_count": 16,
                "unblocked_section_count": 0,
                "ready_for_clinical_interpretation": "no",
            },
        },
        "change_control": {
            "status": "passed",
            "summary": {
                "trigger_count": 12,
                "approved_trigger_count": 0,
                "clinical_release_allowed_count": 0,
                "ready_for_clinical_interpretation": "no",
            },
        },
        "signoff": {
            "status": "passed",
            "summary": {
                "pending_decision_count": 5,
                "approved_decision_count": 0,
                "ready_for_clinical_interpretation": "no",
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
