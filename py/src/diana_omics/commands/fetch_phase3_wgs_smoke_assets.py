from __future__ import annotations

import gzip
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ..paths import path_from_root
from ..utils import (
    command_path,
    ensure_dir,
    iso_now,
    parse_csv,
    read_text,
    round_value,
    validate_fastq_record,
    write_csv,
    write_json,
    write_text,
)

PAIR_ID = os.environ.get("PHASE3_WGS_PAIR_ID", "seqc2_hcc1395_wgs_hiseqx_full")
READ_PAIRS_PER_END = int(os.environ.get("PHASE3_WGS_READS", "500000"))
FETCH_CONCURRENCY = max(1, int(os.environ.get("PHASE3_WGS_FETCH_CONCURRENCY", "2")))
RESULTS_DIR = "results/phase3_wgs_smoke"
SMOKE_ROOT = "data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full"
SEQC2_TRUTH_ROOT = "data/raw/reference/seqc2_hcc1395_truth/latest"


def reference_dict_path(fasta_path: str) -> str:
    for suffix in (".fasta", ".fa"):
        if fasta_path.lower().endswith(suffix):
            return f"{fasta_path[: -len(suffix)]}.dict"
    return f"{fasta_path}.dict"


def java_works(candidate: str) -> bool:
    if not candidate or not Path(candidate).exists():
        return False
    import subprocess

    result = subprocess.run([candidate, "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    output = f"{result.stdout}{result.stderr}"
    import re

    match = re.search(r'version "(\d+)', output)
    return result.returncode == 0 and int(match.group(1) if match else "0") >= 17


def find_java(fallback: str = "") -> str:
    candidates = [
        os.environ.get("GATK_JAVA", ""),
        fallback,
        "/opt/homebrew/opt/openjdk@17/bin/java",
        "/opt/homebrew/bin/java",
        command_path("java"),
    ]
    for candidate in candidates:
        if java_works(candidate):
            return candidate
    raise RuntimeError("Phase 3 WGS smoke requires Java 17+ for GATK. Install openjdk@17 or set GATK_JAVA.")


def summarize_fastq(run: str, read: str, source_url: str, output_path: Path, source: str) -> dict[str, Any]:
    current: list[str] = []
    ids: list[str] = []
    records = total_length = gc = n = bases = 0
    min_length = 10**9
    max_length = 0
    q_min = 10**9
    q_max = 0
    first_read_id = ""
    last_read_id = ""

    with output_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            current.append(raw_line.rstrip("\n"))
            if len(current) != 4:
                continue
            records += 1
            record = validate_fastq_record(current, f"{run} {read}", records)
            first_read_id = first_read_id or record["id"]
            last_read_id = record["id"]
            ids.append(record["id"])
            sequence = record["sequence"].upper()
            quality = record["quality"]
            length = len(sequence)
            total_length += length
            min_length = min(min_length, length)
            max_length = max(max_length, length)
            gc += sequence.count("G") + sequence.count("C")
            n += sequence.count("N")
            bases += length
            for char in quality:
                code = ord(char)
                q_min = min(q_min, code)
                q_max = max(q_max, code)
            current = []

    if current:
        raise RuntimeError(f"{run} {read} ended mid-record")
    if records != READ_PAIRS_PER_END:
        raise RuntimeError(f"{run} {read} has {records} records; expected {READ_PAIRS_PER_END}")

    return {
        "run": run,
        "read": read,
        "sourceUrl": source_url,
        "outputPath": str(output_path),
        "records": records,
        "minLength": min_length,
        "maxLength": max_length,
        "meanLength": total_length / records,
        "gcFraction": gc / bases,
        "nFraction": n / bases,
        "qualityAsciiMin": q_min,
        "qualityAsciiMax": q_max,
        "firstReadId": first_read_id,
        "lastReadId": last_read_id,
        "ids": ids,
        "source": source,
    }


def stream_fastq_subset(run: str, read: str, source_url: str, output_relative_path: str) -> dict[str, Any]:
    output_path = path_from_root(output_relative_path)
    ensure_dir(output_path.parent)
    if output_path.exists() and output_path.stat().st_size > 0:
        return summarize_fastq(run, read, source_url, output_path, "existing")

    request = urllib.request.Request(source_url)
    current: list[str] = []
    records = 0
    with urllib.request.urlopen(request, timeout=300) as response:
        with gzip.GzipFile(fileobj=response) as gzip_handle:
            with output_path.open("w", encoding="utf-8") as output:
                for raw_line in gzip_handle:
                    line = raw_line.decode("utf-8").rstrip("\n")
                    output.write(f"{line}\n")
                    current.append(line)
                    if len(current) != 4:
                        continue
                    records += 1
                    validate_fastq_record(current, f"{run} {read}", records)
                    current = []
                    if records >= READ_PAIRS_PER_END:
                        break

    return summarize_fastq(run, read, source_url, output_path, "streamed")


def assert_paired(r1: dict[str, Any], r2: dict[str, Any]) -> None:
    if r1["records"] != r2["records"]:
        raise RuntimeError(f"{r1['run']} R1/R2 record-count mismatch")
    for index, (left, right) in enumerate(zip(r1["ids"], r2["ids"])):
        if left != right:
            raise RuntimeError(f"{r1['run']} R1/R2 read-id mismatch at {index}: {left} vs {right}")


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))

    raw_panel = parse_csv(read_text(path_from_root("manifests/raw_representative_panel.csv")))
    selected = sorted([row for row in raw_panel if row["pair_id"] == PAIR_ID], key=lambda row: 0 if row["role"] == "tumor" else 1)
    if len(selected) != 2 or {row["role"] for row in selected} != {"tumor", "normal"}:
        raise RuntimeError(f"Expected tumor and normal raw panel rows for {PAIR_ID}.")

    references = parse_csv(read_text(path_from_root("manifests/full_reference_smoke_references.csv")))
    reference = next((row for row in references if row["reference_id"] == "ucsc_hg38_analysis_set_full"), None)
    if not reference:
        raise RuntimeError("Expected ucsc_hg38_analysis_set_full in manifests/full_reference_smoke_references.csv.")
    for relative_path in [reference["fasta_path"], reference["fasta_fai_path"], reference["interval_bed_path"]]:
        if not path_from_root(relative_path).exists():
            raise RuntimeError(f"Required Phase 3 WGS reference asset is missing: {relative_path}")

    full_wes_rows = (
        parse_csv(read_text(path_from_root("manifests/full_wes_benchmark_samplesheet.csv")))
        if path_from_root("manifests/full_wes_benchmark_samplesheet.csv").exists()
        else []
    )
    full_wes_resource = full_wes_rows[0] if full_wes_rows else {}
    java_path = find_java(full_wes_resource.get("java_path", ""))
    gatk_jar = full_wes_resource.get("gatk_jar_path") or "data/raw/tools/gatk/gatk-4.6.2.0/gatk-package-4.6.2.0-local.jar"
    if not path_from_root(gatk_jar).exists():
        raise RuntimeError(f"GATK jar is missing: {gatk_jar}. Run fetch:production-somatic or fetch:full-wes first.")

    truth_snv_path = f"{SEQC2_TRUTH_ROOT}/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz"
    truth_indel_path = f"{SEQC2_TRUTH_ROOT}/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz"
    truth_high_confidence_bed_path = f"{SEQC2_TRUTH_ROOT}/High-Confidence_Regions_v1.2.bed"
    for relative_path in [truth_snv_path, truth_indel_path, truth_high_confidence_bed_path]:
        if not path_from_root(relative_path).exists():
            raise RuntimeError(f"SEQC2 truth asset is missing: {relative_path}. Run fetch:production-somatic first.")

    sample_rows: list[dict[str, Any]] = []
    for row in selected:
        sample_name = "HCC1395" if row["role"] == "tumor" else "HCC1395BL"
        sample_rows.append(
            {
                "pair_id": row["pair_id"],
                "patient": "HCC1395",
                "sample": sample_name,
                "role": row["role"],
                "status": "tumor" if row["role"] == "tumor" else "matched_normal",
                "run_accession": row["run"],
                "assay": row["assay"],
                "library_strategy": row["library_strategy"],
                "library_layout": row["library_layout"],
                "platform": row["platform"],
                "model": row["model"],
                "source_read_pairs": row["spots"],
                "source_bases": row["bases"],
                "source_fastq_1": row["fastq_1_url"],
                "source_fastq_2": row["fastq_2_url"],
                "source_fastq_1_md5": row["fastq_1_md5"],
                "source_fastq_2_md5": row["fastq_2_md5"],
                "source_fastq_1_bytes": row["fastq_1_bytes"],
                "source_fastq_2_bytes": row["fastq_2_bytes"],
                "read_pairs_per_end": READ_PAIRS_PER_END,
                "fastq_1": f"{SMOKE_ROOT}/fastq/{row['run']}_R1.{READ_PAIRS_PER_END}reads.fastq",
                "fastq_2": f"{SMOKE_ROOT}/fastq/{row['run']}_R2.{READ_PAIRS_PER_END}reads.fastq",
                "reference_id": reference["reference_id"],
                "assembly": reference["assembly"],
                "genome_build": reference["genome_build"],
                "reference_path": reference["fasta_path"],
                "reference_fai_path": reference["fasta_fai_path"],
                "reference_dict_path": reference_dict_path(reference["fasta_path"]),
                "reference_sha256": reference["fasta_sha256"],
                "brca_interval_bed_path": reference["interval_bed_path"],
                "brca_interval_regions": reference["interval_regions"],
                "brca_interval_genes": reference["interval_genes"],
                "truth_snv_vcf_path": truth_snv_path,
                "truth_indel_vcf_path": truth_indel_path,
                "truth_high_confidence_bed_path": truth_high_confidence_bed_path,
                "gatk_jar_path": gatk_jar,
                "java_path": java_path,
                "mutect2_panel_of_normals_path": full_wes_resource.get("mutect2_panel_of_normals_path", ""),
                "production_caller": "GATK Mutect2 + FilterMutectCalls",
                "read_group_id": f"{row['run']}.{row['role']}.phase3wgs",
                "read_group_sample": sample_name,
                "read_group_library": row["run"],
                "read_group_platform": "ILLUMINA",
                "read_group_platform_unit": row["run"],
                "output_bam": f"{SMOKE_ROOT}/{reference['reference_id']}/bam/{row['run']}.{row['role']}.bam",
                "output_bai": f"{SMOKE_ROOT}/{reference['reference_id']}/bam/{row['run']}.{row['role']}.bam.bai",
                "caller_interval_strategy": "covered SEQC2 WGS truth loci from tumor and normal downsampled BAM depth, fallback to mapped-read intervals if needed",
                "cnv_strategy": "samtools bedcov over fixed-width standard-contig bins with tumor/normal log2 coverage ratios",
                "sv_strategy": "samtools split-read, supplementary-read, discordant-pair, and interchromosomal-pair evidence counts",
                "signature_strategy": "local SBS96 mutation matrix from actual filtered WGS smoke VCF records; signature classification deferred unless mutation count is sufficient",
                "caveat": "Phase 3 WGS smoke uses a real WGS FASTQ subset from the full SEQC2/HCC1395 HiSeq X pair. It validates WGS-capable mechanics, not full-depth WGS HRD sensitivity or a clinical Diana interpretation.",
            }
        )

    tasks: list[tuple[str, str, str, str]] = []
    for row in sample_rows:
        tasks.append((row["run_accession"], "R1", row["source_fastq_1"], row["fastq_1"]))
        tasks.append((row["run_accession"], "R2", row["source_fastq_2"], row["fastq_2"]))
    with ThreadPoolExecutor(max_workers=min(FETCH_CONCURRENCY, len(tasks))) as pool:
        fastq_stats = list(pool.map(lambda task: stream_fastq_subset(*task), tasks))

    for row in sample_rows:
        r1 = next(stat for stat in fastq_stats if stat["run"] == row["run_accession"] and stat["read"] == "R1")
        r2 = next(stat for stat in fastq_stats if stat["run"] == row["run_accession"] and stat["read"] == "R2")
        assert_paired(r1, r2)

    fastq_rows: list[dict[str, Any]] = []
    for row in sample_rows:
        r1 = next(stat for stat in fastq_stats if stat["run"] == row["run_accession"] and stat["read"] == "R1")
        r2 = next(stat for stat in fastq_stats if stat["run"] == row["run_accession"] and stat["read"] == "R2")
        fastq_rows.append(
            {
                "pair_id": row["pair_id"],
                "sample": row["sample"],
                "role": row["role"],
                "run_accession": row["run_accession"],
                "assay": row["assay"],
                "source_read_pairs": row["source_read_pairs"],
                "reads_per_end": r1["records"],
                "local_fastq_1": row["fastq_1"],
                "local_fastq_2": row["fastq_2"],
                "r1_mean_length": round_value(r1["meanLength"], 2),
                "r2_mean_length": round_value(r2["meanLength"], 2),
                "r1_gc_fraction": round_value(r1["gcFraction"], 4),
                "r2_gc_fraction": round_value(r2["gcFraction"], 4),
                "r1_n_fraction": round_value(r1["nFraction"], 6),
                "r2_n_fraction": round_value(r2["nFraction"], 6),
                "first_read_id": r1["firstReadId"],
                "last_read_id": r1["lastReadId"],
                "paired_id_check": "passed",
                "fetch_state": f"{r1['source']}/{r2['source']}",
                "caveat": "Downsampled real WGS FASTQ subset for Phase 3 WGS-capable HRD lane validation.",
            }
        )

    write_csv(path_from_root("manifests/phase3_wgs_smoke_samplesheet.csv"), sample_rows)
    write_csv(path_from_root(f"{RESULTS_DIR}/fastq_summary.csv"), fastq_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/fastq_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "passed",
            "pairId": PAIR_ID,
            "readPairsPerEnd": READ_PAIRS_PER_END,
            "fetchConcurrency": FETCH_CONCURRENCY,
            "rows": fastq_rows,
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/asset_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "ready",
            "phase": "3",
            "pairId": PAIR_ID,
            "readPairsPerEnd": READ_PAIRS_PER_END,
            "sampleRows": len(sample_rows),
            "source": "SEQC2/HCC1395 public HiSeq X Ten WGS tumor-normal FASTQ pair",
            "reference": {
                "referenceId": reference["reference_id"],
                "assembly": reference["assembly"],
                "genomeBuild": reference["genome_build"],
                "fastaPath": reference["fasta_path"],
                "faiPath": reference["fasta_fai_path"],
                "dictPath": reference_dict_path(reference["fasta_path"]),
            },
            "gatk": {"jarPath": gatk_jar, "javaPath": java_path},
            "seqc2Truth": {
                "snvVcfPath": truth_snv_path,
                "indelVcfPath": truth_indel_path,
                "highConfidenceBedPath": truth_high_confidence_bed_path,
            },
            "parallelism": {
                "fetchConcurrency": FETCH_CONCURRENCY,
                "note": "FASTQ end streams can be fetched concurrently; alignment/runtime thread controls live in smoke:phase3-wgs.",
            },
            "boundary": "This prepares a bounded WGS smoke subset from full public WGS FASTQs. It does not download the complete 198 GB compressed HiSeq X tumor-normal WGS pair.",
        },
    )
    write_text(
        path_from_root(f"{RESULTS_DIR}/README.md"),
        f"""# Phase 3 WGS Smoke Assets

Status: **ready**.

Representative pair: `{PAIR_ID}`

Reads per FASTQ end: `{READ_PAIRS_PER_END}`

This stage streams a bounded subset from the full public SEQC2/HCC1395 HiSeq X Ten WGS tumor-normal FASTQ pair. It validates real WGS FASTQ access and pairing while keeping the local Phase 3 run tractable.

Boundary: this is a WGS-capable smoke subset, not the complete compressed WGS pair and not a clinical HRD result.
""",
    )
    print(f"Phase 3 WGS smoke assets ready: {len(sample_rows)} samples, {READ_PAIRS_PER_END} read pairs/end.")


if __name__ == "__main__":
    main()
