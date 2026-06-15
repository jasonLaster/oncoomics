from __future__ import annotations

import hashlib
import tempfile
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, md5_file, parse_csv, read_text, sha256_file, write_csv, write_json, write_text
from .verify_known_answer_public_findings import CHECK_MANIFEST_PATH
from .verify_known_answer_sample_pull_plan import MANIFEST_PATH as PULL_PLAN_PATH

ASSET_ROOT = "data/raw/known_answer_public"
RESULTS_ROOT = "results/clinicalization"
EXECUTION_CSV_PATH = f"{RESULTS_ROOT}/known_answer_public_finding_execution.csv"
EXECUTION_JSON_PATH = f"{RESULTS_ROOT}/known_answer_public_finding_execution.json"
EXECUTION_MD_PATH = f"{RESULTS_ROOT}/known_answer_public_finding_execution.md"
REQUEST_TIMEOUT_SECONDS = 300

HG008_WGS_BASE = "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/NYGC_Illumina-WGS_20231023/"
HG008_RNA_BASE = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/NIST/HG008-T_bulk/20240508p21/UMD_RNA-seq_20250925/"
)
HG008_SMVAR_BASE = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/"
    "NIST_HG008-T_somatic-smvar_DraftBenchmark_V0.3-20260425/"
)
HG008_SV_CNV_BASE = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/analysis/"
    "NIST_HG008-T_somatic-stvar-CNV_DraftBenchmark_V0.5-20260318/"
)
COLO829_ENA_REPORT_URL = (
    "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=PRJEB27698&result=read_run&fields="
    "run_accession,sample_accession,sample_alias,fastq_ftp,fastq_md5,fastq_bytes,submitted_ftp,"
    "submitted_md5,submitted_bytes,library_layout,library_strategy,instrument_platform,instrument_model"
    "&format=tsv&limit=0"
)
COLO829_ZENODO_API_URL = "https://zenodo.org/api/records/7515830"
SERASEQ_PRODUCT_URL = "https://www.seracare.com/Seraseq-ctDNA-MRD-Panel-Mix-0710-2146/"
SERASEQ_PACKAGE_INSERT_URL = "https://www.seracare.com/globalassets/seracare-resources/pi-0710-2146-seraseq-ctdna-mrd-panel-mix.pdf"


@dataclass(frozen=True)
class AssetSpec:
    label: str
    url: str
    relative_path: str
    expected_md5: str = ""
    required: bool = True


@dataclass(frozen=True)
class ArtifactExecutionSpec:
    status: str
    asset_groups: tuple[str, ...]
    blocker_category: str
    blockers: tuple[str, ...]
    next_action: str


def _asset(group_root: str, label: str, url: str, filename: str, expected_md5: str = "", required: bool = True) -> AssetSpec:
    return AssetSpec(
        label=label, url=url, relative_path=f"{ASSET_ROOT}/{group_root}/{filename}", expected_md5=expected_md5, required=required
    )


