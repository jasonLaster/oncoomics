"""Metadata-held, material-agnostic diagnostics; never patient admission or clinical inference."""

from __future__ import annotations

import re
import time
from itertools import combinations

from .scrna_io import safe_id, safe_key

PANELS = {
    "autophagy_machinery": ["ATG4B", "ATG13", "RB1CC1", "ULK1", "BECN1", "ATG5", "ATG7", "MAP1LC3B", "SQSTM1", "LAMP1", "LAMP2"],
    "mtor_rna_components": ["MTOR", "RPTOR", "RICTOR", "AKT1", "AKT2", "PIK3CA", "PTEN", "TSC1", "TSC2", "RHEB", "EIF4EBP1", "RPS6KB1"],
    "proteasome_components": ["PSMA1", "PSMA2", "PSMA3", "PSMB1", "PSMB2", "PSMB5", "PSMB8", "PSMB9", "PSMC1", "PSMD1"],
    "oxidative_stress_components": ["CUL3", "KEAP1", "NFE2L2", "NQO1", "HMOX1", "CAT", "GCLC", "GCLM", "SLC7A11", "TXNRD1"],
    "hrr_rna_components": [
        "BRCA1",
        "BRCA2",
        "PALB2",
        "RAD51",
        "RAD51C",
        "RAD51D",
        "BARD1",
        "BRIP1",
        "FANCD2",
        "FANCA",
        "ATM",
        "ATR",
        "CHEK1",
        "CHEK2",
        "PARP1",
    ],
    "lipid_rna_components": ["SCAP", "RXRA", "SREBF1", "SREBF2", "HMGCR", "HMGCS1", "LDLR", "FASN", "ACACA", "PPARD"],
    "cycling_review": ["MKI67", "TOP2A", "UBE2C", "CENPF", "PCNA", "MCM5"],
    "basal_epithelial_review": ["KRT5", "KRT14", "KRT17", "TP63", "KRT6A", "KRT16"],
}
TARGETS = sorted(
    set(
        sum(PANELS.values(), [])
        + [
            "TACSTD2",
            "TOP1",
            "SLFN11",
            "ABCB1",
            "ABCG2",
            "VIM",
            "FOLR1",
            "GPNMB",
            "EGFR",
            "ERBB2",
            "ERBB3",
            "MET",
            "MSLN",
            "DLL3",
            "CD274",
            "SLC29A1",
            "ERCC1",
            "TUBB3",
            "MGMT",
            "RRM1",
            "TYMP",
            "HSP90AA1",
            "HSP90AB1",
            "MCL1",
            "DLL4",
            "FGFR4",
            "BRD3",
            "WNT2B",
            "WNT6",
            "FZD10",
            "LIN28A",
            "EPCAM",
            "KRT8",
            "KRT18",
            "KRT19",
            "PTPRC",
            "COL1A1",
            "COL1A2",
            "DCN",
            "LUM",
            "CD3D",
            "CD3E",
            "TRAC",
            "NKG7",
            "GNLY",
            "MS4A1",
            "CD79A",
            "LYZ",
            "LST1",
            "PECAM1",
            "VWF",
        ]
    )
)


def validate_library(library: dict) -> None:
    """This lane cannot establish capture identity or change patient admission."""
    safe_id(library["library_id"])
    if not isinstance(library.get("expected_cells"), int) or not 100 <= library["expected_cells"] <= 100000:
        raise ValueError("Exploratory breast matrices require 100 to 100000 expected vendor barcodes")
    inputs = library["inputs"]
    if len(inputs) != 2 or {item["role"] for item in inputs} != {"raw_h5", "filtered_h5"}:
        raise ValueError("One raw and one filtered 10x H5 matrix are required")
    names = set()
    for item in inputs:
        safe_key(item["key"])
        safe_key(item["local_name"])
        if "/" in item["local_name"] or item["local_name"] in names:
            raise ValueError("Input filenames must be unique basenames")
        names.add(item["local_name"])
        if not item.get("version_id") or item["version_id"] == "null" or not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", "")):
            raise ValueError("Exact source versions and full SHA-256 hashes are required")
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] <= 0:
            raise ValueError("Positive input byte count required")


