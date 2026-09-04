from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import modal

APP_NAME = "diana-rosalind-rnaseq-trop2"
RAW_MOUNT_PATH = Path("/s3/raw")
RESULTS_MOUNT_PATH = Path("/s3/results")
RAW_BUCKET = "diana-omics-raw-inputs-172630973301-us-east-1"
RAW_PREFIX = "diana/inbox/2026-07-14-echo-personalis/data/immunoid/"
RESULTS_BUCKET = "diana-omics-private-results-172630973301-us-east-1"
RESULTS_PREFIX = "modal/rosalind-rnaseq-trop2/"

FASTQ_1 = "E019_S01/RNA_Pipeline/FASTQ/RNA_E019_S01_tumor_rna_reads1.fastq.gz"
FASTQ_2 = "E019_S01/RNA_Pipeline/FASTQ/RNA_E019_S01_tumor_rna_reads2.fastq.gz"
RECAL_BAM = "E019_S01/RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.recal.sorted.bam"
RECAL_BAI = "E019_S01/RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.recal.sorted.bam.bai"
PRE_BQSR_BAM = "E019_S01/RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.sorted.bam"
PRE_BQSR_BAI = "E019_S01/RNA_Pipeline/Alignments/RNA_E019_S01_tumor_rna_aligned.sorted.bam.bai"
VENDOR_CHECKSUMS = "E019_S01/checksum.txt"

SOURCE_MANIFEST = {
    FASTQ_1: {
        "bytes": 9_465_843_803,
        "vendorMd5": "cbdea4afbc7359a39c6ffb0fcaf3a6f2",
        "sha256": "272c5f5f16ebfc1bde50f1b64d3c855cb328c5c60a2597d9769603cba0f9a3f5",
        "versionId": "1YAZ8n1nvfdkFlxfIOg24y7egbO.YZFx",
    },
    FASTQ_2: {
        "bytes": 9_630_262_591,
        "vendorMd5": "dfbae08c65ed5cff710289a590545537",
        "sha256": "218b487fe5341842a6a353fe5f3c8a21e4c95c05508525670872247d8eba6a80",
        "versionId": "9FSDHC2EVgunzHphA_3YzHUTO4owsdLb",
    },
    RECAL_BAM: {
        "bytes": 24_905_892_448,
        "vendorMd5": "fba901d6e8e3198f84c4feda38a0d377",
        "sha256": "cbca1be437a294b07f2d2fe5ead19cb737eb0592abfc0984c829994ce933e7e2",
        "versionId": "g9JfmajCh6R1ObwwtC.DA1rts0uPNGIJ",
    },
    RECAL_BAI: {
        "bytes": 3_411_312,
        "vendorMd5": "e84e598da54687c82c10bbcf22b4d8eb",
        "sha256": "309aa3eaa3240e98a56b572dca485b36db04ba2b4e02c4ce2a484da574cc57c4",
        "versionId": "1zcicEZYfAVK9YiR.PUKtVpZqrKuqoxu",
    },
    PRE_BQSR_BAM: {
        "bytes": 9_769_769_184,
        "vendorMd5": "4bde7113fd6e810dbf6a96ab3bb95a82",
        "sha256": "422326debfd42ba0639898d646a5961aa780b954a2de08a7f184d28ed84e4b95",
        "versionId": "ntUadPKrIcUDmSfTqyk37GClAHg8Y8CC",
    },
    PRE_BQSR_BAI: {
        "bytes": 12_571_960,
        "vendorMd5": "f9525043480b26d7916710a4f38b8409",
        "sha256": "7cae2b1fd89b1b5657c08213fe801b1f63b132a01a71cfa6bd844e2b9db884b4",
        "versionId": "_BmbDSZGlnaaCcvzrEVFNBWim8SYKoZQ",
    },
}

TACSTD2 = {
    "geneSymbol": "TACSTD2",
    "proteinName": "TROP-2",
    "ensemblGeneId": "ENSG00000184292",
    "canonicalTranscript": "ENST00000371225.2",
    "reference": "GRCh37/hs37d5",
    "contig": "1",
    "start": 59_041_099,
    "end": 59_043_166,
    "strand": "-",
    "annotationSource": "https://grch37.rest.ensembl.org/lookup/symbol/homo_sapiens/TACSTD2?expand=1",
}
TACSTD2["lengthBp"] = TACSTD2["end"] - TACSTD2["start"] + 1


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


