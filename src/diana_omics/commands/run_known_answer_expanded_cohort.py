from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ..paths import path_from_root
from ..utils import iso_now, parse_csv, read_json, read_text, round_value, write_csv, write_json, write_text
from . import run_known_answer_bounded_non_dry as bounded

PLAN_PATH = "manifests/known_answer_expanded_cohort_plan.csv"
RESULTS_ROOT = "results/clinicalization"
RUN_ROOT = f"{RESULTS_ROOT}/known_answer_runs/expanded_cohort"
EXECUTION_CSV_PATH = f"{RESULTS_ROOT}/known_answer_expanded_cohort_execution.csv"
EXECUTION_JSON_PATH = f"{RESULTS_ROOT}/known_answer_expanded_cohort_execution.json"
EXECUTION_MD_PATH = f"{RESULTS_ROOT}/known_answer_expanded_cohort_execution.md"

HCC1395_WES_SUMMARY = "results/full_wes_benchmark/full_wes_benchmark_summary.json"
HCC1395_WGS_SUMMARY_CANDIDATES = (
    "artifacts/phase3_wgs_selective5/results/phase3_wgs_smoke/phase3_wgs_summary.json",
    "results/phase3_wgs_smoke/phase3_wgs_summary.json",
)
HG008_EXPANDED_VARIANT_LIMIT = int(os.environ.get("KNOWN_ANSWER_EXPANDED_HG008_VARIANT_LIMIT", "40"))
HG008_CNV_WINDOW_BASES = int(os.environ.get("KNOWN_ANSWER_EXPANDED_CNV_WINDOW_BASES", "1000"))
REQUIRED_PUBLIC_ASSETS = (
    bounded.HG008_SMALL_VARIANT_VCF,
    bounded.HG008_CNV_BED,
    bounded.COLO829_ENA_REPORT,
    bounded.COLO829_SV_CNA_TRUTH,
    bounded.COLO829_COPY_NUMBER_TRUTH_ZIP,
)

COLO829_PLATFORM_PAIRS = {
    "colo829_platform_illumina_hiseqx": {
        "label": "Illumina HiSeq X",
        "region": "7:140453136-140453136",
        "tumor_bam": "https://ftp.sra.ebi.ac.uk/vol1/run/ERR275/ERR2752450/COLO829T_dedup.realigned.bam",
        "normal_bam": "https://ftp.sra.ebi.ac.uk/vol1/run/ERR275/ERR2752449/COLO829R_dedup.realigned.bam",
    },
    "colo829_platform_pacbio_sequel": {
        "label": "PacBio Sequel",
        "region": "chr7:140453136-140453136",
        "tumor_bam": "https://ftp.sra.ebi.ac.uk/vol1/run/ERR280/ERR2808248/hg19.COLO_829T.bam",
        "normal_bam": "https://ftp.sra.ebi.ac.uk/vol1/run/ERR280/ERR2808247/hg19.COLO_829N.bam",
    },
    "colo829_platform_ont_minion": {
        "label": "Oxford Nanopore MinION",
        "region": "7:140453136-140453136",
        "tumor_bam": "https://ftp.sra.ebi.ac.uk/vol1/run/ERR275/ERR2752452/colo829.tumor.ngmlr.sorted.merged.bam",
        "normal_bam": "https://ftp.sra.ebi.ac.uk/vol1/run/ERR275/ERR2752451/colo829.normal.ngmlr.sorted.bam",
    },
    "colo829_platform_illumina_novaseq_phased": {
        "label": "Illumina NovaSeq phased",
        "region": "7:140453136-140453136",
        "tumor_bam": "https://ftp.sra.ebi.ac.uk/vol1/run/ERR282/ERR2820167/phased_possorted_bamCOLO829T.bam",
        "normal_bam": "https://ftp.sra.ebi.ac.uk/vol1/run/ERR282/ERR2820166/phased_possorted_bamCOLO829R.bam",
    },
}


