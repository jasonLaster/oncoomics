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
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_fetch_workspace --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}" --phase3-include-wes "${params.phase3_include_wes}"
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
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_reference_index --previous-workspace "${previous_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_reference_index --stub --workspace workspace --python-bin "${params.python_bin}"
    """
}

process PHASE3_ALIGN_SAMPLE {
    tag "phase3_align_${role}_${params.phase3_reads ?: '500000'}"
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
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_align_sample --previous-workspace "${previous_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --role "${role}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
    """

    stub:
    """
    set -euo pipefail
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_align_sample --stub --workspace workspace --python-bin "${params.python_bin}" --role "${role}"
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
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_downstream --tumor-role "${tumor_role}" --normal-role "${normal_role}" --tumor-workspace "${tumor_workspace}" --normal-workspace "${normal_workspace}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-include-wes "${params.phase3_include_wes}"
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
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process phase3_wgs --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}" --phase3-include-wes "${params.phase3_include_wes}" --phase3-prereq-mode "${params.phase3_prereq_mode}"
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
    PYTHONPATH="${params.repo_dir}/src" "${params.python_bin}" -m diana_omics.nextflow_process all_public --source-dir "${params.repo_dir}" --workspace workspace --python-bin "${params.python_bin}" --skip-wiki-checks "${params.skip_wiki_checks}" --task-cpus "${task.cpus}" --phase3-reads "${params.phase3_reads ?: '500000'}" --phase3-fetch-concurrency "${params.phase3_fetch_concurrency}" --phase3-aria2-split "${params.phase3_aria2_split}" --phase3-source-mode "${params.phase3_source_mode}" --phase3-sra-aws-bucket "${params.phase3_sra_aws_bucket}" --phase3-s3-range-concurrency "${params.phase3_s3_range_concurrency}" --phase3-s3-range-bytes "${params.phase3_s3_range_bytes}" --phase3-s3-range-retries "${params.phase3_s3_range_retries}" --phase3-sra-run-concurrency "${params.phase3_sra_run_concurrency}" --phase3-sra-command-retries "${params.phase3_sra_command_retries}" --phase3-fastq-stats-mode "${params.phase3_fastq_stats_mode}" --phase3-cache-upload-workers "${params.phase3_cache_upload_workers}" --phase3-alignment-cache-workers "${params.phase3_alignment_cache_workers}" --phase3-asset-cache-uri "${params.phase3_asset_cache_uri ?: ''}" --phase3-asset-cache-mode "${params.phase3_asset_cache_mode}" --phase3-delete-sra-after-conversion "${params.phase3_delete_sra_after_conversion}"
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

workflow {
    selectedWorkflow = params.workflow.toString()
    effectivePhase3Reads = params.phase3_reads ? params.phase3_reads.toString() : '500000'
    allowFullWgs = params.allow_full_wgs.toString() == 'true'
    workflows = ['quick', 'full_wes', 'phase3_fetch', 'phase3_sra_benchmark', 'phase3_wgs', 'phase3_wgs_monolith', 'all_public']

    if (!workflows.contains(selectedWorkflow)) {
        error "Unknown workflow '${selectedWorkflow}'. Choose one of: ${workflows.join(', ')}."
    }

    if (selectedWorkflow == 'all_public' && !params.phase3_reads) {
        error "all_public requires an explicit --phase3_reads value, for example --phase3_reads 500000 or --phase3_reads full."
    }

    if (selectedWorkflow == 'all_public' && effectivePhase3Reads == 'full' && !allowFullWgs) {
        error "Full-source WGS in all_public requires --phase3_reads full --allow_full_wgs true."
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
    } else if (selectedWorkflow == 'phase3_wgs_monolith') {
        PHASE3_WGS()
    } else {
        ALL_PUBLIC()
    }
}
