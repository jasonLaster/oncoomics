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
    SOURCE_DIR="${params.repo_dir}"
    rm -rf workspace
    mkdir -p workspace
    rsync -a --delete --exclude '.git/' --exclude '.nextflow/' --exclude 'work/' --exclude 'nextflow-out/' "\${SOURCE_DIR%/}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    run() { echo "==> \$*"; "\$@"; }

    run "\$PYTHON_BIN" -m diana_omics verify:plan
    run "\$PYTHON_BIN" -m diana_omics fetch:phase1
    run "\$PYTHON_BIN" -m diana_omics fetch:raw-candidates
    run "\$PYTHON_BIN" -m diana_omics audit:raw-tools
    run "\$PYTHON_BIN" -m diana_omics build:diana-template
    run "\$PYTHON_BIN" -m diana_omics verify:diana-raw
    run "\$PYTHON_BIN" -m diana_omics build:raw-samplesheets
    run "\$PYTHON_BIN" -m diana_omics smoke:raw
    run "\$PYTHON_BIN" -m diana_omics build:alignment-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:alignment
    run "\$PYTHON_BIN" -m diana_omics fetch:human-reference-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:human-reference
    run "\$PYTHON_BIN" -m diana_omics fetch:full-reference-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:full-reference
    run "\$PYTHON_BIN" -m diana_omics fetch:production-somatic
    run "\$PYTHON_BIN" -m diana_omics smoke:production-somatic
    run "\$PYTHON_BIN" -m diana_omics build:panel
    run "\$PYTHON_BIN" -m diana_omics analyze:hrd
    run "\$PYTHON_BIN" -m diana_omics analyze:rna
    run "\$PYTHON_BIN" -m diana_omics build:packet
    if "\$PYTHON_BIN" -m diana_omics verify:outputs; then
        echo "==> Full output verification passed."
    else
        echo "==> Full output verification did not pass; quick does not recompute full-source WGS acceptance artifacts."
    fi
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests workspace/results
    PYTHONPATH="${params.repo_dir}/py/src" "${params.python_bin}" -m diana_omics --help > workspace/results/nextflow_stub_help.txt
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
    SOURCE_DIR="${params.repo_dir}"
    rm -rf workspace
    mkdir -p workspace
    rsync -a --delete --exclude '.git/' --exclude '.nextflow/' --exclude 'work/' --exclude 'nextflow-out/' "\${SOURCE_DIR%/}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export PHASE2F_THREADS="\${PHASE2F_THREADS:-${task.cpus}}"
    run() { echo "==> \$*"; "\$@"; }

    run "\$PYTHON_BIN" -m diana_omics verify:plan
    run "\$PYTHON_BIN" -m diana_omics fetch:phase1
    run "\$PYTHON_BIN" -m diana_omics fetch:raw-candidates
    run "\$PYTHON_BIN" -m diana_omics audit:raw-tools
    run "\$PYTHON_BIN" -m diana_omics build:diana-template
    run "\$PYTHON_BIN" -m diana_omics verify:diana-raw
    run "\$PYTHON_BIN" -m diana_omics build:raw-samplesheets
    run "\$PYTHON_BIN" -m diana_omics smoke:raw
    run "\$PYTHON_BIN" -m diana_omics build:alignment-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:alignment
    run "\$PYTHON_BIN" -m diana_omics fetch:human-reference-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:human-reference
    run "\$PYTHON_BIN" -m diana_omics fetch:full-reference-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:full-reference
    run "\$PYTHON_BIN" -m diana_omics fetch:production-somatic
    run "\$PYTHON_BIN" -m diana_omics smoke:production-somatic
    run "\$PYTHON_BIN" -m diana_omics fetch:full-wes
    run "\$PYTHON_BIN" -m diana_omics benchmark:full-wes
    run "\$PYTHON_BIN" -m diana_omics verify:orthogonal
    run "\$PYTHON_BIN" -m diana_omics build:panel
    run "\$PYTHON_BIN" -m diana_omics analyze:hrd
    run "\$PYTHON_BIN" -m diana_omics analyze:rna
    run "\$PYTHON_BIN" -m diana_omics build:packet
    if "\$PYTHON_BIN" -m diana_omics verify:outputs; then
        echo "==> Full output verification passed."
    else
        echo "==> Full output verification did not pass; full_wes does not recompute full-source WGS acceptance artifacts."
    fi
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests workspace/results
    PYTHONPATH="${params.repo_dir}/py/src" "${params.python_bin}" -m diana_omics --help > workspace/results/nextflow_stub_help.txt
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
    SOURCE_DIR="${params.repo_dir}"
    rm -rf workspace
    mkdir -p workspace
    rsync -a --delete --exclude '.git/' --exclude '.nextflow/' --exclude 'work/' --exclude 'nextflow-out/' "\${SOURCE_DIR%/}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export PHASE3_WGS_READS="${params.phase3_reads ?: '500000'}"
    export PHASE3_WGS_FETCH_CONCURRENCY="${params.phase3_fetch_concurrency}"
    export PHASE3_WGS_ARIA2_SPLIT="${params.phase3_aria2_split}"
    export PHASE3_WGS_SOURCE_MODE="${params.phase3_source_mode}"
    export PHASE3_WGS_SRA_AWS_BUCKET="${params.phase3_sra_aws_bucket}"
    export PHASE3_WGS_SRA_THREADS="\${PHASE3_WGS_SRA_THREADS:-${task.cpus}}"
    export PHASE3_WGS_S3_RANGE_CONCURRENCY="${params.phase3_s3_range_concurrency}"
    export PHASE3_WGS_S3_RANGE_BYTES="${params.phase3_s3_range_bytes}"
    export PHASE3_WGS_S3_RANGE_RETRIES="${params.phase3_s3_range_retries}"
    export PHASE3_WGS_SRA_RUN_CONCURRENCY="${params.phase3_sra_run_concurrency}"
    export PHASE3_WGS_SRA_COMMAND_RETRIES="${params.phase3_sra_command_retries}"
    export PHASE3_WGS_FASTQ_STATS_MODE="${params.phase3_fastq_stats_mode}"
    export PHASE3_WGS_CACHE_UPLOAD_WORKERS="${params.phase3_cache_upload_workers}"
    export PHASE3_WGS_ASSET_CACHE_URI="${params.phase3_asset_cache_uri ?: ''}"
    export PHASE3_WGS_ASSET_CACHE_MODE="${params.phase3_asset_cache_mode}"
    export PHASE3_WGS_DELETE_SRA_AFTER_CONVERSION="${params.phase3_delete_sra_after_conversion}"
    run() { echo "==> \$*"; "\$@"; }

    run "\$PYTHON_BIN" -m diana_omics verify:plan
    run "\$PYTHON_BIN" -m diana_omics fetch:phase1
    run "\$PYTHON_BIN" -m diana_omics fetch:raw-candidates
    run "\$PYTHON_BIN" -m diana_omics audit:raw-tools
    run "\$PYTHON_BIN" -m diana_omics build:diana-template
    run "\$PYTHON_BIN" -m diana_omics verify:diana-raw
    run "\$PYTHON_BIN" -m diana_omics build:raw-samplesheets
    run "\$PYTHON_BIN" -m diana_omics fetch:full-reference-smoke
    run "\$PYTHON_BIN" -m diana_omics fetch:production-somatic
    run "\$PYTHON_BIN" -m diana_omics fetch:phase3-wgs
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests workspace/results
    PYTHONPATH="${params.repo_dir}/py/src" "${params.python_bin}" -m diana_omics --help > workspace/results/nextflow_stub_help.txt
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
    SOURCE_DIR="${params.repo_dir}"
    rm -rf workspace
    mkdir -p workspace
    rsync -a --delete --exclude '.git/' --exclude '.nextflow/' --exclude 'work/' --exclude 'nextflow-out/' "\${SOURCE_DIR%/}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export PHASE3_WGS_READS="${params.phase3_reads ?: '500000'}"
    export PHASE3_WGS_FETCH_CONCURRENCY="${params.phase3_fetch_concurrency}"
    export PHASE3_WGS_ARIA2_SPLIT="${params.phase3_aria2_split}"
    export PHASE3_WGS_SOURCE_MODE="${params.phase3_source_mode}"
    export PHASE3_WGS_SRA_AWS_BUCKET="${params.phase3_sra_aws_bucket}"
    export PHASE3_WGS_SRA_THREADS="\${PHASE3_WGS_SRA_THREADS:-${task.cpus}}"
    export PHASE3_WGS_S3_RANGE_CONCURRENCY="${params.phase3_s3_range_concurrency}"
    export PHASE3_WGS_S3_RANGE_BYTES="${params.phase3_s3_range_bytes}"
    export PHASE3_WGS_S3_RANGE_RETRIES="${params.phase3_s3_range_retries}"
    export PHASE3_WGS_SRA_RUN_CONCURRENCY="${params.phase3_sra_run_concurrency}"
    export PHASE3_WGS_SRA_COMMAND_RETRIES="${params.phase3_sra_command_retries}"
    export PHASE3_WGS_FASTQ_STATS_MODE="${params.phase3_fastq_stats_mode}"
    export PHASE3_WGS_CACHE_UPLOAD_WORKERS="${params.phase3_cache_upload_workers}"
    export PHASE3_WGS_ASSET_CACHE_URI="${params.phase3_asset_cache_uri ?: ''}"
    export PHASE3_WGS_ASSET_CACHE_MODE="${params.phase3_asset_cache_mode}"
    export PHASE3_WGS_DELETE_SRA_AFTER_CONVERSION="${params.phase3_delete_sra_after_conversion}"
    run() { echo "==> \$*"; "\$@"; }

    run "\$PYTHON_BIN" -m diana_omics verify:plan
    run "\$PYTHON_BIN" -m diana_omics fetch:phase1
    run "\$PYTHON_BIN" -m diana_omics fetch:raw-candidates
    run "\$PYTHON_BIN" -m diana_omics audit:raw-tools
    run "\$PYTHON_BIN" -m diana_omics build:diana-template
    run "\$PYTHON_BIN" -m diana_omics verify:diana-raw
    run "\$PYTHON_BIN" -m diana_omics build:raw-samplesheets
    run "\$PYTHON_BIN" -m diana_omics fetch:full-reference-smoke
    run "\$PYTHON_BIN" -m diana_omics fetch:production-somatic
    if [ "${params.phase3_include_wes}" = "true" ]; then
        run "\$PYTHON_BIN" -m diana_omics fetch:full-wes
        run "\$PYTHON_BIN" -m diana_omics benchmark:full-wes
    else
        echo "==> Skipping full WES prerequisite for split Phase 3 WGS; use --phase3_include_wes true for orthogonal WES ladder."
    fi
    run "\$PYTHON_BIN" -m diana_omics fetch:phase3-wgs
    rm -rf data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full/fastq
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests workspace/results
    PYTHONPATH="${params.repo_dir}/py/src" "${params.python_bin}" -m diana_omics --help > workspace/results/nextflow_stub_help.txt
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
    rm -rf workspace
    rsync -a "${previous_workspace}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export PHASE3_WGS_STAGE=reference_index
    export PHASE3_WGS_READS="${params.phase3_reads ?: '500000'}"
    export PHASE3_WGS_THREADS="\${PHASE3_WGS_THREADS:-${task.cpus}}"
    run() { echo "==> \$*"; "\$@"; }
    run "\$PYTHON_BIN" -m diana_omics validate:phase3-wgs
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/results/phase3_wgs_smoke/stage_markers
    echo '{"stub":true,"stage":"reference_index"}' > workspace/results/phase3_wgs_smoke/stage_markers/reference_index.json
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
    rm -rf workspace
    rsync -a "${previous_workspace}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export PHASE3_WGS_FETCH_CONCURRENCY="${params.phase3_fetch_concurrency}"
    export PHASE3_WGS_ARIA2_SPLIT="${params.phase3_aria2_split}"
    export PHASE3_WGS_SOURCE_MODE="${params.phase3_source_mode}"
    export PHASE3_WGS_SRA_AWS_BUCKET="${params.phase3_sra_aws_bucket}"
    export PHASE3_WGS_SRA_THREADS="\${PHASE3_WGS_SRA_THREADS:-${task.cpus}}"
    export PHASE3_WGS_S3_RANGE_CONCURRENCY="${params.phase3_s3_range_concurrency}"
    export PHASE3_WGS_S3_RANGE_BYTES="${params.phase3_s3_range_bytes}"
    export PHASE3_WGS_S3_RANGE_RETRIES="${params.phase3_s3_range_retries}"
    export PHASE3_WGS_SRA_RUN_CONCURRENCY="${params.phase3_sra_run_concurrency}"
    export PHASE3_WGS_SRA_COMMAND_RETRIES="${params.phase3_sra_command_retries}"
    export PHASE3_WGS_FASTQ_STATS_MODE="${params.phase3_fastq_stats_mode}"
    export PHASE3_WGS_CACHE_UPLOAD_WORKERS="${params.phase3_cache_upload_workers}"
    export PHASE3_WGS_ASSET_CACHE_URI="${params.phase3_asset_cache_uri ?: ''}"
    export PHASE3_WGS_ASSET_CACHE_MODE="${params.phase3_asset_cache_mode}"
    export PHASE3_WGS_DELETE_SRA_AFTER_CONVERSION="${params.phase3_delete_sra_after_conversion}"
    export PHASE3_WGS_FETCH_ONLY_ROLE="${role}"
    export PHASE3_WGS_STAGE=align_sample
    export PHASE3_WGS_SAMPLE_ROLE="${role}"
    export PHASE3_WGS_READS="${params.phase3_reads ?: '500000'}"
    export PHASE3_WGS_THREADS="\${PHASE3_WGS_THREADS:-${task.cpus}}"
    export PHASE3_WGS_PARALLEL_ALIGN=0
    export PHASE3_WGS_ALIGNMENT_CACHE_WORKERS="${params.phase3_alignment_cache_workers}"
    export PHASE3_WGS_ASSET_CACHE_URI="${params.phase3_asset_cache_uri ?: ''}"
    export PHASE3_WGS_ASSET_CACHE_MODE="${params.phase3_asset_cache_mode}"
    run() { echo "==> \$*"; "\$@"; }
    run "\$PYTHON_BIN" -m diana_omics fetch:phase3-wgs
    run "\$PYTHON_BIN" -m diana_omics validate:phase3-wgs
    rm -rf data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full/fastq
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/results/phase3_wgs_smoke/stage_markers
    echo '{"stub":true,"stage":"align_sample","role":"${role}"}' > workspace/results/phase3_wgs_smoke/stage_markers/align_${role}.json
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
    if [ "${tumor_role}" != "tumor" ] || [ "${normal_role}" != "normal" ]; then
        echo "Expected tumor then normal workspaces, got ${tumor_role} and ${normal_role}." >&2
        exit 1
    fi
    rm -rf workspace
    rsync -a "${tumor_workspace}/" workspace/
    mkdir -p \
        workspace/data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full/ucsc_hg38_analysis_set_full/full/bam \
        workspace/results/phase3_wgs_smoke/logs \
        workspace/results/phase3_wgs_smoke/stage_markers
    rsync -a "${normal_workspace}/data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full/ucsc_hg38_analysis_set_full/full/bam/" \
        workspace/data/raw/phase3_wgs_smoke/seqc2_hcc1395_wgs_hiseqx_full/ucsc_hg38_analysis_set_full/full/bam/
    rsync -a "${normal_workspace}/results/phase3_wgs_smoke/logs/" workspace/results/phase3_wgs_smoke/logs/
    rsync -a "${normal_workspace}/results/phase3_wgs_smoke/stage_markers/" workspace/results/phase3_wgs_smoke/stage_markers/
    for reusable_source in "${tumor_workspace}" "${normal_workspace}"; do
        for reusable_artifact in \
            results/phase3_wgs_smoke/bam_validation_summary.csv \
            results/phase3_wgs_smoke/bam_validation_summary.json \
            results/phase3_wgs_smoke/coverage_cnv_bins.csv \
            results/phase3_wgs_smoke/coverage_cnv_summary.csv \
            results/phase3_wgs_smoke/coverage_cnv_summary.json \
            results/phase3_wgs_smoke/seqc2_truth_depth.tsv \
            results/phase3_wgs_smoke/sv_evidence_candidates.csv \
            results/phase3_wgs_smoke/sv_evidence_summary.csv \
            results/phase3_wgs_smoke/sv_evidence_summary.json
        do
            if [ -f "\${reusable_source}/\${reusable_artifact}" ]; then
                mkdir -p "workspace/\$(dirname "\${reusable_artifact}")"
                cp -a "\${reusable_source}/\${reusable_artifact}" "workspace/\${reusable_artifact}"
            fi
        done
    done
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export PHASE3_WGS_STAGE=downstream
    export PHASE3_WGS_READS="${params.phase3_reads ?: '500000'}"
    export PHASE3_WGS_THREADS="\${PHASE3_WGS_THREADS:-${task.cpus}}"
    export PHASE3_WGS_PARALLEL_ALIGN=0
    export PHASE3_WGS_ALIGNMENT_CACHE_WORKERS="${params.phase3_alignment_cache_workers}"
    export PHASE3_WGS_ASSET_CACHE_URI="${params.phase3_asset_cache_uri ?: ''}"
    export PHASE3_WGS_ASSET_CACHE_MODE="${params.phase3_asset_cache_mode}"
    run() { echo "==> \$*"; "\$@"; }

    run "\$PYTHON_BIN" -m diana_omics validate:phase3-wgs
    if [ "${params.phase3_include_wes}" = "true" ]; then
        run "\$PYTHON_BIN" -m diana_omics verify:orthogonal
    else
        echo "==> Skipping orthogonal WES verification because --phase3_include_wes is false."
    fi
    run "\$PYTHON_BIN" -m diana_omics build:panel
    run "\$PYTHON_BIN" -m diana_omics analyze:hrd
    run "\$PYTHON_BIN" -m diana_omics analyze:rna
    run "\$PYTHON_BIN" -m diana_omics build:packet
    if [ "${params.phase3_reads ?: '500000'}" = "full" ]; then
        if [ "${params.phase3_include_wes}" = "true" ]; then
            run "\$PYTHON_BIN" -m diana_omics verify:outputs
        else
            run "\$PYTHON_BIN" -m diana_omics verify:phase3-outputs
        fi
    else
        echo "==> Skipping fatal full output verification for bounded Phase 3 developer run."
        "\$PYTHON_BIN" -m diana_omics verify:outputs || true
    fi
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests workspace/results/phase3_wgs_smoke
    PYTHONPATH="${params.repo_dir}/py/src" "${params.python_bin}" -m diana_omics --help > workspace/results/nextflow_stub_help.txt
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
    SOURCE_DIR="${params.repo_dir}"
    rm -rf workspace
    mkdir -p workspace
    rsync -a --delete --exclude '.git/' --exclude '.nextflow/' --exclude 'work/' --exclude 'nextflow-out/' "\${SOURCE_DIR%/}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export AWS_CA_BUNDLE="\${AWS_CA_BUNDLE:-/etc/ssl/certs/ca-certificates.crt}"
    AWS_CLI="\$(command -v aws || true)"
    S5CMD="\$(command -v s5cmd || true)"
    if [ -z "\$AWS_CLI" ] && [ -x /opt/diana-aws/bin/aws ]; then
        AWS_CLI=/opt/diana-aws/bin/aws
    fi
    if [ -z "\$AWS_CLI" ]; then
        echo "AWS CLI is required for phase3_sra_benchmark." >&2
        exit 1
    fi

    BYTES="${params.sra_benchmark_bytes}"
    PARTS="${params.sra_benchmark_parts}"
    RUNS="${params.sra_benchmark_runs}"
    BUCKET="${params.phase3_sra_aws_bucket}"
    CONCURRENCY="${params.phase3_fetch_concurrency}"
    STRATEGY="${params.sra_benchmark_strategy}"
    MATRIX="${params.sra_benchmark_matrix ?: ''}"
    export AWS_CLI S5CMD BYTES PARTS RUNS BUCKET CONCURRENCY STRATEGY MATRIX

    run() { echo "==> \$*"; "\$@"; }
    run "\$PYTHON_BIN" -m diana_omics benchmark:sra-range
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/results/phase3_wgs_smoke
    cat > workspace/results/phase3_wgs_smoke/sra_benchmark.json <<'JSON'
{"sourceMode":"aws_sra","stub":true}
JSON
    touch workspace/results/phase3_wgs_smoke/sra_benchmark.tsv
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
    SOURCE_DIR="${params.repo_dir}"
    rm -rf workspace
    mkdir -p workspace
    rsync -a --delete --exclude '.git/' --exclude '.nextflow/' --exclude 'work/' --exclude 'nextflow-out/' "\${SOURCE_DIR%/}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export PHASE3_WGS_READS="${params.phase3_reads ?: '500000'}"
    export PHASE3_WGS_THREADS="\${PHASE3_WGS_THREADS:-${task.cpus}}"
    export PHASE3_WGS_FETCH_CONCURRENCY="${params.phase3_fetch_concurrency}"
    export PHASE3_WGS_ARIA2_SPLIT="${params.phase3_aria2_split}"
    export PHASE3_WGS_SOURCE_MODE="${params.phase3_source_mode}"
    export PHASE3_WGS_SRA_AWS_BUCKET="${params.phase3_sra_aws_bucket}"
    export PHASE3_WGS_SRA_THREADS="\${PHASE3_WGS_SRA_THREADS:-${task.cpus}}"
    export PHASE3_WGS_S3_RANGE_CONCURRENCY="${params.phase3_s3_range_concurrency}"
    export PHASE3_WGS_S3_RANGE_BYTES="${params.phase3_s3_range_bytes}"
    export PHASE3_WGS_S3_RANGE_RETRIES="${params.phase3_s3_range_retries}"
    export PHASE3_WGS_SRA_RUN_CONCURRENCY="${params.phase3_sra_run_concurrency}"
    export PHASE3_WGS_SRA_COMMAND_RETRIES="${params.phase3_sra_command_retries}"
    export PHASE3_WGS_FASTQ_STATS_MODE="${params.phase3_fastq_stats_mode}"
    export PHASE3_WGS_CACHE_UPLOAD_WORKERS="${params.phase3_cache_upload_workers}"
    export PHASE3_WGS_ALIGNMENT_CACHE_WORKERS="${params.phase3_alignment_cache_workers}"
    export PHASE3_WGS_ASSET_CACHE_URI="${params.phase3_asset_cache_uri ?: ''}"
    export PHASE3_WGS_ASSET_CACHE_MODE="${params.phase3_asset_cache_mode}"
    export PHASE3_WGS_DELETE_SRA_AFTER_CONVERSION="${params.phase3_delete_sra_after_conversion}"
    run() { echo "==> \$*"; "\$@"; }

    run "\$PYTHON_BIN" -m diana_omics verify:plan
    run "\$PYTHON_BIN" -m diana_omics fetch:phase1
    run "\$PYTHON_BIN" -m diana_omics fetch:raw-candidates
    run "\$PYTHON_BIN" -m diana_omics audit:raw-tools
    run "\$PYTHON_BIN" -m diana_omics build:diana-template
    run "\$PYTHON_BIN" -m diana_omics verify:diana-raw
    run "\$PYTHON_BIN" -m diana_omics build:raw-samplesheets
    if [ "${params.phase3_prereq_mode}" = "full" ]; then
        run "\$PYTHON_BIN" -m diana_omics smoke:raw
        run "\$PYTHON_BIN" -m diana_omics build:alignment-smoke
        run "\$PYTHON_BIN" -m diana_omics smoke:alignment
        run "\$PYTHON_BIN" -m diana_omics fetch:human-reference-smoke
        run "\$PYTHON_BIN" -m diana_omics smoke:human-reference
    else
        echo "==> Skipping raw/alignment/human-reference smoke prerequisites for Phase 3 WGS minimal mode."
    fi
    run "\$PYTHON_BIN" -m diana_omics fetch:full-reference-smoke
    if [ "${params.phase3_prereq_mode}" = "full" ]; then
        run "\$PYTHON_BIN" -m diana_omics smoke:full-reference
    else
        echo "==> Skipping full-reference smoke alignment for Phase 3 WGS minimal mode."
    fi
    run "\$PYTHON_BIN" -m diana_omics fetch:production-somatic
    if [ "${params.phase3_prereq_mode}" = "full" ]; then
        run "\$PYTHON_BIN" -m diana_omics smoke:production-somatic
    else
        echo "==> Skipping production somatic smoke for Phase 3 WGS minimal mode."
    fi
    if [ "${params.phase3_include_wes}" = "true" ]; then
        run "\$PYTHON_BIN" -m diana_omics fetch:full-wes
        run "\$PYTHON_BIN" -m diana_omics benchmark:full-wes
    else
        echo "==> Skipping full WES prerequisite for Phase 3 WGS; use --phase3_include_wes true for orthogonal WES ladder."
    fi
    run "\$PYTHON_BIN" -m diana_omics fetch:phase3-wgs
    run "\$PYTHON_BIN" -m diana_omics validate:phase3-wgs
    if [ "${params.phase3_include_wes}" = "true" ]; then
        run "\$PYTHON_BIN" -m diana_omics verify:orthogonal
    else
        echo "==> Skipping orthogonal WES verification because --phase3_include_wes is false."
    fi
    run "\$PYTHON_BIN" -m diana_omics build:panel
    run "\$PYTHON_BIN" -m diana_omics analyze:hrd
    run "\$PYTHON_BIN" -m diana_omics analyze:rna
    run "\$PYTHON_BIN" -m diana_omics build:packet
    if [ "${params.phase3_reads ?: '500000'}" = "full" ]; then
        if [ "${params.phase3_include_wes}" = "true" ]; then
            # Full WES ladder ran: the whole-pipeline output set must verify.
            run "\$PYTHON_BIN" -m diana_omics verify:outputs
        else
            # WGS-only full run: the WES/orthogonal artifacts were intentionally
            # skipped, so gate fatally on the Phase 3 WGS acceptance subset instead
            # of letting the full verifier pass non-fatally.
            run "\$PYTHON_BIN" -m diana_omics verify:phase3-outputs
        fi
    else
        echo "==> Skipping fatal full output verification for bounded Phase 3 developer run."
        "\$PYTHON_BIN" -m diana_omics verify:outputs || true
    fi
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests workspace/results
    PYTHONPATH="${params.repo_dir}/py/src" "${params.python_bin}" -m diana_omics --help > workspace/results/nextflow_stub_help.txt
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
    SOURCE_DIR="${params.repo_dir}"
    rm -rf workspace
    mkdir -p workspace
    rsync -a --delete --exclude '.git/' --exclude '.nextflow/' --exclude 'work/' --exclude 'nextflow-out/' "\${SOURCE_DIR%/}/" workspace/
    cd workspace
    export DIANA_OMICS_ROOT="\$PWD"
    export DIANA_OMICS_SKIP_WIKI_CHECKS="${params.skip_wiki_checks}"
    export PYTHONPATH="\$PWD/py/src"
    export PYTHON_BIN="${params.python_bin}"
    export PHASE2F_THREADS="\${PHASE2F_THREADS:-8}"
    export PHASE3_WGS_READS="${params.phase3_reads ?: '500000'}"
    export PHASE3_WGS_THREADS="\${PHASE3_WGS_THREADS:-${task.cpus}}"
    export PHASE3_WGS_FETCH_CONCURRENCY="${params.phase3_fetch_concurrency}"
    export PHASE3_WGS_ARIA2_SPLIT="${params.phase3_aria2_split}"
    export PHASE3_WGS_SOURCE_MODE="${params.phase3_source_mode}"
    export PHASE3_WGS_SRA_AWS_BUCKET="${params.phase3_sra_aws_bucket}"
    export PHASE3_WGS_SRA_THREADS="\${PHASE3_WGS_SRA_THREADS:-${task.cpus}}"
    export PHASE3_WGS_S3_RANGE_CONCURRENCY="${params.phase3_s3_range_concurrency}"
    export PHASE3_WGS_S3_RANGE_BYTES="${params.phase3_s3_range_bytes}"
    export PHASE3_WGS_S3_RANGE_RETRIES="${params.phase3_s3_range_retries}"
    export PHASE3_WGS_SRA_RUN_CONCURRENCY="${params.phase3_sra_run_concurrency}"
    export PHASE3_WGS_SRA_COMMAND_RETRIES="${params.phase3_sra_command_retries}"
    export PHASE3_WGS_FASTQ_STATS_MODE="${params.phase3_fastq_stats_mode}"
    export PHASE3_WGS_CACHE_UPLOAD_WORKERS="${params.phase3_cache_upload_workers}"
    export PHASE3_WGS_ALIGNMENT_CACHE_WORKERS="${params.phase3_alignment_cache_workers}"
    export PHASE3_WGS_ASSET_CACHE_URI="${params.phase3_asset_cache_uri ?: ''}"
    export PHASE3_WGS_ASSET_CACHE_MODE="${params.phase3_asset_cache_mode}"
    export PHASE3_WGS_DELETE_SRA_AFTER_CONVERSION="${params.phase3_delete_sra_after_conversion}"
    run() { echo "==> \$*"; "\$@"; }

    run "\$PYTHON_BIN" -m diana_omics verify:plan
    run "\$PYTHON_BIN" -m diana_omics fetch:phase1
    run "\$PYTHON_BIN" -m diana_omics fetch:raw-candidates
    run "\$PYTHON_BIN" -m diana_omics audit:raw-tools
    run "\$PYTHON_BIN" -m diana_omics build:diana-template
    run "\$PYTHON_BIN" -m diana_omics verify:diana-raw
    run "\$PYTHON_BIN" -m diana_omics build:raw-samplesheets
    run "\$PYTHON_BIN" -m diana_omics smoke:raw
    run "\$PYTHON_BIN" -m diana_omics build:alignment-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:alignment
    run "\$PYTHON_BIN" -m diana_omics fetch:human-reference-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:human-reference
    run "\$PYTHON_BIN" -m diana_omics fetch:full-reference-smoke
    run "\$PYTHON_BIN" -m diana_omics smoke:full-reference
    run "\$PYTHON_BIN" -m diana_omics fetch:production-somatic
    run "\$PYTHON_BIN" -m diana_omics smoke:production-somatic
    run "\$PYTHON_BIN" -m diana_omics fetch:full-wes
    run "\$PYTHON_BIN" -m diana_omics benchmark:full-wes
    run "\$PYTHON_BIN" -m diana_omics fetch:phase3-wgs
    run "\$PYTHON_BIN" -m diana_omics validate:phase3-wgs
    run "\$PYTHON_BIN" -m diana_omics verify:orthogonal
    run "\$PYTHON_BIN" -m diana_omics build:panel
    run "\$PYTHON_BIN" -m diana_omics analyze:hrd
    run "\$PYTHON_BIN" -m diana_omics analyze:rna
    run "\$PYTHON_BIN" -m diana_omics build:packet
    if [ "${params.phase3_reads ?: '500000'}" = "full" ]; then
        run "\$PYTHON_BIN" -m diana_omics verify:outputs
    else
        echo "==> Skipping fatal full output verification for bounded Phase 3 developer run."
        "\$PYTHON_BIN" -m diana_omics verify:outputs || true
    fi
    """

    stub:
    """
    set -euo pipefail
    mkdir -p workspace/manifests workspace/results
    PYTHONPATH="${params.repo_dir}/py/src" "${params.python_bin}" -m diana_omics --help > workspace/results/nextflow_stub_help.txt
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
