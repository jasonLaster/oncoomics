"""Private, version-bound exploratory worker. Set SCRNA_EXPLORATORY_PLAN to an ignored plan."""

import json
import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[2]
app = modal.App("diana-scrna-exploratory")
image = (
    modal.Image.micromamba(python_version="3.11")
    .micromamba_install("r-base=4.4", "bioconductor-scdblfinder=1.20.2", "bioconductor-miqc=1.14.0", channels=["conda-forge", "bioconda"])
    .uv_pip_install(
        "scanpy==1.11.1",
        "anndata==0.11.4",
        "numpy==1.26.4",
        "pandas==2.2.3",
        "scipy==1.15.2",
        "scikit-learn==1.5.2",
        "igraph==0.11.8",
        "leidenalg==0.10.2",
        "umap-learn==0.5.7",
        "matplotlib==3.10.1",
        "boto3==1.40.45",
    )
    .micromamba_install("r-base=4.4", "r-soupx=1.6.2", channels=["conda-forge", "bioconda"])
    .uv_pip_install("requests==2.32.3", "requests-toolbelt==1.0.0")
    .env({"PYTHONPATH": "/opt/diana/src:/opt/diana", "MPLBACKEND": "Agg", "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4"})
)
secret = modal.Secret.from_dict({})
if modal.is_local():
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    import boto3
    from botocore.config import Config

    from diana_omics.scrna_private import BUCKET, KMS_KEY, storage_guard

    s3 = boto3.client(
        "s3", region_name="us-east-1", config=Config(signature_version="s3v4", s3={"us_east_1_regional_endpoint": "regional"})
    )
    storage_guard(s3)
    from diana_omics.scrna_exploratory import validate_plan

    plan_path = Path(os.environ["SCRNA_EXPLORATORY_PLAN"]).resolve()
    if ROOT / "private" not in plan_path.parents:
        raise ValueError("Keep patient exploratory plans under the ignored private directory")
    plan = json.loads(plan_path.read_text())
    validate_plan(plan)
    prefix = plan["output_prefix"]
    inputs = []
    for lib in plan["libraries"]:
        for x in lib["inputs"]:
            inputs.append(
                {
                    "key": x["key"],
                    "version_id": x["version_id"],
                    "url": s3.generate_presigned_url(
                        "get_object", Params={"Bucket": BUCKET, "Key": x["key"], "VersionId": x["version_id"]}, ExpiresIn=14400
                    ),
                }
            )
    fields = {
        "x-amz-server-side-encryption": "aws:kms",
        "x-amz-server-side-encryption-aws-kms-key-id": KMS_KEY,
        "success_action_status": "201",
        "x-amz-meta-sha256": "",
    }
    conditions = [{k: v} for k, v in fields.items() if k != "x-amz-meta-sha256"] + [
        ["content-length-range", 0, 1024**3],
        ["starts-with", "$x-amz-meta-sha256", ""],
    ]
    caps = {
        "inputs": inputs,
        "output": s3.generate_presigned_post(
            Bucket=BUCKET, Key=prefix + "${filename}", Fields=fields, Conditions=conditions, ExpiresIn=14400
        ),
        "output_prefix": prefix,
    }
    secret = modal.Secret.from_dict({"SCRNA_EXPLORATORY_CAPABILITIES": json.dumps(caps)})
    image = image.add_local_dir(ROOT / "src/diana_omics", "/opt/diana/src/diana_omics")


