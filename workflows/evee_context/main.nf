#!/usr/bin/env nextflow

nextflow.enable.dsl = 2

params.variants = null
params.genome_build = 'GRCh38'
params.outdir = 'results'
params.no_network = false
params.expression = null
params.metadata = null
params.gene_sets = null
params.patient_sample = null
params.min_genes = 10
params.run_evo2 = false
params.reference = null
params.evo2_model = 'evo2_1b_base'
params.evo2_window_size = 8192
params.evo2_batch_size = 16

process LOOKUP_PUBLIC_EVEE {
    tag 'public_evee_lookup'
    publishDir "${params.outdir}", mode: 'copy', overwrite: true

    input:
    path variants

    output:
    path 'evee_lookup'

    script:
    network_flag = params.no_network ? '--no-network' : ''
    """
    python3 ${projectDir}/bin/score_evee_variants.py \
      --input "${variants}" \
      --output-dir evee_lookup \
      --genome-build "${params.genome_build}" \
      ${network_flag}
    """
}

process SCORE_PATHWAY_RANKS {
    tag 'pathway_rank_scores'
    publishDir "${params.outdir}", mode: 'copy', overwrite: true

    input:
    path expression
    path metadata
    path gene_sets

    output:
    path 'pathway_ranks'

    script:
    """
    python3 ${projectDir}/bin/score_pathway_ranks.py \
      --expression "${expression}" \
      --metadata "${metadata}" \
      --gene-sets "${gene_sets}" \
      --patient-sample "${params.patient_sample}" \
      --min-genes "${params.min_genes}" \
      --output-dir pathway_ranks
    """
}

process SCORE_EVO2_ZERO_SHOT {
    tag 'evo2_zero_shot'
    publishDir "${params.outdir}", mode: 'copy', overwrite: true
    accelerator 1, type: 'nvidia-tesla-h100'

    input:
    path variants
    path reference

    output:
    path 'evo2_zero_shot'

    script:
    """
    python3 ${projectDir}/bin/score_evo2_zero_shot.py \
      --input "${variants}" \
      --reference "${reference}" \
      --model "${params.evo2_model}" \
      --window-size "${params.evo2_window_size}" \
      --batch-size "${params.evo2_batch_size}" \
      --output-dir evo2_zero_shot
    """
}

workflow {
    if (!params.variants) {
        error "--variants is required"
    }

    variants_ch = Channel.fromPath(params.variants, checkIfExists: true)
    LOOKUP_PUBLIC_EVEE(variants_ch)

    pathway_inputs = [params.expression, params.metadata, params.gene_sets, params.patient_sample]
    if (pathway_inputs.any { it }) {
        if (!pathway_inputs.every { it }) {
            error "--expression, --metadata, --gene_sets, and --patient_sample are all required for pathway scoring"
        }
        SCORE_PATHWAY_RANKS(
            Channel.fromPath(params.expression, checkIfExists: true),
            Channel.fromPath(params.metadata, checkIfExists: true),
            Channel.fromPath(params.gene_sets, checkIfExists: true)
        )
    }

    if (params.run_evo2) {
        if (!params.reference) {
            error "--reference is required when --run_evo2 is true"
        }
        SCORE_EVO2_ZERO_SHOT(
            Channel.fromPath(params.variants, checkIfExists: true),
            Channel.fromPath(params.reference, checkIfExists: true)
        )
    }
}
