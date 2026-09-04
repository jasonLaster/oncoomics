from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import modal

APP_NAME = "diana-adc-atlas-patient-bridge"
RAW_BUCKET = "diana-omics-raw-inputs-172630973301-us-east-1"
RAW_PREFIX = "diana/inbox/2026-07-14-echo-personalis/data/immunoid/"
RESULTS_BUCKET = "diana-omics-private-results-172630973301-us-east-1"
RESULTS_PREFIX = "modal/pan-cancer-adc-atlas/patient-bridge/"
RAW_MOUNT_PATH = Path("/s3/raw")
RESULTS_MOUNT_PATH = Path("/s3/results")
REFERENCE_MOUNT_PATH = Path("/reference")
REFERENCE_ID = "gencode-v23-grch38-primary-full-decoy-salmon-1.10.3"
REFERENCE_DIR = REFERENCE_MOUNT_PATH / REFERENCE_ID

FASTQ_1 = "E019_S01/RNA_Pipeline/FASTQ/RNA_E019_S01_tumor_rna_reads1.fastq.gz"
FASTQ_2 = "E019_S01/RNA_Pipeline/FASTQ/RNA_E019_S01_tumor_rna_reads2.fastq.gz"
SOURCE_OBJECTS = {
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
}

REFERENCE_SOURCES = {
    "gencode.v23.annotation.gtf.gz": {
        "url": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_23/gencode.v23.annotation.gtf.gz",
        "bytes": 38_449_390,
        "md5": "4c06cb6f2eb5d4e1e161f895be32c33b",
    },
    "gencode.v23.transcripts.fa.gz": {
        "url": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_23/gencode.v23.transcripts.fa.gz",
        "bytes": 47_012_866,
        "md5": "98ba7a199a2bc9b0a707d9567edb4aec",
    },
    "GRCh38.primary_assembly.genome.fa.gz": {
        "url": "https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_23/GRCh38.primary_assembly.genome.fa.gz",
        "bytes": 844_691_642,
        "md5": "5d6d8cc23bea6d1beb18efa041c55496",
    },
}

TARGET_MANIFEST_LOCAL = Path("/opt/diana/manifests/adc_atlas_targets_v1.csv")
CANCER_REFERENCE_LOCAL = Path("/opt/diana/atlas/cancer_expression_summary.csv")
BRCA_COHORT = "Breast Invasive Carcinoma"
MINIMUM_MAPPING_RATE = 50.0
MINIMUM_TX2GENE_FRACTION = 0.999
GENE_TPM_SUM_RANGE = (999_000.0, 1_001_000.0)

REVIEW_BUNDLE_PATHS = (
    "artifact_index.json",
    "run_manifest.json",
    "input_evidence_index.json",
    "reference_manifest.json",
    "qa_summary.json",
    "summary.md",
    "tables/adc_target_expression.csv",
    "tables/adc_target_breast_comparison.csv",
    "tables/payload_context_expression.csv",
    "versions/software.json",
    "salmon/aux_info/meta_info.json",
    "salmon/lib_format_counts.json",
    "salmon/logs/salmon_quant.log",
)

PAYLOAD_CONTEXT_GENES = (
    ("TOP1", "topoisomerase-I payload target"),
    ("SLFN11", "DNA-damage response sensitization context"),
    ("ABCB1", "drug-efflux resistance context"),
    ("ABCG2", "drug-efflux resistance context"),
    ("TUBB3", "microtubule payload context"),
    ("LAMP1", "lysosomal trafficking context"),
    ("CTSD", "lysosomal protease context"),
    ("RAB5A", "early-endosome trafficking context"),
    ("RAB7A", "late-endosome trafficking context"),
    ("BAX", "apoptosis context"),
    ("BCL2", "apoptosis resistance context"),
)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


