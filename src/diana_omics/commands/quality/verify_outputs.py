from __future__ import annotations

import sys
from typing import Any

from ...paths import path_from_root
from ...utils import parse_csv, read_json, read_text

REQUIRED_FILES = [
    "data/processed/catalog/cbioportal_tcga_brca_summary.json",
    "data/processed/catalog/gdc_tcga_brca_open_summary.json",
    "data/processed/catalog/xena_tcga_brca_clinical_summary.json",
    "manifests/file_manifest.json",
    "manifests/hrd_reference_panel.csv",
    "manifests/raw_representative_panel.csv",
    "manifests/raw_representative_panel_summary.json",
    "manifests/raw_samplesheet.csv",
    "manifests/raw_smoke_samplesheet.csv",
    "manifests/alignment_smoke_samplesheet.csv",
    "manifests/human_reference_smoke_references.csv",
    "manifests/human_reference_smoke_samplesheet.csv",
    "manifests/full_reference_smoke_references.csv",
    "manifests/full_reference_smoke_samplesheet.csv",
    "manifests/production_somatic_smoke_samplesheet.csv",
    "manifests/full_wes_benchmark_samplesheet.csv",
    "manifests/phase3_wgs_smoke_samplesheet.csv",
    "manifests/diana_raw_inputs.template.csv",
    "manifests/orthogonal_public_examples.csv",
    "manifests/orthogonal_validation_candidates.csv",
    "manifests/reference_panel_validation.json",
    "docs/operations/diana-raw-inputs.md",
    "docs/data/reference-panel-label-rules.md",
    "results/hrd_event_table.csv",
    "results/allele_state_table.csv",
    "results/scar_signature_table.csv",
    "results/hrd_confusion_matrix.csv",
    "results/hrd_failure_modes.csv",
    "results/hrd_predictions.csv",
    "results/rna_subtype_context.csv",
    "results/rna_module_context.csv",
    "data/processed/lehmann/tcga_tnbc_lehmann_s1_calls.csv",
    "data/processed/lehmann/lehmann_signature_genes.csv",
    "results/lehmann_tnbc_tcga_panel.csv",
    "results/evidence_tables/lehmann_tnbc_tcga_panel.csv",
    "results/lehmann_signature_tcga_validation.csv",
    "results/evidence_tables/lehmann_signature_tcga_validation.csv",
    "results/lehmann_signature_tcga_validation_summary.json",
    "results/lehmann_signature_tcga_validation.md",
    "results/lehmann_tnbc_feasibility_summary.json",
    "results/lehmann_tnbc_feasibility.md",
    "results/methods.md",
    "results/reviewer_packet.md",
    "results/diana_readiness_gate.md",
    "results/raw_smoke/README.md",
    "results/raw_smoke/fastq_smoke_summary.csv",
    "results/raw_smoke/fastq_smoke_summary.json",
    "results/raw_smoke/samplesheet_summary.json",
    "results/raw_smoke/tooling_audit.json",
    "results/raw_smoke/tooling_audit.md",
    "results/alignment_smoke/README.md",
    "results/alignment_smoke/reference_summary.json",
    "results/alignment_smoke/tool_versions.json",
    "results/alignment_smoke/alignment_smoke_summary.csv",
    "results/alignment_smoke/alignment_smoke_summary.json",
    "results/alignment_smoke/bam_validation_summary.csv",
    "results/alignment_smoke/bam_validation_summary.json",
    "results/human_reference_smoke/README.md",
    "results/human_reference_smoke/reference_assets_summary.json",
    "results/human_reference_smoke/tool_versions.json",
    "results/human_reference_smoke/human_reference_alignment_summary.csv",
    "results/human_reference_smoke/human_reference_alignment_summary.json",
    "results/human_reference_smoke/bam_validation_summary.csv",
    "results/human_reference_smoke/bam_validation_summary.json",
    "results/human_reference_smoke/reference_comparison_summary.csv",
    "results/human_reference_smoke/reference_comparison_summary.json",
    "results/full_reference_smoke/README.md",
    "results/full_reference_smoke/reference_assets_summary.json",
    "results/full_reference_smoke/tool_versions.json",
    "results/full_reference_smoke/full_reference_alignment_summary.csv",
    "results/full_reference_smoke/full_reference_alignment_summary.json",
    "results/full_reference_smoke/bam_validation_summary.csv",
    "results/full_reference_smoke/bam_validation_summary.json",
    "results/full_reference_smoke/caller_smoke_summary.csv",
    "results/full_reference_smoke/caller_smoke_summary.json",
    "results/production_somatic_smoke/README.md",
    "results/production_somatic_smoke/asset_summary.json",
    "results/production_somatic_smoke/tool_versions.json",
    "results/production_somatic_smoke/fastq_summary.csv",
    "results/production_somatic_smoke/fastq_summary.json",
    "results/production_somatic_smoke/bam_validation_summary.csv",
    "results/production_somatic_smoke/bam_validation_summary.json",
    "results/production_somatic_smoke/mutect2_smoke_summary.csv",
    "results/production_somatic_smoke/mutect2_smoke_summary.json",
    "results/production_somatic_smoke/production_somatic_summary.csv",
    "results/production_somatic_smoke/production_somatic_summary.json",
    "results/full_wes_benchmark/README.md",
    "results/full_wes_benchmark/asset_summary.json",
    "results/full_wes_benchmark/tool_versions.json",
    "results/full_wes_benchmark/full_wes_fastq_validation.csv",
    "results/full_wes_benchmark/full_wes_fastq_validation.json",
    "results/full_wes_benchmark/full_wes_bam_validation.csv",
    "results/full_wes_benchmark/full_wes_bam_validation.json",
    "results/full_wes_benchmark/truth_overlap_benchmark_summary.csv",
    "results/full_wes_benchmark/truth_overlap_benchmark_summary.json",
    "results/full_wes_benchmark/full_wes_benchmark_summary.csv",
    "results/full_wes_benchmark/full_wes_benchmark_summary.json",
    "results/phase3_wgs_smoke/README.md",
    "results/phase3_wgs_smoke/asset_summary.json",
    "results/phase3_wgs_smoke/tool_versions.json",
    "results/phase3_wgs_smoke/fastq_summary.csv",
    "results/phase3_wgs_smoke/fastq_summary.json",
    "results/phase3_wgs_smoke/bam_validation_summary.csv",
    "results/phase3_wgs_smoke/bam_validation_summary.json",
    "results/phase3_wgs_smoke/mutect2_wgs_summary.csv",
    "results/phase3_wgs_smoke/mutect2_wgs_summary.json",
    "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
    "results/phase3_wgs_smoke/coverage_cnv_summary.csv",
    "results/phase3_wgs_smoke/coverage_cnv_summary.json",
    "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
    "results/phase3_wgs_smoke/signature_assignment_summary.csv",
    "results/phase3_wgs_smoke/signature_assignment_summary.json",
    "results/phase3_wgs_smoke/sv_evidence_candidates.csv",
    "results/phase3_wgs_smoke/sv_evidence_summary.csv",
    "results/phase3_wgs_smoke/sv_evidence_summary.json",
    "results/phase3_wgs_smoke/hrd_tool_readiness_summary.csv",
    "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json",
    "results/phase3_wgs_smoke/covered_truth_variants.csv",
    "results/phase3_wgs_smoke/phase3_wgs_summary.csv",
    "results/phase3_wgs_smoke/phase3_wgs_summary.json",
    "results/orthogonal_validation/public_examples_summary.csv",
    "results/orthogonal_validation/public_examples_summary.json",
    "results/diana_raw_intake/README.md",
    "results/diana_raw_intake/input_contract.json",
    "results/diana_raw_intake/intake_readiness_summary.csv",
    "results/diana_raw_intake/intake_readiness_summary.json",
    "results/diana_raw_intake/input_validation_summary.csv",
    "results/diana_raw_intake/input_validation_summary.json",
]


