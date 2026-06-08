#!/usr/bin/env nextflow

nextflow.enable.dsl = 2

params.workflow = params.workflow ?: 'quick'
params.phase3_reads = params.phase3_reads ?: null
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

process PHASE3_WGS {
    tag "phase3_wgs_${params.phase3_reads ?: '500000'}"
    cpus 16
    memory '64 GB'
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

workflow {
    selectedWorkflow = params.workflow.toString()
    effectivePhase3Reads = params.phase3_reads ? params.phase3_reads.toString() : '500000'
    allowFullWgs = params.allow_full_wgs.toString() == 'true'
    workflows = ['quick', 'full_wes', 'phase3_wgs', 'all_public']

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
    } else if (selectedWorkflow == 'phase3_wgs') {
        PHASE3_WGS()
    } else {
        ALL_PUBLIC()
    }
}
