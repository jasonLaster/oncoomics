import tempfile
import unittest
from pathlib import Path

from diana_omics import tcga_standard as tcga
from diana_omics import vendor_normalize as vn
from diana_omics.commands import normalize_vendor


class TcgaStandardTest(unittest.TestCase):
    def test_gene_alias_normalization(self):
        self.assertEqual(tcga.normalize_gene_symbol("mre11a"), "MRE11")
        self.assertEqual(tcga.normalize_gene_symbol("NBS1"), "NBN")
        self.assertEqual(tcga.normalize_gene_symbol("BRCA1"), "BRCA1")
        self.assertTrue(tcga.is_hrr_gene("MRE11A"))
        self.assertFalse(tcga.is_hrr_gene("TP53"))

    def test_consequence_to_variant_classification(self):
        self.assertEqual(tcga.variant_classification("stop_gained"), "Nonsense_Mutation")
        self.assertEqual(tcga.variant_classification("missense_variant"), "Missense_Mutation")
        self.assertEqual(tcga.variant_classification("splice_acceptor_variant&intron_variant"), "Splice_Site")
        self.assertEqual(tcga.variant_classification("frameshift_variant", ref="AT", alt="A"), "Frame_Shift_Del")
        self.assertEqual(tcga.variant_classification("frameshift_variant", ref="A", alt="ATT"), "Frame_Shift_Ins")
        self.assertEqual(tcga.variant_classification("Nonsense_Mutation"), "Nonsense_Mutation")

    def test_nonsynonymous_classification(self):
        self.assertTrue(tcga.is_nonsynonymous("Frame_Shift_Del"))
        self.assertFalse(tcga.is_nonsynonymous("Silent"))

    def test_gistic_from_copy_number(self):
        self.assertEqual(tcga.gistic_from_copy_number(0), -2)
        self.assertEqual(tcga.gistic_from_copy_number(1), -1)
        self.assertEqual(tcga.gistic_from_copy_number(2), 0)
        self.assertEqual(tcga.gistic_from_copy_number(3), 1)
        self.assertEqual(tcga.gistic_from_copy_number(4), 2)

    def test_gistic_from_log2(self):
        self.assertEqual(tcga.gistic_from_log2(-1.5), -2)
        self.assertEqual(tcga.gistic_from_log2(-0.5), -1)
        self.assertEqual(tcga.gistic_from_log2(0.0), 0)
        self.assertEqual(tcga.gistic_from_log2(0.5), 1)
        self.assertEqual(tcga.gistic_from_log2(1.2), 2)

    def test_build_harmonization_and_compatibility(self):
        self.assertEqual(tcga.normalize_build("hg38"), "GRCh38")
        self.assertEqual(tcga.normalize_build("b37"), "GRCh37")
        self.assertTrue(tcga.position_compatible_with_tcga("hg19"))
        self.assertFalse(tcga.position_compatible_with_tcga("GRCh38"))


class VariantFilterTest(unittest.TestCase):
    def _base_record(self, **overrides):
        record = {
            "chrom": "17",
            "gene": "BRCA1",
            "filter": "PASS",
            "t_depth": 50,
            "t_alt_count": 20,
            "t_vaf": 0.4,
            "n_vaf": 0.0,
        }
        record.update(overrides)
        return record

    def test_keeps_clean_somatic_hrr_variant(self):
        kept, reason = vn.filter_variant(self._base_record())
        self.assertTrue(kept)
        self.assertEqual(reason, "")

    def test_drops_non_pass(self):
        kept, reason = vn.filter_variant(self._base_record(filter="germline"))
        self.assertFalse(kept)
        self.assertEqual(reason, "filter_not_pass")

    def test_drops_off_target_gene(self):
        kept, reason = vn.filter_variant(self._base_record(gene="TP53"))
        self.assertFalse(kept)
        self.assertEqual(reason, "off_target_gene")

    def test_drops_low_depth_and_low_vaf_and_germline(self):
        self.assertEqual(vn.filter_variant(self._base_record(t_depth=5, t_alt_count=2))[1], "low_tumor_depth")
        self.assertEqual(vn.filter_variant(self._base_record(t_vaf=0.01))[1], "low_tumor_vaf")
        self.assertEqual(vn.filter_variant(self._base_record(n_vaf=0.3))[1], "germline_in_normal")

    def test_drops_non_standard_contig(self):
        kept, reason = vn.filter_variant(self._base_record(chrom="GL000220"))
        self.assertFalse(kept)
        self.assertEqual(reason, "non_standard_contig")


class CopyNumberTest(unittest.TestCase):
    def test_gene_cnv_to_gistic_filters_to_hrr(self):
        rows = [
            {"gene": "BRCA1", "copy_number": "1", "log2": ""},
            {"gene": "BRCA2", "copy_number": "", "log2": "-1.4"},
            {"gene": "TP53", "copy_number": "0", "log2": ""},
        ]
        result = vn.gene_cnv_to_gistic(rows, ploidy=2.0)
        self.assertEqual(result, {"BRCA1": -1, "BRCA2": -2})

    def test_fraction_genome_altered(self):
        rows = [
            {"chrom": "1", "start": "0", "end": "100", "log2": "0.05"},
            {"chrom": "1", "start": "100", "end": "200", "log2": "0.9"},
            {"chrom": "2", "start": "0", "end": "200", "log2": "-1.0"},
        ]
        fga = vn.fraction_genome_altered(rows, ploidy=2.0)
        assert fga is not None
        self.assertAlmostEqual(fga, 300 / 400, places=4)


