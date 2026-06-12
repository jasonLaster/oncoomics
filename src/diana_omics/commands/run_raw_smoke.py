from __future__ import annotations

import os

from ..paths import path_from_root
from ..utils import (
    ensure_dir,
    iso_now,
    parse_csv,
    read_text,
    round_value,
    stream_gzip_text,
    validate_fastq_record,
    write_csv,
    write_json,
    write_text,
)

SMOKE_PAIR_ID = "seqc2_hcc1395_wes_minimal_smoke"
READ_LIMIT = int(os.environ.get("RAW_SMOKE_READS", "1000"))
SMOKE_DIR = path_from_root("data/raw/smoke/seqc2_hcc1395_wes_minimal_smoke")
REPORT_DIR = path_from_root("results/raw_smoke")


def stream_fastq_subset(run: str, read: str, source_url: str, output_path) -> dict:
    ensure_dir(output_path.parent)
    current: list[str] = []
    records = total_length = gc = n = bases = 0
    min_length = 10**9
    max_length = 0
    q_min = 10**9
    q_max = 0
    first_read_id = ""
    last_read_id = ""
    ids = []
    with output_path.open("w", encoding="utf-8") as output:
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
            if records >= READ_LIMIT:
                break
    if records != READ_LIMIT:
        raise RuntimeError(f"{run} {read} produced {records} records; expected {READ_LIMIT}")
    if current:
        raise RuntimeError(f"{run} {read} ended mid-record")
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
    }


def assert_paired(r1: dict, r2: dict) -> None:
    if r1["records"] != r2["records"]:
        raise RuntimeError(f"{r1['run']} R1/R2 record-count mismatch")
    for index, (r1_id, r2_id) in enumerate(zip(r1["ids"], r2["ids"])):
        if r1_id != r2_id:
            raise RuntimeError(f"{r1['run']} R1/R2 read-id mismatch at {index}: {r1_id} vs {r2_id}")


def public_stats(stats: dict) -> dict:
    public = {key: value for key, value in stats.items() if key != "ids"}
    public["outputPath"] = str(public["outputPath"]).replace(str(path_from_root("")) + "/", "")
    public["meanLength"] = round_value(public["meanLength"], 2)
    public["gcFraction"] = round_value(public["gcFraction"], 4)
    public["nFraction"] = round_value(public["nFraction"], 6)
    public["fileSizeBytes"] = os.path.getsize(stats["outputPath"]) if os.path.exists(stats["outputPath"]) else ""
    return public


def main() -> None:
    ensure_dir(SMOKE_DIR)
    ensure_dir(REPORT_DIR)
    raw_panel = parse_csv(read_text(path_from_root("manifests/raw_representative_panel.csv")))
    selected = sorted([row for row in raw_panel if row["pair_id"] == SMOKE_PAIR_ID], key=lambda row: row["role"])
    if len(selected) != 2 or not any(row["role"] == "tumor" for row in selected) or not any(row["role"] == "normal" for row in selected):
        raise RuntimeError(f"Expected tumor and normal rows for {SMOKE_PAIR_ID}")
    stats = []
    for row in selected:
        r1_path = SMOKE_DIR / f"{row['run']}_R1.fastq"
        r2_path = SMOKE_DIR / f"{row['run']}_R2.fastq"
        r1 = stream_fastq_subset(row["run"], "R1", row["fastq_1_url"], r1_path)
        r2 = stream_fastq_subset(row["run"], "R2", row["fastq_2_url"], r2_path)
        assert_paired(r1, r2)
        stats.extend([r1, r2])
    summary_rows = []
    for row in selected:
        r1 = next(item for item in stats if item["run"] == row["run"] and item["read"] == "R1")
        r2 = next(item for item in stats if item["run"] == row["run"] and item["read"] == "R2")
        summary_rows.append(
            {
                "pair_id": row["pair_id"],
                "sample_name": row["sample_name"],
                "role": row["role"],
                "run": row["run"],
                "assay": row["assay"],
                "library_strategy": row["library_strategy"],
                "library_layout": row["library_layout"],
                "reads_per_end": r1["records"],
                "r1_mean_length": round_value(r1["meanLength"], 2),
                "r2_mean_length": round_value(r2["meanLength"], 2),
                "r1_gc_fraction": round_value(r1["gcFraction"], 4),
                "r2_gc_fraction": round_value(r2["gcFraction"], 4),
                "r1_n_fraction": round_value(r1["nFraction"], 6),
                "r2_n_fraction": round_value(r2["nFraction"], 6),
                "first_read_id": r1["firstReadId"],
                "last_read_id": r1["lastReadId"],
                "paired_id_check": "passed",
                "local_fastq_1": str(SMOKE_DIR / f"{row['run']}_R1.fastq").replace(str(path_from_root("")) + "/", ""),
                "local_fastq_2": str(SMOKE_DIR / f"{row['run']}_R2.fastq").replace(str(path_from_root("")) + "/", ""),
            }
        )
    write_csv(path_from_root("results/raw_smoke/fastq_smoke_summary.csv"), summary_rows)
    write_json(
        path_from_root("results/raw_smoke/fastq_smoke_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "passed",
            "pairId": SMOKE_PAIR_ID,
            "readLimit": READ_LIMIT,
            "source": "ENA direct paired FASTQ links for SEQC2/HCC1395 minimal WES pair",
            "stats": [public_stats(item) for item in stats],
            "limitations": [
                "This is a tiny first-read subset, not variant-calling depth.",
                "No alignment or somatic caller was run locally because aligner/BAM tools are not installed in the current environment.",
                "Use the remote samplesheet for full WES/WGS on a genomics-ready machine or container runtime.",
            ],
        },
    )
    write_text(
        path_from_root("results/raw_smoke/README.md"),
        f"# Raw FASTQ Smoke Test\n\nStatus: **passed**.\n\nSmoke pair: `{SMOKE_PAIR_ID}`\n\nSource: ENA direct paired FASTQ files derived from SEQC2/HCC1395 SRA run metadata.\n\nReads streamed per FASTQ end: `{READ_LIMIT}`\n",
    )
    print(f"Raw FASTQ smoke passed for {len(selected)} samples with {READ_LIMIT} read pairs each.")


if __name__ == "__main__":
    main()