@dataclass(frozen=True)
class ProbeResult:
    status: str
    pipeline_confirmation: str
    public_documentation_alignment: str
    evidence_type: str
    public_finding_result: str
    evidence: dict[str, Any]
    blockers: tuple[str, ...] = ()
    next_action: str = ""
    artifact_path: str = ""


def _read_manifest() -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(PLAN_PATH)))


def _read_json_if_present(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.is_file():
        return {}
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def _artifact_exists(relative_path: str) -> bool:
    return path_from_root(relative_path).is_file()


def _ensure_public_assets() -> None:
    missing = [relative_path for relative_path in REQUIRED_PUBLIC_ASSETS if not _artifact_exists(relative_path)]
    if not missing:
        return
    from .run_known_answer_public_findings import main as run_known_answer_public_findings

    run_known_answer_public_findings()


def _write_probe_artifact(probe_key: str, result: ProbeResult) -> ProbeResult:
    artifact_path = f"{RUN_ROOT}/{probe_key}.json"
    payload = {
        "generatedAt": iso_now(),
        "probeKey": probe_key,
        "status": result.status,
        "pipelineConfirmation": result.pipeline_confirmation,
        "clinicalUseAllowed": "no",
        "publicDocumentationAlignment": result.public_documentation_alignment,
        "evidenceType": result.evidence_type,
        "publicFindingResult": result.public_finding_result,
        "evidence": result.evidence,
        "blockers": list(result.blockers),
        "nextAction": result.next_action,
    }
    write_json(path_from_root(artifact_path), payload)
    return ProbeResult(
        status=result.status,
        pipeline_confirmation=result.pipeline_confirmation,
        public_documentation_alignment=result.public_documentation_alignment,
        evidence_type=result.evidence_type,
        public_finding_result=result.public_finding_result,
        evidence=result.evidence,
        blockers=result.blockers,
        next_action=result.next_action,
        artifact_path=artifact_path,
    )


def _hcc1395_wes_summary() -> ProbeResult:
    summary = _read_json_if_present(HCC1395_WES_SUMMARY)
    passed = (
        summary.get("status") == "passed"
        and summary.get("readyForPhase3") is True
        and summary.get("bamValidationStatus") == "passed"
        and int(summary.get("fullWesFastqsValidated") or 0) >= 4
        and int(summary.get("exactPassTruthMatches") or 0) > 0
    )
    return ProbeResult(
        status="expanded_non_dry_passed" if passed else "expanded_non_dry_gap_identified",
        pipeline_confirmation="full_wes_public_truth_confirmed" if passed else "not_confirmed",
        public_documentation_alignment="aligned" if passed else "gap",
        evidence_type="existing_full_wes_non_dry_artifact",
        public_finding_result=(
            "SEQC2/HCC1395 full WES benchmark passed with "
            f"{summary.get('exactPassTruthMatches', 0)} exact truth matches and "
            f"{summary.get('exactPassPrecision', '')} precision."
        )
        if passed
        else "SEQC2/HCC1395 WES benchmark artifact is missing or incomplete.",
        evidence={"summaryPath": HCC1395_WES_SUMMARY, "summary": summary},
        blockers=() if passed else ("Run fetch:full-wes and benchmark:full-wes with public HCC1395 inputs.",),
        next_action="" if passed else "Regenerate the WES benchmark summary from full public FASTQs.",
    )


def _best_hcc1395_wgs_summary() -> tuple[str, dict[str, Any]]:
    first_present: tuple[str, dict[str, Any]] = ("", {})
    for relative_path in HCC1395_WGS_SUMMARY_CANDIDATES:
        summary = _read_json_if_present(relative_path)
        if not summary:
            continue
        if not first_present[0]:
            first_present = (relative_path, summary)
        if summary.get("fullSourceFastqs") is True or summary.get("readPairsMode") == "full":
            return relative_path, summary
    return first_present


def _hcc1395_wgs_summary() -> ProbeResult:
    summary_path, summary = _best_hcc1395_wgs_summary()
    full_source = summary.get("fullSourceFastqs") is True or summary.get("readPairsMode") == "full"
    passed = (
        summary.get("status") == "passed"
        and summary.get("phase3Complete") is True
        and full_source
        and summary.get("coverageCnvStatus") == "passed"
        and summary.get("sbs96MatrixStatus") == "passed"
        and summary.get("svEvidenceStatus") == "passed"
    )
    stale_top_level = _read_json_if_present("results/phase3_wgs_smoke/phase3_wgs_summary.json")
    stale_is_bounded = bool(stale_top_level) and stale_top_level.get("fullSourceFastqs") is not True
    evidence = {
        "summaryPath": summary_path,
        "summary": summary,
        "topLevelSummaryIsBounded": stale_is_bounded,
        "topLevelReadPairsPerEnd": stale_top_level.get("readPairsPerEnd", ""),
    }
    return ProbeResult(
        status="expanded_non_dry_passed" if passed else "expanded_non_dry_gap_identified",
        pipeline_confirmation="full_wgs_public_truth_confirmed" if passed else "not_confirmed",
        public_documentation_alignment="aligned" if passed else "gap",
        evidence_type="existing_full_source_wgs_non_dry_artifact",
        public_finding_result=(
            "SEQC2/HCC1395 full-source WGS artifact passed with "
            f"{summary.get('exactPassTruthMatches', 0)} exact truth matches, "
            f"{summary.get('coverageCnvBins', 0)} CNV bins, "
            f"{summary.get('sbs96UsableSnvRecords', 0)} SBS96 SNVs, and SV evidence."
        )
        if passed
        else "SEQC2/HCC1395 WGS full-source artifact is missing or not marked full-source.",
        evidence=evidence,
        blockers=() if passed else ("Run full-source Phase 3 WGS and keep fullSourceFastqs=true in the summary.",),
        next_action="" if passed else "Regenerate Phase 3 WGS with --phase3_reads full and publish the summary.",
    )


def _run_hg008_variant_panel(limit: int) -> dict[str, Any]:
    variants = bounded._load_hg008_snv_records(limit)
    rows: list[dict[str, Any]] = []
    for variant in variants:
        region = f"{variant.chrom}:{variant.pos}-{variant.pos}"
        pileup = bounded._pileup_locus(region, variant.ref, variant.alt, (bounded.HG008_TUMOR_BAM, bounded.HG008_NORMAL_BAM))
        samples = pileup.get("samples", [])
        tumor = samples[0] if samples else {}
        normal = samples[1] if len(samples) > 1 else {}
        tumor_alt_fraction = float(tumor.get("altFraction") or 0)
        normal_alt_fraction = float(normal.get("altFraction") or 0)
        rows.append(
            {
                "chrom": variant.chrom,
                "pos": variant.pos,
                "ref": variant.ref,
                "alt": variant.alt,
                "pileupStatus": pileup.get("status"),
                "tumorDepth": tumor.get("depth", 0),
                "tumorAltCount": tumor.get("altCount", 0),
                "tumorAltFraction": tumor.get("altFraction", 0),
                "normalDepth": normal.get("depth", 0),
                "normalAltCount": normal.get("altCount", 0),
                "normalAltFraction": normal.get("altFraction", 0),
                "passed": (
                    pileup.get("status") == "passed"
                    and int(tumor.get("depth") or 0) >= 20
                    and int(normal.get("depth") or 0) >= 20
                    and tumor_alt_fraction >= 0.2
                    and normal_alt_fraction <= 0.05
                ),
                "elapsedSeconds": pileup.get("elapsedSeconds", ""),
                "stderr": pileup.get("stderr", ""),
            }
        )
    passed_count = sum(1 for row in rows if row["passed"])
    return {
        "truthVcf": bounded.HG008_SMALL_VARIANT_VCF,
        "tumorBam": bounded.HG008_TUMOR_BAM,
        "normalBam": bounded.HG008_NORMAL_BAM,
        "variantLimit": limit,
        "evaluatedVariantCount": len(rows),
        "passedVariantCount": passed_count,
        "failedVariantCount": len(rows) - passed_count,
        "allVariantsPassed": bool(rows) and passed_count == len(rows),
        "rows": rows,
    }


def _hg008_snv_panel() -> ProbeResult:
    panel = _run_hg008_variant_panel(HG008_EXPANDED_VARIANT_LIMIT)
    passed = panel["allVariantsPassed"] and panel["evaluatedVariantCount"] >= HG008_EXPANDED_VARIANT_LIMIT
    return ProbeResult(
        status="expanded_non_dry_passed" if passed else "expanded_non_dry_gap_identified",
        pipeline_confirmation="bounded_expanded_snv_panel_confirmed" if passed else "not_confirmed",
        public_documentation_alignment="aligned" if passed else "gap",
        evidence_type="truth_vcf_remote_bam_pileup",
        public_finding_result=f"{panel['passedVariantCount']}/{panel['evaluatedVariantCount']} HG008 truth SNVs passed tumor ALT and normal REF pileup gates.",
        evidence={"variantPanel": panel},
        blockers=() if passed else ("Expanded HG008 SNV panel did not fully pass bounded pileup gates.",),
        next_action="Promote to strict recall precision only after caller output is generated.",
    )


def _bed_rows(relative_path: str) -> list[list[str]]:
    return [line.split("\t") for line in read_text(path_from_root(relative_path)).splitlines() if line.strip()]


def _select_cnv_by_copy(rows: list[list[str]], copy_total: str) -> list[str]:
    candidates = [row for row in rows if len(row) >= 7 and row[3] == copy_total]
    if not candidates:
        raise RuntimeError(f"No HG008 CNV interval found for copy_total={copy_total}.")
    large_candidates = [row for row in candidates if int(row[2]) - int(row[1]) >= 100_000]
    return max(large_candidates or candidates, key=lambda row: int(row[2]) - int(row[1]))


def _probe_cnv_interval(row: list[str], neutral_ratio: float) -> dict[str, Any]:
    start = bounded._interior_window_start(row, HG008_CNV_WINDOW_BASES)
    depth = bounded._depth_region(row[0], start, start + HG008_CNV_WINDOW_BASES)
    ratio = float(depth.get("tumorNormalRatio") or 0)
    normalized = ratio / neutral_ratio if neutral_ratio else 0.0
    copy_total = int(row[3])
    if copy_total < 2:
        passed = depth.get("status") == "passed" and normalized < 0.85
        expected = "below_neutral"
    elif copy_total > 2:
        passed = depth.get("status") == "passed" and normalized > 1.05
        expected = "above_neutral"
    else:
        passed = depth.get("status") == "passed"
        expected = "neutral"
    return {
        "chrom": row[0],
        "start": int(row[1]),
        "end": int(row[2]),
        "copyTotal": row[3],
        "minorCopy": row[4],
        "majorCopy": row[5],
        "eventId": row[6],
        "depth": depth,
        "normalizedTumorNormalRatio": round_value(normalized, 6),
        "expectedDirection": expected,
        "passed": passed,
    }


def _hg008_cnv_sweep() -> ProbeResult:
    rows = _bed_rows(bounded.HG008_CNV_BED)
    neutral = _select_cnv_by_copy(rows, "2")
    neutral_start = bounded._interior_window_start(neutral, HG008_CNV_WINDOW_BASES)
    neutral_depth = bounded._depth_region(neutral[0], neutral_start, neutral_start + HG008_CNV_WINDOW_BASES)
    neutral_ratio = float(neutral_depth.get("tumorNormalRatio") or 0)
    intervals = [_select_cnv_by_copy(rows, copy_total) for copy_total in ("0", "1", "3", "4")]
    probes = [_probe_cnv_interval(row, neutral_ratio) for row in intervals]
    passed_count = sum(1 for probe in probes if probe["passed"])
    partial = passed_count >= 2
    passed = passed_count == len(probes)
    return ProbeResult(
        status="expanded_non_dry_passed" if passed else "expanded_non_dry_partial" if partial else "expanded_non_dry_gap_identified",
        pipeline_confirmation="bounded_expanded_cnv_depth_confirmed"
        if passed
        else "bounded_partial_cnv_depth_only"
        if partial
        else "not_confirmed",
        public_documentation_alignment="aligned" if partial else "gap",
        evidence_type="truth_cnv_remote_bam_depth_sweep",
        public_finding_result=f"{passed_count}/{len(probes)} HG008 CNV truth intervals passed normalized tumor-normal depth direction checks.",
        evidence={
            "truthBed": bounded.HG008_CNV_BED,
            "neutralInterval": {
                "chrom": neutral[0],
                "start": int(neutral[1]),
                "end": int(neutral[2]),
                "copyTotal": neutral[3],
                "eventId": neutral[6],
                "depth": neutral_depth,
            },
            "cnvProbes": probes,
        },
        blockers=("No Diana-generated CNV callset or reciprocal-overlap result exists for HG008.",),
        next_action="Run CNV calling and compare segments against HG008 v0.5 truth.",
    )


def _hg008_sv_truth_asset() -> ProbeResult:
    truth_path = bounded.HG008_CNV_BED.replace("somatic-CNV_PASS.draftbenchmark.calls.bed", "somatic-stvar_PASS.draftbenchmark.vcf.gz")
    exists = _artifact_exists(truth_path)
    cnv_bed_rows = len(_bed_rows(bounded.HG008_CNV_BED)) if _artifact_exists(bounded.HG008_CNV_BED) else 0
    return ProbeResult(
        status="expanded_non_dry_gap_identified" if exists else "expanded_non_dry_blocked_missing_asset",
        pipeline_confirmation="not_confirmed",
        public_documentation_alignment="gap",
        evidence_type="truth_asset_presence_without_caller_output",
        public_finding_result=(
            "HG008 SV truth asset is present but no Diana SV callset exists for reciprocal-overlap confirmation."
            if exists
            else "HG008 SV truth asset is missing locally."
        ),
        evidence={"truthVcf": truth_path, "truthVcfExists": exists, "cnvBedRows": cnv_bed_rows},
        blockers=("No Diana-generated SV callset exists for HG008 in this expanded bounded run.",),
        next_action="Run SV callers and reciprocal-overlap comparison against HG008 v0.5 truth.",
    )


def _hg008_rna_stats() -> ProbeResult:
    stats = bounded._read_hg008_rna_stats()
    passed = bool(stats.get("pairedReadStatsConsistent"))
    return ProbeResult(
        status="expanded_non_dry_partial" if passed else "expanded_non_dry_gap_identified",
        pipeline_confirmation="bounded_rna_intake_stats_confirmed" if passed else "not_confirmed",
        public_documentation_alignment="aligned" if passed else "gap",
        evidence_type="public_fastq_stats_only",
        public_finding_result=(
            "HG008 RNA paired FASTQ stats are internally consistent but quantification has not run."
            if passed
            else "HG008 RNA paired FASTQ stats are missing or inconsistent."
        ),
        evidence={"rnaStats": stats},
        blockers=("RNA FASTQs were not downloaded and no transcript-level truth target is selected.",),
        next_action="Transfer HG008 RNA FASTQs and run quantification against a selected RNA QC target.",
    )


def _colo829_platform_probe(probe_key: str) -> ProbeResult:
    config = COLO829_PLATFORM_PAIRS[probe_key]
    pileup = bounded._pileup_locus(
        str(config["region"]),
        bounded.COLO829_BRAF_REF,
        bounded.COLO829_BRAF_ALT,
        (str(config["tumor_bam"]), str(config["normal_bam"])),
    )
    samples = pileup.get("samples", [])
    tumor = samples[0] if samples else {}
    normal = samples[1] if len(samples) > 1 else {}
    tumor_alt_fraction = float(tumor.get("altFraction") or 0)
    normal_alt_fraction = float(normal.get("altFraction") or 0)
    passed = (
        pileup.get("status") == "passed"
        and int(tumor.get("depth") or 0) >= 15
        and int(normal.get("depth") or 0) >= 15
        and tumor_alt_fraction >= 0.2
        and normal_alt_fraction <= 0.15
    )
    return ProbeResult(
        status="expanded_non_dry_passed" if passed else "expanded_non_dry_gap_identified",
        pipeline_confirmation="bounded_braf_guardrail_confirmed" if passed else "not_confirmed",
        public_documentation_alignment="aligned" if passed else "gap",
        evidence_type="remote_indexed_bam_braf_pileup",
        public_finding_result=(
            f"COLO829 {config['label']} tumor has BRAF V600E ALT fraction {round_value(tumor_alt_fraction, 6)} "
            f"while normal ALT fraction is {round_value(normal_alt_fraction, 6)}."
        ),
        evidence={
            "platform": config["label"],
            "region": config["region"],
            "expectedRef": bounded.COLO829_BRAF_REF,
            "expectedAlt": bounded.COLO829_BRAF_ALT,
            "tumorBam": config["tumor_bam"],
            "normalBam": config["normal_bam"],
            "pileup": pileup,
        },
        blockers=() if passed else (f"COLO829 {config['label']} BRAF pileup did not pass bounded guardrails.",),
        next_action="Run full COLO829 tumor-normal calling and signature analysis before strict pipeline confirmation.",
    )


def _count_vcf_records(relative_path: str) -> int:
    path = path_from_root(relative_path)
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line and not line.startswith("#"))


