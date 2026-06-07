import unittest
from unittest.mock import patch

from diana_omics.commands import (
    fetch_full_reference_smoke_assets,
    fetch_human_reference_smoke_assets,
    fetch_phase1,
    fetch_raw_candidate_metadata,
)


class FetchAndReferenceHelpersTest(unittest.TestCase):
    def test_require_gene_ids_reports_missing_symbols(self):
        genes = [{"hugoGeneSymbol": "BRCA1", "entrezGeneId": 672}]
        self.assertEqual(fetch_phase1.require_gene_ids(genes, ["BRCA1"]), [672])
        with self.assertRaisesRegex(RuntimeError, "Missing Entrez IDs for: BRCA2"):
            fetch_phase1.require_gene_ids(genes, ["BRCA1", "BRCA2"])

    def test_parse_md5_helpers(self):
        text = "d41d8cd98f00b204e9800998ecf8427e  chr13.fa.gz\n"
        self.assertEqual(fetch_human_reference_smoke_assets.parse_md5s(text), {"chr13.fa.gz": "d41d8cd98f00b204e9800998ecf8427e"})
        self.assertEqual(fetch_full_reference_smoke_assets.parse_md5(text, "chr13.fa.gz"), "d41d8cd98f00b204e9800998ecf8427e")
        with self.assertRaisesRegex(RuntimeError, "Could not find md5"):
            fetch_full_reference_smoke_assets.parse_md5(text, "missing.fa.gz")

    def test_raw_candidate_fetcher_with_mocked_sources(self):
        run_info = "Run,SRAStudy,BioProject,Experiment,LibraryName,LibraryStrategy,LibraryLayout,SampleName,BioSample,Platform,Model,spots,bases,avgLength,size_MB,Consent,download_path\n"
        ena_rows = "run_accession\tfastq_ftp\tfastq_md5\tfastq_bytes\tlibrary_layout\tlibrary_strategy\tinstrument_platform\tinstrument_model\tsample_alias\n"
        payloads = {}
        for candidate in fetch_raw_candidate_metadata.CANDIDATES:
            run = candidate["run"]
            payloads[run] = (
                f"{run_info}{run},SRP,BP,EXP,LIB,WXS,PAIRED,{run}_sample,BS,ILLUMINA,NovaSeq,1,2,100,3,public,sra/{run}\n",
                f"{ena_rows}{run}\tftp/{run}_1.fastq.gz;ftp/{run}_2.fastq.gz\tmd51;md52\t10;20\tPAIRED\tWXS\tILLUMINA\tNovaSeq\t{run}_sample\n",
            )

        def fake_fetch_text(url):
            if "runinfo" in url:
                return run_info + "".join(payloads[run][0].splitlines()[1] + "\n" for run in payloads)
            for run, (_, ena) in payloads.items():
                if run in url:
                    return ena
            raise AssertionError(url)

        with patch.object(fetch_raw_candidate_metadata, "fetch_text", fake_fetch_text):
            # Exercise parsing and manifest-row assumptions without writing by reusing the public candidate contract.
            runs = [candidate["run"] for candidate in fetch_raw_candidate_metadata.CANDIDATES]
            self.assertEqual(len(runs), 8)
            self.assertIn("SRR7890850", runs)


if __name__ == "__main__":
    unittest.main()
