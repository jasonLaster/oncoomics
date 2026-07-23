from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import modal

APP_NAME = "diana-modal-s3-target-discovery"
MOUNT_PATH = Path("/s3/target")
RAW_MOUNT_PATH = Path("/s3/raw")
INPUT_DIR = MOUNT_PATH / "input"
OUTPUT_DIR = MOUNT_PATH / "output"
LOCI_PATH = Path("/opt/diana/manifests/target_gene_loci_hs37d5.csv")
CANDIDATES_PATH = Path("/opt/diana/manifests/target_discovery_candidates.csv")
RAW_PREFIX = "diana/inbox/2026-07-14-echo-personalis"
TUMOR_BAM = "data/immunoid/E019_S01/DNA_Pipeline/Alignments/DNA_E019_S01_tumor_dna_aligned_recal.sorted.bam"
TUMOR_BAI = "data/immunoid/E019_S01/DNA_Pipeline/Alignments/DNA_E019_S01_tumor_dna_aligned_recal.sorted.bai"
NORMAL_BAM = "data/immunoid/E019_S01/DNA_Pipeline/Alignments/DNA_E019_S05_Vial1_normal_dna_aligned_recal.sorted.bam"
NORMAL_BAI = "data/immunoid/E019_S01/DNA_Pipeline/Alignments/DNA_E019_S05_Vial1_normal_dna_aligned_recal.sorted.bai"
RNA_BAM = "data/immunoid/E019_S01/RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.recal.sorted.bam"
RNA_BAI = "data/immunoid/E019_S01/RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.recal.sorted.bam.bai"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _prefix(value: str) -> str:
    return value if value.endswith("/") else f"{value}/"


app = modal.App(APP_NAME)
aws_secret = modal.Secret.from_name(_env("MODAL_AWS_SECRET_NAME", "onco-omics"))
s3_mount = modal.CloudBucketMount(
    _env("MODAL_TARGET_S3_BUCKET", "diana-omics-private-results-172630973301-us-east-1"),
    key_prefix=_prefix(_env("MODAL_TARGET_S3_PREFIX", "modal/target-discovery/local")),
    secret=aws_secret,
)
raw_mount = modal.CloudBucketMount(
    "diana-omics-raw-inputs-172630973301-us-east-1",
    key_prefix=_prefix(RAW_PREFIX),
    secret=aws_secret,
    read_only=True,
)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("samtools")
    .add_local_dir("src/diana_omics", remote_path="/opt/diana/src/diana_omics", copy=True)
    .add_local_file("manifests/target_gene_loci_hs37d5.csv", remote_path=LOCI_PATH.as_posix(), copy=True)
    .add_local_file("manifests/target_discovery_candidates.csv", remote_path=CANDIDATES_PATH.as_posix(), copy=True)
    .env({"PYTHONPATH": "/opt/diana/src"})
)