def require_columns(errors: list[str], relative_path: str, rows: list[dict[str, str]], columns: list[str]) -> None:
    actual = set(rows[0].keys()) if rows else set()
    for column in columns:
        if column not in actual:
            errors.append(f"{relative_path} is missing required column {column}.")


def require_rows(errors: list[str], relative_path: str, minimum: int) -> list[dict[str, str]]:
    path = path_from_root(relative_path)
    if not path.exists():
        errors.append(f"Missing {relative_path}")
        return []
    rows = parse_csv(read_text(path))
    if len(rows) < minimum:
        errors.append(f"{relative_path} has {len(rows)} rows; expected at least {minimum}.")
    return rows


def read_json_if_exists(errors: list[str], relative_path: str) -> dict[str, Any]:
    path = path_from_root(relative_path)
    if not path.exists():
        errors.append(f"Missing {relative_path}")
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        errors.append(f"{relative_path} must contain a JSON object.")
        return {}
    return data


def require_status(errors: list[str], relative_path: str, expected: str = "passed", key: str = "status") -> dict[str, Any]:
    data = read_json_if_exists(errors, relative_path)
    if data and data.get(key) != expected:
        errors.append(f"{relative_path} {key} is {data.get(key)!r}; expected {expected!r}.")
    return data


def require_all_rows_pass(errors: list[str], relative_path: str, rows: list[dict[str, str]]) -> None:
    for row in rows:
        if row.get("status") != "passed":
            errors.append(f"{relative_path} contains non-passing row: {row}")


