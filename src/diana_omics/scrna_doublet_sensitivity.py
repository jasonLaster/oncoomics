"""GEM-X expected-rate and rate-free challengers; no barcode exclusion."""

from __future__ import annotations

import subprocess
from pathlib import Path


def doublet_sensitivity(counts, directory: Path, seed: int = 42) -> dict:
    import numpy as np
    import pandas as pd
    from scipy.io import mmwrite

    from .scrna_io import write_json

    directory.mkdir()
    mmwrite(directory / "counts.mtx", counts.X.T)
    counts.obs_names.to_series().to_csv(directory / "barcodes.tsv", header=False, index=False)
    script = directory / "run.R"
    script.write_text("""args<-commandArgs(trailingOnly=TRUE)
suppressPackageStartupMessages({library(Matrix);library(SingleCellExperiment);library(scDblFinder)})
stopifnot(as.character(packageVersion("scDblFinder"))=="1.20.2")
d<-args[1];x<-as(readMM(file.path(d,"counts.mtx")),"CsparseMatrix")
barcodes<-readLines(file.path(d,"barcodes.tsv"));colnames(x)<-barcodes
for (policy in c("gemx_rate","rate_free")) {
 set.seed(as.integer(args[2]));sce<-SingleCellExperiment(list(counts=x))
 if (policy=="gemx_rate") sce<-scDblFinder(sce,dbr.per1k=0.004,BPPARAM=BiocParallel::SerialParam())
 else sce<-scDblFinder(sce,dbr.sd=1,BPPARAM=BiocParallel::SerialParam())
 write.csv(data.frame(barcode=barcodes,doublet_score=sce$scDblFinder.score,
   doublet_class=sce$scDblFinder.class),file.path(d,paste0(policy,".csv")),row.names=FALSE)
}
writeLines(capture.output(sessionInfo()),file.path(d,"r_session.txt"))
""")
    result = subprocess.run(["Rscript", str(script), str(directory), str(seed)], capture_output=True, text=True, timeout=1800)
    (directory / "r.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("scDblFinder sensitivity execution failed; inspect retained R log")
    calls = {}
    for policy in ("gemx_rate", "rate_free"):
        frame = pd.read_csv(directory / (policy + ".csv"), index_col="barcode")
        if not frame.index.is_unique or set(frame.index) != set(counts.obs_names):
            raise ValueError("Sensitivity calls must match every vendor barcode exactly once")
        frame = frame.loc[counts.obs_names]
        if not frame.doublet_class.isin(["singlet", "doublet"]).all() or not np.isfinite(frame.doublet_score).all():
            raise ValueError("Incomplete diagnostic doublet calls")
        calls[policy] = frame
        for column in frame:
            counts.obs["diagnostic_" + policy + "_" + column] = frame[column]
    summary = {
        "input_barcodes": counts.n_obs,
        "gemx_dbr_per1k": 0.004,
        "rate_free_dbr_sd": 1,
        "class_agreement": float(calls["gemx_rate"].doublet_class.eq(calls["rate_free"].doublet_class).mean()),
        "doublets": {policy: int(frame.doublet_class.eq("doublet").sum()) for policy, frame in calls.items()},
        "seed": seed,
        "filters_applied": False,
        "clinical_ready": False,
        "boundary": "Loading and complete-capture identity require review; rate sensitivity does not establish doublet accuracy.",
    }
    write_json(directory / "summary.json", summary)
    (directory / "counts.mtx").unlink()
    return summary