ASSET_GROUPS: dict[str, tuple[AssetSpec, ...]] = {
    "hg008_wgs_metadata": (
        _asset("hg008/wgs", "hg008_wgs_directory_index", HG008_WGS_BASE, "index.html"),
        _asset("hg008/wgs", "hg008_wgs_readme", HG008_WGS_BASE + "README_NYGC.md", "README_NYGC.md"),
        _asset("hg008/wgs", "hg008_wgs_checksums", HG008_WGS_BASE + "checksums.md5", "checksums.md5"),
    ),
    "hg008_rna_metadata": (
        _asset("hg008/rna", "hg008_rna_directory_index", HG008_RNA_BASE, "index.html"),
        _asset("hg008/rna", "hg008_rna_readme", HG008_RNA_BASE + "README_UMD_20250925.md", "README_UMD_20250925.md"),
        _asset("hg008/rna", "hg008_rna_checksums", HG008_RNA_BASE + "checksums.md5", "checksums.md5"),
        _asset(
            "hg008/rna",
            "hg008_rna_fastq_1_stats",
            HG008_RNA_BASE + "XZOOK_20250905_A00904_IL23896-001_N4UD-C12_L001_R1_stats.txt",
            "XZOOK_20250905_A00904_IL23896-001_N4UD-C12_L001_R1_stats.txt",
        ),
        _asset(
            "hg008/rna",
            "hg008_rna_fastq_2_stats",
            HG008_RNA_BASE + "XZOOK_20250905_A00904_IL23896-001_N4UD-C12_L001_R2_stats.txt",
            "XZOOK_20250905_A00904_IL23896-001_N4UD-C12_L001_R2_stats.txt",
        ),
    ),
    "hg008_small_variant_truth": (
        _asset("hg008/small_variant_truth", "hg008_smvar_readme", HG008_SMVAR_BASE + "README.md", "README.md"),
        _asset(
            "hg008/small_variant_truth",
            "hg008_smvar_tumor_variants_vcf",
            HG008_SMVAR_BASE + "HG008-T_somatic_smvar_benchmark_v0.3_tumorvariants.vcf.gz",
            "HG008-T_somatic_smvar_benchmark_v0.3_tumorvariants.vcf.gz",
        ),
        _asset(
            "hg008/small_variant_truth",
            "hg008_smvar_tumor_variants_index",
            HG008_SMVAR_BASE + "HG008-T_somatic_smvar_benchmark_v0.3_tumorvariants.vcf.gz.tbi",
            "HG008-T_somatic_smvar_benchmark_v0.3_tumorvariants.vcf.gz.tbi",
        ),
        _asset(
            "hg008/small_variant_truth",
            "hg008_smvar_callable_all_bed",
            HG008_SMVAR_BASE + "HG008-T_somatic_smvar_benchmark_v0.3_all.bed",
            "HG008-T_somatic_smvar_benchmark_v0.3_all.bed",
        ),
        _asset(
            "hg008/small_variant_truth",
            "hg008_smvar_no_germline_interference_bed",
            HG008_SMVAR_BASE + "HG008-T_somatic_smvar_benchmark_v0.3_nogermlineinterference.bed",
            "HG008-T_somatic_smvar_benchmark_v0.3_nogermlineinterference.bed",
        ),
    ),
    "hg008_sv_cnv_truth": (
        _asset("hg008/sv_cnv_truth", "hg008_sv_cnv_readme", HG008_SV_CNV_BASE + "README.md", "README.md"),
        _asset("hg008/sv_cnv_truth", "hg008_sv_cnv_checksums", HG008_SV_CNV_BASE + "checksums.md5", "checksums.md5"),
        _asset(
            "hg008/sv_cnv_truth",
            "hg008_sv_pass_vcf",
            HG008_SV_CNV_BASE + "GRCh38_HG008-T-V0.5_somatic-stvar_PASS.draftbenchmark.vcf.gz",
            "GRCh38_HG008-T-V0.5_somatic-stvar_PASS.draftbenchmark.vcf.gz",
        ),
        _asset(
            "hg008/sv_cnv_truth",
            "hg008_sv_pass_index",
            HG008_SV_CNV_BASE + "GRCh38_HG008-T-V0.5_somatic-stvar_PASS.draftbenchmark.vcf.gz.tbi",
            "GRCh38_HG008-T-V0.5_somatic-stvar_PASS.draftbenchmark.vcf.gz.tbi",
        ),
        _asset(
            "hg008/sv_cnv_truth",
            "hg008_cnv_pass_bed",
            HG008_SV_CNV_BASE + "GRCh38_HG008-T-V0.5_somatic-CNV_PASS.draftbenchmark.calls.bed",
            "GRCh38_HG008-T-V0.5_somatic-CNV_PASS.draftbenchmark.calls.bed",
        ),
        _asset(
            "hg008/sv_cnv_truth",
            "hg008_cnv_all_bedpe",
            HG008_SV_CNV_BASE + "GRCh38_HG008-T-V0.5_somatic-CNV_ALL.draftbenchmark.calls.bedpe",
            "GRCh38_HG008-T-V0.5_somatic-CNV_ALL.draftbenchmark.calls.bedpe",
        ),
        _asset(
            "hg008/sv_cnv_truth",
            "hg008_cnv_column_descriptions",
            HG008_SV_CNV_BASE + "V0.5_CNV_BEDPE_BED_Column_Descriptions.xlsx",
            "V0.5_CNV_BEDPE_BED_Column_Descriptions.xlsx",
        ),
    ),
    "colo829_ena_metadata": (
        _asset("colo829/ena", "colo829_ena_prjeb27698_filereport", COLO829_ENA_REPORT_URL, "PRJEB27698_filereport.tsv"),
    ),
    "colo829_sv_cna_truth": (
        _asset("colo829/sv_cna_truth", "colo829_zenodo_record_json", COLO829_ZENODO_API_URL, "zenodo_7515830.json"),
        _asset(
            "colo829/sv_cna_truth",
            "colo829_hg38_lifted_sv_truth",
            "https://zenodo.org/api/records/7515830/files/truthset_somaticSVs_COLO829_hg38lifted.vcf/content",
            "truthset_somaticSVs_COLO829_hg38lifted.vcf",
            expected_md5="504e4ca4bd285706c261f93be1f33a95",
        ),
        _asset(
            "colo829/sv_cna_truth",
            "colo829_copy_number_truth_zip",
            "https://zenodo.org/api/records/7515830/files/COLO829_somaticSV_copynumber.zip/content",
            "COLO829_somaticSV_copynumber.zip",
            expected_md5="156544f39152dca24694c0afc3247d40",
        ),
    ),
    "seraseq_public_docs": (
        _asset("seraseq_mrd/public_docs", "seraseq_product_page", SERASEQ_PRODUCT_URL, "product_page.html", required=False),
        _asset(
            "seraseq_mrd/public_docs",
            "seraseq_package_insert",
            SERASEQ_PACKAGE_INSERT_URL,
            "pi-0710-2146-seraseq-ctdna-mrd-panel-mix.pdf",
            required=False,
        ),
    ),
}