@app.function(
    image=image,
    volumes={MOUNT_PATH.as_posix(): s3_mount},
    timeout=120,
    single_use_containers=True,
    restrict_modal_access=True,
)
def build_modal_target_packet(run_id: str) -> str:
    if _env("MODAL_DIANA_APPROVED") == "1":
        raise RuntimeError(
            "This derived-evidence runner must not mount raw Diana S3 prefixes; "
            "use a separate reviewed raw-BAM runner."
        )

    from diana_omics import target_discovery

    candidates_path = INPUT_DIR / "target_discovery_candidates.csv"
    evidence_path = INPUT_DIR / "target_dna_evidence.csv"
    candidates = _read_csv(candidates_path)
    dna_evidence = _read_csv(evidence_path)
    locus_rows, board_rows = target_discovery.build_dna_board(candidates, dna_evidence)

    board_errors = target_discovery.validate_candidate_board(board_rows)
    if board_errors:
        raise RuntimeError("candidate board failed validation: " + "; ".join(board_errors))

    OUTPUT_DIR.mkdir(exist_ok=True)
    board_path = OUTPUT_DIR / "candidate_target_board.csv"
    locus_path = OUTPUT_DIR / "dna_target_locus_summary.csv"
    _write_csv(board_path, board_rows, target_discovery.CANDIDATE_BOARD_COLUMNS)
    _write_csv(locus_path, locus_rows, [
        "target_id",
        "gene_symbol",
        "dna_status",
        "copy_number_status",
        "variant_effect",
        "hla_loss_status",
        "evidence_detail",
    ])

    trop2 = next((row for row in board_rows if row["target_id"] == "trop2"), {})
    packet = {
        "schema": "diana_modal_target_packet.v1",
        "status": "partial_evidence",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runId": run_id,
        "execution": {
            "runtime": "modal",
            "app": APP_NAME,
            "s3Mount": "modal.CloudBucketMount",
            "rawDataMounted": False,
            "inputPath": INPUT_DIR.as_posix(),
            "outputPath": OUTPUT_DIR.as_posix(),
        },
        "inputEvidence": [
            _file_record(candidates_path),
            _file_record(evidence_path),
        ],
        "outputs": [
            _file_record(board_path),
            _file_record(locus_path),
        ],
        "boardSummary": {
            "candidateRows": len(board_rows),
            "partialEvidenceRows": sum(row["overall_status"] == "partial_evidence" for row in board_rows),
            "readyRows": sum(row["overall_status"] == "ready" for row in board_rows),
            "trop2Status": trop2.get("overall_status", ""),
            "trop2CandidateClass": trop2.get("candidate_class", ""),
            "trop2RnaStatus": trop2.get("rna_status", ""),
            "trop2ProteinStatus": trop2.get("protein_status", ""),
        },
        "boundary": (
            "Modal consumed derived DNA target evidence only; raw BAM, raw FASTQ, "
            "RNA expression, surface protein abundance, and drug sensitivity remain outside this run."
        ),
    }
    packet_path = OUTPUT_DIR / "modal_target_packet.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    packet["outputs"].append(_file_record(packet_path))
    return json.dumps(packet, indent=2, sort_keys=True)