def _colo829_sv_cna_truth_asset() -> ProbeResult:
    sv_exists = _artifact_exists(bounded.COLO829_SV_CNA_TRUTH)
    cna_exists = _artifact_exists(bounded.COLO829_COPY_NUMBER_TRUTH_ZIP)
    return ProbeResult(
        status="expanded_non_dry_gap_identified" if sv_exists and cna_exists else "expanded_non_dry_blocked_missing_asset",
        pipeline_confirmation="not_confirmed",
        public_documentation_alignment="gap",
        evidence_type="truth_assets_only_with_driver_context",
        public_finding_result=(
            "COLO829 SV/CNA truth assets are present but no build-matched Diana SV/CNA callset exists."
            if sv_exists and cna_exists
            else "COLO829 SV/CNA truth assets are missing locally."
        ),
        evidence={
            "truthVcf": bounded.COLO829_SV_CNA_TRUTH,
            "truthVcfExists": sv_exists,
            "truthVcfRecordCount": _count_vcf_records(bounded.COLO829_SV_CNA_TRUTH),
            "copyNumberTruthZip": bounded.COLO829_COPY_NUMBER_TRUTH_ZIP,
            "copyNumberTruthZipExists": cna_exists,
            "copyNumberTruthZipBytes": path_from_root(bounded.COLO829_COPY_NUMBER_TRUTH_ZIP).stat().st_size if cna_exists else 0,
        },
        blockers=(
            "COLO829 submitted BAMs and fetched hg38-lifted truth still require build reconciliation.",
            "No Diana SV/CNA callset exists.",
        ),
        next_action="Fetch or generate build-matched COLO829 calls and run SV/CNA reciprocal-overlap evaluation.",
    )


