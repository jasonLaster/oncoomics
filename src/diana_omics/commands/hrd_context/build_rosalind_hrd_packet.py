from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_json, read_text, write_csv, write_json, write_text

RESULT_ROOT = "results/rosalind_hrd"
DEFAULT_SAMPLE_SETS = ("hcc1395_wes", "hcc1395_wgs", "hg008", "colo829", "diana_raw_intake")


@dataclass(frozen=True)
class PacketSpec:
    sample_set: str
    title: str
    use_case: str
    allowed_conclusion: str
    artifacts: tuple[str, ...]


PACKET_SPECS: dict[str, PacketSpec] = {
    "hcc1395_wes": PacketSpec(
        sample_set="hcc1395_wes",
        title="SEQC2/HCC1395 WES HRD Readiness Packet",
        use_case="Demonstrate tumor-normal WES intake, BAM QC, contamination review, Mutect2 calling, and truth-overlap reporting.",
        allowed_conclusion=(
            "This sample demonstrates WES small-variant and caller-readiness behavior. It does not support a genome-wide "
            "HRD scar, SV, SBS3, CHORD, or HRDetect-style score."
        ),
        artifacts=(
            "results/full_wes_benchmark/full_wes_benchmark_summary.json",
            "results/full_wes_benchmark/truth_overlap_benchmark_summary.json",
            "results/full_wes_benchmark/full_wes_fastq_validation.csv",
            "results/full_wes_benchmark/full_wes_bam_validation.csv",
            "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wes_summary.json",
        ),
    ),
    "hcc1395_wgs": PacketSpec(
        sample_set="hcc1395_wgs",
        title="SEQC2/HCC1395 WGS HRD Evidence-Surface Packet",
        use_case="Exercise the current WGS HRD evidence surfaces: BAM QC, small variants, coverage CNV bins, SBS96, and SV evidence.",
        allowed_conclusion=(
            "This sample exercises the WGS evidence surfaces needed for HRD review. It remains a partial HRD evidence packet "
            "until allele-specific CNV/LOH, production SV calls, signature thresholds, CHORD/scarHRD/HRDetect policy, and "
            "known-answer performance are locked."
        ),
        artifacts=(
            "results/phase3_wgs_smoke/phase3_wgs_summary.json",
            "results/phase3_wgs_smoke/bam_validation_summary.csv",
            "results/phase3_wgs_smoke/coverage_cnv_summary.json",
            "results/phase3_wgs_smoke/signature_assignment_summary.json",
            "results/phase3_wgs_smoke/sv_evidence_summary.json",
            "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json",
            "results/clinicalization/hrd_interpretation_readiness_summary.json",
            "results/clinicalization/known_answer_runs/expanded_cohort/hcc1395_wgs_summary.json",
        ),
    ),
    "hg008": PacketSpec(
        sample_set="hg008",
        title="GIAB HG008 Truth-Set Readiness Packet",
        use_case="Pressure-test correctness against independent NIST tumor-normal small-variant and CNV truth probes.",
        allowed_conclusion=(
            "HG008 is a truth-set validation sample. It should improve confidence in caller correctness and CNV/SV "
            "benchmarking, not produce a Diana-style HRD interpretation."
        ),
        artifacts=(
            "results/clinicalization/known_answer_runs/expanded_cohort/hg008_snv_panel.json",
            "results/clinicalization/known_answer_runs/expanded_cohort/hg008_cnv_sweep.json",
            "results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json",
            "results/clinicalization/known_answer_runs/expanded_cohort/hg008_rna_stats.json",
        ),
    ),
    "colo829": PacketSpec(
        sample_set="colo829",
        title="COLO829/COLO829BL Tumor-Normal Guardrail Packet",
        use_case="Demonstrate independent tumor-normal driver recovery and multi-platform BAM handling.",
        allowed_conclusion=(
            "COLO829 is an independent tumor-normal and driver-recovery guardrail. It does not establish HRD status until "
            "full SV/CNA/signature evidence is generated and benchmarked."
        ),
        artifacts=(
            "results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_illumina_hiseqx.json",
            "results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_pacbio_sequel.json",
            "results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_ont_minion.json",
            "results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_illumina_novaseq_phased.json",
            "results/clinicalization/known_answer_runs/expanded_cohort/colo829_sv_cna_truth_asset.json",
            "results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json",
        ),
    ),
    "diana_raw_intake": PacketSpec(
        sample_set="diana_raw_intake",
        title="Diana Raw BAM/FASTQ Intake Readiness Packet",
        use_case="Prepare the exact validation and staging path for Diana tumor-normal BAM, CRAM, FASTQ, and optional RNA FASTQ files.",
        allowed_conclusion=(
            "This packet proves the raw-data intake contract is ready. It does not validate Diana files or produce HRD "
            "evidence until the actual BAM/FASTQ/CRAM paths are supplied and pass strict intake validation."
        ),
        artifacts=(
            "manifests/diana_raw_inputs.template.csv",
            "docs/operations/diana-raw-inputs.md",
            "results/diana_raw_intake/input_contract.json",
            "results/diana_raw_intake/intake_readiness_summary.json",
            "results/diana_raw_intake/input_validation_summary.json",
        ),
    ),
}