# Acceptance artifacts a full-source Phase 3 WGS run produces on its own (without the
# WES ladder). verify:phase3-outputs gates exactly these so a WGS-only run still has a
# fatal output verifier; the full verify:outputs reuses the same checks via
# verify_phase3_wgs_outputs.
PHASE3_WGS_REQUIRED_FILES = [
    "manifests/phase3_wgs_smoke_samplesheet.csv",
    "results/phase3_wgs_smoke/README.md",
    "results/phase3_wgs_smoke/asset_summary.json",
    "results/phase3_wgs_smoke/tool_versions.json",
    "results/phase3_wgs_smoke/fastq_summary.csv",
    "results/phase3_wgs_smoke/fastq_summary.json",
    "results/phase3_wgs_smoke/bam_validation_summary.csv",
    "results/phase3_wgs_smoke/bam_validation_summary.json",
    "results/phase3_wgs_smoke/mutect2_wgs_summary.csv",
    "results/phase3_wgs_smoke/mutect2_wgs_summary.json",
    "results/phase3_wgs_smoke/coverage_cnv_bins.csv",
    "results/phase3_wgs_smoke/coverage_cnv_summary.csv",
    "results/phase3_wgs_smoke/coverage_cnv_summary.json",
    "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
    "results/phase3_wgs_smoke/signature_assignment_summary.csv",
    "results/phase3_wgs_smoke/signature_assignment_summary.json",
    "results/phase3_wgs_smoke/sv_evidence_candidates.csv",
    "results/phase3_wgs_smoke/sv_evidence_summary.csv",
    "results/phase3_wgs_smoke/sv_evidence_summary.json",
    "results/phase3_wgs_smoke/hrd_tool_readiness_summary.csv",
    "results/phase3_wgs_smoke/hrd_tool_readiness_summary.json",
    "results/phase3_wgs_smoke/covered_truth_variants.csv",
    "results/phase3_wgs_smoke/phase3_wgs_summary.csv",
    "results/phase3_wgs_smoke/phase3_wgs_summary.json",
]


