"""On-demand single-cell calibration on Modal; source/results live in S3."""
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path("/opt/diana")
RAW_BUCKET = "diana-omics-raw-inputs-172630973301-us-east-1"
RESULTS_BUCKET = "diana-omics-results-172630973301-us-east-1"
SECRET_NAME = "onco-omics-use1"
app = modal.App("diana-scrna-platform")
secret = modal.Secret.from_name(SECRET_NAME)
image = (
    modal.Image.micromamba(python_version="3.11")
    .micromamba_install("r-base=4.4", "bioconductor-scdblfinder=1.20.2", channels=["conda-forge", "bioconda"])
    .uv_pip_install(
        "scanpy==1.11.1", "anndata==0.11.4", "numpy==1.26.4", "pandas==2.2.3", "scipy==1.15.2",
        "scikit-learn==1.5.2", "igraph==0.11.8", "leidenalg==0.10.2", "umap-learn==0.5.7",
        "matplotlib==3.10.1", "boto3==1.40.45",
    )
    .env({"PYTHONPATH": "/opt/diana/src", "MPLBACKEND": "Agg", "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"})
)
if modal.is_local():
    image = image.add_local_dir(ROOT / "src" / "diana_omics", "/opt/diana/src/diana_omics")


@app.function(
    image=image, secrets=[secret], cpu=4, memory=16384, timeout=1800, max_containers=2, region="us-east",
    volumes={"/raw/public": modal.CloudBucketMount(RAW_BUCKET, secret=secret, key_prefix="public/", read_only=True)},
)
def calibrate(config: dict, run_id: str, runner_source: str):
    import json
    import tempfile
    from datetime import datetime, timezone

    import boto3

    from diana_omics.scrna import execute
    from diana_omics.scrna_io import artifact_index, safe_id, safe_key, sha256_file, validate_config, write_json

    safe_id(run_id)
    validate_config(config)
    for dataset in config["datasets"]:
        for item in dataset["inputs"]:
            if item["bucket"] != RAW_BUCKET or not safe_key(item["key"]).startswith("public/scrna/inputs/"):
                raise ValueError("Only staged public calibration inputs are allowed")
    s3 = boto3.client("s3", region_name="us-east-1")
    prefix = f"public/scrna/runs/{run_id}/"
    started = datetime.now(timezone.utc).isoformat()
    # Atomically claim an immutable run ID. Failed runs require a fresh ID.
    s3.put_object(Bucket=RESULTS_BUCKET, Key=prefix + "_STARTED.json", IfNoneMatch="*",
                  Body=json.dumps({"run_id": run_id, "started_at": started}).encode(), ServerSideEncryption="AES256")
    try:
        with tempfile.TemporaryDirectory(prefix="scrna-") as temporary:
            output = Path(temporary) / run_id
            summaries = execute(config, Path("/raw"), output)
            (output / "source" / "modal_runner.py").write_text(runner_source)
            index = artifact_index(output)
            write_json(output / "artifact_index.json", index)
            for record in index:
                with (output / record["path"]).open("rb") as body:
                    s3.put_object(Bucket=RESULTS_BUCKET, Key=prefix + record["path"], Body=body, IfNoneMatch="*",
                                  ServerSideEncryption="AES256", Metadata={"sha256": record["sha256"]})
            with (output / "artifact_index.json").open("rb") as body:
                s3.put_object(Bucket=RESULTS_BUCKET, Key=prefix + "artifact_index.json", Body=body, IfNoneMatch="*",
                              ServerSideEncryption="AES256")
            manifest = {
                "schema_version": 1, "run_id": run_id, "status": "complete", "evidence_lane": "public_benchmark",
                "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
                "results_uri": f"s3://{RESULTS_BUCKET}/{prefix}",
                "artifact_index_sha256": sha256_file(output / "artifact_index.json"),
                "compute": {"platform": "Modal", "cpu": 4, "memory_mib": 16384, "timeout_seconds": 1800, "gpu": None},
                "calibration_status": "pass" if all(v["calibration_status"] == "pass" for v in summaries.values()) else "needs_review",
                "limitations": ["Post-count matrix calibration only", "Ambient RNA unassessed without empty droplets",
                                "Doublet caller executed; precision/recall unvalidated", "Tutorial annotations are not independent truth",
                                "No donor-level DE, cross-dataset integration, tumor validation, or clinical claims"],
            }
            # Write the completion marker last, after all indexed artifacts.
            s3.put_object(Bucket=RESULTS_BUCKET, Key=prefix + "run_manifest.json", Body=json.dumps(manifest, indent=2).encode(),
                          IfNoneMatch="*", ServerSideEncryption="AES256")
            return {"run": manifest, "datasets": summaries}
    except Exception as error:
        s3.put_object(Bucket=RESULTS_BUCKET, Key=prefix + "_FAILED.json", IfNoneMatch="*",
                      Body=json.dumps({"run_id": run_id, "status": "failed", "error": str(error)}).encode(), ServerSideEncryption="AES256")
        raise


@app.function(image=image, secrets=[secret], cpu=4, memory=16384, timeout=1800, max_containers=2, region="us-east")
def preflight():
    import subprocess

    import boto3
    import scanpy

    s3 = boto3.client("s3", region_name="us-east-1")
    for bucket in (RAW_BUCKET, RESULTS_BUCKET):
        s3.head_bucket(Bucket=bucket)
    r = subprocess.run(["Rscript", "-e", 'cat(as.character(packageVersion("scDblFinder")))'], check=True, capture_output=True, text=True)
    return {"scanpy": scanpy.__version__, "scDblFinder": r.stdout, "s3_access": "verified", "cpu": 4, "memory_mib": 16384}


@app.local_entrypoint()
def main(preflight_only: bool = False, run_id: str = "", config: str = "manifests/scrna/calibration.lock.json", repeat_check: bool = False):
    import json

    from diana_omics.scrna_io import safe_id

    if preflight_only:
        print(preflight.remote())
    else:
        safe_id(run_id)
        config_path = Path(config)
        if not config_path.is_absolute():
            config_path = ROOT / config_path
        payload = json.loads(config_path.read_text())
        runner_source = Path(__file__).read_text()
        result = calibrate.remote(payload, run_id, runner_source)
        print(json.dumps(result, indent=2))
        if repeat_check:
            repeat_id = safe_id(run_id + "-repeat")
            payload["datasets"] = [payload["datasets"][0]]
            print(json.dumps(calibrate.remote(payload, repeat_id, runner_source), indent=2))
