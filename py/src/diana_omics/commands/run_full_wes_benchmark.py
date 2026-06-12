from __future__ import annotations

import gzip
import os
import re
import subprocess
from typing import Any, Optional

from ..paths import path_from_root
from ..utils import (
    bcftools_norm_ref_mismatch_count,
    capture_command,
    ensure_dir,
    iso_now,
    md5_file,
    parse_csv,
    quote_shell_arg,
    read_text,
    round_value,
    run_command,
    write_csv,
    write_json,
    write_text,
)

RESULTS_DIR = "results/full_wes_benchmark"
FORCE = os.environ.get("PHASE2F_FORCE") == "1"
THREADS = int(os.environ.get("PHASE2F_THREADS", "8"))
MIN_TRUTH_DEPTH = int(os.environ.get("PHASE2F_MIN_TRUTH_DEPTH", "10"))
MAX_TRUTH_VARIANTS = int(os.environ.get("PHASE2F_MAX_TRUTH_VARIANTS", "5000"))
INTERVAL_PADDING = int(os.environ.get("PHASE2F_INTERVAL_PADDING", "100"))
# Cap on REF-mismatch records bcftools norm may drop before we treat it as a
# wrong-reference misconfiguration rather than a few benign discordances.
NORM_MAX_REF_MISMATCH = int(os.environ.get("PHASE2F_NORM_MAX_REF_MISMATCH", "1000"))


def file_non_empty(relative_path: str) -> bool:
    path = path_from_root(relative_path)
    return path.exists() and path.stat().st_size > 0


