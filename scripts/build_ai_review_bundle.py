#!/usr/bin/env python3
"""Build a de-identified, model-safe review bundle from report manifests only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from ai_model_catalog import MODEL_CATALOG_MODEL_KEYS, MODEL_CATALOG_RECEIPT_KEYS
from forbidden_text import (
    forbidden_token_fingerprints,
    merge_forbidden_tokens,
    normalized_scan_text,
)
from hrd_report_inventory import (
    INVENTORY_ID,
    inventory_payload,
    inventory_sha256,
    require_pinned_methods,
)

ALLOWED_EVIDENCE_STATES = {"ready", "partial_evidence", "no_call", "blocked"}
ALLOWED_HRD_STATES = {"no_call", "positive", "negative"}
ALLOWED_CLASSIFICATION_QC = {"passed", "failed", "not_applicable", "blocked", "not_run"}
METHOD_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,79}$")
SUBJECT_ALIAS = re.compile(r"^subject[0-9]{2,4}$")
MODEL_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{1,159}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SOURCE_ARTIFACT_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
RESERVED_JSON_OBJECT_NAMES = {"false", "null", "true"}
NUMBER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?%?"
    r"(?![A-Za-z0-9])"
)
DENIED_KEYS = re.compile(
    r"(?:^|_)(?:patient|person|subject|participant|individual|donor|case|specimen|"
    r"sample|aliquot|library|name|mrn|dob|date_of_birth|email|vendor|accession|"
    r"barcode|external_id|institution|site|source_name|source_uri|result_uri|"
    r"s3_uri|gcs_uri|bucket|object_key|local_path|file_path)(?:$|_)",
    re.IGNORECASE,
)
DENIED_VALUE_PATTERNS = (
    re.compile(r"\b[A-Z][A-Z0-9+.-]*://", re.IGNORECASE),
    re.compile(r"arn:aws:", re.IGNORECASE),
    re.compile(
        r"(?:^|[\s'\"=(:,\[])(?:~[/\\]|/(?!/)(?:[^/\s'\"]+/)+[^/\s'\"]*|[A-Za-z]:[/\\]|\\\\[^\\\s]+\\)",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"\.(?:fastq|fq|bam|cram|sam|vcf|bcf|bai|crai|tbi|csi)(?:\.(?:gz|bgz))?"
        r"(?=$|[\s'\"?#,;:)>\]}])",
        re.IGNORECASE,
    ),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)

BUNDLE_FILENAMES = (
    "review_bundle.json",
    "reviewer-a.prompt.md",
    "reviewer-b.prompt.md",
    "bundle_manifest.json",
)
BUNDLE_FILE_SET = set(BUNDLE_FILENAMES)
BUNDLE_MANIFEST_BOUND_FILES = {
    "review_bundle.json": "review_bundle_sha256",
    "reviewer-a.prompt.md": ("prompt_sha256", "A"),
    "reviewer-b.prompt.md": ("prompt_sha256", "B"),
}
BUNDLE_REVIEW_BUNDLE_BOUND_FIELDS = (
    "schema_version",
    "subject_alias",
    "authorized_hrd_state",
    "required_method_ids",
    "method_inventory",
    "method_inventory_sha256",
    "model_execution_contracts",
    "model_catalog_receipt_sha256",
)
BUNDLE_REVIEW_BUNDLE_KEYS = set(BUNDLE_REVIEW_BUNDLE_BOUND_FIELDS) | {
    "generated_at",
    "purpose",
    "evidence_sources",
    "quantitative_facts",
    "policy",
}
BUNDLE_EVIDENCE_SOURCE_KEYS = {
    "evidence_id",
    "method_id",
    "report_kind",
    "evidence_status",
    "authorized_hrd_state",
    "classification_authorized",
    "classification_qc_status",
    "report_sha256",
    "source_artifact_sha256",
    "review_summary",
}
BUNDLE_MANIFEST_KEYS = set(BUNDLE_REVIEW_BUNDLE_BOUND_FIELDS) | {
    "generated_at",
    "input_manifest_sha256",
    "forbidden_token_sha256",
    "review_bundle_sha256",
    "prompt_sha256",
}
CORE_REPORT_FILES = {"report.md", "report_manifest.json"}
CORE_REPORT_MANIFEST_KEYS = {
    "schema_version",
    "method_id",
    "report_kind",
    "evidence_status",
    "authorized_hrd_state",
    "classification_authorized",
    "classification_qc_status",
    "review_summary",
    "report_sha256",
    "support_sha256",
    "source_sha256",
}
REPORT_KIND_EXTRA_KEYS = {
    "blocked_method": frozenset(
        {
            "alias_scope",
            "blockers",
            "classification_authorization",
            "explicit_no_patient_result",
            "generated_at",
            "intended_computation",
            "interpretation_status",
            "next_gate",
            "patient_result",
            "prerequisites",
            "run_id",
            "source_report_binding_scope",
            "sources",
        }
    ),
    "comparative_synthesis": frozenset(
        {
            "agreement_disagreement_sha256",
            "classification_authorization",
            "generated_at",
            "interpretation_status",
            "subject_alias",
        }
    ),
    "deterministic_baseline": frozenset(),
    "executable_crosscheck_method": frozenset({"route"}),
    "hcc1395_wgs_known_answer": frozenset(),
    "independent_ai_hrd_evidence_review": frozenset(),
    "phase3_fast_deterministic_evidence": frozenset(),
    "public_known_answer_method_no_call": frozenset({"execution_status"}),
    "rosalind_hrd_reviewer_packet": frozenset(),
}


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise ValueError(f"{label} parent is not a directory: {parent}")


def require_real_hash_input(path: Path) -> None:
    label = f"{path.name} SHA-256 input"
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a real file: {path}")


def sha256(path: Path) -> str:
    return read_stable_file_with_sha256(
        path,
        f"{path.name} SHA-256 input",
    )[1]


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_exact_int(value: Any, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


class DuplicateJsonKeyError(ValueError):
    pass


def reject_duplicate_json_object_names(
    pairs: Sequence[tuple[str, Any]],
) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise DuplicateJsonKeyError(key)
        parsed[key] = value
    return parsed


def load_object(path: Path) -> dict[str, Any]:
    value, _ = load_object_with_sha256(path)
    return value


def load_object_with_sha256(path: Path) -> tuple[dict[str, Any], str]:
    path = require_real_input_file(path, f"manifest {path.name}")
    data, digest = read_stable_file_with_sha256(path, f"manifest {path.name}")
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(
            f"duplicate JSON object name in manifest {path.name}: {error}"
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in manifest {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"manifest must be a JSON object: {path.name}")
    return value, digest


def read_stable_file_with_sha256(path: Path, label: str) -> tuple[bytes, str]:
    data = read_real_hash_input_once(path, label)
    digest = sha256_bytes(data)
    if not data or sha256_bytes(read_real_hash_input_once(path, label)) != digest:
        raise ValueError(f"{label} changed during read: {path}")
    return data, digest


def read_real_hash_input_once(path: Path, label: str) -> bytes:
    require_real_hash_input(path)
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{label} must be a real file: {path}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            data = handle.read()
            after_read = os.fstat(handle.fileno())
        current = path.stat(follow_symlinks=False)
    except OSError as error:
        raise ValueError(f"{label} changed during read: {path}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    require_no_symlinked_ancestors(path, label)
    if not os.path.samestat(opened, after_read) or not os.path.samestat(
        after_read,
        current,
    ):
        raise ValueError(f"{label} changed during read: {path}")
    return data


def scan_text(text: str, forbidden_tokens: list[str], context: str) -> None:
    text = normalized_scan_text(text)
    for pattern in DENIED_VALUE_PATTERNS:
        if pattern.search(text):
            raise ValueError(
                f"unsafe raw object, URI, identifier, or local path in {context}"
            )
    lowered = text.lower()
    for token in forbidden_tokens:
        normalized_token = normalized_scan_text(token).lower()
        if normalized_token and normalized_token in lowered:
            raise ValueError(f"forbidden token found in {context}")


def checked_source_artifact_id(value: Any, method: str) -> str:
    if (
        not isinstance(value, str)
        or not SOURCE_ARTIFACT_ID.fullmatch(value)
        or value in RESERVED_JSON_OBJECT_NAMES
    ):
        raise ValueError(f"malformed source-artifact ID for {method}")
    return value


def normalized_key(value: str) -> str:
    camel_split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", normalized_scan_text(value))
    return re.sub(r"[^a-z0-9]+", "_", camel_split.lower()).strip("_")


def sanitize(
    value: Any,
    forbidden_tokens: list[str],
    context: str = "review_summary",
) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite number in {context}")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        scan_text(value, forbidden_tokens, context)
        return value
    if isinstance(value, list):
        if len(value) > 500:
            raise ValueError(f"too many values in {context}")
        return [sanitize(item, forbidden_tokens, f"{context}[]") for item in value]
    if isinstance(value, dict):
        if len(value) > 500:
            raise ValueError(f"too many keys in {context}")
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if DENIED_KEYS.search(normalized_key(key_text)):
                raise ValueError(
                    f"identifier or location key is prohibited in {context}"
                )
            scan_text(key_text, forbidden_tokens, f"{context} key")
            output[key_text] = sanitize(item, forbidden_tokens, f"{context}.{key_text}")
        return output
    raise ValueError(f"unsupported value type in {context}: {type(value).__name__}")


def json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def quantitative_facts(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inventory every scalar number and exposed numeric string token."""
    facts: list[dict[str, Any]] = []

    def visit(value: Any, evidence_id: str, pointer: str) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            facts.append(
                {
                    "quantitative_fact_id": f"Q{len(facts) + 1:04d}",
                    "evidence_id": evidence_id,
                    "summary_path": pointer,
                    "value_kind": "number",
                    "exact_text": json.dumps(
                        value,
                        allow_nan=False,
                        separators=(",", ":"),
                    ),
                }
            )
            return
        if isinstance(value, str):
            for ordinal, match in enumerate(NUMBER_TOKEN.finditer(value), 1):
                facts.append(
                    {
                        "quantitative_fact_id": f"Q{len(facts) + 1:04d}",
                        "evidence_id": evidence_id,
                        "summary_path": pointer,
                        "value_kind": "string_token",
                        "token_ordinal": ordinal,
                        "exact_text": match.group(0),
                    }
                )
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, evidence_id, f"{pointer}/{index}")
            return
        if isinstance(value, dict):
            for key in sorted(value):
                visit(value[key], evidence_id, f"{pointer}/{json_pointer_token(str(key))}")

    for row in evidence:
        visit(row["review_summary"], row["evidence_id"], "review_summary")
    return facts


