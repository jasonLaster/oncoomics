from __future__ import annotations

from pathlib import Path
from typing import Any

from .paths import path_from_root

DIANA_RAW_TEMPLATE = "manifests/diana_raw_inputs.template.csv"
DIANA_RAW_DEFAULT = "manifests/diana_raw_inputs.csv"
DIANA_RAW_RESULTS = "results/diana_raw_intake"
DIANA_RAW_S3_INBOX_URI = "s3://diana-omics-raw-inputs-172630973301-us-east-1/diana/inbox"

DIANA_RAW_COLUMNS = [
    "patient_id",
    "pair_id",
    "sample_id",
    "role",
    "assay",
    "data_type",
    "library_layout",
    "fastq_1",
    "fastq_2",
    "bam",
    "bai",
    "cram",
    "crai",
    "reference_id",
    "reference_path",
    "reference_fai_path",
    "reference_dict_path",
    "read_group_id",
    "read_group_sample",
    "read_group_library",
    "read_group_platform",
    "read_group_platform_unit",
    "tumor_purity",
    "tumor_content",
    "normal_type",
    "capture_bed",
    "rna_fastq_1",
    "rna_fastq_2",
    "notes",
    "caveat",
]

DNA_ROLES = {"tumor", "normal"}
DNA_ASSAYS = {"WGS", "WES"}
DATA_TYPES = {"FASTQ", "BAM", "CRAM", "RNA_FASTQ", "MANIFEST_ONLY"}


def default_samplesheet_path(value: str = "") -> str:
    return value or DIANA_RAW_DEFAULT


def template_rows() -> list[dict[str, str]]:
    reference_path = "data/raw/reference/full_reference_smoke/ucsc_hg38_analysis_set_full/ucsc_hg38_analysis_set_full.fa"
    return [
        {
            "patient_id": "DIANA",
            "pair_id": "DIANA-DNA-001",
            "sample_id": "DIANA-TUMOR-DNA",
            "role": "tumor",
            "assay": "WGS",
            "data_type": "FASTQ",
            "library_layout": "PAIRED",
            "fastq_1": "data/raw/diana/DIANA-TUMOR-DNA_R1.fastq.gz",
            "fastq_2": "data/raw/diana/DIANA-TUMOR-DNA_R2.fastq.gz",
            "bam": "",
            "bai": "",
            "cram": "",
            "crai": "",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": reference_path,
            "reference_fai_path": f"{reference_path}.fai",
            "reference_dict_path": "data/raw/reference/full_reference_smoke/ucsc_hg38_analysis_set_full/ucsc_hg38_analysis_set_full.dict",
            "read_group_id": "DIANA-TUMOR-DNA.rg1",
            "read_group_sample": "DIANA-TUMOR-DNA",
            "read_group_library": "DIANA-DNA-001",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "pending",
            "tumor_purity": "pending",
            "tumor_content": "pending",
            "normal_type": "",
            "capture_bed": "",
            "rna_fastq_1": "",
            "rna_fastq_2": "",
            "notes": "Replace placeholder paths once Diana tumor DNA data arrive.",
            "caveat": "Template row only; do not interpret until file paths and metadata are confirmed.",
        },
        {
            "patient_id": "DIANA",
            "pair_id": "DIANA-DNA-001",
            "sample_id": "DIANA-NORMAL-DNA",
            "role": "normal",
            "assay": "WGS",
            "data_type": "FASTQ",
            "library_layout": "PAIRED",
            "fastq_1": "data/raw/diana/DIANA-NORMAL-DNA_R1.fastq.gz",
            "fastq_2": "data/raw/diana/DIANA-NORMAL-DNA_R2.fastq.gz",
            "bam": "",
            "bai": "",
            "cram": "",
            "crai": "",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "reference_path": reference_path,
            "reference_fai_path": f"{reference_path}.fai",
            "reference_dict_path": "data/raw/reference/full_reference_smoke/ucsc_hg38_analysis_set_full/ucsc_hg38_analysis_set_full.dict",
            "read_group_id": "DIANA-NORMAL-DNA.rg1",
            "read_group_sample": "DIANA-NORMAL-DNA",
            "read_group_library": "DIANA-DNA-001",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "pending",
            "tumor_purity": "",
            "tumor_content": "",
            "normal_type": "matched_normal",
            "capture_bed": "",
            "rna_fastq_1": "",
            "rna_fastq_2": "",
            "notes": "Replace placeholder paths once Diana matched-normal DNA data arrive.",
            "caveat": "Template row only; do not interpret until file paths and metadata are confirmed.",
        },
        {
            "patient_id": "DIANA",
            "pair_id": "DIANA-RNA-001",
            "sample_id": "DIANA-TUMOR-RNA",
            "role": "rna_tumor",
            "assay": "RNA",
            "data_type": "RNA_FASTQ",
            "library_layout": "PAIRED",
            "fastq_1": "",
            "fastq_2": "",
            "bam": "",
            "bai": "",
            "cram": "",
            "crai": "",
            "reference_id": "",
            "reference_path": "",
            "reference_fai_path": "",
            "reference_dict_path": "",
            "read_group_id": "",
            "read_group_sample": "DIANA-TUMOR-RNA",
            "read_group_library": "DIANA-RNA-001",
            "read_group_platform": "ILLUMINA",
            "read_group_platform_unit": "pending",
            "tumor_purity": "pending",
            "tumor_content": "pending",
            "normal_type": "",
            "capture_bed": "",
            "rna_fastq_1": "data/raw/diana/DIANA-TUMOR-RNA_R1.fastq.gz",
            "rna_fastq_2": "data/raw/diana/DIANA-TUMOR-RNA_R2.fastq.gz",
            "notes": "Optional RNA context row; omit if no RNA raw data are available.",
            "caveat": "RNA is a context lane and is not required for DNA HRD mechanics.",
        },
    ]


