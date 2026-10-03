nextflow.enable.dsl = 2

params.repo_root = null
params.runner_path = null
params.runner_sha256 = null
params.helper_path = null
params.helper_sha256 = null
params.run_id = null
params.recover_existing_run = false

process RUN_CORRECTIVE_MODAL_TROP2 {
    tag "${params.run_id}"

    publishDir "${launchDir}/results", mode: 'copy', overwrite: false

    output:
    path "modal_preflight.log"
    path "modal_run.log"
    path "modal_result"

    script:
    """
    work_dir=\$PWD
    printf '%s  %s\n' "${params.runner_sha256}" "${params.runner_path}" | shasum -a 256 -c -
    printf '%s  %s\n' "${params.helper_sha256}" "${params.helper_path}" | shasum -a 256 -c -
    cd "${params.repo_root}"
    if [[ "${params.recover_existing_run}" == "true" ]]; then
      printf '%s\n' 'Recovery mode: reusing the completed immutable S3 run.' > "\$work_dir/modal_preflight.log"
      modal run "${params.runner_path}" \
        --run-id "${params.run_id}" \
        --download-only \
        --download-dir "\$work_dir/modal_result" \
        > "\$work_dir/modal_run.log"
    else
      modal run "${params.runner_path}" --preflight-only > "\$work_dir/modal_preflight.log"
      modal run "${params.runner_path}" \
        --run-id "${params.run_id}" \
        --download-dir "\$work_dir/modal_result" \
        > "\$work_dir/modal_run.log"
    fi
    """
}

workflow {
    if (!params.repo_root) {
        error "--repo_root is required"
    }
    if (!params.runner_path) {
        error "--runner_path is required"
    }
    if (!params.runner_sha256) {
        error "--runner_sha256 is required"
    }
    if (!params.helper_path) {
        error "--helper_path is required"
    }
    if (!params.helper_sha256) {
        error "--helper_sha256 is required"
    }
    if (!params.run_id) {
        error "--run_id is required"
    }

    RUN_CORRECTIVE_MODAL_TROP2()
}