@app.function(
    image=image,
    volumes={
        MOUNT_PATH.as_posix(): s3_mount,
        RAW_MOUNT_PATH.as_posix(): raw_mount,
    },
    timeout=600,
    single_use_containers=True,
    restrict_modal_access=True,
)
def build_modal_raw_bam_target_packet(run_id: str, approval_token: str = "") -> str:
    if approval_token != "public-data":
        raise RuntimeError("approval_token must be 'public-data' before the raw ImmunoID BAM mount is used")

    from diana_omics import target_discovery

    raw_manifest = _read_csv(RAW_MOUNT_PATH / "manifest.csv")
    expected = {row["relative_path"]: row for row in raw_manifest}
    for relative in (TUMOR_BAM, TUMOR_BAI, NORMAL_BAM, NORMAL_BAI):
        _require_raw_object(relative, expected)

    candidates = _read_csv(CANDIDATES_PATH)
    loci = _read_csv(LOCI_PATH)
    tumor_bam = RAW_MOUNT_PATH / TUMOR_BAM
    tumor_bai = RAW_MOUNT_PATH / TUMOR_BAI
    normal_bam = RAW_MOUNT_PATH / NORMAL_BAM
    normal_bai = RAW_MOUNT_PATH / NORMAL_BAI

    count_inputs = []
    for index, locus in enumerate(loci):
        region = f"{locus['contig']}:{locus['start']}-{locus['end']}"
        count_inputs.append((index, "tumor", tumor_bam, tumor_bai, region))
        count_inputs.append((index, "normal", normal_bam, normal_bai, region))

    counts: dict[tuple[int, str], int] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for index, role, reads in executor.map(_count_target, count_inputs):
            counts[(index, role)] = reads

    dna_rows: list[dict[str, str]] = []
    for index, locus in enumerate(loci):
        tumor_reads = counts[(index, "tumor")]
        normal_reads = counts[(index, "normal")]
        dna_rows.append(
            {
                "target_id": locus["target_id"],
                "gene_symbol": locus["gene_symbol"],
                "callability_status": "callable" if tumor_reads >= 10 and normal_reads >= 10 else "missing",
                "copy_number_status": "no_call",
                "variant_effect": "no_call",
                "hla_loss_status": "no_call",
                "evidence_detail": (
                    f"Modal mounted-S3 hs37d5 locus {locus['contig']}:{locus['start']}-{locus['end']}; "
                    f"tumor_reads={tumor_reads}; normal_reads={normal_reads}; "
                    "indexed BAM range-read callability only; variant, CNV, HLA-loss, RNA, and protein evidence remain no_call."
                ),
            }
        )

    locus_rows, board_rows = target_discovery.build_dna_board(candidates, dna_rows)
    board_errors = target_discovery.validate_candidate_board(board_rows)
    if board_errors:
        raise RuntimeError("candidate board failed validation: " + "; ".join(board_errors))

    OUTPUT_DIR.mkdir(exist_ok=True)
    evidence_path = OUTPUT_DIR / "target_dna_evidence.csv"
    board_path = OUTPUT_DIR / "candidate_target_board.csv"
    locus_path = OUTPUT_DIR / "dna_target_locus_summary.csv"
    _write_csv(evidence_path, dna_rows, target_discovery.DNA_EVIDENCE_COLUMNS)
    _write_csv(board_path, board_rows, target_discovery.CANDIDATE_BOARD_COLUMNS)
    _write_csv(locus_path, locus_rows, [
        "target_id",
        "gene_symbol",
        "dna_status",
        "copy_number_status",
        "variant_effect",
        "hla_loss_status",
        "evidence_detail",
    ])

    trop2 = next((row for row in board_rows if row["target_id"] == "trop2"), {})
    packet = {
        "schema": "diana_modal_target_packet.v1",
        "status": "partial_evidence",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runId": run_id,
        "execution": {
            "runtime": "modal",
            "app": APP_NAME,
            "s3Mount": "modal.CloudBucketMount",
            "rawDataMounted": True,
            "rawS3Prefix": f"s3://diana-omics-raw-inputs-172630973301-us-east-1/{RAW_PREFIX}",
            "inputPath": RAW_MOUNT_PATH.as_posix(),
            "outputPath": OUTPUT_DIR.as_posix(),
        },
        "inputEvidence": [
            _file_record(CANDIDATES_PATH),
            _file_record(LOCI_PATH),
            _mounted_raw_record(TUMOR_BAM, expected),
            _mounted_raw_record(TUMOR_BAI, expected),
            _mounted_raw_record(NORMAL_BAM, expected),
            _mounted_raw_record(NORMAL_BAI, expected),
        ],
        "outputs": [
            _file_record(evidence_path),
            _file_record(board_path),
            _file_record(locus_path),
        ],
        "boardSummary": {
            "candidateRows": len(board_rows),
            "partialEvidenceRows": sum(row["overall_status"] == "partial_evidence" for row in board_rows),
            "readyRows": sum(row["overall_status"] == "ready" for row in board_rows),
            "callableRows": sum(row["callability_status"] == "callable" for row in dna_rows),
            "trop2TumorReads": counts[(0, "tumor")],
            "trop2NormalReads": counts[(0, "normal")],
            "trop2Status": trop2.get("overall_status", ""),
            "trop2CandidateClass": trop2.get("candidate_class", ""),
            "trop2RnaStatus": trop2.get("rna_status", ""),
            "trop2ProteinStatus": trop2.get("protein_status", ""),
        },
        "boundary": (
            "Modal consumed public mounted raw BAM indexes for DNA locus callability only; "
            "raw BAM range counts do not call SNVs, CNVs, HLA loss, RNA expression, "
            "surface protein abundance, or drug sensitivity."
        ),
    }
    packet_path = OUTPUT_DIR / "modal_target_packet.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    packet["outputs"].append(_file_record(packet_path))
    return json.dumps(packet, indent=2, sort_keys=True)