def _ena_rows() -> list[dict[str, str]]:
    path = path_from_root(bounded.COLO829_ENA_REPORT)
    return list(csv.DictReader(path.open(encoding="utf-8"), delimiter="\t"))


def _colo829_purity_probe(platform_group: str) -> ProbeResult:
    rows = [row for row in _ena_rows() if row.get("sample_alias", "").startswith("COLO829_purity_")]
    if platform_group == "illumina":
        selected = [row for row in rows if row.get("instrument_platform") == "ILLUMINA"]
    else:
        selected = [row for row in rows if row.get("instrument_platform") in {"PACBIO_SMRT", "OXFORD_NANOPORE"}]
    levels = sorted({row.get("sample_alias", "").removeprefix("COLO829_purity_") for row in selected})
    platform_counts = Counter(row.get("instrument_platform", "") for row in selected)
    indexed_count = sum(1 for row in selected if ".bai" in row.get("submitted_ftp", ""))
    return ProbeResult(
        status="expanded_non_dry_blocked_remote_index_missing",
        pipeline_confirmation="not_confirmed",
        public_documentation_alignment="gap",
        evidence_type="ena_metadata_without_remote_indexes",
        public_finding_result=(
            f"COLO829 purity {platform_group} metadata exposes {len(selected)} runs across levels {', '.join(levels)} "
            "but submitted BAM indexes are missing for remote slicing."
        ),
        evidence={
            "enaReport": bounded.COLO829_ENA_REPORT,
            "platformGroup": platform_group,
            "selectedRunCount": len(selected),
            "selectedLevels": levels,
            "instrumentPlatformCounts": dict(platform_counts),
            "submittedBamCount": sum(1 for row in selected if ".bam" in row.get("submitted_ftp", "")),
            "submittedBaiCount": indexed_count,
            "runAccessions": [row.get("run_accession", "") for row in selected],
        },
        blockers=("Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested.",),
        next_action="Transfer selected dilution BAM/FASTQ inputs and index locally before running purity recall.",
    )