def validate_plan(plan: dict) -> None:
    from .scrna_private import BUCKET, run_prefix

    if plan.get("schema_version") != 1 or plan.get("evidence_lane") not in {"patient_research", "public_control"}:
        raise ValueError("Explicit evidence lane required; public accessibility does not make a patient a public control")
    if plan.get("metadata_hold") is not True or plan.get("clinical_ready") is not False:
        raise ValueError("Exploratory runs must retain metadata hold and clinical no-call")
    if plan["output_prefix"] != run_prefix(plan["run_id"]):
        raise ValueError("Use the canonical private run namespace")
    libraries = plan["libraries"]
    if not 1 <= len(libraries) <= 4:
        raise ValueError("Bound this exploratory run to at most four libraries")
    ids = [lib["library_id"] for lib in libraries]
    if len(ids) != len(set(ids)):
        raise ValueError("Library namespaces must be unique")
    sources = set()
    for lib in libraries:
        validate_library(lib)
        for item in lib["inputs"]:
            if item.get("bucket") != BUCKET or not item["key"].startswith("private/scrna/"):
                raise ValueError("Inputs must have a private frozen receipt")
            identity = (item["key"], item["version_id"])
            if identity in sources:
                raise ValueError("The same source matrix cannot impersonate two libraries")
            sources.add(identity)


