import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands.hrd_context import triage_rosalind_hrd_readiness as triage


class RosalindHrdReadinessTriageTest(unittest.TestCase):
    def test_triage_marks_materialized_wgs_closure_and_diana_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            utils.write_json(
                root / "results/rosalind_hrd/public/run_manifest.json",
                {
                    "generatedAt": "2026-06-17T18:00:00Z",
                    "runId": "public",
                    "sampleSets": ["hcc1395_wgs", "diana_raw_intake"],
                    "packets": [
                        {
                            "sampleSet": "hcc1395_wgs",
                            "outputDir": "results/rosalind_hrd/hcc1395_wgs/public",
                            "blockers": ["Current SV evidence summary has no discordant mapped-pair counts."],
                        },
                        {
                            "sampleSet": "diana_raw_intake",
                            "outputDir": "results/rosalind_hrd/diana_raw_intake/public",
                            "blockers": ["Actual Diana BAM/FASTQ/CRAM paths have not passed strict intake validation."],
                        },
                    ],
                },
            )
            utils.write_json(
                root / "results/rosalind_hrd/selective/run_manifest.json",
                {
                    "generatedAt": "2026-06-17T18:01:00Z",
                    "runId": "selective",
                    "sampleSets": ["hcc1395_wgs"],
                    "packets": [
                        {
                            "sampleSet": "hcc1395_wgs",
                            "outputDir": "results/rosalind_hrd/hcc1395_wgs/selective",
                            "blockers": [],
                        }
                    ],
                },
            )
            utils.write_csv(
                root / "results/rosalind_hrd/hcc1395_wgs/public/hrd_adapter_status.csv",
                [{"adapter": "chord", "state": "no_call"}],
            )

            with patch.object(triage, "path_from_root", lambda relative: root / relative):
                summary = triage.write_triage("unit", "public")

            decisions = {row["sample_set"]: row for row in summary["rows"]}
            self.assertEqual(decisions["hcc1395_wgs"]["decision"], "closed_by_materialized_packet")
            self.assertEqual(decisions["hcc1395_wgs"]["closed_by_runs"], ["selective"])
            self.assertEqual(decisions["diana_raw_intake"]["decision"], "waiting_for_dinah_files")
            markdown = utils.read_text(root / "results/rosalind_hrd/readiness_triage/unit/blocker_triage.md")
            self.assertIn("closed_by_materialized_packet", markdown)


if __name__ == "__main__":
    unittest.main()
