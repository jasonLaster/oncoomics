# Wiki Source Summary

Source directory: `/Users/jasonlaster/src/projects/diana-tnbc/obsidian/wiki/omics`

The requested path `../diana-tnbc/wiki/omics` is not present from this project checkout. The active omics packet is under the Diana Obsidian vault at `../diana-tnbc/obsidian/wiki/omics`.

## Source Pages Read

- `index.md` defines the packet as operational omics work for report-level findings, raw-data reproduction, benchmarking, and partner questions.
- `findings-overview.md` frames HRD, biallelic BRCA/HRR loss, mutational signatures, Lehmann/TNBCtype, and PAM50 as biology-review findings, not standalone treatment orders.
- `derived-findings.md` narrows the fallback findings to HRD/biallelic BRCA/mutational signatures from tumor-normal DNA and Lehmann/TNBC RNA subtype from bulk RNA-seq.
- `analysis-workflows.md` recommends a locked sample manifest, auditable evidence tables, conservative HRD confidence labels, and reviewer-facing outputs.
- `validation-atlases.md` names TCGA-BRCA, UCSC Xena, cBioPortal, METABRIC, CPTAC Breast, breast WGS/ICGC, Hartwig, DepMap/CCLE, and Vanderbilt TNBCtype as benchmark sources.
- `partner-questions.md` keeps proprietary, wet-lab, liquid biopsy, vaccine, pathology, and functional-testing questions outside this internal fallback project.

## Practical Project Boundary

The first project should not try to be an all-omics platform. It should build an auditable HRD validation harness:

1. Causal HRR event: BRCA1/2 and related HRR alterations, with source and evidence strength.
2. Functional second hit: allele state, copy number, LOH/deletion, expression or methylation context if available.
3. Genome-wide scar/signature: copy-number scar, SBS3-like signal, indel/microhomology, structural-variant features, and HRD classifier output when inputs support it.
4. Confidence label: strong, suggestive, incomplete, discordant, or not assessable from available data.
5. Action boundary: biology/reviewer material unless clinician-owned validation changes the clinical status.

## Local Runtime Reality

- Bun is available locally.
- Python 3.9 is available locally.
- R is not installed locally at plan time, so R-native tools should be wrapped later through containers, Conda, or a dedicated R setup rather than assumed in the first verifier.