def parse_catalog_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("model catalog verification timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("model catalog verification timestamp must include timezone")
    now = datetime.now(timezone.utc)
    parsed_utc = parsed.astimezone(timezone.utc)
    if parsed_utc > now:
        raise ValueError("model catalog verification timestamp is in the future")
    if (now - parsed_utc).total_seconds() > 31 * 24 * 60 * 60:
        raise ValueError("model catalog verification is older than 31 days")
    return parsed_utc


def require_exact_catalog_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"model catalog receipt {label} is not exact")
    return value


def validate_catalog_receipt(
    path: Path,
    catalog_verified_at: str,
    model_contracts: dict[str, dict[str, Any]],
) -> str:
    resolved = require_real_input_file(path, "model catalog receipt")
    receipt, receipt_sha256 = load_object_with_sha256(resolved)
    if set(receipt) != MODEL_CATALOG_RECEIPT_KEYS:
        raise ValueError("model catalog receipt envelope is not exact")
    if not is_exact_int(receipt.get("schema_version"), 1):
        raise ValueError("model catalog receipt schema is unsupported")
    receipt_time = parse_catalog_time(
        require_exact_catalog_string(
            receipt.get("catalog_verified_at"),
            "timestamp",
        )
    ).isoformat()
    if receipt_time != catalog_verified_at:
        raise ValueError(
            "model catalog receipt timestamp differs from the attested timestamp"
        )
    if (
        not require_exact_catalog_string(
            receipt.get("provider_catalog"),
            "provider catalog",
        )
        or not require_exact_catalog_string(
            receipt.get("catalog_source"),
            "catalog source",
        )
    ):
        raise ValueError("model catalog receipt lacks provider catalog provenance")
    rows = receipt.get("models")
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError(
            "model catalog receipt must contain exactly the two reviewer models"
        )
    observed: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != MODEL_CATALOG_MODEL_KEYS:
            raise ValueError("model catalog receipt model row envelope is not exact")
        provider = row.get("provider")
        model_id = row.get("model_id")
        if (
            not isinstance(provider, str)
            or not provider
            or provider != provider.strip()
            or not isinstance(model_id, str)
            or not model_id
            or model_id != model_id.strip()
        ):
            raise ValueError("model catalog receipt model identity is not exact")
        pair = (provider, model_id)
        if (
            pair in observed
            or row.get("available") is not True
            or row.get("latest_available") is not True
        ):
            raise ValueError(
                "model catalog receipt contains duplicate, unavailable, or non-latest models"
            )
        observed.add(pair)
    expected = {
        (row["provider"], row["model_id"]) for row in model_contracts.values()
    }
    if observed != expected:
        raise ValueError(
            "model catalog receipt does not match the pinned reviewer models"
        )
    return receipt_sha256


