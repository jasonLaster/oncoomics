# Scripts

Most workflows should use `PYTHONPATH=src /usr/bin/python3 -m diana_omics ...` rather than shell scripts.

Current shell utilities:

- `build_ai_review_bundle.py`: build a de-identified, hash-bound model review
  bundle from the frozen seven-source HRD report inventory without invoking a
  model.
- `build_public_results_index.py`: build the reviewed static S3 object index
  from the ten passed reviewed-public report publication receipts that power
  `data.diana-tnbc.com`.
- `capture_batch_provenance.py`: capture a successful full-WGS Batch execution
  and verify the exact worker source before terminal artifact freezing.
- `capture_materializer_terminal.py`: capture a successful cross-check
  materializer Batch job and download its content-addressed receipt by the exact
  VersionId printed in the terminal CloudWatch payload.
- `capture_route_terminal.py`: capture a successful Sequenza→scarHRD or
  SigProfiler SBS3 Batch route and download its content-addressed publication
  receipt by exact S3 VersionId.
- `check_contract.py`: validate a finalized, alias-only HRD cross-check input
  contract before route submission.
- `download_materializer_staged_validation.py`: download the materializer's
  versioned `staged_input_validation.json` object for deterministic report
  staging.
- `download_exact_report_tree.py`: materialize a passed private cross-check
  report publication by exact S3 VersionId before compacting it for review.
- `finalize_ai_review.py`: wrap a passed independent AI review in a schema-1
  HRD report manifest that can be privately frozen.
- `finalize_input_contract.py`: bind final frozen VCF, VCF index, SBS96, and
  staged-input validation receipts into the HRD cross-check route input
  contract.
- `freeze_final_artifacts.py`: copy a successful deterministic artifact tree
  into versioned private storage with exact destination VersionIds.
- `freeze_stage_provenance.py`: freeze terminal WGS preflight/gather evidence
  from expiring work storage into the versioned private bucket.
- `generate_blocked_hrd_crosscheck_reports.py`: render FACETS→scarHRD,
  Oncoanalyser→CHORD, and HRDetect no-call packets for routes that are not yet
  executable or clinically authorized.
- `generate_comparative_hrd_synthesis.py`: generate the offline
  `comparative_hrd_synthesis` packet from the frozen seven-source report
  inventory and two independently validated AI-review outputs.
- `hrd_report_inventory.py`: pin the canonical seven-source and ten-publication
  Diana WGS report inventories shared by deterministic, Rosalind, cross-check,
  AI-review, comparative-synthesis, and reviewed-public index reporting.
- `launch_phase3_aws_full.sh`: legacy full Phase 3 WGS AWS wrapper with an
  explicit interlock for pre-fast-path CPU workflows.
- `materialize_frozen_artifacts.py`: download a passed final-artifact private
  freeze by exact S3 VersionId into a local tree for deterministic reporting.
- `materialize_crosscheck_inputs.py`: rewrite exact frozen deterministic
  VCF/SBS96/reference inputs into alias-only cross-check artifacts inside the
  private results bucket.
- `publish_private_report.py`: freeze an allowlisted HRD report packet in the
  private versioned results bucket before reviewed public release.
- `publish_input_contract.py`: publish a finalized HRD cross-check input
  contract as a create-only, content-addressed, exact-VersionId private object.
- `prepare_ai_review_run.py`: build a seven-source de-identified AI review
  bundle and stage exact two-file input directories for reviewers A and B.
- `publish_public_results_index.py`: publish a freshly built reviewed object
  index to `public-index/objects.json` with SHA-256 and S3 metadata custody.
- `publish_reviewed_public_report.py`: publish an allowlisted private HRD report
  packet into the reviewed public Diana WGS alias tree.
- `render_ai_synthesis_runbook.py`: render the post-freeze AI review,
  validation, comparative-synthesis, and private-publication handoff from
  seven current source private-publication receipts.
- `render_materializer_job_definition.py`: render a reviewed, frozen-script
  AWS Batch job definition payload for the next cross-check materializer
  revision without uploading, registering, or submitting anything.
- `render_source_report_freeze_runbook.py`: render the private-freeze commands
  for the seven canonical source HRD report packets plus the exact-receipt AI
  handoff command.
- `render_reviewed_publication_runbook.py`: render the ten-method reviewed
  public-publication handoff plus the public-index rebuild and publish tail.
- `render_materializer_capture_command.py`: render the exact terminal-capture
  command from a bound cross-check materializer request/response pair.
- `render_post_success_runbook.py`: render the first post-success handoff from
  a successful WGS Batch job through deterministic, Rosalind, and cross-check
  packet staging.
- `write_ai_model_catalog_receipt.py`: materialize the pinned independent
  AI-review model catalog receipt used by bundle preparation, review
  validation, and AI report finalization.
- `review_phase3_aws_run.sh`: inspect a Phase 3 AWS run directory and summarize logs, traces, and exits.
- `stage_hrd_crosscheck_report.py`: compact an exact Sequenza→scarHRD or
  SigProfiler SBS3 route replay into a three-file method packet for review
  bundling and private freeze.
- `stage_deterministic_wgs_report.py`: validate terminal frozen Diana full-WGS
  worker artifacts and custody receipts into the six-file
  `deterministic_full_wgs` packet consumed by Rosalind, AI-review, and
  private/public publication steps.
- `stage_ai_review_inputs.py`: split a hash-bound AI review bundle into
  isolated two-file reviewer input directories.
- `submit_materializer_v4.py`: validate final freeze, reference, registration,
  image, queue, and empty-destination custody before the one-shot ARM
  cross-check materializer submission.
- `aws/submit_route.py`: validate a published input contract, exact x86 route
  revision, image, queue, and empty output prefix before one guarded HRD
  cross-check route submission.
- `validate_ai_review.py`: validate one isolated model review against its
  bundle, source manifests, pinned model, exact claims table, and no-promotion
  HRD authorization boundary without invoking a model.
- `aws-silly-ec2`: legacy disposable EC2 smoke utility. It is not part of the omics validation path and is intentionally absent from the main docs.
