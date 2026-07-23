from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .paths import path_from_root

TARGET_DISCOVERY_CANDIDATES = "manifests/target_discovery_candidates.csv"
TARGET_DISCOVERY_TEMPLATE = "manifests/target_discovery_inputs.template.csv"
TARGET_DISCOVERY_DEFAULT = "manifests/target_discovery_inputs.csv"
TARGET_DNA_EVIDENCE_DEFAULT = "manifests/target_dna_evidence.csv"
TARGET_RNA_EVIDENCE_DEFAULT = "results/target_discovery/rna_target_expression_summary.csv"
TARGET_DISCOVERY_RESULTS = "results/target_discovery"
ROSALIND_TARGET_RESULTS = "results/rosalind_targets"

TARGET_FAMILIES = {
    "adc_antigen",
    "bispecific_antigen",
    "immune_context",
    "ddr_transcription_cdk",
    "cell_cycle_resistance",
    "payload_context",
}
EVIDENCE_LAYERS = {
    "dna",
    "rna",
    "protein",
    "phospho_protein",
    "pathology",
    "clinical_context",
    "report",
}
DNA_QUESTIONS = {
    "callability",
    "coding_disruption",
    "focal_loss",
    "copy_gain",
    "amplification",
    "hla_loss",
    "loh",
    "pathway_bypass",
}

CANDIDATE_COLUMNS = [
    "target_id",
    "gene_symbol",
    "display_name",
    "target_family",
    "required_sample_layers",
    "primary_no_call_reason",
    "dna_questions",
    "orthogonal_followup",
    "caveat",
]

TARGET_INPUT_COLUMNS = [
    "evidence_id",
    "patient_id",
    "sample_id",
    "pair_id",
    "role",
    "assay",
    "evidence_layer",
    "data_type",
    "path",
    "index_path",
    "reference_id",
    "gene_symbol",
    "target_id",
    "source_name",
    "status",
    "notes",
    "caveat",
]

DNA_EVIDENCE_COLUMNS = [
    "target_id",
    "gene_symbol",
    "callability_status",
    "copy_number_status",
    "variant_effect",
    "hla_loss_status",
    "evidence_detail",
]

RNA_EVIDENCE_COLUMNS = [
    "target_id",
    "gene_symbol",
    "rna_status",
    "read_count",
    "evidence_detail",
]

CANDIDATE_BOARD_COLUMNS = [
    "target_id",
    "gene_symbol",
    "display_name",
    "target_family",
    "overall_status",
    "candidate_class",
    "dna_status",
    "rna_status",
    "protein_status",
    "sample_support_summary",
    "sample_blockers",
    "research_context_status",
    "recommended_followup",
    "clinical_boundary",
]

FOLLOWUP_BOUNDARY = "Research-use follow-up triage only; clinical decisions require reviewer signoff."
NO_RNA_PROTEIN = "no_call"


class DuplicateJsonObjectName(ValueError):
    """Raised when a JSON object repeats a key."""


class TargetDiscoveryError(ValueError):
    """Raised when target-discovery source artifacts violate packet contracts."""


def _reject_duplicate_json_object_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateJsonObjectName(key)
        value[key] = item
    return value