def prompt(
    role: str,
    bundle_hash: str,
    subject_alias: str,
    model: dict[str, Any],
    method_inventory_sha256: str,
) -> str:
    common = f"""# Independent HRD evidence reviewer {role}

Input: `review_bundle.json` with SHA-256 `{bundle_hash}`.
Subject alias: `{subject_alias}`. Use this alias only; do not invent or infer any other subject identifier.
Pinned model: `{model['provider']}/{model['model_id']}`. The operator attested this was the latest available model in its catalog at `{model['catalog_verified_at']}`.

This is a narrative evidence audit, not an HRD algorithm or clinical workflow. Use only evidence IDs present in the bundle. Do not infer facts from filenames, outside knowledge, or absent raw data. Never request or reproduce FASTQ, BAM, CRAM, full VCF, S3/GCS URI, direct identifier, vendor identifier, clinical note, or credential content.

The bundle's `authorized_hrd_state` is an absolute ceiling. Do not write `HRD-positive` or `HRD-negative`, and do not propose `positive` or `negative`, unless that exact state is authorized in the bundle. Preserve each evidence source's exact `ready`, `partial_evidence`, `no_call`, or `blocked` state. A disagreement must be retained.

Numerical results are immutable. Every number used in narrative or claims must copy the `exact_text` of a cited `quantitative_fact_id`. Do not calculate, round, reformat, spell out, average, normalize, combine, or introduce a number. Arithmetic expressions are prohibited. If a derived number would help, describe the need without computing it.

Produce exactly:

1. `report.md`, with these headings in order: `# Independent HRD evidence review`, `## Methods and evidence`, `## Findings`, `## Disagreements`, `## Limitations`, `## Authorized conclusion`. Before the first section, state the exact authorization line `Authorized HRD state: <state>` and exact alias line `Subject alias: <alias>`, using backticks around the values. Cite every substantive paragraph or table with `[C###|E###]`; for multiple evidence sources use semicolons and make the cited evidence list exactly match that claim row.
2. `claims.csv` with the exact header:
   `claim_id,claim,evidence_ids,source_methods,evidence_states,support_level,caveat,disposition,proposed_hrd_state,quantitative_fact_ids,disagreement_status,disagreement_evidence_ids,resolution_needed`
3. `review_manifest.json` with reviewer ID, the exact pinned model contract, invocation ID/interface/start/end timestamps, subject alias, prompt SHA-256, input-bundle SHA-256, the pinned method-inventory SHA-256 `{method_inventory_sha256}`, an exact two-file input-artifact hash inventory, the required independence/isolation attestation, and SHA-256 for `report.md` and `claims.csv`.

The exact input-artifact inventory is `review_bundle.json` plus this reviewer-specific prompt only. Attest that no other reviewer output, external research, or raw input was received.

Allowed support levels: `direct`, `indirect`, `conflicting`, `absent`.
Allowed dispositions: `supported`, `partially_supported`, `unsupported`, `cannot_assess`.
Allowed disagreement statuses: `none`, `method_conflict`, `insufficient_comparability`, `missing_evidence`.

Use semicolons for aligned lists in `evidence_ids`, `source_methods`, and `evidence_states`. Every evidence source in the bundle must be represented by at least one claim. Use `none` for an empty quantitative-fact or disagreement-evidence list. When disagreement status is `none`, use `not_applicable` for `resolution_needed`; otherwise cite the relevant evidence IDs and state the additional observation needed.
"""
    if role == "A":
        task = """
Role: evidence integrator.

- Summarize what each deterministic method measured.
- Identify concordant and discordant evidence without averaging disagreements.
- Separate sample evidence, public validation evidence, and research context.
- State the strongest supported conclusions and every unsupported conclusion.
- Include explicit uncertainty and missing-input gates.
"""
    else:
        task = """
Role: adversarial discrepancy reviewer. Work independently; do not consume reviewer A's report or claims.

- Attempt to falsify apparent conclusions in the bundle.
- Test reference, pairing, purity, subclonality, CN adapter, signature, SV, threshold, and calibration failure modes.
- Flag claims that exceed deterministic evidence.
- State what additional observation would resolve each material discrepancy.
"""
    return common + task


