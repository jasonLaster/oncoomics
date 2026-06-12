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
- `DIANA_OMICS_LOG_UPLOAD_URI`
- `DIANA_OMICS_TRACE_HEARTBEAT_SECONDS`
- `DIANA_OMICS_COMMAND_HEARTBEAT_SECONDS`
- `PHASE3_WGS_FETCH_CONCURRENCY`
- `PHASE3_WGS_ARIA2_SPLIT`
- `PHASE2F_THREADS`
- `PHASE2F_FORCE`
- `PHASE2F_BAM_SCAN_THREADS`
- `PHASE2F_FASTQ_VALIDATION_WORKERS`
- `PHASE2F_BAM_VALIDATION_WORKERS`
- `PHASE2F_REUSE_FASTQ_VALIDATION`
- `PHASE2F_REUSE_BAM_VALIDATION`
- `PHASE2F_MIN_TRUTH_DEPTH`
- `PHASE2F_MAX_TRUTH_VARIANTS`
- `PHASE3_WGS_THREADS`
- `PHASE3_WGS_GATK_THREADS`
- `PHASE3_WGS_PARALLEL_ALIGN`
- `PHASE3_WGS_READS`
- `PHASE3_WGS_CACHE_UPLOAD_WORKERS`
- `PHASE3_WGS_ALIGNMENT_CACHE_WORKERS`

Use force flags only when intentionally rebuilding expensive outputs.

Current full WGS fetch/run command pattern:

```sh
PHASE3_WGS_FETCH_CONCURRENCY=4 PHASE3_WGS_ARIA2_SPLIT=1 PYTHONPATH=src /usr/bin/python3 -m diana_omics fetch:phase3-wgs
PHASE3_WGS_THREADS=18 PYTHONPATH=src /usr/bin/python3 -m diana_omics validate:phase3-wgs
```

Keep `PHASE3_WGS_ARIA2_SPLIT=1` for acceptance data unless a segmented run has already been proven against the provider MD5s. A 16-segment ENA transfer reached the expected byte counts for the SEQC2/HCC1395 WGS FASTQs but failed both MD5 and gzip CRC validation, so full-source acceptance now favors checksum-correct single-stream downloads over maximum transfer speed.

Use `PYTHONPATH=src /usr/bin/python3 -m diana_omics diagnose:pipeline` after local or AWS experiments. It parses Nextflow traces, heartbeat logs, and result summaries into `results/pipeline_diagnostics.md`, including the best completed stage timings and known failure signatures.

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

On AWS, keep `phase3_asset_cache_uri` enabled for full-source public validation. Fetch jobs cache validated FASTQ derivatives, and alignment jobs cache cloud-generated public BAM/BAI outputs after BAM read-scope validation. That cache is for retry acceleration only; do not seed it from local raw/generated files.

Downstream reruns now avoid touching unrelated expensive work when inputs are current:

- Phase 2F FASTQ and BAM validation summaries are reused when the summaries are newer than their FASTQ/BAM/BAI/metrics inputs and BAMs still pass `samtools quickcheck`.
- Phase 2F BAM validation parses threaded `samtools flagstat` output for total, mapped, properly paired, and duplicate counts instead of launching separate whole-BAM `samtools view -c` scans for each counter.
- Phase 2F BRCA-interval and truth-position depth outputs are written to reusable TSVs, and generated BED files keep their timestamps when content is unchanged so depth reruns are not forced by identical metadata rewrites.
- BWA indexing runs only for reference or alignment stages, not downstream-only validation.
- CNV bin BED files keep their timestamp when the reference/bin content is unchanged, so cached `samtools bedcov` summaries can be reused.
- `bcftools stats`, SBS96 summaries, and BAM-derived SV evidence are skipped when their outputs are newer than their VCF/BAM/reference inputs.
- FASTQ/SRA cache publishes and BAM cache publishes use bounded workers so AWS Batch can use available network throughput without changing validation semantics.

## Logging and Spans

Treat logs as first-class outputs. Full-WES benchmark telemetry is written under `results/full_wes_benchmark/logs/telemetry/<run-id>/`:

- `otel_spans.jsonl` shows nested spans such as FASTQ validation, BAM preparation, BAM validation, depth, contamination, variant calling, and truth-overlap scoring.
- `events.jsonl` records cache reuse/miss decisions and command lifecycle events.
- `resource_samples.jsonl` records system load/disk state and command process-tree CPU/RSS samples.
- `heartbeat.json` is the latest in-run state with data-level progress such as validated FASTQ bytes, total alignments, covered truth variants, and truth-overlap counts.

Use `DIANA_OMICS_LOG_UPLOAD_URI=s3://bucket/prefix` for S3 sync after the run, or point it at a local directory for an artifact mirror. Upload failure is logged as `logs.upload_failed` and does not turn a successful benchmark into a failed benchmark.

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
