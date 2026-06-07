# Phase 3 Parallel Compute Strategy

Phase 3 now has a local WGS-capable smoke lane and a clear path to full-depth WGS scaling.

## Local Smoke Defaults

The local machine reported 18 CPUs during the Phase 3 run. The smoke runner uses these defaults:

1. `PHASE3_WGS_THREADS=16`
2. `PHASE3_WGS_PARALLEL_ALIGN=1`
3. `PHASE3_WGS_GATK_THREADS=8`
4. `PHASE3_WGS_READS=500000`

That means tumor and matched-normal alignment run at the same time, each with 8 BWA/samtools threads. Mutect2 then uses 8 native PairHMM threads on bounded intervals.

Run:

```sh
bun run fetch:phase3-wgs
bun run smoke:phase3-wgs
```

Force a fresh run:

```sh
PHASE3_WGS_FORCE=1 bun run smoke:phase3-wgs
```

Use fewer CPUs on a busy workstation:

```sh
PHASE3_WGS_THREADS=8 PHASE3_WGS_GATK_THREADS=4 bun run smoke:phase3-wgs
```

Disable parallel tumor/normal alignment if memory or IO is constrained:

```sh
PHASE3_WGS_PARALLEL_ALIGN=0 PHASE3_WGS_THREADS=12 bun run smoke:phase3-wgs
```

## Full WGS Scaling

The full HiSeq X WGS pair is roughly 198 GB compressed FASTQ across tumor and normal. A full run should be treated as a production or cloud/HPC job, not a casual laptop extension of the smoke.

Recommended full-depth strategy:

1. Keep tumor and normal FASTQ download/validation independent and resumable.
2. Align tumor and normal as separate jobs.
3. Mark duplicates or CRAM-convert as separate downstream jobs.
4. Scatter small-variant calling by interval shards, then gather VCFs.
5. Run CNV segmentation on genome-wide bins or allele-specific tooling after BAM validation.
6. Run SV calling as its own lane, preferably with a pinned caller/container that emits VCF/BEDPE.
7. Build SBS/ID/DB matrices only after PASS-filter policy is settled.
8. Run CHORD/scarHRD/HRDetect-style feature handling only after SNV/indel, CNV, and SV inputs meet each tool's contract.

## Practical Job Shapes

Local smoke:

1. 16 CPU threads.
2. Less than 1 GB Phase 3 local WGS smoke data.
3. Real BAM/VCF/CNV/matrix/SV-evidence outputs.
4. Not full-depth interpretation.

Full WGS local workstation:

1. At least 16 to 32 CPU threads.
2. Hundreds of GB free for FASTQ, BAM/CRAM, temporary sort files, VCFs, CNV/SV outputs, and logs.
3. Run tumor/normal alignment separately if IO contention dominates.
4. Prefer CRAM output once reference policy is frozen.

Cloud/HPC:

1. One job per sample for alignment.
2. One job per sample for duplicate marking and QC.
3. One scatter array for Mutect2 intervals.
4. One scatter array or caller-native parallel mode for SV.
5. One gather/QC/reporting job.

## Phase 3 Boundary

The completed Phase 3 smoke proves the mechanics:

1. Representative WGS FASTQ access.
2. Full-reference WGS BAM contracts.
3. Tumor-normal Mutect2 VCF output.
4. Coverage-CNV bin output.
5. SBS96 matrix output.
6. BAM-derived SV evidence output.

It does not replace a full-depth WGS production run. Diana interpretation still needs Diana's raw data, final reference/resource policy, production CNV/SV/signature tooling, and reviewer sign-off.
