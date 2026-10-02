"""Immutable private S3 custody and narrowly scoped, expiring worker access."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .scrna_intake import inspect_delivery, local_file, validate_contract
from .scrna_io import safe_id, safe_key, sha256_file, validate_artifact_index

BUCKET = "diana-omics-private-results-172630973301-us-east-1"
REGION = "us-east-1"
KMS_KEY = "arn:aws:kms:us-east-1:172630973301:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
ROOT_PREFIX = "private/scrna/"


def digest_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def storage_guard(s3) -> dict:
    blocks = s3.get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
    encryption = s3.get_bucket_encryption(Bucket=BUCKET)["ServerSideEncryptionConfiguration"]["Rules"]
    policy_public = s3.get_bucket_policy_status(Bucket=BUCKET)["PolicyStatus"]["IsPublic"]
    versioning = s3.get_bucket_versioning(Bucket=BUCKET).get("Status")
    default = encryption[0]["ApplyServerSideEncryptionByDefault"]
    if not all(blocks.get(key) is True for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")) or policy_public or versioning != "Enabled":
        raise ValueError("Private bucket guard failed: access blocks/policy/versioning")
    if default.get("SSEAlgorithm") != "aws:kms" or default.get("KMSMasterKeyID") != KMS_KEY or encryption[0].get("BucketKeyEnabled", False):
        raise ValueError("Private bucket guard failed: pinned KMS key/object encryption context")
    return {"public_access_block": "all_enabled", "policy_public": False, "versioning": versioning, "encryption": "aws:kms"}


def _put(s3, key: str, body, sha: str, size: int) -> dict:
    """Atomic put (or multipart completion) refuses replacement; verify the returned version's actual bytes."""
    from botocore.exceptions import ClientError

    if not safe_key(key).startswith(ROOT_PREFIX):
        raise ValueError("Private scRNA prefix required")
    kwargs = {"Bucket": BUCKET, "Key": key, "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": KMS_KEY,
              "BucketKeyEnabled": False, "Metadata": {"sha256": sha}}
    try:
        if size <= 64 * 1024**2:
            import base64
            response = s3.put_object(**kwargs, Body=body, IfNoneMatch="*", ChecksumSHA256=base64.b64encode(bytes.fromhex(sha)).decode())
        else:
            upload = s3.create_multipart_upload(**kwargs)["UploadId"]
            parts = []
            try:
                while block := body.read(128 * 1024**2):
                    part = s3.upload_part(Bucket=BUCKET, Key=key, UploadId=upload, PartNumber=len(parts) + 1, Body=block)
                    parts.append({"ETag": part["ETag"], "PartNumber": len(parts) + 1})
                response = s3.complete_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload,
                                                        MultipartUpload={"Parts": parts}, IfNoneMatch="*")
            except Exception:
                s3.abort_multipart_upload(Bucket=BUCKET, Key=key, UploadId=upload)
                raise
        version = response.get("VersionId")
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"PreconditionFailed", "412"}:
            raise
        existing = s3.head_object(Bucket=BUCKET, Key=key)
        version = existing.get("VersionId")
    if not version or version == "null":
        raise ValueError("Upload did not return a durable S3 version")
    received = s3.get_object(Bucket=BUCKET, Key=key, VersionId=version)
    checksum = hashlib.sha256()
    observed = 0
    with received["Body"] as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            checksum.update(block)
            observed += len(block)
    if checksum.hexdigest() != sha or observed != size or received.get("ServerSideEncryption") != "aws:kms" or received.get("SSEKMSKeyId") != KMS_KEY:
        raise ValueError("Versioned S3 bytes/encryption do not match source")
    return {"bucket": BUCKET, "key": key, "version_id": version, "sha256": sha, "size_bytes": size}


def put_json(s3, key: str, value) -> dict:
    import io
    data = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    return _put(s3, key, io.BytesIO(data), hashlib.sha256(data).hexdigest(), len(data))


