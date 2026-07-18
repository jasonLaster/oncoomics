#!/usr/bin/env nextflow

nextflow.enable.dsl = 2

params.workflow = params.workflow ?: 'quick'
params.phase3_reads = params.phase3_reads ?: null
params.phase3_fetch_cpus = params.phase3_fetch_cpus ?: 4
params.phase3_fetch_memory = params.phase3_fetch_memory ?: '16 GB'
params.phase3_ref_cpus = params.phase3_ref_cpus ?: 16
params.phase3_ref_memory = params.phase3_ref_memory ?: '32 GB'
params.phase3_align_cpus = params.phase3_align_cpus ?: 16
params.phase3_align_memory = params.phase3_align_memory ?: '32 GB'
params.phase3_downstream_cpus = params.phase3_downstream_cpus ?: 16
params.phase3_downstream_memory = params.phase3_downstream_memory ?: '32 GB'
params.phase3_wgs_cpus = params.phase3_wgs_cpus ?: 16
params.phase3_wgs_memory = params.phase3_wgs_memory ?: '32 GB'
params.phase3_fetch_concurrency = params.phase3_fetch_concurrency ?: 2
params.phase3_aria2_split = params.phase3_aria2_split ?: 1
params.phase3_source_mode = params.phase3_source_mode ?: 'ena_fastq'
params.phase3_sra_aws_bucket = params.phase3_sra_aws_bucket ?: 'sra-pub-run-odp'
params.phase3_s3_range_concurrency = params.phase3_s3_range_concurrency ?: 8
params.phase3_s3_range_bytes = params.phase3_s3_range_bytes ?: 268435456
params.phase3_s3_range_retries = params.phase3_s3_range_retries ?: 4
params.phase3_include_wes = params.phase3_include_wes ?: false
params.phase3_prereq_mode = params.phase3_prereq_mode ?: 'minimal'
params.phase3_sra_run_concurrency = params.phase3_sra_run_concurrency ?: 1
params.phase3_sra_command_retries = params.phase3_sra_command_retries ?: 2
params.phase3_fastq_stats_mode = params.phase3_fastq_stats_mode ?: 'seqkit'
params.phase3_cache_upload_workers = params.containsKey('phase3_cache_upload_workers') ? params.phase3_cache_upload_workers : 4
params.phase3_alignment_cache_workers = params.containsKey('phase3_alignment_cache_workers') ? params.phase3_alignment_cache_workers : 2
params.phase3_aligner = params.containsKey('phase3_aligner') ? params.phase3_aligner : 'bwa'
params.phase3_bwa_threads = params.containsKey('phase3_bwa_threads') ? params.phase3_bwa_threads : 0
params.phase3_sort_threads = params.containsKey('phase3_sort_threads') ? params.phase3_sort_threads : 0
params.phase3_align_input_mode = params.containsKey('phase3_align_input_mode') ? params.phase3_align_input_mode : 'local_fastq'
params.phase3_align_profile_mode = params.containsKey('phase3_align_profile_mode') ? params.phase3_align_profile_mode : 'pipe'
params.phase3_scatter_output_mode = params.containsKey('phase3_scatter_output_mode') ? params.phase3_scatter_output_mode : 'merged_bam'
params.phase3_shard_input_mode = params.containsKey('phase3_shard_input_mode') ? params.phase3_shard_input_mode : 'fastq_cache'
params.phase3_force = params.containsKey('phase3_force') ? params.phase3_force : false
params.phase3_force_shard_alignment = params.containsKey('phase3_force_shard_alignment') ? params.phase3_force_shard_alignment : false
params.phase3_scatter_role = params.containsKey('phase3_scatter_role') ? params.phase3_scatter_role : 'tumor'
params.phase3_shard_count = params.containsKey('phase3_shard_count') ? params.phase3_shard_count : 8
params.phase3_bam_validation_mode = params.containsKey('phase3_bam_validation_mode') ? params.phase3_bam_validation_mode : 'full'
params.phase3_coverage_cnv_mode = params.containsKey('phase3_coverage_cnv_mode') ? params.phase3_coverage_cnv_mode : 'full'
params.phase3_allow_metadata_cnv_timing = params.containsKey('phase3_allow_metadata_cnv_timing') ? params.phase3_allow_metadata_cnv_timing : false
params.phase3_fast_gpu_smoke_cpus = params.containsKey('phase3_fast_gpu_smoke_cpus') ? params.phase3_fast_gpu_smoke_cpus : 192
params.phase3_fast_gpu_smoke_memory = params.containsKey('phase3_fast_gpu_smoke_memory') ? params.phase3_fast_gpu_smoke_memory : '1900 GB'
params.phase3_fast_gpu_smoke_expected_gpus = params.containsKey('phase3_fast_gpu_smoke_expected_gpus') ? params.phase3_fast_gpu_smoke_expected_gpus : 8
params.phase3_fast_gpu_smoke_gpu_name = params.containsKey('phase3_fast_gpu_smoke_gpu_name') ? params.phase3_fast_gpu_smoke_gpu_name : 'H200'
params.phase3_fast_private_freeze_receipt = params.phase3_fast_private_freeze_receipt ?: null
params.phase3_fast_private_sha256_receipt = params.phase3_fast_private_sha256_receipt ?: null
params.phase3_fast_reference_freeze_receipt = params.phase3_fast_reference_freeze_receipt ?: null
params.phase3_fast_reference_sha256_receipt = params.phase3_fast_reference_sha256_receipt ?: null
params.phase3_fast_bam_validation_receipt = params.phase3_fast_bam_validation_receipt ?: null
params.phase3_fast_contig_compatibility_receipt = params.phase3_fast_contig_compatibility_receipt ?: null
params.phase3_fast_caller_resource_receipt = params.phase3_fast_caller_resource_receipt ?: null
params.phase3_fast_parameter_sha256 = params.phase3_fast_parameter_sha256 ?: null
params.phase3_fast_parabricks_container_digest = params.phase3_fast_parabricks_container_digest ?: (
    params.parabricks_container?.toString()?.contains('@') ? params.parabricks_container.toString().split('@', 2)[1] : null
)
params.phase3_fast_parabricks_version = params.phase3_fast_parabricks_version ?: null
params.phase3_fast_sequenza_female = params.phase3_fast_sequenza_female ?: null
params.phase3_fast_cache_prefix = params.phase3_fast_cache_prefix ?: null
params.phase3_fast_cache_kms_key_arn = params.phase3_fast_cache_kms_key_arn ?: null
params.phase3_fast_cache_region = params.phase3_fast_cache_region ?: 'us-east-2'
params.phase3_fast_replication_mode = params.phase3_fast_replication_mode ?: 'dry_run'
params.phase3_fast_replication_part_size_bytes = params.phase3_fast_replication_part_size_bytes ?: 536870912
params.phase3_fast_staging_root = params.phase3_fast_staging_root ?: '/scratch/diana/phase3_wgs_fast'
params.phase3_fast_parabricks_cpus = params.phase3_fast_parabricks_cpus ?: 192
params.phase3_fast_parabricks_memory = params.phase3_fast_parabricks_memory ?: '1900 GB'
params.phase3_fast_parabricks_num_gpus = params.phase3_fast_parabricks_num_gpus ?: 8
params.phase3_fast_parabricks_output_root = params.phase3_fast_parabricks_output_root ?: '/scratch/diana/phase3_wgs_fast/parabricks_mutect'
params.phase3_fast_bam_qc_output_root = params.phase3_fast_bam_qc_output_root ?: '/scratch/diana/phase3_wgs_fast/bam_qc'
params.phase3_fast_bam_qc_threads = params.phase3_fast_bam_qc_threads ?: 8
params.phase3_fast_cnv_evidence_output_root = params.phase3_fast_cnv_evidence_output_root ?: '/scratch/diana/phase3_wgs_fast/cnv_evidence'
params.phase3_fast_cnv_evidence_bin_size = params.phase3_fast_cnv_evidence_bin_size ?: 5000000
params.phase3_fast_cnv_evidence_bedcov_workers = params.phase3_fast_cnv_evidence_bedcov_workers ?: 4
params.phase3_fast_sv_evidence_output_root = params.phase3_fast_sv_evidence_output_root ?: '/scratch/diana/phase3_wgs_fast/sv_evidence'
params.phase3_fast_sv_evidence_threads = params.phase3_fast_sv_evidence_threads ?: 8
params.phase3_fast_filter_mutect_output_root = params.phase3_fast_filter_mutect_output_root ?: '/scratch/diana/phase3_wgs_fast/filter_mutect'
params.phase3_fast_small_variant_mode = params.phase3_fast_small_variant_mode ?: 'plan'
params.phase3_fast_gatk_version = params.phase3_fast_gatk_version ?: '4.6.2.0'
params.phase3_fast_source_commit = params.phase3_fast_source_commit ?: ''
params.phase3_fast_run_id = params.phase3_fast_run_id ?: 'diana-wgs-hrd-20260716T033101Z'
params.phase3_fast_generated_at = params.phase3_fast_generated_at ?: '2026-07-16T03:31:01+00:00'
params.phase3_fast_subject_alias = params.phase3_fast_subject_alias ?: 'subject01'
params.phase3_fast_pair_id = params.phase3_fast_pair_id ?: 'subject01_tumor_normal'
params.phase3_fast_tumor_sample_id = params.phase3_fast_tumor_sample_id ?: 'subject01_tumor'
params.phase3_fast_normal_sample_id = params.phase3_fast_normal_sample_id ?: 'subject01_normal'
params.phase3_fast_reference_id = params.phase3_fast_reference_id ?: 'ucsc_hg38_analysis_set_full'
params.phase3_fast_forbidden_tokens_json = params.phase3_fast_forbidden_tokens_json ?: null
params.phase3_asset_cache_uri = params.phase3_asset_cache_uri ?: null
params.phase3_asset_cache_mode = params.phase3_asset_cache_mode ?: 'readwrite'
params.phase3_delete_sra_after_conversion = params.phase3_delete_sra_after_conversion ?: false
params.sra_benchmark_runs = params.sra_benchmark_runs ?: 'SRR7890824,SRR7890827'
params.sra_benchmark_bytes = params.sra_benchmark_bytes ?: 1073741824
params.sra_benchmark_parts = params.sra_benchmark_parts ?: 1
params.sra_benchmark_strategy = params.sra_benchmark_strategy ?: 'aws_s3api_range'
params.sra_benchmark_matrix = params.sra_benchmark_matrix ?: null
params.allow_full_wgs = params.allow_full_wgs ?: false
params.repo_dir = params.repo_dir ?: projectDir.toString()
params.outdir = params.outdir ?: "${projectDir}/nextflow-out"
params.python_bin = params.python_bin ?: '/usr/bin/python3'