AWS_SECRET_NAME = _env("MODAL_AWS_SECRET_NAME", "onco-omics-use1")
app = modal.App(APP_NAME)
aws_secret = modal.Secret.from_name(AWS_SECRET_NAME)
raw_mount = modal.CloudBucketMount(RAW_BUCKET, key_prefix=RAW_PREFIX, secret=aws_secret, read_only=True)
results_mount = modal.CloudBucketMount(RESULTS_BUCKET, key_prefix=RESULTS_PREFIX, secret=aws_secret)
reference_volume = modal.Volume.from_name("diana-adc-atlas-gencode-v23", create_if_missing=True)
image = (
    modal.Image.micromamba(python_version="3.12")
    .apt_install("ca-certificates", "curl", "gzip")
    .micromamba_install("salmon=1.10.3", channels=["conda-forge", "bioconda"])
    .add_local_file(
        "src/diana_omics/adc_patient_bridge.py",
        remote_path="/opt/diana/src/diana_omics/adc_patient_bridge.py",
        copy=True,
    )
    .add_local_file("manifests/adc_atlas_targets_v1.csv", remote_path=TARGET_MANIFEST_LOCAL.as_posix(), copy=True)
    .add_local_file(
        "results/pan_cancer_adc_atlas/v1/cancer_expression_summary.csv",
        remote_path=CANCER_REFERENCE_LOCAL.as_posix(),
        copy=True,
    )
    .env({"PYTHONPATH": "/opt/diana/src"})
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str] | None = None) -> None:
    resolved_columns = list(columns or dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=resolved_columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter=delimiter)]


def _run(command: Sequence[str], *, stdout_path: Path | None = None, stderr_path: Path | None = None) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if stdout_path is not None:
        _write_text(stdout_path, result.stdout)
    if stderr_path is not None:
        _write_text(stderr_path, result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}) {command[0]}: {result.stderr.strip()[-3000:]}")
    return result.stdout


def _safe_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        raise ValueError("run_id must be 1-128 safe identifier characters")
    return run_id


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "runtime-managed-no-distribution-metadata"


def _input_path(relative: str) -> Path:
    path = RAW_MOUNT_PATH / relative
    if not path.is_file():
        raise RuntimeError(f"required input is missing: {relative}")
    observed_size = path.stat().st_size
    expected_size = int(SOURCE_OBJECTS[relative]["bytes"])
    if observed_size != expected_size:
        raise RuntimeError(f"input size mismatch for {relative}: expected {expected_size}, observed {observed_size}")
    return path


