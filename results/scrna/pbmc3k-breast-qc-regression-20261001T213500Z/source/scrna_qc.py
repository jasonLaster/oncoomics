"""Breast-cohort QC policy and audits; reference labels never choose thresholds."""
from __future__ import annotations

BREAST_MARKERS = {
    "Epithelial": ["EPCAM", "KRT8", "KRT18", "KRT19"],
    "T cells": ["CD3D", "CD3E", "TRAC"],
    "B cells": ["MS4A1", "CD79A", "CD79B"],
    "Plasma cells": ["MZB1", "JCHAIN", "SDC1"],
    "NK cells": ["NKG7", "GNLY", "KLRD1"],
    "Myeloid": ["LYZ", "LST1", "TYROBP", "FCER1G"],
    "Fibroblast": ["COL1A1", "COL1A2", "DCN", "LUM"],
    "Endothelial": ["PECAM1", "VWF", "CLDN5"],
    "Perivascular": ["RGS5", "PDGFRB", "MCAM", "CSPG4"],
}
REVIEW_PANELS = {
    "hemoglobin": ["HBA1", "HBA2", "HBB", "HBD"],
    "stress": ["FOS", "FOSB", "JUN", "JUNB", "DUSP1", "HSPA1A", "HSPA1B"],
    "cycling": ["MKI67", "TOP2A", "UBE2C", "CENPF", "PCNA", "MCM5"],
}
AUTHOR_COMPARTMENTS = {
    "Cancer Epithelial": "Epithelial", "Normal Epithelial": "Epithelial",
    "T-cells": "T cells", "B-cells": "B cells", "Plasmablasts": "Plasma cells",
    "Myeloid": "Myeloid", "CAFs": "Fibroblast", "PVL": "Perivascular", "Endothelial": "Endothelial",
}


def thresholds(obs, multiplier: float, profile: str = "human_pbmc") -> dict:
    import numpy as np

    if profile not in {"human_pbmc", "human_breast_tumor"}:
        raise ValueError("Unsupported QC profile")

    def tail(values, lower=False, log=False):
        data = np.log1p(values) if log else np.asarray(values)
        if not len(data) or not np.isfinite(data).all():
            raise ValueError("QC metrics must be finite and nonempty")
        median = float(np.median(data))
        mad = float(np.median(np.abs(data - median)))
        value = median + (-1 if lower else 1) * multiplier * mad
        return float(np.expm1(value) if log else value), mad

    genes, genes_mad = tail(obs.n_genes_by_counts, lower=True, log=True)
    umis, umis_mad = tail(obs.total_counts, lower=True, log=True)
    mt, mt_mad = tail(obs.pct_counts_mt)
    if profile == "human_breast_tumor":
        # A mixed tissue's median can be dominated by high-RNA epithelial cells.
        # Cap lower cutoffs at the observed 5th percentile; do not force low-RNA
        # immune cells to meet an epithelial-centered lower outlier threshold.
        genes = min(genes, float(np.quantile(obs.n_genes_by_counts, 0.05))) if genes_mad else 50
        umis = min(umis, float(np.quantile(obs.total_counts, 0.05))) if umis_mad else 100
        mt = min(100.0, mt) if mt_mad else 100.0
        rationale = "Sample/capture log1p lower MAD tails capped at observed p05 for mixed tissue; mt upper MAD tail without PBMC 5-25% bounds. Zero MAD disables that tail; no upper-count exclusion. Review loss by compartment and sensitivity before use."
    else:
        mt = min(25.0, max(5.0, mt))
        rationale = "Capture-level MAD robust tails; PBMC guardrails retain low-RNA lymphocytes and bound the mt tail."
    return {"min_genes": max(50, int(genes)), "min_umis": max(100, int(umis)),
            "max_pct_mt": mt, "profile": profile, "mad_multiplier": multiplier, "rationale": rationale}


def core_decisions(obs, policy: dict):
    import pandas as pd

    flags = pd.DataFrame({"fails_low_genes": obs.n_genes_by_counts < policy["min_genes"],
                          "fails_low_umis": obs.total_counts < policy["min_umis"],
                          "fails_mt": obs.pct_counts_mt > policy["max_pct_mt"]}, index=obs.index)
    flags["passes_core_qc"] = ~flags.any(axis=1)
    return flags


