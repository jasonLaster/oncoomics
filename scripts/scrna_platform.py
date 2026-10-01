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
from diana_omics.scrna_io import (  # noqa: E402
    safe_id,
    safe_key,
    sha256_file,
    validate_artifact_index,
    validate_config,
    verify_file,
    write_json,
)

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
    if root.is_symlink() or not root.resolve().is_relative_to((ROOT / "results/scrna").resolve()):
        raise ValueError("Run directory escapes results root")
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
    validate_artifact_index(index)
    for record in index:
        relative = safe_key(record["path"])
        target = root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Artifact escapes run directory")
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


def status(s3, run_id: str) -> dict:
    from diana_omics.scrna_release import run_state

    safe_id(run_id)
    markers = []
    for filename in ("_STARTED.json", "_FAILED.json", "run_manifest.json"):
        try:
            obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=f"public/scrna/runs/{run_id}/{filename}")
            marker = json.loads(obj["Body"].read())
            if marker.get("run_id") != run_id:
                raise ValueError("Status marker run ID mismatch")
            markers.append(marker)
        except s3.exceptions.ClientError as error:
            if error.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
                raise
            markers.append(None)
    report = {"run_id": run_id, **run_state(*markers)}
    print(json.dumps(report, indent=2))
    return report


def assess(run_id: str, config_path: Path, evidence_path: Path | None) -> bool:
    from html import escape

    from diana_omics.scrna_release import assess_release

    safe_id(run_id)
    root = ROOT / "results/scrna" / run_id
    config = json.loads(config_path.read_text())
    validation = ROOT / "results/scrna/validation" / run_id
    report = assess_release(root, config, validation / "independent_review.json", evidence_path)
    write_json(validation / "release_decision.json", report)
    blockers = "".join(f"<li>{escape(reason)}</li>" for reason in report["blockers"])
    (validation / "release_review.html").write_text('''<!doctype html><html lang="en"><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1"><title>Breast cohort release review</title>
        <style>body{font:17px/1.6 system-ui;color:#182a39;background:#f6f8fa;max-width:1000px;margin:auto;padding:30px}
        main{background:white;border:1px solid #dbe3ea;border-radius:10px;padding:25px}a{color:#17547c}li{margin:8px 0}</style>
        <main><h1>Breast cohort release: ''' + escape(report["decision"]) + '''</h1><p>''' + escape(run_id) + '''</p>
        <p>Allowed use: ''' + escape(report["allowed_use"]) + '''. Clinical use: no.</p><ul>''' + blockers + '''</ul>
        <p><a href="release_decision.json">Machine-readable decision and custody</a> ·
        <a href="../../''' + escape(run_id) + '''/review.html">QC plots and miQC challenger</a></p>
        <p>Completion confirms artifact delivery. Admission additionally requires passing calibration, exact-source
        count audits, source-backed capture/chemistry, matching raw-droplet assessment, and reviewed independent
        validation. Missing evidence never becomes a pass.</p></main></html>''')
    print(json.dumps(report, indent=2))
    return report["production_ready"]


def promote(s3, run_id: str, config_path: Path, evidence_path: Path | None) -> bool:
    """Only admitted cohorts get a production release manifest; runs stay immutable."""
    import hashlib

    if not assess(run_id, config_path, evidence_path):
        return False  # Do not make any S3 writes for a quarantined cohort.
    root = ROOT / "results/scrna" / run_id
    decision = json.loads((ROOT / "results/scrna/validation" / run_id / "release_decision.json").read_text())
    controls = {}
    for name in ("run_manifest.json", "artifact_index.json"):
        obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=f"public/scrna/runs/{run_id}/{name}")
        digest = hashlib.sha256(obj["Body"].read()).hexdigest()
        if digest != sha256_file(root / name) or not obj.get("VersionId"):
            raise ValueError("Production release requires matching versioned S3 controls")
        controls[name] = {"sha256": digest, "version_id": obj["VersionId"]}
    release = {"schema_version": 1, "run_id": run_id, "decision": decision, "controls": controls,
               "results_uri": f"s3://{RESULTS_BUCKET}/public/scrna/runs/{run_id}/"}
    body = json.dumps(release, sort_keys=True, indent=2, allow_nan=False).encode()
    key = f"public/scrna/releases/{run_id}/release_manifest.json"
    try:
        s3.put_object(Bucket=RESULTS_BUCKET, Key=key, Body=body, IfNoneMatch="*", ServerSideEncryption="AES256",
                      Metadata={"sha256": hashlib.sha256(body).hexdigest()})
    except s3.exceptions.ClientError as error:
        if error.response["Error"]["Code"] != "PreconditionFailed":
            raise
        existing = s3.get_object(Bucket=RESULTS_BUCKET, Key=key)["Body"].read()
        if existing != body:
            raise ValueError("An immutable release already exists with different evidence") from error
    obj = s3.get_object(Bucket=RESULTS_BUCKET, Key=key)
    if obj["Body"].read() != body or not obj.get("VersionId"):
        raise ValueError("Release upload verification failed")
    print(f"Verified production research release: s3://{RESULTS_BUCKET}/{key}")
    return True


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
    inspect = commands.add_parser("status", help="Read completion/failure markers and detect stale runs")
    inspect.add_argument("--run-id", required=True)
    admission = commands.add_parser("assess-release", help="Verify artifacts and quarantine cohorts lacking readiness evidence")
    admission.add_argument("--run-id", required=True)
    admission.add_argument("--config", type=Path, default=ROOT / "manifests/scrna/breast/calibration.lock.json")
    admission.add_argument("--evidence", type=Path)
    publish = commands.add_parser("promote", help="Publish an immutable release manifest only for an admitted research cohort")
    publish.add_argument("--run-id", required=True)
    publish.add_argument("--config", type=Path, default=ROOT / "manifests/scrna/breast/calibration.lock.json")
    publish.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.command == "assess-release":
        raise SystemExit(0 if assess(args.run_id, args.config, args.evidence) else 2)
    s3 = boto3.client("s3", region_name="us-east-1")
    if args.command == "promote":
        raise SystemExit(0 if promote(s3, args.run_id, args.config, args.evidence) else 2)
    if args.command == "stage":
        stage(s3, args.config)
    elif args.command == "collect":
        collect(s3, args.run_id)
    elif args.command == "compare":
        compare(args.first_run, args.second_run, args.dataset_id)
    else:
        report = status(s3, args.run_id)
        raise SystemExit(2 if report["state"] in {"failed", "stale", "inconsistent"} else 0)


if __name__ == "__main__":
    main()
