#!/usr/bin/env python3
"""Validate one independently generated AI HRD review without invoking a model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from ai_model_catalog import MODEL_CATALOG_MODEL_KEYS, MODEL_CATALOG_RECEIPT_KEYS
from build_ai_review_bundle import (
    BUNDLE_MANIFEST_KEYS,
    BUNDLE_REVIEW_BUNDLE_KEYS,
    DuplicateJsonKeyError,
    checked_source_artifact_id,
    is_exact_int,
    reject_duplicate_json_object_names,
    require_bundle_manifest,
    validate_report_manifest_support,
)
from forbidden_text import (
    forbidden_token_fingerprints,
    has_unauthorized_hrd_classification,
    merge_forbidden_tokens,
    normalized_scan_text,
)
from hrd_report_inventory import (
    inventory_payload,
    inventory_sha256,
    require_inventory_binding,
    require_pinned_methods,
)

CLAIMS_FIELDS = [
    "claim_id",
    "claim",
    "evidence_ids",
    "source_methods",
    "evidence_states",
    "support_level",
    "caveat",
    "disposition",
    "proposed_hrd_state",
    "quantitative_fact_ids",
    "disagreement_status",
    "disagreement_evidence_ids",
    "resolution_needed",
]
SUPPORT_LEVELS = {"direct", "indirect", "conflicting", "absent"}
DISPOSITIONS = {"supported", "partially_supported", "unsupported", "cannot_assess"}
DISAGREEMENT_STATUSES = {
    "none",
    "method_conflict",
    "insufficient_comparability",
    "missing_evidence",
}
HRD_STATES = {"no_call", "positive", "negative"}
EVIDENCE_STATES = {"ready", "partial_evidence", "no_call", "blocked"}
CLASSIFICATION_QC_STATES = {"passed", "failed", "not_applicable", "blocked", "not_run"}
REQUIRED_POLICY = {
    "raw_inputs_prohibited": True,
    "external_research_prohibited": True,
    "reviewers_independent": True,
    "other_reviewer_outputs_prohibited": True,
    "numerical_results_immutable": True,
    "classification_may_not_exceed_authorized_state": True,
}
REQUIRED_ATTESTATION = {
    "other_reviewer_outputs_received": False,
    "other_reviewer_context_received": False,
    "external_research_used": False,
    "raw_inputs_received": False,
    "isolated_session": True,
    "input_directory_contained_only_declared_artifacts": True,
}
REQUIRED_REPORT_HEADINGS = (
    "# Independent HRD evidence review",
    "## Methods and evidence",
    "## Findings",
    "## Disagreements",
    "## Limitations",
    "## Authorized conclusion",
)
REVIEW_OUTPUT_FILES = {"claims.csv", "report.md", "review_manifest.json"}
VALIDATED_REVIEW_OUTPUT_FILES = REVIEW_OUTPUT_FILES | {"validation.json"}
REVIEW_MANIFEST_KEYS = {
    "schema_version",
    "reviewer_id",
    "subject_alias",
    "model",
    "invocation",
    "prompt_sha256",
    "input_bundle_sha256",
    "method_inventory_sha256",
    "input_artifact_sha256",
    "independence_attestation",
    "output_sha256",
}
REVIEW_INVOCATION_KEYS = {
    "invocation_id",
    "interface",
    "started_at",
    "completed_at",
}
VALIDATION_KEYS = {
    "schema_version",
    "status",
    "reviewer_id",
    "subject_alias",
    "model",
    "authorized_hrd_state",
    "required_method_ids",
    "method_inventory",
    "method_inventory_sha256",
    "model_catalog_receipt_sha256",
    "claim_count",
    "covered_evidence_ids",
    "disagreement_claim_count",
    "bundle_manifest_sha256",
    "review_bundle_sha256",
    "prompt_sha256",
    "report_sha256",
    "claims_sha256",
    "review_manifest_sha256",
    "forbidden_token_count",
}

CLAIM_ID = re.compile(r"^C[0-9]{3,}$")
CITATION = re.compile(r"(?<!!)\[(C[0-9]{3,})\|((?:E[0-9]{3,})(?:;E[0-9]{3,})*)\](?!\()")
EVIDENCE_ID = re.compile(r"^E[0-9]{3,}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
METHOD_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,79}$")
QUANTITATIVE_FACT_ID = re.compile(r"^Q[0-9]{4,}$")
SUBJECT_ALIAS = re.compile(r"^subject[0-9]{2,4}$")
NUMBER_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
    r"(?:[eE][-+]?[0-9]+)?%?(?![A-Za-z0-9])"
)
NUMBER_WORD = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|"
    r"thousand|million|billion|trillion|first|second|third|fourth|fifth|"
    r"sixth|seventh|eighth|ninth|tenth|half|quarter)\b",
    re.IGNORECASE,
)
DERIVED_NUMERIC_EXPRESSION = re.compile(
    r"(?<![A-Za-z0-9])[-+]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
    r"(?:[eE][-+]?[0-9]+)?%?\s*"
    r"(?:/|\\|\*|×|÷|\+|-|–|—|=|<|>|\bof\b|\bto\b|\bthrough\b)\s*"
    r"[-+]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?%?",
    re.IGNORECASE,
)
PROHIBITED_INPUT = re.compile(
    r"\b[A-Z][A-Z0-9+.-]*://|arn:aws:|"
    r"(?:^|[\s'\"=(:,\[])(?:~[/\\]|/(?!/)(?:[^/\s'\"]+/)+[^/\s'\"]*|"
    r"[A-Za-z]:[/\\]|\\\\[^\\\s]+\\)|"
    r"\.(?:fastq|fq|bam|cram|sam|vcf|bcf|bai|crai|tbi|csi)"
    r"(?:\.(?:gz|bgz))?(?=$|[\s'\"?#,;:)>\]}])|"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE | re.MULTILINE,
)


def is_platform_root_alias(path: Path) -> bool:
    return path.is_absolute() and path.parent == path.parent.parent


def require_no_symlinked_ancestors(path: Path, label: str) -> None:
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"{label} parent may not be a symlink: {parent}")


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


def load_object(path: Path) -> dict[str, Any]:
    value, _ = load_object_with_sha256(path)
    return value


def load_object_with_sha256(path: Path) -> tuple[dict[str, Any], str]:
    path = resolve_real_file(path, path.name)
    data, digest = read_stable_file_with_sha256(path, path.name)
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_json_object_names,
        )
    except DuplicateJsonKeyError as error:
        raise ValueError(
            f"duplicate JSON object name in {path.name}: {error}"
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON in {path.name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.name}")
    return value, digest


def read_stable_file_with_sha256(path: Path, label: str) -> tuple[bytes, str]:
    require_real_hash_input(path)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not data or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f"{label} changed during read: {path}")
    return data, digest


def read_stable_text(path: Path, label: str) -> str:
    data, _ = read_stable_file_with_sha256(path, label)
    try:
        return data.decode("utf-8")
    except UnicodeError as error:
        raise ValueError(f"invalid UTF-8 in {label}") from error


def resolve_real_dir(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} is missing or a symlink")
    return path.resolve()


def resolve_real_file(path: Path, label: str) -> Path:
    require_no_symlinked_ancestors(path, label)
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{label} is missing or a symlink")
    return path.resolve()


def parse_time(value: Any, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {label} timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{label} timestamp must include timezone")
    return parsed


def exact_invocation_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def require_exact_review_invocation(invocation: Any) -> dict[str, str]:
    if not isinstance(invocation, dict) or set(invocation) != REVIEW_INVOCATION_KEYS:
        raise ValueError("review invocation envelope is not exact")
    if not all(
        exact_invocation_string(invocation.get(key))
        for key in REVIEW_INVOCATION_KEYS
    ):
        raise ValueError("complete invocation metadata is required")
    return dict(invocation)


def exact_nonempty_string(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        return ""
    return value


def require_exact_claim_row(
    row: dict[str, Any],
    row_number: int,
) -> dict[str, str]:
    if None in row or any(
        not isinstance(row.get(field), str) for field in CLAIMS_FIELDS
    ):
        raise ValueError(f"claims.csv row does not match schema at row {row_number}")
    for field in CLAIMS_FIELDS:
        value = row[field]
        if (
            value != value.strip()
            or "\n" in value
            or "\r" in value
            or "\0" in value
        ):
            raise ValueError(
                f"claims.csv field is not exact at row {row_number}: {field}"
            )
    return {field: row[field] for field in CLAIMS_FIELDS}


def split_semicolon(value: str, label: str, row_number: int) -> tuple[str, ...]:
    if not value or value != value.strip():
        raise ValueError(f"{label} is not exact at row {row_number}")
    parts = tuple(value.split(";"))
    if any(not item or item != item.strip() for item in parts):
        raise ValueError(f"{label} is not exact at row {row_number}")
    return parts


def validate_catalog_receipt(path: Path, model_contracts: dict[str, Any]) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError("model catalog receipt is missing or empty")
    receipt, receipt_sha256 = load_object_with_sha256(path)
    if set(receipt) != MODEL_CATALOG_RECEIPT_KEYS:
        raise ValueError("model catalog receipt envelope is not exact")
    if not is_exact_int(receipt.get("schema_version"), 1):
        raise ValueError("model catalog receipt schema is unsupported")
    if not exact_nonempty_string(
        receipt.get("provider_catalog")
    ) or not exact_nonempty_string(receipt.get("catalog_source")):
        raise ValueError("model catalog receipt lacks provider catalog provenance")

    receipt_time = parse_time(
        receipt.get("catalog_verified_at"),
        "catalog receipt",
    ).isoformat()
    contract_times = {parse_time(row.get("catalog_verified_at"), "catalog contract").isoformat() for row in model_contracts.values()}
    if contract_times != {receipt_time}:
        raise ValueError("model catalog receipt timestamp differs from the pinned contracts")

    rows = receipt.get("models")
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValueError("model catalog receipt must contain exactly the two reviewer models")
    observed: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != MODEL_CATALOG_MODEL_KEYS:
            raise ValueError("model catalog receipt model row envelope is not exact")
        provider = exact_nonempty_string(row.get("provider"))
        model_id = exact_nonempty_string(row.get("model_id"))
        if not provider or not model_id:
            raise ValueError("model catalog receipt model identity is not exact")
        pair = (provider, model_id)
        if pair in observed or row.get("available") is not True or row.get("latest_available") is not True:
            raise ValueError("model catalog receipt contains duplicate, unavailable, or non-latest models")
        observed.add(pair)

    expected = {(row["provider"], row["model_id"]) for row in model_contracts.values()}
    if observed != expected:
        raise ValueError("model catalog receipt does not match the pinned reviewer models")
    return receipt_sha256


def json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def derived_quantitative_facts(
    evidence_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []

    def visit(value: Any, evidence_id: str, pointer: str) -> None:
        if value is None or isinstance(value, bool):
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

    for row in evidence_rows:
        visit(row["review_summary"], str(row["evidence_id"]), "review_summary")
    return facts


def derived_authorized_state(rows: list[dict[str, Any]]) -> str:
    classified: set[str] = set()
    for row in rows:
        state = row.get("authorized_hrd_state")
        if state in {"positive", "negative"}:
            if row.get("classification_authorized") is not True:
                raise ValueError("classified evidence lacks explicit authorization")
            if row.get("classification_qc_status") != "passed":
                raise ValueError("classified evidence lacks passed classification QC")
            if row.get("evidence_status") != "ready":
                raise ValueError("classified evidence is not ready")
            classified.add(str(state))
        elif row.get("classification_authorized") is not False or row.get("classification_qc_status") != "not_applicable":
            raise ValueError("no_call evidence cannot authorize classification or mark classification QC as applicable")
    if len(classified) > 1:
        raise ValueError("evidence sources contain conflicting authorized classifications")
    return next(iter(classified), "no_call")


def checked_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError("malformed SHA-256 for " + label)
    return value


def validate_source_manifests(
    paths: list[Path],
    evidence_rows: list[dict[str, Any]],
    input_hashes: dict[str, Any],
) -> None:
    if len(paths) != len(evidence_rows):
        raise ValueError("source-manifest count does not match evidence sources")

    for index, (source_path, evidence) in enumerate(zip(paths, evidence_rows), 1):
        evidence_id = f"E{index:03d}"
        path = resolve_real_file(
            source_path,
            f"source manifest for {evidence_id}",
        )
        source, source_sha256 = load_object_with_sha256(path)
        if source_sha256 != input_hashes.get(evidence_id):
            raise ValueError(f"source-manifest hash mismatch for {evidence_id}")
        if not is_exact_int(source.get("schema_version"), 1):
            raise ValueError(f"unsupported source-manifest schema for {evidence_id}")

        report_hash = checked_sha256(
            source.get("report_sha256"),
            f"source report {evidence_id}",
        )
        report_path = path.parent / "report.md"
        source_hashes = source.get("source_sha256")
        if report_path.is_symlink() or not report_path.is_file() or not HEX64.fullmatch(report_hash) or sha256(report_path) != report_hash:
            raise ValueError(f"source report hash mismatch for {evidence_id}")
        if not isinstance(source_hashes, dict) or not source_hashes:
            raise ValueError(f"source artifact hashes are missing for {evidence_id}")
        method = str(source.get("method_id") or source.get("route") or "")
        try:
            source_artifact_sha256 = sorted(
                checked_sha256(
                    value,
                    (
                        f"source artifact {evidence_id} "
                        + checked_source_artifact_id(key, method or evidence_id)
                    ),
                )
                for key, value in source_hashes.items()
            )
        except ValueError as error:
            raise ValueError(f"source artifact hash mismatch for {evidence_id}: {error}") from error
        try:
            validate_report_manifest_support(
                path.parent,
                source,
                method or evidence_id,
            )
        except ValueError as error:
            raise ValueError(f"source support mismatch for {evidence_id}: {error}") from error

        expected_evidence = {
            "method_id": method,
            "report_kind": str(source.get("report_kind", "method")),
            "evidence_status": str(source.get("evidence_status", "")),
            "authorized_hrd_state": str(source.get("authorized_hrd_state") or source.get("interpretation_status") or ""),
            "classification_authorized": source.get("classification_authorized") is True,
            "classification_qc_status": str(source.get("classification_qc_status", "not_applicable")),
            "report_sha256": report_hash,
            "source_artifact_sha256": source_artifact_sha256,
            "review_summary": source.get("review_summary"),
        }
        observed_evidence = {key: evidence.get(key) for key in expected_evidence}
        if observed_evidence != expected_evidence:
            raise ValueError(f"bundle evidence does not match source manifest for {evidence_id}")


def visible_report_text(report: str) -> str:
    without_comments = re.sub(r"<!--[\s\S]*?-->", "", report)
    visible: list[str] = []
    fence_character = ""
    fence_length = 0
    for line in without_comments.splitlines():
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence_character:
            if fence and fence.group(1)[0] == fence_character and len(fence.group(1)) >= fence_length:
                fence_character = ""
                fence_length = 0
            visible.append("")
            continue
        if fence:
            fence_character = fence.group(1)[0]
            fence_length = len(fence.group(1))
            visible.append("")
            continue
        if line.startswith("    ") or line.startswith("\t"):
            visible.append("")
            continue
        visible.append(line)
    return "\n".join(visible)


def validate_numeric_rendering(
    text: str,
    allowed_numbers: set[str],
    context: str,
) -> None:
    normalized = normalized_scan_text(text)
    if NUMBER_WORD.search(normalized) or DERIVED_NUMERIC_EXPRESSION.search(normalized):
        raise ValueError(f"{context} spells out or derives a numerical result")
    observed_numbers = set(NUMBER_TOKEN.findall(normalized))
    if not observed_numbers.issubset(allowed_numbers):
        raise ValueError(f"{context} changes or invents a numerical result")


def scan_output(paths: list[Path], forbidden_tokens: list[str]) -> None:
    for path in paths:
        text = normalized_scan_text(read_stable_text(path, path.name))
        if PROHIBITED_INPUT.search(text):
            raise ValueError(f"raw object, URI, or local path leaked into {path.name}")
        lowered = text.lower()
        for token in forbidden_tokens:
            normalized_token = normalized_scan_text(token).lower()
            if normalized_token and normalized_token in lowered:
                raise ValueError(f"forbidden token leaked into {path.name}")


def validate_prompt(
    prompt_path: Path,
    bundle_hash: str,
    subject_alias: str,
    model: dict[str, Any],
) -> None:
    prompt_text = read_stable_text(prompt_path, prompt_path.name)
    if f"Input: `review_bundle.json` with SHA-256 `{bundle_hash}`." not in prompt_text:
        raise ValueError("reviewer prompt is not bound to the current bundle hash")
    if (
        f"Subject alias: `{subject_alias}`." not in prompt_text
        or f"Pinned model: `{model['provider']}/{model['model_id']}`." not in prompt_text
    ):
        raise ValueError("reviewer prompt is not bound to alias and pinned model")


def validate_other_reviewer(
    other_dir: Path,
    current_manifest: dict[str, Any],
    current_outputs: dict[str, str],
    bundle_hash: str,
    reviewer_a_prompt_hash: str,
    reviewer_a_model: dict[str, Any],
    subject_alias: str,
    required_methods: list[str],
    catalog_receipt_hash: str,
) -> None:
    paths = {
        "validation": other_dir / "validation.json",
        "manifest": other_dir / "review_manifest.json",
        "report": other_dir / "report.md",
        "claims": other_dir / "claims.csv",
    }
    if any(path.is_symlink() or not path.is_file() or path.stat().st_size == 0 for path in paths.values()):
        raise ValueError("reviewer B requires a complete validated reviewer A output")

    other_validation = load_object(paths["validation"])
    other_manifest, other_manifest_sha256 = load_object_with_sha256(
        paths["manifest"],
    )
    if (
        not is_exact_int(other_validation.get("schema_version"), 2)
        or other_validation.get("status") != "passed"
        or other_validation.get("reviewer_id") != "A"
    ):
        raise ValueError("other review is not a passed reviewer A validation")
    if (
        other_validation.get("review_bundle_sha256") != bundle_hash
        or other_validation.get("prompt_sha256") != reviewer_a_prompt_hash
        or other_validation.get("model") != reviewer_a_model
        or other_validation.get("subject_alias") != subject_alias
        or other_validation.get("required_method_ids") != required_methods
        or other_validation.get("model_catalog_receipt_sha256") != catalog_receipt_hash
    ):
        raise ValueError("reviewer A validation is not bound to this review bundle")

    other_outputs = {
        "report.md": sha256(paths["report"]),
        "claims.csv": sha256(paths["claims"]),
    }
    if (
        other_validation.get("report_sha256") != other_outputs["report.md"]
        or other_validation.get("claims_sha256") != other_outputs["claims.csv"]
        or other_validation.get("review_manifest_sha256") != other_manifest_sha256
    ):
        raise ValueError("reviewer A artifacts changed after validation")
    if other_manifest.get("reviewer_id") != "A":
        raise ValueError("other review manifest is not reviewer A")
    if (
        other_manifest.get("input_bundle_sha256") != bundle_hash
        or other_manifest.get("prompt_sha256") != reviewer_a_prompt_hash
        or other_manifest.get("model") != reviewer_a_model
        or other_manifest.get("subject_alias") != subject_alias
    ):
        raise ValueError("reviewer A manifest is not bound to this review bundle")

    current_invocation = require_exact_review_invocation(
        current_manifest.get("invocation", {}),
    )
    other_invocation = require_exact_review_invocation(
        other_manifest.get("invocation", {}),
    )
    if current_invocation["invocation_id"] == other_invocation["invocation_id"]:
        raise ValueError("reviewer A and B share an invocation ID")
    if current_outputs["report.md"] == other_outputs["report.md"] or current_outputs["claims.csv"] == other_outputs["claims.csv"]:
        raise ValueError("reviewer B duplicates a reviewer A output")


def validate_bundle(
    bundle: dict[str, Any],
    bundle_manifest: dict[str, Any],
    bundle_hash: str,
    prompt_hash: str,
    reviewer: str,
    forbidden_tokens: list[str],
    catalog_receipt: Path,
) -> tuple[
    str,
    dict[str, Any],
    list[str],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    str,
    str,
]:
    if set(bundle) != BUNDLE_REVIEW_BUNDLE_KEYS:
        raise ValueError("AI review bundle envelope is not exact")
    if set(bundle_manifest) != BUNDLE_MANIFEST_KEYS:
        raise ValueError("AI review bundle manifest envelope is not exact")
    if not is_exact_int(bundle.get("schema_version"), 2) or not is_exact_int(
        bundle_manifest.get("schema_version"),
        2,
    ):
        raise ValueError("unsupported bundle or bundle-manifest schema")
    if bundle_manifest.get("forbidden_token_sha256") != forbidden_token_fingerprints(forbidden_tokens):
        raise ValueError("forbidden-token inventory differs from bundle construction")
    if bundle.get("purpose") != "deidentified_independent_narrative_crosscheck":
        raise ValueError("review bundle purpose is missing or altered")
    if bundle.get("policy") != REQUIRED_POLICY:
        raise ValueError("review bundle policy is missing or altered")

    subject_alias = str(bundle.get("subject_alias", ""))
    if not SUBJECT_ALIAS.fullmatch(subject_alias):
        raise ValueError("review bundle subject alias is missing or malformed")
    if bundle_manifest.get("subject_alias") != subject_alias:
        raise ValueError("subject alias differs from bundle_manifest.json")

    model_contracts = bundle.get("model_execution_contracts")
    if (
        not isinstance(model_contracts, dict)
        or set(model_contracts) != {"A", "B"}
        or bundle_manifest.get("model_execution_contracts") != model_contracts
    ):
        raise ValueError("model execution contracts are missing or altered")
    for role, contract in model_contracts.items():
        if not isinstance(contract, dict) or set(contract) != {
            "provider",
            "model_id",
            "catalog_verified_at",
            "latest_available_attested",
        }:
            raise ValueError(f"pinned model contract is malformed for reviewer {role}")
        if not exact_nonempty_string(contract["provider"]) or not exact_nonempty_string(contract["model_id"]):
            raise ValueError(f"pinned model identity is empty for reviewer {role}")
        if not exact_nonempty_string(contract["catalog_verified_at"]):
            raise ValueError(f"model catalog attestation is malformed for reviewer {role}")
        if contract["latest_available_attested"] is not True:
            raise ValueError(f"latest-model attestation is absent for reviewer {role}")
        verified_at = parse_time(contract["catalog_verified_at"], "catalog_verified_at")
        age_seconds = (datetime.now(verified_at.tzinfo) - verified_at).total_seconds()
        if age_seconds < 0 or age_seconds > 31 * 24 * 60 * 60:
            raise ValueError(f"model catalog attestation is stale for reviewer {role}")

    if (
        model_contracts["A"]["provider"],
        model_contracts["A"]["model_id"],
    ) == (
        model_contracts["B"]["provider"],
        model_contracts["B"]["model_id"],
    ):
        raise ValueError("reviewers are not assigned distinct pinned models")

    catalog_receipt_hash = validate_catalog_receipt(catalog_receipt, model_contracts)
    if (
        bundle.get("model_catalog_receipt_sha256") != catalog_receipt_hash
        or bundle_manifest.get("model_catalog_receipt_sha256") != catalog_receipt_hash
    ):
        raise ValueError("model catalog receipt hash is missing or altered")
    if bundle_manifest.get("review_bundle_sha256") != bundle_hash:
        raise ValueError("bundle hash differs from bundle_manifest.json")

    prompt_hashes = bundle_manifest.get("prompt_sha256")
    if (
        not isinstance(prompt_hashes, dict)
        or set(prompt_hashes) != {"A", "B"}
    ):
        raise ValueError("bundle-manifest prompt inventory is malformed")
    for role, digest in prompt_hashes.items():
        try:
            checked_sha256(digest, "reviewer " + role + " prompt")
        except ValueError as error:
            raise ValueError("bundle-manifest prompt inventory is malformed") from error
    if prompt_hashes.get(reviewer) != prompt_hash:
        raise ValueError("prompt hash differs from bundle_manifest.json")

    required_methods = bundle.get("required_method_ids")
    if not isinstance(required_methods, list) or bundle_manifest.get("required_method_ids") != required_methods:
        raise ValueError("required method inventory is missing or altered")
    inventory_id = require_inventory_binding(
        bundle.get("method_inventory"),
        bundle.get("method_inventory_sha256"),
        "review bundle method inventory binding",
        None,
    )
    require_pinned_methods(
        required_methods,
        "review bundle method inventory",
        inventory_id,
    )
    require_inventory_binding(
        bundle_manifest.get("method_inventory"),
        bundle_manifest.get("method_inventory_sha256"),
        "bundle manifest method inventory binding",
        inventory_id,
    )
    if bundle.get("method_inventory_sha256") != bundle_manifest.get("method_inventory_sha256"):
        raise ValueError("bundle method inventory hashes disagree")

    evidence_rows = bundle.get("evidence_sources")
    if not isinstance(evidence_rows, list) or not evidence_rows:
        raise ValueError("review bundle contains no evidence sources")
    evidence: dict[str, dict[str, Any]] = {}
    for row in evidence_rows:
        if not isinstance(row, dict):
            raise ValueError("malformed evidence source")
        evidence_id = str(row.get("evidence_id", ""))
        source_hashes = row.get("source_artifact_sha256")
        review_summary = row.get("review_summary")
        if not EVIDENCE_ID.fullmatch(evidence_id) or evidence_id in evidence:
            raise ValueError("malformed or duplicate evidence source")
        if not METHOD_ID.fullmatch(str(row.get("method_id", ""))):
            raise ValueError("invalid method ID in evidence source")
        if row.get("evidence_status") not in EVIDENCE_STATES or row.get("authorized_hrd_state") not in HRD_STATES:
            raise ValueError("invalid evidence or authorization state")
        if (
            not isinstance(row.get("classification_authorized"), bool)
            or row.get("classification_qc_status") not in CLASSIFICATION_QC_STATES
        ):
            raise ValueError("malformed classification authorization metadata")
        if not isinstance(row.get("report_sha256"), str) or not HEX64.fullmatch(
            row["report_sha256"]
        ):
            raise ValueError("malformed source-report hash")
        if not isinstance(source_hashes, list) or not source_hashes or not all(
            isinstance(value, str) and HEX64.fullmatch(value) for value in source_hashes
        ):
            raise ValueError("malformed source-artifact hashes")
        if not isinstance(review_summary, dict) or not review_summary:
            raise ValueError("evidence source lacks a review summary")
        evidence[evidence_id] = row
    if [str(row.get("method_id", "")) for row in evidence_rows] != required_methods:
        raise ValueError("evidence sources do not match the ordered required method inventory")

    quantitative_facts = bundle.get("quantitative_facts")
    if not isinstance(quantitative_facts, list):
        raise ValueError("quantitative fact inventory is missing")
    if quantitative_facts != derived_quantitative_facts(evidence_rows):
        raise ValueError("quantitative fact inventory is not derived from evidence")
    facts: dict[str, dict[str, Any]] = {}
    for fact in quantitative_facts:
        if not isinstance(fact, dict):
            raise ValueError("malformed quantitative fact")
        fact_id = str(fact.get("quantitative_fact_id", ""))
        if not QUANTITATIVE_FACT_ID.fullmatch(fact_id) or fact_id in facts:
            raise ValueError("malformed or duplicate quantitative fact ID")
        if fact.get("evidence_id") not in evidence:
            raise ValueError(f"quantitative fact {fact_id} has unknown evidence ID")
        exact_text = str(fact.get("exact_text", ""))
        if fact.get("value_kind") not in {"number", "string_token"}:
            raise ValueError(f"quantitative fact {fact_id} has invalid value kind")
        if NUMBER_TOKEN.fullmatch(exact_text) is None:
            raise ValueError(f"quantitative fact {fact_id} has malformed exact text")
        if not str(fact.get("summary_path", "")).startswith("review_summary"):
            raise ValueError(f"quantitative fact {fact_id} has malformed summary path")
        facts[fact_id] = fact

    authorized = str(bundle.get("authorized_hrd_state", ""))
    if authorized not in HRD_STATES:
        raise ValueError("invalid bundle authorization state")
    derived = derived_authorized_state(evidence_rows)
    if authorized != derived or bundle_manifest.get("authorized_hrd_state") != derived:
        raise ValueError("bundle authorization is not derived from its evidence sources")

    input_hashes = bundle_manifest.get("input_manifest_sha256")
    if (
        not isinstance(input_hashes, dict)
        or set(input_hashes) != set(evidence)
    ):
        raise ValueError("bundle-manifest source hashes do not match evidence sources")
    for evidence_id, digest in input_hashes.items():
        try:
            checked_sha256(digest, "source manifest " + evidence_id)
        except ValueError as error:
            raise ValueError(
                "bundle-manifest source hashes do not match evidence sources"
            ) from error

    return (
        subject_alias,
        model_contracts,
        required_methods,
        evidence_rows,
        facts,
        catalog_receipt_hash,
        inventory_id,
    )


def validate_report_and_claims(
    report_path: Path,
    claims_path: Path,
    reviewer: str,
    subject_alias: str,
    authorized: str,
    evidence: dict[str, dict[str, Any]],
    quantitative_facts: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, str]], set[str]]:
    claims_text = read_stable_text(claims_path, "claims.csv")
    handle = io.StringIO(claims_text, newline="")
    reader = csv.DictReader(handle)
    if reader.fieldnames != CLAIMS_FIELDS:
        raise ValueError("claims.csv header does not match the required schema")
    claims = list(reader)
    if not claims:
        raise ValueError("claims.csv contains no claims")

    report = read_stable_text(report_path, "report.md")
    if re.search(r"</?[A-Za-z][^>]*>", report):
        raise ValueError("raw HTML is prohibited in report.md")

    visible_report = visible_report_text(report)
    report_lines = visible_report.splitlines()
    heading_positions: list[int] = []
    for heading in REQUIRED_REPORT_HEADINGS:
        positions = [index for index, line in enumerate(report_lines) if line.strip() == heading]
        if len(positions) != 1:
            raise ValueError(f"report heading is missing or duplicated: {heading}")
        heading_positions.append(positions[0])
    if heading_positions != sorted(heading_positions):
        raise ValueError("report headings are out of order")

    first_visible_line = next(
        (line.strip() for line in report_lines if line.strip()),
        "",
    )
    if first_visible_line != REQUIRED_REPORT_HEADINGS[0]:
        raise ValueError("report must begin with the required title")

    expected_header = f"Authorized HRD state: `{authorized}`"
    expected_alias = f"Subject alias: `{subject_alias}`"
    substantive = [(index, line.strip()) for index, line in enumerate(report_lines) if line.strip() and not line.lstrip().startswith("#")]
    if len(substantive) < 2 or substantive[0][1] != expected_header:
        raise ValueError("authorization line must precede substantive review text")
    if substantive[1][1] != expected_alias:
        raise ValueError("exact subject alias line must follow authorization")
    if substantive[1][0] >= heading_positions[1]:
        raise ValueError("authorization and alias must precede report sections")

    for section_index, start in enumerate(heading_positions[1:], 1):
        end = heading_positions[section_index + 1] if section_index + 1 < len(heading_positions) else len(report_lines)
        section_text = re.sub(
            r"`+[^`\n]*`+",
            "",
            "\n".join(report_lines[start + 1 : end]),
        )
        if not CITATION.search(section_text):
            raise ValueError("report section has no evidence-cited content: " + REQUIRED_REPORT_HEADINGS[section_index])

    report_citations: dict[str, tuple[str, ...]] = {}
    report_blocks: list[tuple[str, set[str]]] = []
    for block in re.split(r"\n\s*\n", visible_report):
        stripped = block.strip()
        if not stripped or all(line.lstrip().startswith("#") for line in stripped.splitlines()):
            continue
        if stripped in {expected_header, expected_alias}:
            continue

        citation_text = re.sub(r"`+[^`\n]*`+", "", stripped)
        block_markers = CITATION.findall(citation_text)
        if not block_markers:
            raise ValueError("report contains an uncited substantive block")

        block_claim_ids: set[str] = set()
        for claim_id, evidence_text in block_markers:
            cited_evidence = tuple(evidence_text.split(";"))
            previous = report_citations.setdefault(claim_id, cited_evidence)
            if previous != cited_evidence:
                raise ValueError(f"inconsistent evidence citation for {claim_id}")
            block_claim_ids.add(claim_id)
        report_blocks.append((CITATION.sub("", citation_text), block_claim_ids))

    claim_ids: set[str] = set()
    covered_evidence: set[str] = set()
    claim_fact_ids: dict[str, set[str]] = {}
    claim_numeric_text: dict[str, str] = {}
    for row_number, raw_row in enumerate(claims, 2):
        row = require_exact_claim_row(raw_row, row_number)
        claim_id = row["claim_id"]
        if not CLAIM_ID.fullmatch(claim_id) or claim_id in claim_ids:
            raise ValueError(f"invalid or duplicate claim_id at row {row_number}")
        claim_ids.add(claim_id)

        evidence_ids = split_semicolon(
            row["evidence_ids"],
            "evidence_ids",
            row_number,
        )
        source_methods = split_semicolon(
            row["source_methods"],
            "source_methods",
            row_number,
        )
        evidence_states = split_semicolon(
            row["evidence_states"],
            "evidence_states",
            row_number,
        )
        if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError(f"empty or duplicate evidence_ids at row {row_number}")
        if any(evidence_id not in evidence for evidence_id in evidence_ids):
            raise ValueError(f"unknown evidence_id at row {row_number}")

        expected_methods = tuple(str(evidence[item]["method_id"]) for item in evidence_ids)
        expected_states = tuple(str(evidence[item]["evidence_status"]) for item in evidence_ids)
        if source_methods != expected_methods or evidence_states != expected_states:
            raise ValueError(f"method or evidence state does not match evidence_ids at row {row_number}")
        if report_citations.get(claim_id) != evidence_ids:
            raise ValueError(f"report evidence citation does not match {claim_id}")
        covered_evidence.update(evidence_ids)

        support = row["support_level"]
        disposition = row["disposition"]
        proposed = row["proposed_hrd_state"]
        disagreement = row["disagreement_status"]
        if support not in SUPPORT_LEVELS or disposition not in DISPOSITIONS:
            raise ValueError(f"invalid support level or disposition at row {row_number}")
        if disposition == "supported" and support != "direct":
            raise ValueError(f"supported claim lacks direct support at row {row_number}")
        if disposition == "unsupported" and support not in {"absent", "conflicting"}:
            raise ValueError(f"unsupported claim has inconsistent support level at row {row_number}")
        if proposed not in HRD_STATES:
            raise ValueError(f"invalid proposed_hrd_state at row {row_number}")
        if proposed != "no_call" and proposed != authorized:
            raise ValueError(f"HRD classification promotion at row {row_number}")
        if authorized == "no_call" and proposed != "no_call":
            raise ValueError(f"no_call bundle cannot be promoted at row {row_number}")
        if not row["claim"] or not row["caveat"]:
            raise ValueError(f"claim and caveat are required at row {row_number}")

        raw_fact_ids = row["quantitative_fact_ids"]
        fact_id_list = [] if raw_fact_ids == "none" else raw_fact_ids.split(";")
        fact_ids = set(fact_id_list)
        if any(not QUANTITATIVE_FACT_ID.fullmatch(item) for item in fact_ids) or len(fact_ids) != len(fact_id_list):
            raise ValueError(f"malformed quantitative_fact_ids at row {row_number}")
        for fact_id in fact_ids:
            fact = quantitative_facts.get(fact_id)
            if fact is None or fact["evidence_id"] not in evidence_ids:
                raise ValueError(f"quantitative fact is not bound to cited evidence at row {row_number}")
        claim_fact_ids[claim_id] = fact_ids

        raw_disagreement_ids = row["disagreement_evidence_ids"]
        disagreement_ids = () if raw_disagreement_ids == "none" else tuple(raw_disagreement_ids.split(";"))
        if disagreement not in DISAGREEMENT_STATUSES:
            raise ValueError(f"invalid disagreement status at row {row_number}")
        if any(item not in evidence_ids for item in disagreement_ids) or len(set(disagreement_ids)) != len(disagreement_ids):
            raise ValueError(f"disagreement evidence is not bound to claim at row {row_number}")
        resolution = row["resolution_needed"]
        if disagreement == "none":
            if disagreement_ids or resolution != "not_applicable" or support == "conflicting":
                raise ValueError(f"disagreement fields are inconsistent at row {row_number}")
        else:
            if not disagreement_ids or not resolution or resolution == "not_applicable":
                raise ValueError(f"unresolved disagreement lacks evidence or resolution at row {row_number}")
            if disagreement == "method_conflict" and (support != "conflicting" or len(disagreement_ids) < 2):
                raise ValueError(f"method conflict lacks conflicting support at row {row_number}")

        narrative = "\n".join((row["claim"], row["caveat"], resolution))
        allowed_numbers = {str(quantitative_facts[fact_id]["exact_text"]) for fact_id in fact_ids}
        try:
            validate_numeric_rendering(narrative, allowed_numbers, "claim")
        except ValueError as error:
            raise ValueError(f"{error} at row {row_number}") from error
        claim_numeric_text[claim_id] = narrative

    if set(report_citations) != claim_ids:
        raise ValueError("report and claims.csv citation inventories differ")
    if covered_evidence != set(evidence):
        raise ValueError("claims do not preserve every evidence source and state")

    report_text_by_claim: dict[str, list[str]] = {claim_id: [] for claim_id in claim_ids}
    for block_text, block_claim_ids in report_blocks:
        allowed_fact_ids = set().union(*(claim_fact_ids[item] for item in block_claim_ids))
        allowed_numbers = {str(quantitative_facts[fact_id]["exact_text"]) for fact_id in allowed_fact_ids}
        validate_numeric_rendering(block_text, allowed_numbers, "report")
        for claim_id in block_claim_ids:
            report_text_by_claim[claim_id].append(block_text)

    for claim_id, fact_ids in claim_fact_ids.items():
        combined = claim_numeric_text[claim_id] + "\n" + "\n".join(report_text_by_claim[claim_id])
        observed = set(NUMBER_TOKEN.findall(normalized_scan_text(combined)))
        required = {str(quantitative_facts[fact_id]["exact_text"]) for fact_id in fact_ids}
        if not required.issubset(observed):
            raise ValueError(f"{claim_id} cites an unused quantitative fact")

    review_narrative = normalized_scan_text(visible_report + "\n" + claims_text)
    other_role = "B" if reviewer == "A" else "A"
    other_context = re.compile(
        rf"\breviewer\s*{other_role}\b|\bother reviewer(?:'s)?\b|"
        r"\bpeer reviewer output\b|\bprior AI review\b",
        re.IGNORECASE,
    )
    if other_context.search(review_narrative):
        raise ValueError("review refers to prohibited other-reviewer context")
    if authorized == "no_call" and has_unauthorized_hrd_classification(review_narrative):
        raise ValueError("review text contains unauthorized positive/negative HRD language")

    return claims, covered_evidence


def validate_review_manifest(
    review_manifest: dict[str, Any],
    reviewer: str,
    subject_alias: str,
    model_contract: dict[str, Any],
    prompt_hash: str,
    bundle_hash: str,
    report_path: Path,
    claims_path: Path,
    inventory_id: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    if set(review_manifest) != REVIEW_MANIFEST_KEYS:
        raise ValueError("review manifest envelope is not exact")
    if (
        not is_exact_int(review_manifest.get("schema_version"), 2)
        or review_manifest.get("reviewer_id") != reviewer
    ):
        raise ValueError("review manifest schema or reviewer ID mismatch")

    invocation = require_exact_review_invocation(
        review_manifest.get("invocation", {}),
    )
    if review_manifest.get("model") != model_contract:
        raise ValueError("review did not use its pinned latest-model contract")
    if review_manifest.get("subject_alias") != subject_alias:
        raise ValueError("review manifest subject alias mismatch")
    started = parse_time(invocation["started_at"], "started_at")
    completed = parse_time(invocation["completed_at"], "completed_at")
    if completed < started:
        raise ValueError("invocation completion precedes start")

    if review_manifest.get("prompt_sha256") != prompt_hash:
        raise ValueError("review prompt hash mismatch")
    if review_manifest.get("input_bundle_sha256") != bundle_hash:
        raise ValueError("review input-bundle hash mismatch")
    if review_manifest.get("method_inventory_sha256") != inventory_sha256(inventory_id):
        raise ValueError("review method inventory hash mismatch")

    expected_inputs = {
        "review_bundle.json": bundle_hash,
        f"reviewer-{reviewer.lower()}.prompt.md": prompt_hash,
    }
    if review_manifest.get("input_artifact_sha256") != expected_inputs:
        raise ValueError("review input-artifact inventory is not exact")
    if review_manifest.get("independence_attestation") != REQUIRED_ATTESTATION:
        raise ValueError("review independence attestation is missing or altered")

    expected_outputs = {
        "report.md": sha256(report_path),
        "claims.csv": sha256(claims_path),
    }
    if review_manifest.get("output_sha256") != expected_outputs:
        raise ValueError("review output hashes mismatch")
    return expected_outputs, invocation


def require_exact_review_output_dir(review_dir: Path) -> None:
    require_exact_review_dir(
        review_dir,
        REVIEW_OUTPUT_FILES,
        (
            "review directory must contain exactly report.md, claims.csv, "
            "and review_manifest.json before validation"
        ),
    )


def require_exact_validated_review_dir(review_dir: Path) -> None:
    require_exact_review_dir(
        review_dir,
        VALIDATED_REVIEW_OUTPUT_FILES,
        (
            "validated review directory must contain exactly report.md, "
            "claims.csv, review_manifest.json, and validation.json"
        ),
    )


def require_exact_review_dir(
    review_dir: Path,
    expected: set[str],
    message: str,
) -> None:
    if review_dir.is_symlink() or not review_dir.is_dir():
        raise ValueError("review directory is missing or a symlink")

    observed = {path.name for path in review_dir.iterdir()}
    if observed != expected:
        missing = sorted(expected - observed)
        unexpected = sorted(observed - expected)
        details = []
        if missing:
            details.append("missing " + ",".join(missing))
        if unexpected:
            details.append("unexpected " + ",".join(unexpected))
        raise ValueError(message + ": " + "; ".join(details))

    invalid = sorted(path.name for path in review_dir.iterdir() if path.is_symlink() or not path.is_file())
    if invalid:
        raise ValueError("review directory contains invalid output paths: " + ",".join(invalid))


def write_validation_create_only(path: Path, validation: dict[str, Any]) -> str:
    require_safe_validation_parent(path)
    payload = (json.dumps(validation, indent=2, sort_keys=True) + "\n").encode("utf-8")
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    file_descriptor = -1
    try:
        file_descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as error:
        raise ValueError("validation.json already exists") from error

    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            file_descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(path.parent)
        require_installed_validation(path, expected_sha256)
        return expected_sha256
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)


def require_installed_validation(path: Path, expected_sha256: str) -> None:
    require_no_symlinked_ancestors(path, "validation.json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("validation.json changed during write")
    if (path.stat().st_mode & 0o777) != 0o600:
        raise ValueError("validation.json changed during write")
    if sha256(path) != expected_sha256:
        raise ValueError("validation.json changed during write")


def require_installed_review_artifacts(
    report_path: Path,
    claims_path: Path,
    review_manifest_path: Path,
    validation: dict[str, Any],
) -> None:
    if (
        sha256(report_path) != validation.get("report_sha256")
        or sha256(claims_path) != validation.get("claims_sha256")
        or sha256(review_manifest_path) != validation.get("review_manifest_sha256")
    ):
        raise ValueError("validated review artifacts changed during write")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require_safe_validation_parent(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("validation.json already exists")
    for parent in path.parents:
        if parent.is_symlink() and not is_platform_root_alias(parent):
            raise ValueError(f"review directory is missing or a symlink: {parent}")
        if parent.exists() and not parent.is_dir():
            raise NotADirectoryError(parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--source-manifest", action="append", required=True, type=Path)
    parser.add_argument("--reviewer", required=True, choices=("A", "B"))
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--other-review-dir", type=Path)
    parser.add_argument("--model-catalog-receipt", required=True, type=Path)
    parser.add_argument("--forbidden-token", action="append", default=[])
    parser.add_argument("--forbidden-tokens-file", action="append", default=[], type=Path)
    args = parser.parse_args(argv)

    try:
        review_dir = resolve_real_dir(args.review_dir, "review directory")
        validation_path = review_dir / "validation.json"
        if validation_path.exists() or validation_path.is_symlink():
            raise ValueError("validation.json already exists")
        if args.reviewer == "B" and args.other_review_dir is None:
            raise ValueError("reviewer B requires --other-review-dir for validated reviewer A")
        if args.reviewer == "A" and args.other_review_dir is not None:
            raise ValueError("reviewer A must not consume another reviewer output")

        forbidden = merge_forbidden_tokens(
            args.forbidden_token,
            files=args.forbidden_tokens_file,
        )
        if not forbidden:
            raise ValueError("at least one forbidden token is required")

        bundle_dir = resolve_real_dir(args.bundle_dir, "bundle directory")
        require_bundle_manifest(bundle_dir)
        bundle_path = bundle_dir / "review_bundle.json"
        bundle_manifest_path = bundle_dir / "bundle_manifest.json"
        prompt_paths = {
            role: bundle_dir / f"reviewer-{role.lower()}.prompt.md"
            for role in ("A", "B")
        }
        prompt_path = prompt_paths[args.reviewer]
        report_path = review_dir / "report.md"
        claims_path = review_dir / "claims.csv"
        review_manifest_path = review_dir / "review_manifest.json"
        require_exact_review_output_dir(review_dir)
        required_paths = (
            bundle_path,
            bundle_manifest_path,
            prompt_path,
            report_path,
            claims_path,
            review_manifest_path,
        )
        missing = [path.name for path in required_paths if path.is_symlink() or not path.is_file() or path.stat().st_size == 0]
        if missing:
            raise ValueError("missing review artifacts: " + ",".join(missing))

        bundle = load_object(bundle_path)
        bundle_manifest, bundle_manifest_sha256 = load_object_with_sha256(
            bundle_manifest_path,
        )
        review_manifest, review_manifest_sha256 = load_object_with_sha256(
            review_manifest_path,
        )
        bundle_hash = sha256(bundle_path)
        prompt_hash = sha256(prompt_path)

        (
            subject_alias,
            model_contracts,
            required_methods,
            evidence_rows,
            quantitative_facts,
            catalog_receipt_hash,
            inventory_id,
        ) = validate_bundle(
            bundle,
            bundle_manifest,
            bundle_hash,
            prompt_hash,
            args.reviewer,
            forbidden,
            resolve_real_file(args.model_catalog_receipt, "model catalog receipt"),
        )
        validate_source_manifests(
            args.source_manifest,
            evidence_rows,
            bundle_manifest["input_manifest_sha256"],
        )
        validate_prompt(
            prompt_path,
            bundle_hash,
            subject_alias,
            model_contracts[args.reviewer],
        )
        evidence = {str(row["evidence_id"]): row for row in evidence_rows}
        authorized = str(bundle["authorized_hrd_state"])

        claims, covered_evidence = validate_report_and_claims(
            report_path,
            claims_path,
            args.reviewer,
            subject_alias,
            authorized,
            evidence,
            quantitative_facts,
        )
        expected_outputs, _invocation = validate_review_manifest(
            review_manifest,
            args.reviewer,
            subject_alias,
            model_contracts[args.reviewer],
            prompt_hash,
            bundle_hash,
            report_path,
            claims_path,
            inventory_id,
        )

        scan_output(
            [
                bundle_path,
                bundle_manifest_path,
                prompt_paths["A"],
                prompt_paths["B"],
                report_path,
                claims_path,
                review_manifest_path,
            ],
            forbidden,
        )

        if args.reviewer == "B":
            validate_other_reviewer(
                resolve_real_dir(args.other_review_dir, "other review directory"),
                review_manifest,
                expected_outputs,
                bundle_hash,
                checked_sha256(
                    bundle_manifest["prompt_sha256"]["A"],
                    "reviewer A prompt",
                ),
                model_contracts["A"],
                subject_alias,
                required_methods,
                catalog_receipt_hash,
            )
    except (ValueError, json.JSONDecodeError) as error:
        raise SystemExit(f"Fail-closed: {error}") from error

    validation = {
        "schema_version": 2,
        "status": "passed",
        "reviewer_id": args.reviewer,
        "subject_alias": subject_alias,
        "model": model_contracts[args.reviewer],
        "authorized_hrd_state": authorized,
        "required_method_ids": required_methods,
        "method_inventory": inventory_payload(inventory_id),
        "method_inventory_sha256": inventory_sha256(inventory_id),
        "model_catalog_receipt_sha256": catalog_receipt_hash,
        "claim_count": len(claims),
        "covered_evidence_ids": sorted(covered_evidence),
        "disagreement_claim_count": sum(
            row["disagreement_status"] != "none" for row in claims
        ),
        "bundle_manifest_sha256": bundle_manifest_sha256,
        "review_bundle_sha256": bundle_hash,
        "prompt_sha256": prompt_hash,
        "report_sha256": expected_outputs["report.md"],
        "claims_sha256": expected_outputs["claims.csv"],
        "review_manifest_sha256": review_manifest_sha256,
        "forbidden_token_count": len(forbidden),
    }

    try:
        validation_sha256 = write_validation_create_only(validation_path, validation)
        try:
            require_exact_validated_review_dir(review_dir)
            require_installed_review_artifacts(
                report_path,
                claims_path,
                review_manifest_path,
                validation,
            )
            require_installed_validation(validation_path, validation_sha256)
        except ValueError:
            validation_path.unlink(missing_ok=True)
            raise
    except ValueError as error:
        raise SystemExit(f"Fail-closed: {error}") from error
    print(f"Validated independent reviewer {args.reviewer}: {len(claims)} claims; authorized state {authorized}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
