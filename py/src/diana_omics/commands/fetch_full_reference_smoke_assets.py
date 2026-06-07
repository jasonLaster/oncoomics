from __future__ import annotations

import re

from ..paths import path_from_root
from ..utils import (
    ensure_dir,
    fetch_text,
    iso_now,
    md5_file,
    parse_csv,
    quote_shell_arg,
    read_text,
    run_command,
    sha256_file,
    write_csv,
    write_json,
    write_text,
)

REFERENCES = [
    {
        "reference_id": "ucsc_hg38_analysis_set_full",
        "assembly": "hg38",
        "genome_build": "GRCh38",
        "source_url": "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/analysisSet/hg38.analysisSet.fa.gz",
        "md5_url": "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/bigZips/analysisSet/md5sum.txt",
        "source_file": "hg38.analysisSet.fa.gz",
        "interval_bed_path": "data/raw/reference/full_reference_smoke/ucsc_hg38_analysis_set_full/brca_chr13_chr17_smoke.bed",
        "interval_regions": "chr13:32315086-32400266;chr17:43044295-43125482",
        "interval_genes": "BRCA2;BRCA1",
    }
]
SMOKE_PAIR_ID = "seqc2_hcc1395_wes_minimal_smoke"
REFERENCE_ROOT = "data/raw/reference/full_reference_smoke"
SMOKE_ROOT = "data/raw/smoke/seqc2_hcc1395_full_reference_smoke"
RESULTS_DIR = "results/full_reference_smoke"


def parse_md5(text: str, file_name: str) -> str:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1] == file_name and re.fullmatch(r"[0-9a-fA-F]{32}", parts[0]):
            return parts[0].lower()
    raise RuntimeError(f"Could not find md5 for {file_name}.")


def sample_name(row: dict[str, str]) -> str:
    return row["sample"].replace(f"_{row['run_accession']}", "")