def is_template_placeholder(value: str) -> bool:
    return value.startswith("data/raw/diana/DIANA-") or value in {"pending", "template", "TBD"}


def resolve_existing_file(relative_or_absolute: str) -> Path:
    path = Path(relative_or_absolute)
    return path if path.is_absolute() else path_from_root(path)


def row_has_fastq_pair(row: dict[str, str]) -> bool:
    return bool(row.get("fastq_1") and row.get("fastq_2"))


def row_has_bam_pair(row: dict[str, str]) -> bool:
    return bool(row.get("bam") and row.get("bai"))


def row_has_cram_pair(row: dict[str, str]) -> bool:
    return bool(row.get("cram") and row.get("crai"))


def diana_raw_contract() -> dict[str, Any]:
    return {
        "samplesheet": DIANA_RAW_DEFAULT,
        "template": DIANA_RAW_TEMPLATE,
        "requiredColumns": DIANA_RAW_COLUMNS,
        "dnaRoles": sorted(DNA_ROLES),
        "dnaAssays": sorted(DNA_ASSAYS),
        "dataTypes": sorted(DATA_TYPES),
        "requiredDnaContract": "At least one tumor DNA row and one matched normal DNA row sharing pair_id, with FASTQ pairs, BAM+BAI, or CRAM+CRAI.",
        "rnaContract": "Optional RNA_FASTQ rows can be included for expression context, but DNA tumor-normal rows are required for HRD mechanics.",
        "referenceContract": "Diana DNA rows should use the same reference_id/reference_path/reference_fai_path/reference_dict_path unless a reviewer approves a build-specific split.",
        "handoffPlanCommand": "PYTHONPATH=src /usr/bin/python3 -m diana_omics plan:diana-raw-handoff",
        "s3InboxUri": DIANA_RAW_S3_INBOX_URI,
        "uploadContract": "Upload or transfer Diana raw files only under the diana/inbox prefix. The AWS bucket policy allows write-only uploads from any AWS principal; no presigned URLs are required.",
        "recomputeCommand": "DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics stage:diana-raw",
        "validationCommand": "DIANA_RAW_SAMPLESHEET=manifests/diana_raw_inputs.csv DIANA_RAW_REQUIRE_DATA=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics verify:diana-raw",
    }
