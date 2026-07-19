#!/usr/bin/env python3
"""Recover reviewed Diana HRD artifacts into a pseudonymous public alias tree."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
from typing import Any

REGION = "us-east-1"
WORK_BUCKET = "diana-omics-work-172630973301-us-east-1"
WORK_PREFIX = "runs/diana-hrd/diana-wgs-hrd-20260716T033101Z/private-results/early-look/"
PRESERVATION_BUCKET = "diana-omics-raw-inputs-172630973301-us-east-1"
PRESERVATION_PREFIX = "security/incidents/2026-07-17/results-bucket-preservation/"
DESTINATION_BUCKET = "diana-omics-results-172630973301-us-east-1"
DESTINATION_PREFIX = "runs/diana-hrd-public/subject01/diana-wgs-hrd-20260716T033101Z/"
EXPECTED_WORK_OBJECTS = 143
EXPECTED_WORK_BYTES = 949_788_813
EXPECTED_HISTORICAL_OBJECTS = 20
EXPECTED_HISTORICAL_BYTES = 27_135
EXPECTED_KMS_KEY = "arn:aws:kms:us-east-1:172630973301:key/45aa290c-d70c-4d86-9c8d-c4a76f1ff97f"
CLASSIFICATION = "reviewed-public-pseudonymous-analysis"

REPLACEMENTS = (
    (b"DRF-PSN49561_normal", b"subject01_normal"),
    (b"DRF-PSN49561_tumor", b"subject01_tumor"),
    (b"DRF-PSN49561", b"subject01"),
)
FORBIDDEN_TOKENS = (
    b"DRF-PSN49561",
    b"E019_S01",
    b"echo-personalis",
    b"personalis",
)
TEXT_SUFFIXES = {".bed", ".csv", ".json", ".md", ".table", ".tsv", ".txt"}
VARIANT_FILES = {
    "core_hrr.mutect2.filtered.vcf.gz",
    "core_hrr.mutect2.filtered.vcf.gz.filteringStats.tsv",
    "core_hrr_all_filtered_variants.csv",
    "core_hrr_grch38_gene_spans_plus_100bp.bed",
    "core_hrr_pass_variants.csv",
    "core_hrr_variant_summary.json",
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def checksum_sha256(digest: str) -> str:
    return base64.b64encode(bytes.fromhex(digest)).decode()


def exact_s3_size(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} is not an exact nonnegative S3 size")
    return value


def exact_s3_key(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is not an exact nonempty S3 key")
    return value


def exact_version_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value == "null":
        raise ValueError(f"{label} is not a non-null S3 VersionId")
    return value


def exact_crc64nvme(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is not an exact CRC64NVME checksum")
    return value


def inventory_total_bytes(rows: list[dict[str, Any]], label: str) -> int:
    total = 0
    for index, row in enumerate(rows, 1):
        key = exact_s3_key(row.get("Key"), f"{label} object {index} Key")
        total += exact_s3_size(row.get("Size"), f"{label} {key} Size")
    return total


def validate_final_destination_history(
    versions: list[dict[str, Any]],
    markers: list[dict[str, Any]],
    uploaded_records: list[dict[str, Any]],
) -> None:
    if markers:
        raise ValueError("final destination history contains delete markers")

    expected: dict[str, dict[str, Any]] = {}
    for record in uploaded_records:
        key = str(record.get("destination_key", ""))
        if not key.startswith(DESTINATION_PREFIX):
            raise ValueError(
                f"final destination record is outside the alias prefix: {key}"
            )
        upload = record.get("upload")
        if not isinstance(upload, dict):
            raise ValueError(
                f"final destination record is missing upload evidence: {key}"
            )
        if key in expected:
            raise ValueError(f"final destination record is duplicated: {key}")
        expected[key] = {
            "bytes": exact_s3_size(
                record.get("bytes"),
                f"final destination {key} bytes",
            ),
            "version_id": exact_version_id(
                upload.get("version_id"),
                f"final destination {key} upload VersionId",
            ),
        }

    if len(versions) != len(expected):
        raise ValueError("final destination history is not exactly one version per object")

    observed: set[str] = set()
    for version in versions:
        key = str(version.get("Key", ""))
        if key not in expected:
            raise ValueError(
                f"final destination history contains an unexpected key: {key}"
            )
        if key in observed:
            raise ValueError(f"final destination history contains a duplicate key: {key}")
        observed.add(key)
        if version.get("IsLatest") is not True:
            raise ValueError(
                f"final destination history contains a non-latest version: {key}"
            )

        expected_record = expected[key]
        observed_version_id = exact_version_id(
            version.get("VersionId"),
            f"final destination {key} history VersionId",
        )
        if observed_version_id != expected_record["version_id"]:
            raise ValueError(f"final destination history VersionId differs: {key}")

        observed_size = exact_s3_size(
            version.get("Size"),
            f"final destination {key} history Size",
        )
        if observed_size != expected_record["bytes"]:
            raise ValueError(f"final destination history byte count differs: {key}")

    if observed != set(expected):
        raise ValueError("final destination history is missing an expected object")


def aws_json(*arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["aws", *arguments, "--region", REGION, "--output", "json"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    value = json.loads(completed.stdout) if completed.stdout.strip() else {}
    if not isinstance(value, dict):
        raise ValueError("AWS command returned a non-object")
    return value


def require_safe_private_output_parent(path: pathlib.Path) -> None:
    if path.is_symlink():
        raise ValueError(f"receipt output may not be a symlink: {path}")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"receipt output parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"receipt output parent is not a directory: {parent}")


def is_platform_root_alias(path: pathlib.Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_new_private_output(path: pathlib.Path) -> None:
    require_safe_private_output_parent(path)
    if path.exists():
        raise ValueError(f"receipt output already exists: {path}")


def fsync_directory(path: pathlib.Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_private(path: pathlib.Path, value: Any, *, create: bool) -> None:
    require_safe_private_output_parent(path)
    if not create and (path.is_symlink() or not path.is_file()):
        raise ValueError(f"reserved receipt output is missing: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if create:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        temporary: pathlib.Path | None = None
    else:
        descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        os.fchmod(descriptor, 0o600)
        temporary = pathlib.Path(raw)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        if temporary is not None:
            os.replace(temporary, path)
        fsync_directory(path.parent)
    except Exception:
        if temporary is None:
            path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def list_objects(bucket: str, prefix: str) -> list[dict[str, Any]]:
    payload = aws_json("s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix)
    rows = payload.get("Contents", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"malformed object listing for s3://{bucket}/{prefix}")
    for index, row in enumerate(rows, 1):
        key = exact_s3_key(row.get("Key"), f"listed object {index} Key")
        exact_s3_size(row.get("Size"), f"listed object {key} Size")
    return sorted(rows, key=lambda row: row["Key"])


def list_destination_history() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = aws_json(
        "s3api",
        "list-object-versions",
        "--bucket",
        DESTINATION_BUCKET,
        "--prefix",
        DESTINATION_PREFIX,
    )
    versions = payload.get("Versions", [])
    markers = payload.get("DeleteMarkers", [])
    if not isinstance(versions, list) or not isinstance(markers, list):
        raise ValueError("destination version history is malformed")
    return versions, markers


def head(bucket: str, key: str) -> dict[str, Any]:
    return aws_json(
        "s3api",
        "head-object",
        "--bucket",
        bucket,
        "--key",
        key,
        "--checksum-mode",
        "ENABLED",
    )


def source_evidence(bucket: str, row: dict[str, Any]) -> dict[str, Any]:
    key = exact_s3_key(row.get("Key"), "source listing Key")
    listed_size = exact_s3_size(row.get("Size"), f"source listing {key} Size")
    evidence = head(bucket, key)
    head_size = exact_s3_size(
        evidence.get("ContentLength"),
        f"source head {key} ContentLength",
    )
    checksum = exact_crc64nvme(
        evidence.get("ChecksumCRC64NVME"),
        f"source head {key} ChecksumCRC64NVME",
    )
    checks = {
        "bytes": head_size == listed_size,
        "encryption": evidence.get("ServerSideEncryption") == "aws:kms",
        "kms_key": evidence.get("SSEKMSKeyId") == EXPECTED_KMS_KEY,
        "checksum": bool(checksum),
        "checksum_type": evidence.get("ChecksumType") == "FULL_OBJECT",
    }
    if not all(checks.values()):
        raise ValueError(f"source custody check failed for {key}: {checks}")
    return {
        "bucket": bucket,
        "key": key,
        "bytes": listed_size,
        "checksum_crc64nvme": checksum,
        "content_type": str(evidence.get("ContentType", "application/octet-stream")),
    }


def download(source: dict[str, Any], path: pathlib.Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "aws",
            "s3api",
            "get-object",
            "--bucket",
            source["bucket"],
            "--key",
            source["key"],
            "--checksum-mode",
            "ENABLED",
            "--region",
            REGION,
            "--output",
            "json",
            str(path),
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    response = json.loads(completed.stdout) if completed.stdout.strip() else {}
    if response.get("ChecksumCRC64NVME") != source["checksum_crc64nvme"]:
        raise ValueError(f"download checksum response mismatch for {source['key']}")
    data = path.read_bytes()
    if len(data) != source["bytes"]:
        raise ValueError(f"download byte count mismatch for {source['key']}")
    return data


def selected_early_look(relative: str) -> bool:
    try:
        relative = safe_relative_key(relative, "early-look source key")
    except ValueError:
        return False

    if relative in {"artifacts/README.md", "artifacts/early_look_summary.json"}:
        return True
    if relative.startswith("artifacts/qc/"):
        return True
    if relative.startswith("artifacts/coverage_cnv/"):
        return True
    if relative in {
        "artifacts/contamination/contamination.table",
        "artifacts/contamination/contamination_summary.json",
        "artifacts/contamination/tumor-segmentation.table",
    }:
        return True
    if relative.startswith("artifacts/variants/"):
        return pathlib.PurePosixPath(relative).name in VARIANT_FILES
    return relative in {
        "handoff/VARIANT_REVIEW.tsv",
        "handoff/annotations/core_hrr.mutect2.filtered.ensembl116.vcf.gz",
    }


def safe_relative_key(value: str, label: str) -> str:
    path = pathlib.PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or ".." in path.parts
    ):
        raise ValueError(f"{label} is unsafe: {value}")
    return value


def destination_relative(destination_key: str) -> str:
    if not destination_key.startswith(DESTINATION_PREFIX):
        raise ValueError(
            f"destination key is outside the public alias prefix: {destination_key}"
        )
    return safe_relative_key(
        destination_key.removeprefix(DESTINATION_PREFIX),
        "destination key",
    )


def replace_tokens(data: bytes) -> bytes:
    for source, alias in REPLACEMENTS:
        data = data.replace(source, alias)
    return data


def scan_public_bytes(key: str, data: bytes) -> None:
    lowered = data.lower()
    matched = [token.decode(errors="replace") for token in FORBIDDEN_TOKENS if token.lower() in lowered]
    if matched:
        raise ValueError(f"forbidden identifiers remain in {key}: {matched}")


def bgzip(data: bytes) -> bytes:
    completed = subprocess.run(
        ["bgzip", "-c"],
        input=data,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def materialize_source(
    source: dict[str, Any],
    destination_key: str,
    staging: pathlib.Path,
) -> dict[str, Any]:
    destination_path = staging / "public" / destination_relative(destination_key)
    raw_path = staging / "downloads" / hashlib.sha256(source["key"].encode()).hexdigest()
    raw = download(source, raw_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    transformed = False
    if destination_key.endswith(".vcf.gz"):
        decoded = gzip.decompress(raw)
        published = bgzip(replace_tokens(decoded))
        scan_public_bytes(destination_key, gzip.decompress(published))
        transformed = published != raw
    elif pathlib.PurePosixPath(destination_key).suffix in TEXT_SUFFIXES:
        published = replace_tokens(raw)
        published.decode("utf-8")
        scan_public_bytes(destination_key, published)
        transformed = published != raw
    else:
        published = raw
        scan_public_bytes(destination_key, published)
    destination_path.write_bytes(published)
    return {
        "source": source,
        "destination_key": destination_key,
        "path": str(destination_path),
        "bytes": len(published),
        "sha256": hashlib.sha256(published).hexdigest(),
        "content_type": content_type(destination_key),
        "transformed": transformed,
    }


def content_type(key: str) -> str:
    if key.endswith(".json"):
        return "application/json"
    if key.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if key.endswith((".csv", ".tsv", ".table", ".txt", ".bed")):
        return "text/plain; charset=utf-8"
    if key.endswith(".vcf.gz"):
        return "application/gzip"
    if key.endswith(".tbi"):
        return "application/octet-stream"
    return "application/octet-stream"


def generated_object(staging: pathlib.Path, relative: str, data: bytes) -> dict[str, Any]:
    relative = safe_relative_key(relative, "generated object key")
    key = f"{DESTINATION_PREFIX}{relative}"
    scan_public_bytes(key, data)
    path = staging / "public" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "source": None,
        "destination_key": key,
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_type": content_type(key),
        "transformed": False,
    }


def private_receipt_source(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if source is None:
        return None
    return {
        "bucket": source["bucket"],
        "key": source["key"],
        "bytes": source["bytes"],
        "checksum_crc64nvme": source["checksum_crc64nvme"],
    }


def publication_manifest_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "destination_key": item["destination_key"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "transformed": item["transformed"],
        }
        for item in sorted(items, key=lambda value: value["destination_key"])
    ]


def build_readme() -> bytes:
    return (
        b"# Diana WGS HRD public analysis\n\n"
        b"This alias-only tree publishes reviewed research analysis for run "
        b"`diana-wgs-hrd-20260716T033101Z` as `subject01`. The data owner "
        b"authorized public analysis distribution for collaborator access and "
        b"public cross-reference.\n\n"
        b"The recovered early-look result remains `partial_evidence`; overall HRD "
        b"is `no_call`. It must not be interpreted as a clinical result. Raw FASTQs, "
        b"BAMs, contamination pileups, direct source identifiers, CloudWatch logs, "
        b"and version-history/custody inventories are intentionally excluded.\n\n"
        b"Start with `early-look/artifacts/early_look_summary.json`, "
        b"`early-look/artifacts/variants/core_hrr_variant_summary.json`, and "
        b"`early-look/handoff/VARIANT_REVIEW.tsv`. The `historical/` subtree contains "
        b"superseded pre-data Rosalind protocol packets for provenance only.\n"
    )


def build_historical_readme() -> bytes:
    return (
        b"# Superseded pre-data Rosalind packets\n\n"
        b"These two recovered packets predate arrival and analysis of the Diana WGS "
        b"data. They report `waiting_for_diana_raw_data` and `no_call`; they are "
        b"published only as historical workflow/protocol provenance. They are not "
        b"inputs to the current HRD interpretation.\n"
    )


def upload(item: dict[str, Any]) -> dict[str, Any]:
    digest_bytes = bytes.fromhex(item["sha256"])
    expected_checksum = base64.b64encode(digest_bytes).decode()
    metadata = {
        "classification": CLASSIFICATION,
        "sha256": item["sha256"],
    }
    response = aws_json(
        "s3api",
        "put-object",
        "--bucket",
        DESTINATION_BUCKET,
        "--key",
        item["destination_key"],
        "--body",
        item["path"],
        "--content-type",
        item["content_type"],
        "--server-side-encryption",
        "AES256",
        "--checksum-algorithm",
        "SHA256",
        "--checksum-sha256",
        expected_checksum,
        "--metadata",
        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    )
    version_id = exact_version_id(
        response.get("VersionId"),
        f"put-object {item['destination_key']} VersionId",
    )
    evidence = head(DESTINATION_BUCKET, item["destination_key"])
    destination_size = exact_s3_size(
        evidence.get("ContentLength"),
        f"destination {item['destination_key']} ContentLength",
    )
    checks = {
        "bytes": destination_size == item["bytes"],
        "checksum": evidence.get("ChecksumSHA256") == expected_checksum,
        "checksum_type": evidence.get("ChecksumType") == "FULL_OBJECT",
        "encryption": evidence.get("ServerSideEncryption") == "AES256",
        "version": evidence.get("VersionId") == version_id,
        "metadata": evidence.get("Metadata", {}) == metadata,
    }
    if not all(checks.values()):
        raise ValueError(f"destination verification failed for {item['destination_key']}: {checks}")
    return {"version_id": version_id, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt-output", required=True, type=pathlib.Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        require_new_private_output(args.receipt_output)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    receipt: dict[str, Any] = {
        "schema_version": 2,
        "status": "preflighting",
        "generated_at_utc": now(),
        "apply": args.apply,
        "destination": {"bucket": DESTINATION_BUCKET, "prefix": DESTINATION_PREFIX},
        "classification": CLASSIFICATION,
        "objects": [],
    }
    write_private(args.receipt_output, receipt, create=True)

    try:
        work_rows = list_objects(WORK_BUCKET, WORK_PREFIX)
        if (
            len(work_rows) != EXPECTED_WORK_OBJECTS
            or inventory_total_bytes(work_rows, "preserved early-look")
            != EXPECTED_WORK_BYTES
        ):
            raise ValueError("preserved early-look inventory changed")
        selected = [
            row
            for row in work_rows
            if selected_early_look(str(row["Key"]).removeprefix(WORK_PREFIX))
        ]

        preserved_rows = list_objects(PRESERVATION_BUCKET, PRESERVATION_PREFIX)
        historical = [row for row in preserved_rows if "/runs/rosalind_hrd/" in str(row["Key"])]
        if (
            len(historical) != EXPECTED_HISTORICAL_OBJECTS
            or inventory_total_bytes(historical, "preserved historical Rosalind")
            != EXPECTED_HISTORICAL_BYTES
        ):
            raise ValueError("preserved historical Rosalind inventory changed")

        versions, markers = list_destination_history()
        if versions or markers:
            raise ValueError("destination alias prefix is not create-only empty")

        with tempfile.TemporaryDirectory(prefix="diana-public-recovery-") as raw_staging:
            staging = pathlib.Path(raw_staging)
            items: list[dict[str, Any]] = []
            for row in selected:
                source = source_evidence(WORK_BUCKET, row)
                relative = source["key"].removeprefix(WORK_PREFIX)
                items.append(
                    materialize_source(
                        source,
                        f"{DESTINATION_PREFIX}early-look/{relative}",
                        staging,
                    )
                )

            for item in list(items):
                if not item["destination_key"].endswith(".vcf.gz"):
                    continue
                subprocess.run(
                    ["tabix", "-f", "-p", "vcf", item["path"]],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                index_path = pathlib.Path(f"{item['path']}.tbi")
                index_key = f"{item['destination_key']}.tbi"
                index_data = index_path.read_bytes()
                items.append(
                    {
                        "source": item["source"],
                        "destination_key": index_key,
                        "path": str(index_path),
                        "bytes": len(index_data),
                        "sha256": hashlib.sha256(index_data).hexdigest(),
                        "content_type": content_type(index_key),
                        "transformed": True,
                    }
                )

            for row in historical:
                source = source_evidence(PRESERVATION_BUCKET, row)
                relative = source["key"].split("/runs/rosalind_hrd/", 1)[1]
                items.append(
                    materialize_source(
                        source,
                        f"{DESTINATION_PREFIX}historical/superseded-rosalind/{relative}",
                        staging,
                    )
                )

            items.append(generated_object(staging, "README.md", build_readme()))
            items.append(
                generated_object(
                    staging,
                    "historical/superseded-rosalind/README.md",
                    build_historical_readme(),
                )
            )

            manifest = {
                "schema_version": 1,
                "generated_at_utc": receipt["generated_at_utc"],
                "classification": CLASSIFICATION,
                "evidence_state": "partial_evidence",
                "overall_hrd_state": "no_call",
                "objects": publication_manifest_rows(items),
            }
            items.append(generated_object(staging, "publication_manifest.json", canonical_bytes(manifest)))
            items.sort(key=lambda value: value["destination_key"])

            receipt["selected_early_look_source_objects"] = len(selected)
            receipt["historical_rosalind_source_objects"] = len(historical)
            receipt["publication_object_count"] = len(items)
            receipt["publication_total_bytes"] = sum(item["bytes"] for item in items)
            receipt["excluded_boundaries"] = [
                "raw FASTQ",
                "BAM and BAI",
                "contamination pileup tables",
                "direct source identifiers",
                "CloudWatch and Batch logs",
                "version-history and custody inventories",
                "unfiltered VCF and read-orientation evidence",
            ]

            for item in items:
                record = {
                    "destination_key": item["destination_key"],
                    "bytes": item["bytes"],
                    "sha256": item["sha256"],
                    "transformed": item["transformed"],
                    "source": private_receipt_source(item["source"]),
                    "action": "planned_upload",
                }
                if args.apply:
                    record["upload"] = upload(item)
                    record["action"] = "uploaded_and_verified"
                receipt["objects"].append(record)
                receipt["status"] = "publishing" if args.apply else "preflighting"
                write_private(args.receipt_output, receipt, create=False)

        if args.apply:
            final_versions, final_markers = list_destination_history()
            validate_final_destination_history(
                final_versions,
                final_markers,
                receipt["objects"],
            )

        receipt["status"] = "passed" if args.apply else "ready"
        receipt["completed_at_utc"] = now()
        receipt["checks"] = {
            "exact_preserved_source_inventory": True,
            "pseudonymous_forbidden_token_scan": True,
            "source_kms_crc64_bound": True,
            "public_destination_create_only": True,
            "historical_rosalind_labeled_superseded": True,
            "raw_bam_pileup_and_custody_material_excluded": True,
        }
        write_private(args.receipt_output, receipt, create=False)
    except Exception as error:
        receipt["status"] = "failed"
        receipt["failed_at_utc"] = now()
        receipt["error"] = f"{type(error).__name__}: {error}"
        write_private(args.receipt_output, receipt, create=False)
        raise SystemExit(f"Fail-closed: {error}") from error

    print(
        json.dumps(
            {
                "status": receipt["status"],
                "publication_object_count": receipt["publication_object_count"],
                "publication_total_bytes": receipt["publication_total_bytes"],
                "receipt": str(args.receipt_output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
