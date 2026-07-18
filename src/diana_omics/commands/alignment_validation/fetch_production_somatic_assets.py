from __future__ import annotations

import os
import re
import subprocess

from ...paths import path_from_root
from ...utils import (
    capture_command,
    command_path,
    ensure_dir,
    fetch_json,
    iso_now,
    parse_csv,
    quote_shell_arg,
    read_text,
    run_command,
    sha256_file,
    write_csv,
    write_json,
)

GATK_VERSION = os.environ.get("GATK_VERSION", "4.6.2.0")
PAIR_ID = "seqc2_hcc1395_wes_minimal_smoke"
READ_PAIRS_PER_END = int(os.environ.get("PRODUCTION_SOMATIC_READS", "50000"))
RESULTS_DIR = "results/production_somatic_smoke"
TOOL_ROOT = "data/raw/tools/gatk"
GATK_DIR = f"{TOOL_ROOT}/gatk-{GATK_VERSION}"
GATK_ZIP = f"{TOOL_ROOT}/gatk-{GATK_VERSION}.zip"
GATK_JAR = f"{GATK_DIR}/gatk-package-{GATK_VERSION}-local.jar"
SEQC2_TRUTH_ROOT = "data/raw/reference/seqc2_hcc1395_truth/latest"
TRUTH_ASSETS = [
    {
        "kind": "snv",
        "url": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz",
        "path": f"{SEQC2_TRUTH_ROOT}/high-confidence_sSNV_in_HC_regions_v1.2.1.vcf.gz",
    },
    {
        "kind": "indel",
        "url": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz",
        "path": f"{SEQC2_TRUTH_ROOT}/high-confidence_sINDEL_in_HC_regions_v1.2.1.vcf.gz",
    },
    {
        "kind": "high_confidence_regions",
        "url": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/High-Confidence_Regions_v1.2.bed",
        "path": f"{SEQC2_TRUTH_ROOT}/High-Confidence_Regions_v1.2.bed",
    },
    {
        "kind": "readme",
        "url": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/README.md",
        "path": f"{SEQC2_TRUTH_ROOT}/README.md",
    },
]


