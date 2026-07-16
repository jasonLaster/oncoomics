# Full early-look work summary and agent handoff

Public run root:

```text
s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/
```

The bucket is anonymously listable/readable. See `PUBLIC_DATA.md` for HTTPS
links and download commands.

## Outcome

The early-look run completed successfully without stopping, restarting, or
modifying the larger full-genome evidence job. It produced validated BAM QC,
matched-normal contamination estimates, a 5 Mb coverage-CNV proxy, and a
targeted somatic SNV/indel callset over BRCA1, BRCA2, and 13 additional core
HRR genes.

The packet remains exploratory research evidence:

- `status`: `partial_evidence`
- `overall_hrd_status`: `no_call`
- no scalar HRD result is authorized
- no biallelic BRCA conclusion is authorized
- scarHRD, SBS3, CHORD, and HRDetect remain `no_call`
- PASS is a caller-filter state, not pathogenicity or clinical classification

The generic `build:rosalind-hrd-packet` command was not used because its
supported sample sets are public validation sets and raw-intake readiness,
not this live Diana WGS run. This handoff follows the same packet boundaries
while preserving the actual Diana artifact tree unchanged.

## Run history

### Full-genome job

- Run ID: `diana-wgs-hrd-20260716T033101Z`
- AWS Batch job: `26023088-83dc-4a2b-9038-0df3ba286d09`
- Job name: `diana-wgs-hrd-evidence-v2-20260716T033101Z`
- Queue: `diana-omics-prod-use1-spot`
- Resources: 64 vCPU, 120,000 MiB
- Started: 2026-07-16 04:37:37 PDT
- State when this handoff was assembled: `RUNNING`
- Action taken: left running and untouched

Refresh this state before follow-up:

```bash
aws batch describe-jobs --region us-east-1 \
  --jobs 26023088-83dc-4a2b-9038-0df3ba286d09 \
  --query 'jobs[0].{status:status,statusReason:statusReason,startedAt:startedAt,stoppedAt:stoppedAt}'
```

### Early-look attempts

1. `b178575a-b5e6-44b8-8937-89b832418071` was the initial 16-vCPU serial job.
   It was intentionally terminated after the chromosome-scattered replacement
   was live. AWS records it as `FAILED` with the explicit superseded reason.
2. `28bd5f1c-e822-4dfd-876d-c817437b6d08` scattered pileups by chromosome,
   but the first interval expression would have scanned entire contigs. It was
   intentionally superseded by a corrected common-sites intersection job.
3. `a1aa4109-4b38-46a4-9b58-bfe6335b02d4` was the corrected job. It used
   `-L common-sites -L chromosome --interval-set-rule INTERSECTION`, 23
   standard contigs, 12 scatter workers, 32 vCPU, and 100,000 MiB. It started
   at 08:06:44 PDT, completed at 08:32:54 PDT, exited 0, and is `SUCCEEDED`.

The complete AWS records are [publicly available here](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/handoff/provenance/aws_batch_jobs.json).

## Inputs and provenance

### Validated BAMs

| Role | Object | Bytes | Validation |
| --- | --- | ---: | --- |
| Tumor | `tumor.markdup.bam` | 51,081,679,103 | gather passed; early-look `samtools quickcheck` passed |
| Normal | `normal.markdup.bam` | 55,978,126,326 | gather passed; early-look `samtools quickcheck` passed |

The validated pair and sidecars are available in the public result run under
`inputs/validated_bams/`. Exact public locations, sizes, ETags, and anonymous
staging commands are preserved in `INPUT_POINTERS.md`.

### Reference and caller resources

- UCSC hg38 analysis-set full reference, dictionary, BWA indexes, and FASTA
  index: public `inputs/reference/`
- GATK 4.6.2.0 jar, Broad hg38 1000 Genomes PoN, af-only gnomAD,
  common-biallelic sites, and indexes: public `inputs/caller_resources/`
- Ensembl GRCh38 release 116 GFF3 and checksum file: public
  `handoff/references/`

## Work performed

1. Confirmed the tumor and normal gather outputs and S3 object metadata.
2. Kept the full WGS job running without mutation.
3. Built a separate early-look worker and isolated S3 output prefix.
4. Ran matched tumor-normal GATK Mutect2 4.6.2.0 across 15 HRR gene spans
   padded by 100 bp.
