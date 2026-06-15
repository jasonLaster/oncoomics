# Scripts

Most workflows should use `PYTHONPATH=src /usr/bin/python3 -m diana_omics ...` rather than shell scripts.

Current shell utilities:

- `launch_phase3_aws_full.sh`: launch a full Phase 3 WGS AWS run with repo-specific defaults.
- `review_phase3_aws_run.sh`: inspect a Phase 3 AWS run directory and summarize logs, traces, and exits.
- `aws-silly-ec2`: legacy disposable EC2 smoke utility. It is not part of the omics validation path and is intentionally absent from the main docs.