class VcfParsingTest(unittest.TestCase):
    def test_parse_vcf_extracts_gene_consequence_and_tumor_depth(self):
        vcf = "\n".join(
            [
                "##fileformat=VCFv4.2",
                "##INFO=<ID=CSQ,Number=.,Type=String,Description=consequence>",
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTUMOR\tNORMAL",
                "17\t43000\t.\tC\tT\t.\tPASS\tCSQ=T|stop_gained|HIGH|BRCA1|672|p.Arg100Ter\tGT:AD:DP:AF\t0/1:30,20:50:0.4\t0/0:48,0:48:0.0",
            ]
        )
        records = vn.parse_vcf(vcf, tumor_column="TUMOR", normal_column="NORMAL")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["gene"], "BRCA1")
        self.assertEqual(record["consequence"], "stop_gained")
        self.assertEqual(record["t_alt_count"], 20)
        self.assertEqual(record["t_depth"], 50)
        self.assertEqual(record["n_vaf"], 0.0)
        kept, _ = vn.filter_variant(record)
        self.assertTrue(kept)


class CanonicalMutationTest(unittest.TestCase):
    def test_to_canonical_mutation_matches_tcga_shape(self):
        record = {
            "chrom": "17",
            "pos": "43000",
            "ref": "C",
            "alt": "T",
            "gene": "mre11a",
            "consequence": "stop_gained",
            "protein_change": "p.Arg100Ter",
            "t_alt_count": 20,
            "t_ref_count": 30,
        }
        mutation = vn.to_canonical_mutation(record, "DIANA-T", "DIANA", "GRCh38")
        self.assertEqual(mutation["gene"]["hugoGeneSymbol"], "MRE11")
        self.assertEqual(mutation["mutationType"], "Nonsense_Mutation")
        self.assertEqual(mutation["tumorAltCount"], 20)
        self.assertEqual(mutation["ncbiBuild"], "GRCh38")
        self.assertEqual(mutation["sampleId"], "DIANA-T")


class NormalizeSampleIntegrationTest(unittest.TestCase):
    def test_end_to_end_maf_and_gene_cnv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            maf = root / "sample.maf"
            maf.write_text(
                "\n".join(
                    [
                        "Hugo_Symbol\tChromosome\tStart_Position\tReference_Allele\tTumor_Seq_Allele2\tVariant_Classification\tHGVSp_Short\tt_alt_count\tt_depth\tFILTER",
                        "BRCA1\t17\t43000\tC\tT\tNonsense_Mutation\tp.R100*\t25\t60\tPASS",
                        "NBS1\t8\t90000\tA\tAG\tframeshift_variant\tp.X1\t18\t55\tPASS",
                        "TP53\t17\t7570000\tG\tA\tMissense_Mutation\tp.R1\t30\t60\tPASS",
                        "BRCA2\t13\t32000\tC\tT\tMissense_Mutation\tp.R2\t2\t8\tPASS",
                    ]
                )
            )
            cnv = root / "genes.tsv"
            cnv.write_text("gene\tcopy_number\nBRCA1\t1\nBRCA2\t0\n")
            row = {column: "" for column in vn.VENDOR_MANIFEST_COLUMNS}
            row.update(
                {
                    "sample_id": "DIANA-T",
                    "patient_id": "DIANA",
                    "vendor": "natera",
                    "assay": "WES",
                    "reference_build": "GRCh38",
                    "variant_file": str(maf),
                    "variant_format": "maf",
                    "cnv_gene_file": str(cnv),
                    "ploidy": "2.0",
                    "capture_megabases": "36",
                    "mutation_count": "360",
                }
            )
            result = normalize_vendor.normalize_sample(row)
            kept_genes = sorted(mutation["gene"]["hugoGeneSymbol"] for mutation in result["mutations"])
            # BRCA1 + NBS1->NBN kept; TP53 off-target; BRCA2 dropped for low depth/alt.
            self.assertEqual(kept_genes, ["BRCA1", "NBN"])
            report = result["report"]
            self.assertEqual(report["referenceBuildCanonical"], "GRCh38")
            self.assertFalse(report["positionCompatibleWithTcga"])
            self.assertEqual(report["droppedByRule"].get("off_target_gene"), 1)
            self.assertEqual(report["cnaGenesNormalized"], 2)
            # TMB normalized from vendor mutation_count / capture_megabases.
            self.assertAlmostEqual(report["tmbNonsynonymous"], 360 / 36, places=4)
            cna = {entry["gene"]["hugoGeneSymbol"]: entry["value"] for entry in result["cna"]}
            self.assertEqual(cna, {"BRCA1": -1, "BRCA2": -2})


if __name__ == "__main__":
    unittest.main()