def _artifact(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _download_reference(destination: Path, source: Mapping[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(str(source["url"]), headers={"User-Agent": f"{APP_NAME}/1.0"})
    with urllib.request.urlopen(request, timeout=900) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=8 * 1024 * 1024)
    observed_size = destination.stat().st_size
    observed_md5 = _md5(destination)
    if observed_size != int(source["bytes"]) or observed_md5 != source["md5"]:
        raise RuntimeError(f"reference integrity mismatch for {destination.name}")
    return {
        **source,
        "observedBytes": observed_size,
        "observedMd5": observed_md5,
        "observedSha256": _sha256(destination),
    }


@app.function(
    image=image,
    volumes={REFERENCE_MOUNT_PATH.as_posix(): reference_volume},
    cpu=16,
    memory=65536,
    timeout=3600,
    region="us-east",
    single_use_containers=True,
    restrict_modal_access=True,
)
def prepare_reference() -> str:
    ready_path = REFERENCE_DIR / "reference_manifest.json"
    if ready_path.is_file():
        manifest = json.loads(ready_path.read_text(encoding="utf-8"))
        if manifest.get("referenceId") != REFERENCE_ID or not (REFERENCE_DIR / "salmon_index" / "versionInfo.json").is_file():
            raise RuntimeError("cached reference manifest is inconsistent")
        return json.dumps({"status": "cached_reference_ready", **manifest}, indent=2, sort_keys=True)
    if REFERENCE_DIR.exists():
        raise RuntimeError(f"incomplete reference cache exists without ready manifest: {REFERENCE_DIR}")

    work = Path("/tmp") / REFERENCE_ID
    work.mkdir(parents=True, exist_ok=False)
    downloaded: dict[str, Any] = {}
    for name, source in REFERENCE_SOURCES.items():
        downloaded[name] = _download_reference(work / name, source)

    transcript_fasta = work / "transcripts.fa"
    genome_fasta = work / "genome.fa"
    with gzip.open(work / "gencode.v23.transcripts.fa.gz", "rb") as source, transcript_fasta.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)
    with gzip.open(work / "GRCh38.primary_assembly.genome.fa.gz", "rb") as source, genome_fasta.open("wb") as destination:
        shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)

    decoys = []
    with genome_fasta.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(">"):
                decoys.append(line[1:].split()[0])
    decoys_path = work / "decoys.txt"
    _write_text(decoys_path, "\n".join(decoys))
    gentrome = work / "gentrome.fa"
    with gentrome.open("wb") as destination:
        for source_path in (transcript_fasta, genome_fasta):
            with source_path.open("rb") as source:
                shutil.copyfileobj(source, destination, length=8 * 1024 * 1024)

    index_dir = work / "salmon_index"
    _run(
        [
            "salmon",
            "index",
            "-t",
            gentrome.as_posix(),
            "-d",
            decoys_path.as_posix(),
            "-i",
            index_dir.as_posix(),
            "--gencode",
            "-k",
            "31",
            "-p",
            "16",
        ],
        stdout_path=work / "salmon_index.stdout.log",
        stderr_path=work / "salmon_index.stderr.log",
    )
    manifest = {
        "schema": "diana_adc_atlas_reference.v1",
        "referenceId": REFERENCE_ID,
        "status": "ready",
        "assembly": "GRCh38.p3 primary assembly",
        "annotation": "GENCODE v23",
        "indexMode": "Salmon full-genome decoy-aware selective-alignment index",
        "decoyCount": len(decoys),
        "salmon": _run(["salmon", "--version"]).strip(),
        "sources": downloaded,
        "indexVersionInfo": json.loads((index_dir / "versionInfo.json").read_text(encoding="utf-8")),
    }
    REFERENCE_DIR.mkdir(parents=True, exist_ok=False)
    shutil.copytree(index_dir, REFERENCE_DIR / "salmon_index")
    shutil.copy2(work / "gencode.v23.annotation.gtf.gz", REFERENCE_DIR / "gencode.v23.annotation.gtf.gz")
    shutil.copy2(work / "gencode.v23.transcripts.fa.gz", REFERENCE_DIR / "gencode.v23.transcripts.fa.gz")
    shutil.copy2(work / "decoys.txt", REFERENCE_DIR / "decoys.txt")
    shutil.copy2(work / "salmon_index.stdout.log", REFERENCE_DIR / "salmon_index.stdout.log")
    shutil.copy2(work / "salmon_index.stderr.log", REFERENCE_DIR / "salmon_index.stderr.log")
    _write_json(ready_path, manifest)
    reference_volume.commit()
    return json.dumps({"status": "reference_built", **manifest}, indent=2, sort_keys=True)


@app.function(
    image=image,
    volumes={RAW_MOUNT_PATH.as_posix(): raw_mount, REFERENCE_MOUNT_PATH.as_posix(): reference_volume},
    cpu=2,
    memory=4096,
    timeout=600,
    region="us-east",
    single_use_containers=True,
    restrict_modal_access=True,
)
def preflight_inputs() -> str:
    paths = {relative: _input_path(relative) for relative in SOURCE_OBJECTS}
    ready_path = REFERENCE_DIR / "reference_manifest.json"
    if not ready_path.is_file():
        raise RuntimeError("reference cache is not ready")
    if not TARGET_MANIFEST_LOCAL.is_file() or not CANCER_REFERENCE_LOCAL.is_file():
        raise RuntimeError("bundled atlas inputs are missing")
    return json.dumps(
        {
            "status": "preflight_passed",
            "inputs": {relative: {"bytes": path.stat().st_size} for relative, path in paths.items()},
            "referenceId": REFERENCE_ID,
            "referenceManifestSha256": _sha256(ready_path),
            "targetManifestSha256": _sha256(TARGET_MANIFEST_LOCAL),
            "cancerReferenceSha256": _sha256(CANCER_REFERENCE_LOCAL),
            "salmon": _run(["salmon", "--version"]).strip(),
        },
        indent=2,
        sort_keys=True,
    )