AWS_SECRET_NAME = _env("MODAL_AWS_SECRET_NAME", "onco-omics-use1")

app = modal.App(APP_NAME)
aws_secret = modal.Secret.from_name(AWS_SECRET_NAME)
raw_mount = modal.CloudBucketMount(
    RAW_BUCKET,
    key_prefix=RAW_PREFIX,
    secret=aws_secret,
    read_only=True,
)
results_mount = modal.CloudBucketMount(
    RESULTS_BUCKET,
    key_prefix=RESULTS_PREFIX,
    secret=aws_secret,
)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("samtools", "fastqc")
    .pip_install("multiqc==1.31", "matplotlib==3.10.6")
    .add_local_dir("src/diana_omics", remote_path="/opt/diana/src/diana_omics", copy=True)
    .env({"MPLBACKEND": "Agg", "PYTHONPATH": "/opt/diana/src"})
)


def _path(relative: str) -> Path:
    path = RAW_MOUNT_PATH / relative
    if not path.is_file():
        raise RuntimeError(f"required input is missing from the mounted prefix: {relative}")
    expected_size = int(SOURCE_MANIFEST.get(relative, {}).get("bytes", path.stat().st_size))
    observed_size = path.stat().st_size
    if observed_size != expected_size:
        raise RuntimeError(f"input size mismatch for {relative}: expected {expected_size}, observed {observed_size}")
    return path


def _run(command: Sequence[str], *, stdout_path: Path | None = None, stderr_path: Path | None = None) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if stdout_path is not None:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(result.stdout, encoding="utf-8")
    if stderr_path is not None:
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        stderr = result.stderr.strip()[-2_000:]
        raise RuntimeError(f"command failed with exit code {result.returncode}: {command[0]}: {stderr}")
    return result.stdout


def _samtools_count(bam: Path, *, excluded_flags: int, minimum_mapq: int = 0) -> int:
    region = f"{TACSTD2['contig']}:{TACSTD2['start']}-{TACSTD2['end']}"
    output = _run(
        [
            "samtools",
            "view",
            "-@",
            "4",
            "-c",
            "-F",
            str(excluded_flags),
            "-q",
            str(minimum_mapq),
            bam.as_posix(),
            region,
        ]
    )
    return int(output.strip())


def _unique_templates(bam: Path) -> int:
    region = f"{TACSTD2['contig']}:{TACSTD2['start']}-{TACSTD2['end']}"
    output = _run(
        ["samtools", "view", "-@", "4", "-F", str(0xF04), "-q", "20", bam.as_posix(), region]
    )
    return len({line.split("\t", 1)[0] for line in output.splitlines() if line})