def stage_delivery(s3, contract: dict, root: Path, reference: dict | None = None, reference_root: Path | None = None) -> dict:
    """Inspection must succeed before any upload. File checksums in the source contract are mandatory."""
    import copy

    guard = storage_guard(s3)
    report = inspect_delivery(contract, root)
    plan = None
    if reference is not None:
        from .scrna_count import count_plan
        plan = count_plan(contract, root, reference, reference_root)
        if not plan["ready_for_reference_locked_counting"]:
            raise ValueError("Reference-locked counting preflight failed; do not upload an incompatible reference")
    intake_id = digest_json(contract)
    prefix = f"{ROOT_PREFIX}intakes/{intake_id}/"
    remote = copy.deepcopy(contract)
    objects = []
    for capture in remote["captures"]:
        original = next(c for c in contract["captures"] if c["capture_id"] == capture["capture_id"])
        for index, item in enumerate(capture["files"]):
            source = local_file(root, original["files"][index]["path"])
            # Role-index names preserve compression without putting vendor filenames in remote arguments/logs.
            suffix = ".gz" if source.suffix == ".gz" else ".h5" if item["role"].endswith("_h5") else ".dat"
            item["path"] = f"{capture['capture_id']}/{index}-{item['role']}{suffix}"
            with source.open("rb") as body:
                objects.append({"path": item["path"], **_put(s3, prefix + item["path"], body, item["sha256"], item["size_bytes"])})
        metadata = capture["metadata"]
        if metadata["status"] == "reviewed":
            source = local_file(root, original["metadata"]["path"])
            metadata["path"] = f"{capture['capture_id']}/vendor-metadata.dat"
            with source.open("rb") as body:
                objects.append({"path": metadata["path"], **_put(s3, prefix + metadata["path"], body, metadata["sha256"], source.stat().st_size)})
    validate_contract(remote)
    bundle = {"schema_version": 1, "intake_id": intake_id, "contract": remote, "objects": objects,
              "source_contract": contract, "inspection": report, "storage_guard": guard}
    if reference is not None:
        ref_objects = []
        for item in reference["files"].values():
            source = local_file(reference_root, item["path"])
            relative = "reference/" + safe_key(item["path"])
            with source.open("rb") as body:
                ref_objects.append({"path": relative, **_put(s3, prefix + relative, body, item["sha256"], item["size_bytes"])})
        bundle["count_reference"] = {"lock": reference, "objects": ref_objects}
    receipt = put_json(s3, prefix + "intake_bundle.json", bundle)
    return {"schema_version": 1, "intake_id": intake_id, "bundle": receipt, "inspection": report, "storage_guard": guard, "count_plan": plan}


def run_prefix(run_id: str) -> str:
    return f"{ROOT_PREFIX}runs/{safe_id(run_id)}/"


def signed_capabilities(s3, receipt: dict, run_id: str) -> dict:
    """Send exact-version GETs and a KMS-constrained POST policy, never AWS account credentials.

    Signed capabilities are bearer secrets. They are injected as ephemeral Modal
    Secrets, not function arguments, source files, logs, or saved receipts.
    """
    storage_guard(s3)
    intake_id = receipt["intake_id"]
    if not re.fullmatch(r"[a-f0-9]{64}", intake_id):
        raise ValueError("Invalid intake digest")
    bundle_item = receipt["bundle"]
    prefix = f"{ROOT_PREFIX}intakes/{intake_id}/"
    if bundle_item["bucket"] != BUCKET or bundle_item["key"] != prefix + "intake_bundle.json":
        raise ValueError("Intake bundle descriptor mismatch")
    response = s3.get_object(Bucket=BUCKET, Key=bundle_item["key"], VersionId=bundle_item["version_id"])
    content = response["Body"].read()
    if len(content) != bundle_item["size_bytes"] or hashlib.sha256(content).hexdigest() != bundle_item["sha256"]:
        raise ValueError("Intake bundle checksum mismatch")
    bundle = json.loads(content)
    if bundle.get("intake_id") != intake_id or digest_json(bundle["source_contract"]) != intake_id:
        raise ValueError("Intake bundle is not bound to its source contract")
    inputs = []
    expires = 10800 if bundle.get("count_reference") else 7200
    for item in [bundle_item] + bundle["objects"] + bundle.get("count_reference", {}).get("objects", []):
        if item["bucket"] != BUCKET or not safe_key(item["key"]).startswith(prefix) or not item.get("version_id"):
            raise ValueError("Signed input escapes chosen intake")
        url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET, "Key": item["key"], "VersionId": item["version_id"]}, ExpiresIn=expires)
        inputs.append({"key": item["key"], "version_id": item["version_id"], "url": url})
    output_prefix = run_prefix(run_id)
    fields = {"x-amz-server-side-encryption": "aws:kms", "x-amz-server-side-encryption-aws-kms-key-id": KMS_KEY,
              "success_action_status": "201", "x-amz-meta-sha256": ""}
    conditions = [{key: value} for key, value in fields.items() if key != "x-amz-meta-sha256"]
    conditions += [["content-length-range", 0, 1024**3], ["starts-with", "$x-amz-meta-sha256", ""]]
    post = s3.generate_presigned_post(Bucket=BUCKET, Key=output_prefix + "${filename}", Fields=fields, Conditions=conditions, ExpiresIn=expires)
    return {"inputs": inputs, "output": post, "output_prefix": output_prefix, "expires_in_seconds": expires}