5. Applied the run PoN, gnomAD germline resource, orientation-bias model,
   matched-normal contamination estimate, and FilterMutectCalls.
6. Computed tumor and normal pileups over common biallelic sites using 23
   contig-intersection shards, then ran CalculateContamination.
7. Computed normalized tumor/normal coverage over 5,000,000 bp bins using
   `samtools bedcov`.
8. Preserved flagstat, duplicate metrics, gather evidence, VCF statistics,
   pileup tables, orientation-model files, and per-contig CNV inputs.
9. Annotated the filtered VCF with `bcftools csq` and Ensembl release
   116. No sample variants were submitted to an external annotation API.
10. Queried public ClinVar pages only for the two BRCA entities after their
    exact coordinates/HGVS were established from the sample evidence.

## QC findings

### BAM QC

| Metric | Tumor | Normal |
| --- | ---: | ---: |
| Total reads | 1,176,920,018 | 1,318,466,785 |
| Mapped reads | 1,176,032,268 | 1,317,691,709 |
| Mapped fraction | 99.9246% | 99.9412% |
| Duplicate reads | 183,575,154 | 264,791,807 |
| Duplicate fraction | 15.5979% | 20.0833% |
| Properly paired reads | 1,140,476,018 | 1,295,579,572 |

Input validation, gather, and quickcheck all passed.

### Contamination

- Status: `passed`
- Tumor contamination: `0.0015779768215893645` (0.1578%)
- Standard error: `3.284984569516683E-5` (0.0033 percentage points)
- Tumor pileup sites: 7,590,882
- Normal pileup sites: 7,594,196
- Matched normal used: yes

The complete pileup tables are present; they account for most of the 0.78 GiB
early-look artifact set.

## Coverage-CNV findings

- Method: normalized tumor/normal `samtools bedcov`
- Bin size: 5,000,000 bp
- Bins: 619
- Median raw log2 tumor/normal: -0.1012
- Relative-gain bins: 45
- Relative-loss bins: 99
- State: `partial_evidence`

This is a broad coverage proxy only. It is not allele-specific CNV, cannot
establish BRCA1/BRCA2 LOH, does not provide purity/ploidy, and is not valid
scarHRD input.

## Variant findings

### Callset summary

- Caller: GATK Mutect2 4.6.2.0 matched tumor-normal
- Scope: exploratory somatic SNV/indel early look
- Target genes: BARD1, RAD50, NBN, MRE11, ATM, BRCA2, RAD51B, RAD51,
  PALB2, FANCA, RAD51D, BRCA1, RAD51C, BRIP1, CHEK2
- All filtered records: 484
- PASS records: 39
- BRCA1/BRCA2 PASS records: 8
- Germline calling: not run

The PASS CSV contains every passing record. Local Ensembl consequence review
identified two coding/splice-relevant records; the remaining PASS records were
predominantly intronic or noncoding.

### BRCA1 splice-acceptor call — highest priority

- GRCh38: `chr17:43115780 C>T`
- RefSeq: `NM_007294.4(BRCA1):c.81-1G>A`
- Consequence: splice acceptor across the canonical BRCA1 transcript and many
  other protein-coding transcripts
- Tumor AD/DP: 26 ref, 7 alt / 33; AF field 0.208
- Normal AD/DP: 50 ref, 0 alt / 50
- Tumor strand support: 4 forward, 3 reverse alt reads
- Median mapping quality: 60/60
- Median alt base quality: 20
- Median alt read position: 39 bp from the read end
- TLOD: 14.01
- NLOD: 12.34
- Filter: PASS

Case context: the existing sequencing summary records a negative
hereditary germline panel and an Altera-confirmed somatic BRCA1 c.81-1G>A
tumor finding. The WGS coordinate and HGVS match that prior finding, so this is
best treated as independent WGS support rather than a novel discovery.

ClinVar VCV000091668.48 classifies the variant as germline pathogenic with
criteria provided, multiple submitters, and no conflicts. ClinVar reports no
submitted somatic clinical-impact or oncogenicity classification. The germline
classification supports damage to BRCA1 function; it does not by itself make a
somatic treatment or HRD determination.

Source: <https://www.ncbi.nlm.nih.gov/clinvar/variation/91668/>