def main() -> None:
    ensure_dir(path_from_root("manifests"))
    ensure_dir(path_from_root(RESULTS_DIR))
    smoke_rows = sorted(
        [row for row in parse_csv(read_text(path_from_root("manifests/raw_smoke_samplesheet.csv"))) if row["pair_id"] == SMOKE_PAIR_ID],
        key=lambda row: row["role"],
    )
    if (
        len(smoke_rows) != 2
        or not any(row["role"] == "tumor" for row in smoke_rows)
        or not any(row["role"] == "normal" for row in smoke_rows)
    ):
        raise RuntimeError(f"Expected tumor and normal rows for {SMOKE_PAIR_ID}.")
    reference_rows = []
    samplesheet_rows = []
    for reference in REFERENCES:
        reference_dir = f"{REFERENCE_ROOT}/{reference['reference_id']}"
        source_path = f"{reference_dir}/{reference['source_file']}"
        fasta_path = f"{reference_dir}/{reference['reference_id']}.fa"
        ensure_dir(path_from_root(reference_dir))
        ensure_dir(path_from_root(f"{SMOKE_ROOT}/{reference['reference_id']}/bam"))
        ensure_dir(path_from_root(f"{SMOKE_ROOT}/{reference['reference_id']}/vcf"))
        expected_md5 = parse_md5(fetch_text(reference["md5_url"]), reference["source_file"])
        if not path_from_root(source_path).exists():
            run_command(f"curl -fL --retry 3 --continue-at - {quote_shell_arg(reference['source_url'])} -o {quote_shell_arg(source_path)}")
        observed_md5 = md5_file(source_path)
        if observed_md5 != expected_md5:
            raise RuntimeError(f"{source_path} md5 mismatch: expected {expected_md5}, observed {observed_md5}.")
        if not path_from_root(fasta_path).exists():
            run_command(f"gzip -cd {quote_shell_arg(source_path)} > {quote_shell_arg(fasta_path)}")
        if not path_from_root(f"{fasta_path}.fai").exists():
            run_command(f"samtools faidx {quote_shell_arg(fasta_path)}")
        write_text(
            path_from_root(reference["interval_bed_path"]),
            "chr13\t32315085\t32400266\tBRCA2_smoke_interval\nchr17\t43044294\t43125482\tBRCA1_smoke_interval\n",
        )
        fasta_sha256 = sha256_file(fasta_path)
        reference_rows.append(
            {
                "reference_id": reference["reference_id"],
                "assembly": reference["assembly"],
                "genome_build": reference["genome_build"],
                "source": "UCSC hg38 analysisSet FASTA",
                "source_url": reference["source_url"],
                "source_md5": expected_md5,
                "md5_status": "passed",
                "fasta_path": fasta_path,
                "fasta_fai_path": f"{fasta_path}.fai",
                "fasta_sha256": fasta_sha256,
                "fasta_size_bytes": path_from_root(fasta_path).stat().st_size,
                "interval_bed_path": reference["interval_bed_path"],
                "interval_regions": reference["interval_regions"],
                "interval_genes": reference["interval_genes"],
                "caller_smoke_tool": "bcftools mpileup/call",
                "caveat": "Full hg38 analysis-set reference for local caller-readiness smoke. Uses tiny HCC1395 FASTQ subset and BRCA interval targets; not full-depth WES/WGS sensitivity validation.",
            }
        )
        for row in smoke_rows:
            run = row["run_accession"]
            sample = sample_name(row)
            bam = f"{SMOKE_ROOT}/{reference['reference_id']}/bam/{run}.coordinate_sorted.bam"
            samplesheet_rows.append(
                {
                    **{
                        key: row[key]
                        for key in [
                            "pair_id",
                            "patient",
                            "role",
                            "status",
                            "assay",
                            "library_strategy",
                            "library_layout",
                            "platform",
                            "model",
                            "run_accession",
                            "fastq_1",
                            "fastq_2",
                        ]
                    },
                    "sample": sample,
                    "reference_id": reference["reference_id"],
                    "assembly": reference["assembly"],
                    "genome_build": reference["genome_build"],
                    "reference_path": fasta_path,
                    "reference_sha256": fasta_sha256,
                    "interval_bed_path": reference["interval_bed_path"],
                    "interval_regions": reference["interval_regions"],
                    "interval_genes": reference["interval_genes"],
                    "aligner": "bwa mem",
                    "aligner_threads": "4",
                    "read_group_id": f"{run}_{reference['assembly']}_full",
                    "read_group_sample": sample,
                    "read_group_library": f"{row['assay']}_{row['role']}_{reference['assembly']}_full",
                    "read_group_platform": "ILLUMINA",
                    "read_group_platform_unit": run,
                    "output_bam": bam,
                    "output_bai": f"{bam}.bai",
                    "caller_ready_scope": "full reference plus BRCA1/BRCA2 interval metadata",
                    "source": "Phase 2A local HCC1395 FASTQ subset aligned to full UCSC hg38 analysis set",
                    "caveat": "Full-reference caller-readiness smoke using tiny downsampled reads; not full-depth WES/WGS, not clinical somatic calling, and not HRD evidence.",
                }
            )
    write_csv(path_from_root("manifests/full_reference_smoke_references.csv"), reference_rows)
    write_csv(path_from_root("manifests/full_reference_smoke_samplesheet.csv"), samplesheet_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/reference_assets_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "built",
            "referenceCount": len(reference_rows),
            "sampleRows": len(samplesheet_rows),
            "references": reference_rows,
            "boundary": "Phase 2D uses a full UCSC hg38 analysis-set reference with BRCA1/BRCA2 smoke intervals. It validates full-reference plumbing and caller-readiness contracts, not full-depth WES/WGS sensitivity.",
        },
    )
    print(f"Built {len(reference_rows)} full-reference smoke bundle and {len(samplesheet_rows)} sample rows.")


if __name__ == "__main__":
    main()
