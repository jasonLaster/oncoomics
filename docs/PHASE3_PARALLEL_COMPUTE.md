# Parallel Compute Strategy

The workflow should use local CPU aggressively without hiding reproducibility or failure details.

## Current Local Pattern

Phase 3 WGS smoke records:

- available CPUs
- total threads
- per-sample threads
- GATK threads
- whether alignment ran in parallel

Latest smoke values:

- available CPUs: 18
- total threads: 16
- per-sample threads: 8
- GATK threads: 8
- parallel alignment: true

## Where Parallelism Helps

FASTQ validation:

- Validate tumor and normal files independently.
- Hash large files in separate workers when IO allows it.

Alignment:

- Run tumor and normal alignment concurrently.
- Give each sample a bounded thread count, for example 8 threads each on an 18 CPU machine.
- Avoid oversubscribing when samtools sort also uses threads.

Post-alignment QC:

- Run flagstat, stats, quickcheck, and depth summaries per BAM in parallel.

Somatic calling:

- Use native tool threads where available.
- Split large WGS calling by intervals only after reference, PoN, contamination, and merge behavior are locked down.

CNV/SV/signature:

- CNV bins can be computed by chromosome or interval shard.
- SV callers are often memory-heavy; prefer sample-level or interval-level parallelism after benchmarking.
- Signature summaries are cheap compared with alignment and calling.

## Environment Knobs

Existing commands use environment variables such as:

- `PHASE2F_THREADS`
- `PHASE2F_FORCE`
- `PHASE2F_MIN_TRUTH_DEPTH`
- `PHASE2F_MAX_TRUTH_VARIANTS`
- `PHASE3_WGS_THREADS`
- `PHASE3_WGS_READ_PAIRS`

Use force flags only when intentionally rebuilding expensive outputs.

## Full-Depth Recommendation

For full HG008, COLO829, or Diana WGS:

1. Download and checksum files first.
2. Align tumor and normal in parallel.
3. Mark duplicates per sample in parallel if memory allows.
4. Run BAM QC per sample in parallel.
5. Run Mutect2 by interval shards if full-genome runtime becomes limiting.
6. Merge and index VCFs deterministically.
7. Run CNV/SV/signature tools with tool-specific parallelism.
8. Record wall time, CPU count, thread counts, and tool versions in summary JSON.

## Bug Risks

- Too many threads can make jobs slower through IO contention.
- Parallel commands can obscure which sample failed unless logs are per sample.
- Interval sharding can create boundary artifacts.
- Merged VCF order can change if sorting is not explicit.
- Existing outputs can mask stale runs unless force flags and input checksums are tracked.

## Documentation Requirement

Every full-depth run should record:

- command
- input checksums
- reference ID
- thread counts
- tool versions
- elapsed time
- output paths
- pass/fail status
