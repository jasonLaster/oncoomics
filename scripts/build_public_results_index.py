#!/usr/bin/env python3
"""Build a static index for explicitly reviewed public S3 analysis prefixes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import tempfile
from typing import Any, Sequence

from publish_reviewed_public_report import METHOD_CONTRACTS, PUBLIC_ROOT

REGION = "us-east-1"
BUCKET = "diana-omics-results-172630973301-us-east-1"
DIANA_HRD_PUBLIC_PREFIXES = tuple(
    PUBLIC_ROOT + str(contract["destination"])
    for contract in METHOD_CONTRACTS.values()
)
PUBLIC_PREFIXES = (
    *DIANA_HRD_PUBLIC_PREFIXES,
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
    "runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/",
    "runs/diana-raw-intake/",
    "runs/rosalind_hrd/cloud-diana-raw-intake-20260617/",
    "runs/rosalind_hrd/cloud-diana-raw-intake-handoff-20260617/",
    "version-history/",
)


def list_prefix(prefix: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    continuation_token = ""
    seen_tokens: set[str] = set()

    while True:
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
        if continuation_token:
            command.extend(["--continuation-token", continuation_token])
        result = subprocess.run(command, check=True, text=True, capture_output=True)
        response = json.loads(result.stdout)
        contents = response.get("Contents", [])
        if not isinstance(contents, list) or any(
            not isinstance(item, dict) for item in contents
        ):
            raise RuntimeError(f"S3 returned malformed objects for {prefix}")
        for item in contents:
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

        if response.get("IsTruncated") is not True:
            return objects
        next_token = str(response.get("NextContinuationToken", ""))
        if not next_token or next_token in seen_tokens:
            raise RuntimeError(f"S3 pagination did not advance for {prefix}")
        seen_tokens.add(next_token)
        continuation_token = next_token


def write_index(path: pathlib.Path, payload: dict[str, Any]) -> None:
    """Atomically write the local public index without following symlinks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeError(f"Refusing to write public index through symlink: {path}")
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = pathlib.Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)

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
        "classification": "reviewed_public_validation_and_alias_only_analysis_outputs",
        "prefixes": list(PUBLIC_PREFIXES),
        "object_count": len(objects),
        "total_size": sum(item["size"] for item in objects),
        "objects": objects,
    }
    write_index(args.output, payload)
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
