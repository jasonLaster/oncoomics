from __future__ import annotations

import gzip
import shutil
from typing import Any

from ...paths import path_from_root
from ...utils import (
    capture_command,
    command_path,
    ensure_dir,
    iso_now,
    md5_file,
    parse_csv,
    quote_shell_arg,
    read_json,
    read_text,
    run_command,
    sha256_file,
    write_csv,
    write_json,
)

PAIR_ID = "seqc2_hcc1395_wes_minimal_smoke"
RESULTS_DIR = "results/full_wes_benchmark"
FULL_WES_ROOT = "data/raw/full_wes/seqc2_hcc1395_wes_minimal"
SOMATIC_RESOURCE_ROOT = "data/raw/reference/gatk_best_practices/somatic-hg38"
PRODUCTION_ASSET_SUMMARY = "results/production_somatic_smoke/asset_summary.json"
RESOURCES = [
    {
        "kind": "mutect2_panel_of_normals",
        "url": "https://storage.googleapis.com/gatk-best-practices/somatic-hg38/1000g_pon.hg38.vcf.gz",
        "path": f"{SOMATIC_RESOURCE_ROOT}/1000g_pon.hg38.vcf.gz",
        "index_url": "https://storage.googleapis.com/gatk-best-practices/somatic-hg38/1000g_pon.hg38.vcf.gz.tbi",
        "index_path": f"{SOMATIC_RESOURCE_ROOT}/1000g_pon.hg38.vcf.gz.tbi",
    },
    {
        "kind": "common_biallelic_gnomad_resource",
        "url": "https://downloads.sourceforge.net/project/mutect2-data/common_biallelic/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.gz",
        "path": f"{SOMATIC_RESOURCE_ROOT}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.gz",
        "index_url": "https://downloads.sourceforge.net/project/mutect2-data/common_biallelic/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.idx",
        "index_path": f"{SOMATIC_RESOURCE_ROOT}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.idx",
        "usable_path": f"{SOMATIC_RESOURCE_ROOT}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf",
        "usable_index_path": f"{SOMATIC_RESOURCE_ROOT}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.idx",
    },
]


def reference_dict_path(fasta_path: str) -> str:
    for suffix in (".fasta", ".fa"):
        if fasta_path.lower().endswith(suffix):
            return f"{fasta_path[: -len(suffix)]}.dict"
    return f"{fasta_path}.dict"


def ensure_readable_gzip(relative_path: str, label: str) -> None:
    with gzip.open(path_from_root(relative_path), "rb") as handle:
        while handle.read(1024 * 1024):
            pass
    run_command(f"gzip -t {quote_shell_arg(relative_path)}", f"{RESULTS_DIR}/logs/{label}.gzip_test.log")


def download_resume(url: str, relative_path: str, label: str) -> dict[str, Any]:
    ensure_dir(path_from_root("/".join(relative_path.split("/")[:-1])))
    target = path_from_root(relative_path)
    before_bytes = target.stat().st_size if target.exists() else 0
    run_command(
        f"curl -L --fail --retry 5 --retry-delay 3 -C - -o {quote_shell_arg(relative_path)} {quote_shell_arg(url)}",
        f"{RESULTS_DIR}/logs/download.{label}.log",
    )
    after_bytes = target.stat().st_size
    return {"downloaded": after_bytes != before_bytes, "beforeBytes": before_bytes, "afterBytes": after_bytes}


def maybe_download_index(url: str, relative_path: str, label: str) -> dict[str, Any]:
    ensure_dir(path_from_root("/".join(relative_path.split("/")[:-1])))
    target = path_from_root(relative_path)
    before_bytes = target.stat().st_size if target.exists() else 0
    if before_bytes > 0:
        return {"indexStatus": "cached", "beforeBytes": before_bytes, "afterBytes": before_bytes}
    try:
        run_command(
            f"curl -L --fail --retry 3 --retry-delay 2 -C - -o {quote_shell_arg(relative_path)} {quote_shell_arg(url)}",
            f"{RESULTS_DIR}/logs/download.{label}.log",
        )
    except RuntimeError:
        return {"indexStatus": "not_available_from_source", "beforeBytes": before_bytes, "afterBytes": 0}
    return {
        "indexStatus": "downloaded_or_cached" if target.exists() and target.stat().st_size > 0 else "not_available_from_source",
        "beforeBytes": before_bytes,
        "afterBytes": target.stat().st_size if target.exists() else 0,
    }


