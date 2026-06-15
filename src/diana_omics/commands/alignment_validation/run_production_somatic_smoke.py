from __future__ import annotations

import gzip
import os
from typing import Any

from ...alignment import align_and_validate, ensure_bwa_index, tool_version
from ...paths import path_from_root
from ...utils import (
    capture_command,
    ensure_dir,
    iso_now,
    parse_csv,
    quote_shell_arg,
    read_text,
    run_command,
    stream_gzip_text,
    validate_fastq_record,
    write_csv,
    write_json,
    write_text,
)

RESULTS_DIR = "results/production_somatic_smoke"
MAX_ACTIVE_INTERVALS = int(os.environ.get("PRODUCTION_SOMATIC_MAX_INTERVALS", "500"))
ACTIVE_WINDOW_PADDING = int(os.environ.get("PRODUCTION_SOMATIC_ACTIVE_PADDING", "125"))
THREADS = int(os.environ.get("PRODUCTION_SOMATIC_THREADS", "4"))


def stream_fastq_subset(run: str, read: str, source_url: str, output_path: str, read_limit: int) -> dict[str, Any]:
    ensure_dir(path_from_root("/".join(output_path.split("/")[:-1])))
    current: list[str] = []
    records = total_length = gc = n = bases = 0
    min_length = 10**9
    max_length = 0
    q_min = 10**9
    q_max = 0
    first_read_id = ""
    last_read_id = ""
    ids = []
    with path_from_root(output_path).open("w", encoding="utf-8") as output:
        for line in stream_gzip_text(source_url):
            output.write(f"{line}\n")
            current.append(line)
            if len(current) != 4:
                continue
            records += 1
            record = validate_fastq_record(current, f"{run} {read}", records)
            first_read_id = first_read_id or record["id"]
            last_read_id = record["id"]
            ids.append(record["id"])
            sequence = record["sequence"].upper()
            total_length += len(sequence)
            min_length = min(min_length, len(sequence))
            max_length = max(max_length, len(sequence))
            gc += sequence.count("G") + sequence.count("C")
            n += sequence.count("N")
            bases += len(sequence)
            for char in record["quality"]:
                q_min = min(q_min, ord(char))
                q_max = max(q_max, ord(char))
            current = []
            if records >= read_limit:
                break
    if records != read_limit:
        raise RuntimeError(f"{run} {read} produced {records} records; expected {read_limit}")
    return {
        "run": run,
        "read": read,
        "sourceUrl": source_url,
        "outputPath": output_path,
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
    }


def assert_paired(r1: dict, r2: dict) -> None:
    if r1["records"] != r2["records"]:
        raise RuntimeError(f"{r1['run']} R1/R2 record-count mismatch")
    for index, (r1_id, r2_id) in enumerate(zip(r1["ids"], r2["ids"])):
        if r1_id != r2_id:
            raise RuntimeError(f"{r1['run']} R1/R2 read-id mismatch at {index}: {r1_id} vs {r2_id}")


def strip_ids(stats: dict) -> dict:
    public = {key: value for key, value in stats.items() if key != "ids"}
    public["fileSizeBytes"] = path_from_root(stats["outputPath"]).stat().st_size if path_from_root(stats["outputPath"]).exists() else ""
    return public


