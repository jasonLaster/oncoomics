
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
