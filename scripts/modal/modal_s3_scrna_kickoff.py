from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import modal

APP_NAME = "diana-rosalind-scrna-kickoff"
RAW_MOUNT_PATH = Path("/s3/raw")
RESULTS_MOUNT_PATH = Path("/s3/results")
DEFAULT_INPUT_OBJECT = "pbmc3k_filtered_gene_bc_matrices.tar.gz"
DEFAULT_INPUT_SHA256 = "847d6ebd9a1ec9a768f2be7e40ca42cbfe75ebeb6d76a4c24167041699dc28b5"
SOURCE_URL = "https://s3-us-west-2.amazonaws.com/10x.files/samples/cell/pbmc3k/pbmc3k_filtered_gene_bc_matrices.tar.gz"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _prefix(value: str) -> str:
    return value if value.endswith("/") else f"{value}/"


AWS_SECRET_NAME = _env("MODAL_AWS_SECRET_NAME", "onco-omics-use1")
RAW_BUCKET = _env("ROSALIND_SCRNA_RAW_BUCKET", "diana-omics-raw-inputs-172630973301-us-east-1")
RAW_PREFIX = _prefix(_env("ROSALIND_SCRNA_RAW_PREFIX", "public/10x/pbmc3k"))
RESULTS_BUCKET = _env("ROSALIND_SCRNA_RESULTS_BUCKET", "diana-omics-results-172630973301-us-east-1")
RESULTS_PREFIX = _prefix(_env("ROSALIND_SCRNA_RESULTS_PREFIX", "modal/rosalind-scrna"))

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
    .pip_install(
        "scanpy==1.11.4",
        "leidenalg==0.10.2",
        "igraph==0.11.8",
    )
    .add_local_dir("src/diana_omics", remote_path="/opt/diana/src/diana_omics", copy=True)
    .env(
        {
            "MPLBACKEND": "Agg",
            "NUMBA_CACHE_DIR": "/tmp/numba-cache",
            "PYTHONPATH": "/opt/diana/src",
        }
    )
)


