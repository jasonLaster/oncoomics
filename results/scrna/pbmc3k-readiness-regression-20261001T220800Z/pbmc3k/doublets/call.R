args <- commandArgs(trailingOnly=TRUE)
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
