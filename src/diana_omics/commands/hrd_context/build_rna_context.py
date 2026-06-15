from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from ...paths import path_from_root
from ...utils import (
    ensure_dir,
    group_by,
    iso_now,
    mean,
    parse_csv,
    pivot_clinical,
    read_json,
    read_text,
    round_value,
    standard_deviation,
    write_csv,
    write_json,
)

MODULES = {
    "basal_marker": ["KRT5", "KRT14", "KRT17", "EGFR", "FOXC1"],
    "lar_luminal_marker": ["AR", "FOXA1", "GATA3", "ESR1"],
    "proliferation_marker": ["MKI67"],
    "immune_inflammation_marker": ["CD8A", "CD274", "CXCL9", "IFNG"],
    "epithelial_marker": ["EPCAM", "MUC1"],
    "stromal_emt_marker": ["VIM"],
}


def expression_value(record: Mapping[str, Any]) -> float:
    return math.log2((record.get("value") or 0) + 1)


def expression_gene(record: Mapping[str, Any]) -> str:
    gene = record["gene"]
    return str(gene["hugoGeneSymbol"])


def classify_context(module_scores: Mapping[str, Optional[float]], subtype: str, pam50: str) -> str:
    basal = module_scores.get("basal_marker") or 0
    lar = module_scores.get("lar_luminal_marker") or 0
    immune = module_scores.get("immune_inflammation_marker") or 0
    if "basal" in subtype.lower() or "basal" in pam50.lower() or basal >= 0.75:
        return "basal_like_context"
    if lar >= 0.75 and basal < 0.5:
        return "lar_luminal_marker_context"
    if immune >= 0.75:
        return "immune_inflamed_context"
    return "mixed_or_non_basal_context"


def main() -> None:
    ensure_dir(path_from_root("results/evidence_tables"))

    panel = parse_csv(read_text(path_from_root("manifests/hrd_reference_panel.csv")))
    expression = read_json(path_from_root("data/raw/cbioportal/expression_marker_genes.json"))
    patient_clinical = pivot_clinical(read_json(path_from_root("data/raw/cbioportal/clinical_patient_selected.json")), "patientId")
    xena_rows = parse_csv(read_text(path_from_root("data/processed/xena/brca_clinical_subset.csv")))

    expression_by_gene = group_by(expression, expression_gene)
    expression_stats = {
        gene: {
            "mean": mean([expression_value(record) for record in records]) or 0,
            "sd": standard_deviation([expression_value(record) for record in records]) or 1,
        }
        for gene, records in expression_by_gene.items()
    }

    z_by_sample_gene = {}
    for record in expression:
        gene = expression_gene(record)
        stats = expression_stats[gene]
        z_by_sample_gene[f"{record['sampleId']}:{gene}"] = (expression_value(record) - stats["mean"]) / (stats["sd"] or 1)

    patient_clinical_by_id = {row["patientId"]: row for row in patient_clinical}
    xena_by_sample = {row["sampleID"]: row for row in xena_rows}
    subtype_rows = []
    module_rows = []

    for panel_row in panel:
        sample_id = panel_row["sample_id"]
        patient_id = panel_row["patient_id"]
        clinical_subtype = patient_clinical_by_id.get(patient_id, {}).get("SUBTYPE", "")
        xena = xena_by_sample.get(sample_id, {})
        pam50 = xena.get("PAM50Call_RNAseq") or xena.get("PAM50_mRNA_nature2012") or clinical_subtype
        module_scores = {
            module_name: mean([z_by_sample_gene.get(f"{sample_id}:{gene}") for gene in genes]) for module_name, genes in MODULES.items()
        }
        context = classify_context(module_scores, clinical_subtype, pam50 or "")
        subtype_rows.append(
            {
                "sample_id": sample_id,
                "source": "cBioPortal expression plus UCSC Xena clinical subset",
                "tool": "marker-module context script",
                "tool_version": "diana_omics.commands.hrd_context.build_rna_context",
                "cbioportal_subtype": clinical_subtype,
                "xena_pam50_call_rnaseq": xena.get("PAM50Call_RNAseq", ""),
                "xena_pam50_mrna_nature2012": xena.get("PAM50_mRNA_nature2012", ""),
                "er_status_nature2012": xena.get("ER_Status_nature2012", ""),
                "pr_status_nature2012": xena.get("PR_Status_nature2012", ""),
                "her2_status_nature2012": xena.get("HER2_Final_Status_nature2012", ""),
                "inferred_context": context,
                "confidence": "processed_public_context" if clinical_subtype or pam50 else "limited",
                "caveat": "This is not TNBCtype/TNBC-DX/Reveal. It is a small marker-module context lane for the HRD validation panel.",
            }
        )
        module_rows.append(
            {
                "sample_id": sample_id,
                "source": "cBioPortal RNA Seq V2 RSEM batch-normalized marker expression",
                "tool": "log2 expression z-score module means",
                "tool_version": "diana_omics.commands.hrd_context.build_rna_context",
                "basal_marker_z": round_value(module_scores["basal_marker"]),
                "lar_luminal_marker_z": round_value(module_scores["lar_luminal_marker"]),
                "proliferation_marker_z": round_value(module_scores["proliferation_marker"]),
                "immune_inflammation_marker_z": round_value(module_scores["immune_inflammation_marker"]),
                "epithelial_marker_z": round_value(module_scores["epithelial_marker"]),
                "stromal_emt_marker_z": round_value(module_scores["stromal_emt_marker"]),
                "marker_genes": "; ".join(f"{module_name}:{'|'.join(genes)}" for module_name, genes in MODULES.items()),
                "caveat": "Module scores are cohort-relative marker means, not locked clinical classifier outputs.",
            }
        )

    write_csv(path_from_root("results/rna_subtype_context.csv"), subtype_rows)
    write_csv(path_from_root("results/rna_module_context.csv"), module_rows)
    write_csv(path_from_root("results/evidence_tables/rna_subtype_context.csv"), subtype_rows)
    write_csv(path_from_root("results/evidence_tables/rna_module_context.csv"), module_rows)
    write_json(
        path_from_root("results/rna_context_summary.json"),
        {
            "generatedAt": iso_now(),
            "panelSampleCount": len(panel),
            "expressionRecordCount": len(expression),
            "moduleDefinitions": MODULES,
            "boundary": "RNA context is a small marker-module lane and does not reproduce TNBCtype, TNBC-DX, or Reveal.",
        },
    )
    print(f"Built RNA context tables for {len(panel)} panel samples.")


if __name__ == "__main__":
    main()
