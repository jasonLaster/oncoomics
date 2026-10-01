#!/usr/bin/env python3
"""Stage public calibration fixtures and verify/download immutable S3 runs."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from diana_omics.scrna_io import safe_id, safe_key, sha256_file, validate_config, verify_file, write_json  # noqa: E402

RAW_BUCKET = "diana-omics-raw-inputs-172630973301-us-east-1"
RESULTS_BUCKET = "diana-omics-results-172630973301-us-east-1"


def stage(s3, config_path: Path) -> None:
    config = json.loads(config_path.read_text())
    validate_config(config)
    cache = ROOT / "data/raw/scrna"
    cache.mkdir(parents=True, exist_ok=True)
    for dataset in config["datasets"]:
        for item in dataset["inputs"]:
            path = cache / item["filename"]
            if not path.exists():
                temporary = path.with_suffix(path.suffix + ".partial")
                request = urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0 (Diana public calibration)"})
                with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                    length = 0
                    while block := response.read(1024 * 1024):
                        length += len(block)
                        if length > 64 * 1024**2:
                            raise ValueError("Public fixture exceeds 64 MiB transfer limit")
                        output.write(block)
                temporary.replace(path)
            digest = sha256_file(path)
            if "sha256" in item:
                verify_file(path, item["sha256"])
            item["sha256"] = digest
            key = f"public/scrna/inputs/{dataset['dataset_id']}/{digest}/{item['filename']}"
            # Content-addressed objects cannot be replaced; verify existing object bytes on a rerun.
            try:
                with path.open("rb") as body:
                    receipt = s3.put_object(Bucket=RAW_BUCKET, Key=key, Body=body, IfNoneMatch="*",
                                            ServerSideEncryption="AES256", Metadata={"sha256": digest, "evidence-lane": "public_benchmark"})
            except s3.exceptions.ClientError as error:
                if error.response["Error"]["Code"] != "PreconditionFailed":
                    raise
                existing = cache / (item["filename"] + ".s3-check")
                s3.download_file(RAW_BUCKET, key, str(existing))
                verify_file(existing, digest)
                existing.unlink()
                receipt = s3.head_object(Bucket=RAW_BUCKET, Key=key)
            item.update({"bucket": RAW_BUCKET, "key": key, "size_bytes": path.stat().st_size, "version_id": receipt.get("VersionId")})
            print(f"Staged {dataset['dataset_id']} / {item['role']}: {path.stat().st_size:,} bytes, SHA-256 {digest}")
    lock = config_path.with_name("calibration.lock.json")
    write_json(lock, config)
    print(f"Frozen input manifest: {lock}")


def collect(s3, run_id: str) -> None:
    safe_id(run_id)
    root = ROOT / "results/scrna" / run_id
    root.mkdir(parents=True, exist_ok=True)
    prefix = f"public/scrna/runs/{run_id}/"
    receipt = {}
    for name in ("run_manifest.json", "artifact_index.json"):
        obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=prefix + name)
        content = obj["Body"].read()
        (root / name).write_bytes(content)
        receipt[name] = {"version_id": obj.get("VersionId"), "sha256": sha256_file(root / name)}
    manifest = json.loads((root / "run_manifest.json").read_text())
    if manifest["run_id"] != run_id or manifest["status"] != "complete":
        raise ValueError("Run does not have a valid completion manifest")
    verify_file(root / "artifact_index.json", manifest["artifact_index_sha256"])
    index = json.loads((root / "artifact_index.json").read_text())
    for record in index:
        relative = safe_key(record["path"])
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=prefix + relative)
        if obj["ContentLength"] != record["size_bytes"]:
            raise ValueError(f"S3 size mismatch: {relative}")
        with target.open("wb") as output:
            shutil.copyfileobj(obj["Body"], output)
        verify_file(target, record["sha256"])
        receipt[relative] = {"version_id": obj.get("VersionId"), "sha256": record["sha256"]}
    write_json(root / "s3_verification.json", {"run_id": run_id, "status": "all_hashes_verified", "bucket": RESULTS_BUCKET,
                                               "prefix": prefix, "objects": receipt})
    print(f"Verified {len(index)} artifacts plus run/index manifests in {root}")


def compare(first_run: str, second_run: str, dataset_id: str) -> None:
    for value in (first_run, second_run, dataset_id):
        safe_id(value)
    roots = [ROOT / "results/scrna" / run for run in (first_run, second_run)]
    inputs = [json.loads((root / "input_manifest.json").read_text()) for root in roots]
    datasets = [next(d for d in config["datasets"] if d["dataset_id"] == dataset_id) for config in inputs]
    if datasets[0] != datasets[1] or inputs[0]["parameters"] != inputs[1]["parameters"]:
        raise ValueError("Repeat comparison requires identical inputs and parameters")
    verification = [json.loads((root / "s3_verification.json").read_text()) for root in roots]
    if any(v["status"] != "all_hashes_verified" for v in verification):
        raise ValueError("Collect and verify both runs before comparing")
    checks = {}
    for relative in ["python_packages.json", "conda-explicit.txt", "source_hashes.json", f"{dataset_id}/all_cells_qc.csv",
                     f"{dataset_id}/umap.csv", f"{dataset_id}/markers.csv"]:
        # Verify files still match downloaded custody records before comparing.
        for root, receipt in zip(roots, verification):
            verify_file(root / relative, receipt["objects"][relative]["sha256"])
        checks[relative] = sha256_file(roots[0] / relative) == sha256_file(roots[1] / relative)
    report = {"first_run": first_run, "second_run": second_run, "dataset_id": dataset_id,
              "status": "pass" if all(checks.values()) else "needs_review", "exact_hash_checks": checks,
              "scope": "Same pinned environment, inputs, parameters, and code. Exact barcode QC, UMAP/cluster table, and marker reproducibility."}
    target = ROOT / "results/scrna" / f"{first_run}-repeat-check.json"
    write_json(target, report)
    print(json.dumps(report, indent=2))


def main() -> None:
    import boto3
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("stage")
    prep.add_argument("--config", type=Path, default=ROOT / "manifests/scrna/calibration.json")
    fetch = commands.add_parser("collect")
    fetch.add_argument("--run-id", required=True)
    repeated = commands.add_parser("compare")
    repeated.add_argument("--first-run", required=True)
    repeated.add_argument("--second-run", required=True)
    repeated.add_argument("--dataset-id", default="pbmc3k")
    args = parser.parse_args()
    s3 = boto3.client("s3", region_name="us-east-1")
    if args.command == "stage":
        stage(s3, args.config)
    elif args.command == "collect":
        collect(s3, args.run_id)
    else:
        compare(args.first_run, args.second_run, args.dataset_id)


if __name__ == "__main__":
    main()