def selected_sample_sets() -> tuple[str, ...]:
    raw = os.environ.get("ROSALIND_HRD_SAMPLE_SET", "all")
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    if not values or values == ("all",):
        return DEFAULT_SAMPLE_SETS
    unknown = sorted(set(values) - set(PACKET_SPECS))
    if unknown:
        raise SystemExit(f"Unknown ROSALIND_HRD_SAMPLE_SET value(s): {', '.join(unknown)}")
    return values


def run_id() -> str:
    value = os.environ.get("ROSALIND_HRD_RUN_ID")
    if value:
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "manual"
    return iso_now().replace(":", "").replace(".", "-")


def artifact_root() -> Path:
    raw = os.environ.get("ROSALIND_HRD_ARTIFACT_ROOT")
    if raw:
        return Path(raw).expanduser()
    return path_from_root("")


def artifact_root_mode() -> str:
    return "materialized_artifact_root" if os.environ.get("ROSALIND_HRD_ARTIFACT_ROOT") else "repo_root"


def artifact_root_label() -> str:
    return str(artifact_root()) if artifact_root_mode() == "materialized_artifact_root" else "repo_root"


def artifact_path_from_root(relative_path: str | Path) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        return path
    return artifact_root() / path


def read_json_or_empty(relative_path: str) -> dict[str, Any]:
    path = artifact_path_from_root(relative_path)
    if not path.exists():
        return {}
    payload = read_json(path)
    return payload if isinstance(payload, dict) else {"payload": payload}


def read_csv_or_empty(relative_path: str) -> list[dict[str, str]]:
    path = artifact_path_from_root(relative_path)
    if not path.exists():
        return []
    return parse_csv(read_text(path))


