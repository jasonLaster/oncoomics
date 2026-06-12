from __future__ import annotations

import os
import re

from ..paths import path_from_root
from ..utils import (
    command_path,
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
ASSET_CACHE_URI = os.environ.get("PHASE3_WGS_ASSET_CACHE_URI", "").rstrip("/")
ASSET_CACHE_MODE = os.environ.get("PHASE3_WGS_ASSET_CACHE_MODE", "readwrite" if ASSET_CACHE_URI else "off").lower()


def cache_reads_enabled() -> bool:
    return bool(ASSET_CACHE_URI) and ASSET_CACHE_MODE in {"read", "readwrite"}


def cache_writes_enabled() -> bool:
    return bool(ASSET_CACHE_URI) and ASSET_CACHE_MODE in {"write", "readwrite"}


def aws_cli_path() -> str:
    aws = command_path("aws")
    if aws:
        return aws
    bundled = "/opt/diana-aws/bin/aws"
    return bundled if path_from_root(bundled).exists() else ""


def reference_cache_uri(reference_id: str, file_name: str) -> str:
    return f"{ASSET_CACHE_URI}/reference/{reference_id}/{file_name}"


def s3_object_exists(aws: str, uri: str) -> bool:
    try:
        run_command(f"{quote_shell_arg(aws)} s3 ls {quote_shell_arg(uri)} >/dev/null")
    except RuntimeError:
        return False
    return True


def restore_cached_reference_file(aws: str, reference_id: str, relative_path: str) -> bool:
    if not cache_reads_enabled() or not aws:
        return False
    target = path_from_root(relative_path)
    if target.exists() and target.stat().st_size > 0:
        return False
    uri = reference_cache_uri(reference_id, target.name)
    if not s3_object_exists(aws, uri):
        print(f"[cache-miss] label={reference_id}.{target.name} uri={uri}", flush=True)
        return False
    ensure_dir(target.parent)
    run_command(
        f"{quote_shell_arg(aws)} s3 cp --only-show-errors {quote_shell_arg(uri)} {quote_shell_arg(str(target))}",
        f"{RESULTS_DIR}/cache_restore.{reference_id}.{target.name}.log",
    )
    print(f"[cache-restore] label={reference_id}.{target.name} bytes={target.stat().st_size} uri={uri}", flush=True)
    return True


def publish_cached_reference_file(aws: str, reference_id: str, relative_path: str) -> bool:
    if not cache_writes_enabled() or not aws:
        return False
    source = path_from_root(relative_path)
    if not source.exists() or source.stat().st_size == 0:
        return False
    uri = reference_cache_uri(reference_id, source.name)
    if s3_object_exists(aws, uri):
        print(f"[cache-hit] label={reference_id}.{source.name} bytes={source.stat().st_size} uri={uri}", flush=True)
        return False
    run_command(
        f"{quote_shell_arg(aws)} s3 cp --only-show-errors {quote_shell_arg(str(source))} {quote_shell_arg(uri)}",
        f"{RESULTS_DIR}/cache_publish.{reference_id}.{source.name}.log",
    )
    print(f"[cache-publish] label={reference_id}.{source.name} bytes={source.stat().st_size} uri={uri}", flush=True)
    return True


def reference_cache_paths(reference: dict[str, str], source_path: str, fasta_path: str) -> list[str]:
    return [
        source_path,
        fasta_path,
        f"{fasta_path}.fai",
        f"{fasta_path}.amb",
        f"{fasta_path}.ann",
        f"{fasta_path}.bwt",
        f"{fasta_path}.pac",
        f"{fasta_path}.sa",
        f"{reference_dir(reference)}/{reference['reference_id']}.dict",
        reference["interval_bed_path"],
    ]


def reference_dir(reference: dict[str, str]) -> str:
    return f"{REFERENCE_ROOT}/{reference['reference_id']}"


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
    aws = aws_cli_path()
    cache_events: list[dict[str, str]] = []
    for reference in REFERENCES:
        reference_root = reference_dir(reference)
        source_path = f"{reference_root}/{reference['source_file']}"
        fasta_path = f"{reference_root}/{reference['reference_id']}.fa"
        ensure_dir(path_from_root(reference_root))
        ensure_dir(path_from_root(f"{SMOKE_ROOT}/{reference['reference_id']}/bam"))
        ensure_dir(path_from_root(f"{SMOKE_ROOT}/{reference['reference_id']}/vcf"))
        for cache_path in reference_cache_paths(reference, source_path, fasta_path):
            if restore_cached_reference_file(aws, reference["reference_id"], cache_path):
                cache_events.append({"action": "restored", "path": cache_path})
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
        for cache_path in reference_cache_paths(reference, source_path, fasta_path):
            if publish_cached_reference_file(aws, reference["reference_id"], cache_path):
                cache_events.append({"action": "published", "path": cache_path})
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
            "assetCache": {
                "enabled": bool(ASSET_CACHE_URI),
                "uri": ASSET_CACHE_URI,
                "mode": ASSET_CACHE_MODE,
                "events": cache_events,
            },
            "references": reference_rows,
            "boundary": "Phase 2D uses a full UCSC hg38 analysis-set reference with BRCA1/BRCA2 smoke intervals. It validates full-reference plumbing and caller-readiness contracts, not full-depth WES/WGS sensitivity.",
        },
    )
    print(f"Built {len(reference_rows)} full-reference smoke bundle and {len(samplesheet_rows)} sample rows.")


if __name__ == "__main__":
    main()