def _materialize_bundle(bundle: Mapping[str, bytes], destination: Path, run_result: Mapping[str, Any]) -> None:
    if destination.exists():
        raise RuntimeError(f"refusing to overwrite download directory: {destination}")
    destination.mkdir(parents=True)
    for relative, payload in bundle.items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError(f"unsafe bundle path: {relative}")
        output = destination / relative_path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
    _write_json(destination / "modal_run_result.json", run_result)


@app.function(
    image=image,
    volumes={RESULTS_MOUNT_PATH.as_posix(): results_mount},
    timeout=600,
    region="us-east",
    single_use_containers=True,
    restrict_modal_access=True,
)
def fetch_review_bundle(run_id: str) -> dict[str, bytes]:
    run_id = _safe_run_id(run_id)
    run_dir = RESULTS_MOUNT_PATH / "runs" / run_id
    if not (run_dir / "run_manifest.json").is_file():
        raise RuntimeError(f"completed run manifest is missing: {run_id}")
    bundle = {}
    for relative in REVIEW_BUNDLE_PATHS:
        path = run_dir / relative
        if not path.is_file():
            raise RuntimeError(f"review-bundle artifact is missing: {relative}")
        bundle[relative] = path.read_bytes()
    return bundle


@app.function(
    image=image,
    volumes={
        RAW_MOUNT_PATH.as_posix(): raw_mount,
        RESULTS_MOUNT_PATH.as_posix(): results_mount,
        REFERENCE_MOUNT_PATH.as_posix(): reference_volume,
    },
    cpu=16,
    memory=65536,
    timeout=14_400,
    region="us-east",
    single_use_containers=True,
    restrict_modal_access=True,
)
def run_patient_bridge(run_id: str) -> str:
    from diana_omics.adc_patient_bridge import aggregate_salmon_to_genes, build_target_comparison, transcript_gene_map

    run_id = _safe_run_id(run_id)
    remote_run_dir = RESULTS_MOUNT_PATH / "runs" / run_id
    if remote_run_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing run prefix: {run_id}")
    ready_path = REFERENCE_DIR / "reference_manifest.json"
    if not ready_path.is_file():
        raise RuntimeError("reference cache is not ready")
    fastq_1 = _input_path(FASTQ_1)
    fastq_2 = _input_path(FASTQ_2)

    run_dir = Path("/tmp") / f"{APP_NAME}-{run_id}"
    run_dir.mkdir(exist_ok=False)
    for relative in ("logs", "tables", "versions"):
        (run_dir / relative).mkdir(parents=True, exist_ok=True)
    salmon_dir = run_dir / "salmon"
    print("Starting decoy-aware Salmon quantification from the read-only S3 FASTQ mount.", flush=True)
    _run(
        [
            "salmon",
            "quant",
            "-i",
            (REFERENCE_DIR / "salmon_index").as_posix(),
            "-l",
            "A",
            "-1",
            fastq_1.as_posix(),
            "-2",
            fastq_2.as_posix(),
            "--validateMappings",
            "--seqBias",
            "--gcBias",
            "-p",
            "16",
            "-o",
            salmon_dir.as_posix(),
        ],
        stdout_path=run_dir / "logs" / "salmon.stdout.log",
        stderr_path=run_dir / "logs" / "salmon.stderr.log",
    )

    quant_rows = _read_csv(salmon_dir / "quant.sf", delimiter="\t")
    with gzip.open(REFERENCE_DIR / "gencode.v23.annotation.gtf.gz", "rt", encoding="utf-8") as handle:
        tx2gene = transcript_gene_map(handle)
    gene_rows, aggregation_qa = aggregate_salmon_to_genes(quant_rows, tx2gene)
    _write_csv(run_dir / "tables" / "gene_expression.csv", gene_rows)

    targets = _read_csv(TARGET_MANIFEST_LOCAL)
    cancer_reference = [row for row in _read_csv(CANCER_REFERENCE_LOCAL) if row.get("cancer") == BRCA_COHORT]
    comparisons = build_target_comparison(targets, gene_rows, cancer_reference)
    target_by_symbol = {row["gene_symbol"]: row for row in comparisons}
    target_rows = sorted(comparisons, key=lambda row: (-float(row["patient_tpm"]), row["display_name"]))
    _write_csv(run_dir / "tables" / "adc_target_expression.csv", target_rows)
    _write_csv(run_dir / "tables" / "adc_target_breast_comparison.csv", comparisons)

    gene_by_symbol = {row["gene_symbol"]: row for row in gene_rows}
    payload_rows = [
        {
            "gene_symbol": symbol,
            "role": role,
            "patient_tpm": gene_by_symbol.get(symbol, {}).get("tpm", 0.0),
            "gene_type": gene_by_symbol.get(symbol, {}).get("gene_type", "not_mapped"),
            "evidence_status": "context_only",
            "interpretation_boundary": "Expression is mechanistic context, not a payload-sensitivity or resistance prediction.",
        }
        for symbol, role in PAYLOAD_CONTEXT_GENES
    ]
    _write_csv(run_dir / "tables" / "payload_context_expression.csv", payload_rows)

    meta = json.loads((salmon_dir / "aux_info" / "meta_info.json").read_text(encoding="utf-8"))
    percent_mapped = float(meta.get("percent_mapped", 0.0))
    target_count = sum(row["comparison_status"] == "directionally_comparable" for row in comparisons)
    tpm_sum_ok = GENE_TPM_SUM_RANGE[0] <= float(aggregation_qa["gene_tpm_sum"]) <= GENE_TPM_SUM_RANGE[1]
    mapping_ok = percent_mapped >= MINIMUM_MAPPING_RATE
    tx2gene_ok = float(aggregation_qa["transcript_mapping_fraction"]) >= MINIMUM_TX2GENE_FRACTION
    target_coverage_ok = target_count == len(targets)
    qa_status = (
        "passed_for_directional_comparison_with_cross_pipeline_caveat"
        if mapping_ok and tx2gene_ok and tpm_sum_ok and target_coverage_ok
        else "review_required"
    )
    qa_summary = {
        "schema": "diana_adc_atlas_patient_bridge_qa.v1",
        "status": qa_status,
        "salmon": {
            "numProcessedFragments": meta.get("num_processed"),
            "numMappedFragments": meta.get("num_mapped"),
            "percentMapped": percent_mapped,
            "minimumPercentMapped": MINIMUM_MAPPING_RATE,
            "mappingGatePassed": mapping_ok,
            "libraryTypes": meta.get("library_types", []),
            "decoyFragments": meta.get("num_decoy_fragments"),
        },
        "aggregation": {**aggregation_qa, "minimumTranscriptMappingFraction": MINIMUM_TX2GENE_FRACTION, "gatePassed": tx2gene_ok},
        "tpmSumGate": {"expectedRange": GENE_TPM_SUM_RANGE, "passed": tpm_sum_ok},
        "targetCoverage": {"expected": len(targets), "directionallyComparable": target_count, "passed": target_coverage_ok},
        "comparisonStatus": "directionally_comparable" if qa_status.startswith("passed") else "not_comparable",
        "evidenceStatus": "partial_evidence",
    }
    _write_json(run_dir / "qa_summary.json", qa_summary)
    reference_manifest = json.loads(ready_path.read_text(encoding="utf-8"))
    _write_json(run_dir / "reference_manifest.json", reference_manifest)
    _write_json(
        run_dir / "input_evidence_index.json",
        {
            "schema": "diana_adc_atlas_patient_bridge_inputs.v1",
            "classification": "private_human_tumor_rna",
            "sampleAlias": "E019_S01",
            "sourcePrefix": f"s3://{RAW_BUCKET}/{RAW_PREFIX}",
            "objects": [
                {"path": relative, "s3Uri": f"s3://{RAW_BUCKET}/{RAW_PREFIX}{relative}", **record}
                for relative, record in SOURCE_OBJECTS.items()
            ],
            "largeObjectHashPolicy": "Mounted object sizes and the prior versioned intake manifest bind the FASTQs; large objects were not reread solely to recompute SHA-256.",
        },
    )
    software = {
        "python": platform.python_version(),
        "salmon": _run(["salmon", "--version"]).strip(),
        "modal": _distribution_version("modal"),
    }
    _write_json(run_dir / "versions" / "software.json", software)

    top_targets = target_rows[:8]
    _write_text(
        run_dir / "summary.md",
        "\n".join(
            [
                "# Diana Pan-cancer ADC Atlas patient bridge",
                "",
                f"Run `{run_id}` quantified the paired E019_S01 tumor RNA FASTQs with a GENCODE v23 GRCh38 full-decoy Salmon index.",
                "",
                f"- QA status: `{qa_status}`",
                f"- Salmon mapping rate: {percent_mapped:.2f}%",
                f"- Gene-level TPM sum: {float(aggregation_qa['gene_tpm_sum']):,.2f}",
                f"- ADC targets quantified: {target_count}/{len(targets)}",
                "- TCGA BRCA comparison status: `directionally_comparable`, not an exact patient percentile",
                "",
                "## Highest patient target TPM values",
                "",
                *[
                    f"- {row['display_name']} ({row['gene_symbol']}): {float(row['patient_tpm']):,.3f} TPM; "
                    f"TCGA-BRCA band `{row['cohort_quantile_band']}`"
                    for row in top_targets
                ],
                "",
                "## Interpretation boundary",
                "",
                "The private sample and public atlas use the same GENCODE v23 feature model and TPM scale, but Salmon versus Toil/RSEM, library preparation, specimen composition, and batch differ. Ratios and quantile bands are descriptive directional checks, not exact cohort percentiles. This single bulk sample does not support differential expression, malignant-cell localization, membrane-protein abundance, ADC eligibility, response prediction, or treatment recommendation.",
            ]
        ),
    )

    artifact_paths = sorted(
        path for path in run_dir.rglob("*") if path.is_file() and path.name not in {"artifact_index.json", "run_manifest.json"}
    )
    artifact_index = {
        "schema": "diana_adc_atlas_patient_bridge_artifact_index.v1",
        "runId": run_id,
        "artifacts": [_artifact(path, run_dir) for path in artifact_paths],
    }
    _write_json(run_dir / "artifact_index.json", artifact_index)
    run_manifest = {
        "schema": "diana_adc_atlas_patient_bridge_run.v1",
        "runId": run_id,
        "status": "completed_research_analysis",
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "question": "How do Diana E019 bulk-RNA ADC-target measurements compare directionally with the public Pan-cancer ADC Atlas v1?",
        "dataClassification": "private_human_tumor_rna",
        "execution": {
            "runtime": "modal",
            "app": APP_NAME,
            "region": "us-east",
            "cpu": 16,
            "memoryMiB": 65536,
            "inputMount": "read_only_exact_s3_prefix",
            "outputMount": "private_versioned_s3_prefix",
        },
        "reference": {"referenceId": REFERENCE_ID, "manifestSha256": _sha256(run_dir / "reference_manifest.json")},
        "software": software,
        "quantification": {
            "method": "Salmon selective alignment with full-genome decoys, automatic library inference, sequence bias correction, and GC bias correction",
            "geneAggregation": "sum transcript TPM and estimated NumReads by GENCODE v23 gene_id",
        },
        "publicComparator": {
            "cohort": BRCA_COHORT,
            "sampleCount": int(comparisons[0]["tcga_brca_sample_count"]),
            "method": "UCSC Toil/RSEM GENCODE v23 log2(TPM+0.001) inverted to TPM",
            "comparisonStatus": qa_summary["comparisonStatus"],
        },
        "qaStatus": qa_status,
        "evidenceStatus": "partial_evidence",
        "artifactIndex": _artifact(run_dir / "artifact_index.json", run_dir),
        "outputPrefix": f"s3://{RESULTS_BUCKET}/{RESULTS_PREFIX}runs/{run_id}/",
        "evidenceBoundary": "Directional RNA target comparison only; no exact cohort percentile, differential expression, malignant-cell localization, membrane protein, ADC response, eligibility, or treatment recommendation.",
    }
    _write_json(run_dir / "run_manifest.json", run_manifest)

    remote_run_dir.mkdir(parents=True)
    for source_path in [*artifact_paths, run_dir / "artifact_index.json"]:
        destination = remote_run_dir / source_path.relative_to(run_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source_path.open("rb") as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target, length=8 * 1024 * 1024)
    with (run_dir / "run_manifest.json").open("rb") as source, (remote_run_dir / "run_manifest.json").open("wb") as target:
        shutil.copyfileobj(source, target, length=8 * 1024 * 1024)

    trop2 = target_by_symbol["TACSTD2"]
    return json.dumps(
        {
            "status": "completed_research_analysis",
            "runId": run_id,
            "qaStatus": qa_status,
            "evidenceStatus": "partial_evidence",
            "mappingRate": percent_mapped,
            "targetCount": target_count,
            "trop2Tpm": trop2["patient_tpm"],
            "trop2TcgaBrcaBand": trop2["cohort_quantile_band"],
            "comparisonStatus": trop2["comparison_status"],
            "outputPrefix": run_manifest["outputPrefix"],
            "runManifestSha256": _sha256(run_dir / "run_manifest.json"),
        },
        indent=2,
        sort_keys=True,
    )


