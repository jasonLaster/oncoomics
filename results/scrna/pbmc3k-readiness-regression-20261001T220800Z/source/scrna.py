"""Sparse, capture-aware post-count calibration for public human PBMC and breast tumor data."""
from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import time
from pathlib import Path

from .scrna_io import calibration_gates, extract_matrix, verify_file, write_json
from .scrna_miqc import assess_miqc
from .scrna_qc import (
    AUTHOR_COMPARTMENTS,
    BREAST_MARKERS,
    REVIEW_PANELS,
    breast_audits,
    coarse_marker_scores,
    cohort_summary,
    core_decisions,
    read_geo_matrix,
    thresholds,
)

MARKERS = {
    "T cells": ["CD3D", "CD3E", "TRAC"],
    "B cells": ["MS4A1", "CD79A", "CD79B"],
    "NK cells": ["NKG7", "GNLY", "PRF1"],
    "Monocytes": ["LYZ", "LST1", "S100A8", "S100A9"],
    "Dendritic cells": ["FCER1A", "CD1C", "CLEC10A"],
    "Platelets": ["PPBP", "PF4"],
}


def doublets(adata, directory: Path, seed: int):
    """Pass only sparse counts/barcodes to R; require a one-to-one return mapping."""
    import pandas as pd
    from scipy.io import mmwrite
    from scipy.sparse import csr_matrix

    bridge = directory / "doublets"
    bridge.mkdir()
    mmwrite(bridge / "counts.mtx", csr_matrix(adata.X).T)
    adata.obs_names.to_series().to_csv(bridge / "barcodes.tsv", index=False, header=False)
    script = bridge / "call.R"
    script.write_text('''args <- commandArgs(trailingOnly=TRUE)
suppressPackageStartupMessages({library(Matrix); library(SingleCellExperiment); library(scDblFinder)})
set.seed(as.integer(args[2]))
x <- as(readMM(file.path(args[1], "counts.mtx")), "CsparseMatrix")
barcodes <- readLines(file.path(args[1], "barcodes.tsv"))
colnames(x) <- barcodes
sce <- SingleCellExperiment(list(counts=x))
sce <- scDblFinder(sce, BPPARAM=BiocParallel::SerialParam())
write.csv(data.frame(barcode=barcodes, doublet_score=sce$scDblFinder.score,
                    doublet_class=sce$scDblFinder.class), file.path(args[1], "calls.csv"), row.names=FALSE)
writeLines(capture.output(sessionInfo()), file.path(args[1], "r_session.txt"))
''')
    result = subprocess.run(["Rscript", str(script), str(bridge), str(seed)], capture_output=True, text=True, timeout=900)
    (bridge / "r.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"scDblFinder failed: {result.stderr[-2000:]}")
    calls = pd.read_csv(bridge / "calls.csv", index_col="barcode")
    if not calls.index.is_unique or set(calls.index) != set(adata.obs_names):
        raise ValueError("scDblFinder barcodes do not map one-to-one onto counts")
    calls = calls.loc[adata.obs_names]
    import numpy as np
    if not calls.doublet_class.isin(["singlet", "doublet"]).all() or not np.isfinite(calls.doublet_score).all():
        raise ValueError("Incomplete doublet calls")
    # The full count checkpoint is canonical; bridge data are redundant.
    (bridge / "counts.mtx").unlink()
    return calls


def qc_thresholds(obs, multiplier: float, profile: str = "human_pbmc") -> dict:
    return thresholds(obs, multiplier, profile)


def marker_hints(adata, directory: Path, panel=None):
    import numpy as np
    import pandas as pd

    panels = MARKERS if panel is None else panel
    scores = {}
    for name, geneset in panels.items():
        genes = [g for g in geneset if g in adata.var_names]
        if len(genes) < 2:
            continue
        # Densify a small marker panel only, never the complete expression matrix.
        expression = adata[:, genes].X.toarray()
        standardized = (expression - expression.mean(axis=0)) / np.maximum(expression.std(axis=0), 0.1)
        scores[name] = standardized.mean(axis=1)
    if len(scores) < 2:
        raise ValueError("Insufficient matched tissue marker panel")
    frame = pd.DataFrame(scores, index=adata.obs_names)
    grouped = frame.groupby(adata.obs.leiden, observed=True).mean()
    grouped = coarse_marker_scores(grouped, breast=panel is not None)
    grouped.to_csv(directory / "cluster_marker_scores.csv")
    hints, margins = {}, {}
    for cluster, row in grouped.iterrows():
        ordered = row.sort_values(ascending=False)
        margin = float(ordered.iloc[0] - ordered.iloc[1])
        hints[cluster] = ordered.index[0] if ordered.iloc[0] >= 0.25 and margin >= 0.15 else "Unknown / mixed"
        margins[cluster] = margin
    adata.obs["coarse_label_hint"] = adata.obs.leiden.astype(str).map(hints).astype("category")
    adata.obs["fine_label"] = "unreviewed"
    adata.obs["marker_score_margin"] = adata.obs.leiden.astype(str).map(margins).astype(float)
    adata.uns["annotation_policy"] = "Provisional cluster tissue marker scores; margin is a heuristic, not a calibrated probability. Epithelial markers do not establish malignancy."
    return {k: list(v) for k, v in panels.items()}


def breast_qc_plots(obs, policy, dataset_id, directory):
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    ax = axes.flat[0]
    ax.scatter(np.log1p(obs.total_counts), np.log1p(obs.n_genes_by_counts), s=4,
               c=np.where(obs.passes_QC, "#527a99", "#b94646"), alpha=0.4)
    ax.axvline(np.log1p(policy["min_umis"]), color="#b94646", linestyle="--")
    ax.axhline(np.log1p(policy["min_genes"]), color="#b94646", linestyle="--")
    ax.set(xlabel="log1p UMIs", ylabel="log1p detected genes", title="Core QC / doublet loss (red)")
    for ax, name in zip(list(axes.flat)[1:], ["hemoglobin", "stress", "cycling", "ribosomal", "mt"]):
        ax.scatter(np.log1p(obs.total_counts), obs[f"pct_counts_{name}"], s=4, alpha=0.3, color="#527a99")
        ax.set(xlabel="log1p UMIs", ylabel=f"{name} percent", title="Core filter" if name == "mt" else "Review only")
    fig.suptitle(dataset_id + ": tissue QC and review signals")
    fig.tight_layout()
    fig.savefig(directory / "breast_qc_review.png", dpi=150)
    plt.close(fig)
    grouped = obs.groupby("author_compartment", observed=True).passes_QC.agg(["sum", "count"])
    fig, ax = plt.subplots(figsize=(8, 4))
    (grouped["sum"] / grouped["count"]).sort_values().plot.barh(ax=ax, color="#527a99")
    ax.axvline(0.7, color="#b94646", linestyle="--")
    ax.set(xlim=(0, 1), xlabel="Fraction retained from already-filtered author matrix", title=dataset_id + ": compartment loss audit")
    fig.tight_layout()
    fig.savefig(directory / "compartment_retention.png", dpi=150)
    plt.close(fig)


def analyze(dataset: dict, parameters: dict, acceptance: dict, input_paths: dict[str, Path], directory: Path) -> dict:
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import scanpy as sc
    from scipy.sparse import csr_matrix, issparse
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

    started = time.monotonic()
    directory.mkdir(parents=True)
    seed = parameters["seed"]
    np.random.seed(seed)
    sc.settings.n_jobs = 4
    counts_path = input_paths["counts"]
    profile = dataset.get("qc_profile", "human_pbmc")
    author_metadata = None
    if dataset["format"] == "geo_breast_mtx_tar":
        matrix_dir = extract_matrix(counts_path, directory / "input_matrix", "count_matrix_sparse.mtx")
        adata, author_metadata = read_geo_matrix(matrix_dir, dataset)
    elif dataset["format"] == "10x_mtx_tar":
        matrix_dir = extract_matrix(counts_path, directory / "input_matrix")
        adata = sc.read_10x_mtx(matrix_dir, var_names="gene_symbols", cache=False)
    else:
        adata = sc.read_10x_h5(counts_path, gex_only=True)
    adata.var_names_make_unique()
    if not adata.obs_names.is_unique:
        raise ValueError("Duplicate cell barcodes")
    adata.X = csr_matrix(adata.X)
    if not np.isfinite(adata.X.data).all() or (adata.X.data < 0).any() or not np.equal(adata.X.data, np.round(adata.X.data)).all():
        raise ValueError("Non-finite, negative, or non-integer values: expected raw UMI counts")
    input_cells, input_genes = adata.shape
    if input_cells != dataset["expected_cells"]:
        raise ValueError(f"Input identity mismatch: {input_cells} cells, expected {dataset['expected_cells']}")
    if not adata.var_names.str.startswith("MT-").any():
        raise ValueError("No mitochondrial gene symbols; check feature identifiers")
    adata.obs["capture_id"] = dataset["capture_id"]
    adata.obs["donor_id"] = dataset["donor_id"]
    adata.var["mt"] = adata.var_names.str.startswith("MT-")
    for name, geneset in REVIEW_PANELS.items():
        adata.var[name] = adata.var_names.isin(geneset)
    adata.var["ribosomal"] = adata.var_names.str.match(r"^RP[SL]\d")
    sc.pp.calculate_qc_metrics(adata, qc_vars=["mt", "hemoglobin", "stress", "cycling", "ribosomal"], percent_top=None, log1p=False, inplace=True)
    if author_metadata is not None:
        for column, observed in (("nCount_RNA", adata.obs.total_counts), ("nFeature_RNA", adata.obs.n_genes_by_counts)):
            if column not in author_metadata or not np.allclose(author_metadata[column], observed, atol=1e-6, rtol=0):
                raise ValueError(f"Author {column} does not agree with matrix counts")
    thresholds = qc_thresholds(adata.obs, parameters["qc_mad_multiplier"], profile)
    decisions = core_decisions(adata.obs, thresholds)
    for column in decisions:
        adata.obs[column] = decisions[column]
    # Review signals have no effect on passes_core_qc or passes_QC.
    review_cutoffs = {}
    for name in ("hemoglobin", "stress", "cycling", "ribosomal"):
        values = adata.obs[f"pct_counts_{name}"]
        median = float(np.median(values))
        cutoff = median + 3 * float(np.median(np.abs(values - median)))
        review_cutoffs[name] = cutoff
        adata.obs[f"review_high_{name}"] = values > cutoff
    log_umis = np.log1p(adata.obs.total_counts)
    high_umi_cutoff = float(np.expm1(np.median(log_umis) + 3 * np.median(np.abs(log_umis - np.median(log_umis)))))
    review_cutoffs["high_umis"] = high_umi_cutoff
    adata.obs["review_high_umis"] = adata.obs.total_counts > high_umi_cutoff
    if profile == "human_breast_tumor":
        for field in ("sample_id", "clinical_subtype", "treatment_status", "timepoint", "capture_scope", "chemistry_status"):
            adata.obs[field] = dataset[field]
        adata.obs["malignancy_status"] = "not_assessed"
    qualified = adata[adata.obs.passes_core_qc]
    if qualified.n_obs < 100:
        raise ValueError("Too few cells after core QC")
    calls = doublets(qualified, directory, seed)
    adata.obs["doublet_score"] = calls.doublet_score.reindex(adata.obs_names)
    adata.obs["doublet_class"] = calls.doublet_class.reindex(adata.obs_names).fillna("not_called_core_qc_fail")
    adata.obs["doublet_partition"] = dataset["capture_id"]
    adata.obs["passes_QC"] = adata.obs.passes_core_qc & (adata.obs.doublet_class == "singlet")
    adata.uns["qc_thresholds"] = thresholds
    adata.uns["review_only_cutoffs"] = review_cutoffs
    adata.uns["upstream_processing"] = dataset.get("upstream_processing", "vendor filtered matrix")
    adata.obs["qc_failure_reasons"] = adata.obs.apply(lambda row: ";".join(
        [key for key in ("fails_low_genes", "fails_low_umis", "fails_mt") if row[key]]
        + (["scDblFinder_doublet"] if row.doublet_class == "doublet" else [])), axis=1)
    miqc_metrics = {}
    if profile == "human_breast_tumor" and parameters.get("miqc_challenger"):
        miqc_metrics = assess_miqc(adata.obs, directory, seed)
    breast_metrics = {}
    if author_metadata is not None:
        # Labels are read only for custody checks, then joined after all decisions.
        adata.obs["author_compartment"] = author_metadata.celltype_major.map(AUTHOR_COMPARTMENTS)
        breast_metrics = breast_audits(adata.obs, dataset, parameters, directory)
        if miqc_metrics.get("seed_decision_agreement") is not None:
            adata.obs.groupby("author_compartment", observed=True).agg(
                input_cells=("passes_core_qc", "size"), active_core_cells=("passes_core_qc", "sum"),
                candidate_mt_kept=("miqc_candidate_keep", "sum"),
                alternate_candidate_mt_kept=("miqc_alternate_candidate_keep", "sum"),
            ).to_csv(directory / "miqc" / "compartment_comparison.csv")
    adata.uns["ambient_rna_status"] = "not_assessed_no_empty_droplet_matrix"
    adata.write_h5ad(directory / "all_cells_qc.h5ad", compression="gzip")
    adata.obs.to_csv(directory / "all_cells_qc.csv")
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.5))
    for ax, (metric, threshold, label) in zip(axes, [
        ("n_genes_by_counts", thresholds["min_genes"], "Detected genes"),
        ("total_counts", thresholds["min_umis"], "Total UMIs"),
        ("pct_counts_mt", thresholds["max_pct_mt"], "Mitochondrial percent"),
    ]):
        values = adata.obs[metric]
        ax.hist(np.log1p(values) if metric != "pct_counts_mt" else values, bins=60, color="#527a99")
        ax.axvline(np.log1p(threshold) if metric != "pct_counts_mt" else threshold, color="#b94646", linestyle="--")
        ax.set_xlabel(("log1p " if metric != "pct_counts_mt" else "") + label)
        ax.set_ylabel("Barcodes")
    fig.suptitle(f"{dataset['dataset_id']}: observed distributions and selected thresholds")
    fig.tight_layout()
    fig.savefig(directory / "qc_thresholds.png", dpi=150)
    plt.close(fig)
    if profile == "human_breast_tumor":
        breast_qc_plots(adata.obs, thresholds, dataset["dataset_id"], directory)
    all_metrics = adata.obs
    filtered = adata[adata.obs.passes_QC].copy()
    del qualified, adata
    filtered.layers["counts"] = filtered.X.copy()
    counts_sum_before = float(filtered.layers["counts"].sum())
    sc.pp.normalize_total(filtered, target_sum=10000)
    sc.pp.log1p(filtered)
    sc.pp.highly_variable_genes(filtered, n_top_genes=parameters["n_hvg"], flavor="seurat")
    if profile == "human_breast_tumor":
        nuisance = filtered.var[["mt", "hemoglobin", "ribosomal", "stress"]].any(axis=1)
        filtered.var["highly_variable"] &= ~nuisance
    # Preserve normalized expression on all genes for marker testing. Only copy HVGs for PCA.
    latent = filtered[:, filtered.var.highly_variable].copy()
    sc.pp.scale(latent, zero_center=False, max_value=10)
    n_pcs = min(parameters["n_pcs"], latent.n_obs - 1, latent.n_vars - 1)
    sc.pp.pca(latent, n_comps=n_pcs, svd_solver="arpack", random_state=seed)
    filtered.obsm["X_pca"] = latent.obsm["X_pca"]
    del latent
    sc.pp.neighbors(filtered, n_neighbors=parameters["n_neighbors"], n_pcs=n_pcs, random_state=seed)
    sc.tl.umap(filtered, random_state=seed)
    for clustering_seed, key in ((seed, "leiden"), (seed + 1, "leiden_alternate_seed")):
        sc.tl.leiden(filtered, resolution=parameters["leiden_resolution"], random_state=clustering_seed,
                     key_added=key, flavor="igraph", n_iterations=parameters["leiden_iterations"], directed=False)
    panel = marker_hints(filtered, directory, BREAST_MARKERS if profile == "human_breast_tumor" else None)
    sc.tl.rank_genes_groups(filtered, "leiden", method="wilcoxon", use_raw=False, pts=True)
    sc.get.rank_genes_groups_df(filtered, group=None).groupby("group", observed=True).head(50).to_csv(directory / "markers.csv", index=False)
    coords = pd.DataFrame(filtered.obsm["X_umap"], index=filtered.obs_names, columns=["umap_1", "umap_2"])
    coords.join(filtered.obs[["leiden", "coarse_label_hint", "marker_score_margin", "capture_id"]]).to_csv(directory / "umap.csv")
    for color in ("leiden", "coarse_label_hint"):
        sc.pl.umap(filtered, color=color, show=False, title=f"{dataset['dataset_id']} — {color}")
        plt.savefig(directory / f"umap_{color}.png", dpi=150, bbox_inches="tight")
        plt.close("all")
    raw_preserved = issparse(filtered.layers["counts"]) and float(filtered.layers["counts"].sum()) == counts_sum_before
    filtered.write_h5ad(directory / "analysis.h5ad", compression="gzip")
    # Verify the persisted checkpoint, not just the in-memory object.
    checkpoint = sc.read_h5ad(directory / "analysis.h5ad", backed="r")
    persisted = checkpoint.layers["counts"]
    raw_preserved = (
        raw_preserved and issparse(persisted) and persisted.shape == filtered.layers["counts"].shape
        and (persisted != filtered.layers["counts"]).nnz == 0
    )
    checkpoint.file.close()
    metrics = {
        **breast_metrics, "qc_profile": profile, "miqc_challenger": miqc_metrics,
        "input_cells": input_cells, "input_genes": input_genes,
        "core_qc_cells": int(all_metrics.passes_core_qc.sum()),
        "retained_cells": filtered.n_obs, "retained_fraction": filtered.n_obs / input_cells,
        "low_genes_flagged": int(all_metrics.fails_low_genes.sum()), "low_umis_flagged": int(all_metrics.fails_low_umis.sum()),
        "mt_flagged": int(all_metrics.fails_mt.sum()), "doublets_flagged": int((all_metrics.doublet_class == "doublet").sum()),
        "doublet_method": "scDblFinder", "doublet_validation": "no_independent_truth_labels",
        "clusters": int(filtered.obs.leiden.nunique()),
        "seed_stability_ari": float(adjusted_rand_score(filtered.obs.leiden, filtered.obs.leiden_alternate_seed)),
        "finite_embedding": bool(np.isfinite(filtered.obsm["X_umap"]).all()), "raw_counts_preserved": bool(raw_preserved),
        "ambient_rna_status": "not_assessed_no_empty_droplet_matrix",
        "coarse_label_hint_counts": {str(k): int(v) for k, v in filtered.obs.coarse_label_hint.value_counts().items()},
        "thresholds": thresholds,
        "review_only_flags": {key: int(all_metrics[key].sum()) for key in all_metrics if key.startswith("review_high_")},
    }
    if author_metadata is not None:
        truth = author_metadata.loc[filtered.obs_names, "celltype_major"].map(AUTHOR_COMPARTMENTS)
        predicted = filtered.obs.coarse_label_hint.astype(str)
        overlap = pd.crosstab(truth, predicted)
        overlap.to_csv(directory / "reference_compartment_overlap.csv")
        recall = [(predicted[truth == label] == label).mean() for label in truth.unique()]
        metrics["coarse_reference_accuracy"] = float((truth == predicted).mean())
        metrics["coarse_reference_balanced_accuracy"] = float(np.mean(recall))
        metrics["unknown_label_fraction"] = float(predicted.eq("Unknown / mixed").mean())
    if "reference_labels" in input_paths:
        reference = sc.read_h5ad(input_paths["reference_labels"])
        common = filtered.obs_names.intersection(reference.obs_names)
        column = dataset["reference_label_column"]
        if not reference.obs_names.is_unique or column not in reference.obs or reference.obs.loc[common, column].isna().any():
            raise ValueError("Invalid reference annotations")
        observed_labels = filtered.obs.loc[common, "leiden"]
        reference_labels = reference.obs.loc[common, column]
        metrics.update({"reference_common_cells": len(common),
                        "reference_ari": float(adjusted_rand_score(reference_labels, observed_labels)),
                        "reference_nmi": float(normalized_mutual_info_score(reference_labels, observed_labels)),
                        "reference_status": "same-dataset tutorial annotations; not independent truth"})
        pd.crosstab(reference_labels, observed_labels).to_csv(directory / "reference_cluster_overlap.csv")
    metrics["gates"] = calibration_gates(metrics, dataset["expected_cells"], acceptance, "reference_labels" in input_paths)
    if profile == "human_breast_tumor":
        metrics["gates"]["compartment_retention"] = metrics["minimum_compartment_retention"] >= 0.7
        metrics["gates"]["capture_metadata_resolved"] = dataset["capture_scope"] == "verified_single_capture"
        metrics["gates"]["chemistry_metadata_resolved"] = dataset["chemistry_status"] == "verified"
    metrics["calibration_status"] = "pass" if all(metrics["gates"].values()) else "needs_review"
    metrics["elapsed_seconds"] = round(time.monotonic() - started, 2)
    write_json(directory / "calibration.json", metrics)
    write_json(directory / "parameters.json", {"parameters": parameters, "thresholds": thresholds, "marker_panel": panel,
                                               "review_only_cutoffs": review_cutoffs,
                                               "embedding_policy": "Breast: exclude mt/hemoglobin/ribosomal/stress HVGs, preserve cycling genes; PBMC: existing HVGs",
                                               "latent_method": "HVG PCA; captures/sample proxies analyzed separately; no cross-donor integration or DE"})
    # Extracted public matrix duplicates are not canonical outputs.
    import shutil
    shutil.rmtree(directory / "input_matrix", ignore_errors=True)
    return metrics


