"""Raw-droplet SoupX challenger. Correction is preserved for review, never auto-selected."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .scrna_intake import align_raw
from .scrna_io import write_json


def assess_ambient(filtered, raw, directory: Path, seed: int = 42) -> dict:
    import numpy as np
    import pandas as pd
    import scanpy as sc
    from scipy.io import mmread, mmwrite
    from scipy.sparse import csr_matrix

    directory.mkdir(parents=True, exist_ok=False)
    lineage = align_raw(filtered, raw)
    raw_gene_positions = {gene: position for position, gene in enumerate(raw.var.gene_ids)}
    raw = raw[:, [raw_gene_positions[gene] for gene in filtered.var.gene_ids]].copy()
    totals = np.asarray(raw.X.sum(axis=1)).ravel()
    empty = ~raw.obs_names.isin(filtered.obs_names) & (totals > 0) & (totals < 100)
    # Include filtered cells for SoupChannel's lineage checks. Other raw droplets remain in immutable source files.
    selected = empty | raw.obs_names.isin(filtered.obs_names)
    mmwrite(directory / "droplets.mtx", raw[selected].X.T)
    mmwrite(directory / "cells.mtx", filtered.X.T)
    pd.Series(raw.obs_names[selected]).to_csv(directory / "droplets.tsv", header=False, index=False)
    filtered.obs_names.to_series().to_csv(directory / "cells.tsv", header=False, index=False)
    filtered.var.gene_ids.to_csv(directory / "genes.tsv", header=False, index=False)
    # Preliminary clustering uses uncorrected expression and no clinical/author labels.
    initial = filtered.copy()
    if (np.asarray(initial.X.sum(axis=1)).ravel() == 0).any():
        raise ValueError("Filtered matrix contains zero-count cells; resolve vendor cell calling")
    sc.pp.normalize_total(initial, target_sum=10000)
    sc.pp.log1p(initial)
    sc.pp.highly_variable_genes(initial, n_top_genes=min(2000, initial.n_vars), flavor="seurat")
    latent = initial[:, initial.var.highly_variable].copy()
    if latent.n_vars < 3:
        raise ValueError("Insufficient variable genes for ambient preliminary clustering")
    sc.pp.scale(latent, zero_center=False, max_value=10)
    sc.pp.pca(latent, n_comps=min(30, latent.n_obs - 1, latent.n_vars - 1), svd_solver="arpack", random_state=seed)
    sc.pp.neighbors(latent, n_neighbors=min(15, latent.n_obs - 1), random_state=seed)
    sc.tl.leiden(latent, flavor="igraph", n_iterations=-1, directed=False, resolution=0.5, random_state=seed)
    pd.DataFrame({"barcode": latent.obs_names, "cluster": latent.obs.leiden.astype(str)}).to_csv(directory / "initial_clusters.csv", index=False)
    script = directory / "assess.R"
    script.write_text('''args <- commandArgs(trailingOnly=TRUE)
suppressPackageStartupMessages({library(Matrix); library(SoupX); library(jsonlite)})
set.seed(as.integer(args[2]))
dir <- args[1]
stopifnot(as.character(packageVersion("SoupX")) == "1.6.2")
writeLines(capture.output(sessionInfo()), file.path(dir, "r_session.txt"))
tod <- as(readMM(file.path(dir,"droplets.mtx")), "CsparseMatrix")
toc <- as(readMM(file.path(dir,"cells.mtx")), "CsparseMatrix")
rownames(tod) <- rownames(toc) <- readLines(file.path(dir,"genes.tsv"))
colnames(tod) <- readLines(file.path(dir,"droplets.tsv"))
colnames(toc) <- readLines(file.path(dir,"cells.tsv"))
clusters <- read.csv(file.path(dir,"initial_clusters.csv"), colClasses="character")
channel <- SoupChannel(tod, toc, soupRange=c(0,100), calcSoupProfile=TRUE)
channel <- setClusters(channel, setNames(clusters$cluster, clusters$barcode))
# Identification failure is a no-call. Missing packages/invalid input remain hard failures.
channel <- tryCatch(autoEstCont(channel, doPlot=FALSE, forceAccept=FALSE), error=function(e) {
  write_json(list(status="no_call", reason=conditionMessage(e)), file.path(dir,"fit.json"), auto_unbox=TRUE)
  NULL
})
if (!is.null(channel)) {
  corrected <- adjustCounts(channel, roundToInt=TRUE)
  writeMM(corrected, file.path(dir,"corrected.mtx"))
  write.csv(data.frame(barcode=rownames(channel$metaData), rho=channel$metaData$rho), file.path(dir,"contamination.csv"), row.names=FALSE)
  write_json(list(status="estimated", rho=unique(channel$metaData$rho)), file.path(dir,"fit.json"), auto_unbox=TRUE)
}
''')
    result = subprocess.run(["Rscript", str(script), str(directory), str(seed)], capture_output=True, text=True, timeout=900)
    (directory / "r.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("SoupX execution failed; inspect the private ambient/r.log")
    fit = json.loads((directory / "fit.json").read_text())
    report = {"method": "SoupX", "version": "1.6.2", "seed": seed, "lineage": lineage,
              "correction_applied_to_analysis": False, "evidence_level": "internal_qc",
              "policy": "Diagnostic challenger; no automatic selection or forceAccept; low-count non-cell droplets 1..99 UMIs"}
    if fit["status"] == "estimated":
        corrected = csr_matrix(mmread(directory / "corrected.mtx").T)
        if corrected.shape != filtered.shape or not np.isfinite(corrected.data).all() or (corrected.data < 0).any() or not np.equal(corrected.data, np.round(corrected.data)).all() or (corrected > filtered.X).nnz:
            raise ValueError("Invalid corrected counts: shape, finiteness, integer or monotonicity violation")
        contamination = pd.read_csv(directory / "contamination.csv", index_col="barcode")
        if not contamination.index.is_unique or set(contamination.index) != set(filtered.obs_names):
            raise ValueError("Ambient scores do not map one-to-one onto cells")
        rho = contamination.loc[filtered.obs_names, "rho"]
        if not np.isfinite(rho).all() or not rho.between(0, 1).all():
            raise ValueError("Invalid contamination fraction")
        filtered.layers["soupx_counts_candidate"] = corrected
        filtered.obs["soupx_rho"] = rho
        removed = np.asarray((filtered.X - corrected).sum(axis=1)).ravel()
        filtered.obs["soupx_umis_removed_candidate"] = removed
        report.update({"status": "estimated_review_required", "rho_min": float(rho.min()), "rho_max": float(rho.max()),
                       "candidate_removed_fraction": float(removed.sum() / filtered.X.sum()), "original_counts_preserved": True})
        (directory / "corrected.mtx").unlink()
    else:
        report.update({"status": "no_call", "reason": "Automatic contamination estimate was not identifiable; see private fit.json"})
    for name in ("droplets.mtx", "cells.mtx"):
        (directory / name).unlink()
    write_json(directory / "assessment.json", report)
    return report
