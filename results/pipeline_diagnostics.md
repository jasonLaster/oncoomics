# Pipeline Diagnostics

## Summary

- Trace rows reviewed: 47
- Trace statuses: {'FAILED': 27, 'COMPLETED': 11, 'ABORTED': 7, 'CACHED': 2}
- Split checkpoint acceleration: 56h 6m 41s baseline failure window to 11m 18s through fetch/reference, about 297.94x faster (through fetch plus reference-index checkpoints).

## Best Completed Stages

| Stage | Status | Duration | Realtime | Source |
| --- | --- | --- | --- | --- |
| phase3_fetch | COMPLETED | 9m 19s | 8m 9s | trace.tsv |
| reference_index | COMPLETED | 1m 59s | 10s | trace.tsv |

## Failure Signals

- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-phase3fix-full-20260610T033453Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-split-full-20260610T155813Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-split-full-20260610T160301Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-split-metafast-full-20260610T162733Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-split-stagefix-full-20260610T174106Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3opt_align32_20260612T192540Z/nextflow.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3opt_align64_20260612T200806Z/nextflow.log`: spot_or_host_interruption
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3opt_align64_20260612T200806Z/review.log`: spot_or_host_interruption
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3opt_full_20260612T184427Z/nextflow.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3split-stagefix-resume-20260611T094700Z.log`: duplicate_alignment_resume
- `/Users/jasonlaster/src/projects/diana-omics/logs/test_launch_trace/nextflow.log`: manual_or_superseded_termination, missing_cloudwatch_stream
- `/Users/jasonlaster/src/projects/diana-omics/nextflow-out/aws/phase3-wgs-full-20260608-145948-heartbeat/launcher.out`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/nextflow-out/aws/phase3-wgs-full-20260608-145948-heartbeat/nextflow.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/nextflow-out/aws/phase3-wgs-full-20260608-152125-heartbeat-spot/launcher.out`: spot_or_host_interruption, aws_credentials_metadata
- `/Users/jasonlaster/src/projects/diana-omics/nextflow-out/aws/phase3-wgs-full-20260608-152125-heartbeat-spot/nextflow.log`: spot_or_host_interruption, aws_credentials_metadata

## Recommendations

- Persist cloud-generated alignment BAM/BAI outputs in the asset cache so launcher interruptions do not force alignment rework.
- Keep AWS smoke tests split and short; credential or host failures should burn minutes, not multi-hour monolithic runs.
- The next optimization target is alignment checkpoint durability; fetch and reference-index already complete quickly.

## Current Result Statuses

- `results/phase3_wgs_smoke/fastq_summary.json`: passed
- `results/phase3_wgs_smoke/phase3_wgs_summary.json`: passed
- `results/full_wes_benchmark/full_wes_benchmark_summary.json`: passed
- `results/orthogonal_validation/public_examples_summary.json`: failed
