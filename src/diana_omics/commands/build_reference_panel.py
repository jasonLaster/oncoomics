from __future__ import annotations

from typing import Any, Mapping

from ..domain import BRCA_GENES, cna_state, gene_symbol, mutation_class, score_mutation
from ..paths import path_from_root
from ..utils import ensure_dir, group_by, iso_now, pivot_clinical, read_json, to_number, write_csv, write_json, write_text


def row_score(row: Mapping[str, Any]) -> float:
    if row["panel_category"] == "positive_control":
        return 1000 + float(row["fraction_genome_altered"]) * 100 + float(row["best_event_score"])
    if row["panel_category"] == "mechanistic_control":
        return 800 + float(row["fraction_genome_altered"]) * 100 + float(row["best_event_score"])
    if row["panel_category"] == "ambiguous_control":
        return 500 + float(row["best_event_score"]) + float(row["fraction_genome_altered"])
    if row["panel_category"] == "negative_control":
        return 300 - float(row["fraction_genome_altered"]) * 100
    return 0


def main() -> None:
    ensure_dir(path_from_root("manifests"))
    ensure_dir(path_from_root("docs"))

    sample_ids_by_list = read_json(path_from_root("data/raw/cbioportal/sample_ids_by_list.json"))
    mutations = read_json(path_from_root("data/raw/cbioportal/mutations_hrr.json"))
    cna = read_json(path_from_root("data/raw/cbioportal/cna_hrr_gistic.json"))
    sample_clinical = pivot_clinical(read_json(path_from_root("data/raw/cbioportal/clinical_sample_selected.json")), "sampleId")
    patient_clinical = pivot_clinical(read_json(path_from_root("data/raw/cbioportal/clinical_patient_selected.json")), "patientId")

    clinical_by_sample = {row["sampleId"]: row for row in sample_clinical}
    clinical_by_patient = {row["patientId"]: row for row in patient_clinical}
    mutations_by_sample = group_by(mutations, lambda mutation: mutation["sampleId"])
    cna_by_sample_gene = {f"{row['sampleId']}:{gene_symbol(row)}": row["value"] for row in cna}

    candidates = []
    for sample_id in sample_ids_by_list["brca_tcga_pan_can_atlas_2018_3way_complete"]:
        patient_id = sample_id[:12]
        sample_row = clinical_by_sample.get(sample_id, {})
        patient_row = clinical_by_patient.get(patient_id, {})
        sample_mutations = mutations_by_sample.get(sample_id, [])
        ranked_mutations = sorted(sample_mutations, key=score_mutation, reverse=True)
        best_mutation = ranked_mutations[0] if ranked_mutations else None
        primary_gene = gene_symbol(best_mutation) if best_mutation else ""
        primary_cna = cna_by_sample_gene.get(f"{sample_id}:{primary_gene}") if primary_gene else None
        brca1_cna = cna_by_sample_gene.get(f"{sample_id}:BRCA1")
        brca2_cna = cna_by_sample_gene.get(f"{sample_id}:BRCA2")
        mutation_classes = [mutation_class(mutation) for mutation in sample_mutations]
        damaging_brca = any(
            gene_symbol(mutation) in BRCA_GENES and mutation_class(mutation) == "likely_damaging" for mutation in sample_mutations
        )
        damaging_other_hrr = any(
            gene_symbol(mutation) not in BRCA_GENES and mutation_class(mutation) == "likely_damaging" for mutation in sample_mutations
        )
        has_any_hrr_mutation = bool(sample_mutations)
        fga = to_number(sample_row.get("FRACTION_GENOME_ALTERED")) or 0
        aneuploidy = to_number(sample_row.get("ANEUPLOIDY_SCORE"))
        mutation_count = to_number(sample_row.get("MUTATION_COUNT"))
        tmb = to_number(sample_row.get("TMB_NONSYNONYMOUS"))
        second_hit_proxy = (
            "copy_loss_proxy_present"
            if primary_cna is not None and primary_cna <= -1
            else "copy_loss_proxy_absent"
            if primary_gene
            else "no_causal_event"
        )

        panel_category = "background"
        expected_label = "not_selected"
        label_strength = "not_selected"
        caveat = "Not selected for the frozen phase-1 panel."
        if damaging_brca and primary_cna is not None and primary_cna <= -1 and fga >= 0.3:
            panel_category = "positive_control"
            expected_label = "expected_hrd_like"
            label_strength = "processed_public_positive_candidate"
            caveat = "Damaging BRCA1/2 event plus GISTIC copy-loss proxy and high fraction genome altered; not a WGS signature truth label."
        elif damaging_other_hrr and primary_cna is not None and primary_cna <= -1 and fga >= 0.25:
            panel_category = "mechanistic_control"
            expected_label = "expected_hrd_like_mechanistic"
            label_strength = "processed_public_mechanistic_candidate"
            caveat = "Damaging non-BRCA HRR event plus copy-loss proxy and elevated fraction genome altered; mechanism is less direct than BRCA1/2."
        elif has_any_hrr_mutation:
            panel_category = "ambiguous_control"
            expected_label = "expected_ambiguous"
            label_strength = "event_without_complete_support" if "likely_damaging" in mutation_classes else "vus_or_missense_only"
            caveat = "HRR alteration exists but phase-1 processed data does not prove functional HRD."
        elif not has_any_hrr_mutation and (brca1_cna or 0) == 0 and (brca2_cna or 0) == 0 and fga <= 0.15 and (mutation_count or 0) <= 80:
            panel_category = "negative_control"
            expected_label = "expected_hrd_negative"
            label_strength = "processed_public_negative_candidate"
            caveat = "No fetched HRR mutation, neutral BRCA1/2 GISTIC calls, low fraction genome altered, and modest mutation count in processed public data."

        candidates.append(
            {
                "sample_id": sample_id,
                "patient_id": patient_id,
                "panel_category": panel_category,
                "expected_hrd_label": expected_label,
                "label_strength": label_strength,
                "label_source": "cBioPortal TCGA-BRCA PanCancer Atlas processed mutation/CNA/sample clinical data",
                "primary_event_gene": primary_gene,
                "primary_event": f"{primary_gene} {best_mutation.get('proteinChange') or best_mutation.get('mutationType')}"
                if best_mutation
                else "none",
                "primary_event_class": mutation_class(best_mutation) if best_mutation else "none",
                "copy_number_context": cna_state(primary_cna)
                if primary_gene
                else f"BRCA1={cna_state(brca1_cna)}; BRCA2={cna_state(brca2_cna)}",
                "second_hit_proxy": second_hit_proxy,
                "fraction_genome_altered": fga,
                "aneuploidy_score": aneuploidy,
                "mutation_count": mutation_count,
                "tmb_nonsynonymous": tmb,
                "cbioportal_subtype": patient_row.get("SUBTYPE", ""),
                "caveat": caveat,
                "best_event_score": score_mutation(best_mutation) if best_mutation else 0,
            }
        )

    selected = (
        sorted([row for row in candidates if row["panel_category"] == "positive_control"], key=row_score, reverse=True)[:8]
        + sorted([row for row in candidates if row["panel_category"] == "mechanistic_control"], key=row_score, reverse=True)[:4]
        + sorted([row for row in candidates if row["panel_category"] == "ambiguous_control"], key=row_score, reverse=True)[:8]
        + sorted([row for row in candidates if row["panel_category"] == "negative_control"], key=row_score, reverse=True)[:8]
    )
    selected = sorted(selected, key=lambda row: (row["panel_category"], row["sample_id"]))
    public_rows = [{key: value for key, value in row.items() if key != "best_event_score"} for row in selected]

    write_csv(path_from_root("manifests/hrd_reference_panel.csv"), public_rows)
    write_json(
        path_from_root("manifests/reference_panel_validation.json"),
        {
            "generatedAt": iso_now(),
            "selectedSampleCount": len(selected),
            "availableCandidatesByCategory": {
                key: len(rows) for key, rows in group_by(candidates, lambda row: row["panel_category"]).items()
            },
            "selectedByCategory": {key: len(rows) for key, rows in group_by(selected, lambda row: row["panel_category"]).items()},
            "validationRules": [
                "Positive controls require damaging BRCA1/2 event plus GISTIC copy-loss proxy and high fraction genome altered.",
                "Negative controls require no fetched HRR mutation, neutral BRCA1/2 GISTIC calls, low fraction genome altered, and modest mutation count.",
                "Ambiguous controls are explicitly allowed and should not be forced into binary HRD labels.",
                "No sample is treated as WGS-signature validated in this phase-1 panel.",
            ],
        },
    )
    write_text(
        path_from_root("docs/reference-panel-label-rules.md"),
        """# HRD Reference Panel Label Rules

This frozen phase-1 panel uses open processed TCGA-BRCA PanCancer Atlas data from cBioPortal. It is a validation panel for workflow mechanics, not a clinical HRD truth set.

## Positive Controls

Positive controls require all of the following:

1. A likely damaging BRCA1/2 event in the fetched HRR mutation table.
2. A GISTIC copy-loss proxy for the same gene.
3. Elevated fraction genome altered in sample clinical data.

These are labeled expected HRD-like, but still carry a caveat that WGS structural-signature and companion-diagnostic evidence are not available in this phase.

## Mechanistic Controls

Mechanistic controls use likely damaging non-BRCA HRR events with copy-loss proxy and elevated fraction genome altered. These are useful stress tests, but less direct than BRCA1/2 controls.

## Ambiguous Controls

Ambiguous controls include HRR alterations without enough second-hit or scar-proxy support. They are intentionally included so the workflow can prove it does not force hard cases into binary labels.

## Negative Controls

Negative controls require no fetched HRR mutation, neutral BRCA1/2 GISTIC calls, low fraction genome altered, and modest mutation count. They are processed-data negative candidates, not proof of homologous-recombination proficiency.

## Boundary

No phase-1 label is based on WGS rearrangement signatures, SBS3 assignment, HRDetect, CHORD, Myriad myChoice, or clinician-owned companion-diagnostic review. Those remain future or external validation lanes.
""",
    )
    print(f"Selected {len(selected)} reference-panel samples.")


if __name__ == "__main__":
    main()
