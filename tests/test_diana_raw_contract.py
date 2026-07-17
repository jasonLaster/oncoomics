import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diana_omics import utils
from diana_omics.commands.diana_intake import (
    build_diana_raw_samplesheet_from_delivery,
    plan_diana_raw_handoff,
    stage_diana_raw_analysis,
)
from diana_omics.commands.diana_intake.verify_diana_raw import validate_rows
from diana_omics.diana_raw import DIANA_RAW_COLUMNS, diana_raw_contract, template_rows


class DianaRawContractTest(unittest.TestCase):
    def test_template_rows_include_required_tumor_normal_and_rna_context(self):
        rows = template_rows()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(set(DIANA_RAW_COLUMNS).issubset(row.keys()) for row in rows))
        self.assertTrue(any(row["role"] == "tumor" and row["assay"] == "WGS" for row in rows))
        self.assertTrue(any(row["role"] == "normal" and row["assay"] == "WGS" for row in rows))
        self.assertTrue(any(row["assay"] == "RNA" for row in rows))

    def test_contract_names_s3_inbox_prefix(self):
        contract = diana_raw_contract()
        self.assertEqual(
            contract["s3InboxUri"],
            "s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox",
        )
        self.assertNotIn("/cache/phase3_wgs", contract["s3InboxUri"])
        self.assertIn("authenticated writes", contract["uploadContract"])
        self.assertIn("anonymous listing and downloads", contract["uploadContract"])
        self.assertIn("AES256", contract["uploadContract"])

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

    def test_maps_uploaded_delivery_manifest_to_strict_samplesheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.csv"
            checksums = root / "checksums.sha256"
            output = root / "diana_raw_inputs.csv"
            rows = [
                _delivery_row("wgs", "DRF-normal", "matched_normal", "Personalis WGS", "FASTQ", "Normal/sample_L001_R1_001.fastq.gz", "a" * 64),
                _delivery_row("wgs", "DRF-normal", "matched_normal", "Personalis WGS", "FASTQ", "Normal/sample_L001_R2_001.fastq.gz", "b" * 64),
                _delivery_row("wgs", "DRF-tumor", "tumor", "Personalis WGS", "FASTQ", "Tumor/sample_L005_R1_001.fastq.gz", "c" * 64),
                _delivery_row("wgs", "DRF-tumor", "tumor", "Personalis WGS", "FASTQ", "Tumor/sample_L005_R2_001.fastq.gz", "d" * 64),
                _delivery_row(
                    "immunoid",
                    "DNA_E019_S01",
                    "tumor",
                    "Personalis ImmunoID NeXT",
                    "BAM",
                    "DNA/DNA_E019_S01_tumor_dna_aligned_recal.sorted.bam",
                    "e" * 64,
                    reference_build="hs37d5",
                ),
                _delivery_row(
                    "immunoid",
                    "DNA_E019_S01",
                    "tumor",
                    "Personalis ImmunoID NeXT",
                    "BAI",
                    "DNA/DNA_E019_S01_tumor_dna_aligned_recal.sorted.bai",
                    "f" * 64,
                    reference_build="hs37d5",
                ),
                _delivery_row(
                    "immunoid",
                    "RNA_E019_S01",
                    "tumor",
                    "Personalis ImmunoID NeXT",
                    "FASTQ",
                    "RNA/RNA_E019_S01_tumor_rna_reads1.fastq.gz",
                    "1" * 64,
                ),
                _delivery_row(
                    "immunoid",
                    "RNA_E019_S01",
                    "tumor",
                    "Personalis ImmunoID NeXT",
                    "FASTQ",
                    "RNA/RNA_E019_S01_tumor_rna_reads2.fastq.gz",
                    "2" * 64,
                ),
            ]
            utils.write_csv(manifest, rows)
            checksums.write_text("".join(f"{row['sha256']}  {row['relative_path']}\n" for row in rows), encoding="utf-8")

            with (
                patch.object(build_diana_raw_samplesheet_from_delivery, "path_from_root", lambda relative: root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "DIANA_RAW_DELIVERY_MANIFEST": manifest.name,
                        "DIANA_RAW_DELIVERY_CHECKSUMS": checksums.name,
                        "DIANA_RAW_SAMPLESHEET": output.name,
                        "DIANA_RAW_DELIVERY_ROOT": "staged",
                    },
                    clear=False,
                ),
            ):
                build_diana_raw_samplesheet_from_delivery.main()

            mapped = utils.parse_csv(utils.read_text(output))
            self.assertEqual(len(mapped), 3)
            self.assertEqual({row["data_type"] for row in mapped}, {"FASTQ", "RNA_FASTQ"})
            self.assertTrue(all(row["sample_id"] for row in mapped))
            self.assertTrue(all(path.startswith("staged/") for row in mapped for path in [row["fastq_1"], row["fastq_2"], row["rna_fastq_1"], row["rna_fastq_2"]] if path))

            errors, warnings, summary = validate_rows(mapped, require_files=False)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])
            self.assertEqual(summary["matchedPairIds"], ["DIANA_WGS_wgs"])

            mapping = utils.read_json(root / "results/diana_raw_intake/delivery_manifest_mapping.json")
            self.assertEqual(mapping["summary"]["manifestRows"], 8)
            self.assertEqual(mapping["summary"]["mappedRows"], 3)
            self.assertEqual(mapping["summary"]["skippedRows"], 1)
            self.assertEqual(mapping["skipped"][0]["reason"], "bam_reference_not_selected_analysis_reference")

    def test_delivery_manifest_mapping_rejects_checksum_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.csv"
            checksums = root / "checksums.sha256"
            row = _delivery_row("wgs", "DRF-normal", "matched_normal", "Personalis WGS", "FASTQ", "Normal/sample_L001_R1_001.fastq.gz", "a" * 64)
            utils.write_csv(manifest, [row])
            checksums.write_text(f"{'b' * 64}  {row['relative_path']}\n", encoding="utf-8")

            with (
                patch.object(build_diana_raw_samplesheet_from_delivery, "path_from_root", lambda relative: root / relative),
                patch.dict(
                    "os.environ",
                    {
                        "DIANA_RAW_DELIVERY_MANIFEST": manifest.name,
                        "DIANA_RAW_DELIVERY_CHECKSUMS": checksums.name,
                    },
                    clear=False,
                ),
                self.assertRaises(SystemExit),
            ):
                build_diana_raw_samplesheet_from_delivery.main()

            mapping = utils.read_json(root / "results/diana_raw_intake/delivery_manifest_mapping.json")
            self.assertEqual(mapping["status"], "failed")
            self.assertIn("Delivery manifest SHA-256 does not match", mapping["errors"][0])

    def test_delivery_manifest_mapping_records_missing_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                patch.object(build_diana_raw_samplesheet_from_delivery, "path_from_root", lambda relative: root / relative),
                patch.dict("os.environ", {}, clear=True),
                self.assertRaises(SystemExit),
            ):
                build_diana_raw_samplesheet_from_delivery.main()

            mapping = utils.read_json(root / "results/diana_raw_intake/delivery_manifest_mapping.json")
            self.assertEqual(mapping["status"], "failed")
            self.assertIn("Missing delivery manifest", mapping["errors"][0])
            self.assertIn("Missing delivery checksums", mapping["errors"][1])

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


def _delivery_row(
    dataset: str,
    sample_id: str,
    role: str,
    assay: str,
    data_type: str,
    relative_path: str,
    sha256: str,
    *,
    reference_build: str = "not_applicable",
) -> dict[str, str]:
    return {
        "dataset": dataset,
        "sample_id": sample_id,
        "role": role,
        "assay": assay,
        "data_type": data_type,
        "relative_path": relative_path,
        "size_bytes": "42",
        "sha256": sha256,
        "reference_build": reference_build,
        "source_vendor": "Personalis",
        "notes": "synthetic",
    }


if __name__ == "__main__":
    unittest.main()