def authorized_state(rows: list[dict[str, Any]]) -> str:
    classified: set[str] = set()
    for row in rows:
        state = row["authorized_hrd_state"]
        if state in {"positive", "negative"}:
            if (
                row.get("classification_authorized") is not True
                or row.get("classification_qc_status") != "passed"
            ):
                raise ValueError(
                    "positive/negative manifest state lacks explicit authorization and passed QC"
                )
            if row.get("evidence_status") != "ready":
                raise ValueError(
                    "positive/negative manifest state requires ready evidence"
                )
            classified.add(state)
        elif (
            row.get("classification_authorized") is not False
            or row.get("classification_qc_status") != "not_applicable"
        ):
            raise ValueError(
                "no_call manifest state must not authorize classification "
                "or mark classification QC as applicable"
            )
    if len(classified) > 1:
        raise ValueError(
            "deterministic manifests contain conflicting authorized HRD classifications"
        )
    return next(iter(classified), "no_call")


def require_allowed_string(value: Any, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"invalid {label}")
    return value


def require_report_kind(value: Any, method: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid report kind for {method}")
    return value


def require_method_id(manifest: dict[str, Any]) -> str:
    method = manifest.get("method_id")
    if not isinstance(method, str) or not METHOD_ID.fullmatch(method):
        raise ValueError("invalid or missing method identifier")
    return method


def require_real_input_file(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{label} is missing, unsafe, or empty: {path}")
    return path.resolve()


def validate_report_manifest_support(
    packet_dir: Path,
    manifest: dict[str, Any],
    method: str,
) -> None:
    report_kind = str(manifest.get("report_kind", ""))
    expected_extra = REPORT_KIND_EXTRA_KEYS.get(report_kind)
    schema_version = manifest.get("schema_version")
    if (
        not is_exact_int(schema_version, 1)
        or manifest.get("method_id") != method
        or expected_extra is None
        or set(manifest) != CORE_REPORT_MANIFEST_KEYS | set(expected_extra)
    ):
        raise ValueError(f"report manifest envelope is not exact for {method}")
    if not isinstance(manifest.get("classification_authorized"), bool):
        raise ValueError(
            f"report manifest classification authorization is not exact for {method}"
        )

    support_hashes = manifest.get("support_sha256")
    if not isinstance(support_hashes, dict) or not support_hashes:
        raise ValueError(f"missing support hashes for {method}")

    bound_support_files: set[str] = set()
    for relative, digest in support_hashes.items():
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).name != relative
            or relative in CORE_REPORT_FILES
        ):
            raise ValueError(f"malformed support path for {method}: {relative}")

        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise ValueError(f"malformed support SHA-256 for {method}: {relative}")

        try:
            support_path = require_real_input_file(
                packet_dir / relative,
                f"{method} support file",
            )
        except ValueError as error:
            raise ValueError(
                f"support hash mismatch for {method}: {relative}: {error}"
            ) from error
        if sha256(support_path) != digest:
            raise ValueError(f"support hash mismatch for {method}: {relative}")
        bound_support_files.add(relative)

    expected_inventory = CORE_REPORT_FILES | bound_support_files
    observed_inventory = {path.name for path in packet_dir.iterdir()}
    if observed_inventory != expected_inventory:
        raise ValueError(f"support inventory is not exact for {method}")


