import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_clinical_validation_evidence_links as verify


class ClinicalValidationEvidenceLinksTest(unittest.TestCase):
    def test_evidence_links_cover_packet_sections_but_do_not_unblock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_csv(root / verify.PACKET_SECTIONS_PATH, [_packet_section("intended_use", "scope")])
            utils.write_csv(root / verify.MANIFEST_PATH, [_link_row("intended_use", "scope", "summary.json")])
            utils.write_json(root / "summary.json", {"status": "passed"})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                verify.main()
            summary = utils.read_json(root / verify.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["linked_section_count"], 1)
        self.assertEqual(summary["summary"]["unblocked_section_count"], 0)
        self.assertEqual(summary["summary"]["clinical_use_allowed_count"], 0)
        self.assertEqual(summary["summary"]["ready_for_clinical_packet"], "no")

    def test_evidence_links_reject_missing_packet_section_or_summary(self):
        row = _link_row("missing_section", "scope", "missing.json")
        errors = "\n".join(verify.validate_links([_packet_section("intended_use", "scope")], [row]))
        self.assertIn("unknown section_id", errors)
        self.assertIn("must have status passed", errors)
        self.assertIn("missing evidence link", errors)

    def test_evidence_links_reject_unblocked_or_clinical_rows(self):
        row = _link_row("intended_use", "scope", "summary.json")
        row["packet_section_unblocked"] = "yes"
        row["clinical_use_allowed"] = "yes"
        row["signoff_status"] = "approved"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(root / "summary.json", {"status": "passed"})
            with patch.object(verify, "path_from_root", lambda relative: root / relative):
                errors = "\n".join(verify.validate_links([_packet_section("intended_use", "scope")], [row]))
        self.assertIn("packet_section_unblocked=no", errors)
        self.assertIn("clinical_use_allowed=no", errors)
        self.assertIn("cannot be approved", errors)


def _packet_section(section_id: str, domain: str) -> dict[str, str]:
    return {
        "section_id": section_id,
        "section_title": "Section",
        "validation_domain": domain,
        "required_evidence": "evidence",
        "current_evidence_status": "template",
        "blocking_dependency": "blocker",
        "packet_status": "template_only",
        "signoff_status": "not_approved",
        "caveat": "not validated",
    }


def _link_row(section_id: str, domain: str, summary_path: str) -> dict[str, str]:
    return {
        "link_id": f"{section_id}_evidence",
        "section_id": section_id,
        "validation_domain": domain,
        "readiness_summary_paths": summary_path,
        "required_status": "passed",
        "blocking_signal": "not_ready",
        "packet_section_unblocked": "no",
        "clinical_use_allowed": "no",
        "signoff_status": "not_approved",
        "next_action": "Attach evidence after validation.",
    }


if __name__ == "__main__":
    unittest.main()
