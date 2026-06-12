from __future__ import annotations

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
)

REFERENCES = [
    {
        "reference_id": "ucsc_hg38_chr13_chr17",
        "assembly": "hg38",
        "genome_build": "GRCh38",
        "source_base_url": "https://hgdownload.soe.ucsc.edu/goldenPath/hg38/chromosomes",
        "chromosomes": ["chr13", "chr17"],
        "genes_covered": ["BRCA2", "BRCA1"],
    },
    {
        "reference_id": "ucsc_hg19_chr13_chr17",
        "assembly": "hg19",
        "genome_build": "GRCh37",
        "source_base_url": "https://hgdownload.soe.ucsc.edu/goldenPath/hg19/chromosomes",
        "chromosomes": ["chr13", "chr17"],
        "genes_covered": ["BRCA2", "BRCA1"],
    },
]
SMOKE_PAIR_ID = "seqc2_hcc1395_wes_minimal_smoke"
REFERENCE_ROOT = "data/raw/reference/human_reference_smoke"
SMOKE_ROOT = "data/raw/smoke/seqc2_hcc1395_human_reference_smoke"
RESULTS_DIR = "results/human_reference_smoke"


def parse_md5s(text: str) -> dict[str, str]:
    md5s = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and len(parts[0]) == 32:
            md5s[parts[1]] = parts[0].lower()
    return md5s


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
        fasta_path = f"{reference_dir}/{reference['reference_id']}.fa"
        ensure_dir(path_from_root(reference_dir))
        ensure_dir(path_from_root(f"{SMOKE_ROOT}/{reference['reference_id']}/bam"))
        md5s = parse_md5s(fetch_text(f"{reference['source_base_url']}/md5sum.txt"))
        source_urls = []
        md5_values = []
        local_gz_paths = []
        for chromosome in reference["chromosomes"]:
            file_name = f"{chromosome}.fa.gz"
            source_url = f"{reference['source_base_url']}/{file_name}"
            gz_path = f"{reference_dir}/{file_name}"
            source_urls.append(source_url)
            local_gz_paths.append(gz_path)
            expected_md5 = md5s.get(file_name, "")
            md5_values.append(expected_md5)
            if not path_from_root(gz_path).exists():
                run_command(f"curl -fsSL {quote_shell_arg(source_url)} -o {quote_shell_arg(gz_path)}")
            if expected_md5 and md5_file(gz_path) != expected_md5:
                raise RuntimeError(f"{gz_path} md5 mismatch: expected {expected_md5}, observed {md5_file(gz_path)}.")
        if not path_from_root(fasta_path).exists():
            run_command(f"gzip -cd {' '.join(quote_shell_arg(path) for path in local_gz_paths)} > {quote_shell_arg(fasta_path)}")
        if not path_from_root(f"{fasta_path}.fai").exists():
            run_command(f"samtools faidx {quote_shell_arg(fasta_path)}")
        fasta_sha256 = sha256_file(fasta_path)
        reference_rows.append(
            {
                "reference_id": reference["reference_id"],
                "assembly": reference["assembly"],
                "genome_build": reference["genome_build"],
                "source": "UCSC Genome Browser per-chromosome FASTA",
                "source_base_url": reference["source_base_url"],
                "chromosomes": ";".join(reference["chromosomes"]),
                "genes_covered": ";".join(reference["genes_covered"]),
                "source_urls": ";".join(source_urls),
                "source_md5s": ";".join(md5_values),
                "md5_status": "passed" if all(md5_values) else "not_available",
                "fasta_path": fasta_path,
                "fasta_fai_path": f"{fasta_path}.fai",
                "fasta_sha256": fasta_sha256,
                "fasta_size_bytes": path_from_root(fasta_path).stat().st_size,
                "caveat": "Partial human-reference smoke containing chr13 and chr17 only. Validates real-reference alignment mechanics, not whole-genome/full-exome performance.",
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
                    "chromosomes": ";".join(reference["chromosomes"]),
                    "genes_covered": ";".join(reference["genes_covered"]),
                    "reference_path": fasta_path,
                    "reference_sha256": fasta_sha256,
                    "aligner": "bwa mem",
                    "aligner_threads": "2",
                    "read_group_id": f"{run}_{reference['assembly']}",
                    "read_group_sample": sample,
                    "read_group_library": f"{row['assay']}_{row['role']}_{reference['assembly']}",
                    "read_group_platform": "ILLUMINA",
                    "read_group_platform_unit": run,
                    "output_bam": bam,
                    "output_bai": f"{bam}.bai",
                    "source": "Phase 2A local HCC1395 FASTQ subset aligned to partial UCSC human reference",
                    "caveat": "Partial chr13/chr17 human-reference smoke for reference-build and BAM contract validation only; not full-depth WES/WGS, somatic calling, or HRD evidence.",
                }
            )
    write_csv(path_from_root("manifests/human_reference_smoke_references.csv"), reference_rows)
    write_csv(path_from_root("manifests/human_reference_smoke_samplesheet.csv"), samplesheet_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/reference_assets_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "built",
            "referenceCount": len(reference_rows),
            "sampleRows": len(samplesheet_rows),
            "references": reference_rows,
            "boundary": "Phase 2C uses partial UCSC hg38/hg19 chromosome references for local validation. Full-depth Diana or SEQC2 calling still requires full reference bundles, intervals, known-sites resources, and caller configuration.",
        },
    )
    print(f"Built {len(reference_rows)} partial human-reference smoke bundles and {len(samplesheet_rows)} sample rows.")


if __name__ == "__main__":
    main()