def require_safe_new_bundle_file(path: Path) -> Path:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(
                f"AI review bundle output parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise ValueError(
                f"AI review bundle output parent is not a directory: {parent}"
            )
    if path.is_symlink():
        raise ValueError(
            "AI review bundle output may not be a symlink: " + path.name
        )
    if path.exists():
        raise ValueError(
            "AI review bundle output already exists: " + path.name
        )
    return path.resolve()


def require_safe_new_staged_file(path: Path) -> Path:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(
                f"staged AI review bundle file parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise ValueError(
                f"staged AI review bundle file parent is not a directory: {parent}"
            )
    if path.is_symlink():
        raise ValueError(
            "staged AI review bundle file may not be a symlink: " + path.name
        )
    if path.exists():
        raise ValueError(
            "staged AI review bundle file already exists: " + path.name
        )
    return path.resolve()


def require_staged_bytes(path: Path, expected_sha256: str) -> None:
    path = require_real_input_file(path, "staged AI review bundle file")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError(f"staged AI review bundle file mode is not 0600: {path}")
    if sha256(path) != expected_sha256:
        raise ValueError(
            "staged AI review bundle file changed during write: " + path.name
        )


def write_staged_bytes(path: Path, payload: bytes) -> None:
    expected_sha256 = sha256_bytes(payload)
    path = require_safe_new_staged_file(path)
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        require_staged_bytes(path, expected_sha256)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def require_bundle_manifest(bundle_dir: Path) -> None:
    observed = {path.name for path in bundle_dir.iterdir()}
    if observed != BUNDLE_FILE_SET:
        missing = sorted(BUNDLE_FILE_SET - observed)
        unexpected = sorted(observed - BUNDLE_FILE_SET)
        details = []
        if missing:
            details.append("missing " + ",".join(missing))
        if unexpected:
            details.append("unexpected " + ",".join(unexpected))
        raise ValueError(
            "AI review bundle inventory is not exact: " + "; ".join(details)
        )

    bundle = load_object(
        require_real_input_file(
            bundle_dir / "review_bundle.json",
            "AI review bundle file",
        )
    )
    manifest = load_object(
        require_real_input_file(
            bundle_dir / "bundle_manifest.json",
            "AI review bundle manifest",
        )
    )
    if set(bundle) != BUNDLE_REVIEW_BUNDLE_KEYS or not is_exact_int(
        bundle.get("schema_version"),
        2,
    ):
        raise ValueError("AI review bundle envelope is not exact")
    if set(manifest) != BUNDLE_MANIFEST_KEYS or not is_exact_int(
        manifest.get("schema_version"),
        2,
    ):
        raise ValueError("AI review bundle manifest envelope is not exact")
    for field in BUNDLE_REVIEW_BUNDLE_BOUND_FIELDS:
        if manifest.get(field) != bundle.get(field):
            raise ValueError(
                "AI review bundle manifest differs from review_bundle.json for "
                + field
            )

    prompt_sha256 = manifest.get("prompt_sha256")
    if not isinstance(prompt_sha256, dict) or set(prompt_sha256) != {"A", "B"}:
        raise ValueError("AI review bundle manifest lacks prompt hashes")

    for filename, field in BUNDLE_MANIFEST_BOUND_FILES.items():
        expected_sha256 = (
            prompt_sha256.get(field[1])
            if isinstance(field, tuple)
            else manifest.get(field)
        )
        if not isinstance(expected_sha256, str) or not HEX64.fullmatch(
            expected_sha256
        ):
            raise ValueError(
                "AI review bundle manifest has malformed SHA-256 for " + filename
            )
        observed_sha256 = sha256(
            require_real_input_file(
                bundle_dir / filename,
                "AI review bundle file",
            )
        )
        if observed_sha256 != expected_sha256:
            raise ValueError(
                "AI review bundle manifest is stale for " + filename
            )


