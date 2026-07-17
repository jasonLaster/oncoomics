#!/usr/bin/env python3
"""Copy noncurrent S3 object versions into a public SSE-S3 archive namespace."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote


def aws_json(*args: str, allow_failure: bool = False) -> dict:
    command = ["aws", *args, "--output", "json"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        if allow_failure:
            return {"error": result.stderr.strip(), "returncode": result.returncode}
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr.strip()}")
    return json.loads(result.stdout or "{}")


def archive_key(prefix: str, key: str, version_id: str) -> str:
    digest = hashlib.sha256(f"{key}\0{version_id}".encode()).hexdigest()
    return f"{prefix.rstrip('/')}/objects/{digest[:2]}/{digest}"


def existing_archive(bucket: str, prefix: str) -> dict[str, int]:
    response = aws_json(
        "s3api",
        "list-objects-v2",
        "--bucket",
        bucket,
        "--prefix",
        f"{prefix.rstrip('/')}/objects/",
    )
    return {item["Key"]: item["Size"] for item in response.get("Contents", [])}


def copy_version(
    *, bucket: str, prefix: str, version: dict, existing: dict[str, int]
) -> dict:
    key = version["Key"]
    version_id = version["VersionId"]
    destination = archive_key(prefix, key, version_id)
    base = {
        "archive_key": destination,
        "original_key": key,
        "version_id": version_id,
        "original_last_modified": version["LastModified"],
        "bytes": version["Size"],
        "original_etag": version["ETag"].strip('"'),
        "original_storage_class": version.get("StorageClass", "STANDARD"),
    }
    if destination in existing:
        if existing[destination] != version["Size"]:
            return {
                **base,
                "status": "error",
                "error": "existing archive object has the wrong size",
            }
        return {**base, "status": "already_present", "archive_encryption": "AES256"}

    copy_source = (
        f"{bucket}/{quote(key, safe='/')}?versionId={quote(version_id, safe='')}"
    )
    response = aws_json(
        "s3api",
        "copy-object",
        "--bucket",
        bucket,
        "--key",
        destination,
        "--copy-source",
        copy_source,
        "--server-side-encryption",
        "AES256",
        allow_failure=True,
    )
    if "error" in response:
        return {**base, "status": "error", "error": response["error"]}
    result = response.get("CopyObjectResult", {})
    return {
        **base,
        "status": "copied",
        "archive_etag": result.get("ETag", "").strip('"'),
        "archive_last_modified": result.get("LastModified"),
        "archive_encryption": response.get("ServerSideEncryption"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()

    snapshot = json.loads(args.snapshot.read_text())
    versions = sorted(
        (item for item in snapshot.get("Versions", []) if not item["IsLatest"]),
        key=lambda item: (item["Key"], item["LastModified"], item["VersionId"]),
    )
    existing = existing_archive(args.bucket, args.prefix)
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                copy_version,
                bucket=args.bucket,
                prefix=args.prefix,
                version=version,
                existing=existing,
            )
            for version in versions
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if index % 100 == 0 or result["status"] == "error":
                print(
                    json.dumps(
                        {
                            "completed": index,
                            "total": len(versions),
                            "last_status": result["status"],
                        }
                    ),
                    flush=True,
                )

    results.sort(key=lambda item: (item["original_key"], item["version_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in results)
    )
    failures = [item for item in results if item["status"] == "error"]
    print(
        json.dumps(
            {
                "archived_versions": len(results) - len(failures),
                "failed_versions": len(failures),
                "bytes": sum(
                    item["bytes"] for item in results if item["status"] != "error"
                ),
                "output": str(args.output),
            }
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
