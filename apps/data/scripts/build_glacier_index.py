#!/usr/bin/env python3
"""Build the public, metadata-only index for the Diana Glacier cache."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import tempfile
from typing import Any

BUCKET = "diana-omics-raw-inputs-172630973301-us-east-1"
PREFIX = "cache/phase3_wgs/"
REGION = "us-east-1"
STORAGE_CLASS = "GLACIER"


def list_objects() -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    continuation_token = ""

    while True:
        command = [
            "aws",
            "s3api",
            "list-objects-v2",
            "--bucket",
            BUCKET,
            "--prefix",
            PREFIX,
            "--region",
            REGION,
            "--output",
            "json",
        ]
        if continuation_token:
            command.extend(["--continuation-token", continuation_token])

        response = json.loads(
            subprocess.run(command, check=True, capture_output=True, text=True).stdout
        )
        for item in response.get("Contents", []):
            key = item.get("Key")
            size = item.get("Size")
            storage_class = item.get("StorageClass")
            last_modified = item.get("LastModified")
            if not isinstance(key, str) or not key.startswith(PREFIX) or key.endswith("/"):
                raise RuntimeError(f"S3 returned an invalid archive key: {key!r}")
            if type(size) is not int or size < 0:
                raise RuntimeError(f"S3 returned an invalid size for {key}")
            if storage_class != STORAGE_CLASS:
                raise RuntimeError(
                    f"Refusing to publish {key}: expected {STORAGE_CLASS}, got {storage_class}"
                )
            if not isinstance(last_modified, str) or not last_modified:
                raise RuntimeError(f"S3 returned an invalid timestamp for {key}")
            objects.append(
                {
                    "key": key,
                    "last_modified": last_modified,
                    "size": size,
                    "storage_class": storage_class,
                }
            )

        if response.get("IsTruncated") is not True:
            break
        continuation_token = response.get("NextContinuationToken", "")
        if not isinstance(continuation_token, str) or not continuation_token:
            raise RuntimeError("S3 pagination did not provide a continuation token")

    return sorted(objects, key=lambda item: item["key"])


def write_index(path: pathlib.Path, objects: list[dict[str, Any]]) -> None:
    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bucket": BUCKET,
        "prefix": PREFIX,
        "storage_class": STORAGE_CLASS,
        "retrieval_class": "Glacier Flexible Retrieval",
        "object_count": len(objects),
        "total_size": sum(item["size"] for item in objects),
        "objects": objects,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(rendered)
        temporary = pathlib.Path(handle.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path(__file__).parents[1] / "public" / "glacier-index.json",
    )
    arguments = parser.parse_args()
    objects = list_objects()
    write_index(arguments.output, objects)
    print(
        f"Wrote {len(objects)} Glacier objects "
        f"({sum(item['size'] for item in objects)} bytes) to {arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