ARTIFACT_EXECUTION_SPECS: dict[str, ArtifactExecutionSpec] = {
    "results/clinicalization/known_answer_runs/hg008/input_provenance_summary.json": ArtifactExecutionSpec(
        status="not_confirmed_input_metadata_only",
        asset_groups=("hg008_wgs_metadata",),
        blocker_category="raw_input_and_runner_gap",
        blockers=(
            "HG008 WGS inputs are public but hundreds of gigabytes across FASTQ/BAM assets.",
            "benchmark:known-answer non-dry execution is not implemented for hg008_small_variants.",
            "No tumor-normal alignment/calling/comparison artifact has been generated from the downloaded metadata.",
        ),
        next_action="Approve transfer plan, fetch HG008-T and HG008-N-D WGS inputs, then implement the non-dry benchmark runner and concordance adapter.",
    ),
    "results/clinicalization/known_answer_runs/hg008/rna_qc_summary.json": ArtifactExecutionSpec(
        status="not_confirmed_input_metadata_only",
        asset_groups=("hg008_rna_metadata",),
        blocker_category="raw_input_and_runner_gap",
        blockers=(
            "HG008-T RNA FASTQs are public but multi-gigabyte inputs.",
            "No HG008 RNA smoke runner or quantification truth target is implemented.",
        ),
        next_action="Approve RNA transfer, fetch the selected HG008-T RNA FASTQs, and add the RNA QC or quantification smoke gate.",
    ),
    "results/clinicalization/known_answer_runs/hg008/small_variant_concordance_summary.json": ArtifactExecutionSpec(
        status="not_confirmed_truth_assets_verified",
        asset_groups=("hg008_small_variant_truth", "hg008_wgs_metadata"),
        blocker_category="truth_assets_without_pipeline_calls",
        blockers=(
            "HG008 v0.3 small-variant truth assets were fetched, but no Diana-generated HG008 callset exists.",
            "benchmark:known-answer non-dry execution is not implemented for hg008_small_variants.",
        ),
        next_action="Run HG008 tumor-normal WGS through the small-variant caller and compare against the v0.3 truth VCF/callable BED.",
    ),
    "results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json": ArtifactExecutionSpec(
        status="not_confirmed_truth_assets_verified",
        asset_groups=("hg008_sv_cnv_truth", "hg008_wgs_metadata"),
        blocker_category="truth_assets_without_pipeline_calls",
        blockers=(
            "HG008 v0.5 SV/CNV truth assets were fetched, but no Diana-generated HG008 SV/CNV callset exists.",
            "benchmark:known-answer non-dry execution is not implemented for hg008_sv_cnv.",
        ),
        next_action="Run HG008 tumor-normal WGS through SV/CNV callers and compare using reciprocal-overlap rules.",
    ),
    "results/clinicalization/known_answer_runs/colo829/input_provenance_summary.json": ArtifactExecutionSpec(
        status="not_confirmed_input_metadata_only",
        asset_groups=("colo829_ena_metadata",),
        blocker_category="raw_input_and_runner_gap",
        blockers=(
            "COLO829/COLO829BL WGS inputs are public in ENA but each selected FASTQ/BAM is tens to hundreds of gigabytes.",
            "benchmark:known-answer non-dry execution is not implemented for colo829_driver_signature.",
            "No tumor-normal driver/signature artifact has been generated from the COLO829 inputs.",
        ),
        next_action="Approve COLO829 transfer, fetch selected tumor-normal WGS inputs, then implement the driver/signature guardrail run.",
    ),
    "results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json": ArtifactExecutionSpec(
        status="not_confirmed_truth_assets_verified",
        asset_groups=("colo829_sv_cna_truth", "colo829_ena_metadata"),
        blocker_category="truth_assets_without_pipeline_calls",
        blockers=(
            "COLO829 SV/CNA truth assets were fetched, but no Diana-generated COLO829 SV/CNA callset exists.",
            "benchmark:known-answer non-dry execution is not implemented for colo829_sv_cna.",
        ),
        next_action="Run COLO829 tumor-normal WGS through SV/CNA callers and compare against the Zenodo truth assets.",
    ),
    "results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json": ArtifactExecutionSpec(
        status="not_confirmed_input_metadata_only",
        asset_groups=("colo829_ena_metadata", "colo829_sv_cna_truth"),
        blocker_category="raw_input_and_runner_gap",
        blockers=(
            "Selected COLO829 dilution inputs are public in ENA but are large WGS files.",
            "benchmark:known-answer non-dry execution is not implemented for colo829_purity_series.",
            "No recall table exists to test monotonic sensitivity across purity levels.",
        ),
        next_action="Approve selected dilution transfers, run each level, and compute truth-overlap recall by tumor fraction.",
    ),
    "results/clinicalization/known_answer_runs/seraseq_mrd/positive_negative_summary.json": ArtifactExecutionSpec(
        status="blocked_request_or_purchase",
        asset_groups=("seraseq_public_docs",),
        blocker_category="request_or_purchase_required",
        blockers=(
            "Seraseq ctDNA MRD material and variant files are not freely downloadable public analysis inputs.",
            "Assay-specific acceptance ranges and sequencing design are not established for Diana Omics.",
        ),
        next_action="Request or purchase Seraseq material or variant files, then define assay-specific positive-negative and dilution gates.",
    ),
}