def _seraseq_mrd_docs() -> ProbeResult:
    product_page = "data/raw/known_answer_public/seraseq_mrd/public_docs/product_page.html"
    package_insert = "data/raw/known_answer_public/seraseq_mrd/public_docs/pi-0710-2146-seraseq-ctdna-mrd-panel-mix.pdf"
    return ProbeResult(
        status="expanded_non_dry_blocked_request_or_purchase",
        pipeline_confirmation="not_confirmed",
        public_documentation_alignment="blocked_request_or_purchase",
        evidence_type="source_access_blocker",
        public_finding_result=(
            "Seraseq ctDNA MRD components are documented at 0, 0.005, 0.05, and 0.5 percent tumor fractions, "
            "but material or VCF files require request or purchase."
        ),
        evidence={
            "sourceAccess": "request_or_purchase",
            "productPageCached": _artifact_exists(product_page),
            "packageInsertCached": _artifact_exists(package_insert),
            "blockedReason": "No freely downloadable public FASTQ, BAM, or variant truth files were available for non-dry analysis.",
        },
        blockers=("Request or purchase is required before non-dry positive-negative MRD validation.",),
        next_action="Obtain Seraseq material or request-only VCFs and define assay-specific acceptance ranges.",
    )


def _probe_functions() -> dict[str, Callable[[], ProbeResult]]:
    functions: dict[str, Callable[[], ProbeResult]] = {
        "hcc1395_wes_summary": _hcc1395_wes_summary,
        "hcc1395_wgs_summary": _hcc1395_wgs_summary,
        "hg008_snv_panel": _hg008_snv_panel,
        "hg008_cnv_sweep": _hg008_cnv_sweep,
        "hg008_sv_truth_asset": _hg008_sv_truth_asset,
        "hg008_rna_stats": _hg008_rna_stats,
        "colo829_sv_cna_truth_asset": _colo829_sv_cna_truth_asset,
        "colo829_purity_illumina": lambda: _colo829_purity_probe("illumina"),
        "colo829_purity_long_read": lambda: _colo829_purity_probe("long_read"),
        "seraseq_mrd_docs": _seraseq_mrd_docs,
    }
    for probe_key in COLO829_PLATFORM_PAIRS:
        functions[probe_key] = lambda probe_key=probe_key: _colo829_platform_probe(probe_key)
    return functions


