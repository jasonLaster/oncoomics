# Pipeline Diagnostics

## Summary

- Trace rows reviewed: 27
- Trace statuses: {'FAILED': 18, 'COMPLETED': 5, 'ABORTED': 2, 'CACHED': 2}
- Split checkpoint acceleration: 2h 34m 54s baseline failure window to 14m 16s through fetch/reference, about 10.86x faster (through fetch plus reference-index checkpoints).

## Best Completed Stages

| Stage | Status | Duration | Realtime | Source |
| --- | --- | --- | --- | --- |
| phase3_fetch | COMPLETED | 12m 8s | 9m 48s | phase3-wgs-split-granular-full-20260610T165947Z.trace.tsv |
| reference_index | COMPLETED | 2m 8s | 11s | phase3-wgs-split-stagefix-full-20260610T174106Z.trace.tsv |

## Failure Signals

- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-phase3fix-full-20260610T033453Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-split-full-20260610T155813Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-split-full-20260610T160301Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-split-metafast-full-20260610T162733Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3-wgs-split-stagefix-full-20260610T174106Z.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/logs/phase3split-stagefix-resume-20260611T094700Z.log`: duplicate_alignment_resume
- `/Users/jasonlaster/src/projects/diana-omics/nextflow-out/aws/phase3-wgs-full-20260608-145948-heartbeat/nextflow.log`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/nextflow-out/aws/phase3-wgs-full-20260608-152125-heartbeat-spot/nextflow.log`: spot_or_host_interruption, aws_credentials_metadata
- `/Users/jasonlaster/src/projects/diana-omics/nextflow-out/aws/phase3-wgs-full-20260608-145948-heartbeat/launcher.out`: manual_or_superseded_termination
- `/Users/jasonlaster/src/projects/diana-omics/nextflow-out/aws/phase3-wgs-full-20260608-152125-heartbeat-spot/launcher.out`: spot_or_host_interruption, aws_credentials_metadata
- `/Users/jasonlaster/src/projects/diana-omics/.nextflow.log.1`: duplicate_alignment_resume, report_overwrite, missing_cloudwatch_stream
- `/Users/jasonlaster/src/projects/diana-omics/.nextflow.log.2`: manual_or_superseded_termination, report_overwrite
- `/Users/jasonlaster/src/projects/diana-omics/.nextflow.log.4`: report_overwrite
- `/Users/jasonlaster/src/projects/diana-omics/.nextflow.log.6`: report_overwrite
- `/Users/jasonlaster/src/projects/diana-omics/.nextflow.log.8`: spot_or_host_interruption, manual_or_superseded_termination, report_overwrite

## Recommendations

- Persist cloud-generated alignment BAM/BAI outputs in the asset cache so launcher interruptions do not force alignment rework.
- Keep AWS smoke tests split and short; credential or host failures should burn minutes, not multi-hour monolithic runs.
- Enable Nextflow report/timeline overwrite or use unique report names for resume loops.
- The next optimization target is alignment checkpoint durability; fetch and reference-index already complete quickly.

## Current Result Statuses

- `results/phase3_wgs_smoke/fastq_summary.json`: passed
- `results/phase3_wgs_smoke/phase3_wgs_summary.json`: passed
- `results/full_wes_benchmark/full_wes_benchmark_summary.json`: passed
- `results/orthogonal_validation/public_examples_summary.json`: failed