def ensure_resource_index(vcf_path: str, index_path: str, label: str, java_path: str, gatk_jar: str) -> str:
    target = path_from_root(index_path)
    if target.exists() and target.stat().st_size > 0:
        return "present"
    if index_path.endswith(".idx"):
        run_command(
            f"{quote_shell_arg(java_path)} -jar {quote_shell_arg(gatk_jar)} IndexFeatureFile -I {quote_shell_arg(vcf_path)}",
            f"{RESULTS_DIR}/logs/{label}.gatk_index_feature_file.log",
        )
        alternate_index = path_from_root(f"{vcf_path}.idx")
        if not target.exists() and alternate_index.exists():
            shutil.copyfile(alternate_index, target)
        if not target.exists() or target.stat().st_size == 0:
            raise RuntimeError(f"GATK did not create expected index {index_path} for {vcf_path}.")
        return "created_with_gatk"
    run_command(f"bcftools index -t -f {quote_shell_arg(vcf_path)}", f"{RESULTS_DIR}/logs/{label}.bcftools_index.log")
    return "created_with_bcftools"


def ensure_uncompressed_vcf(gzip_path: str, vcf_path: str, label: str) -> str:
    target = path_from_root(vcf_path)
    if target.exists() and target.stat().st_size > 0:
        return "present"
    run_command(f"gunzip -c {quote_shell_arg(gzip_path)} > {quote_shell_arg(vcf_path)}", f"{RESULTS_DIR}/logs/{label}.uncompress_vcf.log")
    return "created"


