from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import modal

APP_NAME = "diana-modal-sequenza-scarhrd"
REGION = "us-east-1"
INPUT_BUCKET = "diana-omics-private-results-172630973301-us-east-1"
OUTPUT_BUCKET = "diana-omics-private-results-172630973301-us-east-1"
KMS_KEY_ARN = "arn:aws:kms:us-east-1:172630973301:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
RUN_PREFIX = "runs/subject01/diana-wgs-hrd-20260716T033101Z"
OUTPUT_PREFIX = "runs/subject01/modal-sequenza-scarhrd"
IMAGE_REFERENCE = (
    "172630973301.dkr.ecr.us-east-1.amazonaws.com/"
    "diana-hrd-sequenza@sha256:4ba1c915409ecedfc0beb5373a2bddbbb0866823a554fafc5243e10670c5a151"
)
IMAGE_SECURITY_RECEIPT_SHA256 = "7a8a59aef77788b44b85dec1c6b9dcd90be6513ad738c57bf1666f913ec31ac5"
WORK = Path("/work/hrd")
FIXED_SEQUENZA_UTILS = "/opt/hrd/sequenza_utils_fixed.py"
EXPECTED_CHROMS = tuple(f"chr{index}" for index in range(1, 23)) + ("chrX",)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


INPUT_OBJECTS: tuple[dict[str, str], ...] = (
    {
        "id": "tumor_bam",
        "local_name": "tumor.bam",
        "key": f"{RUN_PREFIX}/deterministic/inputs/tumor.markdup.bam",
        "version_id": "APPI0V_GH4Jzi4TKtDOnAtG2SPappDHS",
        "sha256": "f8ddea9f78dbd4c59b787c17c3264d4775f554892cbef59b4890a65739347e25",
    },
    {
        "id": "tumor_bai",
        "local_name": "tumor.bam.bai",
        "key": f"{RUN_PREFIX}/deterministic/inputs/tumor.markdup.bam.bai",
        "version_id": "IRESfzBu1vWSmXjUP9_OCZ5W1wMgmYNF",
        "sha256": "bc4b6bb67464b57e559a9e66e5ccecb86dd99ba7b7663b624b794c849d3de7eb",
    },
    {
        "id": "normal_bam",
        "local_name": "normal.bam",
        "key": f"{RUN_PREFIX}/deterministic/inputs/normal.markdup.bam",
        "version_id": "xXSOcffjAvujaB0wpWcy6kq9FH_r1_0I",
        "sha256": "f1a9b9790f0b1e3643b0d785ca629c2a463a9b1d146055de81f1c3bb96cb59c7",
    },
    {
        "id": "normal_bai",
        "local_name": "normal.bam.bai",
        "key": f"{RUN_PREFIX}/deterministic/inputs/normal.markdup.bam.bai",
        "version_id": "I0kQfYYG0UZf1dIYfA08tg83WekKjF2p",
        "sha256": "241d79870471f34d3b7217de46c02722ef6f7f7c68c8f5c403c1c90a516b4774",
    },
    {
        "id": "reference_fasta",
        "local_name": "reference.fa",
        "key": f"{RUN_PREFIX}/deterministic/reference/reference.fa",
        "version_id": "QKDgwVfJ_OqcPgq19DK4FP.4LW0K6sbW",
        "sha256": "d2b7be348fb20af46461855faec64dfbd21532620bd125783df050180446055e",
    },
    {
        "id": "reference_fai",
        "local_name": "reference.fa.fai",
        "key": f"{RUN_PREFIX}/deterministic/reference/reference.fa.fai",
        "version_id": "njuokIWXp4Edkz5SFeTx4S5APDcZdRcJ",
        "sha256": "eb7e1fea3ac1c264d6f21a1358727ef533ad560634b0ef360818d970c5f09687",
    },
)

app = modal.App(APP_NAME)
aws_secret = modal.Secret.from_name(_env("MODAL_AWS_SECRET_NAME", "onco-omics"))
sequenza_image = modal.Image.from_aws_ecr(
    IMAGE_REFERENCE,
    secret=aws_secret,
    setup_dockerfile_commands=[
        "ENTRYPOINT []",
        "RUN ln -sf /usr/bin/python3 /usr/bin/python",
    ],
).add_local_file(
    "scripts/modal/sequenza_utils_fixed.py",
    remote_path=FIXED_SEQUENZA_UTILS,
    copy=True,
)


