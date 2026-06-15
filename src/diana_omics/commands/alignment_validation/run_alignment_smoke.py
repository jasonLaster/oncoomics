from __future__ import annotations

from ...alignment import align_and_validate, ensure_bwa_index, tool_version
from ...paths import path_from_root
from ...utils import capture_command, ensure_dir, iso_now, parse_csv, read_text, sha256_file, write_csv, write_json, write_text

RESULTS_DIR = "results/alignment_smoke"


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    rows = parse_csv(read_text(path_from_root("manifests/alignment_smoke_samplesheet.csv")))
    if len(rows) != 2 or not any(row["role"] == "tumor" for row in rows) or not any(row["role"] == "normal" for row in rows):
        raise RuntimeError("Expected tumor and normal rows in manifests/alignment_smoke_samplesheet.csv.")
    reference_paths = set(row["reference_path"] for row in rows)
    if len(reference_paths) != 1:
        raise RuntimeError("Alignment smoke samplesheet must use exactly one reference.")
    reference_path = rows[0]["reference_path"]
    observed_reference_sha256 = sha256_file(reference_path)
    for row in rows:
        if row["reference_sha256"] != observed_reference_sha256:
            raise RuntimeError(
                f"{row['run_accession']} expected reference sha256 {row['reference_sha256']}; observed {observed_reference_sha256}."
            )
    indexed_reference = ensure_bwa_index(reference_path, RESULTS_DIR, "bwa_index")
    validation_rows = []
    for row in rows:
        validation = align_and_validate(row, RESULTS_DIR)
        idxstats_mapped = sum(item["mapped"] for item in validation.pop("idxstats_rows"))
        validation.update({"idxstats_mapped_alignments": idxstats_mapped})
        validation_rows.append(validation)
    status = "passed" if all(row["status"] == "passed" for row in validation_rows) else "failed"
    write_csv(path_from_root(f"{RESULTS_DIR}/bam_validation_summary.csv"), validation_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/bam_validation_summary.json"), {"generatedAt": iso_now(), "status": status, "rows": validation_rows}
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/tool_versions.json"),
        {
            "generatedAt": iso_now(),
            "bwa": {"path": capture_command("command -v bwa"), "version": tool_version("bwa", 6)},
            "samtools": {"path": capture_command("command -v samtools"), "version": tool_version("samtools", 6)},
        },
    )
    write_json(
        path_from_root(f"{RESULTS_DIR}/alignment_smoke_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": status,
            "pairId": rows[0]["pair_id"],
            "referenceId": rows[0]["reference_id"],
            "referencePath": reference_path,
            "referenceSha256": observed_reference_sha256,
            "indexedReference": indexed_reference,
            "aligner": "bwa mem",
            "bamTool": "samtools",
            "samples": len(validation_rows),
            "tumorRows": len([row for row in validation_rows if row["role"] == "tumor"]),
            "normalRows": len([row for row in validation_rows if row["role"] == "normal"]),
            "boundary": "Phase 2B local BAM smoke validates FASTQ-to-coordinate-sorted-BAM mechanics and caller-input file contracts against a read-backed synthetic reference. It does not validate GRCh37/GRCh38 alignment, coverage, somatic calls, or HRD signatures.",
        },
    )
    write_csv(
        path_from_root(f"{RESULTS_DIR}/alignment_smoke_summary.csv"),
        [
            {
                "status": status,
                "pair_id": rows[0]["pair_id"],
                "reference_id": rows[0]["reference_id"],
                "aligner": "bwa mem",
                "bam_tool": "samtools",
                "samples": len(validation_rows),
                "tumor_rows": len([row for row in validation_rows if row["role"] == "tumor"]),
                "normal_rows": len([row for row in validation_rows if row["role"] == "normal"]),
                "boundary": "Local file-contract smoke only; not human-reference alignment, somatic calling, or HRD signature evidence.",
            }
        ],
    )
    write_text(path_from_root(f"{RESULTS_DIR}/README.md"), f"# Alignment Smoke Test\n\nStatus: **{status}**.\n")
    if status != "passed":
        raise RuntimeError("Alignment smoke failed. See results/alignment_smoke/.")
    print(f"Alignment smoke {status} for {len(validation_rows)} BAMs.")


if __name__ == "__main__":
    main()
