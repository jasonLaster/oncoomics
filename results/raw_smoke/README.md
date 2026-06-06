# Raw FASTQ Smoke Test

Status: **passed**.

Smoke pair: `seqc2_hcc1395_wes_minimal_smoke`

Source: ENA direct paired FASTQ files derived from SEQC2/HCC1395 SRA run metadata.

Reads streamed per FASTQ end: `1000`

What this validates:

1. Public raw-data source metadata resolves to direct paired FASTQ URLs.
2. Tumor and normal sample rows can be represented in a Diana-ready tumor-normal samplesheet shape.
3. R1/R2 files are stream-readable, have valid FASTQ structure, and preserve matching read IDs.
4. Tiny local FASTQ subsets are present under `data/raw/smoke/` for immediate parser/QC development.

What this does not validate yet:

1. Full-depth WES or WGS download.
2. Alignment to GRCh37/GRCh38.
3. BAM/CRAM generation.
4. Somatic variant calling.
5. scarHRD/CHORD/HRDetect/SBS3 or SV signature calling.

Next raw-readiness step:

Install or containerize a genomics stack, then run the minimal WES pair through alignment and somatic-caller input validation.
