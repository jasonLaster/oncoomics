"""Pinned miQC challenger: diagnostic only, never a silent change to QC."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .scrna_io import write_json


def assess_miqc(obs, directory: Path, seed: int, cutoff: float = 0.75) -> dict:
    """Bridge only standard QC metrics to R; keep all cells and both seeded fits."""
    import numpy as np
    import pandas as pd

    if cutoff != 0.75:
        raise ValueError("Challenger cutoff is frozen at the published miQC default")
    bridge = directory / "miqc"
    bridge.mkdir()
    obs[["n_genes_by_counts", "pct_counts_mt"]].rename(columns={
        "n_genes_by_counts": "detected", "pct_counts_mt": "subsets_mito_percent",
    }).to_csv(bridge / "metrics.tsv", sep="\t", index_label="barcode")
    script = bridge / "assess.R"
    script.write_text(r'''
suppressPackageStartupMessages(library(SingleCellExperiment))
suppressPackageStartupMessages(library(miQC))
suppressPackageStartupMessages(library(flexmix))
args <- commandArgs(trailingOnly=TRUE)
d <- args[1]; seed <- as.integer(args[2]); cutoff <- as.numeric(args[3])
m <- read.delim(file.path(d, "metrics.tsv"), row.names=1, check.names=FALSE)
sce <- SingleCellExperiment(colData=S4Vectors::DataFrame(m))
colnames(sce) <- rownames(m)
for (s in c(seed, seed+1L)) {
    set.seed(s)
    outcome <- tryCatch({
        model <- mixtureModel(sce, model_type="linear")
        if (length(model@components) != 2 || !model@converged)
            stop("miQC did not converge to two components")
        intact <- filterCells(sce, model, posterior_cutoff=cutoff, verbose=FALSE)
        compromised <- which.max(parameters(model)[1, ])
        out <- data.frame(barcode=colnames(sce),
            prob_compromised=posterior(model)[, compromised],
            candidate_keep=colnames(sce) %in% colnames(intact))
        write.csv(out, file.path(d, paste0("seed-", s, ".csv")), row.names=FALSE)
        saveRDS(model, file.path(d, paste0("model-", s, ".rds")))
        png(file.path(d, paste0("filtering-", s, ".png")), width=1200, height=850, res=130)
        print(plotFiltering(sce, model, posterior_cutoff=cutoff)); dev.off()
        capture.output(parameters(model), file=file.path(d, paste0("parameters-", s, ".txt")))
        "fit_complete"
    }, error=function(e) paste0("not_assessable: ", conditionMessage(e)))
    writeLines(outcome, file.path(d, paste0("status-", s, ".txt")))
}
capture.output(sessionInfo(), file=file.path(d, "R_session.txt"))
''')
    result = subprocess.run(["Rscript", str(script), str(bridge), str(seed), str(cutoff)],
                            capture_output=True, text=True, timeout=300)
    (bridge / "execution.log").write_text(result.stdout + result.stderr)
    result.check_returncode()  # Missing runtime/package is an execution failure, never a successful assessment.
    statuses = [(bridge / f"status-{s}.txt").read_text().strip() for s in (seed, seed + 1)]
    report = {"method": "miQC", "role": "challenger_review_only", "posterior_cutoff": cutoff,
              "seeds": [seed, seed + 1], "fit_statuses": statuses, "changes_active_qc": False,
              "independent_quality_truth": "unavailable", "status": "not_assessable"}
    if all(s == "fit_complete" for s in statuses):
        fits = []
        for s in (seed, seed + 1):
            fit = pd.read_csv(bridge / f"seed-{s}.csv", index_col="barcode")
            if not fit.index.is_unique or set(fit.index) != set(obs.index):
                raise ValueError("miQC must return every barcode exactly once")
            fit = fit.loc[obs.index]
            if not np.isfinite(fit.prob_compromised).all() or not fit.prob_compromised.between(0, 1).all():
                raise ValueError("Invalid miQC probabilities")
            if not fit.candidate_keep.isin([True, False]).all():
                raise ValueError("Invalid miQC decisions")
            fits.append(fit)
        obs["miqc_prob_compromised"] = fits[0].prob_compromised
        obs["miqc_candidate_keep"] = fits[0].candidate_keep
        obs["miqc_alternate_candidate_keep"] = fits[1].candidate_keep
        agreement = float((fits[0].candidate_keep == fits[1].candidate_keep).mean())
        report.update({"status": "stable_challenger" if agreement >= 0.95 else "unstable_challenger",
                       "seed_decision_agreement": agreement,
                       "candidate_kept_cells": int(fits[0].candidate_keep.sum()),
                       "active_mt_discordant_cells": int((fits[0].candidate_keep != ~obs.fails_mt).sum())})
    else:
        # Explicit no-call; no probabilities or keep-all fallback for an unidentifiable model.
        obs["miqc_prob_compromised"] = np.nan
        obs["miqc_candidate_keep"] = pd.Series(pd.NA, index=obs.index, dtype="boolean")
        obs["miqc_alternate_candidate_keep"] = pd.Series(pd.NA, index=obs.index, dtype="boolean")
    write_json(bridge / "assessment.json", report)
    return report
