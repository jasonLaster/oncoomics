"""On-demand private scRNA worker. Expiring signed capabilities; no AWS credentials or bucket mounts."""
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[2] if modal.is_local() else Path("/opt/diana")
app = modal.App("diana-scrna-private")
image = (
    modal.Image.micromamba(python_version="3.11")
    .micromamba_install("r-base=4.4", "bioconductor-scdblfinder=1.20.2", "bioconductor-miqc=1.14.0", channels=["conda-forge", "bioconda"])
    .uv_pip_install(
        "scanpy==1.11.1", "anndata==0.11.4", "numpy==1.26.4", "pandas==2.2.3", "scipy==1.15.2",
        "scikit-learn==1.5.2", "igraph==0.11.8", "leidenalg==0.10.2", "umap-learn==0.5.7",
        "matplotlib==3.10.1", "boto3==1.40.45",
    )
    .micromamba_install("r-base=4.4", "r-soupx=1.6.2", channels=["conda-forge", "bioconda"])
    .uv_pip_install("requests==2.32.3", "requests-toolbelt==1.0.0")
    .env({"PYTHONPATH": "/opt/diana/src", "MPLBACKEND": "Agg", "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"})
)
worker_secret = modal.Secret.from_dict({})
count_image = image.micromamba_install("star=2.7.11b", channels=["conda-forge", "bioconda"])
if modal.is_local():
    import json
    import os
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    image = image.add_local_dir(ROOT / "src" / "diana_omics", "/opt/diana/src/diana_omics")
    count_image = count_image.add_local_dir(ROOT / "src" / "diana_omics", "/opt/diana/src/diana_omics")
    receipt_path = os.environ.get("SCRNA_STAGE_RECEIPT")
    if receipt_path:
        import boto3
        from botocore.config import Config

        from diana_omics.scrna_private import signed_capabilities

        receipt = json.loads(Path(receipt_path).read_text())
        s3 = boto3.client("s3", region_name="us-east-1", config=Config(signature_version="s3v4", s3={"us_east_1_regional_endpoint": "regional"}))
        capabilities = signed_capabilities(s3, receipt, os.environ["SCRNA_RUN_ID"])
        values = {"SCRNA_OUTPUT_CAPABILITY": json.dumps({key: value for key, value in capabilities.items() if key != "inputs"})}
        for index in range(0, len(capabilities["inputs"]), 10):
            values[f"SCRNA_READ_CAPABILITY_{index // 10}"] = json.dumps(capabilities["inputs"][index:index + 10])
        worker_secret = modal.Secret.from_dict(values)


@app.function(image=image, cpu=4, memory=16384, timeout=600, max_containers=1, region="us-east")
def runtime_preflight():
    import importlib.metadata
    import subprocess

    result = subprocess.run(["Rscript", "-e", 'cat(as.character(packageVersion("scDblFinder")), as.character(packageVersion("miQC")), as.character(packageVersion("SoupX")))'], capture_output=True, text=True, check=True)
    dbl, miqc, ambient = result.stdout.strip().split()
    return {"scanpy": importlib.metadata.version("scanpy"), "scDblFinder": dbl, "miQC": miqc, "SoupX": ambient,
            "private_bucket_mounts": False, "gpu": False}


@app.function(image=count_image, cpu=1, memory=2048, timeout=300, max_containers=1, region="us-east")
def star_preflight():
    import subprocess
    version = subprocess.run(["STAR", "--version"], capture_output=True, text=True, check=True).stdout.strip()
    return {"STAR": version, "biological_cell_calling_qualified": False}


@app.function(image=image, secrets=[worker_secret], cpu=4, memory=16384, timeout=3600, max_containers=1, region="us-east")
def process(bundle_receipt: dict, intake_id: str, run_id: str, runner_source: str):
    return _process_impl(bundle_receipt, intake_id, run_id, runner_source, count_mode=False)