def _split_semicolon(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_csv(text: str) -> list[dict[str, str]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def read_csv_rows(relative_path: str) -> list[dict[str, str]]:
    path = path_from_root(relative_path)
    if not path.exists():
        return []
    return _parse_csv(path.read_text(encoding="utf-8"))


def read_json_no_duplicates(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_object_names)
    except DuplicateJsonObjectName as error:
        raise TargetDiscoveryError(f"{path} repeats JSON key {error}") from error


def target_input_rows() -> list[dict[str, str]]:
    return [
        {
            "evidence_id": "diana-wgs-dna",
            "patient_id": "DIANA",
            "sample_id": "DIANA-TUMOR-DNA",
            "pair_id": "DIANA-DNA-001",
            "role": "tumor",
            "assay": "WGS",
            "evidence_layer": "dna",
            "data_type": "SUMMARY",
            "path": "results/target_discovery/dna_target_locus_summary.csv",
            "index_path": "",
            "reference_id": "ucsc_hg38_analysis_set_full",
            "gene_symbol": "",
            "target_id": "",
            "source_name": "WGS first-pass DNA target summary",
            "status": "pending",
            "notes": "Replace with a generated DNA target summary after WGS/WES staging.",
            "caveat": "Template row only; DNA cannot prove RNA expression, surface protein, or drug response.",
        },
        {
            "evidence_id": "diana-rna-expression",
            "patient_id": "DIANA",
            "sample_id": "DIANA-TUMOR-RNA",
            "pair_id": "DIANA-RNA-001",
            "role": "rna_tumor",
            "assay": "RNA",
            "evidence_layer": "rna",
            "data_type": "SUMMARY",
            "path": "results/target_discovery/rna_target_expression_summary.csv",
            "index_path": "",
            "reference_id": "",
            "gene_symbol": "",
            "target_id": "",
            "source_name": "RNA target expression sidecar",
            "status": "optional",
            "notes": "Optional RNA evidence for expression and heterogeneity review.",
            "caveat": "Bulk or single-cell RNA remains expression support, not surface protein confirmation.",
        },
        {
            "evidence_id": "diana-target-protein",
            "patient_id": "DIANA",
            "sample_id": "DIANA-IHC",
            "pair_id": "DIANA-PROTEIN-001",
            "role": "tumor",
            "assay": "IHC",
            "evidence_layer": "protein",
            "data_type": "REPORT",
            "path": "results/target_discovery/protein_target_report.csv",
            "index_path": "",
            "reference_id": "",
            "gene_symbol": "",
            "target_id": "",
            "source_name": "Protein target report sidecar",
            "status": "optional",
            "notes": "Optional IHC, flow, CITE-seq, or spatial protein summary.",
            "caveat": "Protein reports must be reviewed in pathology and clinical context.",
        },
    ]


def candidate_rows() -> list[dict[str, str]]:
    adc_layers = "dna;rna;protein;pathology;clinical_context"
    return [
        _candidate("trop2", "TACSTD2", "TROP-2", "adc_antigen", adc_layers, "IHC;RNA-seq;scRNA-seq;spatial"),
        _candidate("her2", "ERBB2", "HER2", "adc_antigen", adc_layers, "IHC;RNA-seq;spatial"),
        _candidate("her3", "ERBB3", "HER3", "adc_antigen", adc_layers, "IHC;RNA-seq"),
        _candidate("liv1", "SLC39A6", "LIV-1", "adc_antigen", adc_layers, "IHC;RNA-seq"),
        _candidate("nectin4", "NECTIN4", "Nectin-4", "adc_antigen", adc_layers, "IHC;RNA-seq;scRNA-seq"),
        _candidate("b7h3", "CD276", "B7-H3", "adc_antigen", adc_layers, "IHC;RNA-seq;spatial"),
        _candidate("folr1", "FOLR1", "Folate receptor alpha", "adc_antigen", adc_layers, "IHC;RNA-seq"),
        _candidate("egfr", "EGFR", "EGFR", "adc_antigen", adc_layers, "IHC;RNA-seq;phospho-protein"),
        _candidate("tissue_factor", "F3", "Tissue factor", "adc_antigen", adc_layers, "IHC;RNA-seq"),
        _candidate("hla_a", "HLA-A", "HLA-A", "immune_context", "dna;rna;protein", "HLA typing;RNA-seq"),
        _candidate("hla_b", "HLA-B", "HLA-B", "immune_context", "dna;rna;protein", "HLA typing;RNA-seq"),
        _candidate("hla_c", "HLA-C", "HLA-C", "immune_context", "dna;rna;protein", "HLA typing;RNA-seq"),
        _candidate("b2m", "B2M", "B2M", "bispecific_antigen", "dna;rna;protein", "IHC;RNA-seq"),
        _candidate("pdl1", "CD274", "PD-L1", "immune_context", "dna;rna;protein;pathology", "IHC;RNA-seq"),
        _candidate("pd1", "PDCD1", "PD-1", "immune_context", "rna;protein;pathology", "flow;scRNA-seq"),
        _candidate("4_1bb", "TNFRSF9", "4-1BB", "immune_context", "rna;protein;pathology", "flow;scRNA-seq"),
        _candidate("cd3e", "CD3E", "CD3E", "bispecific_antigen", "rna;protein;pathology", "flow;scRNA-seq"),
        _candidate("cdk12", "CDK12", "CDK12", "ddr_transcription_cdk", "dna;rna;clinical_context", "RNA-seq;HRR review"),
        _candidate("cdk13", "CDK13", "CDK13", "ddr_transcription_cdk", "dna;rna;clinical_context", "RNA-seq;HRR review"),
        _candidate("ccnk", "CCNK", "Cyclin K", "ddr_transcription_cdk", "dna;rna;clinical_context", "RNA-seq"),
        _candidate("rb1", "RB1", "RB1", "cell_cycle_resistance", "dna;protein;clinical_context", "IHC;phospho-Rb"),
        _candidate("ccne1", "CCNE1", "Cyclin E1", "cell_cycle_resistance", "dna;rna;protein", "RNA-seq;cyclin-E protein"),
        _candidate("cdk4", "CDK4", "CDK4", "cell_cycle_resistance", "dna;rna;protein", "RNA-seq;phospho-Rb"),
        _candidate("cdk6", "CDK6", "CDK6", "cell_cycle_resistance", "dna;rna;protein", "RNA-seq;phospho-Rb"),
        _candidate("ccnd1", "CCND1", "Cyclin D1", "cell_cycle_resistance", "dna;rna;protein", "RNA-seq;cyclin-D1 protein"),
        _candidate("cdkn2a", "CDKN2A", "CDKN2A", "cell_cycle_resistance", "dna;rna;protein", "RNA-seq;p16 IHC"),
        _candidate("cdkn2b", "CDKN2B", "CDKN2B", "cell_cycle_resistance", "dna;rna", "RNA-seq"),
        _candidate("pik3ca", "PIK3CA", "PI3K alpha", "cell_cycle_resistance", "dna;clinical_context", "PI3K pathway review"),
        _candidate("akt1", "AKT1", "AKT1", "cell_cycle_resistance", "dna;clinical_context", "PI3K pathway review"),
        _candidate("pten", "PTEN", "PTEN", "cell_cycle_resistance", "dna;protein;clinical_context", "IHC;PI3K pathway review"),
        _candidate("fgfr1", "FGFR1", "FGFR1", "cell_cycle_resistance", "dna;rna;protein", "RNA-seq;phospho-protein"),
        _candidate("fgfr2", "FGFR2", "FGFR2", "cell_cycle_resistance", "dna;rna;protein", "RNA-seq;phospho-protein"),
        _candidate("esr1", "ESR1", "ESR1", "cell_cycle_resistance", "dna;rna;protein;clinical_context", "ER IHC;RNA-seq"),
        _candidate("top1", "TOP1", "TOP1", "payload_context", "dna;rna;protein;clinical_context", "RNA-seq;protein"),
        _candidate("slfn11", "SLFN11", "SLFN11", "payload_context", "dna;rna;protein", "RNA-seq;IHC"),
        _candidate("abcb1", "ABCB1", "ABCB1", "payload_context", "dna;rna;protein", "RNA-seq"),
        _candidate("ugt1a1", "UGT1A1", "UGT1A1", "payload_context", "dna;clinical_context", "germline pharmacogenomics"),
    ]


def _candidate(
    target_id: str,
    gene_symbol: str,
    display_name: str,
    target_family: str,
    required_sample_layers: str,
    orthogonal_followup: str,
) -> dict[str, str]:
    if target_family in {"adc_antigen", "bispecific_antigen"}:
        primary_no_call_reason = "Surface protein abundance and malignant-cell heterogeneity are not confirmed."
        dna_questions = "callability;coding_disruption;focal_loss;copy_gain;amplification"
    elif target_family == "immune_context":
        primary_no_call_reason = "Immune-cell expression and protein context are not confirmed."
        dna_questions = "callability;coding_disruption;focal_loss;hla_loss"
    elif target_family == "ddr_transcription_cdk":
        primary_no_call_reason = "CDK12/13 dependency and DDR transcriptional context are not validated."
        dna_questions = "callability;coding_disruption;focal_loss;copy_gain;amplification;loh"
    elif target_family == "cell_cycle_resistance":
        primary_no_call_reason = "CDK-pathway dependence and resistance context are not clinically locked."
        dna_questions = "callability;coding_disruption;focal_loss;copy_gain;amplification;pathway_bypass"
    else:
        primary_no_call_reason = "Payload-specific sensitivity context is not validated."
        dna_questions = "callability;coding_disruption;focal_loss;copy_gain;pathway_bypass"

    return {
        "target_id": target_id,
        "gene_symbol": gene_symbol,
        "display_name": display_name,
        "target_family": target_family,
        "required_sample_layers": required_sample_layers,
        "primary_no_call_reason": primary_no_call_reason,
        "dna_questions": dna_questions,
        "orthogonal_followup": orthogonal_followup,
        "caveat": "WES/WGS is a first-pass support or blocker lane only.",
    }


def validate_candidate_rows(rows: Sequence[Mapping[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return [f"{TARGET_DISCOVERY_CANDIDATES} has no rows."]
    missing_columns = set(CANDIDATE_COLUMNS) - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"{TARGET_DISCOVERY_CANDIDATES} is missing required column {column}.")

    ids: set[str] = set()
    for row in rows:
        target_id = row.get("target_id", "")
        if not target_id:
            errors.append(f"{TARGET_DISCOVERY_CANDIDATES} has a row with blank target_id.")
        if target_id in ids:
            errors.append(f"{TARGET_DISCOVERY_CANDIDATES} has duplicate target_id {target_id}.")
        ids.add(target_id)
        if row.get("target_family") not in TARGET_FAMILIES:
            errors.append(f"{TARGET_DISCOVERY_CANDIDATES} row {target_id} has unsupported target_family.")
        for layer in _split_semicolon(row.get("required_sample_layers", "")):
            if layer not in EVIDENCE_LAYERS:
                errors.append(f"{TARGET_DISCOVERY_CANDIDATES} row {target_id} has unsupported evidence layer {layer}.")
        for question in _split_semicolon(row.get("dna_questions", "")):
            if question not in DNA_QUESTIONS:
                errors.append(f"{TARGET_DISCOVERY_CANDIDATES} row {target_id} has unsupported DNA question {question}.")
        for column in CANDIDATE_COLUMNS:
            if not row.get(column, "").strip():
                errors.append(f"{TARGET_DISCOVERY_CANDIDATES} row {target_id or '(blank)'} is missing {column}.")
    return errors


def validate_input_rows(rows: Sequence[Mapping[str, str]], *, require_files: bool = True) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not rows:
        errors.append("Target discovery inputs must include at least one evidence row.")
        return errors, warnings, _input_summary(rows)

    missing_columns = set(TARGET_INPUT_COLUMNS) - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"Target discovery inputs are missing required column {column}.")

    evidence_ids: set[str] = set()
    dna_reference_ids = {row.get("reference_id", "") for row in rows if row.get("evidence_layer") == "dna" and row.get("reference_id")}
    for row in rows:
        evidence_id = row.get("evidence_id", "")
        if not evidence_id:
            errors.append("Target discovery inputs have a row with blank evidence_id.")
        if evidence_id in evidence_ids:
            errors.append(f"Target discovery inputs have duplicate evidence_id {evidence_id}.")
        evidence_ids.add(evidence_id)
        layer = row.get("evidence_layer", "")
        if layer not in EVIDENCE_LAYERS:
            errors.append(f"Evidence row {evidence_id or '(blank)'} has unsupported evidence_layer {layer}.")
        if row.get("assay") in {"WGS", "WES"} and layer != "dna":
            warnings.append(f"Evidence row {evidence_id} uses DNA assay {row.get('assay')} outside the dna layer.")
        if layer == "dna" and not row.get("reference_id"):
            errors.append(f"DNA evidence row {evidence_id or '(blank)'} is missing reference_id.")

        for column in ("path", "index_path"):
            value = row.get(column, "")
            if value and require_files and not resolve_existing_file(value).exists():
                errors.append(f"Evidence row {evidence_id or '(blank)'} {column} path does not exist: {value}")

    if len(dna_reference_ids) > 1:
        warnings.append(f"DNA evidence rows contain multiple reference_id values: {', '.join(sorted(dna_reference_ids))}.")

    return errors, warnings, _input_summary(rows)


def _input_summary(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    layer_counts = {layer: sum(1 for row in rows if row.get("evidence_layer") == layer) for layer in sorted(EVIDENCE_LAYERS)}
    return {
        "rowCount": len(rows),
        "dnaRowCount": layer_counts["dna"],
        "rnaRows": layer_counts["rna"],
        "proteinRows": layer_counts["protein"],
        "phosphoProteinRows": layer_counts["phospho_protein"],
        "reportRows": layer_counts["report"],
        "layerCounts": layer_counts,
        "referenceIds": sorted({row.get("reference_id", "") for row in rows if row.get("reference_id")}),
    }


def check_files() -> bool:
    return os.environ.get("TARGET_DISCOVERY_CHECK_FILES", "1") != "0"


def selected_inputs_path() -> str:
    return os.environ.get("TARGET_DISCOVERY_INPUTS", TARGET_DISCOVERY_DEFAULT)


def selected_dna_evidence_path() -> str:
    return os.environ.get("TARGET_DISCOVERY_DNA_EVIDENCE", TARGET_DNA_EVIDENCE_DEFAULT)


def selected_rna_evidence_path() -> str:
    return os.environ.get("TARGET_DISCOVERY_RNA_EVIDENCE", TARGET_RNA_EVIDENCE_DEFAULT)


def selected_sample_or_cohort() -> str:
    return _slug(os.environ.get("ROSALIND_TARGET_SAMPLE", "diana_target_discovery")) or "diana_target_discovery"


def selected_run_id() -> str:
    raw = os.environ.get("ROSALIND_TARGET_RUN_ID", "initial")
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-") or "initial"


def resolve_existing_file(relative_or_absolute: str) -> Path:
    path = Path(relative_or_absolute)
    return path if path.is_absolute() else path_from_root(path)


def build_dna_board(
    candidates: Sequence[Mapping[str, str]],
    evidence_rows: Sequence[Mapping[str, str]],
    rna_evidence_rows: Sequence[Mapping[str, str]] = (),
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    evidence_by_id = {row.get("target_id", ""): row for row in evidence_rows if row.get("target_id")}
    evidence_by_gene = {row.get("gene_symbol", ""): row for row in evidence_rows if row.get("gene_symbol")}
    rna_by_id = {row.get("target_id", ""): row for row in rna_evidence_rows if row.get("target_id")}
    rna_by_gene = {row.get("gene_symbol", ""): row for row in rna_evidence_rows if row.get("gene_symbol")}

    locus_rows: list[dict[str, str]] = []
    board_rows: list[dict[str, str]] = []
    for candidate in candidates:
        target_id = candidate["target_id"]
        gene_symbol = candidate["gene_symbol"]
        evidence = evidence_by_id.get(target_id) or evidence_by_gene.get(gene_symbol) or {}
        rna_evidence = rna_by_id.get(target_id) or rna_by_gene.get(gene_symbol) or {}
        required_layers = set(_split_semicolon(candidate.get("required_sample_layers", "")))
        rna_status = classify_rna_evidence(rna_evidence) if "rna" in required_layers else NO_RNA_PROTEIN
        classification = classify_target(candidate, evidence, rna_status=rna_status)
        locus_rows.append(
            {
                "target_id": target_id,
                "gene_symbol": gene_symbol,
                "callability_status": evidence.get("callability_status", "missing"),
                "copy_number_status": evidence.get("copy_number_status", "no_call"),
                "variant_effect": evidence.get("variant_effect", "no_call"),
                "hla_loss_status": evidence.get("hla_loss_status", "no_call"),
                "dna_status": classification["dna_status"],
                "candidate_class": classification["candidate_class"],
                "detail": evidence.get("evidence_detail", candidate["primary_no_call_reason"]),
            }
        )
        board_rows.append(
            {
                "target_id": target_id,
                "gene_symbol": gene_symbol,
                "display_name": candidate["display_name"],
                "target_family": candidate["target_family"],
                "overall_status": classification["overall_status"],
                "candidate_class": classification["candidate_class"],
                "dna_status": classification["dna_status"],
                "rna_status": rna_status,
                "protein_status": NO_RNA_PROTEIN,
                "sample_support_summary": classification["sample_support_summary"],
                "sample_blockers": classification["sample_blockers"],
                "research_context_status": "no_call",
                "recommended_followup": candidate["orthogonal_followup"],
                "clinical_boundary": FOLLOWUP_BOUNDARY,
            }
        )
    return locus_rows, board_rows


def classify_rna_evidence(evidence: Mapping[str, str]) -> str:
    if not evidence:
        return NO_RNA_PROTEIN
    status = _slug(evidence.get("rna_status", ""))
    if status in {"detected", "expressed", "present", "partial_evidence", "supported"}:
        return "partial_evidence"
    if status in {"not_detected", "not_supported"}:
        return "not_supported"
    return NO_RNA_PROTEIN


def classify_target(
    candidate: Mapping[str, str],
    evidence: Mapping[str, str],
    *,
    rna_status: str = NO_RNA_PROTEIN,
) -> dict[str, str]:
    if not evidence:
        return {
            "overall_status": "blocked",
            "candidate_class": "blocked",
            "dna_status": "no_call",
            "sample_support_summary": "No DNA target evidence row was available.",
            "sample_blockers": candidate["primary_no_call_reason"],
        }

    family = candidate["target_family"]
    gene = candidate["gene_symbol"]
    copy_number = _slug(evidence.get("copy_number_status", ""))
    variant = _slug(evidence.get("variant_effect", ""))
    hla_loss = _slug(evidence.get("hla_loss_status", ""))
    callable_status = _slug(evidence.get("callability_status", ""))

    target_loss = copy_number in {"focal_loss", "deep_deletion", "homozygous_deletion", "loss"} or variant in {
        "disruptive",
        "frameshift",
        "frame_shift",
        "nonsense",
        "splice",
        "loss_of_function",
        "target_loss",
    }
    copy_gain = copy_number in {"copy_gain", "gain", "amplification", "high_amplification"}
    is_callable = callable_status in {"callable", "ready", "passed", "pass", "covered"}

    if hla_loss in {"loss", "hla_loss", "loh"} or target_loss:
        return {
            "overall_status": "not_supported",
            "candidate_class": "not_supported_candidate",
            "dna_status": "not_supported",
            "sample_support_summary": f"{gene} has DNA-level loss or disruption evidence.",
            "sample_blockers": "Reviewed DNA argues against this candidate until orthogonal review resolves the loss call.",
        }

    if family == "ddr_transcription_cdk" and (copy_gain or is_callable):
        return {
            "overall_status": "partial_evidence",
            "candidate_class": "ddr_transcriptional_cdk_followup",
            "dna_status": "partial_evidence",
            "sample_support_summary": f"{gene} has first-pass DNA evidence for DDR/transcriptional-CDK follow-up.",
            "sample_blockers": "CDK12/13 dependency and drug context remain no_call without expression and pathway review.",
        }

    if family == "cell_cycle_resistance":
        if gene == "RB1":
            summary = "RB1 DNA status is cell-cycle resistance context for CDK4/6 review."
        elif gene == "CCNE1":
            summary = "CCNE1 DNA status is cyclin-E/CDK2-bypass context for CDK4/6 review."
        else:
            summary = f"{gene} DNA status is cell-cycle pathway context."
        return {
            "overall_status": "partial_evidence",
            "candidate_class": "cell_cycle_resistance_context",
            "dna_status": "partial_evidence" if is_callable or copy_gain else "no_call",
            "sample_support_summary": summary,
            "sample_blockers": "Clinical exposure, RB1/cyclin-E-axis review, and orthogonal pathway evidence remain no_call.",
        }

    rna_supported = rna_status == "partial_evidence"

    if copy_gain:
        return {
            "overall_status": "partial_evidence",
            "candidate_class": (
                "expression_supported_protein_unconfirmed"
                if rna_supported
                else "copy_gain_expression_unconfirmed"
            ),
            "dna_status": "partial_evidence",
            "sample_support_summary": (
                f"{gene} has copy gain or amplification evidence and RNA support."
                if rna_supported
                else f"{gene} has copy gain or amplification evidence in the DNA lane."
            ),
            "sample_blockers": (
                "Surface protein abundance and malignant-cell heterogeneity are not confirmed."
                if rna_supported
                else "RNA expression and surface protein abundance remain no_call."
            ),
        }

    if is_callable:
        if rna_supported and family in {"adc_antigen", "bispecific_antigen", "immune_context", "payload_context"}:
            return {
                "overall_status": "partial_evidence",
                "candidate_class": "expression_supported_protein_unconfirmed",
                "dna_status": "partial_evidence",
                "sample_support_summary": (
                    f"{gene} has first-pass DNA callability and unnormalized RNA locus support."
                ),
                "sample_blockers": "Surface protein abundance and malignant-cell heterogeneity are not confirmed.",
            }

        sample_support_summary = (
            f"{gene} has first-pass locus callability; CNV and disruptive-variant evidence are no_call."
            if copy_number == "no_call" and variant == "no_call"
            else f"{gene} is callable with no first-pass disruptive DNA event."
        )
        return {
            "overall_status": "partial_evidence",
            "candidate_class": "genomically_supported_expression_unconfirmed",
            "dna_status": "partial_evidence",
            "sample_support_summary": sample_support_summary,
            "sample_blockers": candidate["primary_no_call_reason"],
        }

    return {
        "overall_status": "blocked",
        "candidate_class": "blocked",
        "dna_status": "no_call",
        "sample_support_summary": f"{gene} DNA callability is missing or unresolved.",
        "sample_blockers": candidate["primary_no_call_reason"],
    }


def validate_candidate_board(rows: Sequence[Mapping[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return ["candidate_target_board.csv has no rows."]
    missing_columns = set(CANDIDATE_BOARD_COLUMNS) - set(rows[0])
    for column in sorted(missing_columns):
        errors.append(f"candidate_target_board.csv is missing required column {column}.")

    ids: set[str] = set()
    for row in rows:
        target_id = row.get("target_id", "")
        if not target_id:
            errors.append("candidate_target_board.csv has a blank target_id.")
        if target_id in ids:
            errors.append(f"candidate_target_board.csv has duplicate target_id {target_id}.")
        ids.add(target_id)
        for column in CANDIDATE_BOARD_COLUMNS:
            value = row.get(column, "")
            if not value.strip():
                errors.append(f"candidate_target_board.csv row {target_id or '(blank)'} is missing {column}.")
            if "\n" in value or "\r" in value or "|" in value:
                errors.append(f"candidate_target_board.csv row {target_id or '(blank)'} has unsafe {column}.")
            if value != value.strip():
                errors.append(f"candidate_target_board.csv row {target_id or '(blank)'} has padded {column}.")
    return errors


def source_index(paths: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative_path in sorted(set(paths)):
        path = path_from_root(relative_path)
        if not path.exists():
            continue
        if path.suffix == ".json":
            read_json_no_duplicates(path)
        rows.append(
            {
                "path": relative_path,
                "bytes": path.stat().st_size,
                "sha256": _sha256_path(path),
            }
        )
    return rows


def markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _column in columns) + " |",
    ]
    for row in rows:
        values = [str(row.get(column, "")).replace("|", "\\|").replace("\n", " ") for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