def execute(config: dict, source_root: Path, output: Path) -> dict:
    from .scrna_io import validate_config

    validate_config(config)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "input_manifest.json", config)
    versions = {dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions() if dist.metadata["Name"]}
    write_json(output / "python_packages.json", {"python": platform.python_version(), "packages": versions})
    explicit = subprocess.run(["micromamba", "list", "--explicit"], capture_output=True, text=True, check=True)
    (output / "conda-explicit.txt").write_text(explicit.stdout)
    source_hashes = {}
    from .scrna_io import safe_key, sha256_file
    for path in (Path(__file__), Path(__file__).with_name("scrna_io.py"), Path(__file__).with_name("scrna_qc.py"),
                 Path(__file__).with_name("scrna_miqc.py"), Path(__file__).with_name("scrna_release.py")):
        source_hashes[path.name] = sha256_file(path)
        shutil_path = output / "source" / path.name
        shutil_path.parent.mkdir(exist_ok=True)
        shutil_path.write_bytes(path.read_bytes())
    write_json(output / "source_hashes.json", source_hashes)
    summaries = {}
    for dataset in config["datasets"]:
        paths = {}
        for item in dataset["inputs"]:
            path = source_root / safe_key(item["key"])
            verify_file(path, item["sha256"])
            paths[item["role"]] = path
        print(f"Analyzing {dataset['dataset_id']}", flush=True)
        summaries[dataset["dataset_id"]] = analyze(dataset, config["parameters"], config["acceptance"], paths, output / dataset["dataset_id"])
    cohort_summary(config, summaries, output)
    write_json(output / "calibration_summary.json", summaries)
    write_review(output, summaries)
    return summaries


