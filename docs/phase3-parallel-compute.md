# Parallel Compute Strategy

The workflow should use local CPU aggressively without hiding reproducibility or failure details.

## Current Local Pattern

Phase 3 WGS validation records:

- available CPUs
- total threads
- per-sample threads
- GATK threads
- whether alignment ran in parallel

Latest full-run values are written to `results/phase3_wgs_smoke/phase3_wgs_summary.json`:

- available CPUs
- total threads
- per-sample threads
- GATK threads
- parallel alignment
- read-pair mode

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

- `PYTHON_BIN`
- `PHASE3_WGS_FETCH_CONCURRENCY`
- `PHASE3_WGS_ARIA2_SPLIT`
- `PHASE2F_THREADS`
- `PHASE2F_FORCE`
- `PHASE2F_MIN_TRUTH_DEPTH`
- `PHASE2F_MAX_TRUTH_VARIANTS`
- `PHASE3_WGS_THREADS`
- `PHASE3_WGS_GATK_THREADS`
- `PHASE3_WGS_PARALLEL_ALIGN`
- `PHASE3_WGS_READS`

Use force flags only when intentionally rebuilding expensive outputs.

Current full WGS fetch/run command pattern:

```sh
PHASE3_WGS_FETCH_CONCURRENCY=4 PHASE3_WGS_ARIA2_SPLIT=1 bun run fetch:phase3-wgs
PHASE3_WGS_THREADS=18 bun run validate:phase3-wgs
```

Keep `PHASE3_WGS_ARIA2_SPLIT=1` for acceptance data unless a segmented run has already been proven against the provider MD5s. A 16-segment ENA transfer reached the expected byte counts for the SEQC2/HCC1395 WGS FASTQs but failed both MD5 and gzip CRC validation, so full-source acceptance now favors checksum-correct single-stream downloads over maximum transfer speed.

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
- Existing outputs can mask stale runs unless force flags, input checksums, indexed BAM alignment counts, and output timestamps are checked.
- Bounded developer BAMs are much smaller than full WGS BAMs. Full-source validation must reject them even if `samtools quickcheck` passes.

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