def analyze_library(plan, source, output):
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import scanpy as sc
    from sklearn.metrics import adjusted_rand_score

    from diana_omics.scrna import doublets, marker_hints
    from diana_omics.scrna_ambient import assess_ambient
    from diana_omics.scrna_intake import align_raw, read_matrix
    from diana_omics.scrna_io import write_json
    from diana_omics.scrna_qc import BREAST_MARKERS, REVIEW_PANELS, core_decisions, thresholds

    validate_library(plan)
    start = time.monotonic()
    output.mkdir(parents=True, exist_ok=False)
    sc.settings.n_jobs = 4
    seed = 42
    paths = {x["role"]: source / x["local_name"] for x in plan["inputs"]}
    counts = read_matrix({"format": "10x_h5", "expected_cells": plan["expected_cells"]}, paths)
    import h5py

    with h5py.File(paths["filtered_h5"], "r") as vendor:
        types = {x.decode() if isinstance(x, bytes) else str(x) for x in vendor["matrix/features/feature_type"][:]}
    if types != {"Gene Expression"}:
        raise ValueError("This exploratory lane requires a gene-expression-only vendor matrix")
    raw = read_matrix({"format": "10x_h5"}, paths, raw=True)
    lineage = align_raw(counts, raw)
    write_json(output / "lineage.json", lineage)
    counts.obs["vendor_library_id"] = plan["library_id"]
    counts.obs["specimen_mapping_status"] = "unresolved"
    counts.obs["malignancy_status"] = "not_assessed"
    counts.var["mt"] = counts.var.gene_symbols.str.startswith("MT-").to_numpy()
    for key, genes in REVIEW_PANELS.items():
        counts.var[key] = counts.var.gene_symbols.isin(genes).to_numpy()
    counts.var["ribosomal"] = counts.var.gene_symbols.str.match(r"^RP[SL]\d").to_numpy()
    sc.pp.calculate_qc_metrics(
        counts, qc_vars=["mt", "hemoglobin", "stress", "cycling", "ribosomal"], percent_top=None, log1p=False, inplace=True
    )
    if (counts.obs.total_counts <= 0).any():
        raise ValueError("Zero-count vendor barcode requires cell-calling review")
    policy = thresholds(counts.obs, 3, "human_breast_tumor")
    for k, v in core_decisions(counts.obs, policy).items():
        counts.obs["conditional_whole_cell_" + k] = v
    write_json(
        output / "conditional_policy.json",
        {
            "policy": policy,
            "applied": False,
            "reason": "Material and specimen identity unresolved; these are sensitivity flags, never exclusions.",
        },
    )
    # Every original vendor-called barcode stays in the primary analysis.
    counts.obs.to_csv(output / "matrix_qc_before_doublets.csv")
    write_json(output / "progress.json", {"stage": "matrix_lineage_and_qc_complete", "cells": counts.n_obs})
    print(plan["library_id"], "matrix lineage and QC complete", flush=True)
    calls = doublets(counts, output, seed)
    for col in calls:
        counts.obs["diagnostic_" + col] = calls[col]
    if plan.get("chemistry") == "10x_3prime_v4":
        from .scrna_doublet_sensitivity import doublet_sensitivity

        counts.uns["doublet_rate_sensitivity"] = doublet_sensitivity(counts, output / "doublet_sensitivity", seed)
    counts.uns["doublet_policy"] = (
        "scDblFinder 1.20.2, full single-GEM vendor library, automatic expected rate; v4 loading and complete-capture identity not qualified; calls never filter this diagnostic analysis."
    )
    write_json(output / "progress.json", {"stage": "diagnostic_doublets_complete", "cells": counts.n_obs})
    print(plan["library_id"], "diagnostic doublets complete", flush=True)
    ambient = assess_ambient(counts, raw, output / "ambient", seed)
    del raw
    counts.uns["ambient_policy"] = "SoupX diagnostic challenger only; no correction applied to primary analysis."
    print(plan["library_id"], "ambient diagnostic complete", flush=True)
    # Log CP10k is used only for visualization; the counts object is never normalized in place.
    norm = counts.copy()
    norm.layers.clear()
    sc.pp.normalize_total(norm, target_sum=10000)
    sc.pp.log1p(norm)
    sc.pp.highly_variable_genes(norm, n_top_genes=2000, flavor="seurat")
    latent = norm[:, norm.var.highly_variable].copy()
    sc.pp.scale(latent, zero_center=False, max_value=10)
    sc.pp.pca(latent, n_comps=40, svd_solver="arpack", random_state=seed)
    sc.pp.neighbors(latent, n_neighbors=15, n_pcs=40, random_state=seed)
    partitions = []
    for s in [42, 43, 44]:
        sc.tl.leiden(latent, resolution=0.5, flavor="igraph", n_iterations=-1, directed=False, random_state=s, key_added=f"leiden_{s}")
        partitions.append(latent.obs[f"leiden_{s}"].astype(str).to_numpy())
    stability = [
        {"seed_a": 42 + i, "seed_b": 42 + j, "ari": float(adjusted_rand_score(partitions[i], partitions[j]))}
        for i, j in combinations(range(3), 2)
    ]
    pd.DataFrame(stability).to_csv(output / "diagnostic_seed_stability.csv", index=False)
    norm.obs["leiden"] = latent.obs.leiden_42
    marker_hints(norm, output, BREAST_MARKERS)
    sc.tl.umap(latent, random_state=seed)
    counts.obsm["X_umap"] = latent.obsm["X_umap"]
    counts.obsm["X_pca"] = latent.obsm["X_pca"]
    counts.obs["leiden_diagnostic_r05"] = norm.obs.leiden
    counts.obs["coarse_label_hint"] = norm.obs.coarse_label_hint
    counts.obs["marker_score_margin"] = norm.obs.marker_score_margin
    counts.uns["annotation_policy"] = norm.uns["annotation_policy"]
    counts.uns["embedding_policy"] = (
        "All vendor-called barcodes, original counts log-CP10k/HVG2000/PCA40/neighbors15/UMAP seed42; no integration or clinical sample identity claim; no QC/doublet exclusions."
    )

    gene_positions = {g: list(counts.var.gene_symbols[counts.var.gene_symbols == g].index) for g in TARGETS}
    expression, logs = {}, {}
    for g, names in gene_positions.items():
        if not names:
            continue
        expression[g] = np.asarray(counts[:, names].X.sum(axis=1)).ravel()
        logs[g] = np.log1p(expression[g] * 10000 / counts.obs.total_counts.to_numpy())
    target_counts = pd.DataFrame(expression, index=counts.obs_names)
    target_counts.to_csv(output / "target_umi_per_barcode.csv.gz", compression="gzip")
    targets = []
    groupings = [
        ("all_vendor_barcodes", np.repeat("all", counts.n_obs)),
        ("coarse_marker_hint", counts.obs.coarse_label_hint.astype(str).to_numpy()),
        ("diagnostic_cluster", counts.obs.leiden_diagnostic_r05.astype(str).to_numpy()),
        ("diagnostic_doublet_class", counts.obs.diagnostic_doublet_class.astype(str).to_numpy()),
        (
            "conditional_whole_cell_core_flag",
            np.where(counts.obs.conditional_whole_cell_passes_core_qc, "conditional_core_pass", "conditional_core_flag"),
        ),
    ]
    for grouping, labels in groupings:
        for label in sorted(set(labels)):
            mask = labels == label
            libsum = float(counts.obs.total_counts.to_numpy()[mask].sum())
            for g in TARGETS:
                if g not in expression:
                    targets.append(
                        {
                            "library_id": plan["library_id"],
                            "grouping": grouping,
                            "group": label,
                            "gene": g,
                            "feature_present": False,
                            "cells": int(mask.sum()),
                        }
                    )
                    continue
                v = expression[g][mask]
                targets.append(
                    {
                        "library_id": plan["library_id"],
                        "grouping": grouping,
                        "group": label,
                        "gene": g,
                        "feature_present": True,
                        "feature_matches": len(gene_positions[g]),
                        "cells": int(mask.sum()),
                        "detected_cells": int((v > 0).sum()),
                        "detected_fraction": float((v > 0).mean()),
                        "umi_sum": int(v.sum()),
                        "pseudobulk_umi_cpm": float(v.sum() / libsum * 1e6),
                        "mean_log1p_cp10k": float(logs[g][mask].mean()),
                        "median_log1p_cp10k": float(np.median(logs[g][mask])),
                    }
                )
    pd.DataFrame(targets).to_csv(output / "target_expression_by_group.csv", index=False)
    membership = []
    panel_rows = []
    for panel, genes in PANELS.items():
        matched = [g for g in genes if g in logs]
        for g in genes:
            membership.append({"panel": panel, "gene": g, "feature_present": g in logs})
        values = np.mean(np.column_stack([logs[g] for g in matched]), axis=1) if matched else np.full(counts.n_obs, np.nan)
        counts.obs["descriptive_panel_" + panel] = values
        for grouping, labels in groupings:
            for label in sorted(set(labels)):
                mask = labels == label
                panel_rows.append(
                    {
                        "library_id": plan["library_id"],
                        "panel": panel,
                        "grouping": grouping,
                        "group": label,
                        "cells": int(mask.sum()),
                        "genes_matched": len(matched),
                        "genes_requested": len(genes),
                        "mean_log1p_cp10k": float(values[mask].mean()) if matched else None,
                        "interpretation": "Descriptive gene-panel abundance; no pathway activity, flux, HRD, bulk percentile or dependency call.",
                    }
                )
    pd.DataFrame(membership).to_csv(output / "panel_gene_membership.csv", index=False)
    pd.DataFrame(panel_rows).to_csv(output / "descriptive_panels_by_group.csv", index=False)

    # Preserve full reference identifiers and raw source counts for reproducible reinspection.
    counts.var.to_csv(output / "features.csv")
    counts.obs.to_csv(output / "all_vendor_barcodes.csv.gz", compression="gzip")
    coords = pd.DataFrame(counts.obsm["X_umap"], index=counts.obs_names, columns=["UMAP1", "UMAP2"])
    coords.to_csv(output / "umap_coordinates.csv")
    counts.uns["clinical_ready"] = False
    counts.uns["metadata_hold"] = True
    counts.write_h5ad(output / "all_vendor_cells_counts.h5ad", compression="gzip")
    fig, axes = plt.subplots(1, 3, figsize=(14, 4))
    axes[0].scatter(counts.obs.total_counts, counts.obs.n_genes_by_counts, s=1, alpha=0.25)
    axes[0].set(xscale="log", yscale="log", xlabel="UMIs", ylabel="Detected genes")
    axes[1].hist(counts.obs.pct_counts_mt, bins=80)
    axes[1].set(xlabel="Mitochondrial UMI %", ylabel="Vendor barcodes")
    axes[2].hist(counts.obs.diagnostic_doublet_score, bins=80)
    axes[2].set(xlabel="Diagnostic scDblFinder score", ylabel="Vendor barcodes")
    fig.suptitle(plan["library_id"] + ": all barcodes retained; metadata held")
    fig.tight_layout()
    fig.savefig(output / "matrix_qc.png", dpi=160)
    plt.close(fig)
    for color, filename in [
        ("coarse_label_hint", "umap_marker_hints.png"),
        ("leiden_diagnostic_r05", "umap_clusters.png"),
        ("diagnostic_doublet_class", "umap_doublets.png"),
    ]:
        sc.pl.umap(counts, color=color, title=plan["library_id"] + " — " + color + " (diagnostic)", show=False)
        plt.savefig(output / filename, dpi=160, bbox_inches="tight")
        plt.close("all")
    for g in ["TACSTD2", "SLFN11", "VIM", "BRCA1", "ATG4B", "MTOR"]:
        if g in logs:
            coords = counts.obsm["X_umap"]
            fig, ax = plt.subplots(figsize=(5, 4))
            p = ax.scatter(coords[:, 0], coords[:, 1], c=logs[g], s=1, cmap="viridis", vmin=0, vmax=float(np.quantile(logs[g], 0.99)) or 1)
            ax.set(title=f"{plan['library_id']}: {g} RNA", xlabel="UMAP1", ylabel="UMAP2")
            fig.colorbar(p, ax=ax, label="log1p CP10k")
            fig.tight_layout()
            fig.savefig(output / f"umap_{g}.png", dpi=160)
            plt.close(fig)
    qc_summary = {}
    for metric in [
        "total_counts",
        "n_genes_by_counts",
        "pct_counts_mt",
        "pct_counts_stress",
        "pct_counts_hemoglobin",
        "pct_counts_cycling",
    ]:
        qc_summary[metric] = {str(q): float(counts.obs[metric].quantile(q)) for q in [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1]}
    summary = {
        "library_id": plan["library_id"],
        "input_cells": counts.n_obs,
        "analysis_cells": counts.n_obs,
        "gex_features": counts.n_vars,
        "source_integer_counts": True,
        "lineage": lineage,
        "qc_distributions": qc_summary,
        "diagnostic_doublets": int(counts.obs.diagnostic_doublet_class.eq("doublet").sum()),
        "diagnostic_doublet_fraction": float(counts.obs.diagnostic_doublet_class.eq("doublet").mean()),
        "conditional_whole_cell_core_flagged": int((~counts.obs.conditional_whole_cell_passes_core_qc).sum()),
        "conditional_flags_applied": False,
        "coarse_hint_counts": {str(k): int(v) for k, v in counts.obs.coarse_label_hint.value_counts().items()},
        "unknown_hint_fraction": float(counts.obs.coarse_label_hint.eq("Unknown / mixed").mean()),
        "cluster_count": int(counts.obs.leiden_diagnostic_r05.nunique()),
        "seed_ari_median": float(np.median([x["ari"] for x in stability])),
        "ambient": ambient,
        "metadata_hold": True,
        "clinical_ready": False,
        "production_ready": False,
        "duration_seconds": time.monotonic() - start,
    }
    write_json(output / "summary.json", summary)
    return summary
