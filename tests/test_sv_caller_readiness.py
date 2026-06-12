import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import verify_sv_caller_readiness as sv


class SvCallerReadinessTest(unittest.TestCase):
    def test_validate_manifest_requires_primary_candidate(self):
        rows = [
            {
                "tool_id": "x",
                "tool_name": "X",
                "priority": "secondary_candidate",
                "input_contract": "tumor-normal BAMs",
                "primary_outputs": "SV VCF",
                "chord_ready": "yes",
                "bedpe_support": "convertible",
                "vcf_support": "yes",
                "somatic_filter_support": "yes",
                "container_required": "yes",
                "validation_target": "HG008",
                "current_status": "planned_not_run",
                "caveat": "not validated",
                "source_url": "https://example.test",
            }
        ]
        self.assertIn("must include one primary_candidate", "\n".join(sv.validate_manifest(rows)))

    def test_validate_manifest_requires_vcf_support(self):
        rows = [
            {
                "tool_id": "x",
                "tool_name": "X",
                "priority": "primary_candidate",
                "input_contract": "tumor-normal BAMs",
                "primary_outputs": "SV evidence",
                "chord_ready": "yes",
                "bedpe_support": "convertible",
                "vcf_support": "no",
                "somatic_filter_support": "yes",
                "container_required": "yes",
                "validation_target": "HG008",
                "current_status": "planned_not_run",
                "caveat": "not validated",
                "source_url": "https://example.test",
            }
        ]
        self.assertIn("must support VCF output", "\n".join(sv.validate_manifest(rows)))

    def test_chord_status_accepts_low_depth_full_depth_sv_caller_vcf_no_call(self):
        self.assertTrue(
            sv.chord_status_requires_validated_sv_vcf("not_assessable_low_depth_smoke_requires_full_depth_sv_caller_vcf")
        )
        self.assertFalse(sv.chord_status_requires_validated_sv_vcf("ready_for_chord"))

    def test_main_writes_not_clinical_readiness_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / sv.MANIFEST_PATH
            manifest_path.parent.mkdir(parents=True)
            utils.write_csv(
                manifest_path,
                [
                    {
                        "tool_id": "manta",
                        "tool_name": "Manta",
                        "priority": "primary_candidate",
                        "input_contract": "tumor-normal BAMs",
                        "primary_outputs": "somatic SV VCF",
                        "chord_ready": "yes",
                        "bedpe_support": "convertible",
                        "vcf_support": "yes",
                        "somatic_filter_support": "yes",
                        "container_required": "yes",
                        "validation_target": "HG008 and COLO829",
                        "current_status": "planned_not_run",
                        "caveat": "not validated",
                        "source_url": "https://github.com/Illumina/manta",
                    }
                ],
            )
            summary_path = root / sv.PHASE3_SV_SUMMARY_PATH
            summary_path.parent.mkdir(parents=True)
            utils.write_json(
                summary_path,
                {
                    "status": "passed",
                    "rows": [
                        {
                            "status": "passed",
                            "tool": "samtools view flag/evidence counters",
                            "sample": "HCC1395",
                            "supplementary_alignments": 10,
                            "discordant_mapped_pairs": 20,
                            "interchromosomal_pairs": 5,
                            "large_insert_pairs": 3,
                            "sv_candidate_rows_written": 2,
                            "chord_input_status": "not_assessable_requires_validated_sv_caller_vcf",
                        }
                    ],
                },
            )
            with patch.object(sv, "path_from_root", lambda relative: root / relative):
                sv.main()
            summary = utils.read_json(root / sv.SUMMARY_JSON_PATH)
        self.assertEqual(summary["status"], "passed")
        row = summary["rows"][0]
        self.assertEqual(row["ready_for_clinical_interpretation"], "no")
        self.assertEqual(row["current_evidence_is_not_validated_sv_vcf"], "yes")
        self.assertEqual(row["phase3_discordant_mapped_pairs"], 20)


if __name__ == "__main__":
    unittest.main()