@app.function(
    image=sequenza_image,
    secrets=[aws_secret],
    timeout=300,
    cpu=2,
    memory=4096,
    single_use_containers=True,
    restrict_modal_access=True,
)
def probe_sequenza_image() -> str:
    result = subprocess.run(
        [
            "Rscript",
            "-e",
            (
                "cat(jsonlite::toJSON(list("
                "sequenza=as.character(packageVersion('sequenza')), "
                "scarHRD=as.character(packageVersion('scarHRD')), "
                "samtools=system2('samtools', '--version', stdout=TRUE)[[1]], "
                "sequenza_utils=system2('sequenza-utils', '--help', stdout=TRUE)[[1]]), "
                "auto_unbox=TRUE))"
            ),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    return result.stdout


@app.function(
    image=sequenza_image,
    timeout=300,
    cpu=2,
    memory=4096,
    single_use_containers=True,
    restrict_modal_access=True,
)
def probe_sequenza_cli() -> str:
    probe = Path("/tmp/sequenza-cli-probe")
    probe.mkdir(exist_ok=True)
    fasta = probe / "toy.fa"
    wiggle = probe / "toy.gc.wig.gz"
    fasta.write_text(">chr1\nACGTACGTNNNN\n", encoding="utf-8")
    subprocess.run(
        [
            "python3",
            FIXED_SEQUENZA_UTILS,
            "gc_wiggle",
            "-w",
            "4",
            "--fasta",
            fasta.as_posix(),
            "-o",
            wiggle.as_posix(),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    result = subprocess.run(
        ["gzip", "-cd", wiggle.as_posix()],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    return result.stdout


@app.function(
    image=sequenza_image,
    secrets=[aws_secret],
    timeout=24 * 60 * 60,
    cpu=32,
    memory=122880,
    ephemeral_disk=512 * 1024,
    single_use_containers=True,
    restrict_modal_access=True,
)
def run_sequenza_scarhrd(run_id: str, approval_token: str = "") -> str:
    if approval_token != "public-data":
        raise RuntimeError("approval_token must be 'public-data' before private Diana WGS BAMs are used")

    import boto3

    output_prefix = f"{_env('DIANA_HRD_OUTPUT_PREFIX', OUTPUT_PREFIX).rstrip('/')}/{run_id}"
    s3 = boto3.client("s3", region_name=REGION)
    staged = WORK / "staged"
    output = WORK / "out"
    checkpoints = WORK / "checkpoints"
    staged.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    checkpoints.mkdir(parents=True, exist_ok=True)

    provenance: dict[str, Any] = {
        "schema": "diana_modal_sequenza_scarhrd.v1",
        "app": APP_NAME,
        "runId": run_id,
        "generatedAt": _utc_now(),
        "runtime": {
            "provider": "modal",
            "image": IMAGE_REFERENCE,
            "imageSecurityReceiptSha256": IMAGE_SECURITY_RECEIPT_SHA256,
            "sequenzaFemale": True,
        },
        "inputs": [],
    }
    _download_input(s3, "reference_fai", staged, provenance)

    _write_json(output / "modal_staged_inputs.provenance.json", provenance)
    (output / "command.json").write_text(
        json.dumps(
            {
                "stages": [
                    "samtools quickcheck",
                    "sequenza-utils gc_wiggle",
                    "sequenza-utils bam2seqz per chromosome",
                    "sequenza-utils seqz_binning",
                    "Rscript /opt/hrd/run_sequenza_scarhrd.R",
                ],
                "checkpointS3Prefix": (
                    f"s3://{OUTPUT_BUCKET}/{output_prefix}/checkpoints/"
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    bin_dir = WORK / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "sequenza-utils"
    shim.write_text(
        f'#!/usr/bin/env bash\nexec /usr/bin/python3 {FIXED_SEQUENZA_UTILS} "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}

    started_at = _utc_now()
    process: dict[str, Any] = {"returncode": 0, "status": "passed"}
    try:
        chroms = _chromosomes_from_fai(staged / "reference.fa.fai")
        part_paths_by_chrom, pending_chroms = _download_chromosome_seqz_parts(
            s3=s3,
            output_prefix=output_prefix,
            chromosomes=chroms,
            checkpoint_dir=checkpoints,
        )
        provenance["checkpointFastPath"] = {
            "reusedChromosomes": [chrom for chrom in chroms if chrom not in pending_chroms],
            "pendingChromosomes": pending_chroms,
        }

        if pending_chroms:
            _download_input(s3, "tumor_bam", staged, provenance)
            _download_input(s3, "tumor_bai", staged, provenance)
            _download_input(s3, "normal_bam", staged, provenance)
            _download_input(s3, "normal_bai", staged, provenance)
            _download_input(s3, "reference_fasta", staged, provenance)
            _write_json(output / "modal_staged_inputs.provenance.json", provenance)

            _run_logged(
                [
                    "samtools",
                    "quickcheck",
                    "-v",
                    (staged / "normal.bam").as_posix(),
                    (staged / "tumor.bam").as_posix(),
                ],
                output / "samtools_quickcheck.stdout.log",
                output / "samtools_quickcheck.stderr.log",
                env,
                timeout=15 * 60,
            )
            gc = checkpoints / "reference.gc50Base.wig.gz"
            _download_checkpoint(s3, f"{output_prefix}/checkpoints/reference.gc50Base.wig.gz", gc)
            if not gc.is_file():
                _run_logged(
                    [
                        "sequenza-utils",
                        "gc_wiggle",
                        "-w",
                        "50",
                        "--fasta",
                        (staged / "reference.fa").as_posix(),
                        "-o",
                        gc.as_posix(),
                    ],
                    output / "gc_wiggle.stdout.log",
                    output / "gc_wiggle.stderr.log",
                    env,
                    timeout=60 * 60,
                )
                _assert_gzip(gc)
                _upload_file(s3, gc, output_prefix, "checkpoints/reference.gc50Base.wig.gz")

            _build_chromosome_seqz_parts(
                s3=s3,
                output_prefix=output_prefix,
                chromosomes=chroms,
                part_paths=part_paths_by_chrom,
                pending_chromosomes=pending_chroms,
                gc=gc,
                fasta=staged / "reference.fa",
                normal_bam=staged / "normal.bam",
                tumor_bam=staged / "tumor.bam",
                log_dir=output,
                env=env,
            )
        else:
            _write_json(output / "modal_staged_inputs.provenance.json", provenance)

        small = output / "subject01.small.seqz.gz"
        if not _download_checkpoint(s3, f"{output_prefix}/checkpoints/{small.name}", small):
            binned_part_paths_by_chrom, pending_binned_chroms = (
                _download_chromosome_binned_seqz_parts(
                    s3=s3,
                    output_prefix=output_prefix,
                    chromosomes=chroms,
                    checkpoint_dir=checkpoints,
                )
            )
            binned_part_paths = _build_chromosome_binned_seqz_parts(
                s3=s3,
                output_prefix=output_prefix,
                chromosomes=chroms,
                seqz_part_paths=part_paths_by_chrom,
                binned_part_paths=binned_part_paths_by_chrom,
                pending_chromosomes=pending_binned_chroms,
                log_dir=output,
                env=env,
            )
            _combine_seqz_parts(binned_part_paths, small, log_dir=output, env=env)
            _assert_gzip(small)
            _upload_file(s3, small, output_prefix, f"checkpoints/{small.name}")
        _run_logged(
            [
                "Rscript",
                "/opt/hrd/run_sequenza_scarhrd.R",
                small.as_posix(),
                (staged / "reference.fa.fai").as_posix(),
                output.as_posix(),
                "true",
            ],
            output / "scarhrd.stdout.log",
            output / "scarhrd.stderr.log",
            env,
            timeout=2 * 60 * 60,
        )
        _run_logged(
            [
                "bash",
                "-c",
                (
                    'cd "$1"\n'
                    "find . -type f ! -name checksums.sha256 -print0 | "
                    "sort -z | xargs -0 sha256sum > checksums.sha256"
                ),
                "checksums",
                output.as_posix(),
            ],
            output / "checksums.stdout.log",
            output / "checksums.stderr.log",
            env,
            timeout=15 * 60,
        )
    except Exception as exc:
        process = {"returncode": 1, "status": "blocked", "error": str(exc)}
    finished_at = _utc_now()

    packet: dict[str, Any] = {
        "schema": "diana_modal_sequenza_scarhrd.v1",
        "runId": run_id,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "inputS3Prefix": f"s3://{INPUT_BUCKET}/{RUN_PREFIX}/",
        "outputS3Prefix": f"s3://{OUTPUT_BUCKET}/{output_prefix}/",
        "checkpointS3Prefix": f"s3://{OUTPUT_BUCKET}/{output_prefix}/checkpoints/",
        "process": process,
        "boundary": (
            "Sequenza/scarHRD scalar genomic scar scoring uses exact-version WGS BAMs; "
            "known-answer acceptance limits and HRD-positive interpretation thresholds "
            "remain outside this Modal execution."
        ),
    }
    route_result_path = output / "route_result.json"
    qc_path = output / "sequenza.qc.json"
    if route_result_path.is_file():
        packet["routeResult"] = json.loads(route_result_path.read_text(encoding="utf-8"))
    if qc_path.is_file():
        packet["sequenzaQc"] = json.loads(qc_path.read_text(encoding="utf-8"))

    (output / "modal_hrd_packet.json").write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_records = _upload_tree(s3, output, output_prefix)
    packet["outputs"] = output_records
    (output / "modal_hrd_packet.json").write_text(
        json.dumps(packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    packet["outputs"].append(
        _upload_file(s3, output / "modal_hrd_packet.json", output_prefix, "modal_hrd_packet.json")
    )

    if process["returncode"] != 0:
        raise RuntimeError(json.dumps(packet, indent=2, sort_keys=True))
    return json.dumps(packet, indent=2, sort_keys=True)


def _chromosomes_from_fai(fai: Path) -> tuple[str, ...]:
    pattern = re.compile(r"chr([1-9]|1[0-9]|2[0-2]|X)$")
    chromosomes = tuple(
        line.split("\t", 1)[0]
        for line in fai.read_text(encoding="utf-8").splitlines()
        if pattern.fullmatch(line.split("\t", 1)[0])
    )
    if chromosomes != EXPECTED_CHROMS:
        raise RuntimeError(
            f"expected FASTA index chromosomes {EXPECTED_CHROMS}, observed {chromosomes}"
        )
    return chromosomes


def _build_chromosome_seqz_parts(
    *,
    s3: Any,
    output_prefix: str,
    chromosomes: tuple[str, ...],
    part_paths: dict[str, Path],
    pending_chromosomes: list[str],
    gc: Path,
    fasta: Path,
    normal_bam: Path,
    tumor_bam: Path,
    log_dir: Path,
    env: Mapping[str, str],
) -> list[Path]:
    if pending_chromosomes:
        with ThreadPoolExecutor(
            max_workers=min(len(pending_chromosomes), _bam2seqz_workers())
        ) as executor:
            futures = {
                executor.submit(
                    _run_chromosome_bam2seqz,
                    chrom=chrom,
                    destination=part_paths[chrom],
                    gc=gc,
                    fasta=fasta,
                    normal_bam=normal_bam,
                    tumor_bam=tumor_bam,
                    log_dir=log_dir,
                    env=env,
                ): chrom
                for chrom in pending_chromosomes
            }
            for future in as_completed(futures):
                chrom = futures[future]
                part = future.result()
                _upload_file(
                    s3,
                    part,
                    output_prefix,
                    f"checkpoints/seqz/subject01.{chrom}.seqz.gz",
                )

    return [part_paths[chrom] for chrom in chromosomes]


def _download_chromosome_seqz_parts(
    *,
    s3: Any,
    output_prefix: str,
    chromosomes: tuple[str, ...],
    checkpoint_dir: Path,
) -> tuple[dict[str, Path], list[str]]:
    seqz_dir = checkpoint_dir / "seqz"
    seqz_dir.mkdir(parents=True, exist_ok=True)
    part_paths = {chrom: seqz_dir / f"subject01.{chrom}.seqz.gz" for chrom in chromosomes}
    pending: list[str] = []
    for chrom, part in part_paths.items():
        key = f"{output_prefix}/checkpoints/seqz/{part.name}"
        if not _download_checkpoint(s3, key, part):
            pending.append(chrom)

    return part_paths, pending


def _build_chromosome_binned_seqz_parts(
    *,
    s3: Any,
    output_prefix: str,
    chromosomes: tuple[str, ...],
    seqz_part_paths: dict[str, Path],
    binned_part_paths: dict[str, Path],
    pending_chromosomes: list[str],
    log_dir: Path,
    env: Mapping[str, str],
) -> list[Path]:
    if pending_chromosomes:
        with ThreadPoolExecutor(
            max_workers=min(len(pending_chromosomes), _seqz_binning_workers())
        ) as executor:
            futures = {
                executor.submit(
                    _run_chromosome_seqz_binning,
                    chrom=chrom,
                    source=seqz_part_paths[chrom],
                    destination=binned_part_paths[chrom],
                    log_dir=log_dir,
                    env=env,
                ): chrom
                for chrom in pending_chromosomes
            }
            for future in as_completed(futures):
                chrom = futures[future]
                part = future.result()
                _upload_file(
                    s3,
                    part,
                    output_prefix,
                    f"checkpoints/small-seqz/subject01.{chrom}.small.seqz.gz",
                )

    return [binned_part_paths[chrom] for chrom in chromosomes]


def _download_chromosome_binned_seqz_parts(
    *,
    s3: Any,
    output_prefix: str,
    chromosomes: tuple[str, ...],
    checkpoint_dir: Path,
) -> tuple[dict[str, Path], list[str]]:
    binned_dir = checkpoint_dir / "small-seqz"
    binned_dir.mkdir(parents=True, exist_ok=True)
    part_paths = {
        chrom: binned_dir / f"subject01.{chrom}.small.seqz.gz" for chrom in chromosomes
    }
    pending: list[str] = []
    for chrom, part in part_paths.items():
        key = f"{output_prefix}/checkpoints/small-seqz/{part.name}"
        if not _download_checkpoint(s3, key, part):
            pending.append(chrom)

    return part_paths, pending


def _download_input(
    s3: Any,
    input_id: str,
    staged: Path,
    provenance: dict[str, Any],
) -> Path:
    record = _input_record(input_id)
    local_path = staged / record["local_name"]
    provenance["inputs"].append(_download_exact(s3, record, local_path))
    return local_path


def _input_record(input_id: str) -> Mapping[str, str]:
    for record in INPUT_OBJECTS:
        if record["id"] == input_id:
            return record
    raise RuntimeError(f"unknown input object: {input_id}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_chromosome_bam2seqz(
    *,
    chrom: str,
    destination: Path,
    gc: Path,
    fasta: Path,
    normal_bam: Path,
    tumor_bam: Path,
    log_dir: Path,
    env: Mapping[str, str],
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(f"{destination.suffix}.tmp")
    tmp.unlink(missing_ok=True)
    _run_logged(
        [
            "bash",
            "-c",
            (
                "set -euo pipefail\n"
                'sequenza-utils bam2seqz -gc "$1" --fasta "$2" '
                '-n "$3" --tumor "$4" -C "$5" | bgzip -c > "$6"'
            ),
            "bam2seqz",
            gc.as_posix(),
            fasta.as_posix(),
            normal_bam.as_posix(),
            tumor_bam.as_posix(),
            chrom,
            tmp.as_posix(),
        ],
        log_dir / f"bam2seqz.{chrom}.stdout.log",
        log_dir / f"bam2seqz.{chrom}.stderr.log",
        env,
        timeout=8 * 60 * 60,
    )
    _assert_gzip(tmp)
    tmp.replace(destination)
    return destination


def _run_chromosome_seqz_binning(
    *,
    chrom: str,
    source: Path,
    destination: Path,
    log_dir: Path,
    env: Mapping[str, str],
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(f"{destination.suffix}.tmp")
    tmp.unlink(missing_ok=True)
    _run_logged(
        [
            "bash",
            "-c",
            'set -euo pipefail\nsequenza-utils seqz_binning -w 50 -s "$1" | bgzip -c > "$2"',
            "seqz_binning",
            source.as_posix(),
            tmp.as_posix(),
        ],
        log_dir / f"seqz_binning.{chrom}.stdout.log",
        log_dir / f"seqz_binning.{chrom}.stderr.log",
        env,
        timeout=2 * 60 * 60,
    )
    _assert_gzip(tmp)
    tmp.replace(destination)
    return destination


def _combine_seqz_parts(
    parts: list[Path],
    destination: Path,
    *,
    log_dir: Path,
    env: Mapping[str, str],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    parts_file = destination.with_suffix(f"{destination.suffix}.parts.txt")
    tmp = destination.with_suffix(f"{destination.suffix}.tmp")
    parts_file.write_text(
        "".join(f"{part.as_posix()}\n" for part in parts),
        encoding="utf-8",
    )
    tmp.unlink(missing_ok=True)
    _run_logged(
        [
            "bash",
            "-c",
            (
                "set -euo pipefail\n"
                "first=1\n"
                'while IFS= read -r part; do\n'
                '  if [ "$first" -eq 1 ]; then\n'
                '    gzip -cd "$part"\n'
                "    first=0\n"
                "  else\n"
                '    gzip -cd "$part" | tail -n +2\n'
                "  fi\n"
                'done < "$1" | bgzip -c > "$2"\n'
            ),
            "combine_seqz",
            parts_file.as_posix(),
            tmp.as_posix(),
        ],
        log_dir / "combine_seqz.stdout.log",
        log_dir / "combine_seqz.stderr.log",
        env,
        timeout=4 * 60 * 60,
    )
    tmp.replace(destination)


def _download_checkpoint(s3: Any, key: str, destination: Path) -> bool:
    try:
        s3.head_object(Bucket=OUTPUT_BUCKET, Key=key, ChecksumMode="ENABLED")
    except Exception as exc:
        error = getattr(exc, "response", {}).get("Error", {})
        if error.get("Code") in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise

    destination.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(OUTPUT_BUCKET, key, str(destination))
    _assert_gzip(destination)
    return True


def _run_logged(
    command: list[str],
    stdout_path: Path,
    stderr_path: Path,
    env: Mapping[str, str],
    *,
    timeout: int,
) -> None:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w",
        encoding="utf-8",
    ) as stderr:
        process = subprocess.run(
            command,
            check=False,
            env=env,
            stderr=stderr,
            stdout=stdout,
            text=True,
            timeout=timeout,
        )
    if process.returncode != 0:
        raise RuntimeError(
            f"{command[0]} exited {process.returncode}; see {stderr_path.name}"
        )


def _assert_gzip(path: Path) -> None:
    _run_logged(
        ["gzip", "-t", path.as_posix()],
        path.with_suffix(f"{path.suffix}.gzip-test.stdout.log"),
        path.with_suffix(f"{path.suffix}.gzip-test.stderr.log"),
        os.environ,
        timeout=15 * 60,
    )


def _bam2seqz_workers() -> int:
    try:
        configured = int(_env("DIANA_HRD_BAM2SEQZ_JOBS", "4"))
    except ValueError:
        return 4
    return min(max(configured, 1), 8)


def _seqz_binning_workers() -> int:
    try:
        configured = int(_env("DIANA_HRD_SEQZ_BINNING_JOBS", "6"))
    except ValueError:
        return 6
    return min(max(configured, 1), 8)


def _download_exact(
    s3: Any,
    record: Mapping[str, str],
    destination: Path,
) -> dict[str, Any]:
    head = s3.head_object(
        Bucket=INPUT_BUCKET,
        Key=record["key"],
        VersionId=record["version_id"],
        ChecksumMode="ENABLED",
    )
    if head.get("VersionId") != record["version_id"]:
        raise RuntimeError(f"{record['id']} VersionId mismatch")
    if head.get("SSEKMSKeyId") != KMS_KEY_ARN:
        raise RuntimeError(f"{record['id']} KMS key mismatch")
    s3.download_file(
        INPUT_BUCKET,
        record["key"],
        str(destination),
        ExtraArgs={"VersionId": record["version_id"]},
    )
    observed_sha256 = _sha256(destination)
    if observed_sha256 != record["sha256"]:
        raise RuntimeError(f"{record['id']} SHA-256 mismatch")
    return {
        "id": record["id"],
        "uri": f"s3://{INPUT_BUCKET}/{record['key']}",
        "versionId": record["version_id"],
        "bytes": destination.stat().st_size,
        "sha256": observed_sha256,
        "ssekmsKeyId": head.get("SSEKMSKeyId", ""),
        "checksumCRC64NVME": head.get("ChecksumCRC64NVME", ""),
    }


def _upload_tree(s3: Any, root: Path, output_prefix: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name == "modal_hrd_packet.json":
            continue
        records.append(_upload_file(s3, path, output_prefix, path.relative_to(root).as_posix()))
    return records


def _upload_file(s3: Any, path: Path, output_prefix: str, relative: str) -> dict[str, Any]:
    digest = _sha256(path)
    key = f"{output_prefix.rstrip('/')}/{relative}"
    s3.upload_file(
        str(path),
        OUTPUT_BUCKET,
        key,
        ExtraArgs={
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": KMS_KEY_ARN,
            "Metadata": {"sha256": digest},
        },
    )
    head = s3.head_object(Bucket=OUTPUT_BUCKET, Key=key, ChecksumMode="ENABLED")
    return {
        "path": path.as_posix(),
        "uri": f"s3://{OUTPUT_BUCKET}/{key}",
        "versionId": head.get("VersionId", ""),
        "bytes": path.stat().st_size,
        "sha256": digest,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_run_id() -> str:
    return "modal-sequenza-scarhrd-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@app.local_entrypoint()
def main(run_id: str = "", approval_token: str = "") -> None:
    run_id = run_id or _new_run_id()
    print(run_sequenza_scarhrd.remote(run_id, approval_token))