@app.function(image=count_image, secrets=[worker_secret], cpu=8, memory=65536, timeout=7200, max_containers=1, region="us-east")
def count(bundle_receipt: dict, intake_id: str, run_id: str, runner_source: str):
    return _process_impl(bundle_receipt, intake_id, run_id, runner_source, count_mode=True)


def _process_impl(bundle_receipt: dict, intake_id: str, run_id: str, runner_source: str, count_mode: bool):
    import hashlib
    import json
    import os
    import tempfile
    from datetime import datetime, timezone

    from diana_omics.scrna_io import artifact_index, safe_key, sha256_file, write_json
    from diana_omics.scrna_patient import execute_patient
    from diana_omics.scrna_private import BUCKET, ROOT_PREFIX, download_signed, run_prefix, upload_signed

    expected_bundle_key = f"{ROOT_PREFIX}intakes/{intake_id}/intake_bundle.json"
    if bundle_receipt["bucket"] != BUCKET or bundle_receipt["key"] != expected_bundle_key:
        raise ValueError("Unexpected private intake descriptor")
    capabilities = json.loads(os.environ["SCRNA_OUTPUT_CAPABILITY"])
    capabilities["inputs"] = []
    for key in sorted(name for name in os.environ if name.startswith("SCRNA_READ_CAPABILITY_")):
        capabilities["inputs"].extend(json.loads(os.environ[key]))
    prefix = run_prefix(run_id)
    if capabilities["output_prefix"] != prefix:
        raise ValueError("Output capability belongs to another run")
    started = datetime.now(timezone.utc).isoformat()
    try:
        with tempfile.TemporaryDirectory(prefix="scrna-private-") as temporary:
            root = Path(temporary)
            bundle_path = root / "intake_bundle.json"
            download_signed(capabilities, bundle_receipt, bundle_path)
            bundle = json.loads(bundle_path.read_text())
            if bundle["intake_id"] != intake_id:
                raise ValueError("Intake identity mismatch")
            source = root / "inputs"
            for item in bundle["objects"] + bundle.get("count_reference", {}).get("objects", []):
                if item["key"] != f"{ROOT_PREFIX}intakes/{intake_id}/" + safe_key(item["path"]):
                    raise ValueError("Input receipt escapes selected intake")
                download_signed(capabilities, item, source / item["path"])
            output = root / "outputs"
            if count_mode:
                from diana_omics.scrna_count import run_starsolo
                if not bundle.get("count_reference"):
                    raise ValueError("Reference-locked counting requires its own staged reference assets")
                result = run_starsolo(bundle["contract"], source, bundle["count_reference"]["lock"], source / "reference", output)
                (output / "source").mkdir()
                for name in ("scrna_count.py", "scrna_intake.py", "scrna_private.py"):
                    (output / "source" / name).write_bytes((Path("/opt/diana/src/diana_omics") / name).read_bytes())
                (output / "source/modal_patient_runner.py").write_text(runner_source)
                scientific_status = "count_generation_provisional"
            else:
                result = execute_patient(bundle["contract"], source, output, runner_source)
                scientific_status = "qc_provisional"
            write_json(output / "intake_custody.json", {"intake_id": intake_id, "bundle": bundle_receipt, "objects": bundle["objects"]})
            index = artifact_index(output)
            write_json(output / "artifact_index.json", index)
            versions = {}
            for item in index:
                upload = upload_signed(capabilities, prefix + item["path"], output / item["path"])
                versions[item["path"]] = upload["version_id"]
            upload = upload_signed(capabilities, prefix + "artifact_index.json", output / "artifact_index.json")
            versions["artifact_index.json"] = upload["version_id"]
            manifest = {"schema_version": 1, "run_id": run_id, "status": "complete", "intake_id": intake_id,
                        "evidence_lane": bundle["contract"]["evidence_lane"], "started_at": started,
                        "completed_at": datetime.now(timezone.utc).isoformat(), "scientific_status": scientific_status,
                        "artifact_index_sha256": sha256_file(output / "artifact_index.json"),
                        "method_sha256": result.get("method_sha256"), "production_ready": False, "clinical_ready": False,
                        "artifact_versions": versions,
                        "runner_sha256": hashlib.sha256(runner_source.encode()).hexdigest(),
                        "compute": {"cpu": 8 if count_mode else 4, "memory_mib": 65536 if count_mode else 16384,
                                    "timeout_seconds": 7200 if count_mode else 3600, "max_containers": 1}}
            write_json(output / "run_manifest.json", manifest)
            upload_signed(capabilities, prefix + "run_manifest.json", output / "run_manifest.json")
            # Return only non-identifying mechanics; detailed data stay in private S3.
            return {"run_id": run_id, "status": "complete", "scientific_status": scientific_status, "artifacts": len(index), "clinical_ready": False}
    except Exception as error:
        import traceback

        with tempfile.TemporaryDirectory() as failed:
            path = Path(failed) / "failure.json"
            write_json(path, {"run_id": run_id, "status": "failed", "error_category": type(error).__name__})
            upload_signed(capabilities, prefix + "_FAILED.json", path)
            detail = traceback.format_exc()
            if any(token in detail.lower() for token in ("x-amz-", "aws_secret", "scrna_output_capability", "scrna_read_capability")):
                detail = "Transfer/credential context omitted. Inspect the failed execution stage and generic error category."
            write_json(path, {"error_category": type(error).__name__, "detail": detail[-10000:]})
            upload_signed(capabilities, prefix + "failure_detail.json", path)
        raise RuntimeError("Private scRNA run failed; inspect its private failure receipt") from None