process QUICK {
    tag 'quick'
    cpus 4
    memory '16 GB'
    time '12h'
    publishDir "${params.outdir}/quick", mode: 'copy', overwrite: true

    output:
    path 'workspace/manifests', optional: true
    path 'workspace/results', optional: true

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process quick --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process quick --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process FULL_WES {
    tag 'full_wes'
    cpus 8
    memory '32 GB'
    time '48h'
    publishDir "${params.outdir}/full_wes", mode: 'copy', overwrite: true

    output:
    path 'workspace/manifests', optional: true
    path 'workspace/results', optional: true

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process full_wes --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process full_wes --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process PHASE3_FETCH {
    tag "phase3_fetch_${params.phase3_reads ?: '500000'}_${params.phase3_source_mode}_c${params.phase3_fetch_concurrency}_s${params.phase3_aria2_split}"
    cpus { params.phase3_fetch_cpus as int }
    memory { params.phase3_fetch_memory }
    time '48h'
    publishDir "${params.outdir}/phase3_fetch", mode: 'copy', overwrite: true

    output:
    path 'workspace/manifests', optional: true
    path 'workspace/results', optional: true

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_fetch --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_fetch --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process PHASE3_FETCH_WORKSPACE {
    tag "phase3_fetch_workspace_${params.phase3_reads ?: '500000'}_${params.phase3_source_mode}_c${params.phase3_fetch_concurrency}_s${params.phase3_aria2_split}"
    cpus { params.phase3_fetch_cpus as int }
    memory { params.phase3_fetch_memory }
    time '48h'

    output:
    path 'workspace'

    script:
    """
    set -euo pipefail
	    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_fetch_workspace --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-align-input-mode "${params.phase3_align_input_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}" --phase3-include-wes "${params.phase3_include_wes}" --phase3-prereq-mode "${params.phase3_prereq_mode}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_fetch_workspace --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process PHASE3_REFERENCE_INDEX {
    tag "phase3_reference_index_${params.phase3_reads ?: '500000'}"
    cpus { params.phase3_ref_cpus as int }
    memory { params.phase3_ref_memory }
    time '8h'

    input:
    path previous_workspace, stageAs: 'previous_workspace'

    output:
    path 'workspace'

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_reference_index --previous-workspace "${previous_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-aligner "${params.phase3_aligner}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_reference_index --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process PHASE3_REFERENCE_INDEX_SOURCE {
    tag "phase3_reference_index_source_${params.phase3_reads ?: '500000'}_${params.phase3_source_mode}_${params.phase3_aligner}"
    cpus { params.phase3_ref_cpus as int }
    memory { params.phase3_ref_memory }
    time '8h'

    output:
    path 'workspace'

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_reference_index --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-align-input-mode "${params.phase3_align_input_mode}" --phase3-aligner "${params.phase3_aligner}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}" --phase3-include-wes "${params.phase3_include_wes}" --phase3-prereq-mode "${params.phase3_prereq_mode}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_reference_index --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process PHASE3_ALIGN_SAMPLE {
    tag "phase3_align_${role}_${params.phase3_reads ?: '500000'}_${params.phase3_align_input_mode}_${params.phase3_align_profile_mode}_${params.phase3_aligner}"
    cpus { params.phase3_align_cpus as int }
    memory { params.phase3_align_memory }
    time '48h'

    input:
    tuple val(role), path(previous_workspace, stageAs: 'previous_workspace')

    output:
    tuple val(role), path('workspace')

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_align_sample --previous-workspace "${previous_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --role "${role}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-aligner "${params.phase3_aligner}" --phase3-bwa-threads "${params.phase3_bwa_threads}" --phase3-sort-threads "${params.phase3_sort_threads}" --phase3-align-input-mode "${params.phase3_align_input_mode}" --phase3-align-profile-mode "${params.phase3_align_profile_mode}" --phase3-force "${params.phase3_force}" --phase3-bam-validation-mode "${params.phase3_bam_validation_mode}" --phase3-coverage-cnv-mode "${params.phase3_coverage_cnv_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_align_sample --stub --workspace workspace --python-bin "${params.python_bin}" --role "${role}"
    """
}

process PHASE3_PREPARE_FASTQ_SHARDS {
    tag "phase3_prepare_shards_${role}_${params.phase3_shard_count}way_${params.phase3_reads ?: '500000'}"
    cpus { params.phase3_fetch_cpus as int }
    memory { params.phase3_fetch_memory }
    time '24h'

    input:
    tuple val(role), path(previous_workspace, stageAs: 'previous_workspace')

    output:
    tuple val(role), path('workspace')

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_prepare_fastq_shards --previous-workspace "${previous_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --role "${role}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-aligner "${params.phase3_aligner}" --phase3-bwa-threads "${params.phase3_bwa_threads}" --phase3-sort-threads "${params.phase3_sort_threads}" --phase3-align-input-mode "${params.phase3_align_input_mode}" --phase3-align-profile-mode "${params.phase3_align_profile_mode}" --phase3-scatter-output-mode "${params.phase3_scatter_output_mode}" --phase3-shard-input-mode "${params.phase3_shard_input_mode}" --phase3-force "${params.phase3_force}" --phase3-force-shard-alignment "${params.phase3_force_shard_alignment}" --phase3-shard-count "${params.phase3_shard_count}" --phase3-bam-validation-mode "${params.phase3_bam_validation_mode}" --phase3-coverage-cnv-mode "${params.phase3_coverage_cnv_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_prepare_fastq_shards --stub --workspace workspace --python-bin "${params.python_bin}" --role "${role}" --phase3-shard-count "${params.phase3_shard_count}"
    """
}

process PHASE3_ALIGN_SHARD {
    tag "phase3_align_${role}_shard${shard_index}_${params.phase3_shard_count}way_${params.phase3_aligner}"
    cpus { params.phase3_align_cpus as int }
    memory { params.phase3_align_memory }
    time '24h'

    input:
    tuple val(role), val(shard_index), path(previous_workspace, stageAs: 'previous_workspace')

    output:
    tuple val(role), val(shard_index), path('workspace')

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_align_shard --previous-workspace "${previous_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --role "${role}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-aligner "${params.phase3_aligner}" --phase3-bwa-threads "${params.phase3_bwa_threads}" --phase3-sort-threads "${params.phase3_sort_threads}" --phase3-align-input-mode "${params.phase3_align_input_mode}" --phase3-align-profile-mode "${params.phase3_align_profile_mode}" --phase3-scatter-output-mode "${params.phase3_scatter_output_mode}" --phase3-shard-input-mode "${params.phase3_shard_input_mode}" --phase3-force "${params.phase3_force}" --phase3-force-shard-alignment "${params.phase3_force_shard_alignment}" --phase3-shard-count "${params.phase3_shard_count}" --phase3-shard-index "${shard_index}" --phase3-bam-validation-mode "${params.phase3_bam_validation_mode}" --phase3-coverage-cnv-mode "${params.phase3_coverage_cnv_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_align_shard --stub --workspace workspace --python-bin "${params.python_bin}" --role "${role}" --phase3-shard-count "${params.phase3_shard_count}" --phase3-shard-index "${shard_index}"
    """
}

process PHASE3_GATHER_SHARDS {
    tag "phase3_gather_${role}_${params.phase3_shard_count}way"
    cpus { params.phase3_downstream_cpus as int }
    memory { params.phase3_downstream_memory }
    time '24h'
    publishDir "${params.outdir}/phase3_wgs_scatter", mode: 'copy', overwrite: true

    input:
    tuple val(role), path(previous_workspace, stageAs: 'previous_workspace')
    path shard_workspaces, stageAs: 'shard_workspaces/shard??/*'

    output:
    path 'workspace/manifests', optional: true
    path 'workspace/results', optional: true

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_gather_shards --previous-workspace "${previous_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --role "${role}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-aligner "${params.phase3_aligner}" --phase3-bwa-threads "${params.phase3_bwa_threads}" --phase3-sort-threads "${params.phase3_sort_threads}" --phase3-align-input-mode "${params.phase3_align_input_mode}" --phase3-align-profile-mode "${params.phase3_align_profile_mode}" --phase3-scatter-output-mode "${params.phase3_scatter_output_mode}" --phase3-shard-input-mode "${params.phase3_shard_input_mode}" --phase3-force "${params.phase3_force}" --phase3-force-shard-alignment "${params.phase3_force_shard_alignment}" --phase3-shard-count "${params.phase3_shard_count}" --phase3-bam-validation-mode "${params.phase3_bam_validation_mode}" --phase3-coverage-cnv-mode "${params.phase3_coverage_cnv_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_gather_shards --stub --workspace workspace --python-bin "${params.python_bin}" --role "${role}" --phase3-shard-count "${params.phase3_shard_count}"
    """
}

process PHASE3_GATHER_SHARD_MANIFEST {
    tag "phase3_gather_manifest_${role}_${params.phase3_shard_count}way"
    cpus { params.phase3_downstream_cpus as int }
    memory { params.phase3_downstream_memory }
    time '24h'
    publishDir "${params.outdir}/phase3_wgs_scatter", mode: 'copy', overwrite: true

    input:
    tuple val(role), path(src_dir, stageAs: 'gather_inputs/src'), path(samplesheet, stageAs: 'gather_inputs/phase3_wgs_smoke_samplesheet.csv'), path(asset_summary, stageAs: 'gather_inputs/asset_summary.json'), path(shards_dir, stageAs: 'gather_inputs/shards')
    val completed_shards

    output:
    path 'workspace/manifests', optional: true
    path 'workspace/results', optional: true

    script:
    """
    set -euo pipefail
    mkdir -p workspace/src workspace/manifests workspace/results/phase3_wgs_smoke/shards
    cp -a gather_inputs/src/. workspace/src/
    cp gather_inputs/phase3_wgs_smoke_samplesheet.csv workspace/manifests/phase3_wgs_smoke_samplesheet.csv
    cp gather_inputs/asset_summary.json workspace/results/phase3_wgs_smoke/asset_summary.json
    cp -a gather_inputs/shards/. workspace/results/phase3_wgs_smoke/shards/
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_gather_shards --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --role "${role}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-aligner "${params.phase3_aligner}" --phase3-bwa-threads "${params.phase3_bwa_threads}" --phase3-sort-threads "${params.phase3_sort_threads}" --phase3-align-input-mode "${params.phase3_align_input_mode}" --phase3-align-profile-mode "${params.phase3_align_profile_mode}" --phase3-scatter-output-mode "${params.phase3_scatter_output_mode}" --phase3-shard-input-mode "${params.phase3_shard_input_mode}" --phase3-force "${params.phase3_force}" --phase3-force-shard-alignment "${params.phase3_force_shard_alignment}" --phase3-shard-count "${params.phase3_shard_count}" --phase3-bam-validation-mode "${params.phase3_bam_validation_mode}" --phase3-coverage-cnv-mode "${params.phase3_coverage_cnv_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_gather_shards --stub --workspace workspace --python-bin "${params.python_bin}" --role "${role}" --phase3-shard-count "${params.phase3_shard_count}"
    """
}

process PHASE3_DOWNSTREAM {
    tag "phase3_downstream_${params.phase3_reads ?: '500000'}"
    cpus { params.phase3_downstream_cpus as int }
    memory { params.phase3_downstream_memory }
    time '48h'
    publishDir "${params.outdir}/phase3_wgs", mode: 'copy', overwrite: true

    input:
    tuple val(tumor_role), path(tumor_workspace, stageAs: 'tumor_workspace')
    tuple val(normal_role), path(normal_workspace, stageAs: 'normal_workspace')

    output:
    path 'workspace/manifests', optional: true
    path 'workspace/results', optional: true

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_downstream --tumor-role "${tumor_role}" --normal-role "${normal_role}" --tumor-workspace "${tumor_workspace}" --normal-workspace "${normal_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-bam-validation-mode "${params.phase3_bam_validation_mode}" --phase3-coverage-cnv-mode "${params.phase3_coverage_cnv_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-include-wes "${params.phase3_include_wes}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_downstream --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process PHASE3_SRA_BENCHMARK {
    tag "phase3_sra_benchmark_${params.sra_benchmark_strategy}_${params.sra_benchmark_bytes}_p${params.sra_benchmark_parts}_c${params.phase3_fetch_concurrency}"
    cpus { params.phase3_fetch_cpus as int }
    memory { params.phase3_fetch_memory }
    time '4h'
    publishDir "${params.outdir}/phase3_sra_benchmark", mode: 'copy', overwrite: true

    output:
    path 'workspace/results/phase3_wgs_smoke/sra_benchmark.*'

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_sra_benchmark --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --sra-benchmark-runs "${params.sra_benchmark_runs}" --sra-benchmark-bytes "${params.sra_benchmark_bytes}" --sra-benchmark-parts "${params.sra_benchmark_parts}" --sra-benchmark-strategy "${params.sra_benchmark_strategy}" --sra-benchmark-matrix "${params.sra_benchmark_matrix ?: ''}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_sra_benchmark --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process KNOWN_ANSWER_PUBLIC_FINDINGS {
    tag 'known_answer_public_findings'
    cpus 2
    memory '8 GB'
    time '4h'
    publishDir "${params.outdir}/known_answer_public_findings", mode: 'copy', overwrite: true

    output:
    path 'workspace/results/clinicalization/known_answer_public_finding_*'
    path 'workspace/results/clinicalization/known_answer_runs', optional: true
    path 'workspace/results/clinicalization/clinicalization_readiness_rollup.*'

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process known_answer_public_findings --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process known_answer_public_findings --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process KNOWN_ANSWER_BOUNDED_NON_DRY {
    tag 'known_answer_bounded_non_dry'
    cpus 2
    memory '8 GB'
    time '4h'
    publishDir "${params.outdir}/known_answer_bounded_non_dry", mode: 'copy', overwrite: true

    output:
    path 'workspace/results/clinicalization/known_answer_bounded_non_dry_*'
    path 'workspace/results/clinicalization/known_answer_public_finding_*'
    path 'workspace/results/clinicalization/known_answer_runs', optional: true
    path 'workspace/results/clinicalization/clinicalization_readiness_rollup.*'

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process known_answer_bounded_non_dry --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process known_answer_bounded_non_dry --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process KNOWN_ANSWER_EXPANDED_COHORT {
    tag 'known_answer_expanded_cohort'
    cpus 2
    memory '8 GB'
    time '4h'
    publishDir "${params.outdir}/known_answer_expanded_cohort", mode: 'copy', overwrite: true

    output:
    path 'workspace/results/clinicalization/known_answer_expanded_cohort_*'
    path 'workspace/results/clinicalization/known_answer_public_finding_*'
    path 'workspace/results/clinicalization/known_answer_runs/expanded_cohort', optional: true
    path 'workspace/results/clinicalization/clinicalization_readiness_rollup.*'

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process known_answer_expanded_cohort --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process known_answer_expanded_cohort --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process PHASE3_WGS {
    tag "phase3_wgs_${params.phase3_reads ?: '500000'}"
    cpus { params.phase3_wgs_cpus as int }
    memory { params.phase3_wgs_memory }
    time '72h'
    publishDir "${params.outdir}/phase3_wgs", mode: 'copy', overwrite: true

    output:
    path 'workspace/manifests', optional: true
    path 'workspace/results', optional: true

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_wgs --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-aligner "${params.phase3_aligner}" --phase3-bwa-threads "${params.phase3_bwa_threads}" --phase3-sort-threads "${params.phase3_sort_threads}" --phase3-bam-validation-mode "${params.phase3_bam_validation_mode}" --phase3-coverage-cnv-mode "${params.phase3_coverage_cnv_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}" --phase3-include-wes "${params.phase3_include_wes}" --phase3-prereq-mode "${params.phase3_prereq_mode}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_wgs --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process FAST_INPUT_MANIFEST {
    tag "fast_input_manifest_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/input_manifest", mode: 'copy', overwrite: true

    input:
    tuple path(private_freeze_receipt), path(private_sha256_receipt), path(reference_freeze_receipt), path(reference_sha256_receipt), path(bam_validation_receipt), path(contig_compatibility_receipt), path(caller_resource_receipt)

    output:
    path 'workspace/manifests/phase3_wgs_fast/input_manifest.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_PRIVATE_FREEZE_RECEIPT="\$PWD/${private_freeze_receipt}"
    export PHASE3_WGS_FAST_PRIVATE_SHA256_RECEIPT="\$PWD/${private_sha256_receipt}"
    export PHASE3_WGS_FAST_REFERENCE_FREEZE_RECEIPT="\$PWD/${reference_freeze_receipt}"
    export PHASE3_WGS_FAST_REFERENCE_SHA256_RECEIPT="\$PWD/${reference_sha256_receipt}"
    export PHASE3_WGS_FAST_BAM_VALIDATION_RECEIPT="\$PWD/${bam_validation_receipt}"
    export PHASE3_WGS_FAST_CONTIG_COMPATIBILITY_RECEIPT="\$PWD/${contig_compatibility_receipt}"
    export PHASE3_WGS_FAST_CALLER_RESOURCE_RECEIPT="\$PWD/${caller_resource_receipt}"
    export PHASE3_WGS_FAST_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/input_manifest.json"
    export PHASE3_WGS_FAST_PARAMETER_SHA256="${params.phase3_fast_parameter_sha256}"
    export PHASE3_WGS_FAST_PARABRICKS_CONTAINER="${params.parabricks_container}"
    export PHASE3_WGS_FAST_PARABRICKS_CONTAINER_DIGEST="${params.phase3_fast_parabricks_container_digest}"
    export PHASE3_WGS_FAST_PARABRICKS_VERSION="${params.phase3_fast_parabricks_version}"
    export PHASE3_WGS_FAST_SEQUENZA_FEMALE="${params.phase3_fast_sequenza_female}"
    export PHASE3_WGS_FAST_GATK_VERSION="${params.phase3_fast_gatk_version}"
    export PHASE3_WGS_FAST_SOURCE_COMMIT="${params.phase3_fast_source_commit}"
    export PHASE3_WGS_FAST_RUN_ID="${params.phase3_fast_run_id}"
    export PHASE3_WGS_FAST_SUBJECT_ALIAS="${params.phase3_fast_subject_alias}"
    export PHASE3_WGS_FAST_PAIR_ID="${params.phase3_fast_pair_id}"
    export PHASE3_WGS_FAST_TUMOR_SAMPLE_ID="${params.phase3_fast_tumor_sample_id}"
    export PHASE3_WGS_FAST_NORMAL_SAMPLE_ID="${params.phase3_fast_normal_sample_id}"
    export PHASE3_WGS_FAST_REFERENCE_ID="${params.phase3_fast_reference_id}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-input-manifest
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/input_manifest.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_input_manifest",
      "status": "stubbed",
      "workflow": {
        "name": "phase3_wgs_fast"
      },
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_GPU_SMOKE {
    tag "fast_gpu_smoke_${params.phase3_fast_gpu_smoke_expected_gpus}x_${params.phase3_fast_gpu_smoke_gpu_name}"
    label 'gpu_parabricks'
    cpus { params.phase3_fast_gpu_smoke_cpus as int }
    memory { params.phase3_fast_gpu_smoke_memory }
    time '30m'
    publishDir "${params.outdir}/phase3_wgs_fast/gpu_smoke", mode: 'copy', overwrite: true

    output:
    path 'workspace/results/phase3_wgs_fast_gpu_smoke'

    script:
    """
    set -euo pipefail
    mkdir -p workspace/results/phase3_wgs_fast_gpu_smoke

    nvidia-smi --query-gpu=index,name,uuid --format=csv,noheader \\
      | tee workspace/results/phase3_wgs_fast_gpu_smoke/nvidia-smi-gpus.csv

    gpu_count="\$(wc -l < workspace/results/phase3_wgs_fast_gpu_smoke/nvidia-smi-gpus.csv | tr -d '[:space:]')"
    expected_gpus="${params.phase3_fast_gpu_smoke_expected_gpus}"
    required_name="${params.phase3_fast_gpu_smoke_gpu_name}"

    if [[ "\${gpu_count}" != "\${expected_gpus}" ]]; then
      echo "Expected \${expected_gpus} GPUs, saw \${gpu_count}" >&2
      exit 42
    fi

    if [[ -n "\${required_name}" ]]; then
      awk -F, -v needle="\${required_name}" '
        index(\$2, needle) == 0 { bad = 1 }
        END { exit bad }
      ' workspace/results/phase3_wgs_fast_gpu_smoke/nvidia-smi-gpus.csv
    fi

    pbrun version > workspace/results/phase3_wgs_fast_gpu_smoke/parabricks-version.txt 2>&1
    test -s workspace/results/phase3_wgs_fast_gpu_smoke/parabricks-version.txt

    cat > workspace/results/phase3_wgs_fast_gpu_smoke/gpu_smoke.json <<JSON
    {
      "schema": "phase3_wgs_fast_gpu_smoke.v1",
      "status": "passed",
      "awsRegion": "${params.aws_region}",
      "awsGpuQueue": "${params.aws_gpu_queue}",
      "parabricksContainer": "${params.parabricks_container}",
      "expectedGpuCount": \${expected_gpus},
      "observedGpuCount": \${gpu_count},
      "requiredGpuName": "\${required_name}",
      "nvidiaSmiCsv": "nvidia-smi-gpus.csv",
      "parabricksVersionCommand": "pbrun version",
      "parabricksVersionTxt": "parabricks-version.txt"
    }
    JSON
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/results/phase3_wgs_fast_gpu_smoke
    cat > workspace/results/phase3_wgs_fast_gpu_smoke/nvidia-smi-gpus.csv <<CSV
    0, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000000
    1, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000001
    2, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000002
    3, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000003
    4, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000004
    5, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000005
    6, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000006
    7, NVIDIA H200, GPU-00000000-0000-0000-0000-000000000007
    CSV
    cat > workspace/results/phase3_wgs_fast_gpu_smoke/parabricks-version.txt <<TXT
    Parabricks v4.5.1-1
    TXT
    cat > workspace/results/phase3_wgs_fast_gpu_smoke/gpu_smoke.json <<JSON
    {
      "schema": "phase3_wgs_fast_gpu_smoke.v1",
      "status": "stubbed",
      "awsRegion": "${params.aws_region}",
      "awsGpuQueue": "${params.aws_gpu_queue}",
      "parabricksContainer": "${params.parabricks_container}",
      "expectedGpuCount": 8,
      "observedGpuCount": 8,
      "requiredGpuName": "H200",
      "nvidiaSmiCsv": "nvidia-smi-gpus.csv",
      "parabricksVersionCommand": "pbrun version",
      "parabricksVersionTxt": "parabricks-version.txt"
    }
    JSON
    """
}

process ALL_PUBLIC {
    tag "all_public_phase3_${params.phase3_reads ?: '500000'}"
    cpus 16
    memory '64 GB'
    time '96h'
    publishDir "${params.outdir}/all_public", mode: 'copy', overwrite: true

    output:
    path 'workspace/manifests', optional: true
    path 'workspace/results', optional: true

    script:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process all_public --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-aligner "${params.phase3_aligner}" --phase3-bwa-threads "${params.phase3_bwa_threads}" --phase3-sort-threads "${params.phase3_sort_threads}" --phase3-bam-validation-mode "${params.phase3_bam_validation_mode}" --phase3-coverage-cnv-mode "${params.phase3_coverage_cnv_mode}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process all_public --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

workflow PHASE3_WGS_SPLIT {
    PHASE3_FETCH_WORKSPACE()
    PHASE3_REFERENCE_INDEX(PHASE3_FETCH_WORKSPACE.out)

    align_inputs = Channel
        .of('tumor', 'normal')
        .combine(PHASE3_REFERENCE_INDEX.out)

    PHASE3_ALIGN_SAMPLE(align_inputs)

    tumor_workspace = PHASE3_ALIGN_SAMPLE.out.filter { role, workspace -> role == 'tumor' }
    normal_workspace = PHASE3_ALIGN_SAMPLE.out.filter { role, workspace -> role == 'normal' }
    PHASE3_DOWNSTREAM(tumor_workspace, normal_workspace)
}

workflow PHASE3_WGS_ALIGN_ONLY {
    PHASE3_REFERENCE_INDEX_SOURCE()

    align_inputs = Channel
        .of('tumor', 'normal')
        .combine(PHASE3_REFERENCE_INDEX_SOURCE.out)

    PHASE3_ALIGN_SAMPLE(align_inputs)
}

workflow PHASE3_WGS_ALIGN_SCATTER {
    PHASE3_REFERENCE_INDEX_SOURCE()

    shard_role = params.phase3_scatter_role.toString()
    prepare_input = Channel
        .of(shard_role)
        .combine(PHASE3_REFERENCE_INDEX_SOURCE.out)

    PHASE3_PREPARE_FASTQ_SHARDS(prepare_input)

    shard_inputs = Channel
        .fromList((0..<(params.phase3_shard_count as int)).toList())
        .combine(PHASE3_PREPARE_FASTQ_SHARDS.out)
        .map { shard_index, role, workspace -> tuple(role, shard_index, workspace) }

    PHASE3_ALIGN_SHARD(shard_inputs)

    completed_shards = PHASE3_ALIGN_SHARD.out.map { role, shard_index, workspace -> shard_index }.collect()
    if (params.phase3_scatter_output_mode.toString().replace('-', '_') == 'shard_manifest') {
        gather_manifest_input = PHASE3_PREPARE_FASTQ_SHARDS.out.map { role, workspace ->
            tuple(
                role,
                file("${workspace}/src"),
                file("${workspace}/manifests/phase3_wgs_smoke_samplesheet.csv"),
                file("${workspace}/results/phase3_wgs_smoke/asset_summary.json"),
                file("${workspace}/results/phase3_wgs_smoke/shards")
            )
        }
        PHASE3_GATHER_SHARD_MANIFEST(gather_manifest_input, completed_shards)
    } else {
        gather_input = PHASE3_PREPARE_FASTQ_SHARDS.out
        shard_workspaces = PHASE3_ALIGN_SHARD.out.map { role, shard_index, workspace -> workspace }.collect()
        PHASE3_GATHER_SHARDS(gather_input, shard_workspaces)
    }
}

process FAST_REPLICATION_PLAN {
    tag "fast_replication_plan_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/replication_plan", mode: 'copy', overwrite: true

    input:
    path input_manifest

    output:
    path 'workspace/manifests/phase3_wgs_fast/replication_plan.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_INPUT_MANIFEST="\$PWD/${input_manifest}"
    export PHASE3_WGS_FAST_REPLICATION_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/replication_plan.json"
    export PHASE3_WGS_FAST_CACHE_PREFIX="${params.phase3_fast_cache_prefix}"
    export PHASE3_WGS_FAST_CACHE_KMS_KEY_ARN="${params.phase3_fast_cache_kms_key_arn}"
    export PHASE3_WGS_FAST_CACHE_REGION="${params.phase3_fast_cache_region}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-replication-plan
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/replication_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_replication_plan",
      "status": "stubbed",
      "copy_plan": [],
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_REPLICATE_INPUTS {
    tag "fast_replicate_inputs_${params.phase3_fast_replication_mode}_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/replication_receipt", mode: 'copy', overwrite: true

    input:
    path replication_plan

    output:
    path 'workspace/manifests/phase3_wgs_fast/replication_receipt.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_REPLICATION_PLAN="\$PWD/${replication_plan}"
    export PHASE3_WGS_FAST_REPLICATION_RECEIPT_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/replication_receipt.json"
    export PHASE3_WGS_FAST_REPLICATION_MODE="${params.phase3_fast_replication_mode}"
    export PHASE3_WGS_FAST_REPLICATION_PART_SIZE_BYTES="${params.phase3_fast_replication_part_size_bytes}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics replicate:phase3-fast-inputs
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/replication_receipt.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_replication_receipt",
      "status": "stubbed",
      "mode": "${params.phase3_fast_replication_mode}",
      "copy_results": [],
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_CACHE_MANIFEST {
    tag "fast_cache_manifest_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/cache_manifest", mode: 'copy', overwrite: true

    input:
    path replication_receipt

    output:
    path 'workspace/manifests/phase3_wgs_fast/cache_manifest.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_REPLICATION_RECEIPT="\$PWD/${replication_receipt}"
    export PHASE3_WGS_FAST_CACHE_MANIFEST_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/cache_manifest.json"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-cache-manifest
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/cache_manifest.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_cache_manifest",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_STAGING_PLAN {
    tag "fast_staging_plan_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/staging_plan", mode: 'copy', overwrite: true

    input:
    path cache_manifest

    output:
    path 'workspace/manifests/phase3_wgs_fast/staging_plan.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_CACHE_MANIFEST="\$PWD/${cache_manifest}"
    export PHASE3_WGS_FAST_STAGING_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/staging_plan.json"
    export PHASE3_WGS_FAST_STAGING_ROOT="${params.phase3_fast_staging_root}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-staging-plan
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/staging_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_staging_plan",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_PARABRICKS_MUTECT_PLAN {
    tag "fast_parabricks_mutect_plan_${params.phase3_fast_run_id}"
    label 'gpu_parabricks'
    cpus { params.phase3_fast_parabricks_cpus as int }
    memory { params.phase3_fast_parabricks_memory }
    time '4h'
    publishDir "${params.outdir}/phase3_wgs_fast/parabricks_mutect_plan", mode: 'copy', overwrite: true

    input:
    path staging_plan

    output:
    tuple path('workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json'), path('workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json')

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_STAGING_PLAN="\$PWD/${staging_plan}"
    export PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"
    export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"
    export PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json"
    export PHASE3_WGS_FAST_PARABRICKS_OUTPUT_ROOT="${params.phase3_fast_parabricks_output_root}"
    export PHASE3_WGS_FAST_PARABRICKS_NUM_GPUS="${params.phase3_fast_parabricks_num_gpus}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics stage:phase3-fast-inputs
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-parabricks-mutect-plan
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_staged_inputs_manifest",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_parabricks_mutect_plan",
      "status": "stubbed",
      "commands": {},
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_FILTER_MUTECT_PLAN {
    tag "fast_filter_mutect_plan_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/filter_mutect_plan", mode: 'copy', overwrite: true

    input:
    tuple path(staged_inputs_manifest), path(parabricks_mutect_plan)

    output:
    path 'workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\$PWD/${staged_inputs_manifest}"
    export PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN="\$PWD/${parabricks_mutect_plan}"
    export PHASE3_WGS_FAST_FILTER_MUTECT_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json"
    export PHASE3_WGS_FAST_FILTER_MUTECT_OUTPUT_ROOT="${params.phase3_fast_filter_mutect_output_root}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-filter-mutect-plan
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_filter_mutect_plan",
      "status": "stubbed",
      "commands": {},
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_BAM_QC_PLAN {
    tag "fast_bam_qc_plan_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/bam_qc_plan", mode: 'copy', overwrite: true

    input:
    tuple path(staged_inputs_manifest), path(parabricks_mutect_plan)

    output:
    path 'workspace/manifests/phase3_wgs_fast/bam_qc_plan.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\$PWD/${staged_inputs_manifest}"
    export PHASE3_WGS_FAST_BAM_QC_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/bam_qc_plan.json"
    export PHASE3_WGS_FAST_BAM_QC_OUTPUT_ROOT="${params.phase3_fast_bam_qc_output_root}"
    export PHASE3_WGS_FAST_BAM_QC_THREADS="${params.phase3_fast_bam_qc_threads}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-bam-qc-plan
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/bam_qc_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_bam_qc_plan",
      "status": "stubbed",
      "commands": {},
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_CNV_EVIDENCE_PLAN {
    tag "fast_cnv_evidence_plan_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/cnv_evidence_plan", mode: 'copy', overwrite: true

    input:
    tuple path(staged_inputs_manifest), path(parabricks_mutect_plan)

    output:
    path 'workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\$PWD/${staged_inputs_manifest}"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_OUTPUT_ROOT="${params.phase3_fast_cnv_evidence_output_root}"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_BIN_SIZE="${params.phase3_fast_cnv_evidence_bin_size}"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_BEDCOV_WORKERS="${params.phase3_fast_cnv_evidence_bedcov_workers}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-cnv-evidence-plan
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_cnv_evidence_plan",
      "status": "stubbed",
      "commands": {},
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_SV_EVIDENCE_PLAN {
    tag "fast_sv_evidence_plan_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/sv_evidence_plan", mode: 'copy', overwrite: true

    input:
    tuple path(staged_inputs_manifest), path(parabricks_mutect_plan)

    output:
    path 'workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\$PWD/${staged_inputs_manifest}"
    export PHASE3_WGS_FAST_SV_EVIDENCE_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json"
    export PHASE3_WGS_FAST_SV_EVIDENCE_OUTPUT_ROOT="${params.phase3_fast_sv_evidence_output_root}"
    export PHASE3_WGS_FAST_SV_EVIDENCE_THREADS="${params.phase3_fast_sv_evidence_threads}"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-sv-evidence-plan
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_sv_evidence_plan",
      "status": "stubbed",
      "commands": {},
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_MUTECT_PARABRICKS_FILTER {
    tag "fast_mutect_parabricks_filter_${params.phase3_fast_run_id}"
    label 'gpu_parabricks'
    cpus { params.phase3_fast_parabricks_cpus as int }
    memory { params.phase3_fast_parabricks_memory }
    time '4h'
    publishDir "${params.outdir}/phase3_wgs_fast/small_variant_execution", mode: 'copy', overwrite: true

    input:
    path staging_plan

    output:
    tuple path('workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json'),
          path('workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json'),
          path('workspace/manifests/phase3_wgs_fast/parabricks_mutect_receipt.json'),
          path('workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json'),
          path('workspace/manifests/phase3_wgs_fast/filter_mutect_receipt.json'),
          path('workspace/manifests/phase3_wgs_fast/small_variant_artifact_export.json'),
          path('workspace/results/phase3_wgs_fast/small_variant_execution/artifacts')

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_STAGING_PLAN="\$PWD/${staging_plan}"
    export PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"
    export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"
    export PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json"
    export PHASE3_WGS_FAST_PARABRICKS_OUTPUT_ROOT="${params.phase3_fast_parabricks_output_root}"
    export PHASE3_WGS_FAST_PARABRICKS_NUM_GPUS="${params.phase3_fast_parabricks_num_gpus}"
    export PHASE3_WGS_FAST_PARABRICKS_MUTECT_PLAN="\$PWD/workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json"
    export PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/parabricks_mutect_receipt.json"
    export PHASE3_WGS_FAST_FILTER_MUTECT_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json"
    export PHASE3_WGS_FAST_FILTER_MUTECT_OUTPUT_ROOT="${params.phase3_fast_filter_mutect_output_root}"
    export PHASE3_WGS_FAST_FILTER_MUTECT_PLAN="\$PWD/workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json"
    export PHASE3_WGS_FAST_PARABRICKS_MUTECT_RECEIPT="\$PWD/workspace/manifests/phase3_wgs_fast/parabricks_mutect_receipt.json"
    export PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/filter_mutect_receipt.json"
    export PHASE3_WGS_FAST_FILTER_MUTECT_RECEIPT="\$PWD/workspace/manifests/phase3_wgs_fast/filter_mutect_receipt.json"
    export PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_ROOT="\$PWD/workspace/results/phase3_wgs_fast/small_variant_execution/artifacts"
    export PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/small_variant_artifact_export.json"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics stage:phase3-fast-inputs
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-parabricks-mutect-plan
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics run:phase3-fast-parabricks-mutect
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-filter-mutect-plan
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics run:phase3-fast-filter-mutect
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics export:phase3-fast-small-variants
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_staged_inputs_manifest",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/parabricks_mutect_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_parabricks_mutect_plan",
      "status": "stubbed",
      "commands": {},
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/parabricks_mutect_receipt.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_parabricks_mutect_receipt",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/filter_mutect_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_filter_mutect_plan",
      "status": "stubbed",
      "commands": {},
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/filter_mutect_receipt.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_filter_mutect_receipt",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    mkdir -p workspace/results/phase3_wgs_fast/small_variant_execution/artifacts
    cat > workspace/manifests/phase3_wgs_fast/small_variant_artifact_export.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_small_variant_artifact_export",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_BAM_CNV_SV_EVIDENCE {
    tag "fast_bam_cnv_sv_evidence_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus { params.phase3_fast_sv_evidence_threads as int }
    memory '16 GB'
    time '4h'
    publishDir "${params.outdir}/phase3_wgs_fast/bam_cnv_sv_evidence_execution", mode: 'copy', overwrite: true

    input:
    path staging_plan

    output:
    tuple path('workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json'),
          path('workspace/manifests/phase3_wgs_fast/bam_qc_plan.json'),
          path('workspace/manifests/phase3_wgs_fast/bam_qc_receipt.json'),
          path('workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json'),
          path('workspace/manifests/phase3_wgs_fast/cnv_evidence_receipt.json'),
          path('workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json'),
          path('workspace/manifests/phase3_wgs_fast/sv_evidence_receipt.json'),
          path('workspace/results/phase3_wgs_fast/bam_qc'),
          path('workspace/results/phase3_wgs_fast/cnv_evidence'),
          path('workspace/results/phase3_wgs_fast/sv_evidence')

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_STAGING_PLAN="\$PWD/${staging_plan}"
    export PHASE3_WGS_FAST_STAGED_INPUTS_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"
    export PHASE3_WGS_FAST_STAGED_INPUTS_MANIFEST="\$PWD/workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json"
    export PHASE3_WGS_FAST_BAM_QC_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/bam_qc_plan.json"
    export PHASE3_WGS_FAST_BAM_QC_OUTPUT_ROOT="\$PWD/workspace/results/phase3_wgs_fast/bam_qc"
    export PHASE3_WGS_FAST_BAM_QC_THREADS="${params.phase3_fast_bam_qc_threads}"
    export PHASE3_WGS_FAST_BAM_QC_PLAN="\$PWD/workspace/manifests/phase3_wgs_fast/bam_qc_plan.json"
    export PHASE3_WGS_FAST_BAM_QC_RECEIPT_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/bam_qc_receipt.json"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_OUTPUT_ROOT="\$PWD/workspace/results/phase3_wgs_fast/cnv_evidence"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_BIN_SIZE="${params.phase3_fast_cnv_evidence_bin_size}"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_BEDCOV_WORKERS="${params.phase3_fast_cnv_evidence_bedcov_workers}"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_PLAN="\$PWD/workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/cnv_evidence_receipt.json"
    export PHASE3_WGS_FAST_SV_EVIDENCE_PLAN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json"
    export PHASE3_WGS_FAST_SV_EVIDENCE_OUTPUT_ROOT="\$PWD/workspace/results/phase3_wgs_fast/sv_evidence"
    export PHASE3_WGS_FAST_SV_EVIDENCE_THREADS="${params.phase3_fast_sv_evidence_threads}"
    export PHASE3_WGS_FAST_SV_EVIDENCE_PLAN="\$PWD/workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json"
    export PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/sv_evidence_receipt.json"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics stage:phase3-fast-inputs
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-bam-qc-plan
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics run:phase3-fast-bam-qc
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-cnv-evidence-plan
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics run:phase3-fast-cnv-evidence
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-sv-evidence-plan
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics run:phase3-fast-sv-evidence
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    mkdir -p workspace/results/phase3_wgs_fast/bam_qc
    mkdir -p workspace/results/phase3_wgs_fast/cnv_evidence
    mkdir -p workspace/results/phase3_wgs_fast/sv_evidence
    cat > workspace/manifests/phase3_wgs_fast/staged_inputs_manifest.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_staged_inputs_manifest",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/bam_qc_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_bam_qc_plan",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/bam_qc_receipt.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_bam_qc_receipt",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call",
        "hrd_use": "qc_only_not_hrd_evidence"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/cnv_evidence_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_cnv_evidence_plan",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/cnv_evidence_receipt.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_cnv_evidence_receipt",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call",
        "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/sv_evidence_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_sv_evidence_plan",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    cat > workspace/manifests/phase3_wgs_fast/sv_evidence_receipt.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_sv_evidence_receipt",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call",
        "chord_use": "no_call_requires_validated_production_sv_caller_vcf",
        "hrdetect_use": "no_call_requires_validated_structural_variant_features"
      }
    }
    JSON
    """
}

process FAST_EVIDENCE_JOIN {
    tag "fast_evidence_join_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/evidence_join", mode: 'copy', overwrite: true

    input:
    path small_variant_artifact_export
    tuple path(bam_qc_receipt),
          path(cnv_evidence_receipt),
          path(sv_evidence_receipt)

    output:
    path 'workspace/manifests/phase3_wgs_fast/evidence_join_manifest.json'

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_SMALL_VARIANT_EXPORT="\$PWD/${small_variant_artifact_export}"
    export PHASE3_WGS_FAST_BAM_QC_RECEIPT="\$PWD/${bam_qc_receipt}"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_RECEIPT="\$PWD/${cnv_evidence_receipt}"
    export PHASE3_WGS_FAST_SV_EVIDENCE_RECEIPT="\$PWD/${sv_evidence_receipt}"
    export PHASE3_WGS_FAST_EVIDENCE_JOIN_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/evidence_join_manifest.json"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics join:phase3-fast-evidence
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/evidence_join_manifest.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_evidence_join_manifest",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call",
        "sbs96_use": "input_matrix_not_validated_sbs3_assignment",
        "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments",
        "chord_use": "no_call_requires_validated_production_sv_caller_vcf",
        "hrdetect_use": "no_call_requires_validated_structural_variant_features"
      }
    }
    JSON
    """
}

process FAST_VERIFY_AND_PUBLISH {
    tag "fast_verify_and_publish_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/final", mode: 'copy', overwrite: true

    input:
    path evidence_join_manifest
    path small_variant_artifacts
    tuple path(bam_qc_results),
          path(cnv_evidence_results),
          path(sv_evidence_results)

    output:
    tuple path('workspace/manifests/phase3_wgs_fast/final_evidence_manifest.json'),
          path('workspace/results/phase3_wgs_fast/final')

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_EVIDENCE_JOIN="\$PWD/${evidence_join_manifest}"
    export PHASE3_WGS_FAST_SMALL_VARIANT_ARTIFACT_ROOT="\$PWD/${small_variant_artifacts}"
    export PHASE3_WGS_FAST_BAM_QC_ARTIFACT_ROOT="\$PWD/${bam_qc_results}"
    export PHASE3_WGS_FAST_CNV_EVIDENCE_ARTIFACT_ROOT="\$PWD/${cnv_evidence_results}"
    export PHASE3_WGS_FAST_SV_EVIDENCE_ARTIFACT_ROOT="\$PWD/${sv_evidence_results}"
    export PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT="\$PWD/workspace/results/phase3_wgs_fast/final"
    export PHASE3_WGS_FAST_FINAL_EVIDENCE_OUTPUT="\$PWD/workspace/manifests/phase3_wgs_fast/final_evidence_manifest.json"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics publish:phase3-fast-final-evidence
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    mkdir -p workspace/results/phase3_wgs_fast/final/artifacts
    cat > workspace/manifests/phase3_wgs_fast/final_evidence_manifest.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_final_evidence_manifest",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call",
        "sbs96_use": "input_matrix_not_validated_sbs3_assignment",
        "scarhrd_use": "no_call_requires_allele_specific_cnv_loh_segments",
        "chord_use": "no_call_requires_validated_production_sv_caller_vcf",
        "hrdetect_use": "no_call_requires_validated_structural_variant_features"
      }
    }
    JSON
    """
}

process FAST_STAGE_DETERMINISTIC_REPORT {
    tag "fast_stage_deterministic_report_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/deterministic_report", mode: 'copy', overwrite: true

    input:
    path crosscheck_materialization_plan
    tuple path(final_evidence_manifest),
          path(final_evidence_root)

    output:
    tuple path('workspace/results/phase3_wgs_fast/deterministic_report/report.md'),
          path('workspace/results/phase3_wgs_fast/deterministic_report/report_manifest.json'),
          path('workspace/results/phase3_wgs_fast/deterministic_report/readiness.csv'),
          path('workspace/results/phase3_wgs_fast/deterministic_report/evidence_checks.json'),
          path('workspace/results/phase3_wgs_fast/deterministic_report/input_sha256.csv'),
          path('workspace/results/phase3_wgs_fast/deterministic_report/crosscheck_input_plans.json')

    script:
    """
    set -euo pipefail
    export PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN="\$PWD/${crosscheck_materialization_plan}"
    export PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST="\$PWD/${final_evidence_manifest}"
    export PHASE3_WGS_FAST_FINAL_EVIDENCE_ROOT="\$PWD/${final_evidence_root}"
    export PHASE3_WGS_FAST_DETERMINISTIC_REPORT_OUTPUT="\$PWD/workspace/results/phase3_wgs_fast/deterministic_report"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics stage:phase3-fast-deterministic-report
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/results/phase3_wgs_fast/deterministic_report
    cat > workspace/results/phase3_wgs_fast/deterministic_report/report.md <<'MD'
    # Phase 3 fast deterministic WGS evidence report

    Stubbed `no_call` report.
    MD
    cat > workspace/results/phase3_wgs_fast/deterministic_report/readiness.csv <<'CSV'
    evidence_surface,state,reason
    overall_hrd,no_call,stubbed
    CSV
    cat > workspace/results/phase3_wgs_fast/deterministic_report/input_sha256.csv <<'CSV'
    input_id,path,bytes,sha256
    CSV
    cat > workspace/results/phase3_wgs_fast/deterministic_report/evidence_checks.json <<JSON
    {"schema_version":1,"status":"stubbed","report_status":"partial_evidence","overall_hrd_status":"no_call","checks":[],"input_sha256":[]}
    JSON
    cat > workspace/results/phase3_wgs_fast/deterministic_report/crosscheck_input_plans.json <<JSON
    {"schema_version":1,"plan_type":"phase3_fast_crosscheck_input_materialization_plan","status":"stubbed","authorized_hrd_state":"no_call","classification_authorized":false,"routes":{}}
    JSON
    cat > workspace/results/phase3_wgs_fast/deterministic_report/report_manifest.json <<JSON
    {"schema_version":1,"method_id":"deterministic_full_wgs","report_kind":"phase3_fast_deterministic_evidence","evidence_status":"partial_evidence","authorized_hrd_state":"no_call","classification_authorized":false}
    JSON
    """
}

process FAST_CROSSCHECK_MATERIALIZATION_PLAN {
    tag "fast_crosscheck_materialization_plan_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/crosscheck_materialization_plan", mode: 'copy', overwrite: true

    input:
    tuple path(final_evidence_manifest),
          path(final_evidence_root)

    output:
    path 'workspace/manifests/phase3_wgs_fast/crosscheck_materialization_plan.json'

    script:
    """
    set -euo pipefail
    test -d "${final_evidence_root}"
    export PHASE3_WGS_FAST_FINAL_EVIDENCE_MANIFEST="\$PWD/${final_evidence_manifest}"
    export PHASE3_WGS_FAST_CROSSCHECK_MATERIALIZATION_PLAN="\$PWD/workspace/manifests/phase3_wgs_fast/crosscheck_materialization_plan.json"

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:phase3-fast-crosscheck-materialization-plan
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests/phase3_wgs_fast
    cat > workspace/manifests/phase3_wgs_fast/crosscheck_materialization_plan.json <<JSON
    {
      "schema_version": 1,
      "manifest_type": "phase3_wgs_fast_crosscheck_materialization_plan",
      "status": "stubbed",
      "interpretation": {
        "authorized_hrd_state": "no_call"
      }
    }
    JSON
    """
}

process FAST_STAGE_ROSALIND_PACKET {
    tag "fast_stage_rosalind_packet_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '2 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/rosalind_hrd", mode: 'copy', overwrite: true

    input:
    tuple path(report_md),
          path(report_manifest),
          path(readiness),
          path(evidence_checks),
          path(input_sha256),
          path(crosscheck_input_plans)
    tuple path(final_evidence_manifest),
          path(final_evidence_root)

    output:
    tuple path("workspace/results/rosalind_hrd/${params.phase3_fast_run_id}/run_manifest.json"),
          path("workspace/results/rosalind_hrd/${params.phase3_fast_run_id}/packet_index.md"),
          path("workspace/results/rosalind_hrd/${params.phase3_fast_run_id}/cloud_materialization_plan.md"),
          path("workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}/input_evidence_index.json"),
          path("workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}/sample_validation_summary.csv"),
          path("workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}/hrd_adapter_status.csv"),
          path("workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}/research_context_sources.json"),
          path("workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}/next_actions.md"),
          path("workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}/reviewer_packet.md"),
          path("workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}/report.md"),
          path("workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}/report_manifest.json")

    script:
    """
    set -euo pipefail
    mkdir -p deterministic_report
    cp "${report_md}" deterministic_report/report.md
    cp "${report_manifest}" deterministic_report/report_manifest.json
    cp "${readiness}" deterministic_report/readiness.csv
    cp "${evidence_checks}" deterministic_report/evidence_checks.json
    cp "${input_sha256}" deterministic_report/input_sha256.csv
    cp "${crosscheck_input_plans}" deterministic_report/crosscheck_input_plans.json

    export DIANA_OMICS_ROOT="\$PWD/workspace"
    export ROSALIND_HRD_SAMPLE_SET="diana_wgs"
    export ROSALIND_HRD_RUN_ID="${params.phase3_fast_run_id}"
    export ROSALIND_HRD_ARTIFACT_ROOT="\$PWD/${final_evidence_root}"
    export ROSALIND_HRD_DETERMINISTIC_REPORT_DIR="\$PWD/deterministic_report"
    export ROSALIND_HRD_FORBIDDEN_TOKENS_JSON='${params.phase3_fast_forbidden_tokens_json}'

    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics build:rosalind-hrd-packet
    """

    stub:
    """
    set -euo pipefail
    root="workspace/results/rosalind_hrd/${params.phase3_fast_run_id}"
    output="workspace/results/rosalind_hrd/diana_wgs/${params.phase3_fast_run_id}"
    mkdir -p "\$root"
    mkdir -p "\$output"
    cat > "\$root/run_manifest.json" <<JSON
    {"runId":"${params.phase3_fast_run_id}","sampleSets":["diana_wgs"],"packets":[]}
    JSON
    cat > "\$root/packet_index.md" <<'MD'
    # Rosalind HRD Packet Index
    MD
    cat > "\$root/cloud_materialization_plan.md" <<'MD'
    # Cloud Materialization Plan
    MD
    cat > "\$output/input_evidence_index.json" <<JSON
    {"sampleSet":"diana_wgs","artifacts":[]}
    JSON
    cat > "\$output/sample_validation_summary.csv" <<CSV
    evidence_id,status,detail,artifact,caveat
    phase3_fast_run_boundary,no_call,stubbed,report_manifest.json,stubbed
    CSV
    cat > "\$output/hrd_adapter_status.csv" <<CSV
    adapter,state,blocker,next_action
    scarHRD,no_call,stubbed,stubbed
    CSV
    cat > "\$output/research_context_sources.json" <<JSON
    {"status":"stubbed","sample_set":"diana_wgs"}
    JSON
    cat > "\$output/next_actions.md" <<'MD'
    # Next Actions: Diana WGS HRD Evidence Review Packet
    MD
    cat > "\$output/reviewer_packet.md" <<'MD'
    # Diana WGS HRD Evidence Review Packet

    Stubbed Phase 3 fast no_call packet.
    MD
    cp "\$output/reviewer_packet.md" "\$output/report.md"
    cat > "\$output/report_manifest.json" <<JSON
    {"schema_version":1,"method_id":"rosalind_diana_wgs","report_kind":"rosalind_hrd_reviewer_packet","evidence_status":"partial_evidence","authorized_hrd_state":"no_call","classification_authorized":false}
    JSON
    """
}

process FAST_STAGE_BLOCKED_CROSSCHECKS {
    tag "fast_stage_blocked_crosschecks_${params.phase3_fast_run_id}"
    label 'cpu_io'
    cpus 1
    memory '1 GB'
    time '15m'
    publishDir "${params.outdir}/phase3_wgs_fast/blocked_crosschecks", mode: 'copy', overwrite: true

    input:
    tuple path(rosalind_run_manifest),
          path(rosalind_packet_index),
          path(rosalind_cloud_materialization_plan),
          path(rosalind_input_evidence_index),
          path(rosalind_sample_validation_summary),
          path(rosalind_hrd_adapter_status),
          path(rosalind_research_context_sources),
          path(rosalind_next_actions),
          path(rosalind_reviewer_packet),
          path(rosalind_report),
          path(rosalind_report_manifest)

    output:
    tuple path('workspace/results/phase3_wgs_fast/blocked_crosschecks/facets_scarhrd_blocked/method_spec.json'),
          path('workspace/results/phase3_wgs_fast/blocked_crosschecks/facets_scarhrd_blocked/report.md'),
          path('workspace/results/phase3_wgs_fast/blocked_crosschecks/facets_scarhrd_blocked/report_manifest.json'),
          path('workspace/results/phase3_wgs_fast/blocked_crosschecks/oncoanalyser_chord_blocked/method_spec.json'),
          path('workspace/results/phase3_wgs_fast/blocked_crosschecks/oncoanalyser_chord_blocked/report.md'),
          path('workspace/results/phase3_wgs_fast/blocked_crosschecks/oncoanalyser_chord_blocked/report_manifest.json'),
          path('workspace/results/phase3_wgs_fast/blocked_crosschecks/hrdetect_blocked/method_spec.json'),
          path('workspace/results/phase3_wgs_fast/blocked_crosschecks/hrdetect_blocked/report.md'),
          path('workspace/results/phase3_wgs_fast/blocked_crosschecks/hrdetect_blocked/report_manifest.json')

    script:
    """
    set -euo pipefail
    test -s "${rosalind_run_manifest}"
    test -s "${rosalind_packet_index}"
    test -s "${rosalind_report_manifest}"
    test -s "${rosalind_cloud_materialization_plan}"
    test -s "${rosalind_input_evidence_index}"
    test -s "${rosalind_sample_validation_summary}"
    test -s "${rosalind_hrd_adapter_status}"
    test -s "${rosalind_research_context_sources}"
    test -s "${rosalind_next_actions}"
    test -s "${rosalind_reviewer_packet}"
    test -s "${rosalind_report}"

    "${params.python_bin}" "${params.repo_dir}/scripts/generate_blocked_hrd_crosscheck_reports.py" \
        --output-dir "\$PWD/workspace/results/phase3_wgs_fast/blocked_crosschecks" \
        --run-id "${params.phase3_fast_run_id}" \
        --source-report-manifest "rosalind_diana_wgs=${rosalind_report_manifest}" \
        --generated-at "${params.phase3_fast_generated_at}"
    """

    stub:
    """
    set -euo pipefail
    output="workspace/results/phase3_wgs_fast/blocked_crosschecks"
    mkdir -p "\$output"
    for method_id in facets_scarhrd_blocked oncoanalyser_chord_blocked hrdetect_blocked; do
      mkdir -p "\$output/\$method_id"
      cat > "\$output/\$method_id/method_spec.json" <<JSON
    {"schema_version":1,"method_id":"\$method_id","execution_status":"not_run","evidence_status":"blocked","interpretation_status":"no_call","patient_result":"none"}
    JSON
      cat > "\$output/\$method_id/report.md" <<'MD'
    # Blocked HRD cross-check report

    Stubbed blocked `no_call` report.
    MD
      cat > "\$output/\$method_id/report_manifest.json" <<JSON
    {"schema_version":1,"method_id":"\$method_id","report_kind":"blocked_method","evidence_status":"blocked","authorized_hrd_state":"no_call","classification_authorized":false}
    JSON
    done
    """
}

workflow PHASE3_WGS_FAST_GPU_SMOKE {
    FAST_GPU_SMOKE()
}

workflow PHASE3_WGS_FAST {
    requiredFastManifestParams = [
        'phase3_fast_private_freeze_receipt',
        'phase3_fast_private_sha256_receipt',
        'phase3_fast_reference_freeze_receipt',
        'phase3_fast_reference_sha256_receipt',
        'phase3_fast_bam_validation_receipt',
        'phase3_fast_contig_compatibility_receipt',
        'phase3_fast_caller_resource_receipt',
        'phase3_fast_parameter_sha256',
        'phase3_fast_parabricks_container_digest',
        'phase3_fast_parabricks_version',
        'phase3_fast_sequenza_female',
        'phase3_fast_cache_prefix',
        'phase3_fast_cache_kms_key_arn',
    ]
    missing = requiredFastManifestParams.findAll { name ->
        def value = params[name]
        value == null || value.toString().trim() == ''
    }
    if (missing) {
        error "phase3_wgs_fast requires: ${missing.join(', ')}"
    }
    allowedSmallVariantModes = ['plan', 'execute']
    smallVariantMode = params.phase3_fast_small_variant_mode.toString()
    if (!allowedSmallVariantModes.contains(smallVariantMode)) {
        error "Unknown phase3_fast_small_variant_mode '${smallVariantMode}'. Choose one of: ${allowedSmallVariantModes.join(', ')}."
    }

    inputReceipts = Channel.of(tuple(
        file(params.phase3_fast_private_freeze_receipt.toString(), checkIfExists: true),
        file(params.phase3_fast_private_sha256_receipt.toString(), checkIfExists: true),
        file(params.phase3_fast_reference_freeze_receipt.toString(), checkIfExists: true),
        file(params.phase3_fast_reference_sha256_receipt.toString(), checkIfExists: true),
        file(params.phase3_fast_bam_validation_receipt.toString(), checkIfExists: true),
        file(params.phase3_fast_contig_compatibility_receipt.toString(), checkIfExists: true),
        file(params.phase3_fast_caller_resource_receipt.toString(), checkIfExists: true)
    ))
    FAST_INPUT_MANIFEST(inputReceipts)
    FAST_REPLICATION_PLAN(FAST_INPUT_MANIFEST.out)
    FAST_REPLICATE_INPUTS(FAST_REPLICATION_PLAN.out)
    if (params.phase3_fast_replication_mode.toString().replace('-', '_') == 'apply') {
        FAST_CACHE_MANIFEST(FAST_REPLICATE_INPUTS.out)
        FAST_STAGING_PLAN(FAST_CACHE_MANIFEST.out)
        if (smallVariantMode == 'execute') {
            if (params.phase3_fast_forbidden_tokens_json == null || params.phase3_fast_forbidden_tokens_json.toString().trim() == '') {
                error "phase3_wgs_fast execute mode requires: phase3_fast_forbidden_tokens_json"
            }
            FAST_MUTECT_PARABRICKS_FILTER(FAST_STAGING_PLAN.out)
            FAST_BAM_CNV_SV_EVIDENCE(FAST_STAGING_PLAN.out)
            small_variant_export_for_join = FAST_MUTECT_PARABRICKS_FILTER.out.map {
                small_staged_inputs_manifest,
                parabricks_mutect_plan,
                parabricks_mutect_receipt,
                filter_mutect_plan,
                filter_mutect_receipt,
                small_variant_artifact_export,
                small_variant_artifacts -> small_variant_artifact_export
            }
            aux_receipts_for_join = FAST_BAM_CNV_SV_EVIDENCE.out.map {
                aux_staged_inputs_manifest,
                bam_qc_plan,
                bam_qc_receipt,
                cnv_evidence_plan,
                cnv_evidence_receipt,
                sv_evidence_plan,
                sv_evidence_receipt,
                bam_qc_results,
                cnv_evidence_results,
                sv_evidence_results -> tuple(bam_qc_receipt, cnv_evidence_receipt, sv_evidence_receipt)
            }
            FAST_EVIDENCE_JOIN(small_variant_export_for_join, aux_receipts_for_join)
            small_variant_artifacts_for_publish = FAST_MUTECT_PARABRICKS_FILTER.out.map {
                small_staged_inputs_manifest,
                parabricks_mutect_plan,
                parabricks_mutect_receipt,
                filter_mutect_plan,
                filter_mutect_receipt,
                small_variant_artifact_export,
                small_variant_artifacts -> small_variant_artifacts
            }
            aux_artifacts_for_publish = FAST_BAM_CNV_SV_EVIDENCE.out.map {
                aux_staged_inputs_manifest,
                bam_qc_plan,
                bam_qc_receipt,
                cnv_evidence_plan,
                cnv_evidence_receipt,
                sv_evidence_plan,
                sv_evidence_receipt,
                bam_qc_results,
                cnv_evidence_results,
                sv_evidence_results -> tuple(bam_qc_results, cnv_evidence_results, sv_evidence_results)
            }
            FAST_VERIFY_AND_PUBLISH(FAST_EVIDENCE_JOIN.out, small_variant_artifacts_for_publish, aux_artifacts_for_publish)
            FAST_CROSSCHECK_MATERIALIZATION_PLAN(FAST_VERIFY_AND_PUBLISH.out)
            FAST_STAGE_DETERMINISTIC_REPORT(FAST_CROSSCHECK_MATERIALIZATION_PLAN.out, FAST_VERIFY_AND_PUBLISH.out)
            FAST_STAGE_ROSALIND_PACKET(FAST_STAGE_DETERMINISTIC_REPORT.out, FAST_VERIFY_AND_PUBLISH.out)
            FAST_STAGE_BLOCKED_CROSSCHECKS(FAST_STAGE_ROSALIND_PACKET.out)
        } else {
            FAST_PARABRICKS_MUTECT_PLAN(FAST_STAGING_PLAN.out)
            FAST_BAM_QC_PLAN(FAST_PARABRICKS_MUTECT_PLAN.out)
            FAST_CNV_EVIDENCE_PLAN(FAST_PARABRICKS_MUTECT_PLAN.out)
            FAST_SV_EVIDENCE_PLAN(FAST_PARABRICKS_MUTECT_PLAN.out)
            FAST_FILTER_MUTECT_PLAN(FAST_PARABRICKS_MUTECT_PLAN.out)
        }
    }
}

workflow {
    selectedWorkflow = params.workflow.toString()
    effectivePhase3Reads = params.phase3_reads ? params.phase3_reads.toString() : '500000'
    allowFullWgs = params.allow_full_wgs.toString() == 'true'
    workflows = ['quick', 'full_wes', 'phase3_fetch', 'phase3_sra_benchmark', 'known_answer_public_findings', 'known_answer_bounded_non_dry', 'known_answer_expanded_cohort', 'phase3_wgs', 'phase3_wgs_align_only', 'phase3_wgs_align_scatter', 'phase3_wgs_fast', 'phase3_wgs_fast_gpu_smoke', 'phase3_wgs_monolith', 'all_public']

    if (!workflows.contains(selectedWorkflow)) {
        error "Unknown workflow '${selectedWorkflow}'. Choose one of: ${workflows.join(', ')}."
    }

    if (selectedWorkflow == 'all_public' && !params.phase3_reads) {
        error "all_public requires an explicit --phase3_reads value, for example --phase3_reads 500000 or --phase3_reads full."
    }

    if (selectedWorkflow == 'all_public' && effectivePhase3Reads == 'full' && !allowFullWgs) {
        error "Full-source WGS in all_public requires --phase3_reads full --allow_full_wgs true."
    }

    allowMetadataCnvTiming = params.phase3_allow_metadata_cnv_timing.toString() == 'true'
    if (selectedWorkflow == 'phase3_wgs' && effectivePhase3Reads == 'full' && params.phase3_coverage_cnv_mode.toString().replace('-', '_') == 'metadata' && !allowMetadataCnvTiming) {
        error 'Full-source Phase 3 WGS acceptance requires real coverage CNV bins; use --phase3_coverage_cnv_mode full or --phase3_allow_metadata_cnv_timing true for bounded developer timing runs.'
    }

    if (selectedWorkflow == 'quick') {
        QUICK()
    } else if (selectedWorkflow == 'full_wes') {
        FULL_WES()
    } else if (selectedWorkflow == 'phase3_fetch') {
        PHASE3_FETCH()
    } else if (selectedWorkflow == 'phase3_sra_benchmark') {
        PHASE3_SRA_BENCHMARK()
    } else if (selectedWorkflow == 'known_answer_public_findings') {
        KNOWN_ANSWER_PUBLIC_FINDINGS()
    } else if (selectedWorkflow == 'known_answer_bounded_non_dry') {
        KNOWN_ANSWER_BOUNDED_NON_DRY()
    } else if (selectedWorkflow == 'known_answer_expanded_cohort') {
        KNOWN_ANSWER_EXPANDED_COHORT()
    } else if (selectedWorkflow == 'phase3_wgs') {
        PHASE3_WGS_SPLIT()
    } else if (selectedWorkflow == 'phase3_wgs_align_only') {
        PHASE3_WGS_ALIGN_ONLY()
    } else if (selectedWorkflow == 'phase3_wgs_align_scatter') {
        PHASE3_WGS_ALIGN_SCATTER()
    } else if (selectedWorkflow == 'phase3_wgs_fast') {
        PHASE3_WGS_FAST()
    } else if (selectedWorkflow == 'phase3_wgs_fast_gpu_smoke') {
        PHASE3_WGS_FAST_GPU_SMOKE()
    } else if (selectedWorkflow == 'phase3_wgs_monolith') {
        PHASE3_WGS()
    } else {
        ALL_PUBLIC()
    }
}