def pull_plan_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(PULL_PLAN_PATH)))


def check_rows() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(CHECK_MANIFEST_PATH)))


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "diana-omics-known-answer-validation/1.0"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return cast(bytes, response.read())


def download_asset(asset: AssetSpec) -> dict[str, Any]:
    target = path_from_root(asset.relative_path)
    ensure_dir(target.parent)
    before_bytes = target.stat().st_size if target.exists() else 0
    if before_bytes > 0:
        actual_md5 = md5_file(asset.relative_path)
        if asset.expected_md5 and actual_md5 != asset.expected_md5:
            target.unlink()
        else:
            return {
                "label": asset.label,
                "url": asset.url,
                "path": asset.relative_path,
                "required": "yes" if asset.required else "no",
                "status": "cached",
                "downloaded": "no",
                "bytes": before_bytes,
                "md5": actual_md5,
                "sha256": sha256_file(asset.relative_path),
                "expected_md5": asset.expected_md5,
                "error": "",
            }
    try:
        payload = _download_bytes(asset.url)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {
            "label": asset.label,
            "url": asset.url,
            "path": asset.relative_path,
            "required": "yes" if asset.required else "no",
            "status": "download_failed",
            "downloaded": "no",
            "bytes": 0,
            "md5": "",
            "sha256": "",
            "expected_md5": asset.expected_md5,
            "error": str(error),
        }

    digest = hashlib.md5(payload).hexdigest()
    if asset.expected_md5 and digest != asset.expected_md5:
        return {
            "label": asset.label,
            "url": asset.url,
            "path": asset.relative_path,
            "required": "yes" if asset.required else "no",
            "status": "checksum_mismatch",
            "downloaded": "yes",
            "bytes": len(payload),
            "md5": digest,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "expected_md5": asset.expected_md5,
            "error": f"md5 mismatch: {digest} != {asset.expected_md5}",
        }

    with tempfile.NamedTemporaryFile(delete=False, dir=str(target.parent)) as handle:
        handle.write(payload)
        temporary_path = Path(handle.name)
    temporary_path.replace(target)
    return {
        "label": asset.label,
        "url": asset.url,
        "path": asset.relative_path,
        "required": "yes" if asset.required else "no",
        "status": "downloaded",
        "downloaded": "yes",
        "bytes": len(payload),
        "md5": digest,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "expected_md5": asset.expected_md5,
        "error": "",
    }