@app.function(
    image=image,
    volumes={
        MOUNT_PATH.as_posix(): s3_mount,
        RAW_MOUNT_PATH.as_posix(): raw_mount,
    },
    timeout=600,
    single_use_containers=True,
    restrict_modal_access=True,
)
def build_modal_raw_multiomic_target_packet(run_id: str, approval_token: str = "") -> str:
    if approval_token != "public-data":
        raise RuntimeError("approval_token must be 'public-data' before the raw ImmunoID BAM mounts are used")

    from diana_omics import target_discovery
    from diana_omics.commands.target_discovery import build_rosalind_target_packet as packet_builder

    raw_manifest = _read_csv(RAW_MOUNT_PATH / "manifest.csv")
    expected = {row["relative_path"]: row for row in raw_manifest}
    for relative in (TUMOR_BAM, TUMOR_BAI, NORMAL_BAM, NORMAL_BAI, RNA_BAM, RNA_BAI):
        _require_raw_object(relative, expected)

    candidates = _read_csv(CANDIDATES_PATH)
    loci = _read_csv(LOCI_PATH)
    tumor_bam = RAW_MOUNT_PATH / TUMOR_BAM
    tumor_bai = RAW_MOUNT_PATH / TUMOR_BAI
    normal_bam = RAW_MOUNT_PATH / NORMAL_BAM
    normal_bai = RAW_MOUNT_PATH / NORMAL_BAI
    rna_bam = RAW_MOUNT_PATH / RNA_BAM
    rna_bai = RAW_MOUNT_PATH / RNA_BAI

    dna_count_inputs = []
    rna_count_inputs = []
    for index, locus in enumerate(loci):
        region = f"{locus['contig']}:{locus['start']}-{locus['end']}"
        dna_count_inputs.append((index, "tumor", tumor_bam, tumor_bai, region))
        dna_count_inputs.append((index, "normal", normal_bam, normal_bai, region))
        rna_count_inputs.append((index, "rna", rna_bam, rna_bai, region))

    dna_counts: dict[tuple[int, str], int] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for index, role, reads in executor.map(_count_target, dna_count_inputs):
            dna_counts[(index, role)] = reads

    rna_counts: dict[int, int] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for index, _role, reads in executor.map(_count_target, rna_count_inputs):
            rna_counts[index] = reads

    dna_rows: list[dict[str, str]] = []
    rna_rows: list[dict[str, str]] = []
    for index, locus in enumerate(loci):
        tumor_reads = dna_counts[(index, "tumor")]
        normal_reads = dna_counts[(index, "normal")]
        rna_reads = rna_counts[index]
        region = f"{locus['contig']}:{locus['start']}-{locus['end']}"
        dna_rows.append(
            {
                "target_id": locus["target_id"],
                "gene_symbol": locus["gene_symbol"],
                "callability_status": "callable" if tumor_reads >= 10 and normal_reads >= 10 else "missing",
                "copy_number_status": "no_call",
                "variant_effect": "no_call",
                "hla_loss_status": "no_call",
                "evidence_detail": (
                    f"Modal mounted-S3 hs37d5 DNA locus {region}; "
                    f"tumor_reads={tumor_reads}; normal_reads={normal_reads}; "
                    "indexed BAM range-read callability only; variant, CNV, and HLA-loss evidence remain no_call."
                ),
            }
        )
        rna_rows.append(
            {
                "target_id": locus["target_id"],
                "gene_symbol": locus["gene_symbol"],
                "rna_status": "detected" if rna_reads >= 10 else "no_call",
                "read_count": str(rna_reads),
                "evidence_detail": (
                    f"Modal mounted-S3 hs37d5 RNA locus {region}; "
                    f"tumor_rna_reads={rna_reads}; "
                    "unnormalized indexed RNA BAM range-read support only; TPM, malignant-cell heterogeneity, "
                    "surface protein abundance, and drug sensitivity remain unproven."
                ),
            }
        )

    locus_rows, board_rows = target_discovery.build_dna_board(candidates, dna_rows, rna_rows)
    board_errors = target_discovery.validate_candidate_board(board_rows)
    if board_errors:
        raise RuntimeError("candidate board failed validation: " + "; ".join(board_errors))

    OUTPUT_DIR.mkdir(exist_ok=True)
    evidence_path = OUTPUT_DIR / "target_dna_evidence.csv"
    rna_path = OUTPUT_DIR / "rna_target_expression_summary.csv"
    board_path = OUTPUT_DIR / "candidate_target_board.csv"
    locus_path = OUTPUT_DIR / "dna_target_locus_summary.csv"
    followup_path = OUTPUT_DIR / "orthogonal_followup.csv"
    validation_path = OUTPUT_DIR / "sample_validation_summary.csv"
    research_path = OUTPUT_DIR / "research_context_sources.json"
    index_path = OUTPUT_DIR / "input_evidence_index.json"
    manifest_path = OUTPUT_DIR / "run_manifest.json"
    reviewer_path = OUTPUT_DIR / "reviewer_packet.md"
    next_actions_path = OUTPUT_DIR / "next_actions.md"
    _write_csv(evidence_path, dna_rows, target_discovery.DNA_EVIDENCE_COLUMNS)
    _write_csv(rna_path, rna_rows, target_discovery.RNA_EVIDENCE_COLUMNS)
    _write_csv(board_path, board_rows, target_discovery.CANDIDATE_BOARD_COLUMNS)
    _write_csv(locus_path, locus_rows, [
        "target_id",
        "gene_symbol",
        "dna_status",
        "copy_number_status",
        "variant_effect",
        "hla_loss_status",
        "evidence_detail",
    ])
    followup_rows = [
        {
            "target_id": row["target_id"],
            "gene_symbol": row["gene_symbol"],
            "recommended_followup": row["recommended_followup"],
            "reason": row["sample_blockers"],
        }
        for row in board_rows
        if row["overall_status"] in {"partial_evidence", "blocked", "no_call"}
    ]
    research_rows = packet_builder.research_context_rows(candidates)
    validation_rows = [
        {
            "status": "passed",
            "candidate_count": len(candidates),
            "board_row_count": len(board_rows),
            "ready_count": sum(1 for row in board_rows if row["overall_status"] == "ready"),
            "partial_evidence_count": sum(1 for row in board_rows if row["overall_status"] == "partial_evidence"),
            "blocked_count": sum(1 for row in board_rows if row["overall_status"] == "blocked"),
            "not_supported_count": sum(1 for row in board_rows if row["overall_status"] == "not_supported"),
            "boundary": "Target packets rank follow-up hypotheses; they do not authorize treatment decisions.",
        }
    ]
    _write_csv(followup_path, followup_rows, ["target_id", "gene_symbol", "recommended_followup", "reason"])
    _write_csv(
        validation_path,
        validation_rows,
        [
            "status",
            "candidate_count",
            "board_row_count",
            "ready_count",
            "partial_evidence_count",
            "blocked_count",
            "not_supported_count",
            "boundary",
        ],
    )
    _write_json(
        research_path,
        {
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "no_call",
            "rows": research_rows,
            "boundary": "External research context is recorded after sample evidence and cannot rescue failed or missing sample lanes.",
        },
    )
    _write_json(
        index_path,
        {
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "passed",
            "rows": [
                _file_record(CANDIDATES_PATH),
                _file_record(LOCI_PATH),
                _file_record(evidence_path),
                _file_record(rna_path),
                _file_record(board_path),
                _file_record(locus_path),
            ],
        },
    )
    _write_json(
        manifest_path,
        {
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "passed",
            "sampleOrCohort": "echo_personalis",
            "runId": run_id,
            "outputs": [
                "sample_validation_summary.csv",
                "dna_target_locus_summary.csv",
                "rna_target_expression_summary.csv",
                "candidate_target_board.csv",
                "orthogonal_followup.csv",
                "research_context_sources.json",
                "reviewer_packet.md",
                "next_actions.md",
            ],
            "boundary": "Pan-target Rosalind discovery is research-use follow-up triage.",
        },
    )
    _write_text(reviewer_path, packet_builder.reviewer_packet("echo_personalis", run_id, validation_rows[0], board_rows, research_rows))
    _write_text(next_actions_path, packet_builder.next_actions(followup_rows))

    trop2 = next((row for row in board_rows if row["target_id"] == "trop2"), {})
    output_paths = [
        evidence_path,
        rna_path,
        board_path,
        locus_path,
        followup_path,
        validation_path,
        research_path,
        index_path,
        manifest_path,
        reviewer_path,
        next_actions_path,
    ]
    packet = {
        "schema": "diana_modal_target_packet.v1",
        "status": "partial_evidence",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "runId": run_id,
        "execution": {
            "runtime": "modal",
            "app": APP_NAME,
            "s3Mount": "modal.CloudBucketMount",
            "rawDataMounted": True,
            "rnaDataMounted": True,
            "rawS3Prefix": f"s3://diana-omics-raw-inputs-172630973301-us-east-1/{RAW_PREFIX}",
            "inputPath": RAW_MOUNT_PATH.as_posix(),
            "outputPath": OUTPUT_DIR.as_posix(),
        },
        "inputEvidence": [
            _file_record(CANDIDATES_PATH),
            _file_record(LOCI_PATH),
            _mounted_raw_record(TUMOR_BAM, expected),
            _mounted_raw_record(TUMOR_BAI, expected),
            _mounted_raw_record(NORMAL_BAM, expected),
            _mounted_raw_record(NORMAL_BAI, expected),
            _mounted_raw_record(RNA_BAM, expected),
            _mounted_raw_record(RNA_BAI, expected),
        ],
        "outputs": [_file_record(path) for path in output_paths],
        "boardSummary": {
            "candidateRows": len(board_rows),
            "partialEvidenceRows": sum(row["overall_status"] == "partial_evidence" for row in board_rows),
            "readyRows": sum(row["overall_status"] == "ready" for row in board_rows),
            "callableRows": sum(row["callability_status"] == "callable" for row in dna_rows),
            "rnaEvidenceRows": len(rna_rows),
            "rnaPartialEvidenceRows": sum(row["rna_status"] == "detected" for row in rna_rows),
            "trop2TumorReads": dna_counts[(0, "tumor")],
            "trop2NormalReads": dna_counts[(0, "normal")],
            "trop2RnaReads": rna_counts[0],
            "trop2Status": trop2.get("overall_status", ""),
            "trop2CandidateClass": trop2.get("candidate_class", ""),
            "trop2RnaStatus": trop2.get("rna_status", ""),
            "trop2ProteinStatus": trop2.get("protein_status", ""),
        },
        "boundary": (
            "Modal consumed public mounted raw BAM indexes for DNA locus callability and unnormalized "
            "RNA expression support only; raw BAM range counts do not call SNVs, CNVs, HLA loss, "
            "surface protein abundance, malignant-cell heterogeneity, or drug sensitivity."
        ),
    }
    packet_path = OUTPUT_DIR / "modal_target_packet.json"
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    packet["outputs"].append(_file_record(packet_path))
    return json.dumps(packet, indent=2, sort_keys=True)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: "" if row.get(column) is None else row.get(column) for column in columns})


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")


def _file_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _require_raw_object(relative: str, expected: Mapping[str, Mapping[str, str]]) -> None:
    if relative not in expected:
        raise RuntimeError(f"{relative} is missing from the raw delivery manifest")
    path = RAW_MOUNT_PATH / relative
    expected_size = int(expected[relative]["size_bytes"])
    if not path.is_file():
        raise RuntimeError(f"{path} is missing from the mounted raw bucket")
    if path.stat().st_size != expected_size:
        raise RuntimeError(f"{relative} size does not match the raw delivery manifest")


def _mounted_raw_record(relative: str, expected: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    row = expected[relative]
    return {
        "path": (RAW_MOUNT_PATH / relative).as_posix(),
        "bytes": int(row["size_bytes"]),
        "sha256": row["sha256"],
    }


def _count_target(args: tuple[int, str, Path, Path, str]) -> tuple[int, str, int]:
    index, role, bam, bai, region = args
    result = subprocess.run(
        ["samtools", "view", "-c", "-X", bam.as_posix(), bai.as_posix(), region],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    return index, role, int(result.stdout.strip())