def _vendor_hashes(path: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            continue
        digest, relative = fields
        relative = relative.lstrip("*./")
        if len(digest) in {32, 64}:
            hashes[relative] = digest
    return hashes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    resolved_path = path.resolve()
    resolved_root = root.resolve()
    if resolved_root not in resolved_path.parents:
        raise ValueError(f"artifact is outside the run directory: {path}")
    return {
        "path": resolved_path.relative_to(resolved_root).as_posix(),
        "bytes": resolved_path.stat().st_size,
        "sha256": _sha256(resolved_path),
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _fastqc_records(fastqc_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    module_rows: list[dict[str, str]] = []
    basic_rows: list[dict[str, str]] = []
    for archive_path in sorted(fastqc_dir.glob("*_fastqc.zip")):
        sample = archive_path.name.removesuffix("_fastqc.zip")
        with zipfile.ZipFile(archive_path) as archive:
            summary_name = next(name for name in archive.namelist() if name.endswith("/summary.txt"))
            data_name = next(name for name in archive.namelist() if name.endswith("/fastqc_data.txt"))
            for line in archive.read(summary_name).decode("utf-8").splitlines():
                status, module, _filename = line.split("\t", 2)
                module_rows.append({"sample": sample, "module": module, "status": status.lower()})
            in_basic = False
            for line in archive.read(data_name).decode("utf-8").splitlines():
                if line.startswith(">>Basic Statistics"):
                    in_basic = True
                    continue
                if in_basic and line == ">>END_MODULE":
                    break
                if in_basic and line and not line.startswith("#"):
                    metric, value = line.split("\t", 1)
                    basic_rows.append({"sample": sample, "metric": metric, "value": value})
    if len({row["sample"] for row in basic_rows}) != 2:
        raise RuntimeError("FastQC did not produce two readable paired-end reports")
    return module_rows, basic_rows


@app.function(
    image=image,
    volumes={RAW_MOUNT_PATH.as_posix(): raw_mount},
    cpu=4,
    memory=8192,
    timeout=900,
    region="us-east",
    single_use_containers=True,
    restrict_modal_access=True,
)
def preflight_inputs() -> str:
    from diana_omics.trop2_rna import compare_counts, parse_idxstats

    paths = {relative: _path(relative) for relative in SOURCE_MANIFEST}
    checksums = _vendor_hashes(_path(VENDOR_CHECKSUMS))
    for relative, expected in SOURCE_MANIFEST.items():
        vendor_relative = relative.removeprefix("E019_S01/")
        if checksums.get(vendor_relative) != expected["vendorMd5"]:
            raise RuntimeError(f"vendor checksum record mismatch for {relative}")

    quickcheck: dict[str, str] = {}
    idxstats: dict[str, Any] = {}
    target_counts: dict[str, int] = {}
    for label, bam_relative in (("recalibrated", RECAL_BAM), ("pre_bqsr", PRE_BQSR_BAM)):
        bam = paths[bam_relative]
        _run(["samtools", "quickcheck", "-vv", bam.as_posix()])
        quickcheck[label] = "passed"
        idxstats[label] = parse_idxstats(_run(["samtools", "idxstats", "-@", "2", bam.as_posix()]))
        target_counts[label] = _samtools_count(bam, excluded_flags=0x904)

    recal_chr1 = next(row for row in idxstats["recalibrated"]["contigs"] if row["contig"] == "1")
    if recal_chr1["length"] != 249_250_621:
        raise RuntimeError("RNA BAM chromosome 1 length is not the expected GRCh37/hs37d5 length")

    return json.dumps(
        {
            "status": "preflight_passed",
            "reference": "hs37d5",
            "quickcheck": quickcheck,
            "targetPrimaryReads": target_counts,
            "targetCountComparison": compare_counts(target_counts["recalibrated"], target_counts["pre_bqsr"]),
            "totalMappedAlignments": {
                label: value["totalMappedAlignments"] for label, value in idxstats.items()
            },
        },
        indent=2,
        sort_keys=True,
    )


@app.function(
    image=image,
    cpu=2,
    memory=4096,
    timeout=300,
    region="us-east",
    single_use_containers=True,
    restrict_modal_access=True,
)
def preflight_postprocessing() -> str:
    import matplotlib.pyplot as plt

    work_dir = Path("/tmp/postprocess-preflight")
    plots_dir = work_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=False)
    plt.figure(figsize=(2, 2))
    plt.plot([0, 1], [0, 1])
    plt.tight_layout()
    plot_path = plots_dir / "smoke.png"
    plt.savefig(plot_path, dpi=72)
    plt.close()

    receipt_path = work_dir / "receipt.json"
    _write_json(
        receipt_path,
        {
            "samtools": _run(["samtools", "--version"]).splitlines()[0],
            "fastqc": _run(["fastqc", "--version"]).strip(),
            "multiqc": importlib.metadata.version("multiqc"),
            "matplotlib": importlib.metadata.version("matplotlib"),
        },
    )
    return json.dumps(
        {
            "status": "postprocessing_preflight_passed",
            "artifacts": [_artifact(path, work_dir) for path in (plot_path, receipt_path)],
        },
        indent=2,
        sort_keys=True,
    )


@app.function(
    image=image,
    volumes={RAW_MOUNT_PATH.as_posix(): raw_mount, RESULTS_MOUNT_PATH.as_posix(): results_mount},
    cpu=16,
    memory=65536,
    timeout=7_200,
    region="us-east",
    single_use_containers=True,
    restrict_modal_access=True,
)
def run_trop2_rna(run_id: str) -> str:
    import matplotlib.pyplot as plt

    from diana_omics.trop2_rna import (
        build_expression_metrics,
        compare_counts,
        parse_depth,
        parse_idxstats,
        require_run_id,
        summarize_depth,
    )

    run_id = require_run_id(run_id)
    remote_run_dir = RESULTS_MOUNT_PATH / "runs" / run_id
    if remote_run_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing run prefix: {run_id}")

    run_dir = Path("/tmp") / f"{APP_NAME}-{run_id}"
    run_dir.mkdir(exist_ok=False)
    logs_dir = run_dir / "logs"
    fastqc_dir = run_dir / "qc" / "fastqc"
    multiqc_dir = run_dir / "qc" / "multiqc"
    for output_dir in (
        logs_dir,
        fastqc_dir,
        multiqc_dir,
        run_dir / "qc" / "bam",
        run_dir / "tables",
        run_dir / "plots",
        run_dir / "reviews",
    ):
        output_dir.mkdir(parents=True, exist_ok=True)

    paths = {relative: _path(relative) for relative in SOURCE_MANIFEST}
    vendor_checksums_path = _path(VENDOR_CHECKSUMS)
    vendor_hashes = _vendor_hashes(vendor_checksums_path)
    for relative, expected in SOURCE_MANIFEST.items():
        vendor_relative = relative.removeprefix("E019_S01/")
        if vendor_hashes.get(vendor_relative) != expected["vendorMd5"]:
            raise RuntimeError(f"vendor checksum record mismatch for {relative}")
    if _sha256(paths[RECAL_BAI]) != SOURCE_MANIFEST[RECAL_BAI]["sha256"]:
        raise RuntimeError("recalibrated BAM index failed direct SHA-256 verification")
    if _sha256(paths[PRE_BQSR_BAI]) != SOURCE_MANIFEST[PRE_BQSR_BAI]["sha256"]:
        raise RuntimeError("pre-BQSR BAM index failed direct SHA-256 verification")

    for bam in (paths[RECAL_BAM], paths[PRE_BQSR_BAM]):
        _run(["samtools", "quickcheck", "-vv", bam.as_posix()])

    print("Input custody and BAM quickcheck passed; collecting indexed metrics.", flush=True)
    idxstats: dict[str, Any] = {}
    target_counts: dict[str, dict[str, int]] = {}
    for label, bam_relative in (("recalibrated", RECAL_BAM), ("pre_bqsr", PRE_BQSR_BAM)):
        bam = paths[bam_relative]
        idxstats_text = _run(["samtools", "idxstats", "-@", "4", bam.as_posix()])
        _write_text(run_dir / "qc" / "bam" / f"{label}_idxstats.tsv", idxstats_text)
        idxstats[label] = parse_idxstats(idxstats_text)
        target_counts[label] = {
            "primaryRegionReads": _samtools_count(bam, excluded_flags=0x904),
            "hqNonduplicateRegionReads": _samtools_count(bam, excluded_flags=0xF04, minimum_mapq=20),
        }

    recal_chr1 = next(row for row in idxstats["recalibrated"]["contigs"] if row["contig"] == "1")
    pre_chr1 = next(row for row in idxstats["pre_bqsr"]["contigs"] if row["contig"] == "1")
    if recal_chr1["length"] != 249_250_621 or pre_chr1["length"] != 249_250_621:
        raise RuntimeError("RNA BAM contig length does not match GRCh37/hs37d5")

    selected_bam = paths[RECAL_BAM]
    header_path = run_dir / "qc" / "bam" / "recalibrated_header.sam"
    _run(["samtools", "view", "-H", selected_bam.as_posix()], stdout_path=header_path)

    print("Running raw FASTQ QC and full-BAM flagstat in parallel.", flush=True)
    fastqc_log = logs_dir / "fastqc.log"
    flagstat_path = run_dir / "qc" / "bam" / "recalibrated_flagstat.txt"
    with ThreadPoolExecutor(max_workers=2) as executor:
        fastqc_future = executor.submit(
            _run,
            [
                "fastqc",
                "--threads",
                "8",
                "--outdir",
                fastqc_dir.as_posix(),
                paths[FASTQ_1].as_posix(),
                paths[FASTQ_2].as_posix(),
            ],
            stdout_path=fastqc_log,
            stderr_path=logs_dir / "fastqc.stderr.log",
        )
        flagstat_future = executor.submit(
            _run,
            ["samtools", "flagstat", "-@", "8", selected_bam.as_posix()],
            stdout_path=flagstat_path,
            stderr_path=logs_dir / "samtools_flagstat.stderr.log",
        )
        fastqc_future.result()
        flagstat_future.result()

    print("FASTQ QC complete; building MultiQC and TROP-2 depth evidence.", flush=True)
    _run(
        ["multiqc", fastqc_dir.as_posix(), "--outdir", multiqc_dir.as_posix(), "--force"],
        stdout_path=logs_dir / "multiqc.log",
        stderr_path=logs_dir / "multiqc.stderr.log",
    )
    module_rows, basic_rows = _fastqc_records(fastqc_dir)
    _write_csv(run_dir / "qc" / "fastqc_module_status.csv", module_rows, ["sample", "module", "status"])
    _write_csv(run_dir / "qc" / "fastqc_basic_statistics.csv", basic_rows, ["sample", "metric", "value"])

    total_sequences = {
        row["sample"]: int(row["value"].replace(",", ""))
        for row in basic_rows
        if row["metric"] == "Total Sequences"
    }
    pair_status = "matched" if len(total_sequences) == 2 and len(set(total_sequences.values())) == 1 else "mismatch"

    unique_templates = _unique_templates(selected_bam)
    region = f"{TACSTD2['contig']}:{TACSTD2['start']}-{TACSTD2['end']}"
    depth_text = _run(
        [
            "samtools",
            "depth",
            "-aa",
            "-d",
            "0",
            "-Q",
            "20",
            "-q",
            "20",
            "-G",
            "0x800",
            "-r",
            region,
            selected_bam.as_posix(),
        ]
    )
    depth_path = run_dir / "tables" / "tacstd2_depth.tsv"
    _write_text(depth_path, "contig\tposition\tdepth\n" + depth_text)
    depths = parse_depth(
        depth_text,
        contig=str(TACSTD2["contig"]),
        start=int(TACSTD2["start"]),
        end=int(TACSTD2["end"]),
    )
    depth_summary = summarize_depth(depths)
    expression = build_expression_metrics(
        primary_region_reads=target_counts["recalibrated"]["primaryRegionReads"],
        hq_nonduplicate_region_reads=target_counts["recalibrated"]["hqNonduplicateRegionReads"],
        unique_hq_templates=unique_templates,
        total_index_mapped_alignments=idxstats["recalibrated"]["totalMappedAlignments"],
        gene_length_bp=int(TACSTD2["lengthBp"]),
    )
    bam_comparison = compare_counts(
        target_counts["recalibrated"]["hqNonduplicateRegionReads"],
        target_counts["pre_bqsr"]["hqNonduplicateRegionReads"],
    )

    expression_rows = []
    for label in ("recalibrated", "pre_bqsr"):
        expression_rows.append(
            {
                "gene_symbol": TACSTD2["geneSymbol"],
                "protein_name": TACSTD2["proteinName"],
                "bam_form": label,
                "reference": TACSTD2["reference"],
                "region": region,
                "gene_length_bp": TACSTD2["lengthBp"],
                "primary_region_reads": target_counts[label]["primaryRegionReads"],
                "hq_nonduplicate_region_reads": target_counts[label]["hqNonduplicateRegionReads"],
                "total_index_mapped_alignments": idxstats[label]["totalMappedAlignments"],
                "alignment_reads_per_million": (
                    target_counts[label]["primaryRegionReads"]
                    / idxstats[label]["totalMappedAlignments"]
                    * 1_000_000
                ),
                "unique_hq_templates": unique_templates if label == "recalibrated" else "not_computed",
                "approximate_fragment_rpkm": expression["approximateFragmentRpkm"] if label == "recalibrated" else "not_computed",
                "evidence_status": "partial_evidence",
            }
        )
    _write_csv(
        run_dir / "tables" / "tacstd2_expression.csv",
        expression_rows,
        list(expression_rows[0]),
    )

    positions = list(range(int(TACSTD2["start"]), int(TACSTD2["end"]) + 1))
    plt.figure(figsize=(10, 4))
    plt.plot(positions, depths, color="#7c3aed", linewidth=1)
    plt.axhline(100, color="#64748b", linestyle="--", linewidth=0.8, label="100x")
    plt.xlabel("GRCh37 chromosome 1 position")
    plt.ylabel("HQ nonduplicate read depth")
    plt.title("TACSTD2 / TROP-2 RNA alignment depth")
    plt.legend()
    plt.tight_layout()
    plt.savefig(run_dir / "plots" / "tacstd2_depth.png", dpi=180)
    plt.close()

    module_failures = sorted({row["module"] for row in module_rows if row["status"] == "fail"})
    module_warnings = sorted({row["module"] for row in module_rows if row["status"] == "warn"})
    narrow_signal_supported = (
        target_counts["recalibrated"]["hqNonduplicateRegionReads"] >= 100
        and depth_summary["fractionAtLeast10x"] >= 0.90
        and bam_comparison["status"] == "concordant"
        and pair_status == "matched"
    )
    qa_status = "passed_for_narrow_expression_signal" if narrow_signal_supported else "review_required"

    _write_json(
        run_dir / "input_evidence_index.json",
        {
            "schema": "diana_rosalind_rnaseq_trop2_input_index.v1",
            "classification": "private_human_tumor_rna",
            "sourcePrefix": f"s3://{RAW_BUCKET}/{RAW_PREFIX}",
            "sourceManifest": {
                "uri": f"s3://{RAW_BUCKET}/diana/inbox/2026-07-14-echo-personalis/manifest.csv",
                "versionId": "Wvu0g3LJg1mJIMoYUOSryNLUGSSBdqe4",
            },
            "objects": [
                {"path": relative, "s3Uri": f"s3://{RAW_BUCKET}/{RAW_PREFIX}{relative}", **record}
                for relative, record in SOURCE_MANIFEST.items()
            ],
            "directHashVerification": [RECAL_BAI, PRE_BQSR_BAI],
            "largeObjectHashPolicy": (
                "Large objects were matched to the mounted vendor MD5 ledger and bound to SHA-256 values and "
                "S3 VersionIds from the versioned intake manifest; the analysis did not re-read all large objects "
                "solely to recompute their hashes."
            ),
        },
    )
    _write_json(
        run_dir / "qa_summary.json",
        {
            "schema": "diana_rosalind_rnaseq_trop2_qa.v1",
            "status": qa_status,
            "fastqPairCountStatus": pair_status,
            "fastqcFailedModules": module_failures,
            "fastqcWarningModules": module_warnings,
            "bamQuickcheck": {"recalibrated": "passed", "preBqsr": "passed"},
            "referenceCheck": "passed_hs37d5_chr1_length",
            "bamFormCountComparison": bam_comparison,
            "depth": depth_summary,
            "expression": expression,
        },
    )
    _write_json(
        run_dir / "differential_expression_status.json",
        {
            "status": "blocked",
            "reason": "One tumor RNA sample and no contrast, biological replicates, batch design, or comparator were supplied.",
            "allowedConclusion": "Single-sample TACSTD2 alignment and QC evidence only.",
        },
    )
    _write_json(
        run_dir / "reviews" / "strategy_review.json",
        {
            "verdict": "promising_with_gaps",
            "decision": "Does this tumor RNA dataset contain reproducible TACSTD2 transcript evidence worth protein-level follow-up?",
            "chain": "tumor RNA FASTQs and indexed BAM -> FASTQ/BAM QA -> locus counts and depth -> narrow expression evidence -> orthogonal protein review",
            "smallestNextEvidence": "TROP-2 membrane IHC with malignant-cell percent positive, intensity, H-score, heterogeneity, and controls.",
            "claimBoundary": "Bulk RNA cannot identify the expressing cell compartment or establish surface-protein abundance or ADC benefit.",
        },
    )
    _write_json(
        run_dir / "reviews" / "custody_review.json",
        {
            "verdict": "usable_with_documented_gaps",
            "strengths": [
                "Manifest SHA-256 records and S3 VersionIds are preserved.",
                "The exact human-data prefix is mounted read-only.",
                "BAM indexes are directly re-hashed and both BAMs pass samtools quickcheck.",
                "Outputs land in a versioned KMS-encrypted private bucket.",
            ],
            "gaps": [
                "Library strandedness and complete library-preparation metadata are absent from the intake manifest.",
                "No normal RNA, cohort comparator, tumor purity estimate, or cell-compartment annotation is available.",
            ],
        },
    )
    _write_json(
        run_dir / "reviews" / "validation_review.json",
        {
            "verdict": "validated_for_narrower_claim" if narrow_signal_supported else "partial",
            "claim": "TACSTD2-aligned RNA reads are reproducibly present in this indexed bulk tumor RNA dataset.",
            "evidenceLevel": "internal_qc",
            "controls": ["paired FASTQ count check", "FastQC/MultiQC", "two BAM-form concordance", "MAPQ/duplicate filtering", "basewise depth"],
            "notValidated": ["TPM", "differential expression", "tumor-cell specificity", "surface protein", "drug response"],
        },
    )
    _write_json(
        run_dir / "reviews" / "governance_review.json",
        {
            "verdict": "research_only",
            "deploymentContext": "reviewer_packet",
            "requiredHumanOversight": ["bioinformatics review", "pathology review for protein assay", "oncologist review for any treatment relevance"],
            "requiredNoCallStates": ["failed FASTQ/BAM QC", "reference mismatch", "discordant BAM forms", "missing protein confirmation"],
            "highestLeverageNextArtifact": "matched TROP-2 membrane-IHC pathology report with specimen lineage and a locked scoring rubric",
        },
    )

    _write_text(
        run_dir / "summary.md",
        "\n".join(
            [
                "# Rosalind bulk RNA-seq TROP-2 exploration",
                "",
                f"Run `{run_id}` evaluated the private Personalis ImmunoID tumor RNA inputs with FastQC, MultiQC, samtools BAM QA, and focused `TACSTD2` locus counting on hs37d5.",
                "",
                f"- QA status: `{qa_status}`",
                f"- Recalibrated BAM primary TACSTD2 reads: {target_counts['recalibrated']['primaryRegionReads']:,}",
                f"- Recalibrated BAM HQ nonduplicate TACSTD2 reads: {target_counts['recalibrated']['hqNonduplicateRegionReads']:,}",
                f"- Unique HQ TACSTD2 templates: {unique_templates:,}",
                f"- Index-normalized TACSTD2 reads per million: {expression['alignmentReadsPerMillion']:.3f}",
                f"- Approximate fragment RPKM diagnostic: {expression['approximateFragmentRpkm']:.3f}",
                f"- TACSTD2 bases with at least 10x depth: {depth_summary['fractionAtLeast10x']:.1%}",
                f"- Recalibrated versus pre-BQSR count status: `{bam_comparison['status']}`",
                f"- Raw FASTQ pair count status: `{pair_status}`",
                f"- FastQC failed modules: {', '.join(module_failures) if module_failures else 'none'}",
                f"- FastQC warning modules: {', '.join(module_warnings) if module_warnings else 'none'}",
                "",
                "## Interpretation boundary",
                "",
                "This run can support only the narrow claim that reproducible `TACSTD2`-aligned transcript signal is present in this bulk tumor RNA dataset if the QA gates pass. The RPKM value is an approximate single-gene diagnostic, not Salmon/tximport TPM. There is one tumor sample, so differential expression is blocked. Bulk RNA cannot identify malignant-cell specificity, antigen heterogeneity, membrane localization, surface abundance, or treatment benefit.",
                "",
                "The next decisive measurement is controlled TROP-2 membrane IHC (or another protein-localizing assay) on a lineage-matched specimen.",
            ]
        ),
    )

    software = {
        "python": platform.python_version(),
        "samtools": _run(["samtools", "--version"]).splitlines()[0],
        "fastqc": _run(["fastqc", "--version"]).strip(),
        "multiqc": importlib.metadata.version("multiqc"),
        "matplotlib": importlib.metadata.version("matplotlib"),
    }
    artifact_paths = sorted(
        path for path in run_dir.rglob("*") if path.is_file() and path.name not in {"artifact_index.json", "run_manifest.json"}
    )
    artifact_records = [_artifact(path, run_dir) for path in artifact_paths]
    artifact_index_path = run_dir / "artifact_index.json"
    _write_json(
        artifact_index_path,
        {"schema": "diana_rosalind_rnaseq_trop2_artifact_index.v1", "runId": run_id, "artifacts": artifact_records},
    )
    run_manifest_path = run_dir / "run_manifest.json"
    _write_json(
        run_manifest_path,
        {
            "schema": "diana_rosalind_rnaseq_trop2_run.v1",
            "status": "completed_research_analysis",
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "runId": run_id,
            "dataClassification": "private_human_tumor_rna",
            "question": "Does this ImmunoID bulk tumor RNA dataset contain reproducible TACSTD2/TROP-2 transcript evidence worth protein-level follow-up?",
            "execution": {
                "runtime": "modal",
                "app": APP_NAME,
                "region": "us-east",
                "cpu": 16,
                "memoryMiB": 65536,
                "ephemeralDisk": "modal_default",
                "inputMount": "modal.CloudBucketMount_read_only_exact_prefix",
                "outputMount": "modal.CloudBucketMount_private_kms_versioned",
            },
            "software": software,
            "annotation": TACSTD2,
            "thresholds": {
                "minimumMapq": 20,
                "minimumBaseQualityForDepth": 20,
                "excludedFlags": "UNMAP|SECONDARY|DUP|SUPPLEMENTARY",
                "minimumHqReadsForNarrowSignal": 100,
                "minimumFractionBasesAt10x": 0.90,
                "maximumBamFormRelativeDifference": 0.02,
            },
            "outputPrefix": f"s3://{RESULTS_BUCKET}/{RESULTS_PREFIX}runs/{run_id}/",
            "qaStatus": qa_status,
            "evidenceStatus": "partial_evidence",
            "artifactIndex": _artifact(artifact_index_path, run_dir),
            "evidenceBoundary": (
                "Single-sample bulk-RNA internal QC only; no differential expression, malignant-cell specificity, "
                "surface-protein abundance, ADC eligibility, response prediction, or treatment recommendation."
            ),
        },
    )

    remote_run_dir.mkdir(parents=True)
    for source_path in [*artifact_paths, artifact_index_path]:
        relative = source_path.relative_to(run_dir)
        destination = remote_run_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("rb") as source_handle, destination.open("wb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=8 * 1024 * 1024)
    destination_manifest = remote_run_dir / "run_manifest.json"
    with run_manifest_path.open("rb") as source_handle, destination_manifest.open("wb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=8 * 1024 * 1024)

    return json.dumps(
        {
            "status": "completed_research_analysis",
            "runId": run_id,
            "qaStatus": qa_status,
            "evidenceStatus": "partial_evidence",
            "target": "TACSTD2/TROP-2",
            "primaryRegionReads": expression["primaryRegionReads"],
            "hqNonduplicateRegionReads": expression["hqNonduplicateRegionReads"],
            "uniqueHqTemplates": expression["uniqueHqTemplates"],
            "alignmentReadsPerMillion": expression["alignmentReadsPerMillion"],
            "approximateFragmentRpkm": expression["approximateFragmentRpkm"],
            "fractionBasesAt10x": depth_summary["fractionAtLeast10x"],
            "bamFormCountStatus": bam_comparison["status"],
            "fastqPairCountStatus": pair_status,
            "outputPrefix": f"s3://{RESULTS_BUCKET}/{RESULTS_PREFIX}runs/{run_id}/",
            "runManifestSha256": _sha256(run_manifest_path),
        },
        indent=2,
        sort_keys=True,
    )


@app.local_entrypoint()
def main(run_id: str = "", preflight_only: bool = False) -> None:
    if preflight_only:
        print(preflight_inputs.remote())
        print(preflight_postprocessing.remote())
        return
    resolved_run_id = run_id or f"immunoid-trop2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    print(run_trop2_rna.remote(resolved_run_id))
