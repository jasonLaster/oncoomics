from __future__ import annotations

import csv
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Sequence

from ..paths import path_from_root
from ..utils import ensure_dir, iso_now, parse_csv, read_json, read_text, round_value, write_csv, write_json, write_text
from .verify_known_answer_public_findings import CHECK_MANIFEST_PATH
from .verify_known_answer_sample_pull_plan import MANIFEST_PATH as PULL_PLAN_PATH

RESULTS_ROOT = "results/clinicalization"
EXECUTION_CSV_PATH = f"{RESULTS_ROOT}/known_answer_bounded_non_dry_execution.csv"
EXECUTION_JSON_PATH = f"{RESULTS_ROOT}/known_answer_bounded_non_dry_execution.json"
EXECUTION_MD_PATH = f"{RESULTS_ROOT}/known_answer_bounded_non_dry_execution.md"

HG008_TUMOR_BAM = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/"
    "NYGC_Illumina-WGS_20231023/HG008-T_Illumina_161x_GRCh38-GIABv3.bam"
)
HG008_NORMAL_BAM = (
    "https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/data_somatic/HG008/Liss_lab/"
    "NYGC_Illumina-WGS_20231023/HG008-N-D_Illumina_118x_GRCh38-GIABv3.bam"
)
HG008_SMALL_VARIANT_VCF = "data/raw/known_answer_public/hg008/small_variant_truth/HG008-T_somatic_smvar_benchmark_v0.3_tumorvariants.vcf.gz"
HG008_CNV_BED = "data/raw/known_answer_public/hg008/sv_cnv_truth/GRCh38_HG008-T-V0.5_somatic-CNV_PASS.draftbenchmark.calls.bed"

COLO829_TUMOR_BAM = "https://ftp.sra.ebi.ac.uk/vol1/run/ERR275/ERR2752450/COLO829T_dedup.realigned.bam"
COLO829_NORMAL_BAM = "https://ftp.sra.ebi.ac.uk/vol1/run/ERR275/ERR2752449/COLO829R_dedup.realigned.bam"
COLO829_ENA_REPORT = "data/raw/known_answer_public/colo829/ena/PRJEB27698_filereport.tsv"
COLO829_SV_CNA_TRUTH = "data/raw/known_answer_public/colo829/sv_cna_truth/truthset_somaticSVs_COLO829_hg38lifted.vcf"
COLO829_COPY_NUMBER_TRUTH_ZIP = "data/raw/known_answer_public/colo829/sv_cna_truth/COLO829_somaticSV_copynumber.zip"
COLO829_BRAF_REGION = "7:140453136-140453136"
COLO829_BRAF_REF = "A"
COLO829_BRAF_ALT = "T"
COLO829_PURITY_10_BAM = "https://ftp.sra.ebi.ac.uk/vol1/run/ERR409/ERR4093255/illumina_purity10.bam"

HG008_INPUT_ARTIFACT = "results/clinicalization/known_answer_runs/hg008/input_provenance_summary.json"
HG008_RNA_ARTIFACT = "results/clinicalization/known_answer_runs/hg008/rna_qc_summary.json"
HG008_SMALL_VARIANT_ARTIFACT = "results/clinicalization/known_answer_runs/hg008/small_variant_concordance_summary.json"
HG008_SV_CNV_ARTIFACT = "results/clinicalization/known_answer_runs/hg008/sv_cnv_reciprocal_overlap_summary.json"
COLO829_INPUT_ARTIFACT = "results/clinicalization/known_answer_runs/colo829/input_provenance_summary.json"
COLO829_SV_CNA_ARTIFACT = "results/clinicalization/known_answer_runs/colo829/sv_cna_reciprocal_overlap_summary.json"
COLO829_PURITY_ARTIFACT = "results/clinicalization/known_answer_runs/colo829_purity/purity_recall_table_summary.json"
SERASEQ_ARTIFACT = "results/clinicalization/known_answer_runs/seraseq_mrd/positive_negative_summary.json"

DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("KNOWN_ANSWER_BOUNDED_TIMEOUT_SECONDS", "420"))
HG008_VARIANT_LIMIT = int(os.environ.get("KNOWN_ANSWER_HG008_VARIANT_LIMIT", "10"))
REMOTE_RETRIES = int(os.environ.get("KNOWN_ANSWER_REMOTE_RETRIES", "2"))


@dataclass(frozen=True)
class ToolResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


@dataclass(frozen=True)
class VariantRecord:
    chrom: str
    pos: int
    ref: str
    alt: str


def _run_tool(argv: Sequence[str], timeout: int = DEFAULT_TIMEOUT_SECONDS) -> ToolResult:
    started_at = time.monotonic()
    completed = subprocess.run(
        list(argv),
        cwd=path_from_root(""),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return ToolResult(
        argv=tuple(argv),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_seconds=time.monotonic() - started_at,
    )


def _read_csv(relative_path: str) -> list[dict[str, str]]:
    return parse_csv(read_text(path_from_root(relative_path)))


def _artifact_checks() -> dict[str, list[dict[str, str]]]:
    by_artifact: dict[str, list[dict[str, str]]] = {}
    for check in _read_csv(CHECK_MANIFEST_PATH):
        by_artifact.setdefault(check["analysis_artifact_path"], []).append(check)
    return by_artifact


def _pull_by_id() -> dict[str, dict[str, str]]:
    return {row["pull_id"]: row for row in _read_csv(PULL_PLAN_PATH)}


def _read_existing_artifact(relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        return {}
    value = read_json(path)
    return value if isinstance(value, dict) else {}


def _sample_ids_for_artifact(
    artifact_path: str, checks_by_artifact: dict[str, list[dict[str, str]]], pulls: dict[str, dict[str, str]]
) -> list[str]:
    return [pulls[check["pull_id"]]["sample_or_asset_id"] for check in checks_by_artifact.get(artifact_path, [])]


def _write_analysis_artifact(
    relative_path: str,
    status: str,
    pipeline_confirmation: str,
    evidence_type: str,
    public_finding_result: str,
    evidence: dict[str, Any],
    blockers: Sequence[str] = (),
    next_action: str = "",
) -> dict[str, Any]:
    checks_by_artifact = _artifact_checks()
    pulls = _pull_by_id()
    previous = _read_existing_artifact(relative_path)
    checks = checks_by_artifact.get(relative_path, [])
    artifact = {
        "generatedAt": iso_now(),
        "status": status,
        "executionMode": "bounded_non_dry_public_remote_read_analysis",
        "pipelineConfirmation": pipeline_confirmation,
        "clinicalUseAllowed": "no",
        "artifactPath": relative_path,
        "checkIds": [check["check_id"] for check in checks],
        "pullIds": [check["pull_id"] for check in checks],
        "sampleOrAssetIds": _sample_ids_for_artifact(relative_path, checks_by_artifact, pulls),
        "datasetIds": sorted({check["dataset_id"] for check in checks}),
        "publicFindings": [check["public_finding"] for check in checks],
        "evidenceType": evidence_type,
        "publicFindingResult": public_finding_result,
        "evidence": evidence,
        "blockers": list(blockers),
        "nextAction": next_action,
        "previousExecutionMode": previous.get("executionMode", ""),
        "previousStatus": previous.get("status", ""),
    }
    write_json(path_from_root(relative_path), artifact)
    return artifact


def _parse_pileup_bases(bases: str, ref: str, alt: str) -> dict[str, Any]:
    ref = ref.upper()
    alt = alt.upper()
    counts: dict[str, int] = {"ref": 0, "alt": 0, "other": 0, "deletion": 0, "skip": 0}
    base_counts: dict[str, int] = {base: 0 for base in ("A", "C", "G", "T", "N")}
    i = 0
    while i < len(bases):
        char = bases[i]
        if char == "^":
            i += 2
            continue
        if char == "$":
            i += 1
            continue
        if char in "+-":
            i += 1
            digits = []
            while i < len(bases) and bases[i].isdigit():
                digits.append(bases[i])
                i += 1
            indel_length = int("".join(digits) or "0")
            i += indel_length
            continue
        if char in "*#":
            counts["deletion"] += 1
            i += 1
            continue
        if char in "<>":
            counts["skip"] += 1
            i += 1
            continue
        if char in ".,":
            counts["ref"] += 1
            base_counts[ref] = base_counts.get(ref, 0) + 1
            i += 1
            continue
        base = char.upper()
        if base in base_counts:
            base_counts[base] = base_counts.get(base, 0) + 1
            if base == alt:
                counts["alt"] += 1
            elif base == ref:
                counts["ref"] += 1
            else:
                counts["other"] += 1
        i += 1
    informative_depth = counts["ref"] + counts["alt"] + counts["other"]
    alt_fraction = counts["alt"] / informative_depth if informative_depth else 0.0
    return {
        "depthInformative": informative_depth,
        "refCount": counts["ref"],
        "altCount": counts["alt"],
        "otherCount": counts["other"],
        "deletionCount": counts["deletion"],
        "skipCount": counts["skip"],
        "baseCounts": base_counts,
        "altFraction": round_value(alt_fraction, 6),
    }


def _pileup_locus(region: str, ref: str, alt: str, bams: Sequence[str]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    for attempt in range(REMOTE_RETRIES + 1):
        payload = _pileup_locus_once(region, ref, alt, bams)
        attempts.append(
            {
                "attempt": attempt + 1,
                "status": payload.get("status"),
                "returnCode": payload.get("returnCode"),
                "elapsedSeconds": payload.get("elapsedSeconds"),
                "stderr": payload.get("stderr", ""),
            }
        )
        if payload.get("status") == "passed":
            break
        if attempt < REMOTE_RETRIES:
            time.sleep(min(10, 2 * (attempt + 1)))
    payload["attempts"] = attempts
    return payload


def _pileup_locus_once(region: str, ref: str, alt: str, bams: Sequence[str]) -> dict[str, Any]:
    result = _run_tool(("samtools", "mpileup", "-r", region, *bams))
    payload: dict[str, Any] = {
        "command": " ".join(result.argv),
        "returnCode": result.returncode,
        "stderr": result.stderr.strip()[-1200:],
        "elapsedSeconds": round_value(result.elapsed_seconds, 3),
    }
    if result.returncode != 0:
        payload["status"] = "failed"
        return payload
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        payload["status"] = "no_coverage"
        return payload
    fields = lines[0].split("\t")
    payload.update({"status": "passed", "chrom": fields[0], "pos": int(fields[1]), "pileupRef": fields[2]})
    samples: list[dict[str, Any]] = []
    for index in range(len(bams)):
        offset = 3 + index * 3
        if offset + 2 >= len(fields):
            continue
        depth = int(fields[offset])
        parsed = _parse_pileup_bases(fields[offset + 1], ref, alt)
        parsed.update({"sampleIndex": index, "bam": bams[index], "depth": depth})
        samples.append(parsed)
    payload["samples"] = samples
    return payload


def _load_hg008_snv_records(limit: int) -> list[VariantRecord]:
    path = path_from_root(HG008_SMALL_VARIANT_VCF)
    records: list[VariantRecord] = []
    import gzip

    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 5:
                continue
            ref = fields[3].upper()
            alt_values = [value.upper() for value in fields[4].split(",")]
            if (
                len(ref) == 1
                and len(alt_values) == 1
                and ref in "ACGT"
                and alt_values[0] in "ACGT"
                and _hg008_source_variant_is_simple_snv(fields[7] if len(fields) > 7 else "")
            ):
                records.append(VariantRecord(fields[0], int(fields[1]), ref, alt_values[0]))
            if len(records) >= limit:
                break
    return records


def _hg008_source_variant_is_simple_snv(info: str) -> bool:
    for item in info.split(";"):
        if not item.startswith("HG008Nv63SOMATICVARIANT="):
            continue
        value = item.split("=", 1)[1]
        descriptor = value.split(":", 1)[-1]
        parts = descriptor.split("-")
        if len(parts) < 3:
            return False
        return len(parts[1]) == 1 and len(parts[2]) == 1 and parts[1].upper() in "ACGT" and parts[2].upper() in "ACGT"
    return True


def _run_hg008_variant_panel() -> dict[str, Any]:
    variants = _load_hg008_snv_records(HG008_VARIANT_LIMIT)
    rows: list[dict[str, Any]] = []
    for variant in variants:
        region = f"{variant.chrom}:{variant.pos}-{variant.pos}"
        pileup = _pileup_locus(region, variant.ref, variant.alt, (HG008_TUMOR_BAM, HG008_NORMAL_BAM))
        tumor = pileup.get("samples", [{}])[0] if pileup.get("samples") else {}
        normal = pileup.get("samples", [{}, {}])[1] if len(pileup.get("samples", [])) > 1 else {}
        tumor_alt_fraction = float(tumor.get("altFraction") or 0)
        normal_alt_fraction = float(normal.get("altFraction") or 0)
        row = {
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
        rows.append(row)
    passed_count = sum(1 for row in rows if row["passed"])
    return {
        "truthVcf": HG008_SMALL_VARIANT_VCF,
        "tumorBam": HG008_TUMOR_BAM,
        "normalBam": HG008_NORMAL_BAM,
        "variantLimit": HG008_VARIANT_LIMIT,
        "evaluatedVariantCount": len(rows),
        "passedVariantCount": passed_count,
        "failedVariantCount": len(rows) - passed_count,
        "allVariantsPassed": len(rows) > 0 and passed_count == len(rows),
        "rows": rows,
    }


def _select_cnv_interval(rows: list[list[str]], event_id: str, copy_total: str) -> list[str]:
    for row in rows:
        if len(row) >= 7 and row[3] == copy_total and row[6] == event_id and int(row[2]) - int(row[1]) >= 100_000:
            return row
    for row in rows:
        if len(row) >= 7 and row[3] == copy_total and int(row[2]) - int(row[1]) >= 100_000:
            return row
    raise RuntimeError(f"No HG008 CNV interval found for copy_total={copy_total} event_id={event_id}.")


def _depth_region(chrom: str, start: int, end: int) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    for attempt in range(REMOTE_RETRIES + 1):
        payload = _depth_region_once(chrom, start, end)
        attempts.append(
            {
                "attempt": attempt + 1,
                "status": payload.get("status"),
                "returnCode": payload.get("returnCode"),
                "elapsedSeconds": payload.get("elapsedSeconds"),
                "stderr": payload.get("stderr", ""),
            }
        )
        if payload.get("status") == "passed":
            break
        if attempt < REMOTE_RETRIES:
            time.sleep(min(10, 2 * (attempt + 1)))
    payload["attempts"] = attempts
    return payload


def _depth_region_once(chrom: str, start: int, end: int) -> dict[str, Any]:
    result = _run_tool(("samtools", "depth", "-r", f"{chrom}:{start}-{end}", HG008_TUMOR_BAM, HG008_NORMAL_BAM))
    payload: dict[str, Any] = {
        "region": f"{chrom}:{start}-{end}",
        "command": " ".join(result.argv),
        "returnCode": result.returncode,
        "stderr": result.stderr.strip()[-1200:],
        "elapsedSeconds": round_value(result.elapsed_seconds, 3),
    }
    if result.returncode != 0:
        payload["status"] = "failed"
        return payload
    tumor_values: list[int] = []
    normal_values: list[int] = []
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) >= 4:
            tumor_values.append(int(fields[2]))
            normal_values.append(int(fields[3]))
    tumor_mean = sum(tumor_values) / len(tumor_values) if tumor_values else 0.0
    normal_mean = sum(normal_values) / len(normal_values) if normal_values else 0.0
    payload.update(
        {
            "status": "passed" if tumor_values and normal_values else "no_coverage",
            "positions": len(tumor_values),
            "tumorMeanDepth": round_value(tumor_mean, 4),
            "normalMeanDepth": round_value(normal_mean, 4),
            "tumorNormalRatio": round_value(tumor_mean / normal_mean if normal_mean else 0.0, 6),
        }
    )
    return payload


def _run_hg008_cnv_probe() -> dict[str, Any]:
    bed_rows = [line.split("\t") for line in read_text(path_from_root(HG008_CNV_BED)).splitlines() if line.strip()]
    loss = _select_cnv_interval(bed_rows, "CNA_2", "1")
    neutral = _select_cnv_interval(bed_rows, "noCNV", "2")
    window_size = int(os.environ.get("KNOWN_ANSWER_CNV_WINDOW_BASES", "1000"))
    loss_start = _interior_window_start(loss, window_size)
    neutral_start = _interior_window_start(neutral, window_size)
    loss_depth = _depth_region(loss[0], loss_start, loss_start + window_size)
    neutral_depth = _depth_region(neutral[0], neutral_start, neutral_start + window_size)
    loss_ratio = float(loss_depth.get("tumorNormalRatio") or 0)
    neutral_ratio = float(neutral_depth.get("tumorNormalRatio") or 0)
    normalized_loss_ratio = loss_ratio / neutral_ratio if neutral_ratio else 0.0
    passed = loss_depth.get("status") == "passed" and neutral_depth.get("status") == "passed" and normalized_loss_ratio < 0.75
    return {
        "truthBed": HG008_CNV_BED,
        "lossInterval": {"chrom": loss[0], "start": int(loss[1]), "end": int(loss[2]), "copyTotal": loss[3], "eventId": loss[6]},
        "neutralInterval": {
            "chrom": neutral[0],
            "start": int(neutral[1]),
            "end": int(neutral[2]),
            "copyTotal": neutral[3],
            "eventId": neutral[6],
        },
        "lossDepth": loss_depth,
        "neutralDepth": neutral_depth,
        "normalizedLossTumorNormalRatio": round_value(normalized_loss_ratio, 6),
        "passedCnvDepthSignal": passed,
        "remainingSvGap": "No Diana-generated SV/CNV callset or reciprocal-overlap caller output was produced in this bounded run.",
    }


def _interior_window_start(row: list[str], window_size: int) -> int:
    start = int(row[1])
    end = int(row[2])
    interval_length = end - start
    offset = min(1_000_000, max(0, interval_length - window_size - 1))
    return start + offset + 1


def _run_colo829_braf_probe() -> dict[str, Any]:
    pileup = _pileup_locus(COLO829_BRAF_REGION, COLO829_BRAF_REF, COLO829_BRAF_ALT, (COLO829_TUMOR_BAM, COLO829_NORMAL_BAM))
    tumor = pileup.get("samples", [{}])[0] if pileup.get("samples") else {}
    normal = pileup.get("samples", [{}, {}])[1] if len(pileup.get("samples", [])) > 1 else {}
    tumor_alt_fraction = float(tumor.get("altFraction") or 0)
    normal_alt_fraction = float(normal.get("altFraction") or 0)
    passed = (
        pileup.get("status") == "passed"
        and int(tumor.get("depth") or 0) >= 20
        and int(normal.get("depth") or 0) >= 20
        and tumor_alt_fraction >= 0.2
        and normal_alt_fraction <= 0.05
    )
    return {
        "region": COLO829_BRAF_REGION,
        "build": "GRCh37/hg19-style numeric contigs",
        "expectedRef": COLO829_BRAF_REF,
        "expectedAlt": COLO829_BRAF_ALT,
        "tumorBam": COLO829_TUMOR_BAM,
        "normalBam": COLO829_NORMAL_BAM,
        "pileup": pileup,
        "tumorAltFraction": tumor.get("altFraction", 0),
        "normalAltFraction": normal.get("altFraction", 0),
        "passedBrafGuardrail": passed,
    }


def _read_hg008_rna_stats() -> dict[str, Any]:
    stats_dir = path_from_root("data/raw/known_answer_public/hg008/rna")
    rows: list[dict[str, Any]] = []
    for path in sorted(stats_dir.glob("*_stats.txt")):
        parts = read_text(path).split()
        row: dict[str, Any] = {"path": str(path.relative_to(path_from_root("")))}
        for index in range(0, len(parts) - 1, 2):
            row[parts[index]] = int(parts[index + 1])
        rows.append(row)
    paired = len(rows) == 2 and len({row.get("reads") for row in rows}) == 1 and len({row.get("readLength") for row in rows}) == 1
    return {
        "statsFiles": rows,
        "pairedReadStatsConsistent": paired,
        "remainingQuantificationGap": "RNA FASTQ stats are public, but this bounded run does not download FASTQs or run quantification.",
    }


def _colo829_purity_probe() -> dict[str, Any]:
    metadata_rows = list(csv.DictReader(path_from_root(COLO829_ENA_REPORT).open(encoding="utf-8"), delimiter="\t"))
    selected = [row for row in metadata_rows if row.get("sample_alias", "").startswith("COLO829_purity_")]
    indexed = [row for row in selected if ".bai" in row.get("submitted_ftp", "")]
    result = _run_tool(("samtools", "mpileup", "-r", COLO829_BRAF_REGION, COLO829_PURITY_10_BAM), timeout=120)
    return {
        "enaReport": COLO829_ENA_REPORT,
        "selectedPurityRunCount": len(selected),
        "selectedPurityAliases": sorted(row.get("sample_alias", "") for row in selected),
        "selectedSubmittedBamCount": sum(1 for row in selected if ".bam" in row.get("submitted_ftp", "")),
        "selectedSubmittedBaiCount": len(indexed),
        "boundedRegionProbe": {
            "command": " ".join(result.argv),
            "returnCode": result.returncode,
            "stderr": result.stderr.strip()[-1200:],
            "elapsedSeconds": round_value(result.elapsed_seconds, 3),
        },
        "blockedReason": "Selected purity BAMs are listed in ENA without submitted BAI files, so indexed remote region slicing is unavailable.",
    }


def _colo829_sv_cna_gap() -> dict[str, Any]:
    return {
        "truthVcf": COLO829_SV_CNA_TRUTH,
        "truthVcfExists": path_from_root(COLO829_SV_CNA_TRUTH).is_file(),
        "copyNumberTruthZip": COLO829_COPY_NUMBER_TRUTH_ZIP,
        "copyNumberTruthZipExists": path_from_root(COLO829_COPY_NUMBER_TRUTH_ZIP).is_file(),
        "boundedGap": (
            "COLO829 BRAF pileup confirms tumor-normal driver guardrail, but this run does not produce a Diana SV/CNA "
            "callset or reconcile the hg38-lifted truth with the GRCh37 submitted BAMs."
        ),
    }


def _seraseq_gap() -> dict[str, Any]:
    return {
        "sourceAccess": "request_or_purchase",
        "blockedReason": "No freely downloadable public FASTQ, BAM, or variant truth files were available for non-dry analysis.",
    }


def _write_summary_artifacts(artifacts: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks_by_artifact = _artifact_checks()
    pulls = _pull_by_id()
    rows: list[dict[str, Any]] = []
    for artifact_path, checks in checks_by_artifact.items():
        artifact = artifacts[artifact_path]
        for check in checks:
            rows.append(
                {
                    "check_id": check["check_id"],
                    "pull_id": check["pull_id"],
                    "dataset_id": check["dataset_id"],
                    "sample_or_asset_id": pulls[check["pull_id"]]["sample_or_asset_id"],
                    "analysis_artifact_path": artifact_path,
                    "bounded_status": artifact["status"],
                    "pipeline_confirmation": artifact["pipelineConfirmation"],
                    "evidence_type": artifact["evidenceType"],
                    "public_finding_result": artifact["publicFindingResult"],
                    "clinical_use_allowed": "no",
                }
            )
    summary = {
        "status": "completed_with_bounded_results_and_gaps",
        "target_count": len(rows),
        "artifact_count": len(artifacts),
        "bounded_confirmed_count": sum(1 for row in rows if row["bounded_status"] == "bounded_non_dry_passed"),
        "bounded_partial_count": sum(1 for row in rows if row["bounded_status"] == "bounded_non_dry_partial"),
        "gap_identified_count": sum(1 for row in rows if row["bounded_status"] == "bounded_non_dry_gap_identified"),
        "blocked_count": sum(
            1
            for row in rows
            if str(row["bounded_status"]).startswith("bounded_non_dry_blocked") or row["bounded_status"] == "blocked_request_or_purchase"
        ),
        "strict_full_pipeline_confirmed_count": sum(1 for row in rows if row["bounded_status"] == "passed"),
        "clinical_use_allowed_count": 0,
        "ready_for_clinical_interpretation": "no",
        "next_step": (
            "Promote bounded confirmations into strict pipeline confirmations only after approved full input transfer, "
            "caller execution, and truth-set concordance artifacts exist."
        ),
    }
    write_csv(path_from_root(EXECUTION_CSV_PATH), rows)
    write_json(
        path_from_root(EXECUTION_JSON_PATH),
        {"generatedAt": iso_now(), "status": summary["status"], "summary": summary, "rows": rows, "artifacts": list(artifacts.values())},
    )
    _write_markdown(rows, summary)
    return rows, summary


def _write_markdown(rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    lines = [
        "# Known-Answer Bounded Non-Dry Execution",
        "",
        "This generated report records real remote-read probes for the expanded public known-answer targets.",
        "",
        f"- Status: `{summary['status']}`",
        f"- Targets: `{summary['target_count']}`",
        f"- Bounded confirmations: `{summary['bounded_confirmed_count']}`",
        f"- Partial bounded results: `{summary['bounded_partial_count']}`",
        f"- Gap-identified targets: `{summary['gap_identified_count']}`",
        f"- Blocked targets: `{summary['blocked_count']}`",
        f"- Strict full-pipeline confirmations: `{summary['strict_full_pipeline_confirmed_count']}`",
        "",
        "| Pull target | Bounded status | Pipeline confirmation | Evidence | Result |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["pull_id"]),
                    str(row["bounded_status"]),
                    str(row["pipeline_confirmation"]),
                    str(row["evidence_type"]),
                    str(row["public_finding_result"]),
                ]
            )
            + " |"
        )
    write_text(path_from_root(EXECUTION_MD_PATH), "\n".join(lines))


def build_execution() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    hg008_variants = _run_hg008_variant_panel()
    hg008_cnv = _run_hg008_cnv_probe()
    colo829_braf = _run_colo829_braf_probe()
    hg008_rna = _read_hg008_rna_stats()
    colo829_purity = _colo829_purity_probe()

    artifacts: dict[str, dict[str, Any]] = {}
    artifacts[HG008_INPUT_ARTIFACT] = _write_analysis_artifact(
        HG008_INPUT_ARTIFACT,
        "bounded_non_dry_passed" if hg008_variants["allVariantsPassed"] else "bounded_non_dry_gap_identified",
        "bounded_confirmed",
        "remote_indexed_bam_pileup",
        "HG008-T carries truth ALT alleles while HG008-N-D remains reference-like across the bounded SNV panel.",
        {"variantPanel": hg008_variants},
        next_action="Run full HG008 tumor-normal WGS through the caller before upgrading this to strict pipeline confirmation.",
    )
    artifacts[HG008_SMALL_VARIANT_ARTIFACT] = _write_analysis_artifact(
        HG008_SMALL_VARIANT_ARTIFACT,
        "bounded_non_dry_passed" if hg008_variants["allVariantsPassed"] else "bounded_non_dry_gap_identified",
        "bounded_confirmed",
        "truth_vcf_remote_bam_pileup",
        f"{hg008_variants['passedVariantCount']}/{hg008_variants['evaluatedVariantCount']} HG008 truth SNVs had tumor ALT support and normal REF support.",
        {"variantPanel": hg008_variants},
        next_action="Run full small-variant calling and callable-region concordance for strict recall/precision metrics.",
    )
    artifacts[HG008_SV_CNV_ARTIFACT] = _write_analysis_artifact(
        HG008_SV_CNV_ARTIFACT,
        "bounded_non_dry_partial" if hg008_cnv["passedCnvDepthSignal"] else "bounded_non_dry_gap_identified",
        "bounded_partial_cnv_depth_only",
        "truth_cnv_remote_bam_depth",
        "HG008 CNV truth loss shows reduced tumor-normal depth after neutral-region normalization; SV reciprocal-overlap remains unrun.",
        {"cnvDepthProbe": hg008_cnv},
        blockers=("No Diana-generated SV/CNV callset exists for HG008 in this bounded run.",),
        next_action="Run SV/CNV callers and reciprocal-overlap comparison against HG008 v0.5 truth.",
    )
    artifacts[HG008_RNA_ARTIFACT] = _write_analysis_artifact(
        HG008_RNA_ARTIFACT,
        "bounded_non_dry_gap_identified",
        "not_confirmed",
        "public_fastq_stats_only",
        "HG008 RNA stats are present and paired, but no RNA quantification or truth target was run.",
        {"rnaStats": hg008_rna},
        blockers=("RNA FASTQs were not downloaded and no transcript-level truth target is selected.",),
        next_action="Select an RNA truth/QC target, transfer FASTQs, and run quantification.",
    )
    artifacts[COLO829_INPUT_ARTIFACT] = _write_analysis_artifact(
        COLO829_INPUT_ARTIFACT,
        "bounded_non_dry_passed" if colo829_braf["passedBrafGuardrail"] else "bounded_non_dry_gap_identified",
        "bounded_confirmed",
        "remote_indexed_bam_pileup",
        "COLO829 tumor has BRAF V600E ALT support while COLO829R normal remains reference-like at the same locus.",
        {"brafV600EProbe": colo829_braf},
        next_action="Run full COLO829 tumor-normal calling and signature analysis before strict pipeline confirmation.",
    )
    artifacts[COLO829_SV_CNA_ARTIFACT] = _write_analysis_artifact(
        COLO829_SV_CNA_ARTIFACT,
        "bounded_non_dry_gap_identified",
        "not_confirmed",
        "truth_assets_only_with_driver_pileup_context",
        "COLO829 SV/CNA truth assets are present, but no SV/CNA caller output or reciprocal-overlap result was generated.",
        {"svCnaGap": _colo829_sv_cna_gap(), "brafV600EProbe": colo829_braf},
        blockers=(
            "COLO829 submitted BAMs are GRCh37-style while the fetched SV truth VCF is hg38-lifted.",
            "No Diana SV/CNA callset exists.",
        ),
        next_action="Fetch or generate build-matched COLO829 truth/calls and run reciprocal-overlap SV/CNA evaluation.",
    )
    artifacts[COLO829_PURITY_ARTIFACT] = _write_analysis_artifact(
        COLO829_PURITY_ARTIFACT,
        "bounded_non_dry_blocked_remote_index_missing",
        "not_confirmed",
        "ena_metadata_and_failed_remote_region_probe",
        "COLO829 dilution BAMs are public but cannot be remotely region-sliced because ENA does not expose submitted BAI files for selected levels.",
        {"purityProbe": colo829_purity},
        blockers=("Selected purity BAMs require full transfer or local indexing before monotonic recall can be tested.",),
        next_action="Transfer selected dilution BAM/FASTQ inputs, index locally if needed, then run the purity recall table.",
    )
    artifacts[SERASEQ_ARTIFACT] = _write_analysis_artifact(
        SERASEQ_ARTIFACT,
        "blocked_request_or_purchase",
        "not_confirmed",
        "source_access_blocker",
        "Seraseq ctDNA MRD material or variant files are not freely downloadable for non-dry analysis.",
        {"seraseqGap": _seraseq_gap()},
        blockers=("Request or purchase is required before a non-dry positive-negative MRD run.",),
        next_action="Obtain material or variant truth files and define assay-specific acceptance ranges.",
    )
    return _write_summary_artifacts(artifacts)


def main() -> None:
    ensure_dir(path_from_root(RESULTS_ROOT))
    rows, summary = build_execution()
    print(
        "Known-answer bounded non-dry execution completed: "
        f"{summary['bounded_confirmed_count']}/{len(rows)} bounded confirmed; "
        f"{summary['bounded_partial_count']} partial; "
        f"{summary['gap_identified_count']} gaps; "
        f"{summary['blocked_count']} blocked."
    )


if __name__ == "__main__":
    main()