@app.function(image=image, secrets=[secret], cpu=8, memory=65536, timeout=7200, max_containers=1, region="us-east")
def analyze(plan):
    import importlib.metadata
    import tempfile
    import traceback
    from datetime import datetime, timezone

    from diana_omics.scrna_exploratory import analyze_library, validate_plan
    from diana_omics.scrna_io import artifact_index, sha256_file, write_json
    from diana_omics.scrna_private import download_signed, upload_signed

    caps = json.loads(os.environ["SCRNA_EXPLORATORY_CAPABILITIES"])
    validate_plan(plan)
    if caps["output_prefix"] != plan["output_prefix"]:
        raise ValueError("Capability namespace does not match this plan")
    started = datetime.now(timezone.utc).isoformat()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        output = root / "outputs"
        output.mkdir()
        versions = {}
        summaries = {}
        try:
            write_json(output / "plan.json", plan)
            write_json(
                output / "python_packages.json",
                {d.metadata["Name"]: d.version for d in importlib.metadata.distributions() if d.metadata["Name"]},
            )
            source_dir = output / "source"
            source_dir.mkdir()
            for path in Path("/opt/diana/src/diana_omics").glob("scrna*.py"):
                (source_dir / path.name).write_bytes(path.read_bytes())
            for lib in plan["libraries"]:
                source = root / lib["library_id"]
                source.mkdir()
                for x in lib["inputs"]:
                    download_signed(caps, x, source / x["local_name"])
                directory = output / lib["library_id"]
                summaries[lib["library_id"]] = analyze_library(lib, source, directory)
                # Upload each finished library so a second-library failure cannot erase it.
                for item in artifact_index(directory):
                    rel = lib["library_id"] + "/" + item["path"]
                    versions[rel] = upload_signed(caps, caps["output_prefix"] + rel, directory / item["path"])["version_id"]
                write_json(output / "library_completion.json", {"completed_libraries": list(summaries)})
                upload_signed(caps, caps["output_prefix"] + "library_completion.json", output / "library_completion.json")
                import shutil

                shutil.rmtree(source)
            write_json(output / "summary.json", summaries)
            index = artifact_index(output)
            for item in index:
                if item["path"] not in versions:
                    versions[item["path"]] = upload_signed(caps, caps["output_prefix"] + item["path"], output / item["path"])["version_id"]
            write_json(output / "artifact_index.json", index)
            versions["artifact_index.json"] = upload_signed(
                caps, caps["output_prefix"] + "artifact_index.json", output / "artifact_index.json"
            )["version_id"]
            manifest = {
                "schema_version": 1,
                "run_id": plan["run_id"],
                "status": "complete",
                "evidence_lane": plan["evidence_lane"],
                "scientific_status": "exploratory_metadata_hold",
                "clinical_ready": False,
                "production_ready": False,
                "started_at": started,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "artifact_index_sha256": sha256_file(output / "artifact_index.json"),
                "artifact_versions": versions,
                "analysis_source_sha256": sha256_file(output / "source/scrna_exploratory.py"),
                "compute": {"cpu": 8, "memory_mib": 65536, "timeout_seconds": 7200, "max_containers": 1},
            }
            write_json(output / "run_manifest.json", manifest)
            upload_signed(caps, caps["output_prefix"] + "run_manifest.json", output / "run_manifest.json")
            return {"run_id": plan["run_id"], "status": "complete", "artifacts": len(index), "clinical_ready": False}
        except Exception as e:
            detail = traceback.format_exc()
            if any(x in detail.lower() for x in ["x-amz-", "capabilities", "aws_secret"]):
                detail = "Sensitive transport context omitted"
            write_json(
                output / "failure.json",
                {"status": "failed", "category": type(e).__name__, "detail": detail[-12000:], "completed_libraries": list(summaries)},
            )
            upload_signed(caps, caps["output_prefix"] + "failure.json", output / "failure.json")
            raise RuntimeError("Exploratory analysis failed; inspect private failure receipt") from None


@app.local_entrypoint()
def main():
    from diana_omics.scrna_io import sha256_file
    from diana_omics.scrna_private import BUCKET, KMS_KEY

    claim = {
        "run_id": plan["run_id"],
        "plan": plan,
        "runner_sha256": sha256_file(Path(__file__)),
        "metadata_hold": True,
        "clinical_ready": False,
    }
    s3.put_object(
        Bucket=BUCKET,
        Key=plan["output_prefix"] + "_STARTED.json",
        IfNoneMatch="*",
        Body=json.dumps(claim, sort_keys=True).encode(),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=KMS_KEY,
    )
    print(json.dumps(analyze.remote(plan), sort_keys=True))