def artifact_index(paths: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative_path in paths:
        path = artifact_path_from_root(relative_path)
        resolved_path = str(path) if artifact_root_mode() == "materialized_artifact_root" else relative_path
        rows.append(
            {
                "path": relative_path,
                "resolved_path": resolved_path,
                "exists": "yes" if path.exists() else "no",
                "bytes": path.stat().st_size if path.exists() else "",
            }
        )
    return rows


def count_csv_status(rows: Sequence[Mapping[str, str]], status: str = "passed") -> int:
    return sum(1 for row in rows if row.get("status") == status)


def first_json_row(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows", [])
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def evidence_row(evidence_id: str, status: str, detail: str, artifact: str, caveat: str = "") -> dict[str, str]:
    return {
        "evidence_id": evidence_id,
        "status": status,
        "detail": detail,
        "artifact": artifact,
        "caveat": caveat,
    }


def adapter_row(adapter: str, state: str, blocker: str, next_action: str) -> dict[str, str]:
    return {
        "adapter": adapter,
        "state": state,
        "blocker": blocker,
        "next_action": next_action,
    }


def hcc1395_wes_evidence() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    summary = read_json_or_empty("results/full_wes_benchmark/full_wes_benchmark_summary.json")
    truth = read_json_or_empty("results/full_wes_benchmark/truth_overlap_benchmark_summary.json")
    fastq_rows = read_csv_or_empty("results/full_wes_benchmark/full_wes_fastq_validation.csv")
    bam_rows = read_csv_or_empty("results/full_wes_benchmark/full_wes_bam_validation.csv")
    evidence = [
        evidence_row(
            "fastq_validation",
            "passed" if count_csv_status(fastq_rows) == 4 else "partial",
            f"{count_csv_status(fastq_rows)}/4 FASTQ rows passed validation.",
            "results/full_wes_benchmark/full_wes_fastq_validation.csv",
        ),
        evidence_row(
            "bam_validation",
            str(summary.get("bamValidationStatus", "missing")),
            f"{count_csv_status(bam_rows)}/{len(bam_rows)} BAM rows passed validation.",
            "results/full_wes_benchmark/full_wes_bam_validation.csv",
        ),
        evidence_row(
            "somatic_small_variant_truth_overlap",
            str(summary.get("status", "missing")),
            (
                f"{summary.get('exactPassTruthMatches', 'unknown')} exact PASS truth matches; "
                f"recall {summary.get('exactPassRecall', 'unknown')}; precision {summary.get('exactPassPrecision', 'unknown')}."
            ),
            "results/full_wes_benchmark/full_wes_benchmark_summary.json",
            "WES truth-overlap evidence does not establish genome-wide HRD signatures, SVs, or scarHRD.",
        ),
        evidence_row(
            "contamination",
            str(summary.get("contaminationStatus", "missing")),
            f"Contamination estimate {summary.get('contaminationEstimate', 'unknown')}.",
            "results/full_wes_benchmark/full_wes_benchmark_summary.json",
        ),
    ]
    if truth.get("status"):
        evidence.append(
            evidence_row(
                "truth_overlap_detail",
                str(truth.get("status")),
                "Detailed truth-overlap summary is present.",
                "results/full_wes_benchmark/truth_overlap_benchmark_summary.json",
            )
        )
    adapters = [
        adapter_row("HRR SNV/indel evidence", "partial_evidence", "Small-variant evidence exists but HRR event curation is not a final HRD score.", "Curate observed HRR events if Diana WES/WGS calls contain them."),
        adapter_row("Biallelic/LOH evidence", "no_call", "Allele-specific CNV/LOH segments are unavailable.", "Run allele-specific CNV/LOH tooling before assessing second hits."),
        adapter_row("SBS3", "no_call", "WES is not sufficient for locked genome-wide SBS3 interpretation.", "Use WGS mutation matrix plus locked thresholds."),
        adapter_row("scarHRD", "no_call", "Allele-specific total/minor copy-number segments are unavailable.", "Generate FACETS/ASCAT/PURPLE-like segments."),
        adapter_row("CHORD", "no_call", "Validated SV caller VCF/BEDPE and full feature vector are unavailable.", "Run validated SV/CNV/small-variant feature adapters."),
        adapter_row("HRDetect-style model", "no_call", "Integrated calibrated feature vector is unavailable.", "Lock component adapters and model calibration before scoring."),
    ]
    return evidence, adapters, []


def hcc1395_wgs_evidence() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    summary = read_json_or_empty("results/phase3_wgs_smoke/phase3_wgs_summary.json")
    hrd_tools = read_json_or_empty("results/phase3_wgs_smoke/hrd_tool_readiness_summary.json")
    sv_summary = read_json_or_empty("results/phase3_wgs_smoke/sv_evidence_summary.json")
    sv_readiness = read_json_or_empty("results/clinicalization/sv_caller_readiness_summary.json")
    cnv_readiness = read_json_or_empty("results/clinicalization/cnv_loh_readiness_summary.json")
    hrd_readiness = read_json_or_empty("results/clinicalization/hrd_interpretation_readiness_summary.json")
    sv_rows = sv_summary.get("rows", []) if isinstance(sv_summary.get("rows"), list) else []
    discordant_pairs = sum(as_int(row.get("discordant_mapped_pairs")) for row in sv_rows if isinstance(row, dict))
    sv_statuses = sorted({str(row.get("chord_input_status", "")) for row in sv_rows if isinstance(row, dict) and row.get("chord_input_status")})
    sv_readiness_row = first_json_row(sv_readiness)
    cnv_readiness_row = first_json_row(cnv_readiness)
    sv_readiness_pairs = as_int(sv_readiness_row.get("phase3_discordant_mapped_pairs"))
    blockers: list[str] = []
    if discordant_pairs <= 0:
        blockers.append("Current SV evidence summary has no discordant mapped-pair counts; regenerate full SV evidence before using WGS as the flagship HRD packet.")
    if discordant_pairs <= 0 and sv_readiness_pairs > 0:
        blockers.append(
            "SV readiness sidecar is stale relative to the current SV evidence summary: "
            f"sv_caller_readiness reports {sv_readiness_pairs} discordant mapped pairs, but sv_evidence_summary reports 0. "
            "Regenerate SV evidence and rerun verify:sv-caller-readiness before treating the WGS packet as current."
        )
    evidence = [
        evidence_row(
            "wgs_pair_validation",
            str(summary.get("status", "missing")),
            (
                f"Full-source FASTQs: {summary.get('fullSourceFastqs', 'unknown')}; "
                f"read pairs per end: {summary.get('readPairsPerEnd', 'unknown')}; BAM validation: {summary.get('bamValidationStatus', 'unknown')}."
            ),
            "results/phase3_wgs_smoke/phase3_wgs_summary.json",
        ),
        evidence_row(
            "small_variant_lane",
            str(summary.get("mutect2Status", "missing")),
            (
                f"Truth-depth eligible variants: {summary.get('truthVariantsDepthEligible', 'unknown')}; "
                f"exact PASS matches: {summary.get('exactPassTruthMatches', 'unknown')}."
            ),
            "results/phase3_wgs_smoke/phase3_wgs_summary.json",
            "Public-BAM timing runs may skip local variant calling; do not infer HRD score readiness from this alone.",
        ),
        evidence_row(
            "coverage_cnv_bins",
            str(summary.get("coverageCnvStatus", "missing")),
            f"{summary.get('coverageCnvBins', 'unknown')} coverage CNV bins generated.",
            "results/phase3_wgs_smoke/coverage_cnv_summary.json",
            "Coverage bins are not allele-specific CNV/LOH segments.",
        ),
        evidence_row(
            "sbs96_matrix",
            str(summary.get("sbs96MatrixStatus", "missing")),
            f"{summary.get('sbs96UsableSnvRecords', 'unknown')} usable SNV records for SBS96.",
            "results/phase3_wgs_smoke/signature_assignment_summary.json",
            "SBS3 interpretation remains no-call until thresholds and known-answer performance are locked.",
        ),
        evidence_row(
            "sv_evidence",
            str(sv_summary.get("status", "missing")),
            f"SV evidence rows: {len(sv_rows)}; discordant mapped pairs: {discordant_pairs}; CHORD statuses: {';'.join(sv_statuses) or 'missing'}.",
            "results/phase3_wgs_smoke/sv_evidence_summary.json",
            "CHORD and HRDetect need validated SV caller VCF/BEDPE, not metadata-only evidence.",
        ),
        evidence_row(
            "sv_caller_readiness",
            str(sv_readiness.get("status", "missing")),
            (
                f"Candidate SV caller rows: {sv_readiness_row.get('candidate_count', 'unknown')}; "
                f"discordant mapped pairs in sidecar: {sv_readiness_row.get('phase3_discordant_mapped_pairs', 'unknown')}; "
                f"ready for clinical interpretation: {sv_readiness_row.get('ready_for_clinical_interpretation', 'unknown')}."
            ),
            "results/clinicalization/sv_caller_readiness_summary.json",
            "Use this as a readiness gate only after it agrees with the current SV evidence summary.",
        ),
        evidence_row(
            "cnv_loh_readiness",
            str(cnv_readiness.get("status", "missing")),
            (
                f"CNV bins: {cnv_readiness_row.get('phase3_cnv_bins', 'unknown')}; "
                f"allele-specific segments available: "
                f"{'no' if cnv_readiness_row.get('current_bins_are_not_allele_specific_segments') == 'yes' else 'unknown'}; "
                f"ready for clinical interpretation: {cnv_readiness_row.get('ready_for_clinical_interpretation', 'unknown')}."
            ),
            "results/clinicalization/cnv_loh_readiness_summary.json",
            "Coverage bins remain a plumbing check, not scarHRD-ready allele-specific CNV/LOH evidence.",
        ),
    ]
    adapters: list[dict[str, str]] = []
    tool_rows = hrd_tools.get("rows", []) if isinstance(hrd_tools.get("rows"), list) else []
    for row in tool_rows:
        if not isinstance(row, dict):
            continue
        adapters.append(
            adapter_row(
                str(row.get("tool", "unknown")),
                str(row.get("interpretability_status", "unknown")),
                str(row.get("caveat", "")),
                "Promote to ready only after the required production adapter and known-answer validation pass.",
            )
        )
    readiness_rows = hrd_readiness.get("rows", []) if isinstance(hrd_readiness.get("rows"), list) else []
    for row in readiness_rows:
        if not isinstance(row, dict):
            continue
        adapters.append(
            adapter_row(
                str(row.get("adapter_id", "unknown")),
                str(row.get("interpretation_status", "unknown")),
                str(row.get("no_call_reason", "")),
                str(row.get("required_inputs", "")),
            )
        )
    return evidence, adapters, blockers


def hg008_evidence() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    snv = read_json_or_empty("results/clinicalization/known_answer_runs/expanded_cohort/hg008_snv_panel.json")
    cnv = read_json_or_empty("results/clinicalization/known_answer_runs/expanded_cohort/hg008_cnv_sweep.json")
    sv = read_json_or_empty("results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json")
    evidence = [
        evidence_row("snv_truth_panel", str(snv.get("status", "missing")), str(snv.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/expanded_cohort/hg008_snv_panel.json"),
        evidence_row("cnv_depth_sweep", str(cnv.get("status", "missing")), str(cnv.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/expanded_cohort/hg008_cnv_sweep.json"),
        evidence_row("sv_cnv_reciprocal_overlap", str(sv.get("status", "missing")), str(sv.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json"),
    ]
    adapters = [
        adapter_row("SNV correctness validation", "partial_evidence", "Bounded truth-pileup confirmations are present, but full caller-level recall/precision is not complete.", "Run full small-variant caller concordance."),
        adapter_row("CNV/LOH correctness validation", "partial_evidence", "Depth-direction checks passed, but no Diana-generated CNV segment overlap exists.", "Run CNV calling and reciprocal-overlap against HG008 truth."),
        adapter_row("SV correctness validation", "blocked", "No Diana-generated SV callset exists for HG008 in the bounded run.", "Run SV caller and reciprocal-overlap against HG008 v0.5 truth."),
        adapter_row("HRD interpretation", "no_call", "HG008 is a truth-set validator, not a Diana HRD interpretation sample.", "Use only for pipeline correctness."),
    ]
    blockers = [str(item) for item in sv.get("blockers", [])] if isinstance(sv.get("blockers"), list) else []
    return evidence, adapters, blockers


def colo829_evidence() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    platform_paths = (
        "results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_illumina_hiseqx.json",
        "results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_pacbio_sequel.json",
        "results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_ont_minion.json",
        "results/clinicalization/known_answer_runs/expanded_cohort/colo829_platform_illumina_novaseq_phased.json",
    )
    evidence = []
    for path in platform_paths:
        payload = read_json_or_empty(path)
        evidence.append(evidence_row(Path(path).stem, str(payload.get("status", "missing")), str(payload.get("publicFindingResult", "")), path))
    sv = read_json_or_empty("results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json")
    truth = read_json_or_empty("results/clinicalization/known_answer_runs/expanded_cohort/colo829_sv_cna_truth_asset.json")
    evidence.append(evidence_row("sv_cna_truth_asset", str(truth.get("status", "missing")), str(truth.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/expanded_cohort/colo829_sv_cna_truth_asset.json"))
    evidence.append(evidence_row("sv_cna_reciprocal_overlap", str(sv.get("status", "missing")), str(sv.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json"))
    adapters = [
        adapter_row("BRAF driver guardrail", "partial_evidence", "BRAF V600E pileup recovery is confirmed across available platforms.", "Use as a tumor-normal handling guardrail only."),
        adapter_row("SV/CNA benchmark", "blocked", "No build-matched Diana SV/CNA callset exists.", "Fetch or generate build-matched COLO829 calls and run reciprocal overlap."),
        adapter_row("HRD interpretation", "no_call", "Driver recovery does not establish HRD status.", "Run full SV/CNA/signature evidence before any HRD interpretation."),
    ]
    blockers = [str(item) for item in sv.get("blockers", [])] if isinstance(sv.get("blockers"), list) else []
    return evidence, adapters, blockers


def diana_raw_intake_evidence() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    contract = read_json_or_empty("results/diana_raw_intake/input_contract.json")
    readiness = read_json_or_empty("results/diana_raw_intake/intake_readiness_summary.json")
    validation = read_json_or_empty("results/diana_raw_intake/input_validation_summary.json")
    validation_summary = validation.get("summary", {}) if isinstance(validation.get("summary"), dict) else {}
    required_columns = contract.get("requiredColumns", []) if isinstance(contract.get("requiredColumns"), list) else []
    matched_pairs = validation_summary.get("matchedPairIds", []) if isinstance(validation_summary.get("matchedPairIds"), list) else []
    validation_status = str(validation.get("status", "missing"))
    evidence = [
        evidence_row(
            "intake_template",
            str(readiness.get("status", "missing")),
            (
                f"Template: {readiness.get('template', 'unknown')}; "
                f"samplesheet: {readiness.get('actualSamplesheet', 'unknown')}; "
                f"ready for raw data: {readiness.get('readyForDianaRawData', 'unknown')}."
            ),
            "results/diana_raw_intake/intake_readiness_summary.json",
            "Template readiness only confirms the intake surface exists.",
        ),
        evidence_row(
            "input_contract",
            "present" if required_columns else "missing",
            (
                f"{len(required_columns)} required columns; DNA assays: {';'.join(contract.get('dnaAssays', []))}; "
                f"data types: {';'.join(contract.get('dataTypes', []))}."
            ),
            "results/diana_raw_intake/input_contract.json",
        ),
        evidence_row(
            "strict_file_validation",
            validation_status,
            (
                f"Rows: {validation_summary.get('rowCount', 0)}; DNA rows: {validation_summary.get('dnaRowCount', 0)}; "
                f"tumor DNA rows: {validation_summary.get('tumorDnaRows', 0)}; normal DNA rows: {validation_summary.get('normalDnaRows', 0)}; "
                f"matched pair IDs: {';'.join(matched_pairs) or 'none'}."
            ),
            "results/diana_raw_intake/input_validation_summary.json",
            "Expected to remain waiting until actual Diana BAM/FASTQ/CRAM paths are supplied.",
        ),
        evidence_row(
            "run_path",
            "ready_to_validate" if readiness.get("status") == "template_ready" else "blocked",
            (
                f"Validate with `{contract.get('validationCommand', 'missing')}`; "
                f"stage with `{contract.get('recomputeCommand', 'missing')}`."
            ),
            "results/diana_raw_intake/input_contract.json",
            "Passing intake validation still does not produce an HRD score.",
        ),
    ]
    if validation_status == "passed":
        raw_state = "ready_to_stage"
        raw_blocker = ""
        raw_next = "Stage the Diana analysis packet, then choose WGS/WES feature lanes from the staged rows."
        blockers: list[str] = []
    else:
        raw_state = "blocked_until_files"
        raw_blocker = "Actual Diana BAM/FASTQ/CRAM paths have not passed strict intake validation."
        raw_next = "Copy the template to manifests/diana_raw_inputs.csv, fill actual paths and metadata, then run verify:diana-raw with DIANA_RAW_REQUIRE_DATA=1."
        blockers = [raw_blocker]
    adapters = [
        adapter_row("Raw file intake", raw_state, raw_blocker, raw_next),
        adapter_row("Tumor-normal DNA pairing", "blocked_until_files" if not matched_pairs else "ready_to_stage", "No validated matched tumor-normal DNA pair is staged." if not matched_pairs else "", "Confirm tumor and normal rows share pair_id before compute."),
        adapter_row("Reference/index preflight", "ready_to_validate", "Reference files must exist and match all DNA rows when strict validation runs.", "Validate reference FASTA, FAI, and dict paths in verify:diana-raw."),
        adapter_row("HRD interpretation", "no_call", "No Diana sample evidence exists yet.", "Run the staged DNA feature lanes and public validation sidecars before interpretation."),
    ]
    return evidence, adapters, blockers


EVIDENCE_BUILDERS = {
    "hcc1395_wes": hcc1395_wes_evidence,
    "hcc1395_wgs": hcc1395_wgs_evidence,
    "hg008": hg008_evidence,
    "colo829": colo829_evidence,
    "diana_raw_intake": diana_raw_intake_evidence,
}


def research_context(spec: PacketSpec, evidence_rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    observed = [row for row in evidence_rows if any(token in row.get("detail", "") for token in ("BRAF", "BRCA", "HRR"))]
    return {
        "status": "deferred_until_observed_sample_events" if not observed else "candidate_context_available",
        "boundary": "Research context may enrich observed events, but it must not override failed QC, missing adapters, or HRD no-call states.",
        "recommended_source_skills": [
            "clinvar-variation-skill for observed variant pathogenicity context",
            "gnomad-graphql-skill for population frequency and constraint context",
            "cbioportal-skill and civic-skill for cancer recurrence and clinical evidence context",
            "uniprot-skill and reactome-skill for HR repair gene and pathway context",
            "clinicaltrials-skill only for explicit translational follow-up questions",
        ],
        "candidate_observed_evidence_ids": [row["evidence_id"] for row in observed],
        "sample_set": spec.sample_set,
    }


def markdown_table(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return ""
    columns = list(rows[0].keys())
    lines = [f"| {' | '.join(columns)} |", f"| {' | '.join(['---'] * len(columns))} |"]
    for row in rows:
        lines.append(f"| {' | '.join(str(row.get(column, '')).replace('|', '/') for column in columns)} |")
    return "\n".join(lines)


def write_packet(spec: PacketSpec, packet_run_id: str) -> dict[str, Any]:
    evidence_rows, adapter_rows, blockers = EVIDENCE_BUILDERS[spec.sample_set]()
    output_dir = f"{RESULT_ROOT}/{spec.sample_set}/{packet_run_id}"
    ensure_dir(path_from_root(output_dir))
    artifacts = artifact_index(spec.artifacts)
    missing_artifacts = [row["path"] for row in artifacts if row["exists"] != "yes"]
    if missing_artifacts:
        blockers.extend(f"Missing artifact: {path}" for path in missing_artifacts)

    write_json(path_from_root(f"{output_dir}/input_evidence_index.json"), {"sampleSet": spec.sample_set, "artifacts": artifacts})
    write_csv(path_from_root(f"{output_dir}/sample_validation_summary.csv"), evidence_rows)
    write_csv(path_from_root(f"{output_dir}/hrd_adapter_status.csv"), adapter_rows)
    write_json(path_from_root(f"{output_dir}/research_context_sources.json"), research_context(spec, evidence_rows))
    write_text(
        path_from_root(f"{output_dir}/next_actions.md"),
        "\n".join(
            [
                f"# Next Actions: {spec.title}",
                "",
                "## Blockers",
                *(f"- {blocker}" for blocker in blockers),
                *(["- No packet-specific blockers beyond the standard no-call boundaries."] if not blockers else []),
                "",
                "## Recommended Order",
                "- Preserve this packet as the run boundary before recompute.",
                "- Fix missing or blocked adapters before rerunning only the affected lane.",
                "- Add research context only after sample-derived event evidence exists.",
            ]
        ),
    )
    write_text(
        path_from_root(f"{output_dir}/reviewer_packet.md"),
        "\n".join(
            [
                f"# {spec.title}",
                "",
                f"Run ID: `{packet_run_id}`",
                "",
                "## Use Case",
                spec.use_case,
                "",
                "## Allowed Conclusion",
                spec.allowed_conclusion,
                "",
                "## Sample Evidence",
                markdown_table(evidence_rows),
                "",
                "## HRD Adapter Status",
                markdown_table(adapter_rows),
                "",
                "## Blockers",
                *(f"- {blocker}" for blocker in blockers),
                *(["- None beyond the listed adapter no-call boundaries."] if not blockers else []),
                "",
                "## Research Context Boundary",
                "Use external databases only to enrich observed sample events. Do not use literature or database context to override missing inputs, failed QC, or no-call adapter states.",
            ]
        ),
    )
    return {
        "sampleSet": spec.sample_set,
        "title": spec.title,
        "outputDir": output_dir,
        "evidenceRows": len(evidence_rows),
        "adapterRows": len(adapter_rows),
        "blockers": blockers,
        "missingArtifacts": missing_artifacts,
        "allowedConclusion": spec.allowed_conclusion,
    }


def write_cloud_materialization_plan(root: str, packet_run_id: str, packet_summaries: Sequence[Mapping[str, Any]]) -> None:
    required_prefixes = sorted(
        {
            str(Path(path).parts[0])
            for packet in packet_summaries
            for path in packet.get("missingArtifacts", [])
            if Path(str(path)).parts
        }
    )
    write_text(
        path_from_root(f"{root}/cloud_materialization_plan.md"),
        "\n".join(
            [
                "# Cloud Materialization Plan",
                "",
                f"Run ID: `{packet_run_id}`",
                "",
                f"Artifact root mode: `{artifact_root_mode()}`",
                "",
                "Use this when the container image does not include repository `results/`, `manifests/`, or `docs/operations` artifacts.",
                "",
                "## Required Environment",
                "",
                "```sh",
                "export ROSALIND_HRD_ARTIFACT_ROOT=/workspace/artifacts",
                f"export ROSALIND_HRD_RUN_ID={packet_run_id}",
                "PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet",
                "```",
                "",
                "Materialize the artifact root so paths like `results/phase3_wgs_smoke/phase3_wgs_summary.json` resolve under `$ROSALIND_HRD_ARTIFACT_ROOT`.",
                "",
                "## Typical Prefixes",
                "",
                "- `results/full_wes_benchmark/`",
                "- `results/phase3_wgs_smoke/`",
                "- `results/clinicalization/`",
                "- `results/diana_raw_intake/`",
                "- `manifests/`",
                "- `docs/operations/`",
                "",
                "## Missing Prefixes In This Run",
                *(f"- `{prefix}/`" for prefix in required_prefixes),
                *(["- None."] if not required_prefixes else []),
                "",
                "The packet builder writes new output to the repo checkout, but reads source evidence from `$ROSALIND_HRD_ARTIFACT_ROOT` when that variable is set.",
            ]
        ),
    )


def main() -> None:
    packet_run_id = run_id()
    sample_sets = selected_sample_sets()
    packet_summaries = [write_packet(PACKET_SPECS[sample_set], packet_run_id) for sample_set in sample_sets]
    root = f"{RESULT_ROOT}/{packet_run_id}"
    ensure_dir(path_from_root(root))
    manifest = {
        "generatedAt": iso_now(),
        "runId": packet_run_id,
        "sampleSets": list(sample_sets),
        "packetRoot": RESULT_ROOT,
        "artifactRoot": artifact_root_label(),
        "artifactRootMode": artifact_root_mode(),
        "packets": packet_summaries,
        "sourcePattern": {
            "ngs": "Derived from NGS Analysis router/runtime/DNA somatic patterns: inspect inputs, preflight, route, preserve provenance.",
            "research": "Derived from Life Science Research router/variant/cancer/pathway patterns: normalize entities, query targeted sources, synthesize caveats.",
        },
    }
    write_json(path_from_root(f"{root}/run_manifest.json"), manifest)
    write_text(
        path_from_root(f"{root}/packet_index.md"),
        "\n".join(
            [
                "# Rosalind HRD Packet Index",
                "",
                f"Run ID: `{packet_run_id}`",
                "",
                markdown_table(
                    [
                        {
                            "sample_set": packet["sampleSet"],
                            "output_dir": packet["outputDir"],
                            "evidence_rows": packet["evidenceRows"],
                            "adapter_rows": packet["adapterRows"],
                            "blocker_count": len(packet["blockers"]),
                        }
                        for packet in packet_summaries
                    ]
                ),
            ]
        ),
    )
    write_cloud_materialization_plan(root, packet_run_id, packet_summaries)
    print(f"Rosalind HRD packets written: {root}")


if __name__ == "__main__":
    main()