def verify_phase3_wgs_outputs(errors: list[str]) -> None:
    """Fatal contract checks for the Phase 3 WGS acceptance artifacts.

    Shared by the full verify:outputs gate and the WGS-only verify:phase3-outputs
    gate so a full-source WGS run that skips the WES ladder still fails hard on a
    malformed output set (validate:phase3-wgs already fails on bad internal status;
    this adds the cross-artifact contract that verify:outputs otherwise owns).
    """
    for relative_path in PHASE3_WGS_REQUIRED_FILES:
        if not path_from_root(relative_path).exists():
            errors.append(f"Missing {relative_path}")

    phase3_bam_rows = require_rows(errors, "results/phase3_wgs_smoke/bam_validation_summary.csv", 1)
    require_columns(
        errors,
        "results/phase3_wgs_smoke/bam_validation_summary.csv",
        phase3_bam_rows,
        ["status", "output_bam", "output_bai", "quickcheck", "sort_order", "read_group_present", "caveat"],
    )
    require_all_rows_pass(errors, "results/phase3_wgs_smoke/bam_validation_summary.csv", phase3_bam_rows)

    phase3_samplesheet = require_rows(errors, "manifests/phase3_wgs_smoke_samplesheet.csv", 2)
    require_columns(
        errors,
        "manifests/phase3_wgs_smoke_samplesheet.csv",
        phase3_samplesheet,
        [
            "pair_id",
            "sample",
            "role",
            "assay",
            "run_accession",
            "source_read_pairs",
            "read_pairs_per_end",
            "fastq_1",
            "fastq_2",
            "reference_id",
            "reference_dict_path",
            "truth_snv_vcf_path",
            "truth_indel_vcf_path",
            "gatk_jar_path",
            "mutect2_panel_of_normals_path",
            "output_bam",
            "output_bai",
            "cnv_strategy",
            "sv_strategy",
            "signature_strategy",
            "caveat",
        ],
    )
    if {row.get("role") for row in phase3_samplesheet} != {"tumor", "normal"}:
        errors.append("Phase 3 WGS samplesheet must include tumor and normal rows.")
    for row in phase3_samplesheet:
        if row.get("assay") != "WGS":
            errors.append(f"Phase 3 samplesheet must use WGS assay rows, not {row.get('assay')}.")
        if row.get("reference_id") != "ucsc_hg38_analysis_set_full":
            errors.append(f"Phase 3 samplesheet must use ucsc_hg38_analysis_set_full, not {row.get('reference_id')}.")
        if row.get("read_pairs_per_end") != row.get("source_read_pairs"):
            errors.append(f"Phase 3 WGS validation must use full source read pairs for {row.get('run_accession')}.")
        if not row.get("fastq_1", "").endswith(".full.fastq.gz") or not row.get("fastq_2", "").endswith(".full.fastq.gz"):
            errors.append(f"Phase 3 WGS validation FASTQs must be complete compressed source files for {row.get('run_accession')}.")
        if "/full/bam/" not in row.get("output_bam", ""):
            errors.append(f"Phase 3 WGS full validation BAM must be isolated under a full output directory for {row.get('run_accession')}.")
        caveat = row.get("caveat", "")
        if "Full-source validation is the acceptance gate" not in caveat:
            errors.append(f"Phase 3 caveat must preserve the full-source acceptance gate for {row.get('run_accession')}.")

    phase3_summary_rows = require_rows(errors, "results/phase3_wgs_smoke/phase3_wgs_summary.csv", 1)
    require_columns(
        errors,
        "results/phase3_wgs_smoke/phase3_wgs_summary.csv",
        phase3_summary_rows,
        [
            "status",
            "phase",
            "read_pairs_per_end",
            "read_pairs_mode",
            "read_request",
            "bam_validation_status",
            "mutect2_status",
            "coverage_cnv_status",
            "sbs96_matrix_status",
            "sv_evidence_status",
            "phase3_complete",
            "ready_for_phase4_when_diana_raw_arrives",
            "boundary",
        ],
    )
    if phase3_summary_rows:
        row = phase3_summary_rows[0]
        if row.get("status") != "passed" or row.get("phase") != "3" or row.get("phase3_complete") != "yes":
            errors.append("Phase 3 WGS summary CSV did not pass the completed Phase 3 gate.")
        if row.get("ready_for_phase4_when_diana_raw_arrives") != "yes":
            errors.append("Phase 3 WGS summary must mark the project ready for Phase 4 setup once Diana raw files arrive.")
        if row.get("read_pairs_mode") != "full":
            errors.append("Phase 3 WGS summary CSV must come from a full-source run.")
        if row.get("read_request") != "full":
            errors.append("Phase 3 WGS summary CSV must record read_request=full.")
        source_pairs = [int(sample.get("source_read_pairs") or "0") for sample in phase3_samplesheet]
        if source_pairs and int(row.get("read_pairs_per_end") or "0") < min(source_pairs):
            errors.append("Phase 3 WGS full validation must use the full source read-pair count.")
        if "Full-depth Diana interpretation" not in row.get("boundary", ""):
            errors.append("Phase 3 WGS summary must preserve the full-depth Diana interpretation boundary.")

    phase3_summary = read_json_if_exists(errors, "results/phase3_wgs_smoke/phase3_wgs_summary.json")
    if phase3_summary.get("phase3Complete") is not True or phase3_summary.get("readyForPhase4WhenDianaRawArrives") is not True:
        errors.append("Phase 3 WGS JSON summary must mark Phase 3 complete and ready for Phase 4 setup.")
    if phase3_summary.get("readPairsMode") != "full" or phase3_summary.get("fullSourceFastqs") is not True:
        errors.append("Phase 3 WGS JSON summary must be from full-source FASTQs, not a bounded smoke run.")
    if int(phase3_summary.get("coverageCnvBins") or 0) <= 0:
        errors.append("Phase 3 WGS summary must include non-empty coverage CNV bins.")

    sbs96_rows = require_rows(errors, "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv", 96)
    require_columns(
        errors,
        "results/phase3_wgs_smoke/wgs_sbs96_matrix.csv",
        sbs96_rows,
        ["sample", "mutation_type", "trinucleotide", "count", "source_records", "source_vcf_policy"],
    )
    if len(sbs96_rows) != 96:
        errors.append(f"Phase 3 SBS96 matrix must have exactly 96 rows, found {len(sbs96_rows)}.")

    tool_rows = require_rows(errors, "results/phase3_wgs_smoke/hrd_tool_readiness_summary.csv", 3)
    require_columns(
        errors,
        "results/phase3_wgs_smoke/hrd_tool_readiness_summary.csv",
        tool_rows,
        ["tool", "evidence_input", "real_output_status", "interpretability_status", "caveat"],
    )
    for tool in ["SigProfilerAssignment", "scarHRD", "CHORD"]:
        if not any(row.get("tool") == tool for row in tool_rows):
            errors.append(f"Phase 3 HRD tool readiness summary is missing {tool}.")