def require_staged_bundle_manifest(staging: Path) -> None:
    require_bundle_manifest(staging)


def prepare_output_dir(output: Path, expected_files: Iterable[str]) -> None:
    expected = set(expected_files)
    if output.is_symlink():
        raise ValueError("AI review bundle output may not be a symlink")
    for parent in output.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(
                f"AI review bundle output parent may not be a symlink: {parent}"
            )
        if parent.exists() and not parent.is_dir():
            raise ValueError(
                f"AI review bundle output parent is not a directory: {parent}"
            )
    if output.exists() and not output.is_dir():
        raise ValueError(f"AI review bundle output is not a directory: {output}")

    output.mkdir(parents=True, exist_ok=True)

    unexpected: list[str] = []
    invalid: list[str] = []
    for path in output.iterdir():
        if path.name not in expected:
            unexpected.append(path.name)
        elif path.is_symlink() or not path.is_file():
            invalid.append(path.name)
    if unexpected:
        raise ValueError(
            "AI review bundle output contains unexpected existing files: "
            + ", ".join(sorted(unexpected))
        )
    if invalid:
        raise ValueError(
            "AI review bundle output contains invalid existing bundle paths: "
            + ", ".join(sorted(invalid))
        )

    existing = sorted(path.name for path in output.iterdir() if path.name in expected)
    if existing:
        raise ValueError(
            "AI review bundle output already contains bundle files: "
            + ", ".join(existing)
        )


