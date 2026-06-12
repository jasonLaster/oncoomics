import tempfile
import unittest
from pathlib import Path

from diana_omics.commands.verify_diana_raw import validate_rows
from diana_omics.diana_raw import DIANA_RAW_COLUMNS, template_rows


class DianaRawContractTest(unittest.TestCase):
    def test_template_rows_include_required_tumor_normal_and_rna_context(self):
        rows = template_rows()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(set(DIANA_RAW_COLUMNS).issubset(row.keys()) for row in rows))
        self.assertTrue(any(row["role"] == "tumor" and row["assay"] == "WGS" for row in rows))
        self.assertTrue(any(row["role"] == "normal" and row["assay"] == "WGS" for row in rows))
        self.assertTrue(any(row["assay"] == "RNA" for row in rows))

    def test_validate_rows_accepts_existing_fastq_pair_and_reference_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = root / "ref.fa"
            fai = root / "ref.fa.fai"
            dictionary = root / "ref.dict"
            for path in [reference, fai, dictionary]:
                path.write_text("ok")
            rows = []
            for role in ["tumor", "normal"]:
                r1 = root / f"{role}_R1.fastq.gz"
                r2 = root / f"{role}_R2.fastq.gz"
                r1.write_text("r1")
                r2.write_text("r2")
                row = {column: "" for column in DIANA_RAW_COLUMNS}
                row.update(
                    {
                        "patient_id": "DIANA",
                        "pair_id": "DIANA-DNA-001",
                        "sample_id": f"DIANA-{role.upper()}",
                        "role": role,
                        "assay": "WGS",
                        "data_type": "FASTQ",
                        "library_layout": "PAIRED",
                        "fastq_1": str(r1),
                        "fastq_2": str(r2),
                        "reference_id": "ucsc_hg38_analysis_set_full",
                        "reference_path": str(reference),
                        "reference_fai_path": str(fai),
                        "reference_dict_path": str(dictionary),
                        "read_group_sample": f"DIANA-{role.upper()}",
                    }
                )
                rows.append(row)

            errors, warnings, summary = validate_rows(rows, require_files=True)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])
            self.assertEqual(summary["dnaRowCount"], 2)
            self.assertEqual(summary["matchedPairIds"], ["DIANA-DNA-001"])

    def test_validate_rows_rejects_unmatched_dna_pair(self):
        rows = template_rows()[:2]
        rows[0]["pair_id"] = "tumor-only"
        rows[1]["pair_id"] = "normal-only"
        errors, _warnings, _summary = validate_rows(rows, require_files=False)
        self.assertIn("Diana raw tumor and normal DNA rows must share at least one non-empty pair_id.", errors)

    def test_validate_rows_rejects_data_type_file_mismatch(self):
        rows = template_rows()[:2]
        rows[0]["data_type"] = "BAM"
        errors, _warnings, _summary = validate_rows(rows, require_files=False)
        self.assertIn("DNA row DIANA-TUMOR-DNA data_type BAM must provide bam and bai.", errors)


if __name__ == "__main__":
    unittest.main()