### BRCA2 missense call — provisional, lower priority

- GRCh38: `chr13:32363286 C>T`
- RefSeq: `NM_000059.4(BRCA2):c.8084C>T`
- Protein: `p.Ser2695Leu`
- Tumor AD/DP: 47 ref, 7 alt / 54; AF field 0.154
- Normal AD/DP: 67 ref, 0 alt / 67
- Tumor strand support: 4 forward, 3 reverse alt reads
- Median mapping quality: 60/60
- Median alt base quality: 20
- Median alt read position: 45 bp from the read end
- TLOD: 15.8
- NLOD: 15.65
- Filter: PASS

ClinVar VCV000052500.49 has conflicting germline classifications: one VUS and
six likely-benign submissions contribute to the aggregate. It has no submitted
somatic clinical-impact or oncogenicity classification. Do not count this as
an HRD-driving event without independent technical concordance and convincing
allelic/functional evidence.

Source: <https://www.ncbi.nlm.nih.gov/clinvar/variation/52500/>

## Interpretation boundary

The strongest current statement is:

> The WGS early look independently supports the previously reported somatic
> BRCA1 c.81-1G>A splice-acceptor event. Its HRD relevance remains unresolved
> until allele-specific BRCA1 state, purity/ploidy, focal CNV/SV context, and
> genome-wide HRD evidence are available. BRCA2 p.Ser2695Leu is a provisional
> lower-priority call and should not currently contribute to an HRD driver set.

Do not infer inherited risk from this somatic callset, do not call BRCA1 or
BRCA2 biallelic loss from the 5 Mb bins, and do not translate these exploratory
results into treatment guidance without a clinically validated report and
molecular-pathology review.

## Key public files

- [Machine-readable run summary](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/early_look_summary.json)
- [All 39 PASS records](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/variants/core_hrr_pass_variants.csv)
- [All 484 filtered records](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/variants/core_hrr_all_filtered_variants.csv)
- [Filtered callset](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/variants/core_hrr.mutect2.filtered.vcf.gz)
- [Ensembl-annotated callset](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/handoff/annotations/core_hrr.mutect2.filtered.ensembl116.vcf.gz)
- [All 619 CNV proxy bins](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/coverage_cnv/coverage_cnv_bins.csv)
- [Contamination estimate](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/contamination/contamination.table)
- [Complete tumor pileups](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/contamination/tumor.pileups.table)
- [Complete normal pileups](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/contamination/normal.pileups.table)
- [Consolidated BAM QC](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/artifacts/qc/bam_qc_summary.json)
- [Readable execution log](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/handoff/provenance/cloudwatch_early_look_log.tsv)
- [AWS job records](https://diana-omics-results-172630973301-us-east-1.s3.us-east-1.amazonaws.com/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z/handoff/provenance/aws_batch_jobs.json)

## Reproduction and inspection commands

Download only the small result files needed for inspection:

```bash
PUBLIC_RUN='s3://diana-omics-results-172630973301-us-east-1/runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/early-look/early-look-intersected-20260716T150517Z'
mkdir -p /tmp/diana-hrd-early-look/variants

aws s3 cp "$PUBLIC_RUN/artifacts/early_look_summary.json" \
  /tmp/diana-hrd-early-look/early_look_summary.json --no-sign-request
aws s3 cp "$PUBLIC_RUN/artifacts/variants/core_hrr.mutect2.filtered.vcf.gz" \
  /tmp/diana-hrd-early-look/variants/core_hrr.mutect2.filtered.vcf.gz --no-sign-request
aws s3 cp "$PUBLIC_RUN/artifacts/variants/core_hrr.mutect2.filtered.vcf.gz.tbi" \
  /tmp/diana-hrd-early-look/variants/core_hrr.mutect2.filtered.vcf.gz.tbi --no-sign-request

bcftools query -f '%CHROM\t%POS\t%REF\t%ALT\t%FILTER[\t%AD\t%AF\t%DP]\t%INFO/TLOD\t%INFO/NLOD\n' \
  -r chr17:43115780,chr13:32363286 \
  /tmp/diana-hrd-early-look/variants/core_hrr.mutect2.filtered.vcf.gz

jq . /tmp/diana-hrd-early-look/early_look_summary.json
```
