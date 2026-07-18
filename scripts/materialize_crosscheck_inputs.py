#!/usr/bin/env python3
"""Create alias-only PASS-SNV/SBS96 cross-check inputs in private S3.

The deterministic worker emits a filtered VCF and an SBS96 matrix.  This
materializer creates a true PASS-SNV VCF, replaces VCF sample identities with
the run aliases, rewrites the matrix without a source identifier, independently
re-derives all 96 contexts from the exact FASTA, and only then uploads the three
canonical artifacts with a hash-bound custody receipt.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

AWS = "/opt/diana-aws/bin/aws" if Path("/opt/diana-aws/bin/aws").exists() else shutil.which("aws") or "aws"
BASES = "ACGT"
SUBSTITUTIONS = ("C>A", "C>G", "C>T", "T>A", "T>C", "T>G")
CANONICAL = {f"{left}[{sub}]{right}" for sub in SUBSTITUTIONS for left in BASES for right in BASES}
CONTEXT = re.compile(r"^[ACGT]\[(C>A|C>G|C>T|T>A|T>C|T>G)\][ACGT]$")
COMPLEMENT = {"A": "T", "C": "G", "G": "C", "T": "A"}
STANDARD_CONTIGS = [f"chr{i}" for i in range(1, 23)] + ["chrX"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_safe_new_output_parent(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} may not be a symlink")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def require_safe_new_output(path: Path, label: str) -> None:
    require_safe_new_output_parent(path, label)
    if path.exists():
        raise FileExistsError(f"{label} already exists: {path}")


def require_real_local_file(path: Path, label: str) -> None:
    require_safe_new_output_parent(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def require_real_downloaded_file(path: Path, label: str) -> None:
    require_real_local_file(path, label)


def write_json_create_only(path: Path, value: dict[str, Any], label: str) -> None:
    require_safe_new_output_parent(path, label)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    fsync_directory(path.parent)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def capture(command: list[str]) -> str:
    output = subprocess.check_output(command, stderr=subprocess.STDOUT)
    return output.decode("utf-8", errors="replace").strip()


def normalize_context(row: dict[str, str]) -> str:
    direct = (row.get("MutationType") or row.get("context") or row.get("mutation_context") or "").strip()
    if CONTEXT.fullmatch(direct):
        return direct
    mutation = (row.get("mutation_type") or row.get("substitution") or "").strip()
    trinucleotide = (row.get("trinucleotide") or row.get("trinuc") or "").strip().upper()
    if mutation not in SUBSTITUTIONS or len(trinucleotide) != 3:
        raise ValueError(f"cannot derive an SBS96 context from row: {row}")
    value = f"{trinucleotide[0]}[{mutation}]{trinucleotide[2]}"
    if value not in CANONICAL:
        raise ValueError(f"non-canonical SBS96 context: {value}")
    return value


def matrix_counts(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("SBS96 matrix is empty")
    dialect = csv.Sniffer().sniff(text[:8192], delimiters=",\t")
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    counts: dict[str, int] = {}
    for row in reader:
        context = normalize_context(row)
        raw = row.get("count") or row.get("Count")
        if raw is None:
            candidates = [
                key for key in row
                if key not in {
                    "sample", "mutation_type", "substitution", "trinucleotide", "trinuc",
                    "MutationType", "context", "mutation_context",
                }
            ]
            if len(candidates) == 1:
                raw = row[candidates[0]]
        try:
            count = int(str(raw))
        except (TypeError, ValueError) as error:
            raise ValueError(f"non-integer SBS96 count for {context}: {raw}") from error
        if count < 0 or context in counts:
            raise ValueError(f"negative or duplicate SBS96 context: {context}")
        counts[context] = count
    if set(counts) != CANONICAL:
        raise ValueError("matrix does not contain exactly the 96 canonical SBS contexts")
    return counts


def write_alias_matrix(counts: dict[str, int], output: Path) -> None:
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["MutationType", "count"])
        for context in sorted(CANONICAL):
            writer.writerow([context, counts[context]])


class IndexedFasta:
    def __init__(self, fasta: Path, fai: Path):
        self.handle = fasta.open("rb")
        self.index: dict[str, tuple[int, int, int, int]] = {}
        for line in fai.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) < 5:
                raise ValueError(f"invalid FAI row: {line}")
            name, length, offset, line_bases, line_width = fields[:5]
            self.index[name] = (int(length), int(offset), int(line_bases), int(line_width))
        missing = sorted(set(STANDARD_CONTIGS) - set(self.index))
        if missing:
            raise ValueError(f"FAI lacks required standard contigs: {missing}")

    def base(self, contig: str, position: int) -> str:
        length, offset, line_bases, line_width = self.index[contig]
        if position < 1 or position > length:
            return "N"
        zero = position - 1
        self.handle.seek(offset + (zero // line_bases) * line_width + zero % line_bases)
        return self.handle.read(1).decode("ascii").upper()

    def context(self, contig: str, position: int) -> str:
        return "".join(self.base(contig, value) for value in (position - 1, position, position + 1))

    def close(self) -> None:
        self.handle.close()


def reverse_complement(value: str) -> str:
    return "".join(COMPLEMENT.get(base, "N") for base in reversed(value))


def derive_counts(vcf: Path, fasta: Path, fai: Path) -> tuple[dict[str, int], int]:
    reference = IndexedFasta(fasta, fai)
    counts: Counter[str] = Counter()
    allele_count = 0
    try:
        with subprocess.Popen(
            ["bcftools", "view", "-f", "PASS", "-v", "snps", "-H", str(vcf)],
            stdout=subprocess.PIPE,
            text=True,
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 7 or fields[6] != "PASS":
                    raise ValueError("canonical VCF contains a non-PASS or malformed record")
                contig, raw_position, ref, raw_alt = fields[0], fields[1], fields[3].upper(), fields[4].upper()
                if contig not in STANDARD_CONTIGS or len(ref) != 1 or ref not in BASES:
                    raise ValueError(f"non-canonical PASS SNV record: {contig}:{raw_position}")
                position = int(raw_position)
                context = reference.context(contig, position)
                if len(context) != 3 or context[1] != ref:
                    raise ValueError(f"VCF REF differs from FASTA at {contig}:{position}")
                for alt in raw_alt.split(","):
                    if len(alt) != 1 or alt not in BASES or alt == ref:
                        raise ValueError(f"non-canonical PASS SNV ALT at {contig}:{position}: {alt}")
                    if ref in "CT":
                        mutation = f"{ref}>{alt}"
                        normalized = f"{context[0]}[{mutation}]{context[2]}"
                    else:
                        rc = reverse_complement(context)
                        mutation = f"{COMPLEMENT[ref]}>{COMPLEMENT[alt]}"
                        normalized = f"{rc[0]}[{mutation}]{rc[2]}"
                    if normalized not in CANONICAL:
                        raise ValueError(f"unrepresentable SBS96 allele at {contig}:{position}")
                    counts[normalized] += 1
                    allele_count += 1
            if process.wait() != 0:
                raise RuntimeError("bcftools failed while deriving SBS96")
    finally:
        reference.close()
    return {context: counts[context] for context in CANONICAL}, allele_count


def sample_roles(header: str, samples: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for role in ("tumor", "normal"):
        match = re.search(rf"^##{role}_sample=(.+)$", header, re.MULTILINE)
        if not match:
            raise ValueError(f"VCF header lacks ##{role}_sample")
        values[role] = match.group(1).strip()
    if values["tumor"] == values["normal"] or set(values.values()) != set(samples):
        raise ValueError("VCF tumor/normal metadata does not exactly match its two sample columns")
    return values


def materialize(
    *,
    source_vcf: Path,
    source_vcf_index: Path,
    source_matrix: Path,
    fasta: Path,
    fai: Path,
    output_dir: Path,
    run_alias: str = "subject01",
) -> dict[str, Any]:
    if not re.fullmatch(r"subject[0-9]{2,}", run_alias):
        raise ValueError("run alias must be de-identified")
    if source_vcf_index != Path(f"{source_vcf}.tbi"):
        raise ValueError("source VCF index must be adjacent at VCF_PATH.tbi")
    require_real_local_file(source_vcf, "source VCF")
    require_real_local_file(source_vcf_index, "source VCF index")
    require_real_local_file(source_matrix, "source SBS96 matrix")
    require_real_local_file(fasta, "reference FASTA")
    require_real_local_file(fai, "reference FASTA index")
    require_safe_new_output_parent(output_dir, "materializer output directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    capture(["bcftools", "index", "-n", str(source_vcf)])
    source_header = capture(["bcftools", "view", "-h", str(source_vcf)]) + "\n"
    samples = [value for value in capture(["bcftools", "query", "-l", str(source_vcf)]).splitlines() if value]
    if len(samples) != 2:
        raise ValueError("expected exactly two VCF sample columns")
    roles = sample_roles(source_header, samples)

    raw_pass = output_dir / "pass-snvs.with-source-header.vcf.gz"
    require_safe_new_output(raw_pass, "PASS-SNV source-header VCF")
    run(["bcftools", "view", "-f", "PASS", "-v", "snps", "-Oz", "-o", str(raw_pass), str(source_vcf)])
    require_real_local_file(raw_pass, "PASS-SNV source-header VCF")
    raw_header = capture(["bcftools", "view", "-h", str(raw_pass)]) + "\n"
    aliases = {
        roles["tumor"]: f"{run_alias}_tumor",
        roles["normal"]: f"{run_alias}_normal",
    }
    sanitized_header = raw_header
    for original, alias in aliases.items():
        sanitized_header = sanitized_header.replace(original, alias)
    if any(original in sanitized_header for original in aliases):
        raise ValueError("source sample identity remains in the sanitized VCF header")
    header_path = output_dir / "sanitized-header.vcf"
    require_safe_new_output(header_path, "sanitized VCF header")
    header_path.write_text(sanitized_header, encoding="utf-8")
    require_real_local_file(header_path, "sanitized VCF header")
    final_vcf = output_dir / "somatic.pass.vcf.gz"
    require_safe_new_output(final_vcf, "alias-only PASS-SNV VCF")
    run(["bcftools", "reheader", "-h", str(header_path), "-o", str(final_vcf), str(raw_pass)])
    require_real_local_file(final_vcf, "alias-only PASS-SNV VCF")
    final_index = Path(f"{final_vcf}.tbi")
    require_safe_new_output(final_index, "alias-only PASS-SNV VCF index")
    run(["bcftools", "index", "-t", "-f", str(final_vcf)])
    require_real_local_file(final_index, "alias-only PASS-SNV VCF index")
    final_samples = set(capture(["bcftools", "query", "-l", str(final_vcf)]).splitlines())
    if final_samples != {f"{run_alias}_tumor", f"{run_alias}_normal"}:
        raise ValueError(f"unexpected alias-only VCF samples: {sorted(final_samples)}")
    final_header = capture(["bcftools", "view", "-h", str(final_vcf)])
    if any(original in final_header for original in aliases):
        raise ValueError("source sample identity remains in final VCF header")
    indexed_records = int(capture(["bcftools", "index", "-n", str(final_vcf)]))
    if indexed_records <= 0:
        raise ValueError("PASS-SNV VCF contains no records")

    observed = matrix_counts(source_matrix)
    final_matrix = output_dir / "sbs96.csv"
    require_safe_new_output(final_matrix, "alias-only SBS96 matrix")
    write_alias_matrix(observed, final_matrix)
    require_real_local_file(final_matrix, "alias-only SBS96 matrix")
    independently_derived, allele_count = derive_counts(final_vcf, fasta, fai)
    mismatches = sorted(context for context in CANONICAL if observed[context] != independently_derived[context])
    if mismatches:
        raise ValueError(f"SBS96 matrix differs from independent PASS-VCF derivation in {len(mismatches)} contexts")

    artifacts = {
        "somatic.pass.vcf.gz": final_vcf,
        "somatic.pass.vcf.gz.tbi": final_index,
        "sbs96.csv": final_matrix,
    }
    return {
        "status": "passed",
        "run_alias": run_alias,
        "source_sample_names_retained": False,
        "pass_snv_records": indexed_records,
        "pass_snv_alleles": allele_count,
        "sbs96_contexts": 96,
        "sbs96_burden": sum(observed.values()),
        "matrix_matches_independent_pass_vcf_derivation": True,
        "input_sha256": {
            "filtered_vcf": sha256(source_vcf),
            "filtered_vcf_index": sha256(source_vcf_index),
            "source_sbs96_matrix": sha256(source_matrix),
            "reference_fasta": sha256(fasta),
            "reference_fai": sha256(fai),
        },
        "output_sha256": {name: sha256(path) for name, path in artifacts.items()},
        "output_bytes": {name: path.stat().st_size for name, path in artifacts.items()},
    }


def s3_parts(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise ValueError(f"invalid S3 object/prefix URI: {uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def aws_json(arguments: list[str], region: str) -> dict[str, Any]:
    value = json.loads(capture([AWS, *arguments, "--region", region, "--output", "json"]))
    if not isinstance(value, dict):
        raise ValueError("AWS command did not return a JSON object")
    return value


def version_history(bucket: str, prefix: str, region: str) -> list[dict[str, Any]]:
    """Return complete object and delete-marker history for one exact prefix."""
    rows: list[dict[str, Any]] = []
    key_marker = ""
    version_marker = ""
    while True:
        arguments = [
            "s3api", "list-object-versions", "--bucket", bucket, "--prefix", prefix
        ]
        if key_marker:
            arguments.extend(["--key-marker", key_marker])
        if version_marker:
            arguments.extend(["--version-id-marker", version_marker])
        page = aws_json(arguments, region)
        for field, kind in (("Versions", "version"), ("DeleteMarkers", "delete_marker")):
            values = page.get(field, [])
            if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
                raise ValueError("S3 version history is malformed")
            rows.extend({**row, "history_kind": kind} for row in values)
        if page.get("IsTruncated") is not True:
            return rows
        key_marker = str(page.get("NextKeyMarker", ""))
        version_marker = str(page.get("NextVersionIdMarker", ""))
        if not key_marker:
            raise ValueError("truncated S3 history omitted NextKeyMarker")


def require_bucket_versioning(bucket: str, region: str) -> None:
    value = aws_json(["s3api", "get-bucket-versioning", "--bucket", bucket], region)
    if value.get("Status") != "Enabled":
        raise ValueError(f"destination bucket versioning is not Enabled: {bucket}")


def head(uri: str, region: str, version_id: Optional[str] = None) -> dict[str, Any]:
    bucket, key = s3_parts(uri)
    arguments = [
        "s3api", "head-object", "--bucket", bucket, "--key", key, "--checksum-mode", "ENABLED"
    ]
    if version_id:
        arguments.extend(["--version-id", version_id])
    return aws_json(arguments, region)


def require_private_versioned_kms(
    uri: str,
    metadata: dict[str, Any],
    kms_key_arn: str,
    expected_version_id: Optional[str] = None,
) -> None:
    bucket, _ = s3_parts(uri)
    if not bucket.startswith("diana-omics-private-results-"):
        raise ValueError(f"object is outside the private-results bucket: {uri}")
    if metadata.get("ServerSideEncryption") != "aws:kms" or metadata.get("SSEKMSKeyId") != kms_key_arn:
        raise ValueError(f"object lacks the exact KMS key: {uri}")
    observed_version_id = str(metadata.get("VersionId", ""))
    if observed_version_id in {"", "null", "None"}:
        raise ValueError(f"object is not versioned: {uri}")
    if expected_version_id is not None and observed_version_id != expected_version_id:
        raise ValueError(f"object VersionId differs from the frozen input contract: {uri}")
    if int(metadata.get("ContentLength", 0)) <= 0:
        raise ValueError(f"object is empty: {uri}")


def download(uri: str, path: Path, region: str, version_id: str) -> None:
    bucket, key = s3_parts(uri)
    require_safe_new_output(path, "downloaded exact input")
    path.parent.mkdir(parents=True, exist_ok=True)
    run([
        AWS,
        "s3api",
        "get-object",
        "--bucket",
        bucket,
        "--key",
        key,
        "--version-id",
        version_id,
        "--checksum-mode",
        "ENABLED",
        str(path),
        "--region",
        region,
    ])
    require_real_downloaded_file(path, "downloaded exact input")


def upload(path: Path, uri: str, kms_key_arn: str, region: str) -> dict[str, Any]:
    """Publish one small artifact with PutObject create-only semantics."""
    require_real_local_file(path, "upload source")
    local_sha256 = sha256(path)
    bucket, key = s3_parts(uri)
    if version_history(bucket, key, region):
        raise ValueError(f"create-only destination already has history: {uri}")
    response = aws_json([
        "s3api", "put-object", "--bucket", bucket, "--key", key,
        "--body", str(path), "--if-none-match", "*",
        "--server-side-encryption", "aws:kms", "--sse-kms-key-id", kms_key_arn,
        "--checksum-algorithm", "SHA256", "--metadata", f"sha256={local_sha256}",
    ], region)
    version_id = str(response.get("VersionId", ""))
    if not version_id or version_id.lower() in {"none", "null"}:
        raise ValueError(f"create-only put omitted VersionId: {uri}")
    metadata = head(uri, region, version_id)
    require_private_versioned_kms(uri, metadata, kms_key_arn, version_id)
    if int(metadata.get("ContentLength", -1)) != path.stat().st_size:
        raise ValueError(f"uploaded object size mismatch: {uri}")
    if str(metadata.get("Metadata", {}).get("sha256", "")) != local_sha256:
        raise ValueError(f"uploaded object SHA-256 metadata mismatch: {uri}")
    history = version_history(bucket, key, region)
    history_exact = (
        len(history) == 1
        and history[0].get("history_kind") == "version"
        and history[0].get("Key") == key
        and history[0].get("VersionId") == version_id
        and history[0].get("IsLatest") is True
    )
    if not history_exact:
        raise ValueError(f"uploaded object lacks exact single-version history: {uri}")
    return {
        "uri": uri,
        "version_id": str(metadata["VersionId"]),
        "bytes": int(metadata["ContentLength"]),
        "etag": str(metadata.get("ETag", "")),
        "checksums": {
            key: str(value)
            for key, value in metadata.items()
            if key.startswith("Checksum") and str(value)
        },
        "sha256": local_sha256,
        "kms_key_arn": str(metadata.get("SSEKMSKeyId", "")),
        "checks": {
            "create_only_put": True,
            "version_exact": True,
            "bytes_exact": True,
            "metadata_sha256_exact": True,
            "exact_kms": True,
            "single_version_history": True,
        },
    }


def audit_output_history(
    destination_prefix: str,
    outputs: dict[str, dict[str, Any]],
    kms_key_arn: str,
    region: str,
) -> list[dict[str, Any]]:
    bucket, sentinel = s3_parts(destination_prefix.rstrip("/") + "/sentinel")
    prefix = sentinel.removesuffix("sentinel")
    history = version_history(bucket, prefix, region)
    if len(history) != len(outputs) or any(row.get("history_kind") != "version" for row in history):
        raise ValueError("cross-check output prefix history contains extras, duplicates, or delete markers")
    by_key = {str(row.get("Key", "")): row for row in history}
    expected_keys = {s3_parts(row["uri"])[1] for row in outputs.values()}
    if set(by_key) != expected_keys:
        raise ValueError("cross-check output prefix history differs from receipt outputs")
    audited: list[dict[str, Any]] = []
    for filename, output in sorted(outputs.items()):
        _, key = s3_parts(output["uri"])
        history_row = by_key[key]
        if (
            history_row.get("VersionId") != output.get("version_id")
            or history_row.get("IsLatest") is not True
        ):
            raise ValueError(f"cross-check output history VersionId differs: {filename}")
        metadata = head(output["uri"], region, str(output["version_id"]))
        require_private_versioned_kms(
            output["uri"], metadata, kms_key_arn, str(output["version_id"])
        )
        if (
            int(metadata.get("ContentLength", -1)) != int(output.get("bytes", -2))
            or metadata.get("Metadata", {}).get("sha256") != output.get("sha256")
        ):
            raise ValueError(f"cross-check output exact-version audit failed: {filename}")
        audited.append({
            "filename": filename,
            "key": key,
            "version_id": output["version_id"],
            "bytes": output["bytes"],
            "sha256": output["sha256"],
            "checksums": output["checksums"],
        })
    return audited


def staged_validation(result: dict[str, Any]) -> dict[str, Any]:
    """Render the independent VCF/reference/SBS96 gate consumed by reports."""
    return {
        "schema_version": 1,
        "route": "sigprofiler_sbs3",
        "status": "passed",
        "checks": {
            "somatic_vcf_reference": {
                "status": "passed",
                "pass_snv_records": result["pass_snv_records"],
                "pass_snv_alleles": result["pass_snv_alleles"],
                "reference_fasta_sha256": result["input_sha256"]["reference_fasta"],
                "reference_fai_sha256": result["input_sha256"]["reference_fai"],
            },
            "sbs96_equivalence": {
                "status": "passed",
                "matrix_matches_independent_pass_vcf_derivation": result[
                    "matrix_matches_independent_pass_vcf_derivation"
                ],
                "contexts": result["sbs96_contexts"],
                "usable_pass_snv_alleles": result["pass_snv_alleles"],
                "matrix_burden": result["sbs96_burden"],
            },
        },
        "classification_authorization": "none",
        "authorized_hrd_state": "no_call",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-vcf-uri", required=True)
    parser.add_argument("--source-vcf-index-uri", required=True)
    parser.add_argument("--source-matrix-uri", required=True)
    parser.add_argument("--reference-fasta-uri", required=True)
    parser.add_argument("--reference-fai-uri", required=True)
    parser.add_argument("--source-vcf-version-id", required=True)
    parser.add_argument("--source-vcf-index-version-id", required=True)
    parser.add_argument("--source-matrix-version-id", required=True)
    parser.add_argument("--reference-fasta-version-id", required=True)
    parser.add_argument("--reference-fai-version-id", required=True)
    parser.add_argument("--source-vcf-sha256")
    parser.add_argument("--source-vcf-index-sha256")
    parser.add_argument("--source-matrix-sha256")
    parser.add_argument("--reference-fasta-sha256")
    parser.add_argument("--reference-fai-sha256")
    parser.add_argument("--destination-prefix", required=True)
    parser.add_argument(
        "--receipt-prefix",
        required=True,
        help="private provenance prefix; the receipt key is its content SHA-256",
    )
    parser.add_argument("--receipt-anchor-output", required=True, type=Path)
    parser.add_argument("--kms-key-arn", required=True)
    parser.add_argument("--run-alias", default="subject01")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()

    destination_bucket, destination_key = s3_parts(args.destination_prefix.rstrip("/") + "/sentinel")
    receipt_bucket, receipt_sentinel = s3_parts(
        args.receipt_prefix.rstrip("/") + "/sentinel"
    )
    receipt_prefix_key = receipt_sentinel.removesuffix("sentinel")
    if not destination_bucket.startswith("diana-omics-private-results-") or receipt_bucket != destination_bucket:
        raise SystemExit("destination and receipt must use the same private-results bucket")
    destination_prefix = f"s3://{destination_bucket}/{destination_key.removesuffix('/sentinel').rstrip('/')}"
    destination_prefix_key = destination_key.removesuffix("/sentinel").rstrip("/") + "/"
    if receipt_prefix_key.startswith(destination_prefix_key) or destination_prefix_key.startswith(receipt_prefix_key):
        raise SystemExit("receipt provenance prefix must be disjoint from output prefix")
    require_safe_new_output_parent(
        args.receipt_anchor_output, "receipt anchor output"
    )
    if args.receipt_anchor_output.exists():
        raise SystemExit("receipt anchor output already exists; choose a one-shot path")
    require_bucket_versioning(destination_bucket, args.region)
    initial_destination_history = version_history(
        destination_bucket, destination_prefix_key, args.region
    )
    if initial_destination_history:
        raise SystemExit("destination prefix has prior object or delete-marker history")

    temporary = None
    if args.work_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="diana-crosscheck-materialize-")
        work = Path(temporary.name)
    else:
        work = args.work_dir
        require_safe_new_output_parent(work, "work directory")
        work.mkdir(parents=True, exist_ok=True)
    try:
        local = {
            "vcf": work / "source.filtered.vcf.gz",
            "vcf_index": work / "source.filtered.vcf.gz.tbi",
            "matrix": work / "source.sbs96.csv",
            "fasta": work / "reference.fa",
            "fai": work / "reference.fa.fai",
        }
        uris = {
            "vcf": args.source_vcf_uri,
            "vcf_index": args.source_vcf_index_uri,
            "matrix": args.source_matrix_uri,
            "fasta": args.reference_fasta_uri,
            "fai": args.reference_fai_uri,
        }
        version_ids = {
            "vcf": args.source_vcf_version_id,
            "vcf_index": args.source_vcf_index_version_id,
            "matrix": args.source_matrix_version_id,
            "fasta": args.reference_fasta_version_id,
            "fai": args.reference_fai_version_id,
        }
        expected_sha256 = {
            "vcf": args.source_vcf_sha256,
            "vcf_index": args.source_vcf_index_sha256,
            "matrix": args.source_matrix_sha256,
            "fasta": args.reference_fasta_sha256,
            "fai": args.reference_fai_sha256,
        }
        if any(not value or value in {"null", "None"} for value in version_ids.values()):
            raise ValueError("every input must have an exact frozen S3 VersionId")
        for name, expected in expected_sha256.items():
            if expected is not None and not re.fullmatch(r"[0-9a-f]{64}", expected):
                raise ValueError(f"invalid expected SHA-256 for {name}")
        source_custody: dict[str, Any] = {}
        for name, uri in uris.items():
            metadata = head(uri, args.region, version_ids[name])
            require_private_versioned_kms(
                uri,
                metadata,
                args.kms_key_arn,
                version_ids[name],
            )
            download(uri, local[name], args.region, version_ids[name])
            require_real_downloaded_file(
                local[name],
                f"downloaded exact input {name}",
            )
            if local[name].stat().st_size != int(metadata["ContentLength"]):
                raise ValueError(f"downloaded object size mismatch: {name}")
            observed_sha256 = sha256(local[name])
            if expected_sha256[name] is not None and observed_sha256 != expected_sha256[name]:
                raise ValueError(f"downloaded object SHA-256 mismatch: {name}")
            source_custody[name] = {
                "uri": uri,
                "version_id": str(metadata["VersionId"]),
                "bytes": int(metadata["ContentLength"]),
                "etag": str(metadata.get("ETag", "")),
                "checksums": {
                    key: str(value)
                    for key, value in metadata.items()
                    if key.startswith("Checksum") and str(value)
                },
                "sha256": observed_sha256,
                "expected_sha256": expected_sha256[name],
                "kms_key_arn": str(metadata.get("SSEKMSKeyId", "")),
            }
        output_dir = work / "output"
        result = materialize(
            source_vcf=local["vcf"],
            source_vcf_index=local["vcf_index"],
            source_matrix=local["matrix"],
            fasta=local["fasta"],
            fai=local["fai"],
            output_dir=output_dir,
            run_alias=args.run_alias,
        )
        staged_validation_path = output_dir / "staged_input_validation.json"
        write_json_create_only(
            staged_validation_path,
            staged_validation(result),
            "staged input validation output",
        )
        require_real_local_file(
            staged_validation_path,
            "staged input validation output",
        )
        output_custody: dict[str, Any] = {}
        for filename in (
            "somatic.pass.vcf.gz",
            "somatic.pass.vcf.gz.tbi",
            "sbs96.csv",
            "staged_input_validation.json",
        ):
            uri = f"{destination_prefix}/{filename}"
            output_custody[filename] = upload(
                output_dir / filename, uri, args.kms_key_arn, args.region
            )
            if filename in result["output_sha256"] and output_custody[filename]["sha256"] != result["output_sha256"][filename]:
                raise ValueError(f"receipt/output SHA-256 mismatch: {filename}")
        destination_inventory = audit_output_history(
            destination_prefix,
            output_custody,
            args.kms_key_arn,
            args.region,
        )
        receipt = {
            "schema_version": 2,
            "status": "passed",
            "generated_at_utc": now(),
            "run_alias": args.run_alias,
            "script_sha256": sha256(Path(__file__)),
            "destination_prefix": destination_prefix.rstrip("/") + "/",
            "destination_bucket_versioning": "Enabled",
            "destination_initial_version_history_count": len(
                initial_destination_history
            ),
            "receipt_anchor_strategy": "sha256_content_addressed_create_only",
            "source_custody": source_custody,
            "validation": {
                key: value for key, value in result.items()
                if key not in {"input_sha256", "output_sha256", "output_bytes"}
            },
            "input_sha256": result["input_sha256"],
            "outputs": output_custody,
            "destination_inventory": destination_inventory,
            "checks": {
                "all_sources_exact_version_and_sha256": True,
                "alias_only_pass_snv_vcf": True,
                "sbs96_matches_independent_pass_vcf_derivation": True,
                "destination_prefix_initially_empty": True,
                "all_outputs_create_only": True,
                "destination_exact_single_version_history": True,
            },
            "classification_authorization": "none",
            "authorized_hrd_state": "no_call",
        }
        receipt_path = work / "materialization-receipt.json"
        write_json_create_only(
            receipt_path,
            receipt,
            "materialization receipt output",
        )
        require_real_local_file(receipt_path, "materialization receipt output")
        receipt_sha = sha256(receipt_path)
        receipt_uri = (
            f"s3://{receipt_bucket}/{receipt_prefix_key}"
            f"{receipt_sha}.json"
        )
        receipt_upload = upload(
            receipt_path, receipt_uri, args.kms_key_arn, args.region
        )
        anchor = {
            "schema_version": 1,
            "status": "passed",
            "receipt_sha256": receipt_sha,
            "receipt_bytes": receipt_path.stat().st_size,
            "receipt_uri": receipt_uri,
            "receipt_version_id": receipt_upload["version_id"],
            "checks": {
                "version_exact": True,
                "bytes_exact": True,
                "sha256_exact": True,
                "sha256_checksum_exact": bool(
                    receipt_upload.get("checksums", {}).get("ChecksumSHA256")
                ),
                "metadata_sha256_exact": True,
                "exact_kms": True,
                "single_create_only_version": True,
            },
        }
        if not all(anchor["checks"].values()):
            raise ValueError(
                f"materialization receipt anchor checks failed: {anchor['checks']}"
            )
        write_json_create_only(
            args.receipt_anchor_output,
            anchor,
            "receipt anchor output",
        )
        print(json.dumps({"status": "passed", "receipt": receipt_upload, "receipt_anchor": anchor, "outputs": output_custody}, indent=2, sort_keys=True))
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
