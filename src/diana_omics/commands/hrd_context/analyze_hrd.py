from __future__ import annotations

from typing import Any, Mapping, Optional

from ...domain import cna_state, confusion_bucket, gene_symbol, mutation_class, prediction_class, scar_proxy_class
from ...paths import path_from_root
from ...utils import (
    ensure_dir,
    group_by,
    iso_now,
    parse_csv,
    pivot_clinical,
    read_json,
    read_text,
    round_value,
    to_number,
    write_csv,
    write_json,
)


def expected_bucket_for_label(expected_label: str) -> str:
    if "negative" in expected_label:
        return "expected_negative"
    if "ambiguous" in expected_label:
        return "expected_ambiguous"
    if "hrd" in expected_label or "positive" in expected_label:
        return "expected_hrd_like"
    return "expected_unknown"


def main() -> None:
    ensure_dir(path_from_root("results/evidence_tables"))

    panel = parse_csv(read_text(path_from_root("manifests/hrd_reference_panel.csv")))
    mutations = read_json(path_from_root("data/raw/cbioportal/mutations_hrr.json"))
    cna = read_json(path_from_root("data/raw/cbioportal/cna_hrr_gistic.json"))
    clinical = pivot_clinical(read_json(path_from_root("data/raw/cbioportal/clinical_sample_selected.json")), "sampleId")

    mutations_by_sample = group_by(mutations, lambda mutation: mutation["sampleId"])
    cna_by_sample_gene = {f"{row['sampleId']}:{gene_symbol(row)}": row["value"] for row in cna}
    clinical_by_sample = {row["sampleId"]: row for row in clinical}

    event_rows: list[dict[str, Any]] = []
    allele_rows: list[dict[str, Any]] = []
    scar_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, str]] = []

    for panel_row in panel:
        sample_id = panel_row["sample_id"]
        sample_mutations = mutations_by_sample.get(sample_id, [])
        clinical_row = clinical_by_sample.get(sample_id, {})
        fga = to_number(clinical_row.get("FRACTION_GENOME_ALTERED"))
        aneuploidy = to_number(clinical_row.get("ANEUPLOIDY_SCORE"))
        mutation_count = to_number(clinical_row.get("MUTATION_COUNT"))
        tmb = to_number(clinical_row.get("TMB_NONSYNONYMOUS"))
        ranked_mutations = sorted(
            sample_mutations,
            key=lambda mutation: (
                2 if mutation_class(mutation) == "likely_damaging" else 1 if mutation_class(mutation) == "missense_or_vus" else 0
            ),
            reverse=True,
        )
        best_mutation: Optional[Mapping[str, Any]] = ranked_mutations[0] if ranked_mutations else None
        best_cna = cna_by_sample_gene.get(f"{sample_id}:{gene_symbol(best_mutation)}") if best_mutation else None
        prediction = prediction_class(panel_row, best_mutation, best_cna, fga, aneuploidy)

        if not sample_mutations:
            event_rows.append(
                {
                    "sample_id": sample_id,
                    "source": "cBioPortal TCGA-BRCA PanCancer Atlas",
                    "tool": "cBioPortal processed WES mutation profile",
                    "tool_version": "study import 2026-06-05",
                    "gene": "",
                    "alteration": "none_in_fetched_hrr_gene_set",
                    "mutation_type": "",
                    "event_class": "none",
                    "vaf_proxy": "",
                    "confidence": "no_event_in_selected_hrr_gene_set",
                    "caveat": "Absence is limited to fetched HRR genes and processed mutation calls.",
                }
            )

        for mutation in sample_mutations:
            alt = mutation.get("tumorAltCount")
            ref = mutation.get("tumorRefCount")
            vaf = alt / (alt + ref) if isinstance(alt, (int, float)) and isinstance(ref, (int, float)) and alt + ref > 0 else None
            classification = mutation_class(mutation)
            event_rows.append(
                {
                    "sample_id": sample_id,
                    "source": "cBioPortal TCGA-BRCA PanCancer Atlas",
                    "tool": "cBioPortal processed WES mutation profile",
                    "tool_version": "study import 2026-06-05",
                    "gene": gene_symbol(mutation),
                    "alteration": mutation.get("proteinChange") or mutation.get("mutationType", ""),
                    "mutation_type": mutation.get("mutationType", ""),
                    "event_class": classification,
                    "vaf_proxy": round_value(vaf),
                    "reference_build": mutation.get("ncbiBuild", "GRCh37"),
                    "confidence": "causal_event_supported" if classification == "likely_damaging" else "variant_requires_review",
                    "caveat": "Processed WES mutation record; pathogenicity is rule-based, not manual clinical curation.",
                }
            )

        allele_mutation_rows = sample_mutations or [None]
        for mutation in allele_mutation_rows:
            gene = gene_symbol(mutation) if mutation else "BRCA1/BRCA2"
            cna_value = cna_by_sample_gene.get(f"{sample_id}:{gene}") if mutation else None
            classification = mutation_class(mutation) if mutation else "none"
            allele_rows.append(
                {
                    "sample_id": sample_id,
                    "source": "cBioPortal TCGA-BRCA PanCancer Atlas",
                    "tool": "GISTIC discrete CNA plus processed WES mutation profile",
                    "tool_version": "study import 2026-06-05",
                    "gene": gene,
                    "causal_event_class": classification,
                    "gistic_value": cna_value if cna_value is not None else "",
                    "copy_number_state": cna_state(cna_value),
                    "second_hit_status": "copy_loss_proxy_supports_second_hit"
                    if mutation and classification == "likely_damaging" and cna_value is not None and cna_value <= -1
                    else "second_hit_not_proven"
                    if mutation
                    else "no_causal_event_to_assess",
                    "confidence": "proxy_support" if mutation and cna_value is not None and cna_value <= -1 else "incomplete",
                    "caveat": "GISTIC is not allele-specific purity/ploidy; LOH and biallelic status require FACETS/ASCAT/PURPLE-style evidence.",
                }
            )

        scar_proxy = scar_proxy_class(fga, aneuploidy)
        scar_rows.append(
            {
                "sample_id": sample_id,
                "source": "cBioPortal TCGA-BRCA PanCancer Atlas sample clinical fields",
                "tool": "processed proxy summary",
                "tool_version": "study import 2026-06-05",
                "fraction_genome_altered": round_value(fga),
                "aneuploidy_score": aneuploidy if aneuploidy is not None else "",
                "mutation_count": mutation_count if mutation_count is not None else "",
                "tmb_nonsynonymous": round_value(tmb),
                "scar_proxy_class": scar_proxy,
                "sbs3_signature_status": "not_assessable_from_phase1_processed_data",
                "structural_variant_signature_status": "not_assessable_from_phase1_processed_data",
                "hrd_classifier_status": "not_run_without_WGS_or_required_feature_matrix",
                "predicted_hrd_class": prediction,
                "confidence": "high_for_processed_public_candidate"
                if "strong" in prediction
                else "moderate_for_processed_public_candidate"
                if "suggestive" in prediction
                else "limited",
                "caveat": "FGA/aneuploidy are copy-number scar proxies, not scarHRD/CHORD/HRDetect/SBS3 outputs.",
            }
        )

        failure_rows.append(
            {
                "sample_id": sample_id,
                "failure_mode": "no_wgs_signature_inputs",
                "severity": "expected_phase1_limitation",
                "detail": "SBS3, rearrangement signatures, CHORD, and HRDetect-style outputs are not assessable from this processed cBioPortal phase-1 data alone.",
            }
        )
        failure_rows.append(
            {
                "sample_id": sample_id,
                "failure_mode": "no_allele_specific_purity_ploidy",
                "severity": "expected_phase1_limitation",
                "detail": "GISTIC copy loss is only a second-hit proxy; biallelic status needs allele-specific copy number and purity/ploidy.",
            }
        )
        if best_mutation and not (best_cna is not None and best_cna <= -1):
            failure_rows.append(
                {
                    "sample_id": sample_id,
                    "failure_mode": "second_hit_not_proven",
                    "severity": "sample_specific_limitation",
                    "detail": f"{gene_symbol(best_mutation)} event lacks GISTIC copy-loss proxy in this phase-1 evidence table.",
                }
            )

        expected_label = panel_row["expected_hrd_label"]
        prediction_rows.append(
            {
                "sample_id": sample_id,
                "expected_hrd_label": expected_label,
                "predicted_hrd_class": prediction,
                "expected_bucket": expected_bucket_for_label(expected_label),
                "predicted_bucket": confusion_bucket(prediction),
            }
        )

    matrix: dict[str, int] = {}
    for row in prediction_rows:
        key = f"{row['expected_bucket']}|{row['predicted_bucket']}"
        matrix[key] = matrix.get(key, 0) + 1
    matrix_rows = [
        {"expected_bucket": key.split("|")[0], "predicted_bucket": key.split("|")[1], "count": count} for key, count in matrix.items()
    ]

    write_csv(path_from_root("results/hrd_event_table.csv"), event_rows)
    write_csv(path_from_root("results/allele_state_table.csv"), allele_rows)
    write_csv(path_from_root("results/scar_signature_table.csv"), scar_rows)
    write_csv(path_from_root("results/hrd_confusion_matrix.csv"), matrix_rows)
    write_csv(path_from_root("results/hrd_failure_modes.csv"), failure_rows)
    write_csv(path_from_root("results/hrd_predictions.csv"), prediction_rows)
    write_csv(path_from_root("results/evidence_tables/hrd_event_table.csv"), event_rows)
    write_csv(path_from_root("results/evidence_tables/allele_state_table.csv"), allele_rows)
    write_csv(path_from_root("results/evidence_tables/scar_signature_table.csv"), scar_rows)
    write_csv(path_from_root("results/evidence_tables/hrd_failure_modes.csv"), failure_rows)
    write_json(
        path_from_root("results/hrd_analysis_summary.json"),
        {
            "generatedAt": iso_now(),
            "panelSampleCount": len(panel),
            "eventRowCount": len(event_rows),
            "alleleStateRowCount": len(allele_rows),
            "scarSignatureRowCount": len(scar_rows),
            "failureModeRowCount": len(failure_rows),
            "confusionMatrix": matrix_rows,
            "boundary": "Phase-1 HRD classes are processed public-data candidates. WGS signatures, allele-specific LOH, CHORD, HRDetect, and companion diagnostics are not run.",
        },
    )
    print(f"Built HRD evidence tables for {len(panel)} panel samples.")


if __name__ == "__main__":
    main()
