from __future__ import annotations

from ...alignment import align_and_validate, count, ensure_bwa_index, tool_version
from ...paths import path_from_root
from ...utils import (
    capture_command,
    ensure_dir,
    iso_now,
    parse_csv,
    quote_shell_arg,
    read_text,
    run_command,
    sha256_file,
    write_csv,
    write_json,
    write_text,
)

RESULTS_DIR = "results/full_reference_smoke"


def parse_vcf_stats(text: str) -> dict[str, int]:
    rows = [line for line in text.splitlines() if line.startswith("SN")]

    def get(label: str) -> int:
        row = next((line for line in rows if label in line), "")
        return int(row.split("\t")[-1]) if row else 0

    return {"records": get("number of records:"), "snps": get("number of SNPs:"), "indels": get("number of indels:")}


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    rows = parse_csv(read_text(path_from_root("manifests/full_reference_smoke_samplesheet.csv")))
    if len(rows) != 2 or not any(row["role"] == "tumor" for row in rows) or not any(row["role"] == "normal" for row in rows):
        raise RuntimeError("Expected tumor and normal rows in manifests/full_reference_smoke_samplesheet.csv.")
    reference_id = rows[0]["reference_id"]
    reference_path = rows[0]["reference_path"]
    reference_sha256 = sha256_file(reference_path)
    for row in rows:
        if row["reference_path"] != reference_path or row["reference_sha256"] != reference_sha256:
            raise RuntimeError(f"Full-reference samplesheet has inconsistent reference state for {row['run_accession']}.")
    indexed_reference = ensure_bwa_index(reference_path, RESULTS_DIR, reference_id)
    validation_rows = []
    for row in rows:
        validation = align_and_validate(row, RESULTS_DIR, ["chr13", "chr17"])
        idxstats_rows = validation.pop("idxstats_rows")
        interval_alignments = count(f"samtools view -c -L {quote_shell_arg(row['interval_bed_path'])} {quote_shell_arg(row['output_bam'])}")
        chr13_mapped = next((idx["mapped"] for idx in idxstats_rows if idx["contig"] == "chr13"), 0)
        chr17_mapped = next((idx["mapped"] for idx in idxstats_rows if idx["contig"] == "chr17"), 0)
        validation.update(
            {
                "assembly": row["assembly"],
                "genome_build": row["genome_build"],
                "interval_bed_path": row["interval_bed_path"],
                "interval_regions": row["interval_regions"],
                "interval_genes": row["interval_genes"],
                "reference_contig_count": len(validation["reference_contigs"].split(";")) if validation["reference_contigs"] else 0,
                "expected_brca_contigs_present": "yes"
                if {"chr13", "chr17"}.issubset(set(validation["reference_contigs"].split(";")))
                else "no",
                "interval_alignments": interval_alignments,
                "mapped_by_key_contig": f"chr13:{chr13_mapped};chr17:{chr17_mapped}",
                "caller_ready_scope": row["caller_ready_scope"],
            }
        )
        validation_rows.append(validation)
    tumor = next(row for row in rows if row["role"] == "tumor")
    normal = next(row for row in rows if row["role"] == "normal")
    vcf_path = f"data/raw/smoke/seqc2_hcc1395_full_reference_smoke/{reference_id}/vcf/{reference_id}.bcftools_smoke.vcf.gz"
    caller_command = "set -o pipefail; " + " | ".join(
        [
            f"bcftools mpileup -Ou -f {quote_shell_arg(reference_path)} -R {quote_shell_arg(tumor['interval_bed_path'])} {quote_shell_arg(normal['output_bam'])} {quote_shell_arg(tumor['output_bam'])}",
            "bcftools call -mv -Oz",
            f"tee {quote_shell_arg(vcf_path)} >/dev/null",
        ]
    )
    run_command(caller_command, f"{RESULTS_DIR}/logs/{reference_id}.bcftools_call.log")
    run_command(f"bcftools index -t {quote_shell_arg(vcf_path)}", f"{RESULTS_DIR}/logs/{reference_id}.bcftools_index.log")
    run_command(f"bcftools stats {quote_shell_arg(vcf_path)}", f"{RESULTS_DIR}/logs/{reference_id}.bcftools_stats.txt")
    vcf_header = capture_command(f"bcftools view -h {quote_shell_arg(vcf_path)}")
    stats = parse_vcf_stats(read_text(path_from_root(f"{RESULTS_DIR}/logs/{reference_id}.bcftools_stats.txt")))
    sample_line = next((line for line in vcf_header.splitlines() if line.startswith("#CHROM")), "")
    vcf_samples = sample_line.split("\t")[9:]
    caller_status = "passed" if path_from_root(vcf_path).exists() and path_from_root(f"{vcf_path}.tbi").exists() else "failed"
    caller_rows = [
        {
            "reference_id": reference_id,
            "caller": "bcftools mpileup/call",
            "caller_scope": "tiny germline-style variant-caller smoke over BRCA1/BRCA2 intervals using tumor and normal BAM inputs",
            "reference_path": reference_path,
            "interval_bed_path": tumor["interval_bed_path"],
            "input_bams": f"{normal['output_bam']};{tumor['output_bam']}",
            "output_vcf": vcf_path,
            "output_tbi": f"{vcf_path}.tbi",
            "vcf_exists": "yes" if path_from_root(vcf_path).exists() else "no",
            "tbi_exists": "yes" if path_from_root(f"{vcf_path}.tbi").exists() else "no",
            "sample_count": len(vcf_samples),
            "samples": ";".join(vcf_samples),
            "records": stats["records"],
            "snps": stats["snps"],
            "indels": stats["indels"],
            "status": caller_status,
            "caveat": "This is a caller execution and VCF contract smoke only. bcftools call is not a tumor-normal somatic caller and this tiny downsample is not interpreted biologically.",
        }
    ]
    status = "passed" if all(row["status"] == "passed" for row in validation_rows) and caller_status == "passed" else "failed"
    write_csv(path_from_root(f"{RESULTS_DIR}/bam_validation_summary.csv"), validation_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/bam_validation_summary.json"), {"generatedAt": iso_now(), "status": status, "rows": validation_rows}
    )
    write_csv(path_from_root(f"{RESULTS_DIR}/caller_smoke_summary.csv"), caller_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/caller_smoke_summary.json"), {"generatedAt": iso_now(), "status": caller_status, "rows": caller_rows}
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/tool_versions.json"),
        {
            "generatedAt": iso_now(),
            "bwa": {"path": capture_command("command -v bwa"), "version": tool_version("bwa")},
            "samtools": {"path": capture_command("command -v samtools"), "version": tool_version("samtools")},
            "bcftools": {"path": capture_command("command -v bcftools"), "version": tool_version("bcftools")},
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/full_reference_alignment_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": status,
            "referenceId": reference_id,
            "assembly": rows[0]["assembly"],
            "genomeBuild": rows[0]["genome_build"],
            "sampleRows": len(validation_rows),
            "tumorRows": len([row for row in validation_rows if row["role"] == "tumor"]),
            "normalRows": len([row for row in validation_rows if row["role"] == "normal"]),
            "callerSmokeStatus": caller_status,
            "indexedReference": indexed_reference,
            "boundary": "Phase 2D validates one full hg38 analysis-set reference, BRCA interval metadata, caller-ready BAM contracts, and a tiny bcftools VCF smoke. It does not validate full-depth WES/WGS coverage, clinical somatic calling, CNV/SV calling, or HRD signatures.",
        },
    )
    write_csv(
        path_from_root(f"{RESULTS_DIR}/full_reference_alignment_summary.csv"),
        [
            {
                "status": status,
                "reference_id": reference_id,
                "assembly": rows[0]["assembly"],
                "genome_build": rows[0]["genome_build"],
                "sample_rows": len(validation_rows),
                "tumor_rows": len([row for row in validation_rows if row["role"] == "tumor"]),
                "normal_rows": len([row for row in validation_rows if row["role"] == "normal"]),
                "caller_smoke_status": caller_status,
                "boundary": "Full hg38 analysis-set reference smoke with BRCA intervals and bcftools VCF contract check; not full-depth WES/WGS or clinical somatic calling.",
            }
        ],
    )
    write_text(path_from_root(f"{RESULTS_DIR}/README.md"), f"# Full-Reference Caller-Readiness Smoke\n\nStatus: **{status}**.\n")
    if status != "passed":
        raise RuntimeError("Full-reference smoke failed. See results/full_reference_smoke/.")
    print(f"Full-reference smoke {status} for {len(validation_rows)} BAM validations and {len(caller_rows)} caller smoke.")


if __name__ == "__main__":
    main()
