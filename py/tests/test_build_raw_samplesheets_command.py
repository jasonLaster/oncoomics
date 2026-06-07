import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands import build_raw_samplesheets


class BuildRawSamplesheetsCommandTest(unittest.TestCase):
    def test_builds_remote_and_smoke_samplesheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_dir = root / "manifests"
            manifest_dir.mkdir()
            utils.write_csv(
                manifest_dir / "raw_representative_panel.csv",
                [
                    {
                        "pair_id": "seqc2_hcc1395_wes_minimal_smoke",
                        "role": "tumor",
                        "run": "SRR1",
                        "assay": "WES",
                        "phase": "phase",
                        "sample_name": "tumor",
                        "fastq_1_url": "https://example.test/r1.fastq.gz",
                        "fastq_2_url": "https://example.test/r2.fastq.gz",
                        "library_layout": "PAIRED",
                        "library_strategy": "WXS",
                        "platform": "ILLUMINA",
                        "model": "NovaSeq",
                        "size_mb": "1",
                    },
                    {
                        "pair_id": "seqc2_hcc1395_wes_minimal_smoke",
                        "role": "normal",
                        "run": "SRR2",
                        "assay": "WES",
                        "phase": "phase",
                        "sample_name": "normal",
                        "fastq_1_url": "https://example.test/n1.fastq.gz",
                        "fastq_2_url": "https://example.test/n2.fastq.gz",
                        "library_layout": "PAIRED",
                        "library_strategy": "WXS",
                        "platform": "ILLUMINA",
                        "model": "NovaSeq",
                        "size_mb": "1",
                    },
                ],
            )

            with patch.object(build_raw_samplesheets, "path_from_root", lambda relative: root / relative):
                build_raw_samplesheets.main()

            remote = utils.parse_csv(utils.read_text(root / "manifests/raw_samplesheet.csv"))
            smoke = utils.parse_csv(utils.read_text(root / "manifests/raw_smoke_samplesheet.csv"))
            summary = utils.read_json(root / "results/raw_smoke/samplesheet_summary.json")

            self.assertEqual(len(remote), 2)
            self.assertEqual(len(smoke), 2)
            self.assertEqual(remote[0]["status"], "1")
            self.assertTrue(smoke[0]["fastq_1"].startswith("data/raw/smoke/"))
            self.assertEqual(summary["smokeRows"], 2)


if __name__ == "__main__":
    unittest.main()