def quickcheck(bam_path: str) -> bool:
    if not path_from_root(bam_path).exists():
        return False
    result = subprocess.run(
        ["samtools", "quickcheck", "-v", str(path_from_root(bam_path))],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0


def read_group(row: dict[str, str]) -> str:
    return "\\t".join(
        [
            "@RG",
            f"ID:{row['read_group_id']}",
            f"SM:{row['read_group_sample']}",
            f"LB:{row['read_group_library']}",
            f"PL:{row['read_group_platform']}",
            f"PU:{row['read_group_platform_unit']}",
        ]
    )


def parse_header(header: str, row: dict[str, str]) -> dict[str, Any]:
    lines = header.splitlines()
    hd = next((line for line in lines if line.startswith("@HD")), "")
    sort_match = re.search(r"\bSO:([^\t]+)", hd)
    rg_lines = [line for line in lines if line.startswith("@RG")]
    sq_lines = [line for line in lines if line.startswith("@SQ")]
    contigs = [match.group(1) for line in sq_lines if (match := re.search(r"\bSN:([^\t]+)", line))]
    read_group_present = any(f"ID:{row['read_group_id']}" in line and f"SM:{row['read_group_sample']}" in line for line in rg_lines)
    return {
        "sortOrder": sort_match.group(1) if sort_match else "",
        "readGroupPresent": read_group_present,
        "readGroupCount": len(rg_lines),
        "contigs": contigs,
    }


def count(command: str) -> int:
    text = capture_command(command)
    return int(text or "0")


def standard_contig(contig: str) -> bool:
    return re.match(r"^chr([1-9]|1[0-9]|2[0-2]|X|Y)$", contig) is not None


def parse_duplicate_metrics(relative_path: str) -> dict[str, str]:
    lines = read_text(path_from_root(relative_path)).splitlines()
    try:
        header_index = next(index for index, line in enumerate(lines) if line.startswith("LIBRARY\t"))
    except StopIteration:
        return {}
    if header_index + 1 >= len(lines):
        return {}
    headers = lines[header_index].split("\t")
    values = lines[header_index + 1].split("\t")
    return {header: values[index] if index < len(values) else "" for index, header in enumerate(headers)}


def parse_depth_summary(depth_text: str) -> dict[str, Any]:
    bases = tumor_depth = normal_depth = both_at_10 = 0
    for line in depth_text.splitlines():
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        tumor = int(fields[2] or "0")
        normal = int(fields[3] or "0")
        bases += 1
        tumor_depth += tumor
        normal_depth += normal
        if tumor >= 10 and normal >= 10:
            both_at_10 += 1
    return {
        "bases": bases,
        "tumorMeanDepth": round_value(tumor_depth / bases if bases else None, 2),
        "normalMeanDepth": round_value(normal_depth / bases if bases else None, 2),
        "basesBothDepthAtLeast10": both_at_10,
        "fractionBothDepthAtLeast10": round_value(both_at_10 / bases if bases else None, 4),
    }


def load_truth_variants(vcf_path: str, variant_type: str) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    with gzip.open(path_from_root(vcf_path), "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            contig, position_text, _id, ref, alt_text, *_rest = line.rstrip("\n").split("\t")
            position = int(position_text)
            if not standard_contig(contig):
                continue
            for alt in alt_text.split(","):
                variants.append(
                    {
                        "key": f"{contig}:{position}:{ref}:{alt}",
                        "type": variant_type,
                        "contig": contig,
                        "position": position,
                        "ref": ref,
                        "alt": alt,
                    }
                )
    return variants


def normalize_vcf_for_comparison(vcf_path: str, reference_path: str, output_path: str, log_path: str) -> str:
    if FORCE or not file_non_empty(output_path):
        ensure_dir(path_from_root("/".join(output_path.split("/")[:-1])))
        # --check-ref x excludes records whose REF allele does not match the
        # reference instead of aborting the whole benchmark on the first one
        # (bcftools defaults to --check-ref e, which exits 255). A handful of
        # discordant sites outside the compared region are tolerated; a flood
        # means the wrong reference, so we fail closed below.
        run_command(
            f"bcftools norm -m -both --check-ref x -f {quote_shell_arg(reference_path)} -Oz -o {quote_shell_arg(output_path)} {quote_shell_arg(vcf_path)}",
            log_path,
        )
        run_command(f"bcftools index -t -f {quote_shell_arg(output_path)}", f"{log_path}.index")
        mismatches = bcftools_norm_ref_mismatch_count(read_text(path_from_root(log_path)))
        if mismatches:
            print(f"[norm] {output_path}: bcftools norm excluded {mismatches} REF-mismatch record(s) vs {reference_path}", flush=True)
        if mismatches > NORM_MAX_REF_MISMATCH:
            raise RuntimeError(
                f"bcftools norm excluded {mismatches} REF-mismatch records from {vcf_path} "
                f"(cap {NORM_MAX_REF_MISMATCH}); reference {reference_path} likely does not match this VCF build."
            )
    return output_path


def write_truth_position_bed(variants: list[dict[str, Any]], output_path: str) -> None:
    ensure_dir(path_from_root("/".join(output_path.split("/")[:-1])))
    write_text(
        path_from_root(output_path),
        "\n".join(f"{variant['contig']}\t{int(variant['position']) - 1}\t{variant['position']}\t{variant['key']}" for variant in variants),
    )


def read_reference_order(fai_path: str) -> dict[str, int]:
    order: dict[str, int] = {}
    for index, line in enumerate(read_text(path_from_root(fai_path)).splitlines()):
        if line:
            order[line.split("\t")[0]] = index
    return order


def pick_covered_truth_variants(variants: list[dict[str, Any]], depth_text: str) -> list[dict[str, Any]]:
    by_position: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        by_position.setdefault(f"{variant['contig']}:{variant['position']}", []).append(variant)
    unique: dict[str, dict[str, Any]] = {}
    for line in depth_text.splitlines():
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        contig, position_text, tumor_text, normal_text = fields[:4]
        position = int(position_text)
        tumor_depth = int(tumor_text or "0")
        normal_depth = int(normal_text or "0")
        if tumor_depth < MIN_TRUTH_DEPTH or normal_depth < MIN_TRUTH_DEPTH:
            continue
        for variant in by_position.get(f"{contig}:{position}", []):
            enriched = dict(variant)
            enriched["tumorDepth"] = tumor_depth
            enriched["normalDepth"] = normal_depth
            enriched["minDepth"] = min(tumor_depth, normal_depth)
            unique[enriched["key"]] = enriched
    return sorted(unique.values(), key=lambda row: (-int(row["minDepth"]), str(row["contig"]), int(row["position"])))[:MAX_TRUTH_VARIANTS]


def write_benchmark_intervals(variants: list[dict[str, Any]], reference_order: dict[str, int], output_path: str) -> list[dict[str, Any]]:
    intervals = sorted(
        [
            {
                "contig": variant["contig"],
                "start": max(0, int(variant["position"]) - 1 - INTERVAL_PADDING),
                "end": int(variant["position"]) + INTERVAL_PADDING,
            }
            for variant in variants
        ],
        key=lambda row: (reference_order.get(str(row["contig"]), 9999), int(row["start"]), int(row["end"])),
    )
    merged: list[dict[str, Any]] = []
    for interval in intervals:
        last = merged[-1] if merged else None
        if not last or last["contig"] != interval["contig"] or int(interval["start"]) > int(last["end"]) + 50:
            merged.append(dict(interval))
        else:
            last["end"] = max(int(last["end"]), int(interval["end"]))
    ensure_dir(path_from_root("/".join(output_path.split("/")[:-1])))
    write_text(path_from_root(output_path), "\n".join(f"{row['contig']}\t{row['start']}\t{row['end']}" for row in merged))
    return merged


def variant_keys(vcf_path: str, region_bed_path: Optional[str] = None) -> dict[str, Any]:
    region_part = f"-R {quote_shell_arg(region_bed_path)}" if region_bed_path else ""
    rows = capture_command(f"bcftools view {region_part} -H {quote_shell_arg(vcf_path)}")
    keys: set[str] = set()
    pass_keys: set[str] = set()
    snv_count = indel_count = pass_count = 0
    for line in rows.splitlines():
        contig, position, _id, ref, alt_text, _qual, filter_value, *_rest = line.split("\t")
        for alt in alt_text.split(","):
            key = f"{contig}:{position}:{ref}:{alt}"
            keys.add(key)
            if len(ref) == 1 and len(alt) == 1:
                snv_count += 1
            else:
                indel_count += 1
            if filter_value == "PASS":
                pass_keys.add(key)
                pass_count += 1
    return {
        "keys": keys,
        "passKeys": pass_keys,
        "totalCount": len(keys),
        "passCount": pass_count,
        "snvCount": snv_count,
        "indelCount": indel_count,
    }


def parse_contamination_table(relative_path: str) -> dict[str, str]:
    if not file_non_empty(relative_path):
        return {"contamination": "", "error": ""}
    rows = [line for line in read_text(path_from_root(relative_path)).splitlines() if line and not line.startswith("#")]
    header_index = next((index for index, line in enumerate(rows) if "contamination" in line.split("\t")), -1)
    if header_index == -1 or header_index + 1 >= len(rows):
        return {"contamination": "", "error": ""}
    headers = rows[header_index].split("\t")
    values = rows[header_index + 1].split("\t")
    contamination_index = headers.index("contamination") if "contamination" in headers else -1
    error_index = headers.index("error") if "error" in headers else -1
    return {
        "contamination": values[contamination_index] if contamination_index >= 0 and contamination_index < len(values) else "",
        "error": values[error_index] if error_index >= 0 and error_index < len(values) else "",
    }


def tool_version(tool: str) -> str:
    result = subprocess.run(
        ["bash", "-lc", f"{tool} 2>&1 | head -n 8"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return f"{result.stdout}{result.stderr}".strip()


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    rows = parse_csv(read_text(path_from_root("manifests/full_wes_benchmark_samplesheet.csv")))
    if len(rows) != 2 or not any(row["role"] == "tumor" for row in rows) or not any(row["role"] == "normal" for row in rows):
        raise RuntimeError("Expected tumor and normal rows in manifests/full_wes_benchmark_samplesheet.csv.")
    tumor = next(row for row in rows if row["role"] == "tumor")
    normal = next(row for row in rows if row["role"] == "normal")
    reference_id = tumor["reference_id"]
    output_root = f"data/raw/full_wes_benchmark/seqc2_hcc1395_wes_minimal/{reference_id}"
    interval_dir = f"{output_root}/intervals"
    metrics_dir = f"{output_root}/metrics"
    vcf_dir = f"{output_root}/vcf"
    truth_position_bed = f"{interval_dir}/seqc2_truth_positions.bed"
    benchmark_intervals = f"{interval_dir}/covered_truth_benchmark_intervals.bed"
    contamination_intervals = tumor["brca_interval_bed_path"]
    covered_truth_tsv = f"{interval_dir}/covered_truth_variants.tsv"
    unfiltered_vcf = f"{vcf_dir}/hcc1395.full_wes.resource_aware.mutect2.unfiltered.vcf.gz"
    filtered_vcf = f"{vcf_dir}/hcc1395.full_wes.resource_aware.mutect2.filtered.vcf.gz"
    f1r2_path = f"{vcf_dir}/hcc1395.full_wes.resource_aware.mutect2.f1r2.tar.gz"
    tumor_pileups = f"{metrics_dir}/{tumor['run_accession']}.tumor.getpileupsummaries.table"
    normal_pileups = f"{metrics_dir}/{normal['run_accession']}.normal.getpileupsummaries.table"
    contamination_table = f"{metrics_dir}/hcc1395.calculate_contamination.table"

    fastq_rows: list[dict[str, Any]] = []
    for row in rows:
        for read in ("1", "2"):
            path = row[f"fastq_{read}"]
            expected_md5 = row[f"fastq_{read}_md5"]
            expected_bytes = int(row[f"fastq_{read}_bytes"])
            actual_md5 = md5_file(path)
            actual_bytes = path_from_root(path).stat().st_size
            if actual_md5 != expected_md5 or actual_bytes != expected_bytes:
                raise RuntimeError(f"{path} failed md5/byte validation.")
            fastq_rows.append(
                {
                    "pair_id": row["pair_id"],
                    "sample": row["sample"],
                    "role": row["role"],
                    "run_accession": row["run_accession"],
                    "read": read,
                    "fastq_path": path,
                    "expected_md5": expected_md5,
                    "actual_md5": actual_md5,
                    "expected_bytes": expected_bytes,
                    "actual_bytes": actual_bytes,
                    "source_read_pairs": row["source_read_pairs"],
                    "status": "passed",
                }
            )
    write_csv(path_from_root(f"{RESULTS_DIR}/full_wes_fastq_validation.csv"), fastq_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/full_wes_fastq_validation.json"), {"generatedAt": iso_now(), "status": "passed", "rows": fastq_rows}
    )

    for row in rows:
        ensure_dir(path_from_root("/".join(row["raw_bam"].split("/")[:-1])))
        ensure_dir(path_from_root("/".join(row["duplicate_metrics_path"].split("/")[:-1])))
        if FORCE or not quickcheck(row["raw_bam"]):
            align_command = (
                "set -o pipefail; "
                f"bwa mem -t {THREADS} -R {quote_shell_arg(read_group(row))} {quote_shell_arg(row['reference_path'])} "
                f"{quote_shell_arg(row['fastq_1'])} {quote_shell_arg(row['fastq_2'])} | "
                f"samtools sort -@ {THREADS} -o {quote_shell_arg(row['raw_bam'])} -"
            )
            run_command(align_command, f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.full_wes_align.log")
        should_mark_duplicates = FORCE or not quickcheck(row["dedup_bam"]) or not path_from_root(row["duplicate_metrics_path"]).exists()
        if should_mark_duplicates:
            run_command(
                " ".join(
                    [
                        f"{quote_shell_arg(row['java_path'])} -Xmx12g -jar {quote_shell_arg(row['gatk_jar_path'])} MarkDuplicates",
                        f"-I {quote_shell_arg(row['raw_bam'])}",
                        f"-O {quote_shell_arg(row['dedup_bam'])}",
                        f"-M {quote_shell_arg(row['duplicate_metrics_path'])}",
                        "--VALIDATION_STRINGENCY SILENT",
                    ]
                ),
                f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.mark_duplicates.log",
            )
            run_command(
                f"samtools index -@ {THREADS} -o {quote_shell_arg(row['dedup_bai'])} {quote_shell_arg(row['dedup_bam'])}",
                f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.dedup_index.log",
            )
        elif not path_from_root(row["dedup_bai"]).exists():
            run_command(
                f"samtools index -@ {THREADS} -o {quote_shell_arg(row['dedup_bai'])} {quote_shell_arg(row['dedup_bam'])}",
                f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.dedup_index.log",
            )
        run_command(
            f"samtools flagstat {quote_shell_arg(row['dedup_bam'])}",
            f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.dedup_flagstat.txt",
        )
        run_command(
            f"samtools stats {quote_shell_arg(row['dedup_bam'])}",
            f"{RESULTS_DIR}/logs/{reference_id}.{row['run_accession']}.dedup_stats.txt",
        )

    bam_rows: list[dict[str, Any]] = []
    for row in rows:
        header_state = parse_header(capture_command(f"samtools view -H {quote_shell_arg(row['dedup_bam'])}"), row)
        total_alignments = count(f"samtools view -c {quote_shell_arg(row['dedup_bam'])}")
        mapped_alignments = count(f"samtools view -c -F 4 {quote_shell_arg(row['dedup_bam'])}")
        properly_paired_alignments = count(f"samtools view -c -f 2 {quote_shell_arg(row['dedup_bam'])}")
        duplicate_alignments = count(f"samtools view -c -f 1024 {quote_shell_arg(row['dedup_bam'])}")
        brca_interval_alignments = count(
            f"samtools view -c -L {quote_shell_arg(row['brca_interval_bed_path'])} {quote_shell_arg(row['dedup_bam'])}"
        )
        duplicate_metrics = parse_duplicate_metrics(row["duplicate_metrics_path"])
        status = (
            "passed"
            if quickcheck(row["dedup_bam"])
            and path_from_root(row["dedup_bai"]).exists()
            and header_state["sortOrder"] == "coordinate"
            and header_state["readGroupPresent"]
            and mapped_alignments > 0
            and brca_interval_alignments > 0
            else "failed"
        )
        bam_rows.append(
            {
                "pair_id": row["pair_id"],
                "reference_id": row["reference_id"],
                "assembly": row["assembly"],
                "genome_build": row["genome_build"],
                "role": row["role"],
                "run_accession": row["run_accession"],
                "sample": row["sample"],
                "source_read_pairs": row["source_read_pairs"],
                "raw_bam": row["raw_bam"],
                "dedup_bam": row["dedup_bam"],
                "dedup_bai": row["dedup_bai"],
                "dedup_bam_exists": "yes" if path_from_root(row["dedup_bam"]).exists() else "no",
                "dedup_bai_exists": "yes" if path_from_root(row["dedup_bai"]).exists() else "no",
                "quickcheck": "passed" if quickcheck(row["dedup_bam"]) else "failed",
                "sort_order": header_state["sortOrder"],
                "read_group_present": "yes" if header_state["readGroupPresent"] else "no",
                "read_group_count": header_state["readGroupCount"],
                "reference_contig_count": len(header_state["contigs"]),
                "total_alignments": total_alignments,
                "mapped_alignments": mapped_alignments,
                "mapped_fraction": round_value(mapped_alignments / total_alignments if total_alignments else None, 4),
                "properly_paired_alignments": properly_paired_alignments,
                "properly_paired_fraction": round_value(properly_paired_alignments / total_alignments if total_alignments else None, 4),
                "duplicate_alignments": duplicate_alignments,
                "duplicate_fraction": round_value(duplicate_alignments / total_alignments if total_alignments else None, 4),
                "picard_percent_duplication": duplicate_metrics.get("PERCENT_DUPLICATION", ""),
                "brca_interval_alignments": brca_interval_alignments,
                "bam_size_bytes": path_from_root(row["dedup_bam"]).stat().st_size,
                "duplicate_metrics_path": row["duplicate_metrics_path"],
                "status": status,
                "caveat": row["caveat"],
            }
        )
    bam_status = "passed" if all(row["status"] == "passed" for row in bam_rows) else "failed"
    write_csv(path_from_root(f"{RESULTS_DIR}/full_wes_bam_validation.csv"), bam_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/full_wes_bam_validation.json"), {"generatedAt": iso_now(), "status": bam_status, "rows": bam_rows}
    )
    if bam_status != "passed":
        raise RuntimeError("Full WES BAM validation failed.")

    brca_depth = capture_command(
        f"samtools depth -a -b {quote_shell_arg(tumor['brca_interval_bed_path'])} {quote_shell_arg(tumor['dedup_bam'])} {quote_shell_arg(normal['dedup_bam'])}"
    )
    brca_depth_summary = parse_depth_summary(brca_depth)
    truth_snv_path = "data/raw/reference/seqc2_hcc1395_truth/latest/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz"
    truth_indel_path = "data/raw/reference/seqc2_hcc1395_truth/latest/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz"
    normalized_truth_snv_path = normalize_vcf_for_comparison(
        truth_snv_path,
        tumor["reference_path"],
        f"{vcf_dir}/seqc2.high_confidence_sSNV.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.truth_snv.norm.log",
    )
    normalized_truth_indel_path = normalize_vcf_for_comparison(
        truth_indel_path,
        tumor["reference_path"],
        f"{vcf_dir}/seqc2.high_confidence_sINDEL.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.truth_indel.norm.log",
    )
    truth_variants = load_truth_variants(normalized_truth_snv_path, "snv") + load_truth_variants(normalized_truth_indel_path, "indel")
    all_truth_keys = {str(variant["key"]) for variant in truth_variants}
    write_truth_position_bed(truth_variants, truth_position_bed)
    truth_depth_text = capture_command(
        f"samtools depth -a -b {quote_shell_arg(truth_position_bed)} {quote_shell_arg(tumor['dedup_bam'])} {quote_shell_arg(normal['dedup_bam'])}"
    )
    covered_truth_variants = pick_covered_truth_variants(truth_variants, truth_depth_text)
    if not covered_truth_variants:
        raise RuntimeError("No covered truth variants passed the Phase 2F depth threshold.")
    benchmark_interval_rows = write_benchmark_intervals(
        covered_truth_variants, read_reference_order(tumor["reference_fai_path"]), benchmark_intervals
    )
    write_csv(
        path_from_root(covered_truth_tsv.replace(".tsv", ".csv")),
        [
            {
                "key": variant["key"],
                "type": variant["type"],
                "contig": variant["contig"],
                "position": variant["position"],
                "ref": variant["ref"],
                "alt": variant["alt"],
                "tumor_depth": variant["tumorDepth"],
                "normal_depth": variant["normalDepth"],
                "min_depth": variant["minDepth"],
            }
            for variant in covered_truth_variants
        ],
    )
    write_text(
        path_from_root(covered_truth_tsv),
        "\n".join(
            ["key\ttype\tcontig\tposition\tref\talt\ttumor_depth\tnormal_depth\tmin_depth"]
            + [
                f"{variant['key']}\t{variant['type']}\t{variant['contig']}\t{variant['position']}\t{variant['ref']}\t{variant['alt']}\t{variant['tumorDepth']}\t{variant['normalDepth']}\t{variant['minDepth']}"
                for variant in covered_truth_variants
            ]
        ),
    )

    ensure_dir(path_from_root(metrics_dir))
    contamination_inputs_ready = (
        file_non_empty(tumor["common_biallelic_resource_path"])
        and file_non_empty(tumor["common_biallelic_resource_index_path"])
        and file_non_empty(contamination_intervals)
    )
    contamination_status = "not_run"
    contamination_reason = ""
    if contamination_inputs_ready:
        try:
            if FORCE or not file_non_empty(tumor_pileups):
                run_command(
                    f"{quote_shell_arg(tumor['java_path'])} -Xmx8g -jar {quote_shell_arg(tumor['gatk_jar_path'])} GetPileupSummaries -R {quote_shell_arg(tumor['reference_path'])} -I {quote_shell_arg(tumor['dedup_bam'])} -V {quote_shell_arg(tumor['common_biallelic_resource_path'])} -L {quote_shell_arg(contamination_intervals)} -O {quote_shell_arg(tumor_pileups)}",
                    f"{RESULTS_DIR}/logs/{reference_id}.{tumor['run_accession']}.tumor.get_pileup_summaries.log",
                )
            if FORCE or not file_non_empty(normal_pileups):
                run_command(
                    f"{quote_shell_arg(normal['java_path'])} -Xmx8g -jar {quote_shell_arg(normal['gatk_jar_path'])} GetPileupSummaries -R {quote_shell_arg(normal['reference_path'])} -I {quote_shell_arg(normal['dedup_bam'])} -V {quote_shell_arg(normal['common_biallelic_resource_path'])} -L {quote_shell_arg(contamination_intervals)} -O {quote_shell_arg(normal_pileups)}",
                    f"{RESULTS_DIR}/logs/{reference_id}.{normal['run_accession']}.normal.get_pileup_summaries.log",
                )
            if FORCE or not file_non_empty(contamination_table):
                run_command(
                    f"{quote_shell_arg(tumor['java_path'])} -Xmx8g -jar {quote_shell_arg(tumor['gatk_jar_path'])} CalculateContamination -I {quote_shell_arg(tumor_pileups)} -matched {quote_shell_arg(normal_pileups)} -O {quote_shell_arg(contamination_table)}",
                    f"{RESULTS_DIR}/logs/{reference_id}.calculate_contamination.log",
                )
            contamination_status = "passed" if file_non_empty(contamination_table) else "failed"
        except RuntimeError as error:
            contamination_status = "not_assessable"
            contamination_reason = str(error)
    else:
        contamination_status = "not_assessable"
        contamination_reason = "Common-biallelic resource, index, or contamination intervals were unavailable."
    contamination_estimate = parse_contamination_table(contamination_table)

    ensure_dir(path_from_root(vcf_dir))
    mutect2_ready = not FORCE and path_from_root(filtered_vcf).exists() and path_from_root(f"{filtered_vcf}.tbi").exists()
    if not mutect2_ready:
        run_command(
            " ".join(
                [
                    f"{quote_shell_arg(tumor['java_path'])} -Xmx12g -jar {quote_shell_arg(tumor['gatk_jar_path'])} Mutect2",
                    f"-R {quote_shell_arg(tumor['reference_path'])}",
                    f"-L {quote_shell_arg(benchmark_intervals)}",
                    f"-I {quote_shell_arg(tumor['dedup_bam'])} -tumor {quote_shell_arg(tumor['sample'])}",
                    f"-I {quote_shell_arg(normal['dedup_bam'])} -normal {quote_shell_arg(normal['sample'])}",
                    f"--panel-of-normals {quote_shell_arg(tumor['mutect2_panel_of_normals_path'])}",
                    f"--native-pair-hmm-threads {max(1, min(THREADS, 8))}",
                    f"--f1r2-tar-gz {quote_shell_arg(f1r2_path)}",
                    f"-O {quote_shell_arg(unfiltered_vcf)}",
                ]
            ),
            f"{RESULTS_DIR}/logs/{reference_id}.full_wes.resource_aware.mutect2.log",
        )
        contamination_arg = f"--contamination-table {quote_shell_arg(contamination_table)}" if contamination_status == "passed" else ""
        run_command(
            f"{quote_shell_arg(tumor['java_path'])} -Xmx8g -jar {quote_shell_arg(tumor['gatk_jar_path'])} FilterMutectCalls -R {quote_shell_arg(tumor['reference_path'])} -V {quote_shell_arg(unfiltered_vcf)} {contamination_arg} -O {quote_shell_arg(filtered_vcf)}",
            f"{RESULTS_DIR}/logs/{reference_id}.full_wes.resource_aware.filter_mutect_calls.log",
        )
        run_command(
            f"bcftools index -t -f {quote_shell_arg(filtered_vcf)}", f"{RESULTS_DIR}/logs/{reference_id}.full_wes.filtered_vcf_index.log"
        )
    run_command(f"bcftools stats {quote_shell_arg(filtered_vcf)}", f"{RESULTS_DIR}/logs/{reference_id}.full_wes.filtered_vcf_stats.txt")
    normalized_filtered_vcf = normalize_vcf_for_comparison(
        filtered_vcf,
        tumor["reference_path"],
        f"{vcf_dir}/hcc1395.full_wes.mutect2.filtered.normalized.vcf.gz",
        f"{RESULTS_DIR}/logs/{reference_id}.full_wes.filtered_vcf.norm.log",
    )

    filtered_calls = variant_keys(normalized_filtered_vcf, benchmark_intervals)
    truth_keys = {str(variant["key"]) for variant in covered_truth_variants}
    pass_truth_matches = [key for key in filtered_calls["passKeys"] if key in truth_keys]
    all_truth_matches = [key for key in filtered_calls["keys"] if key in truth_keys]
    truth_outside_recall_matches = [key for key in filtered_calls["passKeys"] if key in all_truth_keys and key not in truth_keys]
    false_positive_pass = [key for key in filtered_calls["passKeys"] if key not in all_truth_keys]
    false_negative_truth = [key for key in truth_keys if key not in filtered_calls["passKeys"]]
    truth_snv_count = len([variant for variant in covered_truth_variants if variant["type"] == "snv"])
    truth_indel_count = len([variant for variant in covered_truth_variants if variant["type"] == "indel"])
    recall = len(pass_truth_matches) / len(truth_keys) if truth_keys else None
    precision_denominator = len(pass_truth_matches) + len(false_positive_pass)
    precision = len(pass_truth_matches) / precision_denominator if precision_denominator else None
    mutect_status = "passed" if path_from_root(filtered_vcf).exists() and path_from_root(f"{filtered_vcf}.tbi").exists() else "failed"
    ready_for_phase3 = (
        mutect_status == "passed"
        and bam_status == "passed"
        and len(fastq_rows) == 4
        and contamination_status == "passed"
        and bool(covered_truth_variants)
    )

    benchmark_rows = [
        {
            "status": mutect_status,
            "phase": "2F",
            "caller": tumor["production_caller"],
            "reference_id": reference_id,
            "pair_id": tumor["pair_id"],
            "tumor_sample": tumor["sample"],
            "normal_sample": normal["sample"],
            "tumor_run": tumor["run_accession"],
            "normal_run": normal["run_accession"],
            "source_tumor_read_pairs": tumor["source_read_pairs"],
            "source_normal_read_pairs": normal["source_read_pairs"],
            "duplicate_marking_tool": tumor["duplicate_marking_tool"],
            "germline_resource": tumor["mutect2_germline_resource_path"],
            "germline_resource_source_url": tumor["mutect2_germline_resource_source_url"],
            "panel_of_normals": tumor["mutect2_panel_of_normals_path"],
            "common_biallelic_resource": tumor["common_biallelic_resource_path"],
            "bqsr_known_sites_policy": tumor["bqsr_known_sites_policy"],
            "contamination_policy": tumor["contamination_policy"],
            "contamination_status": contamination_status,
            "contamination_table": contamination_table if contamination_status == "passed" else "",
            "contamination_interval_bed_path": contamination_intervals,
            "contamination_estimate": contamination_estimate["contamination"],
            "contamination_error": contamination_estimate["error"],
            "contamination_reason": contamination_reason,
            "benchmark_interval_bed_path": benchmark_intervals,
            "benchmark_interval_count": len(benchmark_interval_rows),
            "truth_variants_total": len(truth_variants),
            "truth_variants_depth_eligible": len(covered_truth_variants),
            "truth_snv_depth_eligible": truth_snv_count,
            "truth_indel_depth_eligible": truth_indel_count,
            "min_truth_depth": MIN_TRUTH_DEPTH,
            "max_truth_variants": MAX_TRUTH_VARIANTS,
            "filtered_vcf": filtered_vcf,
            "normalized_filtered_vcf": normalized_filtered_vcf,
            "filtered_records_in_benchmark_intervals": filtered_calls["totalCount"],
            "pass_records_in_benchmark_intervals": filtered_calls["passCount"],
            "exact_pass_truth_matches": len(pass_truth_matches),
            "exact_all_filter_truth_matches": len(all_truth_matches),
            "pass_truth_matches_outside_recall_subset": len(truth_outside_recall_matches),
            "false_positive_pass_records": len(false_positive_pass),
            "false_negative_truth_records": len(false_negative_truth),
            "exact_pass_recall": round_value(recall, 4),
            "exact_pass_precision": round_value(precision, 4),
            "brca_tumor_mean_depth": brca_depth_summary["tumorMeanDepth"],
            "brca_normal_mean_depth": brca_depth_summary["normalMeanDepth"],
            "brca_fraction_both_depth_at_least_10": brca_depth_summary["fractionBothDepthAtLeast10"],
            "boundary": "Full WES FASTQs and resource-aware Mutect2 were run on covered SEQC2 truth-overlap intervals. This is full-depth WES small-variant benchmark evidence, not WGS HRD signature, CNV, or SV evidence.",
        }
    ]
    write_csv(path_from_root(f"{RESULTS_DIR}/truth_overlap_benchmark_summary.csv"), benchmark_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/truth_overlap_benchmark_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": mutect_status,
            "rows": benchmark_rows,
            "truthMatchExamples": pass_truth_matches[:20],
            "falsePositiveExamples": false_positive_pass[:20],
            "falseNegativeExamples": false_negative_truth[:20],
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/tool_versions.json"),
        {
            "generatedAt": iso_now(),
            "bwa": {"path": capture_command("command -v bwa"), "version": tool_version("bwa")},
            "samtools": {"path": capture_command("command -v samtools"), "version": tool_version("samtools")},
            "bcftools": {"path": capture_command("command -v bcftools"), "version": tool_version("bcftools")},
            "java": {
                "path": tumor["java_path"],
                "version": capture_command(f"{quote_shell_arg(tumor['java_path'])} -version 2>&1 | head -n 1"),
            },
            "gatk": {
                "jarPath": tumor["gatk_jar_path"],
                "version": capture_command(
                    f"{quote_shell_arg(tumor['java_path'])} -jar {quote_shell_arg(tumor['gatk_jar_path'])} --version 2>&1 | head -n 1"
                ),
            },
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/full_wes_benchmark_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": mutect_status,
            "phase": "2F",
            "caller": tumor["production_caller"],
            "referenceId": reference_id,
            "pairId": tumor["pair_id"],
            "tumorRun": tumor["run_accession"],
            "normalRun": normal["run_accession"],
            "fullWesFastqsValidated": len(fastq_rows),
            "bamValidationStatus": bam_status,
            "benchmarkIntervalCount": len(benchmark_interval_rows),
            "truthVariantsDepthEligible": len(covered_truth_variants),
            "passRecordsInBenchmarkIntervals": filtered_calls["passCount"],
            "exactPassTruthMatches": len(pass_truth_matches),
            "passTruthMatchesOutsideRecallSubset": len(truth_outside_recall_matches),
            "exactPassRecall": round_value(recall, 4),
            "exactPassPrecision": round_value(precision, 4),
            "contaminationStatus": contamination_status,
            "contaminationTable": contamination_table if contamination_status == "passed" else "",
            "contaminationIntervalBedPath": contamination_intervals,
            "contaminationEstimate": contamination_estimate["contamination"],
            "bqsrKnownSitesPolicy": tumor["bqsr_known_sites_policy"],
            "contaminationPolicy": tumor["contamination_policy"],
            "readyForPhase3": ready_for_phase3 and "not WGS HRD signature" in benchmark_rows[0]["boundary"],
            "boundary": "Phase 2F closes raw WES readiness with full FASTQ download, full-reference alignment, duplicate marking, resource-aware Mutect2, and bounded SEQC2 truth comparison. Phase 3 starts WGS HRD signature/CNV/SV capability.",
        },
    )
    write_csv(
        path_from_root(f"{RESULTS_DIR}/full_wes_benchmark_summary.csv"),
        [
            {
                "status": mutect_status,
                "phase": "2F",
                "caller": tumor["production_caller"],
                "reference_id": reference_id,
                "full_wes_fastqs_validated": len(fastq_rows),
                "bam_validation_status": bam_status,
                "benchmark_interval_count": len(benchmark_interval_rows),
                "truth_variants_depth_eligible": len(covered_truth_variants),
                "pass_records_in_benchmark_intervals": filtered_calls["passCount"],
                "exact_pass_truth_matches": len(pass_truth_matches),
                "exact_pass_recall": round_value(recall, 4),
                "exact_pass_precision": round_value(precision, 4),
                "contamination_status": contamination_status,
                "contamination_table": contamination_table if contamination_status == "passed" else "",
                "contamination_interval_bed_path": contamination_intervals,
                "contamination_estimate": contamination_estimate["contamination"],
                "ready_for_phase3": "yes" if ready_for_phase3 else "no",
                "boundary": "Full-depth WES small-variant benchmark complete; WGS HRD signature/CNV/SV evidence remains Phase 3.",
            }
        ],
    )
    write_text(
        path_from_root(f"{RESULTS_DIR}/README.md"),
        f"""# Full WES Benchmark

Status: **{mutect_status}**.

Phase 2F caller path: `{tumor["production_caller"]}`

Reference: `{reference_id}` ({tumor["genome_build"]}/{tumor["assembly"]})

Input: full ENA FASTQ gzip files for SEQC2/HCC1395 WES tumor-normal pair.

Benchmark interval count: `{len(benchmark_interval_rows)}`

Depth-eligible truth variants: `{len(covered_truth_variants)}`

PASS truth matches: `{len(pass_truth_matches)}`

Exact PASS recall: `{round_value(recall, 4)}`

Exact PASS precision: `{round_value(precision, 4)}`

Contamination status: `{contamination_status}`

Contamination estimate: `{contamination_estimate["contamination"] or "not_available"}`

Boundary: this closes Phase 2 raw WES readiness; Phase 3 is WGS HRD signature, CNV, and SV capability.
""",
    )
    if not ready_for_phase3:
        raise RuntimeError("Full WES benchmark failed the Phase 2F ready-for-Phase-3 gate.")
    print(
        f"Full WES benchmark {mutect_status}: {len(covered_truth_variants)} depth-eligible truth variants, {len(pass_truth_matches)} exact PASS truth matches."
    )


if __name__ == "__main__":
    main()
