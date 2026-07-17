# Scripts

Most workflows should use `PYTHONPATH=src /usr/bin/python3 -m diana_omics ...` rather than shell scripts.

Current shell utilities:

- `build_ai_review_bundle.py`: build a de-identified, hash-bound model review
  bundle from the frozen seven-method HRD report inventory without invoking a
  model.
- `build_public_results_index.py`: build the reviewed static S3 object index that
  powers `data.diana-tnbc.com`.
- `finalize_ai_review.py`: wrap a passed independent AI review in a schema-1
  HRD report manifest that can be privately frozen.
- `generate_blocked_hrd_crosscheck_reports.py`: render FACETS→scarHRD,
  Oncoanalyser→CHORD, and HRDetect no-call packets for routes that are not yet
  executable or clinically authorized.
- `hrd_report_inventory.py`: pin the canonical seven-method Diana WGS report
  inventory shared by deterministic, Rosalind, cross-check, and AI-review
  reporting.
- `launch_phase3_aws_full.sh`: launch a full Phase 3 WGS AWS run with repo-specific defaults.
- `publish_private_report.py`: freeze an allowlisted HRD report packet in the
  private versioned results bucket before reviewed public release.
- `prepare_ai_review_run.py`: build a seven-method de-identified AI review
  bundle and stage exact two-file input directories for reviewers A and B.
- `publish_public_results_index.py`: publish a freshly built reviewed object
  index to `public-index/objects.json` with SHA-256 and S3 metadata custody.
- `publish_reviewed_public_report.py`: publish an allowlisted private HRD report
  packet into the reviewed public Diana WGS alias tree.
- `review_phase3_aws_run.sh`: inspect a Phase 3 AWS run directory and summarize logs, traces, and exits.
- `stage_hrd_crosscheck_report.py`: compact an exact Sequenza→scarHRD or
  SigProfiler SBS3 route replay into a three-file method packet for review
  bundling and private freeze.
- `stage_deterministic_wgs_report.py`: validate terminal frozen Diana full-WGS
  worker artifacts and custody receipts into the five-file
  `deterministic_full_wgs` packet consumed by Rosalind, AI-review, and
  private/public publication steps.
- `stage_ai_review_inputs.py`: split a hash-bound AI review bundle into
  isolated two-file reviewer input directories.
- `validate_ai_review.py`: validate one isolated model review against its
  bundle, source manifests, pinned model, exact claims table, and no-promotion
  HRD authorization boundary without invoking a model.
- `aws-silly-ec2`: legacy disposable EC2 smoke utility. It is not part of the omics validation path and is intentionally absent from the main docs.
