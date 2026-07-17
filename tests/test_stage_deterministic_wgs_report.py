#!/usr/bin/env python3
"""De-identified end-to-end contract tests for stage_deterministic_wgs_report.py.

The fixture mirrors the dictionaries and CSVs emitted by the build_* and
stage_evidence functions in /tmp/diana_hrd_wgs_worker.py. It contains no live
artifact paths, sample identifiers, cloud calls, or patient data.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

GENERATOR = SCRIPT_DIR / "stage_deterministic_wgs_report.py"
SPEC = importlib.util.spec_from_file_location(
    "stage_deterministic_wgs_report", GENERATOR
)
assert SPEC and SPEC.loader
REPORT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT_MODULE)

PUBLISH_SCRIPT = SCRIPT_DIR / "publish_private_report.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_private_report", PUBLISH_SCRIPT
)
assert PUBLISH_SPEC and PUBLISH_SPEC.loader
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)

KMS_ARN = "arn:aws:kms:us-east-1:000000000000:key/00000000-0000-0000-0000-000000000000"
RUN_ID = "synthetic-hrd-run"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
    delimiter: str = ",",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = fieldnames or list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=delimiter, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_indexed_vcf(path: Path, records: list[str]) -> None:
    plain = path.with_suffix("")
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text(
        "\n".join(
            [
                "##fileformat=VCFv4.2",
                "##FILTER=<ID=LowQual,Description=\"Synthetic non-PASS record\">",
                "##contig=<ID=chr1,length=1000000>",
                "##contig=<ID=chr13,length=50000000>",
                "##contig=<ID=chr17,length=50000000>",
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                *records,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(["bcftools", "view", "-Oz", "-o", str(path), str(plain)], check=True)
    subprocess.run(["bcftools", "index", "-t", "-f", str(path)], check=True)
    plain.unlink()


def readiness_rows(pass_records: int, bin_count: int, usable_snvs: int) -> list[dict[str, str]]:
    return [
        {"evidence_surface": "source_sha256", "status": "ready", "detail": "30/30 synthetic payload objects passed SHA-256."},
        {"evidence_surface": "wgs_alignment", "status": "ready", "detail": "Eight synthetic lanes were structurally validated."},
        {"evidence_surface": "matched_normal_somatic_variants", "status": "ready", "detail": f"Mutect2 PASS records: {pass_records}."},
        {"evidence_surface": "coverage_cnv", "status": "partial_evidence", "detail": f"{bin_count} normalized coverage bins; not allele-specific."},
        {"evidence_surface": "sbs96", "status": "partial_evidence", "detail": f"{usable_snvs} PASS SNV in SBS96; no SBS3 assignment."},
        {"evidence_surface": "sv", "status": "partial_evidence", "detail": "BAM-derived counts only; no validated SV callset."},
        {"evidence_surface": "scarHRD", "status": "no_call", "detail": "No allele-specific segments or purity/ploidy solution."},
        {"evidence_surface": "CHORD", "status": "no_call", "detail": "No validated production SV callset."},
        {"evidence_surface": "HRDetect", "status": "no_call", "detail": "Integrated model is not validated."},
        {"evidence_surface": "overall_hrd", "status": "no_call", "detail": "No defensible scalar HRD classification."},
    ]


class SyntheticFixture:
    def __init__(self, root: Path, *, inconsistent_variant_count: bool = False):
        self.root = root
        self.artifacts = root / "artifacts"
        self.early = root / "early"
        self.aux = root / "auxiliary"
        self.output = root / "report-output"
        self.inconsistent_variant_count = inconsistent_variant_count
        self._build()

    def _build(self) -> None:
        alignment_rows = [
            {
                "status": "passed",
                "role": "tumor",
                "bam_bytes": 1000,
                "total_reads": 100,
                "mapped_reads": 90,
                "duplicate_reads": 10,
                "reference": "ucsc_hg38_analysis_set_full",
            },
            {
                "status": "passed",
                "role": "normal",
                "bam_bytes": 1200,
                "total_reads": 120,
                "mapped_reads": 110,
                "duplicate_reads": 12,
                "reference": "ucsc_hg38_analysis_set_full",
            },
        ]
        alignment = {"status": "passed", "rows": alignment_rows}
        write_json(self.artifacts / "alignment/bam_validation_summary.json", alignment)
        write_csv(self.artifacts / "alignment/bam_validation_summary.csv", alignment_rows)
        for row in alignment_rows:
            flagstat = (
                f"{row['total_reads']} + 0 in total (QC-passed reads + QC-failed reads)\n"
                f"{row['duplicate_reads']} + 0 duplicates\n"
                f"{row['mapped_reads']} + 0 mapped (90.00% : N/A)\n"
            )
            (self.artifacts / f"alignment/{row['role']}.flagstat.txt").write_text(flagstat, encoding="utf-8")

        filtered_vcf = self.artifacts / "variants/diana.wgs.mutect2.filtered.vcf.gz"
        brca_vcf = self.artifacts / "variants/brca1_brca2.pass.vcf.gz"
        pass_snv = "chr17\t43050000\t.\tC\tT\t60\tPASS\t."
        write_indexed_vcf(
            filtered_vcf,
            ["chr1\t100\t.\tA\tAT\t10\tLowQual\t.", pass_snv],
        )
        write_indexed_vcf(brca_vcf, [pass_snv])
        brca_rows = [
            {
                "contig": "chr17",
                "position": "43050000",
                "ref": "C",
                "alt": "T",
                "filter": "PASS",
                "genotype": "",
                "allele_depth": "",
                "allele_fraction": "",
                "region_label": "BRCA1",
                "annotation_status": "region_only_requires_variant_annotation_review",
            }
        ]
        write_csv(
            self.artifacts / "variants/brca1_brca2_pass_variants.csv",
            brca_rows,
            [
                "contig", "position", "ref", "alt", "filter", "genotype",
                "allele_depth", "allele_fraction", "region_label", "annotation_status",
            ],
        )
        reported_pass = 2 if self.inconsistent_variant_count else 1
        variants = {
            "status": "passed",
            "caller": "GATK Mutect2 synthetic matched tumor-normal fixture",
            "total_filtered_records": 2,
            "pass_records": reported_pass,
            "pass_snvs": 1,
            "pass_indels": 0,
            "brca1_brca2_pass_region_records": 1,
            "panel_of_normals": "synthetic-pon.vcf.gz",
            "germline_resource": "synthetic-germline.vcf.gz",
            "contamination_resource": "synthetic-common.vcf",
            "contamination_table": "contamination.table",
            "orientation_bias_model": "read-orientation-model.tar.gz",
            "filtered_vcf": filtered_vcf.name,
            "caveat": "Synthetic research-use fixture.",
        }
        write_json(self.artifacts / "variants/mutect2_summary.json", variants)
        write_csv(
            self.artifacts / "variants/contamination.table",
            [{"sample": "subject01_tumor", "contamination": "0.01", "error": "0.001"}],
            delimiter="\t",
        )
        for name in (
            "tumor-segmentation.table",
            "tumor.pileups.table",
            "normal.pileups.table",
            "read-orientation-model.tar.gz",
        ):
            (self.artifacts / f"variants/{name}").write_bytes(b"synthetic\n")

        cnv_rows = [
            {"contig": "chr1", "start": 0, "end": 100, "length": 100, "tumor_depth_sum": 10, "normal_depth_sum": 10, "tumor_mean_depth": 0.1, "normal_mean_depth": 0.1, "raw_log2_tumor_normal": 0, "normalized_log2_tumor_normal": 0.7, "coverage_class": "relative_gain"},
            {"contig": "chr1", "start": 100, "end": 200, "length": 100, "tumor_depth_sum": 5, "normal_depth_sum": 10, "tumor_mean_depth": 0.05, "normal_mean_depth": 0.1, "raw_log2_tumor_normal": -1, "normalized_log2_tumor_normal": -0.7, "coverage_class": "relative_loss"},
            {"contig": "chr1", "start": 200, "end": 300, "length": 100, "tumor_depth_sum": 10, "normal_depth_sum": 10, "tumor_mean_depth": 0.1, "normal_mean_depth": 0.1, "raw_log2_tumor_normal": 0, "normalized_log2_tumor_normal": 0, "coverage_class": "neutral_or_low_signal"},
        ]
        cnv = {
            "status": "partial_evidence",
            "tool": "samtools bedcov normalized tumor-normal synthetic bins",
            "bin_count": len(cnv_rows),
            "median_raw_log2_tumor_normal": 0.0,
            "relative_gain_bins": 1,
            "relative_loss_bins": 1,
            "scarhrd_input_status": "no_call_without_allele_specific_segments_purity_ploidy",
            "caveat": "Synthetic coverage proxy.",
        }
        write_csv(self.artifacts / "cnv/coverage_cnv_bins.csv", cnv_rows)
        write_json(self.artifacts / "cnv/coverage_cnv_summary.json", cnv)

        mutation_types = ("C>A", "C>G", "C>T", "T>A", "T>C", "T>G")
        bases = "ACGT"
        sbs_rows: list[dict[str, Any]] = []
        for mutation in mutation_types:
            for left in bases:
                for right in bases:
                    sbs_rows.append(
                        {
                            "sample": "subject01_tumor",
                            "mutation_type": mutation,
                            "trinucleotide": f"{left}[{mutation}]{right}",
                            "count": 1 if not sbs_rows else 0,
                        }
                    )
        signatures = {
            "status": "partial_evidence",
            "source_vcf": filtered_vcf.name,
            "source_record_policy": "PASS SNVs",
            "usable_snv_records": 1,
            "skipped_snv_records": 0,
            "sbs96_rows": 96,
            "sigprofiler_assignment_status": "not_assessable_low_mutation_count",
            "sbs3_status": "no_call_signature_assignment_and_threshold_policy_not_locked",
            "caveat": "Synthetic SBS96 fixture.",
        }
        write_csv(self.artifacts / "signatures/wgs_sbs96_matrix.csv", sbs_rows)
        write_json(self.artifacts / "signatures/signature_assignment_summary.json", signatures)

        sv_rows = [
            {"status": "partial_evidence", "role": "tumor", "total_alignments": 100, "supplementary_alignments": 2, "discordant_mapped_pairs": 3, "interchromosomal_pairs": 1, "large_insert_pairs": 1, "chord_input_status": "no_call_requires_validated_production_sv_caller_vcf", "caveat": "Synthetic counts."},
            {"status": "partial_evidence", "role": "normal", "total_alignments": 120, "supplementary_alignments": 1, "discordant_mapped_pairs": 2, "interchromosomal_pairs": 1, "large_insert_pairs": 0, "chord_input_status": "no_call_requires_validated_production_sv_caller_vcf", "caveat": "Synthetic counts."},
        ]
        sv = {"status": "partial_evidence", "rows": sv_rows, "production_sv_callset_status": "no_call"}
        write_csv(self.artifacts / "sv/sv_evidence_summary.csv", sv_rows)
        write_json(self.artifacts / "sv/sv_evidence_summary.json", sv)
        write_json(
            self.artifacts / "tool_versions.json",
            {"bwa": "synthetic-bwa", "samtools": "synthetic-samtools", "bcftools": "synthetic-bcftools", "gatk": "synthetic-gatk"},
        )

        readiness = readiness_rows(reported_pass, len(cnv_rows), 1)
        write_csv(self.artifacts / "hrd_readiness.csv", readiness)
        summary = {
            "status": "no_call",
            "evidence_status": "partial_evidence",
            "run_id": RUN_ID,
            "generated_at": "2026-07-17T00:00:00+00:00",
            "elapsed_seconds": 1.0,
            "input": {
                "dataset": "WGS data",
                "pair": "tumor matched normal",
                "lanes": 8,
                "reference": "UCSC hg38 analysis set full",
                "source_integrity": "passed",
            },
            "alignment": alignment,
            "variants": variants,
            "coverage_cnv": cnv,
            "signatures": signatures,
            "sv": sv,
            "hrd_readiness": readiness,
            "boundary": "Synthetic partial evidence; overall HRD remains no_call.",
        }
        write_json(self.artifacts / "diana_hrd_summary.json", summary)

        write_json(
            self.aux / "preflight.json",
            {"status": "passed", "run_id": RUN_ID, "wgs_lanes": 8, "wgs_bytes": 16, "reference": "UCSC hg38 analysis set full"},
        )
        write_json(
            self.aux / "gather.json",
            {
                "status": "passed",
                "run_id": RUN_ID,
                "reference": "ucsc_hg38_analysis_set_full",
                "samples": [
                    {"status": "passed", "role": "tumor", "lane_count": 4, "output_bam": "tumor.markdup.bam", "output_bam_bytes": 1000},
                    {"status": "passed", "role": "normal", "lane_count": 4, "output_bam": "normal.markdup.bam", "output_bam_bytes": 1200},
                ],
            },
        )
        audit_objects = [
            {
                "status": "passed",
                "dataset": "wgs" if index < 16 else "immunoid",
                "data_type": "FASTQ",
                "actual_size_bytes": 1,
                "size_matches": True,
                "sha256_matches": True,
                "sample_id": "subject01",
                "assay": "",
            }
            for index in range(30)
        ]
        write_json(
            self.aux / "sha-audit.json",
            {
                "status": "passed",
                "algorithm": "sha256",
                "object_count": 30,
                "passed_count": 30,
                "failed_count": 0,
                "bytes_streamed": 30,
                "objects": audit_objects,
            },
        )
        launch_uri = "s3://synthetic-work/run/worker.py"
        executed_uri = (
            "s3://diana-omics-private-results-test/"
            "runs/subject01/synthetic-run/deterministic/provenance/worker.py"
        )
        worker_receipt_path = self.aux / "executed-worker-freeze.json"
        write_json(
            worker_receipt_path,
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "source": {
                    "task_arn": "arn:aws:ecs:us-east-1:0:task/synthetic/task",
                    "container_runtime_id": "synthetic-runtime",
                    "bytes": 123,
                    "sha256": "b" * 64,
                },
                "freeze": {
                    "bucket": "diana-omics-private-results-test",
                    "key": (
                        "runs/subject01/synthetic-run/deterministic/"
                        "provenance/worker.py"
                    ),
                    "version_id": "executed-worker-version",
                    "bytes": 123,
                    "checksum_type": "FULL_OBJECT",
                    "checksum_sha256_hex": "b" * 64,
                    "kms_key_id": KMS_ARN,
                },
                "checks": {"synthetic_container_capture": True},
            },
        )
        worker_receipt_upload_path = self.aux / "executed-worker-freeze-upload.json"
        write_json(
            worker_receipt_upload_path,
            {
                "schema_version": 1,
                "status": "passed",
                "local_receipt_sha256": sha256(worker_receipt_path),
                "object": {
                    "version_id": "executed-worker-receipt-version",
                    "checksum_sha256_hex": sha256(worker_receipt_path),
                    "kms_key_id": KMS_ARN,
                },
                "checks": {"synthetic_receipt_upload": True},
            },
        )
        write_json(
            self.aux / "execution.json",
            {
                "schema_version": 1,
                "run_id": RUN_ID,
                "batch": {
                    "status": "SUCCEEDED",
                    "started_at_epoch_ms": 1,
                    "stopped_at_epoch_ms": 2,
                    "attempt_count": 1,
                    "attempts": [
                        {
                            "started_at_epoch_ms": 1,
                            "stopped_at_epoch_ms": 2,
                            "status_reason": "",
                            "container_instance_arn": "arn:aws:ecs:us-east-1:0:container-instance/synthetic",
                            "task_arn": "arn:aws:ecs:us-east-1:0:task/synthetic/task",
                            "log_stream": "synthetic-stream",
                            "exit_code": 0,
                            "reason": "",
                        }
                    ],
                    "retry_strategy": {"attempts": 1, "evaluateOnExit": []},
                    "timeout": {"attemptDurationSeconds": 129600},
                    "job_id": "synthetic-job",
                    "job_queue_arn": "arn:aws:batch:us-east-1:000000000000:job-queue/synthetic",
                    "job_definition_arn": "arn:aws:batch:us-east-1:000000000000:job-definition/synthetic:1",
                    "log_group": "/synthetic/logs",
                    "log_stream": "synthetic-stream",
                    "command": [
                        "aws",
                        "s3",
                        "cp",
                        launch_uri,
                        "worker.py",
                        "python3",
                        "worker.py",
                        "evidence",
                        "--run-id",
                        RUN_ID,
                    ],
                },
                "container": {
                    "image_reference": "synthetic/image:fixture",
                    "image_digest": "sha256:" + "a" * 64,
                    "task_arn": "arn:aws:ecs:us-east-1:0:task/synthetic/task",
                    "runtime_ids": ["synthetic-runtime"],
                },
                "queue": {"name": "synthetic", "status": "VALID"},
                "job_definition": {"name": "synthetic", "revision": 1},
                "worker": {
                    "launch_uri": launch_uri,
                    "executed_uri": executed_uri,
                    "executed_version_id": "executed-worker-version",
                    "freeze_receipt_path": str(worker_receipt_path),
                    "freeze_receipt_sha256": sha256(worker_receipt_path),
                    "freeze_receipt_version_id": "executed-worker-receipt-version",
                    "freeze_receipt_upload_path": str(worker_receipt_upload_path),
                    "freeze_receipt_upload_sha256": sha256(
                        worker_receipt_upload_path
                    ),
                    "bytes": 123,
                    "sha256": "b" * 64,
                    "etag": '"synthetic-worker"',
                    "last_modified": "2026-07-16T23:00:00+00:00",
                    "checksums": {"ChecksumSHA256": "synthetic-checksum"},
                    "checksum_type": "FULL_OBJECT",
                    "server_side_encryption": "aws:kms",
                    "kms_key_id": KMS_ARN,
                    "checks": {"synthetic_exact_container_capture": True},
                },
            },
        )
        stage_destination_prefix = (
            f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/"
            "deterministic/provenance/wgs-stage/"
        )
        stage_rows = []
        for index, name in enumerate(("preflight.json", "gather.json"), 1):
            local = self.aux / name
            digest = sha256(local)
            checksum = base64.b64encode(bytes.fromhex(digest)).decode("ascii")
            stage_rows.append(
                {
                    "name": name,
                    "source": {
                        "bucket": "diana-omics-work-test",
                        "key": (
                            f"runs/diana-hrd/{RUN_ID}/private-results/{name}"
                        ),
                        "version_id": "null",
                        "bytes": local.stat().st_size,
                        "etag": "synthetic-stage-source",
                        "checksums": {"ChecksumSHA256": checksum},
                        "checksum_type": "FULL_OBJECT",
                        "sha256": digest,
                        "server_side_encryption": "aws:kms",
                        "kms_key_id": KMS_ARN,
                    },
                    "destination": {
                        "bucket": "diana-omics-private-results-test",
                        "key": (
                            f"runs/subject01/{RUN_ID}/deterministic/"
                            f"provenance/wgs-stage/{name}"
                        ),
                        "version_id": f"stage-version-{index}",
                        "bytes": local.stat().st_size,
                        "etag": "synthetic-stage-destination",
                        "checksums": {"ChecksumSHA256": checksum},
                        "checksum_type": "FULL_OBJECT",
                        "sha256": digest,
                        "kms_key_id": KMS_ARN,
                    },
                    "checks": {
                        "source_unchanged": True,
                        "copy_version_exact": True,
                        "bytes_equal": True,
                        "sha256_equal": True,
                        "full_object_checksum": True,
                        "exact_kms": True,
                    },
                    "status": "passed",
                }
            )
        stage_receipt_path = self.aux / "stage-provenance.json"
        write_json(
            stage_receipt_path,
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "batch_status": "SUCCEEDED",
                "execution_receipt_sha256": sha256(self.aux / "execution.json"),
                "source_prefix": (
                    f"s3://diana-omics-work-test/runs/diana-hrd/{RUN_ID}/"
                    "private-results/"
                ),
                "destination_prefix": stage_destination_prefix,
                "kms_key_arn": KMS_ARN,
                "source_bucket_versioning": "Suspended",
                "destination_bucket_versioning": "Enabled",
                "destination_history_exact": True,
                "script_sha256": "f" * 64,
                "receipt_anchor_strategy": (
                    "sha256_content_addressed_never_overwritten"
                ),
                "objects": stage_rows,
                "object_count": 2,
                "passed_count": 2,
            },
        )
        stage_receipt_sha = sha256(stage_receipt_path)
        write_json(
            self.aux / "stage-provenance-anchor.json",
            {
                "schema_version": 1,
                "status": "passed",
                "receipt_sha256": stage_receipt_sha,
                "receipt_bytes": stage_receipt_path.stat().st_size,
                "receipt_uri": (
                    stage_destination_prefix
                    + f"receipts/{stage_receipt_sha}.json"
                ),
                "receipt_version_id": "stage-receipt-version",
                "checks": {
                    "version_exact": True,
                    "bytes_exact": True,
                    "sha256_checksum_exact": True,
                    "exact_kms": True,
                },
            },
        )
        reference_fasta_sha256 = "d" * 64
        reference_fai_sha256 = "e" * 64
        write_json(
            self.aux / "staged-input-validation.json",
            {
                "schema_version": 1,
                "route": "sigprofiler_sbs3",
                "status": "passed",
                "checks": {
                    "somatic_vcf_reference": {
                        "status": "passed",
                        "pass_snv_records": 1,
                        "pass_snv_alleles": 1,
                        "reference_fasta_sha256": reference_fasta_sha256,
                        "reference_fai_sha256": reference_fai_sha256,
                    },
                    "sbs96_equivalence": {
                        "status": "passed",
                        "matrix_matches_independent_pass_vcf_derivation": True,
                        "contexts": 96,
                        "usable_pass_snv_alleles": 1,
                        "matrix_burden": 1,
                    },
                },
                "classification_authorization": "none",
                "authorized_hrd_state": "no_call",
            },
        )

        early_pass = [{"contig": "chr1", "position": "1", "filter": "PASS"}]
        early_cnv_rows = [{"contig": "chr1", "start": "0", "end": "100", "coverage_class": "neutral_or_low_signal"}]
        write_csv(self.early / "variants/core_hrr_pass_variants.csv", early_pass)
        write_csv(self.early / "coverage_cnv/coverage_cnv_bins.csv", early_cnv_rows)
        write_json(
            self.early / "early_look_summary.json",
            {
                "status": "partial_evidence",
                "overall_hrd_status": "no_call",
                "core_hrr_variants": {"pass_records": 1, "brca1_brca2_pass_records": 0},
                "coverage_cnv": {"bin_count": 1, "relative_gain_bins": 0, "relative_loss_bins": 0, "median_raw_log2_tumor_normal": 0.0},
                "contamination": {"contamination": 0.02},
                "bam_qc": {"tumor": {"total_reads": 10}, "normal": {"total_reads": 12}},
            },
        )
        (self.artifacts / "logs/worker-extra.log").parent.mkdir(parents=True, exist_ok=True)
        (self.artifacts / "logs/worker-extra.log").write_text(
            "synthetic unconsumed final artifact\n", encoding="utf-8"
        )
        freeze_rows = []
        for index, path in enumerate(sorted(item for item in self.artifacts.rglob("*") if item.is_file()), 1):
            relative = str(path.relative_to(self.artifacts))
            checksum = base64.b64encode(hashlib.sha256(path.read_bytes()).digest()).decode("ascii")
            freeze_rows.append(
                {
                    "relative_key": relative,
                    "source": {
                        "bucket": "diana-omics-results-test",
                        "key": f"runs/diana-hrd/{RUN_ID}/artifacts/{relative}",
                        "version_id": "source-version",
                        "bytes": path.stat().st_size,
                        "etag": "synthetic",
                        "checksums": {"ChecksumSHA256": checksum},
                        "checksum_type": "FULL_OBJECT",
                    },
                    "destination": {
                        "bucket": "diana-omics-private-results-test",
                        "key": f"runs/subject01/{RUN_ID}/deterministic/artifacts/{relative}",
                        "version_id": f"destination-version-{index}",
                        "bytes": path.stat().st_size,
                        "etag": "synthetic",
                        "checksums": {"ChecksumSHA256": checksum},
                        "checksum_type": "FULL_OBJECT",
                        "server_side_encryption": "aws:kms",
                        "kms_key_id": KMS_ARN,
                    },
                    "checks": {
                        "source_stable": True,
                        "size_matches": True,
                        "common_checksum_matches": True,
                        "exact_kms_matches": True,
                        "destination_versioned": True,
                    },
                    "status": "passed",
                }
            )
        write_json(
            self.aux / "final-freeze.json",
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "batch_status": "SUCCEEDED",
                "execution_receipt": {
                    "path": str(self.aux / "execution.json"),
                    "sha256": sha256(self.aux / "execution.json"),
                },
                "source_prefix": f"s3://diana-omics-results-test/runs/diana-hrd/{RUN_ID}/artifacts/",
                "destination_prefix": f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/deterministic/artifacts/",
                "kms_key_arn": KMS_ARN,
                "script_sha256": "e" * 64,
                "destination_bucket_versioning": "Enabled",
                "destination_initial_version_history_count": 0,
                "receipt_anchor_strategy": "sha256_content_addressed_create_only",
                "object_count": len(freeze_rows),
                "passed_count": len(freeze_rows),
                "initial_inventory_identity": [
                    {
                        "relative_key": row["relative_key"],
                        "key": row["source"]["key"],
                        "bytes": row["source"]["bytes"],
                        "etag": row["source"]["etag"],
                        "version_id": row["source"]["version_id"],
                    }
                    for row in freeze_rows
                ],
                "final_inventory_identity": [
                    {
                        "relative_key": row["relative_key"],
                        "key": row["source"]["key"],
                        "bytes": row["source"]["bytes"],
                        "etag": row["source"]["etag"],
                        "version_id": row["source"]["version_id"],
                    }
                    for row in freeze_rows
                ],
                "destination_inventory": [
                    {
                        "relative_key": row["relative_key"],
                        "key": row["destination"]["key"],
                        "version_id": row["destination"]["version_id"],
                        "bytes": row["destination"]["bytes"],
                        "etag": row["destination"]["etag"],
                        "checksums": row["destination"]["checksums"],
                        "checksum_type": "FULL_OBJECT",
                        "kms_key_id": KMS_ARN,
                    }
                    for row in freeze_rows
                ],
                "checks": {
                    "execution_receipt_bound": True,
                    "complete_source_inventory_unchanged": True,
                    "destination_exact_history_and_receipt_match": True,
                },
                "objects": freeze_rows,
            },
        )
        freeze_receipt = self.aux / "final-freeze.json"
        freeze_receipt_sha = sha256(freeze_receipt)
        write_json(
            self.aux / "final-freeze-anchor.json",
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "receipt_sha256": freeze_receipt_sha,
                "receipt_bytes": freeze_receipt.stat().st_size,
                "receipt_uri": (
                    f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/"
                    "deterministic/provenance/final-artifact-freeze-receipts/"
                    f"{freeze_receipt_sha}.json"
                ),
                "receipt_version_id": "final-freeze-receipt-version",
                "checks": {
                    "version_exact": True,
                    "bytes_exact": True,
                    "sha256_exact": True,
                    "sha256_checksum_exact": True,
                    "exact_kms": True,
                    "single_create_only_version": True,
                },
            },
        )
        write_json(
            self.aux / "exact-materialization.json",
            {
                "schema_version": 1,
                "status": "passed",
                "run_id": RUN_ID,
                "batch_job_id": "synthetic-job",
                "freeze_receipt_sha256": sha256(freeze_receipt),
                "expected_kms_key_arn": KMS_ARN,
                "object_count": len(freeze_rows),
                "passed_count": len(freeze_rows),
                "objects": [
                    {
                        "relative_key": row["relative_key"],
                        "bucket": row["destination"]["bucket"],
                        "key": row["destination"]["key"],
                        "bytes": row["destination"]["bytes"],
                        "version_id": row["destination"]["version_id"],
                        "checksums": row["destination"]["checksums"],
                        "checksum_type": "FULL_OBJECT",
                        "server_side_encryption": "aws:kms",
                        "kms_key_id": KMS_ARN,
                        "sha256": sha256(self.artifacts / row["relative_key"]),
                        "checks": {
                            "version_id": True,
                            "content_length": True,
                            "local_bytes": True,
                            "checksums": True,
                            "sse": True,
                            "kms": True,
                        },
                    }
                    for row in freeze_rows
                ],
            },
        )
        freeze_by_relative = {row["relative_key"]: row for row in freeze_rows}

        def final_source(relative: str) -> dict[str, Any]:
            freeze_row = freeze_by_relative[relative]
            return {
                "version_id": freeze_row["destination"]["version_id"],
                "bytes": freeze_row["destination"]["bytes"],
                "etag": "synthetic",
                "checksums": freeze_row["destination"]["checksums"],
                "sha256": sha256(self.artifacts / relative),
                "expected_sha256": None,
                "kms_key_arn": KMS_ARN,
            }

        def reference_source(
            artifact: str, digest: str, version_id: str
        ) -> dict[str, Any]:
            return {
                "version_id": version_id,
                "bytes": 100,
                "etag": "synthetic-reference",
                "checksums": {
                    "ChecksumSHA256": base64.b64encode(
                        bytes.fromhex(digest)
                    ).decode("ascii")
                },
                "sha256": digest,
                "expected_sha256": digest,
                "kms_key_arn": KMS_ARN,
                "artifact": artifact,
            }

        final_prefix = (
            f"s3://diana-omics-private-results-test/runs/subject01/{RUN_ID}/"
            "deterministic/final/"
        )
        staged_path = self.aux / "staged-input-validation.json"
        output_digests = {
            "somatic.pass.vcf.gz": "1" * 64,
            "somatic.pass.vcf.gz.tbi": "2" * 64,
            "sbs96.csv": "3" * 64,
            "staged_input_validation.json": sha256(staged_path),
        }
        outputs = {
            name: {
                "uri": final_prefix + name,
                "version_id": f"canonical-version-{index}",
                "bytes": (
                    staged_path.stat().st_size
                    if name == "staged_input_validation.json"
                    else 100 + index
                ),
                "etag": "synthetic-output",
                "checksums": {
                    "ChecksumSHA256": base64.b64encode(
                        bytes.fromhex(digest)
                    ).decode("ascii")
                },
                "sha256": digest,
                "kms_key_arn": KMS_ARN,
            }
            for index, (name, digest) in enumerate(output_digests.items(), 1)
        }
        source_vcf = "variants/diana.wgs.mutect2.filtered.vcf.gz"
        source_vcf_index = source_vcf + ".tbi"
        source_matrix = "signatures/wgs_sbs96_matrix.csv"
        write_json(
            self.aux / "crosscheck-materialization.json",
            {
                "schema_version": 2,
                "status": "passed",
                "generated_at_utc": "2026-07-17T00:00:01+00:00",
                "run_alias": "subject01",
                "script_sha256": "f" * 64,
                "source_custody": {
                    "vcf": final_source(source_vcf),
                    "vcf_index": final_source(source_vcf_index),
                    "matrix": final_source(source_matrix),
                    "fasta": reference_source(
                        "reference.fa",
                        reference_fasta_sha256,
                        "reference-fasta-version",
                    ),
                    "fai": reference_source(
                        "reference.fa.fai",
                        reference_fai_sha256,
                        "reference-fai-version",
                    ),
                },
                "validation": {
                    "status": "passed",
                    "run_alias": "subject01",
                    "source_sample_names_retained": False,
                    "pass_snv_records": 1,
                    "pass_snv_alleles": 1,
                    "sbs96_contexts": 96,
                    "sbs96_burden": 1,
                    "matrix_matches_independent_pass_vcf_derivation": True,
                },
                "input_sha256": {
                    "filtered_vcf": sha256(self.artifacts / source_vcf),
                    "filtered_vcf_index": sha256(
                        self.artifacts / source_vcf_index
                    ),
                    "source_sbs96_matrix": sha256(
                        self.artifacts / source_matrix
                    ),
                    "reference_fasta": reference_fasta_sha256,
                    "reference_fai": reference_fai_sha256,
                },
                "outputs": outputs,
                "classification_authorization": "none",
                "authorized_hrd_state": "no_call",
            },
        )

    def command(self) -> list[str]:
        return [
            sys.executable,
            str(GENERATOR),
            "--artifact-root", str(self.artifacts),
            "--preflight-json", str(self.aux / "preflight.json"),
            "--gather-json", str(self.aux / "gather.json"),
            "--sha-audit", str(self.aux / "sha-audit.json"),
            "--execution-json", str(self.aux / "execution.json"),
            "--executed-worker-freeze-receipt", str(self.aux / "executed-worker-freeze.json"),
            "--executed-worker-freeze-receipt-upload", str(self.aux / "executed-worker-freeze-upload.json"),
            "--final-freeze-receipt", str(self.aux / "final-freeze.json"),
            "--final-freeze-anchor", str(self.aux / "final-freeze-anchor.json"),
            "--exact-materialization-receipt", str(self.aux / "exact-materialization.json"),
            "--crosscheck-materialization-receipt", str(self.aux / "crosscheck-materialization.json"),
            "--stage-provenance-receipt", str(self.aux / "stage-provenance.json"),
            "--stage-provenance-anchor", str(self.aux / "stage-provenance-anchor.json"),
            "--staged-input-validation-json", str(self.aux / "staged-input-validation.json"),
            "--expected-kms-key-arn", KMS_ARN,
            "--early-look-root", str(self.early),
            "--output-dir", str(self.output),
        ]


@unittest.skipUnless(shutil.which("bcftools"), "bcftools is required for the indexed-VCF E2E fixture")
class StageDeterministicWgsReportTests(unittest.TestCase):
    def test_stable_snapshot_is_independent_of_later_source_changes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-input-snapshot-") as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            early = root / "early"
            auxiliary = root / "auxiliary.json"
            (artifacts / "nested").mkdir(parents=True)
            early.mkdir()
            source_artifact = artifacts / "nested/result.json"
            source_early = early / "summary.json"
            source_artifact.write_text('{"value":1}\n', encoding="utf-8")
            source_early.write_text('{"value":2}\n', encoding="utf-8")
            auxiliary.write_text('{"value":3}\n', encoding="utf-8")
            snapshot = REPORT_MODULE.create_stable_input_snapshot(
                artifacts,
                early,
                {"auxiliary": auxiliary},
                root / "snapshot",
            )
            frozen_artifact = snapshot["artifact_root"] / "nested/result.json"
            frozen_hash = sha256(frozen_artifact)
            source_artifact.write_text('{"value":99}\n', encoding="utf-8")
            auxiliary.write_text('{"value":99}\n', encoding="utf-8")
            self.assertEqual(sha256(frozen_artifact), frozen_hash)
            self.assertEqual(snapshot["manifest"]["status"], "passed")
            self.assertEqual(snapshot["manifest"]["file_count"], 3)

    def test_stable_snapshot_rejects_concurrent_source_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-input-snapshot-") as temporary:
            root = Path(temporary)
            artifacts = root / "artifacts"
            early = root / "early"
            auxiliary = root / "auxiliary.json"
            artifacts.mkdir()
            early.mkdir()
            target = artifacts / "result.json"
            target.write_text('{"value":1}\n', encoding="utf-8")
            (early / "summary.json").write_text('{"value":2}\n', encoding="utf-8")
            auxiliary.write_text('{"value":3}\n', encoding="utf-8")
            original_copy = REPORT_MODULE.copy_baseline_file
            changed = False

            def mutate_after_copy(
                source: Path,
                destination: Path,
                identity: tuple[int, int, int, int, int, int],
            ) -> None:
                nonlocal changed
                original_copy(source, destination, identity)
                if not changed and source.resolve() == target.resolve():
                    changed = True
                    source.write_text('{"value":99}\n', encoding="utf-8")

            with patch.object(
                REPORT_MODULE,
                "copy_baseline_file",
                side_effect=mutate_after_copy,
            ), self.assertRaisesRegex(
                ValueError, "file changed during stable snapshot"
            ):
                REPORT_MODULE.create_stable_input_snapshot(
                    artifacts,
                    early,
                    {"auxiliary": auxiliary},
                    root / "snapshot",
                )

    def test_deidentified_worker_schema_fixture_generates_no_call_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                {path.name for path in fixture.output.iterdir()},
                {
                    "report.md",
                    "readiness.csv",
                    "evidence_checks.json",
                    "input_sha256.csv",
                    "report_manifest.json",
                },
            )
            report = (fixture.output / "report.md").read_text(encoding="utf-8")
            self.assertIn("Overall HRD status: `no_call`", report)
            self.assertIn("its 1 total targeted PASS record", report)
            self.assertNotIn("subject01", report)
            self.assertNotIn("Synthetic WGS", report)
            checks = json.loads((fixture.output / "evidence_checks.json").read_text(encoding="utf-8"))
            self.assertEqual(checks["status"], "passed")
            self.assertEqual(checks["overall_hrd_status"], "no_call")
            self.assertTrue(all(row["status"] == "passed" for row in checks["checks"]))
            self.assertIn("alignment_metric_bounds", {row["check_id"] for row in checks["checks"]})
            self.assertIn("final_artifact_freeze", {row["check_id"] for row in checks["checks"]})
            self.assertIn("exact_version_materialization", {row["check_id"] for row in checks["checks"]})
            self.assertIn("crosscheck_materialization_custody", {row["check_id"] for row in checks["checks"]})
            self.assertIn("stable_input_snapshot", {row["check_id"] for row in checks["checks"]})
            self.assertIn("stage_provenance_custody", {row["check_id"] for row in checks["checks"]})
            self.assertEqual(checks["stage_provenance"]["status"], "passed")
            self.assertEqual(checks["input_snapshot"]["strategy"], "open_no_follow_fstat_copy_global_restat")
            with (fixture.output / "input_sha256.csv").open(
                newline="", encoding="utf-8"
            ) as handle:
                input_rows = list(csv.DictReader(handle))
            self.assertTrue(input_rows)
            self.assertTrue(
                all(not row["path"].startswith("/") for row in input_rows)
            )
            manifest = json.loads((fixture.output / "report_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["method_id"], "deterministic_full_wgs")
            self.assertEqual(manifest["evidence_status"], "partial_evidence")
            self.assertEqual(manifest["authorized_hrd_state"], "no_call")
            self.assertFalse(manifest["classification_authorized"])
            self.assertEqual(manifest["review_summary"]["sbs96"]["matrix_equivalence"], "passed")
            self.assertEqual(
                set(manifest["support_sha256"]),
                {"readiness.csv", "evidence_checks.json", "input_sha256.csv"},
            )
            for relative, expected_hash in manifest["support_sha256"].items():
                self.assertEqual(expected_hash, sha256(fixture.output / relative))
            self.assertEqual(manifest["review_summary"]["custody"]["private_freeze_status"], "passed")
            self.assertGreater(manifest["review_summary"]["custody"]["report_consumed_versioned_artifacts"], 0)
            self.assertTrue(
                manifest["review_summary"]["custody"]["exact_materialization_receipt_sha256"]
            )
            self.assertTrue(
                manifest["review_summary"]["custody"]
                ["crosscheck_materialization_receipt_sha256"]
            )
            self.assertEqual(
                manifest["review_summary"]["custody"]
                ["stage_provenance_receipt_version_id"],
                "stage-receipt-version",
            )
            self.assertEqual(
                manifest["review_summary"]["custody"]
                ["freeze_receipt_version_id"],
                "final-freeze-receipt-version",
            )
            self.assertTrue(
                manifest["review_summary"]["custody"]
                ["input_snapshot_receipt_sha256"]
            )
            self.assertEqual(manifest["report_sha256"], sha256(fixture.output / "report.md"))
            self.assertTrue(manifest["source_sha256"])
            rows = PUBLISH.validate_packet_dir(
                fixture.output,
                "deterministic_full_wgs",
                ("subject01", "Synthetic WGS"),
            )
            self.assertEqual(
                [row["relative_path"] for row in rows],
                sorted(PUBLISH.METHOD_CONTRACTS["deterministic_full_wgs"]["files"]),
            )
            self.assertFalse(
                any(
                    fixture.root.glob(
                        "deterministic-full-input-snapshot-*"
                    )
                )
            )

    def test_variant_count_inconsistency_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary), inconsistent_variant_count=True)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("variant_summary_counts", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_effective_job_timeout_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            execution_path = fixture.aux / "execution.json"
            execution = json.loads(execution_path.read_text(encoding="utf-8"))
            execution["batch"]["timeout"] = {}
            write_json(execution_path, execution)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_execution_provenance", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_missing_frozen_version_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "final-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["destination"]["version_id"] = ""
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_final_freeze_anchor_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            anchor_path = fixture.aux / "final-freeze-anchor.json"
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            anchor["receipt_version_id"] = ""
            write_json(anchor_path, anchor)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("final_artifact_freeze", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_exact_version_materialization_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "exact-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact_version_materialization", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_unconsumed_frozen_artifact_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "exact-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            extra = next(
                row
                for row in receipt["objects"]
                if row["relative_key"] == "logs/worker-extra.log"
            )
            extra["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact_version_materialization", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_crosscheck_source_version_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["source_custody"]["vcf"]["version_id"] = "wrong-version"
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_materialization_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_crosscheck_source_sha_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["source_custody"]["matrix"]["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_materialization_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_staged_output_hash_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["outputs"]["staged_input_validation.json"]["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_materialization_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_canonical_output_kms_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "crosscheck-materialization.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["outputs"]["sbs96.csv"]["kms_key_arn"] = (
                "arn:aws:kms:us-east-1:000000000000:key/wrong"
            )
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("crosscheck_materialization_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_stage_provenance_version_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "stage-provenance.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["objects"][0]["destination"]["version_id"] = ""
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stage_provenance_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_stage_anchor_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            anchor_path = fixture.aux / "stage-provenance-anchor.json"
            anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
            anchor["receipt_sha256"] = "0" * 64
            write_json(anchor_path, anchor)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stage_provenance_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_local_preflight_fails_frozen_stage_binding(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            preflight_path = fixture.aux / "preflight.json"
            preflight_path.write_text(
                preflight_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stage_provenance_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())

    def test_changed_executed_worker_receipt_fails_before_report_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synthetic-hrd-report-") as temporary:
            fixture = SyntheticFixture(Path(temporary))
            receipt_path = fixture.aux / "executed-worker-freeze.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["source"]["sha256"] = "0" * 64
            write_json(receipt_path, receipt)
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("batch_worker_custody", result.stdout + result.stderr)
            self.assertFalse((fixture.output / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
