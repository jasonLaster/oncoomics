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

workflow {
    selectedWorkflow = params.workflow.toString()
    effectivePhase3Reads = params.phase3_reads ? params.phase3_reads.toString() : '500000'
    allowFullWgs = params.allow_full_wgs.toString() == 'true'
    workflows = ['quick', 'full_wes', 'phase3_fetch', 'phase3_sra_benchmark', 'phase3_wgs', 'phase3_wgs_align_only', 'phase3_wgs_align_scatter', 'phase3_wgs_monolith', 'all_public']

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
    } else if (selectedWorkflow == 'phase3_wgs') {
        PHASE3_WGS_SPLIT()
    } else if (selectedWorkflow == 'phase3_wgs_align_only') {
        PHASE3_WGS_ALIGN_ONLY()
    } else if (selectedWorkflow == 'phase3_wgs_align_scatter') {
        PHASE3_WGS_ALIGN_SCATTER()
    } else if (selectedWorkflow == 'phase3_wgs_monolith') {
        PHASE3_WGS()
    } else {
        ALL_PUBLIC()
    }
}