def download_signed(capabilities: dict, item: dict, path: Path) -> None:
    import time

    import requests

    matches = [entry for entry in capabilities["inputs"] if entry["key"] == item["key"] and entry["version_id"] == item["version_id"]]
    if len(matches) != 1:
        raise ValueError("No exact-version read capability for this input")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("Signed download destination already exists")
    observed = 0
    for attempt in range(3):
        try:
            headers = {"Range": f"bytes={observed}-"} if observed else {}
            with requests.get(matches[0]["url"], headers=headers, stream=True, timeout=(30, 120), allow_redirects=False) as response:
                if response.status_code in {500, 502, 503, 504}:
                    raise requests.ConnectionError("Transient private source service failure")
                if response.status_code != (206 if observed else 200) or response.headers.get("x-amz-version-id") != item["version_id"] or response.headers.get("x-amz-server-side-encryption") != "aws:kms" or response.headers.get("x-amz-server-side-encryption-aws-kms-key-id") != KMS_KEY:
                    raise ValueError("Private signed read failed/version/encryption mismatch")
                if observed and not response.headers.get("Content-Range", "").startswith(f"bytes {observed}-"):
                    raise ValueError("Resumed input range mismatch")
                with path.open("ab" if observed else "xb") as output:
                    for block in response.iter_content(chunk_size=1024**2):
                        observed += len(block)
                        if observed > item["size_bytes"]:
                            raise ValueError("Input exceeds receipt size")
                        output.write(block)
            break
        except requests.RequestException:
            if attempt == 2:
                raise RuntimeError("Private signed download failed after three attempts; credentials/URLs omitted") from None
            if not observed and path.exists():
                path.unlink()
            time.sleep(2 * (attempt + 1))
    if observed != item["size_bytes"] or sha256_file(path) != item["sha256"]:
        raise ValueError("Downloaded signed input differs from receipt")


