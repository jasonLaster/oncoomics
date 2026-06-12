import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_clinical_signoff_workflow as verify


class ClinicalSignoffWorkflowTest(unittest.TestCase):
    def test_signoff_workflow_keeps_release_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = _all_signoff_rows("summary.json")
            utils.write_csv(root / verify.MANIFEST_PATH, rows)
            utils.write_json(root / "summary.json", {"status": "passed"})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["signoff_step_count"], 5)
        self.assertEqual(summary["summary"]["pending_decision_count"], 5)
        self.assertEqual(summary["summary"]["approved_decision_count"], 0)
        self.assertEqual(summary["summary"]["release_allowed_count"], 0)
        self.assertEqual(summary["summary"]["ready_for_clinical_release"], "no")

    def test_signoff_workflow_rejects_approval_or_release(self):
        rows = _all_signoff_rows("summary.json")
        rows[0]["decision_status"] = "approved"
        rows[0]["release_allowed"] = "yes"
        rows[0]["clinical_use_allowed"] = "yes"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(root / "summary.json", {"status": "passed"})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                errors = "\n".join(verify.validate_manifest(rows))
        self.assertIn("cannot be approved", errors)
        self.assertIn("release_allowed=no", errors)
        self.assertIn("clinical_use_allowed=no", errors)

    def test_signoff_workflow_requires_passed_evidence_and_all_roles(self):
        rows = [_row("assay_owner_scope_review", "assay_owner", "missing.json")]
        errors = "\n".join(verify.validate_manifest(rows))
        self.assertIn("must have status passed", errors)
        self.assertIn("missing required review_role laboratory_director", errors)


def _all_signoff_rows(evidence: str) -> list[dict[str, str]]:
    return [
        _row("assay_owner_scope_review", "assay_owner", evidence),
        _row("bioinformatics_owner_review", "bioinformatics_owner", evidence),
        _row("clinical_scientist_accuracy_review", "clinical_scientist", evidence),
        _row("quality_reviewer_review", "quality_reviewer", evidence),
        _row("laboratory_director_release", "laboratory_director", evidence),
    ]


def _row(signoff_id: str, role: str, evidence: str) -> dict[str, str]:
    return {
        "signoff_id": signoff_id,
        "review_role": role,
        "review_domain": "domain",
        "required_evidence_paths": evidence,
        "decision_status": "pending",
        "release_allowed": "no",
        "clinical_use_allowed": "no",
        "signoff_required": "yes",
        "blocking_condition": "not_ready",
        "next_action": "Assign reviewer after evidence is complete.",
    }


if __name__ == "__main__":
    unittest.main()
