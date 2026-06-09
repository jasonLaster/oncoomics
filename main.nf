#!/usr/bin/env nextflow

nextflow.enable.dsl = 2

params.workflow = params.workflow ?: 'quick'
params.phase3_reads = params.phase3_reads ?: null
params.phase3_fetch_cpus = params.phase3_fetch_cpus ?: 4
params.phase3_fetch_memory = params.phase3_fetch_memory ?: '16 GB'
params.phase3_fetch_concurrency = params.phase3_fetch_concurrency ?: 2
params.phase3_aria2_split = params.phase3_aria2_split ?: 1
params.phase3_source_mode = params.phase3_source_mode ?: 'ena_fastq'
params.phase3_sra_aws_bucket = params.phase3_sra_aws_bucket ?: 'sra-pub-run-odp'
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

    mkdir -p results/phase3_wgs_smoke
    BYTES="${params.sra_benchmark_bytes}"
    PARTS="${params.sra_benchmark_parts}"
    RUNS="${params.sra_benchmark_runs}"
    BUCKET="${params.phase3_sra_aws_bucket}"
    CONCURRENCY="${params.phase3_fetch_concurrency}"
    STRATEGY="${params.sra_benchmark_strategy}"
    MATRIX="${params.sra_benchmark_matrix ?: ''}"
    export AWS_CLI S5CMD BYTES PARTS RUNS BUCKET CONCURRENCY STRATEGY MATRIX

    "\$PYTHON_BIN" - <<'PY'
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

aws = os.environ["AWS_CLI"]
s5cmd = os.environ.get("S5CMD", "")
bucket = os.environ["BUCKET"]
bytes_requested = int(os.environ["BYTES"])
parts_per_run = max(1, int(os.environ["PARTS"]))
runs = [run.strip() for run in os.environ["RUNS"].split(",") if run.strip()]
concurrency = max(1, int(os.environ["CONCURRENCY"]))
strategy = os.environ["STRATEGY"]
matrix = os.environ.get("MATRIX", "").strip()
outdir = Path("results/phase3_wgs_smoke")
outdir.mkdir(parents=True, exist_ok=True)

def parse_matrix():
    if not matrix:
        return [{
            "label": "single",
            "strategy": strategy,
            "bytes": bytes_requested,
            "parts": parts_per_run,
            "concurrency": concurrency,
        }]
    configs = []
    for index, raw_entry in enumerate(matrix.split(","), start=1):
        entry = raw_entry.strip()
        if not entry:
            continue
        pieces = entry.split(":")
        if len(pieces) not in {4, 5}:
            raise SystemExit(f"Invalid sra_benchmark_matrix entry '{entry}'. Expected strategy:concurrency:bytes:parts[:label].")
        entry_strategy, entry_concurrency, entry_bytes, entry_parts = pieces[:4]
        label = pieces[4] if len(pieces) == 5 else f"{entry_strategy}-c{entry_concurrency}-p{entry_parts}-b{entry_bytes}"
        configs.append({
            "label": label,
            "strategy": entry_strategy,
            "bytes": int(entry_bytes),
            "parts": max(1, int(entry_parts)),
            "concurrency": max(1, int(entry_concurrency)),
        })
    if not configs:
        raise SystemExit("sra_benchmark_matrix did not contain any benchmark configs.")
    return configs

def run_aws_range(run, part_index, requested_bytes):
    key = f"sra/{run}/{run}"
    start_byte = part_index * requested_bytes
    end_byte = start_byte + requested_bytes - 1
    target = Path("/tmp") / f"{run}.{start_byte}-{end_byte}.sra.part"
    target.unlink(missing_ok=True)
    command = [
        aws,
        "s3api",
        "get-object",
        "--no-sign-request",
        "--bucket",
        bucket,
        "--key",
        key,
        "--range",
        f"bytes={start_byte}-{end_byte}",
        str(target),
    ]
    subprocess.run(command, check=True)
    size = target.stat().st_size
    target.unlink(missing_ok=True)
    return size, f"bytes={start_byte}-{end_byte}", key