def _evaluate_probe(probe_key: str, cache: dict[str, ProbeResult]) -> ProbeResult:
    if probe_key in cache:
        return cache[probe_key]
    functions = _probe_functions()
    if probe_key not in functions:
        raise KeyError(f"Unknown expanded known-answer probe key: {probe_key}")
    result = _write_probe_artifact(probe_key, functions[probe_key]())
    cache[probe_key] = result
    return result


def _write_markdown(rows: Sequence[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Expanded Known-Answer Cohort Execution",
        "",
        "This generated report records non-dry bounded evidence and explicit gaps across a larger representative public cohort.",
        "",
        f"- Status: `{summary['status']}`",
        f"- Targets: `{summary['target_count']}`",
        f"- Cohort groups: `{summary['cohort_group_count']}`",
        f"- Non-dry confirmations: `{summary['passed_count']}`",
        f"- Partial confirmations: `{summary['partial_count']}`",
        f"- Gap-identified targets: `{summary['gap_identified_count']}`",
        f"- Blocked targets: `{summary['blocked_count']}`",
        f"- Clinical use allowed: `{summary['clinical_use_allowed_count']}`",
        "",
        "| Target | Group | Status | Public-doc alignment | Result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["target_id"]),
                    str(row["cohort_group"]),
                    str(row["target_status"]),
                    str(row["public_documentation_alignment"]),
                    str(row["public_finding_result"]).replace("|", "/"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            summary["interpretation"],
            "",
            "## Next Step",
            "",
            summary["next_step"],
        ]
    )
    write_text(path_from_root(EXECUTION_MD_PATH), "\n".join(lines))


def _summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(1 for row in rows if row["target_status"] == "expanded_non_dry_passed")
    partial = sum(1 for row in rows if row["target_status"] == "expanded_non_dry_partial")
    blocked = sum(1 for row in rows if str(row["target_status"]).startswith("expanded_non_dry_blocked"))
    gaps = sum(1 for row in rows if row["target_status"] == "expanded_non_dry_gap_identified")
    return {
        "status": "completed_with_confirmations_and_gaps",
        "target_count": len(rows),
        "cohort_group_count": len({row["cohort_group"] for row in rows}),
        "passed_count": passed,
        "partial_count": partial,
        "gap_identified_count": gaps,
        "blocked_count": blocked,
        "clinical_use_allowed_count": 0,
        "ready_for_clinical_interpretation": "no",
        "interpretation": (
            "The expanded cohort confirms public WES and WGS baseline mechanics plus bounded HG008 and COLO829 driver/CNV evidence. "
            "It also exposes the remaining strict-validation gaps: HG008 and COLO829 SV/CNA caller overlap, HG008 RNA quantification, "
            "COLO829 purity local indexing, and Seraseq MRD material or request-only VCF access."
        ),
        "next_step": (
            "Promote bounded confirmations to strict pipeline confirmations by generating caller outputs for HG008 and COLO829, "
            "running reciprocal-overlap truth comparisons, indexing purity inputs locally, and obtaining Seraseq MRD material or VCFs."
        ),
    }


def main() -> None:
    _ensure_public_assets()
    manifest_rows = _read_manifest()
    cache: dict[str, ProbeResult] = {}
    output_rows: list[dict[str, Any]] = []
    for manifest_row in manifest_rows:
        result = _evaluate_probe(manifest_row["probe_key"], cache)
        output_rows.append(
            {
                "target_id": manifest_row["target_id"],
                "cohort_group": manifest_row["cohort_group"],
                "sample_or_asset_id": manifest_row["sample_or_asset_id"],
                "target_role": manifest_row["target_role"],
                "modality": manifest_row["modality"],
                "source_access": manifest_row["source_access"],
                "source_url": manifest_row["source_url"],
                "public_finding": manifest_row["public_finding"],
                "expected_signal": manifest_row["expected_signal"],
                "probe_key": manifest_row["probe_key"],
                "artifact_path": result.artifact_path,
                "target_status": result.status,
                "pipeline_confirmation": result.pipeline_confirmation,
                "public_documentation_alignment": result.public_documentation_alignment,
                "evidence_type": result.evidence_type,
                "public_finding_result": result.public_finding_result,
                "blockers": "; ".join(result.blockers),
                "next_action": result.next_action,
                "clinical_use_allowed": "no",
                "no_call_policy": manifest_row["no_call_policy"],
            }
        )
    summary = _summary(output_rows)
    write_csv(path_from_root(EXECUTION_CSV_PATH), output_rows)
    write_json(
        path_from_root(EXECUTION_JSON_PATH),
        {
            "generatedAt": iso_now(),
            "status": summary["status"],
            "summary": summary,
            "rows": output_rows,
            "probeArtifacts": [result.artifact_path for result in cache.values()],
        },
    )
    _write_markdown(output_rows, summary)


if __name__ == "__main__":
    main()
