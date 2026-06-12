import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_hrd_interpretation_readiness as hrd


class HrdInterpretationReadinessTest(unittest.TestCase):
    def test_validate_manifest_requires_no_call_scaffold(self):
        rows = [
            {
                "adapter_id": "sigprofiler_sbs3",
                "tool_name": "SigProfilerAssignment SBS3 adapter",
                "priority": "signature_context_adapter",
                "required_inputs": "SBS96 matrix",
                "locked_threshold_status": "locked",
                "no_call_condition": "No clinical SBS3 call without thresholds",
                "output_contract": "SBS3 activity",
                "current_status": "production_ready",
                "caveat": "not validated",
                "source_url": "https://example.test",
            }
        ]
        errors = "\n".join(hrd.validate_manifest(rows))
        self.assertIn("cannot lock thresholds", errors)
        self.assertIn("must remain scaffold_no_call", errors)

    def test_main_writes_all_no_call_adapter_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / hrd.MANIFEST_PATH
            manifest_path.parent.mkdir(parents=True)
            utils.write_csv(
                manifest_path,
                [
                    _manifest_row("sigprofiler_sbs3", "SigProfilerAssignment SBS3 adapter"),
                    _manifest_row("scarhrd", "scarHRD adapter"),
                    _manifest_row("chord", "CHORD adapter"),
                    _manifest_row("hrdetect", "HRDetect-style adapter"),
                ],
            )
            utils.write_json(
                root / hrd.PHASE3_HRD_TOOL_SUMMARY_PATH,
                {
                    "status": "passed",
                    "rows": [
                        {"tool": "SigProfilerAssignment", "interpretability_status": "input_ready_threshold_met"},
                        {"tool": "scarHRD", "interpretability_status": "not_assessable_without_allele_specific_segments"},
                        {"tool": "CHORD", "interpretability_status": "not_assessable_requires_validated_sv_caller_vcf"},
                    ],
                },
            )
            (root / hrd.CNV_LOH_READINESS_PATH).parent.mkdir(parents=True, exist_ok=True)
            utils.write_json(
                root / hrd.CNV_LOH_READINESS_PATH,
                {
                    "status": "passed",
                    "rows": [
                        {
                            "ready_for_clinical_interpretation": "no",
                            "current_bins_are_not_allele_specific_segments": "yes",
                        }
                    ],
                },
            )
            utils.write_json(
                root / hrd.SV_CALLER_READINESS_PATH,
                {
                    "status": "passed",
                    "rows": [
                        {
                            "ready_for_clinical_interpretation": "no",
                            "current_evidence_is_not_validated_sv_vcf": "yes",
                        }
                    ],
                },
            )
            with patch.object(hrd, "path_from_root", lambda relative: root / relative):
                hrd.main()
            summary = utils.read_json(root / hrd.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["summary"]["ready_for_clinical_interpretation"], "no")
        self.assertEqual(summary["summary"]["no_call_adapter_count"], 4)
        self.assertEqual({row["interpretation_status"] for row in summary["rows"]}, {"no_call"})


def _manifest_row(adapter_id: str, tool_name: str) -> dict[str, str]:
    return {
        "adapter_id": adapter_id,
        "tool_name": tool_name,
        "priority": "adapter",
        "required_inputs": "validated inputs",
        "locked_threshold_status": "not_locked",
        "no_call_condition": "No clinical call without validated inputs",
        "output_contract": "call and no-call reason",
        "current_status": "scaffold_no_call",
        "caveat": "not validated",
        "source_url": "https://example.test",
    }


if __name__ == "__main__":
    unittest.main()