def upload_signed(capabilities: dict, key: str, path: Path) -> dict:
    import time

    import requests
    from requests_toolbelt.multipart.encoder import MultipartEncoder

    if not safe_key(key).startswith(capabilities["output_prefix"]):
        raise ValueError("Upload escapes selected run")
    fields = dict(capabilities["output"]["fields"], key=key, **{"x-amz-meta-sha256": sha256_file(path)})
    for attempt in range(3):
        try:
            with path.open("rb") as body:
                multipart = MultipartEncoder(fields=[*fields.items(), ("file", ("artifact", body, "application/octet-stream"))])
                response = requests.post(capabilities["output"]["url"], data=multipart, headers={"Content-Type": multipart.content_type}, timeout=(30, 120), allow_redirects=False)
            if response.status_code in {500, 502, 503, 504}:
                raise requests.ConnectionError("Transient private destination service failure")
            if response.status_code != 201 or not response.headers.get("x-amz-version-id"):
                raise RuntimeError("Private signed upload failed; inspect access and expiration, without logging signed credentials")
            break
        except requests.RequestException:
            if attempt == 2:
                raise RuntimeError("Private signed upload failed after three attempts; credentials/URLs omitted") from None
            time.sleep(2 * (attempt + 1))
    return {"key": key, "version_id": response.headers["x-amz-version-id"], "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def download_version(s3, item: dict, path: Path) -> None:
    if item["bucket"] != BUCKET or not safe_key(item["key"]).startswith(ROOT_PREFIX + "intakes/") or not item.get("version_id"):
        raise ValueError("Input receipt is outside private versioned intake")
    path.parent.mkdir(parents=True, exist_ok=True)
    response = s3.get_object(Bucket=BUCKET, Key=item["key"], VersionId=item["version_id"])
    if response.get("ServerSideEncryption") != "aws:kms" or response.get("SSEKMSKeyId") != KMS_KEY:
        raise ValueError("Input encryption mismatch")
    with response["Body"] as stream, path.open("xb") as output:
        observed = 0
        while block := stream.read(1024**2):
            observed += len(block)
            if observed > item["size_bytes"]:
                raise ValueError("Input is larger than receipt")
            output.write(block)
    if observed != item["size_bytes"] or sha256_file(path) != item["sha256"]:
        raise ValueError("Downloaded version differs from intake receipt")


def collect_private(s3, run_id: str, destination: Path) -> dict:
    """Validate all controls before writing anything. A failed collection never claims completion."""
    storage_guard(s3)
    prefix = run_prefix(run_id)
    controls = {}
    for name in ("run_manifest.json", "artifact_index.json"):
        response = s3.get_object(Bucket=BUCKET, Key=prefix + name)
        if not response.get("VersionId") or response.get("ServerSideEncryption") != "aws:kms" or response.get("SSEKMSKeyId") != KMS_KEY:
            raise ValueError("Unversioned or unencrypted run control")
        controls[name] = response["Body"].read()
    manifest = json.loads(controls["run_manifest.json"])
    index_version = manifest.get("artifact_versions", {}).get("artifact_index.json")
    if not index_version:
        raise ValueError("Missing immutable index version")
    response = s3.get_object(Bucket=BUCKET, Key=prefix + "artifact_index.json", VersionId=index_version)
    controls["artifact_index.json"] = response["Body"].read()
    index = json.loads(controls["artifact_index.json"])
    validate_artifact_index(index)
    if manifest.get("run_id") != run_id or manifest.get("status") != "complete" or manifest.get("evidence_lane") not in {"patient_research", "public_control"} or hashlib.sha256(controls["artifact_index.json"]).hexdigest() != manifest.get("artifact_index_sha256"):
        raise ValueError("Incomplete or inconsistent private run")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Collection destination must be empty")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.is_symlink():
        raise ValueError("Collection destination is a symlink")
    for record in index:
        path = destination / safe_key(record["path"])
        if not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError("Artifact escapes collection root")
        path.parent.mkdir(parents=True, exist_ok=True)
        version = manifest.get("artifact_versions", {}).get(record["path"])
        if not version:
            raise ValueError("Missing immutable artifact version")
        response = s3.get_object(Bucket=BUCKET, Key=prefix + record["path"], VersionId=version)
        if response.get("ServerSideEncryption") != "aws:kms" or response.get("SSEKMSKeyId") != KMS_KEY or response.get("VersionId") != version:
            raise ValueError("Artifact encryption/version mismatch")
        with response["Body"] as body, path.open("xb") as out:
            observed = 0
            while block := body.read(1024**2):
                observed += len(block)
                if observed > record["size_bytes"]:
                    raise ValueError("Artifact exceeds indexed size")
                out.write(block)
        if observed != record["size_bytes"] or sha256_file(path) != record["sha256"]:
            raise ValueError("Private artifact checksum/size mismatch")
    for name, data in controls.items():
        (destination / name).write_bytes(data)
    return {"status": "all_artifacts_verified", "run_id": run_id, "artifacts": len(index), "clinical_ready": False}
