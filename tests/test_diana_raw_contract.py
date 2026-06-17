import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands.diana_intake import plan_diana_raw_handoff, stage_diana_raw_analysis
from diana_omics.commands.diana_intake.verify_diana_raw import validate_rows
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

    def test_stage_plan_refreshes_rosalind_intake_packet(self):
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
            utils.write_csv(root / "manifests/diana_raw_inputs.csv", rows, DIANA_RAW_COLUMNS)

            with (
                patch.object(stage_diana_raw_analysis, "path_from_root", lambda relative: root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "DIANA_RAW_SAMPLESHEET": "manifests/diana_raw_inputs.csv",
                        "DIANA_RAW_ANALYSIS_ID": "unit",
                    },
                    clear=False,
                ),
            ):
                stage_diana_raw_analysis.main()

            command_rows = utils.parse_csv(utils.read_text(root / "results/diana_raw_analysis/unit/recompute_command_plan.csv"))
            names = [row["name"] for row in command_rows]
            self.assertIn("refresh_rosalind_intake_packet", names)
            refresh = next(row for row in command_rows if row["name"] == "refresh_rosalind_intake_packet")
            self.assertIn("build:rosalind-hrd-packet", refresh["command"])
            self.assertIn("ROSALIND_HRD_SAMPLE_SET=diana_raw_intake", refresh["command"])

    def test_handoff_plan_writes_prearrival_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(plan_diana_raw_handoff, "path_from_root", lambda relative: root / relative),
                patch.dict("os.environ", {"DIANA_RAW_ANALYSIS_ID": "unit"}, clear=False),
            ):
                plan_diana_raw_handoff.main()

            summary = utils.read_json(root / "results/diana_raw_intake/dinah_handoff_plan.json")
            self.assertEqual(summary["status"], "waiting_for_dinah_files")
            rows = utils.parse_csv(utils.read_text(root / "results/diana_raw_intake/dinah_handoff_plan.csv"))
            names = [row["name"] for row in rows]
            self.assertIn("cloud_upload_permission_gate", names)
            self.assertIn("strict_validate_diana_inputs", names)
            self.assertIn("stage_diana_raw_analysis_packet", names)
            self.assertIn("refresh_rosalind_raw_intake_packet", names)
            strict = next(row for row in rows if row["name"] == "strict_validate_diana_inputs")
            self.assertIn("DIANA_RAW_REQUIRE_DATA=1", strict["command_or_action"])
            self.assertIn("verify:diana-raw", strict["command_or_action"])
            markdown = utils.read_text(root / "results/diana_raw_intake/dinah_handoff_plan.md")
            self.assertIn("No AWS Batch or S3 upload for human data until permission is explicit.", markdown)


if __name__ == "__main__":
    unittest.main()