def run_s5cmd_cat(run, part_index, requested_bytes):
    if not s5cmd:
        raise SystemExit("s5cmd is required for s5cmd_cat benchmarks.")
    key = f"sra/{run}/{run}"
    object_uri = f"s3://{bucket}/{key}"
    count = max(1, (requested_bytes + (8 * 1024 * 1024) - 1) // (8 * 1024 * 1024))
    command = (
        f"set -eu; "
        f"{subprocess.list2cmdline([s5cmd, '--no-sign-request', 'cat', object_uri])} "
        f"| dd of=/dev/null bs=8M count={count} iflag=fullblock status=none"
    )
    subprocess.run(["bash", "-lc", command], check=True)
    return count * 8 * 1024 * 1024, f"stream-prefix:{requested_bytes}", key

def benchmark(config, part):
    run, part_index = part
    started = time.monotonic()
    if config["strategy"] == "aws_s3api_range":
        size, byte_range, key = run_aws_range(run, part_index, config["bytes"])
    elif config["strategy"] == "s5cmd_cat":
        size, byte_range, key = run_s5cmd_cat(run, part_index, config["bytes"])
    else:
        raise SystemExit(f"Unsupported sra benchmark strategy: {config['strategy']}")
    elapsed = time.monotonic() - started
    return {
        "label": config["label"],
        "strategy": config["strategy"],
        "run": run,
        "bucket": bucket,
        "key": key,
        "part": part_index,
        "range": byte_range,
        "bytes": size,
        "elapsedSeconds": round(elapsed, 3),
        "mbPerSecond": round(size / 1_000_000 / elapsed, 2),
    }

summaries = []
all_rows = []
for config in parse_matrix():
    print(f"[sra-benchmark] starting {config['label']} strategy={config['strategy']} concurrency={config['concurrency']} bytes={config['bytes']} parts={config['parts']}", flush=True)
    parts = [(run, part_index) for run in runs for part_index in range(config["parts"])]
    started_all = time.monotonic()
    with ThreadPoolExecutor(max_workers=min(config["concurrency"], len(parts))) as pool:
        rows = list(pool.map(lambda part: benchmark(config, part), parts))
    elapsed_all = time.monotonic() - started_all
    total_bytes = sum(row["bytes"] for row in rows)
    summary_row = {
        "label": config["label"],
        "strategy": config["strategy"],
        "requestedBytesPerPart": config["bytes"],
        "partsPerRun": config["parts"],
        "concurrency": config["concurrency"],
        "totalBytes": total_bytes,
        "wallSeconds": round(elapsed_all, 3),
        "aggregateMbPerSecond": round(total_bytes / 1_000_000 / elapsed_all, 2),
    }
    summaries.append(summary_row)
    all_rows.extend(rows)
    print(f"[sra-benchmark] finished {config['label']} aggregateMbPerSecond={summary_row['aggregateMbPerSecond']}", flush=True)

summary = {
    "sourceMode": "aws_sra",
    "bucket": bucket,
    "benchmarkMode": "matrix" if matrix else "single",
    "summaries": summaries,
    "runs": all_rows,
}
(outdir / "sra_benchmark.json").write_text(json.dumps(summary, indent=2) + chr(10), encoding="utf-8")
with (outdir / "sra_benchmark.tsv").open("w", encoding="utf-8") as handle:
    handle.write("label\tstrategy\trun\tpart\trange\tbytes\telapsedSeconds\tmbPerSecond" + chr(10))
    for row in all_rows:
        handle.write(f"{row['label']}\t{row['strategy']}\t{row['run']}\t{row['part']}\t{row['range']}\t{row['bytes']}\t{row['elapsedSeconds']}\t{row['mbPerSecond']}" + chr(10))
print(json.dumps(summary, indent=2))
PY
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
    export PHASE3_WGS_FETCH_CONCURRENCY="${params.phase3_fetch_concurrency}"
    export PHASE3_WGS_ARIA2_SPLIT="${params.phase3_aria2_split}"
    export PHASE3_WGS_SOURCE_MODE="${params.phase3_source_mode}"
    export PHASE3_WGS_SRA_AWS_BUCKET="${params.phase3_sra_aws_bucket}"
    export PHASE3_WGS_SRA_THREADS="\${PHASE3_WGS_SRA_THREADS:-${task.cpus}}"
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
    export PHASE3_WGS_FETCH_CONCURRENCY="${params.phase3_fetch_concurrency}"
    export PHASE3_WGS_ARIA2_SPLIT="${params.phase3_aria2_split}"
    export PHASE3_WGS_SOURCE_MODE="${params.phase3_source_mode}"
    export PHASE3_WGS_SRA_AWS_BUCKET="${params.phase3_sra_aws_bucket}"
    export PHASE3_WGS_SRA_THREADS="\${PHASE3_WGS_SRA_THREADS:-${task.cpus}}"
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
    workflows = ['quick', 'full_wes', 'phase3_fetch', 'phase3_sra_benchmark', 'phase3_wgs', 'all_public']

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
        PHASE3_WGS()
    } else {
        ALL_PUBLIC()
    }
}