def copy_create_only(source: Path, destination: Path) -> None:
    source = require_real_input_file(source, "staged AI review bundle file")
    payload, expected_sha256 = read_stable_file_with_sha256(
        source,
        "staged AI review bundle file",
    )
    destination = require_safe_new_bundle_file(destination)
    try:
        file_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o644,
        )
    except FileExistsError as error:
        raise ValueError(
            "AI review bundle output already exists: " + destination.name
        ) from error

    try:
        destination_handle = os.fdopen(file_descriptor, "wb")
    except Exception:
        os.close(file_descriptor)
        destination.unlink(missing_ok=True)
        raise

    try:
        with destination_handle:
            destination_handle.write(payload)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        fsync_directory(destination.parent)
        if sha256(destination) != expected_sha256:
            raise ValueError(
                "staged AI review bundle file changed during copy: " + source.name
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def install_bundle_create_only(staged_paths: Sequence[Path], output: Path) -> None:
    installed: list[Path] = []
    expected_hashes: dict[Path, str] = {}
    try:
        for path in staged_paths:
            destination = output / path.name
            expected_hashes[destination] = sha256(
                require_real_input_file(path, "staged AI review bundle file")
            )
            destination_preexisted = destination.exists() or destination.is_symlink()
            try:
                copy_create_only(path, destination)
            except Exception:
                if not destination_preexisted:
                    installed.append(destination)
                raise
            installed.append(destination)
        fsync_directory(output)
        for destination, expected_sha256 in expected_hashes.items():
            if sha256(
                require_real_input_file(
                    destination,
                    "AI review bundle output",
                )
            ) != expected_sha256:
                raise ValueError(
                    "AI review bundle output changed during install: "
                    + destination.name
                )
        require_bundle_manifest(output)
    except Exception:
        for path in reversed(installed):
            path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", action="append", required=True, type=Path)
    parser.add_argument(
        "--require-method",
        action="append",
        required=True,
        help="Expected method ID, repeated in the exact manifest order.",
    )
    parser.add_argument(
        "--inventory-id",
        default=INVENTORY_ID,
        help="Pinned HRD report inventory ID. Defaults to the Diana WGS inventory.",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--forbidden-token", action="append", default=[])
    parser.add_argument("--subject-alias", default="subject01")
    parser.add_argument("--reviewer-a-provider", required=True)
    parser.add_argument("--reviewer-a-model-id", required=True)
    parser.add_argument("--reviewer-b-provider", required=True)
    parser.add_argument("--reviewer-b-model-id", required=True)
    parser.add_argument("--model-catalog-verified-at", required=True)
    parser.add_argument("--model-catalog-receipt", required=True, type=Path)
    parser.add_argument("--attest-models-latest", action="store_true")
    args = parser.parse_args()

    try:
        output = args.output_dir
        prepare_output_dir(output, BUNDLE_FILENAMES)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    output = output.resolve()

    try:
        forbidden = list(merge_forbidden_tokens(args.forbidden_token))
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    if not forbidden:
        raise SystemExit("Fail-closed: at least one --forbidden-token is required")
    if not SUBJECT_ALIAS.fullmatch(args.subject_alias):
        raise SystemExit("Fail-closed: subject alias must match subjectNN")
    if not args.attest_models_latest:
        raise SystemExit("Fail-closed: --attest-models-latest is required")

    required_methods = args.require_method
    if (
        not required_methods
        or any(not METHOD_ID.fullmatch(value) for value in required_methods)
        or len(set(required_methods)) != len(required_methods)
    ):
        raise SystemExit(
            "Fail-closed: required method inventory is empty, invalid, or duplicated"
        )
    try:
        require_pinned_methods(
            required_methods,
            "required method arguments",
            args.inventory_id,
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    method_inventory = inventory_payload(args.inventory_id)
    method_inventory_sha256 = inventory_sha256(args.inventory_id)

    try:
        catalog_verified = parse_catalog_time(
            args.model_catalog_verified_at
        ).isoformat()
        model_contracts = {
            "A": {
                "provider": args.reviewer_a_provider,
                "model_id": args.reviewer_a_model_id,
                "catalog_verified_at": catalog_verified,
                "latest_available_attested": True,
            },
            "B": {
                "provider": args.reviewer_b_provider,
                "model_id": args.reviewer_b_model_id,
                "catalog_verified_at": catalog_verified,
                "latest_available_attested": True,
            },
        }
        for role, model in model_contracts.items():
            if not MODEL_VALUE.fullmatch(model["provider"]) or not MODEL_VALUE.fullmatch(
                model["model_id"]
            ):
                raise ValueError(f"invalid pinned model identifier for reviewer {role}")
        if (model_contracts["A"]["provider"], model_contracts["A"]["model_id"]) == (
            model_contracts["B"]["provider"],
            model_contracts["B"]["model_id"],
        ):
            raise ValueError("reviewers A and B must use distinct pinned models")
        catalog_receipt_hash = validate_catalog_receipt(
            args.model_catalog_receipt,
            catalog_verified,
            model_contracts,
        )
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    evidence: list[dict[str, Any]] = []
    input_hashes: dict[str, str] = {}
    observed_methods: list[str] = []
    for index, manifest_path in enumerate(args.manifest, 1):
        try:
            path = require_real_input_file(manifest_path, "report manifest")
        except ValueError as error:
            raise SystemExit(
                f"Fail-closed: missing or unsafe report manifest {manifest_path}: "
                f"{error}"
            ) from error
        try:
            manifest, manifest_hash = load_object_with_sha256(path)
        except ValueError as error:
            raise SystemExit(f"Fail-closed: {error}") from error
        if not is_exact_int(manifest.get("schema_version"), 1):
            raise SystemExit(
                f"Fail-closed: unsupported report-manifest schema in {path.name}"
            )

        try:
            method = require_method_id(manifest)
        except ValueError as error:
            raise SystemExit(
                f"Fail-closed: invalid or missing method identifier in {path.name}"
            ) from error
        if method in observed_methods:
            raise SystemExit(f"Fail-closed: duplicate method manifest for {method}")
        observed_methods.append(method)

        try:
            evidence_status = require_allowed_string(
                manifest.get("evidence_status"),
                ALLOWED_EVIDENCE_STATES,
                f"evidence status for {method}",
            )
            hrd_state = require_allowed_string(
                manifest.get("authorized_hrd_state"),
                ALLOWED_HRD_STATES,
                f"authorized HRD state for {method}",
            )
            classification_qc = require_allowed_string(
                manifest.get("classification_qc_status"),
                ALLOWED_CLASSIFICATION_QC,
                f"classification QC state for {method}",
            )
        except ValueError as error:
            raise SystemExit(f"Fail-closed: {error}") from error
        report_hash = manifest.get("report_sha256")
        if not isinstance(report_hash, str) or not HEX64.fullmatch(report_hash):
            raise SystemExit(f"Fail-closed: missing report SHA-256 for {method}")

        report_path = path.parent / "report.md"
        try:
            report_path = require_real_input_file(report_path, "source report")
        except ValueError as error:
            raise SystemExit(
                f"Fail-closed: report hash mismatch for {method}: {error}"
            ) from error
        if sha256(report_path) != report_hash:
            raise SystemExit(f"Fail-closed: report hash mismatch for {method}")

        try:
            raw_summary = manifest.get("review_summary")
            if not isinstance(raw_summary, dict) or not raw_summary:
                raise ValueError(f"missing non-empty review_summary for {method}")
            summary = sanitize(raw_summary, forbidden)
            scan_text(method, forbidden, "method identifier")
            report_kind = require_report_kind(
                manifest.get("report_kind"),
                method,
            )
            scan_text(report_kind, forbidden, "report kind")
        except ValueError as error:
            raise SystemExit(f"Fail-closed: {error}") from error

        source_hashes = manifest.get("source_sha256", {})
        if not isinstance(source_hashes, dict) or not source_hashes:
            raise SystemExit(f"Fail-closed: malformed source hashes for {method}")
        try:
            normalized_source_hashes = []
            for key, digest in source_hashes.items():
                checked_source_artifact_id(key, method)
                if not isinstance(digest, str) or not HEX64.fullmatch(digest):
                    raise ValueError(f"malformed source hashes for {method}")
                normalized_source_hashes.append(digest)
        except ValueError as error:
            raise SystemExit(f"Fail-closed: {error}") from error
        normalized_source_hashes.sort()
        try:
            validate_report_manifest_support(path.parent, manifest, method)
        except ValueError as error:
            raise SystemExit(f"Fail-closed: {error}") from error

        evidence.append(
            {
                "evidence_id": f"E{index:03d}",
                "method_id": method,
                "report_kind": report_kind,
                "evidence_status": evidence_status,
                "authorized_hrd_state": hrd_state,
                "classification_authorized": manifest.get(
                    "classification_authorized"
                )
                is True,
                "classification_qc_status": classification_qc,
                "report_sha256": report_hash,
                "source_artifact_sha256": normalized_source_hashes,
                "review_summary": summary,
            }
        )
        input_hashes[f"E{index:03d}"] = manifest_hash

    if observed_methods != required_methods:
        raise SystemExit(
            "Fail-closed: observed method manifests do not exactly match the "
            "ordered required method inventory; "
            f"required={required_methods!r} observed={observed_methods!r}"
        )

    try:
        ceiling = authorized_state(evidence)
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    facts = quantitative_facts(evidence)
    bundle = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "deidentified_independent_narrative_crosscheck",
        "subject_alias": args.subject_alias,
        "authorized_hrd_state": ceiling,
        "required_method_ids": required_methods,
        "method_inventory": method_inventory,
        "method_inventory_sha256": method_inventory_sha256,
        "evidence_sources": evidence,
        "quantitative_facts": facts,
        "model_execution_contracts": model_contracts,
        "model_catalog_receipt_sha256": catalog_receipt_hash,
        "policy": {
            "raw_inputs_prohibited": True,
            "external_research_prohibited": True,
            "reviewers_independent": True,
            "other_reviewer_outputs_prohibited": True,
            "numerical_results_immutable": True,
            "classification_may_not_exceed_authorized_state": True,
        },
    }
    if len(json_bytes(bundle)) > 2 * 1024 * 1024:
        raise SystemExit("Fail-closed: review bundle exceeds 2 MiB")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="ai-review-bundle-",
        dir=output.parent,
    ) as temporary:
        staging = Path(temporary)
        bundle_path = staging / "review_bundle.json"
        write_staged_bytes(bundle_path, json_bytes(bundle))
        bundle_hash = sha256(bundle_path)

        prompt_paths = {}
        for role in ("A", "B"):
            path = staging / f"reviewer-{role.lower()}.prompt.md"
            write_staged_bytes(
                path,
                prompt(
                    role,
                    bundle_hash,
                    args.subject_alias,
                    model_contracts[role],
                    method_inventory_sha256,
                ).encode("utf-8"),
            )
            prompt_paths[role] = path

        manifest = {
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "subject_alias": args.subject_alias,
            "authorized_hrd_state": ceiling,
            "required_method_ids": required_methods,
            "method_inventory": method_inventory,
            "method_inventory_sha256": method_inventory_sha256,
            "input_manifest_sha256": input_hashes,
            "forbidden_token_sha256": forbidden_token_fingerprints(forbidden),
            "review_bundle_sha256": bundle_hash,
            "prompt_sha256": {
                role: sha256(path) for role, path in prompt_paths.items()
            },
            "model_execution_contracts": model_contracts,
            "model_catalog_receipt_sha256": catalog_receipt_hash,
        }
        manifest_path = staging / "bundle_manifest.json"
        write_staged_bytes(manifest_path, json_bytes(manifest))
        require_staged_bundle_manifest(staging)

        try:
            install_bundle_create_only(
                (bundle_path, *prompt_paths.values(), manifest_path),
                output,
            )
        except ValueError as error:
            raise SystemExit(f"Fail-closed: {error}") from error

    print(f"Wrote de-identified AI review bundle: {output}")
    print(f"Authorized HRD state: {ceiling}; no model invoked")


if __name__ == "__main__":
    main()