@app.function(
    image=image,
    volumes={
        RAW_MOUNT_PATH.as_posix(): raw_mount,
        RESULTS_MOUNT_PATH.as_posix(): results_mount,
    },
    cpu=4,
    memory=16384,
    timeout=1800,
    region="us-east",
    single_use_containers=True,
    restrict_modal_access=True,
)
def run_scrna_kickoff(run_id: str, input_object: str, expected_sha256: str) -> str:
    import matplotlib.pyplot as plt
    import pandas as pd
    import scanpy as sc

    from diana_omics.scrna_kickoff import (
        file_record,
        file_sha256,
        find_10x_matrix_dir,
        require_relative_object,
        require_run_id,
        require_sha256,
        safe_extract_tar,
    )

    run_id = require_run_id(run_id)
    input_object = require_relative_object(input_object)
    expected_sha256 = require_sha256(expected_sha256)
    source_path = RAW_MOUNT_PATH / input_object
    if not source_path.is_file():
        raise RuntimeError(f"input object is missing from the mounted public prefix: {input_object}")
    actual_sha256 = file_sha256(source_path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(f"input SHA-256 mismatch: expected {expected_sha256}, observed {actual_sha256}")

    remote_run_dir = RESULTS_MOUNT_PATH / "runs" / run_id
    if remote_run_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing run prefix: {run_id}")

    extraction_dir = Path("/tmp") / f"{APP_NAME}-{run_id}"
    extracted = safe_extract_tar(source_path, extraction_dir)
    matrix_dir = find_10x_matrix_dir(extracted)
    run_dir = Path("/tmp") / f"{APP_NAME}-output-{run_id}"
    run_dir.mkdir()

    adata = sc.read_10x_mtx(matrix_dir, var_names="gene_symbols", cache=False)
    adata.var_names_make_unique()
    adata.obs_names_make_unique()
    input_cells = int(adata.n_obs)
    input_genes = int(adata.n_vars)
    adata.var["mt"] = adata.var_names.str.startswith("MT-")
    sc.pp.calculate_qc_metrics(adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True)

    min_genes = 200
    max_genes = 2500
    max_pct_mt = 5.0
    keep = (
        (adata.obs["n_genes_by_counts"] >= min_genes)
        & (adata.obs["n_genes_by_counts"] < max_genes)
        & (adata.obs["pct_counts_mt"] < max_pct_mt)
    )
    retained_cells = int(keep.sum())
    if retained_cells < 100:
        raise RuntimeError(f"QC retained only {retained_cells} cells; refusing downstream clustering")
    adata = adata[keep].copy()
    sc.pp.filter_genes(adata, min_cells=3)
    adata.layers["counts"] = adata.X.copy()

    sc.pp.normalize_total(adata, target_sum=10_000)
    sc.pp.log1p(adata)
    adata.raw = adata
    sc.pp.highly_variable_genes(adata, min_mean=0.0125, max_mean=3.0, min_disp=0.5)
    highly_variable_genes = int(adata.var["highly_variable"].sum())
    if highly_variable_genes < 100:
        raise RuntimeError(f"only {highly_variable_genes} highly variable genes were selected")
    adata = adata[:, adata.var["highly_variable"]].copy()
    sc.pp.regress_out(adata, ["total_counts", "pct_counts_mt"])
    sc.pp.scale(adata, max_value=10)

    n_pcs = min(40, int(adata.n_obs) - 1, int(adata.n_vars) - 1)
    sc.tl.pca(adata, n_comps=n_pcs, svd_solver="arpack", random_state=0)
    sc.pp.neighbors(adata, n_neighbors=10, n_pcs=min(30, n_pcs), random_state=0)
    sc.tl.umap(adata, random_state=0)
    sc.tl.leiden(
        adata,
        resolution=0.5,
        random_state=0,
        key_added="leiden",
        flavor="igraph",
        n_iterations=2,
        directed=False,
    )
    sc.tl.rank_genes_groups(adata, "leiden", method="wilcoxon", use_raw=True)

    processed_path = run_dir / "pbmc3k_processed.h5ad"
    qc_summary_path = run_dir / "scrna_qc_summary.csv"
    cell_qc_path = run_dir / "cell_qc.csv"
    cluster_summary_path = run_dir / "cluster_summary.csv"
    markers_path = run_dir / "marker_genes.csv"
    umap_path = run_dir / "umap_leiden.png"
    input_index_path = run_dir / "input_evidence_index.json"
    summary_path = run_dir / "summary.md"
    artifact_index_path = run_dir / "artifact_index.json"
    run_manifest_path = run_dir / "run_manifest.json"

    adata.write_h5ad(processed_path, compression="gzip")
    qc_rows = [
        {"metric": "input_cells", "value": input_cells},
        {"metric": "input_genes", "value": input_genes},
        {"metric": "retained_cells", "value": retained_cells},
        {"metric": "retained_fraction", "value": retained_cells / input_cells},
        {"metric": "retained_genes_min_3_cells", "value": int(adata.raw.n_vars)},
        {"metric": "highly_variable_genes", "value": highly_variable_genes},
        {"metric": "clusters", "value": int(adata.obs["leiden"].nunique())},
        {"metric": "median_genes_per_retained_cell", "value": float(adata.obs["n_genes_by_counts"].median())},
        {"metric": "median_counts_per_retained_cell", "value": float(adata.obs["total_counts"].median())},
        {"metric": "median_pct_mt", "value": float(adata.obs["pct_counts_mt"].median())},
    ]
    _write_csv(qc_summary_path, qc_rows, ["metric", "value"])

    cell_qc = adata.obs[["total_counts", "n_genes_by_counts", "pct_counts_mt", "leiden"]].copy()
    cell_qc.index.name = "barcode"
    cell_qc.reset_index().to_csv(cell_qc_path, index=False, lineterminator="\n")

    cluster_summary = (
        adata.obs.groupby("leiden", observed=True)
        .size()
        .rename("cells")
        .reset_index()
        .sort_values("leiden", key=lambda values: values.astype(int))
    )
    cluster_summary["fraction"] = cluster_summary["cells"] / retained_cells
    cluster_summary["annotation_status"] = "unreviewed"
    cluster_summary.to_csv(cluster_summary_path, index=False, lineterminator="\n")

    marker_frames = []
    for cluster in cluster_summary["leiden"].astype(str):
        marker_frame = sc.get.rank_genes_groups_df(adata, group=cluster).head(25).copy()
        marker_frame.insert(0, "cluster", cluster)
        marker_frames.append(marker_frame)
    pd.concat(marker_frames, ignore_index=True).to_csv(markers_path, index=False, lineterminator="\n")

    sc.pl.umap(adata, color="leiden", legend_loc="on data", title="PBMC3k Leiden clusters", show=False)
    plt.savefig(umap_path, dpi=180, bbox_inches="tight")
    plt.close("all")

    _write_json(
        input_index_path,
        {
            "schema": "diana_rosalind_scrna_input_index.v1",
            "dataClassification": "public_benchmark",
            "sourceUrl": SOURCE_URL,
            "s3Uri": f"s3://{RAW_BUCKET}/{RAW_PREFIX}{input_object}",
            "bytes": source_path.stat().st_size,
            "sha256": actual_sha256,
            "inputFormat": "10x_legacy_mtx_tar",
            "referenceLabel": "hg19_as_published_by_10x",
        },
    )
    _write_text(
        summary_path,
        "\n".join(
            [
                "# Rosalind scRNA-seq Kickoff",
                "",
                f"Run `{run_id}` processed the public 10x PBMC3k count matrix through deterministic Scanpy QC, normalization, PCA, neighbors, UMAP, Leiden clustering, and marker ranking.",
                "",
                f"- Input cells: {input_cells}",
                f"- Cells retained after QC: {retained_cells}",
                f"- Highly variable genes: {highly_variable_genes}",
                f"- Leiden clusters: {adata.obs['leiden'].nunique()}",
                "- Cell-type annotation: unreviewed",
                "",
                "This public benchmark proves the S3 and Modal execution path. It does not contain Diana sample evidence and must not be used for clinical or treatment conclusions. Review the UMAP and marker table in Rosalind before assigning cell types. For a real cohort, add sample metadata, doublet detection, ambient-RNA review, batch assessment, and a reviewer-approved malignant-cell annotation policy.",
            ]
        ),
    )

    base_artifacts = [
        input_index_path,
        qc_summary_path,
        cell_qc_path,
        cluster_summary_path,
        markers_path,
        umap_path,
        processed_path,
        summary_path,
    ]
    artifact_records = [file_record(path, run_dir) for path in base_artifacts]
    _write_json(
        artifact_index_path,
        {
            "schema": "diana_rosalind_scrna_artifact_index.v1",
            "runId": run_id,
            "artifacts": artifact_records,
        },
    )
    artifact_records_with_index = [*artifact_records, file_record(artifact_index_path, run_dir)]
    _write_json(
        run_manifest_path,
        {
            "schema": "diana_rosalind_scrna_run.v1",
            "status": "completed_public_benchmark",
            "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "runId": run_id,
            "execution": {
                "runtime": "modal",
                "app": APP_NAME,
                "region": "us-east",
                "cpu": 4,
                "memoryMiB": 16384,
                "inputMount": "modal.CloudBucketMount_read_only",
                "outputMount": "modal.CloudBucketMount",
            },
            "software": _software_versions(["scanpy", "anndata", "numpy", "pandas", "scipy", "leidenalg", "igraph"]),
            "thresholds": {
                "minGenesPerCellInclusive": min_genes,
                "maxGenesPerCellExclusive": max_genes,
                "maxPctMitochondrialExclusive": max_pct_mt,
                "minCellsPerGene": 3,
                "normalizationTargetSum": 10_000,
                "leidenResolution": 0.5,
                "randomSeed": 0,
            },
            "input": {
                "classification": "public_benchmark",
                "s3Uri": f"s3://{RAW_BUCKET}/{RAW_PREFIX}{input_object}",
                "sha256": actual_sha256,
            },
            "outputPrefix": f"s3://{RESULTS_BUCKET}/{RESULTS_PREFIX}runs/{run_id}/",
            "artifacts": artifact_records_with_index,
            "evidenceBoundary": "Public PBMC benchmark only; cell types are unreviewed and no Diana sample or clinical conclusion is present.",
        },
    )

    remote_run_dir.mkdir(parents=True)
    upload_paths = [*base_artifacts, artifact_index_path, run_manifest_path]
    for path in upload_paths:
        destination = remote_run_dir / path.name
        with path.open("rb") as source_handle, destination.open("wb") as destination_handle:
            shutil.copyfileobj(source_handle, destination_handle, length=8 * 1024 * 1024)

    return json.dumps(
        {
            "status": "completed_public_benchmark",
            "runId": run_id,
            "inputSha256": actual_sha256,
            "inputCells": input_cells,
            "retainedCells": retained_cells,
            "clusters": int(adata.obs["leiden"].nunique()),
            "outputPrefix": f"s3://{RESULTS_BUCKET}/{RESULTS_PREFIX}runs/{run_id}/",
            "runManifestSha256": file_record(run_manifest_path, run_dir)["sha256"],
        },
        indent=2,
        sort_keys=True,
    )


@app.local_entrypoint()
def main(
    run_id: str = "",
    input_object: str = DEFAULT_INPUT_OBJECT,
    expected_sha256: str = DEFAULT_INPUT_SHA256,
) -> None:
    resolved_run_id = run_id or f"pbmc3k-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    print(run_scrna_kickoff.remote(resolved_run_id, input_object, expected_sha256))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, value: str) -> None:
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def _software_versions(packages: Sequence[str]) -> dict[str, str]:
    return {package: importlib.metadata.version(package) for package in packages}