def parse_intervals_from_bam(row: dict[str, str], truth_bed_path: str) -> list[dict[str, Any]]:
    idxstats = capture_command(f"samtools idxstats {quote_shell_arg(row['output_bam'])}")
    mapped_contigs = {line.split("\t")[0] for line in idxstats.splitlines() if line.strip() and int(line.split("\t")[2]) > 0}
    regions = []
    with path_from_root(truth_bed_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            contig, start, end, *_ = line.rstrip("\n").split("\t")
            if contig in mapped_contigs:
                regions.append(
                    {
                        "contig": contig,
                        "start": max(0, int(start) - ACTIVE_WINDOW_PADDING),
                        "end": int(end) + ACTIVE_WINDOW_PADDING,
                        "truthOverlap": True,
                    }
                )
            if len(regions) >= MAX_ACTIVE_INTERVALS:
                break
    if regions:
        return regions
    for contig in sorted(mapped_contigs):
        regions.append({"contig": contig, "start": 0, "end": 1000000, "truthOverlap": False})
        if len(regions) >= MAX_ACTIVE_INTERVALS:
            break
    return regions


def write_interval_bed(path: str, intervals: list[dict[str, Any]]) -> None:
    ensure_dir(path_from_root("/".join(path.split("/")[:-1])))
    write_text(
        path_from_root(path),
        "\n".join(f"{row['contig']}\t{row['start']}\t{row['end']}\tactive_{index + 1}" for index, row in enumerate(intervals)),
    )


def parse_vcf_summary(vcf_path: str) -> dict[str, Any]:
    records = count_pass = 0
    samples: list[str] = []
    with gzip.open(path_from_root(vcf_path), "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#CHROM"):
                samples = line.rstrip("\n").split("\t")[9:]
            elif not line.startswith("#"):
                records += 1
                fields = line.split("\t")
                if len(fields) > 6 and fields[6] == "PASS":
                    count_pass += 1
    return {"records": records, "passRecords": count_pass, "samples": samples}


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    rows = parse_csv(read_text(path_from_root("manifests/production_somatic_smoke_samplesheet.csv")))
    if len(rows) != 2 or not any(row["role"] == "tumor" for row in rows) or not any(row["role"] == "normal" for row in rows):
        raise RuntimeError("Expected tumor and normal rows in manifests/production_somatic_smoke_samplesheet.csv.")
    read_limit = int(rows[0]["read_pairs_per_end"])
    fastq_stats = []
    for row in rows:
        r1 = stream_fastq_subset(row["run_accession"], "R1", row["source_fastq_1"], row["fastq_1"], read_limit)
        r2 = stream_fastq_subset(row["run_accession"], "R2", row["source_fastq_2"], row["fastq_2"], read_limit)
        assert_paired(r1, r2)
        fastq_stats.extend([r1, r2])
    write_csv(path_from_root(f"{RESULTS_DIR}/fastq_summary.csv"), [strip_ids(row) for row in fastq_stats])
    write_json(
        path_from_root(f"{RESULTS_DIR}/fastq_summary.json"),
        {"generatedAt": iso_now(), "status": "passed", "readPairsPerEnd": read_limit, "rows": [strip_ids(row) for row in fastq_stats]},
    )

    reference_path = rows[0]["reference_path"]
    reference_id = rows[0]["reference_id"]
    ensure_bwa_index(reference_path, RESULTS_DIR, reference_id)
    validation_rows = []
    for row in rows:
        row["aligner_threads"] = str(THREADS)
        validation = align_and_validate(row, RESULTS_DIR, ["chr13", "chr17"])
        validation.pop("idxstats_rows", None)
        validation["caller_ready_scope"] = row["caller_interval_strategy"]
        validation_rows.append(validation)
    bam_status = "passed" if all(row["status"] == "passed" for row in validation_rows) else "failed"
    write_csv(path_from_root(f"{RESULTS_DIR}/bam_validation_summary.csv"), validation_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/bam_validation_summary.json"),
        {"generatedAt": iso_now(), "status": bam_status, "rows": validation_rows},
    )

    tumor = next(row for row in rows if row["role"] == "tumor")
    normal = next(row for row in rows if row["role"] == "normal")
    active_intervals = parse_intervals_from_bam(tumor, tumor["truth_high_confidence_bed_path"])
    active_bed = f"data/raw/smoke/seqc2_hcc1395_production_somatic_smoke/{reference_id}/active_intervals.bed"
    write_interval_bed(active_bed, active_intervals)
    vcf_path = f"data/raw/smoke/seqc2_hcc1395_production_somatic_smoke/{reference_id}/vcf/mutect2.filtered.vcf.gz"
    ensure_dir(path_from_root("/".join(vcf_path.split("/")[:-1])))
    raw_vcf = vcf_path.replace(".filtered.vcf.gz", ".unfiltered.vcf.gz")
    run_command(
        f"{quote_shell_arg(tumor['java_path'])} -jar {quote_shell_arg(tumor['gatk_jar_path'])} Mutect2 -R {quote_shell_arg(reference_path)} -I {quote_shell_arg(tumor['output_bam'])} -I {quote_shell_arg(normal['output_bam'])} -tumor {quote_shell_arg(tumor['read_group_sample'])} -normal {quote_shell_arg(normal['read_group_sample'])} -L {quote_shell_arg(active_bed)} -O {quote_shell_arg(raw_vcf)}",
        f"{RESULTS_DIR}/logs/mutect2.log",
    )
    run_command(
        f"{quote_shell_arg(tumor['java_path'])} -jar {quote_shell_arg(tumor['gatk_jar_path'])} FilterMutectCalls -R {quote_shell_arg(reference_path)} -V {quote_shell_arg(raw_vcf)} -O {quote_shell_arg(vcf_path)}",
        f"{RESULTS_DIR}/logs/filter_mutect_calls.log",
    )
    run_command(
        f"{quote_shell_arg(tumor['java_path'])} -jar {quote_shell_arg(tumor['gatk_jar_path'])} IndexFeatureFile -I {quote_shell_arg(vcf_path)} || tabix -p vcf {quote_shell_arg(vcf_path)}",
        f"{RESULTS_DIR}/logs/index_filtered_vcf.log",
    )
    vcf_summary = parse_vcf_summary(vcf_path)
    mutect_rows = [
        {
            "caller": "GATK Mutect2 + FilterMutectCalls",
            "reference_id": reference_id,
            "active_interval_count": len(active_intervals),
            "output_vcf": vcf_path,
            "records": vcf_summary["records"],
            "pass_records": vcf_summary["passRecords"],
            "samples": ";".join(vcf_summary["samples"]),
            "status": "passed" if path_from_root(vcf_path).exists() else "failed",
            "caveat": "Downsampled public WES smoke; validates execution and VCF contracts, not sensitivity or clinical interpretation.",
        }
    ]
    write_csv(path_from_root(f"{RESULTS_DIR}/mutect2_smoke_summary.csv"), mutect_rows)
    mutect_status = "passed" if all(row["status"] == "passed" for row in mutect_rows) else "failed"
    write_json(
        path_from_root(f"{RESULTS_DIR}/mutect2_smoke_summary.json"),
        {"generatedAt": iso_now(), "status": mutect_status, "rows": mutect_rows},
    )
    status = "passed" if bam_status == "passed" and mutect_rows[0]["status"] == "passed" else "failed"
    summary_rows = [
        {
            "status": status,
            "caller": "GATK Mutect2 + FilterMutectCalls",
            "reference_id": reference_id,
            "read_pairs_per_end": read_limit,
            "active_interval_count": len(active_intervals),
            "mutect_records": vcf_summary["records"],
            "mutect_pass_records": vcf_summary["passRecords"],
            "comparison_status": "not_assessed_in_smoke",
            "boundary": "Production-style somatic smoke only; not full-depth WES/WGS, not production-resource-filtered clinical analysis, and not HRD signature evidence.",
        }
    ]
    write_csv(path_from_root(f"{RESULTS_DIR}/production_somatic_summary.csv"), summary_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/production_somatic_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": status,
            "caller": "GATK Mutect2 + FilterMutectCalls",
            "referenceId": reference_id,
            "readPairsPerEnd": read_limit,
            "activeIntervalCount": len(active_intervals),
            "comparisonStatus": "not_assessed_in_smoke",
            "boundary": summary_rows[0]["boundary"],
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/tool_versions.json"),
        {
            "generatedAt": iso_now(),
            "bwa": {"path": capture_command("command -v bwa"), "version": tool_version("bwa")},
            "samtools": {"path": capture_command("command -v samtools"), "version": tool_version("samtools")},
            "gatk": {"jar": tumor["gatk_jar_path"]},
        },
    )
    write_text(path_from_root(f"{RESULTS_DIR}/README.md"), f"# Production Somatic Smoke\n\nStatus: **{status}**.\n")
    if status != "passed":
        raise RuntimeError("Production somatic smoke failed. See results/production_somatic_smoke/.")
    print(f"Production somatic smoke {status} with {len(active_intervals)} active intervals.")


if __name__ == "__main__":
    main()