def verify_phase3_outputs() -> None:
    errors: list[str] = []
    verify_phase3_wgs_outputs(errors)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Phase 3 WGS output verification passed.")


def main() -> None:
    errors: list[str] = []
    warnings: list[str] = []

    for relative_path in REQUIRED_FILES:
        if not path_from_root(relative_path).exists():
            errors.append(f"Missing {relative_path}")

    panel = require_rows(errors, "manifests/hrd_reference_panel.csv", 16)
    require_columns(
        errors,
        "manifests/hrd_reference_panel.csv",
        panel,
        ["sample_id", "panel_category", "expected_hrd_label", "label_source", "second_hit_proxy", "caveat"],
    )
    panel_categories = {row.get("panel_category") for row in panel}
    for category in ["positive_control", "ambiguous_control", "negative_control"]:
        if category not in panel_categories:
            errors.append(f"Reference panel is missing category {category}.")

    table_contracts = [
        ("results/hrd_event_table.csv", len(panel) or 1, ["sample_id", "source", "tool", "gene", "event_class", "confidence", "caveat"]),
        ("results/allele_state_table.csv", len(panel) or 1, ["sample_id", "source", "tool", "gene", "second_hit_status", "caveat"]),
        (
            "results/scar_signature_table.csv",
            len(panel) or 1,
            [
                "sample_id",
                "source",
                "tool",
                "sbs3_signature_status",
                "structural_variant_signature_status",
                "predicted_hrd_class",
                "caveat",
            ],
        ),
        ("results/hrd_predictions.csv", len(panel) or 1, ["sample_id", "expected_hrd_label", "predicted_hrd_class", "predicted_bucket"]),
        ("results/hrd_confusion_matrix.csv", 1, ["expected_bucket", "predicted_bucket", "count"]),
        ("results/rna_subtype_context.csv", len(panel) or 1, ["sample_id", "source", "tool", "inferred_context", "confidence", "caveat"]),
        (
            "results/rna_module_context.csv",
            len(panel) or 1,
            ["sample_id", "source", "tool", "basal_marker_z", "immune_inflammation_marker_z", "caveat"],
        ),
        (
            "data/processed/lehmann/tcga_tnbc_lehmann_s1_calls.csv",
            180,
            ["sample_id", "patient_id", "lehmann_tnbctype", "lehmann_refined_tnbctype", "lehmann_im_corr", "lehmann_lar_corr"],
        ),
        (
            "data/processed/lehmann/lehmann_signature_genes.csv",
            7000,
            ["signature", "gene", "entrez", "coefficient"],
        ),
        (
            "results/lehmann_tnbc_tcga_panel.csv",
            len(panel) or 1,
            ["sample_id", "patient_id", "lehmann_tnbctype", "lehmann_refined_tnbctype", "evidence_status", "next_action"],
        ),
        (
            "results/lehmann_signature_tcga_validation.csv",
            180,
            [
                "sample_id",
                "official_refined_tnbctype",
                "local_signature_refined_tnbctype",
                "matches_official_refined_tnbctype",
                "assessable_from_cbioportal_signature_expression",
                "score_bl1",
                "score_lar",
            ],
        ),
    ]
    for path, minimum, columns in table_contracts:
        rows = require_rows(errors, path, minimum)
        require_columns(errors, path, rows, columns)

    lehmann_summary = read_json_if_exists(errors, "results/lehmann_tnbc_feasibility_summary.json")
    if lehmann_summary.get("officialTcgaTnbcCount") != 180:
        errors.append("Lehmann feasibility summary must preserve the 180-sample official TCGA TNBC table count.")
    if lehmann_summary.get("panelWithOfficialLehmannCount") != 8:
        errors.append("Lehmann feasibility summary must record the current 8-sample official panel overlap.")
    if lehmann_summary.get("currentRnaMarkerGeneCount") != 19:
        errors.append("Lehmann feasibility summary must preserve the current 19-gene marker-lane boundary.")
    classifier = lehmann_summary.get("classifierValidation", {})
    if not isinstance(classifier, dict):
        errors.append("Lehmann feasibility summary must include classifierValidation from the non-dry expression run.")
        classifier = {}
    if classifier.get("runMode") != "non_dry_expression_classifier_validation":
        errors.append("Lehmann classifier validation must record runMode=non_dry_expression_classifier_validation.")
    if int(classifier.get("assessableSamples") or 0) < 179:
        errors.append("Lehmann classifier validation must score at least 179 TCGA TNBC controls.")
    if int(classifier.get("expressionRecordsFetched") or 0) < 700000:
        errors.append("Lehmann classifier validation must fetch the full signature-gene expression payload.")
    if int(classifier.get("localRefinedMatches") or 0) < 100:
        errors.append("Lehmann classifier validation concordance is too low for a completed non-dry run.")

    raw_panel = require_rows(errors, "manifests/raw_representative_panel.csv", 8)
    require_columns(
        errors,
        "manifests/raw_representative_panel.csv",
        raw_panel,
        ["pair_id", "role", "run", "assay", "fastq_1_url", "fastq_2_url", "consent", "caveat"],
    )
    roles_by_pair: dict[str, set[str]] = {}
    for row in raw_panel:
        roles_by_pair.setdefault(row.get("pair_id", ""), set()).add(row.get("role", ""))
        if row.get("consent") != "public":
            errors.append(f"Raw representative run is not public: {row.get('run')}")
        if not row.get("fastq_1_url", "").startswith("https://") or not row.get("fastq_2_url", "").startswith("https://"):
            errors.append(f"Raw representative run is missing HTTPS FASTQ URLs: {row.get('run')}")
    for pair_id, roles in roles_by_pair.items():
        if "tumor" not in roles or "normal" not in roles:
            errors.append(f"Raw representative pair {pair_id} does not have both tumor and normal roles.")

    for path in [
        "results/alignment_smoke/bam_validation_summary.csv",
        "results/human_reference_smoke/bam_validation_summary.csv",
        "results/full_reference_smoke/bam_validation_summary.csv",
        "results/production_somatic_smoke/bam_validation_summary.csv",
        # results/phase3_wgs_smoke/bam_validation_summary.csv is checked by verify_phase3_wgs_outputs.
    ]:
        rows = require_rows(errors, path, 1)
        require_columns(
            errors, path, rows, ["status", "output_bam", "output_bai", "quickcheck", "sort_order", "read_group_present", "caveat"]
        )
        require_all_rows_pass(errors, path, rows)

    full_wes_bam_rows = require_rows(errors, "results/full_wes_benchmark/full_wes_bam_validation.csv", 2)
    require_columns(
        errors,
        "results/full_wes_benchmark/full_wes_bam_validation.csv",
        full_wes_bam_rows,
        [
            "status",
            "dedup_bam",
            "dedup_bai",
            "quickcheck",
            "sort_order",
            "read_group_present",
            "mapped_alignments",
            "brca_interval_alignments",
            "caveat",
        ],
    )
    require_all_rows_pass(errors, "results/full_wes_benchmark/full_wes_bam_validation.csv", full_wes_bam_rows)

    for json_path, expected in [
        ("results/raw_smoke/fastq_smoke_summary.json", "passed"),
        ("results/alignment_smoke/alignment_smoke_summary.json", "passed"),
        ("results/human_reference_smoke/human_reference_alignment_summary.json", "passed"),
        ("results/human_reference_smoke/reference_comparison_summary.json", "passed"),
        ("results/full_reference_smoke/full_reference_alignment_summary.json", "passed"),
        ("results/full_reference_smoke/caller_smoke_summary.json", "passed"),
        ("results/production_somatic_smoke/fastq_summary.json", "passed"),
        ("results/production_somatic_smoke/production_somatic_summary.json", "passed"),
        ("results/production_somatic_smoke/mutect2_smoke_summary.json", "passed"),
        ("results/full_wes_benchmark/full_wes_fastq_validation.json", "passed"),
        ("results/full_wes_benchmark/full_wes_bam_validation.json", "passed"),
        ("results/full_wes_benchmark/truth_overlap_benchmark_summary.json", "passed"),
        ("results/full_wes_benchmark/full_wes_benchmark_summary.json", "passed"),
        ("results/phase3_wgs_smoke/fastq_summary.json", "passed"),
        ("results/phase3_wgs_smoke/bam_validation_summary.json", "passed"),
        ("results/phase3_wgs_smoke/mutect2_wgs_summary.json", "passed"),
        ("results/phase3_wgs_smoke/coverage_cnv_summary.json", "passed"),
        ("results/phase3_wgs_smoke/signature_assignment_summary.json", "passed"),
        ("results/phase3_wgs_smoke/sv_evidence_summary.json", "passed"),
        ("results/phase3_wgs_smoke/hrd_tool_readiness_summary.json", "passed"),
        ("results/phase3_wgs_smoke/phase3_wgs_summary.json", "passed"),
        ("results/orthogonal_validation/public_examples_summary.json", "passed"),
    ]:
        require_status(errors, json_path, expected)

    raw_audit = read_json_if_exists(errors, "results/raw_smoke/tooling_audit.json")
    for key in ["fullWesBenchmarkReady", "phase3WgsToolReady", "phase3WgsSmokeReady"]:
        if raw_audit.get(key) is not True:
            errors.append(f"Raw tooling audit says {key} is not ready.")

    full_wes_samplesheet = require_rows(errors, "manifests/full_wes_benchmark_samplesheet.csv", 2)
    require_columns(
        errors,
        "manifests/full_wes_benchmark_samplesheet.csv",
        full_wes_samplesheet,
        [
            "pair_id",
            "sample",
            "role",
            "run_accession",
            "fastq_1",
            "fastq_2",
            "reference_id",
            "mutect2_panel_of_normals_path",
            "common_biallelic_resource_path",
            "dedup_bam",
            "dedup_bai",
            "caveat",
        ],
    )
    if {row.get("role") for row in full_wes_samplesheet} != {"tumor", "normal"}:
        errors.append("Full WES benchmark samplesheet must include tumor and normal rows.")
    for row in full_wes_samplesheet:
        if row.get("reference_id") != "ucsc_hg38_analysis_set_full":
            errors.append(f"Full WES benchmark samplesheet must use ucsc_hg38_analysis_set_full, not {row.get('reference_id')}.")
        if "full SEQC2/HCC1395 WES FASTQs" not in row.get("caveat", ""):
            errors.append(f"Full WES caveat must preserve full-WES boundary for {row.get('run_accession')}.")

    verify_phase3_wgs_outputs(errors)

    orthogonal_examples = require_rows(errors, "manifests/orthogonal_public_examples.csv", 7)
    require_columns(
        errors,
        "manifests/orthogonal_public_examples.csv",
        orthogonal_examples,
        [
            "example_id",
            "priority",
            "status",
            "public_access",
            "modality",
            "source_scope",
            "raw_inputs",
            "truth_or_expected_answer",
            "runnable_command",
            "full_data_command",
            "completion_artifact",
            "pass_gate",
            "documentation",
        ],
    )
    example_ids = {row.get("example_id") for row in orthogonal_examples}
    for example_id in ["seqc2_hcc1395_full_wes", "seqc2_hcc1395_phase3_wgs", "giab_hg008_wgs", "colo829_wgs"]:
        if example_id not in example_ids:
            errors.append(f"Orthogonal public examples manifest is missing {example_id}.")
    for row in orthogonal_examples:
        if row.get("status") == "implemented" and not row.get("completion_artifact", "").startswith("results/"):
            errors.append(f"Implemented orthogonal example {row.get('example_id')} must point to a results completion artifact.")
        if row.get("status") == "implemented" and not row.get("full_data_command"):
            errors.append(f"Implemented orthogonal example {row.get('example_id')} must include a full_data_command.")
        if row.get("documentation") and not path_from_root(row["documentation"]).exists():
            errors.append(f"Orthogonal example {row.get('example_id')} references missing documentation {row.get('documentation')}.")

    orthogonal_summary = read_json_if_exists(errors, "results/orthogonal_validation/public_examples_summary.json")
    if int(orthogonal_summary.get("implementedExamples") or 0) < 2:
        errors.append("Orthogonal public examples summary must include at least two implemented public examples.")
    if int(orthogonal_summary.get("plannedExamples") or 0) < 4:
        errors.append("Orthogonal public examples summary must keep the HG008/COLO829 known-answer examples visible.")

    diana_template = require_rows(errors, "manifests/diana_raw_inputs.template.csv", 3)
    require_columns(
        errors,
        "manifests/diana_raw_inputs.template.csv",
        diana_template,
        [
            "patient_id",
            "pair_id",
            "sample_id",
            "role",
            "assay",
            "data_type",
            "fastq_1",
            "fastq_2",
            "bam",
            "bai",
            "cram",
            "crai",
            "reference_id",
            "reference_path",
            "reference_fai_path",
            "reference_dict_path",
            "caveat",
        ],
    )
    if not any(row.get("role") == "tumor" and row.get("assay") in {"WGS", "WES"} for row in diana_template):
        errors.append("Diana raw template must include a tumor DNA row.")
    if not any(row.get("role") == "normal" and row.get("assay") in {"WGS", "WES"} for row in diana_template):
        errors.append("Diana raw template must include a matched-normal DNA row.")

    diana_contract = read_json_if_exists(errors, "results/diana_raw_intake/input_contract.json")
    required_columns = diana_contract.get("requiredColumns", [])
    if not isinstance(required_columns, list) or "fastq_1" not in required_columns or "reference_dict_path" not in required_columns:
        errors.append("Diana raw input contract must record required path/reference columns.")
    if "verify:diana-raw" not in str(diana_contract.get("validationCommand", "")):
        errors.append("Diana raw input contract must record the verify:diana-raw command.")
    if "stage:diana-raw" not in str(diana_contract.get("recomputeCommand", "")):
        errors.append("Diana raw input contract must record the stage:diana-raw command.")

    diana_readiness = require_status(errors, "results/diana_raw_intake/intake_readiness_summary.json", "template_ready")
    if diana_readiness.get("readyForDianaRawData") is not True:
        errors.append("Diana raw intake readiness must say the project is ready for Diana raw data.")
    if diana_readiness.get("readyToInterpret") is not False:
        errors.append("Diana raw intake readiness must preserve the not-ready-to-interpret boundary.")

    diana_validation = read_json_if_exists(errors, "results/diana_raw_intake/input_validation_summary.json")
    if diana_validation.get("status") not in {"waiting_for_diana_raw_data", "passed"}:
        errors.append(f"Diana raw input validation status must be waiting or passed, not {diana_validation.get('status')!r}.")

    readiness = (
        read_text(path_from_root("results/diana_readiness_gate.md")) if path_from_root("results/diana_readiness_gate.md").exists() else ""
    )
    if "ready for Phase 4 setup once Diana raw files arrive" not in readiness:
        errors.append("Diana readiness gate must mark the project ready for Phase 4 setup once Diana raw files arrive.")
    if "not ready for clinical interpretation" not in readiness:
        errors.append("Diana readiness gate must preserve the not-ready-for-clinical-interpretation boundary.")

    if warnings:
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    print("Output verification passed.")


if __name__ == "__main__":
    main()