@app.local_entrypoint()
def main(runtime_only: bool = False, run_id: str = ""):
    import json
    import os

    if runtime_only:
        print(json.dumps(runtime_preflight.remote(), sort_keys=True))
        print(json.dumps(star_preflight.remote(), sort_keys=True))
        return
    if not os.environ.get("SCRNA_STAGE_RECEIPT") or run_id != os.environ.get("SCRNA_RUN_ID"):
        raise ValueError("Use the patient CLI run command to supply a stage receipt and matching run ID")
    receipt = json.loads(Path(os.environ["SCRNA_STAGE_RECEIPT"]).read_text())
    count_mode = bool((receipt.get("count_plan") or {}).get("ready_for_reference_locked_counting"))
    if not receipt["inspection"]["ready_for_postcount_qc"] and not count_mode:
        raise ValueError("Post-count QC blocked by intake; FASTQs require their own count-generation lane")
    from datetime import datetime, timezone

    from diana_omics.scrna_private import BUCKET, KMS_KEY, run_prefix

    # The local operator claims the run atomically before any remote processing.
    s3.put_object(Bucket=BUCKET, Key=run_prefix(run_id) + "_STARTED.json", IfNoneMatch="*", ServerSideEncryption="aws:kms",
                  SSEKMSKeyId=KMS_KEY, BucketKeyEnabled=False,
                  Body=json.dumps({"run_id": run_id, "intake_id": receipt["intake_id"], "started_at": datetime.now(timezone.utc).isoformat(), "timeout_seconds": 7200 if count_mode else 3600}).encode())
    try:
        function = count if count_mode else process
        print(json.dumps(function.remote(receipt["bundle"], receipt["intake_id"], run_id, Path(__file__).read_text()), sort_keys=True))
    except Exception as error:
        from botocore.exceptions import ClientError

        try:
            s3.put_object(Bucket=BUCKET, Key=run_prefix(run_id) + "_FAILED.json", IfNoneMatch="*", ServerSideEncryption="aws:kms",
                          SSEKMSKeyId=KMS_KEY, BucketKeyEnabled=False,
                          Body=json.dumps({"run_id": run_id, "status": "failed", "error_category": type(error).__name__}).encode())
        except ClientError as marker_error:
            if marker_error.response["Error"]["Code"] not in {"PreconditionFailed", "412"}:
                raise
        raise RuntimeError("Private worker failed; inspect its protected failure receipt and retry with a new ID") from None