@app.local_entrypoint()
def main(run_id: str = "", preflight_only: bool = False, download_only: bool = False, download_dir: str = "") -> None:
    if preflight_only and download_only:
        raise ValueError("preflight_only and download_only cannot be combined")
    resolved_run_id = run_id or f"adc-atlas-patient-bridge-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    if download_only:
        if not download_dir:
            raise ValueError("download_dir is required with download_only")
        bundle = fetch_review_bundle.remote(resolved_run_id)
        manifest = json.loads(bundle["run_manifest.json"].decode("utf-8"))
        result = {
            "status": "recovered_completed_research_analysis",
            "runId": resolved_run_id,
            "qaStatus": manifest["qaStatus"],
            "evidenceStatus": manifest["evidenceStatus"],
            "outputPrefix": manifest["outputPrefix"],
        }
    else:
        if preflight_only:
            print(prepare_reference.remote())
        print(preflight_inputs.remote())
        if preflight_only:
            return
        result = json.loads(run_patient_bridge.remote(resolved_run_id))
        print(json.dumps(result, indent=2, sort_keys=True))
        bundle = fetch_review_bundle.remote(resolved_run_id) if download_dir else {}
    if download_dir:
        destination = Path(download_dir).expanduser().resolve()
        _materialize_bundle(bundle, destination, result)
        print(json.dumps({"downloadedReviewBundle": destination.as_posix()}, sort_keys=True))
