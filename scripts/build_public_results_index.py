#!/usr/bin/env python3
"""Build a static index for explicitly reviewed public S3 result prefixes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
from typing import Any


REGION = "us-east-1"
BUCKET = "diana-omics-results-172630973301-us-east-1"
PUBLIC_PREFIXES = (
    "runs/known_answer_bounded_non_dry/",
    "runs/known_answer_expanded_cohort/",
    "runs/known_answer_public_findings/",
    "runs/phase3_fastpath_forcealign_minimap2_scatter8_normal_shardmanifest_20260614T2117Z/",
    "runs/phase3_fastpath_forcealign_minimap2_scatter8_tumor_shardmanifest_20260614T2040Z/",
    "runs/phase3_sra_benchmark/",
    "runs/phase3_wgs/",
    "runs/phase3_wgs_scatter/",
    "runs/rosalind_hrd/cloud-colo829-guardrail-20260617/",
    "runs/rosalind_hrd/cloud-hcc1395-wes-20260617/",
    "runs/rosalind_hrd/cloud-helper-selective5-20260617/",
    "runs/rosalind_hrd/cloud-hg008-depth-20260617/",
    "runs/rosalind_hrd/cloud-selective5-20260617/",
)
FORBIDDEN_PREFIXES = (
    "runs/diana-hrd/",
    "runs/diana-raw-intake/",
    "runs/rosalind_hrd/cloud-diana-raw-intake-20260617/",
    "runs/rosalind_hrd/cloud-diana-raw-intake-handoff-20260617/",
    "version-history/",
)


def list_prefix(prefix: str) -> list[dict[str, Any]]:
    command = [
        "aws",
        "s3api",
        "list-objects-v2",
        "--region",
        REGION,
        "--bucket",
        BUCKET,
        "--prefix",
        prefix,
        "--output",
        "json",
    ]
    result = subprocess.run(command, check=True, text=True, capture_output=True)
    response = json.loads(result.stdout)
    objects: list[dict[str, Any]] = []
    for item in response.get("Contents", []):
        key = item["Key"]
        if not key.startswith(prefix):
            raise RuntimeError(f"S3 returned an object outside {prefix}: {key}")
        if any(key.startswith(blocked) for blocked in FORBIDDEN_PREFIXES):
            raise RuntimeError(f"Refusing to index private object: {key}")
        if key.endswith("/"):
            continue
        objects.append(
            {
                "key": key,
                "size": item["Size"],
                "last_modified": item["LastModified"],
            }
        )
    return objects


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()

    objects: list[dict[str, Any]] = []
    for prefix in PUBLIC_PREFIXES:
        objects.extend(list_prefix(prefix))
    objects.sort(key=lambda item: item["key"])

    keys = [item["key"] for item in objects]
    if len(keys) != len(set(keys)):
        raise RuntimeError("Public prefix overlap produced duplicate keys")

    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bucket": BUCKET,
        "classification": "reviewed_public_validation_outputs",
        "prefixes": list(PUBLIC_PREFIXES),
        "object_count": len(objects),
        "total_size": sum(item["size"] for item in objects),
        "objects": objects,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "object_count": payload["object_count"],
                "total_size": payload["total_size"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