def write_review(output: Path, summaries: dict) -> None:
    from html import escape

    sections = []
    readiness_lines = []
    lines = ["# Single-cell calibration", "", "Public matrix-level calibration on Modal with S3 custody.", "",
             "| Dataset | Input cells | Retained | Doublets flagged | Clusters | Seed ARI | Reference ARI | Status |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    for dataset, metrics in summaries.items():
        reference = f"{metrics['reference_ari']:.3f}" if "reference_ari" in metrics else "Not available"
        lines.append(f"| {dataset} | {metrics['input_cells']} | {metrics['retained_cells']} | {metrics['doublets_flagged']} | "
                     f"{metrics['clusters']} | {metrics['seed_stability_ari']:.3f} | {reference} | {metrics['calibration_status']} |")
        gates = "".join(f"<li>{escape(key)}: {'pass' if value else 'NEEDS REVIEW'}</li>" for key, value in metrics["gates"].items())
        breast_review = ""
        if metrics.get("qc_profile") == "human_breast_tumor":
            blockers = "".join(f"<li>{escape(reason)}</li>" for reason in metrics["readiness_blockers"])
            breast_review = f'''<h3>Breast cohort review</h3><p>Production ready: no. Coarse author-label balanced agreement:
                {metrics['coarse_reference_balanced_accuracy']:.3f}; unknown labels: {metrics['unknown_label_fraction']:.1%}.
                Published labels are a same-dataset comparison. Epithelial labels do not establish malignancy.</p>
                <ul>{blockers}</ul><img alt="Breast QC review signals" src="{dataset}/breast_qc_review.png">
                <img alt="Loss by published compartment" src="{dataset}/compartment_retention.png">
                <p><a href="{dataset}/compartment_retention.csv">Compartment losses</a> ·
                <a href="{dataset}/qc_sensitivity.csv">Threshold sensitivity</a> ·
                <a href="{dataset}/reference_compartment_overlap.csv">Coarse label overlap</a></p>'''
            if metrics.get("miqc_challenger"):
                challenger = metrics["miqc_challenger"]
                breast_review += f'''<h3>Joint mitochondrial/complexity challenger</h3>
                    <p>miQC: {escape(challenger['status'])}. Active decisions are unchanged.
                    Seed agreement: {challenger.get('seed_decision_agreement', 'no call')}.</p>
                    <p><a href="{dataset}/miqc/assessment.json">Fit and stability assessment</a></p>'''
                if challenger.get("seed_decision_agreement") is not None:
                    breast_review += f'<img alt="miQC diagnostic filtering" src="{dataset}/miqc/filtering-42.png">'
            readiness_lines.extend(["", f"### {dataset}: breast QC readiness", "",
                          f"Coarse author-label balanced agreement {metrics['coarse_reference_balanced_accuracy']:.3f}; production ready: no.",
                          "", *[f"- {reason}" for reason in metrics["readiness_blockers"]]])
        sections.append(f'''<section><h2>{escape(dataset)}</h2><p>{metrics['retained_cells']:,} / {metrics['input_cells']:,} barcodes retained;
            {metrics['doublets_flagged']:,} scDblFinder doublets; {metrics['clusters']} clusters.
            Seed stability ARI {metrics['seed_stability_ari']:.3f}; tutorial reference ARI {reference}.</p>
            <div class="plots"><a href="{dataset}/umap_leiden.png"><img alt="Leiden clusters" src="{dataset}/umap_leiden.png"></a>
            <a href="{dataset}/umap_coarse_label_hint.png"><img alt="Provisional marker labels" src="{dataset}/umap_coarse_label_hint.png"></a></div>
            <img class="qc" alt="Observed QC distributions and selected thresholds" src="{dataset}/qc_thresholds.png">
            <details><summary>Calibration checks: {metrics['calibration_status']}</summary><ul>{gates}</ul></details>
            <p><a href="{dataset}/calibration.json">Metrics</a> · <a href="{dataset}/all_cells_qc.csv">All barcode decisions</a> ·
            <a href="{dataset}/markers.csv">Markers</a> · <a href="{dataset}/analysis.h5ad">AnnData</a></p>{breast_review}</section>''')
    limits = "Ambient RNA is unassessed because empty-droplet matrices were not provided. Doublet precision/recall is unvalidated. " \
             "PBMC3k tutorial labels are a same-dataset comparison, not independent truth. Labels are provisional marker hints. " \
             "Captures/sample proxies are analyzed separately; published breast labels are evaluation only. No donor-level differential expression, malignant-cell validation, or clinical claims."
    lines.extend(readiness_lines)
    lines.extend(["", "## Interpretation boundaries", "", limits, "", "Use artifact_index.json and run_manifest.json for immutable custody.", ""])
    (output / "review.md").write_text("\n".join(lines))
    (output / "review.html").write_text('''<!doctype html><html lang="en"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Diana single-cell calibration</title>
        <style>body{font:16px/1.5 system-ui,sans-serif;color:#182a39;background:#f6f8fa;margin:0 auto;padding:28px;max-width:1100px}
        h1,h2{line-height:1.2}section{background:white;border:1px solid #dbe3ea;border-radius:10px;padding:20px;margin:20px 0}
        .plots{display:grid;grid-template-columns:1fr 1fr;gap:12px}img{width:100%;height:auto}.qc{margin:16px 0}
        a{color:#17547c}details{padding:12px;background:#eef3f7}header p{max-width:850px}
        @media(max-width:650px){body{padding:14px}.plots{grid-template-columns:1fr}section{padding:12px}}</style>
        <header><h1>Single-cell calibration</h1><p>Public single-cell post-count analysis · Modal CPU workers · S3 artifacts</p>
        <p>''' + escape(limits) + "</p></header>" + "".join(sections) + '''<footer><p>
        <a href="input_manifest.json">Inputs and frozen criteria</a> · <a href="python_packages.json">Python versions</a> ·
        <a href="conda-explicit.txt">R/Conda lock</a> · <a href="artifact_index.json">Artifact hashes</a></p></footer></html>''')
