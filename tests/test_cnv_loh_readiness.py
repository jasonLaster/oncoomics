import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_cnv_loh_readiness as cnv


class CnvLohReadinessTest(unittest.TestCase):
    def test_validate_manifest_requires_primary_candidate(self):
        rows = [
            {
                "tool_id": "x",
                "tool_name": "X",
                "priority": "secondary_candidate",
                "input_contract": "tumor-normal BAMs",
                "primary_outputs": "segments",
                "scarhrd_segment_ready": "yes",
                "loh_support": "yes",
                "purity_ploidy_support": "yes",
                "container_required": "yes",
                "validation_target": "HG008",
                "current_status": "planned_not_run",
                "caveat": "not validated",
                "source_url": "https://example.test",
            }
        ]
        self.assertIn("must include one primary_candidate", "\n".join(cnv.validate_manifest(rows)))

    def test_main_writes_not_clinical_readiness_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / cnv.MANIFEST_PATH
            manifest_path.parent.mkdir(parents=True)
            utils.write_csv(
                manifest_path,
                [
                    {
                        "tool_id": "facets",
                        "tool_name": "FACETS",
                        "priority": "primary_candidate",
                        "input_contract": "tumor-normal BAMs",
                        "primary_outputs": "allele-specific segments",
                        "scarhrd_segment_ready": "yes",
                        "loh_support": "yes",
                        "purity_ploidy_support": "yes",
                        "container_required": "yes",
                        "validation_target": "HG008 and COLO829",
                        "current_status": "planned_not_run",
                        "caveat": "not validated",
                        "source_url": "https://github.com/mskcc/facets",
                    }
                ],
            )
            summary_path = root / cnv.PHASE3_CNV_SUMMARY_PATH
            utils.write_json(
                summary_path,
                {
                    "status": "passed",
                    "rows": [
                        {
                            "tool": "samtools bedcov",
                            "bin_count": 631,
                            "scarhrd_input_status": "not_assessable_without_allele_specific_segments",
                        }
                    ],
                },
            )
            with patch.object(cnv, "path_from_root", lambda relative: root / relative):
                cnv.main()
            summary = utils.read_json(root / cnv.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        row = summary["rows"][0]
        self.assertEqual(row["ready_for_clinical_interpretation"], "no")
        self.assertEqual(row["current_bins_are_not_allele_specific_segments"], "yes")


if __name__ == "__main__":
    unittest.main()
