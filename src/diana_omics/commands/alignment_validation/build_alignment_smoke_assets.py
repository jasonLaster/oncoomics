from __future__ import annotations

import hashlib

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_fastq, read_text, write_csv, write_json, write_text

SMOKE_PAIR_ID = "seqc2_hcc1395_wes_minimal_smoke"
ALIGNMENT_DIR = "data/raw/smoke/seqc2_hcc1395_alignment_smoke"
REFERENCE_ID = "seqc2_hcc1395_readback_smoke_v1"
REFERENCE_PATH = f"{ALIGNMENT_DIR}/reference/{REFERENCE_ID}.fa"
RESULTS_DIR = "results/alignment_smoke"
GAP = "N" * 100


def reverse_complement(sequence: str) -> str:
    complement = str.maketrans("ACGTNacgtn", "TGCANtgcan")
    return sequence.translate(complement)[::-1].upper()


def wrap_fasta(sequence: str) -> str:
    return "\n".join(sequence[index : index + 80] for index in range(0, len(sequence), 80))


def sample_name(row: dict[str, str]) -> str:
    return row["sample"].replace(f"_{row['run_accession']}", "")


def main() -> None:
    ensure_dir(path_from_root(f"{ALIGNMENT_DIR}/reference"))
    ensure_dir(path_from_root(f"{ALIGNMENT_DIR}/bam"))
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root("manifests"))
    rows = sorted(
        [row for row in parse_csv(read_text(path_from_root("manifests/raw_smoke_samplesheet.csv"))) if row["pair_id"] == SMOKE_PAIR_ID],
        key=lambda row: row["role"],
    )
    if len(rows) != 2 or not any(row["role"] == "tumor" for row in rows) or not any(row["role"] == "normal" for row in rows):
        raise RuntimeError(f"Expected tumor and normal rows for {SMOKE_PAIR_ID}.")
    fasta_parts = []
    sample_summaries = []
    contigs = 0
    min_contig_length = 10**9
    max_contig_length = 0
    for row in rows:
        r1 = read_fastq(path_from_root(row["fastq_1"]))
        r2 = read_fastq(path_from_root(row["fastq_2"]))
        if len(r1) != len(r2):
            raise RuntimeError(f"{row['run_accession']} R1/R2 record-count mismatch.")
        for index, (r1_record, r2_record) in enumerate(zip(r1, r2), start=1):
            if r1_record["id"] != r2_record["id"]:
                raise RuntimeError(f"{row['run_accession']} R1/R2 read-id mismatch at pair {index}.")
            contig_name = f"{row['run_accession']}_pair_{index:06d}"
            sequence = f"{r1_record['sequence'].upper()}{GAP}{reverse_complement(r2_record['sequence'])}"
            contigs += 1
            min_contig_length = min(min_contig_length, len(sequence))
            max_contig_length = max(max_contig_length, len(sequence))
            fasta_parts.append(f">{contig_name}\n{wrap_fasta(sequence)}")
        sample_summaries.append(
            {
                "run_accession": row["run_accession"],
                "role": row["role"],
                "sample": sample_name(row),
                "read_pairs": len(r1),
                "fastq_1": row["fastq_1"],
                "fastq_2": row["fastq_2"],
            }
        )
    fasta_text = "\n".join(fasta_parts) + "\n"
    write_text(path_from_root(REFERENCE_PATH), fasta_text)
    reference_sha256 = hashlib.sha256(fasta_text.encode("utf-8")).hexdigest()
    alignment_rows = []
    for row in rows:
        run = row["run_accession"]
        bam = f"{ALIGNMENT_DIR}/bam/{run}.coordinate_sorted.bam"
        alignment_rows.append(
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
                "sample": sample_name(row),
                "reference_id": REFERENCE_ID,
                "reference_path": REFERENCE_PATH,
                "reference_sha256": reference_sha256,
                "aligner": "bwa mem",
                "aligner_threads": "2",
                "read_group_id": run,
                "read_group_sample": sample_name(row),
                "read_group_library": f"{row['assay']}_{row['role']}",
                "read_group_platform": "ILLUMINA",
                "read_group_platform_unit": run,
                "output_bam": bam,
                "output_bai": f"{bam}.bai",
                "source": "Phase 2A local HCC1395 FASTQ subset",
                "caveat": "Read-backed synthetic smoke reference for local alignment and BAM contract validation only; not a human-reference or variant-calling result.",
            }
        )
    write_csv(path_from_root("manifests/alignment_smoke_samplesheet.csv"), alignment_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/reference_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "built",
            "referenceId": REFERENCE_ID,
            "referencePath": REFERENCE_PATH,
            "referenceSha256": reference_sha256,
            "referenceType": "read-backed synthetic smoke reference",
            "smokePairId": SMOKE_PAIR_ID,
            "samples": sample_summaries,
            "contigs": contigs,
            "minContigLength": min_contig_length,
            "maxContigLength": max_contig_length,
            "gapLength": len(GAP),
            "caveat": "This reference is intentionally built from the representative FASTQ subset to validate alignment mechanics locally. It is not GRCh37, GRCh38, or any biological reference.",
        },
    )
    print(f"Built {REFERENCE_ID} with {contigs} read-backed contigs and {len(alignment_rows)} alignment rows.")


if __name__ == "__main__":
    main()
