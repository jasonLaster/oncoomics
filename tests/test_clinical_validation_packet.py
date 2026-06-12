import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_clinical_validation_packet as packet


class ClinicalValidationPacketTest(unittest.TestCase):
    def test_validate_manifest_requires_template_only_sections(self):
        rows = [_section_row("intended_use", "scope")]
        rows[0]["packet_status"] = "complete"
        rows[0]["signoff_status"] = "approved"
        errors = "\n".join(packet.validate_manifest(rows))
        self.assertIn("must remain template_only", errors)
        self.assertIn("cannot be approved", errors)

    def test_main_writes_template_only_packet_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / packet.MANIFEST_PATH
            manifest_path.parent.mkdir(parents=True)
            utils.write_csv(manifest_path, [_section_row(section_id, domain) for section_id, domain in _required_sections()])
            template_path = root / packet.TEMPLATE_DOC_PATH
            utils.write_text(
                template_path,
                "\n".join(
                    [
                        "template only",
                        "Clinical reporting allowed: no",
                        "Reportable range locked: no",
                        "not approved",
                        "no-call",
                        "Change control",
                    ]
                ),
            )
            (root / packet.CLINICAL_BOUNDARIES_PATH).parent.mkdir(parents=True, exist_ok=True)
            utils.write_json(
                root / packet.CLINICAL_BOUNDARIES_PATH,
                {
                    "status": "passed",
                    "summary": {
                        "clinical_reporting_allowed": "no",
                        "reportable_range_locked": "no",
                    },
                },
            )
            utils.write_json(
                root / packet.KNOWN_ANSWER_READINESS_PATH,
                {"status": "passed", "summary": {"locked_threshold_count": 0}},
            )
            with patch.object(packet, "path_from_root", lambda relative: root / relative):
                packet.main()
            summary = utils.read_json(root / packet.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["section_count"], 16)
        self.assertEqual(summary["summary"]["approved_section_count"], 0)
        self.assertEqual(summary["summary"]["packet_status"], "template_only")
        self.assertEqual({row["ready_for_clinical_packet"] for row in summary["rows"]}, {"no"})


def _required_sections() -> list[tuple[str, str]]:
    return [
        ("intended_use", "scope"),
        ("workflow_overview", "workflow"),
        ("input_acceptance", "preanalytic_qc"),
        ("accuracy_small_variants", "accuracy"),
        ("accuracy_cnv_loh", "accuracy"),
        ("accuracy_sv", "accuracy"),
        ("signature_model_accuracy", "accuracy"),
        ("precision_repeatability", "precision"),
        ("reproducibility", "reproducibility"),
        ("lod", "lod"),
        ("reportable_range", "reportable_range"),
        ("interferences_limitations", "limitations"),
        ("qc_gates", "qc"),
        ("report_template", "reporting"),
        ("change_control", "change_control"),
        ("approval_signoff", "signoff"),
    ]


def _section_row(section_id: str, domain: str) -> dict[str, str]:
    return {
        "section_id": section_id,
        "section_title": section_id.replace("_", " "),
        "validation_domain": domain,
        "required_evidence": "evidence",
        "current_evidence_status": "not_started",
        "blocking_dependency": "validation",
        "packet_status": "template_only",
        "signoff_status": "not_approved",
        "caveat": "not validated",
    }


if __name__ == "__main__":
    unittest.main()
