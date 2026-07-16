# Ordered next steps for the follow-up agent

## 1. Verify and orient

1. Read `README.md`, `PUBLIC_DATA.md`, and `HANDOFF.md`.
2. List the public run with `aws s3 ls --recursive --no-sign-request`.
3. Confirm expected objects, bytes, and encryption against the public manifest.
4. Refresh the full-genome AWS Batch status; do not restart or terminate it
   unless the user explicitly changes the instruction.

## 2. Reconcile with the completed full-genome callset

When AWS job `26023088-83dc-4a2b-9038-0df3ba286d09` completes:

1. Copy its complete result prefix into a separate sibling directory.
2. Locate the production full-genome filtered somatic VCF.
3. Compare exact allele, FILTER, AD, DP, AF, TLOD, NLOD, strand support, and
   local haplotype for:
   - `chr17:43115780 C>T` (BRCA1 c.81-1G>A)
   - `chr13:32363286 C>T` (BRCA2 c.8084C>T; p.Ser2695Leu)
4. Record concordant, discordant, or not-callable status. Do not silently
   replace the early-look files.

## 3. Perform manual read-level review

Stage the BAMs and indexes anonymously using `INPUT_POINTERS.md`, or stream
them directly from the public S3 run:

1. Generate tumor and normal IGV snapshots with at least a 200 bp window around
   each locus.
2. Inspect mapping quality, base quality, forward/reverse balance, read-pair
   placement, soft clipping, nearby indels/repeats, overlapping mates,
   duplicate-family behavior, and positional bias.
3. Save snapshots and a short review table under a new `review/` directory.
4. Preserve the original BAMs and VCFs unchanged.

The existing metrics are compatible with real calls but modest in depth: each
has seven alternate tumor reads, balanced 4/3 by strand, and zero alternate
reads in the matched normal. Manual review is still required.

## 4. Resolve cross-assay identity

### BRCA1

1. Obtain the existing Altera report/source record from the approved Diana
   case evidence store.
2. Confirm exact transcript, HGVS, build, specimen, tumor fraction, and VAF.
3. Record whether the Altera and WGS events are exact matches.
4. Treat an exact match as orthogonal cross-assay support.

The current case summary says the hereditary panel was negative and
Altera confirmed somatic BRCA1 c.81-1G>A. Do not relabel it germline based on
ClinVar's germline pathogenicity aggregation.

### BRCA2

1. Search the existing Altera, UCSF500, Personalis, and other approved tumor
   reports for c.8084C>T / p.Ser2695Leu.
2. If absent from a sufficiently deep independent assay, keep the finding
   provisional; document assay coverage before treating absence as discordance.
3. Do not count it as an HRD driver on the current evidence.

## 5. Determine the allele-specific BRCA state

This is the most important missing HRD step.

1. Run a production allele-specific CNV/LOH workflow on the matched tumor and
   normal BAMs using the exact hg38 reference in this packet.
2. Estimate purity, ploidy, total copy number, minor copy number, and LOH at
   BRCA1 and BRCA2.
3. Check for focal deletion, copy-neutral LOH, homozygous deletion, or another
   damaging event affecting the remaining allele.
4. Phase a second event with the observed SNV when the data allow.
5. Report `biallelic_supported`, `monoallelic_only`, `indeterminate`, or
   `no_call` with explicit evidence. Do not derive this from the 5 Mb bins.

## 6. Review structural variation

1. Use the completed full-genome SV output, or run the locked production SV
   caller if the full job does not produce a suitable VCF/BEDPE.
2. Inspect BRCA1 and BRCA2 for exon-level/focal deletions, breakpoints,
   rearrangements, or promoter-disrupting events.
3. Integrate SV and allele-specific CNV evidence before making any second-hit
   statement.

## 7. Finish genome-wide HRD evidence only with production adapters

Once required inputs exist, run the production adapters for scarHRD, SBS3,
CHORD, and HRDetect according to their locked contracts and validation gates.
Until then, retain `no_call`; do not substitute the coverage-CNV proxy or a
single pathogenic BRCA event for a scalar HRD result.

## 8. Update the reviewer packet

Create a new, versioned follow-up packet rather than editing this handoff in
place. It should include:

- early-look/full-run concordance table
- IGV screenshots and manual review notes
- cross-assay BRCA1/BRCA2 concordance
- allele-specific CNV/LOH and purity/ploidy
- focal CNV/SV evidence
- adapter-specific HRD outputs and no-call reasons
- separate sample evidence, public database context, and clinical boundary

If a result could influence care, route it through a clinically validated
assay and molecular-pathology/oncology review. This research packet is not a
clinical report.