def main() -> None:
    ensure_dir(path_from_root(RESULTS_DIR))
    ensure_dir(path_from_root(f"{RESULTS_DIR}/logs"))
    ensure_dir(path_from_root(FULL_WES_ROOT))
    ensure_dir(path_from_root(SOMATIC_RESOURCE_ROOT))

    if not path_from_root(PRODUCTION_ASSET_SUMMARY).exists():
        raise RuntimeError("Phase 2F requires Phase 2E production assets. Run fetch:production-somatic first.")
    production_assets = read_json(path_from_root(PRODUCTION_ASSET_SUMMARY))
    gatk_jar = str(production_assets.get("gatk", {}).get("jarPath", ""))
    java_path = str(production_assets.get("java", {}).get("path", ""))
    if not gatk_jar or not java_path:
        raise RuntimeError("Production asset summary is missing GATK or Java paths.")

    full_references = parse_csv(read_text(path_from_root("manifests/full_reference_smoke_references.csv")))
    reference = next((row for row in full_references if row["reference_id"] == "ucsc_hg38_analysis_set_full"), None)
    if not reference:
        raise RuntimeError("Expected ucsc_hg38_analysis_set_full in full-reference manifest.")

    raw_panel = parse_csv(read_text(path_from_root("manifests/raw_representative_panel.csv")))
    selected = sorted([row for row in raw_panel if row["pair_id"] == PAIR_ID], key=lambda row: 0 if row["role"] == "tumor" else 1)
    if len(selected) != 2 or not any(row["role"] == "tumor" for row in selected) or not any(row["role"] == "normal" for row in selected):
        raise RuntimeError(f"Expected tumor and normal rows for {PAIR_ID}.")

    fastq_assets: list[dict[str, Any]] = []
    for row in selected:
        for read in ("1", "2"):
            url = row[f"fastq_{read}_url"]
            expected_md5 = row[f"fastq_{read}_md5"]
            expected_bytes = int(row[f"fastq_{read}_bytes"])
            path = f"{FULL_WES_ROOT}/{row['run']}_R{read}.fastq.gz"
            cached = (
                path_from_root(path).exists() and path_from_root(path).stat().st_size == expected_bytes and md5_file(path) == expected_md5
            )
            download = (
                {"downloaded": False, "beforeBytes": expected_bytes, "afterBytes": expected_bytes}
                if cached
                else download_resume(url, path, f"{row['run']}.R{read}")
            )
            actual_md5 = md5_file(path)
            actual_bytes = path_from_root(path).stat().st_size
            if actual_md5 != expected_md5:
                raise RuntimeError(f"{path} md5 mismatch: {actual_md5} != {expected_md5}")
            if actual_bytes != expected_bytes:
                raise RuntimeError(f"{path} byte-size mismatch: {actual_bytes} != {expected_bytes}")
            ensure_readable_gzip(path, f"{row['run']}.R{read}")
            fastq_assets.append(
                {
                    "pair_id": row["pair_id"],
                    "sample": "HCC1395" if row["role"] == "tumor" else "HCC1395BL",
                    "role": row["role"],
                    "run_accession": row["run"],
                    "read": read,
                    "url": url,
                    "path": path,
                    "expected_md5": expected_md5,
                    "actual_md5": actual_md5,
                    "expected_bytes": expected_bytes,
                    "actual_bytes": actual_bytes,
                    "downloaded": download["downloaded"],
                    "gzip_test": "passed",
                }
            )

    resource_assets: list[dict[str, Any]] = []
    for resource in RESOURCES:
        resource_path = path_from_root(resource["path"])
        download = (
            {"downloaded": False, "beforeBytes": resource_path.stat().st_size, "afterBytes": resource_path.stat().st_size}
            if resource_path.exists() and resource_path.stat().st_size > 0
            else download_resume(resource["url"], resource["path"], resource["kind"])
        )
        ensure_readable_gzip(resource["path"], resource["kind"])
        index_download = maybe_download_index(resource["index_url"], resource["index_path"], f"{resource['kind']}.index")
        usable_path = resource.get("usable_path", resource["path"])
        usable_index_path = resource.get("usable_index_path", resource["index_path"])
        uncompressed_status = (
            ensure_uncompressed_vcf(resource["path"], usable_path, resource["kind"]) if "usable_path" in resource else "not_needed"
        )
        index_status = (
            "present_for_uncompressed_vcf"
            if "usable_path" in resource
            and path_from_root(usable_index_path).exists()
            and path_from_root(usable_index_path).stat().st_size > 0
            else ensure_resource_index(usable_path, usable_index_path, resource["kind"], java_path, gatk_jar)
        )
        resource_assets.append(
            {
                "kind": resource["kind"],
                "url": resource["url"],
                "path": resource["path"],
                "usable_path": usable_path,
                "size_bytes": path_from_root(resource["path"]).stat().st_size,
                "sha256": sha256_file(resource["path"]),
                "index_url": resource["index_url"],
                "index_path": resource["index_path"],
                "usable_index_path": usable_index_path,
                "index_status": index_status,
                "index_download_status": index_download["indexStatus"],
                "uncompressed_status": uncompressed_status,
                "usable_size_bytes": path_from_root(usable_path).stat().st_size,
                "usable_sha256": sha256_file(usable_path),
                "index_size_bytes": path_from_root(resource["index_path"]).stat().st_size,
                "index_sha256": sha256_file(resource["index_path"]),
                "downloaded": download["downloaded"],
            }
        )

    output_root = "data/raw/full_wes_benchmark/seqc2_hcc1395_wes_minimal"
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
                "source_read_pairs": row["spots"],
                "source_bases": row["bases"],
                "fastq_1": f"{FULL_WES_ROOT}/{row['run']}_R1.fastq.gz",
                "fastq_2": f"{FULL_WES_ROOT}/{row['run']}_R2.fastq.gz",
                "fastq_1_md5": row["fastq_1_md5"],
                "fastq_2_md5": row["fastq_2_md5"],
                "fastq_1_bytes": row["fastq_1_bytes"],
                "fastq_2_bytes": row["fastq_2_bytes"],
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
                "gatk_jar_path": gatk_jar,
                "java_path": java_path,
                "mutect2_germline_resource_path": "not_downloaded_for_phase_2f_local_gate_full_resource_is_3gb",
                "mutect2_germline_resource_source_url": "https://storage.googleapis.com/gatk-best-practices/somatic-hg38/af-only-gnomad.hg38.vcf.gz",
                "mutect2_panel_of_normals_path": f"{SOMATIC_RESOURCE_ROOT}/1000g_pon.hg38.vcf.gz",
                "common_biallelic_resource_path": f"{SOMATIC_RESOURCE_ROOT}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf",
                "common_biallelic_resource_index_path": f"{SOMATIC_RESOURCE_ROOT}/af-only-gnomad.hg38.common_biallelic.chr1-22XY.vcf.idx",
                "bqsr_known_sites_policy": "deferred_until_capture_intervals_and_matching_known_sites_are_selected",
                "contamination_policy": "estimate_with_common_biallelic_gnomad_sites_inside_phase_2f_benchmark_intervals_when_sites_overlap",
                "duplicate_marking_tool": "GATK MarkDuplicates",
                "production_caller": "GATK Mutect2 + FilterMutectCalls with hg38 PoN; common-biallelic gnomAD for contamination pileups",
                "read_group_id": f"{row['run']}.{row['role']}.full_wes",
                "read_group_sample": sample_name,
                "read_group_library": row["run"],
                "read_group_platform": "ILLUMINA",
                "read_group_platform_unit": row["run"],
                "raw_bam": f"{output_root}/{reference['reference_id']}/bam/{row['run']}.{row['role']}.raw.bam",
                "dedup_bam": f"{output_root}/{reference['reference_id']}/bam/{row['run']}.{row['role']}.dedup.bam",
                "dedup_bai": f"{output_root}/{reference['reference_id']}/bam/{row['run']}.{row['role']}.dedup.bai",
                "duplicate_metrics_path": f"{output_root}/{reference['reference_id']}/metrics/{row['run']}.{row['role']}.markduplicates.metrics.txt",
                "caveat": "Phase 2F uses full SEQC2/HCC1395 WES FASTQs and production-style resource-aware Mutect2 on covered truth-overlap intervals. It is not WGS HRD signature, CNV, or SV evidence.",
            }
        )

    write_csv(path_from_root("manifests/full_wes_benchmark_samplesheet.csv"), sample_rows)
    write_json(
        path_from_root(f"{RESULTS_DIR}/asset_summary.json"),
        {
            "generatedAt": iso_now(),
            "status": "ready",
            "pairId": PAIR_ID,
            "source": "ENA direct full FASTQ gzip files for SEQC2/HCC1395 minimal WES pair",
            "fullWesFastqs": fastq_assets,
            "resourcePolicy": {
                "duplicateMarking": "run GATK MarkDuplicates on full WES BAMs",
                "mutect2GermlineResource": "Broad gatk-best-practices somatic-hg38 af-only gnomAD",
                "mutect2PanelOfNormals": "Broad gatk-best-practices somatic-hg38 1000g PoN",
                "commonBiallelicResource": "common-biallelic af-only gnomAD chr1-22XY resource for GetPileupSummaries/contamination",
                "bqsr": "deferred until matching known-sites and capture interval policy are selected",
                "contamination": "run on benchmark intervals when common biallelic sites overlap",
                "intervalStrategy": "derive covered SEQC2 truth-overlap intervals from full WES BAMs; report sensitivity/precision only inside the bounded interval set",
            },
            "resources": resource_assets,
            "reference": {
                "referenceId": reference["reference_id"],
                "assembly": reference["assembly"],
                "genomeBuild": reference["genome_build"],
                "fastaPath": reference["fasta_path"],
                "fastaSha256": reference["fasta_sha256"],
                "dictPath": reference_dict_path(reference["fasta_path"]),
            },
            "tools": {
                "java": java_path,
                "gatkJar": gatk_jar,
                "bwa": command_path("bwa"),
                "samtools": command_path("samtools"),
                "bcftools": command_path("bcftools"),
            },
        },
    )
    capture_command("true")
    print(f"Full WES benchmark assets ready: {len(fastq_assets)} FASTQ files and {len(resource_assets)} Mutect2 resources.")


if __name__ == "__main__":
    main()