def java_works(candidate: str) -> bool:
    if not candidate or not os.path.exists(candidate):
        return False
    result = subprocess.run(
        [candidate, "-version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = (
        result.stdout.decode("utf-8", errors="replace")
        + result.stderr.decode("utf-8", errors="replace")
    )
    match = re.search(r'version "(\d+)', output)
    return result.returncode == 0 and match is not None and int(match.group(1)) >= 17


def find_java() -> str:
    candidates = [os.environ.get("GATK_JAVA", ""), "/opt/homebrew/opt/openjdk@17/bin/java", "/opt/homebrew/bin/java", command_path("java")]
    for candidate in candidates:
        if java_works(candidate):
            return candidate
    raise RuntimeError("GATK Mutect2 smoke requires Java 17+. Install with `brew install openjdk@17` or set GATK_JAVA.")


def reference_dict_path(fasta_path: str) -> str:
    return re.sub(r"\.(fa|fasta)$", ".dict", fasta_path, flags=re.I)


def download_if_missing(url: str, relative_path: str, label: str) -> bool:
    ensure_dir(path_from_root("/".join(relative_path.split("/")[:-1])))
    if path_from_root(relative_path).exists() and path_from_root(relative_path).stat().st_size > 0:
        return False
    tmp_path = f"{relative_path}.tmp"
    run_command(download_command(url, tmp_path, relative_path), f"{RESULTS_DIR}/logs/download.{label}.log")
    return True


def download_command(url: str, tmp_path: str, relative_path: str) -> str:
    return (
        "curl -L --fail --retry 8 --retry-all-errors --retry-delay 5 "
        "--connect-timeout 30 --speed-time 60 --speed-limit 1024 "
        f"-C - -o {quote_shell_arg(tmp_path)} {quote_shell_arg(url)} && "
        f"mv {quote_shell_arg(tmp_path)} {quote_shell_arg(relative_path)}"
    )


def file_summary(asset: dict[str, str]) -> dict:
    return {
        "kind": asset["kind"],
        "url": asset["url"],
        "path": asset["path"],
        "sizeBytes": path_from_root(asset["path"]).stat().st_size,
        "sha256": sha256_file(asset["path"]),
    }


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    ensure_dir(path_from_root(TOOL_ROOT))
    ensure_dir(path_from_root(SEQC2_TRUTH_ROOT))
    java_path = find_java()
    release = fetch_json(f"https://api.github.com/repos/broadinstitute/gatk/releases/tags/{GATK_VERSION}")
    asset = next((item for item in release.get("assets", []) if item.get("name") == f"gatk-{GATK_VERSION}.zip"), None)
    if not asset:
        raise RuntimeError(f"Could not find gatk-{GATK_VERSION}.zip in {release.get('html_url')}")
    downloaded_gatk = download_if_missing(asset["browser_download_url"], GATK_ZIP, "gatk")
    if not path_from_root(GATK_JAR).exists():
        run_command(f"unzip -q -o {quote_shell_arg(GATK_ZIP)} -d {quote_shell_arg(TOOL_ROOT)}", f"{RESULTS_DIR}/logs/unzip.gatk.log")
    if not path_from_root(GATK_JAR).exists():
        raise RuntimeError(f"GATK jar not found after unzip: {GATK_JAR}")

    full_references = parse_csv(read_text(path_from_root("manifests/full_reference_smoke_references.csv")))
    reference = next((row for row in full_references if row["reference_id"] == "ucsc_hg38_analysis_set_full"), None)
    if not reference:
        raise RuntimeError("Expected ucsc_hg38_analysis_set_full in manifests/full_reference_smoke_references.csv.")
    if not path_from_root(reference["fasta_path"]).exists():
        raise RuntimeError(f"Full reference FASTA is missing: {reference['fasta_path']}. Run fetch:full-reference-smoke first.")
    if sha256_file(reference["fasta_path"]) != reference["fasta_sha256"]:
        raise RuntimeError(f"Full reference FASTA sha256 changed for {reference['reference_id']}.")
    if not path_from_root(reference["fasta_fai_path"]).exists():
        run_command(
            f"samtools faidx {quote_shell_arg(reference['fasta_path'])}",
            f"{RESULTS_DIR}/logs/{reference['reference_id']}.samtools_faidx.log",
        )
    dict_path = reference_dict_path(reference["fasta_path"])
    created_dict = not path_from_root(dict_path).exists()
    if created_dict:
        run_command(
            f"{quote_shell_arg(java_path)} -jar {quote_shell_arg(GATK_JAR)} CreateSequenceDictionary -R {quote_shell_arg(reference['fasta_path'])} -O {quote_shell_arg(dict_path)}",
            f"{RESULTS_DIR}/logs/{reference['reference_id']}.create_sequence_dictionary.log",
        )

    downloaded_truth_assets = []
    for truth_asset in TRUTH_ASSETS:
        downloaded = download_if_missing(truth_asset["url"], truth_asset["path"], truth_asset["kind"])
        summary = file_summary(truth_asset)
        summary["downloaded"] = downloaded
        downloaded_truth_assets.append(summary)

    raw_panel = parse_csv(read_text(path_from_root("manifests/raw_representative_panel.csv")))
    selected = sorted([row for row in raw_panel if row["pair_id"] == PAIR_ID], key=lambda row: 0 if row["role"] == "tumor" else 1)
    if len(selected) != 2 or not any(row["role"] == "tumor" for row in selected) or not any(row["role"] == "normal" for row in selected):
        raise RuntimeError(f"Expected tumor and normal raw panel rows for {PAIR_ID}.")
    smoke_root = "data/raw/smoke/seqc2_hcc1395_production_somatic_smoke"
    sample_rows = []
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
                "source_fastq_1": row["fastq_1_url"],
                "source_fastq_2": row["fastq_2_url"],
                "read_pairs_per_end": READ_PAIRS_PER_END,
                "fastq_1": f"{smoke_root}/fastq/{row['run']}_R1.{READ_PAIRS_PER_END}reads.fastq",
                "fastq_2": f"{smoke_root}/fastq/{row['run']}_R2.{READ_PAIRS_PER_END}reads.fastq",
                "reference_id": reference["reference_id"],
                "assembly": reference["assembly"],
                "genome_build": reference["genome_build"],
                "reference_path": reference["fasta_path"],
                "reference_fai_path": reference["fasta_fai_path"],
                "reference_dict_path": dict_path,
                "reference_sha256": reference["fasta_sha256"],
                "brca_interval_bed_path": reference["interval_bed_path"],
                "brca_interval_regions": reference["interval_regions"],
                "brca_interval_genes": reference["interval_genes"],
                "known_sites_resource_path": "not_supplied_for_phase_2e_smoke",
                "germline_resource_path": "not_supplied_for_phase_2e_smoke",
                "panel_of_normals_path": "not_supplied_for_phase_2e_smoke",
                "truth_snv_vcf_path": next(asset["path"] for asset in TRUTH_ASSETS if asset["kind"] == "snv"),
                "truth_indel_vcf_path": next(asset["path"] for asset in TRUTH_ASSETS if asset["kind"] == "indel"),
                "truth_high_confidence_bed_path": next(
                    asset["path"] for asset in TRUTH_ASSETS if asset["kind"] == "high_confidence_regions"
                ),
                "gatk_jar_path": GATK_JAR,
                "java_path": java_path,
                "production_caller": "GATK Mutect2 + FilterMutectCalls",
                "read_group_id": f"{row['run']}.{row['role']}",
                "read_group_sample": sample_name,
                "read_group_library": row["run"],
                "read_group_platform": "ILLUMINA",
                "read_group_platform_unit": row["run"],
                "output_bam": f"{smoke_root}/{reference['reference_id']}/bam/{row['run']}.{row['role']}.bam",
                "output_bai": f"{smoke_root}/{reference['reference_id']}/bam/{row['run']}.{row['role']}.bam.bai",
                "caller_interval_strategy": "mapped-read active intervals, truth-overlap-prioritized when compatible",
                "caveat": "Phase 2E production-style somatic smoke uses a downsampled public SEQC2/HCC1395 WES pair. It validates Mutect2 plumbing and VCF/QC contracts, not full-depth sensitivity, HRD signatures, or clinical actionability.",
            }
        )
    write_csv(path_from_root("manifests/production_somatic_smoke_samplesheet.csv"), sample_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/asset_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "ready",
            "caller": "GATK Mutect2 + FilterMutectCalls",
            "gatk": {
                "version": GATK_VERSION,
                "releaseApi": f"https://api.github.com/repos/broadinstitute/gatk/releases/tags/{GATK_VERSION}",
                "releaseUrl": release["html_url"],
                "assetUrl": asset["browser_download_url"],
                "assetSizeBytes": asset["size"],
                "zipPath": GATK_ZIP,
                "zipSha256": sha256_file(GATK_ZIP),
                "jarPath": GATK_JAR,
                "jarSha256": sha256_file(GATK_JAR),
                "downloaded": downloaded_gatk,
            },
            "java": {"path": java_path, "version": capture_command(f"{quote_shell_arg(java_path)} -version 2>&1 | head -n 1")},
            "reference": {
                "referenceId": reference["reference_id"],
                "assembly": reference["assembly"],
                "genomeBuild": reference["genome_build"],
                "sourceUrl": reference["source_url"],
                "fastaPath": reference["fasta_path"],
                "fastaSha256": reference["fasta_sha256"],
                "faiPath": reference["fasta_fai_path"],
                "dictPath": dict_path,
                "dictSha256": sha256_file(dict_path),
                "dictCreated": created_dict,
                "brcaIntervalBedPath": reference["interval_bed_path"],
                "brcaIntervalRegions": reference["interval_regions"],
                "brcaIntervalGenes": reference["interval_genes"],
            },
            "seqc2Truth": {
                "sourceDirectory": "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/seqc/Somatic_Mutation_WG/release/latest/",
                "reference": "GRCh38.d1.vd1.fa per VCF header",
                "assets": downloaded_truth_assets,
            },
            "sampleRows": len(sample_rows),
            "readPairsPerEnd": READ_PAIRS_PER_END,
            "productionResourceCaveat": "Known-sites, germline-resource, contamination-estimation, and panel-of-normals resources are intentionally not supplied in this local smoke. They remain required for a full production clinical-grade workflow.",
        },
    )
    print(f"Production somatic assets ready for {len(sample_rows)} samples with GATK {GATK_VERSION}.")


if __name__ == "__main__":
    main()
