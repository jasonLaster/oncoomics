from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ...paths import path_from_root
from ...utils import ensure_dir, iso_now, parse_csv, read_json, read_text

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
            "results/clinicalization/known_answer_runs/expanded_cohort/hg008_sv_truth_asset.json",
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
            "results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_illumina.json",
            "results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_long_read.json",
            "results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json",
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
            "results/diana_raw_intake/dinah_handoff_plan.json",
        ),
    ),
    "diana_wgs": PacketSpec(
        sample_set="diana_wgs",
        title="Diana WGS HRD Evidence Review Packet",
        use_case=(
            "Review sample-derived matched tumor-normal WGS evidence after source integrity, alignment, small-variant, "
            "coverage-CNV, SBS96-input, and BAM-derived SV evidence generation."
        ),
        allowed_conclusion=(
            "This packet records sample-derived WGS evidence and its current readiness boundaries. It does not support a "
            "scalar or categorical HRD conclusion until allele-specific CNV/LOH and purity/ploidy, a validated production "
            "SV callset, locked SBS3 assignment policy, and calibrated scarHRD, CHORD, and HRDetect-style adapters pass "
            "their validation gates."
        ),
        artifacts=(
            "diana_hrd_summary.json",
            "hrd_readiness.csv",
            "alignment/bam_validation_summary.json",
            "variants/mutect2_summary.json",
            "variants/brca1_brca2_pass_variants.csv",
            "cnv/coverage_cnv_summary.json",
            "cnv/coverage_cnv_bins.csv",
            "signatures/signature_assignment_summary.json",
            "signatures/wgs_sbs96_matrix.csv",
            "sv/sv_evidence_summary.json",
            "sv/sv_evidence_summary.csv",
            "tool_versions.json",
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


def write_text_create_only(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(value if value.endswith("\n") else f"{value}\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def write_json_create_only(path: Path, value: Any) -> None:
    write_text_create_only(path, json.dumps(value, indent=2) + "\n")


def write_csv_create_only(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str] | None = None,
) -> None:
    resolved_columns = list(
        columns or dict.fromkeys(key for row in rows for key in row.keys())
    )
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=resolved_columns,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                column: "" if row.get(column) is None else row.get(column)
                for column in resolved_columns
            }
        )
    write_text_create_only(path, output.getvalue())


def read_csv_or_empty(relative_path: str) -> list[dict[str, str]]:
    path = artifact_path_from_root(relative_path)
    if not path.exists():
        return []
    return parse_csv(read_text(path))


def artifact_index(paths: Sequence[str], *, logical_paths_only: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative_path in paths:
        path = artifact_path_from_root(relative_path)
        resolved_path = (
            f"artifact-root/{relative_path}"
            if logical_paths_only
            else (str(path) if artifact_root_mode() == "materialized_artifact_root" else relative_path)
        )
        rows.append(
            {
                "path": relative_path,
                "resolved_path": resolved_path,
                "exists": "yes" if path.exists() else "no",
                "bytes": path.stat().st_size if path.exists() else "",
                "sha256": sha256_file(path) if path.is_file() else "",
            }
        )
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def packet_evidence_status(evidence_rows: Sequence[Mapping[str, str]]) -> str:
    unavailable = {"", "blocked", "failed", "missing", "no_call", "not_run"}
    return (
        "partial_evidence"
        if any(str(row.get("status", "")).strip() not in unavailable for row in evidence_rows)
        else "blocked"
    )


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


def has_value(value: Any) -> bool:
    return value not in (None, "")


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


def payload_blockers(*payloads: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    for payload in payloads:
        values = payload.get("blockers", [])
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value)
            if text and text not in blockers:
                blockers.append(text)
    return blockers


def hg008_cnv_depth_detail(cnv: Mapping[str, Any], sv_cnv: Mapping[str, Any]) -> str:
    evidence = cnv.get("evidence", {}) if isinstance(cnv.get("evidence"), dict) else {}
    probes = evidence.get("cnvProbes", []) if isinstance(evidence.get("cnvProbes"), list) else []
    public_result = str(cnv.get("publicFindingResult", ""))
    sv_cnv_evidence = sv_cnv.get("evidence", {}) if isinstance(sv_cnv.get("evidence"), dict) else {}
    depth_probe = sv_cnv_evidence.get("cnvDepthProbe", {}) if isinstance(sv_cnv_evidence.get("cnvDepthProbe"), dict) else {}
    reciprocal_depth_signal = "yes" if depth_probe.get("passedCnvDepthSignal") is True else "no"
    if probes:
        return f"{public_result} Bounded reciprocal depth signal present: {reciprocal_depth_signal}."
    return public_result


def hg008_sv_cnv_detail(sv_cnv: Mapping[str, Any]) -> str:
    public_result = str(sv_cnv.get("publicFindingResult", ""))
    evidence = sv_cnv.get("evidence", {}) if isinstance(sv_cnv.get("evidence"), dict) else {}
    depth_probe = evidence.get("cnvDepthProbe", {}) if isinstance(evidence.get("cnvDepthProbe"), dict) else {}
    if not depth_probe:
        return public_result
    normalized_ratio = depth_probe.get("normalizedLossTumorNormalRatio", "unknown")
    passed_signal = "yes" if depth_probe.get("passedCnvDepthSignal") is True else "no"
    remaining_gap = depth_probe.get("remainingSvGap", "")
    return (
        f"{public_result} Bounded CNV depth signal: {passed_signal}; "
        f"normalized loss tumor-normal ratio: {normalized_ratio}. {remaining_gap}"
    ).strip()


def hg008_normalized_blockers(cnv: Mapping[str, Any], sv_truth: Mapping[str, Any], sv_cnv: Mapping[str, Any]) -> list[str]:
    raw_blockers = payload_blockers(cnv, sv_truth, sv_cnv)
    blockers: list[str] = []
    raw_text = " ".join(raw_blockers).lower()
    cnv_has_depth_evidence = "cnv" in raw_text or bool(cnv.get("publicFindingResult")) or bool(sv_cnv.get("publicFindingResult"))
    if cnv_has_depth_evidence:
        blockers.append(
            "No Diana-generated CNV segment callset exists for HG008; current HG008 CNV evidence is bounded depth-direction validation, not segment-level reciprocal overlap."
        )
    if "sv" in raw_text or bool(sv_truth.get("publicFindingResult")):
        blockers.append("No Diana-generated SV callset exists for HG008; SV reciprocal-overlap against v0.5 truth remains unrun.")
    for blocker in raw_blockers:
        lower = blocker.lower()
        normalized = (
            "cnv callset" in lower
            or "sv/cnv callset" in lower
            or "sv callset" in lower
            or "reciprocal-overlap" in lower
        )
        if not normalized and blocker not in blockers:
            blockers.append(blocker)
    return blockers


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
    sv_readiness_pairs_present = has_value(sv_readiness_row.get("phase3_discordant_mapped_pairs"))
    blockers: list[str] = []
    if discordant_pairs <= 0:
        blockers.append("Current SV evidence summary has no discordant mapped-pair counts; regenerate full SV evidence before using WGS as the flagship HRD packet.")
    if sv_readiness_pairs_present and discordant_pairs != sv_readiness_pairs:
        blockers.append(
            "SV readiness sidecar is stale relative to the current SV evidence summary: "
            f"sv_caller_readiness reports {sv_readiness_pairs} discordant mapped pairs, but "
            f"sv_evidence_summary reports {discordant_pairs}. "
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
    sv_truth = read_json_or_empty("results/clinicalization/known_answer_runs/expanded_cohort/hg008_sv_truth_asset.json")
    sv = read_json_or_empty("results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json")
    evidence = [
        evidence_row("snv_truth_panel", str(snv.get("status", "missing")), str(snv.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/expanded_cohort/hg008_snv_panel.json"),
        evidence_row("cnv_depth_sweep", str(cnv.get("status", "missing")), hg008_cnv_depth_detail(cnv, sv), "results/clinicalization/known_answer_runs/expanded_cohort/hg008_cnv_sweep.json"),
        evidence_row("sv_truth_asset", str(sv_truth.get("status", "missing")), str(sv_truth.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/expanded_cohort/hg008_sv_truth_asset.json"),
        evidence_row("sv_cnv_reciprocal_overlap", str(sv.get("status", "missing")), hg008_sv_cnv_detail(sv), "results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json"),
    ]
    adapters = [
        adapter_row("SNV correctness validation", "partial_evidence", "Bounded truth-pileup confirmations are present, but full caller-level recall/precision is not complete.", "Run full small-variant caller concordance."),
        adapter_row("CNV/LOH correctness validation", "partial_evidence", "Bounded depth-direction checks passed, but no Diana-generated CNV segment callset or segment-level reciprocal-overlap result exists.", "Run CNV calling and segment-level reciprocal-overlap against HG008 truth."),
        adapter_row("SV correctness validation", "blocked", "No Diana-generated SV callset exists for HG008; SV reciprocal-overlap remains unrun.", "Run SV caller and reciprocal-overlap against HG008 v0.5 truth."),
        adapter_row("HRD interpretation", "no_call", "HG008 is a truth-set validator, not a Diana HRD interpretation sample.", "Use only for pipeline correctness."),
    ]
    blockers = hg008_normalized_blockers(cnv, sv_truth, sv)
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
    purity_illumina = read_json_or_empty("results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_illumina.json")
    purity_long_read = read_json_or_empty("results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_long_read.json")
    purity_recall = read_json_or_empty("results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json")
    evidence.append(evidence_row("sv_cna_truth_asset", str(truth.get("status", "missing")), str(truth.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/expanded_cohort/colo829_sv_cna_truth_asset.json"))
    evidence.append(evidence_row("sv_cna_reciprocal_overlap", str(sv.get("status", "missing")), str(sv.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json"))
    evidence.append(evidence_row("purity_illumina_metadata", str(purity_illumina.get("status", "missing")), str(purity_illumina.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_illumina.json"))
    evidence.append(evidence_row("purity_long_read_metadata", str(purity_long_read.get("status", "missing")), str(purity_long_read.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/expanded_cohort/colo829_purity_long_read.json"))
    evidence.append(evidence_row("purity_recall_table", str(purity_recall.get("status", "missing")), str(purity_recall.get("publicFindingResult", "")), "results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json"))
    adapters = [
        adapter_row("BRAF driver guardrail", "partial_evidence", "BRAF V600E pileup recovery is confirmed across available platforms.", "Use as a tumor-normal handling guardrail only."),
        adapter_row("SV/CNA benchmark", "blocked", "No build-matched Diana SV/CNA callset exists.", "Fetch or generate build-matched COLO829 calls and run reciprocal overlap."),
        adapter_row("Purity sensitivity benchmark", "blocked", "Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested.", "Transfer selected dilution BAM/FASTQ inputs and index locally before running purity recall."),
        adapter_row("HRD interpretation", "no_call", "Driver recovery does not establish HRD status.", "Run full SV/CNA/signature evidence before any HRD interpretation."),
    ]
    blockers = payload_blockers(truth, sv, purity_illumina, purity_long_read, purity_recall)
    return evidence, adapters, blockers


def diana_raw_intake_evidence() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    contract = read_json_or_empty("results/diana_raw_intake/input_contract.json")
    readiness = read_json_or_empty("results/diana_raw_intake/intake_readiness_summary.json")
    validation = read_json_or_empty("results/diana_raw_intake/input_validation_summary.json")
    handoff = read_json_or_empty("results/diana_raw_intake/dinah_handoff_plan.json")
    validation_summary = validation.get("summary", {}) if isinstance(validation.get("summary"), dict) else {}
    handoff_state = handoff.get("currentState", {}) if isinstance(handoff.get("currentState"), dict) else {}
    handoff_steps = handoff.get("handoffSteps", []) if isinstance(handoff.get("handoffSteps"), list) else []
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
            "dinah_handoff_plan",
            str(handoff.get("status", "missing")),
            (
                f"Steps: {len(handoff_steps)}; samplesheet: {handoff.get('samplesheet', 'unknown')}; "
                f"analysis ID: {handoff.get('analysisId', 'unknown')}; current state: {handoff_state.get('status', 'unknown')}."
            ),
            "results/diana_raw_intake/dinah_handoff_plan.json",
            "Planning artifact only; it does not validate files or authorize human-data cloud upload.",
        ),
        evidence_row(
            "run_path",
            "ready_to_validate" if readiness.get("status") == "template_ready" else "blocked",
            (
                f"Plan with `{contract.get('handoffPlanCommand', 'missing')}`; "
                f"validate with `{contract.get('validationCommand', 'missing')}`; "
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
        raw_next = "Run plan:diana-raw-handoff, copy the template to manifests/diana_raw_inputs.csv, fill actual paths and metadata, then run verify:diana-raw with DIANA_RAW_REQUIRE_DATA=1."
        blockers = [raw_blocker]
    adapters = [
        adapter_row("Raw file intake", raw_state, raw_blocker, raw_next),
        adapter_row("Tumor-normal DNA pairing", "blocked_until_files" if not matched_pairs else "ready_to_stage", "No validated matched tumor-normal DNA pair is staged." if not matched_pairs else "", "Confirm tumor and normal rows share pair_id before compute."),
        adapter_row("Reference/index preflight", "ready_to_validate", "Reference files must exist and match all DNA rows when strict validation runs.", "Validate reference FASTA, FAI, and dict paths in verify:diana-raw."),
        adapter_row("HRD interpretation", "no_call", "No Diana sample evidence exists yet.", "Run the staged DNA feature lanes and public validation sidecars before interpretation."),
    ]
    return evidence, adapters, blockers


DIANA_WGS_READINESS_SURFACES = (
    "source_sha256",
    "wgs_alignment",
    "matched_normal_somatic_variants",
    "coverage_cnv",
    "sbs96",
    "sv",
    "scarHRD",
    "CHORD",
    "HRDetect",
    "overall_hrd",
)
DIANA_WGS_PARTIAL_ONLY_SURFACES = {"coverage_cnv", "sbs96", "sv"}
DIANA_WGS_NO_CALL_SURFACES = {"scarHRD", "CHORD", "HRDetect", "overall_hrd"}
PHASE3_FAST_REPORT_KIND = "phase3_fast_deterministic_evidence"
DIANA_WGS_PHASE3_FAST_READINESS_SURFACES = (
    "source_sha256",
    "small_variants",
    "bam_qc",
    "coverage_cnv",
    "sv",
    "sbs96",
    "scarHRD",
    "CHORD",
    "HRDetect",
    "overall_hrd",
)
DIANA_WGS_PHASE3_FAST_PARTIAL_ONLY_SURFACES = {"coverage_cnv", "sbs96", "sv"}
DIANA_WGS_PHASE3_FAST_BLOCKED_SURFACES: set[str] = set()
DIANA_WGS_PHASE3_FAST_NO_CALL_SURFACES = {"scarHRD", "CHORD", "HRDetect", "overall_hrd"}
DIANA_WGS_DETERMINISTIC_INPUTS = {
    "diana_hrd_summary.json": "summary",
    "hrd_readiness.csv": "readiness",
    "alignment/bam_validation_summary.json": "alignment_json",
    "variants/mutect2_summary.json": "variant_summary",
    "variants/brca1_brca2_pass_variants.csv": "brca_rows",
    "cnv/coverage_cnv_summary.json": "cnv_summary",
    "cnv/coverage_cnv_bins.csv": "cnv_bins",
    "signatures/signature_assignment_summary.json": "signature_summary",
    "signatures/wgs_sbs96_matrix.csv": "sbs96",
    "sv/sv_evidence_summary.json": "sv_summary",
    "sv/sv_evidence_summary.csv": "sv_csv",
    "tool_versions.json": "tool_versions",
}
DETERMINISTIC_SUPPORT_FILES = {
    "crosscheck_input_plans.json",
    "readiness.csv",
    "evidence_checks.json",
    "input_sha256.csv",
}
PHASE3_FAST_DETERMINISTIC_SUPPORT_FILES = {
    *DETERMINISTIC_SUPPORT_FILES,
    "crosscheck_input_plans.json",
}
PACKET_REPORT_FILES = {
    "input_evidence_index.json",
    "sample_validation_summary.csv",
    "hrd_adapter_status.csv",
    "research_context_sources.json",
    "next_actions.md",
    "reviewer_packet.md",
    "report.md",
    "report_manifest.json",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_SBS96 = {
    (mutation, f"{left}[{mutation}]{right}")
    for mutation in ("C>A", "C>G", "C>T", "T>A", "T>C", "T>G")
    for left in "ACGT"
    for right in "ACGT"
}


def diana_wgs_deterministic_report_dir() -> Path:
    raw = os.environ.get("ROSALIND_HRD_DETERMINISTIC_REPORT_DIR", "").strip()
    if not raw:
        raise ValueError(
            "ROSALIND_HRD_DETERMINISTIC_REPORT_DIR is required for the Diana WGS packet"
        )
    report_root = Path(raw).expanduser()
    if report_root.is_symlink() or not report_root.is_dir():
        raise ValueError("deterministic report directory must be a real directory")
    return report_root


def diana_wgs_deterministic_report_kind() -> str:
    raw = os.environ.get("ROSALIND_HRD_DETERMINISTIC_REPORT_DIR", "").strip()
    if not raw:
        return ""
    manifest_path = Path(raw).expanduser() / "report_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return ""
    manifest = read_json(manifest_path)
    return str(manifest.get("report_kind", "")) if isinstance(manifest, dict) else ""


def require_real_nonempty_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{label} must be a non-empty regular non-symlink file")
    return path


def require_sha256(value: Any, label: str) -> str:
    digest = str(value).lower()
    if not HEX64.fullmatch(digest):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return digest


def require_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a non-negative integer") from error
    if number < 0 or str(value).strip() not in {str(number), f"{number}.0"}:
        raise ValueError(f"{label} must be a non-negative integer")
    return number


def validate_diana_wgs_worker_schema() -> None:
    alignment = read_json_or_empty("alignment/bam_validation_summary.json")
    alignment_rows = alignment.get("rows", []) if isinstance(alignment.get("rows"), list) else []
    alignment_by_role = {
        str(row.get("role", "")): row for row in alignment_rows if isinstance(row, dict)
    }
    if (
        alignment.get("status") != "passed"
        or len(alignment_rows) != 2
        or set(alignment_by_role) != {"tumor", "normal"}
    ):
        raise ValueError("Diana WGS alignment schema requires one passed tumor and one passed normal row")
    for role, row in alignment_by_role.items():
        total = require_nonnegative_int(row.get("total_reads"), f"{role} total_reads")
        mapped = require_nonnegative_int(row.get("mapped_reads"), f"{role} mapped_reads")
        if row.get("status") != "passed" or total <= 0 or mapped > total:
            raise ValueError(f"Diana WGS {role} alignment counts are inconsistent")

    variants = read_json_or_empty("variants/mutect2_summary.json")
    variant_counts = {
        key: require_nonnegative_int(variants.get(key), f"variant {key}")
        for key in (
            "total_filtered_records", "pass_records", "pass_snvs", "pass_indels",
            "brca1_brca2_pass_region_records",
        )
    }
    brca_rows = read_csv_or_empty("variants/brca1_brca2_pass_variants.csv")
    if (
        variants.get("status") != "passed"
        or variant_counts["pass_records"] != variant_counts["pass_snvs"] + variant_counts["pass_indels"]
        or variant_counts["pass_records"] > variant_counts["total_filtered_records"]
        or len(brca_rows) != variant_counts["brca1_brca2_pass_region_records"]
    ):
        raise ValueError("Diana WGS variant summary and bounded HRR rows do not reconcile")

    cnv = read_json_or_empty("cnv/coverage_cnv_summary.json")
    cnv_rows = read_csv_or_empty("cnv/coverage_cnv_bins.csv")
    cnv_classes = [row.get("coverage_class", "") for row in cnv_rows]
    bin_count = require_nonnegative_int(cnv.get("bin_count"), "CNV bin_count")
    if (
        cnv.get("status") != "partial_evidence"
        or len(cnv_rows) != bin_count
        or set(cnv_classes) - {"relative_gain", "relative_loss", "neutral_or_low_signal"}
        or cnv_classes.count("relative_gain") != require_nonnegative_int(cnv.get("relative_gain_bins"), "CNV gain bins")
        or cnv_classes.count("relative_loss") != require_nonnegative_int(cnv.get("relative_loss_bins"), "CNV loss bins")
    ):
        raise ValueError("Diana WGS coverage-CNV rows and summary do not reconcile")

    signatures = read_json_or_empty("signatures/signature_assignment_summary.json")
    sbs_rows = read_csv_or_empty("signatures/wgs_sbs96_matrix.csv")
    sbs_keys = {(row.get("mutation_type", ""), row.get("trinucleotide", "")) for row in sbs_rows}
    sbs_counts = [require_nonnegative_int(row.get("count"), "SBS96 count") for row in sbs_rows]
    if (
        signatures.get("status") != "partial_evidence"
        or len(sbs_rows) != 96
        or sbs_keys != EXPECTED_SBS96
        or sum(sbs_counts) != require_nonnegative_int(signatures.get("usable_snv_records"), "usable SBS96 SNVs")
        or not str(signatures.get("sbs3_status", "")).startswith("no_call")
    ):
        raise ValueError("Diana WGS SBS96 matrix is not an exact 96-channel input")

    sv = read_json_or_empty("sv/sv_evidence_summary.json")
    sv_json_rows = sv.get("rows", []) if isinstance(sv.get("rows"), list) else []
    sv_csv_rows = read_csv_or_empty("sv/sv_evidence_summary.csv")
    json_by_role = {str(row.get("role", "")): row for row in sv_json_rows if isinstance(row, dict)}
    csv_by_role = {str(row.get("role", "")): row for row in sv_csv_rows}
    count_fields = (
        "total_alignments", "supplementary_alignments", "discordant_mapped_pairs",
        "interchromosomal_pairs", "large_insert_pairs",
    )
    if (
        sv.get("status") != "partial_evidence"
        or sv.get("production_sv_callset_status") != "no_call"
        or len(sv_json_rows) != 2
        or len(sv_csv_rows) != 2
        or set(json_by_role) != {"tumor", "normal"}
        or set(csv_by_role) != {"tumor", "normal"}
    ):
        raise ValueError("Diana WGS SV JSON/CSV role schema is not exact")
    for role in ("tumor", "normal"):
        for field in count_fields:
            json_value = require_nonnegative_int(json_by_role[role].get(field), f"SV {role} {field}")
            csv_value = require_nonnegative_int(csv_by_role[role].get(field), f"SV CSV {role} {field}")
            if json_value != csv_value:
                raise ValueError(f"Diana WGS SV JSON/CSV differs for {role} {field}")
        if require_nonnegative_int(json_by_role[role].get("total_alignments"), f"SV {role} total") != require_nonnegative_int(alignment_by_role[role].get("total_reads"), f"alignment {role} total"):
            raise ValueError(f"Diana WGS SV totals do not reconcile with {role} alignment")


def diana_wgs_deterministic_binding() -> dict[str, Any]:
    report_root = diana_wgs_deterministic_report_dir()
    paths = {
        name: require_real_nonempty_file(report_root / name, f"deterministic {name}")
        for name in {
            "report.md", "report_manifest.json", *DETERMINISTIC_SUPPORT_FILES
        }
    }
    manifest = read_json(paths["report_manifest.json"])
    if not isinstance(manifest, dict):
        raise ValueError("deterministic report manifest must be an object")
    expected_contract = {
        "schema_version": 1,
        "method_id": "deterministic_full_wgs",
        "evidence_status": "partial_evidence",
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
    }
    for key, expected in expected_contract.items():
        if manifest.get(key) != expected:
            raise ValueError(f"deterministic report manifest {key} is not exact")
    support_files = (
        PHASE3_FAST_DETERMINISTIC_SUPPORT_FILES
        if manifest.get("report_kind") == PHASE3_FAST_REPORT_KIND
        else DETERMINISTIC_SUPPORT_FILES
    )
    for name in sorted(support_files - set(paths)):
        paths[name] = require_real_nonempty_file(report_root / name, f"deterministic {name}")
    if manifest.get("report_sha256") != sha256_file(paths["report.md"]):
        raise ValueError("deterministic report hash differs from its manifest")
    support = manifest.get("support_sha256")
    if not isinstance(support, dict) or set(support) != support_files:
        raise ValueError("deterministic support SHA-256 inventory is not exact")
    for name in support_files:
        if require_sha256(support.get(name), f"deterministic support {name}") != sha256_file(paths[name]):
            raise ValueError(f"deterministic support hash differs for {name}")

    source = manifest.get("source_sha256")
    if not isinstance(source, dict) or not source:
        raise ValueError("deterministic source SHA-256 inventory is missing")
    input_rows = parse_csv(read_text(paths["input_sha256.csv"]))
    if not input_rows or any(set(row) != {"input_id", "path", "bytes", "sha256"} for row in input_rows):
        raise ValueError("deterministic input SHA-256 CSV schema is not exact")
    input_by_id = {row["input_id"]: row for row in input_rows}
    if len(input_by_id) != len(input_rows):
        raise ValueError("deterministic input SHA-256 CSV has duplicate input IDs")
    if manifest.get("report_kind") == PHASE3_FAST_REPORT_KIND:
        return diana_wgs_phase3_fast_deterministic_binding(
            paths=paths,
            manifest=manifest,
            support=support,
            source=source,
            input_rows=input_rows,
        )

    validate_diana_wgs_worker_schema()
    artifact_hashes: dict[str, str] = {}
    for relative, input_id in DIANA_WGS_DETERMINISTIC_INPUTS.items():
        artifact = require_real_nonempty_file(
            artifact_path_from_root(relative), f"Diana WGS artifact {relative}"
        )
        digest = sha256_file(artifact)
        row = input_by_id.get(input_id)
        if (
            not row
            or require_sha256(source.get(input_id), f"deterministic source {input_id}") != digest
            or require_sha256(row.get("sha256"), f"deterministic input {input_id}") != digest
            or str(row.get("path")) != f"artifact-root/{relative}"
            or as_int(row.get("bytes")) != artifact.stat().st_size
        ):
            raise ValueError(f"Diana WGS artifact is not exactly bound by deterministic input {input_id}")
        artifact_hashes[input_id] = digest

    checks = read_json(paths["evidence_checks.json"])
    check_rows = checks.get("checks", []) if isinstance(checks, dict) else []
    checks_input = checks.get("input_sha256", []) if isinstance(checks, dict) else []
    normalized_checks_input = [
        {key: str(row.get(key, "")) for key in ("input_id", "path", "bytes", "sha256")}
        for row in checks_input
        if isinstance(row, dict)
    ]
    normalized_csv_input = [
        {key: str(row.get(key, "")) for key in ("input_id", "path", "bytes", "sha256")}
        for row in input_rows
    ]
    if (
        checks.get("status") != "passed"
        or checks.get("report_status") != "partial_evidence"
        or checks.get("overall_hrd_status") != "no_call"
        or not isinstance(check_rows, list)
        or not check_rows
        or any(not isinstance(row, dict) or row.get("status") != "passed" for row in check_rows)
        or normalized_checks_input != normalized_csv_input
    ):
        raise ValueError("deterministic evidence checks are incomplete or not all passed")
    review_summary = manifest.get("review_summary")
    custody = review_summary.get("custody", {}) if isinstance(review_summary, dict) else {}
    if custody.get("private_freeze_status") != "passed" or custody.get("exact_kms_match") is not True:
        raise ValueError("deterministic report lacks passed exact-KMS custody")
    version_fields = (
        "freeze_receipt_version_id",
        "stage_provenance_receipt_version_id",
    )
    if any(not str(custody.get(field, "")).strip() for field in version_fields):
        raise ValueError("deterministic custody lacks exact receipt VersionIds")
    custody_hashes = {
        key: require_sha256(value, f"deterministic custody {key}")
        for key, value in custody.items()
        if key.endswith("_sha256")
    }
    if not custody_hashes:
        raise ValueError("deterministic custody lacks hash-bound receipts")
    tools = read_json(artifact_path_from_root("tool_versions.json"))
    if (
        not isinstance(tools, dict)
        or set(tools) != {"bwa", "samtools", "bcftools", "gatk"}
        or any(not str(value).strip() for value in tools.values())
    ):
        raise ValueError("Diana WGS tool version inventory is missing or malformed")
    return {
        "binding_kind": "terminal_worker",
        "deterministic_report_sha256": sha256_file(paths["report.md"]),
        "deterministic_manifest_sha256": sha256_file(paths["report_manifest.json"]),
        "deterministic_support_sha256": dict(sorted(support.items())),
        "artifact_sha256": artifact_hashes,
        "artifact_count": len(artifact_hashes),
        "custody": {
            "private_freeze_status": "passed",
            "exact_kms_match": True,
            **{field: str(custody[field]) for field in version_fields},
            **custody_hashes,
        },
        "tool_versions": {str(key): str(value) for key, value in sorted(tools.items())},
    }


def diana_wgs_phase3_fast_deterministic_binding(
    *,
    paths: Mapping[str, Path],
    manifest: Mapping[str, Any],
    support: Mapping[str, Any],
    source: Mapping[str, Any],
    input_rows: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    review_summary = manifest.get("review_summary")
    if not isinstance(review_summary, dict):
        raise ValueError("Phase 3 fast deterministic report lacks a review summary")
    overall = review_summary.get("overall")
    if (
        not isinstance(overall, dict)
        or overall.get("evidence_status") != "partial_evidence"
        or overall.get("authorized_hrd_state") != "no_call"
    ):
        raise ValueError("Phase 3 fast deterministic report does not preserve a no-call partial-evidence boundary")

    artifact_groups = review_summary.get("artifact_groups")
    if (
        not isinstance(artifact_groups, dict)
        or set(artifact_groups) != {"small_variants", "bam_qc", "cnv_evidence", "sv_evidence"}
    ):
        raise ValueError("Phase 3 fast deterministic report artifact groups are not exact")

    artifact_count = require_nonnegative_int(
        review_summary.get("artifact_count"),
        "Phase 3 fast artifact_count",
    )
    final_artifact_rows = [row for row in input_rows if row.get("input_id") != "final_evidence_manifest"]
    if artifact_count != len(final_artifact_rows):
        raise ValueError("Phase 3 fast deterministic artifact_count differs from input_sha256.csv")
    if set(source) != {str(row["input_id"]) for row in input_rows}:
        raise ValueError("Phase 3 fast deterministic source SHA-256 inventory differs from input_sha256.csv")
    crosscheck_input_plans = read_json(paths["crosscheck_input_plans.json"])
    if (
        not isinstance(crosscheck_input_plans, dict)
        or crosscheck_input_plans.get("schema_version") != 1
        or crosscheck_input_plans.get("plan_type") != "phase3_fast_crosscheck_input_materialization_plan"
        or crosscheck_input_plans.get("status") != "planned"
        or crosscheck_input_plans.get("authorized_hrd_state") != "no_call"
        or crosscheck_input_plans.get("classification_authorized") is not False
    ):
        raise ValueError("Phase 3 fast cross-check input plan contract is not exact")
    crosscheck_routes = crosscheck_input_plans.get("routes")
    if not isinstance(crosscheck_routes, dict):
        raise ValueError("Phase 3 fast cross-check input plan lacks exact routes")
    crosscheck_route_states = {
        "sigprofiler_sbs3": "plan_ready",
        "sequenza_scarhrd": "blocked",
    }
    for route, expected_status in crosscheck_route_states.items():
        route_plan = crosscheck_routes.get(route)
        if (
            not isinstance(route_plan, dict)
            or route_plan.get("status") != expected_status
            or route_plan.get("execution_status") != "not_run"
            or route_plan.get("interpretation_status") != "no_call"
        ):
            raise ValueError(f"Phase 3 fast {route} materialization plan is not exact")

    checks = read_json(paths["evidence_checks.json"])
    check_rows = checks.get("checks", []) if isinstance(checks, dict) else []
    checks_input = checks.get("input_sha256", []) if isinstance(checks, dict) else []
    normalized_checks_input = [
        {key: str(row.get(key, "")) for key in ("input_id", "path", "bytes", "sha256")}
        for row in checks_input
        if isinstance(row, dict)
    ]
    normalized_csv_input = [
        {key: str(row.get(key, "")) for key in ("input_id", "path", "bytes", "sha256")}
        for row in input_rows
    ]
    if (
        checks.get("status") != "passed"
        or checks.get("report_status") != "partial_evidence"
        or checks.get("overall_hrd_status") != "no_call"
        or not isinstance(check_rows, list)
        or not check_rows
        or any(not isinstance(row, dict) or row.get("status") != "passed" for row in check_rows)
        or normalized_checks_input != normalized_csv_input
    ):
        raise ValueError("Phase 3 fast deterministic evidence checks are incomplete or not all passed")

    artifact_hashes: dict[str, str] = {}
    artifact_index_rows: list[dict[str, Any]] = []
    for row in input_rows:
        input_id = str(row["input_id"])
        relative = str(row["path"])
        digest = require_sha256(row.get("sha256"), f"Phase 3 fast deterministic input {input_id}")
        if require_sha256(source.get(input_id), f"Phase 3 fast deterministic source {input_id}") != digest:
            raise ValueError(f"Phase 3 fast source hash differs from deterministic input {input_id}")
        bytes_ = require_nonnegative_int(row.get("bytes"), f"Phase 3 fast deterministic input {input_id} bytes")

        exists = "yes"
        if input_id != "final_evidence_manifest":
            if not relative.startswith("final/"):
                raise ValueError(f"Phase 3 fast final artifact {input_id} does not use the final/ input namespace")
            artifact = artifact_path_from_root(relative.removeprefix("final/"))
            if artifact.is_symlink() or not artifact.is_file():
                raise ValueError(f"Phase 3 fast final artifact is missing: {input_id}")
            if artifact.stat().st_size != bytes_ or sha256_file(artifact) != digest:
                raise ValueError(f"Phase 3 fast final artifact hash differs from deterministic input {input_id}")

        artifact_hashes[input_id] = digest
        artifact_index_rows.append(
            {
                "path": relative,
                "resolved_path": f"deterministic-input/{relative}",
                "exists": exists,
                "bytes": bytes_,
                "sha256": digest,
            }
        )

    return {
        "binding_kind": "phase3_fast_final",
        "deterministic_report_sha256": sha256_file(paths["report.md"]),
        "deterministic_manifest_sha256": sha256_file(paths["report_manifest.json"]),
        "deterministic_support_sha256": dict(sorted(support.items())),
        "artifact_sha256": artifact_hashes,
        "artifact_count": artifact_count,
        "artifact_index": artifact_index_rows,
        "phase3_fast": {
            "artifact_groups": {
                str(group): require_nonnegative_int(count, f"Phase 3 fast artifact group {group}")
                for group, count in sorted(artifact_groups.items())
            },
            "run": dict(review_summary.get("run", {})) if isinstance(review_summary.get("run"), dict) else {},
            "workflow": (
                dict(review_summary.get("workflow", {}))
                if isinstance(review_summary.get("workflow"), dict)
                else {}
            ),
            "crosscheck_input_plans": crosscheck_route_states,
        },
        "tool_versions": {},
    }


def require_diana_wgs_artifact_index_binding(
    artifacts: Sequence[Mapping[str, Any]],
    deterministic_binding: Mapping[str, Any],
) -> None:
    indexed = {}
    for row in artifacts:
        path = str(row.get("path", ""))
        if path in indexed:
            raise ValueError(f"Diana WGS artifact index repeats {path}")
        indexed[path] = row

    if set(indexed) != set(DIANA_WGS_DETERMINISTIC_INPUTS):
        raise ValueError("Diana WGS artifact index is not exact")

    artifact_sha256 = deterministic_binding.get("artifact_sha256")
    if not isinstance(artifact_sha256, Mapping):
        raise ValueError("Diana WGS deterministic artifact SHA-256 map is missing")

    for relative, input_id in DIANA_WGS_DETERMINISTIC_INPUTS.items():
        row = indexed[relative]
        if (
            row.get("exists") != "yes"
            or require_sha256(row.get("sha256"), f"Diana WGS indexed {relative}")
            != require_sha256(
                artifact_sha256.get(input_id),
                f"Diana WGS deterministic {input_id}",
            )
        ):
            raise ValueError(
                f"Diana WGS artifact index differs from deterministic input {input_id}"
            )


def diana_wgs_readiness_rows(summary: Mapping[str, Any], blockers: list[str]) -> list[dict[str, Any]]:
    csv_rows: list[dict[str, Any]] = read_csv_or_empty("hrd_readiness.csv")
    embedded = summary.get("hrd_readiness", [])
    embedded_rows = [dict(row) for row in embedded if isinstance(row, dict)] if isinstance(embedded, list) else []
    if csv_rows and embedded_rows:
        fields = ("evidence_surface", "status", "detail")
        csv_contract = sorted(tuple(str(row.get(field, "")) for field in fields) for row in csv_rows)
        embedded_contract = sorted(tuple(str(row.get(field, "")) for field in fields) for row in embedded_rows)
        if csv_contract != embedded_contract:
            blockers.append("Diana WGS readiness CSV disagrees with the readiness contract embedded in diana_hrd_summary.json.")
            csv_by_surface = {str(row.get("evidence_surface", "")): row for row in csv_rows if row.get("evidence_surface")}
            embedded_by_surface = {
                str(row.get("evidence_surface", "")): row for row in embedded_rows if row.get("evidence_surface")
            }
            reconciled: list[dict[str, Any]] = []
            for surface in sorted(set(csv_by_surface) | set(embedded_by_surface)):
                csv_row = csv_by_surface.get(surface)
                embedded_row = embedded_by_surface.get(surface)
                row = dict(csv_row or embedded_row or {})
                if not csv_row or not embedded_row or csv_row.get("status") != embedded_row.get("status"):
                    row["status"] = "no_call"
                    row["detail"] = "Readiness artifacts disagree for this surface; no state promotion is accepted."
                reconciled.append(row)
            return reconciled
    elif csv_rows:
        blockers.append("Diana WGS summary is missing its embedded readiness contract; no CSV-only state promotion is accepted.")
        return [
            {
                **row,
                "status": "no_call",
                "detail": "The summary readiness contract is missing; no CSV-only state promotion is accepted.",
            }
            for row in csv_rows
        ]
    return csv_rows or embedded_rows


def bounded_diana_wgs_state(surface: str, state: str, blockers: list[str]) -> str:
    if state not in {"ready", "partial_evidence", "no_call"}:
        blockers.append(f"Diana WGS readiness surface {surface} has unsupported state {state or 'missing'}.")
        return "no_call"
    if surface in DIANA_WGS_NO_CALL_SURFACES and state != "no_call":
        blockers.append(
            f"Diana WGS readiness surface {surface} attempted promotion to {state}; the current packet contract preserves no_call."
        )
        return "no_call"
    if surface in DIANA_WGS_PARTIAL_ONLY_SURFACES and state == "ready":
        blockers.append(
            f"Diana WGS readiness surface {surface} attempted promotion to ready; the current evidence supports partial_evidence only."
        )
        return "partial_evidence"
    return state


def bounded_phase3_fast_state(surface: str, state: str, blockers: list[str]) -> str:
    if state not in {"ready", "partial_evidence", "no_call", "blocked"}:
        blockers.append(f"Phase 3 fast readiness surface {surface} has unsupported state {state or 'missing'}.")
        return "no_call"
    if surface in DIANA_WGS_PHASE3_FAST_NO_CALL_SURFACES and state != "no_call":
        blockers.append(
            f"Phase 3 fast readiness surface {surface} attempted promotion to {state}; the current packet contract preserves no_call."
        )
        return "no_call"
    if surface in DIANA_WGS_PHASE3_FAST_PARTIAL_ONLY_SURFACES and state == "ready":
        blockers.append(
            f"Phase 3 fast readiness surface {surface} attempted promotion to ready; the current evidence supports partial_evidence only."
        )
        return "partial_evidence"
    if surface in DIANA_WGS_PHASE3_FAST_BLOCKED_SURFACES and state not in {"blocked", "no_call"}:
        blockers.append(
            f"Phase 3 fast readiness surface {surface} attempted promotion to {state}; the current packet contract keeps it blocked."
        )
        return "blocked"
    return state


def diana_wgs_phase3_fast_evidence() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    report_root = diana_wgs_deterministic_report_dir()
    manifest = read_json(report_root / "report_manifest.json")
    if not isinstance(manifest, dict) or manifest.get("report_kind") != PHASE3_FAST_REPORT_KIND:
        raise ValueError("Diana WGS Phase 3 fast packet requires a phase3_fast_deterministic_evidence report")
    review_summary = manifest.get("review_summary")
    if not isinstance(review_summary, dict):
        raise ValueError("Diana WGS Phase 3 fast packet requires a deterministic review summary")
    groups = review_summary.get("artifact_groups")
    if not isinstance(groups, dict):
        groups = {}
    crosscheck_input_plans = read_json(report_root / "crosscheck_input_plans.json")
    crosscheck_routes = (
        crosscheck_input_plans.get("routes", {})
        if isinstance(crosscheck_input_plans, dict)
        else {}
    )
    sigprofiler_route = (
        crosscheck_routes.get("sigprofiler_sbs3", {})
        if isinstance(crosscheck_routes, dict)
        else {}
    )
    if not isinstance(sigprofiler_route, dict):
        sigprofiler_route = {}
    sequenza_route = (
        crosscheck_routes.get("sequenza_scarhrd", {})
        if isinstance(crosscheck_routes, dict)
        else {}
    )
    if not isinstance(sequenza_route, dict):
        sequenza_route = {}
    readiness_rows = parse_csv(read_text(report_root / "readiness.csv"))
    surfaces = [str(row.get("evidence_surface", "")) for row in readiness_rows if row.get("evidence_surface")]
    blockers: list[str] = []

    duplicate_surfaces = sorted({surface for surface in surfaces if surfaces.count(surface) > 1})
    if duplicate_surfaces:
        blockers.append(f"Phase 3 fast readiness contract has duplicate surfaces: {', '.join(duplicate_surfaces)}.")
    readiness_by_surface = {
        str(row.get("evidence_surface", "")): row
        for row in readiness_rows
        if row.get("evidence_surface")
    }
    missing_surfaces = [
        surface for surface in DIANA_WGS_PHASE3_FAST_READINESS_SURFACES
        if surface not in readiness_by_surface
    ]
    if missing_surfaces:
        blockers.append(f"Phase 3 fast readiness contract is missing surfaces: {', '.join(missing_surfaces)}.")

    def group_count(group: str) -> int:
        return require_nonnegative_int(groups.get(group, 0), f"Phase 3 fast {group} artifact count")

    def reason(surface: str) -> str:
        return str(readiness_by_surface.get(surface, {}).get("reason") or "Missing or incomplete readiness evidence.")

    evidence = [
        evidence_row(
            "phase3_fast_run_boundary",
            "no_call",
            (
                f"Phase 3 fast final evidence is partial_evidence across "
                f"{review_summary.get('artifact_count', 'unknown')} bound artifacts."
            ),
            "report_manifest.json",
            "The deterministic report authorizes sample-evidence review only; scalar HRD remains no_call.",
        ),
        evidence_row(
            "source_sha256",
            "ready",
            reason("source_sha256"),
            "input_sha256.csv",
            "SHA-256 custody proves byte identity, not HRD interpretability.",
        ),
        evidence_row(
            "matched_normal_somatic_variants",
            "ready",
            f"{group_count('small_variants')} Parabricks/FilterMutect artifacts were bound.",
            "report_manifest.json",
            "Filtered variants still require annotation, review, and second-hit context before HRD interpretation.",
        ),
        evidence_row(
            "wgs_bam_qc",
            "ready",
            f"{group_count('bam_qc')} tumor/normal samtools quickcheck, flagstat, and idxstats artifacts were bound.",
            "report_manifest.json",
        ),
        evidence_row(
            "coverage_cnv",
            "partial_evidence",
            reason("coverage_cnv"),
            "readiness.csv",
            "Coverage bins are not allele-specific CNV/LOH segments and are not scarHRD input.",
        ),
        evidence_row(
            "sbs96_input",
            "partial_evidence",
            reason("sbs96"),
            "readiness.csv",
            "SBS96 is an input matrix, not a validated SBS3 assignment.",
        ),
        evidence_row(
            "sigprofiler_sbs3_input_plan",
            "partial_evidence",
            (
                "Alias-only SigProfiler/SBS3 materialization is "
                f"{sigprofiler_route.get('status', 'missing')}; "
                f"execution is {sigprofiler_route.get('execution_status', 'missing')}."
            ),
            "crosscheck_input_plans.json",
            "This is an executable input plan only; SBS3 assignment and threshold policy remain no_call.",
        ),
        evidence_row(
            "sequenza_scarhrd_input_plan",
            "blocked",
            (
                "Alias-only Sequenza/scarHRD materialization is "
                f"{sequenza_route.get('status', 'missing')}; "
                f"execution is {sequenza_route.get('execution_status', 'missing')}."
            ),
            "crosscheck_input_plans.json",
            (
                "Finalized BAM aliases plus an explicit Sequenza sex model are required before "
                "materializing this route; scarHRD remains no_call."
            ),
        ),
        evidence_row(
            "bam_derived_sv_evidence",
            "partial_evidence",
            reason("sv"),
            "readiness.csv",
            "BAM-derived counters are not a validated production SV VCF/BEDPE and cannot support CHORD scoring.",
        ),
    ]

    labels = {
        "source_sha256": "Source SHA-256 integrity",
        "small_variants": "Matched-normal somatic variants",
        "bam_qc": "BAM QC",
        "coverage_cnv": "Coverage CNV proxy",
        "sv": "BAM-derived SV evidence",
        "sbs96": "SBS96 input matrix",
        "scarHRD": "scarHRD",
        "CHORD": "CHORD",
        "HRDetect": "HRDetect-style model",
        "overall_hrd": "Overall HRD classification",
    }
    next_actions = {
        "source_sha256": "Retain the checksum audit with this run.",
        "small_variants": "Annotate and review observed variants without promoting them to an HRD score.",
        "bam_qc": "Retain tumor/normal BAM QC as an input-integrity support surface.",
        "coverage_cnv": "Generate allele-specific total/minor copy-number segments with purity/ploidy.",
        "sv": "Generate a validated production SV VCF or BEDPE callset.",
        "sbs96": "Run a validated SBS3 assignment policy.",
        "scarHRD": "Supply validated allele-specific segments and purity/ploidy before scoring.",
        "CHORD": "Supply validated SV/CNV/small-variant feature adapters before scoring.",
        "HRDetect": "Lock all component adapters and validate a calibrated model before scoring.",
        "overall_hrd": "Keep no_call until every required component and integration policy passes validation.",
    }
    adapters: list[dict[str, str]] = []
    for surface in DIANA_WGS_PHASE3_FAST_READINESS_SURFACES:
        row = readiness_by_surface.get(surface, {})
        state = bounded_phase3_fast_state(surface, str(row.get("state", "")), blockers)
        adapters.append(
            adapter_row(
                labels[surface],
                state,
                "" if state == "ready" else str(row.get("reason") or "Missing or incomplete readiness evidence."),
                next_actions[surface],
            )
        )
    adapters.extend(
        [
            adapter_row(
                "Biallelic HRR/LOH evidence",
                "no_call",
                "No allele-specific CNV/LOH and curated second-hit assessment is present.",
                "Integrate annotated HRR events with allele-specific segments and purity-aware review.",
            ),
            adapter_row(
                "SBS3",
                "no_call",
                "No validated signature assignment or SBS3 threshold policy is present.",
                "Run validated signature assignment and known-answer calibration before interpreting SBS3.",
            ),
            adapter_row(
                "SigProfiler/SBS3 input materializer",
                "ready_to_materialize",
                "Alias-only inputs are planned but have not been materialized by the exact-version route.",
                "Run the materializer on exact final inputs, then stage a no-call SigProfiler/SBS3 cross-check report.",
            ),
            adapter_row(
                "Sequenza/scarHRD input materializer",
                "blocked",
                "Alias-only BAM/BAM-index inputs need a finalized contract and explicit Sequenza sex model.",
                "Publish the exact BAM contract with method_parameters.sequenza.female before staging Sequenza.",
            ),
        ]
    )
    return evidence, adapters, blockers


def diana_wgs_evidence() -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    if diana_wgs_deterministic_report_kind() == PHASE3_FAST_REPORT_KIND:
        return diana_wgs_phase3_fast_evidence()

    summary = read_json_or_empty("diana_hrd_summary.json")
    alignment = read_json_or_empty("alignment/bam_validation_summary.json")
    variants = read_json_or_empty("variants/mutect2_summary.json")
    cnv = read_json_or_empty("cnv/coverage_cnv_summary.json")
    signatures = read_json_or_empty("signatures/signature_assignment_summary.json")
    sv = read_json_or_empty("sv/sv_evidence_summary.json")
    blockers: list[str] = []
    readiness_rows = diana_wgs_readiness_rows(summary, blockers)

    summary_status = str(summary.get("status", "missing"))
    evidence_status = str(summary.get("evidence_status", "missing"))
    if summary_status != "no_call":
        blockers.append(
            f"Diana WGS summary status is {summary_status}; this packet requires the worker's explicit no_call HRD boundary."
        )
    if evidence_status != "partial_evidence":
        blockers.append(
            f"Diana WGS summary evidence_status is {evidence_status}; expected partial_evidence from the current worker schema."
        )
    if not summary.get("boundary"):
        blockers.append("Diana WGS summary is missing its interpretation boundary.")

    alignment_rows = alignment.get("rows", []) if isinstance(alignment.get("rows"), list) else []
    alignment_rows = [row for row in alignment_rows if isinstance(row, dict)]
    passed_alignment_rows = sum(str(row.get("status", "")) == "passed" for row in alignment_rows)
    total_reads = sum(as_int(row.get("total_reads")) for row in alignment_rows)
    mapped_reads = sum(as_int(row.get("mapped_reads")) for row in alignment_rows)
    alignment_status = str(alignment.get("status", "missing"))
    if alignment_status != "passed":
        blockers.append("Diana WGS alignment validation did not pass.")
    if alignment_status == "passed" and alignment_rows:
        alignment_detail = (
            f"{passed_alignment_rows}/{len(alignment_rows)} tumor/normal alignment rows passed; "
            f"mapped reads: {mapped_reads}/{total_reads}."
        )
    else:
        alignment_detail = "Alignment validation metrics are unavailable; no read counts are reported."

    variant_status = str(variants.get("status", "missing"))
    if variant_status != "passed":
        blockers.append("Diana WGS matched-normal small-variant generation did not pass.")
    hrr_region_records = as_int(variants.get("brca1_brca2_pass_region_records"))
    hrr_region_records_available = variant_status == "passed" and has_value(variants.get("brca1_brca2_pass_region_records"))
    if variant_status == "passed":
        variant_detail = (
            f"Filtered records: {variants.get('total_filtered_records', 'unknown')}; "
            f"PASS: {variants.get('pass_records', 'unknown')} "
            f"({variants.get('pass_snvs', 'unknown')} SNVs, {variants.get('pass_indels', 'unknown')} indels)."
        )
    else:
        variant_detail = "Matched-normal small-variant metrics are unavailable; no variant counts are reported."
    if not hrr_region_records_available:
        hrr_status = "no_call"
        hrr_detail = "The bounded HRR-region record count is unavailable; no negative finding is inferred."
    elif hrr_region_records > 0:
        hrr_status = "partial_evidence"
        hrr_detail = f"Observed HRR-region PASS records requiring annotation: {hrr_region_records}."
    else:
        hrr_status = "no_call"
        hrr_detail = "The completed bounded HRR-region extraction reported zero PASS records."

    cnv_status = str(cnv.get("status", "missing"))
    if cnv and has_value(cnv.get("bin_count")):
        cnv_detail = (
            f"Normalized bins: {cnv.get('bin_count')}; relative gains: "
            f"{cnv.get('relative_gain_bins', 'unknown')}; relative losses: {cnv.get('relative_loss_bins', 'unknown')}."
        )
    else:
        cnv_detail = "Coverage-CNV metrics are unavailable; no bin or gain/loss counts are reported."

    signature_status = str(signatures.get("status", "missing"))
    if signatures and has_value(signatures.get("usable_snv_records")):
        signature_detail = (
            f"Usable PASS SNVs: {signatures.get('usable_snv_records')}; "
            f"assignment readiness: {signatures.get('sigprofiler_assignment_status', 'unknown')}."
        )
    else:
        signature_detail = "SBS96 input metrics are unavailable; no usable-SNV count or SBS3 assignment is inferred."

    sv_rows = sv.get("rows", []) if isinstance(sv.get("rows"), list) else []
    sv_rows = [row for row in sv_rows if isinstance(row, dict)]
    discordant_pairs = sum(as_int(row.get("discordant_mapped_pairs")) for row in sv_rows)
    supplementary_alignments = sum(as_int(row.get("supplementary_alignments")) for row in sv_rows)
    sv_status = str(sv.get("status", "missing"))
    if sv_rows:
        sv_detail = (
            f"Rows: {len(sv_rows)}; discordant mapped pairs: {discordant_pairs}; "
            f"supplementary alignments: {supplementary_alignments}."
        )
    else:
        sv_detail = "BAM-derived SV metrics are unavailable; no zero-count finding or production SV callset is inferred."
    readiness_surfaces = [str(row.get("evidence_surface", "")) for row in readiness_rows if row.get("evidence_surface")]
    duplicate_surfaces = sorted({surface for surface in readiness_surfaces if readiness_surfaces.count(surface) > 1})
    if duplicate_surfaces:
        blockers.append(f"Diana WGS readiness contract has duplicate surfaces: {', '.join(duplicate_surfaces)}.")
    readiness_by_surface = {
        str(row.get("evidence_surface", "")): row
        for row in readiness_rows
        if row.get("evidence_surface")
    }
    missing_surfaces = [surface for surface in DIANA_WGS_READINESS_SURFACES if surface not in readiness_by_surface]
    if missing_surfaces:
        blockers.append(f"Diana WGS readiness contract is missing surfaces: {', '.join(missing_surfaces)}.")

    evidence = [
        evidence_row(
            "wgs_run_boundary",
            summary_status,
            (
                f"Overall HRD status: {summary_status}; evidence status: {evidence_status}; "
                f"reference: {summary.get('input', {}).get('reference', 'unknown') if isinstance(summary.get('input'), dict) else 'unknown'}."
            ),
            "diana_hrd_summary.json",
            "The worker explicitly emits sample-derived evidence with an overall HRD no-call boundary.",
        ),
        evidence_row(
            "wgs_alignment",
            alignment_status,
            alignment_detail,
            "alignment/bam_validation_summary.json",
        ),
        evidence_row(
            "matched_normal_somatic_variants",
            variant_status,
            variant_detail,
            "variants/mutect2_summary.json",
            "Research-use matched-normal calls require annotation and reviewer assessment.",
        ),
        evidence_row(
            "hrr_region_small_variants",
            hrr_status,
            hrr_detail,
            "variants/brca1_brca2_pass_variants.csv",
            "Region membership alone does not establish pathogenicity, germline/somatic origin, biallelic loss, or HRD.",
        ),
        evidence_row(
            "coverage_cnv",
            cnv_status,
            cnv_detail,
            "cnv/coverage_cnv_summary.json",
            "Coverage bins are not allele-specific CNV/LOH segments and are not scarHRD input.",
        ),
        evidence_row(
            "sbs96_input",
            signature_status,
            signature_detail,
            "signatures/signature_assignment_summary.json",
            "An SBS96 matrix is not an SBS3 assignment; SBS3 remains no_call.",
        ),
        evidence_row(
            "bam_derived_sv_evidence",
            sv_status,
            sv_detail,
            "sv/sv_evidence_summary.json",
            "BAM-derived counts are not a validated production SV callset and cannot support CHORD scoring.",
        ),
    ]

    labels = {
        "source_sha256": "Source SHA-256 integrity",
        "wgs_alignment": "WGS alignment",
        "matched_normal_somatic_variants": "Matched-normal somatic variants",
        "coverage_cnv": "Coverage CNV proxy",
        "sbs96": "SBS96 input matrix",
        "sv": "BAM-derived SV evidence",
        "scarHRD": "scarHRD",
        "CHORD": "CHORD",
        "HRDetect": "HRDetect-style model",
        "overall_hrd": "Overall HRD classification",
    }
    next_actions = {
        "source_sha256": "Retain the checksum audit with this run.",
        "wgs_alignment": "Retain BAM validation and reference provenance.",
        "matched_normal_somatic_variants": "Annotate and review observed variants without promoting them to an HRD score.",
        "coverage_cnv": "Generate allele-specific total/minor copy-number segments with purity/ploidy.",
        "sbs96": "Run a validated signature assignment adapter and lock SBS3 thresholds.",
        "sv": "Generate a validated production SV VCF or BEDPE callset.",
        "scarHRD": "Supply validated allele-specific segments and purity/ploidy before scoring.",
        "CHORD": "Supply validated SV/CNV/small-variant feature adapters before scoring.",
        "HRDetect": "Lock all component adapters and validate a calibrated model before scoring.",
        "overall_hrd": "Keep no_call until every required component and integration policy passes validation.",
    }
    adapters: list[dict[str, str]] = []
    for surface in DIANA_WGS_READINESS_SURFACES:
        row = readiness_by_surface.get(surface, {})
        state = bounded_diana_wgs_state(surface, str(row.get("status", "")), blockers)
        adapters.append(
            adapter_row(
                labels[surface],
                state,
                "" if state == "ready" else str(row.get("detail") or "Missing or incomplete readiness evidence."),
                next_actions[surface],
            )
        )
    adapters.extend(
        [
            adapter_row(
                "Biallelic HRR/LOH evidence",
                "no_call",
                "No allele-specific CNV/LOH and curated second-hit assessment is present.",
                "Integrate annotated HRR events with allele-specific segments and purity-aware review.",
            ),
            adapter_row(
                "SBS3",
                "no_call",
                str(signatures.get("sbs3_status", "Signature assignment and threshold policy are not locked.")),
                "Run validated signature assignment and known-answer calibration before interpreting SBS3.",
            ),
        ]
    )
    return evidence, adapters, blockers


EVIDENCE_BUILDERS = {
    "hcc1395_wes": hcc1395_wes_evidence,
    "hcc1395_wgs": hcc1395_wgs_evidence,
    "hg008": hg008_evidence,
    "colo829": colo829_evidence,
    "diana_raw_intake": diana_raw_intake_evidence,
    "diana_wgs": diana_wgs_evidence,
}


def research_context(spec: PacketSpec, evidence_rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    observed = [
        row
        for row in evidence_rows
        if row.get("status") not in {"no_call", "missing", "blocked"}
        and any(token in row.get("detail", "") for token in ("BRAF", "BRCA", "HRR"))
    ]
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


def diana_wgs_forbidden_tokens() -> list[str]:
    summary = read_json_or_empty("diana_hrd_summary.json")
    input_summary = summary.get("input", {}) if isinstance(summary.get("input"), dict) else {}
    tokens = [str(input_summary.get(key, "")).strip() for key in ("dataset", "pair")]
    raw = os.environ.get("ROSALIND_HRD_FORBIDDEN_TOKENS_JSON", "").strip()
    if raw:
        supplied = json.loads(raw)
        if not isinstance(supplied, list) or any(not isinstance(value, str) for value in supplied):
            raise ValueError("ROSALIND_HRD_FORBIDDEN_TOKENS_JSON must be a JSON string array")
        tokens.extend(value.strip() for value in supplied)
    return sorted({token for token in tokens if token}, key=str.casefold)


def scan_generated_packet(paths: Sequence[Path], forbidden_tokens: Sequence[str]) -> None:
    findings: list[str] = []
    for path in paths:
        lowered = path.read_text(encoding="utf-8").casefold()
        for token in forbidden_tokens:
            if token.casefold() in lowered:
                findings.append(f"{path.name}: forbidden identifier token")
    if findings:
        for path in paths:
            path.unlink(missing_ok=True)
        raise ValueError("Diana WGS generated-output identifier scan failed: " + "; ".join(findings))


def prepare_diana_wgs_output_dir(output: Path, expected_files: Iterable[str]) -> None:
    expected = set(expected_files)
    if output.is_symlink():
        raise ValueError("Diana WGS packet output may not be a symlink")
    if output.exists() and not output.is_dir():
        raise ValueError(f"Diana WGS packet output is not a directory: {output}")

    ensure_dir(output)

    unexpected: list[str] = []
    invalid: list[str] = []
    for path in output.iterdir():
        if path.name not in expected:
            unexpected.append(path.name)
        elif path.is_symlink() or not path.is_file():
            invalid.append(path.name)
    if unexpected:
        raise ValueError(
            "Diana WGS packet output contains unexpected existing files: "
            + ", ".join(sorted(unexpected))
        )
    if invalid:
        raise ValueError(
            "Diana WGS packet output contains invalid existing packet paths: "
            + ", ".join(sorted(invalid))
        )

    existing = sorted(path.name for path in output.iterdir() if path.name in expected)
    if existing:
        raise ValueError(
            "Diana WGS packet output already contains packet files: "
            + ", ".join(existing)
        )


def copy_diana_wgs_packet_file(source: Path, destination: Path) -> None:
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as error:
        raise ValueError(
            "Diana WGS packet output already exists: " + destination.name
        ) from error

    try:
        with source.open("rb") as source_handle, os.fdopen(
            descriptor, "wb"
        ) as destination_handle:
            descriptor = -1
            for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                destination_handle.write(chunk)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        destination.unlink(missing_ok=True)
        raise


def install_diana_wgs_packet(staged_paths: Sequence[Path], output: Path) -> None:
    installed: list[Path] = []
    try:
        for path in staged_paths:
            destination = output / path.name
            copy_diana_wgs_packet_file(path, destination)
            installed.append(destination)
    except Exception:
        for path in installed:
            path.unlink(missing_ok=True)
        raise


def write_packet(spec: PacketSpec, packet_run_id: str) -> dict[str, Any]:
    output_dir = f"{RESULT_ROOT}/{spec.sample_set}/{packet_run_id}"
    output_path = path_from_root(output_dir)
    if spec.sample_set == "diana_wgs":
        prepare_diana_wgs_output_dir(output_path, PACKET_REPORT_FILES)
        with tempfile.TemporaryDirectory(
            prefix=f".{output_path.name}.", dir=output_path.parent
        ) as staging:
            return write_packet_to_dir(
                spec, packet_run_id, output_dir, Path(staging), output_path
            )

    ensure_dir(output_path)
    return write_packet_to_dir(spec, packet_run_id, output_dir, output_path, None)


def diana_wgs_deterministic_process_lines(deterministic_binding: Mapping[str, Any]) -> list[str]:
    if deterministic_binding.get("binding_kind") == "phase3_fast_final":
        phase3_fast = deterministic_binding.get("phase3_fast", {})
        if not isinstance(phase3_fast, Mapping):
            phase3_fast = {}
        workflow = phase3_fast.get("workflow", {})
        if not isinstance(workflow, Mapping):
            workflow = {}
        crosscheck_input_plans = phase3_fast.get("crosscheck_input_plans", {})
        if not isinstance(crosscheck_input_plans, Mapping):
            crosscheck_input_plans = {}
        return [
            "## Deterministic custody and process",
            "",
            f"Deterministic report SHA-256: `{deterministic_binding['deterministic_report_sha256']}`.",
            f"Deterministic manifest SHA-256: `{deterministic_binding['deterministic_manifest_sha256']}`.",
            f"Phase 3 fast workflow: `{workflow.get('name', 'phase3_wgs_fast')}`.",
            f"Final artifact binding: {deterministic_binding['artifact_count']} Phase 3 fast final artifacts matched the deterministic input inventory.",
            f"SigProfiler/SBS3 input materialization: `{crosscheck_input_plans.get('sigprofiler_sbs3', 'missing')}`.",
            f"Sequenza/scarHRD input materialization: `{crosscheck_input_plans.get('sequenza_scarhrd', 'missing')}`.",
            "",
        ]

    return [
        "## Deterministic custody and process",
        "",
        f"Deterministic report SHA-256: `{deterministic_binding['deterministic_report_sha256']}`.",
        f"Deterministic manifest SHA-256: `{deterministic_binding['deterministic_manifest_sha256']}`.",
        f"Artifact binding: {deterministic_binding['artifact_count']}/{len(DIANA_WGS_DETERMINISTIC_INPUTS)} required worker artifacts matched the deterministic input inventory.",
        "Private freeze custody: passed; exact destination KMS match: yes; exact receipt VersionIds retained.",
        "",
        "### Tool versions",
        "",
        markdown_table(
            [
                {"tool": tool, "version": version}
                for tool, version in deterministic_binding["tool_versions"].items()
            ]
        ),
        "",
    ]


def write_packet_to_dir(
    spec: PacketSpec,
    packet_run_id: str,
    output_dir: str,
    output_path: Path,
    final_output_path: Path | None,
) -> dict[str, Any]:
    evidence_rows, adapter_rows, blockers = EVIDENCE_BUILDERS[spec.sample_set]()
    deterministic_binding = (
        diana_wgs_deterministic_binding() if spec.sample_set == "diana_wgs" else None
    )
    if (
        spec.sample_set == "diana_wgs"
        and deterministic_binding is not None
        and deterministic_binding.get("binding_kind") == "phase3_fast_final"
    ):
        artifacts = list(deterministic_binding["artifact_index"])
    else:
        artifacts = artifact_index(
            spec.artifacts, logical_paths_only=spec.sample_set == "diana_wgs"
        )
    if (
        spec.sample_set == "diana_wgs"
        and deterministic_binding is not None
        and deterministic_binding.get("binding_kind") != "phase3_fast_final"
    ):
        require_diana_wgs_artifact_index_binding(artifacts, deterministic_binding)
    missing_artifacts = [row["path"] for row in artifacts if row["exists"] != "yes"]
    if missing_artifacts:
        blockers.extend(f"Missing artifact: {path}" for path in missing_artifacts)

    input_index_path = output_path / "input_evidence_index.json"
    evidence_summary_path = output_path / "sample_validation_summary.csv"
    adapter_status_path = output_path / "hrd_adapter_status.csv"
    research_context_path = output_path / "research_context_sources.json"
    next_actions_path = output_path / "next_actions.md"
    reviewer_packet_path = output_path / "reviewer_packet.md"
    report_path = output_path / "report.md"
    report_manifest_path = output_path / "report_manifest.json"

    write_json_create_only(
        input_index_path, {"sampleSet": spec.sample_set, "artifacts": artifacts}
    )
    write_csv_create_only(evidence_summary_path, evidence_rows)
    write_csv_create_only(adapter_status_path, adapter_rows)
    write_json_create_only(research_context_path, research_context(spec, evidence_rows))
    write_text_create_only(
        next_actions_path,
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
    process_lines = diana_wgs_deterministic_process_lines(deterministic_binding) if deterministic_binding else []
    reviewer_report = "\n".join(
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
            *process_lines,
            "## Blockers",
            *(f"- {blocker}" for blocker in blockers),
            *(["- None beyond the listed adapter no-call boundaries."] if not blockers else []),
            "",
            "## Research Context Boundary",
            "Use external databases only to enrich observed sample events. Do not use literature or database context to override missing inputs, failed QC, or no-call adapter states.",
        ]
    )
    write_text_create_only(reviewer_packet_path, reviewer_report)
    write_text_create_only(report_path, reviewer_report)
    evidence_status = packet_evidence_status(evidence_rows)
    generated_paths = {
        "input_evidence_index.json": input_index_path,
        "sample_validation_summary.csv": evidence_summary_path,
        "hrd_adapter_status.csv": adapter_status_path,
        "research_context_sources.json": research_context_path,
        "next_actions.md": next_actions_path,
        "reviewer_packet.md": reviewer_packet_path,
    }
    source_sha256 = (
        dict(deterministic_binding["artifact_sha256"])
        if deterministic_binding
        else {
            f"source_artifact_{index:03d}": str(row["sha256"])
            for index, row in enumerate(artifacts, 1)
            if row.get("sha256")
        }
    )
    report_manifest = {
        "schema_version": 1,
        "method_id": f"rosalind_{spec.sample_set}",
        "report_kind": "rosalind_hrd_reviewer_packet",
        "evidence_status": evidence_status,
        "authorized_hrd_state": "no_call",
        "classification_authorized": False,
        "classification_qc_status": "not_applicable",
        "support_sha256": {
            name: sha256_file(path) for name, path in sorted(generated_paths.items())
        },
        "source_sha256": source_sha256,
        "report_sha256": sha256_file(report_path),
        "review_summary": {
            "overall": {
                "evidence_status": evidence_status,
                "authorized_hrd_state": "no_call",
            },
            "packet_type": spec.sample_set,
            "allowed_conclusion": spec.allowed_conclusion,
            "evidence": [
                {
                    key: str(row.get(key, ""))
                    for key in ("evidence_id", "status", "detail", "caveat")
                }
                for row in evidence_rows
            ],
            "adapters": [
                {
                    key: str(row.get(key, ""))
                    for key in ("adapter", "state", "blocker", "next_action")
                }
                for row in adapter_rows
            ],
            "blockers": list(blockers),
            **({"provenance": deterministic_binding} if deterministic_binding else {}),
        },
    }
    write_json_create_only(report_manifest_path, report_manifest)
    packet_files = [*generated_paths.values(), report_path, report_manifest_path]
    if spec.sample_set == "diana_wgs":
        scan_generated_packet(
            packet_files,
            diana_wgs_forbidden_tokens(),
        )
    report_manifest_sha256 = sha256_file(report_manifest_path)
    if final_output_path is not None:
        install_diana_wgs_packet(packet_files, final_output_path)
    return {
        "sampleSet": spec.sample_set,
        "title": spec.title,
        "outputDir": output_dir,
        "evidenceRows": len(evidence_rows),
        "adapterRows": len(adapter_rows),
        "blockers": blockers,
        "missingArtifacts": missing_artifacts,
        "allowedConclusion": spec.allowed_conclusion,
        "evidenceStatus": evidence_status,
        "reportManifest": f"{output_dir}/report_manifest.json",
        "reportManifestSha256": report_manifest_sha256,
    }


def write_cloud_materialization_plan(root: str, packet_run_id: str, packet_summaries: Sequence[Mapping[str, Any]]) -> None:
    sample_sets = ",".join(str(packet.get("sampleSet", "")) for packet in packet_summaries if packet.get("sampleSet"))
    includes_diana_wgs = any(packet.get("sampleSet") == "diana_wgs" for packet in packet_summaries)
    required_prefixes = sorted(
        {
            str(Path(path).parts[0])
            for packet in packet_summaries
            for path in packet.get("missingArtifacts", [])
            if Path(str(path)).parts
        }
    )
    write_text_create_only(
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
                f"export ROSALIND_HRD_SAMPLE_SET={sample_sets}",
                "PYTHONPATH=src /usr/bin/python3 -m diana_omics build:rosalind-hrd-packet",
                "```",
                "",
                "Materialize the artifact root so paths like `results/phase3_wgs_smoke/phase3_wgs_summary.json` resolve under `$ROSALIND_HRD_ARTIFACT_ROOT`.",
                "",
                *(
                    [
                        "For `diana_wgs`, point `ROSALIND_HRD_ARTIFACT_ROOT` at the worker artifact directory that directly contains `diana_hrd_summary.json`, `hrd_readiness.csv`, and the `alignment/`, `variants/`, `cnv/`, `signatures/`, and `sv/` directories.",
                        "Do not point it at the parent run directory unless those artifacts have been materialized at that level.",
                        "",
                    ]
                    if includes_diana_wgs
                    else []
                ),
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
    write_json_create_only(path_from_root(f"{root}/run_manifest.json"), manifest)
    write_text_create_only(
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
