import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_clinical_change_control as verify


class ClinicalChangeControlTest(unittest.TestCase):
    def test_change_control_summary_keeps_release_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _all_trigger_rows("summary.json")
            utils.write_csv(root / verify.MANIFEST_PATH, rows)
            utils.write_json(root / "summary.json", {"status": "passed"})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["trigger_count"], 12)
        self.assertEqual(summary["summary"]["clinical_release_allowed_count"], 0)
        self.assertEqual(summary["summary"]["approved_trigger_count"], 0)
        self.assertEqual(summary["summary"]["change_control_ready_for_clinical_release"], "no")

    def test_change_control_rejects_release_or_approval(self):
        rows = _all_trigger_rows("summary.json")
        rows[0]["clinical_release_allowed"] = "yes"
        rows[0]["approval_status"] = "approved"
        rows[0]["owner_review_required"] = "no"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(root / "summary.json", {"status": "passed"})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                errors = "\n".join(verify.validate_manifest(rows))
        self.assertIn("clinical_release_allowed=no", errors)
        self.assertIn("cannot be approved", errors)
        self.assertIn("owner_review_required=yes", errors)

    def test_change_control_rejects_missing_dependency_or_policy(self):
        rows = _all_trigger_rows("missing.json")
        rows[0]["rollback_or_no_call_policy"] = "Proceed after local testing"
        errors = "\n".join(verify.validate_manifest(rows))
        self.assertIn("no-release/no-call policy", errors)
        self.assertIn("must have status passed", errors)


def _all_trigger_rows(dependency: str) -> list[dict[str, str]]:
    return [
        _row("workflow_version_change", "workflow", dependency),
        _row("reference_asset_change", "reference", dependency),
        _row("input_policy_change", "preanalytic_qc", dependency),
        _row("small_variant_caller_change", "accuracy", dependency),
        _row("cnv_loh_tool_change", "accuracy", dependency),
        _row("sv_caller_change", "accuracy", dependency),
        _row("hrd_adapter_change", "model", dependency),
        _row("threshold_lock_change", "qc_thresholds", dependency),
        _row("report_language_change", "reporting", dependency),
        _row("benchmark_asset_change", "known_answer", dependency),
        _row("validation_packet_change", "validation_packet", dependency),
        _row("clinical_signoff_change", "signoff", dependency),
    ]


def _row(trigger_id: str, domain: str, dependency: str) -> dict[str, str]:
    return {
        "trigger_id": trigger_id,
        "trigger_domain": domain,
        "change_type": "change",
        "watched_artifact": "artifact",
        "revalidation_scope": "scope",
        "impact_assessment_required": "yes",
        "owner_review_required": "yes",
        "clinical_release_allowed": "no",
        "approval_status": "not_approved",
        "rollback_or_no_call_policy": "No clinical release until reviewed.",
        "evidence_dependency": dependency,
        "next_action": "Review after validation.",
    }


if __name__ == "__main__":
    unittest.main()