def validate_author_metadata(metadata, barcodes, dataset):
    required = {"orig.ident", "subtype", "celltype_major"}
    if not metadata.index.is_unique or set(metadata.index) != set(barcodes) or not required.issubset(metadata.columns):
        raise ValueError("Author metadata must map one-to-one to every barcode")
    metadata = metadata.loc[barcodes]
    if metadata[list(required)].isna().any().any():
        raise ValueError("Missing author metadata values")
    if not metadata["orig.ident"].eq(dataset["sample_id"]).all() or not metadata.subtype.eq(dataset["clinical_subtype"]).all():
        raise ValueError("Sample/subtype metadata disagree with manifest")
    unknown = set(metadata.celltype_major) - set(AUTHOR_COMPARTMENTS)
    if unknown:
        raise ValueError(f"Unmapped author compartments: {sorted(unknown)}")
    return metadata


def breast_audits(obs, dataset, parameters, directory):
    """Audit losses against published compartments after QC; never feed labels to filtering."""
    import numpy as np
    import pandas as pd

    rows = []
    for label, cells in obs.groupby("author_compartment", observed=True):
        rows.append({"compartment": label, "input_cells": len(cells),
                     "core_qc_cells": int(cells.passes_core_qc.sum()), "retained_cells": int(cells.passes_QC.sum()),
                     "retained_fraction": float(cells.passes_QC.mean()), "low_genes": int(cells.fails_low_genes.sum()),
                     "low_umis": int(cells.fails_low_umis.sum()), "mt": int(cells.fails_mt.sum()),
                     "doublets": int(cells.doublet_class.eq("doublet").sum())})
    retention = pd.DataFrame(rows)
    retention.to_csv(directory / "compartment_retention.csv", index=False)
    sensitivity = []
    for multiplier in parameters["qc_sensitivity_multipliers"]:
        policy = thresholds(obs, multiplier, "human_breast_tumor")
        flags = core_decisions(obs, policy)
        for label, cells in obs.groupby("author_compartment", observed=True):
            sensitivity.append({"mad_multiplier": multiplier, "compartment": label, "input_cells": len(cells),
                                "core_retained_cells": int(flags.loc[cells.index, "passes_core_qc"].sum()),
                                "min_genes": policy["min_genes"], "min_umis": policy["min_umis"], "max_pct_mt": policy["max_pct_mt"]})
    pd.DataFrame(sensitivity).to_csv(directory / "qc_sensitivity.csv", index=False)
    # Quantify the mismatch without letting the PBMC profile filter this sample.
    pbmc_flags = core_decisions(obs, thresholds(obs, parameters["qc_mad_multiplier"], "human_pbmc"))
    discordance = int((pbmc_flags.passes_core_qc != obs.passes_core_qc).sum())
    blockers = ["Independent annotation/doublet truth is unavailable", "Empty-droplet matrix unavailable: ambient RNA correction unvalidated"]
    if dataset["capture_scope"] != "verified_single_capture":
        blockers.append("Technical capture map unresolved: scDblFinder used sample matrix as a proxy")
    if dataset["chemistry_status"] != "verified":
        blockers.append("Per-sample chemistry unresolved")
    if dataset["treatment_status"] == "unknown" or dataset["timepoint"] == "unknown":
        blockers.append("Treatment/timepoint metadata unresolved")
    if (retention.retained_fraction < 0.7).any():
        blockers.append("At least one published compartment retained less than 70%; inspect loss before downstream use")
    return {"pbmc_policy_discordant_barcodes": discordance,
            "minimum_compartment_retention": float(np.min(retention.retained_fraction)),
            "production_ready": False, "readiness_blockers": blockers,
            "reference_status": "published same-dataset labels; coarse evaluation only; not independent truth",
            "ambient_rna_status": "not_assessed_no_empty_droplet_matrix",
            "malignancy_status": "not_called; epithelial expression is not malignancy evidence"}


def cohort_summary(config, summaries, output):
    import pandas as pd

    rows = []
    for dataset in config["datasets"]:
        if dataset.get("qc_profile") != "human_breast_tumor":
            continue
        metrics = summaries[dataset["dataset_id"]]
        rows.append({"dataset_id": dataset["dataset_id"], "donor_id": dataset["donor_id"], "sample_id": dataset["sample_id"],
                     "capture_id": dataset["capture_id"], "capture_scope": dataset["capture_scope"],
                     "clinical_subtype": dataset["clinical_subtype"], "treatment_status": dataset["treatment_status"],
                     "timepoint": dataset["timepoint"], "input_cells": metrics["input_cells"],
                     "retained_cells": metrics["retained_cells"], "retained_fraction": metrics["retained_fraction"],
                     "doublets": metrics["doublets_flagged"], "seed_stability_ari": metrics["seed_stability_ari"],
                     "minimum_compartment_retention": metrics["minimum_compartment_retention"],
                     "calibration_status": metrics["calibration_status"], "production_ready": metrics["production_ready"],
                     "readiness_blockers": "; ".join(metrics["readiness_blockers"])})
    if rows:
        pd.DataFrame(rows).to_csv(output / "cohort_qc.csv", index=False)
