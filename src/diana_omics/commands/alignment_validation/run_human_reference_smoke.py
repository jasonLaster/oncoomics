from __future__ import annotations

from ...alignment import align_and_validate, ensure_bwa_index, tool_version
from ...paths import path_from_root
from ...utils import capture_command, ensure_dir, group_by, iso_now, parse_csv, read_text, sha256_file, write_csv, write_json, write_text

RESULTS_DIR = "results/human_reference_smoke"


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    rows = parse_csv(read_text(path_from_root("manifests/human_reference_smoke_samplesheet.csv")))
    if len(rows) < 4:
        raise RuntimeError("Expected at least four human-reference smoke sample rows: two samples across two references.")
    validation_rows = []
    indexed_references = set()
    for row in rows:
        if sha256_file(row["reference_path"]) != row["reference_sha256"]:
            raise RuntimeError(f"{row['reference_id']} sha256 mismatch.")
        if row["reference_id"] not in indexed_references:
            ensure_bwa_index(row["reference_path"], RESULTS_DIR, row["reference_id"])
            indexed_references.add(row["reference_id"])
        required_contigs = [contig for contig in row["chromosomes"].split(";") if contig]
        validation = align_and_validate(row, RESULTS_DIR, required_contigs)
        idxstats_rows = validation.pop("idxstats_rows")
        mapped_by_contig = []
        for contig in required_contigs:
            mapped = next((idx["mapped"] for idx in idxstats_rows if idx["contig"] == contig), 0)
            mapped_by_contig.append(f"{contig}:{mapped}")
        validation.update(
            {
                "assembly": row["assembly"],
                "genome_build": row["genome_build"],
                "chromosomes": row["chromosomes"],
                "genes_covered": row["genes_covered"],
                "expected_contigs_present": "yes"
                if all(contig in validation["reference_contigs"].split(";") for contig in required_contigs)
                else "no",
                "mapped_by_contig": ";".join(mapped_by_contig),
            }
        )
        validation_rows.append(validation)
    comparisons = []
    for run, run_rows in group_by(validation_rows, lambda row: row["run_accession"]).items():
        passed_builds = sorted(row["assembly"] for row in run_rows if row["status"] == "passed")
        mapped_values = [int(row["mapped_alignments"]) for row in run_rows]
        comparisons.append(
            {
                "run_accession": run,
                "sample": run_rows[0]["sample"],
                "role": run_rows[0]["role"],
                "tested_builds": ";".join(sorted(row["assembly"] for row in run_rows)),
                "passed_builds": ";".join(passed_builds),
                "mapped_alignment_range": f"{min(mapped_values)}-{max(mapped_values)}",
                "status": "passed" if "hg19" in passed_builds and "hg38" in passed_builds else "failed",
                "caveat": "Build comparison validates that the same HCC1395 FASTQ subset can align to two partial human references; it is not build-liftover validation.",
            }
        )
    status = (
        "passed"
        if all(row["status"] == "passed" for row in validation_rows) and all(row["status"] == "passed" for row in comparisons)
        else "failed"
    )
    write_csv(path_from_root(f"{RESULTS_DIR}/bam_validation_summary.csv"), validation_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/bam_validation_summary.json"), {"generatedAt": iso_now(), "status": status, "rows": validation_rows}
    )
    write_csv(path_from_root(f"{RESULTS_DIR}/reference_comparison_summary.csv"), comparisons)
    write_json(
        path_from_root(f"{RESULTS_DIR}/reference_comparison_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "passed" if all(row["status"] == "passed" for row in comparisons) else "failed",
            "comparisons": comparisons,
        },
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
        path_from_root(f"{RESULTS_DIR}/human_reference_alignment_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": status,
            "sampleRows": len(validation_rows),
            "references": sorted(set(row["reference_id"] for row in validation_rows)),
            "assemblies": sorted(set(row["assembly"] for row in validation_rows)),
            "genomeBuilds": sorted(set(row["genome_build"] for row in validation_rows)),
            "tumorRows": len([row for row in validation_rows if row["role"] == "tumor"]),
            "normalRows": len([row for row in validation_rows if row["role"] == "normal"]),
            "boundary": "Phase 2C validates partial real-human-reference alignment across hg38 and hg19 chr13/chr17. It does not validate full-depth WES/WGS performance, target capture intervals, somatic calling, CNV/SV calling, or HRD signatures.",
        },
    )
    write_csv(
        path_from_root(f"{RESULTS_DIR}/human_reference_alignment_summary.csv"),
        [
            {
                "status": status,
                "sample_rows": len(validation_rows),
                "references": ";".join(sorted(set(row["reference_id"] for row in validation_rows))),
                "assemblies": ";".join(sorted(set(row["assembly"] for row in validation_rows))),
                "genome_builds": ";".join(sorted(set(row["genome_build"] for row in validation_rows))),
                "tumor_rows": len([row for row in validation_rows if row["role"] == "tumor"]),
                "normal_rows": len([row for row in validation_rows if row["role"] == "normal"]),
                "boundary": "Partial hg38/hg19 chr13/chr17 human-reference smoke only; not full-depth WES/WGS, somatic calling, or HRD evidence.",
            }
        ],
    )
    write_text(path_from_root(f"{RESULTS_DIR}/README.md"), f"# Human-Reference Smoke Test\n\nStatus: **{status}**.\n")
    if status != "passed":
        raise RuntimeError("Human-reference smoke failed. See results/human_reference_smoke/.")
    print(f"Human-reference smoke {status} for {len(validation_rows)} BAM validations across {len(comparisons)} samples.")


if __name__ == "__main__":
    main()