def _artifact_checks(checks: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    by_artifact: dict[str, list[dict[str, str]]] = defaultdict(list)
    for check in checks:
        by_artifact[check["analysis_artifact_path"]].append(check)
    return dict(by_artifact)


def _artifact_status(spec: ArtifactExecutionSpec, assets: list[dict[str, Any]]) -> str:
    required_errors = [asset for asset in assets if asset.get("required") == "yes" and asset.get("status") not in {"cached", "downloaded"}]
    if required_errors:
        return "blocked_source_download_failed"
    return spec.status


def _download_asset_groups(group_ids: tuple[str, ...], cache: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for group_id in group_ids:
        for asset in ASSET_GROUPS[group_id]:
            cached = cache.get(asset.relative_path)
            if cached is None:
                cached = download_asset(asset)
                cache[asset.relative_path] = cached
            assets.append(cached)
    return assets


def write_artifact(
    artifact_path: str,
    checks: list[dict[str, str]],
    pull_by_id: dict[str, dict[str, str]],
    spec: ArtifactExecutionSpec,
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    status = _artifact_status(spec, assets)
    successful_assets = [asset for asset in assets if asset.get("status") in {"cached", "downloaded"}]
    artifact = {
        "generatedAt": iso_now(),
        "status": status,
        "executionMode": "non_dry_public_asset_fetch_and_gap_analysis",
        "pipelineConfirmation": "not_confirmed",
        "clinicalUseAllowed": "no",
        "artifactPath": artifact_path,
        "checkIds": [check["check_id"] for check in checks],
        "pullIds": [check["pull_id"] for check in checks],
        "sampleOrAssetIds": [pull_by_id[check["pull_id"]]["sample_or_asset_id"] for check in checks],
        "datasetIds": sorted({check["dataset_id"] for check in checks}),
        "publicFindings": [check["public_finding"] for check in checks],
        "sourceUrls": sorted({check["source_url"] for check in checks}),
        "evidenceAssets": assets,
        "evidenceAssetCount": len(successful_assets),
        "downloadErrorCount": len(assets) - len(successful_assets),
        "blockerCategory": spec.blocker_category,
        "blockers": list(spec.blockers),
        "nextAction": spec.next_action,
    }
    write_json(path_from_root(artifact_path), artifact)
    return artifact


def write_markdown(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Known-Answer Public Finding Execution",
        "",
        "This generated report records the non-dry public asset fetch and the remaining pipeline-validation gaps for each target.",
        "",
        f"- Status: `{summary['status']}`",
        f"- Targets exercised: `{summary['target_count']}`",
        f"- Pipeline confirmations: `{summary['confirmed_count']}`",
        f"- Gap-identified targets: `{summary['gap_identified_count']}`",
        f"- Request or purchase blockers: `{summary['blocked_request_or_purchase_count']}`",
        "",
        "| Pull target | Execution status | Public assets | Pipeline confirmation | Primary gap | Next action |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["pull_id"]),
                    str(row["execution_status"]),
                    str(row["evidence_asset_count"]),
                    str(row["pipeline_confirmation"]),
                    str(row["blocker_category"]),
                    str(row["next_action"]),
                ]
            )
            + " |"
        )
    write_text(path_from_root(EXECUTION_MD_PATH), "\n".join(lines))


def build_execution() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pulls = pull_plan_rows()
    checks = check_rows()
    pull_by_id = {row["pull_id"]: row for row in pulls}
    checks_by_artifact = _artifact_checks(checks)
    asset_cache: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []

    for artifact_path, grouped_checks in checks_by_artifact.items():
        spec = ARTIFACT_EXECUTION_SPECS.get(artifact_path)
        if spec is None:
            raise RuntimeError(f"No execution spec registered for {artifact_path}.")
        assets = _download_asset_groups(spec.asset_groups, asset_cache)
        artifacts[artifact_path] = write_artifact(artifact_path, grouped_checks, pull_by_id, spec, assets)

    for check in checks:
        artifact = artifacts[check["analysis_artifact_path"]]
        rows.append(
            {
                "check_id": check["check_id"],
                "pull_id": check["pull_id"],
                "dataset_id": check["dataset_id"],
                "sample_or_asset_id": pull_by_id[check["pull_id"]]["sample_or_asset_id"],
                "analysis_artifact_path": check["analysis_artifact_path"],
                "execution_status": artifact["status"],
                "pipeline_confirmation": artifact["pipelineConfirmation"],
                "evidence_asset_count": artifact["evidenceAssetCount"],
                "download_error_count": artifact["downloadErrorCount"],
                "blocker_category": artifact["blockerCategory"],
                "next_action": artifact["nextAction"],
                "clinical_use_allowed": "no",
            }
        )

    return rows, list(artifacts.values())


def main() -> None:
    rows, artifacts = build_execution()
    confirmed_count = sum(1 for row in rows if row["pipeline_confirmation"] == "confirmed")
    blocked_request_or_purchase_count = sum(1 for row in rows if row["execution_status"] == "blocked_request_or_purchase")
    gap_identified_count = len(rows) - confirmed_count - blocked_request_or_purchase_count
    asset_rows = [asset for artifact in artifacts for asset in artifact["evidenceAssets"]]
    summary = {
        "status": "completed_with_gaps",
        "target_count": len(rows),
        "artifact_count": len(artifacts),
        "confirmed_count": confirmed_count,
        "gap_identified_count": gap_identified_count,
        "blocked_request_or_purchase_count": blocked_request_or_purchase_count,
        "public_asset_count": len(asset_rows),
        "public_asset_downloaded_count": sum(1 for asset in asset_rows if asset.get("status") == "downloaded"),
        "public_asset_cached_count": sum(1 for asset in asset_rows if asset.get("status") == "cached"),
        "public_asset_error_count": sum(1 for asset in asset_rows if asset.get("status") not in {"cached", "downloaded"}),
        "ready_for_clinical_interpretation": "no",
        "next_step": "Implement non-dry HG008/COLO829 runners, approve large raw-input transfers, and obtain Seraseq material or variant files before claiming public-finding confirmation.",
    }
    write_csv(path_from_root(EXECUTION_CSV_PATH), rows)
    write_json(
        path_from_root(EXECUTION_JSON_PATH),
        {"generatedAt": iso_now(), "status": summary["status"], "summary": summary, "rows": rows, "artifacts": artifacts},
    )
    write_markdown(rows, summary)
    print(
        "Known-answer public finding execution completed with gaps: "
        f"{confirmed_count}/{len(rows)} pipeline-confirmed; "
        f"{gap_identified_count} gap-identified; "
        f"{blocked_request_or_purchase_count} request/purchase-blocked."
    )


if __name__ == "__main__":
    main()
